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
from app.dispatcher.schema import DDL_STATEMENTS, SCHEMA_VERSION
from app.dispatcher.store import SqliteStore
from app.dispatcher.verification_dispatch import VerificationDispatchLedger
from tests.dispatcher.verification_helpers import request as verification_request


def _store(tmp_path: Path) -> tuple[SqliteStore, object]:
    paths = load_paths({"DISPATCHER_STATE_DIR": str(tmp_path / "state")})
    store = SqliteStore(paths.db_path, JsonlEventWriter(paths.events_path))
    store.initialize()
    return store, paths


def _task() -> TaskRecord:
    now = datetime.now(timezone.utc).isoformat()
    return TaskRecord("task-1", 1, "task", "ready", "high", source_anchor_refs=[], created_at=now, updated_at=now)


def _write_canonical_v1_db(db_path: Path) -> None:
    """Create the exact pre-multi-repo dispatcher schema still supported by store."""
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE dispatcher_tasks (
                task_id TEXT PRIMARY KEY, issue_number INTEGER NOT NULL,
                title TEXT NOT NULL, status TEXT NOT NULL, priority TEXT NOT NULL,
                source_anchor_refs TEXT NOT NULL, claimed_by TEXT, lease_id TEXT,
                lease_expires_at TEXT, linked_pr TEXT, blocked_reason TEXT,
                last_heartbeat_at TEXT, sync_state TEXT, created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE dispatcher_events (
                event_id TEXT PRIMARY KEY, timestamp TEXT NOT NULL,
                task_id TEXT NOT NULL, event_type TEXT NOT NULL, actor TEXT NOT NULL,
                lease_id TEXT, payload TEXT
            );
            """
        )


def _write_pre_repair_v3_state(tmp_path: Path):
    """Create deployed v3 state from before verification head rebinding."""
    store, paths = _store(tmp_path)
    store.upsert_task(_task())
    run = VerificationDispatchLedger(store).ingest(verification_request())
    with sqlite3.connect(paths.db_path) as conn:
        conn.execute(
            """
            INSERT INTO verification_attempts (
                attempt_id, run_id, attempt_kind, ordinal, session_id,
                capability, reasoning_effort, context_hash, outcome,
                receipt_json, created_at
            ) VALUES (?, ?, 'review', 1, 'review-session', 'terra', 'high',
                      'context-hash', 'clean', '{"legacy":true}',
                      '2026-07-13T12:00:01+00:00')
            """,
            ("attempt-pre-repair", run.run_id),
        )
        conn.execute(
            """
            INSERT INTO verification_exceptions (
                exception_id, run_id, failure_class, head_sha, packet_json,
                created_at, updated_at
            ) VALUES (?, ?, 'review_blocked', ?, '{"legacy":true}',
                      '2026-07-13T12:00:02+00:00',
                      '2026-07-13T12:00:02+00:00')
            """,
            ("exception-pre-repair", run.run_id, run.requested_head_sha),
        )
        conn.execute("ALTER TABLE verification_runs DROP COLUMN verified_head_sha")
        conn.execute("ALTER TABLE verification_runs DROP COLUMN current_head_sha")
        conn.execute("ALTER TABLE verification_runs DROP COLUMN supporting_authority_json")
        conn.commit()
    paths.events_path.touch()
    return paths, run


def test_recovery_accepts_and_restores_canonical_v1_until_store_migrates_it(
    tmp_path: Path,
) -> None:
    paths = load_paths({"DISPATCHER_STATE_DIR": str(tmp_path / "state")})
    paths.state_dir.mkdir()
    _write_canonical_v1_db(paths.db_path)
    paths.events_path.touch()

    assert control_plane.health(paths)["ok"] is True
    backup = tmp_path / "backup"
    control_plane.backup(paths, backup)
    restored = load_paths({"DISPATCHER_STATE_DIR": str(tmp_path / "restored")})
    assert control_plane.restore(backup, restored)["integrity"] == "ok"

    # Recovery preserves the v1 artifact; the normal store path owns its
    # atomic in-place migration once the restored dispatcher is opened.
    assert SqliteStore(restored.db_path).get_meta("schema_version") == str(SCHEMA_VERSION)


def test_pre_repair_v3_backup_restore_self_migrates_without_data_loss(
    tmp_path: Path,
) -> None:
    paths, original = _write_pre_repair_v3_state(tmp_path)

    assert control_plane.health(paths)["ok"] is True
    backup = tmp_path / "backup"
    control_plane.backup(paths, backup)
    restored = load_paths({"DISPATCHER_STATE_DIR": str(tmp_path / "restored")})
    assert control_plane.restore(backup, restored)["integrity"] == "ok"

    with sqlite3.connect(restored.db_path) as conn:
        columns_before = {
            row[1] for row in conn.execute("PRAGMA table_info(verification_runs)")
        }
        run_before = conn.execute(
            "SELECT run_id, head_sha, status FROM verification_runs"
        ).fetchone()
        attempt_before = conn.execute(
            "SELECT attempt_id, run_id, receipt_json FROM verification_attempts"
        ).fetchone()
        exception_before = conn.execute(
            "SELECT exception_id, run_id, packet_json FROM verification_exceptions"
        ).fetchone()
    assert {
        "current_head_sha",
        "verified_head_sha",
        "supporting_authority_json",
    }.isdisjoint(columns_before)

    migrated = SqliteStore(restored.db_path)
    assert migrated.get_meta("schema_version") == str(SCHEMA_VERSION)
    with sqlite3.connect(restored.db_path) as conn:
        columns_after = {
            row[1] for row in conn.execute("PRAGMA table_info(verification_runs)")
        }
        run_after = conn.execute(
            "SELECT run_id, head_sha, status FROM verification_runs"
        ).fetchone()
        rebound_heads = conn.execute(
            "SELECT current_head_sha, verified_head_sha FROM verification_runs"
        ).fetchone()
        attempt_after = conn.execute(
            "SELECT attempt_id, run_id, receipt_json FROM verification_attempts"
        ).fetchone()
        exception_after = conn.execute(
            "SELECT exception_id, run_id, packet_json FROM verification_exceptions"
        ).fetchone()

    assert {
        "current_head_sha",
        "verified_head_sha",
        "supporting_authority_json",
    } <= columns_after
    assert run_after == run_before == (original.run_id, original.requested_head_sha, "queued")
    assert rebound_heads == (original.requested_head_sha, None)
    with sqlite3.connect(restored.db_path) as conn:
        supporting_authority = conn.execute(
            "SELECT supporting_authority_json FROM verification_runs WHERE run_id=?",
            (original.run_id,),
        ).fetchone()[0]
    assert json.loads(supporting_authority) == original.request["supporting_issues"]
    assert attempt_after == attempt_before
    assert exception_after == exception_before
    assert migrated.get_task("task-1") is not None
    assert control_plane.health(restored)["ok"] is True


def test_pre_supporting_issue_v3_host_startup_migrates_without_data_loss(
    tmp_path: Path,
) -> None:
    paths, original = _write_pre_repair_v3_state(tmp_path)
    with sqlite3.connect(paths.db_path) as conn:
        stored = json.loads(
            conn.execute(
                "SELECT request_json FROM verification_runs WHERE run_id=?",
                (original.run_id,),
            ).fetchone()[0]
        )
        stored.pop("supporting_issues")
        stored.pop("artifact_provenance")
        stored["base_ref"] = "main"
        stored["head_ref"] = "codex/legacy-verification"
        legacy_audit = json.dumps(stored, sort_keys=True)
        conn.execute(
            "UPDATE verification_runs SET request_json=? WHERE run_id=?",
            (legacy_audit, original.run_id),
        )
        run_before = conn.execute(
            "SELECT run_id, head_sha, status FROM verification_runs"
        ).fetchone()
        attempt_before = conn.execute(
            "SELECT attempt_id, run_id, receipt_json FROM verification_attempts"
        ).fetchone()
        exception_before = conn.execute(
            "SELECT exception_id, run_id, packet_json FROM verification_exceptions"
        ).fetchone()
        conn.commit()

    state = VerificationDispatchLedger(SqliteStore(paths.db_path))
    migrated = state.get(original.run_id)

    assert migrated is not None
    assert migrated.request["supporting_issues"] == []
    assert migrated.supporting_authority == ()
    with sqlite3.connect(paths.db_path) as conn:
        run_after = conn.execute(
            "SELECT run_id, head_sha, status FROM verification_runs"
        ).fetchone()
        attempt_after = conn.execute(
            "SELECT attempt_id, run_id, receipt_json FROM verification_attempts"
        ).fetchone()
        exception_after = conn.execute(
            "SELECT exception_id, run_id, packet_json FROM verification_exceptions"
        ).fetchone()
        request_after, supporting_after = conn.execute(
            "SELECT request_json, supporting_authority_json FROM verification_runs "
            "WHERE run_id=?",
            (original.run_id,),
        ).fetchone()
    assert run_after == run_before
    assert attempt_after == attempt_before
    assert exception_after == exception_before
    assert request_after == legacy_audit
    assert supporting_after == "[]"
    assert control_plane.health(paths)["ok"] is True


@pytest.mark.parametrize(
    "corruption_sql, expected_error",
    [
        (
            "DROP TABLE verification_attempts",
            "missing dispatcher tables: verification_attempts",
        ),
        (
            "ALTER TABLE verification_runs DROP COLUMN coordinator_session_id",
            "missing dispatcher columns in verification_runs: coordinator_session_id",
        ),
        (
            """
            ALTER TABLE verification_exceptions RENAME TO verification_exceptions_old;
            CREATE TABLE verification_exceptions (
                exception_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                failure_class TEXT NOT NULL,
                head_sha TEXT NOT NULL,
                packet_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(run_id) REFERENCES verification_runs(run_id)
            );
            INSERT INTO verification_exceptions
                SELECT * FROM verification_exceptions_old;
            DROP TABLE verification_exceptions_old;
            """,
            "missing required unique key in verification_exceptions: "
            "run_id, failure_class, head_sha",
        ),
    ],
)
def test_pre_repair_v3_corruption_still_fails_closed(
    tmp_path: Path,
    corruption_sql: str,
    expected_error: str,
) -> None:
    paths, _ = _write_pre_repair_v3_state(tmp_path)
    with sqlite3.connect(paths.db_path) as conn:
        conn.executescript(corruption_sql)
    before = paths.db_path.read_bytes()

    with pytest.raises(ValueError, match=expected_error):
        SqliteStore(paths.db_path).get_meta("schema_version")
    assert paths.db_path.read_bytes() == before

    proof = control_plane.health(paths)
    assert proof["ok"] is False
    assert proof["db"]["error"] == expected_error
    with pytest.raises(ValueError, match="unsafe"):
        control_plane.backup(paths, tmp_path / "backup")
    assert not (tmp_path / "backup").exists()

    backup = tmp_path / "restore-source"
    backup.mkdir()
    (backup / paths.db_path.name).write_bytes(before)
    (backup / paths.events_path.name).write_text("", encoding="utf-8")
    restored = load_paths({"DISPATCHER_STATE_DIR": str(tmp_path / "restored")})
    with pytest.raises(ValueError, match=expected_error):
        control_plane.restore(backup, restored)
    assert not restored.state_dir.exists()


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
    assert migrated.get_meta("schema_version") == str(SCHEMA_VERSION)


def test_malformed_v2_migration_does_not_commit_v3(tmp_path: Path) -> None:
    _, paths = _store(tmp_path)
    with sqlite3.connect(paths.db_path) as conn:
        conn.execute(
            "UPDATE dispatcher_meta SET value = '2' WHERE key = 'schema_version'"
        )
        conn.execute(
            "ALTER TABLE verification_runs DROP COLUMN coordinator_session_id"
        )
        conn.commit()

    with pytest.raises(
        ValueError,
        match="missing dispatcher columns in verification_runs: coordinator_session_id",
    ):
        SqliteStore(paths.db_path).get_meta("schema_version")

    with sqlite3.connect(paths.db_path) as conn:
        version = conn.execute(
            "SELECT value FROM dispatcher_meta WHERE key = 'schema_version'"
        ).fetchone()[0]
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(verification_runs)")
        }
    assert version == "2"
    assert "coordinator_session_id" not in columns


def test_valid_v2_migration_still_reaches_v3(tmp_path: Path) -> None:
    _, paths = _store(tmp_path)
    with sqlite3.connect(paths.db_path) as conn:
        conn.execute(
            "UPDATE dispatcher_meta SET value = '2' WHERE key = 'schema_version'"
        )
        conn.commit()

    migrated = SqliteStore(paths.db_path)
    assert migrated.get_meta("schema_version") == str(SCHEMA_VERSION)


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


def test_future_schema_is_rejected_without_mutating_recovery_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Every recovery entry point must leave an unknown schema byte-for-byte intact."""
    _, paths = _store(tmp_path)
    paths.events_path.touch()
    with sqlite3.connect(paths.db_path) as conn:
        conn.execute(
            "UPDATE dispatcher_meta SET value = '99' WHERE key = 'schema_version'"
        )
    before = paths.db_path.read_bytes()

    with pytest.raises(ValueError, match="unsupported dispatcher schema_version: '99'"):
        SqliteStore(paths.db_path).get_meta("schema_version")
    assert paths.db_path.read_bytes() == before

    proof = control_plane.health(paths)
    assert proof["ok"] is False
    assert proof["db"]["error"] == "unsupported dispatcher schema_version: 99"
    assert paths.db_path.read_bytes() == before

    backup_dir = tmp_path / "backup"
    with pytest.raises(ValueError, match="unsafe"):
        control_plane.backup(paths, backup_dir)
    assert not backup_dir.exists()
    assert paths.db_path.read_bytes() == before

    monkeypatch.setenv("DISPATCHER_STATE_DIR", str(paths.state_dir))
    assert main(["status", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["control_plane"] == {
        "mode": "unavailable",
        "revision": None,
        "error": "unsupported dispatcher schema_version: 99",
    }
    assert paths.db_path.read_bytes() == before

    restore_source = tmp_path / "restore-source"
    restore_source.mkdir()
    (restore_source / paths.db_path.name).write_bytes(before)
    (restore_source / paths.events_path.name).write_text("", encoding="utf-8")
    restored = load_paths({"DISPATCHER_STATE_DIR": str(tmp_path / "restored")})
    with pytest.raises(ValueError, match="unsupported dispatcher schema_version: 99"):
        control_plane.restore(restore_source, restored)
    assert not restored.state_dir.exists()
    assert paths.db_path.read_bytes() == before


def test_recovery_rejects_column_compatible_schema_without_unique_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Recovery observation must not certify a DB that later rejects UPSERTs."""
    paths = load_paths({"DISPATCHER_STATE_DIR": str(tmp_path / "state")})
    paths.state_dir.mkdir()
    constraint_free_ddl = ";\n".join(DDL_STATEMENTS).replace(
        " TEXT PRIMARY KEY", " TEXT NOT NULL"
    )
    with sqlite3.connect(paths.db_path) as conn:
        conn.executescript(constraint_free_ddl)
        conn.execute(
            "INSERT INTO dispatcher_meta(key, value) VALUES ('schema_version', '2')"
        )
    paths.events_path.touch()
    before = paths.db_path.read_bytes()

    proof = control_plane.health(paths)
    assert proof["ok"] is False
    assert proof["db"]["error"] == "missing required unique key in dispatcher_tasks: task_id"
    with pytest.raises(ValueError, match="unsafe"):
        control_plane.backup(paths, tmp_path / "backup")

    backup = tmp_path / "restore-source"
    backup.mkdir()
    (backup / paths.db_path.name).write_bytes(before)
    (backup / paths.events_path.name).write_text("", encoding="utf-8")
    restored = load_paths({"DISPATCHER_STATE_DIR": str(tmp_path / "restored")})
    with pytest.raises(ValueError, match="missing required unique key"):
        control_plane.restore(backup, restored)
    assert not restored.state_dir.exists()

    monkeypatch.setenv("DISPATCHER_STATE_DIR", str(paths.state_dir))
    assert main(["status", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert paths.db_path.read_bytes() == before
    assert payload["coordination_mode"] == "github-label-only-fallback"
    assert payload["control_plane"] == {
        "mode": "unavailable",
        "revision": None,
        "error": "missing required unique key in dispatcher_tasks: task_id",
    }


def test_recovery_rejects_partial_unique_key_without_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A partial UNIQUE index does not support the dispatcher's bare UPSERT."""
    paths = load_paths({"DISPATCHER_STATE_DIR": str(tmp_path / "state")})
    paths.state_dir.mkdir()
    partial_meta_ddl = ";\n".join(DDL_STATEMENTS).replace(
        "key TEXT PRIMARY KEY", "key TEXT NOT NULL"
    )
    with sqlite3.connect(paths.db_path) as conn:
        conn.executescript(partial_meta_ddl)
        conn.execute(
            "CREATE UNIQUE INDEX dispatcher_meta_key_partial "
            "ON dispatcher_meta(key) WHERE key IS NOT NULL"
        )
        conn.execute(
            "INSERT INTO dispatcher_meta(key, value) VALUES ('schema_version', '2')"
        )
    paths.events_path.touch()
    before = paths.db_path.read_bytes()

    proof = control_plane.health(paths)
    assert proof["ok"] is False
    assert proof["db"]["error"] == "missing required unique key in dispatcher_meta: key"
    backup_dir = tmp_path / "backup"
    with pytest.raises(ValueError, match="unsafe"):
        control_plane.backup(paths, backup_dir)
    assert not backup_dir.exists()

    backup = tmp_path / "restore-source"
    backup.mkdir()
    (backup / paths.db_path.name).write_bytes(before)
    (backup / paths.events_path.name).write_text("", encoding="utf-8")
    restored = load_paths({"DISPATCHER_STATE_DIR": str(tmp_path / "restored")})
    with pytest.raises(ValueError, match="missing required unique key in dispatcher_meta"):
        control_plane.restore(backup, restored)
    assert not restored.state_dir.exists()

    monkeypatch.setenv("DISPATCHER_STATE_DIR", str(paths.state_dir))
    assert main(["status", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert paths.db_path.read_bytes() == before
    assert payload["control_plane"]["error"] == (
        "missing required unique key in dispatcher_meta: key"
    )


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


def test_restore_events_copy_failure_leaves_target_empty_and_retryable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, paths = _store(tmp_path)
    paths.events_path.touch()
    backup = tmp_path / "backup"
    control_plane.backup(paths, backup)
    restored = load_paths({"DISPATCHER_STATE_DIR": str(tmp_path / "restored")})
    original_copy2 = control_plane.shutil.copy2

    def fail_events_copy(source: object, destination: object, *_args: object, **_kwargs: object) -> object:
        if Path(source) == backup / "events.jsonl":
            raise OSError("events copy failed")
        return original_copy2(source, destination, *_args, **_kwargs)

    monkeypatch.setattr(control_plane.shutil, "copy2", fail_events_copy)
    with pytest.raises(ValueError, match="Dispatcher restore failed: events copy failed"):
        control_plane.restore(backup, restored)
    assert not restored.state_dir.exists()
    assert not list(tmp_path.glob(".restored.tmp-*"))

    monkeypatch.setattr(control_plane.shutil, "copy2", original_copy2)
    assert control_plane.restore(backup, restored)["integrity"] == "ok"


def test_restore_rejects_custom_artifacts_outside_empty_target_root(tmp_path: Path) -> None:
    _, paths = _store(tmp_path)
    paths.events_path.touch()
    backup = tmp_path / "backup"
    control_plane.backup(paths, backup)
    restored = load_paths(
        {
            "DISPATCHER_STATE_DIR": str(tmp_path / "restored"),
            "DISPATCHER_DB_PATH": str(tmp_path / "live" / "dispatcher.sqlite3"),
            "DISPATCHER_EVENTS_PATH": str(tmp_path / "live" / "events.jsonl"),
        }
    )
    with pytest.raises(ValueError, match="artifacts must be inside"):
        control_plane.restore(backup, restored)
    assert not restored.state_dir.exists()
    assert not (tmp_path / "live").exists()


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
    assert "missing dispatcher tables" in payload["control_plane"]["error"]


def test_cli_status_is_readonly_for_initialized_database_missing_schema_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    state_dir = tmp_path / "state"
    monkeypatch.setenv("DISPATCHER_STATE_DIR", str(state_dir))
    store = SqliteStore(state_dir / "dispatcher.sqlite3")
    store.initialize()
    with sqlite3.connect(store.db_path) as conn:
        conn.execute("DELETE FROM dispatcher_meta WHERE key = 'schema_version'")
    before = store.db_path.read_bytes()

    assert main(["status", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert store.db_path.read_bytes() == before
    assert payload["ok"] is True
    assert payload["coordination_mode"] == "github-label-only-fallback"
    assert payload["fallback_reason"] == "dispatcher_db_uninitialized"
    assert payload["control_plane"] == {
        "mode": "unavailable",
        "revision": None,
        "error": "missing dispatcher schema_version",
    }


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
