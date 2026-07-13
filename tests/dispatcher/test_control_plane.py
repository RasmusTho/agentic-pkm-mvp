from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.dispatcher import control_plane, leases
from app.dispatcher.cli import main
from app.dispatcher.config import load_paths
from app.dispatcher.events import JsonlEventWriter
from app.dispatcher.models import TaskRecord
from app.dispatcher.store import SqliteStore


def _store(tmp_path: Path) -> tuple[SqliteStore, object]:
    paths = load_paths({"DISPATCHER_STATE_DIR": str(tmp_path / "state")})
    store = SqliteStore(paths.db_path, JsonlEventWriter(paths.events_path))
    store.initialize()
    return store, paths


def _task() -> TaskRecord:
    now = datetime.now(timezone.utc).isoformat()
    return TaskRecord("task-1", 1, "task", "ready", "high", source_anchor_refs=[], created_at=now, updated_at=now)


def test_health_backup_and_restore_to_separate_root(tmp_path: Path) -> None:
    store, paths = _store(tmp_path)
    store.upsert_task(_task())
    paths.events_path.touch()
    receipt = control_plane.backup(paths, tmp_path / "backup")
    restored = load_paths({"DISPATCHER_STATE_DIR": str(tmp_path / "restored")})
    result = control_plane.restore(tmp_path / "backup", restored)
    assert receipt["db"].endswith("dispatcher.sqlite3")
    assert result["integrity"] == "ok"
    assert SqliteStore(restored.db_path).get_task("task-1") is not None
    with pytest.raises(ValueError, match="separate, empty"):
        control_plane.restore(tmp_path / "backup", paths)


def test_control_plane_rejects_missing_events_and_nonempty_restore_target(tmp_path: Path) -> None:
    store, paths = _store(tmp_path)
    store.upsert_task(_task())
    assert control_plane.health(paths)["ok"] is False
    with pytest.raises(ValueError, match="unsafe"):
        control_plane.backup(paths, tmp_path / "backup")

    paths.events_path.touch()
    control_plane.backup(paths, tmp_path / "backup")
    restored = load_paths({"DISPATCHER_STATE_DIR": str(tmp_path / "restored")})
    restored.state_dir.mkdir()
    restored.events_path.touch()
    with pytest.raises(ValueError, match="separate, empty"):
        control_plane.restore(tmp_path / "backup", restored)


def test_mode_transition_rejects_stale_revision_without_losing_accepted_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store, paths = _store(tmp_path)
    monkeypatch.setattr(control_plane, "health", lambda _paths: {"ok": False})
    accepted = control_plane.transition(store, paths, "degraded", activation_id="incident", expected_revision=0)
    assert accepted["revision"] == 1
    with pytest.raises(ValueError, match="changed concurrently"):
        control_plane.transition(store, paths, "degraded", activation_id="other", expected_revision=0)
    assert control_plane.state(store)["activation_id"] == "incident"


def test_cli_status_reads_persisted_control_plane_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    state_dir = tmp_path / "state"
    monkeypatch.setenv("DISPATCHER_STATE_DIR", str(state_dir))
    store = SqliteStore(state_dir / "dispatcher.sqlite3")
    store.initialize()
    store.set_meta(control_plane.STATE_KEY, '{"activation_id":"receipt","mode":"recovery","revision":4,"updated_at":"now"}')
    assert main(["status", "--json"]) == 0
    assert '"mode": "recovery"' in capsys.readouterr().out


def test_expired_lease_rejects_heartbeat_and_preserves_takeover(tmp_path: Path) -> None:
    store, _ = _store(tmp_path)
    store.upsert_task(_task())
    _, lease = leases.claim(store, "task-1", "old")
    expired = store.get_lease(lease.lease_id)
    assert expired is not None
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    expired.expires_at = past
    store.upsert_lease(expired)
    with pytest.raises(ValueError, match="has expired"):
        leases.heartbeat(store, "task-1", "old")
    task, replacement = leases.claim(store, "task-1", "new", takeover_stale=True)
    assert task.lease_id == replacement.lease_id
    with pytest.raises(ValueError, match="held by new"):
        leases.heartbeat(store, "task-1", "old")
    current = store.get_task("task-1")
    assert current is not None and current.lease_id == replacement.lease_id
