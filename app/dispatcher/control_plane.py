"""Logical control-plane state and recovery observations for dispatcher."""

from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.dispatcher.config import DispatcherPaths
from app.dispatcher.store import SqliteStore

STATE_KEY = "control_plane_state"
MODES = frozenset({"normal", "degraded", "recovery"})
_ALLOWED = {"normal": {"degraded"}, "degraded": {"recovery"}, "recovery": {"normal"}}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def state(store: SqliteStore) -> dict[str, Any]:
    raw = store.get_meta(STATE_KEY)
    if raw is None:
        return {"mode": "normal", "revision": 0, "updated_at": None, "activation_id": None}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("Dispatcher control-plane state is malformed") from exc
    if not isinstance(value, dict) or value.get("mode") not in MODES or not isinstance(value.get("revision"), int):
        raise ValueError("Dispatcher control-plane state is malformed")
    return value


def health(paths: DispatcherPaths) -> dict[str, Any]:
    result: dict[str, Any] = {
        "db": {"path": str(paths.db_path), "exists": paths.db_path.exists()},
        "events": {"path": str(paths.events_path), "exists": paths.events_path.exists()},
        "ok": False,
    }
    if not paths.db_path.exists():
        result["db"]["error"] = "missing"
        return result
    try:
        with sqlite3.connect(paths.db_path, timeout=0) as conn:
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            conn.execute("BEGIN IMMEDIATE")
            conn.rollback()
        result["db"].update({"integrity": integrity, "writable": True})
    except sqlite3.Error as exc:
        result["db"]["error"] = str(exc)
        return result
    try:
        lines = 0
        if paths.events_path.exists():
            for lines, line in enumerate(paths.events_path.read_text(encoding="utf-8").splitlines(), 1):
                json.loads(line)
        result["events"]["valid_lines"] = lines
    except (OSError, json.JSONDecodeError) as exc:
        result["events"]["error"] = str(exc)
        return result
    result["ok"] = result["db"]["integrity"] == "ok"
    return result


def transition(store: SqliteStore, paths: DispatcherPaths, mode: str, *, activation_id: str, expected_revision: int) -> dict[str, Any]:
    if mode not in MODES or not activation_id:
        raise ValueError("Control-plane mode and activation id are required")
    proof = health(paths)
    with store._connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT value FROM dispatcher_meta WHERE key = ?", (STATE_KEY,)).fetchone()
        current = {"mode": "normal", "revision": 0} if row is None else json.loads(row["value"])
        if current.get("revision") != expected_revision:
            conn.rollback()
            raise ValueError("Control-plane state changed concurrently; re-read status before retrying")
        if mode not in _ALLOWED.get(current.get("mode"), set()):
            conn.rollback()
            raise ValueError(f"Invalid control-plane transition: {current.get('mode')} -> {mode}")
        if mode == "degraded" and proof["ok"]:
            conn.rollback()
            raise ValueError("Refusing degraded mode while dispatcher health is ok")
        if mode == "normal" and not proof["ok"]:
            conn.rollback()
            raise ValueError("Refusing normal mode until dispatcher health is verified")
        next_state = {"mode": mode, "revision": expected_revision + 1, "updated_at": _now(), "activation_id": activation_id, "health": proof}
        conn.execute("INSERT INTO dispatcher_meta(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (STATE_KEY, json.dumps(next_state, sort_keys=True)))
        conn.commit()
    return next_state


def backup(paths: DispatcherPaths, destination: Path) -> dict[str, str]:
    if not paths.db_path.exists():
        raise ValueError("Dispatcher database is missing")
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / paths.db_path.name
    with sqlite3.connect(paths.db_path) as source, sqlite3.connect(target) as output:
        source.backup(output)
    if paths.events_path.exists():
        shutil.copy2(paths.events_path, destination / paths.events_path.name)
    return {"db": str(target), "events": str(destination / paths.events_path.name), "created_at": _now()}


def restore(backup_dir: Path, target: DispatcherPaths) -> dict[str, str]:
    if target.db_path.exists() or backup_dir.resolve() == target.state_dir.resolve():
        raise ValueError("Restore target must be a separate, empty state root")
    source = backup_dir / target.db_path.name
    if not source.exists():
        raise ValueError(f"Backup database missing: {source}")
    target.state_dir.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source) as input_db, sqlite3.connect(target.db_path) as output:
        input_db.backup(output)
    with sqlite3.connect(target.db_path) as conn:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    if integrity != "ok":
        raise ValueError(f"Restored database integrity failed: {integrity}")
    events = backup_dir / target.events_path.name
    if events.exists():
        shutil.copy2(events, target.events_path)
    return {"db": str(target.db_path), "events": str(target.events_path), "integrity": integrity}
