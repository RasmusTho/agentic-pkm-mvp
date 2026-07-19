#!/usr/bin/env python3
"""Fail-closed host-wide deployment writer inventory.

The deployment wrapper runs this as one foreground process.  It owns both
Docker and native enumeration, records no raw argv or host path, and emits a
proof candidate only when two complete snapshots are identical and empty.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


INVENTORY_SCHEMA = "agentic-pkm.host-deployment-quiescence.v2"
DOMAINS = ("dev", "native", "prod", "test")
COMPOSE_PROJECT_DOMAINS = {"pkm-dev": "dev", "pkm-prod": "prod", "pkm-test": "test"}
COMPOSE_WRITER_SERVICES = {"api", "heimdal-capture-watch", "watcher", "worker"}
LAUNCHER_SCRIPTS = {"deploy_channel.sh", "start_full_system.sh"}
TOKEN_RE = re.compile(r"^(?:linux|darwin|docker):[0-9a-f]{64}$")
PYTHON_RE = re.compile(r"^python(?:3(?:\.\d+)*)?$")
PF_KTHREAD = 0x00200000
LINUX_PROCESS_READ_ATTEMPTS = 3
LINUX_DEAD_STATES = frozenset({"X", "x", "Z"})
LINUX_PROCESS_STATES = frozenset({"D", "I", "K", "P", "R", "S", "T", "W", "X", "Z", "t", "x"})


class InventoryError(RuntimeError):
    """Enumeration or proof construction was incomplete or unsafe."""


@dataclass(frozen=True)
class ProcessRecord:
    pid: int
    ppid: int
    pgid: int
    start_token: str
    argv: tuple[str, ...]
    executable_hint: str | None = None


def _digest_token(kind: str, *parts: object) -> str:
    raw = "\0".join(str(part) for part in parts).encode("utf-8", errors="surrogateescape")
    return f"{kind}:{hashlib.sha256(raw).hexdigest()}"


def _parse_linux_stat(pid: int, raw: str) -> tuple[str, int, int, int, str]:
    close = raw.rfind(")")
    if close < 2 or not raw.startswith(f"{pid} ("):
        raise InventoryError("native process identity is malformed")
    fields = raw[close + 2 :].split()
    if len(fields) < 20:
        raise InventoryError("native process identity is malformed")
    try:
        state = fields[0]
        ppid = int(fields[1])
        pgid = int(fields[2])
        flags = int(fields[6])
        start_ticks = str(int(fields[19]))
    except (TypeError, ValueError) as exc:
        raise InventoryError("native process identity is malformed") from exc
    if (
        state not in LINUX_PROCESS_STATES
        or flags < 0
        or ppid < 0
        or pgid < 0
        or int(start_ticks) <= 0
    ):
        raise InventoryError("native process identity is malformed")
    return state, flags, ppid, pgid, start_ticks


def _read_linux_boot_id() -> str:
    try:
        boot_id = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
    except OSError as exc:
        raise InventoryError("native process enumeration failed") from exc
    if not boot_id:
        raise InventoryError("native process identity is malformed")
    return boot_id


def _read_linux_stat(pid: int) -> str:
    return (Path("/proc") / str(pid) / "stat").read_text(encoding="utf-8")


def _read_linux_cmdline(pid: int) -> bytes:
    return (Path("/proc") / str(pid) / "cmdline").read_bytes()


def _read_linux_exe(pid: int) -> str:
    return os.readlink(Path("/proc") / str(pid) / "exe")


def _normalize_linux_exe(value: str) -> str:
    suffix = " (deleted)"
    normalized = value[: -len(suffix)] if value.endswith(suffix) else value
    if not normalized.startswith("/") or "\0" in normalized or not _basename(normalized):
        raise InventoryError("native process executable identity is malformed")
    return normalized


def _linux_pid_is_gone(pid: int) -> bool:
    try:
        os.stat(Path("/proc") / str(pid))
    except (FileNotFoundError, ProcessLookupError):
        return True
    except OSError:
        return False
    return False


def _linux_inert(state: str, flags: int) -> bool:
    return state in LINUX_DEAD_STATES or bool(flags & PF_KTHREAD)


def _linux_gone_result(
    *,
    strict_controller: bool,
    fail_closed_on_gone: bool,
) -> None:
    if strict_controller:
        raise InventoryError("controller process identity is unavailable")
    if fail_closed_on_gone:
        raise InventoryError("native process enumeration failed")
    return None


def _linux_record(
    pid: int,
    boot_id: str,
    *,
    strict_controller: bool = False,
    fail_closed_on_gone: bool = False,
) -> ProcessRecord | None:
    """Read one PID without binding argv across exit, exec, or PID reuse races."""

    last_error = InventoryError("native process enumeration did not stabilize")
    for attempt in range(LINUX_PROCESS_READ_ATTEMPTS):
        final_attempt = attempt == LINUX_PROCESS_READ_ATTEMPTS - 1
        try:
            stat_before_raw = _read_linux_stat(pid)
        except (FileNotFoundError, ProcessLookupError):
            last_error = InventoryError("native process enumeration failed")
            if final_attempt and _linux_pid_is_gone(pid):
                return _linux_gone_result(
                    strict_controller=strict_controller,
                    fail_closed_on_gone=fail_closed_on_gone,
                )
            continue
        except (PermissionError, OSError):
            last_error = InventoryError("native process enumeration failed")
            if final_attempt and _linux_pid_is_gone(pid):
                return _linux_gone_result(
                    strict_controller=strict_controller,
                    fail_closed_on_gone=fail_closed_on_gone,
                )
            continue

        try:
            before = _parse_linux_stat(pid, stat_before_raw)
        except InventoryError as exc:
            last_error = exc
            if final_attempt and _linux_pid_is_gone(pid):
                return _linux_gone_result(
                    strict_controller=strict_controller,
                    fail_closed_on_gone=fail_closed_on_gone,
                )
            continue

        try:
            cmdline_raw = _read_linux_cmdline(pid)
        except (FileNotFoundError, ProcessLookupError):
            last_error = InventoryError("native process enumeration failed")
            if final_attempt and _linux_pid_is_gone(pid):
                return _linux_gone_result(
                    strict_controller=strict_controller,
                    fail_closed_on_gone=fail_closed_on_gone,
                )
            continue
        except (PermissionError, OSError):
            last_error = InventoryError("native process enumeration failed")
            if final_attempt and _linux_pid_is_gone(pid):
                return _linux_gone_result(
                    strict_controller=strict_controller,
                    fail_closed_on_gone=fail_closed_on_gone,
                )
            continue

        executable_hint: str | None = None
        exec_pair_changed = False
        if cmdline_raw.endswith(b"\0") and cmdline_raw[:-1].split(b"\0", 1)[0] == b"":
            try:
                executable_hint = _normalize_linux_exe(_read_linux_exe(pid))
                confirmed_cmdline = _read_linux_cmdline(pid)
                confirmed_executable = _normalize_linux_exe(_read_linux_exe(pid))
            except (FileNotFoundError, ProcessLookupError):
                last_error = InventoryError("native process executable identity is unavailable")
                if final_attempt and _linux_pid_is_gone(pid):
                    return _linux_gone_result(
                        strict_controller=strict_controller,
                        fail_closed_on_gone=fail_closed_on_gone,
                    )
                continue
            except (PermissionError, OSError):
                last_error = InventoryError("native process executable identity is unavailable")
                if final_attempt and _linux_pid_is_gone(pid):
                    return _linux_gone_result(
                        strict_controller=strict_controller,
                        fail_closed_on_gone=fail_closed_on_gone,
                    )
                continue
            except InventoryError as exc:
                last_error = exc
                if final_attempt and _linux_pid_is_gone(pid):
                    return _linux_gone_result(
                        strict_controller=strict_controller,
                        fail_closed_on_gone=fail_closed_on_gone,
                    )
                continue
            exec_pair_changed = (
                cmdline_raw != confirmed_cmdline
                or executable_hint != confirmed_executable
            )

        try:
            stat_after_raw = _read_linux_stat(pid)
        except (FileNotFoundError, ProcessLookupError):
            last_error = InventoryError("native process enumeration failed")
            if final_attempt and _linux_pid_is_gone(pid):
                return _linux_gone_result(
                    strict_controller=strict_controller,
                    fail_closed_on_gone=fail_closed_on_gone,
                )
            continue
        except (PermissionError, OSError):
            last_error = InventoryError("native process enumeration failed")
            if final_attempt and _linux_pid_is_gone(pid):
                return _linux_gone_result(
                    strict_controller=strict_controller,
                    fail_closed_on_gone=fail_closed_on_gone,
                )
            continue

        try:
            after = _parse_linux_stat(pid, stat_after_raw)
        except InventoryError as exc:
            last_error = exc
            if final_attempt and _linux_pid_is_gone(pid):
                return _linux_gone_result(
                    strict_controller=strict_controller,
                    fail_closed_on_gone=fail_closed_on_gone,
                )
            continue

        before_start = before[4]
        state, flags, ppid, pgid, after_start = after
        if before_start != after_start:
            last_error = InventoryError("native process identity changed during enumeration")
            continue
        if exec_pair_changed:
            last_error = InventoryError(
                "native process exec identity changed during enumeration"
            )
            continue
        if _linux_inert(state, flags):
            if strict_controller:
                raise InventoryError("controller process identity is unavailable")
            return None
        if not cmdline_raw:
            last_error = InventoryError("native process argv is unavailable")
            continue
        if not cmdline_raw.endswith(b"\0"):
            last_error = InventoryError("native process argv is malformed")
            continue

        # Remove exactly the procfs record terminator. Empty arguments before it
        # are legal and must remain in their original positions.
        argv = tuple(os.fsdecode(value) for value in cmdline_raw[:-1].split(b"\0"))
        return ProcessRecord(
            pid=pid,
            ppid=ppid,
            pgid=pgid,
            start_token=_digest_token("linux", boot_id, pid, after_start),
            argv=argv,
            executable_hint=executable_hint,
        )

    if _linux_pid_is_gone(pid):
        return _linux_gone_result(
            strict_controller=strict_controller,
            fail_closed_on_gone=fail_closed_on_gone,
        )
    raise last_error


_PS_ROW_RE = re.compile(
    r"^\s*(\d+)\s+(\d+)\s+(\d+)\s+"
    r"([A-Z][a-z]{2}\s+[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}\s+\d{4})\s+(.+)$"
)


def _parse_macos_ps_row(line: str) -> ProcessRecord:
    match = _PS_ROW_RE.fullmatch(line)
    if match is None:
        raise InventoryError("native process inventory row is malformed")
    pid_text, ppid_text, pgid_text, started, command = match.groups()
    try:
        dt.datetime.strptime(started, "%a %b %d %H:%M:%S %Y")
        argv = tuple(shlex.split(command, posix=True))
        pid, ppid, pgid = int(pid_text), int(ppid_text), int(pgid_text)
    except (ValueError, TypeError) as exc:
        raise InventoryError("native process inventory row is malformed") from exc
    if pid <= 0 or ppid < 0 or pgid < 0 or not argv:
        raise InventoryError("native process inventory row is malformed")
    return ProcessRecord(
        pid=pid,
        ppid=ppid,
        pgid=pgid,
        start_token=_digest_token("darwin", pid, started),
        argv=argv,
    )


def _run_checked(command: Sequence[str], *, label: str, env: dict[str, str] | None = None) -> str:
    try:
        result = subprocess.run(
            list(command),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise InventoryError(f"{label} failed") from exc
    if result.returncode != 0:
        raise InventoryError(f"{label} failed")
    return result.stdout


def _test_sync(ready_name: str, continue_name: str) -> None:
    ready_raw = os.getenv(ready_name)
    continue_raw = os.getenv(continue_name)
    if ready_raw is None and continue_raw is None:
        return
    if ready_raw is None or continue_raw is None:
        raise InventoryError("inventory synchronization hook is incomplete")
    try:
        ready_fd = int(ready_raw)
        continue_fd = int(continue_raw)
        os.write(ready_fd, b"R")
        if os.read(continue_fd, 1) != b"C":
            raise InventoryError("inventory synchronization hook failed")
    except (OSError, ValueError) as exc:
        raise InventoryError("inventory synchronization hook failed") from exc


def _enumerate_linux(*, boot_id: str) -> list[ProcessRecord]:
    try:
        pids = sorted(int(item.name) for item in Path("/proc").iterdir() if item.name.isdigit())
    except OSError as exc:
        raise InventoryError("native process enumeration failed") from exc
    _test_sync(
        "INSTANCE_STATE_INVENTORY_TEST_PROC_LIST_READY_FD",
        "INSTANCE_STATE_INVENTORY_TEST_PROC_LIST_CONTINUE_FD",
    )
    records: list[ProcessRecord] = []
    for pid in pids:
        record = _linux_record(pid, boot_id, fail_closed_on_gone=True)
        if record is not None:
            records.append(record)
    return records


def _enumerate_macos() -> list[ProcessRecord]:
    env = {**os.environ, "LC_ALL": "C"}
    output = _run_checked(
        ["ps", "-ww", "-axo", "pid=,ppid=,pgid=,lstart=,command="],
        label="native process enumeration",
        env=env,
    )
    rows = output.splitlines()
    if not rows:
        raise InventoryError("native process enumeration is empty")
    return [_parse_macos_ps_row(line) for line in rows]


def _native_processes(*, linux_boot_id: str | None = None) -> list[ProcessRecord]:
    if sys.platform.startswith("linux"):
        if linux_boot_id is None:
            raise InventoryError("native process identity is malformed")
        return _enumerate_linux(boot_id=linux_boot_id)
    if sys.platform == "darwin":
        return _enumerate_macos()
    raise InventoryError("unsupported native process inventory platform")


def _record_for_pid(pid: int, *, linux_boot_id: str | None = None) -> ProcessRecord:
    if pid <= 0:
        raise InventoryError("controller pid is invalid")
    if sys.platform.startswith("linux"):
        boot_id = linux_boot_id if linux_boot_id is not None else _read_linux_boot_id()
        record = _linux_record(pid, boot_id, strict_controller=True)
        if record is None:
            raise InventoryError("controller process identity is unavailable")
        return record
    if sys.platform == "darwin":
        env = {**os.environ, "LC_ALL": "C"}
        output = _run_checked(
            ["ps", "-ww", "-p", str(pid), "-o", "pid=,ppid=,pgid=,lstart=,command="],
            label="controller process identity",
            env=env,
        )
        rows = output.splitlines()
        if len(rows) != 1:
            raise InventoryError("controller process identity is unavailable")
        record = _parse_macos_ps_row(rows[0])
        if record.pid != pid:
            raise InventoryError("controller process identity is unavailable")
        return record
    raise InventoryError("unsupported controller identity platform")


def controller_token(pid: int) -> str:
    return _record_for_pid(pid).start_token


def _basename(value: str) -> str:
    return value.rsplit("/", 1)[-1]


def _native_role(
    argv: tuple[str, ...], *, executable_hint: str | None = None
) -> str | None:
    if not argv:
        return None
    executable = _basename(argv[0]) if argv[0] else _basename(executable_hint or "")
    if executable in LAUNCHER_SCRIPTS:
        return executable.removesuffix(".sh")
    if executable in {"bash", "dash", "sh", "zsh"} and len(argv) >= 2:
        script = _basename(argv[1])
        if script in LAUNCHER_SCRIPTS:
            return script.removesuffix(".sh")
    if executable == "uvicorn":
        return "uvicorn"
    if executable == "celery":
        return "celery"
    if PYTHON_RE.fullmatch(executable) and len(argv) >= 3 and argv[1] == "-m":
        if argv[2] == "uvicorn":
            return "uvicorn"
        if argv[2] == "celery":
            return "celery"
        if len(argv) >= 5 and argv[2:5] == ("app.cli", "watcher", "run"):
            return "watcher"
        if len(argv) >= 5 and argv[2:5] == ("app.cli", "heimdal", "capture-watch"):
            return "heimdal-capture-watch"
    return None


def _docker_writers() -> list[dict[str, object]]:
    ids_output = _run_checked(
        ["docker", "ps", "--no-trunc", "--format", "{{.ID}}"],
        label="docker process enumeration",
    )
    ids = [line.strip() for line in ids_output.splitlines() if line.strip()]
    if any(re.fullmatch(r"[0-9a-f]{12,64}", item) is None for item in ids) or len(ids) != len(set(ids)):
        raise InventoryError("docker process inventory is malformed")
    if not ids:
        return []
    inspect_output = _run_checked(
        ["docker", "inspect", *ids], label="docker process enumeration"
    )
    try:
        payload = json.loads(inspect_output)
    except json.JSONDecodeError as exc:
        raise InventoryError("docker process inventory is malformed") from exc
    if not isinstance(payload, list) or len(payload) != len(ids):
        raise InventoryError("docker process inventory is malformed")
    writers: list[dict[str, object]] = []
    seen: set[str] = set()
    for item in payload:
        if not isinstance(item, dict):
            raise InventoryError("docker process inventory is malformed")
        container_id = str(item.get("Id") or "")
        config = item.get("Config")
        labels = config.get("Labels") if isinstance(config, dict) else None
        if labels is None:
            labels = {}
        state = item.get("State")
        if (
            container_id not in ids
            or container_id in seen
            or not isinstance(labels, dict)
            or not isinstance(state, dict)
        ):
            raise InventoryError("docker process inventory is malformed")
        seen.add(container_id)
        project = labels.get("com.docker.compose.project")
        service = labels.get("com.docker.compose.service")
        if project not in COMPOSE_PROJECT_DOMAINS or service not in COMPOSE_WRITER_SERVICES:
            continue
        pid = state.get("Pid")
        started = state.get("StartedAt")
        if not isinstance(pid, int) or pid <= 0 or not isinstance(started, str) or not started:
            raise InventoryError("docker process inventory is malformed")
        writers.append(
            {
                "domain": COMPOSE_PROJECT_DOMAINS[str(project)],
                "role": str(service),
                "pid": pid,
                "start_token": _digest_token("docker", container_id, started),
            }
        )
    return writers


def _native_writers(
    *,
    controller_pid: int,
    controller_start_token: str,
    linux_boot_id: str | None = None,
) -> list[dict[str, object]]:
    writers: list[dict[str, object]] = []
    for process in _native_processes(linux_boot_id=linux_boot_id):
        role = _native_role(
            process.argv,
            executable_hint=process.executable_hint,
        )
        if role is None:
            continue
        if process.pid == controller_pid and process.start_token == controller_start_token:
            continue
        writers.append(
            {
                "domain": "native",
                "role": role,
                "pid": process.pid,
                "start_token": process.start_token,
            }
        )
    return writers


def _snapshot(*, controller_pid: int, controller_start_token: str) -> dict[str, list[dict[str, object]]]:
    linux_boot_id = _read_linux_boot_id() if sys.platform.startswith("linux") else None
    controller = _record_for_pid(controller_pid, linux_boot_id=linux_boot_id)
    if controller.start_token != controller_start_token:
        raise InventoryError("deployment controller identity changed")
    domains: dict[str, list[dict[str, object]]] = {domain: [] for domain in DOMAINS}
    for writer in _docker_writers() + _native_writers(
        controller_pid=controller_pid,
        controller_start_token=controller_start_token,
        linux_boot_id=linux_boot_id,
    ):
        domain = str(writer.pop("domain"))
        domains[domain].append(writer)
    for domain in domains:
        domains[domain].sort(
            key=lambda item: (str(item["role"]), int(item["pid"]), str(item["start_token"]))
        )
    return domains


def _canonical_digest(domains: dict[str, list[dict[str, object]]]) -> str:
    encoded = json.dumps(domains, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _write_inventory(path: Path, payload: dict[str, object]) -> None:
    destination = Path(path).expanduser().resolve(strict=False)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", dir=destination.parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", closefd=True) as handle:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
        directory = os.open(destination.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def prove_quiescent(
    *, controller_pid: int, controller_start_token: str, output: Path
) -> None:
    if TOKEN_RE.fullmatch(controller_start_token) is None or controller_start_token.startswith("docker:"):
        raise InventoryError("controller start identity is invalid")
    first = _snapshot(
        controller_pid=controller_pid,
        controller_start_token=controller_start_token,
    )
    _test_sync(
        "INSTANCE_STATE_INVENTORY_TEST_BETWEEN_READY_FD",
        "INSTANCE_STATE_INVENTORY_TEST_BETWEEN_CONTINUE_FD",
    )
    second = _snapshot(
        controller_pid=controller_pid,
        controller_start_token=controller_start_token,
    )
    if first != second or any(first.values()) or any(second.values()):
        raise InventoryError("host-wide writer inventory is live or racing")
    digests = [_canonical_digest(first), _canonical_digest(second)]
    _write_inventory(
        output,
        {
            "schema": INVENTORY_SCHEMA,
            "inventory_complete": True,
            "probe_count": 2,
            "all_consumers_stopped": True,
            "controller": {
                "pid": controller_pid,
                "start_token": controller_start_token,
            },
            "domains": first,
            "snapshot_digests": digests,
        },
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    token = subparsers.add_parser("controller-token")
    token.add_argument("--pid", type=int, required=True)
    prove = subparsers.add_parser("prove-quiescent")
    prove.add_argument("--controller-pid", type=int, required=True)
    prove.add_argument("--controller-start-token", required=True)
    prove.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "controller-token":
            print(controller_token(args.pid))
            return 0
        if args.command == "prove-quiescent":
            prove_quiescent(
                controller_pid=args.controller_pid,
                controller_start_token=args.controller_start_token,
                output=args.output,
            )
            return 0
    except InventoryError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    raise AssertionError("unreachable")


if __name__ == "__main__":
    raise SystemExit(main())
