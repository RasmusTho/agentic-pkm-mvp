from __future__ import annotations

from app.watcher.scope import matches_scope
import hashlib
import json
import logging
import os
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import yaml

from app.agents.panel.agent import handle_note_update
from app.agents.panel_agent.policy import watcher_panel_candidate_for_path
from app.components.concurrency import OptimisticWriteGuard, VersionMismatch
from app.events.schema import OutboxEvent
from app.events.types import INGEST_VAULT_CHANGED
from app.outbox.events import get_index_outbox_path
from app.services.note_uuid import ensure_note_uuid
from app.services.outbox import write_outbox_event
from app.settings.panel_actions import PanelActionMapping, load_panel_action_mappings
from app.settings.watcher_settings import resolve_auto_exec_enabled
from app.vault.layout import load_layout
from app.watcher.heartbeat import resolve_heartbeat_path, write_registry_heartbeat
from app.watcher.state import WatcherState
from app.write_guard import DEFAULT_WRITE_GUARD
from scripts.yaml_roundtrip import load_frontmatter

_TRUE_VALUES = {"1", "true", "yes", "on"}

DEFAULT_SCOPE_GLOB = "*.md,**/*.md"

MIN_TICK_SLEEP_SECONDS = 0.05

_WRITE_GUARD = OptimisticWriteGuard()

logger = logging.getLogger(__name__)


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
    return datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")


def _hash_file(path: Path) -> tuple[str, int] | None:
    try:
        data = path.read_bytes()
    except Exception:
        return None
    return hashlib.sha256(data).hexdigest(), len(data)


def _matches_scope(rel_path: Path, scope_glob: str) -> bool:
    return matches_scope(rel_path, scope_glob)


def _scan_markdown(vault_root: Path, scan_root: Path, scope_glob: str) -> Iterable[tuple[Path, float, Path]]:
    for path in sorted(scan_root.rglob("*.md")):
        try:
            rel = path.relative_to(vault_root)
        except Exception:
            continue
        if not _matches_scope(rel, scope_glob):
            continue
        try:
            mtime = path.stat().st_mtime
        except Exception:
            continue
        yield rel, mtime, path


def _scope_prefix(scope_glob: str) -> str:
    wildcard_chars = {"*", "?", "["}
    limit = len(scope_glob)
    for idx, char in enumerate(scope_glob):
        if char in wildcard_chars:
            limit = idx
            break
    prefix = scope_glob[:limit].rstrip("/")
    return prefix


def _derive_scan_root(vault_root: Path, scope_glob: str) -> Path:
    prefix = _scope_prefix(scope_glob)
    if not prefix:
        return vault_root
    candidate = vault_root / prefix
    if not candidate.exists() or not candidate.is_dir():
        raise FileNotFoundError(f"Scan root missing: {candidate}")
    resolved_vault = vault_root.resolve()
    resolved_candidate = candidate.resolve()
    if not resolved_candidate.is_relative_to(resolved_vault):
        raise ValueError(f"Scan root {resolved_candidate} must live under vault root {resolved_vault}")
    return candidate


def _now_iso_from_timestamp(value: float) -> str:
    return datetime.fromtimestamp(value, tz=UTC).isoformat().replace("+00:00", "Z")


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
    finally:
        state.save(_state_path(cfg.state_dir, watcher_name))
    return summary


def _write_jsonl_event(event: OutboxEvent, outbox_path: Path) -> None:
    outbox_path.parent.mkdir(parents=True, exist_ok=True)
    with outbox_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event.model_dump(mode="json"), ensure_ascii=False))
        handle.write("\n")


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


def _process_panel_note(
    *,
    vault_root: Path,
    rel_path: Path,
    outbox_path: Path,
    state: WatcherState,
    action_mappings: Mapping[str, PanelActionMapping],
) -> None:
    note_path = vault_root / rel_path
    try:
        markdown = note_path.read_text(encoding="utf-8")
    except Exception as exc:
        state.errors += 1
        print(f"WARN: failed to read panel note {note_path}: {exc}")
        return

    try:
        note_uuid = ensure_note_uuid(note_path)
    except Exception as exc:
        state.errors += 1
        print(f"WARN: failed to ensure uuid for {note_path}: {exc}")
        return

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
        return

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

    @classmethod
    def from_env(cls, specs: list[WatcherSpec], config_path: Path) -> "RegistryConfig":
        enable = _as_bool(os.getenv("WATCHER_ENABLE", "1"))
        vault_raw = (os.getenv("WATCHER_VAULT_PATH") or "").strip()
        if enable and not vault_raw:
            raise ValueError("WATCHER_VAULT_PATH is required when WATCHER_ENABLE=1")
        vault_path = Path(vault_raw or ".").expanduser()
        scope_glob, scope_source, inbox_source = _resolve_scope_glob(vault_path)
        logger.info(
            "watcher scope resolved vault_path=%s scope_glob=%s provenance=%s inbox_source=%s",
            vault_path,
            scope_glob,
            scope_source,
            inbox_source,
        )
        debounce_ms = _as_int(os.getenv("WATCHER_DEBOUNCE_MS"), fallback=1500)
        rate_limit_per_min = _as_int(os.getenv("WATCHER_RATE_LIMIT_PER_MIN"), fallback=30)
        outbox_path = Path(os.getenv("INDEX_OUTBOX_PATH", get_index_outbox_path()))
        state_dir = Path(os.getenv("WATCHER_STATE_DIR", "tmp")).expanduser()
        heartbeat_path = Path(os.getenv("WATCHER_HEARTBEAT_PATH", resolve_heartbeat_path()))
        summary_interval = _as_int(os.getenv("WATCHER_SUMMARY_INTERVAL"), fallback=60)
        stop_file = Path(os.getenv("WATCHER_STOP_FILE", "/app/tmp/WATCHER_STOP")).expanduser()
        tick_sleep_seconds = max(
            float(os.getenv("WATCHER_TICK_SLEEP_SECONDS", "0.2")),
            MIN_TICK_SLEEP_SECONDS,
        )
        tick_log_env = os.getenv("WATCHER_TICK_LOG_PATH")
        tick_log_path = Path(tick_log_env) if tick_log_env else Path("/app/tmp/watcher_tick.jsonl")
        max_scanned_files_per_tick = _as_int(os.getenv("WATCHER_MAX_SCANNED_FILES_PER_TICK"), fallback=500)
        max_bytes_read_per_tick = _as_int(os.getenv("WATCHER_MAX_BYTES_READ_PER_TICK"), fallback=50_000_000)
        max_elapsed_ms_per_tick = _as_int(os.getenv("WATCHER_MAX_ELAPSED_MS_PER_TICK"), fallback=2000)
        max_bad_ticks = _as_int(os.getenv("WATCHER_MAX_BAD_TICKS"), fallback=10)
        bad_tick_backoff_seconds = _as_float(os.getenv("WATCHER_BAD_TICK_BACKOFF_SECONDS"), fallback=2.0)

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


def _auto_exec_enabled(vault_root: Path) -> bool:
    return resolve_auto_exec_enabled(vault_root=vault_root)


def _db_outbox_required() -> bool:
    if _as_bool(os.getenv("WATCHER_REQUIRE_DB_OUTBOX", "0")):
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
        ensure_note_uuid(note_path)
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
        return None
    if state.rate_window_count(now) >= spec.rate_limit_per_min:
        state.rate_limited += 1
        return None
    _process_panel_note(
        vault_root=cfg.vault_path,
        rel_path=rel,
        outbox_path=cfg.outbox_path,
        state=state,
        action_mappings=action_mappings,
    )
    state.intents_emitted += 1
    state.record_rate_event(now)
    state.update_file_state(str(rel), mtime=mtime, content_hash=digest, emitted_at=now)
    trace_id = uuid4().hex
    state.last_trace_id = trace_id
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
) -> str:
    if spec.emit_event == "panel.scan.requested":
        action_mappings = load_panel_action_mappings()
        trace = _emit_panel_events(
            spec=spec,
            cfg=cfg,
            rel=rel_path,
            mtime=mtime,
            digest=content_hash or "",
            state=state,
            action_mappings=action_mappings,
        )
        return trace or uuid4().hex

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
    outbox_path.parent.mkdir(parents=True, exist_ok=True)
    with outbox_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False))
        handle.write("\n")

    if spec.emit_event == INGEST_VAULT_CHANGED:
        require_db = _db_outbox_required()
        if require_db and not _has_db_outbox_env():
            raise RuntimeError("DATABASE_URL or DB_DSN required for watcher DB outbox")
        if require_db or _has_db_outbox_env():
            try:
                from app.services.outbox import insert_object_and_outbox

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

    scan_root = _derive_scan_root(cfg.vault_path, spec.scope_glob)
    changed_entries: list[tuple[Path, float, str | None]] = []
    for rel, mtime, path in _scan_markdown(cfg.vault_path, scan_root, spec.scope_glob):
        summary["scanned_files"] = int(summary["scanned_files"]) + 1
        rel_str = str(rel)
        last_mtime = state.last_mtime(rel_str)
        previous_hash = state.last_hash(rel_str)
        if last_mtime is not None and last_mtime == mtime:
            state.update_file_state(rel_str, mtime=mtime, content_hash=previous_hash, seen_at=now)
            continue
        hashed = _hash_file(path)
        if hashed is None:
            continue
        digest, read_bytes = hashed
        summary["hashed_files"] = int(summary["hashed_files"]) + 1
        summary["bytes_read"] = int(summary["bytes_read"]) + read_bytes
        if previous_hash is not None and previous_hash == digest:
            state.update_file_state(rel_str, mtime=mtime, content_hash=digest, seen_at=now)
            continue
        changed_entries.append((rel, mtime, digest))

    summary["changed_in_tick"] = len(changed_entries)
    state.changed_detected += len(changed_entries)
    summary["changed_detected"] = state.changed_detected

    emitted_in_tick = 0
    rate_limited_in_tick = 0

    action_mappings: Mapping[str, PanelActionMapping] = {}
    if spec.emit_event == "panel.scan.requested":
        action_mappings = load_panel_action_mappings()

    for rel, mtime, digest in changed_entries:
        last_seen = state.last_seen(str(rel))
        state.update_file_state(str(rel), mtime=mtime, content_hash=digest, seen_at=now)
        if last_seen is not None and (now - last_seen) * 1000 < spec.debounce_ms:
            continue
        if state.rate_window_count(now) >= spec.rate_limit_per_min:
            state.rate_limited += 1
            rate_limited_in_tick += 1
            continue
        if spec.emit_event == "panel.scan.requested":
            candidate, ok = _panel_candidate_for_path(cfg.vault_path / rel)
            if not ok:
                state.errors += 1
                continue
            if candidate:
                summary["panel_candidates"] = int(summary.get("panel_candidates", 0)) + 1
            else:
                summary["panel_skipped_policy"] = int(summary.get("panel_skipped_policy", 0)) + 1
                continue
            if not _auto_exec_enabled(cfg.vault_path):
                summary["panel_skipped_auto_exec"] = int(summary.get("panel_skipped_auto_exec", 0)) + 1
                continue
        current_mtime = mtime
        current_digest = digest or ""
        if spec.emit_event == INGEST_VAULT_CHANGED:
            current_mtime, current_digest = _maybe_heal_ingest_uuid(
                cfg, state, rel, current_mtime, current_digest
            )
        try:
            trace_id = _emit_watch_event(
                spec=spec,
                cfg=cfg,
                outbox_path=cfg.outbox_path,
                vault_root=cfg.vault_path,
                rel_path=rel,
                mtime=current_mtime,
                content_hash=current_digest,
                state=state,
            )
            state.last_trace_id = trace_id
            state.intents_emitted += 1
            emitted_in_tick += 1
            state.record_rate_event(now)
            state.update_file_state(str(rel), mtime=current_mtime, content_hash=current_digest, emitted_at=now)
        except Exception:
            state.errors += 1
            state.backoff_until = now + spec.backoff_seconds
            summary["backoff_active"] = True
            break

    summary["emitted_in_tick"] = emitted_in_tick
    summary["rate_limited_in_tick"] = rate_limited_in_tick
    summary["intents_emitted"] = state.intents_emitted
    summary["errors"] = state.errors
    summary["errors_in_tick"] = state.errors - errors_before
    summary["rate_limited"] = state.rate_limited
    summary["enqueue_failures_total"] = state.enqueue_failures_total
    summary["scan_root"] = str(scan_root)
    summary["scope_glob"] = spec.scope_glob

    elapsed_ms = max(int((time.time() - tick_start) * 1000), 0)
    summary["tick_ms"] = elapsed_ms
    _apply_guardrails_registry(cfg, state, summary)

    return _finalize_spec_tick(cfg, state, summary, tick_start, scan_root, spec.name)


def run_registry_once(config_path: Path) -> dict[str, dict[str, object]]:
    cfg = load_registry_config(config_path)
    states = {
        spec.name: WatcherState.load(_state_path(cfg.state_dir, spec.name))
        for spec in cfg.specs
    }
    now = time.time()
    summaries = {
        spec.name: _run_spec_tick(cfg, spec, states[spec.name], now=now)
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
            spec.name: _run_spec_tick(cfg, spec, states[spec.name], now=now)
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
