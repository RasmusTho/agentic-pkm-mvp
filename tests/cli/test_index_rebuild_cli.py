from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from uuid import uuid4

import psycopg
import pytest
from click.testing import CliRunner

from app.cli import cli
from app.components.embeddings import get_embedding_client, get_embedding_identity
from app.db.dsn import resolve_dsn
from app.store import object_store as legacy_store
from app.store.object_store import DomainObject, ObjectStore
from app.stores import get_vector_index, reset_store_backends


def _seed_object(text: str, *, source_ref: str = "tests") -> str:
    store = ObjectStore()
    obj_id = uuid4()
    store.save_object(
        DomainObject(
            uuid=str(obj_id),
            kind="note",
            payload={"text": text, "content": text},
            source_ref=source_ref,
            created_at=datetime.now(timezone.utc),
        ),
        emit_outbox=False,
        trace_id="trace-seed",
    )
    return str(obj_id)


def test_index_rebuild_dry_run(monkeypatch) -> None:
    reset_store_backends()
    legacy_store._MEMORY_STORE.clear()
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("EMBED_DIM", "8")

    _seed_object("alpha beta knowledge")

    runner = CliRunner()
    result = runner.invoke(cli, ["index", "rebuild", "--dry-run"])

    assert result.exit_code == 0
    assert "Dry run" in result.output

    idx = get_vector_index()
    embedder = get_embedding_client()
    identity = get_embedding_identity(client=embedder)
    query = embedder.embed_text("alpha beta knowledge")
    hits = idx.search(query, k=1, identity=identity)
    assert hits == []

    legacy_store._MEMORY_STORE.clear()


def test_index_rebuild_populates_index(monkeypatch) -> None:
    reset_store_backends()
    legacy_store._MEMORY_STORE.clear()
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("EMBED_DIM", "8")

    obj_uuid = _seed_object("agentic policy note")

    runner = CliRunner()
    result = runner.invoke(cli, ["index", "rebuild"])

    assert result.exit_code == 0
    assert "Rebuilt embeddings" in result.output

    idx = get_vector_index()
    embedder = get_embedding_client()
    identity = get_embedding_identity(client=embedder)
    query = embedder.embed_text("agentic policy")
    hits = idx.search(query, k=1, identity=identity)
    assert hits
    assert str(hits[0].object_id) == obj_uuid

    legacy_store._MEMORY_STORE.clear()


@pytest.mark.pg
def test_index_rebuild_sets_pg_meta(monkeypatch) -> None:
    try:
        from tests.stores.test_store_contract_pg import _pg_available  # reuse helper
    except Exception:  # pragma: no cover - fallback when module moves
        pytest.skip("Postgres helper unavailable")

    if not _pg_available():
        pytest.skip("Postgres backend not available")

    reset_store_backends()
    legacy_store._MEMORY_STORE.clear()
    monkeypatch.setenv("STORE_BACKEND", "pg")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("EMBED_DIM", "8")

    _seed_object("pg domain object", source_ref="pg-test")

    runner = CliRunner()
    result = runner.invoke(cli, ["index", "rebuild"])
    assert result.exit_code == 0

    dsn = resolve_dsn() or os.getenv("DATABASE_URL", "postgresql://app:app@127.0.0.1:15432/app")
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT identity_json FROM vector_index_meta WHERE id = 1")
            row = cur.fetchone()
            assert row is not None
            data = json.loads(row[0])
            assert data.get("provider")
            assert data.get("model")
            assert int(data.get("dim", 0)) > 0

    reset_store_backends()
    legacy_store._MEMORY_STORE.clear()
