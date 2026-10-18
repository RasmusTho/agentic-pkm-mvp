"""Exercise the real lifecycle/CLI against an isolated filesystem and OS boundary."""
from __future__ import annotations

import ast
import errno
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import struct
from types import SimpleNamespace

import pytest

from app.ops import builder_executor_keyring as keyring


class Host:
    def __init__(self):
        self.active = False
        self.linger = False
        self.fail_start = False
        self.fail_decrypt = False
        self.fail_stop_response = False
        self.encryptions: list[bytes] = []
        self.calls: list[tuple[list[str], bytes | None]] = []
        self.inventory = b"existing.socket enabled enabled\n"

    def run(self, args, *, input=None, **kwargs):
        self.calls.append((args, input))
        code, output = 0, b""
        if "/usr/bin/systemd-creds" in args:
            if "encrypt" in args:
                self.encryptions.append(input)
                output = b"encrypted-synthetic:" + keyring.digest(input).encode()
            elif self.fail_decrypt:
                code = 1
        elif "show" in args and keyring.UNIT in args:
            loaded = os.path.lexists(keyring.UNIT_PATH)
            output = (f"LoadState={'loaded' if loaded else 'not-found'}\n"
                      f"ActiveState={'active' if self.active else 'inactive'}\n"
                      "SubState=running\n"
                      f"MainPID={123 if self.active else 0}\n"
                      f"FragmentPath={keyring.BUNDLE / keyring.UNIT if loaded else ''}\n"
                      "DropInPaths=\n").encode()
        elif "show-user" in args:
            output = b"yes\n" if self.linger else b"no\n"
        elif "enable-linger" in args:
            self.linger = True
        elif "list-unit-files" in args:
            output = self.inventory
        elif "NameHasOwner" in args:
            output = b"b false\n"
        elif "native-status" in args:
            output = json.dumps({"native_owner_matches": self.active, "unlocked": self.active}).encode()
        elif "enable" in args:
            if self.fail_start:
                code = 1
            else:
                self.active = True
                keyring.STATE.mkdir(mode=0o700, exist_ok=True)
        elif "disable" in args:
            self.active = False
            if self.fail_stop_response:
                code = 1
        return subprocess.CompletedProcess(args, code, output, b"suppressed synthetic diagnostics")


@pytest.fixture
def host(tmp_path, monkeypatch):
    uid = os.geteuid()
    for name, value in {
        "ROOT_UID": uid, "UID": uid, "BUNDLE": tmp_path / "opt" / "bundle",
        "STATE": tmp_path / "state", "CONTROL": tmp_path / "control",
        "UNIT_PATH": tmp_path / "system" / keyring.UNIT, "LOCK": tmp_path / "lock",
        "MACHINE_KEY": tmp_path / "machine-key", "MASK_DIRECTORY": tmp_path / "masks",
        "CGROUP_PATH": tmp_path / "cgroup",
    }.items():
        monkeypatch.setattr(keyring, name, value)
    keyring.BUNDLE.parent.mkdir(mode=0o755)
    keyring.UNIT_PATH.parent.mkdir(mode=0o755)
    keyring.MASK_DIRECTORY.mkdir(mode=0o755)
    for name in keyring.MASKS:
        (keyring.MASK_DIRECTORY / name).symlink_to("/dev/null")
    keyring.MACHINE_KEY.write_bytes(b"synthetic pre-existing OS host key; never opened by observe")
    keyring.MACHINE_KEY.chmod(0o400)
    monkeypatch.setattr(keyring.sys, "platform", "linux")
    monkeypatch.setattr(keyring.socket, "gethostname", lambda: "builder-system")
    monkeypatch.setattr(keyring.pwd, "getpwnam", lambda name: SimpleNamespace(
        pw_uid=uid, pw_gid=uid, pw_dir=str(tmp_path / "home")))
    monkeypatch.setattr(keyring.shutil, "which", lambda *a, **kw: "/usr/bin/native-tool")

    def parents(path, *, create=False):
        # OS boundary substitute: only this private fixture subtree is writable.
        assert path.is_relative_to(tmp_path)
        for item in path.parents:
            if item == tmp_path:
                break
            if create:
                item.mkdir(mode=0o755, parents=True, exist_ok=True)
            if item.exists():
                assert not item.is_symlink()
                assert item.stat().st_uid == uid
                assert not item.stat().st_mode & 0o022

    monkeypatch.setattr(keyring, "protected_parents", parents)
    fake = Host()
    monkeypatch.setattr(keyring, "_RUN", fake.run)
    root = Path(__file__).resolve().parents[2]
    package = {"source_sha": "a" * 40,
               "module": (root / "app/ops/builder_executor_keyring.py").read_text(),
               "unit": (root / "config/systemd" / keyring.UNIT).read_text()}
    return fake, package


def invoke(package, action="plan", **extra):
    return keyring.remote({"action": action, "payload": package, **extra})


def test_installer_plan_apply_binding_and_existing_state_refusal(host, tmp_path, monkeypatch, capsys):
    fake, package = host
    spec = importlib.util.spec_from_file_location(
        "keyring_installer_test", Path(__file__).resolve().parents[2] / "scripts/install_builder_executor_keyring.py")
    installer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installer)

    def run(args, **kwargs):
        if args[0] == "git":
            output = ""
            if args[1:3] == ["rev-parse", "HEAD"] or args[1:3] == ["rev-parse", "origin/main"]:
                output = package["source_sha"]
            elif args[1] == "show":
                output = package["module" if args[-1].endswith(".py") else "unit"]
            elif args[1] == "ls-remote":
                output = package["source_sha"] + "\trefs/heads/main\n"
            elif args[1:3] == ["remote", "get-url"]:
                output = "https://github.com/RasmusTho/agentic-pkm-mvp.git"
            return subprocess.CompletedProcess(args, 0, output, "")
        assert args[0] == "ssh" and installer.ALIAS in args
        assert args[-1] == "sudo -n /usr/bin/python3 -I -"
        parsed = ast.parse(kwargs["input"])
        request = ast.literal_eval(parsed.body[-1].value.args[0].args[0].args[0])
        return subprocess.CompletedProcess(args, 0, json.dumps(keyring.remote(request)), "")

    monkeypatch.setattr(installer, "_RUN", run)
    before = sorted(str(p) for p in tmp_path.rglob("*"))
    assert installer.main([]) == 0
    approved = json.loads(capsys.readouterr().out)
    assert approved["before"]["installation"] == "absent"
    assert before == sorted(str(p) for p in tmp_path.rglob("*"))
    assert not fake.encryptions
    assert installer.main(["apply"]) == 78
    capsys.readouterr()
    plan_file = tmp_path / "operator-plan.json"
    plan_file.write_text(json.dumps(approved))
    assert installer.main(["apply", "--plan-file", str(plan_file),
                           "--expected-plan-sha256", approved["plan_sha256"]]) == 0
    assert json.loads(capsys.readouterr().out)["native"]["unlocked"]
    assert fake.linger and fake.active and len(fake.encryptions) == 1
    changed = dict(package, source_sha="b" * 40)
    assert invoke(changed)["result"] == "refused"
    original = keyring.BUNDLE / "master.cred"
    content = original.read_bytes()
    original.chmod(0o644)
    assert invoke(package, "apply", plan=approved)["result"] == "refused"
    assert original.read_bytes() == content and len(fake.encryptions) == 1


def test_apply_uses_encrypted_stdin_handoff_and_rejects_bad_custody(host):
    fake, package = host
    approved = invoke(package)
    assert invoke(package, "apply", plan=approved)["native"]["unlocked"]
    master = fake.encryptions[0]
    assert 32 <= len(master) <= 256 and b"\n" not in master
    assert master not in json.dumps(approved).encode()
    for args, data in fake.calls:
        assert master.decode() not in " ".join(args)
        if data == master:
            assert args[0] == "/usr/bin/systemd-run" and "encrypt" in args
            assert "--property=ProtectSystem=strict" in args
            assert f"--property=ReadOnlyPaths={keyring.MACHINE_KEY.parent} {keyring.MACHINE_KEY}" in args
            assert "--property=RuntimeMaxSec=15" in args
    for path in keyring.BUNDLE.iterdir():
        assert master not in path.read_bytes()
    assert (keyring.BUNDLE / "master.cred").stat().st_mode & 0o777 == 0o400
    assert b"LoadCredential=" in (keyring.BUNDLE / keyring.UNIT).read_bytes()
    assert b"LoadCredentialEncrypted=" not in (keyring.BUNDLE / keyring.UNIT).read_bytes()
    assert b"User=ygg" in (keyring.BUNDLE / keyring.UNIT).read_bytes()
    metadata = keyring.BUNDLE / "installation.json"
    alias = metadata.with_name("alias")
    alias.hardlink_to(metadata)
    assert invoke(package, "status")["result"] == "refused"


def test_interrupted_installation_and_disable_preserve_owned_state(host):
    fake, package = host
    approved = invoke(package)
    fake.fail_start = True
    assert invoke(package, "apply", plan=approved)["result"] == "refused"
    content = (keyring.BUNDLE / "master.cred").read_bytes()
    fake.fail_start = False
    assert invoke(package, "apply", plan=approved)["native"]["unlocked"]
    assert len(fake.encryptions) == 1
    assert (keyring.BUNDLE / "master.cred").read_bytes() == content
    stop = invoke(package, operation="disable")
    fake.fail_stop_response = True
    assert invoke(package, "apply", plan=stop)["result"] == "refused"
    fake.fail_stop_response = False
    assert invoke(package, "apply", plan=stop)["owned_service_stopped"]
    assert keyring.STATE.is_dir() and fake.linger
    assert (keyring.BUNDLE / "master.cred").read_bytes() == content
    assert not any("terminate-user" in args or "disable-linger" in args for args, _ in fake.calls)


@pytest.mark.parametrize("failure", [None, "owner", "locked", "timeout", "final-backend-error",
                                      "final-unexpected-exit", "final-owner-missing", "final-locked"])
def test_service_readiness_and_session_lifetime_are_fail_closed(host, monkeypatch, failure):
    fake, package = host
    assert invoke(package, "apply", plan=invoke(package))["native"]["unlocked"]
    stored = None
    cleared = False

    def run(args, *, input=None, **kwargs):
        nonlocal stored, cleared
        if args[0].endswith("busctl"):
            output = b"b true"
            if "NameHasOwner" in args and cleared and failure == "final-owner-missing":
                output = b"b false"
            if "GetConnectionUnixUser" in args:
                output = f"u {keyring.UID}".encode()
            elif "GetConnectionUnixProcessID" in args:
                output = b"u 999" if failure == "owner" else b"u 123"
            elif "ReadAlias" in args:
                output = b'o "/org/freedesktop/secrets/collection/login"'
            elif "Locked" in args:
                output = b"b true" if failure == "locked" or cleared and failure == "final-locked" else b"b false"
            return subprocess.CompletedProcess(args, 0, output, b"")
        if args[0].endswith("secret-tool"):
            if "store" in args:
                stored = input
            elif "clear" in args:
                cleared = True
            elif "lookup" in args:
                if failure == "timeout":
                    raise subprocess.TimeoutExpired(args, 3)
                code = 2 if cleared and failure == "final-unexpected-exit" else 1 if cleared else 0
                error = b"secret-tool: Cannot autolaunch D-Bus" if cleared and failure == "final-backend-error" else b""
                return subprocess.CompletedProcess(args, code, b"" if cleared else stored, error)
            return subprocess.CompletedProcess(args, 0, b"", b"")
        return fake.run(args, input=input, **kwargs)

    monkeypatch.setattr(keyring, "_RUN", run)
    if failure:
        with pytest.raises(keyring.Refusal):
            keyring.ready()
        if failure == "timeout" or failure.startswith("final-"):
            assert cleared
    else:
        assert keyring.ready()["synthetic_roundtrip_and_cleanup"]
        assert cleared
    unit = package["unit"]
    assert "Requires=user@1000.service" in unit and "BindsTo=user@1000.service" in unit
    assert "KillMode=control-group" in unit and "TimeoutStartSec=30" in unit
    assert "StandardOutput=null" in unit and "StandardError=null" in unit


def test_bad_encryption_never_publishes_a_bundle_or_starts_services(host):
    fake, package = host
    approved = invoke(package)
    fake.fail_decrypt = True
    assert invoke(package, "apply", plan=approved)["result"] == "refused"
    assert not keyring.BUNDLE.exists() and not os.path.lexists(keyring.UNIT_PATH)
    assert not fake.linger and not fake.active


def test_reviewed_effects_cannot_hide_master_generation(host):
    fake, package = host
    approved = invoke(package)
    approved["effects"]["generate_dedicated_master"] = False
    approved["plan_sha256"] = keyring.digest(keyring.canonical({
        k: v for k, v in approved.items() if k != "plan_sha256"}))
    assert invoke(package, "apply", plan=approved)["reason"] == "plan_effects_mismatch"
    assert not fake.encryptions and not keyring.BUNDLE.exists()


def test_bundle_published_before_unit_link_is_reconciled_without_new_master(host, monkeypatch):
    fake, package = host
    approved = invoke(package)
    symlink = os.symlink

    def fail_link(target, path, **kwargs):
        if path == keyring.UNIT_PATH:
            raise OSError("synthetic interrupted publication")
        return symlink(target, path, **kwargs)

    monkeypatch.setattr(keyring.os, "symlink", fail_link)
    assert invoke(package, "apply", plan=approved)["result"] == "refused"
    assert keyring.BUNDLE.exists() and not os.path.lexists(keyring.UNIT_PATH)
    assert len(fake.encryptions) == 1
    monkeypatch.setattr(keyring.os, "symlink", symlink)
    assert invoke(package, "apply", plan=approved)["native"]["unlocked"]
    assert len(fake.encryptions) == 1


@pytest.mark.parametrize("failure", ["inventory", "digest", "unit", "default-keyring", "state-link", "machine-key"])
def test_precondition_drift_and_foreign_state_refuse_before_key_generation(host, tmp_path, failure):
    fake, package = host
    approved = invoke(package)
    if failure == "inventory":
        fake.inventory += b"new.socket enabled enabled\n"
    elif failure == "digest":
        approved["action"] = "disable"
    elif failure == "unit":
        keyring.UNIT_PATH.write_text("foreign unit")
    elif failure == "default-keyring":
        (tmp_path / "home/.local/share/keyrings").mkdir(parents=True)
    elif failure == "state-link":
        keyring.STATE.symlink_to(tmp_path)
    else:
        keyring.MACHINE_KEY.unlink()
    assert invoke(package, "apply", plan=approved)["result"] == "refused"
    assert not fake.encryptions and not fake.linger and not fake.active


def test_status_and_withdrawal_survive_unrelated_main_advancement(host):
    fake, package = host
    assert invoke(package, "apply", plan=invoke(package))["native"]["unlocked"]
    later = dict(package, source_sha="b" * 40)
    assert invoke(later, "status")["source_sha"] == package["source_sha"]
    assert invoke(later)["result"] == "refused"  # Upgrades are not implicit.
    stop = invoke(later, operation="disable")
    assert invoke(later, "apply", plan=stop)["owned_service_stopped"]
    assert len(fake.encryptions) == 1 and not fake.active
    retained_start = invoke(later, operation="start")
    assert invoke(later, "apply", plan=retained_start)["native"]["unlocked"]
    assert len(fake.encryptions) == 1
    assert keyring.owned()["source_sha"] == package["source_sha"]


def test_remaining_owned_cgroup_blocks_withdrawal_success_and_reactivation(host):
    fake, package = host
    assert invoke(package, "apply", plan=invoke(package))["native"]["unlocked"]
    stop = invoke(package, operation="disable")
    keyring.CGROUP_PATH.mkdir(mode=0o700)
    (keyring.CGROUP_PATH / "cgroup.procs").write_text("123\n")
    assert invoke(package, "apply", plan=stop)["reason"] == "service_stop_unproven"
    assert not fake.active
    assert invoke(package)["reason"] == "unit_cleanup_unproven"
    (keyring.CGROUP_PATH / "cgroup.procs").write_text("")
    assert invoke(package, "apply", plan=stop)["owned_cgroup_empty_or_reclaimed"]


@pytest.mark.parametrize("failure", [None, "empty", "public", "symlink", "hardlink", "acl", "foreign-acl",
                                         "group-acl", "write-acl", "malformed-acl", "root-no-acl",
                                         "writable-key", "writable-parent", "decrypt", "drop", "owner"])
def test_daemon_hands_protected_credential_to_native_stdin_only(host, tmp_path, monkeypatch, failure):
    _, _package = host
    root = tmp_path / "credentials"
    directory = root / keyring.UNIT
    directory.mkdir(mode=0o700, parents=True)
    credential = directory / keyring.CREDENTIAL
    value, ciphertext = b"s" * 64, b"synthetic-encrypted-master"
    credential.write_bytes(b"" if failure == "empty" else ciphertext)
    credential.chmod(0o644 if failure == "public" else 0o400)
    if failure in ("symlink", "hardlink"):
        original = directory / "original"
        credential.rename(original)
        if failure == "symlink":
            credential.symlink_to(original)
        else:
            credential.hardlink_to(original)
    monkeypatch.setattr(keyring, "CREDENTIAL_DIRECTORY_ROOT", root)
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(directory))
    fstat = os.fstat
    target_uid = os.geteuid() + 100
    monkeypatch.setattr(keyring, "UID", target_uid)
    monkeypatch.setattr(keyring.pwd, "getpwuid", lambda uid: SimpleNamespace(pw_dir=str(tmp_path / 'home')))
    acl_cases = {"acl", "foreign-acl", "group-acl", "write-acl", "malformed-acl", "root-no-acl"}
    if failure in acl_cases:
        credential.chmod(0o400 if failure == "root-no-acl" else 0o440)

    def credential_metadata(fd):
        result = list(fstat(fd))
        result[4] = keyring.ROOT_UID if failure in acl_cases else target_uid
        return os.stat_result(result)

    monkeypatch.setattr(keyring.os, "fstat", credential_metadata)

    def credential_acl(fd, name):
        assert name == "system.posix_acl_access" and fstat(fd).st_size >= 0
        if failure not in acl_cases or failure == "root-no-acl":
            raise OSError(errno.ENODATA, "synthetic no ACL")
        undefined = 0xffffffff
        entries = [(1, 4, undefined), (2, 6 if failure == "write-acl" else 4,
                                      target_uid + 1 if failure == "foreign-acl" else target_uid),
                   (4, 4 if failure == "group-acl" else 0, undefined),
                   (16, 4, undefined), (32, 0, undefined)]
        return (b"bad" if failure == "malformed-acl" else struct.pack("<I", 2)) + b"".join(
            struct.pack("<HHI", *entry) for entry in entries)

    monkeypatch.setattr(keyring.os, "getxattr", credential_acl, raising=False)
    monkeypatch.setattr(keyring.os, "statvfs", lambda path: SimpleNamespace(
        f_flag=0 if path == (keyring.MACHINE_KEY if failure == "writable-key" else
                             keyring.MACHINE_KEY.parent if failure == "writable-parent" else None)
        else os.ST_RDONLY))
    drops, decrypts, executed = [], [], []
    identity = {"uid": keyring.ROOT_UID, "gid": keyring.ROOT_UID, "groups": [keyring.ROOT_UID]}
    monkeypatch.setattr(keyring.os, "getuid", lambda: identity['uid'])
    monkeypatch.setattr(keyring.os, "geteuid", lambda: identity['uid'])
    monkeypatch.setattr(keyring.os, "getgid", lambda: identity['gid'])
    monkeypatch.setattr(keyring.os, "getegid", lambda: identity['gid'])
    monkeypatch.setattr(keyring.os, "getgroups", lambda: identity['groups'])

    def drop(kind, setting):
        drops.append(kind)
        if failure != "drop":
            identity[kind] = setting

    monkeypatch.setattr(keyring.os, "setgroups", lambda setting: drop('groups', setting))
    monkeypatch.setattr(keyring.os, "setgid", lambda setting: drop('gid', setting))
    monkeypatch.setattr(keyring.os, "setuid", lambda setting: drop('uid', setting))

    def decrypt(args, *, input, env, **kwargs):
        assert identity['uid'] == keyring.ROOT_UID
        assert args[:2] == ['/usr/bin/systemd-creds', 'decrypt'] and args[-2:] == ['-', '-']
        assert input == ciphertext and value not in str(args).encode() and value not in str(env).encode()
        decrypts.append(True)
        return subprocess.CompletedProcess(args, 1 if failure == 'decrypt' else 0, value, b'')

    monkeypatch.setattr(keyring, '_RUN', decrypt)

    def owner():
        assert identity['uid'] == target_uid and not identity['groups']
        return 999 if failure == 'owner' else None

    monkeypatch.setattr(keyring, 'bus_owner', owner)

    class ExecObserved(BaseException):
        pass

    def execute(path, argv, env):
        assert path == "/usr/bin/gnome-keyring-daemon"
        assert "--foreground" in argv and "--unlock" in argv
        assert drops == ['groups', 'gid', 'uid'] and identity['uid'] == identity['gid'] == target_uid
        assert value.decode() not in " ".join(argv) and value.decode() not in " ".join(env.values())
        assert "CREDENTIALS_DIRECTORY" not in env
        assert os.read(0, 256) == value
        executed.append(True)
        raise ExecObserved()

    monkeypatch.setattr(keyring.os, "execve", execute)
    saved = os.dup(0)
    try:
        if failure and failure != "acl":
            with pytest.raises((keyring.Refusal, OSError)):
                keyring.daemon()
            assert not executed
            if failure not in ('decrypt', 'drop', 'owner'):
                assert not decrypts
        else:
            with pytest.raises(ExecObserved):
                keyring.daemon()
            assert executed == [True] and decrypts == [True]
    finally:
        os.dup2(saved, 0)
        os.close(saved)


def test_status_and_withdrawal_do_not_require_shared_host_key(host):
    fake, package = host
    assert invoke(package, "apply", plan=invoke(package))["native"]["unlocked"]
    keyring.MACHINE_KEY.unlink()
    assert invoke(package, 'status')['installation'] == 'owned'
    stop = invoke(package, operation='disable')
    assert invoke(package, 'apply', plan=stop)['owned_service_stopped']
    assert not fake.active and len(fake.encryptions) == 1
    assert invoke(package, operation='start')['result'] == 'refused'
