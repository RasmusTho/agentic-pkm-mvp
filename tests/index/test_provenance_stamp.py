"""KERNEL-06: transform provenance stamp — content_hash + chunk_policy_version
+ pipeline_version rides the same upsert as the vector.

Covers docs/RUNTIME_CORRECTNESS_KERNEL/TRANSFORM_PROVENANCE_STAMP.md and audit
invariant I-D1 (CW-6). Cross-task invariant #4: the stamp is written inside
the same upsert payload as the embedding — never a separate "stamp later"
write. Cross-task invariant #5: doctor detects, reconcile repairs, nothing
auto-mutates.

- test_upsert_writes_provenance: the production ingest_object() entrypoint
  stamps provenance into the same payload dict passed to VectorIndex.upsert().
- test_doctor_lists_stale_candidates / test_reconcile_incremental_on_stale_only:
  content-hash staleness detection and incremental repair are Postgres-backed
  capabilities (matching the existing `index reconcile` Postgres-only posture)
  — pg-marked, real DB required.
"""

from __future__ import annotations

import os

import pytest

from app.agents.panel.filters import strip_ai_panels
from app.components.embeddings import EmbeddingIdentity
from app.index.artifact_metadata import compute_content_hash
from app.ingest.chunk_policy import CHUNK_POLICY_VERSION
from app.settings.models import SettingsBundle

pytestmark = pytest.mark.not_pg


def _pg_available() -> bool:
    import psycopg

    from app.db.dsn import resolve_dsn

    url = resolve_dsn() or os.getenv("DATABASE_URL", "postgresql://app:app@127.0.0.1:15432/app")
    try:
        conn = psycopg.connect(url, connect_timeout=1)
        conn.close()
        return True
    except Exception:
        return False


@pytest.fixture(autouse=True)
def _isolate_llm_routing_settings(monkeypatch) -> None:
    monkeypatch.setattr("app.components.llm.router.get_settings_bundle", lambda: SettingsBundle())


class CapturingVectorIndex:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def upsert(self, **kwargs) -> None:
        self.calls.append(kwargs)


def test_upsert_writes_provenance(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every ingest_object() write persists provenance superset fields."""
    from app.search import service as search_service

    identity = EmbeddingIdentity(provider="mock", model="mock-embedding", dim=3, normalize=True)
    index = CapturingVectorIndex()
    monkeypatch.setattr(search_service, "embed_query", lambda text: ([0.1, 0.2, 0.3], identity))
    monkeypatch.setattr(search_service, "get_vector_index", lambda: index)

    text = "Provenance stamp fixture text."
    object_id, _dim = search_service.ingest_object(
        kind="note",
        source_ref="unit-test://provenance",
        payload={"title": "Provenance fixture"},
        text=text,
    )

    assert index.calls, "ingest_object must upsert into the vector index"
    captured = index.calls[-1]
    provenance = captured["payload"]["provenance"]

    assert provenance["source_ref"] == "unit-test://provenance"
    assert provenance["content_hash"] == compute_content_hash(text)
    assert provenance["chunk_policy_version"] == CHUNK_POLICY_VERSION
    assert provenance["pipeline_version"]
    assert provenance["embedding_identity"] == {
        "provider": identity.provider,
        "model": identity.model,
        "dim": identity.dim,
        "normalize": identity.normalize,
    }


def test_content_hash_is_stable_for_same_text() -> None:
    """content_hash is deterministic — a re-run over unchanged text is a no-op signal."""
    text = "Stable hash fixture."
    assert compute_content_hash(text) == compute_content_hash(text)
    assert compute_content_hash(text) != compute_content_hash(text + " changed")


@pytest.mark.pg
def test_doctor_lists_stale_candidates(tmp_path, monkeypatch) -> None:
    """Index doctor reports content-hash staleness as a read-only re-embed
    candidate listing (no mutation) when store_objects text has drifted past
    the stamped store_vector_index content_hash."""
    if not _pg_available():
        pytest.skip("Postgres backend not available")

    from app.index.doctor import diagnose_index, reset_diagnose_cache
    from app.stores import get_object_store
    from tests.indexer.test_outbox_roundtrip_pg import (
        _configure_isolated_pg_test,
        _drop_schema,
        _reset_store_backend_cache_only,
    )

    base_dsn, schema = _configure_isolated_pg_test(tmp_path, monkeypatch)
    reset_diagnose_cache()
    try:
        from app.search import service as search_service
        from app.stores.pg import _connect

        oid, _dim = search_service.ingest_object(
            kind="note",
            source_ref="unit-test://doctor-stale",
            payload={"text": "original content", "content": "original content"},
            text="original content",
        )
        # The staleness join needs a store_objects row (the "current" source
        # text side of the comparison) — ingest_object only writes the
        # vector-index side, so seed store_objects directly here.
        get_object_store().put(
            oid,
            kind="note",
            source_ref="unit-test://doctor-stale",
            payload={"text": "original content", "content": "original content"},
        )

        # Simulate the source drifting: store_objects text changes but the
        # store_vector_index row (and its stamped content_hash) is untouched —
        # exactly the divergence content-hash staleness detects.
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE store_objects SET payload = payload || '{\"text\": \"changed content\", \"content\": \"changed content\"}'::jsonb WHERE object_id = %s",
                    (oid,),
                )

        reset_diagnose_cache()
        result = diagnose_index()

        staleness = result.get("content_hash_staleness") or {}
        assert staleness.get("stale_count", 0) >= 1
        assert str(oid) in (staleness.get("stale_sample_ids") or [])

        # Read-only: the durable vector row's stamped content_hash is untouched
        # by diagnosis (still reflects the original, pre-drift text).
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT payload->'provenance'->>'content_hash' AS content_hash "
                    "FROM store_vector_index WHERE object_id = %s",
                    (oid,),
                )
                row = cur.fetchone()
        assert row["content_hash"] == compute_content_hash("original content")
    finally:
        reset_diagnose_cache()
        _reset_store_backend_cache_only()
        _drop_schema(base_dsn, schema)


@pytest.mark.pg
def test_doctor_uses_rebuild_text_precedence_for_content_hash(tmp_path, monkeypatch) -> None:
    """Doctor hashes the same ``content`` field that rebuild embeds when both
    ``content`` and a divergent legacy ``text`` field are present."""
    if not _pg_available():
        pytest.skip("Postgres backend not available")

    from app.index.doctor import diagnose_index, reset_diagnose_cache
    from app.stores import get_object_store
    from tests.indexer.test_outbox_roundtrip_pg import (
        _configure_isolated_pg_test,
        _drop_schema,
        _reset_store_backend_cache_only,
    )

    base_dsn, schema = _configure_isolated_pg_test(tmp_path, monkeypatch)
    reset_diagnose_cache()
    try:
        from app.search import service as search_service

        canonical_content = "producer-selected content"
        oid, _dim = search_service.ingest_object(
            kind="note",
            source_ref="unit-test://doctor-content-precedence",
            payload={"content": canonical_content, "text": "legacy shadow text"},
            text=canonical_content,
        )
        get_object_store().put(
            oid,
            kind="note",
            source_ref="unit-test://doctor-content-precedence",
            payload={"content": canonical_content, "text": "legacy shadow text"},
        )

        reset_diagnose_cache()
        result = diagnose_index()
        staleness = result.get("content_hash_staleness") or {}
        assert staleness.get("stale_count", 0) == 0
        assert str(oid) not in (staleness.get("stale_sample_ids") or [])
    finally:
        reset_diagnose_cache()
        _reset_store_backend_cache_only()
        _drop_schema(base_dsn, schema)


@pytest.mark.pg
def test_reconcile_incremental_on_stale_only(tmp_path, monkeypatch) -> None:
    """`index reconcile` re-embeds only stale rows: unchanged rows are untouched."""
    if not _pg_available():
        pytest.skip("Postgres backend not available")

    from click.testing import CliRunner

    from app.cli import cli
    from app.stores import get_object_store
    from app.stores.pg import _connect
    from tests.indexer.test_outbox_roundtrip_pg import (
        _configure_isolated_pg_test,
        _drop_schema,
        _reset_store_backend_cache_only,
    )

    base_dsn, schema = _configure_isolated_pg_test(tmp_path, monkeypatch)
    try:
        from app.search import service as search_service

        stale_oid, _ = search_service.ingest_object(
            kind="note",
            source_ref="unit-test://reconcile-stale",
            payload={"text": "stale original", "content": "stale original"},
            text="stale original",
        )
        get_object_store().put(
            stale_oid,
            kind="note",
            source_ref="unit-test://reconcile-stale",
            payload={"text": "stale original", "content": "stale original"},
        )
        fresh_oid, _ = search_service.ingest_object(
            kind="note",
            source_ref="unit-test://reconcile-fresh",
            payload={"text": "fresh unchanged", "content": "fresh unchanged"},
            text="fresh unchanged",
        )
        get_object_store().put(
            fresh_oid,
            kind="note",
            source_ref="unit-test://reconcile-fresh",
            payload={"text": "fresh unchanged", "content": "fresh unchanged"},
        )

        # Simulate content drift on ONE object only. The authoritative
        # ``content`` field includes an AI panel while the legacy ``text``
        # field diverges; reconcile and doctor must both use content-first
        # precedence and the producer's panel-stripping hash canonicalization.
        changed_content = """stale changed

%% AI:Start %%
## AI-instruktion
Transient panel text.
%% AI:End %%
"""
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE store_objects "
                    "SET payload = payload || "
                    "jsonb_build_object('content', %s::text, 'text', %s::text) "
                    "WHERE object_id = %s",
                    (changed_content, "legacy shadow text", stale_oid),
                )

        runner = CliRunner()
        env = dict(os.environ)
        result = runner.invoke(cli, ["index", "reconcile", "--backend", "pg", "--json"], env=env)
        assert result.exit_code == 0, result.output

        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT object_id, payload->'provenance'->>'content_hash' AS content_hash "
                    "FROM store_vector_index WHERE object_id IN (%s, %s)",
                    (stale_oid, fresh_oid),
                )
                rows_after = {row["object_id"]: row["content_hash"] for row in cur.fetchall()}

        # Stale row is re-embedded: its hash matches the producer's canonical
        # panel-free form of the selected content field.
        assert rows_after[stale_oid] == compute_content_hash(strip_ai_panels(changed_content))

        # Fresh (unchanged) row is untouched: same content_hash as before —
        # incremental repair, not a blanket re-embed of the whole index.
        assert rows_after[fresh_oid] == compute_content_hash("fresh unchanged")

        from app.index.doctor import diagnose_index, reset_diagnose_cache

        reset_diagnose_cache()
        diagnosis = diagnose_index()
        staleness = diagnosis.get("content_hash_staleness") or {}
        assert staleness.get("stale_count", 0) == 0
        assert str(stale_oid) not in (staleness.get("stale_sample_ids") or [])
    finally:
        _reset_store_backend_cache_only()
        _drop_schema(base_dsn, schema)
