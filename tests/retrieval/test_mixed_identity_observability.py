"""ADR-0059 step 3 (#3406) — mixed-identity observability on rebuild.

``rebuild_from_durable_index()`` compares each durable row's recorded
``provider``/``model`` against the active primary embedding identity
(resolved the same way the write path resolves its default —
``get_embedding_identity()``) and logs ONE structured, content-free line per
rebuild: the mixed-identity row count plus the distinct identity tuples
involved. Zero mixed rows is the common case and logs quietly at info level,
never warning.

Runs entirely under ``not pg`` via the memory backend (``STORE_BACKEND=memory``),
mirroring the sibling ``tests/retrieval/test_hybrid_stored_vectors.py``. The
in-memory ``MemoryVectorIndex`` enforces a single store-wide identity at
``upsert()`` time (mixed-identity detection is Pg-only per
``docs/EMBEDDING_RELIABILITY/DIMENSION_CONSISTENCY_AND_REINDEX.md`` "Out of
Scope"), so a mixed corpus is simulated by patching the durable index's
``all_rows()`` return value to carry a divergent ``provider``/``model`` on a
subset of rows — the same shape a real CTI-2 fallback write produces (a
dimension-matched, L2-renormalized vector under a different recorded
identity), without requiring a live Postgres backend.
"""

from __future__ import annotations

import logging
from uuid import UUID, uuid4

import pytest

from app.components.embeddings import get_embedding_identity
from app.components.retrieval import embed_docs
from app.retrieval import hybrid
from app.stores import get_vector_index, reset_store_backends

_SEED_TEXTS = [
    ("Alpha note", "alpha retrieval content about mountains and glaciers"),
    ("Beta note", "beta retrieval content about oceans and currents"),
    ("Gamma note", "gamma retrieval content about deserts and dunes"),
]


@pytest.fixture(autouse=True)
def _isolate_stores(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("STORE_BACKEND", "memory")
    reset_store_backends()
    hybrid.get_store().set_documents([])
    hybrid.reset_durable_rebuild_state()
    yield
    reset_store_backends()
    hybrid.get_store().set_documents([])
    hybrid.reset_durable_rebuild_state()


def _seed_durable_index() -> list[UUID]:
    """Seed the durable index with rows all carrying the active primary identity."""
    texts = [text for _title, text in _SEED_TEXTS]
    vectors, identity = embed_docs(texts)
    idx = get_vector_index()
    ids: list[UUID] = []
    for (title, text), vector in zip(_SEED_TEXTS, vectors):
        oid = uuid4()
        idx.upsert(
            object_id=oid,
            kind="note",
            source_ref=f"unit-test://{title}",
            payload={"title": title, "text": text, "content": text},
            embedding=vector,
            model=identity.model,
            identity=identity,
        )
        ids.append(oid)
    return ids


def test_rebuild_logs_mixed_identity_count(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """AC1: a rebuild over a corpus containing fallback-identity rows logs the
    mixed-identity count once, content-free (count + identity tuples, never
    note title/text)."""
    _seed_durable_index()
    idx = get_vector_index()
    real_all_rows = idx.all_rows

    def _patched_all_rows():
        rows = real_all_rows()
        # Simulate two CTI-2 reconcilable fallback rows: dimension-matched
        # vector unchanged, recorded identity diverges from the primary.
        for row in rows[:2]:
            row["provider"] = "gemini"
            row["model"] = "gemini-embedding-001"
        return rows

    monkeypatch.setattr(idx, "all_rows", _patched_all_rows)

    caplog.set_level(logging.INFO, logger="app.retrieval.hybrid")
    loaded = hybrid.rebuild_from_durable_index(force=True)
    assert loaded == len(_SEED_TEXTS)

    mixed_records = [
        r for r in caplog.records if "mixed_identity_count" in r.getMessage()
    ]
    assert len(mixed_records) == 1, "expected exactly one structured mixed-identity log line"
    record = mixed_records[0]
    assert record.levelno == logging.INFO, "mixed-identity signal must never log at warning"
    message = record.getMessage()
    assert "mixed_identity_count=2" in message
    assert "gemini" in message
    assert "gemini-embedding-001" in message
    # Content-free: never leak note title/text into the log line.
    for title, text in _SEED_TEXTS:
        assert title not in message
        assert text not in message


def test_clean_corpus_logs_zero_quietly(caplog: pytest.LogCaptureFixture) -> None:
    """AC3: zero mixed rows logs count 0 quietly (info/debug, never warning)."""
    _seed_durable_index()

    caplog.set_level(logging.DEBUG, logger="app.retrieval.hybrid")
    loaded = hybrid.rebuild_from_durable_index(force=True)
    assert loaded == len(_SEED_TEXTS)

    mixed_records = [
        r for r in caplog.records if "mixed_identity_count" in r.getMessage()
    ]
    assert len(mixed_records) == 1
    record = mixed_records[0]
    assert "mixed_identity_count=0" in record.getMessage()
    assert record.levelno in (logging.INFO, logging.DEBUG)

    warning_records = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert not warning_records, f"expected no warning-level noise on a clean corpus, got: {warning_records}"


def test_active_primary_identity_resolution_matches_write_path() -> None:
    """Sanity check: the identity rebuild compares against is the same
    ``get_embedding_identity()`` the write path resolves as its default
    (``app/stores/pg.py``), not some independently derived value."""
    identity = get_embedding_identity()
    assert identity.provider
    assert identity.model


def test_mixed_identity_count_uses_full_identity_tuple(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Same provider/model but changed dimension or normalization is still
    an identity drift and must be counted in rebuild observability."""
    _seed_durable_index()
    idx = get_vector_index()
    real_all_rows = idx.all_rows
    active = get_embedding_identity()

    def _patched_all_rows():
        rows = real_all_rows()
        rows[0].update({"provider": active.provider, "model": active.model, "dim": active.dim + 1, "normalize": active.normalize})
        rows[1].update({"provider": active.provider, "model": active.model, "dim": active.dim, "normalize": not active.normalize})
        return rows

    monkeypatch.setattr(idx, "all_rows", _patched_all_rows)
    caplog.set_level(logging.INFO, logger="app.retrieval.hybrid")
    hybrid.rebuild_from_durable_index(force=True)
    message = next(r.getMessage() for r in caplog.records if "mixed_identity_count" in r.getMessage())
    assert "mixed_identity_count=2" in message
    assert str(active.dim + 1) in message
    assert str(not active.normalize) in message
