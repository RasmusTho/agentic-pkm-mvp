import os
from pathlib import Path

import psycopg
import pytest
from psycopg.rows import dict_row

from app.db.db import conn_rw
from app.db.dsn import resolve_dsn
from app.ingest.vault_root import ingest_vault_root
from app.receipts.decision_receipt_log import decisions_receipts_dir
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

    # The decision-receipt log (app/receipts/decision_receipt_log.py) requires a
    # selected vault on the durable (pg) path — it writes the canonical decision
    # receipt under <vault>/<system_dir>/receipts/decisions before the Postgres
    # projection insert. This fixture is hermetic, so it must select its own
    # temporary vault explicitly rather than depend on ambient/developer-machine
    # VAULT_ROOT state (#3400).
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
            cur.execute("SELECT id FROM objects WHERE id = %s", (object_id,))
            stored_object = cur.fetchone()
    assert stored_object is not None, "objects table should contain the ingested id"

    receipts_dir = decisions_receipts_dir(vault_root)
    assert receipts_dir.exists(), "decision receipt log should be written under the selected vault"
    assert list(receipts_dir.glob("decisions-*.jsonl")), "a decision receipt shard should be present"


@pytest.mark.pg
def test_ingest_vault_root_skips_classification_when_vault_root_unset(
    tmp_path: Path, monkeypatch
) -> None:
    """Guard the production invariant this fixture's fix depends on: the
    durable (pg) decision path must not classify without a selected vault.

    Exercised at the real production call site (``ingest_vault_root``, the
    same entrypoint the fixed test above calls), not a helper tested in
    isolation. ``ingest_vault_root`` contains per-file failures rather than
    raising (see its ``except Exception`` loop), so the observable contract
    here is: the object is still persisted (ingest order is object-then-
    classify, per this file's other test), classification does not complete
    (``NoVaultSelectedError`` from the decision-receipt log is not silently
    swallowed into a fabricated decision), and the run reports the file as
    not successfully ingested rather than raising past the caller.
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
            stored_object = cur.fetchone()
    assert stored_object is not None, "the object upsert still runs before classification"
