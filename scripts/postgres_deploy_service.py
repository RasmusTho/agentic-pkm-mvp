#!/opt/yggdrasil/bws-deploy-runtime/bin/python3
"""Operator-installed as /usr/local/libexec/yggdrasil-bws-deploy (root-owned)."""
import json
import errno
import fcntl
import hashlib
import io
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
from uuid import UUID

_SOURCE_PROVENANCE_POLICY = "bws-source-bytes-v2"
_SOURCE_HASH_ATTRIBUTE = "__yggdrasil_source_sha256__"
_SOURCE_PACKAGES = ("app", "scripts")
_CANDIDATE_CLEAN_PATHS = ("app", "scripts", "config/secrets/host_secret_contract.json")
_MAX_SOURCE_BYTES = 8 * 1024 * 1024
_RESERVATION_DIRECTORY = Path("/var/lib/yggdrasil/bws-deploy-convergence")
_GLOBAL_LOCK_NAME = "source-installation-global.lock"
_FIXED_LAUNCHER = Path("/usr/local/libexec/yggdrasil-bws-deploy")
_FIXED_RUNTIME = Path("/opt/yggdrasil/bws-deploy-runtime/bin/python3")
_PROC = Path("/proc")
_START_AUTHORIZATION_SCHEMA = "bws-source-installation-start.v1"
_STARTUP_RELEASE_ATTRIBUTE = "_yggdrasil_bws_startup_reservation_release"
_VERIFIED_CANDIDATE_ENTRYPOINT = "_yggdrasil_bws_verified_candidate_entrypoint"
_OWNER_UID = 0
_OWNER_GID = 0
_CLOEXEC = getattr(os, "O_CLOEXEC", 0)


class _PreimportReservation:
    """Hold the existing global shared lock before importing replaceable app code."""

    def __init__(self, descriptor: int | None, *, skip_cleanup: bool = False,
                 authorized_start: bool = False) -> None:
        self._descriptor = descriptor
        self.skip_cleanup = skip_cleanup
        self.authorized_start = authorized_start

    def release(self) -> None:
        descriptor, self._descriptor = self._descriptor, None
        if descriptor is None:
            return
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def _open_owned_directory(path: Path) -> int:
    if not path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts[1:]):
        raise RuntimeError("bws_preimport_reservation_refused")
    descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | _CLOEXEC)
    try:
        for part in path.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | _CLOEXEC,
                            dir_fd=descriptor)
            info = os.fstat(child)
            named = os.stat(part, dir_fd=descriptor, follow_symlinks=False)
            if ((info.st_dev, info.st_ino) != (named.st_dev, named.st_ino)
                    or info.st_uid != _OWNER_UID or info.st_gid != _OWNER_GID
                    or stat.S_IMODE(info.st_mode) & 0o022 or os.get_inheritable(child)):
                os.close(child)
                raise RuntimeError("bws_preimport_reservation_refused")
            os.close(descriptor)
            descriptor = child
        if stat.S_IMODE(os.fstat(descriptor).st_mode) not in {0o700, 0o755}:
            raise RuntimeError("bws_preimport_reservation_refused")
        result, descriptor = descriptor, -1
        return result
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _runtime_directory_fd(*, create: bool) -> int:
    path = _RESERVATION_DIRECTORY
    if not create:
        return _open_owned_directory(path)
    parent = _open_owned_directory(path.parent)
    try:
        try:
            os.mkdir(path.name, 0o700, dir_fd=parent)
            os.fsync(parent)
        except FileExistsError:
            pass
        descriptor = os.open(path.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | _CLOEXEC,
                             dir_fd=parent)
        info = os.fstat(descriptor)
        named = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
        if ((info.st_dev, info.st_ino) != (named.st_dev, named.st_ino)
                or info.st_uid != _OWNER_UID or info.st_gid != _OWNER_GID
                or stat.S_IMODE(info.st_mode) not in {0o700, 0o755}
                or stat.S_IMODE(info.st_mode) & 0o022 or os.get_inheritable(descriptor)):
            os.close(descriptor)
            raise RuntimeError("bws_preimport_reservation_refused")
        return descriptor
    finally:
        os.close(parent)


def _read_installation_owner(parent: int, channel: str) -> bytes:
    name = f"{channel}.source-installation.lock"
    descriptor = None
    try:
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | _CLOEXEC,
                             dir_fd=parent)
        info = os.fstat(descriptor)
        named = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if ((info.st_dev, info.st_ino) != (named.st_dev, named.st_ino)
                or not stat.S_ISREG(info.st_mode) or info.st_uid != _OWNER_UID
                or info.st_gid != _OWNER_GID or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_nlink != 1 or not 0 < info.st_size <= 4096
                or os.get_inheritable(descriptor)):
            raise RuntimeError("bws_preimport_reservation_refused")
        raw = os.pread(descriptor, 4097, 0)
        after = os.fstat(descriptor)
        named_after = os.stat(name, dir_fd=parent, follow_symlinks=False)
        version = lambda value: (value.st_dev, value.st_ino, value.st_uid, value.st_gid, value.st_mode,
                                 value.st_nlink, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
        if (len(raw) != info.st_size or version(after) != version(info)
                or version(named_after) != version(info)):
            raise RuntimeError("bws_preimport_reservation_refused")
        value = json.loads(raw, object_pairs_hook=_unique_json_object)
        caller = value.get("caller") if type(value) is dict else None
        fixed_fields = {"pid", "uid", "gid", "start_time", "argv_sha256",
                        "executable_sha256", "launcher_sha256"}
        checkout_fields = fixed_fields | {"candidate_sha", "source_checkout"}
        if (type(value) is not dict
                or set(value) != {"schema", "operation_id", "channel", "candidate_sha", "image_digest",
                                  "bundle_name", "caller"}
                or value["schema"] != "bws-source-installation-owner.v2"
                or value["channel"] != channel or type(value["operation_id"]) is not str
                or str(UUID(value["operation_id"])) != value["operation_id"]
                or type(value["candidate_sha"]) is not str
                or re.fullmatch(r"[0-9a-f]{40}", value["candidate_sha"]) is None
                or type(value["image_digest"]) is not str
                or re.fullmatch(r"sha256:[0-9a-f]{64}", value["image_digest"]) is None
                or type(value["bundle_name"]) is not str
                or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", value["bundle_name"]) is None
                or type(caller) is not dict
                or set(caller) not in (fixed_fields, checkout_fields)
                or any(type(caller[name]) is not int for name in ("pid", "uid", "gid", "start_time"))
                or caller["pid"] <= 0 or caller["uid"] != _OWNER_UID or caller["gid"] != _OWNER_GID
                or caller["start_time"] <= 0
                or any(type(caller[name]) is not str or re.fullmatch(r"[0-9a-f]{64}", caller[name]) is None
                       for name in ("argv_sha256", "executable_sha256", "launcher_sha256"))
                or (set(caller) == checkout_fields and (type(caller["candidate_sha"]) is not str
                    or caller["candidate_sha"] != value["candidate_sha"]))):
            raise RuntimeError("bws_preimport_reservation_refused")
        _verify_caller_checkout(caller)
        return raw
    except Exception:
        raise RuntimeError("bws_preimport_reservation_refused") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _read_proc_entry(process: int, name: str, limit: int) -> bytes:
    descriptor = None
    try:
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | _CLOEXEC,
                             dir_fd=process)
        if os.get_inheritable(descriptor):
            raise RuntimeError("bws_preimport_reservation_refused")
        content = bytearray()
        while len(content) <= limit:
            block = os.read(descriptor, min(4096, limit + 1 - len(content)))
            if not block:
                break
            content.extend(block)
        if len(content) > limit:
            raise RuntimeError("bws_preimport_reservation_refused")
        return bytes(content)
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _stat_identity(info: os.stat_result) -> tuple[int, ...]:
    return (info.st_dev, info.st_ino, info.st_uid, info.st_gid, info.st_mode,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _verify_caller_checkout(caller: dict[str, object]) -> str | None:
    binding = caller.get("source_checkout")
    if binding is None:
        if "candidate_sha" in caller:
            raise RuntimeError("bws_preimport_reservation_refused")
        return None
    if (type(binding) is not dict or set(binding) != {
            "path", "device", "inode", "mode", "revision", "script_sha256",
    } or any(type(binding[key]) is not int for key in ("device", "inode", "mode"))
            or type(binding["path"]) is not str or not Path(binding["path"]).is_absolute()
            or type(binding["revision"]) is not str
            or binding["revision"] != caller.get("candidate_sha")
            or type(binding["script_sha256"]) is not str
            or re.fullmatch(r"[0-9a-f]{64}", binding["script_sha256"]) is None):
        raise RuntimeError("bws_preimport_reservation_refused")
    checkout = Path(binding["path"])
    descriptors: list[int] = []
    try:
        if (str(checkout) != os.path.abspath(checkout) or "\\" in str(checkout)
                or len(checkout.parts) < 2
                or any(part in {"", ".", ".."} for part in checkout.parts[1:])):
            raise RuntimeError("bws_preimport_reservation_refused")
        current = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | _CLOEXEC)
        descriptors.append(current)
        root = os.fstat(current)
        path_parts = checkout.parts[1:]
        for index, part in enumerate(path_parts):
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | _CLOEXEC,
                            dir_fd=current)
            descriptors.append(child)
            root = os.fstat(child)
            named_root = os.stat(part, dir_fd=current, follow_symlinks=False)
            is_checkout = index == len(path_parts) - 1
            allowed_modes = {0o700, 0o755} if is_checkout else {0o700, 0o750, 0o755}
            if ((root.st_dev, root.st_ino) != (named_root.st_dev, named_root.st_ino)
                    or not stat.S_ISDIR(root.st_mode)
                    or (root.st_uid != _OWNER_UID if is_checkout else root.st_uid not in {0, _OWNER_UID})
                    or (root.st_gid != _OWNER_GID if is_checkout else root.st_mode & 0o022 != 0)
                    or stat.S_IMODE(root.st_mode) not in allowed_modes
                    or os.get_inheritable(child)):
                raise RuntimeError("bws_preimport_reservation_refused")
            current = child
        scripts_fd = os.open("scripts", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | _CLOEXEC,
                             dir_fd=current)
        descriptors.append(scripts_fd)
        scripts_info = os.fstat(scripts_fd)
        scripts_named = os.stat("scripts", dir_fd=current, follow_symlinks=False)
        if ((scripts_info.st_dev, scripts_info.st_ino) != (scripts_named.st_dev, scripts_named.st_ino)
                or not stat.S_ISDIR(scripts_info.st_mode) or scripts_info.st_uid != _OWNER_UID
                or scripts_info.st_gid != _OWNER_GID
                or stat.S_IMODE(scripts_info.st_mode) not in {0o700, 0o755}
                or os.get_inheritable(scripts_fd)):
            raise RuntimeError("bws_preimport_reservation_refused")
        descriptor = os.open("postgres_deploy_service.py",
                             os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | _CLOEXEC,
                             dir_fd=scripts_fd)
        descriptors.append(descriptor)
        info = os.fstat(descriptor)
        named = os.stat("postgres_deploy_service.py", dir_fd=scripts_fd, follow_symlinks=False)
        if (not stat.S_ISDIR(root.st_mode) or root.st_uid != _OWNER_UID or root.st_gid != _OWNER_GID
                or stat.S_IMODE(root.st_mode) != binding["mode"] or root.st_dev != binding["device"]
                or root.st_ino != binding["inode"] or root.st_mode & 0o022
                or not stat.S_ISREG(info.st_mode) or info.st_uid != _OWNER_UID or info.st_gid != _OWNER_GID
                or info.st_mode & 0o022 or info.st_nlink != 1 or not 0 < info.st_size <= 2 * 1024 * 1024
                or os.get_inheritable(descriptor) or _stat_identity(info) != _stat_identity(named)):
            raise RuntimeError("bws_preimport_reservation_refused")
        raw = os.pread(descriptor, info.st_size + 1, 0)
        if (len(raw) != info.st_size or _stat_identity(os.fstat(descriptor)) != _stat_identity(info)
                or hashlib.sha256(raw).hexdigest() != binding["script_sha256"]):
            raise RuntimeError("bws_preimport_reservation_refused")
    except Exception:
        raise RuntimeError("bws_preimport_reservation_refused") from None
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)
    environment = {"PATH": "/usr/bin:/bin", "LC_ALL": "C", "GIT_CONFIG_NOSYSTEM": "1",
                   "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_OPTIONAL_LOCKS": "0",
                   "GIT_TERMINAL_PROMPT": "0", "GIT_NO_REPLACE_OBJECTS": "1"}
    commands = (
        ["git", "-c", "safe.directory=" + str(checkout), "-C", str(checkout), "rev-parse", "--show-toplevel"],
        ["git", "-c", "safe.directory=" + str(checkout), "-C", str(checkout), "rev-parse", "HEAD"],
        ["git", "-c", "safe.directory=" + str(checkout), "-C", str(checkout), "status", "--porcelain=v1",
         "--untracked-files=all", "--", *_CANDIDATE_CLEAN_PATHS],
    )
    try:
        results = [subprocess.run(command, env=environment, stdin=subprocess.DEVNULL,
                                  capture_output=True, check=False, timeout=20)
                   for command in commands]
        if (any(result.returncode != 0 or result.stderr for result in results)
                or Path(os.fsdecode(results[0].stdout.rstrip(b"\n"))) != checkout
                or results[1].stdout.rstrip(b"\n").decode("ascii") != binding["revision"]
                or results[2].stdout):
            raise RuntimeError("bws_preimport_reservation_refused")
    except Exception:
        raise RuntimeError("bws_preimport_reservation_refused") from None
    return str(checkout / "scripts" / "postgres_deploy_service.py")


def _require_live_installation_caller(caller: dict[str, object], channel: str) -> None:
    fixed_fields = {
        "pid", "uid", "gid", "start_time", "argv_sha256", "executable_sha256", "launcher_sha256",
    }
    checkout_fields = fixed_fields | {"candidate_sha", "source_checkout"}
    if (type(caller) is not dict or set(caller) not in (fixed_fields, checkout_fields)
            or any(type(caller[key]) is not int for key in ("pid", "uid", "gid", "start_time"))
            or caller["pid"] <= 0 or caller["pid"] == os.getpid()
            or caller["uid"] != _OWNER_UID or caller["gid"] != _OWNER_GID
            or caller["start_time"] <= 0
            or any(type(caller[key]) is not str or re.fullmatch(r"[0-9a-f]{64}", caller[key]) is None
                   for key in ("argv_sha256", "executable_sha256", "launcher_sha256"))
            or (set(caller) == checkout_fields and (type(caller["candidate_sha"]) is not str
                or re.fullmatch(r"[0-9a-f]{40}", caller["candidate_sha"]) is None))):
        raise RuntimeError("bws_preimport_reservation_refused")
    proc_root = process = None
    try:
        proc_root = os.open(_PROC, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | _CLOEXEC)
        process = os.open(str(caller["pid"]), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | _CLOEXEC,
                          dir_fd=proc_root)
        initial = os.fstat(process)
        first_stat = _read_proc_entry(process, "stat", 8192)
        first_command = _read_proc_entry(process, "cmdline", 65536)
        first_status = _read_proc_entry(process, "status", 65536)
        first_executable = os.stat("exe", dir_fd=process)
        second_stat = _read_proc_entry(process, "stat", 8192)
        second_command = _read_proc_entry(process, "cmdline", 65536)
        second_status = _read_proc_entry(process, "status", 65536)
        second_executable = os.stat("exe", dir_fd=process)
        named = os.stat(str(caller["pid"]), dir_fd=proc_root, follow_symlinks=False)
        if ((initial.st_dev, initial.st_ino) != (named.st_dev, named.st_ino)
                or first_stat != second_stat or first_command != second_command
                or first_status != second_status
                or _stat_identity(first_executable) != _stat_identity(second_executable)
                or not first_command.endswith(b"\0")):
            raise RuntimeError("bws_preimport_reservation_refused")
        closing = first_stat.rfind(b")")
        fields = first_stat[closing + 2:].split()
        if closing < 0 or len(fields) <= 19 or not fields[19].isdigit():
            raise RuntimeError("bws_preimport_reservation_refused")
        status = {}
        for line in first_status.splitlines():
            if line.startswith((b"Uid:\t", b"Gid:\t")):
                key, raw_values = line.split(b":", 1)
                values = raw_values.split()
                if len(values) < 2 or any(not item.isdigit() for item in values[:2]):
                    raise RuntimeError("bws_preimport_reservation_refused")
                status[key] = tuple(int(item) for item in values[:2])
        caller_script = _verify_caller_checkout(caller)
        expected_script = str(_FIXED_LAUNCHER) if caller_script is None else caller_script
        expected_command = b"\0".join(os.fsencode(item) for item in (
            str(_FIXED_RUNTIME), expected_script, "rpc", channel,
        )) + b"\0"
        executable = os.stat(_FIXED_RUNTIME)
        if (first_command != expected_command or status.get(b"Uid", (None, None))[1] != caller["uid"]
                or status.get(b"Gid", (None, None))[1] != caller["gid"]
                or int(fields[19]) != caller["start_time"]
                or hashlib.sha256(first_command).hexdigest() != caller["argv_sha256"]
                or hashlib.sha256(json.dumps(_stat_identity(first_executable), separators=(",", ":"))
                                  .encode("ascii")).hexdigest() != caller["executable_sha256"]
                or _stat_identity(first_executable) != _stat_identity(executable)
                or not stat.S_ISREG(executable.st_mode) or executable.st_uid != _OWNER_UID
                or executable.st_gid != _OWNER_GID or executable.st_mode & 0o022
                or not executable.st_mode & 0o111):
            raise RuntimeError("bws_preimport_reservation_refused")
    except Exception:
        raise RuntimeError("bws_preimport_reservation_refused") from None
    finally:
        for descriptor in (process, proc_root):
            if descriptor is not None:
                os.close(descriptor)


def _require_exclusive_lock(descriptor: int, identity: tuple[int, int]) -> None:
    info = os.fstat(descriptor)
    if ((info.st_dev, info.st_ino) != identity or os.pread(descriptor, 1, 0)
            or os.get_inheritable(descriptor)):
        raise RuntimeError("bws_preimport_reservation_refused")
    try:
        fcntl.flock(descriptor, fcntl.LOCK_SH | fcntl.LOCK_NB)
    except OSError as exc:
        if exc.errno not in {errno.EACCES, errno.EAGAIN}:
            raise RuntimeError("bws_preimport_reservation_refused") from None
    else:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        raise RuntimeError("bws_preimport_reservation_refused")


def _require_active_channel_owner(parent: int, channel: str, owner_raw: bytes) -> None:
    name = f"{channel}.source-installation.lock"
    descriptor = None
    try:
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | _CLOEXEC,
                             dir_fd=parent)
        info = os.fstat(descriptor)
        named = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if ((info.st_dev, info.st_ino) != (named.st_dev, named.st_ino)
                or not stat.S_ISREG(info.st_mode) or info.st_uid != _OWNER_UID or info.st_gid != _OWNER_GID
                or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1
                or os.get_inheritable(descriptor) or os.pread(descriptor, 4097, 0) != owner_raw):
            raise RuntimeError("bws_preimport_reservation_refused")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno not in {errno.EACCES, errno.EAGAIN}:
                raise RuntimeError("bws_preimport_reservation_refused") from None
        else:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            raise RuntimeError("bws_preimport_reservation_refused")
        current = os.fstat(descriptor)
        named_after = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if ((current.st_dev, current.st_ino) != (info.st_dev, info.st_ino)
                or (named_after.st_dev, named_after.st_ino) != (info.st_dev, info.st_ino)
                or os.pread(descriptor, 4097, 0) != owner_raw):
            raise RuntimeError("bws_preimport_reservation_refused")
    except Exception:
        raise RuntimeError("bws_preimport_reservation_refused") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _consume_start_authorization(
    parent: int, channel: str, global_fd: int, global_identity: tuple[int, int], owner_raw: bytes,
) -> None:
    owner = json.loads(owner_raw, object_pairs_hook=_unique_json_object)
    caller = owner["caller"]
    _require_live_installation_caller(caller, channel)
    _require_exclusive_lock(global_fd, global_identity)
    _require_active_channel_owner(parent, channel, owner_raw)
    receipt_name = f"bws-source-installation-{owner['operation_id']}.receipt.json"
    try:
        os.stat(receipt_name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        pass
    else:
        raise RuntimeError("bws_preimport_reservation_refused")
    name = f"{channel}.source-installation-start.json"
    descriptor = None
    try:
        descriptor = os.open(name, os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK | _CLOEXEC,
                             dir_fd=parent)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise RuntimeError("bws_preimport_reservation_refused") from None
        info = os.fstat(descriptor)
        named = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != _OWNER_UID or info.st_gid != _OWNER_GID
                or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1
                or (info.st_dev, info.st_ino) != (named.st_dev, named.st_ino)
                or not 0 < info.st_size <= 4096 or os.get_inheritable(descriptor)):
            raise RuntimeError("bws_preimport_reservation_refused")
        raw = os.pread(descriptor, info.st_size + 1, 0)
        after = os.fstat(descriptor)
        named_after = os.stat(name, dir_fd=parent, follow_symlinks=False)
        version = lambda value: (value.st_dev, value.st_ino, value.st_uid, value.st_gid, value.st_mode,
                                 value.st_nlink, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
        if (len(raw) != info.st_size or version(after) != version(info)
                or version(named_after) != version(info)):
            raise RuntimeError("bws_preimport_reservation_refused")
        permit = json.loads(raw, object_pairs_hook=_unique_json_object)
        if (type(permit) is not dict
                or set(permit) != {"schema", "operation_id", "channel", "candidate_sha", "image_digest",
                                   "phase", "generation_sha256", "caller"}
                or permit["schema"] != _START_AUTHORIZATION_SCHEMA
                or any(permit[key] != owner[key] for key in (
                    "operation_id", "channel", "candidate_sha", "image_digest", "caller",
                ))
                or permit["phase"] not in {"candidate", "restored-old"}
                or type(permit["generation_sha256"]) is not str
                or re.fullmatch(r"[0-9a-f]{64}", permit["generation_sha256"]) is None):
            raise RuntimeError("bws_preimport_reservation_refused")
        if (_read_installation_owner(parent, channel) != owner_raw):
            raise RuntimeError("bws_preimport_reservation_refused")
        _require_live_installation_caller(caller, channel)
        _require_exclusive_lock(global_fd, global_identity)
        _require_active_channel_owner(parent, channel, owner_raw)
        os.unlink(name, dir_fd=parent)
        os.fsync(parent)
        try:
            os.stat(name, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            return
        raise RuntimeError("bws_preimport_reservation_refused")
    except Exception:
        raise RuntimeError("bws_preimport_reservation_refused") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _unique_json_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = item
    return value


def _preimport_reservation(channel: str, action: str) -> _PreimportReservation:
    """Reserve imports, or skip cleanup without writes when state is uncertain/busy."""
    if channel == "prod":
        return _PreimportReservation(None)
    if channel not in {"dev", "test"} or os.geteuid() != _OWNER_UID or os.getegid() != _OWNER_GID:
        raise RuntimeError("bws_preimport_reservation_refused")
    cleanup = action == "cleanup"
    try:
        # ExecStopPost must never create its own admission state. Missing or
        # untrusted state selects the no-write cleanup path.
        parent = _runtime_directory_fd(create=not cleanup)
    except Exception:
        if cleanup:
            return _PreimportReservation(None, skip_cleanup=True)
        raise RuntimeError("bws_preimport_reservation_refused") from None
    descriptor = None
    try:
        flags = os.O_RDONLY if cleanup else os.O_RDWR | os.O_CREAT
        flags |= os.O_NOFOLLOW | os.O_NONBLOCK | _CLOEXEC
        try:
            descriptor = os.open(_GLOBAL_LOCK_NAME, flags, 0o600, dir_fd=parent)
        except Exception:
            if cleanup:
                return _PreimportReservation(None, skip_cleanup=True)
            raise
        info = os.fstat(descriptor)
        named = os.stat(_GLOBAL_LOCK_NAME, dir_fd=parent, follow_symlinks=False)
        if ((info.st_dev, info.st_ino) != (named.st_dev, named.st_ino)
                or not stat.S_ISREG(info.st_mode) or info.st_uid != _OWNER_UID or info.st_gid != _OWNER_GID
                or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1
                or os.get_inheritable(descriptor) or os.pread(descriptor, 1, 0)):
            raise RuntimeError("bws_preimport_reservation_refused")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except OSError as exc:
            if cleanup:
                return _PreimportReservation(None, skip_cleanup=True)
            if exc.errno not in {errno.EACCES, errno.EAGAIN} or action != "serve":
                raise RuntimeError("bws_preimport_reservation_refused") from None
            owner_before = _read_installation_owner(parent, channel)
            try:
                fcntl.flock(descriptor, fcntl.LOCK_SH | fcntl.LOCK_NB)
            except OSError as retry:
                if retry.errno not in {errno.EACCES, errno.EAGAIN}:
                    raise RuntimeError("bws_preimport_reservation_refused") from None
                if (_read_installation_owner(parent, channel) != owner_before
                        or os.pread(descriptor, 1, 0)):
                    raise RuntimeError("bws_preimport_reservation_refused")
                global_identity = (info.st_dev, info.st_ino)
                _consume_start_authorization(parent, channel, descriptor, global_identity, owner_before)
                if ((os.fstat(descriptor).st_dev, os.fstat(descriptor).st_ino) != global_identity
                        or (os.stat(_GLOBAL_LOCK_NAME, dir_fd=parent, follow_symlinks=False).st_dev,
                            os.stat(_GLOBAL_LOCK_NAME, dir_fd=parent, follow_symlinks=False).st_ino)
                        != global_identity
                        or os.pread(descriptor, 1, 0)
                        or _read_installation_owner(parent, channel) != owner_before):
                    raise RuntimeError("bws_preimport_reservation_refused")
                os.close(descriptor)
                descriptor = None
                return _PreimportReservation(None, authorized_start=True)
        if ((os.fstat(descriptor).st_dev, os.fstat(descriptor).st_ino)
                != (info.st_dev, info.st_ino)
                or (os.stat(_GLOBAL_LOCK_NAME, dir_fd=parent, follow_symlinks=False).st_dev,
                    os.stat(_GLOBAL_LOCK_NAME, dir_fd=parent, follow_symlinks=False).st_ino)
                != (info.st_dev, info.st_ino)
                or os.pread(descriptor, 1, 0)):
            raise RuntimeError("bws_preimport_reservation_refused")
        result, descriptor = descriptor, None
        return _PreimportReservation(result)
    except Exception:
        if cleanup:
            return _PreimportReservation(None, skip_cleanup=True)
        raise RuntimeError("bws_preimport_reservation_refused") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(parent)


def _source_installation_request(raw: str) -> bool:
    try:
        request = json.loads(raw, object_pairs_hook=_unique_json_object)
        return (type(request) is dict
                and set(request) == {"action", "operation_id", "candidate_sha", "image_digest", "bundle_name"}
                and request["action"] == "source-installation"
                and type(request["operation_id"]) is str
                and str(UUID(request["operation_id"])) == request["operation_id"]
                and type(request["candidate_sha"]) is str
                and re.fullmatch(r"[0-9a-f]{40}", request["candidate_sha"]) is not None
                and type(request["image_digest"]) is str
                and re.fullmatch(r"sha256:[0-9a-f]{64}", request["image_digest"]) is not None
                and type(request["bundle_name"]) is str
                and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", request["bundle_name"]) is not None)
    except Exception:
        return False


def _source_installation_recovery_request(raw: str) -> bool:
    """Recognize the read-only same-operation recovery request before imports."""
    try:
        request = json.loads(raw, object_pairs_hook=_unique_json_object)
        return (type(request) is dict
                and set(request) == {"action", "operation_id", "candidate_sha", "image_digest", "bundle_name"}
                and request["action"] == "source-installation-reconcile"
                and type(request["operation_id"]) is str
                and str(UUID(request["operation_id"])) == request["operation_id"]
                and type(request["candidate_sha"]) is str
                and re.fullmatch(r"[0-9a-f]{40}", request["candidate_sha"]) is not None
                and type(request["image_digest"]) is str
                and re.fullmatch(r"sha256:[0-9a-f]{64}", request["image_digest"]) is not None
                and type(request["bundle_name"]) is str
                and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", request["bundle_name"]) is not None)
    except Exception:
        return False


def _candidate_checkout_root(candidate_sha: str) -> Path:
    """Accept only the clean exact checkout that launched this rpc process."""
    try:
        script = Path(__file__).resolve(strict=True)
        root = script.parent.parent
        if (script != root / "scripts" / "postgres_deploy_service.py"
                or not re.fullmatch(r"[0-9a-f]{40}", candidate_sha)):
            raise RuntimeError("bws_candidate_checkout_refused")
        info = os.stat(root, follow_symlinks=False)
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != _OWNER_UID or info.st_gid != _OWNER_GID
                or info.st_mode & 0o022):
            raise RuntimeError("bws_candidate_checkout_refused")
        environment = {
            "PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C",
            "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0",
            "GIT_NO_REPLACE_OBJECTS": "1",
        }
        commands = (
            ["git", "-c", "safe.directory=" + str(root), "-C", str(root), "rev-parse", "--show-toplevel"],
            ["git", "-c", "safe.directory=" + str(root), "-C", str(root), "rev-parse", "HEAD"],
            ["git", "-c", "safe.directory=" + str(root), "-C", str(root), "status", "--porcelain=v1",
             "--untracked-files=all", "--", *_CANDIDATE_CLEAN_PATHS],
        )
        results = [subprocess.run(command, env=environment, stdin=subprocess.DEVNULL, capture_output=True,
                                  check=False, timeout=20) for command in commands]
        if (any(result.returncode != 0 or result.stderr for result in results)
                or Path(os.fsdecode(results[0].stdout.rstrip(b"\n"))) != root
                or results[1].stdout.rstrip(b"\n").decode("ascii") != candidate_sha
                or results[2].stdout):
            raise RuntimeError("bws_candidate_checkout_refused")
        return root
    except Exception:
        raise RuntimeError("bws_candidate_checkout_refused") from None


def _candidate_launcher_binding(root: Path, candidate_sha: str) -> tuple[dict[str, str], bytes]:
    """Read the fixed launcher blob from the exact candidate tree without executing it."""
    try:
        if (not root.is_absolute() or re.fullmatch(r"[0-9a-f]{40}", candidate_sha) is None):
            raise RuntimeError("bws_candidate_checkout_refused")
        environment = {
            "PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C",
            "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0",
            "GIT_NO_REPLACE_OBJECTS": "1",
        }
        safe = "safe.directory=" + str(root)
        listing = subprocess.run(
            ["git", "-c", safe, "-C", str(root), "ls-tree", "-z", candidate_sha,
             "--", "scripts/postgres_deploy_service.py"],
            env=environment, stdin=subprocess.DEVNULL, capture_output=True,
            check=False, timeout=20,
        )
        records = listing.stdout.split(b"\0") if listing.stdout.endswith(b"\0") else []
        if listing.returncode != 0 or listing.stderr or len(records) != 2 or records[1] != b"":
            raise RuntimeError("bws_candidate_checkout_refused")
        header, separator, path = records[0].partition(b"\t")
        fields = header.split()
        if (not separator or path != b"scripts/postgres_deploy_service.py" or len(fields) != 3
                or fields[0] != b"100755" or fields[1] != b"blob"
                or re.fullmatch(rb"[0-9a-f]{40}", fields[2]) is None):
            raise RuntimeError("bws_candidate_checkout_refused")
        blob = subprocess.run(
            ["git", "-c", safe, "-C", str(root), "cat-file", "blob", fields[2].decode("ascii")],
            env=environment, stdin=subprocess.DEVNULL, capture_output=True,
            check=False, timeout=20,
        )
        source = blob.stdout
        if blob.returncode != 0 or blob.stderr or not 0 < len(source) <= 2 * 1024 * 1024:
            raise RuntimeError("bws_candidate_checkout_refused")
        return {
            "candidate_sha": candidate_sha,
            "checkout": str(root),
            "script_sha256": hashlib.sha256(source).hexdigest(),
        }, source
    except Exception:
        raise RuntimeError("bws_candidate_checkout_refused") from None


def _execute_verified_candidate_entrypoint(
    binding: dict[str, str], source: bytes, request_raw: str, arguments: list[str],
) -> None:
    """Run the exact verified Git blob as the RPC entrypoint before importing app code."""
    root = Path(binding["checkout"])
    script = root / "scripts" / "postgres_deploy_service.py"
    if (set(binding) != {"candidate_sha", "checkout", "script_sha256"}
            or binding["checkout"] != str(root) or not root.is_absolute()
            or re.fullmatch(r"[0-9a-f]{40}", binding["candidate_sha"]) is None
            or re.fullmatch(r"[0-9a-f]{64}", binding["script_sha256"]) is None
            or hashlib.sha256(source).hexdigest() != binding["script_sha256"]
            or arguments != ["rpc", "dev"] and arguments != ["rpc", "test"]
            or hasattr(sys, _VERIFIED_CANDIDATE_ENTRYPOINT)):
        raise RuntimeError("bws_candidate_checkout_refused")
    previous_argv, previous_stdin = sys.argv, sys.stdin
    namespace = {
        "__name__": "__main__", "__file__": str(script), "__package__": None,
        "__loader__": None, "__spec__": None, "__cached__": None,
        "__builtins__": __builtins__,
    }
    setattr(sys, _VERIFIED_CANDIDATE_ENTRYPOINT, dict(binding))
    sys.argv = [str(script), *arguments]
    sys.stdin = io.StringIO(request_raw)
    try:
        code = compile(source, str(script), "exec", dont_inherit=True)
        exec(code, namespace, namespace)
    finally:
        sys.argv, sys.stdin = previous_argv, previous_stdin
        if hasattr(sys, _VERIFIED_CANDIDATE_ENTRYPOINT):
            delattr(sys, _VERIFIED_CANDIDATE_ENTRYPOINT)


def _dispatch(root: Path, channel: str, arguments: list[str], *, caller_checkout: Path | None = None) -> int:
    """Import the fixed app entrypoint only after reserving its source generation."""
    action = arguments[0]
    previous_stdin = sys.stdin
    prefetched_raw = None
    source_recovery = False
    if action == "rpc":
        prefetched_raw = sys.stdin.read(65537)
        if len(prefetched_raw) > 65536:
            sys.stdin = previous_stdin
            return 78
        sys.stdin = io.StringIO(prefetched_raw)
        source_recovery = channel in {"dev", "test"} and _source_installation_recovery_request(prefetched_raw)
    try:
        reservation = _preimport_reservation(channel, action)
    except RuntimeError:
        if source_recovery:
            # A live source installer owns the global lock.  Recovery is a
            # bounded read-only query and must report unresolved without
            # importing or competing with that transaction.
            print(json.dumps({
                "source_installation": {"status": "unresolved", "reason": "global_lock_active"},
            }, sort_keys=True))
            sys.stdin = previous_stdin
            return 0
        sys.stdin = previous_stdin
        raise
    source_finder = None
    source_installation = False
    source_root = root
    try:
        if reservation.skip_cleanup:
            return 0
        if action == "rpc":
            raw = prefetched_raw if prefetched_raw is not None else sys.stdin.read(65537)
            if len(raw) > 65536:
                return 78
            sys.stdin = io.StringIO(raw)
            source_installation = channel in {"dev", "test"} and _source_installation_request(raw)
            if source_installation:
                request = json.loads(raw, object_pairs_hook=_unique_json_object)
                selected_root = _candidate_checkout_root(request["candidate_sha"])
                if caller_checkout is None or selected_root != caller_checkout:
                    raise RuntimeError("bws_candidate_checkout_refused")
                binding, candidate_source = _candidate_launcher_binding(
                    selected_root, request["candidate_sha"],
                )
                verified_entrypoint = getattr(sys, _VERIFIED_CANDIDATE_ENTRYPOINT, None)
                if verified_entrypoint is None:
                    # A process may have been started from an older checkout and
                    # waited on stdin while that path advanced. Replace its
                    # untrusted entrypoint with the exact, already-verified Git
                    # blob before importing any candidate app module.
                    reservation.release()
                    _execute_verified_candidate_entrypoint(binding, candidate_source, raw, arguments)
                    return 78
                if verified_entrypoint != binding:
                    raise RuntimeError("bws_candidate_checkout_refused")
                source_root = selected_root
                sys._yggdrasil_bws_candidate_checkout = str(source_root)
                sys.path.insert(0, str(source_root))
        source_finder = _install_source_loader(source_root)
        if source_installation or source_recovery:
            import importlib
            importlib.import_module("app.ops.bws_installation_transaction")
            importlib.import_module("app.ops.bws_installation_admission")
        elif action in {"cleanup", "serve"} and channel in {"dev", "test"}:
            import importlib
            admission = importlib.import_module("app.ops.bws_installation_admission")
            if action == "serve" and not reservation.authorized_start:
                # A normal restart may import only after both persistent owner
                # markers are terminal under the shared caller reservation.
                with admission.shared_caller_reservation(channel):
                    pass
        from app.ops.postgres_deploy_linux import main
        if source_installation or source_recovery or (action == "cleanup" and channel in {"dev", "test"}):
            reservation.release()
        if action == "serve":
            setattr(sys, _STARTUP_RELEASE_ATTRIBUTE, reservation.release)
        return main(arguments)
    finally:
        reservation.release()
        if source_finder is not None and source_finder in sys.meta_path:
            sys.meta_path.remove(source_finder)
        if action == "serve" and hasattr(sys, _STARTUP_RELEASE_ATTRIBUTE):
            delattr(sys, _STARTUP_RELEASE_ATTRIBUTE)
        if source_installation and hasattr(sys, "_yggdrasil_bws_candidate_checkout"):
            delattr(sys, "_yggdrasil_bws_candidate_checkout")
        sys.stdin = previous_stdin


def _install_source_loader(root: Path):
    """Compile owned application modules from stable source reads and retain each hash."""
    import hashlib
    import importlib.machinery

    root = Path(os.path.abspath(root))

    class SourceBoundLoader(importlib.machinery.SourceFileLoader):
        def get_code(self, fullname):
            descriptor = None
            try:
                descriptor = os.open(
                    self.path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0),
                )
                before = os.fstat(descriptor)
                named_before = os.stat(self.path, follow_symlinks=False)
                if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                        or not 0 <= before.st_size <= _MAX_SOURCE_BYTES
                        or (before.st_dev, before.st_ino) != (named_before.st_dev, named_before.st_ino)
                        or os.get_inheritable(descriptor)):
                    raise ImportError("BWS source provenance unavailable")
                chunks = bytearray()
                while len(chunks) <= _MAX_SOURCE_BYTES:
                    chunk = os.read(descriptor, min(65536, _MAX_SOURCE_BYTES + 1 - len(chunks)))
                    if not chunk:
                        break
                    chunks.extend(chunk)
                after = os.fstat(descriptor)
                named_after = os.stat(self.path, follow_symlinks=False)
                version = lambda info: (info.st_dev, info.st_ino, info.st_mode, info.st_nlink,
                                        info.st_size, info.st_mtime_ns, info.st_ctime_ns)
                if (len(chunks) != before.st_size or version(after) != version(before)
                        or (named_after.st_dev, named_after.st_ino) != (before.st_dev, before.st_ino)):
                    raise ImportError("BWS source provenance unavailable")
                source = bytes(chunks)
            except ImportError:
                raise
            except Exception as exc:
                raise ImportError("BWS source provenance unavailable") from exc
            finally:
                if descriptor is not None:
                    os.close(descriptor)
            self.loaded_source_sha256 = hashlib.sha256(source).hexdigest()
            return self.source_to_code(source, self.path)

        def exec_module(self, module):
            code = self.get_code(module.__name__)
            source_sha256 = getattr(self, "loaded_source_sha256", None)
            if (type(source_sha256) is not str or len(source_sha256) != 64
                    or any(character not in "0123456789abcdef" for character in source_sha256)):
                raise ImportError("BWS source provenance unavailable")
            exec(code, module.__dict__)
            module.__dict__[_SOURCE_HASH_ATTRIBUTE] = source_sha256

    class SourceBoundFinder:
        def find_spec(self, fullname, path=None, target=None):
            package = fullname.partition(".")[0]
            if package not in _SOURCE_PACKAGES:
                return None
            spec = importlib.machinery.PathFinder.find_spec(fullname, path, target)
            if spec is None:
                raise ImportError("BWS source provenance unavailable")
            if spec.loader is None and spec.submodule_search_locations is not None:
                locations = tuple(Path(os.path.abspath(item)) for item in spec.submodule_search_locations)
                if fullname in _SOURCE_PACKAGES and locations == (root / package,):
                    return spec
                raise ImportError("BWS source provenance unavailable")
            if not isinstance(spec.loader, importlib.machinery.SourceFileLoader):
                raise ImportError("BWS source provenance unavailable")
            try:
                origin = Path(os.path.abspath(spec.origin))
                relative = origin.relative_to(root)
            except Exception as exc:
                raise ImportError("BWS source provenance unavailable") from exc
            if not relative.parts or relative.parts[0] != package:
                raise ImportError("BWS source provenance unavailable")
            spec.loader = SourceBoundLoader(fullname, str(origin))
            return spec

    finder = SourceBoundFinder()
    sys.meta_path.insert(2, finder)
    return finder


def run() -> int:
    try:
        action_counts = {
            'serve': 3,
            'rpc': 3,
            'guard': 3,
            'cleanup': 3,
            'token-push-inspect': 3,
            'token-push-status': 4,
            'token-push-worker': 5,
            'token-push': 6,
            'karakeep-boot': 3,
            'karakeep-acquire': 3,
            'karakeep-project': 3,
            'qualify-heavy': 4,
        }
        if (
            len(sys.argv) != action_counts.get(sys.argv[1], -1)
            or sys.argv[2] not in {'dev', 'test', 'prod'}
            or (sys.argv[1] in {'karakeep-acquire', 'karakeep-project'} and sys.argv[2] != 'test')
        ):
            return 78
        path = Path('/etc/yggdrasil/bws-deploy') / (sys.argv[2] + '.json')
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor) as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o600:
                return 78
            root = Path(json.load(source)['root'])
        if not root.is_absolute() or root.is_symlink() or root.stat().st_uid != 0 or root.stat().st_mode & 0o022:
            return 78
        os.chdir(root)
        sys.path.insert(0, str(root))
        # Ignore every source-tree bytecode cache so restart admission binds
        # the bytes that were installed, including unchecked-hash pyc files.
        sys.pycache_prefix = "/dev/null"
        sys.dont_write_bytecode = True
        caller_checkout = Path(__file__).resolve().parent.parent
        return _dispatch(root, sys.argv[2], sys.argv[1:], caller_checkout=caller_checkout)
    except Exception:
        return 78


if __name__ == '__main__':
    raise SystemExit(run())
