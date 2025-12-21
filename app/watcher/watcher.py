from __future__ import annotations

import fnmatch
import hashlib
import json
import time
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from app.watcher.config import WatcherConfig
from app.watcher.heartbeat import write_heartbeat
from app.watcher.state import WatcherState


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


def _emit_scan_event(
    *,
    outbox_path: Path,
    vault_root: Path,
    rel_path: Path,
    mtime: float,
    content_hash: str | None,
) -> str:
    trace_id = uuid4().hex
    event = {
        "event": "panel.scan.requested",
        "event_id": uuid4().hex,
        "trace_id": trace_id,
        "timestamp": _now_iso(),
        "source": "watcher",
        "payload": {
            "vault_path": str(vault_root / rel_path),
            "relative_path": str(rel_path),
            "mtime": mtime,
            "hash": content_hash,
        },
    }
    outbox_path.parent.mkdir(parents=True, exist_ok=True)
    with outbox_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False))
        handle.write("\n")
    return trace_id


def _warn_once_per_minute(state: WatcherState, message: str, *, now: float) -> None:
    if state.last_stop_warning is None or now - state.last_stop_warning >= 60:
        print(message)
        state.last_stop_warning = now


def _summary_line(state: WatcherState, *, backoff_active: bool) -> str:
    parts = [
        f"ticks={state.ticks_run}",
        f"changed={state.changed_detected}",
        f"emitted={state.intents_emitted}",
        f"errors={state.errors}",
        f"rate_limited={state.rate_limited}",
        f"backoff={backoff_active}",
    ]
    if state.last_trace_id:
        parts.append(f"trace_id={state.last_trace_id}")
    return "watcher summary: " + " ".join(parts)


def run_tick(
    cfg: WatcherConfig,
    state: WatcherState,
    *,
    now: float | None = None,
) -> dict[str, object]:
    now = now if now is not None else time.time()
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
        state.save(cfg.state_path)
        return summary

    if state.in_backoff(now):
        summary["backoff_active"] = True
        state.save(cfg.state_path)
        return summary

    if not cfg.vault_path.exists() or not cfg.vault_path.is_dir():
        state.errors += 1
        state.save(cfg.state_path)
        raise FileNotFoundError(f"Vault path not found: {cfg.vault_path}")

    changed_entries: list[tuple[Path, float, str | None]] = []
    for rel, mtime, path in _scan_markdown(cfg.vault_path, cfg.scope_glob):
        previous_mtime = state.last_mtime(str(rel))
        previous_hash = state.last_hash(str(rel))
        if previous_mtime is not None and abs(previous_mtime - mtime) < 1e-9:
            continue
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
        if last_seen is not None and (now - last_seen) * 1000 < cfg.debounce_ms:
            continue
        if state.rate_window_count(now) >= cfg.rate_limit_per_min:
            state.rate_limited += 1
            rate_limited_in_tick += 1
            continue
        try:
            trace_id = _emit_scan_event(
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
            state.backoff_until = now + cfg.backoff_seconds
            summary["backoff_active"] = True
            break

    summary["emitted_in_tick"] = emitted_in_tick
    summary["rate_limited_in_tick"] = rate_limited_in_tick
    summary["intents_emitted"] = state.intents_emitted
    summary["errors"] = state.errors
    summary["rate_limited"] = state.rate_limited

    state.save(cfg.state_path)
    return summary


def run_forever(cfg: WatcherConfig, state: WatcherState | None = None) -> None:
    state = state or WatcherState.load(cfg.state_path)
    while True:
        now = time.time()
        summary = run_tick(cfg, state, now=now)
        _write_heartbeat(cfg, state, now=now)
        _maybe_log_summary(cfg, state, summary, now=now)
        time.sleep(cfg.tick_sleep_seconds)


def run_once(cfg: WatcherConfig, state: WatcherState | None = None) -> dict[str, object]:
    state = state or WatcherState.load(cfg.state_path)
    now = time.time()
    summary = run_tick(cfg, state, now=now)
    _write_heartbeat(cfg, state, now=now)
    _maybe_log_summary(cfg, state, summary, now=now)
    return summary


def _maybe_log_summary(
    cfg: WatcherConfig,
    state: WatcherState,
    summary: dict[str, object],
    *,
    now: float,
) -> None:
    interval = max(10, cfg.summary_interval)
    if state.last_summary_at is None or now - state.last_summary_at >= interval:
        print(_summary_line(state, backoff_active=bool(summary.get("backoff_active"))))
        state.last_summary_at = now
        state.save(cfg.state_path)


def _write_heartbeat(cfg: WatcherConfig, state: WatcherState, *, now: float) -> None:
    paused = cfg.stop_file.exists()
    write_heartbeat(
        path=cfg.heartbeat_path,
        vault_path=cfg.vault_path,
        scope_glob=cfg.scope_glob,
        outbox_path=cfg.outbox_path,
        ticks_total=state.ticks_run,
        errors_total=state.errors,
        paused=paused,
        now=now,
    )


__all__ = ["run_forever", "run_once", "run_tick"]
