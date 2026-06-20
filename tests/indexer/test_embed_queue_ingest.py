"""Tests that drive the production call site handle_ingest_object_created.

AC5: One embedding failure does not abort handle_ingest_object_created.
The function must emit index.embedding.failed and return without raising.
"""
from __future__ import annotations

from unittest.mock import patch

from app.llm.embed_queue import EmbedDeadLetterError


# ---------------------------------------------------------------------------
# test_exhausted_embed_dead_letters_and_continues
#   Canonical name from the issue spec's committed Verify targets.
#   Drives the PRODUCTION call site; asserts (a) no exception propagates and
#   (b) emit_index_embedding_failed is called.
# ---------------------------------------------------------------------------

def test_exhausted_embed_dead_letters_and_continues(monkeypatch):
    """EmbedDeadLetterError in handle_ingest_object_created → emits failed + continues.

    This test drives the production call site (app.services.indexer) so the
    wiring is exercised, not just an isolated unit.
    """
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("EMBED_DIM", "8")
    monkeypatch.setenv("STORE_BACKEND", "memory")

    obj = {
        "uuid": "11111111-1111-1111-1111-111111111111",
        "content": "some content to embed",
        "title": "Test Note",
        "kind": "note",
        "source_ref": "vault/test/note.md",
        "trace_id": "trace-test-001",
        "payload": {},
    }

    dead_letter_exc = EmbedDeadLetterError("embed exhausted after 3 attempts (transient): EOF")

    emit_calls: list = []

    def fake_emit_failed(**kwargs):
        emit_calls.append(kwargs)

    with patch("app.services.indexer.embed_with_retry", side_effect=dead_letter_exc):
        with patch("app.services.indexer.emit_index_embedding_failed", side_effect=fake_emit_failed):
            # Must not raise
            from app.services.indexer import handle_ingest_object_created
            handle_ingest_object_created(obj)

    # (a) No exception propagated — if we reach here, it's fine.
    # (b) emit_index_embedding_failed was called exactly once.
    assert len(emit_calls) == 1, f"Expected exactly one emit_index_embedding_failed call, got {emit_calls}"
    call_kwargs = emit_calls[0]
    assert call_kwargs.get("object_id") == "11111111-1111-1111-1111-111111111111"
    assert "embed exhausted" in call_kwargs.get("error", "")


# ---------------------------------------------------------------------------
# test_dead_letter_does_not_abort_ingest (AC5 — named in spec ACs)
# ---------------------------------------------------------------------------

def test_dead_letter_does_not_abort_ingest(monkeypatch):
    """Patch embed_with_retry to raise EmbedDeadLetterError; assert no exception propagates."""
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("EMBED_DIM", "8")
    monkeypatch.setenv("STORE_BACKEND", "memory")

    obj = {
        "uuid": "22222222-2222-2222-2222-222222222222",
        "content": "another note",
        "title": "Another Note",
        "kind": "note",
        "source_ref": "vault/test/another.md",
        "trace_id": None,
        "payload": {},
    }

    with patch(
        "app.services.indexer.embed_with_retry",
        side_effect=EmbedDeadLetterError("embed exhausted after 3 attempts (transient): EOF"),
    ):
        with patch("app.services.indexer.emit_index_embedding_failed") as mock_emit:
            from app.services.indexer import handle_ingest_object_created
            # Must not raise
            handle_ingest_object_created(obj)
            assert mock_emit.called, "emit_index_embedding_failed must have been called"
