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
def test_ingest_vault_root_persists_objects_before_classification(tmp_path: Path, monkeypatch) -> None:
    if not _pg_available():
        pytest.skip("Postgres backend not available")

    monkeypatch.setenv("DATABASE_URL", resolve_dsn(os.getenv("DATABASE_URL") or settings.db_dsn))
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("LLM_MOCK_RESPONSE", '{"type":"note","trust":"own","tags":[],"confidence":0.95}')
    monkeypatch.setenv("STORE_BACKEND", "pg")

    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    (vault_root / "sample.md").write_text("# Sample\nBody text", encoding="utf-8")

    dsn = resolve_dsn(os.getenv("DATABASE_URL") or settings.db_dsn)
    _bootstrap_pg_tables_if_missing(dsn)
    with psycopg.connect(dsn) as conn:
        with conn:
            with conn.cursor() as cur:
                cur.execute("DROP TABLE IF EXISTS decisions")
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
            cur.execute("SELECT id FROM objects WHERE id = %s", (object_id,))
            stored_object = cur.fetchone()
    assert stored_object is not None, "objects table should contain the ingested id"
