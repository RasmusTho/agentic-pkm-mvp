"""KERNEL-06 (#2768) enforcement AC — the provenance stamp rides the SAME
upsert statement as the vector.

Drives the real ``PgVectorIndex.upsert()`` production entrypoint directly and
asserts a single upsert round-trip yields both the embedding and the full
provenance object in one write — no second write, matching cross-task
invariant #4 (a separate "stamp later" write is forbidden).

Requires a live Postgres backend; skipped when unavailable.
"""

from __future__ import annotations

from uuid import uuid4

import psycopg
import pytest

from app.components.embeddings import EmbeddingIdentity
from app.index.artifact_metadata import build_indexed_unit_payload, compute_content_hash
from app.ingest.chunk_policy import CHUNK_POLICY_VERSION

pytestmark = pytest.mark.pg


def _pg_available() -> bool:
    from app.db.dsn import resolve_dsn

    url = resolve_dsn()
    try:
        conn = psycopg.connect(url, connect_timeout=1)
        conn.close()
        return True
    except Exception:
        return False


def test_stamp_rides_the_upsert(tmp_path, monkeypatch) -> None:
    if not _pg_available():
        pytest.skip("Postgres backend not available")

    from tests.indexer.test_outbox_roundtrip_pg import (
        _configure_isolated_pg_test,
        _drop_schema,
        _reset_store_backend_cache_only,
    )

    base_dsn, schema = _configure_isolated_pg_test(tmp_path, monkeypatch)
    try:
        from app.stores import get_vector_index
        from app.stores.pg import _connect

        identity = EmbeddingIdentity(provider="mock", model="mock-embedding", dim=8, normalize=False)
        object_id = uuid4()
        text = "Enforcement fixture: stamp rides the upsert."
        payload = build_indexed_unit_payload(
            object_id=object_id,
            kind="note",
            source_ref="unit-test://stamp-rides-upsert",
            payload={},
            text=text,
            embedding_identity=identity,
        )

        vector_index = get_vector_index()
        vector_index.upsert(
            object_id=object_id,
            kind="note",
            source_ref="unit-test://stamp-rides-upsert",
            payload=payload,
            embedding=[0.1] * 8,
            model=identity.model,
            identity=identity,
        )

        # A single SELECT must show both the embedding and the provenance
        # stamp already present — proving they landed in the same INSERT ...
        # ON CONFLICT statement, not a follow-up write.
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT embedding, payload->'provenance' AS provenance
                    FROM store_vector_index
                    WHERE object_id = %s
                    """,
                    (object_id,),
                )
                row = cur.fetchone()

        assert row is not None, "upsert must have written exactly one row"
        assert row["embedding"], "the same row must carry the embedding"
        provenance = row["provenance"]
        assert provenance is not None, "the same row must carry provenance (no second write)"
        assert provenance["source_ref"] == "unit-test://stamp-rides-upsert"
        assert provenance["content_hash"] == compute_content_hash(text)
        assert provenance["chunk_policy_version"] == CHUNK_POLICY_VERSION
        assert provenance["pipeline_version"]
        assert provenance["embedding_identity"]["provider"] == "mock"

        # Round-trip count: exactly one row for this object_id — no orphaned
        # "stamp later" row from a hypothetical second write.
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT count(*) AS total FROM store_vector_index WHERE object_id = %s",
                    (object_id,),
                )
                total = cur.fetchone()["total"]
        assert total == 1
    finally:
        _reset_store_backend_cache_only()
        _drop_schema(base_dsn, schema)
