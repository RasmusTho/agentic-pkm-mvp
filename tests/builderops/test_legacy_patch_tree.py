from __future__ import annotations

import hashlib

import pytest

from app.builderops.legacy_patch_tree import PatchTreeRefused, verify_first_patch_delta


def oid(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def test_exact_two_file_delta_and_rejects_other_changes() -> None:
    selected = {"a": b"new a\x00", "b": b"new b"}
    old = {"a": oid(b"old a"), "b": oid(b"old b")}
    delta = {name: ("100644", old[name], "100644", oid(data)) for name, data in selected.items()}
    assert verify_first_patch_delta(delta, selected, old) == {n: oid(v) for n, v in selected.items()}
    with pytest.raises(PatchTreeRefused):
        verify_first_patch_delta({**delta, "other": ("100644", old["a"], "100644", oid(b"x"))}, selected, old)
    with pytest.raises(PatchTreeRefused):
        verify_first_patch_delta({**delta, "a": ("100644", old["a"], "100755", oid(selected["a"]))}, selected, old)
    with pytest.raises(PatchTreeRefused):
        verify_first_patch_delta(delta, {**selected, "a": b"different"}, old)


def test_real_git_direct_successor_rejects_extra_tree_change(tmp_path, monkeypatch) -> None:
    import subprocess
    from app.builderops import legacy_git_config
    from app.builderops.legacy_patch_tree import verify_first_patch_commit

    def git(*args):
        return subprocess.check_output(["/usr/bin/git", "-C", str(tmp_path), *args]).decode().strip()

    git("init", "-q")
    git("config", "user.name", "fixture")
    git("config", "user.email", "fixture@example.invalid")
    for name in ("a", "b", "other"):
        (tmp_path / name).write_text("old " + name)
    git("add", "a", "b", "other")
    git("commit", "-qm", "base")
    parent = git("rev-parse", "HEAD")
    old = {n: git("rev-parse", f"HEAD:{n}") for n in ("a", "b")}
    selected = {"a": b"new a", "b": b"new b"}
    for name, data in selected.items():
        (tmp_path / name).write_bytes(data)
    git("add", "a", "b")
    git("commit", "-qm", "patch")
    commit = git("rev-parse", "HEAD")
    monkeypatch.setattr(legacy_git_config, "check_host_config", lambda: None)
    monkeypatch.setattr(legacy_git_config, "check", lambda **_kw: None)
    kwargs = dict(cwd=tmp_path, worktree=tmp_path, parent=parent, commit=commit, selected=selected, baseline_oids=old)
    assert verify_first_patch_commit(**kwargs) == {n: oid(v) for n, v in selected.items()}
    (tmp_path / "other").write_text("extra")
    git("add", "other")
    git("commit", "-qm", "extra")
    with pytest.raises(PatchTreeRefused, match="direct single-parent"):
        verify_first_patch_commit(**{**kwargs, "commit": git("rev-parse", "HEAD")})


def test_temporary_index_must_contain_exact_two_file_delta(tmp_path) -> None:
    import os
    import subprocess
    from app.builderops.legacy_patch_tree import verify_first_patch_index

    root = tmp_path / 'checkout'
    root.mkdir()
    index = tmp_path / 'selected.index'

    def git(*args, isolated=False):
        env = os.environ.copy()
        if isolated:
            env['GIT_INDEX_FILE'] = str(index)
        return subprocess.check_output(['/usr/bin/git', '-C', str(root), *args], env=env).decode().strip()

    git('init', '-q')
    git('config', 'user.name', 'fixture')
    git('config', 'user.email', 'fixture@example.invalid')
    for name in ('a', 'b', 'other'):
        (root / name).write_text('old ' + name)
    git('add', 'a', 'b', 'other')
    git('commit', '-qm', 'base')
    parent = git('rev-parse', 'HEAD')
    old = {name: git('rev-parse', f'HEAD:{name}') for name in ('a', 'b')}
    selected = {'a': b'new a', 'b': b'new b'}
    for name, data in selected.items():
        (root / name).write_bytes(data)
    git('read-tree', 'HEAD', isolated=True)
    git('add', '--', 'a', 'b', isolated=True)
    ordinary = root / '.git' / 'index'
    args = dict(worktree=root, index=index, ordinary_index=ordinary, parent=parent,
                selected=selected, baseline_oids=old)
    assert len(verify_first_patch_index(**args)) == 64
    (root / 'other').write_text('extra')
    git('add', '--', 'other', isolated=True)
    with pytest.raises(PatchTreeRefused):
        verify_first_patch_index(**args)
    with pytest.raises(PatchTreeRefused):
        verify_first_patch_index(**{**args, 'index': ordinary})
