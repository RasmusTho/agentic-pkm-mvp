from __future__ import annotations

import json
import sqlite3
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
    with pytest.raises(ValueError, match="Backup destination must be separate"):
        control_plane.backup(paths, paths.state_dir)
    with pytest.raises(ValueError, match="Backup destination must be separate"):
        control_plane.backup(paths, paths.state_dir / "nested")
    control_plane.backup(paths, tmp_path / "backup")
    restored = load_paths({"DISPATCHER_STATE_DIR": str(tmp_path / "restored")})
    restored.state_dir.mkdir()
    restored.events_path.touch()
    with pytest.raises(ValueError, match="separate, empty"):
        control_plane.restore(tmp_path / "backup", restored)


def test_restore_rejects_corrupt_backup_without_creating_target(tmp_path: Path) -> None:
    _, paths = _store(tmp_path)
    backup = tmp_path / "backup"
    backup.mkdir()
    (backup / paths.db_path.name).write_text("not sqlite", encoding="utf-8")
    (backup / paths.events_path.name).write_text("{}\n", encoding="utf-8")
    restored = load_paths({"DISPATCHER_STATE_DIR": str(tmp_path / "restored")})
    with pytest.raises(ValueError, match="Backup database"):
        control_plane.restore(backup, restored)
    assert not restored.state_dir.exists()


@pytest.mark.parametrize(
    "schema_sql, expected_error",
    [
        (None, "missing dispatcher tables"),
        ("CREATE TABLE unrelated (id INTEGER)", "missing dispatcher tables"),
        (
            """
            CREATE TABLE dispatcher_tasks (task_id TEXT);
            CREATE TABLE dispatcher_leases (lease_id TEXT);
            CREATE TABLE dispatcher_events (event_id TEXT);
            CREATE TABLE dispatcher_meta (key TEXT, value TEXT);
            INSERT INTO dispatcher_meta VALUES ('schema_version', '2');
            """,
            "missing dispatcher columns",
        ),
    ],
)
def test_recovery_rejects_sqlite_without_dispatcher_schema(
    tmp_path: Path, schema_sql: str | None, expected_error: str
) -> None:
    paths = load_paths({"DISPATCHER_STATE_DIR": str(tmp_path / "state")})
    paths.state_dir.mkdir()
    with sqlite3.connect(paths.db_path) as conn:
        if schema_sql is not None:
            conn.executescript(schema_sql)
    paths.events_path.touch()

    proof = control_plane.health(paths)
    assert proof["ok"] is False
    assert expected_error in proof["db"]["error"]
    with pytest.raises(ValueError, match="unsafe"):
        control_plane.backup(paths, tmp_path / "backup")

    backup = tmp_path / "restore-source"
    backup.mkdir()
    (backup / paths.db_path.name).write_bytes(paths.db_path.read_bytes())
    (backup / paths.events_path.name).write_text("", encoding="utf-8")
    restored = load_paths({"DISPATCHER_STATE_DIR": str(tmp_path / "restored")})
    with pytest.raises(ValueError, match=expected_error):
        control_plane.restore(backup, restored)
    assert not restored.state_dir.exists()


def test_health_accepts_compatible_v1_shape_until_store_migrates_it(
    tmp_path: Path,
) -> None:
    store, paths = _store(tmp_path)
    with sqlite3.connect(paths.db_path) as conn:
        conn.execute(
            "UPDATE dispatcher_meta SET value = '1' WHERE key = 'schema_version'"
        )
    paths.events_path.touch()

    assert control_plane.health(paths)["ok"] is True
    migrated = SqliteStore(paths.db_path)
    assert migrated.get_meta("schema_version") == "2"


def test_health_rejects_unsupported_dispatcher_schema_version(tmp_path: Path) -> None:
    _, paths = _store(tmp_path)
    with sqlite3.connect(paths.db_path) as conn:
        conn.execute(
            "UPDATE dispatcher_meta SET value = '99' WHERE key = 'schema_version'"
        )
    paths.events_path.touch()

    proof = control_plane.health(paths)
    assert proof["ok"] is False
    assert "unsupported dispatcher schema_version" in proof["db"]["error"]


def test_backup_rejects_custom_events_target_equal_to_source_before_writing(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "state"
    logs_dir = tmp_path / "logs"
    paths = load_paths(
        {
            "DISPATCHER_STATE_DIR": str(state_dir),
            "DISPATCHER_EVENTS_PATH": str(logs_dir / "custom.jsonl"),
        }
    )
    store = SqliteStore(paths.db_path, JsonlEventWriter(paths.events_path))
    store.initialize()
    logs_dir.mkdir()
    paths.events_path.touch()

    with pytest.raises(ValueError, match="separate from dispatcher state"):
        control_plane.backup(paths, logs_dir)
    assert not (logs_dir / paths.db_path.name).exists()


def test_backup_uses_canonical_names_and_restores_custom_sources(
    tmp_path: Path,
) -> None:
    paths = load_paths(
        {
            "DISPATCHER_STATE_DIR": str(tmp_path / "state"),
            "DISPATCHER_DB_PATH": str(tmp_path / "db-source" / "artifact"),
            "DISPATCHER_EVENTS_PATH": str(tmp_path / "event-source" / "artifact"),
        }
    )
    store = SqliteStore(paths.db_path, JsonlEventWriter(paths.events_path))
    store.initialize()
    paths.events_path.parent.mkdir(parents=True, exist_ok=True)
    paths.events_path.touch()

    backup_dir = tmp_path / "backup"
    receipt = control_plane.backup(paths, backup_dir)
    assert Path(receipt["db"]).name == "dispatcher.sqlite3"
    assert Path(receipt["events"]).name == "events.jsonl"
    assert Path(receipt["db"]) != Path(receipt["events"])

    restored = load_paths({"DISPATCHER_STATE_DIR": str(tmp_path / "restored")})
    result = control_plane.restore(backup_dir, restored)
    assert result["integrity"] == "ok"


def test_backup_failure_does_not_publish_partial_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, paths = _store(tmp_path)
    paths.events_path.touch()
    destination = tmp_path / "backup"

    def fail_copy(*_args: object, **_kwargs: object) -> None:
        raise OSError("copy failed")

    monkeypatch.setattr(control_plane.shutil, "copy2", fail_copy)
    with pytest.raises(ValueError, match="backup failed"):
        control_plane.backup(paths, destination)
    assert not destination.exists()
    assert not list(tmp_path.glob(".backup.tmp-*"))


def test_restore_rejects_corrupt_events_without_creating_target(tmp_path: Path) -> None:
    _, paths = _store(tmp_path)
    backup = tmp_path / "backup"
    backup.mkdir()
    with sqlite3.connect(backup / paths.db_path.name) as conn:
        conn.execute("CREATE TABLE probe (id INTEGER)")
    (backup / paths.events_path.name).write_text("{not-json}\n", encoding="utf-8")
    restored = load_paths({"DISPATCHER_STATE_DIR": str(tmp_path / "restored")})
    with pytest.raises(ValueError, match="Backup events are invalid"):
        control_plane.restore(backup, restored)
    assert not restored.state_dir.exists()


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


def test_cli_status_emits_fallback_payload_for_uninitialized_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "dispatcher.sqlite3").touch()
    monkeypatch.setenv("DISPATCHER_STATE_DIR", str(state_dir))
    assert main(["status", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["coordination_mode"] == "github-label-only-fallback"
    assert payload["fallback_reason"] == "dispatcher_db_uninitialized"
    assert payload["control_plane"]["mode"] == "unavailable"
    assert "no such table" in payload["control_plane"]["error"]


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
