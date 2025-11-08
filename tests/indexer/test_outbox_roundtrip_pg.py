from __future__ import annotations

import importlib
import os
from uuid import uuid4

import psycopg
import pytest

from app.db.dsn import resolve_dsn
from app.outbox import events
from app.stores import get_vector_index, reset_store_backends


def _vec(axis: int, dim: int = 8) -> list[float]:
    vec = [0.0] * dim
    vec[axis % dim] = 1.0
    return vec


def _pg_available() -> bool:
    url = resolve_dsn() or os.getenv("DATABASE_URL", "postgresql://app:app@127.0.0.1:15432/app")
    try:
        conn = psycopg.connect(url, connect_timeout=1)
        conn.close()
        return True
    except Exception:
        return False


@pytest.mark.pg
def test_indexer_runner_consumes_outbox_pg(tmp_path, monkeypatch) -> None:
    if not _pg_available():
        pytest.skip("Postgres backend not available")

    reset_store_backends()
    monkeypatch.setenv("STORE_BACKEND", "pg")
    fake_path = tmp_path / "index-outbox.jsonl"
    monkeypatch.setattr(events, "INDEX_OUTBOX_PATH", fake_path, raising=False)

    import app.indexer.runner as runner

    importlib.reload(runner)

    for i in range(2):
        events.emit_index_object_embedded(
            {
                "object_id": uuid4(),
                "kind": "note",
                "source_ref": f"unit-test:{i}",
                "payload": {
                    "text": f"payload-{i}",
                    "content": f"payload-{i}",
                    "object_type": "note",
                    "system_intent": "learn",
                    "emergent_tags": [],
                },
                "embedding": _vec(i),
                "model": "openai/text-embedding-3-large",
            }
        )

    runner.main()

    idx = get_vector_index()
    hits = idx.search(_vec(0), k=2)

    assert hits
    assert hits[0].payload["text"] == "payload-0"

    reset_store_backends()
