"""Slice 3 (#2972) — read cutover: the system works when the DB projection is
rebuilt from the receipt log alone.

The decision-receipt log is now declared canonical and the ``decisions`` table a
derived projection (``docs/architecture/runtime-semantics.md`` row 12;
``docs/CONCEPTS/MACHINE_MIRROR_AND_DB_AUTHORITY_CONTRACT.md`` rule 4). Readers are
unchanged — they still hit the fast projection. This integration test proves the
end-to-end guarantee: with the projection dropped and rebuilt *from the log
alone*, the real readers (``latest_decision`` and the SQL projection view) return
the correct governance verdicts.

``pg``-marked (needs a real Postgres projection to rebuild into); skips cleanly
without a database.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import psycopg
import pytest

from app.jobs.decisions_projection import (
    doctor_decisions_projection,
    rebuild_decisions_projection,
)
from app.receipts.decision_receipt_log import append_decision_receipt

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def scratch_db(monkeypatch: pytest.MonkeyPatch):
    from app.db.dsn import resolve_dsn

    admin_dsn = resolve_dsn()
    if not admin_dsn:
        pytest.skip("DATABASE_URL/DB_DSN not configured")
    try:
        probe = psycopg.connect(admin_dsn, connect_timeout=2)
    except Exception as exc:  # pragma: no cover - environment guard
        pytest.skip(f"Postgres unavailable: {exc}")
    probe.close()

    name = f"scratch_declogonly_{uuid.uuid4().hex[:12]}"
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


def _insert_object(dsn: str) -> str:
    oid = str(uuid.uuid4())
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO objects (id, uuid, kind, payload) VALUES (%s, %s, %s, %s::jsonb)",
            (oid, oid, "note", "{}"),
        )
    return oid


@pytest.mark.pg
def test_readers_correct_after_rebuild_from_log_only(
    scratch_db: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("VAULT_ROOT", str(vault))
    import app.receipts.decision_receipt_log as receipt_log

    monkeypatch.setattr(
        receipt_log.DEFAULT_WRITE_GUARD, "assert_writes_allowed", lambda action: None
    )

    oid = _insert_object(scratch_db)

    # Seed the CANONICAL log directly (as if the DB projection had never been
    # written) — two review decisions (latest-wins) + one classification.
    t0 = datetime(2026, 4, 1, 10, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 4, 1, 11, 0, tzinfo=timezone.utc)
    append_decision_receipt(
        object_id=oid, key="review", value={"allow": False, "score": 0.4, "agent": "reviewer"},
        trace_id="r0", created_at=t0, vault_root=vault, vault_uuid=oid,
    )
    append_decision_receipt(
        object_id=oid, key="review", value={"allow": True, "score": 0.9, "agent": "reviewer"},
        trace_id="r1", created_at=t1, vault_root=vault, vault_uuid=oid,
    )
    append_decision_receipt(
        object_id=oid, key="classification", value={"type": "task", "agent": "classifier"},
        trace_id="c0", created_at=t0, vault_root=vault, vault_uuid=oid,
    )

    # The DB projection is empty at this point (nothing wrote it).
    with psycopg.connect(scratch_db, autocommit=True) as conn:
        assert conn.execute("SELECT count(*) FROM decisions").fetchone()[0] == 0

    # Rebuild the projection from the log alone.
    summary = rebuild_decisions_projection(vault)
    assert summary.inserted == 3
    assert doctor_decisions_projection(vault).ok

    # Reader 1: latest_decision() returns the latest-wins review verdict.
    from app.services.decisions import latest_decision

    latest_review = latest_decision(oid, "review")
    assert latest_review is not None
    assert latest_review["value"]["allow"] is True
    assert latest_review["value"]["score"] == 0.9
    assert latest_review["trace_id"] == "r1"

    # Reader 2: the SQL projection view surfaces the classification type.
    with psycopg.connect(scratch_db, autocommit=True) as conn:
        rows = conn.execute(
            "SELECT object_id, type FROM view_objects_ready_for_projection WHERE object_id = %s",
            (oid,),
        ).fetchall()
    assert rows, "projection view returned nothing after rebuild-from-log-only"
    assert rows[0][1] == "task"
