from __future__ import annotations

import pytest

pytestmark = pytest.mark.not_pg


def test_heading_aware_boundaries():
    """Structural chunker splits on markdown heading boundaries and tracks the
    active heading path per chunk (h1..h6 nesting), rather than blindly
    accumulating lines to max_chars (issue #2323)."""
    from app.ingest.chunk_policy import build_structural_chunks

    text = (
        "# Title\n\n"
        "Intro paragraph.\n\n"
        "## Section A\n\n"
        "Content A line one.\n"
        "Content A line two.\n\n"
        "## Section B\n\n"
        "Content B.\n\n"
        "### Section B.1\n\n"
        "Nested content.\n"
    )

    chunks = build_structural_chunks(text, max_chars=3000)

    assert len(chunks) == 4
    assert chunks[0]["heading_path"] == ["Title"]
    assert "Intro paragraph." in chunks[0]["text"]

    assert chunks[1]["heading_path"] == ["Title", "Section A"]
    assert "Content A line one." in chunks[1]["text"]

    assert chunks[2]["heading_path"] == ["Title", "Section B"]
    assert "Content B." in chunks[2]["text"]

    assert chunks[3]["heading_path"] == ["Title", "Section B", "Section B.1"]
    assert "Nested content." in chunks[3]["text"]

    # Offsets are exact: slicing the original text at [char_start:char_end]
    # reconstructs each chunk's text verbatim.
    for chunk in chunks:
        assert text[chunk["char_start"] : chunk["char_end"]] == chunk["text"]


def test_heading_aware_boundaries_oversized_section_still_splits():
    """A single section that itself exceeds max_chars still gets sub-split
    (char-accumulator fallback within the section), preserving heading_path
    on every sub-chunk."""
    from app.ingest.chunk_policy import build_structural_chunks

    body = ("word " * 50 + "\n") * 40  # long body under one heading
    text = f"# Big Section\n\n{body}"

    chunks = build_structural_chunks(text, max_chars=500)

    assert len(chunks) > 1
    assert all(c["heading_path"] == ["Big Section"] for c in chunks)
    for chunk in chunks:
        assert text[chunk["char_start"] : chunk["char_end"]] == chunk["text"]


def test_diarization_path_preserved_when_segments_supplied(monkeypatch):
    """The existing speaker-aware diarization chunking path must not be
    disturbed by the structural chunker (issue #2323 constraint)."""
    from app.ingest.chunk_policy import build_chunks

    monkeypatch.setenv("DIARIZE_ENABLE", "1")
    records = build_chunks(
        "",
        segments=[
            {"speaker": "spk_a", "text": "alpha statement"},
            {"speaker": "spk_b", "text": "beta reply"},
        ],
        source_id="transcript-1",
    )
    assert records[0]["speaker"] == "spk_a"
    assert records[1]["speaker"] == "spk_b"
    # Diarized chunks still carry chunk metadata schema v1 fields.
    for record in records:
        assert record["heading_path"] == []
        assert record["source_id"] == "transcript-1"


def test_chunk_metadata_complete():
    """Every chunk produced by build_chunks carries the complete chunk metadata
    schema v1: chunk_id, source_id, heading_path, char_start, char_end,
    language, provenance (issue #2323)."""
    from app.ingest.chunk_policy import CHUNK_METADATA_FIELDS_V1, build_chunks

    text = "# Heading\n\nSome body text that is not too long.\n"
    chunks = build_chunks(
        text,
        source_id="note-abc",
        language="en",
        provenance="vault:notes/example.md",
        max_chars=3000,
    )

    assert chunks, "expected at least one chunk"
    for chunk in chunks:
        for field in CHUNK_METADATA_FIELDS_V1:
            assert field in chunk, f"missing chunk metadata field: {field}"
        assert chunk["source_id"] == "note-abc"
        assert chunk["language"] == "en"
        assert chunk["provenance"] == "vault:notes/example.md"
        assert isinstance(chunk["chunk_id"], str) and chunk["chunk_id"]
        assert isinstance(chunk["heading_path"], list)
        assert isinstance(chunk["char_start"], int)
        assert isinstance(chunk["char_end"], int)
        assert chunk["char_start"] <= chunk["char_end"]

    # chunk_id is a plain string, compatible with
    # IncludedItem.chunk_ids: list[str] in app/context_bundles/schema.py.
    chunk_ids = [c["chunk_id"] for c in chunks]
    assert len(chunk_ids) == len(set(chunk_ids)), "chunk_ids must be unique within a source"


def test_chunk_ids_stable_across_rechunking():
    """chunk_id is deterministic: re-chunking identical input with the same
    source_id produces identical chunk_ids (needed so chunk identity survives
    reprocessing without an explicit chunk store)."""
    from app.ingest.chunk_policy import build_chunks

    text = "# A\n\nfoo\n\n# B\n\nbar\n"
    first = build_chunks(text, source_id="stable-note", max_chars=3000)
    second = build_chunks(text, source_id="stable-note", max_chars=3000)

    assert [c["chunk_id"] for c in first] == [c["chunk_id"] for c in second]
