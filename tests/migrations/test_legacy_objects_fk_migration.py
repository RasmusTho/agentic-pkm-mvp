"""Fail-loud migration coverage for #3510."""

from __future__ import annotations

import uuid
from pathlib import Path

import psycopg
import pytest

pytestmark = pytest.mark.pg
REPO_ROOT = Path(__file__).resolve().parents[2]
PRE_CUTOVER_REVISION = "4d1e0c9a3329"


def _admin_dsn() -> str:
    from app.db.dsn import resolve_dsn

    dsn = resolve_dsn()
    if not dsn:
        pytest.skip("DATABASE_URL/DB_DSN not configured")
    return dsn


@pytest.fixture
def scratch_dsn(monkeypatch: pytest.MonkeyPatch):
    admin_dsn = _admin_dsn()
    try:
        probe = psycopg.connect(admin_dsn, connect_timeout=2)
    except Exception as exc:
        pytest.skip(f"Postgres unavailable: {exc}")
    probe.close()
    name = f"scratch_legacy_fk_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
    base, _, _ = admin_dsn.rpartition("/")
    dsn = f"{base}/{name}"
    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.delenv("DB_DSN", raising=False)
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    try:
        yield dsn
    finally:
        with psycopg.connect(admin_dsn, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def _upgrade(revision: str) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "app" / "alembic"))
    command.upgrade(cfg, revision)


def test_legacy_objects_fk_migration_fails_loudly_on_unsupported_state(scratch_dsn: str) -> None:
    _upgrade(PRE_CUTOVER_REVISION)
    with psycopg.connect(scratch_dsn) as conn:
        conn.execute(
            "CREATE TABLE unreviewed_consumer ("
            "id uuid PRIMARY KEY, object_id uuid REFERENCES objects(id))"
        )

    with pytest.raises(Exception, match="unaccounted objects FK"):
        _upgrade("head")

    with psycopg.connect(scratch_dsn) as conn:
        row = conn.execute(
            "SELECT confrelid = 'public.objects'::regclass "
            "FROM pg_constraint WHERE conrelid = 'public.unreviewed_consumer'::regclass "
            "AND contype = 'f'"
        ).fetchone()
    assert row == (True,), "failed migration must roll back without partially retargeting constraints"


def test_legacy_objects_fk_migration_backfills_existing_parents(scratch_dsn: str) -> None:
    _upgrade(PRE_CUTOVER_REVISION)
    object_id = uuid.uuid4()
    with psycopg.connect(scratch_dsn) as conn:
        conn.execute(
            "INSERT INTO objects (id, kind, payload) "
            "VALUES (%s, 'note', '{\"title\": \"Legacy\"}'::jsonb)",
            (object_id,),
        )
        conn.execute(
            "INSERT INTO decisions (object_id, key, value) VALUES (%s, 'review', '{}'::jsonb)",
            (object_id,),
        )

    _upgrade("head")

    with psycopg.connect(scratch_dsn) as conn:
        parent = conn.execute(
            "SELECT kind, source_ref, payload FROM store_objects WHERE object_id = %s",
            (object_id,),
        ).fetchone()
        fk_target = conn.execute(
            "SELECT confrelid::regclass::text FROM pg_constraint "
            "WHERE conrelid = 'public.decisions'::regclass AND contype = 'f'"
        ).fetchone()
    assert parent == ("note", None, {"title": "Legacy"})
    assert fk_target == ("store_objects",)


def test_active_decision_writer_preflights_before_receipt_on_pre_cutover_schema(
    scratch_dsn: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The production writer rejects pre-#3510 schema before its commit point."""
    _upgrade(PRE_CUTOVER_REVISION)
    object_id = uuid.uuid4()
    with psycopg.connect(scratch_dsn) as conn:
        conn.execute(
            "INSERT INTO store_objects (object_id, kind, payload) "
            "VALUES (%s, 'note', '{}'::jsonb)",
            (object_id,),
        )

    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setenv("VAULT_ROOT", str(vault))
    monkeypatch.setenv("STORE_BACKEND", "pg")

    import app.receipts.decision_receipt_log as receipt_log
    from app.services.decisions import (
        DecisionsSchemaMigrationRequired,
        _resolved_backend,
        insert_decision,
    )

    monkeypatch.setattr(
        receipt_log.DEFAULT_WRITE_GUARD,
        "assert_writes_allowed",
        lambda action: None,
    )
    _resolved_backend.cache_clear()

    with pytest.raises(
        DecisionsSchemaMigrationRequired,
        match=r"#3510.*alembic upgrade head",
    ):
        insert_decision(
            str(object_id),
            "classification",
            {"type": "note"},
            trace_id="pre-cutover",
        )

    assert receipt_log.iter_decision_receipts(vault) == []
    with psycopg.connect(scratch_dsn) as conn:
        assert conn.execute("SELECT count(*) FROM decisions").fetchone() == (0,)
