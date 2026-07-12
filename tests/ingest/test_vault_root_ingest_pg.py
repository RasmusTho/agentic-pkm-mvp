import os
from pathlib import Path

import psycopg
import pytest
from psycopg.rows import dict_row

from app.db.db import conn_rw
from app.db.dsn import resolve_dsn
from app.ingest.vault_root import ingest_vault_root
from app.settings import settings
from app.stores import pg as pg_store


def _pg_available() -> bool:
    dsn = os.getenv("DATABASE_URL") or settings.db_dsn
    if not dsn:
        return False
    url = resolve_dsn(dsn)
    try:
        conn = psycopg.connect(url, connect_timeout=1)
        conn.close()
        return True
    except Exception:
        return False


def _bootstrap_pg_tables_if_missing(dsn: str) -> None:
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    to_regclass('public.objects') IS NOT NULL,
                    to_regclass('public.store_objects') IS NOT NULL
                """
            )
            objects_ready, store_objects_ready = cur.fetchone()

    if not objects_ready:
        with conn_rw():
            pass
    if not store_objects_ready:
        pg_store._TABLES_READY = False
        pg_store._ensure_tables()


@pytest.mark.pg
def test_ingest_vault_root_persists_decisions_with_legacy_fk_parent(tmp_path: Path, monkeypatch) -> None:
    if not _pg_available():
        pytest.skip("Postgres backend not available")

    monkeypatch.setenv("DATABASE_URL", resolve_dsn(os.getenv("DATABASE_URL") or settings.db_dsn))
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("LLM_MOCK_RESPONSE", '{"type":"note","trust":"own","tags":[],"confidence":0.95}')
    monkeypatch.setenv("STORE_BACKEND", "pg")

    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    (vault_root / "sample.md").write_text("# Sample\nBody text", encoding="utf-8")
    monkeypatch.setenv("VAULT_ROOT", str(vault_root))

    dsn = resolve_dsn(os.getenv("DATABASE_URL") or settings.db_dsn)
    _bootstrap_pg_tables_if_missing(dsn)
    with psycopg.connect(dsn) as conn:
        with conn:
            with conn.cursor() as cur:
                cur.execute("TRUNCATE TABLE decisions RESTART IDENTITY CASCADE")
                cur.execute("TRUNCATE TABLE objects, store_objects RESTART IDENTITY CASCADE")

    ingested = ingest_vault_root(vault_root, limit=1)
    assert ingested == 1

    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT object_id FROM decisions")
            decision = cur.fetchone()
    assert decision is not None, "classifier should write a decision"
    object_id = decision["object_id"]

    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, payload FROM objects WHERE id = %s", (object_id,))
            parent = cur.fetchone()
            cur.execute("SELECT object_id FROM store_objects WHERE object_id = %s", (object_id,))
            stored_object = cur.fetchone()
    assert parent is not None, "decisions needs its retained legacy FK parent"
    assert parent["payload"] == {}, "legacy parent must not become a second object writer"
    assert stored_object is not None, "canonical store_objects should contain the ingested id"


@pytest.mark.pg
def test_ingest_vault_root_unmigrated_db_fails_with_migration_hint(tmp_path: Path, monkeypatch, caplog) -> None:
    """The real PgObjectStore preflight reports its migration hint through ingest."""
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    (vault_root / "sample.md").write_text("# Sample\nBody text", encoding="utf-8")

    dsn = resolve_dsn(os.getenv("DATABASE_URL") or settings.db_dsn)
    _bootstrap_pg_tables_if_missing(dsn)
    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.setenv("STORE_BACKEND", "pg")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.delenv("STORE_SCHEMA_AUTOCREATE", raising=False)

    pg_store._TABLES_READY = False
    try:
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute("DROP TABLE store_objects")

        assert ingest_vault_root(vault_root, limit=1) == 0
        assert "run 'alembic upgrade head'" in caplog.text
    finally:
        monkeypatch.setenv("STORE_SCHEMA_AUTOCREATE", "1")
        pg_store._TABLES_READY = False
        pg_store._ensure_tables()


@pytest.mark.pg
def test_ingest_vault_root_skips_classification_when_vault_root_unset(tmp_path: Path, monkeypatch) -> None:
    """Guard the inverse of the invariant above: the durable (pg) decision
    path must not classify without a selected vault.

    Exercised at the real production call site (``ingest_vault_root``, the
    same entrypoint the test above calls), not a helper tested in isolation.
    ``ingest_vault_root`` catches per-file failures rather than raising (see
    its ``except Exception`` loop), so the observable contract here is: the
    object is still persisted (ingest order is object-then-classify), the
    decision-receipt log's vault-selection guard is not silently swallowed
    into a fabricated decision, and the run reports the file as not
    successfully ingested rather than raising past the caller (#3400).
    """
    if not _pg_available():
        pytest.skip("Postgres backend not available")

    monkeypatch.setenv("DATABASE_URL", resolve_dsn(os.getenv("DATABASE_URL") or settings.db_dsn))
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("LLM_MOCK_RESPONSE", '{"type":"note","trust":"own","tags":[],"confidence":0.95}')
    monkeypatch.setenv("STORE_BACKEND", "pg")
    monkeypatch.delenv("VAULT_ROOT", raising=False)
    monkeypatch.delenv("VAULT_ROOT_DEV", raising=False)
    monkeypatch.delenv("VAULT_ROOT_TEST", raising=False)

    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    (vault_root / "sample.md").write_text("# Sample\nBody text", encoding="utf-8")

    dsn = resolve_dsn(os.getenv("DATABASE_URL") or settings.db_dsn)
    _bootstrap_pg_tables_if_missing(dsn)
    with psycopg.connect(dsn) as conn:
        with conn:
            with conn.cursor() as cur:
                cur.execute("TRUNCATE TABLE decisions RESTART IDENTITY CASCADE")
                cur.execute("TRUNCATE TABLE objects, store_objects RESTART IDENTITY CASCADE")

    ingested = ingest_vault_root(vault_root, limit=1)
    assert ingested == 0, "classification must not complete without a selected vault"

    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT object_id FROM decisions")
            decision = cur.fetchone()
    assert decision is None, "no decision may be recorded when no vault is selected"

    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM objects")
            legacy_parent = cur.fetchone()
            cur.execute("SELECT object_id FROM store_objects")
            stored_object = cur.fetchone()
    assert legacy_parent is not None, "the object upsert still runs before classification"
    assert stored_object is not None, "canonical store_objects should still contain the ingested id"
