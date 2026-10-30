"""One finite, host-local production probe source upgrade operation.

The carrier sends this module over the existing strict SSH path with a frozen
packet and source bytes.  It is intentionally a one-off operation: there is no
generic service/deployment interface, arbitrary path selector, or retry loop.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import grp
import pwd
import re
import selectors
import signal
import stat
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from typing import Any, Callable

from probe_script_swap_core import SwapFailure, swap_script


ISSUE = 6457
PARENT_ISSUE = 4076
SOURCE_MERGE = "0d064c012296589e92987c1f374fa18b05104f7b"
OLD_SCRIPT_SHA256 = "bde4a4d8b57baaba998b1ac8a5158551f0b0ee52b9a89bb2ecec7bef1ab1750b"
NEW_SCRIPT_SHA256 = "0172b37565a067c26acd37afed8d650be7a56117ad1962860446fd18353058ac"
CONFIG_SHA256 = "b405567652687759d285cd4ffb9e5aed32e5124476c6e427cb4d10ce70b16e75"
UNIT_SHA256 = "c9aa169c8cec7f5e85bcea94115236fc2d2e159060b39f4da085ff318b325332"
ENGINE_SHA256 = "b697f62f732a1c2ad27b7da3df386ecb8935f19964b0f3b0107dfb3b087f97e6"
MANIFEST_SHA256 = "3ae600b78abefb751ef8fd73e7639b75a41b09f30d44fd4d06b1bb77101ae861"

# A second, fixed transition. These bindings do not grant installation authority.
RENDERING_SOURCE_MERGE = "7436ca29b863fca98faeb8e729d00e9832a71c22"
RENDERING_SCRIPT_SHA256 = "17c2dced67a7830e453f4bf5d18e1e330086dab186501b80b259f569936c8e90"
RENDERING_MANIFEST_SHA256 = "317f99b147d23dcf20c3e59be2d542cd9f3f74aeca98d519ba2393a9eab3a635"
RENDERING_SOURCE_ISSUE = 6475
RENDERING_SOURCE_BODY_SHA256 = "aa7d08590ecf9da897575e3e77a6d6be34c4020bd12a223a4ef8619749f8954c"
RENDERING_INSTALLATION_ISSUE = 6476
RENDERING_INSTALLATION_BODY_SHA256 = (
    "7ef11ac405db559eec87c507c11eab13bf794a8421d6cd13e0aec98bcaa8ae1c"
)
ORIGINAL_OPERATION = "5b47bef8b0a64b12a2ffd7109d2b6209"
ORIGINAL_REQUEST_SHA256 = "762b7c69e6059b5c1caba0145be0d0ede0b357e09776261720be56d9b5c2cfa5"
ORIGINAL_FILE_SHA256 = {
    "request.json": ORIGINAL_REQUEST_SHA256,
    "handle.json": "c4070ed1c9fe21b811aeeb82a84e0823f8f7591310a5f24ec041ef3bb5457642",
    "phase.json": "979394c5c039928dc4d7b100c135a7f9ddababe7f634f90b9754dcdf64c48c3d",
    "result.json": "98f01e864c4671decd0a7c0ae0624b39cfb333d378b60fe626d9b01a78d9e6de",
    "go.json": "4efbe2de4f14250e3c151b8f62e8a93417d350e90fabdaddd74fbf4fcfc3de3d",
    "probe_script_swap_core.py": "47127117c9f3ba8fa2f7def8ecc026e3f91d2e1fdf05d47b6d7a12f443b8e7a3",
    "probe_upgrade_operation.py": "425fa0291e0162fee9b6cc11d407e0e0851267ec87d2df155d0f4a1de6ec7bac",
    "worker.py": "fe1217e7a5f5874aa3256876016d80d6b5353314b110cb1b3b7fe690d3367c3e",
}

PACKAGE = Path("/opt/yggdrasil/host-probe")
SCRIPT = PACKAGE / "ops/host-setup/mac-mini/prod_probe.py"
CONFIG = Path("/etc/yggdrasil/host-probe/prod.env")
TEMPLATE = Path("/etc/systemd/system/yggdrasil-host-probe@.service")
INCIDENT = Path("/var/lib/yggdrasil-host-probe-prod/alert-state.json")
UNIT = "yggdrasil-host-probe@prod.service"
INTERPRETER = Path("/opt/yggdrasil/bws-deploy-runtime/bin/python3")
SCRIPT_REL = "ops/host-setup/mac-mini/prod_probe.py"
MAX_FILE_BYTES = 1_048_576
EXPECTED_UID = 0
EXPECTED_GID = 0
PROC_ROOT = Path("/proc")
CGROUP_ROOT = Path("/sys/fs/cgroup")
OPERATION_ROOT = Path("/var/lib/yggdrasil-probe-upgrade-6457")
RUNTIME_DIRECTORY = Path("/run/yggdrasil-host-probe-prod")
RUNTIME_SECONDS = 420
BODY_SHA256 = "f896151b723a1d85ef5cc11e1543404d29d4d687d00c1113128aaaec9f8ef1fb"
CHILD_CODE = (
    "import sys; sys.path.insert(0, sys.argv[1]); "
    "import prod_probe; prod_probe._http_get_child()"
)
BEFORE_IMPORT_CODE = "import sys; sys.path.insert(0, sys.argv[1]); import prod_probe"
UNIT_KEYS = (
    "LoadState,ActiveState,SubState,UnitFileState,MainPID,NRestarts,FragmentPath,"
    "DropInPaths,User,Group,WorkingDirectory,ExecStart,EnvironmentFiles,"
    "InvocationID,ControlGroup,Job,KillMode,Restart,TimeoutStopUSec,"
    "NeedDaemonReload,ProtectSystem,ReadWritePaths,ExecMainStartTimestampMonotonic,"
    "InactiveEnterTimestampMonotonic,Result,StandardOutput,StandardError"
)
OUTCOME_MARKERS = (
    "probe ok:",
    "probe-down alert sent",
    "probe-down detected but outage already recorded",
    "probe-recovered alert sent",
)
PRIMARY_OUTCOME_MARKERS = OUTCOME_MARKERS[:3]


class OperationFailure(Exception):
    def __init__(self, reason: str, *, unknown: bool = False):
        super().__init__(reason)
        self.reason = reason
        self.unknown = unknown


def _signature(meta: os.stat_result) -> tuple[int, ...]:
    return (
        meta.st_dev,
        meta.st_ino,
        meta.st_mode,
        meta.st_uid,
        meta.st_gid,
        meta.st_nlink,
        meta.st_size,
        meta.st_mtime_ns,
        meta.st_ctime_ns,
    )


def _open_directory(path: Path) -> int:
    if not path.is_absolute() or ".." in path.parts:
        raise OperationFailure("directory_path")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC
    descriptor = os.open("/", flags)
    try:
        for part in path.parts[1:]:
            next_descriptor = os.open(
                part,
                flags | os.O_NOFOLLOW,
                dir_fd=descriptor,
            )
            os.close(descriptor)
            descriptor = next_descriptor
            info = os.fstat(descriptor)
            mode = stat.S_IMODE(info.st_mode)
            if (
                info.st_uid != EXPECTED_UID
                or info.st_gid != EXPECTED_GID
                or mode & 0o002
                or (mode & 0o020 and info.st_gid != EXPECTED_GID)
            ):
                raise OperationFailure("directory_metadata")
            list_attributes = getattr(os, "listxattr", None)
            if callable(list_attributes) and {
                "system.posix_acl_access",
                "system.posix_acl_default",
            }.intersection(list_attributes(descriptor)):
                raise OperationFailure("directory_acl_write_domain")
        return descriptor
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise


def _read_bounded(path: Path, limit: int = MAX_FILE_BYTES, *, mode: int | None = None) -> bytes:
    parent = _open_directory(path.parent)
    descriptor: int | None = None
    try:
        descriptor = os.open(
            path.name,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
            dir_fd=parent,
        )
        before = os.fstat(descriptor)
        permissions = stat.S_IMODE(before.st_mode)
        if not (
            stat.S_ISREG(before.st_mode)
            and before.st_uid == EXPECTED_UID
            and before.st_gid == EXPECTED_GID
            and before.st_nlink == 1
            and before.st_size <= limit
            and not permissions & 0o002
            and (not permissions & 0o020 or before.st_gid == EXPECTED_GID)
            and (mode is None or permissions == mode)
        ):
            raise OperationFailure("file_metadata")
        chunks: list[bytes] = []
        size = 0
        while True:
            block = os.read(descriptor, min(65_536, limit + 1 - size))
            if not block:
                break
            chunks.append(block)
            size += len(block)
            if size > limit:
                raise OperationFailure("file_bound")
        after = os.fstat(descriptor)
        slot = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
        if (
            size != before.st_size
            or _signature(before) != _signature(after)
            or _signature(slot) != _signature(before)
        ):
            raise OperationFailure("file_changed")
        return b"".join(chunks)
    except FileNotFoundError:
        raise
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(parent)


def _bounded_process(
    argv: list[str],
    *,
    timeout: float,
    limit: int,
    environment: dict[str, str],
    input_bytes: bytes = b"",
) -> subprocess.CompletedProcess[bytes]:
    """Drain private pipes with an enforced allocation/deadline bound and reap."""
    process = subprocess.Popen(
        argv,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
        start_new_session=True,
    )
    selector = None
    try:
        assert process.stdin and process.stdout and process.stderr
        streams = (process.stdin, process.stdout, process.stderr)
        stream_by_descriptor = {stream.fileno(): stream for stream in streams}
        selector = selectors.DefaultSelector()
        output = {"stdout": bytearray(), "stderr": bytearray()}
        pending = memoryview(input_bytes)
        deadline = time.monotonic() + timeout
        for stream in streams:
            os.set_blocking(stream.fileno(), False)
        if pending:
            selector.register(process.stdin, selectors.EVENT_WRITE, "stdin")
        else:
            process.stdin.close()
        selector.register(process.stdout, selectors.EVENT_READ, "stdout")
        selector.register(process.stderr, selectors.EVENT_READ, "stderr")
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise OperationFailure("process_deadline", unknown=True)
            for key, _ in selector.select(min(remaining, 0.2)):
                if key.data == "stdin":
                    try:
                        written = os.write(key.fd, pending[:65_536])
                    except BrokenPipeError:
                        pending = memoryview(b"")
                    else:
                        pending = pending[written:]
                    if not pending:
                        selector.unregister(key.fileobj)
                        stream_by_descriptor[key.fd].close()
                else:
                    block = os.read(key.fd, min(65_536, limit + 1))
                    if not block:
                        selector.unregister(key.fileobj)
                        stream_by_descriptor[key.fd].close()
                    else:
                        output[key.data].extend(block)
                        if len(output["stdout"]) + len(output["stderr"]) > limit:
                            raise OperationFailure("process_output_bound", unknown=True)
        process.wait(timeout=max(0.01, deadline - time.monotonic()))
        return subprocess.CompletedProcess(
            argv, process.returncode, bytes(output["stdout"]), bytes(output["stderr"])
        )
    except BaseException:
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        try:
            process.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            raise OperationFailure("process_reap_unknown", unknown=True) from None
        raise
    finally:
        try:
            if selector is not None:
                selector.close()
        finally:
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None:
                    stream.close()


def _safe_command(
    argv: list[str],
    *,
    timeout: float = 15.0,
    limit: int = 65_536,
    effect: bool = False,
) -> str:
    env = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C"}
    try:
        result = _bounded_process(
            argv,
            timeout=timeout,
            limit=limit,
            environment=env,
        )
    except OperationFailure as error:
        raise OperationFailure(error.reason, unknown=effect) from None
    except OSError:
        raise OperationFailure("command_unavailable", unknown=effect) from None
    if result.returncode != 0 or result.stderr or len(result.stdout) > limit:
        raise OperationFailure("command_result_unqualified", unknown=effect)
    try:
        return result.stdout.decode("utf-8", "strict")
    except UnicodeError:
        raise OperationFailure("command_encoding", unknown=effect) from None


def _parse_packet(packet: dict[str, Any]) -> dict[str, Any]:
    expected = {"issue", "parent_issue", "source_merge", "claim_holder", "lease_id", "operation"}
    if not isinstance(packet, dict):
        raise OperationFailure("packet_shape")
    rendering = "installation_authority" in packet
    if rendering:
        expected.add("installation_authority")
    if set(packet) != expected:
        raise OperationFailure("packet_shape")
    if rendering:
        authority = _rendering_authority(packet["installation_authority"])
        if (
            packet["issue"] != authority["issue"]
            or packet["parent_issue"] != PARENT_ISSUE
            or packet["source_merge"] != RENDERING_SOURCE_MERGE
            or packet["claim_holder"] != authority["holder"]
        ):
            raise OperationFailure("successor_packet_authority_binding")
    else:
        if packet["issue"] != ISSUE or packet["parent_issue"] != PARENT_ISSUE:
            raise OperationFailure("issue_binding")
        if packet["source_merge"] != SOURCE_MERGE:
            raise OperationFailure("source_binding")
        if packet["claim_holder"] != "codex-4076-upgrade-6457-sol":
            raise OperationFailure("claim_binding")
    if not isinstance(packet["lease_id"], str) or not re.fullmatch(
        r"lease-[0-9a-f]+", packet["lease_id"]
    ):
        raise OperationFailure("lease_binding")
    if not isinstance(packet["operation"], str) or not re.fullmatch(
        r"[0-9a-f]{32}", packet["operation"]
    ):
        raise OperationFailure("operation_binding")
    return packet


def _rendering_authority(value: Any) -> dict[str, Any]:
    """Bind a later explicit installation contract, never the source-only Issue.

    The carrier must freshly authenticate these fields against the normal
    Issue claim, dispatcher lease and sole worktree before sending any effect.
    No host, path, command, service or source selection is accepted here.
    """
    if not isinstance(value, dict) or set(value) != {
        "issue",
        "body_sha256",
        "holder",
        "session",
        "branch",
        "scope",
        "worktree",
        "source_head",
        "registration_generation",
    }:
        raise OperationFailure("successor_installation_authority_shape")
    if (
        type(value["issue"]) is not int
        or RENDERING_INSTALLATION_ISSUE <= 0
        or value["issue"] != RENDERING_INSTALLATION_ISSUE
        or not isinstance(value["body_sha256"], str)
        or value["body_sha256"] != RENDERING_INSTALLATION_BODY_SHA256
        or not isinstance(value["holder"], str)
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{1,127}", value["holder"])
        or not isinstance(value["session"], str)
        or not re.fullmatch(r"[0-9a-f-]{36}", value["session"])
        or value["holder"] != value["session"]
        or not isinstance(value["branch"], str)
        or not re.fullmatch(r"codex/[A-Za-z0-9_-]+", value["branch"])
        or not isinstance(value["worktree"], str)
        or not Path(value["worktree"]).is_absolute()
        or ".." in Path(value["worktree"]).parts
        or not isinstance(value["source_head"], str)
        or not re.fullmatch(r"[0-9a-f]{40}", value["source_head"])
        or not isinstance(value["registration_generation"], str)
        or not re.fullmatch(r"[0-9a-f]{32}", value["registration_generation"])
        or value["scope"] != "install-0172-to-17c2-on-ygg-prod-under-4076"
    ):
        raise OperationFailure("successor_installation_authority_binding")
    return value


def _script_binding(packet: dict[str, Any]) -> tuple[str, str, str]:
    if "installation_authority" in packet:
        return NEW_SCRIPT_SHA256, RENDERING_SCRIPT_SHA256, RENDERING_MANIFEST_SHA256
    return OLD_SCRIPT_SHA256, NEW_SCRIPT_SHA256, MANIFEST_SHA256


def _validate_manifest(manifest: dict[str, dict[str, Any]]) -> None:
    if not isinstance(manifest, dict) or len(manifest) != 60:
        raise OperationFailure("manifest_shape")
    for relative, item in manifest.items():
        if (
            not isinstance(relative, str)
            or not relative
            or relative.startswith("/")
            or ".." in Path(relative).parts
        ):
            raise OperationFailure("manifest_path")
        if (
            not isinstance(item, dict)
            or set(item) != {"mode", "size", "sha256"}
            or item["mode"] != 0o664
            or not isinstance(item["size"], int)
            or not 0 < item["size"] <= MAX_FILE_BYTES
            or not isinstance(item["sha256"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"])
        ):
            raise OperationFailure("manifest_entry")


def _manifest_digest(manifest: dict[str, dict[str, Any]]) -> str:
    rows = [
        {"mode": value["mode"], "path": path, "sha256": value["sha256"], "size": value["size"]}
        for path, value in manifest.items()
    ]
    return hashlib.sha256(json.dumps(rows, separators=(",", ":")).encode()).hexdigest()


def _manifest_matches(manifest: dict[str, dict[str, Any]]) -> None:
    _validate_manifest(manifest)
    for relative, expected in manifest.items():
        actual = _read_bounded(PACKAGE / relative, expected["size"], mode=expected["mode"])
        if hashlib.sha256(actual).hexdigest() != expected["sha256"]:
            raise OperationFailure("public_manifest_mismatch")


def _unit_fields() -> dict[str, str]:
    raw = _safe_command(
        ["/usr/bin/systemctl", "show", UNIT, "--property=" + UNIT_KEYS, "--no-pager"], timeout=5.0
    )
    fields: dict[str, str] = {}
    for line in raw.splitlines():
        if "=" not in line:
            raise OperationFailure("unit_shape")
        key, value = line.split("=", 1)
        if key in fields:
            raise OperationFailure("unit_duplicate")
        fields[key] = value
    return fields


def _configured_unit(fields: dict[str, str]) -> None:
    argv = f"{INTERPRETER} {PACKAGE / 'ops/host-setup/linux/host_probe_launcher.py'} --channel prod"
    environment_file = str(CONFIG) + "(ignore_errors=no)"
    if not (
        fields.get("LoadState") == "loaded"
        and fields.get("UnitFileState") == "enabled"
        and fields.get("FragmentPath") == str(TEMPLATE)
        and fields.get("DropInPaths") == ""
        and fields.get("User") == fields.get("Group") == "root"
        and fields.get("WorkingDirectory") == str(PACKAGE)
        and ("argv[]=" + argv + " ;") in fields.get("ExecStart", "")
        and fields.get("ExecStart", "").count("argv[]=") == 1
        and fields.get("EnvironmentFiles", "").replace(" ", "") == environment_file
        and fields.get("KillMode") == "control-group"
        and fields.get("Restart") == "on-failure"
        and fields.get("TimeoutStopUSec") == "30s"
        and fields.get("NeedDaemonReload") == "no"
        and fields.get("ProtectSystem") == "strict"
        and fields.get("ReadWritePaths") == "/root/.local/state/yggdrasil/secret-controller"
        and fields.get("StandardOutput") == fields.get("StandardError") == "journal"
    ):
        raise OperationFailure("effective_unit_mismatch")


def _unit_projection(fields: dict[str, str]) -> dict[str, str]:
    """Receipt-safe effective-unit identity; omit PID/invocation internals."""
    return {
        key: fields.get(key, "")
        for key in (
            "LoadState",
            "ActiveState",
            "SubState",
            "UnitFileState",
            "FragmentPath",
            "DropInPaths",
            "User",
            "Group",
            "WorkingDirectory",
            "ExecStart",
            "EnvironmentFiles",
            "KillMode",
            "Restart",
            "TimeoutStopUSec",
            "NeedDaemonReload",
            "ProtectSystem",
            "ReadWritePaths",
            "NRestarts",
        )
    }


def _invocation(fields: dict[str, str]) -> str | None:
    invocation = fields.get("InvocationID", "")
    pid = fields.get("MainPID", "")
    if not re.fullmatch(r"[0-9a-f]{32}", invocation) or invocation == "0" * 32 or not pid.isdigit():
        return None
    return hashlib.sha256((invocation + ":" + pid).encode()).hexdigest()


def _require_stopped() -> dict[str, str]:
    fields = _unit_fields()
    _configured_unit(fields)
    if (
        fields.get("ActiveState") not in {"inactive", "failed"}
        or fields.get("MainPID") != "0"
        or fields.get("Job") not in {"", "0"}
    ):
        raise OperationFailure("unit_not_quiescent")
    return fields


def _incident_fingerprint() -> str:
    try:
        return hashlib.sha256(_read_bounded(INCIDENT, 65_536, mode=0o600)).hexdigest()
    except FileNotFoundError:
        return "absent"


def _cache_inventory(
    manifest: dict[str, dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    paths = (
        [PACKAGE / relative for relative in manifest if relative.endswith(".py")]
        if manifest is not None
        else [SCRIPT, SCRIPT.parent / "notification_channels.py"]
    )
    for path in paths:
        key = str(path.relative_to(PACKAGE)) if manifest is not None else path.name
        cache = Path(importlib.util.cache_from_source(str(path)))
        try:
            raw = _read_bounded(cache)
        except FileNotFoundError:
            result[key] = {"present": False}
            continue
        if len(raw) < 16 or raw[:4] != importlib.util.MAGIC_NUMBER:
            raise OperationFailure("cache_header_needs_qualification")
        flags = int.from_bytes(raw[4:8], "little")
        source = _read_bounded(path)
        matches = False
        if flags == 0:
            source_meta = os.stat(path, follow_symlinks=False)
            cached_mtime = int.from_bytes(raw[8:12], "little")
            cached_size = int.from_bytes(raw[12:16], "little")
            matches = cached_mtime == int(source_meta.st_mtime) & 0xFFFFFFFF and cached_size == len(
                source
            )
        elif flags == 3:
            matches = raw[8:16] == importlib.util.source_hash(source)
        else:
            raise OperationFailure("unchecked_cache_needs_qualification")
        result[key] = {
            "present": True,
            "header_flags": flags,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "matches_source": matches,
            "loader_action": "use_checked_cache" if matches else "compile_current_source",
        }
    return result


def _write_domain() -> None:
    """Admit the producer's group-0 modes only for the actual root write domain."""
    members = grp.getgrgid(EXPECTED_GID).gr_mem
    if any(pwd.getpwnam(name).pw_uid != EXPECTED_UID for name in members):
        raise OperationFailure("additional_group_writer")
    if any(item.pw_gid == EXPECTED_GID and item.pw_uid != EXPECTED_UID for item in pwd.getpwall()):
        raise OperationFailure("additional_primary_group_writer")
    list_attributes = getattr(os, "listxattr", None)
    if not callable(list_attributes):
        raise OperationFailure("write_domain_acl_unavailable")
    parents = tuple(path for path in SCRIPT.parents if path == PACKAGE or PACKAGE in path.parents)
    for path in (*parents, SCRIPT):
        if {"system.posix_acl_access", "system.posix_acl_default"}.intersection(
            list_attributes(path)
        ):
            raise OperationFailure("additional_acl_writer")


def _proc_bytes(path: Path, limit: int = 65_536) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        chunks = bytearray()
        while len(chunks) <= limit:
            block = os.read(descriptor, min(16_384, limit + 1 - len(chunks)))
            if not block:
                return bytes(chunks)
            chunks.extend(block)
        raise OperationFailure("process_metadata_bound")
    finally:
        os.close(descriptor)


def _pid_metadata(pid: str) -> dict[str, Any]:
    if not pid.isdigit() or int(pid) <= 0:
        raise OperationFailure("process_identity")
    root = PROC_ROOT / pid
    raw = _proc_bytes(root / "stat", 4_096).decode()
    tail = raw[raw.rfind(")") + 2 :].split()
    if len(tail) < 20 or not tail[1].isdigit() or not tail[19].isdigit():
        raise OperationFailure("process_stat")
    cgroups = _proc_bytes(root / "cgroup", 4_096).decode().splitlines()
    if len(cgroups) != 1 or not cgroups[0].startswith("0::/"):
        raise OperationFailure("cgroup_v2_required")
    return {
        "pid": pid,
        "ppid": tail[1],
        "start_ticks": tail[19],
        "cgroup": cgroups[0][3:],
        "uid": os.stat(root).st_uid,
        "exe": os.readlink(root / "exe"),
        "cwd": os.readlink(root / "cwd"),
    }


def _cgroup_members(cgroup: str) -> set[str]:
    if not cgroup:
        return set()
    path = Path(cgroup)
    if not path.is_absolute() or ".." in path.parts or not cgroup.startswith("/system.slice/"):
        raise OperationFailure("cgroup_path")
    try:
        raw = _proc_bytes(CGROUP_ROOT / cgroup.lstrip("/") / "cgroup.procs", 16_384)
    except FileNotFoundError:
        return set()
    members = raw.decode().splitlines()
    if len(members) > 64 or any(not pid.isdigit() or int(pid) <= 0 for pid in members):
        raise OperationFailure("cgroup_members")
    return set(members)


def _active_identity(fields: dict[str, str]) -> dict[str, Any]:
    _configured_unit(fields)
    invocation = fields.get("InvocationID", "")
    pid = fields.get("MainPID", "")
    cgroup = fields.get("ControlGroup", "")
    started = fields.get("ExecMainStartTimestampMonotonic", "")
    if not (
        fields.get("ActiveState") == "active"
        and fields.get("SubState") == "running"
        and fields.get("NRestarts") == "0"
        and fields.get("Job") in {"", "0"}
        and _invocation(fields)
        and cgroup.endswith("/" + UNIT)
        and started.isdigit()
        and int(started) > 0
    ):
        raise OperationFailure("active_incarnation_unqualified")
    main = _pid_metadata(pid)
    if (
        main["uid"] != EXPECTED_UID
        or main["cgroup"] != cgroup
        or Path(main["exe"]).resolve() != INTERPRETER.resolve()
    ):
        raise OperationFailure("main_process_boundary")
    argv = _proc_bytes(PROC_ROOT / pid / "cmdline").split(b"\0")[:-1]
    expected_main = [
        str(INTERPRETER),
        str(PACKAGE / "ops/host-setup/linux/host_probe_launcher.py"),
        "--channel",
        "prod",
    ]
    if argv != [arg.encode() for arg in expected_main] or main["cwd"] != str(PACKAGE):
        raise OperationFailure("launcher_entry_boundary")
    members = _cgroup_members(cgroup)
    if pid not in members:
        raise OperationFailure("main_not_in_cgroup")
    probe_child = None
    http_children = 0
    for member in sorted(members):
        if member == pid:
            continue
        try:
            process = _pid_metadata(member)
            command = _proc_bytes(PROC_ROOT / member / "cmdline").split(b"\0")[:-1]
            environ = _proc_bytes(PROC_ROOT / member / "environ", 131_072)
        except (FileNotFoundError, ProcessLookupError):
            continue
        if (
            process["uid"] != EXPECTED_UID
            or process["cgroup"] != cgroup
            or Path(process["exe"]).resolve() != INTERPRETER.resolve()
        ):
            raise OperationFailure("foreign_cgroup_process")
        if (
            command == [str(INTERPRETER).encode(), str(SCRIPT).encode(), b"--loop"]
            and process["ppid"] == pid
        ):
            env = dict(item.split(b"=", 1) for item in environ.split(b"\0") if b"=" in item)
            if any(
                key in env
                for key in (b"BWS_ACCESS_TOKEN", b"BWS_ACCESS_TOKEN_FILE", b"CREDENTIALS_DIRECTORY")
            ):
                raise OperationFailure("probe_child_credential_boundary")
            if (
                env.get(b"HOST_SECRET_BOOTSTRAP_CHANNEL") != b"prod"
                or env.get(b"HOST_SECRET_BOOTSTRAP_CONSUMER") != b"heimdal-external-alerts"
            ):
                raise OperationFailure("probe_consumer_boundary")
            runtime = Path(env.get(b"HOST_SECRET_RUNTIME_ENV_FILE", b"").decode())
            if runtime.parent != RUNTIME_DIRECTORY:
                raise OperationFailure("runtime_binding_path")
            runtime_parent = _open_directory(runtime.parent)
            try:
                directory = os.fstat(runtime_parent)
                if stat.S_IMODE(directory.st_mode) != 0o700 or directory.st_uid != EXPECTED_UID:
                    raise OperationFailure("runtime_binding_directory_metadata")
                metadata = os.stat(runtime.name, dir_fd=runtime_parent, follow_symlinks=False)
            finally:
                os.close(runtime_parent)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != EXPECTED_UID
                or metadata.st_nlink != 1
                or stat.S_IMODE(metadata.st_mode) != 0o600
            ):
                raise OperationFailure("runtime_binding_metadata")
            if probe_child is not None:
                raise OperationFailure("multiple_normal_probe_children")
            probe_child = {key: process[key] for key in ("pid", "ppid", "start_ticks")}
        elif (
            command
            == [
                str(INTERPRETER).encode(),
                b"-I",
                b"-c",
                CHILD_CODE.encode(),
                str(SCRIPT.parent).encode(),
            ]
            and not environ
        ):
            http_children += 1
        else:
            raise OperationFailure("unexpected_probe_cgroup_process")
    if probe_child is None:
        raise OperationFailure("normal_probe_child_not_ready")
    # Bind again after walking the process set; PID reuse is not ownership.
    if _pid_metadata(pid) != main:
        raise OperationFailure("main_process_changed")
    child = _pid_metadata(probe_child["pid"])
    if any(child[key] != value for key, value in probe_child.items()):
        raise OperationFailure("normal_probe_child_changed")
    # basicConfig uses stderr. The unchanged bootstrap's Popen inherits this
    # socket; journald attributes inherited stream records to its launcher peer.
    stream = os.readlink(PROC_ROOT / pid / "fd/2")
    if (
        not re.fullmatch(r"socket:\[\d+\]", stream)
        or os.readlink(PROC_ROOT / probe_child["pid"] / "fd/2") != stream
    ):
        raise OperationFailure("normal_journal_stream_lineage")
    return {
        "invocation": invocation,
        "pid": pid,
        "cgroup": cgroup,
        "main_start_usec": started,
        "process_start_ticks": main["start_ticks"],
        "probe_child": probe_child,
        "journal_stderr_socket": stream,
        "http_children_observed": http_children,
    }


def _identity_key(identity: dict[str, Any]) -> tuple[str, ...]:
    return tuple(
        str(identity[key])
        for key in ("invocation", "pid", "cgroup", "main_start_usec", "process_start_ticks")
    ) + (
        identity["probe_child"]["pid"],
        identity["probe_child"]["start_ticks"],
        identity["journal_stderr_socket"],
    )


def _same_active(expected: dict[str, Any]) -> dict[str, Any]:
    actual = _active_identity(_unit_fields())
    if _identity_key(actual) != _identity_key(expected):
        raise OperationFailure("foreign_invocation_drift")
    return actual


def _additional_consumers(owned_cgroup: str) -> None:
    _other_probe_units_quiescent()
    entries = [path for path in PROC_ROOT.iterdir() if path.name.isdigit()]
    if len(entries) > 16_384:
        raise OperationFailure("consumer_census_bound")
    package = str(PACKAGE).encode()
    for path in entries:
        try:
            cwd = os.readlink(path / "cwd")
            executable = os.readlink(path / "exe")
            command = _proc_bytes(path / "cmdline")
            use = cwd == str(PACKAGE) or cwd.startswith(str(PACKAGE) + "/")
            if "python" in Path(executable).name:
                environment = _proc_bytes(path / "environ", 131_072)
                pythonpath = next(
                    (
                        item[11:]
                        for item in environment.split(b"\0")
                        if item.startswith(b"PYTHONPATH=")
                    ),
                    b"",
                )
                use = use or package in command or package in pythonpath
            if use and _pid_metadata(path.name)["cgroup"] != owned_cgroup:
                raise OperationFailure("additional_package_consumer")
        except (FileNotFoundError, ProcessLookupError):
            continue


def _stopped_identity(prior: dict[str, Any], stop_usec: int) -> dict[str, str]:
    fields = _require_stopped()
    if fields.get("InvocationID") not in {prior["invocation"], "", "0" * 32}:
        raise OperationFailure("foreign_stopped_incarnation")
    if fields.get("ExecMainStartTimestampMonotonic") != prior["main_start_usec"]:
        raise OperationFailure("stopped_process_lineage_changed")
    if _cgroup_members(prior["cgroup"]):
        raise OperationFailure("probe_cgroup_not_empty")
    entered = fields.get("InactiveEnterTimestampMonotonic", "")
    if not entered.isdigit() or int(entered) < stop_usec:
        raise OperationFailure("stop_not_owned")
    _additional_consumers(prior["cgroup"])
    return fields


def _target_and_consumers() -> None:
    if platform.system() != "Linux" or os.geteuid() != EXPECTED_UID or os.getegid() != EXPECTED_GID:
        raise OperationFailure("host_role")
    if sys.version_info < (3, 10) or Path(sys.executable).resolve() != INTERPRETER.resolve(
        strict=True
    ):
        raise OperationFailure("interpreter_identity")
    if platform.node() != "ygg-prod":
        raise OperationFailure("guest_identity")
    _write_domain()
    engine = _safe_command(
        ["/usr/bin/docker", "--host=unix:///var/run/docker.sock", "info", "--format", "{{.ID}}"],
        limit=4_096,
    ).strip()
    if not engine or hashlib.sha256(engine.encode()).hexdigest() != ENGINE_SHA256:
        raise OperationFailure("engine_identity")
    _other_probe_units_quiescent()


def _other_probe_units_quiescent() -> None:
    rows = _safe_command(
        [
            "/usr/bin/systemctl",
            "list-units",
            "--all",
            "--type=service",
            "--plain",
            "--no-legend",
            "--no-pager",
            "yggdrasil-host-probe@*.service",
        ]
    )
    names: set[str] = set()
    for line in rows.splitlines():
        parts = line.split()
        if len(parts) < 4 or not re.fullmatch(
            r"yggdrasil-host-probe@[A-Za-z0-9_.-]+\.service", parts[0]
        ):
            raise OperationFailure("consumer_projection")
        names.add(parts[0])
        if parts[0] != UNIT and (
            parts[0] != "yggdrasil-host-probe@test.service"
            or parts[2] not in {"inactive", "failed"}
        ):
            raise OperationFailure("additional_probe_consumer")
        if parts[0] != UNIT:
            raw = _safe_command(
                [
                    "/usr/bin/systemctl",
                    "show",
                    parts[0],
                    "--property=LoadState,ActiveState,MainPID,Job,ControlGroup",
                    "--no-pager",
                ],
                timeout=5.0,
                limit=16_384,
            )
            projection = dict(line.split("=", 1) for line in raw.splitlines() if "=" in line)
            if (
                projection.get("LoadState") != "loaded"
                or projection.get("ActiveState") not in {"inactive", "failed"}
                or projection.get("MainPID") != "0"
                or projection.get("Job") not in {"", "0"}
                or _cgroup_members(projection.get("ControlGroup", ""))
            ):
                raise OperationFailure("additional_consumer_job_or_process")
    if len(names) > 2 or UNIT not in names:
        raise OperationFailure("consumer_projection")


def _fixed_files() -> None:
    if hashlib.sha256(_read_bounded(CONFIG, 65_536, mode=0o644)).hexdigest() != CONFIG_SHA256:
        raise OperationFailure("configuration_mismatch")
    if hashlib.sha256(_read_bounded(TEMPLATE, 65_536, mode=0o644)).hexdigest() != UNIT_SHA256:
        raise OperationFailure("unit_file_mismatch")


def _write_support_file(path: Path, data: bytes) -> None:
    with path.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(path, 0o664)


def _staged_child_support(
    script_bytes: bytes,
    notification_bytes: bytes,
    *,
    child_code: str,
    invalid_packet: bool,
) -> dict[str, Any]:
    if "-B" in child_code or "sys.dont_write_bytecode" in child_code:
        raise OperationFailure("child_flags_changed")
    try:
        with tempfile.TemporaryDirectory(prefix="yggdrasil-probe-6457-", dir="/tmp") as raw:
            root = Path(raw)
            metadata = os.stat(root, follow_symlinks=False)
            if metadata.st_uid != os.geteuid() or stat.S_IMODE(metadata.st_mode) != 0o700:
                raise OperationFailure("support_directory_metadata")
            _write_support_file(root / "prod_probe.py", script_bytes)
            _write_support_file(root / "notification_channels.py", notification_bytes)
            result = _bounded_process(
                [sys.executable, "-I", "-c", child_code, str(root)],
                input_bytes=b"{}" if invalid_packet else b"",
                timeout=2.0,
                limit=4_096,
                environment={},
            )
    except OperationFailure:
        raise OperationFailure("child_support_timeout") from None
    except OSError:
        raise OperationFailure("child_support_unavailable") from None
    if invalid_packet:
        qualified = (
            result.returncode == 0 and not result.stderr and result.stdout == b'{"error":true}'
        )
    else:
        qualified = result.returncode == 0 and not result.stderr and not result.stdout
    if not qualified:
        raise OperationFailure("child_protocol")
    return {
        "argv": [sys.executable, "-I", "-c", child_code, "<owned-support-directory>"],
        "environment": {},
        "invalid_packet": invalid_packet,
        "network_url": False,
        "exit": result.returncode,
        "pipes_closed": True,
        "reaped": True,
        "staged": True,
    }


def _incident_snapshot() -> dict[str, Any]:
    from uuid import UUID

    try:
        raw = _read_bounded(INCIDENT, 65_536, mode=0o600)
    except FileNotFoundError:
        return {"sha256": "absent", "present": False, "correlation_sha256": None}
    try:
        value = json.loads(raw)
        correlation = value["correlation_id"]
        UUID(correlation)
        valid = (
            value["status"] == "down"
            and value["environment"] == "prod"
            and type(value["ts"]) is int
            and value["ts"] > 0
            and isinstance(value["failures"], list)
            and bool(value["failures"])
            and all(isinstance(item, str) and item for item in value["failures"])
        )
    except (ValueError, TypeError, KeyError, AttributeError):
        raise OperationFailure("incident_schema_unqualified") from None
    if not valid:
        raise OperationFailure("incident_schema_unqualified")
    return {
        "sha256": hashlib.sha256(raw).hexdigest(),
        "present": True,
        "correlation_sha256": hashlib.sha256(correlation.encode()).hexdigest(),
    }


def _identity_digest(identity: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(_identity_key(identity)).encode()).hexdigest()


def _await_started(old: dict[str, Any], intent_usec: int) -> dict[str, Any]:
    deadline = time.monotonic() + 20.0
    while True:
        fields = _unit_fields()
        if fields.get("InvocationID") == old["invocation"]:
            raise OperationFailure("old_invocation_reused")
        try:
            actual = _active_identity(fields)
        except OperationFailure as error:
            if error.reason != "normal_probe_child_not_ready" or time.monotonic() >= deadline:
                raise
            time.sleep(0.2)
            continue
        if int(actual["main_start_usec"]) < intent_usec:
            raise OperationFailure("start_not_owned")
        return actual


def _normal_cycles(
    identity: dict[str, Any],
    before: dict[str, Any],
    *,
    sleep: Callable[[float], None] | None = None,
) -> dict[str, Any]:
    """Count completed outcomes on the inherited launcher/child journal stream."""
    if sleep is None:
        sleep = time.sleep
    _same_active(identity)
    sleep(125.0)
    for attempt in range(10):
        _same_active(identity)
        raw = _safe_command(
            [
                "/usr/bin/journalctl",
                "_SYSTEMD_UNIT=" + UNIT,
                "_SYSTEMD_INVOCATION_ID=" + identity["invocation"],
                "--no-pager",
                "--output=json",
                "--lines=512",
                "--output-fields=MESSAGE,_SYSTEMD_INVOCATION_ID,_SYSTEMD_CGROUP,_TRANSPORT,_STREAM_ID,_PID,__MONOTONIC_TIMESTAMP,__CURSOR",
            ],
            timeout=5.0,
            limit=131_072,
        )
        rows: list[tuple[int, str, str]] = []
        cursors: set[str] = set()
        stream_id = None
        producer_pid = None
        for line in raw.splitlines():
            try:
                row = json.loads(line)
                stamp = int(row["__MONOTONIC_TIMESTAMP"])
                cursor = row["__CURSOR"]
                message = row["MESSAGE"]
                if row["_SYSTEMD_INVOCATION_ID"] != identity["invocation"]:
                    raise OperationFailure("foreign_journal_invocation")
                if not isinstance(message, str) or not isinstance(cursor, str) or cursor in cursors:
                    raise OperationFailure("journal_record_identity")
                cursors.add(cursor)
                if stamp < int(identity["main_start_usec"]):
                    raise OperationFailure("journal_before_incarnation")
                match = re.fullmatch(
                    r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d{3} \[prod-probe\] (INFO|WARNING|ERROR) (.*)",
                    message,
                )
                if match:
                    if row["_PID"] not in {identity["pid"], identity["probe_child"]["pid"]}:
                        raise OperationFailure("foreign_journal_process")
                    if producer_pid is not None and row["_PID"] != producer_pid:
                        raise OperationFailure("journal_producer_changed")
                    producer_pid = row["_PID"]
                    if (
                        row["_TRANSPORT"] != "stdout"
                        or row["_SYSTEMD_CGROUP"] != identity["cgroup"]
                        or not isinstance(row["_STREAM_ID"], str)
                        or not re.fullmatch(r"[0-9a-f]{32}", row["_STREAM_ID"])
                    ):
                        raise OperationFailure("foreign_journal_stream")
                    if stream_id is not None and row["_STREAM_ID"] != stream_id:
                        raise OperationFailure("journal_stream_changed")
                    stream_id = row["_STREAM_ID"]
                    rows.append((stamp, cursor, match[2]))
            except (ValueError, TypeError, KeyError):
                raise OperationFailure("journal_record_shape") from None
        outcomes: list[dict[str, Any]] = []
        incident_active = before["present"]
        pending_recovery = False
        confirmed = False
        down_sent = recovery_sent = 0
        for stamp, cursor, message in sorted(rows):
            if "failed to send" in message or message.startswith(
                ("probe iteration failed", "probe execution failed")
            ):
                raise OperationFailure("normal_delivery_or_iteration_failed")
            if message == "discord webhook push confirmed: 200":
                confirmed = True
                continue
            kind = None
            if message.startswith("probe ok:"):
                if incident_active:
                    pending_recovery = True
                else:
                    kind = "healthy"
            elif message == "probe-recovered alert sent; outage state cleared: environment=prod":
                if not (pending_recovery and incident_active and confirmed):
                    raise OperationFailure("recovery_confirmation_unqualified")
                incident_active = pending_recovery = confirmed = False
                recovery_sent += 1
                kind = "confirmed_recovery"
            elif message == "probe-down alert sent and outage state recorded: environment=prod":
                if incident_active or not confirmed:
                    raise OperationFailure("down_confirmation_unqualified")
                incident_active = True
                confirmed = False
                down_sent += 1
                kind = "confirmed_down"
            elif (
                message
                == "probe-down detected but outage already recorded; suppressing duplicate alert. environment=prod"
            ):
                if not incident_active:
                    raise OperationFailure("suppression_without_incident")
                kind = "suppressed_down"
            if kind:
                outcomes.append(
                    {
                        "kind": kind,
                        "monotonic_usec": stamp,
                        "cursor_sha256": hashlib.sha256(cursor.encode()).hexdigest(),
                    }
                )
        if len(outcomes) >= 2 and not pending_recovery:
            after = _incident_snapshot()
            branch = "truthful_observation_unqualified"
            if incident_active and after["present"]:
                if before["present"] and down_sent == recovery_sent == 0 and after == before:
                    branch = "continued_incident_suppressed"
                elif down_sent > 0:
                    branch = (
                        "confirmed_down_incident"
                        if not recovery_sent
                        else "recovered_then_new_confirmed_down"
                    )
            elif not incident_active and not after["present"]:
                if before["present"] and recovery_sent:
                    branch = "recovered_preserved_incident"
                elif not before["present"]:
                    branch = (
                        "healthy_no_incident" if not down_sent else "confirmed_down_then_recovered"
                    )
            if branch == "truthful_observation_unqualified":
                raise OperationFailure("normal_continuation_unqualified")
            _same_active(identity)
            return {
                "completed_cycles": len(outcomes),
                "outcomes": outcomes,
                "continuation_branch": branch,
                "incident_after": after,
                "invocation_sha256": _identity_digest(identity),
                "confirmed_down": down_sent,
                "confirmed_recovery": recovery_sent,
                "journal_peer": "normal_launcher_inherited_stderr"
                if producer_pid == identity["pid"]
                else "normal_child_inherited_stderr",
            }
        if attempt < 9:
            sleep(5.0)
    raise OperationFailure("normal_cycles_unproven")


def _journal_update(
    journal: Callable[[dict[str, Any]], None],
    context: dict[str, Any],
    phase: str,
    **facts: Any,
) -> None:
    context.update(facts)
    context["phase"] = phase
    journal(context)


def _guard_source(manifest: dict[str, dict[str, Any]]) -> None:
    _fixed_files()
    _manifest_matches(manifest)
    _write_domain()


def _stop_owned(
    identity: dict[str, Any],
    manifest: dict[str, dict[str, Any]],
    journal: Callable[[dict[str, Any]], None],
    context: dict[str, Any],
    *,
    recovery: bool = False,
    resource_guard: Callable[[], None] | None = None,
) -> int:
    if resource_guard:
        resource_guard()
    _guard_source(manifest)
    _additional_consumers(identity["cgroup"])
    _same_active(identity)
    intent = int(time.monotonic() * 1_000_000)
    _journal_update(
        journal,
        context,
        "recovery_stop_intent" if recovery else "stop_intent",
        stopping_identity=identity,
        stop_intent_usec=intent,
    )
    # Revalidate after the durable write, immediately before the effect.
    if resource_guard:
        resource_guard()
    _same_active(identity)
    _safe_command(["/usr/bin/systemctl", "stop", UNIT], timeout=35.0, effect=True)
    _stopped_identity(identity, intent)
    return intent


def _start_owned(
    prior: dict[str, Any],
    stop_usec: int,
    manifest: dict[str, dict[str, Any]],
    incident: dict[str, Any],
    journal: Callable[[dict[str, Any]], None],
    context: dict[str, Any],
    *,
    recovery: bool = False,
    resource_guard: Callable[[], None] | None = None,
) -> dict[str, Any]:
    if resource_guard:
        resource_guard()
    _guard_source(manifest)
    _stopped_identity(prior, stop_usec)
    if _incident_snapshot() != incident:
        raise OperationFailure("incident_changed_before_start")
    key = "recovery_start_intent_usec" if recovery else "start_intent_usec"
    if key in context:
        # Recency/configuration cannot bind a lost start to an incarnation.
        raise OperationFailure("original_start_ownership_unproven", unknown=True)
    intent = int(time.monotonic() * 1_000_000)
    _journal_update(
        journal, context, "recovery_start_intent" if recovery else "start_intent", **{key: intent}
    )
    if resource_guard:
        resource_guard()
    _guard_source(manifest)
    if _incident_snapshot() != incident:
        raise OperationFailure("incident_changed_before_start")
    _stopped_identity(prior, stop_usec)
    _safe_command(["/usr/bin/systemctl", "start", UNIT], timeout=20.0, effect=True)
    identity = _await_started(prior, intent)
    _journal_update(
        journal,
        context,
        "restored" if recovery else "started",
        **{"restored_identity" if recovery else "new_identity": identity},
    )
    return identity


def _settle_job() -> dict[str, str]:
    deadline = time.monotonic() + 35.0
    while True:
        fields = _unit_fields()
        _configured_unit(fields)
        if fields.get("Job") in {"", "0"}:
            return fields
        if time.monotonic() >= deadline:
            raise OperationFailure("original_unit_job_unresolved", unknown=True)
        time.sleep(0.2)


def _recover(
    context: dict[str, Any],
    *,
    before_manifest: dict[str, dict[str, Any]],
    after_manifest: dict[str, dict[str, Any]],
    old_bytes: bytes,
    journal: Callable[[dict[str, Any]], None],
    operation_hex: str,
    rendering: bool = False,
    resource_guard: Callable[[], None] | None = None,
) -> dict[str, Any]:
    """Reconcile the original phase, then compensate code and the owned unit once."""
    old_sha = NEW_SCRIPT_SHA256 if rendering else OLD_SCRIPT_SHA256
    new_sha = RENDERING_SCRIPT_SHA256 if rendering else NEW_SCRIPT_SHA256
    if resource_guard:
        resource_guard()
    prior = context.get("old_identity")
    if not prior or "stop_intent_usec" not in context:
        return {"status": "refused", "probe_effect": False}
    fields = _settle_job()
    _fixed_files()
    current_sha = hashlib.sha256(_read_bounded(SCRIPT, 262_144, mode=0o664)).hexdigest()
    if current_sha not in {old_sha, new_sha}:
        raise OperationFailure("foreign_source_during_recovery", unknown=True)
    manifest = before_manifest if current_sha == old_sha else after_manifest
    _guard_source(manifest)
    if fields.get("ActiveState") == "active":
        actual = _active_identity(fields)
        expected = context.get("restored_identity") or context.get("new_identity")
        if (current_sha == new_sha and "start_intent_usec" in context and expected is None) or (
            current_sha == old_sha
            and "recovery_start_intent_usec" in context
            and context.get("restored_identity") is None
        ):
            raise OperationFailure("original_start_ownership_unproven", unknown=True)
        if current_sha == old_sha and _identity_key(actual) == _identity_key(prior):
            return {"status": "refused", "code_changed": False, "original_service_active": True}
        if expected is None or _identity_key(actual) != _identity_key(expected):
            raise OperationFailure("foreign_active_incarnation_during_recovery", unknown=True)
        if current_sha == old_sha and context.get("restored_identity"):
            return {
                "status": "rolled_back",
                "code_only": True,
                "restored_invocation_sha256": _identity_digest(actual),
            }
        stop_usec = _stop_owned(
            actual, manifest, journal, context, recovery=True, resource_guard=resource_guard
        )
        prior = actual
    else:
        prior = context.get("stopping_identity", prior)
        stop_usec = context["stop_intent_usec"]
        _stopped_identity(prior, stop_usec)
    # Normal delivery may have advanced acknowledgment after the first start.
    # The latest quiescent state is the preservation preimage for this rollback.
    incident = _incident_snapshot()
    _journal_update(
        journal,
        context,
        "recovery_quiescent",
        recovery_incident=incident,
        recovery_stopped_identity=prior,
        recovery_stop_usec=stop_usec,
    )
    if current_sha == new_sha:
        parent = _open_directory(SCRIPT.parent)
        try:

            def still_owned() -> None:
                if resource_guard:
                    resource_guard()
                _stopped_identity(prior, stop_usec)
                _guard_source(after_manifest)
                if _incident_snapshot() != incident:
                    raise OperationFailure("latest_incident_changed_during_rollback")

            _journal_update(journal, context, "rollback_replace_intent")
            swap_script(
                parent,
                new_sha,
                old_bytes,
                old_sha,
                operation_hex,
                still_owned,
                expected_uid=EXPECTED_UID,
                expected_gid=EXPECTED_GID,
            )
        finally:
            os.close(parent)
    _guard_source(before_manifest)
    if _incident_snapshot() != incident:
        raise OperationFailure("latest_incident_not_preserved")
    restored = _start_owned(
        prior,
        stop_usec,
        before_manifest,
        incident,
        journal,
        context,
        recovery=True,
        resource_guard=resource_guard,
    )
    _same_active(restored)
    _guard_source(before_manifest)
    if resource_guard:
        resource_guard()
    return {
        "status": "rolled_back",
        "code_only": True,
        "restored_old_sha256": old_sha,
        "restored_invocation_sha256": _identity_digest(restored),
        "latest_quiescent_incident_preserved": incident["sha256"],
        "cache_restored_or_deleted": False,
    }


def run(
    packet: dict[str, Any],
    *,
    before_manifest: dict[str, dict[str, Any]],
    after_manifest: dict[str, dict[str, Any]],
    old_bytes: bytes,
    new_bytes: bytes,
    journal: Callable[[dict[str, Any]], None] | None = None,
    resource_guard: Callable[[], None] | None = None,
    admitted_identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    packet = _parse_packet(packet)
    rendering = "installation_authority" in packet
    old_sha, new_sha, manifest_sha = _script_binding(packet)
    if rendering and (resource_guard is None or admitted_identity is None):
        raise OperationFailure("successor_owned_resource_and_identity_required")
    if (
        hashlib.sha256(old_bytes).hexdigest() != old_sha
        or hashlib.sha256(new_bytes).hexdigest() != new_sha
    ):
        raise OperationFailure("script_binding")
    _validate_manifest(before_manifest)
    _validate_manifest(after_manifest)
    if _manifest_digest(after_manifest) != manifest_sha:
        raise OperationFailure("manifest_binding")
    if rendering and _manifest_digest(before_manifest) != MANIFEST_SHA256:
        raise OperationFailure("successor_before_manifest_binding")
    if set(before_manifest) != set(after_manifest) or any(
        before_manifest[p] != after_manifest[p] for p in before_manifest if p != SCRIPT_REL
    ):
        raise OperationFailure("retained_manifest_mismatch")
    report: dict[str, Any] = {
        "schema": "probe_installation.v1",
        "armed": True,
        "issue": packet["issue"],
        "parent_issue": PARENT_ISSUE,
        "source_merge": packet["source_merge"],
        "operation": packet["operation"],
        "claim_holder": packet["claim_holder"],
        "lease_id": packet["lease_id"],
        "contract_body_sha256": packet["installation_authority"]["body_sha256"]
        if rendering
        else BODY_SHA256,
        "unit": UNIT,
        "script": SCRIPT_REL,
        "old_script_sha256": old_sha,
        "new_script_sha256": new_sha,
        "source_manifest_files": len(after_manifest),
        "source_manifest": [{"path": p, **v} for p, v in after_manifest.items()],
        "source_manifest_sha256": _manifest_digest(after_manifest),
        "configuration_sha256": CONFIG_SHA256,
        "unit_sha256": UNIT_SHA256,
        "test_acceptance": False,
    }
    context: dict[str, Any] = {"operation": packet["operation"], "phase": "entry"}
    parent = None
    try:
        if resource_guard:
            resource_guard()
        _target_and_consumers()
        _guard_source(before_manifest)
        old = admitted_identity if rendering else _active_identity(_unit_fields())
        assert old is not None
        if rendering:
            _same_active(old)
        _additional_consumers(old["cgroup"])
        report["old_invocation_sha256"] = _identity_digest(old)
        report["effective_unit_before"] = _unit_projection(_unit_fields())
        report["cache_before"] = _cache_inventory(before_manifest)
        notification = _read_bounded(
            SCRIPT.parent / "notification_channels.py", 262_144, mode=0o664
        )
        report["old_import_support"] = _staged_child_support(
            old_bytes, notification, child_code=BEFORE_IMPORT_CODE, invalid_packet=False
        )
        report["candidate_child_support"] = _staged_child_support(
            new_bytes, notification, child_code=CHILD_CODE, invalid_packet=True
        )
        if journal is None:
            raise OperationFailure("owned_operation_journal_required")
        _journal_update(journal, context, "qualified", old_identity=old)
        stopped_at = _stop_owned(
            old, before_manifest, journal, context, resource_guard=resource_guard
        )
        incident = _incident_snapshot()
        _journal_update(journal, context, "quiescent", quiescent_incident=incident)
        report["quiescent_incident"] = incident
        parent = _open_directory(SCRIPT.parent)

        def before_replace() -> None:
            if resource_guard:
                resource_guard()
            _stopped_identity(old, stopped_at)
            _guard_source(before_manifest)
            fresh = _open_directory(SCRIPT.parent)
            try:
                left, right = os.fstat(fresh), os.fstat(parent)
                if (left.st_dev, left.st_ino) != (right.st_dev, right.st_ino):
                    raise OperationFailure("directory_chain_changed")
            finally:
                os.close(fresh)
            if _incident_snapshot() != incident:
                raise OperationFailure("quiescent_incident_changed")

        _journal_update(journal, context, "replace_intent")
        report["swap"] = swap_script(
            parent,
            old_sha,
            new_bytes,
            new_sha,
            packet["operation"],
            before_replace,
            expected_uid=EXPECTED_UID,
            expected_gid=EXPECTED_GID,
        )
        _guard_source(after_manifest)
        if _incident_snapshot() != incident:
            raise OperationFailure("incident_changed_across_cutover")
        report["incident_preserved_across_code"] = True
        _journal_update(journal, context, "replaced")
        new = _start_owned(
            old,
            stopped_at,
            after_manifest,
            incident,
            journal,
            context,
            resource_guard=resource_guard,
        )
        if new["invocation"] == old["invocation"]:
            raise OperationFailure("old_invocation_reused")
        report["new_invocation_sha256"] = _identity_digest(new)
        report["normal_cycles"] = _normal_cycles(new, incident)
        _same_active(new)
        _guard_source(after_manifest)
        _additional_consumers(new["cgroup"])
        report["cache_after"] = _cache_inventory(after_manifest)
        report["effective_unit_after"] = _unit_projection(_unit_fields())
        report["actual_launcher_consumer_child_interpreter_qualified"] = True
        if resource_guard:
            resource_guard()
        report["status"] = "committed"
        _journal_update(journal, context, "committed")
        return report
    except (OperationFailure, SwapFailure, OSError) as error:
        reason = (
            error.reason
            if isinstance(error, OperationFailure)
            else (error.phase if isinstance(error, SwapFailure) else "operation_os_failure")
        )
        report.update(status="refused", phase=context["phase"], failure=reason)
        if journal is not None and "stop_intent_usec" in context:
            try:
                report["recovery"] = _recover(
                    context,
                    before_manifest=before_manifest,
                    after_manifest=after_manifest,
                    old_bytes=old_bytes,
                    journal=journal,
                    operation_hex=packet["operation"],
                    rendering=rendering,
                    resource_guard=resource_guard,
                )
                report["status"] = report["recovery"]["status"]
            except (OperationFailure, SwapFailure, OSError) as recovery:
                report["status"] = "unknown"
                report["recovery_failure"] = (
                    recovery.reason
                    if isinstance(recovery, OperationFailure)
                    else "recovery_phase_unqualified"
                )
        elif isinstance(error, OperationFailure) and error.unknown:
            report["status"] = "unknown"
        return report
    finally:
        if parent is not None:
            os.close(parent)


# The following entrypoints are fixed to this one probe operation.  The original
# handle is durable before the worker is permitted to affect the probe.


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _owned_directory(path: Path, *, create: bool = False) -> None:
    parent = _open_directory(path.parent)
    try:
        if create:
            try:
                os.mkdir(path.name, 0o700, dir_fd=parent)
                os.fsync(parent)
            except FileExistsError:
                pass
        descriptor = os.open(
            path.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent
        )
        try:
            meta = os.fstat(descriptor)
            if (
                meta.st_uid != EXPECTED_UID
                or meta.st_gid != EXPECTED_GID
                or stat.S_IMODE(meta.st_mode) != 0o700
            ):
                raise OperationFailure("operation_directory_ownership")
        finally:
            os.close(descriptor)
    finally:
        os.close(parent)


def _metadata_write(path: Path, value: Any, *, exclusive: bool = False) -> None:
    import uuid

    data = _json_bytes(value)
    if len(data) > 1_048_576:
        raise OperationFailure("operation_metadata_bound")
    parent = _open_directory(path.parent)
    name = path.name if exclusive else path.name + ".tmp-" + uuid.uuid4().hex
    descriptor = None
    identity = None
    try:
        if not exclusive:
            try:
                _read_bounded(path, mode=0o600)
            except FileNotFoundError:
                pass
        descriptor = os.open(
            name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
            dir_fd=parent,
        )
        meta = os.fstat(descriptor)
        identity = (meta.st_dev, meta.st_ino)
        view = memoryview(data)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OperationFailure("operation_metadata_partial_write")
            view = view[written:]
        os.fsync(descriptor)
        if not exclusive:
            os.replace(name, path.name, src_dir_fd=parent, dst_dir_fd=parent)
        os.fsync(parent)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if not exclusive and identity:
            try:
                meta = os.stat(name, dir_fd=parent, follow_symlinks=False)
                if (meta.st_dev, meta.st_ino) == identity:
                    os.unlink(name, dir_fd=parent)
            except FileNotFoundError:
                pass
        os.close(parent)


def _metadata_read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(_read_bounded(path, mode=0o600))
    except (ValueError, TypeError, UnicodeError):
        raise OperationFailure("operation_metadata_shape") from None
    if not isinstance(value, dict):
        raise OperationFailure("operation_metadata_shape")
    return value


def _publish_handle(path: Path, handle: dict[str, Any]) -> None:
    try:
        _metadata_write(path, handle, exclusive=True)
    except FileExistsError:
        if _metadata_read(path) != handle:
            raise OperationFailure("original_handle_collision", unknown=True) from None


def _resource_lock(*, blocking: bool = False) -> int:
    import fcntl

    parent = _open_directory(OPERATION_ROOT)
    try:
        descriptor = os.open(
            "resource.lock",
            os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
            dir_fd=parent,
        )
    finally:
        os.close(parent)
    meta = os.fstat(descriptor)
    if (
        meta.st_uid != EXPECTED_UID
        or meta.st_gid != EXPECTED_GID
        or not stat.S_ISREG(meta.st_mode)
        or stat.S_IMODE(meta.st_mode) != 0o600
        or meta.st_nlink != 1
    ):
        os.close(descriptor)
        raise OperationFailure("resource_lock_ownership")
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
    except BlockingIOError:
        os.close(descriptor)
        raise OperationFailure("probe_resource_owned_by_original_operation", unknown=True) from None
    return descriptor


def _original_successor_precondition() -> dict[str, Any]:
    """Read the exact legacy evidence; historical acceptance is never a grant.

    Call with the existing resource.lock held. The legacy active selector and
    operation directory remain immutable, including their honest UNKNOWN result.
    """
    active = _read_bounded(OPERATION_ROOT / "active.json", mode=0o600)
    if active != _json_bytes(
        {"operation": ORIGINAL_OPERATION, "request_sha256": ORIGINAL_REQUEST_SHA256}
    ):
        raise OperationFailure("successor_original_fence_unqualified", unknown=True)
    root = OPERATION_ROOT / ORIGINAL_OPERATION
    _owned_directory(root)
    if any(
        path.name == "reconcile.json" or path.name.startswith("reconcile-")
        for path in root.iterdir()
    ):
        raise OperationFailure("successor_original_continuation_present", unknown=True)
    for name, expected in ORIGINAL_FILE_SHA256.items():
        if hashlib.sha256(_read_bounded(root / name, mode=0o600)).hexdigest() != expected:
            raise OperationFailure("successor_original_evidence_changed", unknown=True)
    original = _status(ORIGINAL_OPERATION, ORIGINAL_REQUEST_SHA256)
    if not (
        original.get("status") == "unknown"
        and original.get("phase") == "start_intent"
        and original.get("failure") == "main_process_boundary"
        and original.get("supervisor", {}).get("reaped") is True
        and original.get("supervisor", {}).get("cgroup_empty") is True
        and original.get("supervisor", {}).get("reconciliation") is False
    ):
        raise OperationFailure("successor_original_not_quiescent_unknown", unknown=True)
    return {"operation": ORIGINAL_OPERATION, "request_sha256": ORIGINAL_REQUEST_SHA256}


def _rendering_current_state(before_manifest: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Fresh observation for the new operation; it does not adopt the old start."""
    original = _original_successor_precondition()
    if _manifest_digest(before_manifest) != MANIFEST_SHA256:
        raise OperationFailure("successor_before_manifest_binding")
    _target_and_consumers()
    _guard_source(before_manifest)
    identity = _active_identity(_unit_fields())
    _additional_consumers(identity["cgroup"])
    return {
        "predecessor": original,
        "identity": identity,
        "incident": _incident_snapshot(),
        "before_manifest_sha256": MANIFEST_SHA256,
        "after_manifest_sha256": RENDERING_MANIFEST_SHA256,
        "configuration_sha256": CONFIG_SHA256,
        "unit_sha256": UNIT_SHA256,
    }


def _same_resource_lock(descriptor: int) -> None:
    parent = _open_directory(OPERATION_ROOT)
    try:
        named = os.stat("resource.lock", dir_fd=parent, follow_symlinks=False)
        held = os.fstat(descriptor)
        if _signature(named) != _signature(held) or held.st_nlink != 1:
            raise OperationFailure("successor_shared_lock_changed", unknown=True)
    finally:
        os.close(parent)


def _selector(request: dict[str, Any]) -> Path:
    # The old selector is never overwritten by the successor. Both protocols
    # still acquire the same physical resource.lock, including old pinned code.
    return OPERATION_ROOT / (
        "rendering-successor.json"
        if "installation_authority" in request["packet"]
        else "active.json"
    )


def _selection(request: dict[str, Any], request_sha: str) -> dict[str, Any]:
    selected = {"operation": request["packet"]["operation"], "request_sha256": request_sha}
    if "installation_authority" in request["packet"]:
        root = OPERATION_ROOT / selected["operation"]
        admission = _metadata_read(root / "admission.json")
        if (
            set(admission) != {"request_sha256", "resource", "current_state"}
            or admission["request_sha256"] != request_sha
            or not isinstance(admission["resource"], dict)
            or set(admission["resource"]) != {"device", "inode"}
            or any(type(item) is not int or item <= 0 for item in admission["resource"].values())
            or not isinstance(admission["current_state"], dict)
            or set(admission["current_state"])
            != {
                "predecessor",
                "identity",
                "incident",
                "before_manifest_sha256",
                "after_manifest_sha256",
                "configuration_sha256",
                "unit_sha256",
            }
            or admission["current_state"]["predecessor"]
            != {
                "operation": ORIGINAL_OPERATION,
                "request_sha256": ORIGINAL_REQUEST_SHA256,
            }
            or admission["current_state"]["before_manifest_sha256"] != MANIFEST_SHA256
            or admission["current_state"]["after_manifest_sha256"] != RENDERING_MANIFEST_SHA256
            or admission["current_state"]["configuration_sha256"] != CONFIG_SHA256
            or admission["current_state"]["unit_sha256"] != UNIT_SHA256
            or not isinstance(admission["current_state"]["identity"], dict)
            or not isinstance(admission["current_state"]["incident"], dict)
        ):
            raise OperationFailure("successor_admission_shape", unknown=True)
        selected["admission_sha256"] = hashlib.sha256(_json_bytes(admission)).hexdigest()
    return selected


def _rendering_resource_guard(request: dict[str, Any], request_sha: str, lock: int) -> None:
    _same_resource_lock(lock)
    _original_successor_precondition()
    if _json_bytes(_metadata_read(_selector(request))) != _json_bytes(
        _selection(request, request_sha)
    ):
        raise OperationFailure("successor_resource_ownership", unknown=True)
    admission = _metadata_read(OPERATION_ROOT / request["packet"]["operation"] / "admission.json")
    held = os.fstat(lock)
    if admission["resource"] != {"device": held.st_dev, "inode": held.st_ino}:
        raise OperationFailure("successor_shared_lock_changed", unknown=True)


def _rendering_entry_guard(request: dict[str, Any], request_sha: str, lock: int) -> dict[str, Any]:
    _rendering_resource_guard(request, request_sha, lock)
    admission = _metadata_read(OPERATION_ROOT / request["packet"]["operation"] / "admission.json")
    current = _rendering_current_state(request["before_manifest"])
    if _identity_key(current["identity"]) != _identity_key(admission["current_state"]["identity"]):
        raise OperationFailure("successor_normal_invocation_changed", unknown=True)
    return admission["current_state"]["identity"]


def _operation_name(operation: str) -> str:
    if not isinstance(operation, str) or not re.fullmatch(r"[0-9a-f]{32}", operation):
        raise OperationFailure("operation_handle_shape")
    return "yggdrasil-probe-upgrade-6457-" + operation + ".service"


def _boot_id() -> str:
    value = _proc_bytes(PROC_ROOT / "sys/kernel/random/boot_id", 64).decode().strip()
    if not re.fullmatch(r"[0-9a-f-]{36}", value):
        raise OperationFailure("boot_identity")
    return value


def _program_files(request: dict[str, Any], root: Path) -> None:
    for name, digest in request["program_sha256"].items():
        if name not in {"probe_script_swap_core.py", "probe_upgrade_operation.py", "worker.py"}:
            raise OperationFailure("operation_program_path")
        if hashlib.sha256(_read_bounded(root / name, mode=0o600)).hexdigest() != digest:
            raise OperationFailure("operation_program_changed")


def _request_parts(request: dict[str, Any]) -> tuple[dict[str, Any], bytes, bytes]:
    import base64

    if set(request) != {
        "packet",
        "before_manifest",
        "after_manifest",
        "old_base64",
        "new_base64",
        "program_sha256",
        "contract_body_sha256",
        "lease_expires_at",
    }:
        raise OperationFailure("operation_request_shape")
    packet = _parse_packet(request["packet"])
    try:
        expiry = datetime.fromisoformat(request["lease_expires_at"].replace("Z", "+00:00"))
        if expiry.tzinfo is None:
            raise ValueError("naive expiry")
    except (ValueError, TypeError, AttributeError):
        raise OperationFailure("operation_claim_expiry") from None
    rendering = "installation_authority" in packet
    body_sha = packet["installation_authority"]["body_sha256"] if rendering else BODY_SHA256
    if request["contract_body_sha256"] != body_sha or set(request["program_sha256"]) != {
        "probe_script_swap_core.py",
        "probe_upgrade_operation.py",
        "worker.py",
    }:
        raise OperationFailure("operation_contract_binding")
    try:
        old = base64.b64decode(request["old_base64"], validate=True)
        new = base64.b64decode(request["new_base64"], validate=True)
    except (ValueError, TypeError):
        raise OperationFailure("operation_source_encoding") from None
    old_sha, new_sha, manifest_sha = _script_binding(packet)
    if hashlib.sha256(old).hexdigest() != old_sha or hashlib.sha256(new).hexdigest() != new_sha:
        raise OperationFailure("operation_source_binding")
    if rendering:
        _validate_manifest(request["before_manifest"])
        _validate_manifest(request["after_manifest"])
        if (
            _manifest_digest(request["before_manifest"]) != MANIFEST_SHA256
            or _manifest_digest(request["after_manifest"]) != manifest_sha
        ):
            raise OperationFailure("successor_request_manifest_binding")
    return packet, old, new


def _supervisor_fields(operation: str) -> dict[str, str]:
    keys = "LoadState,ActiveState,SubState,MainPID,InvocationID,ControlGroup,Job,Transient,User,Group,ExecStart,WorkingDirectory,RuntimeMaxUSec,TimeoutStopUSec,KillMode,Restart,StandardOutput,StandardError"
    raw = _safe_command(
        [
            "/usr/bin/systemctl",
            "show",
            _operation_name(operation),
            "--property=" + keys,
            "--no-pager",
        ],
        timeout=5.0,
    )
    fields: dict[str, str] = {}
    for line in raw.splitlines():
        key, separator, value = line.partition("=")
        if not separator or key in fields:
            raise OperationFailure("supervisor_projection")
        fields[key] = value
    return fields


def _duration_seconds(value: str) -> float:
    scales = {"us": 0.000001, "ms": 0.001, "s": 1, "min": 60}
    parts = re.findall(r"(\d+(?:\.\d+)?)(us|ms|min|s)", value)
    if not parts or " ".join(a + b for a, b in parts) != value:
        raise OperationFailure("supervisor_duration")
    return sum(float(number) * scales[unit] for number, unit in parts)


def _supervisor_handle(operation: str, request_sha: str, fields: dict[str, str]) -> dict[str, Any]:
    root = OPERATION_ROOT / operation
    expected = f"{INTERPRETER} -I -B {root / 'worker.py'} {operation}"
    if not (
        fields.get("LoadState") == "loaded"
        and fields.get("Transient") == "yes"
        and fields.get("User") == fields.get("Group") == "root"
        and fields.get("WorkingDirectory") == str(root)
        and ("argv[]=" + expected + " ;") in fields.get("ExecStart", "")
        and fields.get("ExecStart", "").count("argv[]=") == 1
        and _duration_seconds(fields.get("RuntimeMaxUSec", "")) == RUNTIME_SECONDS
        and _duration_seconds(fields.get("TimeoutStopUSec", "")) == 5
        and fields.get("KillMode") == "control-group"
        and fields.get("Restart") == "no"
        and fields.get("StandardOutput") == fields.get("StandardError") == "null"
        and fields.get("ActiveState") == "active"
        and fields.get("SubState") == "running"
        and re.fullmatch(r"[0-9a-f]{32}", fields.get("InvocationID", ""))
        and fields.get("ControlGroup", "").endswith("/" + _operation_name(operation))
    ):
        raise OperationFailure("finite_supervisor_unqualified", unknown=True)
    process = _pid_metadata(fields["MainPID"])
    if (
        process["uid"] != EXPECTED_UID
        or process["cgroup"] != fields["ControlGroup"]
        or Path(process["exe"]).resolve() != INTERPRETER.resolve()
    ):
        raise OperationFailure("supervisor_process_boundary", unknown=True)
    command = _proc_bytes(PROC_ROOT / process["pid"] / "cmdline").split(b"\0")[:-1]
    if command != [
        str(INTERPRETER).encode(),
        b"-I",
        b"-B",
        str(root / "worker.py").encode(),
        operation.encode(),
    ] or process["cwd"] != str(root):
        raise OperationFailure("supervisor_actual_entry_boundary", unknown=True)
    return {
        "operation": operation,
        "request_sha256": request_sha,
        "unit": _operation_name(operation),
        "invocation": fields["InvocationID"],
        "pid": process["pid"],
        "start_ticks": process["start_ticks"],
        "cgroup": process["cgroup"],
        "boot_id": _boot_id(),
    }


def _reaped(handle: dict[str, Any], fields: dict[str, str]) -> bool:
    if handle["boot_id"] != _boot_id():
        raise OperationFailure("supervisor_boot_changed", unknown=True)
    if (
        fields.get("ActiveState") not in {"inactive", "failed"}
        or fields.get("MainPID") != "0"
        or fields.get("Job") not in {"", "0"}
    ):
        return False
    if _cgroup_members(handle["cgroup"]):
        return False
    try:
        process = _pid_metadata(handle["pid"])
    except (FileNotFoundError, ProcessLookupError):
        return True
    if process["start_ticks"] == handle["start_ticks"]:
        return False
    return True  # A reused PID is a different process, never ours to stop.


def _reconciliation(
    root: Path, original: dict[str, Any], request_sha: str
) -> dict[str, Any] | None:
    """Read the current immutable continuation, retaining every earlier one."""
    try:
        pointer = _metadata_read(root / "reconcile.json")
    except FileNotFoundError:
        return None
    generation = pointer.get("generation")
    if (
        set(pointer) != {"generation", "permission_sha256"}
        or type(generation) is not int
        or generation <= 0
    ):
        raise OperationFailure("reconciliation_pointer_changed", unknown=True)
    permission = _metadata_read(root / f"reconcile-{generation}.json")
    if (
        hashlib.sha256(_json_bytes(permission)).hexdigest() != pointer["permission_sha256"]
        or set(permission)
        != {"generation", "original_invocation", "request_sha256", "previous_handle", "context"}
        or permission["generation"] != generation
        or permission["original_invocation"] != original["invocation"]
        or permission["request_sha256"] != request_sha
        or not isinstance(permission["previous_handle"], dict)
        or permission["previous_handle"].get("operation") != original["operation"]
        or permission["previous_handle"].get("request_sha256") != request_sha
        or any(
            permission["previous_handle"].get(key) != original[key]
            for key in ("unit", "cgroup", "boot_id")
        )
        or (generation == 1 and permission["previous_handle"] != original)
        or not isinstance(permission["context"], dict)
        or permission["context"].get("operation") != original["operation"]
    ):
        raise OperationFailure("reconciliation_lineage_changed", unknown=True)
    return permission


def _reconcile_file(root: Path, permission: dict[str, Any], kind: str) -> Path:
    return root / f"reconcile-{permission['generation']}-{kind}.json"


def _latest_context(root: Path, permission: dict[str, Any] | None) -> dict[str, Any]:
    if permission is None:
        return _metadata_read(root / "phase.json")
    try:
        return _metadata_read(_reconcile_file(root, permission, "phase"))
    except FileNotFoundError:
        return permission["context"]


def _status(operation: str, request_sha: str) -> dict[str, Any]:
    root = OPERATION_ROOT / operation
    request = _metadata_read(root / "request.json")
    if hashlib.sha256(_json_bytes(request)).hexdigest() != request_sha:
        raise OperationFailure("original_request_changed", unknown=True)
    _program_files(request, root)
    fields = _supervisor_fields(operation)
    try:
        handle = _metadata_read(root / "handle.json")
    except FileNotFoundError:
        handle = _supervisor_handle(operation, request_sha, fields)
    if handle["operation"] != operation or handle["request_sha256"] != request_sha:
        raise OperationFailure("original_handle_changed", unknown=True)
    original = handle
    permission = _reconciliation(root, original, request_sha)
    recovery = permission is not None
    if permission is not None:
        try:
            handle = _metadata_read(_reconcile_file(root, permission, "handle"))
        except FileNotFoundError:
            # A worker must publish its handle before any probe effect. A lost
            # helper-start ACK cannot authorize replay while that unit is live.
            if fields.get("ActiveState") == "active":
                current = _supervisor_handle(operation, request_sha, fields)
                if current == permission["previous_handle"]:
                    raise OperationFailure("reconciliation_previous_worker_live", unknown=True)
                reaped = False
            else:
                reaped = _reaped(permission["previous_handle"], fields)
            return {
                "schema": "probe_installation.v1",
                "operation": operation,
                "status": "unknown" if reaped else "pending",
                "phase": "reconciliation_authorized",
                "handle": original,
                "failure": "reconciliation_ended_before_handle" if reaped else None,
                "supervisor": {"reaped": reaped, "cgroup_empty": reaped, "reconciliation": True},
            }
    result_file = (
        _reconcile_file(root, permission, "result")
        if permission is not None
        else root / "result.json"
    )
    if (
        handle.get("operation") != operation
        or handle.get("request_sha256") != request_sha
        or handle.get("unit") != _operation_name(operation)
    ):
        raise OperationFailure("reconciliation_handle_changed", unknown=True)
    try:
        result = _metadata_read(result_file)
    except FileNotFoundError:
        result = None
    if fields.get("ActiveState") == "active":
        current = _supervisor_handle(operation, request_sha, fields)
        if current != handle:
            raise OperationFailure("foreign_supervisor_incarnation", unknown=True)
    elif fields.get("LoadState") == "loaded" and fields.get("InvocationID") not in {
        handle["invocation"],
        "",
        "0" * 32,
    }:
        raise OperationFailure("foreign_supervisor_incarnation", unknown=True)
    reaped = _reaped(handle, fields)
    if result is not None and reaped:
        if (
            result.get("operation") != operation
            or result.get("request_sha256") != request_sha
            or result.get("worker_invocation") != handle["invocation"]
        ):
            raise OperationFailure("terminal_result_binding", unknown=True)
        return {
            **result,
            "handle": original,
            "supervisor": {
                "unit": handle["unit"],
                "runtime_max_seconds": RUNTIME_SECONDS,
                "reaped": True,
                "cgroup_empty": True,
                "reconciliation": recovery,
            },
        }
    phase = _latest_context(root, permission)
    return {
        "schema": "probe_installation.v1",
        "operation": operation,
        "status": "unknown" if reaped else "pending",
        "phase": phase.get("phase"),
        "failure": "missing_terminal_result" if reaped else None,
        "handle": original,
        "supervisor": {"reaped": reaped, "cgroup_empty": reaped, "reconciliation": recovery},
    }


def _launch_supervisor(operation: str) -> None:
    root = OPERATION_ROOT / operation
    argv = [
        "/usr/bin/systemd-run",
        "--quiet",
        "--unit=" + _operation_name(operation),
        "--service-type=exec",
        "--uid=root",
        "--gid=root",
    ]
    properties = {
        "RuntimeMaxSec": str(RUNTIME_SECONDS),
        "TimeoutStopSec": "5",
        "KillMode": "control-group",
        "Restart": "no",
        "StandardOutput": "null",
        "StandardError": "null",
        "UMask": "0077",
        "WorkingDirectory": str(root),
        "NoNewPrivileges": "yes",
        "PrivateTmp": "yes",
        "PrivateDevices": "yes",
        "ProtectSystem": "strict",
        "ReadWritePaths": str(SCRIPT.parent) + " " + str(OPERATION_ROOT),
        "RestrictAddressFamilies": "AF_UNIX",
        "ProtectControlGroups": "yes",
        "ProtectKernelTunables": "yes",
        "ProtectKernelModules": "yes",
    }
    argv += ["--property=" + key + "=" + value for key, value in properties.items()]
    argv += [
        "--setenv=PATH=/usr/sbin:/usr/bin:/sbin:/bin",
        "--setenv=LC_ALL=C",
        "--",
        str(INTERPRETER),
        "-I",
        "-B",
        str(root / "worker.py"),
        operation,
    ]
    _safe_command(argv, timeout=20.0, effect=True)


def remote_entry(
    action: str,
    request: dict[str, Any],
    *,
    programs: dict[str, bytes] | None = None,
    expected_handle: dict[str, Any] | None = None,
) -> dict[str, Any]:
    packet, _, _ = _request_parts(request)
    operation = packet["operation"]
    rendering = "installation_authority" in packet
    request_sha = hashlib.sha256(_json_bytes(request)).hexdigest()
    root = OPERATION_ROOT / operation
    if (
        platform.system() != "Linux"
        or os.geteuid() != EXPECTED_UID
        or Path(sys.executable).resolve() != INTERPRETER.resolve()
    ):
        raise OperationFailure("operation_host_identity")
    if action == "status":
        _owned_directory(OPERATION_ROOT)
        _owned_directory(root)
        return _status(operation, request_sha)
    if action not in {"prepare", "authorize", "reconcile"}:
        raise OperationFailure("operation_action")
    if action == "prepare" and datetime.fromisoformat(
        request["lease_expires_at"].replace("Z", "+00:00")
    ) <= datetime.now(timezone.utc):
        raise OperationFailure("operation_claim_expired")
    _owned_directory(OPERATION_ROOT, create=action == "prepare" and not rendering)
    lock = _resource_lock()
    try:
        if action == "prepare":
            selector = _selector(request)
            try:
                active = _metadata_read(selector)
            except FileNotFoundError:
                active = None
            if rendering and root.exists():
                return _status(operation, request_sha)  # Follow the frozen request; never replay.
            expected = {"operation": operation, "request_sha256": request_sha}
            if rendering and active is None:
                # A genuinely first selector has no earlier successor namespace.
                # A lost pointer after any attempt is ambiguous, never a new ID.
                if any(
                    path.name not in {ORIGINAL_OPERATION, "active.json", "resource.lock"}
                    for path in OPERATION_ROOT.iterdir()
                ):
                    raise OperationFailure("successor_selection_missing_with_history", unknown=True)
            if rendering and active is not None:
                if (
                    set(active) != {"operation", "request_sha256", "admission_sha256"}
                    or not isinstance(active.get("operation"), str)
                    or not re.fullmatch(r"[0-9a-f]{32}", active["operation"])
                    or any(
                        not isinstance(active[key], str)
                        or not re.fullmatch(r"[0-9a-f]{64}", active[key])
                        for key in ("request_sha256", "admission_sha256")
                    )
                ):
                    raise OperationFailure("successor_previous_selection_unqualified", unknown=True)
                previous_request = _metadata_read(
                    OPERATION_ROOT / active["operation"] / "request.json"
                )
                previous_packet, _, _ = _request_parts(previous_request)
                if "installation_authority" not in previous_packet or _json_bytes(
                    active
                ) != _json_bytes(_selection(previous_request, active["request_sha256"])):
                    raise OperationFailure("successor_previous_selection_unqualified", unknown=True)
            same_request = active == expected
            if rendering:
                same_request = (
                    active is not None
                    and active.get("operation") == operation
                    and active.get("request_sha256") == request_sha
                )
            has_predecessor = active is not None if rendering else bool(active)
            if has_predecessor and not same_request:
                previous = _status(active["operation"], active["request_sha256"])
                if previous["status"] not in {"refused", "rolled_back"} or not previous.get(
                    "supervisor", {}
                ).get("reaped"):
                    raise OperationFailure(
                        "original_operation_unresolved_or_committed", unknown=True
                    )
            if root.exists():
                return _status(operation, request_sha)
            admission = None
            if rendering:
                _same_resource_lock(lock)
                current = _rendering_current_state(request["before_manifest"])
                held = os.fstat(lock)
                admission = {
                    "request_sha256": request_sha,
                    "resource": {"device": held.st_dev, "inode": held.st_ino},
                    "current_state": current,
                }
            if programs is None or set(programs) != set(request["program_sha256"]):
                raise OperationFailure("operation_program_set")
            for name, data in programs.items():
                if hashlib.sha256(data).hexdigest() != request["program_sha256"][name]:
                    raise OperationFailure("operation_program_binding")
            _owned_directory(root, create=True)
            _metadata_write(root / "request.json", request, exclusive=True)
            for name, data in programs.items():
                descriptor = os.open(
                    root / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
                )
                try:
                    view = memoryview(data)
                    while view:
                        written = os.write(descriptor, view)
                        if written <= 0:
                            raise OperationFailure("operation_program_partial_write")
                        view = view[written:]
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
            _program_files(request, root)
            if admission is not None:
                _metadata_write(root / "admission.json", admission, exclusive=True)
            _metadata_write(
                selector,
                _selection(request, request_sha),
                exclusive=active is None,
            )
            _metadata_write(
                root / "phase.json",
                {"operation": operation, "phase": "prepared", "boot_id": _boot_id()},
                exclusive=True,
            )
            _launch_supervisor(operation)
            handle = _supervisor_handle(operation, request_sha, _supervisor_fields(operation))
            _publish_handle(root / "handle.json", handle)
            return {
                "schema": "probe_installation.v1",
                "operation": operation,
                "status": "pending",
                "phase": "prepared",
                "handle": handle,
            }
        _owned_directory(root)
        active = _metadata_read(_selector(request))
        if _json_bytes(active) != _json_bytes(_selection(request, request_sha)):
            raise OperationFailure("original_resource_handle_mismatch", unknown=True)
        status = _status(operation, request_sha)
        if expected_handle != status["handle"]:
            raise OperationFailure("original_handle_required", unknown=True)
        if action == "authorize":
            if status["status"] in {"committed", "rolled_back", "refused", "unknown"}:
                return status
            if rendering:
                _rendering_entry_guard(request, request_sha, lock)
            fields = _supervisor_fields(operation)
            if _supervisor_handle(operation, request_sha, fields) != expected_handle:
                raise OperationFailure("authorization_incarnation_changed", unknown=True)
            try:
                _metadata_read(root / "go.json")
            except FileNotFoundError:
                _metadata_write(
                    root / "go.json",
                    {"request_sha256": request_sha, "invocation": expected_handle["invocation"]},
                    exclusive=True,
                )
            return status
        if status["status"] in {"committed", "rolled_back", "refused"}:
            return status
        if not status.get("supervisor", {}).get("reaped"):
            return status
        if rendering:
            _rendering_resource_guard(request, request_sha, lock)
        permission = _reconciliation(root, expected_handle, request_sha)
        context = _latest_context(root, permission)
        fields = _unit_fields()
        if ("recovery_start_intent_usec" in context and not context.get("restored_identity")) or (
            "start_intent_usec" in context
            and not context.get("new_identity")
            and fields.get("ActiveState") == "active"
        ):
            return {**status, "recovery_failure": "original_start_ownership_unproven"}
        previous_handle = expected_handle
        if permission is not None:
            try:
                previous_handle = _metadata_read(_reconcile_file(root, permission, "handle"))
            except FileNotFoundError:
                previous_handle = permission["previous_handle"]
        generation = 1 if permission is None else permission["generation"] + 1
        continuation = {
            "generation": generation,
            "original_invocation": expected_handle["invocation"],
            "request_sha256": request_sha,
            "previous_handle": previous_handle,
            "context": context,
        }
        # Every explicit continuation is finite and starts from the latest
        # durable phase after reap. Earlier permission/phase/result files stay.
        continuation_file = root / f"reconcile-{generation}.json"
        try:
            _metadata_write(continuation_file, continuation, exclusive=True)
        except FileExistsError:
            # The immutable record may have reached disk before the selector.
            # Complete only this exact original-handle publication under the
            # resource lock; unequal/foreign records are never overwritten.
            try:
                matches = _read_bounded(continuation_file, mode=0o600) == _json_bytes(continuation)
            except (OperationFailure, OSError):
                matches = False
            if not matches:
                raise OperationFailure(
                    "reconciliation_permission_collision", unknown=True
                ) from None
        _metadata_write(
            root / "reconcile.json",
            {
                "generation": generation,
                "permission_sha256": hashlib.sha256(_json_bytes(continuation)).hexdigest(),
            },
            exclusive=permission is None,
        )
        fields = _supervisor_fields(operation)
        if fields.get("LoadState") == "not-found":
            _launch_supervisor(operation)
        else:
            _safe_command(
                ["/usr/bin/systemctl", "start", _operation_name(operation)],
                timeout=20.0,
                effect=True,
            )
        return {
            "schema": "probe_installation.v1",
            "operation": operation,
            "status": "pending",
            "phase": "reconciliation_authorized",
            "handle": expected_handle,
        }
    finally:
        os.close(lock)


def worker_main(operation: str) -> int:
    _operation_name(operation)
    root = OPERATION_ROOT / operation
    _owned_directory(root)
    request = _metadata_read(root / "request.json")
    packet, old_bytes, new_bytes = _request_parts(request)
    rendering = "installation_authority" in packet
    request_sha = hashlib.sha256(_json_bytes(request)).hexdigest()
    if packet["operation"] != operation:
        raise OperationFailure("worker_operation_binding")
    _program_files(request, root)
    handle = _supervisor_handle(operation, request_sha, _supervisor_fields(operation))
    if handle["pid"] != str(os.getpid()) or handle["invocation"] != os.environ.get("INVOCATION_ID"):
        raise OperationFailure("worker_incarnation_binding")
    try:
        original = _metadata_read(root / "handle.json")
    except FileNotFoundError:
        original = handle  # The initial worker may win the preparer's publish race.
    permission = _reconciliation(root, original, request_sha)
    recovery = permission is not None
    phase_file = (
        _reconcile_file(root, permission, "phase")
        if permission is not None
        else root / "phase.json"
    )
    result_file = (
        _reconcile_file(root, permission, "result")
        if permission is not None
        else root / "result.json"
    )
    if result_file.exists():
        return 78
    if recovery:
        assert permission is not None
        if (
            handle["invocation"] == original["invocation"]
            or handle["invocation"] == permission["previous_handle"]["invocation"]
        ):
            raise OperationFailure("recovery_worker_lineage")
        _publish_handle(_reconcile_file(root, permission, "handle"), handle)
        context = dict(permission["context"])
        _metadata_write(phase_file, context, exclusive=True)
    else:
        if original != handle:
            raise OperationFailure("worker_replay_or_foreign_incarnation")
        _publish_handle(root / "handle.json", handle)
        context = {"operation": operation, "phase": "waiting_for_authorization"}
        _metadata_write(phase_file, context)
        deadline = time.monotonic() + 30.0
        while True:
            try:
                permission = _metadata_read(root / "go.json")
                break
            except FileNotFoundError:
                if time.monotonic() >= deadline:
                    result = {
                        "schema": "probe_installation.v1",
                        "operation": operation,
                        "status": "refused",
                        "failure": "authorization_not_received",
                        "probe_effect": False,
                        "request_sha256": request_sha,
                        "worker_invocation": handle["invocation"],
                    }
                    _metadata_write(result_file, result, exclusive=True)
                    return 78
                time.sleep(0.1)
        if permission != {"request_sha256": request_sha, "invocation": handle["invocation"]}:
            raise OperationFailure("worker_authorization_binding")
        if datetime.fromisoformat(
            request["lease_expires_at"].replace("Z", "+00:00")
        ) <= datetime.now(timezone.utc):
            raise OperationFailure("worker_claim_expired")
    lock = _resource_lock(blocking=True)
    try:
        if _json_bytes(_metadata_read(_selector(request))) != _json_bytes(
            _selection(request, request_sha)
        ):
            raise OperationFailure("worker_resource_ownership")

        def resource_guard() -> None:
            _rendering_resource_guard(request, request_sha, lock)

        def journal(value: dict[str, Any]) -> None:
            _metadata_write(phase_file, value)

        def deadline_signal(_signum, _frame):
            raise OperationFailure("finite_worker_deadline", unknown=True)

        signal.signal(signal.SIGALRM, deadline_signal)
        signal.alarm(90 if recovery else 300)
        try:
            admitted_identity = None
            if rendering and not recovery:
                admitted_identity = _rendering_entry_guard(request, request_sha, lock)
            if recovery:
                result = _recover(
                    context,
                    before_manifest=request["before_manifest"],
                    after_manifest=request["after_manifest"],
                    old_bytes=old_bytes,
                    journal=journal,
                    operation_hex=operation,
                    rendering=rendering,
                    resource_guard=resource_guard if rendering else None,
                )
                result.update(
                    schema="probe_installation.v1", operation=operation, test_acceptance=False
                )
            else:
                result = run(
                    packet,
                    before_manifest=request["before_manifest"],
                    after_manifest=request["after_manifest"],
                    old_bytes=old_bytes,
                    new_bytes=new_bytes,
                    journal=journal,
                    resource_guard=resource_guard if rendering else None,
                    admitted_identity=admitted_identity,
                )
        except BaseException as error:
            result = {
                "schema": "probe_installation.v1",
                "operation": operation,
                "status": "unknown",
                "failure": error.reason
                if isinstance(error, OperationFailure)
                else "worker_unhandled_failure",
                "test_acceptance": False,
            }
        finally:
            signal.alarm(0)
        result.update(request_sha256=request_sha, worker_invocation=handle["invocation"])
        if rendering:
            result["successor"] = {
                "source_issue": RENDERING_SOURCE_ISSUE,
                "source_contract_body_sha256": RENDERING_SOURCE_BODY_SHA256,
                "installation_authority": packet["installation_authority"],
                "program_sha256": request["program_sha256"],
                "admission_sha256": _selection(request, request_sha)["admission_sha256"],
                "original_operation": ORIGINAL_OPERATION,
                "original_request_sha256": ORIGINAL_REQUEST_SHA256,
                "original_status_required": "unknown",
            }
        _metadata_write(result_file, result, exclusive=True)
        return 0
    finally:
        os.close(lock)


if __name__ == "__main__":
    print('{"schema":"probe_installation.v1","armed":false}')
    raise SystemExit(78)
