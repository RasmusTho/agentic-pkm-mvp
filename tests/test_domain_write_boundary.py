"""Tests for domain validation at ingest/write boundary (Issue #437).

Tests verify that:
1. Missing domain is normalized or recorded as 'unscoped' at ingest
2. Domain assignment is visible in payloads
3. Retrieval treats missing/unscoped domain conservatively
4. Path-derived domain fallback is not used
"""

from __future__ import annotations

import pytest
from pathlib import Path
from datetime import datetime, timezone

from app.ingest.vault_alpha import _ingest_single
from app.retrieval.hybrid import _extract_domain, _doc_in_scope, get_store, Document
from app.store.object_store import ObjectStore, DomainObject


def test_ingest_without_domain_marks_unscoped(tmp_path: Path) -> None:
    """Test that notes without explicit domain are marked 'unscoped'."""
    vault_root = tmp_path / "vault"
    vault_root.mkdir()

    note_path = vault_root / "test_note.md"
    note_path.write_text("# Test Note\n\nNo domain specified in frontmatter.")

    # Ingest the note
    note_uuid = _ingest_single(note_path, vault_root=vault_root, trace_id="test-trace")

    # Retrieve the ingested object
    obj = ObjectStore().get_object(note_uuid)
    assert obj is not None
    assert obj.payload.get("domain") == "unscoped"
    assert obj.payload["core6"].get("domain") == "unscoped"


def test_ingest_with_explicit_domain_preserves_domain(tmp_path: Path) -> None:
    """Test that notes with explicit domain preserve that domain."""
    vault_root = tmp_path / "vault"
    vault_root.mkdir()

    note_path = vault_root / "test_note.md"
    note_path.write_text("---\ndomain: work\n---\n# Test Note\n\nExplicit domain specified.")

    # Ingest the note
    note_uuid = _ingest_single(note_path, vault_root=vault_root, trace_id="test-trace")

    # Retrieve the ingested object
    obj = ObjectStore().get_object(note_uuid)
    assert obj is not None
    assert obj.payload.get("domain") == "work"
    assert obj.payload["core6"].get("domain") == "work"


def test_path_derived_domain_not_used(tmp_path: Path) -> None:
    """Test that domain is NOT inferred from filesystem path.

    This verifies the fix for Finding 1 in V60_ARCHITECTURE_TARGET.md.
    """
    # Document in folder 'work/projects/test.md' should not get domain='work' from path.
    doc = Document(
        doc_id="test-doc",
        text="Test content",
        source_ref="work/projects/test.md",
        payload={}  # No explicit domain in payload
    )

    # Should return None (unscoped), not 'work' from path
    domain = _extract_domain(doc)
    assert domain is None


def test_unscoped_document_filtered_in_specific_scope_query() -> None:
    """Test that unscoped documents are filtered when querying a specific scope.

    Per LAYERING_MODEL contract: "The stricter boundary wins."
    """
    doc_with_domain = Document(
        doc_id="doc-with-domain",
        text="Content with explicit domain",
        source_ref="test.md",
        payload={"domain": "work"}
    )

    doc_without_domain = Document(
        doc_id="doc-without-domain",
        text="Content without domain",
        source_ref="test.md",
        payload={}
    )

    # When querying 'work' scope, only doc with domain='work' should match
    assert _doc_in_scope(doc_with_domain, "work") is True
    assert _doc_in_scope(doc_without_domain, "work") is False


def test_explicit_unscoped_domain_treated_conservatively() -> None:
    """Test that explicitly marked 'unscoped' documents are conservative."""
    doc = Document(
        doc_id="doc-unscoped",
        text="Content marked unscoped",
        source_ref="test.md",
        payload={"domain": "unscoped"}
    )

    # unscoped documents should only match when querying unscoped
    assert _doc_in_scope(doc, "unscoped") is True
    assert _doc_in_scope(doc, "work") is False
    assert _doc_in_scope(doc, "private") is False


def test_bridge_domains_respected(monkeypatch) -> None:
    """Test that bridge_domains are respected in scope matching."""
    doc = Document(
        doc_id="doc-bridge",
        text="Content with bridge",
        source_ref="test.md",
        payload={
            "domain": "work",
            "bridge_domains": "private,shared"
        }
    )

    assert _doc_in_scope(doc, "work") is True
    assert _doc_in_scope(doc, "private") is True  # Via bridge
    assert _doc_in_scope(doc, "shared") is True   # Via bridge
    assert _doc_in_scope(doc, "rpg") is False


def test_hybrid_store_domain_extraction(monkeypatch) -> None:
    """Test domain extraction in hybrid search context."""
    monkeypatch.setenv("LLM_PROVIDER", "mock")

    store = get_store()
    try:
        store.set_documents([
            {
                "doc_id": "work-doc",
                "text": "Work related content",
                "source_ref": "work/notes.md",
                "payload": {"domain": "work"}
            },
            {
                "doc_id": "unscoped-doc",
                "text": "Unscoped content",
                "source_ref": "notes.md",
                "payload": {}  # No domain
            },
            {
                "doc_id": "personal-doc",
                "text": "Personal related content",
                "source_ref": "personal/notes.md",
                "payload": {"domain": "personal"}
            },
        ])

        # Extract domains
        docs = store.all()
        domains = [_extract_domain(doc) for doc in docs]

        assert "work" in domains
        assert "personal" in domains
        assert None in domains  # Unscoped

        # Verify path inference is NOT used for unscoped doc
        unscoped_doc = [d for d in docs if d.doc_id == "unscoped-doc"][0]
        assert _extract_domain(unscoped_doc) is None
    finally:
        store.set_documents([])
