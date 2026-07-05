"""#2788: decisions FK CASCADE->SET NULL + fail-loud decisions writer.

Found by RESEARCH-01 (#2779, divergences D-5/D-7):
- D-5: `decisions.object_id` was `ON DELETE CASCADE` while the sibling
  canonical log `audit.object_id` is `ON DELETE SET NULL`. If object cleanup
  ever lands (owner decision D-2 on #2778), decisions judgment history would
  silently vanish. Migration 1a739d9494af realigns decisions to the audit
  posture.
- D-7: the decisions writer (`app/services/decisions.py`) fell back to
  in-process memory silently on DB failure. It must now raise when Postgres
  is configured but unreachable, mirroring the KERNEL-03 store-backend
  contract (duplicated locally as `app/services/decisions.py::_resolved_backend`
  to avoid a new deprecated-package import), and only use the
  memory fallback under an explicit `STORE_BACKEND=memory` opt-in.

Spec: docs/architecture/runtime-semantics.md :: Divergences (D-5, D-7)
"""

from __future__ import annotations

import uuid
from pathlib import Path

import psycopg
import pytest

pytestmark = pytest.mark.pg

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def scratch_db(monkeypatch: pytest.MonkeyPatch):
    """A throwaway database at `alembic upgrade head`, wired into DATABASE_URL."""
    from app.db.dsn import resolve_dsn

    admin_dsn = resolve_dsn()
    if not admin_dsn:
        pytest.skip("DATABASE_URL/DB_DSN not configured")
    try:
        probe = psycopg.connect(admin_dsn, connect_timeout=2)
    except Exception as exc:  # pragma: no cover - environment guard
        pytest.skip(f"Postgres unavailable: {exc}")
    probe.close()

    name = f"scratch_decisions_fk_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
        # Some local/CI Postgres installs run with a non-English
        # lc_messages (e.g. sv_SE); app/db/db.py::ensure_schema() matches
        # driver error text in English to classify already-applied-schema
        # cases as benign. Pin this scratch DB's messages locale so that
        # matching is exercised deterministically regardless of server
        # locale, without touching the shared role/server configuration.
        conn.execute(f'ALTER DATABASE "{name}" SET lc_messages = \'C\'')
    base, _, _ = admin_dsn.rpartition("/")
    dsn = f"{base}/{name}"

    from alembic import command
    from alembic.config import Config

    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.delenv("DB_DSN", raising=False)
    # The 202510241200 migration declares `embedding VECTOR`, so pgvector
    # must exist in the scratch database (standard harness = pgvector image).
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "app" / "alembic"))
    command.upgrade(cfg, "head")

    yield dsn

    try:
        with psycopg.connect(admin_dsn, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    except Exception:
        pass


def _bind_vault_for_receipt_log(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Bind a selected vault + allow the WriteGuard for the durable decision path.

    Since feat #2969, ``insert_decision`` appends a WriteGuard-gated receipt to the
    vault BEFORE the DB projection write (receipt-before-ack). These FK tests
    exercise the durable path, so they need a vault to receipt into and an allowed
    guard — the receipt is the commit point, not incidental.
    """
    import app.receipts.decision_receipt_log as receipt_log

    vault = tmp_path / "vault"
    vault.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("VAULT_ROOT", str(vault))
    monkeypatch.setattr(
        receipt_log.DEFAULT_WRITE_GUARD, "assert_writes_allowed", lambda action: None
    )


def _insert_object(dsn: str) -> str:
    object_id = str(uuid.uuid4())
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO objects (id, kind, payload) VALUES (%s, %s, %s::jsonb)",
            (object_id, "note", "{}"),
        )
    return object_id


def test_object_delete_preserves_decisions(
    scratch_db: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Deleting an object leaves its decision rows with object_id=NULL."""
    monkeypatch.setenv("STORE_BACKEND", "pg")
    _bind_vault_for_receipt_log(monkeypatch, tmp_path)
    from app.services.decisions import _resolved_backend

    _resolved_backend.cache_clear()

    object_id = _insert_object(scratch_db)

    from app.services.decisions import insert_decision

    insert_decision(object_id, "classification", {"type": "task"}, trace_id="trace-1")

    with psycopg.connect(scratch_db, autocommit=True) as conn:
        rows = conn.execute(
            "SELECT object_id FROM decisions WHERE key = 'classification'"
        ).fetchall()
        assert len(rows) == 1
        assert str(rows[0][0]) == object_id

        # The FK action itself: deleting the object must not cascade-delete
        # the decision row, it must null out object_id (mirrors `audit`).
        conn.execute("DELETE FROM objects WHERE id = %s", (object_id,))

        rows_after = conn.execute(
            "SELECT object_id FROM decisions WHERE key = 'classification'"
        ).fetchall()
        assert len(rows_after) == 1, "decision row was cascade-deleted; expected SET NULL"
        assert rows_after[0][0] is None


def test_fk_delete_rule_is_set_null(scratch_db: str) -> None:
    """Catalog-level assertion: decisions.object_id FK delete_rule is SET NULL."""
    with psycopg.connect(scratch_db, autocommit=True) as conn:
        row = conn.execute(
            """
            SELECT rc.delete_rule
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
             AND tc.table_schema = kcu.table_schema
            JOIN information_schema.referential_constraints rc
              ON rc.constraint_name = tc.constraint_name
             AND rc.constraint_schema = tc.table_schema
            WHERE tc.table_schema = 'public'
              AND tc.table_name = 'decisions'
              AND tc.constraint_type = 'FOREIGN KEY'
              AND kcu.column_name = 'object_id'
            """
        ).fetchone()
        assert row is not None, "no FK found on decisions.object_id"
        assert row[0] == "SET NULL"


def test_writer_fail_loud(
    scratch_db: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Postgres configured but unreachable => the production put path raises.

    Asserted through app.services.decisions.insert_decision (the production
    writer named in the issue's Source Anchors), not a stubbed dependency.
    """
    from app.services.decisions import _resolved_backend

    _bind_vault_for_receipt_log(monkeypatch, tmp_path)

    # First prove the happy path works against the real scratch DB so the
    # subsequent failure is attributable to unreachability, not a broken
    # writer.
    monkeypatch.setenv("DATABASE_URL", scratch_db)
    monkeypatch.delenv("STORE_BACKEND", raising=False)
    _resolved_backend.cache_clear()

    from app.services.decisions import insert_decision

    object_id = _insert_object(scratch_db)
    insert_decision(object_id, "review", {"ok": True}, trace_id="trace-2")

    # Now point at an unreachable Postgres (nothing listens on port 1) with
    # no explicit memory opt-in: the writer must raise, not silently fall
    # back to the in-process memory store.
    monkeypatch.setenv("DATABASE_URL", "postgresql://app:app@127.0.0.1:1/app")
    monkeypatch.delenv("DB_DSN", raising=False)
    monkeypatch.delenv("STORE_BACKEND", raising=False)
    _resolved_backend.cache_clear()

    with pytest.raises(RuntimeError, match="unreachable"):
        insert_decision(object_id, "review", {"ok": False}, trace_id="trace-3")

    with pytest.raises(RuntimeError, match="unreachable"):
        from app.services.decisions import latest_decision

        latest_decision(object_id, "review")


def test_writer_memory_fallback_requires_explicit_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    """No DSN configured at all => raises unless STORE_BACKEND=memory is explicit."""
    from app.services.decisions import _resolved_backend

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DB_DSN", raising=False)
    monkeypatch.delenv("STORE_BACKEND", raising=False)
    _resolved_backend.cache_clear()

    from app.services.decisions import insert_decision, latest_decision

    with pytest.raises(RuntimeError, match="STORE_BACKEND=memory"):
        insert_decision("obj-1", "k", {"v": 1}, trace_id="t")

    monkeypatch.setenv("STORE_BACKEND", "memory")
    _resolved_backend.cache_clear()

    # Explicit opt-in: works purely in-process, no DB required.
    insert_decision("obj-1", "k", {"v": 1}, trace_id="t")
    rec = latest_decision("obj-1", "k")
    assert rec is not None
    assert rec["value"] == {"v": 1}
