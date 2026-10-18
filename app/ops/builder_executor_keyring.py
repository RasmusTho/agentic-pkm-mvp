"""Fixed BOB-1 native keyring lifecycle; no provider credentials cross this API.

The installer runs as root; the native bootstrap drops root before GNOME executes.
Readiness runs as ygg. Only plan-bound apply operations mutate host configuration.
This is not a BWS binding.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import secrets
import shutil
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import time
from typing import Any, Iterator, Mapping

UNIT = "yggdrasil-builder-executor-keyring.service"
USER = "ygg"
UID = 1000
ROOT_UID = 0
BUNDLE = Path("/opt/builderops/executor-keyring")
STATE = Path("/var/lib/yggdrasil-builder-executor-keyring")
CONTROL = Path("/run/yggdrasil-builder-executor-keyring")
UNIT_PATH = Path("/etc/systemd/system") / UNIT
LOCK = Path("/run/lock/yggdrasil-builder-executor-keyring.lock")
MACHINE_KEY = Path("/var/lib/systemd/credential.secret")
MASK_DIRECTORY = Path("/etc/systemd/user")
CREDENTIAL_DIRECTORY_ROOT = Path("/run/credentials")
USER_RUNTIME = Path("/run/user/1000")
BUS_ADDRESS = "unix:path=/run/user/1000/bus"
CGROUP_PATH = Path("/sys/fs/cgroup/system.slice") / UNIT
CREDENTIAL = "builder-executor-keyring-master"
MASKS = tuple(f"{name}.{kind}" for name in ("gnome-keyring-daemon", "gcr-ssh-agent")
              for kind in ("service", "socket"))
_RUN = subprocess.run


class Refusal(Exception):
    """A value-free refusal code, never a subprocess exception or raw diagnostic."""


def require(condition: object, code: str) -> None:
    if not condition:
        raise Refusal(code)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def command(args: list[str], *, data: bytes | None = None, timeout: int = 20,
            env: Mapping[str, str] | None = None) -> subprocess.CompletedProcess[bytes]:
    try:
        return _RUN(args, input=data, capture_output=True, timeout=timeout,
                    env=dict(env) if env is not None else {"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
                    check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Refusal("command_unavailable_or_timeout") from exc


def checked(args: list[str], **kwargs: Any) -> bytes:
    result = command(args, **kwargs)
    require(result.returncode == 0, "command_refused")
    return result.stdout


def properties(args: list[str]) -> dict[str, str]:
    return dict(line.split("=", 1) for line in checked(args).decode().splitlines() if "=" in line)


def private_file(path: Path, owner: int, *, writable: bool = False) -> bytes:
    flags = os.O_RDONLY | os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise Refusal("protected_file_unavailable") from exc
    try:
        s = os.fstat(fd)
        require(stat.S_ISREG(s.st_mode) and s.st_nlink == 1 and s.st_uid == owner
                and not stat.S_IMODE(s.st_mode) & (0o077 if writable else 0o022),
                "protected_file_custody")
        require(s.st_size <= 1024 * 1024, "protected_file_size")
        return os.read(fd, s.st_size + 1)
    finally:
        os.close(fd)


def protected_parents(path: Path, *, create: bool = False) -> None:
    for parent in reversed(path.parents):
        if not os.path.lexists(parent):
            if not create:
                continue
            parent.mkdir(mode=0o755)
        s = parent.lstat()
        require(stat.S_ISDIR(s.st_mode) and s.st_uid == ROOT_UID
                and not stat.S_IMODE(s.st_mode) & 0o022, "parent_custody")


def native_environment() -> dict[str, str]:
    return {"PATH": "/usr/bin:/bin", "LC_ALL": "C.UTF-8", "HOME": pwd.getpwuid(UID).pw_dir,
            "XDG_RUNTIME_DIR": str(USER_RUNTIME), "XDG_DATA_HOME": str(STATE),
            "DBUS_SESSION_BUS_ADDRESS": BUS_ADDRESS}


def bus(*args: str) -> str:
    return checked(["/usr/bin/busctl", f"--address={BUS_ADDRESS}", *args],
                   timeout=2, env=native_environment()).decode().strip()


def bus_owner() -> int | None:
    if bus("call", "org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
           "NameHasOwner", "s", "org.freedesktop.secrets") == "b false":
        return None
    who = bus("call", "org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
              "GetConnectionUnixUser", "s", "org.freedesktop.secrets")
    require(who == f"u {UID}", "foreign_native_owner")
    value = bus("call", "org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                "GetConnectionUnixProcessID", "s", "org.freedesktop.secrets")
    require(re.fullmatch(r"u [1-9][0-9]*", value), "native_owner_unproven")
    return int(value.split()[1])


def unlocked() -> bool:
    alias = bus("call", "org.freedesktop.secrets", "/org/freedesktop/secrets",
                "org.freedesktop.Secret.Service", "ReadAlias", "s", "default").split()
    require(len(alias) == 2 and alias[0] == "o" and alias[1].strip('"') != "/",
            "native_collection_missing")
    return bus("get-property", "org.freedesktop.secrets", alias[1].strip('"'),
               "org.freedesktop.Secret.Collection", "Locked") == "b false"


def native_status(*, wait: bool = False) -> dict[str, object]:
    require(os.geteuid() == UID, "native_user_required")
    deadline = time.monotonic() + (8 if wait else 0)
    while True:
        props = properties(["/usr/bin/systemctl", "show", UNIT, "-p", "MainPID", "-p", "ActiveState"])
        owner = bus_owner()
        if owner is not None:
            require(props.get("MainPID") == str(owner), "foreign_native_owner")
            require(unlocked(), "native_collection_locked")
            require(bus_owner() == owner, "native_owner_changed")
            return {"native_owner_matches": True, "unlocked": True}
        require(wait and time.monotonic() < deadline, "native_owner_missing")
        time.sleep(0.05)


def ready() -> dict[str, object]:
    result = native_status(wait=True)
    identity = "builder-executor-check-" + secrets.token_hex(16)
    value = secrets.token_urlsafe(32).encode()
    env = native_environment()
    args = ["/usr/bin/secret-tool"]
    try:
        checked(args + ["store", "--label=Builder executor readiness", "executor-readiness", identity],
                data=value, timeout=3, env=env)
        read = checked(args + ["lookup", "executor-readiness", identity], timeout=3, env=env)
        require(read.rstrip(b"\n") == value, "native_roundtrip_failed")
    finally:
        checked(args + ["clear", "executor-readiness", identity], timeout=3, env=env)
    absent = command(args + ["lookup", "executor-readiness", identity], timeout=3, env=env)
    require(absent.returncode != 0 and not absent.stdout, "synthetic_cleanup_unproven")
    return {**result, "synthetic_roundtrip_and_cleanup": True}


def daemon() -> None:
    # ExecStart=! retains root only for ciphertext decoding inside the unit's
    # already-applied mount sandbox. PID1 never decrypts this credential.
    require(os.geteuid() == ROOT_UID, "native_bootstrap_root_required")
    require(all(os.statvfs(p).f_flag & os.ST_RDONLY for p in (MACHINE_KEY, MACHINE_KEY.parent)),
            "host_key_mount_must_be_read_only")
    directory = Path(os.environ.get("CREDENTIALS_DIRECTORY", ""))
    require(directory == CREDENTIAL_DIRECTORY_ROOT / UNIT, "credential_directory_mismatch")
    fd = os.open(directory / CREDENTIAL, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        s = os.fstat(fd)
        require(stat.S_ISREG(s.st_mode) and s.st_nlink == 1 and 1 <= s.st_size <= 16384,
                "native_credential_custody_or_size")
        credential_permissions(fd, s)
        encrypted = os.read(fd, s.st_size + 1)
        require(len(encrypted) == s.st_size, "native_credential_changed")
    finally:
        os.close(fd)
    master = checked(["/usr/bin/systemd-creds", "decrypt", f"--name={CREDENTIAL}", "-", "-"],
                     data=encrypted, env={"PATH": "/usr/bin:/bin", "LC_ALL": "C",
                                          "SYSTEMD_CREDENTIAL_SECRET": str(MACHINE_KEY)})
    require(re.fullmatch(rb"[A-Za-z0-9_-]{64}", master), "native_master_format")
    read_fd, write_fd = os.pipe()
    try:
        try:
            require(os.write(write_fd, master) == len(master), "native_master_handoff")
        finally:
            os.close(write_fd)
        os.setgroups([])
        os.setgid(UID)
        os.setuid(UID)
        require(os.getuid() == os.geteuid() == UID and os.getgid() == os.getegid() == UID
                and not os.getgroups(), "native_privilege_drop_unproven")
        require(bus_owner() is None, "competing_native_owner")
        os.dup2(read_fd, 0, inheritable=True)
    except BaseException:
        os.close(read_fd)
        raise
    if read_fd != 0:
        os.close(read_fd)
    os.execve("/usr/bin/gnome-keyring-daemon", ["gnome-keyring-daemon", "--foreground",
              "--components=secrets", "--unlock", f"--control-directory={CONTROL}"], native_environment())


def credential_permissions(fd: int, metadata: os.stat_result) -> None:
    """Validate the ciphertext credential's exact systemd255 ACL/UID custody."""
    try:
        acl = getattr(os, "getxattr")(fd, "system.posix_acl_access")
    except OSError as exc:
        require(exc.errno in (errno.ENODATA, errno.ENOTSUP), "credential_acl_unavailable")
        require(metadata.st_uid == UID and stat.S_IMODE(metadata.st_mode) == 0o400,
                "credential_owner_or_mode")
        return
    require(metadata.st_uid == ROOT_UID and stat.S_IMODE(metadata.st_mode) == 0o440,
            "credential_acl_owner_or_mode")
    # Linux POSIX ACL xattr v2: tag, permissions, qualifier. Reject any extra grant,
    # including ineffective named entries, rather than trusting mode's ACL mask.
    undefined = 0xffffffff
    expected = ((1, 4, undefined), (2, 4, UID), (4, 0, undefined),
                (16, 4, undefined), (32, 0, undefined))
    require(len(acl) == 44 and acl[:4] == struct.pack("<I", 2)
            and tuple(struct.iter_unpack("<HHI", acl[4:])) == expected,
            "credential_acl_grants")


def user_command(args: list[str]) -> list[str]:
    return ["/usr/sbin/runuser", "-u", USER, "--", "/usr/bin/env",
            f"XDG_RUNTIME_DIR=/run/user/{UID}",
            f"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{UID}/bus", *args]


def unit_properties() -> dict[str, str]:
    return properties(["/usr/bin/systemctl", "show", UNIT, "-p", "LoadState", "-p", "ActiveState",
                       "-p", "SubState", "-p", "MainPID", "-p", "FragmentPath", "-p", "DropInPaths",
                       "-p", "ControlGroup"])


def quiescent(props: Mapping[str, str]) -> bool:
    if props.get("ActiveState") not in ("inactive", "failed") or props.get("MainPID") != "0":
        return False
    if props.get("ControlGroup") not in (None, "", f"/system.slice/{UNIT}"):
        return False
    if not os.path.lexists(CGROUP_PATH):
        return True
    require(CGROUP_PATH.is_dir() and not CGROUP_PATH.is_symlink()
            and (CGROUP_PATH / "cgroup.procs").is_file(), "unit_cgroup_unproven")
    return all(not p.read_text().strip() for p in CGROUP_PATH.rglob("cgroup.procs"))


def owned(payload: Mapping[str, str] | None = None) -> dict[str, object] | None:
    if not os.path.lexists(BUNDLE):
        return None
    s = BUNDLE.lstat()
    require(stat.S_ISDIR(s.st_mode) and s.st_uid == ROOT_UID and stat.S_IMODE(s.st_mode) == 0o755,
            "foreign_bundle")
    metadata = json.loads(private_file(BUNDLE / "installation.json", ROOT_UID))
    require(metadata.get("purpose") == "bob-1-builder-executor-keyring", "foreign_installation")
    installed = {"source_sha": metadata["source_sha"]}
    for name, key in (("runtime.py", "module"), (UNIT, "unit")):
        installed[key] = private_file(BUNDLE / name, ROOT_UID).decode()
    require(payload_hash(installed) == metadata["payload_sha256"], "installed_payload_drift")
    if payload is not None:
        require(metadata["source_sha"] == payload["source_sha"]
                and metadata["payload_sha256"] == payload_hash(payload), "foreign_installation")
    require(digest(private_file(BUNDLE / "master.cred", ROOT_UID, writable=True)) == metadata["master_sha256"],
            "encrypted_master_drift")
    return dict(metadata)


def payload_hash(payload: Mapping[str, str]) -> str:
    require(re.fullmatch(r"[0-9a-f]{40}", payload["source_sha"]), "source_identity")
    return digest(canonical({k: payload[k] for k in ("source_sha", "module", "unit")}))


def observe(payload: Mapping[str, str], *, match_source: bool = True,
            need_host_key: bool = True) -> dict[str, object]:
    require(os.geteuid() == ROOT_UID and sys.platform == "linux" and socket.gethostname() == "builder-system",
            "fixed_target_required")
    account = pwd.getpwnam(USER)
    require(account.pw_uid == UID and account.pw_gid == UID, "fixed_user_required")
    for name in ("gnome-keyring-daemon", "secret-tool", "busctl", "systemd-creds", "systemd-run"):
        require(shutil.which(name, path="/usr/bin:/bin"), "native_tool_missing")
    protected_parents(BUNDLE)
    protected_parents(UNIT_PATH)
    for name in MASKS:
        p = MASK_DIRECTORY / name
        require(p.is_symlink() and p.lstat().st_uid == ROOT_UID and os.readlink(p) == "/dev/null",
                "packaged_unit_mask_required")
    installation = owned(payload if match_source else None)
    props = unit_properties()
    require(not props.get("DropInPaths"), "unit_override_refused")
    if props.get("ActiveState") in ("inactive", "failed"):
        require(quiescent(props), "unit_cleanup_unproven")
    if os.path.lexists(UNIT_PATH):
        require(installation is not None and UNIT_PATH.is_symlink()
                and UNIT_PATH.lstat().st_uid == ROOT_UID and os.readlink(UNIT_PATH) == str(BUNDLE / UNIT),
                "foreign_unit")
    else:
        require(props.get("LoadState") == "not-found", "foreign_loaded_unit")
    if installation is None:
        require(not os.path.lexists(STATE), "existing_native_state")
        require(not (Path(account.pw_dir) / ".local/share/keyrings").exists(), "existing_default_keyring")
        owner = checked(user_command(["/usr/bin/busctl", f"--address={BUS_ADDRESS}",
                        "call", "org.freedesktop.DBus", "/org/freedesktop/DBus",
                        "org.freedesktop.DBus", "NameHasOwner", "s", "org.freedesktop.secrets"]))
        require(owner.strip() == b"b false", "competing_native_owner")
        require(not os.path.lexists(CONTROL), "existing_native_control")
    for directory in (STATE, CONTROL):
        if os.path.lexists(directory):
            s = directory.lstat()
            require(stat.S_ISDIR(s.st_mode) and s.st_uid == UID
                    and stat.S_IMODE(s.st_mode) == 0o700, "native_directory_custody")
    key_identity = None
    if need_host_key:
        protected_parents(MACHINE_KEY)
        key = MACHINE_KEY.lstat()
        require(stat.S_ISREG(key.st_mode) and key.st_nlink == 1 and key.st_uid == ROOT_UID
                and stat.S_IMODE(key.st_mode) == 0o400, "machine_key_custody")
        key_identity = digest(canonical([key.st_dev, key.st_ino, key.st_mtime_ns, key.st_size]))
    enabled = checked(user_command(["/usr/bin/systemctl", "--user", "list-unit-files", "--state=enabled",
                                    "--no-legend", "--no-pager"]))
    linger = checked(["/usr/bin/loginctl", "show-user", USER, "-p", "Linger", "--value"]).decode().strip()
    return {"target": "builder-system", "user": USER, "uid": UID,
            "installation": "owned" if installation else "absent",
            "installed_source_sha": installation["source_sha"] if installation else None,
            "unit_state": props.get("ActiveState"), "linger": linger,
            "enabled_user_units_sha256": digest(enabled), "payload_sha256": payload_hash(payload),
            "machine_key_metadata_sha256": key_identity}


def planned_effects(action: str, before: Mapping[str, object]) -> dict[str, object]:
    return {"unit": UNIT, "generate_dedicated_master": action == "apply" and before["installation"] == "absent",
            "ensure_native_started": action in ("apply", "start"), "stop_owned_native_service": action == "disable",
            "enable_user_lingering": action in ("apply", "start") and before["linger"] != "yes",
            "existing_enabled_user_units_may_persist": action in ("apply", "start"),
            "encryption_uses_finite_read_only_host_key_sandbox": action == "apply" and before["installation"] == "absent",
            "pid1_receives_ciphertext_only": True, "native_bootstrap_drops_root_before_daemon": True,
            "host_key_read_only_on_every_decrypt": True,
            "packaged_masks_retained": True, "root_can_decrypt": True,
            "same_uid_can_access_unlocked_keyring": True, "offline_image_protection": False,
            "provider_login_performed": False, "existing_services_restarted": False}


def plan(payload: Mapping[str, str], action: str = "apply") -> dict[str, object]:
    require(action in ("apply", "start", "disable"), "action_refused")
    before = observe(payload, match_source=action == "apply", need_host_key=action != "disable")
    if action != "apply":
        require(before["installation"] == "owned", "installation_missing")
    result: dict[str, object] = {"action": action, "source_sha": payload["source_sha"],
                                "before": before, "effects": planned_effects(action, before)}
    result["plan_sha256"] = digest(canonical(result))
    return result


@contextmanager
def installation_lock() -> Iterator[None]:
    fd = os.open(LOCK, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        s = os.fstat(fd)
        require(stat.S_ISREG(s.st_mode) and s.st_uid == ROOT_UID and s.st_nlink == 1
                and stat.S_IMODE(s.st_mode) == 0o600, "lock_custody")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise Refusal("installation_busy") from exc
        yield
    finally:
        os.close(fd)


def write_new(path: Path, content: bytes, mode: int) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    try:
        with os.fdopen(fd, "wb", closefd=False) as stream:
            stream.write(content)
            stream.flush()
            os.fsync(fd)
    finally:
        os.close(fd)


def sync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def install_bundle(payload: Mapping[str, str], approved: Mapping[str, object]) -> None:
    protected_parents(BUNDLE, create=True)
    with tempfile.TemporaryDirectory(prefix=".executor-keyring-", dir=BUNDLE.parent) as temp:
        stage = Path(temp)
        master = secrets.token_urlsafe(48).encode()
        encrypted = encrypt_master(master)
        require(encrypted and master not in encrypted, "encrypted_master_unproven")
        verified = credential_sandbox(["decrypt", f"--name={CREDENTIAL}", "-", "/dev/null"], encrypted)
        require(not verified, "decrypt_output_refused")
        write_new(stage / "master.cred", encrypted, 0o400)
        write_new(stage / "runtime.py", payload["module"].encode(), 0o555)
        write_new(stage / UNIT, payload["unit"].encode(), 0o644)
        write_new(stage / "installation.json", canonical({"source_sha": payload["source_sha"],
                  "purpose": "bob-1-builder-executor-keyring",
                  "payload_sha256": payload_hash(payload), "master_sha256": digest(encrypted),
                  "plan_sha256": approved["plan_sha256"], "before": approved["before"]}), 0o444)
        stage.chmod(0o755)
        sync_directory(stage)
        require(not os.path.lexists(BUNDLE), "bundle_publish_collision")
        os.rename(stage, BUNDLE)
        sync_directory(BUNDLE.parent)
        # TemporaryDirectory must not try to remove the now-published bundle.
        stage.mkdir(mode=0o700)


def encrypt_master(master: bytes) -> bytes:
    return credential_sandbox(["encrypt", "--with-key=host", f"--name={CREDENTIAL}", "-", "-"], master)


def credential_sandbox(arguments: list[str], value: bytes) -> bytes:
    # systemd-creds may unlink a foreign-machine host key even when it exists.
    # A private, read-only mount namespace makes *both* replacement and generation
    # impossible. No host-key content is opened by this module. --pipe carries the
    # master through descriptors; native stdout is captured ciphertext, never journal.
    return checked(["/usr/bin/systemd-run", "--quiet", "--wait", "--pipe", "--collect",
                    "--service-type=exec", "--property=ProtectSystem=strict",
                    f"--property=ReadOnlyPaths={MACHINE_KEY.parent} {MACHINE_KEY}",
                    "--property=PrivateTmp=yes", "--property=NoNewPrivileges=yes",
                    "--property=LimitCORE=0", "--property=RuntimeMaxSec=15",
                    "--property=TimeoutStopSec=3", "--property=KillMode=control-group",
                    "--property=StandardError=null",
                    f"--setenv=SYSTEMD_CREDENTIAL_SECRET={MACHINE_KEY}",
                    "/usr/bin/systemd-creds", *arguments], data=value)


def status(payload: Mapping[str, str]) -> dict[str, object]:
    observation = observe(payload, match_source=False, need_host_key=False)
    require(observation["installation"] == "owned", "installation_missing")
    result = command(user_command(["/usr/bin/python3", str(BUNDLE / "runtime.py"), "native-status"]))
    native = json.loads(result.stdout) if result.stdout else {"ready": False}
    return {"installation": "owned", "active": unit_properties().get("ActiveState") == "active",
            "native": native, "linger": observation["linger"],
            "source_sha": observation["installed_source_sha"]}


def apply(payload: Mapping[str, str], approved: Mapping[str, object]) -> dict[str, object]:
    unsigned = {k: v for k, v in approved.items() if k != "plan_sha256"}
    require(approved.get("plan_sha256") == digest(canonical(unsigned)), "plan_digest_mismatch")
    require(approved.get("source_sha") == payload["source_sha"], "plan_source_mismatch")
    before = approved.get("before")
    if not isinstance(before, dict):
        raise Refusal("plan_prestate_invalid")
    require(approved.get("effects") == planned_effects(str(approved["action"]), before), "plan_effects_mismatch")
    with installation_lock():
        current = observe(payload, match_source=approved["action"] == "apply",
                          need_host_key=approved["action"] != "disable")
        installation = owned(payload if approved["action"] == "apply" else None)
        resume = installation is not None and installation.get("plan_sha256") == approved["plan_sha256"]
        before = approved.get("before")
        if installation is not None and approved["action"] == "disable" and isinstance(before, dict):
            resume = {k: v for k, v in current.items() if k != "unit_state"} == {
                k: v for k, v in before.items() if k != "unit_state"}
        if installation is not None and approved["action"] == "start" and isinstance(before, dict):
            resume = {k: v for k, v in current.items() if k not in ("unit_state", "linger")} == {
                k: v for k, v in before.items() if k not in ("unit_state", "linger")}
        require(current == approved.get("before") or resume, "plan_prestate_changed")
        if resume and installation is not None and approved["action"] == "apply":
            original = installation["before"]
            immutable = ("target", "user", "uid", "enabled_user_units_sha256", "payload_sha256",
                         "machine_key_metadata_sha256")
            require(isinstance(original, dict) and all(original[k] == current[k] for k in immutable),
                    "installation_precondition_changed")
        if approved["action"] == "disable":
            require(installation is not None, "installation_missing")
            checked(["/usr/bin/systemctl", "disable", "--now", UNIT])
            props = unit_properties()
            require(quiescent(props), "service_stop_unproven")
            return {"owned_service_stopped": True, "encrypted_state_retained": True,
                    "owned_cgroup_empty_or_reclaimed": True,
                    "linger_retained": True, "provider_revoked": False}
        require(approved["action"] in ("apply", "start"), "action_refused")
        if approved["action"] == "start":
            require(installation is not None, "installation_missing")
        if installation is None:
            install_bundle(payload, approved)
        if not os.path.lexists(UNIT_PATH):
            os.symlink(str(BUNDLE / UNIT), UNIT_PATH)
            sync_directory(UNIT_PATH.parent)
        checked(["/usr/bin/systemctl", "daemon-reload"])
        props = unit_properties()
        require(not props.get("DropInPaths") and Path(props.get("FragmentPath", "")).resolve()
                == BUNDLE / UNIT, "loaded_unit_mismatch")
        if props.get("ActiveState") == "failed":
            require(quiescent(props), "unit_cleanup_unproven")
            checked(["/usr/bin/systemctl", "reset-failed", UNIT])
        checked(["/usr/bin/loginctl", "enable-linger", USER])
        checked(["/usr/bin/systemctl", "enable", "--now", UNIT], timeout=45)
        result = status(payload)
        require(result["active"] and isinstance(result["native"], dict)
                and result["native"].get("unlocked"), "native_start_unproven")
        return result


def remote(request: Mapping[str, Any]) -> dict[str, object]:
    try:
        payload = request["payload"]
        action = request["action"]
        if action == "plan":
            return plan(payload, request.get("operation", "apply"))
        if action == "status":
            return status(payload)
        require(action == "apply", "action_refused")
        return apply(payload, request["plan"])
    except Refusal as exc:
        return {"result": "refused", "reason": str(exc)}
    except Exception:
        return {"result": "refused", "reason": "invalid_or_unavailable_state"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("daemon", "ready", "native-status"))
    args = parser.parse_args()
    try:
        if args.mode == "daemon":
            daemon()
            return 1
        print(json.dumps(ready() if args.mode == "ready" else native_status(), sort_keys=True))
        return 0
    except Exception:
        print(json.dumps({"result": "refused", "reason": "native_backend_unavailable"}))
        return 78


if __name__ == "__main__":
    raise SystemExit(main())
