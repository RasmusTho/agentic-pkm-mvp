"""EMBEDREL-06 AC 2 — mixed-identity detection in index doctor.

``diagnose_index`` must flag an index containing more than one distinct
``(provider, model, dim, normalize)`` tuple as MIXED — keying on the full tuple,
not provider alone, so a same-provider model swap at the same dim is caught too.

Requires a live Postgres backend; skipped when unavailable.
"""

from __future__ import annotations

import json
import os
from uuid import uuid4

import psycopg
import pytest

from app.components.embeddings import EmbeddingIdentity
from app.db.dsn import resolve_dsn
from app.index import doctor as doctor_mod
from app.stores import pg as pg_store
from app.stores import reset_store_backends

pytestmark = pytest.mark.pg


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
                    uuid4(),
                    "note",
                    "tests/mixed-identity",
                    json.dumps({"text": "seed"}),
                    embedding,
                    identity.dim,
                    identity.model,
                    identity.provider,
                    identity.normalize,
                ),
            )
        conn.commit()


def _set_primary_identity(identity: EmbeddingIdentity) -> None:
    from dataclasses import asdict

    with psycopg.connect(_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO vector_index_meta (id, identity_json, updated_at)
                VALUES (1, %s, now())
                ON CONFLICT (id) DO UPDATE SET identity_json = EXCLUDED.identity_json, updated_at = now()
                """,
                (json.dumps(asdict(identity)),),
            )
        conn.commit()


OLLAMA_NOMIC = EmbeddingIdentity(provider="ollama", model="nomic-embed-text", dim=4, normalize=True)
OLLAMA_MXBAI = EmbeddingIdentity(provider="ollama", model="mxbai-embed-large", dim=4, normalize=True)
GEMINI = EmbeddingIdentity(provider="gemini", model="gemini-embedding-001", dim=4, normalize=True)


def test_doctor_flags_mixed_identity(pg_env):
    """Different-provider mix (ollama + gemini) at the same dim is flagged MIXED."""
    _set_primary_identity(OLLAMA_NOMIC)
    _seed_row(OLLAMA_NOMIC, embedding=[1.0, 0.0, 0.0, 0.0])
    _seed_row(GEMINI, embedding=[0.0, 1.0, 0.0, 0.0])

    result = doctor_mod.diagnose_index()

    assert result["status"] == "error"
    assert result["mixed_identities"]
    assert len(result["mixed_identities"]) == 2
    assert any("Mixed embedding identities" in issue for issue in result["issues"])
    assert any("index reconcile" in issue for issue in result["issues"])


def test_diagnose_detects_mixed_full_identities(pg_env):
    """Full-tuple keying: a same-provider model swap at the same dim is also MIXED.

    Provider-only matching would miss ollama/nomic vs ollama/mxbai; the full
    (provider, model, dim, normalize) tuple must be used.
    """
    _set_primary_identity(OLLAMA_NOMIC)
    _seed_row(OLLAMA_NOMIC, embedding=[1.0, 0.0, 0.0, 0.0])
    _seed_row(OLLAMA_MXBAI, embedding=[0.0, 1.0, 0.0, 0.0])

    result = doctor_mod.diagnose_index()

    assert result["status"] == "error"
    identities = {tuple(t) for t in result["mixed_identities"]}
    assert (OLLAMA_NOMIC.provider, OLLAMA_NOMIC.model, OLLAMA_NOMIC.dim, OLLAMA_NOMIC.normalize) in identities
    assert (OLLAMA_MXBAI.provider, OLLAMA_MXBAI.model, OLLAMA_MXBAI.dim, OLLAMA_MXBAI.normalize) in identities

    # And the different-provider case is flagged too (regression guard for both).
    pg_store.truncate_pg_tables()
    doctor_mod.reset_diagnose_cache()
    _set_primary_identity(OLLAMA_NOMIC)
    _seed_row(OLLAMA_NOMIC, embedding=[1.0, 0.0, 0.0, 0.0])
    _seed_row(GEMINI, embedding=[0.0, 1.0, 0.0, 0.0])
    result2 = doctor_mod.diagnose_index()
    assert result2["status"] == "error"
    assert len(result2["mixed_identities"]) == 2


def test_doctor_single_identity_is_ok(pg_env):
    """A single-identity index is not flagged mixed."""
    _set_primary_identity(OLLAMA_NOMIC)
    _seed_row(OLLAMA_NOMIC, embedding=[1.0, 0.0, 0.0, 0.0])
    _seed_row(OLLAMA_NOMIC, embedding=[0.0, 1.0, 0.0, 0.0])

    result = doctor_mod.diagnose_index()
    assert result["mixed_identities"] == []
    assert not any("Mixed embedding identities" in issue for issue in result["issues"])
