"""One claimed, source-bound DEV probe outage/recovery operation.

Native entry requires the fixed #6505 caller contract and an accepted finite
DEV window. Core observations are deliberately distinct from the live receipt,
which is emitted only after the native transport and supervisor have completed.

Derived from the independently reviewed TEST source in public PR #6506,
commit 6f85e15a02a45b17b5d2d57d2e0f34e159226d74, program SHA-256
ab48098c9b72845283aa7d53ddc8329b22a092cd6db072073d7b38b3a236c95f.
The separate fixed entry deliberately preserves the active TEST program; it
does not parameterize TEST authority or supply evidence of live DEV acceptance.
"""

from __future__ import annotations

import ast
from dataclasses import asdict, dataclass, field, replace
from functools import wraps
import hashlib
import io
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import stat
import sys
import tarfile
from types import SimpleNamespace
from typing import Any, Callable
from urllib.parse import urlsplit
from uuid import UUID

UNBOUND_OFFLINE_DRAFT = "UNBOUND_OFFLINE_DRAFT"
UNIT = "yggdrasil-host-probe@dev.service"
LAUNCHER = "ops/host-setup/linux/host_probe_launcher.py"
PROBE = "ops/host-setup/mac-mini/prod_probe.py"
SOURCE_HASHES = {
    PROBE: "3c21b02665750401a055f5d5b230429bca674aed513cac07e695537ee6c838e1",
    "ops/host-setup/mac-mini/notification_channels.py": "b8588e6ac926059ae075fa187fe5ea0e5c291826330d31b9175791e3b4e31da3",
    LAUNCHER: "f4b79011a8636ba2300fe0c8e1fa2ade17b0e5a26860eae76ee10f17645d9bb1",
    "app/ops/host_secret_bootstrap.py": "948faa7e6c56cccd0b8b7af70050fabb6424c8025e2884dee873f6446c82f821",
}
MANIFEST_SHA256 = "822ac1094299489b6f40f39a4c32fbf6ee886ebe3e629c2c6aaa37f5fffe9405"
CUSTODY_SHA256 = "43d3ac93535bbe3ed577021ad00f8d2a5a7c5c2fbf8078d7da3d4f840151ac94"
ARCHIVE_SHA256 = "93cfac95951972e471c81749ae3247b12f1b74043aa465ff94615e3f4a019e1e"
ARCHIVE_BYTES = 1_914_880
SOURCE_COMMIT = "afb7990f61a97a5616e7c4a795578ddca1ca1b4e"
TEMPLATE = "config/systemd/yggdrasil-host-probe@.service"
TEMPLATE_SHA256 = "c9aa169c8cec7f5e85bcea94115236fc2d2e159060b39f4da085ff318b325332"
PACKAGE_PATHS = (
    "app/__init__.py",
    "app/ops",
    "config/secrets/host_secret_contract.json",
    TEMPLATE,
    LAUNCHER,
    "ops/host-setup/mac-mini/notification_channels.py",
    PROBE,
)
PREP = Path(__file__).resolve().parent
DEV_CREDENTIAL = (
    "bws-machine-account-token",
    "/var/lib/yggdrasil/bws-tokens/dev/current",
)
UNIT_KEYS = (
    "Id",
    "Names",
    "LoadState",
    "ActiveState",
    "SubState",
    "UnitFileState",
    "MainPID",
    "InvocationID",
    "ControlGroup",
    "ExecMainStartTimestampMonotonic",
    "InactiveEnterTimestampMonotonic",
    "NRestarts",
    "Job",
    "NeedDaemonReload",
    "FragmentPath",
    "DropInPaths",
    "User",
    "Group",
    "WorkingDirectory",
    "ExecStart",
    "EnvironmentFiles",
    "Environment",
    "KillMode",
    "Restart",
    "TimeoutStopUSec",
    "Type",
    "NotifyAccess",
    "ExecStop",
    "ExecStopPost",
    "SendSIGKILL",
    "KillSignal",
    "FinalKillSignal",
    "TimeoutStopFailureMode",
    "RuntimeDirectory",
    "RuntimeDirectoryMode",
    "StateDirectory",
    "StateDirectoryMode",
    "LoadCredentialEncrypted",
    "StandardOutput",
    "StandardError",
    "ProtectSystem",
    "PrivateTmp",
    "PrivateDevices",
    "NoNewPrivileges",
    "ReadWritePaths",
    "ReadOnlyPaths",
    "RestrictAddressFamilies",
    "UMask",
)
VOLATILE = {
    "ActiveState",
    "SubState",
    "MainPID",
    "InvocationID",
    "ControlGroup",
    "ExecMainStartTimestampMonotonic",
    "InactiveEnterTimestampMonotonic",
    "NRestarts",
}
RESTORATION_RESERVE = 65
MAX_PROBE_STOP_SECONDS = 30
JOURNAL_FIELDS = "MESSAGE,_BOOT_ID,_SYSTEMD_UNIT,_SYSTEMD_INVOCATION_ID,_SYSTEMD_CGROUP,_TRANSPORT,_STREAM_ID,_PID,__MONOTONIC_TIMESTAMP,__CURSOR"
LOG_FORMAT = re.compile(
    r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d{3} \[prod-probe\] (INFO|WARNING|ERROR) (.*)"
)
CONFIRMED = "discord webhook push confirmed: 200"
DOWN = "probe-down alert sent and outage state recorded: environment=dev"
REPEAT = (
    "probe-down detected but outage already recorded; suppressing duplicate alert. environment=dev"
)
RECOVERED = "probe-recovered alert sent; outage state cleared: environment=dev"


class Refusal(Exception):
    pass


class Unknown(Exception):
    pass


def native_entry(role: Any = None, data: Any = None, **unsupported: Any) -> Any:
    """Use actual platform ports; injected test ports enter below here."""
    if (
        unsupported
        or not isinstance(role, str)
        or role
        not in {
            "cli",
            "remote-launch",
            "supervised-first-preflight",
            "qualified-worker",
            "watchdog",
        }
    ):
        raise Refusal(UNBOUND_OFFLINE_DRAFT)
    result = native_dispatch(role, data, LinuxDependencies.standard_library())
    if role == "remote-launch":
        if result.get("schema") == "fixed_dev_probe.outcome.v1":
            return result
        return native_completion_receipt(
            result, carrier_packet(json.dumps(data["packet"]).encode())
        )
    return result


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise Refusal("duplicate_json_field")
        result[key] = value
    return result


def identifier(value: str, width: int = 32) -> bool:
    return (
        isinstance(value, str)
        and re.fullmatch(r"[0-9a-f]{%d}" % width, value) is not None
        and value != "0" * width
    )


def absolute(value: str) -> bool:
    return (
        isinstance(value, str)
        and value.startswith("/")
        and not value.startswith("//")
        and str(PurePosixPath(value)) == value
        and ".." not in PurePosixPath(value).parts
        and re.fullmatch(r"/[A-Za-z0-9_./@-]+", value) is not None
    )


def load_public_custody(
    source: str,
    *,
    subprocess_port: Any,
    selector_port: Any,
    os_port: Any,
    signal_port: Any,
    clock_port: Any,
) -> Callable[..., str]:
    """Reuse ONLY public bounded_process/safe_command; no PROD namespace/import.

    Every effect dependency must be injected. This preparation only accepts fake
    ports. The reused function owns setup, pipes, selector, termination and reap.
    A raised close/transport/reap result propagates to the caller's sticky UNKNOWN.
    """
    dependencies = (subprocess_port, selector_port, os_port, signal_port, clock_port)
    if any(getattr(port, "fixture_only", None) is not True for port in dependencies):
        raise Refusal(UNBOUND_OFFLINE_DRAFT)
    selected = {}
    for node in ast.parse(source).body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef)) and node.name in {
            "OperationFailure",
            "_bounded_process",
            "_safe_command",
        }:
            selected[node.name] = (
                "\n".join(source.splitlines()[node.lineno - 1 : node.end_lineno]) + "\n"
            )
    if (
        set(selected) != {"OperationFailure", "_bounded_process", "_safe_command"}
        or sha(selected["_bounded_process"].encode()) != CUSTODY_SHA256
    ):
        raise Refusal("accepted_custody_source_drift")
    namespace = dict(
        subprocess=subprocess_port,
        selectors=selector_port,
        os=os_port,
        signal=signal_port,
        time=clock_port,
    )
    exec(
        "from __future__ import annotations\n"
        + "\n".join(
            selected[key] for key in ("OperationFailure", "_bounded_process", "_safe_command")
        ),
        namespace,
    )
    return namespace["_safe_command"]


@dataclass(frozen=True)
class Handle:
    operation: str
    transport: str
    target: str

    @property
    def fingerprint(self) -> str:
        if any(
            not isinstance(value, str) or not value or len(value) > 256
            for value in (self.operation, self.transport, self.target)
        ):
            raise Refusal("original_handle_unbound")
        return sha("\0".join((self.operation, self.transport, self.target)).encode())


@dataclass(frozen=True)
class CommandResult:
    data: bytes = field(repr=False)
    handle_sha256: str
    exit_code: int | None
    reap: str
    closes: str


@dataclass
class Caller:
    handle: Handle
    clock: Any
    command: Any
    runtime: Any
    socket_factory: Any
    deadline: float
    phase_seconds: float
    max_reads: int = 128
    max_bytes: int = 4_194_304
    phase: str = "admission"
    unknown_reasons: list[str] = field(default_factory=list)
    reads: int = 0
    bytes_read: int = 0
    native_scope: Any = None

    def __post_init__(self) -> None:
        self.original_handle = self.handle.fingerprint
        fixture = all(
            getattr(port, "fixture_only", None) is True
            for port in (self.clock, self.command, self.runtime, self.socket_factory)
        )
        native = (
            isinstance(self.native_scope, FrozenNativeScope)
            and isinstance(self.clock, NativeClock)
            and isinstance(self.command, NativeCommand)
            and isinstance(self.runtime, LinuxRuntimeReader)
            and isinstance(self.socket_factory, NativeSocketFactory)
        )
        if not fixture and not native:
            raise Refusal(UNBOUND_OFFLINE_DRAFT)
        if native and any(
            port.scope != self.native_scope
            for port in (self.clock, self.command, self.runtime, self.socket_factory)
        ):
            raise Refusal("native_ports_not_same_frozen_dev_operation")
        now = self.clock()
        if (
            any(
                type(value) not in {int, float} or not math.isfinite(value)
                for value in (now, self.deadline, self.phase_seconds)
            )
            or not 0 < self.phase_seconds <= self.deadline - now
        ):
            raise Refusal("whole_caller_budget_unbound")
        self.phase_start = now

    def unknown(self, reason: str) -> None:
        if reason not in self.unknown_reasons:
            self.unknown_reasons.append(reason)

    def check(self, count: int = 0) -> float:
        if self.unknown_reasons or self.handle.fingerprint != self.original_handle:
            self.unknown("original_handle_or_custody_unknown")
            raise Unknown("original_handle_sticky_unknown")
        remaining = min(
            self.deadline - self.clock(),
            getattr(self, "work_deadline", self.deadline) - self.clock(),
            self.phase_seconds - (self.clock() - self.phase_start),
        )
        self.bytes_read += count
        if (
            remaining <= 0
            or count < 0
            or self.bytes_read > self.max_bytes
            or self.reads > self.max_reads
        ):
            self.unknown("whole_caller_phase_or_allocation_bound")
            raise Unknown("whole_caller_phase_or_allocation_bound")
        return remaining

    def begin(self, phase: str) -> None:
        self.check()
        self.phase, self.phase_start = phase, self.clock()

    def read_runtime(
        self, binding: "Binding", *, health: bool = False, allow_uninstalled_source: bool = False
    ) -> "Runtime":
        self.reads += 1
        remaining = self.check()
        try:
            if isinstance(self.runtime, LinuxRuntimeReader):
                value = self.runtime.read(
                    binding,
                    original_handle=self.original_handle,
                    timeout=remaining,
                    require_health=health,
                    allow_uninstalled_source=allow_uninstalled_source,
                )
            else:
                value = self.runtime.read(
                    binding, original_handle=self.original_handle, timeout=remaining
                )
            self.check()
            if not isinstance(value, Runtime) or value.handle_sha256 != self.original_handle:
                raise Unknown("runtime_read_unbound_to_original_handle")
            return value
        except BaseException:
            self.unknown("runtime_transport_or_read_unknown")
            raise

    def run(self, argv: tuple[str, ...], *, effect: bool = False, limit: int = 131_072) -> bytes:
        self.reads += 1
        remaining = self.check()
        # Accepted custody reserves up to two seconds for kill/reap on failure.
        # Include that reserve inside the caller/phase deadline, not after it.
        if remaining <= 2.1:
            self.unknown("process_custody_cleanup_reserve_exhausted")
            raise Unknown("process_custody_cleanup_reserve_exhausted")
        try:
            result = self.command.run(
                argv,
                timeout=remaining - 2.1,
                limit=limit,
                effect=effect,
                original_handle=self.original_handle,
            )
            if (
                not isinstance(result, CommandResult)
                or result.handle_sha256 != self.original_handle
                or result.exit_code != 0
                or type(result.exit_code) is not int
                or result.reap != "reaped"
                or result.closes != "closed"
                or not isinstance(result.data, bytes)
                or len(result.data) > limit
            ):
                raise Unknown("command_exit_reap_close_or_handle_unconfirmed")
            self.check(len(result.data))
            return result.data
        except BaseException:
            self.unknown("command_transport_or_custody_unknown")
            raise

    def close(self, label: str, close: Callable[[], Any]) -> None:
        # Ownership survives uncertainty; close all known-owned local handles.
        # This does not authorize service replay, state rewind or remote cleanup.
        try:
            result = close()
            if result is not None:
                raise Unknown("unexpected_close_result")
        except BaseException:
            self.unknown(label + "_close_unknown")


@dataclass(frozen=True)
class Binding:
    target: str
    transport: str
    standing_reference: str
    expected_role: str
    window_start: float
    window_end: float
    boot_id: str
    net_namespace: str
    producer_route: str
    package: str
    sdk: str
    sdk_realpath: str
    config: str
    state_file: str
    heartbeat: str
    heartbeat_backing: str
    worker_pid: str
    worker_start: str
    api_base: str
    observation_max_age: float

    def require(self, caller: Caller) -> None:
        caller.check()
        try:
            parsed = urlsplit(self.api_base)
            port = parsed.port
        except (ValueError, TypeError):
            raise Refusal("normal_endpoint_unqualified") from None
        if (
            self.expected_role != "Product Runtime DEV"
            or self.target != caller.handle.target
            or self.transport != caller.handle.transport
        ):
            raise Refusal("dev_target_transport_or_role_unbound")
        if any(
            not isinstance(value, str) or not value or len(value) > 4096
            for value in (
                self.standing_reference,
                self.producer_route,
                self.heartbeat_backing,
                self.net_namespace,
            )
        ):
            raise Refusal("ownership_route_namespace_or_backing_unbound")
        if any(
            not absolute(value)
            for value in (
                self.package,
                self.sdk,
                self.sdk_realpath,
                self.config,
                self.state_file,
                self.heartbeat,
            )
        ):
            raise Refusal("actual_paths_unbound_or_aliased")
        if (
            not identifier(self.boot_id)
            or not identifier(self.worker_start, 64)
            or not self.worker_pid.isdigit()
            or int(self.worker_pid) < 1
        ):
            raise Refusal("boot_or_worker_producer_unbound")
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or port == 0
            or parsed.username
            or parsed.password
            or parsed.path
            or parsed.query
            or parsed.fragment
            or self.api_base.endswith("/")
            or any(char.isspace() for char in self.api_base)
        ):
            raise Refusal("normal_endpoint_unqualified")
        if (
            any(
                type(value) not in {int, float} or not math.isfinite(value)
                for value in (self.window_start, self.window_end, self.observation_max_age)
            )
            or not self.window_start <= caller.clock() < self.window_end
            or self.window_end > caller.deadline
            or self.observation_max_age <= 0
        ):
            raise Refusal("fixed_window_unbound_or_expired")


@dataclass(frozen=True)
class Process:
    pid: str
    parent: str
    start_identity: str
    uid: int
    cgroup: str
    executable: str
    cwd: str
    argv: tuple[str, ...] = field(repr=False)
    stderr_device: int
    stderr_inode: int
    stderr_target: str
    net_namespace: str
    # Key names only; credential values must never cross this interface.
    environment_keys: tuple[str, ...]


def normal_stream_pid(pid: Any, creator: Process | None, child: Process | None) -> bool:
    # An inherited journald stream can retain its creator's credentials or
    # attribute a write to the exact child. Runtime.qualify and Peer separately
    # bind both complete process identities, parentage and shared stderr FD.
    return (
        isinstance(pid, str)
        and creator is not None
        and child is not None
        and pid in (creator.pid, child.pid)
    )


@dataclass(frozen=True)
class Runtime:
    """Selected concrete preflight observations, not caller proof booleans.

    The native producer performs bounded descriptor, process and cgroup reads.
    Tests substitute external ports while keeping this qualification real.
    """

    handle_sha256: str
    target: str
    transport: str
    standing_reference: str
    role: str
    route: str
    boot_id: str
    observed_monotonic: float
    epoch_seconds: float
    invocation: str
    cgroup: str
    members: tuple[str, ...]
    creator: Process | None
    child: Process | None
    stream: str
    journal_cursor: str
    source_hashes: tuple[tuple[str, str], ...]
    source_manifest_sha256: str
    consumer: str
    project: str
    binding_name: str
    config_sha256: str
    incident_writer_pids: tuple[str, ...]
    active_owner_references: tuple[str, ...]
    pending_controller_operations: tuple[str, ...]
    readyz_url: str
    readyz_status: int
    health_url: str
    health_status: int
    health_body: bytes = field(repr=False)
    worker_pid: str
    worker_start: str
    heartbeat_path: str
    heartbeat_backing: str
    http_children: tuple[Process, ...] = ()

    def independent_health(self, binding: Binding) -> None:
        try:
            payload = json.loads(self.health_body, object_pairs_hook=unique)
        except (ValueError, TypeError, UnicodeError):
            raise Refusal("independent_health_response_malformed") from None
        if (
            self.readyz_url != binding.api_base + "/readyz"
            or self.readyz_status != 200
            or self.health_url != binding.api_base + "/api/health"
            or self.health_status != 200
            or not isinstance(payload, dict)
            or payload.get("required_ok") is not True
            or payload.get("full_channel_qualified") is False
        ):
            raise Refusal("independent_readyz_or_required_health_unhealthy")
        if (self.worker_pid, self.worker_start, self.heartbeat_path, self.heartbeat_backing) != (
            binding.worker_pid,
            binding.worker_start,
            binding.heartbeat,
            binding.heartbeat_backing,
        ):
            raise Refusal("actual_heartbeat_producer_translation_unbound")

    def qualify(
        self,
        binding: Binding,
        caller: Caller,
        unit: dict[str, str],
        config_sha: str,
        *,
        active: bool,
        health: bool = False,
    ) -> None:
        binding.require(caller)
        if (
            self.target,
            self.transport,
            self.standing_reference,
            self.role,
            self.route,
            self.boot_id,
        ) != (
            binding.target,
            binding.transport,
            binding.standing_reference,
            binding.expected_role,
            binding.producer_route,
            binding.boot_id,
        ):
            raise Unknown("runtime_selection_changed")
        if (
            not 0 <= caller.clock() - self.observed_monotonic <= binding.observation_max_age
            or self.config_sha256 != config_sha
        ):
            raise Unknown("runtime_config_or_observation_stale")
        if (
            self.active_owner_references != (binding.standing_reference,)
            or self.pending_controller_operations
        ):
            raise Refusal("foreign_owner_or_pending_controller")
        if (
            dict(self.source_hashes) != SOURCE_HASHES
            or len(self.source_hashes) != len(SOURCE_HASHES)
            or self.source_manifest_sha256 != MANIFEST_SHA256
        ):
            raise Refusal("selected_source_unqualified")
        if (self.consumer, self.project, self.binding_name) != (
            "heimdal-external-alerts",
            "non-prod",
            "shared/discord.webhook",
        ):
            raise Refusal("normal_fixed_bws_consumer_unqualified")
        if health:
            self.independent_health(binding)
        if not active:
            if (
                self.members
                or self.creator is not None
                or self.child is not None
                or self.incident_writer_pids
            ):
                raise Unknown("stopped_cgroup_or_state_writer_not_reaped")
            return
        if self.creator is None or self.child is None:
            raise Unknown("fixed_creator_child_mapping_missing")
        creator, child = self.creator, self.child
        http_pids = {process.pid for process in self.http_children}
        if (
            self.invocation != unit["InvocationID"]
            or self.cgroup != unit["ControlGroup"]
            or creator.pid != unit["MainPID"]
            or set(self.members) != {creator.pid, child.pid} | http_pids
            or len(self.members) != 2 + len(self.http_children)
            or self.incident_writer_pids != (child.pid,)
        ):
            raise Unknown("owned_dev_incarnation_or_exclusive_writer_unqualified")
        for process in self.http_children:
            expected = (
                binding.sdk,
                "-I",
                "-c",
                HTTP_CHILD_CODE,
                binding.package + "/ops/host-setup/mac-mini",
            )
            if (
                process.parent != child.pid
                or process.argv != expected
                or process.environment_keys
                or process.cgroup != self.cgroup
                or process.executable != binding.sdk_realpath
                or process.uid != 0
            ):
                raise Unknown("normal_http_child_not_fixed_source_reader")
        if (
            creator.pid == child.pid
            or child.parent != creator.pid
            or not identifier(self.stream)
            or not self.journal_cursor
        ):
            raise Unknown("fixed_child_ancestry_stream_or_cursor_unbound")
        for process in (creator, child):
            if (
                not process.pid.isascii()
                or not process.pid.isdigit()
                or int(process.pid) < 1
                or not identifier(process.start_identity, 64)
                or process.uid != 0
                or process.cgroup != self.cgroup
                or process.executable != binding.sdk_realpath
                or process.cwd != binding.package
                or process.net_namespace != binding.net_namespace
            ):
                raise Unknown("process_sdk_identity_or_namespace_unqualified")
            if (
                type(process.stderr_device) is not int
                or process.stderr_device < 0
                or type(process.stderr_inode) is not int
                or process.stderr_inode < 1
                or process.stderr_target != f"socket:[{process.stderr_inode}]"
            ):
                raise Unknown("inherited_stream_fd_unqualified")
        if (creator.stderr_device, creator.stderr_inode, creator.stderr_target) != (
            child.stderr_device,
            child.stderr_inode,
            child.stderr_target,
        ):
            raise Unknown("creator_child_inherited_stream_mapping_unqualified")
        if creator.argv != (
            binding.sdk,
            binding.package + "/" + LAUNCHER,
            "--channel",
            "dev",
        ) or child.argv != (binding.sdk, binding.package + "/" + PROBE, "--loop"):
            raise Unknown("normal_fixed_dev_launcher_or_child_unqualified")
        if {"BWS_ACCESS_TOKEN", "BWS_ACCESS_TOKEN_FILE", "CREDENTIALS_DIRECTORY"}.intersection(
            child.environment_keys
        ) or {
            "HOST_SECRET_RUNTIME_ENV_FILE",
            "HOST_SECRET_BOOTSTRAP_CHANNEL",
            "HOST_SECRET_BOOTSTRAP_CONSUMER",
        } - set(child.environment_keys):
            raise Refusal("normal_child_token_scrubbing_or_runtime_binding_unqualified")


def systemd(action: str) -> tuple[str, ...]:
    if action == "show":
        return (
            "/usr/bin/systemctl",
            "show",
            UNIT,
            "--property=" + ",".join(UNIT_KEYS),
            "--all",
            "--no-pager",
        )
    if action in {"stop", "start"}:
        return "/usr/bin/systemctl", action, UNIT, "--no-pager"
    if action == "reload_for_temporary_dev":
        return "/usr/bin/systemctl", "daemon-reload"
    raise Refusal("outside_fixed_dev_service_operations")


def systemctl_fields(raw: bytes | str, keys: tuple[str, ...]) -> dict[str, str]:
    """Decode our exact --all property projection, including empty arrays.

    systemctl-show's EnvironmentFiles/Exec* structure-array printers emit one
    line per element and no line for an empty array, even with --all. Only
    those fixed array properties have an implicit empty representation; every
    scalar/string/list property must be present. Nonempty duplicate array
    entries remain unsupported rather than being silently overwritten.
    """
    fields: dict[str, str] = {}
    try:
        for line in (raw.decode("utf-8") if isinstance(raw, bytes) else raw).splitlines():
            key, separator, value = line.partition("=")
            if (
                not separator
                or key not in keys
                or key in fields
                or any(ord(char) < 32 for char in value)
            ):
                raise ValueError()
            fields[key] = value
    except (ValueError, UnicodeError):
        raise Refusal("unit_metadata_shape_or_duplicate") from None
    for key in {"EnvironmentFiles", "ExecStart", "ExecStop", "ExecStopPost"}.intersection(keys):
        fields.setdefault(key, "")
    if set(fields) != set(keys):
        raise Refusal("unit_metadata_missing_property")
    return fields


def configured_exec(raw: str) -> tuple[tuple[tuple[str, str], ...], ...]:
    """Keep the complete configured command, excluding execution observations.

    systemctl's ExecStart includes timestamps/PID/exit status which change on
    every invocation. Unknown fields and ambiguous command syntax fail closed.
    """
    if not raw:
        return ()
    execution = {"start_time", "stop_time", "pid", "code", "status"}
    commands, position = [], 0
    for match in re.finditer(r"\{([^{}]*)\}", raw):
        if raw[position : match.start()].strip():
            raise Refusal("configured_exec_shape")
        fields = {}
        for item in re.split(r"\s+;\s*", match.group(1).strip()):
            if not item.strip():
                continue
            key, separator, value = item.strip().partition("=")
            if (
                not separator
                or key in fields
                or key not in execution | {"path", "argv[]", "ignore_errors", "flags"}
            ):
                raise Refusal("configured_exec_fields")
            fields[key] = value
        if not {"path", "argv[]", "ignore_errors"} <= fields.keys():
            raise Refusal("configured_exec_incomplete")
        commands.append(
            tuple(sorted((key, value) for key, value in fields.items() if key not in execution))
        )
        position = match.end()
    if not commands or raw[position:].strip():
        raise Refusal("configured_exec_shape")
    return tuple(commands)


def unit_profile(unit: dict[str, str], *, cleanup: bool = False) -> dict[str, Any]:
    return {
        key: configured_exec(unit[key])
        if key in {"ExecStart", "ExecStop", "ExecStopPost"}
        else unit[key]
        for key in UNIT_KEYS
        if key not in VOLATILE | ({"Job"} if cleanup else set())
    }


def dev_credential_property() -> tuple[str, ...]:
    return (
        "/usr/bin/busctl",
        "--json=short",
        "get-property",
        "org.freedesktop.systemd1",
        "/org/freedesktop/systemd1/unit/yggdrasil_2dhost_2dprobe_40dev_2eservice",
        "org.freedesktop.systemd1.Service",
        "LoadCredentialEncrypted",
    )


def read_dev_unit(command: Callable[..., bytes]) -> bytes:
    """Join the fixed unit profile to its typed credential ID/path metadata.

    systemctl can render a(ss) as [unprintable]. Only the exact typed D-Bus
    property establishes the binding; neither that marker nor a path suffix
    does. Both typed reads must qualify around a stable unit/config profile.
    Transient job/process state may advance; return the later actual sample.
    Every read uses the caller's existing finite process/byte/close budget.
    """
    raw = command(systemd("show"))
    first = systemctl_fields(raw, UNIT_KEYS)
    if first["LoadState"] == "not-found":
        # An absent unit needs no credential getter. parse_unit still has to
        # positively qualify absence before temporary staging is permitted.
        return raw
    snapshots = []
    expected = ":".join(DEV_CREDENTIAL)
    for fields in (first, None):
        if fields is None:
            fields = systemctl_fields(command(systemd("show")), UNIT_KEYS)
        if (
            fields["Id"] != UNIT
            or fields["Names"].split() != [UNIT]
            or fields["LoadState"] != "loaded"
            or fields["LoadCredentialEncrypted"] not in {"[unprintable]", expected}
        ):
            raise Refusal("typed_credential_unit_or_projection_unqualified")
        raw_property = command(dev_credential_property(), limit=8192)
        try:
            value = json.loads(raw_property, object_pairs_hook=unique)
        except (ValueError, UnicodeError):
            raise Refusal("typed_dev_credential_metadata_malformed") from None
        if (
            not isinstance(value, dict)
            or set(value) != {"type", "data"}
            or value["type"] != "a(ss)"
            or value["data"] != [list(DEV_CREDENTIAL)]
        ):
            raise Refusal("typed_dev_credential_binding_unqualified")
        fields["LoadCredentialEncrypted"] = expected
        snapshots.append(fields)
    if unit_profile(snapshots[0], cleanup=True) != unit_profile(snapshots[1], cleanup=True):
        raise Unknown("typed_credential_unit_profile_changed_during_read")
    return "".join(key + "=" + snapshots[1][key] + "\n" for key in UNIT_KEYS).encode()


def dev_cgroup(path: str) -> bool:
    # Instantiated services normally live below a per-template subslice.
    parts = PurePosixPath(path).parts
    return (
        len(parts) >= 3
        and parts[:2] == ("/", "system.slice")
        and parts[-1] == UNIT
        and all(re.fullmatch(r"[A-Za-z0-9_.\\-]+\.slice", part) for part in parts[2:-1])
        and str(PurePosixPath(path)) == path
    )


def finite_stop_seconds(unit: dict[str, str]) -> float:
    raw = unit["TimeoutStopUSec"]
    pieces = re.findall(r"(\d+(?:\.\d+)?)(us|ms|s|min|h)", raw)
    if not pieces or "".join(number + suffix for number, suffix in pieces) != raw.replace(" ", ""):
        raise Refusal("normal_stop_timeout_not_finite_supported")
    seconds = sum(
        float(number) * {"us": 1e-6, "ms": 1e-3, "s": 1, "min": 60, "h": 3600}[suffix]
        for number, suffix in pieces
    )
    if not 0 < seconds <= MAX_PROBE_STOP_SECONDS:
        raise Refusal("normal_stop_timeout_exceeds_restoration_budget")
    if (
        unit["Type"] not in {"simple", "exec"}
        or unit["NotifyAccess"] != "none"
        or configured_exec(unit["ExecStop"])
        or configured_exec(unit["ExecStopPost"])
        or unit["SendSIGKILL"] != "yes"
        or unit["KillSignal"] != "15"
        or unit["FinalKillSignal"] != "9"
        or unit["TimeoutStopFailureMode"] not in {"terminate", "kill"}
    ):
        raise Refusal("normal_stop_kill_behavior_unqualified")
    return seconds


def parse_unit(
    raw: bytes,
    *,
    allow_absent: bool = False,
    allow_restarts: bool = False,
    cleanup_states: bool = False,
) -> dict[str, str]:
    fields = systemctl_fields(raw, UNIT_KEYS)
    if fields["Id"] != UNIT or fields["Names"].split() != [UNIT]:
        raise Refusal("unit_metadata_missing_aliased_or_wrong_channel")
    if allow_absent and fields["LoadState"] == "not-found":
        if (
            fields["ActiveState"] != "inactive"
            or fields["SubState"] != "dead"
            or fields["MainPID"] != "0"
            or fields["UnitFileState"] not in {"", "not-found"}
            or fields["DropInPaths"]
            or fields["FragmentPath"]
            or fields["Job"] not in {"", "0"}
            or fields["NeedDaemonReload"] != "no"
            or (
                fields["NRestarts"] != "0"
                and not (
                    allow_restarts
                    and fields["NRestarts"].isascii()
                    and fields["NRestarts"].isdigit()
                )
            )
        ):
            raise Refusal("absent_dev_unit_not_positively_quiescent")
        return fields
    if (
        fields["LoadState"] != "loaded"
        or fields["UnitFileState"] not in {"enabled", "disabled", "static", "indirect"}
        or fields["NeedDaemonReload"] != "no"
        or (not cleanup_states and fields["Job"] not in {"", "0"})
        or (
            fields["NRestarts"] != "0"
            and not (
                allow_restarts and fields["NRestarts"].isascii() and fields["NRestarts"].isdigit()
            )
        )
    ):
        raise Refusal("unit_masked_job_restart_or_load_unqualified")
    for key in ("MainPID", "ExecMainStartTimestampMonotonic", "InactiveEnterTimestampMonotonic"):
        if not fields[key].isascii() or not fields[key].isdigit():
            raise Refusal("unit_numeric_identity_unqualified")
    if cleanup_states:
        # This is decoding only. The guardian must separately prove its
        # physical marker, exact profile/config and any live incarnation.
        if (
            fields["ActiveState"]
            not in {"active", "activating", "deactivating", "reloading", "inactive", "failed"}
            or re.fullmatch(r"[a-z][a-z-]{0,63}", fields["SubState"]) is None
            or len(fields["Job"]) > 4096
            or (int(fields["MainPID"]) > 0 and not identifier(fields["InvocationID"]))
            or (fields["ControlGroup"] and not dev_cgroup(fields["ControlGroup"]))
        ):
            raise Unknown("guard_unit_lifecycle_metadata_unqualified")
        return fields
    if fields["ActiveState"] == "active":
        if (
            fields["SubState"] != "running"
            or int(fields["MainPID"]) < 1
            or int(fields["ExecMainStartTimestampMonotonic"]) < 1
            or not identifier(fields["InvocationID"])
            or not dev_cgroup(fields["ControlGroup"])
        ):
            raise Unknown("active_dev_incarnation_unqualified")
    elif (
        fields["ActiveState"] != "inactive"
        or fields["MainPID"] != "0"
        or fields["SubState"] != "dead"
    ):
        raise Unknown("dev_not_positively_active_or_quiescent")
    return fields


def normal_state_directory(binding: Binding) -> str:
    temporary = re.fullmatch(
        r"(/var/lib/ygg-dev-probe-[0-9a-f]{32})/probe-state/alert-state\.json",
        binding.state_file,
    )
    if temporary is None:
        return "yggdrasil-host-probe-dev"
    root = temporary[1]
    if binding.package != root + "/source" or binding.config != root + "/source/dev-private.env":
        raise Refusal("temporary_state_not_bound_to_owned_source_configuration")
    return root.removeprefix("/var/lib/") + "/probe-state"


def normal_unit(unit: dict[str, str], binding: Binding) -> None:
    expected_exec = binding.sdk + " " + binding.package + "/" + LAUNCHER + " --channel dev"
    commands = configured_exec(unit["ExecStart"])
    configured = dict(commands[0]) if len(commands) == 1 else {}
    if (
        unit["User"] != "root"
        or unit["Group"] != "root"
        or unit["WorkingDirectory"] != binding.package
        or unit["EnvironmentFiles"].replace(" ", "") != binding.config + "(ignore_errors=no)"
        or configured.get("argv[]") != expected_exec
        or configured.get("path") != binding.sdk
        or configured.get("ignore_errors") != "no"
        or configured.get("flags", "") not in {"", "0"}
    ):
        raise Refusal("effective_unit_not_normal_fixed_dev_entry")
    environment = unit["Environment"].split()
    if environment.count("PYTHONPATH=" + binding.package) != 1 or any(
        value.startswith(("PYTHONDONTWRITEBYTECODE=", "PYTHONPYCACHEPREFIX="))
        for value in environment
    ):
        raise Refusal("normal_source_or_cache_policy_unqualified")
    for key, value in {
        "KillMode": "control-group",
        "Restart": "on-failure",
        "StandardOutput": "journal",
        "StandardError": "journal",
        "ProtectSystem": "strict",
        "PrivateTmp": "yes",
        "PrivateDevices": "yes",
        "NoNewPrivileges": "yes",
        "RuntimeDirectory": "yggdrasil-host-probe-dev",
        "RuntimeDirectoryMode": "0700",
        "StateDirectory": normal_state_directory(binding),
        "StateDirectoryMode": "0700",
        "UMask": "0077",
    }.items():
        if unit[key] != value:
            raise Refusal("normal_runtime_state_hardening_or_stream_unqualified")
    if unit["LoadCredentialEncrypted"] != ":".join(DEV_CREDENTIAL):
        raise Refusal("normal_dev_systemd_credential_unqualified")
    finite_stop_seconds(unit)


def parse_config(raw: bytes) -> dict[str, str]:
    if len(raw) > 65_536 or b"\0" in raw or not raw.endswith(b"\n"):
        raise Refusal("config_size_or_encoding")
    result = {}
    try:
        for line in raw.decode("ascii").splitlines():
            key, separator, value = line.partition("=")
            if (
                not separator
                or not re.fullmatch(r"[A-Z][A-Z0-9_]*", key)
                or key in result
                or not value
                or any(char.isspace() or char in "\"'\\$`" for char in value)
            ):
                raise Refusal("config_expansion_duplicate_or_ambiguous_line")
            result[key] = value
    except UnicodeError:
        raise Refusal("config_encoding") from None
    required = {
        "PROBE_ENVIRONMENT",
        "PROBE_ALERT_CHANNEL",
        "PROBE_BASE_URL",
        "PROBE_STATE_FILE",
        "PROBE_INTERVAL_SECONDS",
        "WORKER_HEARTBEAT_PATH",
        "WORKER_HEARTBEAT_STALE_SECONDS",
    }
    if not required.issubset(result) or any(
        key.startswith(("BWS_", "DISCORD_", "NTFY_", "TELEGRAM_", "SMTP_", "PROD_PROBE_", "PYTHON"))
        for key in result
    ):
        raise Refusal("config_required_binding_or_normal_consumer_override")
    return result


@dataclass(frozen=True)
class FileState:
    data: bytes = field(repr=False)
    device: int
    inode: int
    mode: int
    uid: int
    gid: int
    links: int
    mtime_ns: int
    ctime_ns: int

    @property
    def content_sha256(self) -> str:
        return sha(self.data)


def fs_guard(function: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(function)
    def wrapped(self: "PrivateFiles", *args: Any, **kwargs: Any) -> Any:
        self.caller.check()
        try:
            result = function(self, *args, **kwargs)
            self.caller.check()
            return result
        except (OSError, Unknown):
            self.caller.unknown("descriptor_file_effect_or_custody_unknown")
            raise

    return wrapped


class PrivateFiles:
    """Actual no-follow bounded reads/atomic writes in ONE private fixture root.

    This uses the public _open_directory/_read_bounded descriptor pattern, with
    a retained root FD instead of public PROD globals/absolute resource paths.
    No native path mode exists. An actual descriptor binding remains unbound.
    """

    def __init__(self, root: Path, caller: Caller, names: dict[str, str]):
        if (
            root.parent != PREP
            or re.fullmatch(r"fixture-[A-Za-z0-9_-]+", root.name) is None
            or set(names)
            != {"config", "incident", "heartbeat", "shared_prod", "ack_history", "unknown_fences"}
            or len(set(names.values())) != len(names)
            or any(
                re.fullmatch(r"[A-Za-z0-9_.-]+", name) is None or name in {".", ".."}
                for name in names.values()
            )
        ):
            raise Refusal("private_fixture_file_binding_only")
        self.ops = os
        self.caller, self.names, self.fd = caller, dict(names), None
        caller.check()
        descriptor = self.ops.open(
            root,
            self.ops.O_RDONLY | self.ops.O_DIRECTORY | self.ops.O_NOFOLLOW | self.ops.O_CLOEXEC,
        )
        self.fd = descriptor
        info = self.ops.fstat(descriptor)
        if info.st_uid != self.ops.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
            self.close()
            raise Refusal("fixture_root_owner_or_mode")
        self.root_identity = (
            info.st_dev,
            info.st_ino,
            info.st_uid,
            info.st_gid,
            stat.S_IMODE(info.st_mode),
        )
        self.uid, self.gid = info.st_uid, info.st_gid
        self.temporary: dict[str, FileState] = {}
        self.config_fd = None

    def attach_staged_config(self, descriptor: int) -> None:
        if self.config_fd is not None or self.temporary:
            raise Refusal("staged_config_binding_replay")
        self.caller.check()
        info = self.ops.fstat(descriptor)
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid != self.uid
            or info.st_gid != self.gid
            or stat.S_IMODE(info.st_mode) != 0o700
        ):
            raise Refusal("staged_config_directory_unqualified")
        self.config_fd = self.ops.dup(descriptor)
        self.config_directory_identity = (
            info.st_dev,
            info.st_ino,
            info.st_uid,
            info.st_gid,
            stat.S_IMODE(info.st_mode),
        )

    def detach_staged_config(self) -> None:
        if self.config_fd is not None:
            descriptor, self.config_fd = self.config_fd, None
            self.caller.close("staged_config_directory", lambda: self.ops.close(descriptor))
            self.caller.check()

    def _root(self) -> None:
        info = self.ops.fstat(self.fd)
        if (
            info.st_dev,
            info.st_ino,
            info.st_uid,
            info.st_gid,
            stat.S_IMODE(info.st_mode),
        ) != self.root_identity:
            raise Unknown("fixture_root_custody_changed")

    def _read(
        self, name: str, *, absent: bool = False, parent: int | None = None
    ) -> FileState | None:
        self._root()
        self.caller.reads += 1
        self.caller.check()
        descriptor = None
        parent = self.fd if parent is None else parent
        if parent == self.config_fd:
            info = self.ops.fstat(parent)
            if (
                info.st_dev,
                info.st_ino,
                info.st_uid,
                info.st_gid,
                stat.S_IMODE(info.st_mode),
            ) != self.config_directory_identity:
                raise Unknown("staged_config_parent_custody_changed")
        try:
            try:
                descriptor = self.ops.open(
                    name,
                    self.ops.O_RDONLY
                    | self.ops.O_NOFOLLOW
                    | self.ops.O_NONBLOCK
                    | self.ops.O_CLOEXEC,
                    dir_fd=parent,
                )
            except FileNotFoundError:
                if absent:
                    return None
                raise
            before = self.ops.fstat(descriptor)
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_uid != self.uid
                or before.st_gid != self.gid
                or before.st_nlink != 1
                or stat.S_IMODE(before.st_mode) != 0o600
                or before.st_size > 65_536
            ):
                raise Refusal("file_type_owner_mode_alias_or_bound")
            chunks = bytearray()
            while True:
                self.caller.check()
                block = self.ops.read(descriptor, min(16_384, 65_537 - len(chunks)))
                if not block:
                    break
                self.caller.check(len(block))
                chunks.extend(block)
                if len(chunks) > 65_536:
                    raise Refusal("file_allocation_bound")
            after = self.ops.fstat(descriptor)
            slot = self.ops.stat(name, dir_fd=parent, follow_symlinks=False)
            fields = lambda value: (
                value.st_dev,
                value.st_ino,
                value.st_mode,
                value.st_uid,
                value.st_gid,
                value.st_nlink,
                value.st_size,
                value.st_mtime_ns,
                value.st_ctime_ns,
            )
            if (
                fields(before) != fields(after)
                or fields(before) != fields(slot)
                or len(chunks) != before.st_size
            ):
                raise Unknown("file_changed_during_bounded_read")
            return FileState(
                bytes(chunks),
                before.st_dev,
                before.st_ino,
                stat.S_IMODE(before.st_mode),
                before.st_uid,
                before.st_gid,
                before.st_nlink,
                before.st_mtime_ns,
                before.st_ctime_ns,
            )
        finally:
            if descriptor is not None:
                self.caller.close("file", lambda: self.ops.close(descriptor))

    @fs_guard
    def read(self, key: str) -> FileState | None:
        parent = self.config_fd if key == "config" else None
        name = "dev-private.env" if key == "config" and parent is not None else self.names[key]
        return self._read(name, absent=key == "incident", parent=parent)

    @fs_guard
    def atomic_config(
        self, expected: FileState, data: bytes, *, restore: FileState | None = None
    ) -> FileState:
        if not isinstance(data, bytes) or len(data) > 65_536:
            raise Refusal("atomic_config_allocation_bound")
        self.caller.check(len(data))
        parent = self.fd if self.config_fd is None else self.config_fd
        config_name = self.names["config"] if self.config_fd is None else "dev-private.env"
        if self._read(config_name, parent=parent) != expected:
            raise Unknown("config_identity_changed_before_swap")
        name = ".owned-dev-config-" + secrets.token_hex(16)
        descriptor = None
        try:
            descriptor = self.ops.open(
                name,
                self.ops.O_WRONLY
                | self.ops.O_CREAT
                | self.ops.O_EXCL
                | self.ops.O_NOFOLLOW
                | self.ops.O_CLOEXEC,
                0o600,
                dir_fd=parent,
            )
            self.ops.fchmod(descriptor, expected.mode)
            created = self.ops.fstat(descriptor)
            # Retain the exclusive name/inode immediately, also on partial
            # write/close failure. Uncertain bytes never authorize blind unlink.
            self.temporary[name] = FileState(
                b"",
                created.st_dev,
                created.st_ino,
                stat.S_IMODE(created.st_mode),
                created.st_uid,
                created.st_gid,
                created.st_nlink,
                created.st_mtime_ns,
                created.st_ctime_ns,
            )
            if (created.st_uid, created.st_gid) != (expected.uid, expected.gid):
                raise Unknown("temporary_config_owner_changed")
            pending = memoryview(data)
            while pending:
                self.caller.check()
                count = self.ops.write(descriptor, pending[:16_384])
                if count <= 0:
                    raise Unknown("config_write_unconfirmed")
                pending = pending[count:]
            self.ops.fsync(descriptor)
            if restore is not None:
                self.ops.utime(descriptor, ns=(restore.mtime_ns, restore.mtime_ns))
                self.ops.fsync(descriptor)
        finally:
            if descriptor is not None:
                self.caller.close("temporary_config", lambda: self.ops.close(descriptor))
        self.caller.check()
        staged = self._read(name, parent=parent)
        assert staged is not None
        self.temporary[name] = staged
        if self._read(config_name, parent=parent) != expected:
            raise Unknown("config_slot_changed_before_atomic_replace")
        self.ops.replace(name, config_name, src_dir_fd=parent, dst_dir_fd=parent)
        del self.temporary[name]
        self.ops.fsync(parent)
        current = self._read(config_name, parent=parent)
        assert current is not None
        if current.data != data or (current.mode, current.uid, current.gid, current.links) != (
            expected.mode,
            expected.uid,
            expected.gid,
            1,
        ):
            raise Unknown("atomic_config_readback_unconfirmed")
        if restore is not None and current.mtime_ns != restore.mtime_ns:
            raise Unknown("exact_config_metadata_restore_unconfirmed")
        return current

    @fs_guard
    def cleanup(self) -> None:
        # Positive custody before any unlink; a foreign file never gets adopted.
        parent = self.fd if self.config_fd is None else self.config_fd
        for name, expected in self.temporary.items():
            if self._read(name, parent=parent) != expected:
                raise Unknown("temporary_config_cleanup_custody_changed")
        for name in list(self.temporary):
            self.ops.unlink(name, dir_fd=parent)
            del self.temporary[name]
        self.ops.fsync(parent)

    def close(self) -> None:
        if self.config_fd is not None:
            descriptor, self.config_fd = self.config_fd, None
            self.caller.close("staged_config_directory", lambda: self.ops.close(descriptor))
        if self.fd is not None:
            descriptor, self.fd = self.fd, None
            self.caller.close("private_root", lambda: self.ops.close(descriptor))


class SocketFactory:
    """The fixed native socket operations, with all OS boundaries injected.

    No default socket module is imported or selected. Fake-only construction is
    enforced for this preparation, while the actual option/FD/namespace checks
    are implemented here rather than delegated to an 'approved' boolean.
    """

    fixture_only = True

    def __init__(self, api: Any, descriptor_api: Any, namespace_reader: Any):
        if any(
            getattr(port, "fixture_only", None) is not True
            for port in (api, descriptor_api, namespace_reader)
        ):
            raise Refusal(UNBOUND_OFFLINE_DRAFT)
        self.api, self.descriptor_api, self.namespace_reader = api, descriptor_api, namespace_reader

    def create(
        self, family: str, kind: str, *, original_handle: str, net_namespace: str
    ) -> "HeldSocket":
        if (family, kind) != ("AF_INET", "SOCK_STREAM") or self.namespace_reader() != net_namespace:
            raise Unknown("socket_owner_network_namespace_unqualified")
        raw = self.api.socket(self.api.AF_INET, self.api.SOCK_STREAM)
        try:
            return HeldSocket(raw, self, original_handle, net_namespace)
        except BaseException:
            raw.close()
            raise


class HeldSocket:
    def __init__(self, raw: Any, factory: SocketFactory, original_handle: str, namespace: str):
        self.raw, self.factory, self.handle, self.namespace = (
            raw,
            factory,
            original_handle,
            namespace,
        )
        meta = factory.descriptor_api.fstat(raw.fileno())
        self.descriptor_identity = meta.st_dev, meta.st_ino

    def set_inheritable(self, value: bool) -> None:
        if value is not False:
            raise Refusal("socket_inheritance_forbidden")
        self.raw.set_inheritable(False)

    def bind(self, address: tuple[str, int]) -> None:
        if address != ("127.0.0.1", 0):
            raise Refusal("only_numeric_loopback_os_assigned_port")
        self.raw.bind(address)

    def getsockname(self) -> tuple[str, int]:
        return self.raw.getsockname()

    def observe(self) -> tuple[Any, ...]:
        api = self.factory.api
        meta = self.factory.descriptor_api.fstat(self.raw.fileno())
        if (
            (meta.st_dev, meta.st_ino) != self.descriptor_identity
            or not stat.S_ISSOCK(meta.st_mode)
            or self.raw.family != api.AF_INET
            or self.raw.type != api.SOCK_STREAM
        ):
            raise Unknown("socket_descriptor_identity_or_type_changed")
        address, port = self.raw.getsockname()
        return (
            "AF_INET",
            "SOCK_STREAM",
            self.factory.namespace_reader(),
            "BOUND_NOT_LISTENING"
            if self.raw.getsockopt(api.SOL_SOCKET, api.SO_ACCEPTCONN) == 0
            else "LISTENING",
            self.raw.get_inheritable(),
            self.raw.getsockopt(api.SOL_SOCKET, api.SO_REUSEADDR),
            self.raw.getsockopt(api.SOL_SOCKET, api.SO_REUSEPORT),
            address,
            port,
            self.handle,
        )

    def close(self) -> None:
        self.raw.close()
        if self.raw.fileno() != -1:
            raise Unknown("socket_descriptor_close_unconfirmed")


@dataclass(frozen=True)
class Peer:
    runtime: Runtime
    config_sha256: str
    start_usec: int

    @property
    def identity(self) -> tuple[Any, ...]:
        return (
            self.runtime.invocation,
            self.runtime.creator,
            self.runtime.child,
            self.runtime.cgroup,
            self.runtime.stream,
            self.config_sha256,
        )


def incident(snapshot: FileState | None) -> dict[str, Any] | None:
    if snapshot is None:
        return None
    try:
        value = json.loads(snapshot.data, object_pairs_hook=unique)
        if (
            not isinstance(value, dict)
            or set(value) != {"status", "environment", "ts", "failures", "correlation_id"}
            or value["status"] != "down"
            or value["environment"] != "dev"
            or type(value["ts"]) is not int
            or value["ts"] <= 0
            or not isinstance(value["failures"], list)
            or not value["failures"]
            or any(not isinstance(item, str) or not item for item in value["failures"])
            or not isinstance(value["correlation_id"], str)
        ):
            raise ValueError()
        UUID(value["correlation_id"])
        return value
    except (ValueError, TypeError, KeyError, UnicodeError):
        raise Refusal("invalid_or_foreign_incident_is_not_absence") from None


@dataclass
class Transitions:
    down: int = 0
    repeat_markers: int = 0
    completed_repeats: int = 0
    recovery: int = 0
    confirmation_pending: bool = False
    incident_bytes: bytes | None = field(default=None, repr=False)
    correlation: str | None = None
    last_stamp: int = 0
    last_outcome_stamp: int = 0
    seen: set[str] = field(default_factory=set)
    cursor: str = field(default="", repr=False)

    def consume(
        self,
        raw: bytes,
        peer: Peer,
        binding: Binding,
        before: FileState | None,
        after: FileState | None,
        cadence: int,
    ) -> None:
        # A repeat marker is at the final source statement before return False.
        # A following same-child normal outcome proves the preceding repeat
        # returned. Three markers prove TWO later completed suppressions without
        # inventing a new emitter, elapsed-time proof or healthy baseline cycle.
        if type(cadence) is not int or cadence < 1:
            raise Unknown("normal_loop_cadence_not_qualified")
        old, new = incident(before), incident(after)
        observed_state = before
        if len(raw) > 131_072 or len(raw.splitlines()) > 512:
            raise Unknown("bounded_normal_stream_read_exceeded")
        for line in raw.splitlines():
            try:
                row = json.loads(line, object_pairs_hook=unique)
                cursor, stamp, message = (
                    row["__CURSOR"],
                    row["__MONOTONIC_TIMESTAMP"],
                    row["MESSAGE"],
                )
                if (
                    not isinstance(cursor, str)
                    or not cursor
                    or len(cursor) > 4096
                    or any(ord(char) < 33 or ord(char) > 126 for char in cursor)
                    or cursor in self.seen
                    or not isinstance(stamp, str)
                    or not stamp.isascii()
                    or not stamp.isdigit()
                    or int(stamp) <= self.last_stamp
                    or int(stamp) < peer.start_usec
                    or not isinstance(message, str)
                ):
                    raise ValueError()
                if (row["_BOOT_ID"], row["_SYSTEMD_UNIT"], row["_SYSTEMD_INVOCATION_ID"]) != (
                    binding.boot_id,
                    UNIT,
                    peer.runtime.invocation,
                ):
                    raise Unknown("foreign_boot_unit_or_invocation")
                self.seen.add(cursor)
                self.cursor, self.last_stamp = cursor, int(stamp)
                match = LOG_FORMAT.fullmatch(message)
                if match is None:
                    if message.startswith("Traceback") or any(
                        text in message.lower()
                        for text in ("suppressed ", "dropped ", "rate limit", "missed ", "restart")
                    ):
                        raise Unknown("normal_stream_error_restart_or_loss")
                    continue
                if not normal_stream_pid(row["_PID"], peer.runtime.creator, peer.runtime.child) or (
                    row["_TRANSPORT"],
                    row["_SYSTEMD_CGROUP"],
                    row["_STREAM_ID"],
                ) != (
                    "stdout",
                    peer.runtime.cgroup,
                    peer.runtime.stream,
                ):
                    raise Unknown("creator_child_stream_mapping_changed")
                text = match[2]
                if match[1] == "ERROR" or text.startswith(
                    ("failed to send", "probe iteration failed", "probe execution failed")
                ):
                    raise Unknown("normal_iteration_or_delivery_failed")
                if text == CONFIRMED:
                    if self.confirmation_pending:
                        raise Unknown("extra_or_unpaired_confirmation")
                    self.confirmation_pending = True
                elif text == DOWN:
                    if (
                        self.down
                        or self.recovery
                        or not self.confirmation_pending
                        or old is not None
                        or new is None
                        or after is None
                    ):
                        raise Unknown("confirmed_down_or_persisted_incident_unproven")
                    self.down, self.confirmation_pending = 1, False
                    self.incident_bytes, self.correlation = after.data, new["correlation_id"]
                    observed_state = after
                    self.last_outcome_stamp = int(stamp)
                elif text == REPEAT:
                    if (
                        self.down != 1
                        or self.recovery
                        or self.confirmation_pending
                        or observed_state is None
                        or after is None
                        or observed_state != after
                        or after.data != self.incident_bytes
                    ):
                        raise Unknown("suppression_incident_cadence_or_send_unqualified")
                    self.repeat_markers += 1
                    self.completed_repeats = max(0, self.repeat_markers - 1)
                    self.last_outcome_stamp = int(stamp)
                elif text == RECOVERED:
                    if (
                        self.down != 1
                        or self.completed_repeats < 2
                        or self.recovery
                        or not self.confirmation_pending
                        or before is None
                        or before.data != self.incident_bytes
                        or new is not None
                    ):
                        raise Unknown("same_correlation_confirmed_recovery_unproven")
                    self.recovery, self.confirmation_pending = 1, False
                elif not text.startswith("probe ok:"):
                    raise Unknown("unexpected_source_signal")
            except (ValueError, TypeError, KeyError, UnicodeError):
                raise Unknown("normal_stream_shape_cursor_or_order") from None


def owned(function: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(function)
    def wrapped(self: "DevProbeAdapter", *args: Any, **kwargs: Any) -> Any:
        self.caller.check()
        try:
            result = function(self, *args, **kwargs)
            self.caller.check()
            return result
        except Unknown:
            self.caller.unknown("dev_adapter_evidence_or_effect_unknown")
            raise

    return wrapped


class DevProbeAdapter:
    def __init__(self, binding: Binding, caller: Caller, files: PrivateFiles):
        self.binding, self.caller, self.files = binding, caller, files
        self.original_unit: dict[str, str] | None = None
        self.unit: dict[str, str] | None = None
        self.runtime: Runtime | None = None
        self.peer: Peer | None = None
        self.original_config: FileState | None = None
        self.current_config: FileState | None = None
        self.socket: Any = None
        self.socket_state: Any = None
        self.state = "unadmitted"
        self.start_intents: set[str] = set()
        self.transitions = Transitions()

    def _observe(self, *, active: bool, health: bool = False) -> tuple[dict[str, str], Runtime]:
        assert self.current_config is not None
        unit = parse_unit(read_dev_unit(self.caller.run))
        if (unit["ActiveState"] == "active") is not active:
            raise Unknown("dev_service_state_unconfirmed")
        runtime = self.caller.read_runtime(self.binding, health=health)
        runtime.qualify(
            self.binding,
            self.caller,
            unit,
            self.current_config.content_sha256,
            active=active,
            health=health,
        )
        if self.original_unit is not None and unit_profile(unit) != unit_profile(
            self.original_unit
        ):
            raise Unknown("effective_unit_enablement_hardening_or_credential_drift")
        return unit, runtime

    def _same_active(self) -> None:
        unit, runtime = self._observe(active=True)
        assert self.unit is not None and self.runtime is not None
        keys = ("InvocationID", "MainPID", "ControlGroup", "ExecMainStartTimestampMonotonic")
        if any(unit[key] != self.unit[key] for key in keys) or (
            runtime.creator,
            runtime.child,
            runtime.stream,
        ) != (self.runtime.creator, self.runtime.child, self.runtime.stream):
            raise Unknown("dev_service_incarnation_or_stream_changed")

    def _preserved(self) -> None:
        for key, expected in self.preserved.items():
            if not preserves(self.files.read(key), expected):
                raise Unknown("shared_prod_ack_history_or_unknown_fence_changed")

    @owned
    def admit(self) -> None:
        """1. Qualify actual ownership, fixed SDK child/unit/config and baseline."""
        if self.state != "unadmitted":
            raise Refusal("admission_replay")
        self.binding.require(self.caller)
        config = self.files.read("config")
        assert config is not None
        values = parse_config(config.data)
        expected = {
            "PROBE_ENVIRONMENT": "dev",
            "PROBE_ALERT_CHANNEL": "discord",
            "PROBE_BASE_URL": self.binding.api_base,
            "PROBE_STATE_FILE": self.binding.state_file,
            "WORKER_HEARTBEAT_PATH": self.binding.heartbeat,
        }
        if any(values.get(key) != value for key, value in expected.items()):
            raise Refusal("actual_dev_configuration_not_selected_normal_route")
        try:
            self.cadence = int(values["PROBE_INTERVAL_SECONDS"])
            stale = float(values["WORKER_HEARTBEAT_STALE_SECONDS"])
        except ValueError:
            raise Refusal("normal_cadence_or_heartbeat_threshold_unqualified") from None
        if self.cadence < 1 or not math.isfinite(stale) or stale <= 0:
            raise Refusal("normal_cadence_or_heartbeat_threshold_unqualified")
        self.original_config = self.current_config = config
        unit, runtime = self._observe(active=True, health=True)
        normal_unit(unit, self.binding)
        if self.files.read("incident") is not None:
            # Invalid/foreign presence also refuses; it is never cleared/seeded.
            raise Refusal("preexisting_incident_not_baseline_absence")
        heartbeat = self.files.read("heartbeat")
        assert heartbeat is not None
        try:
            payload = json.loads(heartbeat.data, object_pairs_hook=unique)
            timestamp = float(payload.get("ts", payload.get("timestamp")))
        except (ValueError, TypeError, AttributeError, UnicodeError):
            raise Refusal("actual_producer_heartbeat_malformed") from None
        if (
            not math.isfinite(timestamp)
            or timestamp <= 0
            or not 0 <= runtime.epoch_seconds - timestamp <= stale
        ):
            raise Refusal("actual_producer_heartbeat_stale_or_future")
        self.preserved = {
            key: self.files.read(key) for key in ("shared_prod", "ack_history", "unknown_fences")
        }
        if any(value is None for value in self.preserved.values()):
            raise Refusal("preservation_boundary_unbound")
        self.original_unit, self.unit, self.runtime = unit, unit, runtime
        self.state = "healthy"

    @owned
    def stop_owned(self) -> None:
        if self.state not in {"healthy", "fault_running", "recovery_running", "restored"}:
            raise Refusal("stop_outside_finite_sequence")
        self._preserved()
        self._same_active()
        self.caller.begin("quiesce_dev")
        intent_usec = int(self.caller.clock() * 1_000_000)
        self.caller.run(systemd("stop"), effect=True)
        unit, runtime = self._observe(active=False)
        if int(unit["InactiveEnterTimestampMonotonic"]) < intent_usec:
            raise Unknown("stop_not_bound_to_owned_intent")
        self.unit, self.runtime = unit, runtime
        self.state = "quiescent_fault" if self.state == "fault_running" else "quiescent_healthy"

    @owned
    def reserve_fault(self) -> str:
        """3. Hold same-namespace numeric TCP loopback, bound NOT listening."""
        if self.state != "healthy" or self.socket is not None:
            raise Refusal("fault_socket_out_of_order_or_replay")
        self._same_active()
        sock = None
        try:
            sock = self.caller.socket_factory.create(
                "AF_INET",
                "SOCK_STREAM",
                original_handle=self.caller.original_handle,
                net_namespace=self.binding.net_namespace,
            )
            self.socket = sock  # Custody begins immediately after successful create.
            sock.set_inheritable(False)
            sock.bind(("127.0.0.1", 0))
            observed = sock.observe()
            address, port = sock.getsockname()
            expected = (
                "AF_INET",
                "SOCK_STREAM",
                self.binding.net_namespace,
                "BOUND_NOT_LISTENING",
                False,
                0,
                0,
                address,
                port,
                self.caller.original_handle,
            )
            if (
                observed != expected
                or address != "127.0.0.1"
                or type(port) is not int
                or not 1 <= port <= 65_535
            ):
                raise Unknown("held_numeric_socket_namespace_custody_unconfirmed")
            self.socket_state = observed
            return "http://127.0.0.1:" + str(port)
        except BaseException:
            self.caller.unknown("socket_creation_bind_or_observation_unknown")
            if sock is not None:
                self.caller.close("fault_socket", sock.close)
            raise

    @owned
    def swap_base_url(self, *, restore: bool = False) -> None:
        """2. Only PROBE_BASE_URL changes; exact original bytes/metadata restore."""
        assert self.original_config is not None and self.current_config is not None
        expected_state = "quiescent_fault" if restore else "quiescent_healthy"
        if (
            self.state != expected_state
            or self.socket is None
            or self.socket.observe() != self.socket_state
        ):
            raise Unknown("swap_requires_quiescence_and_same_held_socket")
        self._preserved()
        self._observe(active=False)
        old = parse_config(self.original_config.data)
        if restore:
            data = self.original_config.data
        else:
            address, port = self.socket.getsockname()
            line = "PROBE_BASE_URL=" + old["PROBE_BASE_URL"] + "\n"
            if (
                self.current_config != self.original_config
                or self.original_config.data.count(line.encode()) != 1
            ):
                raise Refusal("second_fault_or_ambiguous_base_line")
            data = self.original_config.data.replace(
                line.encode(), f"PROBE_BASE_URL=http://{address}:{port}\n".encode()
            )
            new = parse_config(data)
            if {key: value for key, value in old.items() if key != "PROBE_BASE_URL"} != {
                key: value for key, value in new.items() if key != "PROBE_BASE_URL"
            }:
                raise Refusal("fault_changes_more_than_base_url")
        before_incident = self.files.read("incident")
        if restore and (
            before_incident is None
            or before_incident.data != self.transitions.incident_bytes
            or self.transitions.completed_repeats < 2
        ):
            raise Unknown("restore_before_required_normal_suppressions")
        if not restore and before_incident is not None:
            raise Unknown("incident_appeared_before_fault")
        self.current_config = self.files.atomic_config(
            self.current_config, data, restore=self.original_config if restore else None
        )
        if self.files.read("incident") != before_incident:
            raise Unknown("incident_advanced_during_quiescent_config_swap")
        self.state = "restored_quiescent" if restore else "fault_quiescent"
        if restore:
            self.caller.close("fault_socket", self.socket.close)
            self.caller.check()  # Uncertain close cannot become a recovery start.
            self.socket = None

    @owned
    def start_owned(self) -> None:
        if (
            self.state not in {"fault_quiescent", "restored_quiescent"}
            or self.state in self.start_intents
        ):
            raise Refusal("start_outside_finite_sequence_or_replay")
        self._preserved()
        _, stopped_runtime = self._observe(active=False)
        start_cursor = stopped_runtime.journal_cursor
        if (
            not start_cursor
            or len(start_cursor) > 4096
            or any(ord(char) < 33 or ord(char) > 126 for char in start_cursor)
        ):
            raise Unknown("pre_start_journal_boundary_unbound")
        saved_incident = self.files.read("incident")
        phase = self.state
        self.start_intents.add(phase)  # Retained even if result/transport is lost.
        intent_usec = int(self.caller.clock() * 1_000_000)
        self.caller.begin("start_dev_" + phase)
        self.caller.run(systemd("start"), effect=True)
        unit, runtime = self._observe(active=True)
        if int(unit["ExecMainStartTimestampMonotonic"]) < intent_usec:
            raise Unknown("new_start_not_bound_to_original_intent")
        # The normal child may already have advanced the incident by this read.
        # Its transition must still be proven by the normal stream below.
        self.unit, self.runtime = unit, runtime
        assert self.current_config is not None
        self.peer = Peer(
            runtime,
            self.current_config.content_sha256,
            int(unit["ExecMainStartTimestampMonotonic"]),
        )
        # The boundary precedes start. Taking the latest cursor AFTER the effect
        # would silently skip a fast normal child's down/recovery confirmation.
        self.transitions.cursor = start_cursor
        self.phase_incident = saved_incident
        self.state = "fault_running" if phase == "fault_quiescent" else "recovery_running"

    @owned
    def normal_transitions(self) -> None:
        """4. Parse actual fixed producer signals + independently read incident.

        One bounded selected-stream read per call; no sleeps, retries, arbitrary
        journal collector or elapsed-time completion. Caller owns normal cadence.
        """
        if self.state not in {"fault_running", "recovery_running"} or self.peer is None:
            raise Refusal("normal_observation_out_of_sequence")
        self._same_active()
        self._preserved()
        cursor = self.transitions.cursor
        if (
            not cursor
            or len(cursor) > 4096
            or any(ord(char) < 33 or ord(char) > 126 for char in cursor)
        ):
            raise Unknown("normal_stream_start_cursor_unbound")
        raw = self.caller.run(
            (
                "/usr/bin/journalctl",
                "_BOOT_ID=" + self.binding.boot_id,
                "_SYSTEMD_UNIT=" + UNIT,
                "_SYSTEMD_INVOCATION_ID=" + self.peer.runtime.invocation,
                "--after-cursor=" + cursor,
                "--no-pager",
                "--output=json",
                "--output-fields=" + JOURNAL_FIELDS,
            )
        )
        after = self.files.read("incident")
        try:
            self.transitions.consume(
                raw, self.peer, self.binding, self.phase_incident, after, self.cadence
            )
        except Unknown as error:
            if str(error) == "normal_iteration_or_delivery_failed":
                # An observed normal-source failure could otherwise reach the
                # loop's next send attempt. Requalify and quiesce ONLY this same
                # owned invocation before retaining UNKNOWN; never retry a send.
                # Lost command/transport/custody never reaches this branch.
                self.stop_owned()
            raise
        self.phase_incident = after
        self._same_active()

    @owned
    def finish_restoration(self) -> dict[str, Any]:
        if (
            self.state != "recovery_running"
            or (self.transitions.down, self.transitions.recovery) != (1, 1)
            or self.transitions.completed_repeats < 2
            or self.transitions.confirmation_pending
        ):
            raise Unknown("required_confirmed_dev_pair_or_completed_repeats_missing")
        self._same_active()
        self._preserved()
        if (
            self.files.read("incident") is not None
            or self.files.read("config") != self.current_config
            or self.original_config is None
            or self.current_config is None
        ):
            raise Unknown("restoration_or_incident_clear_unconfirmed")
        current, original = self.current_config, self.original_config
        if (current.data, current.mode, current.uid, current.gid, current.mtime_ns) != (
            original.data,
            original.mode,
            original.uid,
            original.gid,
            original.mtime_ns,
        ) or self.socket is not None:
            raise Unknown("exact_config_metadata_or_socket_restore_unconfirmed")
        self.files.cleanup()
        self.state = "restored"
        return {
            "schema": "fixed_dev_probe.observations.v1",
            "native_entry_enabled": False,
            "live_acceptance": False,
            "original_handle_sha256": self.caller.original_handle,
            "down": 1,
            "completed_later_suppressions": self.transitions.completed_repeats,
            "recovery": 1,
            "same_correlation": self.transitions.correlation,
            "config_restored": True,
            "service_restored": "active_same_effective_configuration",
            "incident_history_rewound": False,
        }


def member(name: str) -> str:
    if (
        not isinstance(name, str)
        or not name
        or name.startswith("/")
        or name.endswith("/")
        or str(PurePosixPath(name)) != name
        or any(part in {".", ".."} for part in PurePosixPath(name).parts)
    ):
        raise Refusal("archive_or_fixture_path_alias")
    return name


def exact_source(
    archive: bytes, manifest_bytes: bytes, caller: Caller
) -> tuple[dict[str, bytes], list[str]]:
    """Pinned finite source validation; no extractall or archive-selected path."""
    caller.check(len(archive) + len(manifest_bytes))
    if (
        len(archive) != ARCHIVE_BYTES
        or sha(archive) != ARCHIVE_SHA256
        or len(manifest_bytes) > 131_072
        or sha(manifest_bytes) != MANIFEST_SHA256
    ):
        raise Refusal("exact_prepared_source_digest")
    manifest = json.loads(manifest_bytes, object_pairs_hook=unique)
    if (
        manifest.get("schema") != "probe_source_archive.v1"
        or manifest.get("source_commit") != SOURCE_COMMIT
        or manifest.get("package_paths") != list(PACKAGE_PATHS)
    ):
        raise Refusal("finite_dev_source_identity")
    files, directories = manifest.get("files"), manifest.get("directories")
    if (
        not isinstance(files, dict)
        or len(files) != 60
        or not isinstance(directories, list)
        or len(set(directories)) != len(directories)
    ):
        raise Refusal("finite_dev_source_shape")
    parents = {
        str(parent)
        for name in files
        for parent in PurePosixPath(member(name)).parents
        if str(parent) != "."
    }
    if set(directories) != parents:
        raise Refusal("finite_dev_source_directory_set")
    result, seen = {}, set()
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as stream:
        for entry in stream:
            caller.check()
            name = member(entry.name)
            if name in seen:
                raise Refusal("duplicate_source_archive_member")
            seen.add(name)
            if entry.isdir() and name in parents:
                continue
            if not entry.isreg() or entry.linkname or name not in files:
                raise Refusal("source_archive_link_special_or_foreign")
            expected = files[name]
            if (
                entry.mode != 0o664
                or expected["archive_mode"] != "0o664"
                or entry.size != expected["size"]
                or not 0 <= entry.size <= 1_048_576
            ):
                raise Refusal("source_archive_member_metadata")
            with stream.extractfile(entry) as handle:
                data = handle.read(entry.size + 1)
            if len(data) != entry.size or sha(data) != expected["sha256"]:
                raise Refusal("source_archive_member_bytes")
            result[name] = data
    if (
        set(result) != set(files)
        or seen != set(files) | parents
        or sha(result[TEMPLATE]) != TEMPLATE_SHA256
    ):
        raise Refusal("source_archive_incomplete_or_template_changed")
    return result, sorted(parents, key=lambda value: (value.count("/"), value))


@dataclass(frozen=True)
class InstallationQualification:
    """Actual native observation interface; fixtures are explicitly synthetic."""

    var_lib_path: str
    var_lib_device: int
    var_lib_inode: int
    var_lib_uid: int
    var_lib_gid: int
    var_lib_mode: int
    sdk_path: str
    sdk_realpath: str
    sdk_device: int
    sdk_inode: int
    sdk_uid: int
    sdk_gid: int
    sdk_mode: int
    sdk_sha256: str
    original_template_path: str | None
    original_template_bytes: bytes | None = field(repr=False)

    def require(self, binding: Binding, original: dict[str, str]) -> None:
        if (
            self.var_lib_path != "/var/lib"
            or self.var_lib_device < 0
            or self.var_lib_inode < 1
            or (self.var_lib_uid, self.var_lib_gid) != (0, 0)
            or self.var_lib_mode & 0o022
        ):
            raise Refusal("selected_existing_var_lib_parent_unqualified")
        if (
            (self.sdk_path, self.sdk_realpath) != (binding.sdk, binding.sdk_realpath)
            or self.sdk_device < 0
            or self.sdk_inode < 1
            or (self.sdk_uid, self.sdk_gid) != (0, 0)
            or self.sdk_mode & 0o022
            or not self.sdk_mode & 0o111
            or not identifier(self.sdk_sha256, 64)
        ):
            raise Refusal("existing_normal_sdk_unqualified_no_provisioning")
        if original["LoadState"] == "loaded":
            if (
                self.original_template_path != original["FragmentPath"]
                or not self.original_template_bytes
                or sha(self.original_template_bytes) != TEMPLATE_SHA256
                or original["DropInPaths"]
            ):
                raise Refusal("foreign_or_custom_inactive_dev_unit_profile")
            finite_stop_seconds(original)


class TemporaryDevInstallation:
    """ONE absent/inactive canonical DEV envelope. No installer/shared writes.

    Actual files are confined to the same private fixture capability. The two
    fixture parents represent separately qualified native /var/lib and /run/
    systemd/system capabilities; no constructor maps them to a real host path.
    """

    def __init__(
        self, files: PrivateFiles, binding: Binding, qualification: InstallationQualification
    ):
        self.ops = files.ops
        self.files, self.caller, self.binding, self.qualification = (
            files,
            files.caller,
            binding,
            qualification,
        )
        self.owned: dict[str, FileState] = {}
        self.directories: dict[str, tuple[int, ...]] = {}
        self.created: set[str] = set()
        self.source_name: str | None = None
        self.artifact: str | None = None
        self.adapter: DevProbeAdapter | None = None
        self.state = "unprepared"

    def _nonce(self) -> str:
        return secrets.token_hex(16)

    def _source_relative(self, nonce: str) -> str:
        return "var-lib/ygg-dev-probe-" + nonce

    def _source_absolute(self, relative: str) -> str:
        return "/var/lib/" + PurePosixPath(relative).name

    def _dir(self, path: str, *, create: bool = False) -> int:
        parts = member(path).split("/")
        descriptor = self.ops.dup(self.files.fd)
        try:
            for index, part in enumerate(parts):
                relative = "/".join(parts[: index + 1])
                if create:
                    try:
                        self.ops.mkdir(part, 0o700, dir_fd=descriptor)
                        self.created.add(relative)
                    except FileExistsError:
                        if relative not in self.directories:
                            raise Unknown("temporary_directory_collision_or_adoption")
                child = self.ops.open(
                    part,
                    self.ops.O_RDONLY
                    | self.ops.O_DIRECTORY
                    | self.ops.O_NOFOLLOW
                    | self.ops.O_CLOEXEC,
                    dir_fd=descriptor,
                )
                info = self.ops.fstat(child)
                identity = (
                    info.st_dev,
                    info.st_ino,
                    info.st_uid,
                    info.st_gid,
                    stat.S_IMODE(info.st_mode),
                )
                if identity[2:] != (self.files.uid, self.files.gid, 0o700) or (
                    relative in self.directories and self.directories[relative] != identity
                ):
                    self.ops.close(child)
                    raise Unknown("temporary_directory_custody_changed")
                self.directories.setdefault(relative, identity)
                self.ops.close(descriptor)
                descriptor = child
            return descriptor
        except BaseException:
            self.caller.close("staging_directory", lambda: self.ops.close(descriptor))
            raise

    def _parent(self, name: str) -> tuple[int, str]:
        path = PurePosixPath(member(name))
        return self._dir(str(path.parent)), path.name

    def _read(self, name: str, *, mode: int) -> FileState:
        self.caller.check()
        parent, leaf = self._parent(name)
        descriptor = None
        try:
            descriptor = self.ops.open(
                leaf,
                self.ops.O_RDONLY | self.ops.O_NOFOLLOW | self.ops.O_NONBLOCK | self.ops.O_CLOEXEC,
                dir_fd=parent,
            )
            before = self.ops.fstat(descriptor)
            if (
                not stat.S_ISREG(before.st_mode)
                or (before.st_uid, before.st_gid, stat.S_IMODE(before.st_mode), before.st_nlink)
                != (self.files.uid, self.files.gid, mode, 1)
                or before.st_size > 1_048_576
            ):
                raise Unknown("staged_file_owner_alias_mode_or_bound")
            chunks = bytearray()
            while True:
                self.caller.check()
                block = self.ops.read(descriptor, min(65_536, 1_048_577 - len(chunks)))
                if not block:
                    break
                self.caller.check(len(block))
                chunks.extend(block)
                if len(chunks) > 1_048_576:
                    raise Unknown("staged_file_read_bound")
            after = self.ops.fstat(descriptor)
            slot = self.ops.stat(leaf, dir_fd=parent, follow_symlinks=False)
            signature = lambda value: (
                value.st_dev,
                value.st_ino,
                value.st_mode,
                value.st_uid,
                value.st_gid,
                value.st_nlink,
                value.st_size,
                value.st_mtime_ns,
                value.st_ctime_ns,
            )
            if (
                signature(before) != signature(after)
                or signature(before) != signature(slot)
                or len(chunks) != before.st_size
            ):
                raise Unknown("staged_file_changed_during_read")
            return FileState(
                bytes(chunks),
                before.st_dev,
                before.st_ino,
                mode,
                before.st_uid,
                before.st_gid,
                before.st_nlink,
                before.st_mtime_ns,
                before.st_ctime_ns,
            )
        finally:
            if descriptor is not None:
                self.caller.close("staging_file", lambda: self.ops.close(descriptor))
            self.caller.close("staging_parent", lambda: self.ops.close(parent))

    def _write(self, name: str, data: bytes, *, mode: int) -> None:
        self.caller.check(len(data))
        parent, leaf = self._parent(name)
        descriptor = None
        try:
            descriptor = self.ops.open(
                leaf,
                self.ops.O_WRONLY
                | self.ops.O_CREAT
                | self.ops.O_EXCL
                | self.ops.O_NOFOLLOW
                | self.ops.O_CLOEXEC,
                mode,
                dir_fd=parent,
            )
            self.ops.fchmod(descriptor, mode)
            created = self.ops.fstat(descriptor)
            self.owned[name] = FileState(
                b"",
                created.st_dev,
                created.st_ino,
                mode,
                created.st_uid,
                created.st_gid,
                created.st_nlink,
                created.st_mtime_ns,
                created.st_ctime_ns,
            )
            pending = memoryview(data)
            while pending:
                self.caller.check()
                count = self.ops.write(descriptor, pending[:65_536])
                if count <= 0:
                    raise Unknown("staged_write_unconfirmed")
                pending = pending[count:]
            self.ops.fsync(descriptor)
            self.ops.fsync(parent)
        finally:
            if descriptor is not None:
                self.caller.close("staged_write", lambda: self.ops.close(descriptor))
            self.caller.close("staged_write_parent", lambda: self.ops.close(parent))
        self.owned[name] = self._read(name, mode=mode)

    def _originals(self) -> None:
        if self.files._read(self.files.names["config"], absent=True) != self.original_config:
            raise Unknown("original_dev_config_changed")
        for key, expected in self.preserved.items():
            if not preserves(self.files.read(key), expected):
                raise Unknown("shared_prod_or_history_changed_during_staging")

    @fs_guard
    def prepare(self, archive: bytes, manifest: bytes, healthy_config: bytes) -> Binding:
        if self.state != "unprepared":
            raise Refusal("temporary_dev_installation_replay")
        self.binding.require(self.caller)
        source, directories = exact_source(archive, manifest, self.caller)
        self.original = parse_unit(read_dev_unit(self.caller.run), allow_absent=True)
        if self.original["ActiveState"] != "inactive":
            raise Refusal("use_existing_active_dev_adapter_instead")
        self.qualification.require(self.binding, self.original)
        observed = self.caller.read_runtime(
            self.binding, health=True, allow_uninstalled_source=True
        )
        if (
            (
                observed.target,
                observed.transport,
                observed.standing_reference,
                observed.role,
                observed.route,
                observed.boot_id,
            )
            != (
                self.binding.target,
                self.binding.transport,
                self.binding.standing_reference,
                self.binding.expected_role,
                self.binding.producer_route,
                self.binding.boot_id,
            )
            or observed.active_owner_references != (self.binding.standing_reference,)
            or observed.pending_controller_operations
            or observed.members
            or observed.creator is not None
            or observed.child is not None
            or observed.incident_writer_pids
        ):
            raise Unknown("absent_or_inactive_ownership_cgroup_or_route_unqualified")
        if self.files.read("incident") is not None:
            raise Refusal("preexisting_incident_before_temporary_launch")
        values = parse_config(healthy_config)
        expected = {
            "PROBE_ENVIRONMENT": "dev",
            "PROBE_ALERT_CHANNEL": "discord",
            "PROBE_BASE_URL": self.binding.api_base,
            "WORKER_HEARTBEAT_PATH": self.binding.heartbeat,
            "PROBE_STATE_FILE": self.binding.state_file,
        }
        if any(values.get(key) != value for key, value in expected.items()):
            raise Refusal("temporary_dev_config_not_qualified_normal_route")
        observed.independent_health(self.binding)
        heartbeat = self.files.read("heartbeat")
        try:
            payload = json.loads(heartbeat.data, object_pairs_hook=unique)
            timestamp = float(payload.get("ts", payload.get("timestamp")))
            stale = float(values["WORKER_HEARTBEAT_STALE_SECONDS"])
        except (ValueError, TypeError, AttributeError):
            raise Refusal("independent_preinstallation_heartbeat_malformed") from None
        if (
            not math.isfinite(stale)
            or stale <= 0
            or not math.isfinite(timestamp)
            or timestamp <= 0
            or not 0 <= observed.epoch_seconds - timestamp <= stale
        ):
            raise Refusal("independent_preinstallation_heartbeat_unhealthy")
        self.original_config = self.files._read(self.files.names["config"], absent=True)
        self.preserved = {
            key: self.files.read(key) for key in ("shared_prod", "ack_history", "unknown_fences")
        }
        # Parents must already exist and be positively owned; never invent or
        # create a native /var/lib or systemd directory from repository defaults.
        for path in ("var-lib", "volatile-systemd"):
            descriptor = self._dir(path)
            self.caller.close("qualified_fixture_parent", lambda: self.ops.close(descriptor))
        parent = self._dir("volatile-systemd")
        try:
            self.original_volatile_entries = set(self.ops.listdir(parent))
        finally:
            self.caller.close("volatile_parent", lambda: self.ops.close(parent))
        nonce = self._nonce()
        self.state = "staging_intent"
        self.source_name = self._source_relative(nonce)
        # Exclusive directory creation refuses a random-name collision.
        descriptor = self._dir(self.source_name, create=True)
        self.caller.close("new_source_parent", lambda: self.ops.close(descriptor))
        for path in directories:
            descriptor = self._dir(self.source_name + "/" + path, create=True)
            self.caller.close("source_directory", lambda: self.ops.close(descriptor))
        for name, data in source.items():
            self._write(self.source_name + "/" + name, data, mode=0o664)
        self.config_relative = self.source_name + "/dev-private.env"
        self._write(self.config_relative, healthy_config, mode=0o600)
        native_source = self._source_absolute(self.source_name)
        self.selected = replace(
            self.binding, package=native_source, config=native_source + "/dev-private.env"
        )
        overrides = (
            "[Service]\nWorkingDirectory="
            + native_source
            + "\nEnvironment=PYTHONPATH="
            + native_source
            + "\nEnvironmentFile=\nEnvironmentFile="
            + self.selected.config
            + "\nStateDirectory=\nStateDirectory="
            + normal_state_directory(self.selected)
            # systemd's empty directory-list assignment also resets its mode.
            + "\nStateDirectoryMode=0700"
            + "\nExecStart=\nExecStart="
            + self.binding.sdk
            + " "
            + native_source
            + "/"
            + LAUNCHER
            + " --channel dev\n"
        ).encode()
        self.absent = self.original["LoadState"] == "not-found"
        if self.absent:
            self.artifact = "volatile-systemd/" + UNIT
            artifact_bytes = source[TEMPLATE] + b"\n" + overrides
        else:
            directory = "volatile-systemd/" + UNIT + ".d"
            descriptor = self._dir(directory, create=True)
            self.caller.close("owned_dropin_parent", lambda: self.ops.close(descriptor))
            self.artifact = directory + "/99-dev-probe-" + nonce + ".conf"
            artifact_bytes = overrides
        temporary = str(PurePosixPath(self.artifact).parent / (".publish-" + nonce))
        self._write(temporary, artifact_bytes, mode=0o600)
        parent, leaf = self._parent(self.artifact)
        try:
            self.ops.link(
                PurePosixPath(temporary).name,
                leaf,
                src_dir_fd=parent,
                dst_dir_fd=parent,
                follow_symlinks=False,
            )
            self.ops.unlink(PurePosixPath(temporary).name, dir_fd=parent)
            del self.owned[temporary]
            self.ops.fsync(parent)
        finally:
            self.caller.close("publication_parent", lambda: self.ops.close(parent))
        self.owned[self.artifact] = self._read(self.artifact, mode=0o600)
        descriptor = self._dir(self.source_name)
        try:
            self.files.attach_staged_config(descriptor)
        finally:
            self.caller.close("staged_config_binding", lambda: self.ops.close(descriptor))
        self.caller.run(systemd("reload_for_temporary_dev"), effect=True)
        loaded = parse_unit(read_dev_unit(self.caller.run))
        if (
            loaded["ActiveState"] != "inactive"
            or loaded["WorkingDirectory"] != native_source
            or loaded["EnvironmentFiles"].replace(" ", "")
            != self.selected.config + "(ignore_errors=no)"
        ):
            raise Unknown("temporary_fixed_dev_unit_reload_unconfirmed")
        normal_unit(loaded, self.selected)
        self.installed_unit = loaded
        self.healthy_config, self.state = healthy_config, "prepared"
        return self.selected

    @fs_guard
    def activate(
        self, *, before_start: Callable[[DevProbeAdapter], None] | None = None
    ) -> DevProbeAdapter:
        if self.state != "prepared":
            raise Refusal("temporary_activation_replay_or_out_of_order")
        if self.caller.native_scope is not None and before_start is None:
            raise Refusal("native_first_start_requires_independent_containment")
        self._originals()
        for name, expected in self.owned.items():
            if self._read(name, mode=expected.mode) != expected:
                raise Unknown("source_or_unit_drift_before_first_launch")
        config = self.files.read("config")
        assert config is not None
        unit = parse_unit(read_dev_unit(self.caller.run))
        if unit["ActiveState"] != "inactive" or unit_profile(unit) != unit_profile(
            self.installed_unit
        ):
            raise Unknown("temporary_unit_profile_changed_before_start")
        normal_unit(unit, self.selected)
        runtime = self.caller.read_runtime(self.selected, health=True)
        runtime.qualify(
            self.selected, self.caller, unit, config.content_sha256, active=False, health=True
        )
        values = parse_config(config.data)
        heartbeat = self.files.read("heartbeat")
        try:
            payload = json.loads(heartbeat.data, object_pairs_hook=unique)
            timestamp = float(payload.get("ts", payload.get("timestamp")))
            stale = float(values["WORKER_HEARTBEAT_STALE_SECONDS"])
        except (ValueError, TypeError, AttributeError):
            raise Refusal("independent_prelaunch_heartbeat_malformed") from None
        if (
            not math.isfinite(stale)
            or stale <= 0
            or not math.isfinite(timestamp)
            or timestamp <= 0
            or not 0 <= runtime.epoch_seconds - timestamp <= stale
            or self.files.read("incident") is not None
        ):
            raise Refusal("independent_prelaunch_heartbeat_or_incident_unhealthy")
        adapter = DevProbeAdapter(self.selected, self.caller, self.files)
        # Qualification is read-only. The native callback arms the independent
        # guardian before the first managed-unit start, including a lost ACK.
        adapter.original_config = adapter.current_config = config
        adapter.original_unit = adapter.unit = unit
        adapter.runtime = runtime
        adapter.cadence = int(values["PROBE_INTERVAL_SECONDS"])
        if before_start is not None:
            before_start(adapter)
        self.state = "start_intent"  # Never clear/retry a lost start.
        intent_usec = int(self.caller.clock() * 1_000_000)
        self.caller.run(systemd("start"), effect=True)
        adapter.admit()
        if int(adapter.unit["ExecMainStartTimestampMonotonic"]) < intent_usec:
            raise Unknown("temporary_first_start_not_owned_by_original_intent")
        self.adapter, self.state = adapter, "active"
        return adapter

    def _tree(self, path: str) -> set[str]:
        descriptor = self._dir(path)
        result = set()
        try:
            for leaf in self.ops.listdir(descriptor):
                relative = path + "/" + member(leaf)
                meta = self.ops.stat(leaf, dir_fd=descriptor, follow_symlinks=False)
                if stat.S_ISDIR(meta.st_mode) and relative in self.created:
                    result |= self._tree(relative)
                elif stat.S_ISREG(meta.st_mode):
                    result.add(relative)
                else:
                    raise Unknown("unowned_cache_directory_alias_or_special")
            return result
        finally:
            self.caller.close("cleanup_directory", lambda: self.ops.close(descriptor))

    @fs_guard
    def restore_and_cleanup(self, *, already_stopped: bool = False) -> dict[str, Any]:
        if (
            self.state != "active"
            or self.adapter is None
            or (self.adapter.state != "restored" and not already_stopped)
        ):
            raise Refusal("cleanup_requires_completed_dev_sequence_and_restoration")
        if not already_stopped:
            self.adapter.stop_owned()
        self.adapter._observe(active=False)
        self._originals()
        config = self.files.read("config")
        if (
            config is None
            or config.data != self.healthy_config
            or self.files.read("incident") is not None
        ):
            raise Unknown("healthy_config_or_recovery_not_restored_before_cleanup")
        self.owned[self.config_relative] = config
        actual_source = self._tree(self.source_name)
        expected_source = {name for name in self.owned if name.startswith(self.source_name + "/")}
        if actual_source != expected_source:
            raise Unknown("unqualified_sdk_cache_or_foreign_source_artifact")
        # Validate EVERY owned file and directory before the first unlink.
        for name, expected in self.owned.items():
            if self._read(name, mode=expected.mode) != expected:
                raise Unknown("positive_cleanup_file_custody_changed")
        parent = self._dir("volatile-systemd")
        try:
            added = UNIT if self.absent else UNIT + ".d"
            if set(self.ops.listdir(parent)) != self.original_volatile_entries | {added}:
                raise Unknown("foreign_volatile_systemd_entry")
        finally:
            self.caller.close("cleanup_volatile_parent", lambda: self.ops.close(parent))
        self.files.detach_staged_config()
        for name in sorted(self.owned, key=lambda value: value.count("/"), reverse=True):
            parent, leaf = self._parent(name)
            try:
                if self._read(name, mode=self.owned[name].mode) != self.owned[name]:
                    raise Unknown("cleanup_slot_changed_after_guard")
                self.ops.unlink(leaf, dir_fd=parent)
                self.ops.fsync(parent)
            finally:
                self.caller.close("owned_unlink_parent", lambda: self.ops.close(parent))
        self.owned.clear()
        for directory in sorted(self.created, key=lambda value: value.count("/"), reverse=True):
            descriptor = self._dir(directory)
            try:
                if self.ops.listdir(descriptor):
                    raise Unknown("owned_source_directory_not_empty")
            finally:
                self.caller.close("empty_owned_directory", lambda: self.ops.close(descriptor))
            parent, leaf = self._parent(directory)
            try:
                self.ops.rmdir(leaf, dir_fd=parent)
                self.ops.fsync(parent)
            finally:
                self.caller.close("owned_rmdir_parent", lambda: self.ops.close(parent))
        self.caller.run(systemd("reload_for_temporary_dev"), effect=True)
        restored = parse_unit(read_dev_unit(self.caller.run), allow_absent=True)
        if (
            unit_profile(restored) != unit_profile(self.original)
            or restored["ActiveState"] != "inactive"
            or restored["MainPID"] != "0"
        ):
            raise Unknown("original_dev_unit_enablement_or_absence_not_restored")
        self._originals()
        self.state = "restored"
        return {
            "native_entry_enabled": False,
            "live_acceptance": False,
            "original_service": "absent" if self.absent else "inactive",
            "original_effective_unit_and_enablement_restored": True,
            "owned_temporary_artifacts_removed": True,
            "shared_package_or_template_overwritten": False,
        }


HTTP_CHILD_CODE = (
    "import sys; sys.path.insert(0, sys.argv[1]); import prod_probe; prod_probe._http_get_child()"
)


@dataclass(frozen=True)
class FrozenNativeScope:
    """One frozen DEV request. Every deployment/authority value is required."""

    binding: Binding
    handle: Handle
    namespace: str
    machine_id: str
    claim_holder: str
    lease_id: str
    program_sha256: str
    manifest: bytes = field(repr=False)
    controller_source: bytes = field(repr=False)
    probe_source: bytes = field(repr=False)
    controller_directory: str
    credential_source: str
    credential_resolved_source: str
    non_prod_project_id: str
    worker_python: str
    worker_uid: int
    protected_files: tuple[tuple[str, str, str, int], ...]
    local_fence_references: tuple[tuple[str, str], ...]
    candidate_references: tuple[tuple[str, str, str, str | None, str, str], ...]

    def __post_init__(self) -> None:
        if (
            not identifier(self.handle.operation)
            or not identifier(self.namespace)
            or not identifier(self.machine_id)
            or not identifier(self.program_sha256, 64)
        ):
            raise Refusal("native_operation_identity_unbound")
        if (
            (self.binding.target, self.binding.transport)
            != (self.handle.target, self.handle.transport)
            or self.binding.expected_role != "Product Runtime DEV"
            or not self.claim_holder
            or not self.lease_id
        ):
            raise Refusal("native_request_claim_or_selection_unbound")
        if (
            sha(self.manifest) != MANIFEST_SHA256
            or not absolute(self.controller_directory)
            or not (
                absolute(self.worker_python)
                or re.fullmatch(r"python(?:3(?:\.[0-9]+)?)?", self.worker_python)
            )
            or type(self.worker_uid) is not int
            or self.worker_uid < 0
        ):
            raise Refusal("native_source_owner_or_worker_profile_unbound")
        document = json.loads(self.manifest, object_pairs_hook=unique)
        controller = document["files"]["app/ops/host_secret_controller.py"]["sha256"]
        if sha(self.controller_source) != controller:
            raise Refusal("native_controller_parser_source_unqualified")
        if sha(self.probe_source) != SOURCE_HASHES[PROBE]:
            raise Refusal("native_probe_reader_source_unqualified")
        prefix = "/var/lib/yggdrasil/bws-tokens/dev/"
        if (
            not self.credential_source.startswith(prefix)
            or not self.credential_resolved_source.startswith(prefix)
            or not absolute(self.credential_source)
            or not absolute(self.credential_resolved_source)
        ):
            raise Refusal("credential_metadata_path_outside_declared_dev_owner")
        if len(self.protected_files) > 128 or any(
            row[0] != "shared_dev_host" for row in self.protected_files
        ):
            raise Refusal("native_preservation_inventory_unbound")
        if {row[0] for row in self.local_fence_references} != {
            "original5b47",
            "successor329",
        } or any(not identifier(row[1], 64) for row in self.local_fence_references):
            raise Refusal("immutable_local_unknown_references_unbound")
        if {row[0] for row in self.candidate_references} != {"api", "worker"} or len(
            self.candidate_references
        ) != 2:
            raise Refusal("observed_dev_candidate_pair_unbound")
        if len({row[2] for row in self.candidate_references}) != 1:
            raise Refusal("api_worker_candidate_image_mismatch")
        for role, container, image, revision, pid, start in self.candidate_references:
            if (
                not identifier(container, 64)
                or re.fullmatch(r"sha256:[0-9a-f]{64}", image) is None
                or revision is not None
                and re.fullmatch(r"[0-9a-f]{40}", revision) is None
                or not pid.isdigit()
                or not identifier(start, 64)
            ):
                raise Refusal("observed_candidate_identity_shape")
        for label, path, digest, mode in self.protected_files:
            if (
                not absolute(path)
                or not identifier(digest, 64)
                or mode & 0o002
                or "/credentials/" in path
                or "/bws-tokens/" in path
            ):
                raise Refusal("native_preservation_path_or_digest_unqualified")

    @property
    def root(self) -> str:
        return "/var/lib/ygg-dev-probe-" + self.namespace

    @property
    def request_bytes(self) -> bytes:
        value = {
            "schema": "fixed_dev_probe.request.v1",
            "issue": 6505,
            "parent_issue": 4076,
            "binding": asdict(self.binding),
            "operation": self.handle.operation,
            "original_handle_sha256": self.handle.fingerprint,
            "claim_holder": self.claim_holder,
            "lease_id": self.lease_id,
            "namespace": self.namespace,
            "program_sha256": self.program_sha256,
            "machine_id": self.machine_id,
            "local_fence_references": self.local_fence_references,
            "candidate_references": self.candidate_references,
        }
        return json.dumps(value, sort_keys=True, separators=(",", ":")).encode() + b"\n"


@dataclass(frozen=True)
class LinuxDependencies:
    os: Any
    subprocess: Any
    selectors: Any
    signal: Any
    time: Any
    socket: Any
    fcntl: Any
    grp: Any
    pwd: Any
    cache: Any
    process: Any

    @classmethod
    def standard_library(cls) -> "LinuxDependencies":
        # Explicit assembly code, never a module default or an enabled entry.
        import subprocess, selectors, signal, time, socket, fcntl, grp, pwd
        import importlib.util

        return cls(
            os, subprocess, selectors, signal, time, socket, fcntl, grp, pwd, importlib.util, sys
        )


class NativeClock:
    def __init__(self, scope: FrozenNativeScope, api: Any):
        self.scope, self.api = scope, api

    def __call__(self) -> float:
        return self.api.monotonic()

    def epoch(self) -> float:
        return self.api.time()


class NativeCommand:
    """Concrete accepted process/pipe/selector runner, with a finite DEV argv set."""

    def __init__(
        self, scope: FrozenNativeScope, dependencies: LinuxDependencies, public_custody_source: str
    ):
        self.scope, self.dependencies = scope, dependencies
        self.public_source = public_custody_source
        selected = {}
        for node in ast.parse(public_custody_source).body:
            if isinstance(node, (ast.ClassDef, ast.FunctionDef)) and node.name in {
                "OperationFailure",
                "_bounded_process",
                "_safe_command",
            }:
                selected[node.name] = (
                    "\n".join(public_custody_source.splitlines()[node.lineno - 1 : node.end_lineno])
                    + "\n"
                )
        if (
            set(selected) != {"OperationFailure", "_bounded_process", "_safe_command"}
            or sha(selected["_bounded_process"].encode()) != CUSTODY_SHA256
        ):
            raise Refusal("native_custody_source_not_accepted_43d")
        namespace = {
            name: getattr(dependencies, name)
            for name in ("os", "subprocess", "selectors", "signal", "time")
        }
        exec(
            "from __future__ import annotations\n"
            + "\n".join(
                selected[key] for key in ("OperationFailure", "_bounded_process", "_safe_command")
            ),
            namespace,
        )
        self.safe, self.bounded = namespace["_safe_command"], namespace["_bounded_process"]

    def _allowed(self, argv: tuple[str, ...], effect: bool) -> None:
        if argv == dev_credential_property() and not effect:
            return
        if argv in {
            systemd("show"),
            systemd("start"),
            systemd("stop"),
            systemd("reload_for_temporary_dev"),
        }:
            if effect != (argv != systemd("show")):
                raise Refusal("native_command_effect_classification")
            return
        if argv[0:1] == ("/usr/bin/journalctl",) and not effect and len(argv) <= 12:
            allowed = {
                "--no-pager",
                "--output=json",
                "--lines=1",
                "--lines=64",
                "--output-fields=" + JOURNAL_FIELDS,
                "--output-fields=__CURSOR,_BOOT_ID,__MONOTONIC_TIMESTAMP",
            }
            for arg in argv[1:]:
                if (
                    arg in allowed
                    or arg == "_BOOT_ID=" + self.scope.binding.boot_id
                    or arg == "_SYSTEMD_UNIT=" + UNIT
                ):
                    continue
                if arg.startswith("_SYSTEMD_INVOCATION_ID=") and identifier(arg.split("=", 1)[1]):
                    continue
                if (
                    arg.startswith("--after-cursor=")
                    and len(arg) <= 4112
                    and all(33 <= ord(char) <= 126 for char in arg)
                ):
                    continue
                raise Refusal("native_journal_argument_outside_fixed_reader")
            return
        if argv in {supervisor_command(self.scope), watchdog_command(self.scope)} and effect:
            return
        if (
            argv == watchdog_show(self.scope)
            and not effect
            or argv == watchdog_stop(self.scope)
            and effect
            or argv == supervisor_show(self.scope.handle.operation)
            and not effect
            or argv == supervisor_stop(self.scope)
            and effect
        ):
            return
        raise Refusal("native_command_outside_fixed_dev_invocation")

    def run(
        self,
        argv: tuple[str, ...],
        *,
        timeout: float,
        limit: int,
        effect: bool,
        original_handle: str,
    ) -> CommandResult:
        if (
            original_handle != self.scope.handle.fingerprint
            or not 0 < timeout <= self.scope.binding.window_end - self.dependencies.time.monotonic()
            or not 0 < limit <= 1_048_576
        ):
            raise Unknown("native_command_original_handle_window_or_limit")
        self._allowed(argv, effect)
        try:
            output = self.safe(list(argv), timeout=timeout, limit=limit, effect=effect)
        except BaseException:
            raise Unknown("native_command_transport_exit_reap_or_close_unknown") from None
        # Returned only after accepted code's wait + all stream/selector closes.
        return CommandResult(output.encode("utf-8"), original_handle, 0, "reaped", "closed")


class LinuxIO:
    """Bounded actual Linux syscalls; fixed read set, zero credential contents."""

    def __init__(self, scope: FrozenNativeScope, dependencies: LinuxDependencies, caller: Caller):
        self.scope, self.dependencies, self.caller = scope, dependencies, caller
        self.os = dependencies.os
        self.pids = {scope.binding.worker_pid}
        self.pids.update(row[4] for row in scope.candidate_references)
        self.cgroup_paths = set()
        self.manifest = json.loads(scope.manifest, object_pairs_hook=unique)["files"]
        self.verified_files = {}

    def _check(self, count: int = 0) -> None:
        self.caller.check(count)

    def _read_allowed(self, path: str) -> None:
        binding, scope = self.scope.binding, self.scope
        exact = {
            binding.config,
            binding.state_file,
            binding.heartbeat,
            binding.sdk_realpath,
            "/etc/machine-id",
            "/proc/sys/kernel/random/boot_id",
            scope.root + "/request.json",
            scope.root + "/program.py",
            scope.root + "/result.json",
            scope.controller_directory + "/operations.jsonl",
            "/etc/yggdrasil/bws-deploy/dev.json",
        }
        exact.update(
            scope.root + "/" + name
            for name in (
                "watchdog.json",
                "watchdog-ready.json",
                "watchdog-result.json",
                "native-input.json",
                "supervisor-start.json",
            )
        )
        exact |= {row[1] for row in scope.protected_files}
        exact.add(scope.root + "/source/dev-private.env")
        if path in exact or any(
            path.startswith(prefix + "/") and path[len(prefix) + 1 :] in self.manifest
            for prefix in (binding.package, scope.root + "/source")
        ):
            return
        if re.fullmatch(r"/proc/([1-9][0-9]*)/(stat|status|cgroup|cmdline|environ)", path):
            if path.split("/")[2] in self.pids:
                return
        if path in {"/sys/fs/cgroup" + group + "/cgroup.procs" for group in self.cgroup_paths}:
            return
        raise Refusal("native_read_outside_declared_dev_metadata_or_source")

    def directory(self, path: str, *, private: bool = False, shared_heartbeat: bool = False) -> int:
        self._check()
        if not absolute(path):
            raise Refusal("native_directory_alias")
        descriptor = self.os.open("/", self.os.O_RDONLY | self.os.O_DIRECTORY | self.os.O_CLOEXEC)
        try:
            parts = PurePosixPath(path).parts[1:]
            for index, part in enumerate(parts):
                child = self.os.open(
                    part,
                    self.os.O_RDONLY | self.os.O_DIRECTORY | self.os.O_NOFOLLOW | self.os.O_CLOEXEC,
                    dir_fd=descriptor,
                )
                self.caller.close("native_directory_parent", lambda: self.os.close(descriptor))
                descriptor = child
                info = self.os.fstat(descriptor)
                allowed_shared = (
                    shared_heartbeat
                    and index == len(parts) - 1
                    and stat.S_IMODE(info.st_mode) & 0o1000
                    and info.st_uid in {0, self.scope.worker_uid}
                )
                if not allowed_shared and (
                    (info.st_uid, info.st_gid) != (0, 0) or stat.S_IMODE(info.st_mode) & 0o022
                ):
                    raise Refusal("native_directory_owner_or_write_domain")
                if {"system.posix_acl_access", "system.posix_acl_default"}.intersection(
                    self.os.listxattr(descriptor)
                ):
                    raise Refusal("native_directory_acl_writer")
                self._check()
            if private and stat.S_IMODE(self.os.fstat(descriptor).st_mode) != 0o700:
                raise Refusal("native_dev_scope_not_private_0700")
            return descriptor
        except BaseException:
            self.caller.close("native_directory", lambda: self.os.close(descriptor))
            raise

    def metadata(
        self, path: str, *, mode: int | None = None, uid: int = 0, secret: bool = False
    ) -> Any:
        self._check()
        if not absolute(path):
            raise Refusal("native_metadata_alias")
        parent = self.directory(str(PurePosixPath(path).parent))
        try:
            info = self.os.stat(PurePosixPath(path).name, dir_fd=parent, follow_symlinks=False)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != uid
                or info.st_nlink != 1
                or mode is not None
                and stat.S_IMODE(info.st_mode) != mode
            ):
                raise Refusal("native_file_metadata_owner_type_mode_or_alias")
            return info
        finally:
            self.caller.close("native_metadata_parent", lambda: self.os.close(parent))

    def verified(self, path: str, expected: str, *, mode: int) -> FileState:
        if path not in self.verified_files:
            value = self.read(path, limit=1_048_576, mode=mode)
            if value.content_sha256 != expected:
                raise Unknown("verified_native_source_or_preservation_digest")
            self.verified_files[path] = value
        value = self.verified_files[path]
        meta = self.metadata(path, mode=mode)
        if (
            meta.st_dev,
            meta.st_ino,
            meta.st_uid,
            meta.st_gid,
            meta.st_nlink,
            meta.st_size,
            meta.st_mtime_ns,
            meta.st_ctime_ns,
        ) != (
            value.device,
            value.inode,
            value.uid,
            value.gid,
            value.links,
            len(value.data),
            value.mtime_ns,
            value.ctime_ns,
        ):
            raise Unknown("verified_native_file_identity_or_bytes_changed")
        return value

    def read(
        self,
        path: str,
        *,
        limit: int = 65_536,
        mode: int | None = None,
        uid: int = 0,
        proc: bool = False,
    ) -> FileState:
        self._read_allowed(path)
        self._check()
        descriptor = None
        parent = None
        try:
            if proc:
                descriptor = self.os.open(
                    path,
                    self.os.O_RDONLY | self.os.O_NOFOLLOW | self.os.O_NONBLOCK | self.os.O_CLOEXEC,
                )
            else:
                parent = self.directory(str(PurePosixPath(path).parent))
                descriptor = self.os.open(
                    PurePosixPath(path).name,
                    self.os.O_RDONLY | self.os.O_NOFOLLOW | self.os.O_NONBLOCK | self.os.O_CLOEXEC,
                    dir_fd=parent,
                )
            before = self.os.fstat(descriptor)
            if (
                not stat.S_ISREG(before.st_mode)
                or not proc
                and (
                    before.st_uid != uid
                    or before.st_nlink != 1
                    or before.st_size > limit
                    or mode is not None
                    and stat.S_IMODE(before.st_mode) != mode
                )
            ):
                raise Refusal("native_file_read_metadata_or_bound")
            chunks = bytearray()
            while True:
                self._check()
                block = self.os.read(descriptor, min(16_384, limit + 1 - len(chunks)))
                if not block:
                    break
                self._check(len(block))
                chunks.extend(block)
                if len(chunks) > limit:
                    raise Unknown("native_read_allocation_bound")
            after = self.os.fstat(descriptor)
            signature = lambda meta: (
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
            if signature(before) != signature(after) or not proc and len(chunks) != before.st_size:
                raise Unknown("native_file_changed_during_read")
            if parent is not None and signature(before) != signature(
                self.os.stat(PurePosixPath(path).name, dir_fd=parent, follow_symlinks=False)
            ):
                raise Unknown("native_file_slot_changed_during_read")
            return FileState(
                bytes(chunks),
                before.st_dev,
                before.st_ino,
                stat.S_IMODE(before.st_mode),
                before.st_uid,
                before.st_gid,
                before.st_nlink,
                before.st_mtime_ns,
                before.st_ctime_ns,
            )
        finally:
            if descriptor is not None:
                self.caller.close("native_file", lambda: self.os.close(descriptor))
            if parent is not None:
                self.caller.close("native_file_parent", lambda: self.os.close(parent))

    def link(self, path: str) -> str:
        if not re.fullmatch(r"/proc/(self|[1-9][0-9]*)/(exe|cwd|ns/net|fd/2|root)", path):
            raise Refusal("native_link_not_selected_proc_metadata")
        if path.split("/")[2] != "self" and path.split("/")[2] not in self.pids:
            raise Refusal("native_proc_pid_not_selected")
        self._check()
        value = self.os.readlink(path)
        if not isinstance(value, str) or len(value) > 4096 or "\0" in value:
            raise Unknown("native_proc_link_bound")
        return value

    def environment(self, pid: str) -> tuple[tuple[str, ...], dict[str, str]]:
        # The host-local scanner keeps ONLY names and these nonsecret metadata
        # values. Credential files are never opened; foreign values are discarded
        # without decoding, copyback, logging or inclusion in any observation.
        raw = self.read("/proc/" + pid + "/environ", limit=131_072, proc=True).data
        selected = {
            "HOST_SECRET_BOOTSTRAP_CHANNEL",
            "HOST_SECRET_BOOTSTRAP_CONSUMER",
            "HOST_SECRET_RUNTIME_ENV_FILE",
            "PKM_ENVIRONMENT",
            "WORKER_HEARTBEAT_PATH",
            "YGG_DEV_OPERATION",
        }
        names, values = [], {}
        for item in raw.split(b"\0"):
            if not item:
                continue
            key, separator, value = item.partition(b"=")
            if not separator:
                raise Refusal("native_proc_environment_shape")
            name = key.decode("ascii")
            if name in names:
                raise Refusal("native_proc_environment_duplicate")
            names.append(name)
            if name in selected:
                values[name] = value.decode("utf-8")
        return tuple(sorted(names)), values

    def process(self, pid: str, boot: str) -> tuple[Process, dict[str, str]]:
        if not pid.isascii() or not pid.isdigit() or int(pid) < 1:
            raise Refusal("native_proc_pid")
        self.pids.add(pid)
        base = "/proc/" + pid

        def identity() -> tuple[str, str]:
            raw = self.read(base + "/stat", limit=4096, proc=True).data.decode("ascii")
            prefix, separator, tail = raw.rpartition(") ")
            fields = tail.split()
            if (
                not separator
                or not prefix.startswith(pid + " (")
                or len(fields) < 20
                or not fields[1].isdigit()
                or not fields[19].isdigit()
            ):
                raise Unknown("native_proc_stat_shape")
            return fields[1], fields[19]

        parent, ticks = identity()
        groups = (
            self.read(base + "/cgroup", limit=4096, proc=True).data.decode("ascii").splitlines()
        )
        if len(groups) != 1 or not groups[0].startswith("0::/"):
            raise Refusal("native_requires_cgroup_v2")
        raw_argv = self.read(base + "/cmdline", proc=True).data
        if not raw_argv.endswith(b"\0"):
            raise Unknown("native_proc_argv_incomplete")
        argv = tuple(item.decode("utf-8") for item in raw_argv[:-1].split(b"\0"))
        names, values = self.environment(pid)
        status = self.read(base + "/status", limit=16384, proc=True).data.decode("ascii")
        namespace_pids = [
            line.split()[1:] for line in status.splitlines() if line.startswith("NSpid:")
        ]
        if (
            len(namespace_pids) != 1
            or not namespace_pids[0]
            or any(not value.isdigit() for value in namespace_pids[0])
        ):
            raise Refusal("worker_namespace_pid_metadata_unavailable")
        values["__NATIVE_NAMESPACE_PID"] = namespace_pids[0][-1]
        uid = self.os.stat(base, follow_symlinks=False).st_uid
        target = self.link(base + "/fd/2")
        fd = self.os.stat(base + "/fd/2")
        process = Process(
            pid,
            parent,
            sha((boot + ":" + pid + ":" + ticks).encode()),
            uid,
            groups[0][3:],
            self.link(base + "/exe"),
            self.link(base + "/cwd"),
            argv,
            fd.st_dev,
            fd.st_ino,
            target,
            self.link(base + "/ns/net"),
            names,
        )
        if identity() != (parent, ticks):
            raise Unknown("native_pid_reused_during_observation")
        return process, values

    def guard_process_identity(self, pid: str, boot: str) -> tuple[str, str] | None:
        """Minimal exit-tolerant observation; never admission evidence."""
        if not pid.isascii() or not pid.isdigit() or int(pid) < 1:
            raise Refusal("guard_proc_pid")
        self.pids.add(pid)
        try:
            raw = self.read("/proc/" + pid + "/stat", limit=4096, proc=True).data.decode("ascii")
        except (FileNotFoundError, ProcessLookupError):
            return None
        prefix, separator, tail = raw.rpartition(") ")
        fields = tail.split()
        if (
            not separator
            or not prefix.startswith(pid + " (")
            or len(fields) < 20
            or not fields[19].isdigit()
        ):
            return None
        return sha((boot + ":" + pid + ":" + fields[19]).encode()), fields[0]

    def guard_creator(self, pid: str, binding: Binding) -> dict[str, Any] | None:
        """Only a coherent finalized normal launcher can veto slot custody.

        PID/start identity survives execve. Read the complete launcher evidence
        twice; a mixed image or a generic pre-exec process is not foreign proof.
        Manager state and pre-exec executable names do not identify completion.
        Emergency cancellation needs neither journal FDs nor a live netns.
        The stricter process() reader remains the admission boundary.
        """
        expected_argv = (binding.sdk, binding.package + "/" + LAUNCHER, "--channel", "dev")

        def snapshot() -> dict[str, Any] | None:
            before = self.guard_process_identity(pid, binding.boot_id)
            if before is None or before[1] in {"Z", "X", "x"}:
                return None
            base = "/proc/" + pid
            raw = self.read(base + "/cmdline", proc=True).data
            if not raw or not raw.endswith(b"\0"):
                return None
            argv = tuple(item.decode("utf-8") for item in raw[:-1].split(b"\0"))
            executable = self.link(base + "/exe")
            if argv != expected_argv or executable != binding.sdk_realpath:
                return None
            names, environment = self.environment(pid)
            if not names:
                return None
            groups = (
                self.read(base + "/cgroup", limit=4096, proc=True).data.decode("ascii").splitlines()
            )
            if len(groups) != 1 or not groups[0].startswith("0::/"):
                return None
            value = {
                "identity": before[0],
                "argv": argv,
                "environment": environment,
                "cgroup": groups[0][3:],
                "uid": self.os.stat(base, follow_symlinks=False).st_uid,
                "exe": executable,
                "cwd": self.link(base + "/cwd"),
            }
            after = self.guard_process_identity(pid, binding.boot_id)
            if after is None or after[0] != before[0] or after[1] in {"Z", "X", "x"}:
                return None
            return value

        try:
            first = snapshot()
            return first if first is not None and snapshot() == first else None
        except (FileNotFoundError, ProcessLookupError):
            return None

    def cgroup(self, path: str) -> tuple[str, ...]:
        suffixes = (
            UNIT,
            "yggdrasil-dev-probe-" + self.scope.handle.operation + ".service",
            watchdog_unit(self.scope),
        )
        if (
            not path.startswith("/system.slice/")
            or not any(path.endswith("/" + suffix) for suffix in suffixes)
            or ".." in PurePosixPath(path).parts
            or any(ord(char) < 32 for char in path)
        ):
            raise Refusal("native_cgroup_outside_fixed_dev_unit")
        self.cgroup_paths.add(path)
        try:
            raw = (
                self.read("/sys/fs/cgroup" + path + "/cgroup.procs", limit=16_384, proc=True)
                .data.decode("ascii")
                .splitlines()
            )
        except FileNotFoundError:
            return ()
        if (
            len(raw) > 64
            or len(set(raw)) != len(raw)
            or any(not pid.isascii() or not pid.isdigit() or int(pid) < 1 for pid in raw)
        ):
            raise Unknown("native_dev_cgroup_members_bound")
        self.pids.update(raw)
        return tuple(sorted(raw, key=int))

    def heartbeat(self) -> FileState:
        path = self.scope.binding.heartbeat
        parent = self.directory(str(PurePosixPath(path).parent), shared_heartbeat=True)
        descriptor = None
        try:
            descriptor = self.os.open(
                PurePosixPath(path).name,
                self.os.O_RDONLY | self.os.O_NOFOLLOW | self.os.O_NONBLOCK | self.os.O_CLOEXEC,
                dir_fd=parent,
            )
            before = self.os.fstat(descriptor)
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_nlink != 1
                or before.st_size > 65536
                or stat.S_IMODE(before.st_mode) not in {0o600, 0o644, 0o666}
                or str(before.st_dev) + ":" + str(before.st_ino)
                != self.scope.binding.heartbeat_backing
            ):
                raise Refusal("native_heartbeat_file_or_backing_not_selected_producer")
            chunks = bytearray()
            while True:
                self._check()
                block = self.os.read(descriptor, min(16384, 65537 - len(chunks)))
                if not block:
                    break
                self._check(len(block))
                chunks.extend(block)
                if len(chunks) > 65536:
                    raise Unknown("native_heartbeat_allocation_bound")
            after = self.os.fstat(descriptor)
            if (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
                before.st_ctime_ns,
            ) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                raise StartupPending("normal_heartbeat_writer_advanced_during_read")
            return FileState(
                bytes(chunks),
                before.st_dev,
                before.st_ino,
                stat.S_IMODE(before.st_mode),
                before.st_uid,
                before.st_gid,
                before.st_nlink,
                before.st_mtime_ns,
                before.st_ctime_ns,
            )
        finally:
            if descriptor is not None:
                self.caller.close("native_heartbeat", lambda: self.os.close(descriptor))
            self.caller.close("native_heartbeat_parent", lambda: self.os.close(parent))


@dataclass(frozen=True)
class HistorySnapshot:
    file: FileState | None


@dataclass(frozen=True)
class PreservationSnapshot:
    files: tuple[tuple[str, FileState], ...]


@dataclass(frozen=True)
class LocalFenceReferences:
    references: tuple[tuple[str, str], ...]


def preserves(current: Any, original: Any) -> bool:
    if isinstance(original, HistorySnapshot):
        if not isinstance(current, HistorySnapshot):
            return False
        a, b = current.file, original.file
        if b is None:
            return True  # A validated normal controller may create its history.
        if a is None:
            return False
        return (a.device, a.inode, a.mode, a.uid, a.gid, a.links) == (
            b.device,
            b.inode,
            b.mode,
            b.uid,
            b.gid,
            b.links,
        ) and a.data.startswith(b.data)
    return current == original


def controller_pending(raw: bytes, public_source: bytes) -> dict[str, Any] | None:
    """Use the unchanged public value-free journal grammar on a bounded copy."""
    selected = []
    namespace = {"json": json, "re": re, "UUID": UUID, "HostSecretAdmissionError": Refusal}
    source = public_source.decode("utf-8")
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and all(
            isinstance(item, ast.Name) and item.id.startswith("_") for item in node.targets
        ):
            try:
                value = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                continue
            for name in node.targets:
                namespace[name.id] = value
        if isinstance(node, ast.ClassDef) and node.name == "HostSecretController":
            method = next(
                item
                for item in node.body
                if isinstance(item, ast.FunctionDef) and item.name == "_pending"
            )
            selected.append(ast.unparse(method).removeprefix("@staticmethod\n"))
    if len(raw) > 1_048_576 or len(raw.splitlines()) > 8192 or len(selected) != 1:
        raise Unknown("existing_controller_journal_bound_or_parser")
    namespace["os"] = SimpleNamespace(
        SEEK_SET=0,
        lseek=lambda *args: None,
        dup=lambda descriptor: descriptor,
        fdopen=lambda *args, **kwargs: io.StringIO(raw.decode("utf-8")),
    )
    exec("from __future__ import annotations\n" + selected[0], namespace)
    try:
        return namespace["_pending"](0)
    except Exception:
        raise Unknown("existing_controller_journal_unqualified") from None


class NativeHttp:
    def __init__(self, scope: FrozenNativeScope, command: NativeCommand, caller: Caller):
        self.scope, self.command, self.caller = scope, command, caller
        source = scope.probe_source.decode("utf-8")
        node = next(
            item
            for item in ast.parse(source).body
            if isinstance(item, ast.FunctionDef) and item.name == "_read_http_json"
        )
        function = ast.get_source_segment(source, node)
        self.reader_code = (
            "from __future__ import annotations\nimport json,sys\n_HTTP_MAX_BYTES=1048576\n"
            + function
            + "\nr=json.loads(sys.stdin.buffer.read(16385));s,b=_read_http_json(r['url'],r['timeout']);"
            "sys.stdout.write(json.dumps({'status':s,'body':b},separators=(',',':')))\n"
        )

    def get(self, url: str, binding: Binding | None = None) -> tuple[int, bytes]:
        binding = self.scope.binding if binding is None else binding
        if url not in {
            binding.api_base + "/readyz",
            binding.api_base + "/api/health",
            binding.api_base + "/api/health?model_access_sampling=cache",
        }:
            raise Refusal("independent_http_outside_fixed_dev_health")
        remaining = self.caller.check()
        if remaining <= 2.1:
            raise Unknown("independent_http_custody_budget")
        request = json.dumps({"url": url, "timeout": min(10.0, remaining - 2.1)}).encode()
        argv = [binding.sdk, "-I", "-c", self.reader_code]
        try:
            result = self.command.bounded(
                argv,
                timeout=min(12.0, remaining - 2.1),
                limit=1_048_576,
                environment={},
                input_bytes=request,
            )
            self.caller.check(len(result.stdout) + len(result.stderr))
            value = json.loads(result.stdout, object_pairs_hook=unique)
            if (
                result.returncode != 0
                or result.stderr
                or set(value) != {"status", "body"}
                or type(value["status"]) is not int
                or not isinstance(value["body"], dict)
            ):
                raise ValueError()
            return value["status"], json.dumps(value["body"], separators=(",", ":")).encode()
        except BaseException:
            self.caller.unknown("independent_http_exit_reap_close_or_response_unknown")
            raise Unknown("independent_http_unqualified") from None


class StartupPending(Exception):
    pass


class LinuxRuntimeReader:
    """Compute Runtime from fixed Linux observations, never supplied proof flags."""

    def __init__(self, scope: FrozenNativeScope, command: NativeCommand, clock: NativeClock):
        self.scope, self.command, self.clock = scope, command, clock
        self.caller = self.io = self.http = None
        self.qualified_packages = set()

    def attach(self, caller: Caller, native_io: LinuxIO, http: NativeHttp) -> None:
        if (
            caller.handle != self.scope.handle
            or native_io.scope != self.scope
            or http.scope != self.scope
        ):
            raise Refusal("native_runtime_assembly_scope_mismatch")
        self.caller, self.io, self.http = caller, native_io, http

    def _selection(self, binding: Binding) -> tuple[str, tuple[str, ...]]:
        scope, io_port = self.scope, self.io
        request = io_port.read(scope.root + "/request.json", mode=0o600).data
        if request != scope.request_bytes:
            raise Unknown("frozen_request_or_original_owner_changed")
        machine = io_port.read("/etc/machine-id", limit=128).data.decode("ascii").strip()
        boot = (
            io_port.read("/proc/sys/kernel/random/boot_id", limit=128, proc=True)
            .data.decode("ascii")
            .strip()
            .replace("-", "")
        )
        if (
            machine != scope.machine_id
            or boot != binding.boot_id
            or io_port.link("/proc/self/ns/net") != binding.net_namespace
        ):
            raise Unknown("actual_host_boot_or_helper_namespace_changed")
        for role, container, image, revision, pid, expected_start in scope.candidate_references:
            raw = io_port.read("/proc/" + pid + "/stat", limit=4096, proc=True).data.decode()
            fields = raw[raw.rfind(") ") + 2 :].split()
            if (
                len(fields) < 20
                or sha((boot + ":" + pid + ":" + fields[19]).encode()) != expected_start
            ):
                raise Unknown("frozen_dev_candidate_process_changed")
        if (
            binding.target,
            binding.transport,
            binding.standing_reference,
            binding.expected_role,
            binding.producer_route,
        ) != (
            scope.binding.target,
            scope.binding.transport,
            scope.binding.standing_reference,
            scope.binding.expected_role,
            scope.binding.producer_route,
        ):
            raise Refusal("runtime_selection_outside_frozen_dev_request")
        binding.require(self.caller)
        # The keeper standing is frozen by the claimed caller, bound to the
        # actually observed machine and DEV producer/config, not guessed here.
        return boot, (binding.standing_reference,)

    def _sources(self, binding: Binding) -> tuple[tuple[str, str], ...]:
        manifest = self.io.manifest
        result = []
        for relative, expected in manifest.items():
            data = self.io.verified(
                binding.package + "/" + relative, expected["sha256"], mode=0o664
            ).data
            if len(data) != expected["size"] or sha(data) != expected["sha256"]:
                raise Unknown("actual_dev_full_source_manifest_mismatch")
            if relative in SOURCE_HASHES:
                result.append((relative, sha(data)))
        return tuple(result)

    def _controller(self, *, active: bool) -> tuple[str, ...]:
        path = self.scope.controller_directory
        try:
            directory = self.io.directory(path, private=True)
        except FileNotFoundError:
            if active:
                raise Unknown("normal_controller_missing_after_child_materialization") from None
            return ()
        lock = None
        try:
            self.io.metadata(path + "/operation.lock", mode=0o600)
            self.io.metadata(path + "/operations.jsonl", mode=0o600)
            lock = self.io.os.open(
                "operation.lock",
                self.io.os.O_RDONLY | self.io.os.O_NOFOLLOW | self.io.os.O_CLOEXEC,
                dir_fd=directory,
            )
            api = self.command.dependencies.fcntl
            api.flock(lock, api.LOCK_SH | api.LOCK_NB)
            snapshot = self.io.read(path + "/operations.jsonl", limit=1_048_576, mode=0o600)
            pending = controller_pending(snapshot.data, self.scope.controller_source)
            return () if pending is None else (str(pending["operation_id"]),)
        except BlockingIOError:
            raise StartupPending("normal_controller_admission_in_progress") from None
        finally:
            if lock is not None:
                self.caller.close("controller_read_lock", lambda: self.io.os.close(lock))
            self.caller.close("controller_read_directory", lambda: self.io.os.close(directory))

    def _credential_metadata(
        self, unit: dict[str, str], creator: Process | None, child_values: dict[str, str]
    ) -> None:
        scope = self.scope
        credential = unit["LoadCredentialEncrypted"].split(":", 1)
        if unit["LoadState"] != "not-found" and (
            credential != ["bws-machine-account-token", scope.credential_source]
            or scope.controller_directory not in unit["ReadWritePaths"].split()
        ):
            raise Refusal("normal_credential_or_controller_owner_path_changed")
        raw_parent = self.io.directory(
            str(PurePosixPath(scope.credential_source).parent), private=True
        )
        try:
            metadata = self.io.os.stat(
                PurePosixPath(scope.credential_source).name,
                dir_fd=raw_parent,
                follow_symlinks=False,
            )
            if stat.S_ISLNK(metadata.st_mode):
                target = self.io.os.readlink(
                    PurePosixPath(scope.credential_source).name, dir_fd=raw_parent
                )
                resolved = (
                    str(PurePosixPath(scope.credential_source).parent / target)
                    if not target.startswith("/")
                    else target
                )
                if not absolute(resolved) or resolved != scope.credential_resolved_source:
                    raise Refusal("declared_dev_credential_generation_changed")
            elif scope.credential_source != scope.credential_resolved_source:
                raise Refusal("credential_generation_alias_unqualified")
        finally:
            self.caller.close("credential_metadata_parent", lambda: self.io.os.close(raw_parent))
        self.io.metadata(scope.credential_resolved_source, mode=0o600, secret=True)
        # Only stat these values: never open the encrypted token, credential or
        # short-lived webhook file. No BWS read/provisioning is performed.
        if creator is not None:
            self.io.directory_close("/run/yggdrasil-host-probe-dev", private=True)
            runtime_file = child_values.get("HOST_SECRET_RUNTIME_ENV_FILE", "")
            if str(PurePosixPath(runtime_file).parent) != "/run/yggdrasil-host-probe-dev":
                raise Refusal("normal_private_consumer_runtime_file_path")
            self.io.metadata(runtime_file, mode=0o600, secret=True)
            if (
                child_values.get("HOST_SECRET_BOOTSTRAP_CHANNEL") != "dev"
                or child_values.get("HOST_SECRET_BOOTSTRAP_CONSUMER") != "heimdal-external-alerts"
            ):
                raise Refusal("observed_fixed_consumer_channel_or_name")
        try:
            self.io.directory_close(
                str(PurePosixPath(scope.binding.state_file).parent), private=True
            )
        except FileNotFoundError:
            if creator is not None:
                raise Unknown("normal_state_directory_missing_after_start") from None

    def _worker(self, binding: Binding, boot: str) -> tuple[Process, str]:
        worker, values = self.io.process(binding.worker_pid, boot)
        if (
            worker.start_identity != binding.worker_start
            or worker.uid != self.scope.worker_uid
            or worker.argv != (self.scope.worker_python, "-m", "app.workers.outbox_worker")
        ):
            raise Refusal("unsupported_or_changed_normal_outbox_worker_process")
        worker_path = values.get("WORKER_HEARTBEAT_PATH", "")
        if values.get("PKM_ENVIRONMENT") != "dev" or not absolute(worker_path):
            raise Refusal("worker_requires_explicit_nonsecret_effective_heartbeat_path")
        # The producer may be native or containerized. This uses its actual
        # /proc root and selected path, with no Docker/volume-name inference.
        producer = self.io.os.stat("/proc/" + worker.pid + "/root" + worker_path)
        host = self.io.heartbeat()
        if (producer.st_dev, producer.st_ino) != (host.device, host.inode):
            raise Refusal("worker_to_host_heartbeat_translation_mismatch")
        payload = json.loads(host.data, object_pairs_hook=unique)
        if (
            str(payload.get("pid")) != values.get("__NATIVE_NAMESPACE_PID")
            or payload.get("status") != "running"
        ):
            raise Refusal("heartbeat_not_current_normal_worker_producer")
        again, _ = self.io.process(worker.pid, boot)
        if again.start_identity != worker.start_identity:
            raise Unknown("worker_replaced_during_translation_read")
        return worker, str(host.device) + ":" + str(host.inode)

    def _journal(
        self,
        binding: Binding,
        unit: dict[str, str],
        creator: Process | None,
        child: Process | None,
    ) -> tuple[str, str]:
        boundary = self.caller.run(
            (
                "/usr/bin/journalctl",
                "_BOOT_ID=" + binding.boot_id,
                "--lines=1",
                "--no-pager",
                "--output=json",
                "--output-fields=__CURSOR,_BOOT_ID,__MONOTONIC_TIMESTAMP",
            )
        )
        rows = [json.loads(line, object_pairs_hook=unique) for line in boundary.splitlines()]
        if (
            len(rows) != 1
            or rows[0].get("_BOOT_ID") != binding.boot_id
            or not isinstance(rows[0].get("__CURSOR"), str)
            or not rows[0]["__CURSOR"]
        ):
            raise Unknown("same_boot_pre_effect_journal_cursor_unavailable")
        cursor = rows[0]["__CURSOR"]
        if creator is None:
            return "", cursor
        raw = self.caller.run(
            (
                "/usr/bin/journalctl",
                "_BOOT_ID=" + binding.boot_id,
                "_SYSTEMD_UNIT=" + UNIT,
                "_SYSTEMD_INVOCATION_ID=" + unit["InvocationID"],
                "--lines=64",
                "--no-pager",
                "--output=json",
                "--output-fields=" + JOURNAL_FIELDS,
            )
        )
        streams = set()
        for line in raw.splitlines():
            row = json.loads(line, object_pairs_hook=unique)
            match = LOG_FORMAT.fullmatch(row.get("MESSAGE", ""))
            if match is None:
                continue
            if (
                row.get("_BOOT_ID"),
                row.get("_SYSTEMD_UNIT"),
                row.get("_SYSTEMD_INVOCATION_ID"),
                row.get("_SYSTEMD_CGROUP"),
                row.get("_TRANSPORT"),
            ) != (
                binding.boot_id,
                UNIT,
                unit["InvocationID"],
                creator.cgroup,
                "stdout",
            ) or not (
                normal_stream_pid(row.get("_PID"), creator, child)
                and identifier(row.get("_STREAM_ID", ""))
            ):
                raise Unknown("actual_creator_child_journal_stream_unqualified")
            if match[1] == "ERROR":
                raise Unknown("normal_source_error_during_runtime_qualification")
            streams.add(row["_STREAM_ID"])
        if not streams:
            raise StartupPending("normal_fixed_child_stream_not_observed_yet")
        if len(streams) != 1:
            raise Unknown("ambiguous_inherited_normal_stream")
        return next(iter(streams)), cursor

    def read(
        self,
        binding: Binding,
        *,
        original_handle: str,
        timeout: float,
        require_health: bool = False,
        allow_uninstalled_source: bool = False,
    ) -> Runtime:
        if self.caller is None or original_handle != self.scope.handle.fingerprint:
            raise Refusal("native_runtime_not_assembled_to_original_handle")
        boot, owner = self._selection(binding)
        first = parse_unit(read_dev_unit(self.caller.run), allow_absent=True)
        if allow_uninstalled_source and (first["ActiveState"] == "active" or not require_health):
            raise Refusal("preinstallation_health_requires_inactive_probe")
        preinstallation = first["ActiveState"] != "active" and (
            allow_uninstalled_source
            or not require_health
            and binding.package not in self.qualified_packages
        )
        sources = () if preinstallation else self._sources(binding)
        if sources:
            self.qualified_packages.add(binding.package)
        deadline = min(self.clock() + min(timeout, 30.0), self.caller.deadline)
        initial = None
        while True:
            self.caller.check()
            unit = parse_unit(read_dev_unit(self.caller.run), allow_absent=True)
            active = unit["ActiveState"] == "active"
            identity = tuple(
                unit[key] for key in ("InvocationID", "MainPID", "ExecMainStartTimestampMonotonic")
            )
            if initial is not None and active and identity != initial:
                raise Unknown("normal_startup_incarnation_changed")
            initial = identity if active else initial
            cgroup = unit["ControlGroup"] or getattr(self, "last_cgroup", "")
            members = self.io.cgroup(cgroup) if cgroup else ()
            if active:
                self.last_cgroup = cgroup
            creator = child = None
            child_values, readers = {}, []
            try:
                if active:
                    normal_unit(unit, binding)
                    creator, _ = self.io.process(unit["MainPID"], boot)
                    if (
                        creator.argv
                        != (binding.sdk, binding.package + "/" + LAUNCHER, "--channel", "dev")
                        or creator.executable != binding.sdk_realpath
                        or creator.uid != 0
                    ):
                        raise Refusal("startup_is_not_fixed_normal_dev_launcher")
                    others = []
                    for pid in members:
                        if pid == creator.pid:
                            continue
                        try:
                            process, values = self.io.process(pid, boot)
                        except (FileNotFoundError, ProcessLookupError):
                            raise StartupPending("serial_reader_exited_during_sample") from None
                        if process.argv == (binding.sdk, binding.package + "/" + PROBE, "--loop"):
                            if child is not None:
                                raise Refusal("multiple_normal_probe_children")
                            child, child_values = process, values
                        else:
                            others.append(process)
                    if child is None:
                        # Type=simple may precede materialization. Nothing here
                        # accepts unknown descendants; no effects proceed until
                        # a complete later sample qualifies the normal child.
                        raise StartupPending("fixed_bws_child_not_materialized_yet")
                    expected_http = (
                        binding.sdk,
                        "-I",
                        "-c",
                        HTTP_CHILD_CODE,
                        binding.package + "/ops/host-setup/mac-mini",
                    )
                    for process in others:
                        if (
                            process.argv != expected_http
                            or process.parent != child.pid
                            or process.environment_keys
                            or process.uid != 0
                            or process.executable != binding.sdk_realpath
                        ):
                            raise Refusal("unqualified_descendant_of_normal_dev_probe")
                        readers.append(process)
                    members = tuple(
                        sorted(
                            (creator.pid, child.pid, *(process.pid for process in readers)), key=int
                        )
                    )
                elif members:
                    raise Unknown("inactive_dev_cgroup_not_reaped")
                pending = self._controller(active=active)
                self._credential_metadata(unit, creator, child_values)
                worker, backing = self._worker(binding, boot)
                if backing != binding.heartbeat_backing:
                    raise Refusal("actual_heartbeat_backing_changed")
                stream, cursor = self._journal(binding, unit, creator, child)
                break
            except StartupPending:
                if self.clock() >= deadline:
                    raise Unknown("bounded_normal_startup_or_metadata_not_ready") from None
                wait = min(0.2, deadline - self.clock(), self.caller.check())
                if wait <= 0:
                    raise Unknown("normal_startup_deadline")
                self.clock.api.sleep(wait)
        config = None if preinstallation else self.io.read(binding.config, mode=0o600)
        deploy = json.loads(
            self.io.read("/etc/yggdrasil/bws-deploy/dev.json", mode=0o600).data,
            object_pairs_hook=unique,
        )
        if deploy.get("project_id") != self.scope.non_prod_project_id:
            raise Refusal("normal_dev_non_prod_reader_project_mismatch")
        ready_status, health_status, health = 0, 0, b"{}"
        if require_health:
            ready_status, _ = self.http.get(binding.api_base + "/readyz", binding)
            health_status, health = self.http.get(binding.api_base + "/api/health", binding)
        again = parse_unit(read_dev_unit(self.caller.run), allow_absent=True)
        if unit_profile(again) != unit_profile(unit) or any(
            again[key] != unit[key] for key in VOLATILE
        ):
            raise Unknown("dev_unit_changed_during_full_runtime_read")
        return Runtime(
            original_handle,
            binding.target,
            binding.transport,
            binding.standing_reference,
            binding.expected_role,
            binding.producer_route,
            boot,
            self.clock(),
            self.clock.epoch(),
            unit["InvocationID"],
            unit["ControlGroup"],
            members,
            creator,
            child,
            stream,
            cursor,
            sources,
            MANIFEST_SHA256 if sources else "",
            "heimdal-external-alerts",
            "non-prod",
            "shared/discord.webhook",
            config.content_sha256 if config else "",
            (child.pid,) if child else (),
            owner,
            pending,
            binding.api_base + "/readyz",
            ready_status,
            binding.api_base + "/api/health",
            health_status,
            health,
            worker.pid,
            worker.start_identity,
            binding.heartbeat,
            backing,
            tuple(readers),
        )


def _directory_close(self: LinuxIO, path: str, *, private: bool = False) -> None:
    descriptor = self.directory(path, private=private)
    self.caller.close("native_qualified_directory", lambda: self.os.close(descriptor))


LinuxIO.directory_close = _directory_close


class NativeSocketFactory(SocketFactory):
    def __init__(
        self, scope: FrozenNativeScope, dependencies: LinuxDependencies, native_io: LinuxIO
    ):
        self.scope, self.api, self.descriptor_api = scope, dependencies.socket, dependencies.os
        self.namespace_reader = lambda: native_io.link("/proc/self/ns/net")


class NativeFiles(PrivateFiles):
    """Separate native factory; the fixture constructor's guard is unchanged."""

    @classmethod
    def open(cls, scope: FrozenNativeScope, caller: Caller, native_io: LinuxIO) -> "NativeFiles":
        value = cls.__new__(cls)
        value.scope, value.io, value.ops, value.caller = scope, native_io, native_io.os, caller
        value.fd = native_io.directory(scope.root, private=True)
        info = value.ops.fstat(value.fd)
        value.uid = value.gid = 0
        value.root_identity = (
            info.st_dev,
            info.st_ino,
            info.st_uid,
            info.st_gid,
            stat.S_IMODE(info.st_mode),
        )
        value.config_fd, value.temporary = None, {}
        value.names = {
            "config": scope.binding.config,
            "incident": scope.binding.state_file,
            "heartbeat": scope.binding.heartbeat,
            "shared_prod": "shared_prod",
            "ack_history": "ack_history",
            "unknown_fences": "unknown_fences",
        }
        if native_io.read(scope.root + "/request.json", mode=0o600).data != scope.request_bytes:
            value.close()
            raise Unknown("native_private_scope_owner_request_mismatch")
        if (
            native_io.read(scope.root + "/program.py", limit=1_048_576, mode=0o600).content_sha256
            != scope.program_sha256
        ):
            value.close()
            raise Unknown("native_assembled_program_bytes_changed")
        return value

    def _read(
        self, name: str, *, absent: bool = False, parent: int | None = None
    ) -> FileState | None:
        if parent is not None or not name.startswith("/"):
            return super()._read(name, absent=absent, parent=parent)
        try:
            return self.io.read(name, mode=0o600)
        except FileNotFoundError:
            if absent:
                return None
            raise

    @fs_guard
    def read(self, key: str) -> Any:
        self.caller.check()
        if key == "ack_history":
            try:
                snapshot = self.io.read(
                    self.scope.controller_directory + "/operations.jsonl",
                    limit=1_048_576,
                    mode=0o600,
                )
            except FileNotFoundError:
                return HistorySnapshot(None)
            if controller_pending(snapshot.data, self.scope.controller_source) is not None:
                raise Unknown("normal_controller_has_active_incident_operation")
            return HistorySnapshot(snapshot)
        if key == "unknown_fences":
            # These references belong to Root's separate PROD/worktree route.
            # No DEV-host fake fence file or cross-host observer is introduced.
            return LocalFenceReferences(self.scope.local_fence_references)
        if key == "shared_prod":  # Legacy fixture key; native meaning is shared DEV-host bytes.
            result = []
            for label, path, expected, mode in self.scope.protected_files:
                if label != "shared_dev_host":
                    continue
                snapshot = self.io.verified(path, expected, mode=mode)
                result.append((path, snapshot))
            return PreservationSnapshot(tuple(result))
        if key == "heartbeat":
            return self.io.heartbeat()
        return super().read(key)

    @fs_guard
    def atomic_config(
        self, expected: FileState, data: bytes, *, restore: FileState | None = None
    ) -> FileState:
        if self.config_fd is None:
            selected = self.names["config"]
            if selected != "/etc/yggdrasil/host-probe/dev.env" and not selected.startswith(
                self.scope.root + "/source/"
            ):
                raise Refusal("native_config_mutation_outside_fixed_dev_scope")
            parent = self.io.directory(
                str(PurePosixPath(selected).parent),
                private=selected.startswith(self.scope.root + "/"),
            )
            old_name, self.names["config"] = self.names["config"], PurePosixPath(selected).name
            self.config_fd = parent
            info = self.ops.fstat(parent)
            self.config_directory_identity = (
                info.st_dev,
                info.st_ino,
                info.st_uid,
                info.st_gid,
                stat.S_IMODE(info.st_mode),
            )
            # Base method's private staged filename is fixed; canonical existing
            # DEV is handled explicitly with the same retained descriptor.
            try:
                return self._atomic_existing(expected, data, restore)
            finally:
                self.names["config"] = old_name
                self.config_fd = None
                self.caller.close("native_dev_config_parent", lambda: self.ops.close(parent))
        return super().atomic_config(expected, data, restore=restore)

    def _atomic_existing(
        self, expected: FileState, data: bytes, restore: FileState | None
    ) -> FileState:
        # Canonical config slot; stage/replace remains bounded to this opened FD.
        name, parent = self.names["config"], self.config_fd
        if self._read(name, parent=parent) != expected:
            raise Unknown("native_existing_config_custody_changed")
        temporary = ".owned-dev-config-" + secrets.token_hex(16)
        descriptor = None
        try:
            descriptor = self.ops.open(
                temporary,
                self.ops.O_WRONLY
                | self.ops.O_CREAT
                | self.ops.O_EXCL
                | self.ops.O_NOFOLLOW
                | self.ops.O_CLOEXEC,
                0o600,
                dir_fd=parent,
            )
            self.ops.fchmod(descriptor, 0o600)
            pending = memoryview(data)
            while pending:
                self.caller.check()
                count = self.ops.write(descriptor, pending[:16_384])
                if count <= 0:
                    raise Unknown("native_config_write_unknown")
                pending = pending[count:]
            if restore is not None:
                self.ops.utime(descriptor, ns=(restore.mtime_ns, restore.mtime_ns))
            self.ops.fsync(descriptor)
        finally:
            if descriptor is not None:
                self.caller.close("native_config_write", lambda: self.ops.close(descriptor))
        staged = self._read(temporary, parent=parent)
        self.temporary[temporary] = staged
        if self._read(name, parent=parent) != expected:
            raise Unknown("native_config_slot_changed_before_replace")
        self.ops.replace(temporary, name, src_dir_fd=parent, dst_dir_fd=parent)
        self.temporary.pop(temporary)
        self.ops.fsync(parent)
        current = self._read(name, parent=parent)
        if (
            current.data != data
            or (current.uid, current.gid, current.mode)
            != (expected.uid, expected.gid, expected.mode)
            or restore is not None
            and current.mtime_ns != restore.mtime_ns
        ):
            raise Unknown("native_config_restore_readback_unknown")
        return current


class NativeInstallation(TemporaryDevInstallation):
    def __init__(
        self, files: NativeFiles, binding: Binding, qualification: InstallationQualification
    ):
        super().__init__(files, binding, qualification)
        self.scope, self.io = files.scope, files.io

    def _probe_directory(self, path: str) -> tuple[int, int, int, int, int] | None:
        try:
            descriptor = self.io.directory(path, private=True)
        except FileNotFoundError:
            return None
        try:
            info = self.ops.fstat(descriptor)
            if self.ops.listdir(descriptor):
                raise Refusal("temporary_probe_directory_not_empty")
            return (info.st_dev, info.st_ino, info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode))
        finally:
            self.caller.close("temporary_probe_directory", lambda: self.ops.close(descriptor))

    def _temporary_directories_unchanged(self, *, operation_state_removed: bool = False) -> None:
        try:
            if self._probe_directory("/run/yggdrasil-host-probe-dev") is not None:
                raise Unknown("foreign_or_unreaped_temporary_runtime_directory")
            if (
                self._probe_directory("/var/lib/yggdrasil-host-probe-dev")
                != self.canonical_state_identity
            ):
                raise Unknown("canonical_probe_state_directory_changed")
            expected_state = None if operation_state_removed else self.probe_state_identity
            if self._probe_directory(self.probe_state_directory) != expected_state:
                raise Unknown("temporary_probe_state_directory_owner_changed")
        except Refusal:
            raise Unknown("temporary_probe_directory_custody_changed") from None

    @fs_guard
    def prepare(self, archive: bytes, manifest: bytes, healthy_config: bytes) -> Binding:
        self.probe_state_directory = str(PurePosixPath(self.binding.state_file).parent)
        if (
            self.probe_state_directory != self.scope.root + "/probe-state"
            or self.binding.state_file != self.probe_state_directory + "/alert-state.json"
        ):
            raise Refusal("temporary_probe_state_directory_outside_fixed_dev_owner")
        if self._probe_directory("/run/yggdrasil-host-probe-dev") is not None:
            raise Refusal("preexisting_temporary_runtime_directory_unsupported")
        self.canonical_state_identity = self._probe_directory("/var/lib/yggdrasil-host-probe-dev")
        if self._probe_directory(self.probe_state_directory) is not None:
            raise Refusal("temporary_probe_state_directory_exists_no_adoption")
        # The base path proves independent health before its first source,
        # config or unit write. Directory creation belongs after that proof.
        selected = super().prepare(archive, manifest, healthy_config)
        parent = self.io.directory(self.scope.root, private=True)
        try:
            self.ops.mkdir("probe-state", 0o700, dir_fd=parent)
            self.ops.fsync(parent)
        finally:
            self.caller.close("new_probe_state_parent", lambda: self.ops.close(parent))
        self.probe_state_identity = self._probe_directory(self.probe_state_directory)
        self._temporary_directories_unchanged()
        return selected

    @fs_guard
    def activate(
        self, *, before_start: Callable[[DevProbeAdapter], None] | None = None
    ) -> DevProbeAdapter:
        if before_start is None:
            raise Refusal("native_first_start_requires_independent_containment")

        def contain(adapter: DevProbeAdapter) -> None:
            self._temporary_directories_unchanged()
            before_start(adapter)
            self._temporary_directories_unchanged()

        return super().activate(before_start=contain)

    @fs_guard
    def restore_and_cleanup(self, *, already_stopped: bool = False) -> dict[str, Any]:
        self._temporary_directories_unchanged()
        result = super().restore_and_cleanup(already_stopped=already_stopped)
        self._temporary_directories_unchanged()
        parent = self.io.directory(self.scope.root, private=True)
        try:
            self._temporary_directories_unchanged()
            self.ops.rmdir("probe-state", dir_fd=parent)
            self.ops.fsync(parent)
        finally:
            self.caller.close("restore_original_probe_state_parent", lambda: self.ops.close(parent))
        self._temporary_directories_unchanged(operation_state_removed=True)
        result.update(
            original_probe_state_directory="absent"
            if self.canonical_state_identity is None
            else "present",
            probe_state_directory_restored=True,
            runtime_directory_restored=True,
            operation_state_directory_removed=True,
        )
        return result

    def _nonce(self) -> str:
        return self.scope.namespace

    def _source_relative(self, nonce: str) -> str:
        return "var-lib/" + PurePosixPath(self.scope.root).name + "/source"

    def _source_absolute(self, relative: str) -> str:
        return self.scope.root + "/source"

    def _dir(self, path: str, *, create: bool = False) -> int:
        parts = member(path).split("/")
        if parts[0] == "var-lib":
            actual = "/var/lib" + ("/" + "/".join(parts[1:]) if len(parts) > 1 else "")
            if len(parts) > 1 and not (
                actual == self.scope.root or actual.startswith(self.scope.root + "/source")
            ):
                raise Refusal("native_source_directory_outside_frozen_namespace")
        elif parts[0] == "volatile-systemd":
            actual = "/run/systemd/system" + ("/" + "/".join(parts[1:]) if len(parts) > 1 else "")
            if len(parts) > 1 and parts[1] != UNIT + ".d":
                raise Refusal("native_systemd_directory_outside_fixed_dev_dropin")
        else:
            raise Refusal("native_staging_parent_not_fixed_dev_capability")
        if create and actual not in {"/var/lib", self.scope.root, "/run/systemd/system"}:
            parent = self.io.directory(str(PurePosixPath(actual).parent))
            try:
                try:
                    self.ops.mkdir(PurePosixPath(actual).name, 0o700, dir_fd=parent)
                    self.created.add(path)
                except FileExistsError:
                    if path not in self.directories:
                        raise Unknown("native_temporary_directory_collision")
            finally:
                self.caller.close("native_create_parent", lambda: self.ops.close(parent))
        descriptor = self.io.directory(
            actual,
            private=actual.startswith(self.scope.root)
            or len(parts) > 1
            and parts[0] == "volatile-systemd",
        )
        info = self.ops.fstat(descriptor)
        identity = (info.st_dev, info.st_ino, info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode))
        if path in self.directories and self.directories[path] != identity:
            self.caller.close("changed_native_directory", lambda: self.ops.close(descriptor))
            raise Unknown("native_staging_directory_identity_changed")
        self.directories.setdefault(path, identity)
        return descriptor

    def _tree(self, path: str) -> set[str]:
        # Normal cache is derived output in this exclusively created root. It
        # must match this SAME SDK's cache format and checked source header.
        if self.io.link("/proc/self/exe") != self.binding.sdk_realpath:
            raise Refusal("cache_reader_not_selected_sdk")
        cache = self.io.dependencies.cache
        descriptor = self._dir(path)
        result = set()
        try:
            for leaf in self.ops.listdir(descriptor):
                relative = path + "/" + member(leaf)
                meta = self.ops.stat(leaf, dir_fd=descriptor, follow_symlinks=False)
                if stat.S_ISDIR(meta.st_mode):
                    if relative not in self.created:
                        if leaf != "__pycache__" or (
                            meta.st_uid,
                            meta.st_gid,
                            stat.S_IMODE(meta.st_mode),
                        ) != (0, 0, 0o700):
                            raise Unknown("unqualified_native_sdk_cache_directory")
                        self.created.add(relative)
                    result |= self._tree(relative)
                elif stat.S_ISREG(meta.st_mode):
                    if relative not in self.owned:
                        actual = (
                            self._source_absolute(self.source_name)
                            + "/"
                            + str(PurePosixPath(relative).relative_to(self.source_name))
                        )
                        source_match = None
                        for source in self.io.manifest:
                            if (
                                source.endswith(".py")
                                and cache.cache_from_source(self.scope.root + "/source/" + source)
                                == actual
                            ):
                                source_match = source
                                break
                        if source_match is None:
                            raise Unknown("unqualified_extra_native_source_file")
                        data = self._read(relative, mode=0o600)
                        raw = data.data
                        source = self._read(self.source_name + "/" + source_match, mode=0o664)
                        flags = int.from_bytes(raw[4:8], "little") if len(raw) >= 16 else -1
                        valid = (
                            len(raw) >= 16
                            and raw[:4] == cache.MAGIC_NUMBER
                            and (
                                flags == 0
                                and int.from_bytes(raw[8:12], "little")
                                == (source.mtime_ns // 1_000_000_000) & 0xFFFFFFFF
                                and int.from_bytes(raw[12:16], "little") == len(source.data)
                                or flags == 3
                                and raw[8:16] == cache.source_hash(source.data)
                            )
                        )
                        if not valid:
                            raise Unknown("native_sdk_cache_header_source_mismatch")
                        self.owned[relative] = data
                    result.add(relative)
                else:
                    raise Unknown("native_source_cache_alias_or_special")
            return result
        finally:
            self.caller.close(
                "native_cache_inventory_directory", lambda: self.ops.close(descriptor)
            )


def native_installation_qualification(
    scope: FrozenNativeScope, native_io: LinuxIO, original: dict[str, str]
) -> InstallationQualification:
    var_lib = native_io.directory("/var/lib")
    try:
        parent = native_io.os.fstat(var_lib)
    finally:
        native_io.caller.close("native_var_lib_qualification", lambda: native_io.os.close(var_lib))
    if (
        native_io.os.path.realpath(scope.binding.sdk) != scope.binding.sdk_realpath
        or native_io.link("/proc/self/exe") != scope.binding.sdk_realpath
    ):
        raise Refusal("actual_helper_or_selected_sdk_resolution_mismatch")
    sdk = native_io.read(scope.binding.sdk_realpath, limit=16_777_216)
    if sdk.mode & 0o022 or not sdk.mode & 0o111 or sdk.uid != 0 or sdk.gid != 0:
        raise Refusal("actual_sdk_owner_or_execute_policy")
    # Native source may preserve root group modes only in a root-only group.
    groups = native_io.dependencies.grp.getgrgid(0).gr_mem
    if any(native_io.dependencies.pwd.getpwnam(name).pw_uid != 0 for name in groups) or any(
        item.pw_gid == 0 and item.pw_uid != 0 for item in native_io.dependencies.pwd.getpwall()
    ):
        raise Refusal("additional_native_root_group_writer")
    template_path = original["FragmentPath"] if original["LoadState"] == "loaded" else None
    template = None
    if template_path is not None:
        # A canonical immutable template is a declared observation, not a write.
        native_io._read_allowed_template = template_path
        native_io._extra_template = template_path
        template = native_io.read_template(template_path)
    return InstallationQualification(
        "/var/lib",
        parent.st_dev,
        parent.st_ino,
        parent.st_uid,
        parent.st_gid,
        stat.S_IMODE(parent.st_mode),
        scope.binding.sdk,
        scope.binding.sdk_realpath,
        sdk.device,
        sdk.inode,
        sdk.uid,
        sdk.gid,
        sdk.mode,
        sdk.content_sha256,
        template_path,
        template,
    )


def _read_template(self: LinuxIO, path: str) -> bytes:
    if path not in {
        "/etc/systemd/system/yggdrasil-host-probe@.service",
        "/usr/lib/systemd/system/yggdrasil-host-probe@.service",
    }:
        raise Refusal("unsupported_native_template_location")
    parent = self.directory(str(PurePosixPath(path).parent))
    descriptor = None
    try:
        descriptor = self.os.open(
            PurePosixPath(path).name,
            self.os.O_RDONLY | self.os.O_NOFOLLOW | self.os.O_CLOEXEC,
            dir_fd=parent,
        )
        info = self.os.fstat(descriptor)
        if (
            (info.st_uid, info.st_gid, info.st_nlink) != (0, 0, 1)
            or not stat.S_ISREG(info.st_mode)
            or info.st_size > 16384
        ):
            raise Refusal("native_template_metadata")
        data = self.os.read(descriptor, 16385)
        self._check(len(data))
        if len(data) != info.st_size or sha(data) != TEMPLATE_SHA256:
            raise Refusal("native_template_not_unchanged_canonical")
        return data
    finally:
        if descriptor is not None:
            self.caller.close("native_template", lambda: self.os.close(descriptor))
        self.caller.close("native_template_parent", lambda: self.os.close(parent))


LinuxIO.read_template = _read_template


@dataclass
class NativeAssembly:
    scope: FrozenNativeScope
    caller: Caller
    io: LinuxIO
    files: NativeFiles
    runtime: LinuxRuntimeReader


def assemble_native(
    scope: FrozenNativeScope, dependencies: LinuxDependencies, custody_source: str
) -> NativeAssembly:
    """Concrete assembly after the fixed caller and native scope are qualified."""
    clock = NativeClock(scope, dependencies.time)
    command = NativeCommand(scope, dependencies, custody_source)
    runtime = LinuxRuntimeReader(scope, command, clock)
    # No native I/O happens before the frozen scope and whole budget exist.
    sockets = NativeSocketFactory.__new__(NativeSocketFactory)
    sockets.scope = scope
    caller = Caller(
        scope.handle,
        clock,
        command,
        runtime,
        sockets,
        scope.binding.window_end,
        min(600.0, scope.binding.window_end - clock()),
        max_reads=16384,
        max_bytes=536_870_912,
        native_scope=scope,
    )
    native_io = LinuxIO(scope, dependencies, caller)
    NativeSocketFactory.__init__(sockets, scope, dependencies, native_io)
    runtime.attach(caller, native_io, NativeHttp(scope, command, caller))
    return NativeAssembly(
        scope, caller, native_io, NativeFiles.open(scope, caller, native_io), runtime
    )


def run_fixed_dev_worker(
    assembly: NativeAssembly, archive: bytes, healthy_config: bytes
) -> dict[str, Any]:
    """One finite native program, including normal cadence, with no send retry."""
    scope, caller, files = assembly.scope, assembly.caller, assembly.files
    original = parse_unit(read_dev_unit(caller.run), allow_absent=True)
    installation = None
    guard = None

    def contain_before_start(selected: DevProbeAdapter) -> None:
        nonlocal guard
        guard = NativeFaultGuard(assembly, selected)
        guard.arm()

    if original["ActiveState"] == "active":
        adapter = DevProbeAdapter(scope.binding, caller, files)
        adapter.admit()
        contain_before_start(adapter)
    else:
        qualification = native_installation_qualification(scope, assembly.io, original)
        installation = NativeInstallation(files, scope.binding, qualification)
        installation.prepare(archive, scope.manifest, healthy_config)
        adapter = installation.activate(before_start=contain_before_start)
    baseline = adapter.runtime
    if baseline is None or adapter.original_config is None:
        raise Refusal("qualified_baseline_observations_missing")
    if guard is None:
        raise Unknown("independent_containment_missing_before_probe_effect")
    fault_url = adapter.reserve_fault()
    guard.fault_intent(fault_url)
    adapter.stop_owned()
    adapter.swap_base_url()
    adapter.start_owned()
    while adapter.transitions.down != 1 or adapter.transitions.completed_repeats < 2:
        caller.begin(
            "normal_down_and_completed_suppressions"
        ) if caller.phase != "normal_down_and_completed_suppressions" else caller.check()
        adapter.normal_transitions()
        if adapter.transitions.completed_repeats >= 2:
            break
        caller.check()
        # Observation sleep never proves a cycle. Positive stream/state does.
        assembly.runtime.clock.api.sleep(min(2.0, caller.check()))
    adapter.stop_owned()
    adapter.swap_base_url(restore=True)
    adapter.start_owned()
    caller.begin("normal_correlated_recovery")
    while adapter.transitions.recovery != 1:
        adapter.normal_transitions()
        if adapter.transitions.recovery != 1:
            assembly.runtime.clock.api.sleep(min(2.0, caller.check()))
    result = adapter.finish_restoration()
    adapter.stop_owned()
    guard.remove_marker()
    adapter.original_unit = dict(guard.before_unit)
    if installation is not None:
        result["temporary_installation"] = installation.restore_and_cleanup(already_stopped=True)
    else:
        caller.run(systemd("start"), effect=True)
        adapter.unit, adapter.runtime = adapter._observe(active=True, health=True)
    guard.disarm()
    # Core observations, including tests with substituted ports, cannot mint
    # the final live receipt. Native entry adds that after transport/reap proof.
    result["status"] = "OBSERVATIONS_COMPLETE"
    result["independent_guard_disarmed"] = True
    result["baseline"] = {
        "observed_epoch_seconds": baseline.epoch_seconds,
        "readyz_status": baseline.readyz_status,
        "required_ok": json.loads(baseline.health_body, object_pairs_hook=unique)["required_ok"],
        "health_body_sha256": sha(baseline.health_body),
        "source_manifest_sha256": baseline.source_manifest_sha256,
        "source_files_sha256": dict(baseline.source_hashes),
        "configuration_sha256": adapter.original_config.content_sha256,
        "producer_route_sha256": sha(baseline.route.encode()),
        "worker_start_sha256": baseline.worker_start,
        "heartbeat_backing_sha256": sha(baseline.heartbeat_backing.encode()),
        "consumer": baseline.consumer,
        "normal_binding": baseline.binding_name,
    }
    result["dev_candidate_references"] = [
        {
            "role": role,
            "container_sha256": sha(container.encode()),
            "image_id": image,
            "source_revision": revision,
        }
        for role, container, image, revision, pid, start in scope.candidate_references
    ]
    return result


def supervisor_command(scope: FrozenNativeScope) -> tuple[str, ...]:
    properties = {
        "RuntimeMaxSec": str(
            max(1, int(scope.binding.window_end - scope.binding.window_start - 5))
        ),
        "TimeoutStopSec": "5",
        "KillMode": "control-group",
        "Restart": "no",
        "StandardOutput": "null",
        "StandardError": "null",
        "UMask": "0077",
        "WorkingDirectory": scope.root,
        "NoNewPrivileges": "yes",
        "PrivateTmp": "yes",
        "PrivateDevices": "yes",
        "ProtectSystem": "strict",
        "ProtectControlGroups": "yes",
        "ProtectKernelTunables": "yes",
        "ProtectKernelModules": "yes",
        "ReadWritePaths": scope.root + " /run/systemd/system -/etc/yggdrasil/host-probe",
        "RestrictAddressFamilies": "AF_UNIX AF_INET AF_INET6",
    }
    # AF_INET is necessary for the held fault socket and independent health.
    # No credential is attached to the supervisor; the normal DEV unit retains
    # its own existing credential/runtime/state mechanisms.
    return (
        "/usr/bin/systemd-run",
        "--quiet",
        "--unit=yggdrasil-dev-probe-" + scope.handle.operation,
        "--service-type=exec",
        "--uid=root",
        "--gid=root",
        *("--property=" + key + "=" + value for key, value in properties.items()),
        "--setenv=PATH=/usr/sbin:/usr/bin:/sbin:/bin",
        "--setenv=LC_ALL=C",
        "--",
        scope.binding.sdk,
        "-I",
        scope.root + "/program.py",
        "--fixed-dev-worker",
        scope.handle.operation,
    )


def watchdog_unit(scope: FrozenNativeScope) -> str:
    return "yggdrasil-dev-probe-watch-" + scope.handle.operation + ".service"


def watchdog_command(scope: FrozenNativeScope) -> tuple[str, ...]:
    duration = max(1, int(scope.binding.window_end - scope.binding.window_start - 5))
    return (
        "/usr/bin/systemd-run",
        "--quiet",
        "--unit=" + watchdog_unit(scope),
        "--service-type=exec",
        "--uid=root",
        "--gid=root",
        "--property=RuntimeMaxSec=" + str(duration),
        "--property=TimeoutStopSec=5",
        "--property=KillMode=control-group",
        "--property=Restart=no",
        "--property=StandardOutput=null",
        "--property=StandardError=null",
        "--property=UMask=0077",
        "--property=NoNewPrivileges=yes",
        "--property=ProtectSystem=strict",
        "--property=ReadWritePaths="
        + scope.root
        + " /run/systemd/system -/etc/yggdrasil/host-probe",
        "--property=RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6",
        "--property=WorkingDirectory=" + scope.root,
        "--",
        scope.binding.sdk,
        "-I",
        scope.root + "/program.py",
        "--watch-dev-operation",
        scope.handle.operation,
    )


def watchdog_show(scope: FrozenNativeScope) -> tuple[str, ...]:
    return (
        "/usr/bin/systemctl",
        "show",
        watchdog_unit(scope),
        "--property=" + ",".join(WATCHDOG_SHOW_KEYS),
        "--all",
        "--no-pager",
    )


def watchdog_stop(scope: FrozenNativeScope) -> tuple[str, ...]:
    return ("/usr/bin/systemctl", "stop", watchdog_unit(scope), "--no-pager")


SUPERVISOR_PROFILE_KEYS = (
    "ExecStart",
    "WorkingDirectory",
    "KillMode",
    "Restart",
    "TimeoutStopUSec",
    "Type",
    "NotifyAccess",
    "ExecStop",
    "ExecStopPost",
    "SendSIGKILL",
    "KillSignal",
    "FinalKillSignal",
    "TimeoutStopFailureMode",
)
SUPERVISOR_SHOW_KEYS = (
    "Id",
    "ActiveState",
    "SubState",
    "MainPID",
    "InvocationID",
    "ControlGroup",
    "Job",
    *SUPERVISOR_PROFILE_KEYS,
)
WATCHDOG_SHOW_KEYS = (
    "ActiveState",
    "SubState",
    "MainPID",
    "InvocationID",
    "ControlGroup",
    "ExecStart",
    "ExecMainStartTimestampMonotonic",
    "Job",
)


def supervisor_show(operation: str) -> tuple[str, ...]:
    return (
        "/usr/bin/systemctl",
        "show",
        "yggdrasil-dev-probe-" + operation + ".service",
        "--property=" + ",".join(SUPERVISOR_SHOW_KEYS),
        "--all",
        "--no-pager",
    )


def supervisor_stop(scope: FrozenNativeScope) -> tuple[str, ...]:
    return (
        "/usr/bin/systemctl",
        "stop",
        "yggdrasil-dev-probe-" + scope.handle.operation + ".service",
        "--no-pager",
    )


def supervisor_profile(unit: dict[str, str]) -> dict[str, Any]:
    return {
        key: configured_exec(unit[key])
        if key in {"ExecStart", "ExecStop", "ExecStopPost"}
        else unit[key]
        for key in SUPERVISOR_PROFILE_KEYS
    }


def original_supervisor(assembly: NativeAssembly, record: dict[str, Any]) -> dict[str, Any]:
    scope, io_port = assembly.scope, assembly.io
    raw = io_port.read(scope.root + "/supervisor-start.json", limit=16384, mode=0o600).data
    saved = json.loads(raw, object_pairs_hook=unique)
    unit_name = "yggdrasil-dev-probe-" + scope.handle.operation + ".service"
    if (
        sha(raw) != record.get("supervisor_start_sha256")
        or saved.get("unit") != unit_name
        or saved.get("operation") != scope.handle.operation
        or saved.get("program_sha256") != scope.program_sha256
        or saved.get("boot_id") != scope.binding.boot_id
        or saved.get("pid") != record.get("helper_pid")
        or saved.get("cgroup") != "/system.slice/" + unit_name
        or not identifier(saved.get("invocation", ""))
    ):
        raise Unknown("guard_original_supervisor_evidence_unqualified")
    if (
        saved["profile"]["KillMode"] != "control-group"
        or saved["profile"]["Restart"] != "no"
        or finite_stop_seconds(saved["profile"]) > 5
    ):
        raise Unknown("guard_original_supervisor_stop_unqualified")
    supervisor_profile(saved["profile"])
    return saved


def quiesce_original_supervisor(assembly: NativeAssembly, record: dict[str, Any]) -> None:
    """Stop the last possible command producer before canceling the probe job."""
    scope, caller, io_port = assembly.scope, assembly.caller, assembly.io
    saved = original_supervisor(assembly, record)
    unit_name = saved["unit"]
    group = saved["cgroup"]
    if io_port.cgroup(group):
        current = systemctl_fields(
            caller.run(supervisor_show(scope.handle.operation)), SUPERVISOR_SHOW_KEYS
        )
        if (
            current.get("Id") != unit_name
            or current.get("InvocationID") != saved["invocation"]
            or current.get("MainPID") not in {"0", saved["pid"]}
            or current.get("ControlGroup") != group
            or supervisor_profile(current) != supervisor_profile(saved["profile"])
            or current["KillMode"] != "control-group"
            or current["Restart"] != "no"
            or finite_stop_seconds(current) > 5
        ):
            raise Unknown("guard_refuses_foreign_supervisor")
        caller.run(supervisor_stop(scope), effect=True)
    # The manager may unload this transient unit immediately after stop.
    # The original saved cgroup, not a new show/PID lookup, proves reaping.
    if io_port.cgroup(group):
        raise Unknown("guard_supervisor_cgroup_not_empty")


class NativeFaultGuard:
    """One independent finite watchdog for the separately managed DEV unit."""

    def __init__(self, assembly: NativeAssembly, adapter: DevProbeAdapter):
        self.assembly, self.scope, self.caller, self.io, self.adapter = (
            assembly,
            assembly.scope,
            assembly.caller,
            assembly.io,
            adapter,
        )
        self.ops = self.io.os
        self.record = {}
        self.marker = "99-ygg-dev-owner-" + self.scope.handle.operation + ".conf"
        self.parent_path = "/run/systemd/system/" + UNIT + ".d"

    @fs_guard
    def write_record(self) -> None:
        raw = json.dumps(self.record, sort_keys=True, separators=(",", ":")).encode()
        self.caller.check(len(raw))
        root = self.assembly.files.fd
        descriptor = None
        try:
            descriptor = self.ops.open(
                "watchdog-new.json",
                self.ops.O_WRONLY
                | self.ops.O_CREAT
                | self.ops.O_EXCL
                | self.ops.O_NOFOLLOW
                | self.ops.O_CLOEXEC,
                0o600,
                dir_fd=root,
            )
            self.ops.fchmod(descriptor, 0o600)
            pending = memoryview(raw)
            while pending:
                self.caller.check()
                count = self.ops.write(descriptor, pending[:65536])
                if count <= 0:
                    raise Unknown("watchdog_record_write_unknown")
                pending = pending[count:]
            self.ops.fsync(descriptor)
        finally:
            if descriptor is not None:
                self.caller.close("watchdog_record", lambda: self.ops.close(descriptor))
        self.ops.replace("watchdog-new.json", "watchdog.json", src_dir_fd=root, dst_dir_fd=root)
        self.ops.fsync(root)

    @fs_guard
    def arm(self) -> None:
        import base64

        if not callable(getattr(self.ops, "pidfd_open", None)):
            raise Refusal("linux_pidfd_watchdog_required_before_fault")
        if self.scope.binding.window_end - self.caller.clock() < 3 * self.adapter.cadence + 90:
            raise Refusal("accepted_window_cannot_cover_normal_cycles_and_cleanup")
        finite_stop_seconds(self.adapter.unit)
        self.caller.work_deadline = self.scope.binding.window_end - RESTORATION_RESERVE
        self.before_unit = dict(self.adapter.unit)
        saved = self.assembly.files.read("config")
        parent = self.io.directory("/run/systemd/system")
        self.parent_created = False
        try:
            try:
                self.ops.mkdir(UNIT + ".d", 0o700, dir_fd=parent)
                self.parent_created = True
            except FileExistsError:
                pass
        finally:
            self.caller.close("watchdog_systemd_parent", lambda: self.ops.close(parent))
        parent = self.io.directory(self.parent_path)
        descriptor = None
        body = (
            "[Service]\nEnvironment=YGG_DEV_OPERATION=" + self.scope.handle.operation + "\n"
        ).encode()
        try:
            descriptor = self.ops.open(
                self.marker,
                self.ops.O_WRONLY
                | self.ops.O_CREAT
                | self.ops.O_EXCL
                | self.ops.O_NOFOLLOW
                | self.ops.O_CLOEXEC,
                0o600,
                dir_fd=parent,
            )
            self.ops.fchmod(descriptor, 0o600)
            if self.ops.write(descriptor, body) != len(body):
                raise Unknown("owned_operation_marker_write_unknown")
            self.ops.fsync(descriptor)
            meta = self.ops.fstat(descriptor)
            self.marker_identity = (
                meta.st_dev,
                meta.st_ino,
                meta.st_uid,
                meta.st_gid,
                meta.st_mode,
                meta.st_nlink,
                meta.st_size,
                meta.st_mtime_ns,
                meta.st_ctime_ns,
            )
            self.ops.fsync(parent)
        finally:
            if descriptor is not None:
                self.caller.close("owned_operation_marker", lambda: self.ops.close(descriptor))
            self.caller.close("owned_operation_marker_parent", lambda: self.ops.close(parent))
        self.caller.run(systemd("reload_for_temporary_dev"), effect=True)
        guarded = parse_unit(read_dev_unit(self.caller.run))
        if (
            "YGG_DEV_OPERATION=" + self.scope.handle.operation not in guarded["Environment"].split()
            or self.parent_path + "/" + self.marker not in guarded["DropInPaths"].split()
        ):
            raise Unknown("effective_owned_marker_not_loaded")
        self.adapter.original_unit = dict(guarded)
        self.adapter.unit = guarded
        pid = str(self.ops.getpid())
        self.io.pids.add(pid)
        statraw = self.io.read("/proc/" + pid + "/stat", limit=4096, proc=True).data.decode()
        fields = statraw[statraw.rfind(") ") + 2 :].split()
        original = asdict(saved)
        original["data"] = base64.b64encode(saved.data).decode()
        self.record = {
            "scope_input": json.loads(
                _scope_json(self.scope, saved.data, self.caller.command.public_source)
            ),
            "binding": asdict(self.adapter.binding),
            "config": original,
            "guarded_unit": guarded,
            "preexisting_identity": [
                self.before_unit[key]
                for key in (
                    "InvocationID",
                    "MainPID",
                    "ControlGroup",
                    "ExecMainStartTimestampMonotonic",
                )
            ],
            "helper_pid": pid,
            "helper_start": sha(
                (self.scope.binding.boot_id + ":" + pid + ":" + fields[19]).encode()
            ),
            "fault": None,
            "disarmed": False,
            "marker": self.marker,
            "marker_identity": list(self.marker_identity),
            "parent_created": self.parent_created,
            "supervisor_start_sha256": sha(
                self.io.read(
                    self.scope.root + "/supervisor-start.json", limit=16384, mode=0o600
                ).data
            ),
        }
        self.write_record()
        self.caller.run(watchdog_command(self.scope), effect=True)
        raw = self.caller.run(watchdog_show(self.scope))
        self.guardian = systemctl_fields(raw, WATCHDOG_SHOW_KEYS)
        expected = (
            self.scope.binding.sdk
            + " -I "
            + self.scope.root
            + "/program.py --watch-dev-operation "
            + self.scope.handle.operation
        )
        if (
            self.guardian.get("ActiveState") != "active"
            or self.guardian.get("MainPID") == "0"
            or not identifier(self.guardian.get("InvocationID", ""))
            or "argv[]=" + expected + " ;" not in self.guardian.get("ExecStart", "")
        ):
            raise Unknown("independent_watchdog_not_positively_running")
        # Type=exec proves execve, not that the watcher has attached its pidfd
        # and selector. No managed probe start/fault may precede this ack.
        until = min(self.caller.clock() + 5, self.caller.work_deadline)
        while True:
            try:
                raw = self.io.read(
                    self.scope.root + "/watchdog-ready.json", limit=16384, mode=0o600
                ).data
                ready = json.loads(raw, object_pairs_hook=unique)
                break
            except FileNotFoundError:
                if self.caller.clock() >= until:
                    raise Unknown("independent_watchdog_initialization_unconfirmed")
                self.assembly.runtime.clock.api.sleep(min(0.05, until - self.caller.clock()))
        identity = self.io.guard_process_identity(
            self.guardian["MainPID"], self.scope.binding.boot_id
        )
        if (
            ready.get("operation") != self.scope.handle.operation
            or ready.get("program_sha256") != self.scope.program_sha256
            or ready.get("boot_id") != self.scope.binding.boot_id
            or ready.get("helper_pid") != pid
            or ready.get("helper_start") != self.record["helper_start"]
            or ready.get("guardian_pid") != self.guardian["MainPID"]
            or identity is None
            or identity[1] in {"Z", "X", "x"}
            or ready.get("guardian_start") != identity[0]
        ):
            raise Unknown("independent_watchdog_ready_identity_unqualified")

    def fault_intent(self, url: str) -> None:
        import base64

        original = base64.b64decode(self.record["config"]["data"])
        values = parse_config(original)
        fault = original.replace(
            ("PROBE_BASE_URL=" + values["PROBE_BASE_URL"] + "\n").encode(),
            ("PROBE_BASE_URL=" + url + "\n").encode(),
        )
        if not url.startswith("http://127.0.0.1:") or fault == original:
            raise Refusal("guard_fault_delta_not_numeric_reserved_socket")
        self.record["fault"] = base64.b64encode(fault).decode()
        self.write_record()

    @fs_guard
    def remove_marker(self) -> None:
        parent = self.io.directory(self.parent_path)
        try:
            meta = self.ops.stat(self.marker, dir_fd=parent, follow_symlinks=False)
            actual = (
                meta.st_dev,
                meta.st_ino,
                meta.st_uid,
                meta.st_gid,
                meta.st_mode,
                meta.st_nlink,
                meta.st_size,
                meta.st_mtime_ns,
                meta.st_ctime_ns,
            )
            if actual != self.marker_identity:
                raise Unknown("owned_marker_identity_changed_no_cleanup")
            self.ops.unlink(self.marker, dir_fd=parent)
            self.ops.fsync(parent)
            empty = not self.ops.listdir(parent)
        finally:
            self.caller.close("owned_marker_removal", lambda: self.ops.close(parent))
        if self.parent_created:
            if not empty:
                raise Unknown("foreign_entry_in_created_guard_parent")
            parent = self.io.directory("/run/systemd/system")
            try:
                self.ops.rmdir(UNIT + ".d", dir_fd=parent)
                self.ops.fsync(parent)
            finally:
                self.caller.close("guard_parent_removal", lambda: self.ops.close(parent))
        self.caller.run(systemd("reload_for_temporary_dev"), effect=True)

        restored = parse_unit(read_dev_unit(self.caller.run))
        if unit_profile(restored) != unit_profile(self.before_unit):
            raise Unknown("original_unit_profile_not_restored_after_owned_marker")

    def disarm(self) -> None:
        self.record["disarmed"] = True
        self.write_record()
        current = systemctl_fields(self.caller.run(watchdog_show(self.scope)), WATCHDOG_SHOW_KEYS)
        if any(
            current.get(key) != self.guardian.get(key)
            for key in (
                "InvocationID",
                "MainPID",
                "ControlGroup",
                "ExecMainStartTimestampMonotonic",
            )
        ) or configured_exec(current.get("ExecStart", "")) != configured_exec(
            self.guardian.get("ExecStart", "")
        ):
            raise Unknown("watchdog_incarnation_changed_no_stop")
        self.caller.run(watchdog_stop(self.scope), effect=True)
        # The authenticated stop job is synchronous. Successful transient
        # units may unload immediately; retain the pre-stop incarnation and
        # prove its saved cgroup empty/removed rather than querying a new unit.
        if self.io.cgroup(current["ControlGroup"]):
            raise Unknown("watchdog_reaping_unknown")


def cleanup_owned_dev_fault(assembly: NativeAssembly, record: dict[str, Any]) -> dict[str, Any]:
    """Guardian terminal path: stop only positively owned DEV, never restart."""
    import base64

    if record.get("disarmed") is True:
        return {"status": "disarmed", "operation": assembly.scope.handle.operation}
    caller, io_port = assembly.caller, assembly.io
    binding = Binding(**record["binding"])
    guarded = record["guarded_unit"]

    def observe() -> dict[str, str]:
        value = parse_unit(read_dev_unit(caller.run), allow_restarts=True, cleanup_states=True)
        if unit_profile(value, cleanup=True) != unit_profile(guarded, cleanup=True):
            raise Unknown("guard_refuses_foreign_dev_profile")
        normal_unit(value, binding)
        if (
            guarded["ControlGroup"]
            and value["ControlGroup"]
            and guarded["ControlGroup"] != value["ControlGroup"]
        ):
            raise Unknown("guard_refuses_changed_dev_cgroup")
        return value

    # A queued restart has no live creator PID. Its ownership comes from the
    # exact effective profile AND the still-owned physical operation marker,
    # never merely from the unit name or a caller-supplied Boolean.
    marker = "99-ygg-dev-owner-" + assembly.scope.handle.operation + ".conf"
    if record.get("marker") != marker:
        raise Unknown("guard_marker_reference_unqualified")
    parent = io_port.directory("/run/systemd/system/" + UNIT + ".d")
    descriptor = None

    def identity(info: Any) -> tuple[int, ...]:
        return (
            info.st_dev,
            info.st_ino,
            info.st_uid,
            info.st_gid,
            info.st_mode,
            info.st_nlink,
            info.st_size,
            info.st_mtime_ns,
            info.st_ctime_ns,
        )

    try:
        descriptor = io_port.os.open(
            marker,
            io_port.os.O_RDONLY
            | io_port.os.O_NOFOLLOW
            | io_port.os.O_NONBLOCK
            | io_port.os.O_CLOEXEC,
            dir_fd=parent,
        )
        expected = tuple(record["marker_identity"])
        body = (
            "[Service]\nEnvironment=YGG_DEV_OPERATION=" + assembly.scope.handle.operation + "\n"
        ).encode()
        if (
            identity(io_port.os.fstat(descriptor)) != expected
            or io_port.os.read(descriptor, 257) != body
            or identity(io_port.os.stat(marker, dir_fd=parent, follow_symlinks=False)) != expected
        ):
            raise Unknown("guard_refuses_unowned_physical_marker")
    finally:
        if descriptor is not None:
            caller.close("guard_marker_descriptor", lambda: io_port.os.close(descriptor))
        caller.close("guard_marker_parent", lambda: io_port.os.close(parent))
    caller.check()

    saved = dict(record["config"])
    saved["data"] = base64.b64decode(saved["data"], validate=True)
    original = FileState(**saved)
    assembly.files.names["config"] = binding.config
    current = assembly.files.read("config")
    fault = base64.b64decode(record["fault"], validate=True) if record.get("fault") else None
    if current.data not in {original.data, fault}:
        raise Unknown("guard_refuses_unowned_config_delta")
    assembly.runtime._sources(binding)

    keys = ("InvocationID", "MainPID", "ControlGroup", "ExecMainStartTimestampMonotonic")
    # Slot authority survives an ordinary exit or pre-exec observation. A
    # complete stable foreign launcher is a veto, not an absence requirement.
    unit = observe()
    producer = io_port.guard_creator(unit["MainPID"], binding) if unit["MainPID"] != "0" else None
    again = observe()
    if producer is not None and all(again[key] == unit[key] for key in keys):
        actual = [unit[key] for key in keys]
        marker_value = producer["environment"].get("YGG_DEV_OPERATION")
        if (
            marker_value != assembly.scope.handle.operation
            and actual != record["preexisting_identity"]
        ):
            raise Unknown("guard_refuses_foreign_incarnation")
        if (
            producer["uid"] != 0
            or producer["cwd"] != binding.package
            or producer["cgroup"] != unit["ControlGroup"]
        ):
            raise Unknown("guard_refuses_foreign_creator")
    retained_groups = {
        value
        for value in (guarded["ControlGroup"], unit["ControlGroup"], again["ControlGroup"])
        if value
    }
    unit = again
    members = io_port.cgroup(unit["ControlGroup"]) if unit["ControlGroup"] else ()
    stopped = (
        unit["ActiveState"] not in {"inactive", "failed"}
        or unit["MainPID"] != "0"
        or unit["Job"] not in {"", "0"}
        or bool(members)
    )
    if stopped:
        # stop synchronously cancels the owned queued start/restart job too.
        caller.run(systemd("stop"), effect=True)
    after = observe()
    if (
        after["ActiveState"] not in {"inactive", "failed"}
        or after["MainPID"] != "0"
        or after["Job"] not in {"", "0"}
        or any(
            io_port.cgroup(group)
            for group in retained_groups
            | ({after["ControlGroup"]} if after["ControlGroup"] else set())
        )
    ):
        raise Unknown("guard_owned_dev_reap_unconfirmed")
    if current.data != original.data:
        assembly.files.atomic_config(current, original.data, restore=original)
    return {
        "status": "unknown",
        "operation": assembly.scope.handle.operation,
        "owned_dev_stopped": stopped,
        "healthy_config_restored": True,
        "history_rewound": False,
    }


def watch_dev_operation(root_path: str, dependencies: LinuxDependencies) -> dict[str, Any]:
    descriptor = dependencies.os.open(
        root_path + "/watchdog.json",
        dependencies.os.O_RDONLY | dependencies.os.O_NOFOLLOW | dependencies.os.O_CLOEXEC,
    )
    try:
        record = json.loads(dependencies.os.read(descriptor, 1048577), object_pairs_hook=unique)
    finally:
        dependencies.os.close(descriptor)
    scope, config, custody = _decode_scope(json.dumps(record["scope_input"]).encode())
    if root_path != scope.root:
        raise Refusal("watchdog_scope_root_mismatch")
    assembly = assemble_native(scope, dependencies, custody)
    assembly.caller.phase_seconds = scope.binding.window_end - assembly.caller.clock()
    selector = pidfd = None
    try:
        budget = BootstrapBudget(
            {
                "_start_epoch": dependencies.time.time() - 1,
                "_end_epoch": dependencies.time.time() + assembly.caller.check(),
            },
            dependencies,
        )
        try:
            original_supervisor(assembly, record)
            before = assembly.io.guard_process_identity(record["helper_pid"], scope.binding.boot_id)
            if (
                before is None
                or before[0] != record["helper_start"]
                or before[1] in {"Z", "X", "x"}
            ):
                raise ProcessLookupError("original helper identity already gone")
            pidfd = dependencies.os.pidfd_open(int(record["helper_pid"]), 0)
            after = assembly.io.guard_process_identity(record["helper_pid"], scope.binding.boot_id)
            if after is None or after[0] != before[0] or after[1] in {"Z", "X", "x"}:
                raise ProcessLookupError("original helper changed during pidfd attach")
            selector = dependencies.selectors.DefaultSelector()
            selector.register(pidfd, dependencies.selectors.EVENT_READ, "original_helper_exit")
            guardian_pid = str(dependencies.os.getpid())
            guardian = assembly.io.guard_process_identity(guardian_pid, scope.binding.boot_id)
            if guardian is None or guardian[1] in {"Z", "X", "x"}:
                raise Unknown("watchdog_own_process_unqualified")
            _write_bootstrap_file(
                assembly.files.fd,
                "watchdog-ready.json",
                json.dumps(
                    {
                        "operation": scope.handle.operation,
                        "program_sha256": scope.program_sha256,
                        "boot_id": scope.binding.boot_id,
                        "helper_pid": record["helper_pid"],
                        "helper_start": record["helper_start"],
                        "guardian_pid": guardian_pid,
                        "guardian_start": guardian[0],
                    },
                    sort_keys=True,
                ).encode(),
                dependencies,
                budget,
            )
            selector.select(
                max(0, scope.binding.window_end - RESTORATION_RESERVE - assembly.caller.clock())
            )
        except Exception:
            # No ready ack on attach/setup failure, hence no first probe start.
            # A wait failure after readiness follows the same bounded cleanup.
            pass
        # Main-PID death is not command-child death. Reconcile the original
        # supervisor cgroup before the final probe cancellation; this also
        # prevents a late systemctl-start child from undoing containment.
        quiesce_original_supervisor(assembly, record)
        # Only after every helper writer is gone is the final phase authoritative.
        latest = assembly.io.read(root_path + "/watchdog.json", limit=1048576, mode=0o600)
        record = json.loads(latest.data, object_pairs_hook=unique)
        result = cleanup_owned_dev_fault(assembly, record)
        root = assembly.files.fd
        _write_bootstrap_file(
            root,
            "watchdog-result.json",
            json.dumps(result, sort_keys=True).encode(),
            dependencies,
            budget,
        )
        return result
    finally:
        if selector is not None:
            assembly.caller.close("watchdog_selector", selector.close)
        if pidfd is not None:
            assembly.caller.close("helper_pidfd", lambda: dependencies.os.close(pidfd))
        assembly.files.close()


def strict_dev_transport(scope: FrozenNativeScope) -> tuple[str, ...]:
    if scope.binding.transport != "ygg-dev":
        raise Refusal("transport_not_fixed_expected_dev_alias")
    return (
        "/usr/bin/ssh",
        "-T",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        "ConnectTimeout=10",
        "-o",
        "ConnectionAttempts=1",
        "-o",
        "ClearAllForwardings=yes",
        "-o",
        "ForwardAgent=no",
        "-o",
        "ControlMaster=no",
        "-o",
        "ControlPath=none",
        "-o",
        "PermitLocalCommand=no",
        "--",
        "ygg-dev",
        "sudo",
        "-n",
        scope.binding.sdk,
        "-I",
        "-",
    )


DOCKER_DEV_METADATA = (
    '{"id":{{json .Id}},"image_id":{{json .Image}},"revision":{{json (index .Config.Labels "org.opencontainers.image.revision")}},"pid":{{.State.Pid}},"project":{{json (index .Config.Labels "com.docker.compose.project")}},'
    '"service":{{json (index .Config.Labels "com.docker.compose.service")}},"channel":{{range .Config.Env}}{{if eq (index (split . "=") 0) "PKM_ENVIRONMENT"}}{{json (index (split . "=") 1)}}{{end}}{{end}},'
    '"heartbeat":{{range .Config.Env}}{{if eq (index (split . "=") 0) "WORKER_HEARTBEAT_PATH"}}{{json (index (split . "=") 1)}}{{end}}{{end}},'
    '"ports":{{json .NetworkSettings.Ports}},"mounts":{{json .Mounts}}}'
)
DOCKER_DEV_API_METADATA = DOCKER_DEV_METADATA.replace(
    '"heartbeat":{{range .Config.Env}}{{if eq (index (split . "=") 0) "WORKER_HEARTBEAT_PATH"}}{{json (index (split . "=") 1)}}{{end}}{{end}},',
    "",
)


def discover_fixed_dev_producer(
    dependencies: LinuxDependencies, custody_source: str, *, deadline: float
) -> dict[str, Any]:
    """The accepted FIRST preflight can compute unknown current DEV values.

    Supported producer: normal Compose api/worker labels + PKM_ENVIRONMENT=dev,
    worker's explicit heartbeat setting, actual mount/port mappings and proc
    namespace. No full topology, model/capture/other-consumer verifier is added.
    """
    # The public process primitive is independent of any PROD resource globals.
    selected, namespace = (
        {},
        {
            name: getattr(dependencies, name)
            for name in ("os", "subprocess", "selectors", "signal", "time")
        },
    )
    for node in ast.parse(custody_source).body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in {
            "OperationFailure",
            "_bounded_process",
            "_safe_command",
        }:
            selected[node.name] = (
                "\n".join(custody_source.splitlines()[node.lineno - 1 : node.end_lineno]) + "\n"
            )
    if (
        set(selected) != {"OperationFailure", "_bounded_process", "_safe_command"}
        or sha(selected["_bounded_process"].encode()) != CUSTODY_SHA256
    ):
        raise Refusal("first_preflight_custody_source_unqualified")
    exec(
        "from __future__ import annotations\n"
        + "\n".join(
            selected[key] for key in ("OperationFailure", "_bounded_process", "_safe_command")
        ),
        namespace,
    )

    def check() -> float:
        left = deadline - dependencies.time.monotonic()
        if left <= 2.1:
            raise Unknown("first_preflight_whole_deadline_or_reap_reserve")
        return left - 2.1

    def command(argv: tuple[str, ...], limit: int = 131072) -> bytes:
        data = namespace["_safe_command"](list(argv), timeout=min(10.0, check()), limit=limit)
        check()
        return data.encode()

    def read(path: str, limit: int = 65536) -> bytes:
        check()
        descriptor = dependencies.os.open(
            path,
            dependencies.os.O_RDONLY
            | dependencies.os.O_NOFOLLOW
            | dependencies.os.O_NONBLOCK
            | dependencies.os.O_CLOEXEC,
        )
        try:
            chunks = bytearray()
            while True:
                check()
                block = dependencies.os.read(descriptor, min(16384, limit + 1 - len(chunks)))
                if not block:
                    return bytes(chunks)
                chunks.extend(block)
                if len(chunks) > limit:
                    raise Unknown("first_preflight_read_bound")
        finally:
            dependencies.os.close(descriptor)

    hostname = read("/proc/sys/kernel/hostname", 256).decode().strip()
    if hostname != "ygg-dev":
        raise Refusal("actual_guest_does_not_match_proposed_fixed_dev_target")
    candidates = (
        command(
            (
                "/usr/bin/docker",
                "ps",
                "--filter",
                "label=com.docker.compose.service=api",
                "--format",
                "{{.ID}}",
            ),
            8192,
        )
        .decode()
        .splitlines()
    )
    if not 1 <= len(candidates) <= 8 or any(
        re.fullmatch(r"[0-9a-f]{12,64}", value) is None for value in candidates
    ):
        raise Refusal("normal_dev_api_producer_candidates_unqualified")
    apis = []
    for container in candidates:
        data = json.loads(
            command(("/usr/bin/docker", "inspect", "--format", DOCKER_DEV_API_METADATA, container)),
            object_pairs_hook=unique,
        )
        if data.get("channel") == "dev" and data.get("service") == "api":
            apis.append(data)
    if len(apis) != 1 or not apis[0].get("project"):
        raise Refusal("one_normal_dev_api_producer_not_observed")
    api = apis[0]
    workers = (
        command(
            (
                "/usr/bin/docker",
                "ps",
                "--filter",
                "label=com.docker.compose.service=worker",
                "--filter",
                "label=com.docker.compose.project=" + api["project"],
                "--format",
                "{{.ID}}",
            ),
            8192,
        )
        .decode()
        .splitlines()
    )
    if len(workers) != 1 or re.fullmatch(r"[0-9a-f]{12,64}", workers[0]) is None:
        raise Refusal("one_normal_matching_dev_worker_not_observed")
    worker = json.loads(
        command(("/usr/bin/docker", "inspect", "--format", DOCKER_DEV_METADATA, workers[0])),
        object_pairs_hook=unique,
    )
    if (
        worker.get("channel") != "dev"
        or worker.get("service") != "worker"
        or worker.get("project") != api["project"]
        or type(worker.get("pid")) is not int
        or worker["pid"] < 1
        or not absolute(worker.get("heartbeat", ""))
    ):
        raise Refusal("normal_worker_requires_explicit_effective_heartbeat_path")
    for candidate in (api, worker):
        if (
            not identifier(candidate.get("id", ""), 64)
            or re.fullmatch(r"sha256:[0-9a-f]{64}", candidate.get("image_id", "")) is None
            or candidate.get("revision") is not None
            and re.fullmatch(r"[0-9a-f]{40}", candidate["revision"]) is None
        ):
            raise Refusal("actual_dev_candidate_container_image_or_revision_missing")
    if (
        api["image_id"] != worker["image_id"]
        or api.get("revision")
        and worker.get("revision")
        and api["revision"] != worker["revision"]
    ):
        raise Refusal("actual_api_worker_candidate_mismatch")
    worker_pid = str(worker["pid"])

    def worker_command(pid: str) -> tuple[str, ...]:
        raw = read("/proc/" + pid + "/cmdline")
        if not raw.endswith(b"\0"):
            raise Refusal("worker_process_command_incomplete")
        return tuple(item.decode() for item in raw[:-1].split(b"\0"))

    argv = worker_command(worker_pid)
    if len(argv) != 3 or argv[1:] != ("-m", "app.workers.outbox_worker"):
        group = read("/proc/" + worker_pid + "/cgroup", 4096).decode().strip()
        if not group.startswith("0::/") or ".." in PurePosixPath(group[3:]).parts:
            raise Refusal("worker_container_requires_supported_cgroup_v2")
        candidates = (
            read("/sys/fs/cgroup" + group[3:] + "/cgroup.procs", 16384).decode().splitlines()
        )
        if len(candidates) > 64 or any(not pid.isdigit() or int(pid) < 1 for pid in candidates):
            raise Refusal("worker_producer_process_set_unbounded")
        matches = []
        for pid in candidates:
            candidate = worker_command(pid)
            if len(candidate) == 3 and candidate[1:] == ("-m", "app.workers.outbox_worker"):
                matches.append((pid, candidate))
        if len(matches) != 1:
            raise Refusal("one_actual_outbox_worker_process_not_observed")
        worker_pid, argv = matches[0]
    published = api.get("ports")
    ports = published.get("8000/tcp") if isinstance(published, dict) else None
    if (
        not isinstance(ports, list)
        or len(ports) not in {1, 2}
        or any(
            not isinstance(row, dict)
            or set(row) != {"HostIp", "HostPort"}
            or not isinstance(row["HostIp"], str)
            or not isinstance(row["HostPort"], str)
            or re.fullmatch(r"[1-9][0-9]{0,4}", row["HostPort"]) is None
            or int(row["HostPort"]) > 65535
            for row in ports
        )
    ):
        raise Refusal("actual_dev_api_publication_ambiguous_or_unsupported")
    addresses = {row["HostIp"] for row in ports}
    if not (
        len(ports) == 1
        and addresses <= {"127.0.0.1", "0.0.0.0"}
        or len(ports) == 2
        and addresses == {"0.0.0.0", "::"}
        and ports[0]["HostPort"] == ports[1]["HostPort"]
    ):
        raise Refusal("actual_dev_api_publication_ambiguous_or_unsupported")
    # Docker's host-IP-omitted publication can include one matching IPv6 row.
    # The health route still derives from the positively observed IPv4 binding.
    api_port = next(row["HostPort"] for row in ports if row["HostIp"] != "::")
    path = worker["heartbeat"]
    mounts = [
        mount
        for mount in worker.get("mounts", [])
        if absolute(mount.get("Source", ""))
        and absolute(mount.get("Destination", ""))
        and (path == mount["Destination"] or path.startswith(mount["Destination"] + "/"))
    ]
    if not mounts:
        raise Refusal("normal_worker_heartbeat_host_translation_not_observed")
    longest = max(len(mount["Destination"]) for mount in mounts)
    mounts = [mount for mount in mounts if len(mount["Destination"]) == longest]
    if len(mounts) != 1:
        raise Refusal("ambiguous_worker_heartbeat_backing_mount")
    heartbeat = mounts[0]["Source"] + path[len(mounts[0]["Destination"]) :]
    producer_meta = dependencies.os.stat("/proc/" + worker_pid + "/root" + path)
    host_meta = dependencies.os.stat(heartbeat, follow_symlinks=False)
    if not stat.S_ISREG(host_meta.st_mode) or (producer_meta.st_dev, producer_meta.st_ino) != (
        host_meta.st_dev,
        host_meta.st_ino,
    ):
        raise Refusal("observed_worker_heartbeat_translation_not_same_inode")
    unit_raw = read_dev_unit(command)
    unit = parse_unit(unit_raw, allow_absent=True)
    sdk_path = (
        unit["ExecStart"].split("path=", 1)[1].split(" ;", 1)[0]
        if unit["LoadState"] == "loaded" and "path=" in unit["ExecStart"]
        else "/opt/yggdrasil/bws-deploy-runtime/bin/python3"
    )
    # The absent-unit candidate is the unchanged canonical command selector.
    # It becomes a fact only after actual resolution/stat/read; never provision.
    sdk_realpath = dependencies.os.path.realpath(sdk_path)
    sdk_meta = dependencies.os.stat(sdk_realpath, follow_symlinks=False)
    if (
        not stat.S_ISREG(sdk_meta.st_mode)
        or (sdk_meta.st_uid, sdk_meta.st_gid) != (0, 0)
        or stat.S_IMODE(sdk_meta.st_mode) & 0o022
        or not stat.S_IMODE(sdk_meta.st_mode) & 0o111
    ):
        raise Refusal("existing_normal_dev_sdk_absent_or_unqualified_no_provisioning")
    sdk_digest = sha(read(sdk_realpath, 16_777_216))
    boot_id = read("/proc/sys/kernel/random/boot_id", 128).decode().strip().replace("-", "")
    stat_raw = read("/proc/" + worker_pid + "/stat", 4096).decode()
    stat_fields = stat_raw[stat_raw.rfind(") ") + 2 :].split()
    if len(stat_fields) < 20 or not stat_fields[19].isdigit():
        raise Refusal("observed_worker_start_identity_missing")
    namespace_status = read("/proc/" + worker_pid + "/status", 16384).decode()
    namespace_pid = [
        line.split()[-1] for line in namespace_status.splitlines() if line.startswith("NSpid:")
    ]
    if len(namespace_pid) != 1 or not namespace_pid[0].isdigit():
        raise Refusal("observed_worker_namespace_identity_missing")
    candidate_refs = []
    for role, candidate, pid in (("api", api, str(api["pid"])), ("worker", worker, worker_pid)):
        raw = read("/proc/" + pid + "/stat", 4096).decode()
        fields = raw[raw.rfind(") ") + 2 :].split()
        if len(fields) < 20 or not fields[19].isdigit():
            raise Refusal("candidate_process_start_identity_missing")
        candidate_refs.append(
            (
                role,
                candidate["id"],
                candidate["image_id"],
                candidate.get("revision"),
                pid,
                sha((boot_id + ":" + pid + ":" + fields[19]).encode()),
            )
        )
    return {
        "hostname": hostname,
        "machine_id": read("/etc/machine-id", 128).decode().strip(),
        "boot_id": boot_id,
        "net_namespace": dependencies.os.readlink("/proc/self/ns/net"),
        "unit_raw": unit_raw,
        "source_package": unit["WorkingDirectory"] if unit["LoadState"] == "loaded" else None,
        "sdk": sdk_path,
        "sdk_realpath": sdk_realpath,
        "sdk_sha256": sdk_digest,
        "api_base": "http://127.0.0.1:" + api_port,
        "producer_route": "compose-dev-api-worker:" + api["project"],
        "worker_host_pid": worker_pid,
        "worker_namespace_pid": namespace_pid[0],
        "worker_python": argv[0],
        "worker_uid": dependencies.os.stat("/proc/" + worker_pid, follow_symlinks=False).st_uid,
        "worker_start": sha((boot_id + ":" + worker_pid + ":" + stat_fields[19]).encode()),
        "worker_heartbeat_path": path,
        "heartbeat_host_path": heartbeat,
        "heartbeat_backing": str(host_meta.st_dev) + ":" + str(host_meta.st_ino),
        "candidate_references": tuple(candidate_refs),
        "proposed_vm_id": 100,  # Dated inventory lead only; not observed identity.
        "actual_vm_id": None,
    }


def create_private_native_namespace(
    scope: FrozenNativeScope,
    dependencies: LinuxDependencies,
    caller: Caller,
    program: bytes,
    archive: bytes,
) -> None:
    """Exclusive finite request/program/source input staging; never adopt/replay."""
    if (
        sha(program) != scope.program_sha256
        or len(archive) != ARCHIVE_BYTES
        or sha(archive) != ARCHIVE_SHA256
    ):
        raise Refusal("native_frozen_program_or_source_input_mismatch")
    native_io = LinuxIO(scope, dependencies, caller)
    machine = native_io.read("/etc/machine-id", limit=128).data.decode().strip()
    boot = (
        native_io.read("/proc/sys/kernel/random/boot_id", limit=128, proc=True)
        .data.decode()
        .strip()
        .replace("-", "")
    )
    if (
        machine != scope.machine_id
        or boot != scope.binding.boot_id
        or native_io.link("/proc/self/ns/net") != scope.binding.net_namespace
    ):
        raise Refusal("native_namespace_target_identity_unqualified")
    scope.binding.require(caller)
    parent = native_io.directory("/var/lib")
    root = None
    try:
        dependencies.os.mkdir(PurePosixPath(scope.root).name, 0o700, dir_fd=parent)
        root = dependencies.os.open(
            PurePosixPath(scope.root).name,
            dependencies.os.O_RDONLY
            | dependencies.os.O_DIRECTORY
            | dependencies.os.O_NOFOLLOW
            | dependencies.os.O_CLOEXEC,
            dir_fd=parent,
        )
        info = dependencies.os.fstat(root)
        if (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) != (0, 0, 0o700):
            raise Unknown("exclusive_native_namespace_metadata_unknown")
        for name, content in (
            ("request.json", scope.request_bytes),
            ("program.py", program),
            ("source.tar", archive),
            ("manifest.json", scope.manifest),
        ):
            caller.check(len(content))
            descriptor = dependencies.os.open(
                name,
                dependencies.os.O_WRONLY
                | dependencies.os.O_CREAT
                | dependencies.os.O_EXCL
                | dependencies.os.O_NOFOLLOW
                | dependencies.os.O_CLOEXEC,
                0o600,
                dir_fd=root,
            )
            try:
                dependencies.os.fchmod(descriptor, 0o600)
                pending = memoryview(content)
                while pending:
                    caller.check()
                    count = dependencies.os.write(descriptor, pending[:65536])
                    if count <= 0:
                        raise Unknown("native_namespace_write_unconfirmed")
                    pending = pending[count:]
                dependencies.os.fsync(descriptor)
            finally:
                caller.close("native_namespace_file", lambda: dependencies.os.close(descriptor))
        dependencies.os.fsync(root)
        dependencies.os.fsync(parent)
    except FileExistsError:
        raise Refusal("original_native_namespace_exists_no_replay") from None
    except BaseException:
        caller.unknown("native_namespace_creation_or_close_unknown")
        raise
    finally:
        if root is not None:
            caller.close("native_namespace", lambda: dependencies.os.close(root))
        caller.close("native_namespace_parent", lambda: dependencies.os.close(parent))


def supervise_fixed_native_worker(scope: FrozenNativeScope, caller: Caller) -> dict[str, str]:
    """One launch + one positive incarnation read, never active-handle polling."""
    caller.run(supervisor_command(scope), effect=True)
    argv = (
        "/usr/bin/systemctl",
        "show",
        "yggdrasil-dev-probe-" + scope.handle.operation + ".service",
        "--property=ActiveState,SubState,MainPID,InvocationID,ControlGroup,Transient,Restart,KillMode,RuntimeMaxUSec,TimeoutStopUSec,ExecStart,WorkingDirectory",
        "--all",
        "--no-pager",
    )
    raw = caller.command.safe(list(argv), timeout=min(5.0, caller.check() - 2.1), limit=16384)
    caller.check(len(raw.encode()))
    fields = systemctl_fields(raw, tuple(argv[3].removeprefix("--property=").split(",")))
    expected_argv = (
        scope.binding.sdk
        + " -I "
        + scope.root
        + "/program.py --fixed-dev-worker "
        + scope.handle.operation
    )
    if (
        fields.get("ActiveState") != "active"
        or fields.get("SubState") != "running"
        or not fields.get("MainPID", "").isdigit()
        or int(fields["MainPID"]) < 1
        or not identifier(fields.get("InvocationID", ""))
        or fields.get("Transient") != "yes"
        or fields.get("Restart") != "no"
        or fields.get("KillMode") != "control-group"
        or fields.get("WorkingDirectory") != scope.root
        or ("argv[]=" + expected_argv + " ;") not in fields.get("ExecStart", "")
    ):
        caller.unknown("native_supervisor_start_incarnation_unconfirmed")
        raise Unknown("native_supervisor_start_incarnation_unconfirmed")
    return {
        "original_handle_sha256": scope.handle.fingerprint,
        "unit": "yggdrasil-dev-probe-" + scope.handle.operation + ".service",
        "invocation": fields["InvocationID"],
        "pid": fields["MainPID"],
        "cgroup": fields["ControlGroup"],
    }


def assert_local_authority(
    scope: FrozenNativeScope,
    *,
    issue: bytes,
    task: bytes,
    git_head: bytes,
    git_status: bytes,
    expected_head: str,
    epoch_seconds: float,
) -> None:
    """Parse real bounded GitHub/normal-dispatcher/Git outputs before transport."""
    from datetime import datetime

    issue_value = json.loads(issue, object_pairs_hook=unique)
    task_value = json.loads(task, object_pairs_hook=unique)
    labels = {
        item["name"] if isinstance(item, dict) else item for item in issue_value.get("labels", [])
    }
    record = task_value.get("task", {})
    expiry = datetime.fromisoformat(
        record.get("lease_expires_at", "").replace("Z", "+00:00")
    ).timestamp()
    if (
        issue_value.get("number") != 6505
        or issue_value.get("state") != "open"
        or "agent:in-progress" not in labels
        or "agent:ready" in labels
    ):
        raise Refusal("fixed_dev_issue_not_currently_claimed")
    if (
        task_value.get("ok") is not True
        or record.get("issue_number") != 6505
        or record.get("status") != "claimed"
        or record.get("claimed_by") != scope.claim_holder
        or record.get("lease_id") != scope.lease_id
        or not expiry > epoch_seconds
    ):
        raise Refusal("normal_original_issue_lease_missing_expired_or_foreign")
    if (
        git_status.strip()
        or git_head.decode("ascii").strip() != expected_head
        or not re.fullmatch(r"[0-9a-f]{40}", expected_head)
    ):
        raise Refusal("caller_current_clean_source_head_unqualified")


class FixedDevTransport:
    """One bounded original-handle submission; no automatic reconnect/replay."""

    def __init__(self, scope: FrozenNativeScope, command: NativeCommand):
        self.scope, self.command, self.submitted = scope, command, False

    def submit(
        self, program: bytes, *, timeout: float, authority_read: Callable[[], None]
    ) -> bytes:
        if self.submitted or sha(program) != self.scope.program_sha256:
            raise Refusal("original_dev_submission_replay_or_program_drift")
        authority_read()  # Root's normal live claim/Git/registry read, inside budget.
        remaining = self.scope.binding.window_end - self.command.dependencies.time.monotonic()
        if not 2.1 < timeout <= remaining:
            raise Refusal("whole_transport_window_or_cleanup_reserve")
        self.submitted = True
        # The carrier can be reviewed as assembled bytes. Its entry stays the
        # unconditional refusal until Root adopts/reviews/enables that boundary.
        payload = program + b"\nnative_entry()\n"
        try:
            result = self.command.bounded(
                list(strict_dev_transport(self.scope)),
                timeout=timeout - 2.1,
                limit=131072,
                environment={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C"},
                input_bytes=payload,
            )
            if result.returncode != 0 or result.stderr or len(result.stdout) > 131072:
                raise Unknown("original_dev_transport_exit_unconfirmed")
            return result.stdout
        except BaseException:
            raise Unknown("original_dev_transport_lost_no_replay") from None


LOCAL_DEV_WORKTREE = "/Users/rasmus/.codex/worktrees/probe-dev-acceptance/agentic-pkm-mvp"
LOCAL_DEV_BRANCH = "codex/issue-6505-dev-probe-acceptance"
LOCAL_DEV_HOLDER = "codex-probe-dev-6505-astra"
LOCAL_DEV_SESSION = "codex-6505-astra-owner-20261031"
LOCAL_DEV_TASK = "github-RasmusTho--agentic-pkm-mvp-issue-6505"
LOCAL_DEV_PROGRAM = LOCAL_DEV_WORKTREE + "/scripts/probe_dev_outage_operation.py"


def actual_local_entry(
    packet: dict[str, Any], dependencies: LinuxDependencies
) -> tuple[bytes, tuple[Any, ...]]:
    """Bind the executing entry, cwd and interpreter before using its claim.

    The registry's logical Issue session remains the ownership authority. An
    inherited chat-id environment value grants no authority and is not a gate.
    """
    api = dependencies.os
    if (
        api.getcwd() != LOCAL_DEV_WORKTREE
        or api.path.realpath(__file__) != LOCAL_DEV_PROGRAM
        or api.path.realpath(LOCAL_DEV_PROGRAM) != LOCAL_DEV_PROGRAM
        or not absolute(dependencies.process.executable)
        or api.path.realpath(dependencies.process.executable)
        != api.path.realpath(packet["caller_interpreter"])
        or run_claimed_local_caller.__code__.co_filename != __file__
    ):
        raise Refusal("actual_local_caller_entry_cwd_or_interpreter_unbound")
    executable = api.path.realpath(dependencies.process.executable)
    interpreter = api.stat(executable, follow_symlinks=False)
    if (
        not stat.S_ISREG(interpreter.st_mode)
        or interpreter.st_mode & 0o022
        or not interpreter.st_mode & 0o111
        or interpreter.st_uid not in {0, api.geteuid()}
    ):
        raise Refusal("actual_local_caller_interpreter_metadata_unqualified")
    descriptor = api.open(
        LOCAL_DEV_PROGRAM, api.O_RDONLY | api.O_NOFOLLOW | api.O_NONBLOCK | api.O_CLOEXEC
    )
    try:
        info = api.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or not 0 < info.st_size <= 1048576
            or info.st_nlink != 1
            or info.st_uid != api.geteuid()
            or info.st_mode & 0o022
        ):
            raise Refusal("actual_local_caller_program_metadata_unqualified")
        content = bytearray()
        while True:
            if packet["_end_epoch"] - dependencies.time.time() <= 2.1:
                raise Unknown("whole_local_caller_entry_budget")
            chunk = api.read(descriptor, min(65536, 1048577 - len(content)))
            if not chunk:
                break
            content.extend(chunk)
            if len(content) > 1048576:
                raise Refusal("actual_local_caller_program_bound")
        current = api.stat(LOCAL_DEV_PROGRAM, follow_symlinks=False)
        after = api.fstat(descriptor)
        fields = (
            "st_dev",
            "st_ino",
            "st_mode",
            "st_uid",
            "st_gid",
            "st_nlink",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
        )
        if len(content) != info.st_size or any(
            getattr(info, key) != getattr(current, key) or getattr(info, key) != getattr(after, key)
            for key in fields
        ):
            raise Refusal("actual_local_caller_program_changed_during_read")
        if sha(bytes(content)) != packet["program_sha256"]:
            raise Refusal("actual_local_caller_program_not_reviewed_bytes")
        compiled = compile(bytes(content), __file__, "exec", dont_inherit=True)
        for function in (actual_local_entry, run_claimed_local_caller, native_entry, main):
            candidates = [
                value
                for value in compiled.co_consts
                if isinstance(value, type(function.__code__)) and value.co_name == function.__name__
            ]
            if len(candidates) != 1 or candidates[0] != function.__code__:
                raise Refusal("executing_local_entry_differs_from_reviewed_program")
        return bytes(content), (
            *(getattr(info, key) for key in fields),
            executable,
            *(getattr(interpreter, key) for key in fields),
        )
    finally:
        api.close(descriptor)


def carrier_packet(raw: bytes) -> dict[str, Any]:
    """Finite caller interface; it contains no pre-known SDK/worker/endpoint."""
    if len(raw) > 65536:
        raise Refusal("carrier_packet_bound")
    value = json.loads(raw, object_pairs_hook=unique)
    required = {
        "schema",
        "issue",
        "operation",
        "namespace",
        "reviewed_head",
        "program_sha256",
        "issue_body_sha256",
        "lease_id",
        "keeper_standing_reference",
        "window_start_utc",
        "window_end_utc",
        "bootstrap_interpreter",
        "local_fence_references",
        "normal_interval_seconds",
        "heartbeat_stale_seconds",
        "gh_executable",
        "caller_interpreter",
    }
    if (
        not isinstance(value, dict)
        or set(value) != required
        or value["schema"] != "fixed_dev_probe.carrier.v1"
        or value["issue"] != 6505
    ):
        raise Refusal("carrier_packet_shape")
    if (
        not identifier(value["operation"])
        or not identifier(value["namespace"])
        or not re.fullmatch(r"[0-9a-f]{40}", value["reviewed_head"] or "")
        or not identifier(value["program_sha256"], 64)
        or not identifier(value["issue_body_sha256"], 64)
    ):
        raise Refusal("carrier_reviewed_identity_unbound")
    if (
        value["bootstrap_interpreter"]
        not in {"/usr/bin/python3", "/usr/bin/python3.12", "/usr/bin/python3.13"}
        or not value["lease_id"]
        or not value["keeper_standing_reference"]
    ):
        raise Refusal("carrier_bootstrap_or_existing_authority_unbound")
    if (
        not absolute(value["gh_executable"])
        or PurePosixPath(value["gh_executable"]).name != "gh"
        or not absolute(value["caller_interpreter"])
    ):
        raise Refusal("absolute_existing_caller_tools_unbound")
    from datetime import datetime

    start = datetime.fromisoformat(value["window_start_utc"].replace("Z", "+00:00")).timestamp()
    end = datetime.fromisoformat(value["window_end_utc"].replace("Z", "+00:00")).timestamp()
    if (
        not 0 < end - start <= 1800
        or type(value["normal_interval_seconds"]) is not int
        or not 1 <= value["normal_interval_seconds"] <= 300
        or type(value["heartbeat_stale_seconds"]) not in {int, float}
        or not math.isfinite(value["heartbeat_stale_seconds"])
        or value["heartbeat_stale_seconds"] <= 0
    ):
        raise Refusal("carrier_window_or_normal_probe_policy")
    value["_start_epoch"], value["_end_epoch"] = start, end
    return value


def scope_from_first_preflight(
    packet: dict[str, Any],
    facts: dict[str, Any],
    dependencies: LinuxDependencies,
    manifest: bytes,
    controller_source: bytes,
    probe_source: bytes,
) -> tuple[FrozenNativeScope, bytes]:
    """Freeze actual observations INSIDE the accepted supervised first preflight."""
    now, mono = dependencies.time.time(), dependencies.time.monotonic()
    if not packet["_start_epoch"] <= now < packet["_end_epoch"]:
        raise Refusal("accepted_keeper_window_not_current")
    unit = parse_unit(facts["unit_raw"], allow_absent=True)
    root = "/var/lib/ygg-dev-probe-" + packet["namespace"]
    config_path = "/etc/yggdrasil/host-probe/dev.env"
    state_file = "/var/lib/yggdrasil-host-probe-dev/alert-state.json"
    package = facts["source_package"] or root + "/source"
    controller = "/root/.local/state/yggdrasil/secret-controller"
    if unit["LoadState"] == "loaded":
        envfiles = unit["EnvironmentFiles"].replace(" ", "")
        if not envfiles.endswith("(ignore_errors=no)") or envfiles.count("(ignore_errors=no)") != 1:
            raise Refusal("one_explicit_normal_dev_config_required")
        config_path = envfiles.removesuffix("(ignore_errors=no)")
        if config_path != "/etc/yggdrasil/host-probe/dev.env":
            raise Refusal("unsupported_custom_original_dev_config")
        controller_paths = unit["ReadWritePaths"].split()
        if controller_paths != [controller]:
            raise Refusal("unsupported_custom_controller_owner_profile")
    credential = "/var/lib/yggdrasil/bws-tokens/dev/current"
    credential_resolved = dependencies.os.path.realpath(credential)

    def read_owned(path: str, limit=65536) -> FileState:
        descriptor = dependencies.os.open(
            path,
            dependencies.os.O_RDONLY
            | dependencies.os.O_NOFOLLOW
            | dependencies.os.O_NONBLOCK
            | dependencies.os.O_CLOEXEC,
        )
        try:
            info = dependencies.os.fstat(descriptor)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != 0
                or info.st_nlink != 1
                or info.st_size > limit
            ):
                raise Refusal("first_preflight_nonsecret_file_metadata")
            chunks = bytearray()
            while True:
                if dependencies.time.time() >= packet["_end_epoch"]:
                    raise Unknown("first_preflight_window_exhausted")
                block = dependencies.os.read(descriptor, min(16384, limit + 1 - len(chunks)))
                if not block:
                    break
                chunks.extend(block)
                if len(chunks) > limit:
                    raise Unknown("first_preflight_file_bound")
            return FileState(
                bytes(chunks),
                info.st_dev,
                info.st_ino,
                stat.S_IMODE(info.st_mode),
                info.st_uid,
                info.st_gid,
                info.st_nlink,
                info.st_mtime_ns,
                info.st_ctime_ns,
            )
        finally:
            dependencies.os.close(descriptor)

    deploy = read_owned("/etc/yggdrasil/bws-deploy/dev.json")
    if deploy.mode != 0o600:
        raise Refusal("existing_dev_reader_metadata")
    identifiers = json.loads(deploy.data, object_pairs_hook=unique)
    project = identifiers.get("project_id")
    if not isinstance(project, str) or not project:
        raise Refusal("existing_normal_dev_project_identifier_missing")
    protected = []
    if unit["LoadState"] == "loaded":
        config = read_owned(config_path)
        existing = parse_config(config.data)
        if existing["PROBE_ENVIRONMENT"] != "dev":
            raise Refusal("existing_config_not_dev")
        state_file = existing["PROBE_STATE_FILE"]
        if state_file != "/var/lib/yggdrasil-host-probe-dev/alert-state.json":
            raise Refusal("unsupported_custom_dev_state_owner_path")
        template = read_owned(unit["FragmentPath"], 16384)
        protected.append(
            ("shared_dev_host", unit["FragmentPath"], template.content_sha256, template.mode)
        )
        # Protect original package bytes without any PROD-host observer.
        for relative in json.loads(manifest)["files"]:
            original = read_owned(package + "/" + relative, 1048576)
            protected.append(
                (
                    "shared_dev_host",
                    package + "/" + relative,
                    original.content_sha256,
                    original.mode,
                )
            )
    if unit["ActiveState"] != "active":
        # Temporary probe state stays inside this operation's existing writable
        # namespace. Canonical DEV state remains untouched under read-only /var/lib.
        state_file = root + "/probe-state/alert-state.json"
    binding = Binding(
        "ygg-dev",
        "ygg-dev",
        packet["keeper_standing_reference"],
        "Product Runtime DEV",
        mono,
        mono + (packet["_end_epoch"] - now),
        facts["boot_id"],
        facts["net_namespace"],
        facts["producer_route"],
        package,
        facts["sdk"],
        facts["sdk_realpath"],
        config_path,
        state_file,
        facts["heartbeat_host_path"],
        facts["heartbeat_backing"],
        facts["worker_host_pid"],
        facts["worker_start"],
        facts["api_base"],
        5.0,
    )
    scope = FrozenNativeScope(
        binding,
        Handle(packet["operation"], "ygg-dev", "ygg-dev"),
        packet["namespace"],
        facts["machine_id"],
        LOCAL_DEV_HOLDER,
        packet["lease_id"],
        packet["program_sha256"],
        manifest,
        controller_source,
        probe_source,
        controller,
        credential,
        credential_resolved,
        project,
        facts["worker_python"],
        facts["worker_uid"],
        tuple(protected),
        tuple(tuple(row) for row in packet["local_fence_references"]),
        tuple(facts["candidate_references"]),
    )
    config = (
        "PROBE_ENVIRONMENT=dev\nPROBE_ALERT_CHANNEL=discord\nPROBE_BASE_URL="
        + binding.api_base
        + "\nWORKER_HEARTBEAT_PATH="
        + binding.heartbeat
        + "\nPROBE_STATE_FILE="
        + state_file
        + "\nPROBE_INTERVAL_SECONDS="
        + str(packet["normal_interval_seconds"])
        + "\nWORKER_HEARTBEAT_STALE_SECONDS="
        + str(packet["heartbeat_stale_seconds"])
        + "\n"
    ).encode()
    return scope, config


def run_claimed_local_caller(
    packet_raw: bytes,
    dependencies: LinuxDependencies,
    custody_source: str,
    archive: bytes,
    manifest: bytes,
) -> bytes:
    """The exact #6505 source/claim-bound caller; no writes to GitHub."""
    import base64

    packet = carrier_packet(packet_raw)
    local_program, original_entry = actual_local_entry(packet, dependencies)
    if sha(archive) != ARCHIVE_SHA256 or sha(manifest) != MANIFEST_SHA256:
        raise Refusal("caller_live_archive_identity")
    # Reuse exact accepted primitives with no PROD resource imports/globals.
    selected = {}
    for node in ast.parse(custody_source).body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in {
            "OperationFailure",
            "_bounded_process",
            "_safe_command",
        }:
            selected[node.name] = (
                "\n".join(custody_source.splitlines()[node.lineno - 1 : node.end_lineno]) + "\n"
            )
    if (
        set(selected) != {"OperationFailure", "_bounded_process", "_safe_command"}
        or sha(selected["_bounded_process"].encode()) != CUSTODY_SHA256
    ):
        raise Refusal("caller_custody_source")
    namespace = {
        name: getattr(dependencies, name)
        for name in ("os", "subprocess", "selectors", "signal", "time")
    }
    exec(
        "from __future__ import annotations\n"
        + "\n".join(
            selected[key] for key in ("OperationFailure", "_bounded_process", "_safe_command")
        ),
        namespace,
    )

    def command(argv, limit=1048576):
        remaining = packet["_end_epoch"] - dependencies.time.time() - 2.1
        if remaining <= 0:
            raise Unknown("whole_local_caller_window_exhausted")
        environment = {
            "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
            "LC_ALL": "C",
            "PYTHONPATH": LOCAL_DEV_WORKTREE,
        }
        for key in ("HOME", "SSH_AUTH_SOCK"):
            if key in dependencies.os.environ:
                environment[key] = dependencies.os.environ[key]
        result = namespace["_bounded_process"](
            list(argv), timeout=min(15.0, remaining), limit=limit, environment=environment
        )
        if result.returncode or result.stderr:
            raise Refusal("qualified_local_command_result")
        return result.stdout

    def git(*args):
        return command(("/usr/bin/git", "-C", LOCAL_DEV_WORKTREE, *args))

    head, status = git("rev-parse", "HEAD"), git("status", "--porcelain")
    if (
        git("branch", "--show-current").decode().strip() != LOCAL_DEV_BRANCH
        or git("rev-parse", "--show-toplevel").decode().strip() != LOCAL_DEV_WORKTREE
    ):
        raise Refusal("registered_exact_dev_worktree_or_branch_changed")
    program = git("show", "HEAD:scripts/probe_dev_outage_operation.py")
    if (
        program != local_program
        or sha(program) != packet["program_sha256"]
        or head.decode().strip() != packet["reviewed_head"]
    ):
        raise Refusal("reviewed_current_assembled_program_changed")
    for executable in (packet["gh_executable"], packet["caller_interpreter"]):
        meta = dependencies.os.stat(executable)
        if (
            not stat.S_ISREG(meta.st_mode)
            or meta.st_mode & 0o022
            or not meta.st_mode & 0o111
            or meta.st_uid not in {0, dependencies.os.geteuid()}
        ):
            raise Refusal("caller_tool_metadata_unqualified")
    issue = command(
        (
            packet["gh_executable"],
            "api",
            "--method",
            "GET",
            "repos/RasmusTho/agentic-pkm-mvp/issues/6505",
        )
    )
    dispatcher_code = (
        "import os,runpy;os.chdir("
        + repr(LOCAL_DEV_WORKTREE)
        + ");runpy.run_module('app.dispatcher',run_name='__main__')"
    )
    task = command(
        (
            packet["caller_interpreter"],
            "-c",
            dispatcher_code,
            "show",
            LOCAL_DEV_TASK,
            "--events",
            "--json",
        )
    )
    registry_code = (
        "import json;from pathlib import Path;from scripts.agent_worktree import load_lifecycle_authority;"
        + "print(json.dumps(load_lifecycle_authority(Path("
        + repr(LOCAL_DEV_WORKTREE)
        + "),candidate_branch="
        + repr(LOCAL_DEV_BRANCH)
        + ")))"
    )
    registry = json.loads(
        command((packet["caller_interpreter"], "-c", registry_code)), object_pairs_hook=unique
    )
    issue_value = json.loads(issue, object_pairs_hook=unique)
    if sha(issue_value.get("body", "").encode()) != packet["issue_body_sha256"]:
        raise Refusal("reviewed_issue_contract_changed")
    # A minimal post-discovery scope is not fabricated locally. Validate the
    # exact existing claim fields here using the same normal output grammar.
    task_response = json.loads(task, object_pairs_hook=unique)
    task_value = task_response.get("task", {})
    lease = task_response.get("lease", {})
    from datetime import datetime

    expiry = datetime.fromisoformat(
        task_value.get("lease_expires_at", "").replace("Z", "+00:00")
    ).timestamp()
    lease_expiry = datetime.fromisoformat(
        lease.get("expires_at", "").replace("Z", "+00:00")
    ).timestamp()
    active = [row for row in registry.values() if row.get("status") == "active"]
    owner = active[0] if len(active) == 1 else {}
    labels = {
        item["name"] if isinstance(item, dict) else item for item in issue_value.get("labels", [])
    }
    if (
        issue_value.get("number") != 6505
        or issue_value.get("state") != "open"
        or {label for label in labels if label.startswith("agent:")} != {"agent:in-progress"}
        or task_response.get("ok") is not True
        or task_value.get("task_id") != LOCAL_DEV_TASK
        or task_value.get("repo") != "RasmusTho/agentic-pkm-mvp"
        or task_value.get("issue_number") != 6505
        or task_value.get("status") != "claimed"
        or task_value.get("claimed_by") != LOCAL_DEV_HOLDER
        or task_value.get("lease_id") != packet["lease_id"]
        or expiry <= dependencies.time.time()
        or lease.get("lease_id") != packet["lease_id"]
        or lease.get("resource") != "issue:6505"
        or lease.get("holder") != LOCAL_DEV_HOLDER
        or "released_at" not in lease
        or lease["released_at"] is not None
        or lease_expiry != expiry
        or owner.get("path") != LOCAL_DEV_WORKTREE
        or owner.get("branch") != LOCAL_DEV_BRANCH
        or owner.get("owner") != LOCAL_DEV_SESSION
        or not identifier(owner.get("generation", ""))
        or type(owner.get("expires_at")) not in {int, float}
        or not math.isfinite(owner["expires_at"])
        or owner["expires_at"] <= dependencies.time.time()
        or status.strip()
    ):
        raise Refusal("current_normal_6505_claim_or_clean_source_missing")
    now = dependencies.time.time()
    if not packet["_start_epoch"] <= now < packet["_end_epoch"]:
        raise Refusal("keeper_window_not_accepted_current")
    envelope = {
        "packet": {key: value for key, value in packet.items() if not key.startswith("_")},
        "program": base64.b64encode(program).decode(),
        "archive": base64.b64encode(archive).decode(),
        "manifest": base64.b64encode(manifest).decode(),
        "custody_source": "\n".join(
            selected[key] for key in ("OperationFailure", "_bounded_process", "_safe_command")
        ),
    }
    payload = (
        "import base64,json,types,sys\ne=json.loads("
        + repr(json.dumps(envelope, separators=(",", ":")))
        + ")\n"
        "m=types.ModuleType('fixed_dev_program');m.__file__='reviewed-dev-program.py';sys.modules[m.__name__]=m;exec(base64.b64decode(e['program']),m.__dict__);r=m.native_entry('remote-launch',e);sys.stdout.write(json.dumps(r,separators=(',',':')))\n"
    ).encode()
    argv = (
        "/usr/bin/ssh",
        "-T",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        "ConnectTimeout=10",
        "-o",
        "ConnectionAttempts=1",
        "-o",
        "ClearAllForwardings=yes",
        "-o",
        "ForwardAgent=no",
        "-o",
        "ControlMaster=no",
        "-o",
        "ControlPath=none",
        "-o",
        "PermitLocalCommand=no",
        "--",
        "ygg-dev",
        "sudo",
        "-n",
        packet["bootstrap_interpreter"],
        "-I",
        "-",
    )
    environment = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C"}
    for key in ("HOME", "SSH_AUTH_SOCK"):
        if key in dependencies.os.environ:
            environment[key] = dependencies.os.environ[key]
    if (
        actual_local_entry(packet, dependencies) != (program, original_entry)
        or git("rev-parse", "HEAD") != head
        or git("status", "--porcelain").strip()
        or dependencies.time.time() >= min(expiry, owner["expires_at"])
    ):
        raise Refusal("actual_caller_or_candidate_changed_before_transport")
    # Single original submission; caller never retries a lost acknowledgement.
    remaining = packet["_end_epoch"] - dependencies.time.time() - 2.1
    if remaining <= 0:
        raise Unknown("whole_caller_transport_reserve")
    try:
        result = namespace["_bounded_process"](
            list(argv),
            timeout=remaining,
            limit=131072,
            environment=environment,
            input_bytes=payload,
        )
        if result.returncode or result.stderr:
            raise Unknown("original_remote_submission_result_unknown")
        return result.stdout
    except BaseException:
        raise Unknown("original_remote_submission_lost_no_replay") from None


class BootstrapBudget:
    """The same accepted UTC window bounds bootstrap before facts are frozen."""

    def __init__(self, packet: dict[str, Any], dependencies: LinuxDependencies):
        self.packet, self.dependencies, self.bytes, self.reasons = packet, dependencies, 0, []

    def check(self, count: int = 0) -> float:
        self.bytes += count
        remaining = self.packet["_end_epoch"] - self.dependencies.time.time()
        if (
            self.reasons
            or not self.packet["_start_epoch"] <= self.dependencies.time.time()
            or remaining <= 2.1
            or self.bytes > 16777216
        ):
            raise Unknown("whole_bootstrap_window_allocation_or_close_unknown")
        return remaining

    def unknown(self, reason: str) -> None:
        self.reasons.append(reason)

    def close(self, label: str, function: Callable[[], Any]) -> None:
        try:
            function()
        except BaseException:
            self.unknown(label + "_close_unknown")


def _bootstrap_directory(
    path: str, dependencies: LinuxDependencies, budget: BootstrapBudget
) -> int:
    if not absolute(path):
        raise Refusal("bootstrap_directory_alias")
    api = dependencies.os
    descriptor = api.open("/", api.O_RDONLY | api.O_DIRECTORY | api.O_CLOEXEC)
    try:
        for part in PurePosixPath(path).parts[1:]:
            budget.check()
            child = api.open(
                part,
                api.O_RDONLY | api.O_DIRECTORY | api.O_NOFOLLOW | api.O_CLOEXEC,
                dir_fd=descriptor,
            )
            budget.close("bootstrap_parent", lambda: api.close(descriptor))
            descriptor = child
            info = api.fstat(descriptor)
            if (info.st_uid, info.st_gid) != (0, 0) or stat.S_IMODE(info.st_mode) & 0o022:
                raise Refusal("bootstrap_owner_or_parent_write_domain")
        return descriptor
    except BaseException:
        budget.close("bootstrap_directory", lambda: api.close(descriptor))
        raise


def _write_bootstrap_file(
    root: int, name: str, data: bytes, dependencies: LinuxDependencies, budget: BootstrapBudget
) -> None:
    if re.fullmatch(r"[a-z-]+\.(?:json|py|tar)", name) is None:
        raise Refusal("bootstrap_file_outside_fixed_packet")
    budget.check(len(data))
    api = dependencies.os
    descriptor = api.open(
        name,
        api.O_WRONLY | api.O_CREAT | api.O_EXCL | api.O_NOFOLLOW | api.O_CLOEXEC,
        0o600,
        dir_fd=root,
    )
    try:
        api.fchmod(descriptor, 0o600)
        pending = memoryview(data)
        while pending:
            budget.check()
            written = api.write(descriptor, pending[:65536])
            if written <= 0:
                raise Unknown("bootstrap_file_write_unknown")
            pending = pending[written:]
        api.fsync(descriptor)
    finally:
        budget.close("bootstrap_file", lambda: api.close(descriptor))


def _scope_json(scope: FrozenNativeScope, config: bytes, custody_source: str) -> bytes:
    import base64

    value = asdict(scope)
    for key in ("manifest", "controller_source", "probe_source"):
        value[key] = base64.b64encode(value[key]).decode()
    return json.dumps(
        {
            "scope": value,
            "healthy_config": base64.b64encode(config).decode(),
            "custody_source": custody_source,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def _bootstrap_read(
    path: str,
    dependencies: LinuxDependencies,
    budget: BootstrapBudget,
    *,
    limit: int,
    private: bool = False,
) -> bytes:
    api = dependencies.os
    budget.check()
    descriptor = api.open(path, api.O_RDONLY | api.O_NOFOLLOW | api.O_NONBLOCK | api.O_CLOEXEC)
    try:
        info = api.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != 0
            or info.st_nlink != 1
            or (private and (info.st_gid != 0 or stat.S_IMODE(info.st_mode) != 0o600))
        ):
            raise Refusal("bootstrap_read_metadata_unqualified")
        result = bytearray()
        while True:
            budget.check()
            chunk = api.read(descriptor, min(65536, limit + 1 - len(result)))
            if not chunk:
                return bytes(result)
            result.extend(chunk)
            budget.check(len(chunk))
            if len(result) > limit:
                raise Unknown("bootstrap_read_bound")
    finally:
        budget.close("bootstrap_read", lambda: api.close(descriptor))


def _bootstrap_guest(dependencies: LinuxDependencies, budget: BootstrapBudget) -> dict[str, str]:
    """Read-only target qualification before any namespace or systemd write."""
    guest = (
        _bootstrap_read("/proc/sys/kernel/hostname", dependencies, budget, limit=256)
        .decode()
        .strip()
    )
    if guest != "ygg-dev":
        raise Refusal("bootstrap_guest_not_fixed_dev")
    machine = _bootstrap_read("/etc/machine-id", dependencies, budget, limit=128).decode().strip()
    boot = (
        _bootstrap_read("/proc/sys/kernel/random/boot_id", dependencies, budget, limit=128)
        .decode()
        .strip()
        .replace("-", "")
    )
    if not identifier(machine) or not identifier(boot):
        raise Refusal("bootstrap_machine_or_boot_unqualified")
    network = dependencies.os.readlink("/proc/self/ns/net")
    if re.fullmatch(r"net:\[[0-9]+\]", network) is None:
        raise Refusal("bootstrap_network_namespace_unqualified")
    budget.check()
    return {"hostname": guest, "machine_id": machine, "boot_id": boot, "net_namespace": network}


def _bootstrap_commands(dependencies: LinuxDependencies, source: str) -> dict[str, Any]:
    selected = {}
    for node in ast.parse(source).body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in {
            "OperationFailure",
            "_bounded_process",
            "_safe_command",
        }:
            selected[node.name] = (
                "\n".join(source.splitlines()[node.lineno - 1 : node.end_lineno]) + "\n"
            )
    if (
        set(selected) != {"OperationFailure", "_bounded_process", "_safe_command"}
        or sha(selected["_bounded_process"].encode()) != CUSTODY_SHA256
    ):
        raise Refusal("remote_custody_program")
    namespace = {
        key: getattr(dependencies, key)
        for key in ("os", "subprocess", "selectors", "signal", "time")
    }
    exec(
        "from __future__ import annotations\n"
        + "\n".join(
            selected[key] for key in ("OperationFailure", "_bounded_process", "_safe_command")
        ),
        namespace,
    )
    return namespace


def _failure_reason(error: BaseException) -> str:
    reason = (
        str(error) if isinstance(error, (Refusal, Unknown)) else "unqualified_operation_failure"
    )
    return (
        reason
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,127}", reason)
        else "unqualified_operation_failure"
    )


def _failure_outcome(packet: dict[str, Any], phase: str, error: BaseException) -> dict[str, Any]:
    return {
        "schema": "fixed_dev_probe.outcome.v1",
        "status": "REFUSED" if isinstance(error, Refusal) else "UNKNOWN",
        "operation": packet["operation"],
        "original_handle_sha256": Handle(packet["operation"], "ygg-dev", "ygg-dev").fingerprint,
        "phase": phase,
        "reason": _failure_reason(error),
        "live_acceptance": False,
        "program_sha256": packet["program_sha256"],
    }


def _supervisor_start(
    envelope: dict[str, Any], dependencies: LinuxDependencies, budget: BootstrapBudget
) -> dict[str, str]:
    packet = budget.packet
    unit = "yggdrasil-dev-probe-" + packet["operation"] + ".service"
    command = _bootstrap_commands(dependencies, envelope["custody_source"])["_safe_command"]
    raw = command(
        list(supervisor_show(packet["operation"])),
        timeout=min(5.0, budget.check() - 2.1),
        limit=16384,
    )
    fields = systemctl_fields(raw, SUPERVISOR_SHOW_KEYS)
    root = "/var/lib/ygg-dev-probe-" + packet["namespace"]
    expected = (
        packet["bootstrap_interpreter"]
        + " -I "
        + root
        + "/program.py --supervised-first-preflight "
        + packet["operation"]
    )
    if (
        fields.get("Id") != unit
        or fields.get("ActiveState") != "active"
        or fields.get("SubState") != "running"
        or fields.get("MainPID") != str(dependencies.os.getpid())
        or not identifier(fields.get("InvocationID"))
        or fields.get("ControlGroup") != "/system.slice/" + unit
        or fields.get("WorkingDirectory") != root
        or fields.get("KillMode") != "control-group"
        or fields.get("Restart") != "no"
        or configured_exec(fields.get("ExecStart", ""))
        != configured_exec(
            "{ path="
            + packet["bootstrap_interpreter"]
            + " ; argv[]="
            + expected
            + " ; ignore_errors=no ; }"
        )
        or finite_stop_seconds(fields) > 5
    ):
        raise Refusal("original_hard_supervisor_identity_unqualified")
    identity = _bootstrap_guest(dependencies, budget)
    if identity != envelope.get("bootstrap_identity"):
        raise Refusal("bootstrap_guest_identity_changed_before_preflight")
    return {
        "operation": packet["operation"],
        "program_sha256": packet["program_sha256"],
        "unit": unit,
        "invocation": fields["InvocationID"],
        "pid": fields["MainPID"],
        "cgroup": fields["ControlGroup"],
        "boot_id": identity["boot_id"],
        "profile": {key: fields[key] for key in SUPERVISOR_PROFILE_KEYS},
    }


def _decode_scope(raw: bytes) -> tuple[FrozenNativeScope, bytes, str]:
    import base64

    data = json.loads(raw, object_pairs_hook=unique)
    value = data["scope"]
    for key in ("manifest", "controller_source", "probe_source"):
        value[key] = base64.b64decode(value[key], validate=True)
    value["binding"], value["handle"] = Binding(**value["binding"]), Handle(**value["handle"])
    for key in ("protected_files", "local_fence_references", "candidate_references"):
        value[key] = tuple(tuple(row) for row in value[key])
    return (
        FrozenNativeScope(**value),
        base64.b64decode(data["healthy_config"], validate=True),
        data["custody_source"],
    )


def remote_launch(envelope: dict[str, Any], dependencies: LinuxDependencies) -> dict[str, Any]:
    """One hard supervisor contains FIRST preflight, discovery, SDK exec and drill."""
    import base64

    packet = carrier_packet(json.dumps(envelope["packet"]).encode())
    budget = BootstrapBudget(packet, dependencies)
    budget.check()
    program = base64.b64decode(envelope["program"], validate=True)
    archive = base64.b64decode(envelope["archive"], validate=True)
    manifest = base64.b64decode(envelope["manifest"], validate=True)
    if (
        sha(program) != packet["program_sha256"]
        or sha(archive) != ARCHIVE_SHA256
        or sha(manifest) != MANIFEST_SHA256
    ):
        raise Refusal("remote_reviewed_envelope_bytes")
    try:
        identity = _bootstrap_guest(dependencies, budget)
    except Exception as error:
        return _failure_outcome(packet, "bootstrap_target", error)
    # These are observations made here, before the first privileged write.
    envelope = dict(envelope, bootstrap_identity=identity)
    root_path = "/var/lib/ygg-dev-probe-" + packet["namespace"]
    api = dependencies.os
    parent = _bootstrap_directory("/var/lib", dependencies, budget)
    root = None
    try:
        api.mkdir(PurePosixPath(root_path).name, 0o700, dir_fd=parent)
        root = api.open(
            PurePosixPath(root_path).name,
            api.O_RDONLY | api.O_DIRECTORY | api.O_NOFOLLOW | api.O_CLOEXEC,
            dir_fd=parent,
        )
        info = api.fstat(root)
        if (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) != (0, 0, 0o700):
            raise Refusal("exclusive_remote_scope_metadata")
        for name, data in (
            ("program.py", program),
            ("source.tar", archive),
            ("manifest.json", manifest),
            (
                "carrier-envelope.json",
                json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode(),
            ),
        ):
            _write_bootstrap_file(root, name, data, dependencies, budget)
        api.fsync(root)
        api.fsync(parent)
    except FileExistsError:
        raise Refusal("original_remote_namespace_exists_no_replay") from None
    finally:
        if root is not None:
            budget.close("remote_namespace", lambda: api.close(root))
        budget.close("remote_namespace_parent", lambda: api.close(parent))
    namespace = _bootstrap_commands(dependencies, envelope["custody_source"])
    unit = "yggdrasil-dev-probe-" + packet["operation"] + ".service"
    properties = {
        "RuntimeMaxSec": str(max(1, int(budget.check() - 5))),
        "TimeoutStopSec": "5",
        "KillMode": "control-group",
        "Restart": "no",
        "StandardOutput": "null",
        "StandardError": "null",
        "UMask": "0077",
        "WorkingDirectory": root_path,
        "NoNewPrivileges": "yes",
        "PrivateTmp": "yes",
        "PrivateDevices": "yes",
        "ProtectSystem": "strict",
        "ProtectControlGroups": "yes",
        "ProtectKernelTunables": "yes",
        "ProtectKernelModules": "yes",
        "RestrictAddressFamilies": "AF_UNIX AF_INET AF_INET6",
        # A temporary DEV instance keeps its config inside root_path/source;
        # the canonical existing-instance directory need not exist at startup.
        "ReadWritePaths": root_path + " /run/systemd/system -/etc/yggdrasil/host-probe",
    }
    argv = [
        "/usr/bin/systemd-run",
        "--quiet",
        "--wait",
        "--unit=" + unit,
        "--service-type=exec",
        "--uid=root",
        "--gid=root",
        *("--property=" + key + "=" + value for key, value in properties.items()),
        "--setenv=PATH=/usr/sbin:/usr/bin:/sbin:/bin",
        "--setenv=LC_ALL=C",
        "--",
        packet["bootstrap_interpreter"],
        "-I",
        root_path + "/program.py",
        "--supervised-first-preflight",
        packet["operation"],
    ]
    completed = namespace["_bounded_process"](
        argv,
        timeout=budget.check() - 2.1,
        limit=131072,
        environment={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C"},
    )
    # --wait authenticates termination of this original job. Its successful
    # transient unit can already be unloaded, so use the incarnation captured
    # by that worker before discovery/SDK exec instead of post-exit show.
    root = _bootstrap_directory(root_path, dependencies, budget)
    try:

        def read_json(name: str) -> tuple[dict[str, Any] | None, bytes]:
            try:
                raw = _bootstrap_read(
                    root_path + "/" + name, dependencies, budget, limit=131072, private=True
                )
            except FileNotFoundError:
                return None, b""
            try:
                value = json.loads(raw, object_pairs_hook=unique)
            except (ValueError, TypeError, UnicodeError):
                raise Unknown("original_outcome_json_unqualified") from None
            if not isinstance(value, dict):
                raise Unknown("original_outcome_shape_unqualified")
            return value, raw

        failure, _ = read_json("failure.json")
        started, started_raw = read_json("supervisor-start.json")
        if failure is not None:
            if (
                failure.get("schema") != "fixed_dev_probe.outcome.v1"
                or failure.get("status") not in {"REFUSED", "UNKNOWN"}
                or failure.get("operation") != packet["operation"]
                or failure.get("program_sha256") != packet["program_sha256"]
                or failure.get("original_handle_sha256")
                != Handle(packet["operation"], "ygg-dev", "ygg-dev").fingerprint
                or re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,127}", failure.get("reason", "")) is None
                or failure.get("phase") not in {"first_preflight", "qualified_worker"}
                or completed.returncode != 78
            ):
                raise Unknown("original_failure_evidence_unqualified")
        if started is None:
            if failure is not None:
                budget.check()
                return failure
            raise Unknown("original_supervisor_start_evidence_missing")
        if (
            started.get("operation") != packet["operation"]
            or started.get("program_sha256") != packet["program_sha256"]
            or started.get("unit") != unit
            or not identifier(started.get("invocation"))
            or started.get("boot_id") != identity["boot_id"]
            or started.get("cgroup") != "/system.slice/" + unit
            or not str(started.get("pid", "")).isdigit()
            or _bootstrap_guest(dependencies, budget) != identity
        ):
            raise Unknown("original_supervisor_start_evidence_unqualified")
        try:
            members = _bootstrap_read(
                "/sys/fs/cgroup" + started["cgroup"] + "/cgroup.procs",
                dependencies,
                budget,
                limit=16384,
            )
        except FileNotFoundError:
            members = b""
        if members.strip():
            raise Unknown("original_supervisor_cgroup_not_empty")
        if failure is not None:
            budget.check()
            return failure
        result, _ = read_json("result.json")
        if completed.returncode != 0 or completed.stdout or completed.stderr or result is None:
            raise Unknown("original_supervisor_completion_unqualified")
        if result.get("operation") != packet["operation"]:
            raise Unknown("original_result_handle_changed")
        result["supervisor"] = {
            "reaped": True,
            "cgroup_empty": True,
            "unit": unit,
            "invocation": started["invocation"],
            "manager_exit_code": completed.returncode,
            "start_record_sha256": sha(started_raw),
        }
        budget.check()
        return result
    finally:
        budget.close("original_outcome_root", lambda: api.close(root))
        budget.check()


def native_completion_receipt(result: dict[str, Any], packet: dict[str, Any]) -> dict[str, Any]:
    """Project completed native evidence; core fixture observations remain unaccepted."""
    from datetime import datetime, timezone

    baseline = result.get("baseline", {})
    supervisor = result.get("supervisor", {})
    if (
        result.get("schema") != "fixed_dev_probe.observations.v1"
        or result.get("status") != "OBSERVATIONS_COMPLETE"
        or result.get("operation") != packet["operation"]
        or result.get("original_handle_sha256")
        != Handle(packet["operation"], "ygg-dev", "ygg-dev").fingerprint
        or result.get("down") != 1
        or result.get("recovery") != 1
        or type(result.get("completed_later_suppressions")) is not int
        or result["completed_later_suppressions"] < 2
        or result.get("config_restored") is not True
        or result.get("service_restored") != "active_same_effective_configuration"
        or result.get("incident_history_rewound") is not False
        or result.get("independent_guard_disarmed") is not True
        or not identifier(result.get("request_sha256"), 64)
        or not identifier(result.get("qualified_interpreter_sha256"), 64)
        or supervisor.get("reaped") is not True
        or supervisor.get("cgroup_empty") is not True
        or supervisor.get("manager_exit_code") != 0
        or not identifier(supervisor.get("invocation"))
        or not identifier(supervisor.get("start_record_sha256"), 64)
        or baseline.get("readyz_status") != 200
        or baseline.get("required_ok") is not True
        or baseline.get("source_manifest_sha256") != MANIFEST_SHA256
        or baseline.get("source_files_sha256") != SOURCE_HASHES
        or baseline.get("consumer") != "heimdal-external-alerts"
        or baseline.get("normal_binding") != "shared/discord.webhook"
    ):
        raise Unknown("native_completed_evidence_unqualified")
    try:
        correlation = str(UUID(result["same_correlation"]))
    except (ValueError, TypeError, KeyError, AttributeError):
        raise Unknown("native_correlation_unqualified") from None
    temporary = result.get("temporary_installation")
    if temporary is not None and (
        temporary.get("original_service") not in {"absent", "inactive"}
        or temporary.get("original_effective_unit_and_enablement_restored") is not True
        or temporary.get("owned_temporary_artifacts_removed") is not True
        or temporary.get("shared_package_or_template_overwritten") is not False
        or temporary.get("original_probe_state_directory") not in {"absent", "present"}
        or temporary.get("probe_state_directory_restored") is not True
        or temporary.get("runtime_directory_restored") is not True
        or temporary.get("operation_state_directory_removed") is not True
    ):
        raise Unknown("native_temporary_restoration_unqualified")
    return {
        "schema": "probe_dev_outage_recovery.v1",
        "status": "PASS",
        "environment": "dev",
        "target": "ygg-dev",
        "native_entry_enabled": True,
        "live_acceptance": True,
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "operation": result["operation"],
        "original_handle_sha256": result["original_handle_sha256"],
        "request_sha256": result["request_sha256"],
        "reviewed_head": packet["reviewed_head"],
        "program_sha256": packet["program_sha256"],
        "issue_body_sha256": packet["issue_body_sha256"],
        "source_commit": SOURCE_COMMIT,
        "source_archive_sha256": ARCHIVE_SHA256,
        "interpreter_sha256": result["qualified_interpreter_sha256"],
        "baseline": baseline,
        "dev_candidate_references": result["dev_candidate_references"],
        "down": 1,
        "completed_later_suppressions": result["completed_later_suppressions"],
        "recovery": 1,
        "same_correlation": True,
        "correlation_sha256": sha(correlation.encode()),
        "config_restored": True,
        "original_service": temporary["original_service"] if temporary else "active",
        "original_lifecycle_and_artifacts_restored": True,
        "temporary_directories": {
            "original_state": temporary["original_probe_state_directory"],
            "state_restored": True,
            "runtime_restored": True,
            "operation_state_removed": True,
        }
        if temporary
        else None,
        "incident_history_rewound": False,
        "independent_guard_disarmed": True,
        "supervisor": supervisor,
        "observations_sha256": sha(
            json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
        ),
        "accepted_window_utc": [packet["window_start_utc"], packet["window_end_utc"]],
    }


def supervised_first_preflight(envelope: dict[str, Any], dependencies: LinuxDependencies) -> None:
    import base64

    packet = carrier_packet(json.dumps(envelope["packet"]).encode())
    budget = BootstrapBudget(packet, dependencies)
    original = _supervisor_start(envelope, dependencies, budget)
    root = _bootstrap_directory(
        "/var/lib/ygg-dev-probe-" + packet["namespace"], dependencies, budget
    )
    try:
        _write_bootstrap_file(
            root,
            "supervisor-start.json",
            json.dumps(original, sort_keys=True, separators=(",", ":")).encode(),
            dependencies,
            budget,
        )
        dependencies.os.fsync(root)
    finally:
        budget.close("supervisor_start_record", lambda: dependencies.os.close(root))
    budget.check()
    archive = base64.b64decode(envelope["archive"], validate=True)
    manifest = base64.b64decode(envelope["manifest"], validate=True)
    source, _ = exact_source(archive, manifest, budget)
    facts = discover_fixed_dev_producer(
        dependencies,
        envelope["custody_source"],
        deadline=dependencies.time.monotonic() + budget.check() - 2.1,
    )
    if any(
        facts[key] != envelope["bootstrap_identity"][key]
        for key in ("hostname", "machine_id", "boot_id", "net_namespace")
    ):
        raise Refusal("bootstrap_target_changed_during_first_preflight")
    scope, config = scope_from_first_preflight(
        packet,
        facts,
        dependencies,
        manifest,
        source["app/ops/host_secret_controller.py"],
        source[PROBE],
    )
    root = _bootstrap_directory(scope.root, dependencies, budget)
    try:
        _write_bootstrap_file(root, "request.json", scope.request_bytes, dependencies, budget)
        _write_bootstrap_file(
            root,
            "native-input.json",
            _scope_json(scope, config, envelope["custody_source"]),
            dependencies,
            budget,
        )
        dependencies.os.fsync(root)
    finally:
        budget.close("frozen_first_preflight", lambda: dependencies.os.close(root))
    # Same hard supervisor/cgroup, now the actually qualified normal SDK.
    dependencies.os.execve(
        scope.binding.sdk,
        [
            scope.binding.sdk,
            "-I",
            scope.root + "/program.py",
            "--qualified-dev-worker",
            scope.handle.operation,
        ],
        {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C"},
    )
    raise Unknown("qualified_sdk_exec_returned")


def qualified_dev_worker(root_path: str, dependencies: LinuxDependencies) -> dict[str, Any]:
    api = dependencies.os
    descriptor = api.open(
        root_path + "/native-input.json", api.O_RDONLY | api.O_NOFOLLOW | api.O_CLOEXEC
    )
    try:
        scope, config, custody = _decode_scope(api.read(descriptor, 1048577))
    finally:
        api.close(descriptor)
    budget = BootstrapBudget(
        {
            "_start_epoch": dependencies.time.time() - 1,
            "_end_epoch": dependencies.time.time()
            + scope.binding.window_end
            - dependencies.time.monotonic(),
        },
        dependencies,
    )
    original = json.loads(
        _bootstrap_read(
            root_path + "/supervisor-start.json", dependencies, budget, limit=16384, private=True
        ),
        object_pairs_hook=unique,
    )
    if (
        original.get("pid") != str(api.getpid())
        or original.get("operation") != scope.handle.operation
        or original.get("boot_id") != scope.binding.boot_id
        or original.get("program_sha256") != scope.program_sha256
    ):
        raise Refusal("qualified_worker_not_original_supervised_process")
    assembly = assemble_native(scope, dependencies, custody)
    descriptor = api.open(root_path + "/source.tar", api.O_RDONLY | api.O_NOFOLLOW | api.O_CLOEXEC)
    try:
        archive = bytearray()
        while len(archive) <= ARCHIVE_BYTES:
            assembly.caller.check()
            block = api.read(descriptor, min(65536, ARCHIVE_BYTES + 1 - len(archive)))
            if not block:
                break
            archive.extend(block)
    finally:
        assembly.caller.close("frozen_archive", lambda: api.close(descriptor))
    try:
        result = run_fixed_dev_worker(assembly, bytes(archive), config)
        result["operation"] = scope.handle.operation
        result["request_sha256"] = sha(scope.request_bytes)
        result["qualified_interpreter_sha256"] = sha(
            assembly.io.read(scope.binding.sdk_realpath, limit=16_777_216).data
        )
        budget = BootstrapBudget(
            {
                "_start_epoch": dependencies.time.time() - 1,
                "_end_epoch": dependencies.time.time() + max(2.2, assembly.caller.check()),
            },
            dependencies,
        )
        root = _bootstrap_directory(scope.root, dependencies, budget)
        try:
            _write_bootstrap_file(
                root,
                "result.json",
                json.dumps(result, sort_keys=True, separators=(",", ":")).encode(),
                dependencies,
                budget,
            )
        finally:
            budget.close("result_directory", lambda: api.close(root))
        return result
    finally:
        assembly.files.close()


def native_dispatch(role: str, data: Any, dependencies: LinuxDependencies) -> Any:
    """Fixed role dispatch, shared by native entry and injected-port tests."""
    if role == "remote-launch":
        return remote_launch(data, dependencies)
    if role == "supervised-first-preflight":
        return supervised_first_preflight(data, dependencies)
    if role == "qualified-worker":
        return qualified_dev_worker(data, dependencies)
    if role == "watchdog":
        return watch_dev_operation(data, dependencies)
    if role == "cli":
        return enabled_cli_dispatch(data, dependencies)
    raise Refusal("unsupported_fixed_dev_dispatch_role")


def retain_worker_failure(args: Any, error: BaseException, dependencies: LinuxDependencies) -> None:
    """Persist one bounded authored outcome before a supervised worker exits."""
    requested = (
        args.supervised_first_preflight or args.qualified_dev_worker or args.fixed_dev_worker
    )
    if not requested:
        return
    root_path = str(Path(__file__).resolve().parent)
    if re.fullmatch(r"/var/lib/ygg-dev-probe-[0-9a-f]{32}", root_path) is None:
        return
    probe_budget = BootstrapBudget(
        {"_start_epoch": dependencies.time.time() - 1, "_end_epoch": dependencies.time.time() + 5},
        dependencies,
    )
    root = _bootstrap_directory(root_path, dependencies, probe_budget)
    try:
        envelope = json.loads(
            _bootstrap_read(
                root_path + "/carrier-envelope.json",
                dependencies,
                probe_budget,
                limit=4194304,
                private=True,
            ),
            object_pairs_hook=unique,
        )
        packet = carrier_packet(json.dumps(envelope["packet"]).encode())
        if (
            root_path != "/var/lib/ygg-dev-probe-" + packet["namespace"]
            or requested != packet["operation"]
        ):
            return
        budget = BootstrapBudget(packet, dependencies)
        phase = "first_preflight" if args.supervised_first_preflight else "qualified_worker"
        outcome = _failure_outcome(packet, phase, error)
        _write_bootstrap_file(
            root,
            "failure.json",
            json.dumps(outcome, sort_keys=True, separators=(",", ":")).encode(),
            dependencies,
            budget,
        )
        dependencies.os.fsync(root)
    finally:
        probe_budget.close("failure_outcome_root", lambda: dependencies.os.close(root))
        probe_budget.check()


def enabled_cli_dispatch(args: Any, dependencies: LinuxDependencies) -> Any:
    """Complete CLI routing for the fixed caller and original remote namespace."""
    api = dependencies.os

    def read(path: str, limit: int) -> bytes:
        descriptor = api.open(path, api.O_RDONLY | api.O_NOFOLLOW | api.O_NONBLOCK | api.O_CLOEXEC)
        try:
            info = api.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_size > limit or info.st_nlink != 1:
                raise Refusal("cli_input_metadata_or_bound")
            result = bytearray()
            while True:
                chunk = api.read(descriptor, min(65536, limit + 1 - len(result)))
                if not chunk:
                    break
                result.extend(chunk)
                if len(result) > limit:
                    raise Refusal("cli_input_bound")
            return bytes(result)
        finally:
            api.close(descriptor)

    if args.request:
        if not args.archive or not args.manifest or not args.custody_source:
            raise Refusal("caller_requires_exact_public_archive_manifest_custody_inputs")
        return run_claimed_local_caller(
            read(args.request, 65536),
            dependencies,
            read(args.custody_source, 1048576).decode(),
            read(args.archive, ARCHIVE_BYTES),
            read(args.manifest, 131072),
        )
    root = str(Path(__file__).resolve().parent)
    if re.fullmatch(r"/var/lib/ygg-dev-probe-[0-9a-f]{32}", root) is None:
        raise Refusal("worker_outside_original_private_native_namespace")
    if args.supervised_first_preflight:
        envelope = json.loads(
            read(root + "/carrier-envelope.json", 4194304), object_pairs_hook=unique
        )
        if envelope["packet"]["operation"] != args.supervised_first_preflight:
            raise Refusal("supervised_original_operation_changed")
        return supervised_first_preflight(envelope, dependencies)
    if args.qualified_dev_worker or args.fixed_dev_worker:
        return qualified_dev_worker(root, dependencies)
    if args.watch_dev_operation:
        return watch_dev_operation(root, dependencies)
    raise Refusal("one_fixed_cli_action_required")


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="One claimed, reviewed #6505 DEV probe operation")
    parser.add_argument(
        "--request", help="fixed_dev_probe.carrier.v1 JSON; actual window/review values required"
    )
    parser.add_argument("--fixed-dev-worker", metavar="OPERATION")
    parser.add_argument("--supervised-first-preflight", metavar="OPERATION")
    parser.add_argument("--qualified-dev-worker", metavar="OPERATION")
    parser.add_argument("--watch-dev-operation", metavar="OPERATION")
    parser.add_argument("--archive")
    parser.add_argument("--manifest")
    parser.add_argument("--custody-source")
    parser.add_argument("--schema", action="store_true")
    args = parser.parse_args(argv)
    if args.schema:
        print(
            json.dumps(
                {
                    "schema": "fixed_dev_probe.carrier.v1",
                    "issue": 6505,
                    "operation": None,
                    "namespace": None,
                    "reviewed_head": None,
                    "program_sha256": None,
                    "issue_body_sha256": None,
                    "lease_id": None,
                    "keeper_standing_reference": None,
                    "window_start_utc": None,
                    "window_end_utc": None,
                    "bootstrap_interpreter": None,
                    "local_fence_references": None,
                    "normal_interval_seconds": 60,
                    "heartbeat_stale_seconds": 60,
                    "gh_executable": None,
                    "caller_interpreter": None,
                },
                sort_keys=True,
                indent=2,
            )
        )
        return 0
    # Native dispatch creates its own actual platform ports and validates the
    # complete claimed caller or original private remote namespace.
    try:
        result = native_entry("cli", args)
    except Exception as error:
        try:
            retain_worker_failure(args, error, LinuxDependencies.standard_library())
        except Exception:
            # A lost write/close is not evidence. The supervisor still exits
            # nonzero and the original caller retains UNKNOWN.
            pass
        raise
    if isinstance(result, bytes):
        value = json.loads(result, object_pairs_hook=unique)
        if not isinstance(value, dict) or value.get("schema") not in {
            "probe_dev_outage_recovery.v1",
            "fixed_dev_probe.outcome.v1",
        }:
            raise Unknown("original_remote_outcome_schema_unqualified")
        print(json.dumps(value, sort_keys=True, separators=(",", ":")))
        return 0 if value.get("status") == "PASS" and value.get("live_acceptance") is True else 78
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (Refusal, Unknown) as error:
        # Only finite authored reasons reach the console; never raw host data.
        print(
            json.dumps(
                {
                    "status": "UNKNOWN" if isinstance(error, Unknown) else "REFUSED",
                    "reason": _failure_reason(error),
                }
            )
        )
        raise SystemExit(78)
    except Exception:
        print(json.dumps({"status": "UNKNOWN", "reason": "unqualified_operation_failure"}))
        raise SystemExit(78)
