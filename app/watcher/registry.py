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

from app.events.types import INGEST_VAULT_CHANGED
from app.outbox.events import get_index_outbox_path
from app.services.outbox import insert_object_and_outbox
from app.watcher.heartbeat import resolve_heartbeat_path, write_registry_heartbeat
from app.watcher.state import WatcherState

_TRUE_VALUES = {"1", "true", "yes", "on"}

MIN_TICK_SLEEP_SECONDS = 0.05


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


def _emit_watch_event(
    *,
    spec: WatcherSpec,
    outbox_path: Path,
    vault_root: Path,
    rel_path: Path,
    mtime: float,
    content_hash: str | None,
) -> str:
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
            insert_object_and_outbox(
                payload,
                spec.emit_event,
                trace_id=trace_id,
                source="watcher.registry",
            )
        except Exception:
            pass
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


def _as_float(value: str | None, fallback: float) -> float:
    try:
        return float(value) if value is not None else fallback
    except Exception:
        return fallback


@dataclass(frozen=True)
class WatcherSpec:
    name: str
    scope_glob: str
    debounce_ms: int = 1500
    rate_limit_per_min: int = 30
    backoff_seconds: int = 10
    emit_event: str = "panel.scan.requested"

    @classmethod
    def from_dict(cls, raw: Mapping[str, object]) -> WatcherSpec:
        name = str(raw.get("name") or "").strip()
        if not name:
            raise ValueError("watcher spec missing name")
        scope_glob = str(raw.get("scope_glob") or "@Inbox/**")
        debounce_ms = _as_int(str(raw.get("debounce_ms") or ""), 1500)
        rate_limit = _as_int(str(raw.get("rate_limit_per_min") or ""), 30)
        backoff = _as_int(str(raw.get("backoff_seconds") or ""), 10)
        emit_event = str(raw.get("emit_event") or "panel.scan.requested")
        return cls(
            name=name,
            scope_glob=scope_glob,
            debounce_ms=debounce_ms,
            rate_limit_per_min=rate_limit,
            backoff_seconds=backoff,
            emit_event=emit_event,
        )


@dataclass(frozen=True)
class RegistryConfig:
    enable: bool
    vault_path: Path
    outbox_path: Path
    heartbeat_path: Path
    stop_file: Path
    state_dir: Path
    summary_interval: int
    tick_sleep_seconds: float
    specs: tuple[WatcherSpec, ...]
    config_path: Path

    @classmethod
    def from_env(cls, specs: Iterable[WatcherSpec], config_path: Path) -> RegistryConfig:
        enable = _as_bool(os.getenv("WATCHER_ENABLE", "0"))
        vault_raw = (
            os.getenv("WATCHER_VAULT_PATH")
            or os.getenv("VAULT_ROOT")
            or os.getenv("VAULT_PATH")
            or ""
        )
        if enable and not vault_raw.strip():
            raise ValueError("WATCHER_VAULT_PATH is required when WATCHER_ENABLE=1")
        vault_path = Path(vault_raw or ".").expanduser()
        outbox_env = os.getenv("INDEX_OUTBOX_PATH")
        if outbox_env and outbox_env.strip():
            outbox_path = Path(outbox_env).expanduser()
        else:
            outbox_path = get_index_outbox_path()
        stop_file = Path(os.getenv("WATCHER_STOP_FILE", "tmp/WATCHER_STOP")).expanduser()
        heartbeat_path = resolve_heartbeat_path()
        state_dir = Path(os.getenv("WATCHER_STATE_DIR", "tmp/watcher_states")).expanduser()
        summary_interval = _as_int(os.getenv("WATCHER_SUMMARY_INTERVAL"), 60)
        tick_sleep_seconds = _as_float(os.getenv("WATCHER_TICK_SLEEP_SECONDS"), 1.0)
        if tick_sleep_seconds <= 0:
            tick_sleep_seconds = MIN_TICK_SLEEP_SECONDS
        return cls(
            enable=enable,
            vault_path=vault_path,
            outbox_path=outbox_path,
            heartbeat_path=heartbeat_path,
            stop_file=stop_file,
            state_dir=state_dir,
            summary_interval=summary_interval,
            tick_sleep_seconds=tick_sleep_seconds,
            specs=tuple(specs),
            config_path=config_path,
        )


def load_registry_config(config_path: Path) -> RegistryConfig:
    config_path = config_path.expanduser()
    if not config_path.exists():
        raise FileNotFoundError(f"watcher config not found: {config_path}")
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    watchers_raw = raw.get("watchers") or []
    if not isinstance(watchers_raw, list):
        raise ValueError("watchers config must include a list of watchers")
    specs = [WatcherSpec.from_dict(entry or {}) for entry in watchers_raw]
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
        }
        if state.last_trace_id:
            payload[spec.name]["last_trace_id"] = state.last_trace_id
    return payload


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
                outbox_path=cfg.outbox_path,
                vault_root=cfg.vault_path,
                rel_path=rel,
                mtime=mtime,
                content_hash=digest,
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
    write_registry_heartbeat(
        path=cfg.heartbeat_path,
        status="running",
        watchers=_build_watchers_payload(cfg.specs, states),
        outbox_path=cfg.outbox_path,
        vault_path=cfg.vault_path,
        config_path=cfg.config_path,
        paused=cfg.stop_file.exists(),
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
        write_registry_heartbeat(
            path=cfg.heartbeat_path,
            status="running",
            watchers=_build_watchers_payload(cfg.specs, states),
            outbox_path=cfg.outbox_path,
            vault_path=cfg.vault_path,
            config_path=cfg.config_path,
            paused=cfg.stop_file.exists(),
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
