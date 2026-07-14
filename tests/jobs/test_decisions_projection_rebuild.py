"""Slice 2 (#2971) — projection rebuild + doctor equivalence.

``rebuild_decisions_projection()`` replays the canonical JSONL receipt log into
the ``decisions`` table; ``doctor_decisions_projection()`` asserts DB == log
row-for-row. Identity re-links via ``vault_uuid`` when the runtime ``object_id``
was re-minted (the §5 decoupling payoff).

The named acceptance test ``test_rebuild_equals_log`` is a real-DB round-trip
(``pg``-marked; skips cleanly without Postgres). Additional ``not pg`` tests pin
the pure re-link resolution logic so the guarantee is also exercised in the
default CI gate.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.jobs.decisions_projection import (
    _resolve_target_object_id,
    doctor_decisions_projection,
    rebuild_decisions_projection,
)
from app.receipts.decision_receipt_log import append_decision_receipt

REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# not-pg: pure re-link resolution logic
# ---------------------------------------------------------------------------


def test_relink_prefers_existing_object_id() -> None:
    receipt = {"object_id": "id-1", "vault_uuid": "vuid-1", "key": "review"}
    assert (
        _resolve_target_object_id(receipt, {"id-1", "id-2"}, {"vuid-1": "id-9"}) == "id-1"
    )


def test_relink_falls_back_to_vault_uuid_when_object_reminted() -> None:
    # The receipt's original object_id no longer exists (DB rebuilt, id re-minted),
    # but vault_uuid resolves to the current object row.
    receipt = {"object_id": "old-id", "vault_uuid": "vuid-1", "key": "review"}
    assert _resolve_target_object_id(receipt, {"new-id"}, {"vuid-1": "new-id"}) == "new-id"


def test_relink_returns_none_for_genuine_orphan() -> None:
    receipt = {"object_id": "gone", "vault_uuid": None, "key": "review"}
    assert _resolve_target_object_id(receipt, {"other"}, {}) is None
    receipt2 = {"object_id": "gone", "vault_uuid": "unknown", "key": "review"}
    assert _resolve_target_object_id(receipt2, {"other"}, {"known": "x"}) is None


# ---------------------------------------------------------------------------
# pg: real rebuild round-trip + doctor equivalence
# ---------------------------------------------------------------------------

import psycopg  # noqa: E402


@pytest.fixture
def scratch_db(monkeypatch: pytest.MonkeyPatch):
    """A throwaway database at ``alembic upgrade head``, wired into DATABASE_URL."""
    from app.db.dsn import resolve_dsn

    admin_dsn = resolve_dsn()
    if not admin_dsn:
        pytest.skip("DATABASE_URL/DB_DSN not configured")
    try:
        probe = psycopg.connect(admin_dsn, connect_timeout=2)
    except Exception as exc:  # pragma: no cover - environment guard
        pytest.skip(f"Postgres unavailable: {exc}")
    probe.close()

    name = f"scratch_decrebuild_{uuid.uuid4().hex[:12]}"
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
            "INSERT INTO store_objects (object_id, kind, source_ref, payload) "
            "VALUES (%s, 'note', 'test://decision-projection', '{}'::jsonb)",
            (oid,),
        )
        conn.execute(
            "INSERT INTO objects (id, uuid, kind, payload) VALUES (%s, %s, %s, %s::jsonb)",
            (oid, ouuid, "note", "{}"),
        )
    return oid, ouuid


def _allow_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.receipts.decision_receipt_log as receipt_log

    monkeypatch.setattr(
        receipt_log.DEFAULT_WRITE_GUARD, "assert_writes_allowed", lambda action: None
    )


@pytest.mark.pg
def test_rebuild_equals_log(
    scratch_db: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Replaying the JSONL log rebuilds the ``decisions`` projection identically,
    and the doctor confirms DB == log row-for-row."""
    vault = tmp_path / "vault"
    vault.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("VAULT_ROOT", str(vault))
    _allow_guard(monkeypatch)

    from app.services.decisions import insert_decision

    oid1, _ = _insert_object(scratch_db)
    oid2, _ = _insert_object(scratch_db)

    # Real writes: each appends a receipt (canonical) then the DB row (projection).
    insert_decision(oid1, "review", {"allow": True, "score": 0.9, "agent": "reviewer"}, "t1")
    insert_decision(oid1, "evaluate", {"promote": True, "score": 0.9, "agent": "set_evaluator"}, "t2")
    insert_decision(oid2, "classification", {"type": "task", "agent": "classifier"}, "t3")

    # Baseline: DB already equals the log after the dual-writes.
    assert doctor_decisions_projection(vault).ok

    # Simulate DB loss of the projection, then rebuild from the log alone.
    with psycopg.connect(scratch_db, autocommit=True) as conn:
        conn.execute("TRUNCATE TABLE decisions")
        assert conn.execute("SELECT count(*) FROM decisions").fetchone()[0] == 0

    summary = rebuild_decisions_projection(vault)
    assert summary.total_receipts == 3
    assert summary.inserted == 3
    assert summary.relinked == 0
    assert summary.skipped_orphans == []

    report = doctor_decisions_projection(vault)
    assert report.ok, (report.missing_in_db, report.extra_in_db)
    assert report.db_rows == 3
    assert report.log_rows == 3

    # The rebuilt rows are the real judgment values (latest-wins still works).
    from app.services.decisions import latest_decision

    rev = latest_decision(oid1, "review")
    assert rev is not None and rev["value"]["allow"] is True
    assert rev["trace_id"] == "t1"


@pytest.mark.pg
def test_rebuild_relinks_via_vault_uuid_after_object_remint(
    scratch_db: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A receipt whose runtime object_id was re-minted re-links via vault_uuid to
    the current object row (§5 decoupling payoff)."""
    vault = tmp_path / "vault"
    vault.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("VAULT_ROOT", str(vault))
    _allow_guard(monkeypatch)

    stable_uuid = str(uuid.uuid4())
    old_id = str(uuid.uuid4())
    new_id = str(uuid.uuid4())
    created = datetime(2026, 3, 1, tzinfo=timezone.utc)

    # A receipt written under the OLD runtime id, carrying the stable vault_uuid.
    append_decision_receipt(
        object_id=old_id,
        key="review",
        value={"allow": True, "agent": "reviewer"},
        trace_id="t-relink",
        created_at=created,
        vault_root=vault,
        vault_uuid=stable_uuid,
    )

    # The DB now only has the object under a NEW id (rebuilt), same vault uuid.
    _insert_object(scratch_db, object_id=new_id, obj_uuid=stable_uuid)

    summary = rebuild_decisions_projection(vault)
    assert summary.inserted == 1
    assert summary.relinked == 1
    assert summary.skipped_orphans == []

    with psycopg.connect(scratch_db, autocommit=True) as conn:
        row = conn.execute(
            "SELECT object_id FROM decisions WHERE key = 'review'"
        ).fetchone()
    assert str(row[0]) == new_id  # re-linked to the current object row


@pytest.mark.pg
def test_rebuild_skips_genuine_orphan(
    scratch_db: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A receipt whose object no longer exists and whose vault_uuid does not
    resolve is skipped (cannot satisfy the FK) and reported, not silently
    dropped."""
    vault = tmp_path / "vault"
    vault.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("VAULT_ROOT", str(vault))
    _allow_guard(monkeypatch)

    append_decision_receipt(
        object_id=str(uuid.uuid4()),
        key="review",
        value={"allow": True},
        trace_id="t-orphan",
        created_at=datetime(2026, 3, 2, tzinfo=timezone.utc),
        vault_root=vault,
        vault_uuid=str(uuid.uuid4()),  # unknown uuid
    )

    summary = rebuild_decisions_projection(vault)
    assert summary.inserted == 0
    assert len(summary.skipped_orphans) == 1
    assert summary.skipped_orphans[0]["reason"] == "unresolved_object"

    report = doctor_decisions_projection(vault)
    assert report.ok  # both DB and (resolvable) log are empty
