"""Slice 4 (#2973) — one-time DB->log export of historical decision rows.

The acceptance property this module proves: a `decisions` row that predates the
dual-write cutover (exists only in Postgres, e.g. the deprecated
`PgDecisions.put` classification path) is exported to the canonical receipt log
faithfully, idempotently, and *before* `rebuild_decisions_projection()` can ever
truncate the table and lose it (issue #2973, 2026-07-05 comment: this happened
on prod residue). `not pg` tests pin the pure fail-loud/formatting logic; `pg`
tests are the real round-trip (skip cleanly without Postgres).
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.jobs.decisions_export import (
    DecisionExportError,
    _created_at_iso,
    _created_at_iso_from_raw,
    _value_json,
    export_decisions_to_receipt_log,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# not-pg: pure formatting/dedupe-key helpers
# ---------------------------------------------------------------------------


def test_created_at_iso_normalizes_to_utc() -> None:
    naive = datetime(2026, 1, 1, 12, 0, 0)
    assert _created_at_iso(naive) == "2026-01-01T12:00:00+00:00"
    aware = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    assert _created_at_iso(aware) == "2026-01-01T12:00:00+00:00"


def test_created_at_iso_from_raw_handles_string_and_z_suffix() -> None:
    assert _created_at_iso_from_raw("2026-01-01T12:00:00Z") == "2026-01-01T12:00:00+00:00"
    assert _created_at_iso_from_raw("") == ""
    assert _created_at_iso_from_raw(None) == ""
    assert _created_at_iso_from_raw("not-a-timestamp") == ""


def test_value_json_sorts_keys_and_handles_empty() -> None:
    assert _value_json({"b": 1, "a": 2}) == json.dumps({"a": 2, "b": 1}, sort_keys=True)
    assert _value_json(None) == "{}"
    assert _value_json({}) == "{}"
    assert _value_json(json.dumps({"a": 1})) == json.dumps({"a": 1}, sort_keys=True)


def test_export_raises_loud_on_missing_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A malformed row (no `key`) aborts the export rather than being skipped --
    unlike rebuild's orphan-skip, a row this function cannot place into the log
    is about to be unrecoverable the moment a rebuild truncates its only home."""
    import app.jobs.decisions_export as export_mod

    monkeypatch.setattr(export_mod, "_db_rows", lambda: [
        {
            "id": "row-1",
            "object_id": str(uuid.uuid4()),
            "key": None,
            "value": {},
            "created_at": datetime.now(timezone.utc),
        }
    ])
    monkeypatch.setattr(export_mod.DEFAULT_WRITE_GUARD, "assert_writes_allowed", lambda action: None)
    monkeypatch.setattr(export_mod, "iter_decision_receipts", lambda vault_root=None: [])

    with pytest.raises(DecisionExportError, match="no key"):
        export_decisions_to_receipt_log(tmp_path / "vault")


def test_export_raises_loud_on_missing_object_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.jobs.decisions_export as export_mod

    monkeypatch.setattr(export_mod, "_db_rows", lambda: [
        {
            "id": "row-1",
            "object_id": None,
            "key": "classification",
            "value": {},
            "created_at": datetime.now(timezone.utc),
        }
    ])
    monkeypatch.setattr(export_mod.DEFAULT_WRITE_GUARD, "assert_writes_allowed", lambda action: None)
    monkeypatch.setattr(export_mod, "iter_decision_receipts", lambda vault_root=None: [])

    with pytest.raises(DecisionExportError, match="no object_id"):
        export_decisions_to_receipt_log(tmp_path / "vault")


def test_export_raises_loud_on_unusable_created_at(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.jobs.decisions_export as export_mod

    monkeypatch.setattr(export_mod, "_db_rows", lambda: [
        {
            "id": "row-1",
            "object_id": str(uuid.uuid4()),
            "key": "classification",
            "value": {},
            "created_at": None,
        }
    ])
    monkeypatch.setattr(export_mod.DEFAULT_WRITE_GUARD, "assert_writes_allowed", lambda action: None)
    monkeypatch.setattr(export_mod, "iter_decision_receipts", lambda vault_root=None: [])

    with pytest.raises(DecisionExportError, match="created_at"):
        export_decisions_to_receipt_log(tmp_path / "vault")


# ---------------------------------------------------------------------------
# pg: real DB round-trip
# ---------------------------------------------------------------------------

import psycopg  # noqa: E402


@pytest.fixture
def scratch_db(monkeypatch: pytest.MonkeyPatch):
    """A throwaway database at ``alembic upgrade head``, wired into DATABASE_URL.

    Duplicated from ``tests/jobs/test_decisions_projection_rebuild.py`` per that
    file's own convention note (copy, don't cross-import test fixtures).
    """
    from app.db.dsn import resolve_dsn

    admin_dsn = resolve_dsn()
    if not admin_dsn:
        pytest.skip("DATABASE_URL/DB_DSN not configured")
    try:
        probe = psycopg.connect(admin_dsn, connect_timeout=2)
    except Exception as exc:  # pragma: no cover - environment guard
        pytest.skip(f"Postgres unavailable: {exc}")
    probe.close()

    name = f"scratch_decexport_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
        conn.execute(f'ALTER DATABASE "{name}" SET lc_messages = \'C\'')
    base, _, _ = admin_dsn.rpartition("/")
    dsn = f"{base}/{name}"

    from alembic import command
    from alembic.config import Config

    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.delenv("DB_DSN", raising=False)
    monkeypatch.setenv("STORE_BACKEND", "pg")
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "app" / "alembic"))
    command.upgrade(cfg, "head")

    from app.services.decisions import _resolved_backend

    _resolved_backend.cache_clear()

    yield dsn

    _resolved_backend.cache_clear()
    try:
        with psycopg.connect(admin_dsn, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    except Exception:
        pass


def _insert_object(dsn: str, *, object_id: str | None = None, obj_uuid: str | None = None) -> tuple[str, str]:
    oid = object_id or str(uuid.uuid4())
    ouuid = obj_uuid or oid
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO objects (id, uuid, kind, payload) VALUES (%s, %s, %s, %s::jsonb)",
            (oid, ouuid, "note", "{}"),
        )
    return oid, ouuid


def _insert_legacy_decision_row(
    dsn: str,
    *,
    object_id: str,
    key: str,
    value: dict,
    created_at: datetime,
    agent: str = "classifier",
    kind: str = "classification",
) -> str:
    """Insert a DB-only decision row the way the deprecated pre-cutover
    ``PgDecisions.put`` path did (``app/stores/postgres.py``): no receipt-log
    write, no ``trace_id`` folded into ``value``. This is exactly the shape of
    the 2 historical prod rows this slice targets."""
    row_id = str(uuid.uuid4())
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO decisions (id, object_id, agent, kind, key, value, created_at) "
            "VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s)",
            (row_id, object_id, agent, kind, key, json.dumps(value), created_at),
        )
    return row_id


def _allow_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.receipts.decision_receipt_log as receipt_log

    monkeypatch.setattr(
        receipt_log.DEFAULT_WRITE_GUARD, "assert_writes_allowed", lambda action: None
    )


@pytest.mark.pg
def test_export_moves_historical_db_only_row_to_log(
    scratch_db: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A DB-only row (no receipt yet) is exported faithfully: exact value
    passthrough, no injected trace_id, correct object_id/key/created_at."""
    vault = tmp_path / "vault"
    vault.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("VAULT_ROOT", str(vault))
    _allow_guard(monkeypatch)

    oid, _ = _insert_object(scratch_db)
    created = datetime(2026, 6, 1, 9, 30, 0, tzinfo=timezone.utc)
    legacy_value = {"type": "task", "confidence": 0.87}  # NOTE: no "trace_id" key
    _insert_legacy_decision_row(scratch_db, object_id=oid, key="classification", value=legacy_value, created_at=created)

    from app.receipts.decision_receipt_log import iter_decision_receipts

    assert iter_decision_receipts(vault) == []  # nothing in the log yet

    summary = export_decisions_to_receipt_log(vault)
    assert summary.total_db_rows == 1
    assert summary.already_in_log == 0
    assert summary.exported == 1

    receipts = iter_decision_receipts(vault)
    assert len(receipts) == 1
    receipt = receipts[0]
    assert receipt["object_id"] == oid
    assert receipt["key"] == "classification"
    assert receipt["value"] == legacy_value  # exact passthrough
    assert "trace_id" not in receipt["value"]  # no injected trace_id
    assert receipt["created_at"] == "2026-06-01T09:30:00+00:00"
    assert receipt["schema_version"] == 1


@pytest.mark.pg
def test_export_is_idempotent(
    scratch_db: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Re-running the export after a successful export finds nothing left to do
    and appends nothing new (no duplicate receipts)."""
    vault = tmp_path / "vault"
    vault.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("VAULT_ROOT", str(vault))
    _allow_guard(monkeypatch)

    oid, _ = _insert_object(scratch_db)
    created = datetime(2026, 6, 1, 9, 30, 0, tzinfo=timezone.utc)
    _insert_legacy_decision_row(
        scratch_db, object_id=oid, key="classification", value={"type": "task"}, created_at=created
    )

    first = export_decisions_to_receipt_log(vault)
    assert first.exported == 1

    second = export_decisions_to_receipt_log(vault)
    assert second.exported == 0
    assert second.already_in_log == 1
    assert second.total_db_rows == 1

    from app.receipts.decision_receipt_log import iter_decision_receipts

    assert len(iter_decision_receipts(vault)) == 1  # no duplicate appended


@pytest.mark.pg
def test_export_then_rebuild_preserves_historical_rows(
    scratch_db: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The safety property this slice exists for: exporting BEFORE a projection
    rebuild means the rebuild's TRUNCATE-and-replay does not lose the historical
    row. Also demonstrates the footgun directly: skipping export and rebuilding
    from an empty log loses the row (issue #2973, 2026-07-05 comment)."""
    from app.jobs.decisions_projection import doctor_decisions_projection, rebuild_decisions_projection

    vault = tmp_path / "vault"
    vault.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("VAULT_ROOT", str(vault))
    _allow_guard(monkeypatch)

    oid, _ = _insert_object(scratch_db)
    created = datetime(2026, 5, 1, 8, 0, 0, tzinfo=timezone.utc)
    legacy_value = {"type": "task", "confidence": 0.9}
    _insert_legacy_decision_row(scratch_db, object_id=oid, key="classification", value=legacy_value, created_at=created)

    # Correct order: export first.
    export_summary = export_decisions_to_receipt_log(vault)
    assert export_summary.exported == 1

    report_before_rebuild = doctor_decisions_projection(vault)
    assert report_before_rebuild.ok, (report_before_rebuild.missing_in_db, report_before_rebuild.extra_in_db)

    rebuild_summary = rebuild_decisions_projection(vault)
    assert rebuild_summary.total_receipts == 1
    assert rebuild_summary.inserted == 1
    assert rebuild_summary.skipped_orphans == []

    with psycopg.connect(scratch_db, autocommit=True) as conn:
        row = conn.execute(
            "SELECT object_id, key, value FROM decisions WHERE key = 'classification'"
        ).fetchone()
    assert row is not None
    assert str(row[0]) == oid
    assert (row[2] if isinstance(row[2], dict) else json.loads(row[2])) == legacy_value

    report_after_rebuild = doctor_decisions_projection(vault)
    assert report_after_rebuild.ok
    assert report_after_rebuild.db_rows == 1


@pytest.mark.pg
def test_rebuild_without_export_loses_historical_row_the_footgun(
    scratch_db: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Negative control: rebuilding from an empty log BEFORE export runs
    TRUNCATEs the DB-only row away. This is the exact incident #2973 warns
    about; it is not fixed by rebuild itself -- callers must export first."""
    from app.jobs.decisions_projection import rebuild_decisions_projection

    vault = tmp_path / "vault"
    vault.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("VAULT_ROOT", str(vault))
    _allow_guard(monkeypatch)

    oid, _ = _insert_object(scratch_db)
    _insert_legacy_decision_row(
        scratch_db,
        object_id=oid,
        key="classification",
        value={"type": "task"},
        created_at=datetime(2026, 5, 1, 8, 0, 0, tzinfo=timezone.utc),
    )

    with psycopg.connect(scratch_db, autocommit=True) as conn:
        before = conn.execute("SELECT count(*) FROM decisions").fetchone()[0]
    assert before == 1

    # The footgun: rebuild without exporting first replays an empty log.
    rebuild_decisions_projection(vault)

    with psycopg.connect(scratch_db, autocommit=True) as conn:
        after = conn.execute("SELECT count(*) FROM decisions").fetchone()[0]
    assert after == 0  # the historical row is gone -- exactly the incident #2973 warns about


@pytest.mark.pg
def test_export_raises_when_object_deleted_sets_object_id_null(
    scratch_db: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A decisions row whose referenced object was deleted (FK ON DELETE SET
    NULL, #2788) has object_id=NULL -- a real, reachable unfaithful-export case,
    not just a defensive check. The export must fail loud, not skip it."""
    vault = tmp_path / "vault"
    vault.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("VAULT_ROOT", str(vault))
    _allow_guard(monkeypatch)

    oid, _ = _insert_object(scratch_db)
    _insert_legacy_decision_row(
        scratch_db,
        object_id=oid,
        key="classification",
        value={"type": "task"},
        created_at=datetime(2026, 5, 1, 8, 0, 0, tzinfo=timezone.utc),
    )
    with psycopg.connect(scratch_db, autocommit=True) as conn:
        conn.execute("DELETE FROM objects WHERE id = %s", (oid,))
        row = conn.execute("SELECT object_id FROM decisions").fetchone()
    assert row[0] is None  # FK SET NULL fired

    with pytest.raises(DecisionExportError, match="no object_id"):
        export_decisions_to_receipt_log(vault)


@pytest.mark.pg
def test_export_dual_write_row_already_in_log_is_skipped(
    scratch_db: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A row written via the current dual-write path (``insert_decision``) is
    already in the log; export must not duplicate it."""
    vault = tmp_path / "vault"
    vault.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("VAULT_ROOT", str(vault))
    _allow_guard(monkeypatch)

    from app.services.decisions import insert_decision

    oid, _ = _insert_object(scratch_db)
    insert_decision(oid, "review", {"allow": True, "score": 0.9, "agent": "reviewer"}, "t1")

    summary = export_decisions_to_receipt_log(vault)
    assert summary.total_db_rows == 1
    assert summary.exported == 0
    assert summary.already_in_log == 1
