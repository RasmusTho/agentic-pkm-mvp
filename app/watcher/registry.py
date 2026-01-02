from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import yaml

from app.vault.paths import ensure_vault_path_env_defaults, get_vault_inbox_dir_rel

from app.agents.panel.agent import handle_note_update
from app.components.concurrency import OptimisticWriteGuard, VersionMismatch
from app.events.schema import OutboxEvent
from app.events.types import INGEST_VAULT_CHANGED
from app.outbox.events import get_index_outbox_path
from app.services.note_uuid import ensure_note_uuid
from app.services.outbox import write_outbox_event
from app.settings.panel_actions import PanelActionMapping, load_panel_action_mappings
from app.watcher.heartbeat import resolve_heartbeat_path, write_registry_heartbeat
from app.watcher.state import WatcherState
from app.write_guard import DEFAULT_WRITE_GUARD
from scripts.yaml_roundtrip import load_frontmatter

_TRUE_VALUES = {"1", "true", "yes", "on"}

MIN_TICK_SLEEP_SECONDS = 0.05

_WRITE_GUARD = OptimisticWriteGuard()

ensure_vault_path_env_defaults()


def _now_iso() -> str:
    return datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")


def _hash_file(path: Path) -> str | None:
    try:
        data = path.read_bytes()
    except Exception:
        return None
    return hashlib.sha256(data).hexdigest()


def _matches_scope(rel_path: Path, scope_glob: str) -> bool:
    rel_str = str(rel_path)
    return fnmatch.fnmatch(rel_str, scope_glob)


def _scan_markdown(vault_root: Path, scope_glob: str) -> Iterable[tuple[Path, float, Path]]:
    for path in sorted(vault_root.rglob("*.md")):
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
        except Exception as exc:
            state.enqueue_failures_total += 1
            print(f"WARN: failed to enqueue DB outbox event {event.event}: {exc}")
        try:
            _write_jsonl_event(event, outbox_path)
        except Exception as exc:
            print(f"WARN: failed to append JSONL outbox event {event.event}: {exc}")




def _default_scope_glob() -> str:
    inbox = os.getenv("VAULT_INBOX_DIR_REL") or get_vault_inbox_dir_rel()
    return f"{inbox}/**"

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
    specs: list[WatcherSpec]

    @classmethod
    def from_env(cls, specs: list[WatcherSpec], config_path: Path) -> "RegistryConfig":
        enable = _as_bool(os.getenv("WATCHER_ENABLE", "1"))
        scope_glob = os.getenv("WATCHER_SCOPE_GLOB", _default_scope_glob())
        debounce_ms = int(os.getenv("WATCHER_DEBOUNCE_MS", "1500"))
        rate_limit_per_min = int(os.getenv("WATCHER_RATE_LIMIT_PER_MIN", "30"))
        outbox_path = Path(os.getenv("INDEX_OUTBOX_PATH", get_index_outbox_path()))
        vault_path = Path(os.getenv("WATCHER_VAULT_PATH", "vault")).expanduser()
        state_dir = Path(os.getenv("WATCHER_STATE_DIR", "tmp")).expanduser()
        heartbeat_path = Path(os.getenv("WATCHER_HEARTBEAT_PATH", resolve_heartbeat_path()))
        summary_interval = _as_int(os.getenv("WATCHER_SUMMARY_INTERVAL"), 60)
        stop_file = Path(os.getenv("WATCHER_STOP_FILE", "tmp/WATCHER_STOP"))
        tick_sleep_seconds = max(float(os.getenv("WATCHER_TICK_SLEEP_SECONDS", "0.2")), MIN_TICK_SLEEP_SECONDS)
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
        try:
            from app.services.outbox import insert_object_and_outbox

            insert_object_and_outbox(
                payload,
                spec.emit_event,
                trace_id=trace_id,
                source="watcher.registry",
            )
        except Exception as exc:
            state.enqueue_failures_total += 1
            print(f"WARN: watcher failed to enqueue DB outbox event: {exc}")
    return trace_id


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


def _run_spec_tick(
    cfg: RegistryConfig,
    spec: WatcherSpec,
    state: WatcherState,
    *,
    now: float,
) -> dict[str, object]:
    state.ticks_run += 1

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
        "rate_limited": state.rate_limited,
        "enqueue_failures_total": state.enqueue_failures_total,
    }

    if not cfg.enable:
        summary["disabled"] = True
        return summary

    if cfg.stop_file.exists():
        summary["kill_switch"] = True
        _warn_once_per_minute(state, f"WATCHER_STOP present at {cfg.stop_file}; pausing.", now=now)
        state.save(_state_path(cfg.state_dir, spec.name))
        return summary

    if state.in_backoff(now):
        summary["backoff_active"] = True
        state.save(_state_path(cfg.state_dir, spec.name))
        return summary

    if not cfg.vault_path.exists() or not cfg.vault_path.is_dir():
        state.errors += 1
        state.save(_state_path(cfg.state_dir, spec.name))
        raise FileNotFoundError(f"Vault path not found: {cfg.vault_path}")

    changed_entries: list[tuple[Path, float, str | None]] = []
    for rel, mtime, path in _scan_markdown(cfg.vault_path, spec.scope_glob):
        previous_hash = state.last_hash(str(rel))
        digest = _hash_file(path)
        if digest is None:
            continue
        if previous_hash is not None and previous_hash == digest:
            state.update_file_state(str(rel), mtime=mtime, content_hash=digest)
            continue
        changed_entries.append((rel, mtime, digest))

    state.changed_detected += len(changed_entries)
    summary["changed_detected"] = state.changed_detected
    summary["changed_in_tick"] = len(changed_entries)

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
        try:
            trace_id = _emit_watch_event(
                spec=spec,
                cfg=cfg,
                outbox_path=cfg.outbox_path,
                vault_root=cfg.vault_path,
                rel_path=rel,
                mtime=mtime,
                content_hash=digest,
                state=state,
            )
            state.last_trace_id = trace_id
            state.intents_emitted += 1
            emitted_in_tick += 1
            state.record_rate_event(now)
            state.update_file_state(str(rel), mtime=mtime, content_hash=digest, emitted_at=now)
        except Exception:
            state.errors += 1
            state.backoff_until = now + spec.backoff_seconds
            summary["backoff_active"] = True
            break

    summary["emitted_in_tick"] = emitted_in_tick
    summary["rate_limited_in_tick"] = rate_limited_in_tick
    summary["intents_emitted"] = state.intents_emitted
    summary["errors"] = state.errors
    summary["rate_limited"] = state.rate_limited
    summary["enqueue_failures_total"] = state.enqueue_failures_total

    state.save(_state_path(cfg.state_dir, spec.name))
    return summary


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
        time.sleep(cfg.tick_sleep_seconds)


__all__ = [
    "WatcherSpec",
    "RegistryConfig",
    "load_registry_config",
    "run_registry_once",
    "run_registry_forever",
]
