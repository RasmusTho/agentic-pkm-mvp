from __future__ import annotations

import errno
import hashlib
import json
import logging
import os
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import timezone, datetime
from pathlib import Path
from uuid import uuid4

import yaml

from app.agents.panel.agent import handle_note_update
from app.agents.panel_agent.policy import watcher_panel_candidate_for_path
from app.components.concurrency import OptimisticWriteGuard, VersionMismatch
from app.events.schema import OutboxEvent
from app.events.types import INGEST_VAULT_CHANGED, PANEL_SCAN_REQUESTED
from app.services.note_uuid import ensure_note_uuid
from app.services.outbox import append_jsonl_outbox_event, insert_object_and_outbox, write_outbox_event
from app.settings.panel_actions import PanelActionMapping, load_panel_action_mappings
from app.settings.tiering import resolve_dev_lab_env_typed, resolve_dev_lab_env_value
from app.settings.watcher_settings import load_watcher_settings, resolve_auto_exec_enabled
from app.vault.manager import VaultManager
from app.vault.manager import iter_vault_markdown_files
from app.vault.layout import load_layout
from app.watcher.events import emit_watcher_run_event
from app.watcher.heartbeat import resolve_heartbeat_path, write_registry_heartbeat
from app.watcher.scope import derive_scope_roots, matches_scope
from app.watcher.settings_delta import handle_settings_local_delta
from app.watcher.state import WatcherState
from app.write_guard import DEFAULT_WRITE_GUARD
from scripts.yaml_roundtrip import load_frontmatter

_TRUE_VALUES = {"1", "true", "yes", "on"}

DEFAULT_SCOPE_GLOB = "*.md,**/*.md"

MIN_TICK_SLEEP_SECONDS = 0.05

_WRITE_GUARD = OptimisticWriteGuard()

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChangedEntry:
    rel_path: Path
    mtime: float
    digest: str


def _detect_inbox_dir(vault_root: Path) -> str:
    env_value = os.getenv("VAULT_INBOX_DIR_REL")
    if env_value:
        return env_value
    if not vault_root.exists():
        raise FileNotFoundError(f"Vault root not found: {vault_root}")
    layout = load_layout(vault_root)
    return layout.inbox_folder


def _resolve_scope_glob(vault_root: Path) -> tuple[str, str, str]:
    """Resolve watcher scope_glob with explicit provenance.

    Returns: (scope_glob, scope_source, inbox_source)
    - scope_source: env | default
    - inbox_source: unused (kept for backwards-compatible logs/tests)
    """

    scope_env = (os.getenv("WATCHER_SCOPE_GLOB") or "").strip()
    if scope_env:
        return scope_env, "env:WATCHER_SCOPE_GLOB", ""

    del vault_root
    return DEFAULT_SCOPE_GLOB, "default:vaultwide", ""


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _hash_file(path: Path) -> tuple[str, int] | None:
    try:
        data = path.read_bytes()
    except Exception:
        return None
    return hashlib.sha256(data).hexdigest(), len(data)


def _matches_scope(rel_path: Path, scope_glob: str) -> bool:
    return matches_scope(rel_path, scope_glob)


def _derive_scan_root(vault_root: Path, scope_glob: str) -> Path:
    return derive_scope_roots(vault_root, scope_glob)[0]


def _scan_markdown_many(
    vault_root: Path,
    scan_roots: Iterable[Path],
    scope_glob: str,
) -> Iterable[tuple[Path, float, Path]]:
    seen: set[Path] = set()
    for scan_root in scan_roots:
        for path in iter_vault_markdown_files(vault_root, subtree_root=scan_root):
            try:
                rel = path.relative_to(vault_root)
            except Exception:
                continue
            if any(part.startswith(".") for part in rel.parts):
                continue
            if rel in seen or not _matches_scope(rel, scope_glob):
                continue
            try:
                mtime = path.stat().st_mtime
            except Exception:
                continue
            seen.add(rel)
            yield rel, mtime, path


def _now_iso_from_timestamp(value: float) -> str:
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _log_tick_diagnostics_registry(
    cfg: RegistryConfig,
    summary: dict[str, object],
    scan_root: Path | None,
    watcher_name: str,
) -> None:
    payload: dict[str, object | None] = {
        "timestamp": summary.get("tick_start_ts"),
        "watcher_name": watcher_name,
        "scope_glob": summary.get("scope_glob") or cfg.scope_glob,
        "scan_root": str(scan_root) if scan_root is not None else None,
        "scanned_files": summary.get("scanned_files", 0),
        "hashed_files": summary.get("hashed_files", 0),
        "bytes_read": summary.get("bytes_read", 0),
        "changed_files": summary.get("changed_in_tick", 0),
        "emitted_events": summary.get("emitted_in_tick", 0),
        "elapsed_ms": summary.get("tick_ms"),
        "panel_candidates": summary.get("panel_candidates", 0),
        "panel_skipped_policy": summary.get("panel_skipped_policy", 0),
        "panel_skipped_auto_exec": summary.get("panel_skipped_auto_exec", 0),
        "bad_tick": summary.get("bad_tick", False),
        "bad_reason": summary.get("bad_tick_reason"),
        "chosen_sleep_seconds": summary.get("chosen_sleep_seconds"),
        "kill_switch": summary.get("kill_switch", False),
        "thresholds": summary.get("thresholds"),
        "stop_reason": summary.get("stop_reason"),
    }
    try:
        cfg.tick_log_path.parent.mkdir(parents=True, exist_ok=True)
        with cfg.tick_log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False))
            handle.write("\n")
    except Exception:
        return


def _trip_stop_file(cfg: RegistryConfig, summary: dict[str, object]) -> None:
    msg = (
        "WATCHER_STOP_TRIPPED: "
        f"scanned={summary.get('scanned_files')} bytes={summary.get('bytes_read')}"
        f" emit={summary.get('emitted_in_tick')} thresholds="
        f"scanned={cfg.max_scanned_files_per_tick} bytes={cfg.max_bytes_read_per_tick}"
        f" elapsed={cfg.max_elapsed_ms_per_tick} bad_ticks={cfg.max_bad_ticks}"
    )
    if not cfg.stop_file.exists():
        print(msg)
        cfg.stop_file.parent.mkdir(parents=True, exist_ok=True)
        cfg.stop_file.write_text(msg + "\n", encoding="utf-8")
    summary["stop_reason"] = msg


def _apply_guardrails_registry(cfg: RegistryConfig, state: WatcherState, summary: dict[str, object]) -> None:
    thresholds = {
        "max_scanned_files_per_tick": cfg.max_scanned_files_per_tick,
        "max_bytes_read_per_tick": cfg.max_bytes_read_per_tick,
        "max_elapsed_ms_per_tick": cfg.max_elapsed_ms_per_tick,
        "max_bad_ticks": cfg.max_bad_ticks,
        "bad_tick_backoff_seconds": cfg.bad_tick_backoff_seconds,
    }
    summary["thresholds"] = thresholds
    scanned = int(summary.get("scanned_files", 0))
    bytes_read = int(summary.get("bytes_read", 0))
    elapsed = int(summary.get("tick_ms", 0))
    errors = int(summary.get("errors_in_tick", 0))
    bad_reason: str | None = None
    if scanned >= cfg.max_scanned_files_per_tick:
        bad_reason = "too_many_files"
    elif bytes_read >= cfg.max_bytes_read_per_tick:
        bad_reason = "too_many_bytes"
    elif elapsed >= cfg.max_elapsed_ms_per_tick:
        bad_reason = "too_slow"
    elif errors:
        bad_reason = "errors"
    if bad_reason:
        state.bad_ticks += 1
        summary["bad_tick"] = True
        summary["bad_tick_reason"] = bad_reason
        sleep_seconds = cfg.tick_sleep_seconds + cfg.bad_tick_backoff_seconds * state.bad_ticks
        summary["chosen_sleep_seconds"] = sleep_seconds
        state.dynamic_sleep_seconds = sleep_seconds
        if state.bad_ticks >= cfg.max_bad_ticks:
            summary["stop_tripped"] = True
            _trip_stop_file(cfg, summary)
    else:
        state.bad_ticks = 0
        summary["bad_tick"] = False
        summary["bad_tick_reason"] = None
        state.dynamic_sleep_seconds = None
        summary["chosen_sleep_seconds"] = cfg.tick_sleep_seconds


def _finalize_spec_tick(
    cfg: RegistryConfig,
    state: WatcherState,
    summary: dict[str, object],
    tick_start: float,
    scan_root: Path | None,
    watcher_name: str,
) -> dict[str, object]:
    if "tick_ms" not in summary:
        summary["tick_ms"] = max(int((time.time() - tick_start) * 1000), 0)
    summary["elapsed_ms"] = summary["tick_ms"]
    summary.setdefault("tick_start_ts", _now_iso_from_timestamp(tick_start))
    summary.setdefault("chosen_sleep_seconds", state.dynamic_sleep_seconds or cfg.tick_sleep_seconds)
    try:
        _log_tick_diagnostics_registry(cfg, summary, scan_root, watcher_name)
        _emit_registry_watcher_run_event(cfg, summary, watcher_name)
    finally:
        state.save(_state_path(cfg.state_dir, watcher_name))
    return summary


def _emit_registry_watcher_run_event(
    cfg: RegistryConfig,
    summary: dict[str, object],
    watcher_name: str,
) -> None:
    """Emit a watcher.run event to the DEDICATED telemetry log.

    NOTE: uses cfg.watcher_run_log (not cfg.outbox_path / index-outbox.jsonl).
    Per-tick watcher.run writes must not land in the index/embedding audit sink.
    """
    try:
        run_summary = {
            "changed": summary.get("changed_in_tick", 0),
            "ingest_attempted": summary.get("ingest_attempted", 0),
            "ingested": summary.get("ingested", 0),
            "panel_candidates": summary.get("panel_candidates", 0),
            "panel_runs": summary.get("panel_runs_in_tick", 0),
            "panel_promotions": 0,
            "panel_skipped_policy": summary.get("panel_skipped_policy", 0),
            "panel_skipped_limit": 0,
            "panel_skipped_auto_exec": summary.get("panel_skipped_auto_exec", 0),
            "errors": summary.get("errors_in_tick", 0),
            "dry_run": False,
            "limit_exceeded": bool(summary.get("stop_tripped")),
            "snapshot_path": "",
            "vault_root": str(cfg.vault_path),
        }
        emit_watcher_run_event(
            run_summary,
            vault_root=cfg.vault_path,
            snapshot_path=None,
            telemetry_log_path=cfg.watcher_run_log,
            trigger=f"registry:{watcher_name}",
        )
    except Exception:
        pass


def _write_jsonl_event(event: OutboxEvent, outbox_path: Path) -> None:
    append_jsonl_outbox_event(outbox_path, event, default_source="watcher.registry")


def _write_markdown_if_changed(note_path: Path, original: str, updated: str) -> bool:
    if original == updated:
        return False
    expected_version = _WRITE_GUARD.compute_version(original.encode("utf-8"))
    DEFAULT_WRITE_GUARD.assert_writes_allowed("panel watcher update")
    try:
        _WRITE_GUARD.write_if_unchanged(note_path, expected_version, updated)
        return True
    except VersionMismatch:
        return False


def _read_panel_note_with_retry(note_path: Path, *, attempts: int = 5, base_sleep: float = 0.2) -> str:
    for attempt in range(attempts):
        try:
            return note_path.read_text(encoding="utf-8")
        except OSError as exc:
            if exc.errno in {errno.ENOENT, errno.EPERM, errno.EACCES, errno.EROFS} and attempt + 1 < attempts:
                time.sleep(base_sleep * (2**attempt))
                continue
            raise
    raise FileNotFoundError(note_path)


def _ensure_panel_note_uuid_with_retry(
    note_path: Path,
    *,
    vault_root: Path,
    attempts: int = 5,
    base_sleep: float = 0.2,
) -> str:
    for attempt in range(attempts):
        try:
            return ensure_note_uuid(note_path, vault_root=vault_root)
        except OSError as exc:
            if exc.errno in {errno.ENOENT, errno.EPERM, errno.EACCES, errno.EROFS} and attempt + 1 < attempts:
                time.sleep(base_sleep * (2**attempt))
                continue
            raise
    raise FileNotFoundError(note_path)


def _process_panel_note(
    *,
    vault_root: Path,
    rel_path: Path,
    outbox_path: Path,
    state: WatcherState,
    action_mappings: Mapping[str, PanelActionMapping],
) -> int:
    note_path = vault_root / rel_path
    logger.info(
        "panel note start relative_path=%s note_path=%s",
        str(rel_path),
        str(note_path),
    )
    try:
        markdown = _read_panel_note_with_retry(note_path)
    except Exception as exc:
        state.errors += 1
        print(f"WARN: failed to read panel note {note_path}: {exc}")
        return 0

    try:
        note_uuid = _ensure_panel_note_uuid_with_retry(note_path, vault_root=vault_root)
    except Exception as exc:
        state.errors += 1
        print(f"WARN: failed to ensure uuid for {note_path}: {exc}")
        return 0

    frontmatter, _ = load_frontmatter(markdown)
    note_title = frontmatter.get("title") if isinstance(frontmatter, dict) else None

    try:
        result = handle_note_update(
            note_id=note_uuid,
            old_markdown=markdown,
            new_markdown=markdown,
            action_mappings=action_mappings,
            note_path=str(note_path),
            proactive_assist=True,
        )
    except Exception as exc:
        state.errors += 1
        print(f"WARN: panel agent failed for {note_path}: {exc}")
        return 0

    try:
        _write_markdown_if_changed(note_path, markdown, result.updated_markdown)
    except Exception as exc:
        state.errors += 1
        print(f"WARN: failed to write panel updates for {note_path}: {exc}")

    for event in result.events:
        try:
            write_outbox_event(event)
        except Exception:
            state.enqueue_failures_total += 1
            logger.exception(
                "watcher db outbox enqueue failed topic=%s trace_id=%s note_path=%s relative_path=%s",
                event.event,
                getattr(event, "trace_id", ""),
                str(note_path),
                str(rel_path),
            )
        try:
            _write_jsonl_event(event, outbox_path)
        except Exception as exc:
            print(f"WARN: failed to append JSONL outbox event {event.event}: {exc}")
    emitted_events = len(result.events)
    if emitted_events <= 0:
        logger.info(
            "panel note no events relative_path=%s note_path=%s note_uuid=%s",
            str(rel_path),
            str(note_path),
            note_uuid,
        )
        return 0
    logger.info(
        "panel note emitted relative_path=%s note_path=%s note_uuid=%s events=%s wrote_markdown=%s",
        str(rel_path),
        str(note_path),
        note_uuid,
        ",".join(getattr(event, "event", "") for event in result.events),
        result.updated_markdown != markdown,
    )
    return emitted_events



@dataclass
class WatcherSpec:
    name: str
    scope_glob: str
    debounce_ms: int
    rate_limit_per_min: int
    emit_event: str
    backoff_seconds: int = 10

    @classmethod
    def from_dict(cls, raw: Mapping[str, object]) -> "WatcherSpec":
        return cls(
            name=str(raw.get("name")),
            scope_glob=str(raw.get("scope_glob")),
            debounce_ms=int(raw.get("debounce_ms", 1000)),
            rate_limit_per_min=int(raw.get("rate_limit_per_min", 60)),
            emit_event=str(raw.get("emit_event", "ingest.vault.changed")),
            backoff_seconds=int(raw.get("backoff_seconds", 10)),
        )


@dataclass
class RegistryConfig:
    enable: bool
    outbox_path: Path
    vault_path: Path
    scope_glob: str
    debounce_ms: int
    rate_limit_per_min: int
    state_dir: Path
    heartbeat_path: Path
    config_path: Path
    summary_interval: int
    stop_file: Path
    tick_sleep_seconds: float
    tick_log_path: Path
    max_scanned_files_per_tick: int
    max_bytes_read_per_tick: int
    max_elapsed_ms_per_tick: int
    max_bad_ticks: int
    bad_tick_backoff_seconds: float
    specs: list[WatcherSpec]
    # Dedicated telemetry sink for watcher.run events — separate from
    # outbox_path (index-outbox.jsonl) so per-tick writes do not bloat it.
    watcher_run_log: Path = field(default_factory=lambda: Path("tmp/watcher_run.jsonl"))

    @classmethod
    def from_env(cls, specs: list[WatcherSpec], config_path: Path) -> "RegistryConfig":
        enable = _as_bool(os.getenv("WATCHER_ENABLE", "1"))
        vault_raw = (os.getenv("WATCHER_VAULT_PATH") or "").strip()
        if enable and not vault_raw:
            # No vault bound — idle until one is opened instead of raising
            # (#2005). The registry comes up disabled; each spec tick
            # short-circuits on `enable=False`.
            logger.info("watcher registry idling: WATCHER_ENABLE=1 but no vault bound")
            enable = False
        vault_path = Path(vault_raw or ".").expanduser()
        if enable and not _validate_registry_vault(vault_path):
            enable = False
        scope_glob, scope_source, inbox_source = _resolve_scope_glob(vault_path)
        logger.info(
            "watcher scope resolved vault_path=%s scope_glob=%s provenance=%s inbox_source=%s",
            vault_path,
            scope_glob,
            scope_source,
            inbox_source,
        )
        debounce_ms = resolve_dev_lab_env_typed(
            "WATCHER_DEBOUNCE_MS",
            default="1500",
            parser=_parse_int_factory(fallback=1500),
            logger=logger,
        )
        rate_limit_per_min = resolve_dev_lab_env_typed(
            "WATCHER_RATE_LIMIT_PER_MIN",
            default="30",
            parser=_parse_int_factory(fallback=30),
            logger=logger,
        )
        watcher_settings = load_watcher_settings(vault_path)
        outbox_path = Path(os.getenv("INDEX_OUTBOX_PATH") or watcher_settings.paths.index_outbox)
        watcher_run_log = Path(os.getenv("WATCHER_RUN_LOG_PATH") or watcher_settings.paths.watcher_run_log)
        state_dir = Path(os.getenv("WATCHER_STATE_DIR") or watcher_settings.paths.watcher_state.parent).expanduser()
        heartbeat_path = Path(os.getenv("WATCHER_HEARTBEAT_PATH", resolve_heartbeat_path()))
        summary_interval = _as_int(os.getenv("WATCHER_SUMMARY_INTERVAL"), fallback=60)
        stop_file = Path(os.getenv("WATCHER_STOP_FILE") or watcher_settings.paths.watcher_stop_file).expanduser()
        tick_sleep_raw = resolve_dev_lab_env_typed(
            "WATCHER_TICK_SLEEP_SECONDS",
            default="0.2",
            parser=_parse_float_factory(fallback=0.2),
            logger=logger,
        )
        tick_sleep_seconds = max(tick_sleep_raw, MIN_TICK_SLEEP_SECONDS)
        tick_log_env = os.getenv("WATCHER_TICK_LOG_PATH")
        tick_log_path = Path(tick_log_env).expanduser() if tick_log_env else watcher_settings.paths.watcher_tick_log
        max_scanned_files_per_tick = resolve_dev_lab_env_typed(
            "WATCHER_MAX_SCANNED_FILES_PER_TICK",
            default="500",
            parser=_parse_int_factory(fallback=500),
            logger=logger,
        )
        max_bytes_read_per_tick = resolve_dev_lab_env_typed(
            "WATCHER_MAX_BYTES_READ_PER_TICK",
            default="50000000",
            parser=_parse_int_factory(fallback=50_000_000),
            logger=logger,
        )
        max_elapsed_ms_per_tick = resolve_dev_lab_env_typed(
            "WATCHER_MAX_ELAPSED_MS_PER_TICK",
            default="2000",
            parser=_parse_int_factory(fallback=2000),
            logger=logger,
        )
        max_bad_ticks = resolve_dev_lab_env_typed(
            "WATCHER_MAX_BAD_TICKS",
            default="10",
            parser=_parse_int_factory(fallback=10),
            logger=logger,
        )
        bad_tick_backoff_seconds = resolve_dev_lab_env_typed(
            "WATCHER_BAD_TICK_BACKOFF_SECONDS",
            default="2.0",
            parser=_parse_float_factory(fallback=2.0),
            logger=logger,
        )

        for spec in specs:
            spec.scope_glob = scope_glob
            spec.debounce_ms = debounce_ms
            spec.rate_limit_per_min = rate_limit_per_min
        return cls(
            enable=enable,
            outbox_path=outbox_path,
            vault_path=vault_path,
            scope_glob=scope_glob,
            debounce_ms=debounce_ms,
            rate_limit_per_min=rate_limit_per_min,
            state_dir=state_dir,
            heartbeat_path=heartbeat_path,
            config_path=config_path,
            summary_interval=summary_interval,
            stop_file=stop_file,
            tick_sleep_seconds=tick_sleep_seconds,
            tick_log_path=tick_log_path.expanduser(),
            max_scanned_files_per_tick=max_scanned_files_per_tick,
            max_bytes_read_per_tick=max_bytes_read_per_tick,
            max_elapsed_ms_per_tick=max_elapsed_ms_per_tick,
            max_bad_ticks=max_bad_ticks,
            bad_tick_backoff_seconds=bad_tick_backoff_seconds,
            specs=specs,
            watcher_run_log=watcher_run_log,
        )


@dataclass
class WatcherSummary:
    ticks_run: int
    changed_detected: int
    emitted: int
    errors: int
    rate_limited: int
    backoff: bool
    tick_sleep: float


@dataclass
class WatcherTickResult:
    summary: WatcherSummary
    last_trace_id: str | None


def _expand_env_values(value: object) -> object:
    if isinstance(value, str):
        return os.path.expandvars(value)
    if isinstance(value, list):
        return [_expand_env_values(item) for item in value]
    if isinstance(value, dict):
        return {key: _expand_env_values(val) for key, val in value.items()}
    return value


def load_registry_config(config_path: Path) -> RegistryConfig:
    config_path = config_path.expanduser()
    if not config_path.exists():
        raise FileNotFoundError(f"watcher config not found: {config_path}")
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    watchers_raw = raw.get("watchers") or []
    if not isinstance(watchers_raw, list):
        raise ValueError("watchers config must include a list of watchers")
    specs = [WatcherSpec.from_dict(_expand_env_values(entry or {})) for entry in watchers_raw]
    if not specs:
        raise ValueError("watchers config is empty")
    return RegistryConfig.from_env(specs, config_path=config_path)


def _state_path(state_dir: Path, name: str) -> Path:
    safe = "".join([c if c.isalnum() or c in {"-", "_"} else "_" for c in name])
    return state_dir / f"watcher_state_{safe}.json"


def _build_watchers_payload(
    specs: Iterable[WatcherSpec],
    states: Mapping[str, WatcherState],
) -> dict[str, dict[str, object]]:
    payload: dict[str, dict[str, object]] = {}
    for spec in specs:
        state = states[spec.name]
        payload[spec.name] = {
            "scope_glob": spec.scope_glob,
            "emit_event": spec.emit_event,
            "debounce_ms": spec.debounce_ms,
            "rate_limit_per_min": spec.rate_limit_per_min,
            "ticks_total": state.ticks_run,
            "changed_total": state.changed_detected,
            "emitted_total": state.intents_emitted,
            "errors_total": state.errors,
            "rate_limited_total": state.rate_limited,
            "enqueue_failures_total": state.enqueue_failures_total,
        }
        if state.last_trace_id:
            payload[spec.name]["last_trace_id"] = state.last_trace_id
        if state.last_emitted_event_at is not None:
            payload[spec.name]["last_emitted_event_at"] = state.last_emitted_event_at
    return payload


def _warn_once_per_minute(state: WatcherState, message: str, *, now: float) -> None:
    if state.last_stop_warning is None or now - state.last_stop_warning >= 60:
        print(message)
        state.last_stop_warning = now


def _summary_line(
    name: str,
    state: WatcherState,
    *,
    backoff_active: bool,
    tick_sleep_seconds: float,
) -> str:
    parts = [
        f"name={name}",
        f"ticks={state.ticks_run}",
        f"changed={state.changed_detected}",
        f"emitted={state.intents_emitted}",
        f"errors={state.errors}",
        f"rate_limited={state.rate_limited}",
        f"enqueue_failures={state.enqueue_failures_total}",
        f"backoff={backoff_active}",
        f"tick_sleep={tick_sleep_seconds}",
    ]
    if state.last_trace_id:
        parts.append(f"trace_id={state.last_trace_id}")
    return "watcher summary: " + " ".join(parts)


def _as_bool(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in _TRUE_VALUES


def _as_int(value: str | None, fallback: int) -> int:
    try:
        return int(value) if value is not None else fallback
    except Exception:
        return fallback


def _as_float(value: str | None, *, fallback: float) -> float:
    try:
        return float(value) if value is not None else fallback
    except Exception:
        return fallback


def _parse_int_factory(*, fallback: int):
    return lambda raw: _as_int(raw, fallback=fallback)


def _parse_float_factory(*, fallback: float):
    return lambda raw: _as_float(raw, fallback=fallback)


def _auto_exec_enabled(vault_root: Path) -> bool:
    return resolve_auto_exec_enabled(vault_root=vault_root)


# Vault statuses that mean "no usable vault yet, but not a misconfiguration":
# the registry idles until a vault is opened/initialized instead of fail-exiting
# (#2005 — flips the #1991 hard precondition). A *set-but-missing*
# (status="missing") or otherwise *invalid* vault still fails loud.
_IDLE_VAULT_STATUSES = {"none", "uninitialized"}


def _validate_registry_vault(vault_path: Path) -> bool:
    """Return True when the registry should run; False when it should idle.

    Raises only for a *loud* misconfiguration (set-but-missing or invalid vault
    path, or a vault whose settings disable the watcher). An absent or
    uninitialized vault returns False so the caller builds an idle runtime.
    """

    manager = VaultManager()
    context = manager.validate_vault(vault_path)
    if context.status in _IDLE_VAULT_STATUSES:
        logger.info(
            "watcher registry idling: no usable vault bound (status=%s path=%s)",
            context.status,
            vault_path,
        )
        return False
    if context.status != "selected":
        detail = f": {context.validation_error}" if context.validation_error else ""
        remedy = (
            f" — run `python -m app.cli vault init --path {vault_path}` to scaffold settings"
            if context.status == "uninitialized"
            else ""
        )
        raise ValueError(
            f"watcher registry requires an initialized selected vault; status={context.status}{detail}{remedy}"
        )
    permissions = manager.permissions_for_context(context)
    if not permissions.enable_vault_watcher:
        raise ValueError("watcher registry is disabled by settings/local.md")
    return True


def _db_outbox_required() -> bool:
    require_db = resolve_dev_lab_env_value(
        "WATCHER_REQUIRE_DB_OUTBOX",
        default="0",
        logger=logger,
    )
    if _as_bool(require_db):
        return True
    backend = (os.getenv("STORE_BACKEND") or "").strip().lower()
    return backend == "pg"


def _has_db_outbox_env() -> bool:
    return bool(os.getenv("DATABASE_URL") or os.getenv("DB_DSN"))


def _panel_candidate_for_path(note_path: Path) -> tuple[bool, bool]:
    try:
        markdown = note_path.read_text(encoding="utf-8")
    except Exception:
        return False, False
    try:
        frontmatter, _ = load_frontmatter(markdown)
    except Exception:
        frontmatter = {}
    if not isinstance(frontmatter, dict):
        frontmatter = {}
    return watcher_panel_candidate_for_path(note_path, frontmatter, markdown), True


def _should_heal_inbox_uuid(cfg: RegistryConfig, rel_path: Path) -> bool:
    inbox_rel = Path(_detect_inbox_dir(cfg.vault_path))
    try:
        rel_path.relative_to(inbox_rel)
        return True
    except Exception:
        return False


def _maybe_heal_ingest_uuid(
    cfg: RegistryConfig,
    state: WatcherState,
    rel_path: Path,
    mtime: float,
    digest: str,
) -> tuple[float, str]:
    if not _should_heal_inbox_uuid(cfg, rel_path):
        return mtime, digest
    note_path = cfg.vault_path / rel_path
    try:
        ensure_note_uuid(note_path, vault_root=cfg.vault_path)
    except Exception as exc:
        state.errors += 1
        print(f"WARN: failed to ensure uuid for {note_path}: {exc}")
        return mtime, digest
    new_mtime = mtime
    try:
        new_mtime = note_path.stat().st_mtime
    except Exception:
        new_mtime = mtime
    hashed = _hash_file(note_path)
    if hashed is None:
        return new_mtime, digest
    new_digest, _ = hashed
    return new_mtime, new_digest


def _emit_panel_events(
    *,
    spec: WatcherSpec,
    cfg: RegistryConfig,
    rel: Path,
    mtime: float,
    digest: str,
    state: WatcherState,
    action_mappings: Mapping[str, PanelActionMapping],
) -> str | None:
    now = time.time()
    last_seen = state.last_seen(str(rel))
    state.update_file_state(str(rel), mtime=mtime, content_hash=digest, seen_at=now)
    if last_seen is not None and (now - last_seen) * 1000 < spec.debounce_ms:
        logger.info(
            "panel emit skipped debounce relative_path=%s debounce_ms=%s",
            str(rel),
            spec.debounce_ms,
        )
        return None
    if state.rate_window_count(now) >= spec.rate_limit_per_min:
        state.rate_limited += 1
        logger.info(
            "panel emit skipped rate_limit relative_path=%s rate_limit_per_min=%s",
            str(rel),
            spec.rate_limit_per_min,
        )
        return None
    emitted_events = _process_panel_note(
        vault_root=cfg.vault_path,
        rel_path=rel,
        outbox_path=cfg.outbox_path,
        state=state,
        action_mappings=action_mappings,
    )
    if emitted_events <= 0:
        logger.info(
            "panel emit produced no events relative_path=%s",
            str(rel),
        )
        return None
    state.intents_emitted += 1
    state.last_emitted_event_at = now
    state.record_rate_event(now)
    state.update_file_state(str(rel), mtime=mtime, content_hash=digest, emitted_at=now)
    trace_id = uuid4().hex
    state.last_trace_id = trace_id
    logger.info(
        "panel emit success relative_path=%s emitted_events=%s trace_id=%s",
        str(rel),
        emitted_events,
        trace_id,
    )
    return trace_id


def _sync_settings_local_state(
    states: Mapping[str, WatcherState],
    *,
    rel_str: str,
    values: Mapping[str, object],
) -> None:
    for state in states.values():
        state.update_file_state(rel_str, settings_runtime_values=values)


def _collect_changed_entries(
    cfg: RegistryConfig,
    spec: WatcherSpec,
    state: WatcherState,
    summary: dict[str, object],
    *,
    scan_roots: Iterable[Path],
    states: Mapping[str, WatcherState],
) -> tuple[list[ChangedEntry], list[str]]:
    changed_entries: list[ChangedEntry] = []
    scanned_paths: list[str] = []
    for rel, mtime, path in _scan_markdown_many(cfg.vault_path, scan_roots, spec.scope_glob):
        summary["scanned_files"] = int(summary["scanned_files"]) + 1
        rel_str = str(rel)
        scanned_paths.append(rel_str)
        last_mtime = state.last_mtime(rel_str)
        previous_hash = state.last_hash(rel_str)
        if last_mtime is not None and last_mtime == mtime:
            state.update_file_state(rel_str, mtime=mtime, content_hash=previous_hash)
            continue
        hashed = _hash_file(path)
        if hashed is None:
            continue
        digest, read_bytes = hashed
        summary["hashed_files"] = int(summary["hashed_files"]) + 1
        summary["bytes_read"] = int(summary["bytes_read"]) + read_bytes
        if previous_hash is not None and previous_hash == digest:
            state.update_file_state(rel_str, mtime=mtime, content_hash=digest)
            continue
        settings_delta = handle_settings_local_delta(
            vault_root=cfg.vault_path,
            rel_path=rel,
            previous_values=state.last_settings_runtime_values(rel_str),
        )
        if settings_delta.errors:
            state.errors += len(settings_delta.errors)
            summary["settings_write_errors_in_tick"] = int(summary.get("settings_write_errors_in_tick", 0)) + len(
                settings_delta.errors
            )
        if settings_delta.receipts:
            summary["settings_receipts_in_tick"] = int(summary.get("settings_receipts_in_tick", 0)) + len(
                settings_delta.receipts
            )
            try:
                mtime = path.stat().st_mtime
            except OSError:
                pass
            hashed = _hash_file(path)
            if hashed is not None:
                digest = hashed[0]
        changed_entries.append(ChangedEntry(rel_path=rel, mtime=mtime, digest=digest))
        if settings_delta.values is not None:
            _sync_settings_local_state(states, rel_str=rel_str, values=settings_delta.values)
    return changed_entries, scanned_paths


def _should_skip_changed_entry(
    *,
    spec: WatcherSpec,
    state: WatcherState,
    last_seen: float | None,
    now: float,
) -> tuple[bool, str | None]:
    if last_seen is not None and (now - last_seen) * 1000 < spec.debounce_ms:
        return True, "debounce"
    if state.rate_window_count(now) >= spec.rate_limit_per_min:
        state.rate_limited += 1
        return True, "rate_limit"
    return False, None


def _panel_emit_allowed(
    *,
    cfg: RegistryConfig,
    rel_path: Path,
    summary: dict[str, object],
    panel_auto_exec_enabled: bool,
    state: WatcherState,
) -> bool:
    candidate, ok = _panel_candidate_for_path(cfg.vault_path / rel_path)
    if not ok:
        state.errors += 1
        return False
    if candidate:
        summary["panel_candidates"] = int(summary.get("panel_candidates", 0)) + 1
    else:
        summary["panel_skipped_policy"] = int(summary.get("panel_skipped_policy", 0)) + 1
        return False
    if not panel_auto_exec_enabled:
        summary["panel_skipped_auto_exec"] = int(summary.get("panel_skipped_auto_exec", 0)) + 1
        return False
    return True


def _emit_changed_entry(
    *,
    cfg: RegistryConfig,
    spec: WatcherSpec,
    state: WatcherState,
    summary: dict[str, object],
    entry: ChangedEntry,
    now: float,
    panel_auto_exec_enabled: bool,
    action_mappings: Mapping[str, PanelActionMapping],
    process_panel_notes_inline: bool,
) -> str | None:
    last_seen = state.last_seen(str(entry.rel_path))
    state.update_file_state(str(entry.rel_path), mtime=entry.mtime, content_hash=entry.digest, seen_at=now)
    should_skip, reason = _should_skip_changed_entry(spec=spec, state=state, last_seen=last_seen, now=now)
    if should_skip:
        if reason == "rate_limit":
            summary["rate_limited_in_tick"] = int(summary.get("rate_limited_in_tick", 0)) + 1
        return None
    if spec.emit_event == "panel.scan.requested" and not _panel_emit_allowed(
        cfg=cfg,
        rel_path=entry.rel_path,
        summary=summary,
        panel_auto_exec_enabled=panel_auto_exec_enabled,
        state=state,
    ):
        return None
    current_mtime = entry.mtime
    current_digest = entry.digest
    if spec.emit_event == INGEST_VAULT_CHANGED:
        current_mtime, current_digest = _maybe_heal_ingest_uuid(
            cfg, state, entry.rel_path, current_mtime, current_digest
        )
    trace_id = _emit_watch_event(
        spec=spec,
        cfg=cfg,
        outbox_path=cfg.outbox_path,
        vault_root=cfg.vault_path,
        rel_path=entry.rel_path,
        mtime=current_mtime,
        content_hash=current_digest,
        state=state,
    )
    if not trace_id:
        return None
    state.last_trace_id = trace_id
    state.intents_emitted += 1
    state.last_emitted_event_at = now
    state.record_rate_event(now)
    state.update_file_state(str(entry.rel_path), mtime=current_mtime, content_hash=current_digest, emitted_at=now)
    if spec.emit_event == PANEL_SCAN_REQUESTED and process_panel_notes_inline:
        _process_panel_note(
            vault_root=cfg.vault_path,
            rel_path=entry.rel_path,
            outbox_path=cfg.outbox_path,
            state=state,
            action_mappings=action_mappings,
        )
    return trace_id


def _emit_watch_event(
    *,
    spec: WatcherSpec,
    cfg: RegistryConfig,
    outbox_path: Path,
    vault_root: Path,
    rel_path: Path,
    mtime: float,
    content_hash: str | None,
    state: WatcherState,
) -> str | None:
    if spec.emit_event == "panel.scan.requested":
        trace_id = uuid4().hex
        payload = {
            "vault_path": str(vault_root / rel_path),
            "relative_path": str(rel_path),
            "mtime": mtime,
            "hash": content_hash,
            "watcher": spec.name,
        }
        event = OutboxEvent(
            event=PANEL_SCAN_REQUESTED,
            source="watcher.registry",
            trace_id=trace_id,
            payload=payload,
        )
        append_jsonl_outbox_event(outbox_path, event, default_source="watcher.registry")
        require_db = _db_outbox_required()
        if require_db and not _has_db_outbox_env():
            raise RuntimeError("DATABASE_URL or DB_DSN required for watcher DB outbox")
        if require_db or _has_db_outbox_env():
            try:
                write_outbox_event(event)
            except Exception:
                state.enqueue_failures_total += 1
                if require_db:
                    raise
                logger.exception(
                    "watcher db outbox enqueue failed topic=%s trace_id=%s note_path=%s relative_path=%s",
                    PANEL_SCAN_REQUESTED,
                    trace_id,
                    str(vault_root / rel_path),
                    str(rel_path),
                )
        return trace_id

    trace_id = uuid4().hex
    payload = {
        "vault_path": str(vault_root / rel_path),
        "relative_path": str(rel_path),
        "mtime": mtime,
        "hash": content_hash,
        "watcher": spec.name,
    }
    event = {
        "event": spec.emit_event,
        "event_id": uuid4().hex,
        "trace_id": trace_id,
        "timestamp": _now_iso(),
        "source": "watcher.registry",
        "payload": payload,
    }
    append_jsonl_outbox_event(outbox_path, event, default_source="watcher.registry")

    if spec.emit_event == INGEST_VAULT_CHANGED:
        require_db = _db_outbox_required()
        if require_db and not _has_db_outbox_env():
            raise RuntimeError("DATABASE_URL or DB_DSN required for watcher DB outbox")
        if require_db or _has_db_outbox_env():
            try:
                insert_object_and_outbox(
                    payload,
                    spec.emit_event,
                    trace_id=trace_id,
                    source="watcher.registry",
                )
            except Exception:
                state.enqueue_failures_total += 1
                if require_db:
                    raise
                logger.exception(
                    "watcher db outbox enqueue failed topic=%s trace_id=%s note_path=%s relative_path=%s",
                    spec.emit_event,
                    trace_id,
                    str(vault_root / rel_path),
                    str(rel_path),
                )
    return trace_id



def _run_spec_tick(
    cfg: RegistryConfig,
    spec: WatcherSpec,
    state: WatcherState,
    *,
    now: float,
    states: Mapping[str, WatcherState] | None = None,
    process_panel_notes_inline: bool = False,
) -> dict[str, object]:
    tick_start = now
    state.ticks_run += 1
    errors_before = state.errors

    summary: dict[str, object] = {
        "changed_in_tick": 0,
        "emitted_in_tick": 0,
        "rate_limited_in_tick": 0,
        "backoff_active": False,
        "kill_switch": False,
        "ticks_run": state.ticks_run,
        "intents_emitted": state.intents_emitted,
        "changed_detected": state.changed_detected,
        "errors": state.errors,
        "errors_in_tick": 0,
        "rate_limited": state.rate_limited,
        "enqueue_failures_total": state.enqueue_failures_total,
        "scanned_files": 0,
        "hashed_files": 0,
        "bytes_read": 0,
        "scope_glob": spec.scope_glob,
        "panel_candidates": 0,
        "panel_skipped_policy": 0,
        "panel_skipped_auto_exec": 0,
    }

    if not cfg.enable:
        summary["disabled"] = True
        return _finalize_spec_tick(cfg, state, summary, tick_start, None, spec.name)

    if cfg.stop_file.exists():
        summary["kill_switch"] = True
        _warn_once_per_minute(state, f"WATCHER_STOP present at {cfg.stop_file}; pausing.", now=now)
        return _finalize_spec_tick(cfg, state, summary, tick_start, None, spec.name)

    if state.in_backoff(now):
        summary["backoff_active"] = True
        return _finalize_spec_tick(cfg, state, summary, tick_start, None, spec.name)

    if not cfg.vault_path.exists() or not cfg.vault_path.is_dir():
        state.errors += 1
        state.save(_state_path(cfg.state_dir, spec.name))
        raise FileNotFoundError(f"Vault path not found: {cfg.vault_path}")

    scan_roots = derive_scope_roots(cfg.vault_path, spec.scope_glob)
    active_states = states or {spec.name: state}
    changed_entries, scanned_paths = _collect_changed_entries(
        cfg,
        spec,
        state,
        summary,
        scan_roots=scan_roots,
        states=active_states,
    )

    summary["changed_in_tick"] = len(changed_entries)
    state.changed_detected += len(changed_entries)
    summary["changed_detected"] = state.changed_detected

    emitted_in_tick = 0
    summary["rate_limited_in_tick"] = 0

    action_mappings: Mapping[str, PanelActionMapping] = {}
    panel_auto_exec_enabled = False
    if spec.emit_event == "panel.scan.requested":
        action_mappings = load_panel_action_mappings()
        panel_auto_exec_enabled = _auto_exec_enabled(cfg.vault_path)

    for entry in changed_entries:
        try:
            trace_id = _emit_changed_entry(
                spec=spec,
                cfg=cfg,
                state=state,
                summary=summary,
                entry=entry,
                now=now,
                panel_auto_exec_enabled=panel_auto_exec_enabled,
                action_mappings=action_mappings,
                process_panel_notes_inline=process_panel_notes_inline,
            )
            if not trace_id:
                continue
            emitted_in_tick += 1
        except Exception:
            state.errors += 1
            state.backoff_until = now + spec.backoff_seconds
            summary["backoff_active"] = True
            break

    summary["emitted_in_tick"] = emitted_in_tick
    summary["intents_emitted"] = state.intents_emitted
    summary["errors"] = state.errors
    summary["errors_in_tick"] = state.errors - errors_before
    summary["rate_limited"] = state.rate_limited
    summary["enqueue_failures_total"] = state.enqueue_failures_total
    summary["scan_root"] = ",".join(str(root) for root in scan_roots)
    summary["scope_glob"] = spec.scope_glob

    elapsed_ms = max(int((time.time() - tick_start) * 1000), 0)
    summary["tick_ms"] = elapsed_ms
    _apply_guardrails_registry(cfg, state, summary)
    state.prune_files(scanned_paths)

    return _finalize_spec_tick(cfg, state, summary, tick_start, scan_roots[0] if scan_roots else None, spec.name)


def run_registry_once(config_path: Path) -> dict[str, dict[str, object]]:
    cfg = load_registry_config(config_path)
    states = {
        spec.name: WatcherState.load(_state_path(cfg.state_dir, spec.name))
        for spec in cfg.specs
    }
    now = time.time()
    summaries = {
        spec.name: _run_spec_tick(
            cfg,
            spec,
            states[spec.name],
            now=now,
            states=states,
            process_panel_notes_inline=True,
        )
        for spec in cfg.specs
    }
    enqueue_failures_total = sum(state.enqueue_failures_total for state in states.values())
    write_registry_heartbeat(
        path=cfg.heartbeat_path,
        status="running",
        watchers=_build_watchers_payload(cfg.specs, states),
        outbox_path=cfg.outbox_path,
        vault_path=cfg.vault_path,
        config_path=cfg.config_path,
        paused=cfg.stop_file.exists(),
        enqueue_failures_total=enqueue_failures_total,
        now=now,
    )
    return summaries


def run_registry_forever(config_path: Path, *, max_ticks: int | None = None) -> None:
    cfg = load_registry_config(config_path)
    states = {
        spec.name: WatcherState.load(_state_path(cfg.state_dir, spec.name))
        for spec in cfg.specs
    }
    tick_limit = max_ticks if max_ticks is not None and max_ticks > 0 else None

    tick = 0
    while True:
        now = time.time()
        summaries = {
            spec.name: _run_spec_tick(cfg, spec, states[spec.name], now=now, states=states)
            for spec in cfg.specs
        }
        enqueue_failures_total = sum(state.enqueue_failures_total for state in states.values())
        write_registry_heartbeat(
            path=cfg.heartbeat_path,
            status="running",
            watchers=_build_watchers_payload(cfg.specs, states),
            outbox_path=cfg.outbox_path,
            vault_path=cfg.vault_path,
            config_path=cfg.config_path,
            paused=cfg.stop_file.exists(),
            enqueue_failures_total=enqueue_failures_total,
            now=now,
        )
        if cfg.summary_interval > 0:
            for spec in cfg.specs:
                state = states[spec.name]
                should_log = (
                    state.last_summary_at is None
                    or now - state.last_summary_at >= cfg.summary_interval
                )
                if should_log:
                    summary = summaries[spec.name]
                    backoff_active = bool(summary.get("backoff_active"))
                    print(
                        _summary_line(
                            spec.name,
                            state,
                            backoff_active=backoff_active,
                            tick_sleep_seconds=cfg.tick_sleep_seconds,
                        )
                    )
                    state.last_summary_at = now
                    state.save(_state_path(cfg.state_dir, spec.name))
        tick += 1
        if tick_limit is not None and tick >= tick_limit:
            break
        dynamic_sleep = max((state.dynamic_sleep_seconds or 0.0) for state in states.values())
        sleep_seconds = max(cfg.tick_sleep_seconds, dynamic_sleep)
        time.sleep(sleep_seconds)


__all__ = [
    "WatcherSpec",
    "RegistryConfig",
    "load_registry_config",
    "run_registry_once",
    "run_registry_forever",
]
