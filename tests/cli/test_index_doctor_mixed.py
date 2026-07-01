"""EMBEDREL-06 AC — `index doctor` CLI surfaces mixed identities.

In non-JSON mode the doctor CLI prints the mixed-identity tuples; in JSON mode
the response includes ``mixed_identities``.

Requires a live Postgres backend; skipped when unavailable.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from uuid import uuid4

import psycopg
import pytest
from click.testing import CliRunner

from app.cli import cli
from app.components.embeddings import EmbeddingIdentity
from app.db.dsn import resolve_dsn
from app.index import doctor as doctor_mod
from app.stores import pg as pg_store
from app.stores import reset_store_backends

pytestmark = pytest.mark.pg


PRIMARY = EmbeddingIdentity(provider="ollama", model="nomic-embed-text", dim=4, normalize=True)
GEMINI = EmbeddingIdentity(provider="gemini", model="gemini-embedding-001", dim=4, normalize=True)


def _dsn() -> str:
    return resolve_dsn() or os.getenv("DATABASE_URL", "postgresql://app:app@127.0.0.1:15432/app")


def _pg_available() -> bool:
    try:
        conn = psycopg.connect(_dsn(), connect_timeout=1)
        conn.close()
        return True
    except Exception:
        return False


@pytest.fixture()
def pg_env(monkeypatch):
    if not _pg_available():
        pytest.skip("Postgres backend not available")
    monkeypatch.setenv("DATABASE_URL", _dsn())
    monkeypatch.setenv("STORE_BACKEND", "pg")
    reset_store_backends()
    pg_store._TABLES_READY = False
    pg_store._ensure_tables()
    pg_store.truncate_pg_tables()
    doctor_mod.reset_diagnose_cache()
    with psycopg.connect(_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO vector_index_meta (id, identity_json, updated_at)
                VALUES (1, %s, now())
                ON CONFLICT (id) DO UPDATE SET identity_json = EXCLUDED.identity_json
                """,
                (json.dumps(asdict(PRIMARY)),),
            )
        conn.commit()
    yield
    pg_store.truncate_pg_tables()
    reset_store_backends()
    doctor_mod.reset_diagnose_cache()


def _seed_row(identity: EmbeddingIdentity, *, embedding: list[float]) -> None:
    with psycopg.connect(_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO store_vector_index (
                    object_id, kind, source_ref, payload, embedding,
                    dim, model, provider, normalize, updated_at
                )
                VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, now())
                """,
                (
                    uuid4(), "note", "tests/doctor-mixed", json.dumps({"text": "seed"}),
                    embedding, identity.dim, identity.model, identity.provider, identity.normalize,
                ),
            )
        conn.commit()


def test_doctor_cli_prints_mixed_identities(pg_env):
    _seed_row(PRIMARY, embedding=[1.0, 0.0, 0.0, 0.0])
    _seed_row(GEMINI, embedding=[0.0, 1.0, 0.0, 0.0])

    runner = CliRunner()

    # Non-JSON: prints the mixed-identity list and the reconcile recommendation.
    doctor_mod.reset_diagnose_cache()
    text_result = runner.invoke(cli, ["index", "doctor", "--no-warn"])
    assert text_result.exit_code == 2  # issues present → non-zero under --no-warn
    assert "Mixed embedding identities" in text_result.output
    assert "index reconcile" in text_result.output
    assert "gemini-embedding-001" in text_result.output

    # JSON: response carries mixed_identities.
    doctor_mod.reset_diagnose_cache()
    json_result = runner.invoke(cli, ["index", "doctor", "--json"])
    payload = json.loads(json_result.output)
    assert payload["mixed_identities"]
    assert len(payload["mixed_identities"]) == 2
