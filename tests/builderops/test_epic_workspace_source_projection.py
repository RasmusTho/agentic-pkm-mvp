"""Stopped-source projection uses real Git through the synthetic container transport."""

import json
import os
import re
import subprocess

import pytest

from app.builderops import epic_workspace as ew
from tests.builderops.test_epic_workspace_isolation import FakeEngine, _cli, _seed_repo
from tests.builderops.test_epic_workspace_lifecycle import _ckpt, _git, _new_worker


def stopped_source(tmp_path, capsys, *, filter_marker=None, replace_staged_with_directory=False,
                   ignored_escape=False):
    repo = _seed_repo(tmp_path)
    root = tmp_path / "ws"
    engine = FakeEngine()
    assert _cli(root, 6615, engine, "init", "--repo-url", repo) == 0
    checkout = _new_worker(root, engine, repo, "w-a", 6617)
    (checkout / "remove.py").write_text("remove me\n")
    (checkout / "executable").write_text("old\n")
    _git(checkout, "add", "remove.py", "executable")
    _git(checkout, "commit", "-m", "add tracked files")
    assert _cli(root, 6615, engine, "worker-start", "--worker", "w-a", "--", "sleep", "60") == 0
    (checkout / "README.md").write_bytes(b"physical\r\nbytes\r\n")
    (checkout / "remove.py").unlink()
    (checkout / "executable").write_text("new executable\n")
    (checkout / "executable").chmod(0o755)
    (checkout / "new.py").write_text("new source\n")
    (checkout / "line\nname.py").write_text("unusual name\n")
    (checkout / "safe-link").symlink_to("README.md")
    (checkout / ".gitattributes").write_text("new.py export-ignore\n*.md text eol=lf\n")
    (checkout / ".gitignore").write_text("*.cache\n")
    (checkout / "secret.cache").write_text("unique ignored work\n")
    if ignored_escape:
        (checkout / "escape.cache").symlink_to("../../outside")
    (checkout / "staged.cache").write_text("explicitly tracked\n")
    _git(checkout, "add", "-f", "staged.cache")
    if replace_staged_with_directory:
        (checkout / "staged.cache").unlink()
        (checkout / "staged.cache").mkdir()
        (checkout / "staged.cache" / "private").write_text("retained ignored directory\n")
    if filter_marker is not None:
        cleaner = tmp_path / "filter.sh"
        cleaner.write_text(f"#!/bin/sh\ntouch {filter_marker}\ncat\n")
        cleaner.chmod(0o755)
        _git(checkout, "config", "filter.evil.clean", str(cleaner))
        _git(checkout, "config", "filter.evil.required", "true")
        (checkout / ".gitattributes").write_text("* filter=evil\nnew.py export-ignore\n")
    capsys.readouterr()
    assert _cli(root, 6615, engine, "worker-stop", "--worker", "w-a", "--reason", "preserve") == 0
    stopped = json.loads(capsys.readouterr().out)["work_at_stop"]
    layout = ew.Layout(root.resolve(), 6615)
    args = {"stop_id": stopped["stop_id"], "checkpoint_ref": stopped["checkpoint"]["ref"],
            "branch": stopped["branch"], "head": stopped["head"], "runner": engine}
    return layout, checkout, engine, stopped, args


def test_projection_builds_real_versioned_tree_and_preserves_full_checkpoint(tmp_path, capsys):
    layout, checkout, engine, stopped, args = stopped_source(tmp_path, capsys)
    index = (checkout / ".git/index").read_bytes()
    config = (checkout / ".git/config").read_bytes()
    engine.host_git.clear()
    first = ew.project_stopped_versioned_source(layout, "w-a", **args)
    second = ew.project_stopped_versioned_source(layout, "w-a", **args)
    assert first == second
    entries = {item["path"]: item for item in first["entries"]}
    assert {"README.md", "new.py", "line\nname.py", "safe-link", "executable", "staged.cache"} <= entries.keys()
    assert "remove.py" not in entries and "secret.cache" not in entries
    assert entries["executable"]["mode"] == "100755"
    assert entries["safe-link"]["mode"] == "120000"
    assert first["checkpoint_tree"] == stopped["checkpoint"]["tree"]
    assert first["versioned_tree"] != first["checkpoint_tree"]
    assert _ckpt(layout.root, "w-a", "show", f"{args['checkpoint_ref']}:secret.cache") == "unique ignored work"
    assert (checkout / "secret.cache").read_text() == "unique ignored work\n"
    assert (checkout / ".git/index").read_bytes() == index
    assert (checkout / ".git/config").read_bytes() == config
    assert not engine.host_git
    assert all("--network" in call and "--cap-drop" in call for call in engine.inspections)


def test_projection_never_executes_worker_filter_or_export_ignore(tmp_path, capsys):
    marker = tmp_path / "filter-ran"
    layout, checkout, _, _, args = stopped_source(tmp_path, capsys, filter_marker=marker)
    projection = ew.project_stopped_versioned_source(layout, "w-a", **args)
    assert "new.py" in {entry["path"] for entry in projection["entries"]}
    assert not marker.exists()
    assert (checkout / "README.md").read_bytes() == b"physical\r\nbytes\r\n"


def test_read_projected_blobs_uses_retained_checkpoint_and_excludes_ignored(tmp_path, capsys):
    layout, checkout, engine, _, args = stopped_source(tmp_path, capsys)
    projection = ew.project_stopped_versioned_source(layout, "w-a", **args)
    before_index = (checkout / ".git/index").read_bytes()
    before_config = (checkout / ".git/config").read_bytes()
    result = ew.read_projected_source_blobs(layout, "w-a", projection, ["README.md", "safe-link"], runner=engine)
    assert result == {"README.md": b"physical\r\nbytes\r\n", "safe-link": b"README.md"}
    with pytest.raises(ew.TakeoverRefused, match="outside the versioned"):
        ew.read_projected_source_blobs(layout, "w-a", projection, ["secret.cache"], runner=engine)
    assert (checkout / ".git/index").read_bytes() == before_index
    assert (checkout / ".git/config").read_bytes() == before_config
    assert (checkout / "secret.cache").read_text() == "unique ignored work\n"


def test_read_projected_blobs_refuses_stale_projection(tmp_path, capsys):
    layout, checkout, engine, _, args = stopped_source(tmp_path, capsys)
    projection = ew.project_stopped_versioned_source(layout, "w-a", **args)
    (checkout / "README.md").write_text("later source\n")
    with pytest.raises(ew.TakeoverRefused):
        ew.read_projected_source_blobs(layout, "w-a", projection, ["README.md"], runner=engine)
    assert (checkout / "README.md").read_text() == "later source\n"


def test_read_projected_blobs_refuses_corrupt_transport(tmp_path, capsys):
    layout, checkout, engine, _, args = stopped_source(tmp_path, capsys)
    projection = ew.project_stopped_versioned_source(layout, "w-a", **args)
    original = engine.__class__.__call__

    class CorruptBlob(FakeEngine):
        def __call__(self, argv, **kwargs):
            result = original(self, argv, **kwargs)
            if "cat-file" in argv and "blob" in argv and result.returncode == 0:
                return subprocess.CompletedProcess(argv, 0, b"corrupt transport", b"")
            return result

    engine.__class__ = CorruptBlob
    with pytest.raises(ew.TakeoverRefused, match="blob is unavailable or has changed"):
        ew.read_projected_source_blobs(layout, "w-a", projection, ["README.md"], runner=engine)
    assert (checkout / "README.md").read_bytes() == b"physical\r\nbytes\r\n"


def test_read_projected_blobs_refuses_source_change_during_read(tmp_path, capsys):
    layout, checkout, engine, _, args = stopped_source(tmp_path, capsys)
    projection = ew.project_stopped_versioned_source(layout, "w-a", **args)
    original = engine.__class__.__call__

    class LateWrite(FakeEngine):
        changed = False

        def __call__(self, argv, **kwargs):
            result = original(self, argv, **kwargs)
            if not self.changed and "cat-file" in argv and "blob" in argv and result.returncode == 0:
                self.changed = True
                (checkout / "secret.cache").write_text("later ignored work\n")
            return result

    engine.__class__ = LateWrite
    with pytest.raises(ew.TakeoverRefused):
        ew.read_projected_source_blobs(layout, "w-a", projection, ["README.md"], runner=engine)
    assert (checkout / "secret.cache").read_text() == "later ignored work\n"


def test_indexed_file_replaced_by_ignored_directory_does_not_publish_its_contents(tmp_path, capsys):
    layout, checkout, _, stopped, args = stopped_source(tmp_path, capsys, replace_staged_with_directory=True)
    projection = ew.project_stopped_versioned_source(layout, "w-a", **args)
    assert all(not entry["path"].startswith("staged.cache/") for entry in projection["entries"])
    assert _ckpt(layout.root, "w-a", "show", f"{stopped['checkpoint']['ref']}:staged.cache/private") == (
        "retained ignored directory"
    )
    assert (checkout / "staged.cache" / "private").read_text() == "retained ignored directory\n"


@pytest.mark.parametrize("drift", ["stop", "branch", "checkpoint", "bytes", "mode", "index", "checkout"])
def test_projection_refuses_drift_and_retains_original_work(tmp_path, capsys, drift):
    layout, checkout, engine, stopped, args = stopped_source(tmp_path, capsys)
    if drift == "stop":
        args["stop_id"] = "f" * 32
    elif drift == "branch":
        _git(checkout, "checkout", "-b", "different")
    elif drift == "checkpoint":
        args["checkpoint_ref"] = "refs/checkpoints/ckpt-9999"
    elif drift == "bytes":
        (checkout / "README.md").write_text("later work\n")
    elif drift == "mode":
        (checkout / "executable").chmod(0o644)
    elif drift == "index":
        _git(checkout, "add", "README.md")
    else:
        ew._record_worker(layout, 6617, checkout=str(checkout.parent / "other"))
    with pytest.raises(ew.EpicWorkspaceError):
        ew.project_stopped_versioned_source(layout, "w-a", **args)
    assert (checkout / "secret.cache").read_text() == "unique ignored work\n"
    assert _ckpt(layout.root, "w-a", "show", f"{stopped['checkpoint']['ref']}:secret.cache") == "unique ignored work"


def test_projection_refuses_escaping_symlink_at_checkpoint(tmp_path, capsys):
    repo = _seed_repo(tmp_path)
    root = tmp_path / "ws"
    engine = FakeEngine()
    assert _cli(root, 6615, engine, "init", "--repo-url", repo) == 0
    checkout = _new_worker(root, engine, repo, "w-a", 6617)
    assert _cli(root, 6615, engine, "worker-start", "--worker", "w-a", "--", "sleep", "60") == 0
    (checkout / "escape").symlink_to("../../outside")
    capsys.readouterr()
    assert _cli(root, 6615, engine, "worker-stop", "--worker", "w-a", "--reason", "preserve") == 0
    stopped = json.loads(capsys.readouterr().out)["work_at_stop"]
    with pytest.raises(ew.TakeoverRefused, match="symlink"):
        ew.project_stopped_versioned_source(ew.Layout(root.resolve(), 6615), "w-a", stop_id=stopped["stop_id"],
                                            checkpoint_ref=stopped["checkpoint"]["ref"], branch=stopped["branch"],
                                            head=stopped["head"], runner=engine)
    assert (checkout / "escape").is_symlink()


def test_ignored_escaping_symlink_does_not_prove_custody(tmp_path, capsys):
    layout, checkout, _, _, args = stopped_source(tmp_path, capsys, ignored_escape=True)
    with pytest.raises(ew.TakeoverRefused, match="symlink"):
        ew.project_stopped_versioned_source(layout, "w-a", **args)
    assert (checkout / "escape.cache").is_symlink()


def test_special_file_silently_omitted_by_git_refuses_projection(tmp_path, capsys):
    layout, checkout, _, _, args = stopped_source(tmp_path, capsys)
    os.mkfifo(checkout / "not-in-git")
    with pytest.raises(ew.TakeoverRefused, match="special file"):
        ew.project_stopped_versioned_source(layout, "w-a", **args)
    assert (checkout / "not-in-git").exists()


def test_projection_rejects_blob_oid_that_does_not_match_physical_source(tmp_path, capsys):
    layout, checkout, engine, stopped, args = stopped_source(tmp_path, capsys)
    original = engine.__class__.__call__

    class Transformed(FakeEngine):
        def __call__(self, argv, **kwargs):
            result = original(self, argv, **kwargs)
            if "ls-tree" in argv and result.returncode == 0 and isinstance(result.stdout, bytes):
                data = re.sub(rb"100644 blob [0-9a-f]{40}\tREADME\.md\x00",
                              b"100644 blob " + b"a" * 40 + b"\tREADME.md\0", result.stdout)
                return subprocess.CompletedProcess(argv, 0, data, result.stderr)
            return result

    engine.__class__ = Transformed
    with pytest.raises(ew.TakeoverRefused, match="physical source bytes"):
        ew.project_stopped_versioned_source(layout, "w-a", **args)
    assert (checkout / "README.md").read_bytes() == b"physical\r\nbytes\r\n"
    assert stopped["checkpoint"]["status"] == "preserved"


def test_projection_refuses_missing_checkpoint_custody(tmp_path, capsys):
    layout, checkout, engine, stopped, args = stopped_source(tmp_path, capsys)
    store = layout.epic_dir / "control" / "checkpoints" / "w-a.git"
    subprocess.run(["git", "--git-dir", str(store), "update-ref", stopped["checkpoint"]["ref"], args["head"]],
                   capture_output=True, check=True)
    with pytest.raises(ew.TakeoverRefused, match="checkpoint custody"):
        ew.project_stopped_versioned_source(layout, "w-a", **args)
    assert (checkout / "secret.cache").read_text() == "unique ignored work\n"


def test_projection_refuses_source_write_during_inspection(tmp_path, capsys):
    layout, checkout, engine, _, args = stopped_source(tmp_path, capsys)
    original = engine.__class__.__call__

    class LateWrite(FakeEngine):
        changed = False
        tree_reads = 0

        def __call__(self, argv, **kwargs):
            result = original(self, argv, **kwargs)
            if "ls-tree" in argv:
                self.tree_reads += 1
            if not self.changed and self.tree_reads == 2:
                self.changed = True
                (checkout / "README.md").write_text("later unique work\n")
            return result

    engine.__class__ = LateWrite
    with pytest.raises(ew.TakeoverRefused):
        ew.project_stopped_versioned_source(layout, "w-a", **args)
    assert (checkout / "README.md").read_text() == "later unique work\n"


@pytest.mark.parametrize("entry", [b"100644 blob " + b"a" * 40 + b"\t../escape\0",
                                    b"160000 commit " + b"a" * 40 + b"\tsubmodule\0"])
def test_projection_tree_parser_refuses_unsafe_paths_and_modes(entry):
    with pytest.raises(ew.TakeoverRefused, match="unsafe path or unsupported"):
        ew._projection_entries(entry)
