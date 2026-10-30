"""BWS-only caller reservation for one public-source installation.

Supported RPC callers hold a shared reservation for the full request. The fixed
installation operation holds the exclusive reservation until its exact terminal
receipt is durable. A non-empty owner marker after interruption is a refusal;
it is never adopted, cleared, or replayed.

This is deliberately limited to the existing DEV/TEST BWS launcher boundary.
It does not qualify a channel, prove the process census, or authorize effects.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import time
from typing import Callable, Iterator, NoReturn, cast
from uuid import UUID

_RECEIPT_DIRECTORY = Path("/var/lib/yggdrasil/bws-deploy-convergence")
# Keep the owner marker beside its durable receipt namespace. A reboot releases
# flock ownership but must not erase an unfinished transaction's refusal state.
_RUNTIME_DIRECTORY = _RECEIPT_DIRECTORY
_OWNER_SCHEMA = "bws-source-installation-owner.v2"
_START_AUTHORIZATION_SCHEMA = "bws-source-installation-start.v1"
_RECEIPT_SCHEMA = "agentic-pkm.bws-source-installation-receipt.v1"
_OWNER_UID = 0
_OWNER_GID = 0
_FIXED_LAUNCHER = Path("/usr/local/libexec/yggdrasil-bws-deploy")
_FIXED_RUNTIME = Path("/opt/yggdrasil/bws-deploy-runtime/bin/python3")
_GLOBAL_LOCK = "source-installation-global.lock"
_CANDIDATE_CLEAN_PATHS = ("app", "scripts", "config/secrets/host_secret_contract.json")
_VERIFIED_CANDIDATE_ENTRYPOINT = "_yggdrasil_bws_verified_candidate_entrypoint"
_PROC = Path("/proc")
_START_CONSUMPTION_TIMEOUT_SECONDS = 30.0
_START_CONSUMPTION_POLL_SECONDS = 0.1
_RECEIPT_STATUSES = frozenset({
    "installed",
    "compensated_restored",
    "compensated_stopped",
    "refused_before_backup",
    "refused_before_stop",
    "unknown",
})
# Closed static contexts; no native values participate in these combinations.
# Kept local at both existing receipt boundaries to preserve source-loader import
# order. The parity test binds both copies to the real producer guard matrix.
_ROOT_CONTROL_PROJECTION_GUARDS = (
    "mapping_type", "fields", "path_type", "path_absolute", "path_canonical",
    "path_backslash", "path_nul", "device_type", "inode_type", "uid_type",
    "gid_type", "mode_type", "device_range", "inode_range", "uid", "gid", "mode",
)
_ROOT_CONTROL_DIRECTORY_GUARDS = (
    "open_unknown", "fstat_unknown", "directory_type", "owner_pair",
    "directory_mode", "inheritable_unknown", "inheritable",
)
_ROOT_CONTROL_CONTEXTS = (
    (("unknown", "captured_empty", "anchored_discovery"), ("unknown",),
     ("application", "control"), _ROOT_CONTROL_PROJECTION_GUARDS),
    (("captured_empty",), ("unknown", "old", "proposed"),
     ("expected_empty",), _ROOT_CONTROL_PROJECTION_GUARDS),
    (("captured_empty", "anchored_discovery"), ("unknown",),
     ("roots",), ("separation", "fixed_subtree")),
    (("captured_empty",), ("unknown",), ("roots",), ("empty_fixed_root",)),
    (("unknown",), ("unknown", "old", "proposed"), ("discovery",),
     ("decode_unknown", "environment_unknown", "environment_files_unknown")),
    (("captured_empty",), ("unknown", "old", "proposed"), ("discovery",),
     ("empty_decode_unknown", "empty_environment_unknown", "empty_environment_files_unknown")),
    (("anchored_discovery",), ("unknown", "old", "proposed"),
     ("discovery",), ("candidates_unknown",)),
    (("captured_empty", "anchored_discovery"), ("unknown", "old", "proposed"),
     ("discovery",), ("control_parts_unknown",)),
    (("captured_empty",), ("unknown", "old", "proposed"),
     ("hints",), ("launcher_hint", "environment_hint", "environment_files_hint")),
    (("anchored_discovery",), ("unknown", "old", "proposed"),
     ("hints",), ("candidate_count",)),
    (("captured_empty", "anchored_discovery"), ("unknown", "old", "proposed"),
     ("fixed_origin", "fixed_ancestor", "fixed_root", "candidate", "anchor_app", "anchor_ops"),
     _ROOT_CONTROL_DIRECTORY_GUARDS),
    (("captured_empty",), ("unknown", "old", "proposed"),
     ("reopen_origin", "reopen_ancestor", "reopen_root"), _ROOT_CONTROL_DIRECTORY_GUARDS),
    (("captured_empty", "anchored_discovery"), ("unknown", "old", "proposed"),
     ("anchor_app", "anchor_ops"), ("stat_unknown", "loader_symlink")),
    (("captured_empty", "anchored_discovery"), ("unknown", "old", "proposed"),
     ("anchor_file",), ("stat_unknown", "file_type", "uid", "gid", "file_mode", "link_count")),
    (("captured_empty", "anchored_discovery"), ("unknown", "old", "proposed"),
     ("candidate_projection",), ("fstat_unknown", "directory_type", "construction_unknown")),
    (("captured_empty",), ("unknown", "old", "proposed"),
     ("fixed_projection", "reopen_projection"), ("fstat_unknown", "directory_type", "construction_unknown")),
    (("captured_empty", "anchored_discovery"), ("unknown", "old", "proposed"),
     ("candidate",), ("components_unknown", "component_count", "components_canonical", "stat_unknown", "symlink")),
    (("captured_empty", "anchored_discovery"), ("unknown", "old", "proposed"),
     ("anchor_root",), ("fstat_unknown", "directory_mode")),
    (("captured_empty",), ("unknown", "old", "proposed"),
     ("empty_root",), ("identity", "anchored_root_present", "reopen_identity")),
    (("captured_empty",), ("unknown", "old", "proposed"),
     ("app_slot", "scripts_slot"), ("stat_unknown", "present")),
    (("anchored_discovery",), ("unknown", "old", "proposed"),
     ("anchored_roots",), ("no_anchor", "multiple_anchors")),
    (("captured_empty", "anchored_discovery"), ("old", "proposed"),
     ("comparison",), ("identity",)),
    (("unknown",), ("unknown",), ("revalidation",), ("phase",)),
    (("anchored_discovery",), ("unknown",), ("revalidation",), ("empty_required",)),
    (("captured_empty",), ("unknown",), ("revalidation",), ("contract_missing", "configuration")),
    (("captured_empty", "anchored_discovery"), ("unknown", "old", "proposed"),
     ("discovery_close",), ("close_unknown",)),
)
_ROOT_CONTROL_REFINEMENTS = frozenset(
    (mode, side, role, guard)
    for modes, sides, roles, guards in _ROOT_CONTROL_CONTEXTS
    for mode in modes for side in sides for role in roles for guard in guards
)
_ROOT_CONTROL_REFINEMENT_GATES = frozenset(
    "old_kernel_" + stage + "_root_control__" + "__".join(context)
    for stage in ("initial", "empty_control") for context in _ROOT_CONTROL_REFINEMENTS
)
# Source symbols only. Value cases are existing unit-property predicates;
# launcher/process/cleanup/root semantic refusals retain their own families.
_UNIT_PROPERTY_VALUE_SITES = frozenset(
    ('Unit_Id Unit_LoadState Unit_OnFailure Unit_OnSuccess Unit_TriggeredBy '
     'Service_Type Service_User Service_Group Service_KillMode Service_Restart '
     'Service_RootDirectory Service_RootImage Service_WorkingDirectory Service_BindPaths '
     'Service_BindReadOnlyPaths Service_TemporaryFileSystem Service_ReadOnlyPaths '
     'Service_ReadWritePaths Service_InaccessiblePaths Service_PassEnvironment '
     'Service_ExtensionDirectories Service_MountImages Service_ExtensionImages Service_PAMName '
     'Service_UnsetEnvironment Service_ExecSearchPath Service_PrivateMounts Service_PrivateTmp '
     'Service_PrivateDevices Service_PrivateUsers Service_DynamicUser Service_ProtectHome '
     'Service_ProtectSystem Unit_DropInPaths Unit_JoinsNamespaceOf').split()
)
_UNIT_PROPERTY_READ_SITES = _UNIT_PROPERTY_VALUE_SITES | frozenset(
    ('Manager_GetUnit Manager_GetUnitProcesses Service_ExecCondition Service_ExecStartPre '
     'Service_ExecStartPost Service_ExecStop Service_ExecReload Service_ExecStart '
     'Service_ExecStopPost Service_ExecStopPost_final Service_Environment Service_EnvironmentFiles '
     'Unit_ActiveState Unit_SubState Unit_Job Service_ControlPID Service_MainPID').split()
)
_UNIT_PROPERTY_REFINEMENTS = frozenset(
    (site, kind) for site in _UNIT_PROPERTY_READ_SITES
    for kind in ('backend', 'decode', 'signature', 'shape')
) | frozenset((site, 'value') for site in _UNIT_PROPERTY_VALUE_SITES)
_UNIT_PROPERTY_REFINEMENT_GATES = frozenset(
    'old_kernel_initial_unit_properties__' + '__'.join(context)
    for context in _UNIT_PROPERTY_REFINEMENTS
)
_PREBACKUP_REFUSAL_GATES = frozenset({
    "channel_lock_entry",
    "channel_owner_check",
    "caller_census",
    "current_writer_snapshot",
    "authority_cutover",
    "candidate_verification",
    "old_disk_state",
    "owner_launcher_profile",
    "backup_roots",
    "source_manifest",
    "descriptor_capacity",
    "descriptor_capacity_unknown",
    "descriptor_capacity_insufficient",
    "descriptor_capacity_ineligible",
    "descriptor_capacity_admission_refused",
    "candidate_profile",
    "old_kernel_qualification",
    "old_kernel_initial_setup",
    "old_kernel_initial_retained_runtime",
    "old_kernel_initial_unit_properties",
    "old_kernel_initial_root_control",
    "old_kernel_initial_launcher",
    "old_kernel_initial_service_process",
    "old_kernel_initial_cleanup_contract",
    "old_kernel_empty_control_retained_runtime",
    "old_kernel_empty_control_unit_properties",
    "old_kernel_empty_control_root_control",
    "old_kernel_empty_control_launcher",
    "old_kernel_empty_control_cleanup_contract",
    "qualified_writer_snapshot",
    "generation_qualification",
}) | _ROOT_CONTROL_REFINEMENT_GATES | _UNIT_PROPERTY_REFINEMENT_GATES
_ADMISSION_TERMINAL_STATUSES = frozenset({
    "installed", "compensated_restored", "refused_before_backup", "refused_before_stop",
})
_CLOEXEC = getattr(os, "O_CLOEXEC", 0)


class InstallationAdmissionRefused(Exception):
    """The BWS reservation or its terminal evidence is unknown."""


_SOURCE_INSTALLATION_RECONCILE_ACTION = "source-installation-reconcile"
_RECOVERY_REFUSAL_REASONS = frozenset({
    "request_binding", "runtime_state_missing", "global_lock_active", "channel_lock_active",
    "owner_missing", "owner_mismatch", "owner_invalid", "receipt_missing", "receipt_invalid",
    "lock_recheck_failed", "retirement_unproven",
})


def _refuse() -> NoReturn:
    raise InstallationAdmissionRefused("bws_installation_admission_refused") from None


def _sha256(value: object) -> bool:
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _receipt_generations(
    status: object, old: object, new: object, backup: object, *,
    prebackup_gate_present: bool = False, prebackup_gate: object = None,
) -> bool:
    if prebackup_gate_present and (
        status != "refused_before_backup" or type(prebackup_gate) is not str
        or prebackup_gate not in _PREBACKUP_REFUSAL_GATES
    ):
        return False
    if status in {"installed", "compensated_restored", "compensated_stopped", "unknown"}:
        return (not prebackup_gate_present and _sha256(old) and _sha256(new)
                and _sha256(backup))
    if status == "refused_before_backup":
        return old is None and new is None and backup is None
    if status == "refused_before_stop":
        return (not prebackup_gate_present and _sha256(old) and _sha256(new)
                and (backup is None or _sha256(backup)))
    return False


def _open_directory(path: Path) -> tuple[int, os.stat_result]:
    """Open a fixed absolute directory through no-follow root-owned ancestors."""
    if not path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts[1:]):
        _refuse()
    descriptor = None
    try:
        descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | _CLOEXEC)
        info = os.fstat(descriptor)
        if (info.st_uid != _OWNER_UID or info.st_gid != _OWNER_GID or stat.S_IMODE(info.st_mode) & 0o022
                or os.get_inheritable(descriptor)):
            _refuse()
        for index, name in enumerate(path.parts[1:]):
            child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | _CLOEXEC,
                            dir_fd=descriptor)
            child_info = os.fstat(child)
            named_info = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            if ((child_info.st_dev, child_info.st_ino) != (named_info.st_dev, named_info.st_ino)
                    or child_info.st_uid != _OWNER_UID or child_info.st_gid != _OWNER_GID
                    or stat.S_IMODE(child_info.st_mode) & 0o022
                    or os.get_inheritable(child)):
                os.close(child)
                _refuse()
            os.close(descriptor)
            descriptor = child
            info = child_info
        if stat.S_IMODE(info.st_mode) not in {0o700, 0o755}:
            _refuse()
        result, descriptor = descriptor, None
        return result, info
    except Exception:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        _refuse()


def _open_runtime_directory(*, create: bool) -> tuple[int, os.stat_result]:
    """Create only the fixed private state leaf on first admitted DEV/TEST use."""
    path = _RUNTIME_DIRECTORY
    if not create:
        return _open_directory(path)
    if not path.is_absolute() or path.name in {"", ".", ".."}:
        _refuse()
    parent = child = None
    try:
        parent, _parent_info = _open_directory(path.parent)
        try:
            os.mkdir(path.name, 0o700, dir_fd=parent)
            os.fsync(parent)
        except FileExistsError:
            pass
        child = os.open(path.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | _CLOEXEC,
                        dir_fd=parent)
        info = os.fstat(child)
        named = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
        if ((info.st_dev, info.st_ino) != (named.st_dev, named.st_ino)
                or info.st_uid != _OWNER_UID or info.st_gid != _OWNER_GID
                or stat.S_IMODE(info.st_mode) not in {0o700, 0o755}
                or stat.S_IMODE(info.st_mode) & 0o022 or os.get_inheritable(child)):
            _refuse()
        result, child = child, None
        return result, info
    except Exception:
        _refuse()
    finally:
        for descriptor in (child, parent):
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    _refuse()


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            _refuse()
        result[key] = value
    return result


def _owner_bytes(lease: InstallationAdmission) -> bytes:
    return (json.dumps({
        "schema": _OWNER_SCHEMA,
        "operation_id": lease.operation_id,
        "channel": lease.channel,
        "candidate_sha": lease.candidate_sha,
        "image_digest": lease.image_digest,
        "bundle_name": lease.bundle_name,
        "caller": lease.caller_identity,
    }, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")


def _start_authorization_name(channel: str) -> str:
    return f"{channel}.source-installation-start.json"


def _start_authorization_bytes(
    lease: InstallationAdmission, phase: str, generation_sha256: str,
) -> bytes:
    if (type(lease.operation_id) is not str or type(lease.candidate_sha) is not str
            or type(lease.image_digest) is not str or type(lease.caller_identity) is not dict):
        _refuse()
    return (json.dumps({
        "schema": _START_AUTHORIZATION_SCHEMA,
        "operation_id": lease.operation_id,
        "channel": lease.channel,
        "candidate_sha": lease.candidate_sha,
        "image_digest": lease.image_digest,
        "phase": phase,
        "generation_sha256": generation_sha256,
        "caller": lease.caller_identity,
    }, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")


def _stat_identity(info: os.stat_result) -> tuple[int, ...]:
    return (info.st_dev, info.st_ino, info.st_uid, info.st_gid, info.st_mode,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _read_proc_entry(directory_fd: int, name: str, limit: int) -> bytes:
    descriptor = None
    try:
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | _CLOEXEC, dir_fd=directory_fd)
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or os.get_inheritable(descriptor):
            _refuse()
        chunks = bytearray()
        while len(chunks) <= limit:
            block = os.read(descriptor, min(4096, limit + 1 - len(chunks)))
            if not block:
                break
            chunks.extend(block)
        if len(chunks) > limit:
            _refuse()
        return bytes(chunks)
    except Exception:
        _refuse()
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                _refuse()


def _proc_identity(pid: int) -> dict[str, object]:
    """Read a stable PID/start-time/argv/executable identity from procfs."""
    if type(pid) is not int or not 0 < pid < 2**31:
        _refuse()
    proc_root = process = None
    try:
        proc_root = os.open(_PROC, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | _CLOEXEC)
        process = os.open(str(pid), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | _CLOEXEC,
                          dir_fd=proc_root)
        initial = os.fstat(process)
        first_stat = _read_proc_entry(process, "stat", 8192)
        first_command = _read_proc_entry(process, "cmdline", 65536)
        first_executable = os.stat("exe", dir_fd=process)
        second_stat = _read_proc_entry(process, "stat", 8192)
        second_command = _read_proc_entry(process, "cmdline", 65536)
        second_executable = os.stat("exe", dir_fd=process)
        named = os.stat(str(pid), dir_fd=proc_root, follow_symlinks=False)
        if ((initial.st_dev, initial.st_ino) != (named.st_dev, named.st_ino)
                or first_stat != second_stat or first_command != second_command
                or _stat_identity(first_executable) != _stat_identity(second_executable)
                or not first_command or not first_command.endswith(b"\0")):
            _refuse()
        closing = first_stat.rfind(b")")
        fields = first_stat[closing + 2:].split()
        if closing < 0 or len(fields) <= 19 or not fields[19].isdigit():
            _refuse()
        return {
            "pid": pid,
            "start_time": int(fields[19]),
            "argv_sha256": _sha(first_command),
            "executable_sha256": _sha(json.dumps(
                _stat_identity(first_executable), separators=(",", ":"),
            ).encode("ascii")),
        }
    except Exception:
        _refuse()
    finally:
        for descriptor in (process, proc_root):
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    _refuse()


def _launcher_sha256() -> str:
    descriptor = None
    try:
        descriptor = os.open(_FIXED_LAUNCHER, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | _CLOEXEC)
        before = os.fstat(descriptor)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != _OWNER_UID or before.st_gid != _OWNER_GID
                or stat.S_IMODE(before.st_mode) != 0o755 or before.st_nlink != 1
                or not 0 < before.st_size <= 65536 or os.get_inheritable(descriptor)):
            _refuse()
        raw = os.pread(descriptor, before.st_size + 1, 0)
        named = os.stat(_FIXED_LAUNCHER, follow_symlinks=False)
        if (len(raw) != before.st_size or _stat_identity(os.fstat(descriptor)) != _stat_identity(before)
                or _stat_identity(named) != _stat_identity(before)):
            _refuse()
        return _sha(raw)
    except Exception:
        _refuse()
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                _refuse()


def _fixed_caller_identity(channel: str) -> dict[str, object]:
    """Bind exclusive ownership to the fixed root launcher RPC process."""
    expected_argv = [str(_FIXED_LAUNCHER), "rpc", channel]
    if (channel not in {"dev", "test"} or os.geteuid() != _OWNER_UID or os.getegid() != _OWNER_GID
            or sys.argv != expected_argv):
        _refuse()
    process = _proc_identity(os.getpid())
    expected_process_argv = [str(_FIXED_RUNTIME), *expected_argv]
    expected_command = b"\0".join(os.fsencode(item) for item in expected_process_argv) + b"\0"
    if process["argv_sha256"] != _sha(expected_command):
        _refuse()
    try:
        executable = os.stat("/proc/self/exe")
        runtime = os.stat(_FIXED_RUNTIME)
        if (_stat_identity(executable) != _stat_identity(runtime)
                or not stat.S_ISREG(runtime.st_mode) or runtime.st_uid != _OWNER_UID
                or runtime.st_gid != _OWNER_GID or runtime.st_mode & 0o022
                or not runtime.st_mode & 0o111):
            _refuse()
    except Exception:
        _refuse()
    return {
        **process,
        "uid": os.geteuid(),
        "gid": os.getegid(),
        "launcher_sha256": _launcher_sha256(),
    }


def _checkout_binding(checkout: Path, candidate_sha: str) -> dict[str, object]:
    """Read the exact clean checkout identity and direct rpc script bytes."""
    descriptors: list[int] = []
    try:
        if (not checkout.is_absolute() or len(checkout.parts) < 2
                or str(checkout) != os.path.abspath(checkout)
                or type(candidate_sha) is not str
                or re.fullmatch(r"[0-9a-f]{40}", candidate_sha) is None
                or "\\" in str(checkout)
                or any(part in {"", ".", ".."} for part in checkout.parts[1:])):
            _refuse()
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
                _refuse()
            current = child
        if (root.st_uid != _OWNER_UID or root.st_gid != _OWNER_GID
                or stat.S_IMODE(root.st_mode) not in {0o700, 0o755}):
            _refuse()
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
            _refuse()
        descriptor = os.open("postgres_deploy_service.py",
                             os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | _CLOEXEC,
                             dir_fd=scripts_fd)
        descriptors.append(descriptor)
        info = os.fstat(descriptor)
        named = os.stat("postgres_deploy_service.py", dir_fd=scripts_fd, follow_symlinks=False)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != _OWNER_UID or info.st_gid != _OWNER_GID
                or info.st_mode & 0o022 or info.st_nlink != 1 or not 0 < info.st_size <= 2 * 1024 * 1024
                or os.get_inheritable(descriptor) or _stat_identity(info) != _stat_identity(named)):
            _refuse()
        raw = os.pread(descriptor, info.st_size + 1, 0)
        if len(raw) != info.st_size or _stat_identity(os.fstat(descriptor)) != _stat_identity(info):
            _refuse()
        environment = {"PATH": "/usr/bin:/bin", "LC_ALL": "C", "GIT_CONFIG_NOSYSTEM": "1",
                       "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_OPTIONAL_LOCKS": "0",
                       "GIT_TERMINAL_PROMPT": "0", "GIT_NO_REPLACE_OBJECTS": "1"}
        commands = (
            ["git", "-c", "safe.directory=" + str(checkout), "-C", str(checkout), "rev-parse", "--show-toplevel"],
            ["git", "-c", "safe.directory=" + str(checkout), "-C", str(checkout), "rev-parse", "HEAD"],
            ["git", "-c", "safe.directory=" + str(checkout), "-C", str(checkout), "status", "--porcelain=v1",
             "--untracked-files=all", "--", *_CANDIDATE_CLEAN_PATHS],
        )
        results = [subprocess.run(command, env=environment, stdin=subprocess.DEVNULL,
                                  capture_output=True, check=False, timeout=20)
                   for command in commands]
        if (any(result.returncode != 0 or result.stderr for result in results)
                or Path(os.fsdecode(results[0].stdout.rstrip(b"\n"))) != checkout
                or results[1].stdout.rstrip(b"\n").decode("ascii") != candidate_sha
                or results[2].stdout):
            _refuse()
        return {"path": str(checkout), "device": root.st_dev, "inode": root.st_ino,
                "mode": stat.S_IMODE(root.st_mode), "revision": candidate_sha,
                "script_sha256": _sha(raw)}
    except Exception:
        _refuse()
    finally:
        for descriptor in reversed(descriptors):
            try:
                os.close(descriptor)
            except OSError:
                _refuse()


def require_verified_candidate_entrypoint(checkout: Path, candidate_sha: str) -> None:
    """Require the app transaction to run under the exact Git-bound candidate launcher."""
    binding = getattr(sys, _VERIFIED_CANDIDATE_ENTRYPOINT, None)
    if (not isinstance(checkout, Path) or not checkout.is_absolute()
            or type(candidate_sha) is not str or re.fullmatch(r"[0-9a-f]{40}", candidate_sha) is None
            or type(binding) is not dict or set(binding) != {"candidate_sha", "checkout", "script_sha256"}
            or binding.get("candidate_sha") != candidate_sha
            or binding.get("checkout") != str(checkout)
            or not _sha256(binding.get("script_sha256"))):
        _refuse()
    try:
        environment = {
            "PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C",
            "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0",
            "GIT_NO_REPLACE_OBJECTS": "1",
        }
        safe = "safe.directory=" + str(checkout)
        listing = subprocess.run(
            ["git", "-c", safe, "-C", str(checkout), "ls-tree", "-z", candidate_sha,
             "--", "scripts/postgres_deploy_service.py"],
            env=environment, stdin=subprocess.DEVNULL, capture_output=True, check=False, timeout=20,
        )
        records = listing.stdout.split(b"\0") if listing.stdout.endswith(b"\0") else []
        if listing.returncode != 0 or listing.stderr or len(records) != 2 or records[1] != b"":
            _refuse()
        header, separator, path = records[0].partition(b"\t")
        fields = header.split()
        if (not separator or path != b"scripts/postgres_deploy_service.py" or len(fields) != 3
                or fields[0] != b"100755" or fields[1] != b"blob"
                or re.fullmatch(rb"[0-9a-f]{40}", fields[2]) is None):
            _refuse()
        blob = subprocess.run(
            ["git", "-c", safe, "-C", str(checkout), "cat-file", "blob", fields[2].decode("ascii")],
            env=environment, stdin=subprocess.DEVNULL, capture_output=True, check=False, timeout=20,
        )
        source = blob.stdout
        if (blob.returncode != 0 or blob.stderr or not 0 < len(source) <= 2 * 1024 * 1024
                or _sha(source) != binding["script_sha256"]):
            _refuse()
    except Exception:
        _refuse()


def _candidate_checkout_caller_identity(channel: str, checkout: Path, candidate_sha: str) -> dict[str, object]:
    """Bind a direct rpc from the exact candidate checkout to its live process."""
    expected_script = checkout / "scripts" / "postgres_deploy_service.py"
    if (channel not in {"dev", "test"} or os.geteuid() != _OWNER_UID or os.getegid() != _OWNER_GID
            or sys.argv != [str(expected_script), "rpc", channel]):
        _refuse()
    require_verified_candidate_entrypoint(checkout, candidate_sha)
    process = _proc_identity(os.getpid())
    expected_command = b"\0".join(os.fsencode(item) for item in (
        str(_FIXED_RUNTIME), str(expected_script), "rpc", channel,
    )) + b"\0"
    if process["argv_sha256"] != _sha(expected_command):
        _refuse()
    try:
        executable = os.stat("/proc/self/exe")
        runtime = os.stat(_FIXED_RUNTIME)
        if (_stat_identity(executable) != _stat_identity(runtime)
                or not stat.S_ISREG(runtime.st_mode) or runtime.st_uid != _OWNER_UID
                or runtime.st_gid != _OWNER_GID or runtime.st_mode & 0o022 or not runtime.st_mode & 0o111):
            _refuse()
    except Exception:
        _refuse()
    return {**process, "uid": os.geteuid(), "gid": os.getegid(),
            "launcher_sha256": _launcher_sha256(),
            "candidate_sha": candidate_sha,
            "source_checkout": _checkout_binding(checkout, candidate_sha)}


def _checkout_caller_binding(caller: dict[str, object]) -> dict[str, object] | None:
    binding = caller.get("source_checkout")
    if binding is None:
        return None
    if (type(binding) is not dict or set(binding) != {
            "path", "device", "inode", "mode", "revision", "script_sha256",
    } or any(type(binding[key]) is not int for key in ("device", "inode", "mode"))
            or binding["device"] < 0 or binding["inode"] <= 0
            or binding["mode"] not in {0o700, 0o755}
            or type(binding["path"]) is not str or not Path(binding["path"]).is_absolute()
            or type(binding["revision"]) is not str
            or binding["revision"] != caller.get("candidate_sha")
            or type(binding["script_sha256"]) is not str
            or re.fullmatch(r"[0-9a-f]{64}", binding["script_sha256"]) is None):
        _refuse()
    return binding


def _verify_checkout_caller(caller: dict[str, object]) -> None:
    binding = _checkout_caller_binding(caller)
    if binding is None:
        return
    selected = _checkout_binding(Path(cast(str, binding["path"])), cast(str, binding["revision"]))
    if selected != binding:
        _refuse()


def _verify_live_caller(caller: dict[str, object]) -> None:
    try:
        if (os.getpid() != caller["pid"] or os.geteuid() != caller["uid"]
                or os.getegid() != caller["gid"]):
            _refuse()
        current = _proc_identity(os.getpid())
        if any(current[key] != caller[key] for key in (
                "pid", "start_time", "argv_sha256", "executable_sha256")):
            _refuse()
        _verify_checkout_caller(caller)
    except Exception:
        _refuse()


def _verify_peer_caller(caller: dict[str, object], credentials: tuple[int, int, int]) -> None:
    if (type(credentials) is not tuple or len(credentials) != 3
            or any(type(value) is not int for value in credentials)):
        _refuse()
    pid, uid, gid = credentials
    if (pid != caller["pid"] or uid != caller["uid"] or gid != caller["gid"]):
        _refuse()
    current = _proc_identity(pid)
    if any(current[key] != caller[key] for key in (
            "pid", "start_time", "argv_sha256", "executable_sha256")):
        _refuse()
    _verify_checkout_caller(caller)


def _owner_record(raw: bytes, channel: str) -> dict[str, object]:
    try:
        record = json.loads(raw, object_pairs_hook=_unique)
    except Exception:
        _refuse()
    if (type(record) is not dict
            or set(record) != {
                "schema", "operation_id", "channel", "candidate_sha", "image_digest", "bundle_name", "caller",
            }
            or record["schema"] != _OWNER_SCHEMA or record["channel"] != channel
            or type(record["operation_id"]) is not str
            or type(record["candidate_sha"]) is not str
            or type(record["image_digest"]) is not str
            or type(record["bundle_name"]) is not str
            or type(record["caller"]) is not dict):
        _refuse()
    try:
        if (str(UUID(record["operation_id"])) != record["operation_id"]
                or re.fullmatch(r"[0-9a-f]{40}", record["candidate_sha"]) is None
                or re.fullmatch(r"sha256:[0-9a-f]{64}", record["image_digest"]) is None
                or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", record["bundle_name"]) is None):
            _refuse()
    except Exception:
        _refuse()
    caller = record["caller"]
    fixed_fields = {
        "pid", "uid", "gid", "start_time", "argv_sha256", "executable_sha256", "launcher_sha256",
    }
    checkout_fields = fixed_fields | {"candidate_sha", "source_checkout"}
    if (set(caller) not in (fixed_fields, checkout_fields)
            or any(type(caller[key]) is not int for key in ("pid", "uid", "gid", "start_time"))
            or not 0 < caller["pid"] < 2**31 or caller["uid"] < 0 or caller["gid"] < 0
            or caller["start_time"] <= 0
            or any(type(caller[key]) is not str or re.fullmatch(r"[0-9a-f]{64}", caller[key]) is None
                   for key in ("argv_sha256", "executable_sha256", "launcher_sha256"))
            or (set(caller) == checkout_fields and (
                type(caller["candidate_sha"]) is not str
                or caller["candidate_sha"] != record["candidate_sha"]
                or type(caller["source_checkout"]) is not dict))):
        _refuse()
    if set(caller) == checkout_fields:
        _checkout_caller_binding(caller)
    return record


def _terminal_receipt(owner: dict[str, object]) -> dict[str, object]:
    parent = descriptor = None
    name = f"bws-source-installation-{owner['operation_id']}.receipt.json"
    try:
        parent, _ = _open_directory(_RECEIPT_DIRECTORY)
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | _CLOEXEC,
                             dir_fd=parent)
        info = os.fstat(descriptor)
        named = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != _OWNER_UID or info.st_gid != _OWNER_GID
                or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1
                or not 0 < info.st_size <= 4096 or os.get_inheritable(descriptor)
                or (info.st_dev, info.st_ino) != (named.st_dev, named.st_ino)):
            _refuse()
        raw = os.pread(descriptor, info.st_size + 1, 0)
        if len(raw) != info.st_size:
            _refuse()
        receipt = json.loads(raw, object_pairs_hook=_unique)
        expected = {
            "schema": _RECEIPT_SCHEMA,
            "operation_id": owner["operation_id"],
            "channel": owner["channel"],
            "candidate_sha": owner["candidate_sha"],
            "image_digest": owner["image_digest"],
        }
        receipt_fields = {
            "schema", "operation_id", "channel", "candidate_sha", "image_digest",
            "old_generation_sha256", "new_generation_sha256", "backup_manifest_sha256", "status",
        }
        gate_present = type(receipt) is dict and "prebackup_gate" in receipt
        if (type(receipt) is not dict or any(receipt.get(key) != value for key, value in expected.items())
                or receipt.get("status") not in _RECEIPT_STATUSES
                or not _receipt_generations(receipt.get("status"), receipt.get("old_generation_sha256"),
                                            receipt.get("new_generation_sha256"),
                                            receipt.get("backup_manifest_sha256"),
                                            prebackup_gate_present=gate_present,
                                            prebackup_gate=receipt.get("prebackup_gate"))
                or set(receipt) not in (receipt_fields, receipt_fields | {"prebackup_gate"})):
            _refuse()
        return receipt
    except Exception:
        _refuse()
    finally:
        for fd in (descriptor, parent):
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass


def _require_unused_receipt_slot(operation_id: str) -> None:
    """Never admit an operation ID whose durable receipt name already exists."""
    parent = None
    try:
        parent, _ = _open_directory(_RECEIPT_DIRECTORY)
        name = f"bws-source-installation-{operation_id}.receipt.json"
        try:
            os.stat(name, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            return
        _refuse()
    except Exception:
        _refuse()
    finally:
        if parent is not None:
            try:
                os.close(parent)
            except OSError:
                _refuse()


def _open_lock(parent_fd: int, name: str, *, create: bool) -> tuple[int, os.stat_result]:
    flags = os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK | _CLOEXEC
    if create:
        flags |= os.O_CREAT
    try:
        descriptor = os.open(name, flags, 0o600, dir_fd=parent_fd)
        info = os.fstat(descriptor)
        named = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if ((info.st_dev, info.st_ino) != (named.st_dev, named.st_ino)
                or not stat.S_ISREG(info.st_mode) or info.st_uid != _OWNER_UID
                or info.st_gid != _OWNER_GID or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_nlink != 1 or os.get_inheritable(descriptor)):
            _refuse()
        return descriptor, info
    except FileNotFoundError:
        if not create:
            raise
        _refuse()
    except Exception:
        _refuse()


def _owner_marker(parent_fd: int, channel: str) -> bytes:
    descriptor = None
    name = f"{channel}.source-installation.lock"
    try:
        try:
            descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | _CLOEXEC,
                                 dir_fd=parent_fd)
        except FileNotFoundError:
            return b""
        info = os.fstat(descriptor)
        named = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if ((info.st_dev, info.st_ino) != (named.st_dev, named.st_ino)
                or not stat.S_ISREG(info.st_mode) or info.st_uid != _OWNER_UID
                or info.st_gid != _OWNER_GID or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_nlink != 1 or os.get_inheritable(descriptor)):
            _refuse()
        raw = os.pread(descriptor, 4097, 0)
        if len(raw) > 4096:
            _refuse()
        return raw
    except Exception:
        _refuse()
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                _refuse()


def _require_exclusive_lock(parent_fd: int, name: str, identity: tuple[int, int]) -> None:
    descriptor = None
    try:
        descriptor, info = _open_lock(parent_fd, name, create=False)
        if (info.st_dev, info.st_ino) != identity:
            _refuse()
        try:
            fcntl.flock(descriptor, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno not in {errno.EACCES, errno.EAGAIN}:
                _refuse()
        else:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            _refuse()
    except Exception:
        _refuse()
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                _refuse()


def _require_terminal_channel_owners(parent_fd: int) -> None:
    """Reject a crashed DEV or TEST owner even after its flock was released."""
    for channel in ("dev", "test"):
        raw = _owner_marker(parent_fd, channel)
        if not raw:
            continue
        owner = _owner_record(raw, channel)
        receipt = _terminal_receipt(owner)
        if receipt["status"] not in _ADMISSION_TERMINAL_STATUSES:
            _refuse()


def _recovery_request(channel: str, request: object) -> dict[str, str]:
    """Validate the immutable binding used by same-operation recovery."""
    fields = {"action", "operation_id", "candidate_sha", "image_digest", "bundle_name"}
    if channel not in {"dev", "test"} or type(request) is not dict or set(request) != fields:
        _refuse()
    operation_id = request.get("operation_id")
    candidate_sha = request.get("candidate_sha")
    image_digest = request.get("image_digest")
    bundle_name = request.get("bundle_name")
    try:
        if (request.get("action") != _SOURCE_INSTALLATION_RECONCILE_ACTION
                or type(operation_id) is not str or str(UUID(operation_id)) != operation_id
                or type(candidate_sha) is not str
                or re.fullmatch(r"[0-9a-f]{40}", candidate_sha) is None
                or type(image_digest) is not str
                or re.fullmatch(r"sha256:[0-9a-f]{64}", image_digest) is None
                or type(bundle_name) is not str
                or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", bundle_name) is None):
            _refuse()
    except Exception:
        _refuse()
    return {
        "operation_id": operation_id,
        "candidate_sha": candidate_sha,
        "image_digest": image_digest,
        "bundle_name": bundle_name,
    }


def _recovery_unresolved(reason: str) -> dict[str, object]:
    if reason not in _RECOVERY_REFUSAL_REASONS:
        reason = "lock_recheck_failed"
    return {"source_installation": {"status": "unresolved", "reason": reason}}


def reconcile_installation_operation(
    channel: str,
    request: object,
    *,
    retire: Callable[[dict[str, object], dict[str, object]], None] | None = None,
) -> dict[str, object]:
    """Recover one lost source-install response without adopting or replaying it.

    The runtime and channel locks are acquired exclusively before the owner and
    receipt are read.  ``retire`` is invoked while those locks remain held so a
    caller can prove/retire its second, source-side lock atomically.  Unknown
    and compensated-stopped receipts are returned but never retired.
    """
    try:
        selected = _recovery_request(channel, request)
    except InstallationAdmissionRefused:
        return _recovery_unresolved("request_binding")

    parent = global_fd = channel_fd = None
    global_identity = channel_identity = None
    try:
        try:
            parent, _ = _open_runtime_directory(create=False)
        except Exception:
            return _recovery_unresolved("runtime_state_missing")
        try:
            global_fd, global_info = _open_lock(parent, _GLOBAL_LOCK, create=False)
            channel_fd, channel_info = _open_lock(
                parent, f"{channel}.source-installation.lock", create=False,
            )
        except Exception:
            return _recovery_unresolved("runtime_state_missing")
        global_identity = (global_info.st_dev, global_info.st_ino)
        channel_identity = (channel_info.st_dev, channel_info.st_ino)
        try:
            fcntl.flock(global_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno in {errno.EACCES, errno.EAGAIN}:
                return _recovery_unresolved("global_lock_active")
            return _recovery_unresolved("lock_recheck_failed")
        try:
            fcntl.flock(channel_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno in {errno.EACCES, errno.EAGAIN}:
                return _recovery_unresolved("channel_lock_active")
            return _recovery_unresolved("lock_recheck_failed")

        if (os.pread(global_fd, 1, 0) or os.pread(channel_fd, 4097, 0) == b""
                or len(os.pread(channel_fd, 4097, 0)) > 4096):
            return _recovery_unresolved("owner_missing")
        owner_raw = os.pread(channel_fd, 4097, 0)
        try:
            owner = _owner_record(owner_raw, channel)
        except InstallationAdmissionRefused:
            return _recovery_unresolved("owner_invalid")
        if any(owner.get(key) != selected[key] for key in (
                "operation_id", "candidate_sha", "image_digest", "bundle_name",
        )):
            return _recovery_unresolved("owner_mismatch")
        try:
            receipt = _terminal_receipt(owner)
        except InstallationAdmissionRefused:
            return _recovery_unresolved("receipt_invalid")

        # Re-read every identity and marker after receipt validation.  A
        # replacement pathname or changed owner is not evidence for recovery.
        global_after = os.fstat(global_fd)
        channel_after = os.fstat(channel_fd)
        global_named = os.stat(_GLOBAL_LOCK, dir_fd=parent, follow_symlinks=False)
        channel_named = os.stat(
            f"{channel}.source-installation.lock", dir_fd=parent, follow_symlinks=False,
        )
        if (os.pread(global_fd, 1, 0)
                or (global_after.st_dev, global_after.st_ino) != global_identity
                or (channel_after.st_dev, channel_after.st_ino) != channel_identity
                or (global_named.st_dev, global_named.st_ino) != global_identity
                or (channel_named.st_dev, channel_named.st_ino) != channel_identity
                or os.pread(channel_fd, 4097, 0) != owner_raw):
            return _recovery_unresolved("lock_recheck_failed")
        if retire is not None:
            try:
                retire(owner, receipt)
            except Exception:
                return _recovery_unresolved("retirement_unproven")
        if os.pread(channel_fd, 4097, 0) != owner_raw:
            return _recovery_unresolved("lock_recheck_failed")
        return {"source_installation": dict(receipt)}
    except InstallationAdmissionRefused:
        return _recovery_unresolved("lock_recheck_failed")
    except Exception:
        return _recovery_unresolved("lock_recheck_failed")
    finally:
        for descriptor in (channel_fd, global_fd, parent):
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass


def cleanup_must_skip(channel: str) -> bool:
    """Prove that this DEV/TEST ExecStopPost must take its no-write branch."""
    if channel == "prod":
        return False
    if channel not in {"dev", "test"}:
        _refuse()
    parent = descriptor = None
    exclusive_acquired = False
    try:
        parent, _ = _open_directory(_RUNTIME_DIRECTORY)
        try:
            descriptor, info = _open_lock(parent, _GLOBAL_LOCK, create=False)
        except FileNotFoundError:
            # Without the persistent cross-channel lock, absence of a writer is
            # unproven. The stop hook fails closed without creating files.
            return True
        if os.pread(descriptor, 1, 0):
            return True
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            exclusive_acquired = True
        except OSError as exc:
            if exc.errno not in {errno.EACCES, errno.EAGAIN}:
                _refuse()
        if not exclusive_acquired:
            # A global shared reservation can still cover either channel.
            return True
        try:
            current = os.fstat(descriptor)
            named = os.stat(_GLOBAL_LOCK, dir_fd=parent, follow_symlinks=False)
            if ((current.st_dev, current.st_ino) != (info.st_dev, info.st_ino)
                    or (named.st_dev, named.st_ino) != (info.st_dev, info.st_ino)
                    or os.pread(descriptor, 1, 0)):
                return True
            _require_terminal_channel_owners(parent)
        except InstallationAdmissionRefused:
            # Missing/ambiguous evidence retains ownership; it never allows the
            # stop hook to perform its ordinary source cleanup.
            return True
        return False
    except Exception:
        # The stop hook is a no-write boundary. Missing or malformed admission
        # state is not evidence that source cleanup may proceed.
        return True
    finally:
        for fd in (descriptor, parent):
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass


def require_active_installation_owner(
    channel: str, operation_id: str, candidate_sha: str, image_digest: str,
    *, peer_credentials: tuple[int, int, int],
) -> dict[str, object]:
    """Authenticate the exact fixed launcher peer for an in-transaction callback."""
    if (channel not in {"dev", "test"} or type(operation_id) is not str
            or type(candidate_sha) is not str or type(image_digest) is not str):
        _refuse()
    parent = descriptor = global_descriptor = None
    try:
        parent, _ = _open_directory(_RUNTIME_DIRECTORY)
        global_descriptor, global_info = _open_lock(parent, _GLOBAL_LOCK, create=False)
        if os.pread(global_descriptor, 1, 0):
            _refuse()
        try:
            fcntl.flock(global_descriptor, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno not in {errno.EACCES, errno.EAGAIN}:
                _refuse()
        else:
            fcntl.flock(global_descriptor, fcntl.LOCK_UN)
            _refuse()
        name = f"{channel}.source-installation.lock"
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | _CLOEXEC,
                             dir_fd=parent)
        info = os.fstat(descriptor)
        named = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if ((info.st_dev, info.st_ino) != (named.st_dev, named.st_ino)
                or not stat.S_ISREG(info.st_mode) or info.st_uid != _OWNER_UID
                or info.st_gid != _OWNER_GID or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_nlink != 1 or os.get_inheritable(descriptor)):
            _refuse()
        raw = os.pread(descriptor, 4097, 0)
        owner = _owner_record(raw, channel)
        if (owner["operation_id"] != operation_id or owner["candidate_sha"] != candidate_sha
                or owner["image_digest"] != image_digest):
            _refuse()
        caller = owner["caller"]
        if type(caller) is not dict:
            _refuse()
        _verify_peer_caller(caller, peer_credentials)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno not in {errno.EACCES, errno.EAGAIN}:
                _refuse()
        else:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            _refuse()
        global_named = os.stat(_GLOBAL_LOCK, dir_fd=parent, follow_symlinks=False)
        if ((global_info.st_dev, global_info.st_ino) != (global_named.st_dev, global_named.st_ino)
                or os.pread(global_descriptor, 1, 0)):
            _refuse()
        return owner
    except Exception:
        _refuse()
    finally:
        for fd in (descriptor, global_descriptor, parent):
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass


@dataclass
class InstallationAdmission:
    channel: str
    mode: str
    operation_id: str | None
    candidate_sha: str | None
    image_digest: str | None
    bundle_name: str | None
    caller_identity: dict[str, object] | None
    _parent_fd: int
    _global_fd: int
    _lock_fd: int
    _parent_identity: tuple[int, int]
    _global_identity: tuple[int, int]
    _lock_identity: tuple[int, int]
    _completed: bool = False
    _closed: bool = False
    _start_authorization: bytes | None = None

    def _verify_lock(self, *, owner: bool) -> None:
        if (self._closed or os.get_inheritable(self._parent_fd)
                or os.get_inheritable(self._global_fd) or os.get_inheritable(self._lock_fd)):
            _refuse()
        parent = os.fstat(self._parent_fd)
        global_lock = os.fstat(self._global_fd)
        lock = os.fstat(self._lock_fd)
        try:
            global_named = os.stat(_GLOBAL_LOCK, dir_fd=self._parent_fd, follow_symlinks=False)
            named = os.stat(f"{self.channel}.source-installation.lock", dir_fd=self._parent_fd,
                            follow_symlinks=False)
        except Exception:
            _refuse()
        if ((parent.st_dev, parent.st_ino) != self._parent_identity
                or (global_lock.st_dev, global_lock.st_ino) != self._global_identity
                or (global_named.st_dev, global_named.st_ino) != self._global_identity
                or not stat.S_ISREG(global_lock.st_mode) or global_lock.st_uid != _OWNER_UID
                or global_lock.st_gid != _OWNER_GID or stat.S_IMODE(global_lock.st_mode) != 0o600
                or global_lock.st_nlink != 1 or os.pread(self._global_fd, 1, 0)
                or (lock.st_dev, lock.st_ino) != self._lock_identity
                or (named.st_dev, named.st_ino) != self._lock_identity
                or not stat.S_ISREG(lock.st_mode) or lock.st_uid != _OWNER_UID or lock.st_gid != _OWNER_GID
                or stat.S_IMODE(lock.st_mode) != 0o600 or lock.st_nlink != 1):
            _refuse()
        content = os.pread(self._lock_fd, 4097, 0)
        if len(content) > 4096:
            _refuse()
        if owner:
            if content != _owner_bytes(self):
                _refuse()
            if self.caller_identity is None:
                _refuse()
            _require_exclusive_lock(self._parent_fd, _GLOBAL_LOCK, self._global_identity)
            _require_exclusive_lock(
                self._parent_fd, f"{self.channel}.source-installation.lock", self._lock_identity,
            )
            _verify_live_caller(self.caller_identity)
        elif content:
            receipt = _terminal_receipt(_owner_record(content, self.channel))
            if receipt["status"] not in _ADMISSION_TERMINAL_STATUSES:
                _refuse()

    def authorize_service_start(self, phase: str, generation_sha256: str) -> None:
        """Publish one exact start permit while this process owns both exclusive locks."""
        if (self.mode != "exclusive" or self._completed or self._start_authorization is not None
                or phase not in {"candidate", "restored-old"}
                or type(generation_sha256) is not str
                or re.fullmatch(r"[0-9a-f]{64}", generation_sha256) is None):
            _refuse()
        raw = _start_authorization_bytes(self, phase, generation_sha256)
        self._verify_lock(owner=True)
        name = _start_authorization_name(self.channel)
        descriptor = readback = None
        try:
            descriptor = os.open(
                name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | _CLOEXEC,
                0o600, dir_fd=self._parent_fd,
            )
            self._start_authorization = raw
            before = os.fstat(descriptor)
            named = os.stat(name, dir_fd=self._parent_fd, follow_symlinks=False)
            if (not stat.S_ISREG(before.st_mode) or before.st_uid != _OWNER_UID or before.st_gid != _OWNER_GID
                    or stat.S_IMODE(before.st_mode) != 0o600 or before.st_nlink != 1
                    or (before.st_dev, before.st_ino) != (named.st_dev, named.st_ino)
                    or os.get_inheritable(descriptor)):
                _refuse()
            offset = 0
            while offset < len(raw):
                count = os.write(descriptor, raw[offset:])
                if count <= 0:
                    _refuse()
                offset += count
            os.fsync(descriptor)
            readback = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | _CLOEXEC,
                               dir_fd=self._parent_fd)
            actual = os.fstat(readback)
            current = os.stat(name, dir_fd=self._parent_fd, follow_symlinks=False)
            if ((actual.st_dev, actual.st_ino) != (before.st_dev, before.st_ino)
                    or (current.st_dev, current.st_ino) != (before.st_dev, before.st_ino)
                    or os.pread(readback, len(raw) + 1, 0) != raw
                    or os.get_inheritable(readback)):
                _refuse()
            os.fsync(self._parent_fd)
        except Exception:
            _refuse()
        finally:
            for fd in (readback, descriptor):
                if fd is not None:
                    try:
                        os.close(fd)
                    except OSError:
                        _refuse()
        self._verify_lock(owner=True)

    def confirm_service_start_consumed(self, phase: str, generation_sha256: str) -> None:
        if (self._start_authorization != _start_authorization_bytes(self, phase, generation_sha256)
                or self.mode != "exclusive"):
            _refuse()
        name = _start_authorization_name(self.channel)
        expected = self._start_authorization
        deadline = time.monotonic() + _START_CONSUMPTION_TIMEOUT_SECONDS
        while True:
            self._verify_lock(owner=True)
            descriptor = None
            try:
                descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | _CLOEXEC,
                                     dir_fd=self._parent_fd)
            except FileNotFoundError:
                self._start_authorization = None
                self._verify_lock(owner=True)
                return
            except Exception:
                _refuse()
            try:
                info = os.fstat(descriptor)
                if (not stat.S_ISREG(info.st_mode) or info.st_uid != _OWNER_UID or info.st_gid != _OWNER_GID
                        or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink not in {0, 1}
                        or os.get_inheritable(descriptor) or os.pread(descriptor, 4097, 0) != expected):
                    _refuse()
                try:
                    named = os.stat(name, dir_fd=self._parent_fd, follow_symlinks=False)
                except FileNotFoundError:
                    # The fixed launcher consumed and unlinked the one-use grant
                    # after authenticating the exact owner and global lock.
                    self._start_authorization = None
                    self._verify_lock(owner=True)
                    return
                if (info.st_nlink != 1 or (info.st_dev, info.st_ino) != (named.st_dev, named.st_ino)):
                    _refuse()
            except Exception:
                _refuse()
            finally:
                try:
                    os.close(descriptor)
                except OSError:
                    _refuse()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _refuse()
            time.sleep(min(_START_CONSUMPTION_POLL_SECONDS, remaining))

    def revoke_service_start(self) -> None:
        """Remove only this operation's unused one-shot start permit."""
        if self._start_authorization is None:
            return
        if self.mode != "exclusive":
            _refuse()
        self._verify_lock(owner=True)
        name = _start_authorization_name(self.channel)
        descriptor = None
        try:
            try:
                descriptor = os.open(name, os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK | _CLOEXEC,
                                     dir_fd=self._parent_fd)
            except FileNotFoundError:
                self._start_authorization = None
                return
            info = os.fstat(descriptor)
            named = os.stat(name, dir_fd=self._parent_fd, follow_symlinks=False)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != _OWNER_UID or info.st_gid != _OWNER_GID
                    or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1
                    or (info.st_dev, info.st_ino) != (named.st_dev, named.st_ino)
                    or os.get_inheritable(descriptor)
                    or os.pread(descriptor, 4097, 0) != self._start_authorization):
                _refuse()
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                _refuse()
            current = os.fstat(descriptor)
            named_after = os.stat(name, dir_fd=self._parent_fd, follow_symlinks=False)
            if ((current.st_dev, current.st_ino) != (info.st_dev, info.st_ino)
                    or (named_after.st_dev, named_after.st_ino) != (info.st_dev, info.st_ino)
                    or os.pread(descriptor, 4097, 0) != self._start_authorization):
                _refuse()
            os.unlink(name, dir_fd=self._parent_fd)
            os.fsync(self._parent_fd)
            try:
                os.stat(name, dir_fd=self._parent_fd, follow_symlinks=False)
            except FileNotFoundError:
                self._start_authorization = None
                return
            _refuse()
        except Exception:
            _refuse()
        finally:
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    _refuse()

    def _validate_receipt(self, receipt: object) -> dict[str, object]:
        fields = {
            "schema", "operation_id", "channel", "candidate_sha", "image_digest",
            "old_generation_sha256", "new_generation_sha256", "backup_manifest_sha256", "status",
        }
        gate_present = type(receipt) is dict and "prebackup_gate" in receipt
        if (type(receipt) is not dict or set(receipt) not in (fields, fields | {"prebackup_gate"})
                or receipt["schema"] != _RECEIPT_SCHEMA
                or receipt["operation_id"] != self.operation_id
                or receipt["channel"] != self.channel
                or receipt["candidate_sha"] != self.candidate_sha
                or receipt["image_digest"] != self.image_digest
                or receipt["status"] not in _RECEIPT_STATUSES
                or not _receipt_generations(receipt["status"], receipt["old_generation_sha256"],
                                            receipt["new_generation_sha256"],
                                            receipt["backup_manifest_sha256"],
                                            prebackup_gate_present=gate_present,
                                            prebackup_gate=receipt.get("prebackup_gate"))):
            _refuse()
        return dict(receipt)

    def _write_receipt(self, raw: bytes) -> None:
        if len(raw) > 4096:
            _refuse()
        parent = None
        descriptor = None
        readback = None
        name = f"bws-source-installation-{self.operation_id}.receipt.json"
        try:
            parent, _ = _open_directory(_RECEIPT_DIRECTORY)
            descriptor = os.open(
                name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | _CLOEXEC,
                0o600, dir_fd=parent,
            )
            before = os.fstat(descriptor)
            if (not stat.S_ISREG(before.st_mode) or before.st_uid != _OWNER_UID or before.st_gid != _OWNER_GID
                    or stat.S_IMODE(before.st_mode) != 0o600 or before.st_nlink != 1
                    or os.get_inheritable(descriptor)):
                _refuse()
            offset = 0
            while offset < len(raw):
                count = os.write(descriptor, raw[offset:])
                if count <= 0:
                    _refuse()
                offset += count
            os.fsync(descriptor)
            readback = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | _CLOEXEC,
                               dir_fd=parent)
            actual = os.fstat(readback)
            named = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if ((actual.st_dev, actual.st_ino) != (before.st_dev, before.st_ino)
                    or (named.st_dev, named.st_ino) != (before.st_dev, before.st_ino)
                    or os.pread(readback, len(raw) + 1, 0) != raw
                    or os.get_inheritable(readback)):
                _refuse()
            os.fsync(parent)
        except Exception:
            _refuse()
        finally:
            for fd in (readback, descriptor, parent):
                if fd is not None:
                    try:
                        os.close(fd)
                    except OSError:
                        pass

    def complete(self, receipt: dict[str, object]) -> dict[str, object]:
        """Publish one operation-bound receipt before clearing the owner marker."""
        if self.mode != "exclusive" or self._completed or self._start_authorization is not None:
            _refuse()
        try:
            os.stat(_start_authorization_name(self.channel), dir_fd=self._parent_fd,
                    follow_symlinks=False)
        except FileNotFoundError:
            pass
        except Exception:
            _refuse()
        else:
            _refuse()
        selected = self._validate_receipt(receipt)
        self._verify_lock(owner=True)
        raw = (json.dumps(selected, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")
        self._write_receipt(raw)
        # The durable owner marker remains as a receipt pointer. Future shared
        # callers proceed only after matching terminal evidence verifies; a
        # later exclusive transaction may replace it only under the same lock.
        self._verify_lock(owner=True)
        self._completed = True
        return selected

    def close(self) -> None:
        if self._closed:
            _refuse()
        self._closed = True
        errors = False
        for descriptor in (self._lock_fd, self._global_fd, self._parent_fd):
            try:
                os.close(descriptor)
            except OSError:
                errors = True
        if errors:
            _refuse()


@contextmanager
def installation_admission(
    channel: str,
    *,
    mode: str,
    operation_id: str | None = None,
    candidate_sha: str | None = None,
    image_digest: str | None = None,
    bundle_name: str | None = None,
    caller_checkout: Path | None = None,
) -> Iterator[InstallationAdmission]:
    """Hold one fixed DEV/TEST caller reservation without adopting old state."""
    if channel not in {"dev", "test"} or mode not in {"shared", "exclusive"}:
        _refuse()
    if mode == "exclusive":
        try:
            if (type(operation_id) is not str or str(UUID(operation_id)) != operation_id
                    or type(candidate_sha) is not str
                    or re.fullmatch(r"[0-9a-f]{40}", candidate_sha) is None
                    or type(image_digest) is not str
                    or re.fullmatch(r"sha256:[0-9a-f]{64}", image_digest) is None
                    or type(bundle_name) is not str
                    or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", bundle_name) is None):
                _refuse()
        except Exception:
            _refuse()
    elif any(value is not None for value in (operation_id, candidate_sha, image_digest, bundle_name)):
        _refuse()

    if mode == "shared" and caller_checkout is not None:
        _refuse()
    caller_identity = (
        _fixed_caller_identity(channel) if caller_checkout is None else
        _candidate_checkout_caller_identity(channel, caller_checkout, cast(str, candidate_sha))
    ) if mode == "exclusive" else None
    parent = global_fd = lock_fd = None
    lease = None
    try:
        parent, parent_info = _open_runtime_directory(create=True)
        global_fd, global_info = _open_lock(parent, _GLOBAL_LOCK, create=True)
        operation = fcntl.LOCK_SH if mode == "shared" else fcntl.LOCK_EX
        fcntl.flock(global_fd, operation | fcntl.LOCK_NB)
        name = f"{channel}.source-installation.lock"
        lock_fd, lock_info = _open_lock(parent, name, create=True)
        fcntl.flock(lock_fd, operation | fcntl.LOCK_NB)
        lease = InstallationAdmission(
            channel, mode, operation_id, candidate_sha, image_digest, bundle_name,
            caller_identity, parent, global_fd, lock_fd, (parent_info.st_dev, parent_info.st_ino),
            (global_info.st_dev, global_info.st_ino), (lock_info.st_dev, lock_info.st_ino),
        )
        parent = global_fd = lock_fd = None
        if mode == "shared":
            _require_terminal_channel_owners(lease._parent_fd)
            lease._verify_lock(owner=False)
        else:
            _require_terminal_channel_owners(lease._parent_fd)
            _require_unused_receipt_slot(cast(str, operation_id))
            current = os.pread(lease._lock_fd, 4097, 0)
            if len(current) > 4096:
                _refuse()
            if current:
                prior_owner = _owner_record(current, channel)
                prior_receipt = _terminal_receipt(prior_owner)
                if (prior_receipt["status"] not in _ADMISSION_TERMINAL_STATUSES
                        or prior_owner["operation_id"] == operation_id):
                    _refuse()
                os.ftruncate(lease._lock_fd, 0)
                if os.pread(lease._lock_fd, 1, 0) != b"":
                    _refuse()
        if mode == "exclusive":
            raw = _owner_bytes(lease)
            if os.lseek(lease._lock_fd, 0, os.SEEK_SET) != 0:
                _refuse()
            if os.write(lease._lock_fd, raw) != len(raw):
                _refuse()
            os.fsync(lease._lock_fd)
            lease._verify_lock(owner=True)
        yield lease
        if mode == "exclusive" and not lease._completed:
            _refuse()
    except Exception:
        if lease is not None:
            try:
                lease.close()
            except Exception:
                pass
            parent = global_fd = lock_fd = None
        _refuse()
    finally:
        if lease is not None and not lease._closed:
            lease.close()
        else:
            for descriptor in (lock_fd, global_fd, parent):
                if descriptor is not None:
                    try:
                        os.close(descriptor)
                    except OSError:
                        pass


@contextmanager
def shared_caller_reservation(channel: str) -> Iterator[None]:
    """Reserve one ordinary supported BWS caller; PROD is outside this fence."""
    if channel in {"dev", "test"}:
        with installation_admission(channel, mode="shared"):
            yield
    elif channel == "prod":
        yield
    else:
        _refuse()
