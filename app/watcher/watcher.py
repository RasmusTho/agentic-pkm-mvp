from __future__ import annotations

from app.watcher.scope import matches_scope
import hashlib
import json
import time
from collections.abc import Iterable
from datetime import timezone, datetime
from pathlib import Path
from uuid import uuid4

from app.watcher.config import WatcherConfig
from app.watcher.heartbeat import write_heartbeat
from app.watcher.state import WatcherState


def _now_iso_from_timestamp(value: float) -> str:
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat().replace("+00:00", "Z")


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
    if not resolved_candidate.is_relative_to(resolved_vault):  # type: ignore[attr-defined]
        raise ValueError(f"Scan root {resolved_candidate} must live under vault root {resolved_vault}")
    return candidate


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


def _hash_file(path: Path) -> tuple[str, int] | None:
    try:
        data = path.read_bytes()
    except Exception:
        return None
    return hashlib.sha256(data).hexdigest(), len(data)


def _emit_scan_event(*, outbox_path: Path, vault_root: Path, rel_path: Path, mtime: float, content_hash: str | None) -> str:
    trace_id = uuid4().hex
    event = {
        "event": "panel.scan.requested",
        "event_id": uuid4().hex,
        "trace_id": trace_id,
        "timestamp": _now_iso_from_timestamp(time.time()),
        "source": "watcher",
        "payload": {
            "vault_path": str(vault_root / rel_path),
            "relative_path": str(rel_path),
            "mtime": mtime,
            "mtime_iso": _now_iso_from_timestamp(mtime),
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


def _log_tick_diagnostics(
    cfg: WatcherConfig,
    summary: dict[str, object],
    scan_root: Path | None,
    watcher_name: str,
) -> None:
    payload: dict[str, object | None] = {
        "timestamp": summary.get("tick_start_ts"),
        "watcher_name": watcher_name,
        "scope_glob": cfg.scope_glob,
        "scan_root": str(scan_root) if scan_root is not None else None,
        "scanned_files": summary.get("scanned_files", 0),
        "hashed_files": summary.get("hashed_files", 0),
        "bytes_read": summary.get("bytes_read", 0),
        "changed_files": summary.get("changed_in_tick", 0),
        "emitted_events": summary.get("emitted_in_tick", 0),
        "elapsed_ms": summary.get("tick_ms"),
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


def _trip_stop_file(cfg: WatcherConfig, summary: dict[str, object]) -> None:
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


def _apply_guardrails(cfg: WatcherConfig, state: WatcherState, summary: dict[str, object]) -> None:
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


def _finalize_tick(
    cfg: WatcherConfig,
    state: WatcherState,
    summary: dict[str, object],
    tick_start: float,
    scan_root: Path | None,
) -> dict[str, object]:
    if "tick_ms" not in summary:
        tick_ms = max(int((time.time() - tick_start) * 1000), 0)
        summary["tick_ms"] = tick_ms
    else:
        tick_ms = int(summary["tick_ms"])
    summary["elapsed_ms"] = tick_ms
    summary.setdefault("tick_start_ts", _now_iso_from_timestamp(tick_start))
    summary.setdefault("chosen_sleep_seconds", state.dynamic_sleep_seconds or cfg.tick_sleep_seconds)
    try:
        _log_tick_diagnostics(cfg, summary, scan_root, watcher_name="single")
    finally:
        state.save(cfg.state_path)
    return summary


def run_tick(
    cfg: WatcherConfig,
    state: WatcherState,
    *,
    now: float | None = None,
) -> dict[str, object]:
    now = now if now is not None else time.time()
    tick_start = now
    state.ticks_run += 1
    errors_before = state.errors

    summary: dict[str, object] = {
        "changed_in_tick": 0,
        "emitted_in_tick": 0,
        "rate_limited_in_tick": 0,
        "backoff_active": False,
        "kill_switch": False,
        "scanned_files": 0,
        "hashed_files": 0,
        "bytes_read": 0,
        "ticks_run": state.ticks_run,
        "intents_emitted": state.intents_emitted,
        "changed_detected": state.changed_detected,
        "errors": state.errors,
        "errors_in_tick": 0,
        "rate_limited": state.rate_limited,
    }

    if not cfg.enable:
        summary["disabled"] = True
        return _finalize_tick(cfg, state, summary, tick_start, None)

    if cfg.stop_file.exists():
        summary["kill_switch"] = True
        _warn_once_per_minute(state, f"WATCHER_STOP present at {cfg.stop_file}; pausing.", now=now)
        return _finalize_tick(cfg, state, summary, tick_start, None)

    if state.in_backoff(now):
        summary["backoff_active"] = True
        return _finalize_tick(cfg, state, summary, tick_start, None)

    if not cfg.vault_path.exists() or not cfg.vault_path.is_dir():
        state.errors += 1
        summary["errors"] = state.errors
        state.save(cfg.state_path)
        raise FileNotFoundError(f"Vault path not found: {cfg.vault_path}")

    scan_root = _derive_scan_root(cfg.vault_path, cfg.scope_glob)
    changed_entries: list[tuple[Path, float, str | None]] = []
    for rel, mtime, path in _scan_markdown(cfg.vault_path, scan_root, cfg.scope_glob):
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

    for rel, mtime, digest in changed_entries:
        rel_str = str(rel)
        last_seen = state.last_seen(rel_str)
        state.update_file_state(rel_str, mtime=mtime, content_hash=digest, seen_at=now)
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
            state.update_file_state(rel_str, mtime=mtime, content_hash=digest, emitted_at=now)
        except Exception:
            state.errors += 1
            summary["errors"] = state.errors
            state.backoff_until = now + cfg.backoff_seconds
            summary["backoff_active"] = True
            break

    summary["emitted_in_tick"] = emitted_in_tick
    summary["rate_limited_in_tick"] = rate_limited_in_tick
    summary["intents_emitted"] = state.intents_emitted
    summary["errors"] = state.errors
    summary["errors_in_tick"] = state.errors - errors_before
    summary["rate_limited"] = state.rate_limited
    summary["scan_root"] = str(scan_root)
    summary["scope_glob"] = cfg.scope_glob

    elapsed_ms = max(int((time.time() - tick_start) * 1000), 0)
    summary["tick_ms"] = elapsed_ms
    _apply_guardrails(cfg, state, summary)

    return _finalize_tick(cfg, state, summary, tick_start, scan_root)


def run_forever(cfg: WatcherConfig, state: WatcherState | None = None) -> None:
    state = state or WatcherState.load(cfg.state_path)
    while True:
        now = time.time()
        summary = run_tick(cfg, state, now=now)
        _write_heartbeat(cfg, state, now=now)
        _maybe_log_summary(cfg, state, summary, now=now)
        sleep_seconds = state.dynamic_sleep_seconds or cfg.tick_sleep_seconds
        time.sleep(sleep_seconds)


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
