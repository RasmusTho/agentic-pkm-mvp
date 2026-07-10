"""Retrieval-spine invariants (Track H).

- retrieval_serves_durable_truth_fresh (G1res-1, #2981): after a durable
  upsert/purge commits, retrieval reflects it within the declared freshness
  bound (one generation check, bounded by the >=1s min-check interval)
  without a process restart or explicit force=True rebuild. Extends the
  KERNEL-05 cache-through contract (docs/RUNTIME_CORRECTNESS_KERNEL/
  RETRIEVAL_READS_DURABLE_INDEX.md); changes only WHEN a rebuild happens,
  never what is eligible.

- embedding_identity_converges_post_reindex (G3-1, #2984): after a BGE-M3
  identity migration + reconcile, index doctor reports exactly one embedding
  identity. Any mixed-identity window during migration must be surfaced
  LOUDLY (as a doctor `issue`, not merely absorbed into a `warning` or
  silently ignored) — never a silent partial migration.
"""

from __future__ import annotations

import os
from uuid import UUID, uuid4

import pytest

from app.components.embeddings import EmbeddingIdentity
from app.retrieval import hybrid
from app.stores import get_vector_index, reset_store_backends


@pytest.fixture(autouse=True)
def _isolate_stores(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("STORE_BACKEND", "memory")
    # ADR-0059 D1 (#3405): the serving path now scores with each row's
    # STORED vector instead of silently re-embedding every document with the
    # live runtime identity, so this file's 8-dim seed vectors must match the
    # dim the live query embedder resolves to (previously masked by the
    # read-path re-embed this ADR removes).
    monkeypatch.setenv("EMBED_DIM", "8")
    reset_store_backends()
    hybrid.get_store().set_documents([])
    hybrid.reset_durable_rebuild_state()
    yield
    reset_store_backends()
    hybrid.get_store().set_documents([])
    hybrid.reset_durable_rebuild_state()


def _upsert_doc(oid: UUID, title: str, text: str) -> None:
    identity = EmbeddingIdentity(provider="mock", model="embed-test", dim=8, normalize=False)
    get_vector_index().upsert(
        object_id=oid,
        kind="note",
        source_ref=f"unit-test://{title}",
        payload={"title": title, "text": text, "content": text},
        embedding=[0.1] * 8,
        model=identity.model,
        identity=identity,
    )


def _force_generation_check_due() -> None:
    """Make the next serving-path access due for a generation check without
    weakening the mandatory >=1s production min-check interval."""
    hybrid._LAST_GENERATION_CHECK_MONOTONIC = 0.0


def test_retrieval_serves_durable_truth_fresh() -> None:
    """Invariant: retrieval serves durable truth fresh — an upsert AND a purge
    committed after process warm are both reflected within the freshness
    bound, with no restart and no force=True."""
    kept = uuid4()
    purged = uuid4()
    _upsert_doc(kept, "Kept note", "kept retrieval content about mountains")
    _upsert_doc(purged, "Purged note", "purged retrieval content about oceans")
    hybrid.rebuild_from_durable_index()

    warm_ids = {hit["doc_id"] for hit in hybrid.hybrid_search("retrieval content", k=10)}
    assert {str(kept), str(purged)} <= warm_ids

    # Durable upsert after warm -> visible without restart.
    fresh = uuid4()
    _upsert_doc(fresh, "Fresh note", "fresh retrieval content about glaciers")
    _force_generation_check_due()
    ids = {hit["doc_id"] for hit in hybrid.hybrid_search("fresh retrieval glaciers", k=10)}
    assert str(fresh) in ids, (
        "retrieval_serves_durable_truth_fresh violated: post-warm durable "
        "upsert not visible without restart"
    )

    # Durable purge after warm -> invisible without restart.
    assert get_vector_index().purge_vectors(purged, view="note") == 1
    _force_generation_check_due()
    ids = {hit["doc_id"] for hit in hybrid.hybrid_search("retrieval content", k=10)}
    assert str(purged) not in ids, (
        "retrieval_serves_durable_truth_fresh violated: post-warm durable "
        "purge still served after the freshness bound"
    )
    assert str(kept) in ids


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


@pytest.mark.pg
def test_identity_converges(tmp_path, monkeypatch) -> None:
    """embedding_identity_converges_post_reindex (G3-1, #2984): a mixed-identity
    window (old nomic-embed-text @768 rows alongside new bge-m3 @1024 rows) is
    surfaced loudly by index doctor as an `issue` (never silent); after
    `index reconcile` converges the non-primary rows, doctor reports exactly
    one identity."""
    if not _pg_available():
        pytest.skip("Postgres backend not available")

    import json
    from dataclasses import asdict

    import psycopg
    from click.testing import CliRunner

    from app.cli.index_rebuild import index as index_cli
    from app.db.dsn import resolve_dsn
    from app.index import doctor as doctor_mod
    from app.stores import pg as pg_store
    import app.cli.index_rebuild as reconcile_mod

    def _dsn() -> str:
        return resolve_dsn() or os.getenv("DATABASE_URL", "postgresql://app:app@127.0.0.1:15432/app")

    monkeypatch.setenv("DATABASE_URL", _dsn())
    monkeypatch.setenv("STORE_BACKEND", "pg")
    reset_store_backends()
    pg_store._TABLES_READY = False
    pg_store._ensure_tables()
    pg_store.truncate_pg_tables()
    doctor_mod.reset_diagnose_cache()

    old_identity = EmbeddingIdentity(provider="ollama", model="nomic-embed-text:latest", dim=1024, normalize=True)
    new_identity = EmbeddingIdentity(provider="ollama", model="bge-m3:latest", dim=1024, normalize=True)

    class _StubClient:
        identity = new_identity

        def embed_text(self, text: str) -> list[float]:
            base = float(len(text) % 7 + 1)
            return [base] * new_identity.dim

    def _seed_row(dsn: str, identity: EmbeddingIdentity, *, text: str) -> str:
        # Writes store_vector_index directly, bypassing VectorIndex.upsert()'s
        # single-identity-per-write guardrail, so a mixed-identity index can be
        # constructed (mirrors tests/cli/test_index_reconcile.py::_seed_row).
        oid = uuid4()
        with psycopg.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO store_objects (object_id, kind, source_ref, payload, created_at, updated_at)
                    VALUES (%s, %s, %s, %s::jsonb, now(), now())
                    """,
                    (oid, "note", "tests/identity-converges", json.dumps({"text": text})),
                )
                cur.execute(
                    """
                    INSERT INTO store_vector_index (
                        object_id, kind, source_ref, payload, embedding,
                        dim, model, provider, normalize, updated_at
                    )
                    VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, now())
                    """,
                    (
                        oid,
                        "note",
                        "tests/identity-converges",
                        json.dumps({"text": text}),
                        [0.1] * identity.dim,
                        identity.dim,
                        identity.model,
                        identity.provider,
                        identity.normalize,
                    ),
                )
            conn.commit()
        return str(oid)

    try:
        with psycopg.connect(_dsn()) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO vector_index_meta (id, identity_json, updated_at)
                    VALUES (1, %s, now())
                    ON CONFLICT (id) DO UPDATE SET identity_json = EXCLUDED.identity_json, updated_at = now()
                    """,
                    (json.dumps(asdict(new_identity)),),
                )
            conn.commit()

        _seed_row(_dsn(), old_identity, text="pre-migration row")
        _seed_row(_dsn(), new_identity, text="post-migration row")

        # Mid-migration: mixed identity must be LOUD (an issue), never silent.
        doctor_mod.reset_diagnose_cache()
        mid_migration = doctor_mod.diagnose_index()
        assert len(mid_migration.get("mixed_identities") or []) > 1
        assert any("Mixed embedding identities" in issue for issue in mid_migration.get("issues") or []), (
            "embedding_identity_converges_post_reindex violated: mixed identity "
            "during migration was not surfaced as a loud doctor issue"
        )

        monkeypatch.setattr(reconcile_mod, "get_embedding_client", lambda *a, **k: _StubClient())
        runner = CliRunner()
        result = runner.invoke(index_cli, ["reconcile", "--json"])
        assert result.exit_code == 0, result.output

        doctor_mod.reset_diagnose_cache()
        post_migration = doctor_mod.diagnose_index()
        mixed_after = post_migration.get("mixed_identities") or []
        assert len(mixed_after) <= 1, (
            "embedding_identity_converges_post_reindex violated: doctor still "
            f"reports more than one identity post-reconcile: {mixed_after}"
        )
    finally:
        doctor_mod.reset_diagnose_cache()
        pg_store.truncate_pg_tables()
        reset_store_backends()
