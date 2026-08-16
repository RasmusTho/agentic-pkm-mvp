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
import io
import json
import os
import posixpath
import re
import stat
import subprocess
import sys
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


INVENTORY_SCHEMA = "agentic-pkm.host-deployment-quiescence.v2"
LEGACY_OWNER_INVENTORY_SCHEMA = "agentic-pkm.legacy-owner-inventory.v1"
DOMAINS = ("dev", "native", "prod", "test")
COMPOSE_PROJECT_DOMAINS = {"pkm-dev": "dev", "pkm-prod": "prod", "pkm-test": "test"}
LAUNCHER_SCRIPTS = {"deploy_channel.sh", "start_full_system.sh"}
LAUNCHER_ROLES = {name.removesuffix(".sh") for name in LAUNCHER_SCRIPTS}
TOKEN_RE = re.compile(r"^(?:linux|darwin|docker):[0-9a-f]{64}$")
PYTHON_RE = re.compile(r"^python(?:3(?:\.\d+)*)?$")
PF_KTHREAD = 0x00200000
LINUX_PROCESS_READ_ATTEMPTS = 3
LINUX_DEAD_STATES = frozenset({"X", "x", "Z"})
LINUX_PROCESS_STATES = frozenset({"D", "I", "K", "P", "R", "S", "T", "W", "X", "Z", "t", "x"})


class InventoryError(RuntimeError):
    """Enumeration or proof construction was incomplete or unsafe."""


def redact_compose_fence_config(source: Path, output: Path) -> None:
    """Write the minimal effective-Compose surface needed by the MVR-05 fence."""

    import yaml

    try:
        document = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
        services = document.get("services")
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise InventoryError("effective Compose fence input is invalid") from exc
    if not isinstance(services, dict):
        raise InventoryError("effective Compose fence input has no services")

    role_label = "com.agentic-pkm.mvr05.db-role"
    redacted_services: dict[str, object] = {}
    for raw_name, raw_service in services.items():
        if not isinstance(raw_name, str) or not isinstance(raw_service, dict):
            raise InventoryError("effective Compose fence service is malformed")
        labels = raw_service.get("labels")
        if isinstance(labels, dict):
            safe_labels: object = (
                {role_label: labels[role_label]} if role_label in labels else {}
            )
        elif isinstance(labels, list):
            prefix = f"{role_label}="
            safe_labels = [str(item) for item in labels if str(item).startswith(prefix)]
        else:
            safe_labels = {}
        depends_on = raw_service.get("depends_on")
        if isinstance(depends_on, dict):
            safe_dependencies: object = sorted(str(item) for item in depends_on)
        elif isinstance(depends_on, list):
            safe_dependencies = [str(item) for item in depends_on]
        else:
            safe_dependencies = []
        safe_service: dict[str, object] = {
            "labels": safe_labels,
            "depends_on": safe_dependencies,
        }
        role = (
            labels.get(role_label)
            if isinstance(labels, dict)
            else next(
                (
                    str(item).removeprefix(f"{role_label}=")
                    for item in labels or []
                    if str(item).startswith(f"{role_label}=")
                ),
                None,
            )
        )
        if role == "migration-runner":
            safe_service["command"] = raw_service.get("command")
        redacted_services[raw_name] = safe_service

    try:
        metadata = output.lstat()
    except OSError as exc:
        raise InventoryError("effective Compose fence output is unavailable") from exc
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or metadata.st_mode & 0o077
    ):
        raise InventoryError("effective Compose fence output is not private")
    flags = os.O_WRONLY | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(output, flags)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            yaml.safe_dump({"services": redacted_services}, handle, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise InventoryError("effective Compose fence output could not be written") from exc


@dataclass(frozen=True)
class ProcessRecord:
    pid: int
    ppid: int
    pgid: int
    start_token: str
    argv: tuple[str, ...]
    executable_hint: str | None = None


@dataclass(frozen=True)
class LegacyOwnerRecord:
    channel_id: str
    root: str
    # Which of this module's owner sources produced this record (docker_env,
    # docker_app_local, config_env, config_app_local, process_env,
    # native_app_local). Named so a refusal can identify *what* it refused
    # without emitting a raw host path. Defaults to "unknown" only as a
    # safety net; every live construction site below supplies a real value.
    source: str = "unknown"


def _compose_writer_services(compose_path: Path | None = None) -> set[str]:
    """Use the same production-derived MVR-05 fence plan as deployment."""

    root = Path(__file__).resolve().parents[1]
    try:
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        from app.instance.mvr05_cutover import discover_db_producer_fence

        plan = discover_db_producer_fence(compose_path or root / "docker-compose.yaml")
    except Exception as exc:
        raise InventoryError("compose DB producer inventory is incomplete") from exc
    return set(plan.stopped_services)


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
        # ps renders `command=` as argv joined with single spaces. It is display
        # text, not shell syntax, so whitespace splitting is its faithful
        # inverse. A shell lexer here both raises on any argument carrying an
        # unbalanced quote — aborting the whole inventory over one unrelated
        # process — and silently strips quote characters that are literal
        # argument content. Only whitespace-free tokens are consumed downstream
        # by _native_role.
        argv = tuple(command.split())
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


def _read_env_bytes(raw: bytes) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise InventoryError("legacy owner config source is invalid") from exc
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key) is None:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


class _AppLocalMalformed(RuntimeError):
    """Internal marker carrying *why* app-local frontmatter parsing failed.

    Never raised across the module boundary: `_parse_app_local_roots` catches
    this and converts it into a domain/source-qualified `InventoryError`, so
    the reason tags below never leak file content or paths on their own.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _yaml_mapping_entry(raw: str) -> tuple[str, str]:
    quote = ""
    escaped = False
    for index, character in enumerate(raw):
        if escaped:
            escaped = False
            continue
        if quote == '"' and character == "\\":
            escaped = True
            continue
        if character in {"'", '"'}:
            if not quote:
                quote = character
            elif quote == character:
                if quote == "'" and index + 1 < len(raw) and raw[index + 1] == "'":
                    escaped = True
                else:
                    quote = ""
            continue
        if character == ":" and not quote and (index + 1 == len(raw) or raw[index + 1].isspace()):
            return raw[:index].strip(), raw[index + 1 :].strip()
    raise _AppLocalMalformed("mapping-missing-colon")


def _yaml_scalar(raw: str) -> str:
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] == "'":
        return value[1:-1].replace("''", "'")
    if len(value) >= 2 and value[0] == value[-1] == '"':
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError as exc:
            raise _AppLocalMalformed("scalar-invalid-json") from exc
        if isinstance(decoded, str):
            return decoded
    if not value or value[0] in {"'", '"', "[", "{", "&", "*", "!", "|", ">"}:
        raise _AppLocalMalformed("scalar-invalid-syntax")
    return value


def _parse_app_local_roots_body(raw: bytes) -> list[str]:
    try:
        text = raw.decode("utf-8")
        if not text.startswith("---\n") or "\n---\n" not in text[4:]:
            raise ValueError
        frontmatter_text = text[4:].split("\n---\n", 1)[0]
    except (UnicodeDecodeError, ValueError) as exc:
        raise _AppLocalMalformed("frontmatter-malformed") from exc
    roots: list[str] = []
    known_seen = False
    in_known = False
    entry_open = False
    entry_path: str | None = None

    def finish_entry() -> None:
        nonlocal entry_open, entry_path
        if entry_open:
            if not entry_path:
                raise _AppLocalMalformed("entry-missing-path")
            roots.append(entry_path)
        entry_open = False
        entry_path = None

    for raw_line in frontmatter_text.splitlines():
        if "\t" in raw_line:
            raise _AppLocalMalformed("tab-indentation")
        content = raw_line.lstrip(" ")
        if not content or content.startswith("#"):
            continue
        indent = len(raw_line) - len(content)
        if indent == 0:
            finish_entry()
            in_known = False
            key_raw, value = _yaml_mapping_entry(content)
            if _yaml_scalar(key_raw) != "knownVaults":
                continue
            if known_seen:
                raise _AppLocalMalformed("duplicate-known-vaults-key")
            known_seen = True
            if value in {"{}", "{ }"}:
                continue
            if value:
                raise _AppLocalMalformed("known-vaults-unexpected-value")
            in_known = True
            continue
        if not in_known:
            continue
        if indent == 2:
            finish_entry()
            key_raw, value = _yaml_mapping_entry(content)
            _yaml_scalar(key_raw)
            if value:
                raise _AppLocalMalformed("list-item-unexpected-value")
            entry_open = True
            continue
        if indent == 4 and entry_open:
            key_raw, value = _yaml_mapping_entry(content)
            if _yaml_scalar(key_raw) == "path":
                if entry_path is not None:
                    raise _AppLocalMalformed("duplicate-path-key")
                entry_path = _yaml_scalar(value)
            continue
        if indent < 4 or not entry_open:
            raise _AppLocalMalformed("unexpected-indent")
    finish_entry()
    return roots


def _parse_app_local_roots(raw: bytes, *, domain: str, source: str) -> list[str]:
    """Parse app-local frontmatter, naming *what* failed without leaking content.

    `domain` and `source` identify which of this module's four owner sources
    produced the offending record; `reason` is a structural diagnosis of the
    malformed frontmatter shape. Neither carries raw file content or a host
    path, preserving the module's no-raw-path redaction posture.
    """

    try:
        return _parse_app_local_roots_body(raw)
    except _AppLocalMalformed as exc:
        raise InventoryError(
            "legacy app-local owner source is invalid: "
            f"domain={domain} source={source} reason={exc.reason}"
        ) from exc


def _docker_copy_file(container_id: str, path: str) -> bytes | None:
    try:
        result = subprocess.run(
            ["docker", "cp", f"{container_id}:{path}", "-"],
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        raise InventoryError("docker legacy owner source enumeration failed") from exc
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace").lower()
        if "no such file" in stderr or "could not find" in stderr:
            return None
        raise InventoryError("docker legacy owner source enumeration failed")
    try:
        with tarfile.open(fileobj=io.BytesIO(result.stdout), mode="r|*") as archive:
            members = [member for member in archive if member.isfile()]
            if len(members) != 1 or members[0].size > 4 * 1024 * 1024:
                raise InventoryError("docker legacy owner source is invalid")
            extracted = archive.extractfile(members[0])
            if extracted is None:
                raise InventoryError("docker legacy owner source is invalid")
            return extracted.read()
    except (tarfile.TarError, OSError) as exc:
        raise InventoryError("docker legacy owner source is invalid") from exc


def _env_list(values: object) -> dict[str, str]:
    if values is None:
        return {}
    if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
        raise InventoryError("docker legacy owner source inventory is malformed")
    return _read_env_bytes(("\n".join(values) + "\n").encode("utf-8"))


def _translate_container_root(value: str, mounts: object) -> Path | None:
    normalized = posixpath.normpath(value)
    if not normalized.startswith("/") or normalized == "/":
        raise InventoryError("legacy owner root is invalid")
    if not isinstance(mounts, list):
        raise InventoryError("docker legacy owner source inventory is malformed")
    candidates: list[tuple[int, str, str]] = []
    for mount in mounts:
        if not isinstance(mount, dict):
            raise InventoryError("docker legacy owner source inventory is malformed")
        destination = posixpath.normpath(str(mount.get("Destination") or ""))
        source = str(mount.get("Source") or "")
        if not destination.startswith("/") or not source.startswith("/"):
            continue
        if normalized == destination or normalized.startswith(f"{destination}/"):
            candidates.append((len(destination), destination, source))
    if not candidates:
        if normalized == "/app/vault":
            return None
        raise InventoryError("configured container owner root has no host mount")
    _, destination, source = max(candidates)
    relative = normalized[len(destination) :].lstrip("/")
    return Path(source, relative).expanduser().resolve(strict=False)


def _roots_from_values(
    values: dict[str, str],
    *,
    channel: str,
    mounts: object | None = None,
) -> list[Path]:
    host_root = values.get("VAULT_HOST_ROOT", "").strip()
    candidates = [
        values.get("VAULT_ROOT", ""),
        values.get(f"VAULT_ROOT_{channel.upper()}", ""),
        values.get("WATCHER_VAULT_PATH", ""),
    ]
    roots: list[Path] = []
    if host_root:
        if "$" in host_root:
            raise InventoryError("legacy owner config contains an unresolved root")
        host_path = Path(host_root).expanduser()
        if not host_path.is_absolute():
            raise InventoryError("legacy owner root is not absolute")
        roots.append(host_path.resolve(strict=False))
    for raw in candidates:
        value = raw.strip()
        if not value or (value == "/app/vault" and mounts is None):
            continue
        if "$" in value:
            raise InventoryError("legacy owner config contains an unresolved root")
        if mounts is None:
            candidate = Path(value).expanduser()
            if not candidate.is_absolute():
                raise InventoryError("legacy owner root is not absolute")
            roots.append(candidate.resolve(strict=False))
        else:
            translated = _translate_container_root(value, mounts)
            if translated is not None:
                roots.append(translated)
    return list(dict.fromkeys(roots))


def _canonical_mounts(mounts: object) -> object:
    # docker inspect does not guarantee an ordering for Mounts, and json.dumps
    # sorts dict keys but not list elements. Hashing the array verbatim therefore
    # makes the two-snapshot stability check in produce_legacy_owners fail on
    # unchanged host state. Only the digest input is canonicalized; root
    # translation keeps consuming the payload exactly as docker returned it.
    if not isinstance(mounts, list):
        return mounts
    return sorted(mounts, key=lambda entry: json.dumps(entry, sort_keys=True))


def _docker_legacy_owner_sources() -> tuple[list[LegacyOwnerRecord], list[str]]:
    ids_output = _run_checked(
        ["docker", "ps", "-a", "--no-trunc", "--format", "{{.ID}}"],
        label="docker legacy owner source enumeration",
    )
    ids = [line.strip() for line in ids_output.splitlines() if line.strip()]
    if any(re.fullmatch(r"[0-9a-f]{12,64}", item) is None for item in ids) or len(ids) != len(
        set(ids)
    ):
        raise InventoryError("docker legacy owner source inventory is malformed")
    if not ids:
        return [], ["docker:empty"]
    output = _run_checked(
        ["docker", "inspect", *ids], label="docker legacy owner source enumeration"
    )
    try:
        payload = json.loads(output)
    except json.JSONDecodeError as exc:
        raise InventoryError("docker legacy owner source inventory is malformed") from exc
    if not isinstance(payload, list) or len(payload) != len(ids):
        raise InventoryError("docker legacy owner source inventory is malformed")
    owners: list[LegacyOwnerRecord] = []
    fingerprints: list[str] = []
    stores: dict[tuple[str, str, str], bytes | None] = {}
    inspected_ids: set[str] = set()
    for item in payload:
        if not isinstance(item, dict):
            raise InventoryError("docker legacy owner source inventory is malformed")
        container_id = str(item.get("Id") or "")
        config = item.get("Config")
        mounts = item.get("Mounts")
        if container_id not in ids or not isinstance(config, dict):
            raise InventoryError("docker legacy owner source inventory is malformed")
        if container_id in inspected_ids:
            raise InventoryError("docker legacy owner source inventory is malformed")
        inspected_ids.add(container_id)
        labels = config.get("Labels") or {}
        if not isinstance(labels, dict):
            raise InventoryError("docker legacy owner source inventory is malformed")
        project = labels.get("com.docker.compose.project")
        service = labels.get("com.docker.compose.service")
        if project not in COMPOSE_PROJECT_DOMAINS or service not in _compose_writer_services():
            continue
        channel = COMPOSE_PROJECT_DOMAINS[str(project)]
        values = _env_list(config.get("Env"))
        for root in _roots_from_values(values, channel=channel, mounts=mounts):
            owners.append(LegacyOwnerRecord(channel, str(root), source="docker_env"))
        store_path = values.get("DESIGN_HANDOFF_APP_LOCAL_SETTINGS", "").strip()
        if not store_path:
            store_path = (
                "/app/tmp-test/agentic-pkm/app-local.md"
                if channel == "test"
                else "/app/tmp/agentic-pkm/app-local.md"
            )
        canonical_mounts = _canonical_mounts(mounts)
        store_key = (channel, store_path, json.dumps(canonical_mounts, sort_keys=True))
        if store_key not in stores:
            stores[store_key] = _docker_copy_file(container_id, store_path)
        raw_store = stores[store_key]
        if raw_store is not None:
            for root in _parse_app_local_roots(raw_store, domain=channel, source="docker_app_local"):
                translated = _translate_container_root(root, mounts)
                if translated is None:
                    raise InventoryError("legacy app-local owner root has no host mount")
                owners.append(LegacyOwnerRecord(channel, str(translated), source="docker_app_local"))
        fingerprints.append(
            hashlib.sha256(
                json.dumps(
                    {
                        "channel": channel,
                        "service": service,
                        "env": values,
                        "mounts": canonical_mounts,
                        "store": None
                        if raw_store is None
                        else hashlib.sha256(raw_store).hexdigest(),
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
        )
    if inspected_ids != set(ids):
        raise InventoryError("docker legacy owner source inventory is malformed")
    return owners, sorted(fingerprints)


def _read_source(path: Path, *, required: bool) -> bytes | None:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        if required:
            raise InventoryError("required legacy owner config source is missing")
        return None
    except OSError as exc:
        raise InventoryError("legacy owner config source is unreadable") from exc
    if not stat.S_ISREG(metadata.st_mode) or path.is_symlink():
        raise InventoryError("legacy owner config source is unsafe")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise InventoryError("legacy owner config source is unreadable") from exc


def _can_host_app_local(directory: Path) -> bool:
    probe = directory
    while True:
        if probe.exists():
            return probe.is_dir() and os.access(probe, os.W_OK)
        parent = probe.parent
        if parent == probe:
            return False
        probe = parent


def _native_app_local_settings_path() -> tuple[Path, bool]:
    override = os.getenv("DESIGN_HANDOFF_APP_LOCAL_SETTINGS", "").strip()
    if override:
        if "$" in override:
            raise InventoryError("legacy owner config contains an unresolved source")
        return Path(override).expanduser().resolve(strict=False), True
    xdg_data = os.getenv("XDG_DATA_HOME", "").strip()
    if xdg_data:
        xdg_base = Path(xdg_data).expanduser() / "Agentic PKM"
        if _can_host_app_local(xdg_base):
            return (xdg_base / "app-local.md").resolve(strict=False), False
    home_env = os.getenv("HOME", "").strip()
    try:
        home = Path(home_env) if home_env else Path.home()
    except (RuntimeError, OSError):
        home = None
    if home is not None and str(home) != home.anchor:
        home_base = home / "Library" / "Application Support" / "Agentic PKM"
        if _can_host_app_local(home_base):
            return (home_base / "app-local.md").resolve(strict=False), False
    container_base = Path("/app/tmp/agentic-pkm")
    if _can_host_app_local(container_base):
        return (container_base / "app-local.md").resolve(strict=False), False
    return (Path(tempfile.gettempdir()) / "agentic-pkm" / "app-local.md").resolve(
        strict=False
    ), False


def _config_legacy_owner_sources(
    repo_root: Path, *, active_channel: str
) -> tuple[list[LegacyOwnerRecord], list[str]]:
    root = repo_root.expanduser().resolve(strict=True)
    known: list[tuple[str, Path, bool]] = []
    for channel in ("dev", "test", "prod"):
        known.extend(
            [
                (channel, root / f".env.{channel}.local", False),
                (channel, root / "config" / "deploy" / f"{channel}.env", False),
            ]
        )
    known.extend([("native", root / ".env", False), ("native", root / ".env.native.local", False)])
    current_runtime_ref = os.getenv("WATCHER_RUNTIME_ENV_FILE", "").strip()
    if current_runtime_ref:
        if "$" in current_runtime_ref:
            raise InventoryError("legacy owner config contains an unresolved source")
        current_runtime_path = Path(current_runtime_ref).expanduser()
        if not current_runtime_path.is_absolute():
            current_runtime_path = root / current_runtime_path
        known.append((active_channel, current_runtime_path.resolve(strict=False), True))
    extra = os.getenv("INSTANCE_LEGACY_OWNER_CONFIG_PATHS", "").strip()
    if extra:
        for item in extra.split(os.pathsep):
            if not item:
                raise InventoryError("legacy owner config source list is invalid")
            known.append((active_channel, Path(item).expanduser().resolve(strict=False), True))
    owners: list[LegacyOwnerRecord] = []
    fingerprints: list[str] = []
    seen_sources: set[tuple[str, str]] = set()
    runtime_ref_channels = {active_channel} if current_runtime_ref else set()
    default_runtime_checked = False
    pending = list(known)
    while pending or not default_runtime_checked:
        if not pending:
            default_runtime_checked = True
            if active_channel not in runtime_ref_channels:
                pending.append((active_channel, root / "tmp" / "runtime.env", False))
            continue
        channel, path, required = pending.pop(0)
        key = (channel, str(path))
        if key in seen_sources:
            continue
        seen_sources.add(key)
        raw = _read_source(path, required=required)
        fingerprints.append(
            hashlib.sha256(f"{channel}\0{path}\0".encode() + (raw or b"<absent>")).hexdigest()
        )
        if raw is None:
            continue
        values = _read_env_bytes(raw)
        for owner_root in _roots_from_values(values, channel=channel):
            owners.append(LegacyOwnerRecord(channel, str(owner_root), source="config_env"))
        runtime_ref = values.get("WATCHER_RUNTIME_ENV_FILE", "").strip()
        if runtime_ref:
            if "$" in runtime_ref:
                raise InventoryError("legacy owner config contains an unresolved source")
            runtime_path = Path(runtime_ref).expanduser()
            if not runtime_path.is_absolute():
                runtime_path = root / runtime_path
            runtime_ref_channels.add(channel)
            pending.append((channel, runtime_path.resolve(strict=False), True))
        app_local = values.get("DESIGN_HANDOFF_APP_LOCAL_SETTINGS", "").strip()
        if app_local and not app_local.startswith("/app/"):
            if "$" in app_local:
                raise InventoryError("legacy owner config contains an unresolved source")
            app_local_path = Path(app_local).expanduser().resolve(strict=False)
            app_local_raw = _read_source(app_local_path, required=True)
            assert app_local_raw is not None
            fingerprints.append(
                hashlib.sha256(
                    f"{channel}\0{app_local_path}\0".encode() + app_local_raw
                ).hexdigest()
            )
            owners.extend(
                LegacyOwnerRecord(channel, root_path, source="config_app_local")
                for root_path in _parse_app_local_roots(
                    app_local_raw, domain=channel, source="config_app_local"
                )
            )
    current_bindings: dict[str, dict[str, str]] = {
        active_channel: {
            name: os.environ[name]
            for name in ("VAULT_HOST_ROOT", "VAULT_ROOT", "WATCHER_VAULT_PATH")
            if name in os.environ
        }
    }
    for channel in ("dev", "test", "prod"):
        name = f"VAULT_ROOT_{channel.upper()}"
        if name in os.environ:
            current_bindings.setdefault(channel, {})[name] = os.environ[name]
    fingerprints.append(
        hashlib.sha256(json.dumps(current_bindings, sort_keys=True).encode()).hexdigest()
    )
    for channel, values in current_bindings.items():
        owners.extend(
            LegacyOwnerRecord(channel, str(path), source="process_env")
            for path in _roots_from_values(values, channel=channel)
        )
    native_app_local, native_required = _native_app_local_settings_path()
    native_raw = _read_source(native_app_local, required=native_required)
    fingerprints.append(
        hashlib.sha256(
            f"native\0{native_app_local}\0".encode() + (native_raw or b"<absent>")
        ).hexdigest()
    )
    if native_raw is not None:
        owners.extend(
            LegacyOwnerRecord("native", root_path, source="native_app_local")
            for root_path in _parse_app_local_roots(
                native_raw, domain="native", source="native_app_local"
            )
        )
    return owners, sorted(fingerprints)


def _owner_identity_material(root: Path, *, domain: str, source: str) -> tuple[str, frozenset[str]]:
    resolved = root.expanduser().resolve(strict=False)
    # A stable digest of the resolved path, not the path itself: enough to
    # correlate the same offending root across two runs of the inventory
    # without emitting a raw host path in the refusal.
    redacted_id = _digest_token("root", str(resolved))
    try:
        metadata = os.stat(resolved)
    except OSError as exc:
        raise InventoryError(
            "legacy owner root is missing or invalid: "
            f"domain={domain} source={source} reason=vanished id={redacted_id}"
        ) from exc
    if not stat.S_ISDIR(metadata.st_mode):
        raise InventoryError(
            "legacy owner root is missing or invalid: "
            f"domain={domain} source={source} reason=not-a-directory id={redacted_id}"
        )
    primary = f"inode:{metadata.st_dev}:{metadata.st_ino}"
    ancestors: set[str] = set()
    for ancestor in resolved.parents:
        try:
            ancestor_metadata = os.stat(ancestor)
        except OSError as exc:
            raise InventoryError(
                "legacy owner ancestor identity is unavailable: "
                f"domain={domain} source={source} id={redacted_id}"
            ) from exc
        ancestors.add(f"inode:{ancestor_metadata.st_dev}:{ancestor_metadata.st_ino}")
    return primary, frozenset(ancestors)


def _normalize_legacy_owners(
    records: list[LegacyOwnerRecord],
) -> tuple[list[LegacyOwnerRecord], list[dict[str, str]]]:
    normalized: dict[tuple[str, str], tuple[LegacyOwnerRecord, frozenset[str]]] = {}
    for record in records:
        if record.channel_id not in DOMAINS:
            raise InventoryError(
                f"legacy owner domain is invalid: domain={record.channel_id} source={record.source}"
            )
        root = Path(record.root).expanduser().resolve(strict=False)
        primary, ancestors = _owner_identity_material(
            root, domain=record.channel_id, source=record.source
        )
        normalized.setdefault(
            (record.channel_id, primary),
            (LegacyOwnerRecord(record.channel_id, str(root), source=record.source), ancestors),
        )
    values = [
        (record, primary, ancestors)
        for (_, primary), (record, ancestors) in normalized.items()
    ]
    for index, (left, left_primary, left_ancestors) in enumerate(values):
        for right, right_primary, right_ancestors in values[index + 1 :]:
            if left.channel_id == right.channel_id:
                continue
            if (
                left_primary == right_primary
                or left_primary in right_ancestors
                or right_primary in left_ancestors
            ):
                shared_id = (
                    left_primary
                    if left_primary == right_primary or left_primary in right_ancestors
                    else right_primary
                )
                raise InventoryError(
                    "legacy owner roots collide across domains: "
                    f"domain_a={left.channel_id} domain_b={right.channel_id} id={shared_id}"
                )
    ordered = sorted(values, key=lambda item: (item[0].channel_id, item[0].root))
    return (
        [item[0] for item in ordered],
        [
            {
                "channel_id": record.channel_id,
                "root": record.root,
                "identity": primary,
            }
            for record, primary, _ in ordered
        ],
    )


def _legacy_owner_snapshot(repo_root: Path, *, active_channel: str) -> dict[str, object]:
    if active_channel not in {"dev", "test", "prod"}:
        raise InventoryError("legacy owner active channel is invalid")
    docker_owners, docker_fingerprints = _docker_legacy_owner_sources()
    config_owners, config_fingerprints = _config_legacy_owner_sources(
        repo_root, active_channel=active_channel
    )
    owners, owner_identities = _normalize_legacy_owners(docker_owners + config_owners)
    # `source` is diagnostic-only context for InventoryError messages; keep the
    # persisted receipt schema unchanged so existing consumers are unaffected.
    owner_rows = [
        {"channel_id": record.channel_id, "root": record.root} for record in owners
    ]
    source_evidence = {
        "docker": docker_fingerprints,
        "config": config_fingerprints,
        "owners": owner_rows,
        "owner_identities": owner_identities,
    }
    source_digest = hashlib.sha256(
        json.dumps(
            source_evidence,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return {
        "source_digest": source_digest,
        "source_evidence": source_evidence,
        "owners": owner_rows,
    }


def produce_legacy_owners(*, repo_root: Path, active_channel: str, output: Path) -> None:
    first = _legacy_owner_snapshot(repo_root, active_channel=active_channel)
    _test_sync(
        "INSTANCE_STATE_OWNER_INVENTORY_TEST_BETWEEN_READY_FD",
        "INSTANCE_STATE_OWNER_INVENTORY_TEST_BETWEEN_CONTINUE_FD",
    )
    second = _legacy_owner_snapshot(repo_root, active_channel=active_channel)
    if first != second:
        raise InventoryError("legacy owner sources are incomplete or racing")
    _write_inventory(
        output,
        {
            "schema": LEGACY_OWNER_INVENTORY_SCHEMA,
            "inventory_complete": True,
            "writers_drained": False,
            "source_probe_count": 2,
            "validated_after_quiescence": False,
            **first,
        },
    )


def validate_legacy_owners(
    *, repo_root: Path, active_channel: str, inventory: Path, output: Path
) -> None:
    try:
        metadata = inventory.lstat()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_mode & 0o777 != 0o600
        ):
            raise ValueError
        baseline = json.loads(inventory.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise InventoryError("legacy owner baseline inventory is invalid") from exc
    if (
        not isinstance(baseline, dict)
        or baseline.get("schema") != LEGACY_OWNER_INVENTORY_SCHEMA
        or baseline.get("inventory_complete") is not True
        or baseline.get("writers_drained") is not False
        or baseline.get("source_probe_count") != 2
        or baseline.get("validated_after_quiescence") is not False
        or not isinstance(baseline.get("source_digest"), str)
        or not isinstance(baseline.get("source_evidence"), dict)
        or not isinstance(baseline.get("owners"), list)
    ):
        raise InventoryError("legacy owner baseline inventory is invalid")
    first = _legacy_owner_snapshot(repo_root, active_channel=active_channel)
    second = _legacy_owner_snapshot(repo_root, active_channel=active_channel)
    if (
        first != second
        or baseline.get("source_digest") != first["source_digest"]
        or baseline.get("source_evidence") != first["source_evidence"]
        or baseline.get("owners") != first["owners"]
    ):
        raise InventoryError("legacy owner sources are incomplete or racing")
    _write_inventory(
        output,
        {
            "schema": LEGACY_OWNER_INVENTORY_SCHEMA,
            "inventory_complete": True,
            "writers_drained": True,
            "source_probe_count": 2,
            "validated_after_quiescence": True,
            **first,
        },
    )


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
        if argv[2] == "app.workers.outbox_worker":
            return "outbox-worker"
        if argv[2] == "uvicorn":
            return "uvicorn"
        if argv[2] == "celery":
            return "celery"
        if len(argv) >= 5 and argv[2:5] == ("app.cli", "watcher", "run"):
            return "watcher"
        if len(argv) >= 5 and argv[2:5] == ("app.cli", "heimdal", "capture-watch"):
            return "heimdal-capture-watch"
        if argv[2].startswith("app."):
            # Future app modules are potential DB producers until classified.
            # The PostgreSQL session fence is the final proof, but the native
            # census must not silently discard an unfamiliar producer argv.
            return "app-python-module"
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
        if project not in COMPOSE_PROJECT_DOMAINS or service not in _compose_writer_services():
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
    controller_pgid: int,
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
        # A running deployment forks subshells (e.g. `deploy_channel_compose()`
        # runs its body in `( ... )`) that inherit the launcher argv but are not
        # the controller pid itself. Those forks stay in the controller's own
        # process group, so excluding launcher-role processes by process-group
        # membership covers the controller's whole tree without exempting a
        # foreign deployment, which runs in its own process group. Scope this
        # to launcher roles only -- a non-launcher native writer (watcher,
        # worker, uvicorn, celery, heimdal capture-watch) that happens to share
        # a process group must still be reported.
        if role in LAUNCHER_ROLES and process.pgid == controller_pgid:
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
        controller_pgid=controller.pgid,
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
    produce = subparsers.add_parser("produce-legacy-owners")
    produce.add_argument("--repo-root", type=Path, required=True)
    produce.add_argument("--active-channel", required=True)
    produce.add_argument("--output", type=Path, required=True)
    validate = subparsers.add_parser("validate-legacy-owners")
    validate.add_argument("--repo-root", type=Path, required=True)
    validate.add_argument("--active-channel", required=True)
    validate.add_argument("--inventory", type=Path, required=True)
    validate.add_argument("--output", type=Path, required=True)
    fence_plan = subparsers.add_parser("compose-fence-plan")
    fence_plan.add_argument("--compose-path", type=Path, required=True)
    fence_plan.add_argument("--receipt-output", type=Path)
    redact_fence = subparsers.add_parser("redact-compose-fence-config")
    redact_fence.add_argument("--compose-path", type=Path, required=True)
    redact_fence.add_argument("--output", type=Path, required=True)
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
        if args.command == "produce-legacy-owners":
            produce_legacy_owners(
                repo_root=args.repo_root,
                active_channel=args.active_channel,
                output=args.output,
            )
            return 0
        if args.command == "validate-legacy-owners":
            validate_legacy_owners(
                repo_root=args.repo_root,
                active_channel=args.active_channel,
                inventory=args.inventory,
                output=args.output,
            )
            return 0
        if args.command == "compose-fence-plan":
            root = Path(__file__).resolve().parents[1]
            if str(root) not in sys.path:
                sys.path.insert(0, str(root))
            from app.instance.mvr05_cutover import discover_db_producer_fence

            plan = discover_db_producer_fence(args.compose_path)
            if args.receipt_output is not None:
                args.receipt_output.write_text(
                    json.dumps(plan.as_payload(), sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                os.chmod(args.receipt_output, 0o600)
            print(" ".join(sorted(plan.stopped_services)))
            return 0
        if args.command == "redact-compose-fence-config":
            redact_compose_fence_config(args.compose_path, args.output)
            return 0
    except InventoryError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    raise AssertionError("unreachable")


if __name__ == "__main__":
    raise SystemExit(main())
