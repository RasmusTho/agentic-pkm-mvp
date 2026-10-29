"""Real temporary files; no native admission, runtime, or dispatch is exercised."""
from __future__ import annotations

import ast
import builtins
from dataclasses import replace
import hashlib
import importlib
import json
import os
from pathlib import Path
import shutil
import socket
import stat
import subprocess

import pytest


@pytest.fixture(autouse=True)
def denied_external_ports(monkeypatch):
    def denied(*_args, **_kwargs):
        pytest.fail("component reached a forbidden external process/network/Product port")

    for name in ("Popen", "run", "call", "check_call", "check_output"):
        monkeypatch.setattr(subprocess, name, denied)
    for name in ("system", "popen", "posix_spawn", "posix_spawnp", "fork", "forkpty", "execve"):
        if hasattr(os, name):
            monkeypatch.setattr(os, name, denied)
    monkeypatch.setattr(socket, "socket", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    original_import = builtins.__import__

    def isolated_import(name, *args, **kwargs):
        if name.startswith("app.") and name not in {"app.ops", "app.ops.bws_control_installation"}:
            return denied()
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", isolated_import)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture
def case(tmp_path):
    module = importlib.import_module("app.ops.bws_control_installation")
    base = tmp_path.resolve()
    paths = {name: base / name for name in ("application", "control", "launcher", "backups")}
    for path in paths.values():
        path.mkdir(mode=0o755)
    legacy_contract = (Path(__file__).parent / "fixtures" / "host_secret_contract_legacy.json").read_bytes()
    specs = (
        ("launcher", "yggdrasil-bws-deploy", b"#!/fixed/python\nold launcher\n", 0o755, b"#!/fixed/python\nnew launcher\n"),
        ("application", "app/ops/helper.py", b"old source\x00\xff\n", 0o600, b"new source\n"),
        ("application", "app/ops/created.py", None, None, b"new module\n"),
        ("application", "app/ops/matching.py", b"unchanged\n", 0o644, b"unchanged\n"),
        ("application", "config/secrets/host_secret_contract.json", legacy_contract, 0o644, b'{"new":true}\n'),
        ("control", "app/ops/helper.py", b"control old\n", 0o644, b"control new\n"),
    )
    changes, payloads = [], {}
    for root, name, before, before_mode, after in specs:
        path = paths[root] / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if before is not None:
            path.write_bytes(before)
            path.chmod(before_mode)
        changes.append(module.Change(root, name, None if before is None else digest(before),
                                     before_mode, digest(after), 0o755 if root == "launcher" else 0o644))
        payloads[(root, name)] = after

    def identity(path):
        info = path.stat()
        return module.Root(str(path), info.st_dev, info.st_ino, info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode))

    roots = {key: identity(value) for key, value in paths.items() if key != "backups"}
    args = dict(roots=roots, changes=tuple(changes), payloads=payloads,
                backup_root=identity(paths["backups"]), bundle_name="synthetic-once")
    return module, paths, args


def snapshot(paths):
    return {str(path): (path.read_bytes(), stat.S_IMODE(path.stat().st_mode), path.stat().st_ino)
            for key, root in paths.items() if key != "backups"
            for path in root.rglob("*") if path.is_file() and not path.is_symlink()}


def refused(module, args):
    with pytest.raises(module.InstallationRefused) as raised:
        module.install_public_files(**args)
    if raised.value.installation is not None:
        assert raised.value.installation.state == "refused"
        raised.value.installation.close()
    return raised.value


@pytest.mark.parametrize("fault", [
    "traversal", "absolute", "double_slash", "backslash", "extra_payload", "duplicate", "wrong_kind",
    "control_json", "control_scripts", "other_launcher", "bad_hash", "hash_mismatch", "bad_before", "bad_mode", "absence_mode",
    "symlink", "ancestor_symlink", "root_symlink", "hardlink", "mode_drift", "root_owner", "root_identity",
    "unsafe_directory", "unsafe_root", "alias_root", "missing_before",
])
def test_public_manifest_and_target_boundaries(case, fault):
    module, paths, args = case
    change = args["changes"][1]
    path = paths["application"] / change.path
    edit = {}
    if fault in {"traversal", "absolute", "double_slash", "backslash", "wrong_kind"}:
        edit["path"] = {"traversal": "app/../outside.py", "absolute": "/app/a.py",
                        "double_slash": "app//a.py", "backslash": "app/ops\\a.py", "wrong_kind": "config/private.json"}[fault]
    elif fault == "extra_payload":
        args["payloads"][("application", "app/extra.py")] = b"extra"
    elif fault == "duplicate":
        args["changes"] += (change,)
    elif fault == "control_json":
        edit.update(root="control", path="config/secrets/host_secret_contract.json")
    elif fault == "control_scripts":
        edit.update(root="control", path="scripts/helper.py")
    elif fault == "other_launcher":
        edit.update(root="launcher", path="other-launcher")
    elif fault == "bad_hash":
        edit["after_sha256"] = "A" * 64
    elif fault == "hash_mismatch":
        edit["after_sha256"] = "0" * 64
    elif fault == "bad_before":
        edit["before_sha256"] = "bad"
    elif fault == "bad_mode":
        edit["mode"] = 0o700
    elif fault == "absence_mode":
        edit["before_sha256"] = None
    elif fault == "symlink":
        path.rename(path.with_suffix(".held"))
        path.symlink_to(path.with_suffix(".held"))
    elif fault == "ancestor_symlink":
        parent = path.parent
        parent.rename(parent.with_name("held"))
        parent.symlink_to(parent.with_name("held"), target_is_directory=True)
    elif fault == "root_symlink":
        root = paths["application"]
        root.rename(root.with_name("held-root"))
        root.symlink_to(root.with_name("held-root"), target_is_directory=True)
    elif fault == "hardlink":
        os.link(path, path.with_suffix(".linked"))
    elif fault == "mode_drift":
        path.chmod(0o666)
    elif fault == "root_owner":
        args["roots"]["application"] = replace(args["roots"]["application"], uid=os.getuid() + 1)
    elif fault == "root_identity":
        args["roots"]["application"] = replace(args["roots"]["application"], inode=0)
    elif fault == "unsafe_directory":
        path.parent.chmod(0o777)
    elif fault == "unsafe_root":
        paths["application"].chmod(0o777)
    elif fault == "alias_root":
        args["roots"]["control"] = args["roots"]["application"]
    elif fault == "missing_before":
        path.unlink()
    if edit:
        changed = replace(change, **edit)
        args["changes"] = (args["changes"][0], changed, *args["changes"][2:])
        if (changed.root, changed.path) != (change.root, change.path):
            args["payloads"][(changed.root, changed.path)] = args["payloads"].pop((change.root, change.path))
    before = snapshot(paths)
    refused(module, args)
    assert snapshot(paths) == before
    assert not list(paths["backups"].iterdir())


@pytest.mark.parametrize("fault", ["file_fsync", "bundle_fsync", "parent_fsync", "partial_write", "foreign_same_bytes", "swapped_publication"])
def test_backup_publication_preserves_exact_ownership(case, monkeypatch, fault):
    module, paths, args = case
    before = snapshot(paths)
    original_fsync, original_write = os.fsync, os.write
    backup_parent = paths["backups"].stat().st_ino
    failed = False

    def fsync(fd):
        nonlocal failed
        info = os.fstat(fd)
        match = ((fault == "file_fsync" and stat.S_ISREG(info.st_mode))
                 or (fault == "bundle_fsync" and stat.S_ISDIR(info.st_mode) and info.st_ino != backup_parent)
                 or (fault == "parent_fsync" and info.st_ino == backup_parent))
        if match and not failed:
            failed = True
            raise OSError("injected fsync failure")
        original_fsync(fd)
        if fault == "swapped_publication" and info.st_ino == backup_parent and not failed:
            failed = True
            bundle = paths["backups"] / args["bundle_name"]
            bundle.rename(bundle.with_name("retained-owned"))
            shutil.copytree(bundle.with_name("retained-owned"), bundle)

    calls = 0

    def write(fd, data):
        nonlocal calls
        calls += 1
        if calls == 1:
            return original_write(fd, data[:3])
        raise OSError("partial owned backup")

    if fault == "foreign_same_bytes":
        with module.install_public_files(**args) as first:
            assert module.compensate_public_files(first)
        bundle = paths["backups"] / args["bundle_name"]
        bundle.rename(bundle.with_name("historical"))
        shutil.copytree(bundle.with_name("historical"), bundle)
        original = bundle.stat().st_ino
        before = snapshot(paths)
    elif fault == "partial_write":
        monkeypatch.setattr(os, "write", write)
    else:
        monkeypatch.setattr(os, "fsync", fsync)
    error = refused(module, args)
    assert snapshot(paths) == before
    bundle = paths["backups"] / args["bundle_name"]
    assert bundle.is_dir()  # Incomplete owned backups are retained, never re-used.
    if fault == "foreign_same_bytes":
        assert error.reason == "bundle_exists" and bundle.stat().st_ino == original
    else:
        assert error.installation._bundle is not None
    assert error.installation.compensation == []
    refused(module, args)


def test_public_files_and_launcher_install_exactly(case, monkeypatch):
    module, paths, args = case
    matching = paths["application"] / "app/ops/matching.py"
    untouched = matching.stat()
    original_write = os.write
    # Short writes are completed, not mistaken for a complete backup or target.
    monkeypatch.setattr(os, "write", lambda fd, raw: original_write(fd, raw[:max(1, len(raw) // 2)]))
    with module.install_public_files(**args) as handle:
        assert handle.state == "installed"
        for change in args["changes"]:
            path = paths[change.root] / change.path
            assert path.read_bytes() == args["payloads"][(change.root, change.path)]
            assert stat.S_IMODE(path.stat().st_mode) == change.mode
        assert matching.stat().st_ino == untouched.st_ino
        assert matching.stat().st_mtime_ns == untouched.st_mtime_ns
        bundle = Path(handle.bundle_path)
        rows = json.loads((bundle / "manifest.json").read_bytes())
        assert rows[2]["before"] is None
        assert rows[0]["before"]["mode"] == 0o755
        assert rows[1]["before"]["mode"] == 0o600
        assert (bundle / "0001.before").read_bytes() == b"old source\x00\xff\n"
        assert {stat.S_IMODE(p.stat().st_mode) for p in bundle.iterdir()} == {0o600}
    assert bundle.exists()


def test_prepare_publishes_backup_without_replacing_targets(case):
    module, paths, args = case
    before = snapshot(paths)

    handle = module.prepare_public_files(**args)

    assert handle.state == "prepared"
    assert snapshot(paths) == before
    bundle = Path(handle.bundle_path)
    assert bundle.is_dir()
    assert json.loads((bundle / "manifest.json").read_bytes())
    assert not (paths["application"] / "app/ops/created.py").exists()
    assert (paths["launcher"] / "yggdrasil-bws-deploy").read_bytes() == b"#!/fixed/python\nold launcher\n"

    assert module.apply_public_files(handle) is handle
    assert handle.state == "installed"
    assert all(outcome != "refused" for _, outcome in module.compensate_public_files(handle))
    assert handle.compensation_attempted is True
    assert handle.compensation_complete is True
    handle.close()


def test_prepared_handle_proves_no_change_before_restored_old_start(case):
    module, paths, args = case
    before = snapshot(paths)
    handle = module.prepare_public_files(**args)

    assert module.compensate_public_files(handle) == ()
    assert handle.compensation_attempted is True
    assert handle.compensation_complete is True
    assert handle.state == "compensated"
    assert snapshot(paths) == before
    assert Path(handle.bundle_path).is_dir()
    handle.close()


def test_prepared_compensation_refuses_drift_in_an_already_matching_target(case):
    module, paths, args = case
    handle = module.prepare_public_files(**args)
    matching = paths["application"] / "app/ops/matching.py"
    matching.write_bytes(b"foreign after preflight\n")
    matching.chmod(0o644)
    foreign_inode = matching.stat().st_ino

    with pytest.raises(module.InstallationRefused, match="compensation_refused"):
        module.compensate_public_files(handle)

    assert handle.compensation_attempted is True
    assert handle.compensation_complete is False
    assert dict(handle.compensation)["app/ops/matching.py"] == "refused"
    assert matching.stat().st_ino == foreign_inode
    assert matching.read_bytes() == b"foreign after preflight\n"
    handle.close()


def test_apply_refuses_drift_after_preparation_without_overwriting_it(case):
    module, paths, args = case
    handle = module.prepare_public_files(**args)
    changed = paths["application"] / "app/ops/helper.py"
    changed.write_bytes(b"foreign after backup\n")
    changed.chmod(0o600)
    foreign_inode = changed.stat().st_ino

    with pytest.raises(module.InstallationRefused, match="file_drift") as raised:
        module.apply_public_files(handle)

    assert raised.value.installation is handle
    assert handle.state == "refused"
    assert changed.stat().st_ino == foreign_inode
    assert changed.read_bytes() == b"foreign after backup\n"
    assert (paths["launcher"] / "yggdrasil-bws-deploy").read_bytes() == b"#!/fixed/python\nold launcher\n"
    assert Path(handle.bundle_path).is_dir()
    handle.close()


def test_apply_refuses_a_closed_or_consumed_handle(case):
    module, _paths, args = case
    handle = module.prepare_public_files(**args)
    handle.close()
    with pytest.raises(module.InstallationRefused, match="installation_state_refused"):
        module.apply_public_files(handle)


def test_handle_refuses_apply_and_close_from_a_different_process(case):
    module, paths, args = case
    before = snapshot(paths)
    handle = module.prepare_public_files(**args)
    owner_pid = handle._owner_pid
    handle._owner_pid = owner_pid + 1

    with pytest.raises(module.InstallationRefused, match="installation_owner_process_refused"):
        module.apply_public_files(handle)
    with pytest.raises(module.InstallationRefused, match="installation_owner_process_refused"):
        handle.close()

    assert handle.state == "prepared"
    assert snapshot(paths) == before
    handle._owner_pid = owner_pid
    handle.close()


def test_prepared_state_cannot_be_reconstructed_from_a_path(case):
    module, paths, args = case
    before = snapshot(paths)
    foreign = module.Installation(args["backup_root"].path + "/synthetic", state="prepared")

    with pytest.raises(module.InstallationRefused, match="installation_state_refused"):
        module.apply_public_files(foreign)

    assert snapshot(paths) == before
    assert not list(paths["backups"].iterdir())


@pytest.mark.parametrize("fault", ["mid_install", "rename_then_error", "link_then_error", "target_fsync", "target_partial_write", "foreign_same_bytes", "inplace_drift", "newcomer"])
def test_partial_install_compensation_is_exact_and_owned(case, monkeypatch, fault):
    module, paths, args = case
    before = snapshot(paths)
    historical = paths["backups"] / "historical"
    historical.mkdir()
    (historical / "pin").write_bytes(b"retain forever")
    original_replace, original_link, original_fsync, original_write = os.replace, os.link, os.fsync, os.write
    calls = 0
    created = paths["application"] / "app/ops/created.py"
    launcher = paths["launcher"] / "yggdrasil-bws-deploy"
    foreign_inode = None

    def replace_file(src, dst, **kwargs):
        nonlocal calls, foreign_inode
        calls += 1
        if fault == "rename_then_error" and calls == 3:
            assert dst == "host_secret_contract.json"
            original_replace(src, dst, **kwargs)
            raise OSError("rename completed but acknowledgement failed")
        if calls == 3 and fault in {"mid_install", "foreign_same_bytes", "inplace_drift"}:
            if fault == "foreign_same_bytes":
                foreign = launcher.with_name("foreign")
                foreign.write_bytes(launcher.read_bytes())
                foreign.chmod(0o755)
                original_replace(foreign, launcher)
                foreign_inode = launcher.stat().st_ino
            elif fault == "inplace_drift":
                launcher.write_bytes(b"foreign bytes")
                foreign_inode = launcher.stat().st_ino
            raise OSError("mid-install failure")
        return original_replace(src, dst, **kwargs)

    def link(src, dst, **kwargs):
        if fault == "newcomer":
            created.write_bytes(b"foreign newcomer")
            created.chmod(0o644)
        result = original_link(src, dst, **kwargs)
        if fault == "link_then_error":
            raise OSError("link completed but acknowledgement failed")
        return result

    def write(fd, raw):
        if fault == "target_partial_write" and raw == b"new source\n":
            original_write(fd, raw[:2])
            raise OSError("partial staged target")
        return original_write(fd, raw)

    failed = False

    def fsync(fd):
        nonlocal failed
        if fault == "target_fsync" and os.fstat(fd).st_ino == paths["launcher"].stat().st_ino and not failed:
            failed = True
            raise OSError("target directory durability unknown")
        return original_fsync(fd)

    monkeypatch.setattr(os, "replace", replace_file)
    monkeypatch.setattr(os, "link", link)
    monkeypatch.setattr(os, "fsync", fsync)
    monkeypatch.setattr(os, "write", write)
    error = refused(module, args)
    result = dict(error.installation.compensation)
    assert error.installation.compensation_attempted is True
    assert error.installation.compensation_complete is all(
        outcome != "refused" for outcome in result.values()
    )
    assert (historical / "pin").read_bytes() == b"retain forever"
    assert (paths["backups"] / args["bundle_name"] / "manifest.json").is_file()
    if fault in {"foreign_same_bytes", "inplace_drift"}:
        assert launcher.stat().st_ino == foreign_inode
        assert result["yggdrasil-bws-deploy"] == "refused"
        before.pop(str(launcher))
    if fault == "newcomer":
        assert created.read_bytes() == b"foreign newcomer"
    else:
        assert not created.exists()
    for name, (data, mode, _) in before.items():
        assert Path(name).read_bytes() == data
        assert stat.S_IMODE(Path(name).stat().st_mode) == mode
    if fault not in {"foreign_same_bytes", "inplace_drift"}:
        assert result["yggdrasil-bws-deploy"] == "restored"


@pytest.mark.parametrize("fault", ["missing", "malformed", "foreign_file", "foreign_bundle", "partial", "ancestor", "closed", "replay"])
def test_uncertain_or_foreign_recovery_refuses(case, fault):
    module, paths, args = case
    handle = module.install_public_files(**args)
    bundle = Path(handle.bundle_path)
    saved = bundle / "0000.before"
    if fault == "missing":
        saved.unlink()
    elif fault == "malformed":
        (bundle / "manifest.json").write_bytes(b"{}")
    elif fault == "foreign_file":
        raw = saved.read_bytes()
        saved.unlink()
        saved.write_bytes(raw)
        saved.chmod(0o600)
    elif fault == "foreign_bundle":
        bundle.rename(bundle.with_name("retained-owned"))
        shutil.copytree(bundle.with_name("retained-owned"), bundle)
    elif fault == "partial":
        saved.write_bytes(b"partial")
    elif fault == "ancestor":
        root = paths["control"]
        root.rename(root.with_name("retained-control"))
        shutil.copytree(root.with_name("retained-control"), root)
    elif fault == "closed":
        handle.close()
    elif fault == "replay":
        assert module.compensate_public_files(handle)
    before = snapshot(paths)
    if fault in {"closed", "replay"}:
        with pytest.raises(module.InstallationRefused, match="compensation_state_refused"):
            module.compensate_public_files(handle)
    else:
        with pytest.raises(module.InstallationRefused, match="compensation_refused"):
            module.compensate_public_files(handle)
        outcomes = handle.compensation
        assert outcomes and all(outcome == "refused" for _, outcome in outcomes)
        assert handle.state == "compensation_refused"
    assert snapshot(paths) == before
    assert bundle.exists()
    handle.close()


def test_component_has_no_native_execution_entrypoint(case):
    module, paths, args = case
    # Re-import executes the module with the denied process/socket/Product ports.
    module = importlib.reload(module)
    # Reload produces new dataclass types; build the public typed inputs from
    # those imported definitions rather than retaining pre-reload instances.
    args["changes"] = tuple(module.Change(**vars(change)) for change in args["changes"])
    args["roots"] = {name: module.Root(**vars(root)) for name, root in args["roots"].items()}
    args["backup_root"] = module.Root(**vars(args["backup_root"]))
    assert not hasattr(module, "main") and not hasattr(module, "run")
    tree = ast.parse(Path(module.__file__).read_text())
    imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    imports |= {name.name for node in ast.walk(tree) if isinstance(node, ast.Import) for name in node.names}
    assert imports <= {"__future__", "fcntl", "hashlib", "json", "os", "pathlib", "re", "stat", "dataclasses", "typing", "uuid", "weakref"}
    with module.install_public_files(**args) as handle:
        assert handle.state == "installed"
        assert all(outcome != "refused" for _, outcome in module.compensate_public_files(handle))
    assert not (paths["application"] / "app/ops/created.py").exists()


def test_component_calls_are_serialized_without_native_admission(case):
    module, paths, args = case
    with module.install_public_files(**args) as first:
        installed = snapshot(paths)
        refused(module, {**args, "bundle_name": "second-invocation"})
        assert snapshot(paths) == installed
        assert not (paths["backups"] / "second-invocation").exists()
        assert all(outcome != "refused" for _, outcome in module.compensate_public_files(first))


def test_install_refuses_same_byte_target_replacement_after_backup(case, monkeypatch):
    module, paths, args = case
    launcher = paths["launcher"] / "yggdrasil-bws-deploy"
    original_fsync = os.fsync
    replaced = False
    foreign_inode = None

    def fsync(fd):
        nonlocal replaced, foreign_inode
        original_fsync(fd)
        if os.fstat(fd).st_ino == paths["backups"].stat().st_ino and not replaced:
            replaced = True
            foreign = launcher.with_name("foreign")
            foreign.write_bytes(launcher.read_bytes())
            foreign.chmod(0o755)
            os.replace(foreign, launcher)
            foreign_inode = launcher.stat().st_ino

    monkeypatch.setattr(os, "fsync", fsync)
    error = refused(module, args)
    assert error.reason == "file_drift"
    assert error.installation.compensation == []
    assert launcher.stat().st_ino == foreign_inode
    assert launcher.read_bytes() == b"#!/fixed/python\nold launcher\n"


def test_compensation_never_removes_foreign_same_byte_new_target(case):
    module, paths, args = case
    with module.install_public_files(**args) as handle:
        created = paths["application"] / "app/ops/created.py"
        foreign = created.with_name("foreign")
        foreign.write_bytes(created.read_bytes())
        foreign.chmod(0o644)
        os.replace(foreign, created)
        foreign_inode = created.stat().st_ino
        with pytest.raises(module.InstallationRefused, match="compensation_refused"):
            module.compensate_public_files(handle)
        outcomes = dict(handle.compensation)
        assert outcomes["app/ops/created.py"] == "refused"
        assert created.stat().st_ino == foreign_inode
        assert created.read_bytes() == b"new module\n"
        assert outcomes["yggdrasil-bws-deploy"] == "restored"


@pytest.mark.parametrize("field,value", [
    ("mode", float(0o644)), ("mode", True), ("mode", "0644"),
    ("before_mode", float(0o600)), ("before_mode", False), ("before_mode", "0600"),
])
def test_mode_types_refuse_before_any_backup_or_target_write(case, field, value):
    module, paths, args = case
    # This is the second target: the old implementation installed the launcher
    # before float(0644) reached fchmod and escaped its compensation exception path.
    bad = replace(args["changes"][1], **{field: value})
    args["changes"] = (args["changes"][0], bad, *args["changes"][2:])
    before = snapshot(paths)
    refused(module, args)
    assert snapshot(paths) == before
    assert not list(paths["backups"].iterdir())


@pytest.mark.parametrize("field", ["device", "inode", "uid", "gid", "mode"])
def test_root_identity_types_refuse_before_backup(case, field):
    module, paths, args = case
    root = args["roots"]["application"]
    args["roots"]["application"] = replace(root, **{field: float(getattr(root, field))})
    before = snapshot(paths)
    assert refused(module, args).reason == "root_refused"
    assert snapshot(paths) == before
    assert not list(paths["backups"].iterdir())


@pytest.mark.parametrize("fault", ["valid", "missing_manifest", "missing_saved", "malformed", "foreign_manifest", "foreign_bundle", "extra_file"])
def test_all_matching_invalid_backup_is_transaction_refusal(case, fault):
    module, paths, args = case
    changes, payloads = [], {}
    for change in args["changes"]:
        if change.before_sha256 is None:
            continue
        path = paths[change.root] / change.path
        path.chmod(change.mode)
        raw = path.read_bytes()
        changes.append(replace(change, before_mode=change.mode, after_sha256=digest(raw)))
        payloads[(change.root, change.path)] = raw
    args.update(changes=tuple(changes), payloads=payloads)
    before = snapshot(paths)
    with module.install_public_files(**args) as handle:
        assert all(target.written is None for target in handle._targets)
        bundle = Path(handle.bundle_path)
        manifest = bundle / "manifest.json"
        if fault == "missing_manifest":
            manifest.unlink()
        elif fault == "missing_saved":
            (bundle / "0000.before").unlink()
        elif fault == "malformed":
            manifest.write_bytes(b"{}")
        elif fault == "foreign_manifest":
            raw = manifest.read_bytes()
            manifest.unlink()
            manifest.write_bytes(raw)
            manifest.chmod(0o600)
        elif fault == "foreign_bundle":
            bundle.rename(bundle.with_name("owned-retained"))
            shutil.copytree(bundle.with_name("owned-retained"), bundle)
        elif fault == "extra_file":
            (bundle / "foreign").write_bytes(b"extra")
        if fault == "valid":
            assert module.compensate_public_files(handle) == ()
            assert handle.state == "compensated"
        else:
            with pytest.raises(module.InstallationRefused, match="compensation_refused"):
                module.compensate_public_files(handle)
            assert handle.state == "compensation_refused"
        assert handle.compensation == []  # No per-target row can carry this failure.
        assert snapshot(paths) == before
        assert bundle.exists()
