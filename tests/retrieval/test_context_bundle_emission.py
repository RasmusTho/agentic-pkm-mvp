"""Tests for retrieval-side context bundle emission (CONTEXT-BUNDLES-02, #896)."""
from __future__ import annotations

import pytest

from app.context_bundles.schema import ContextBundle, ExcludedItem
from app.retrieval.capability import RetrievalHit, RetrievalResponse
from app.retrieval.bundle_emission import emit_retrieval_bundle, RetrievalBundleResult


def _make_response(hit_ids: list[str], scores: list[float] | None = None) -> RetrievalResponse:
    if scores is None:
        scores = [1.0 - i * 0.1 for i in range(len(hit_ids))]
    hits = [
        RetrievalHit(
            object_id=hid,
            doc_id=hid,
            text=f"text for {hid}",
            score=s,
            snippet=None,
            source_ref=None,
            payload={},
        )
        for hid, s in zip(hit_ids, scores)
    ]
    return RetrievalResponse(query="test query", hits=hits, trace_id="trace-1")


def test_retrieval_emits_context_bundle():
    response = _make_response(["doc-a", "doc-b", "doc-c"])
    result = emit_retrieval_bundle(response, selected_ids=["doc-a", "doc-b"])
    assert isinstance(result, RetrievalBundleResult)
    assert isinstance(result.bundle, ContextBundle)
    assert result.bundle.id
    assert result.bundle.created_at is not None


def test_retrieval_distinguishes_candidates_from_selected_context():
    response = _make_response(["doc-a", "doc-b", "doc-c"])
    result = emit_retrieval_bundle(response, selected_ids=["doc-a"])
    included_ids = {item.artifact_id for item in result.bundle.included}
    assert included_ids == {"doc-a"}, "only selected item should be in bundle.included"
    candidate_ids = {c["artifact_id"] for c in result.ranked_candidates}
    assert {"doc-a", "doc-b", "doc-c"} == candidate_ids, (
        "all ranked candidates must be preserved separately, not collapsed into included"
    )


def test_retrieval_context_bundle_records_interpretation_affecting_exclusions():
    response = _make_response(["doc-a", "doc-b", "doc-c"])
    exclusions = [
        ExcludedItem(
            artifact_id="doc-b",
            reason="trust_state=unverified; omission changes answer scope",
        )
    ]
    result = emit_retrieval_bundle(
        response,
        selected_ids=["doc-a"],
        excluded=exclusions,
    )
    excluded_ids = {item.artifact_id for item in result.bundle.excluded}
    assert "doc-b" in excluded_ids
    doc_b_exclusion = next(e for e in result.bundle.excluded if e.artifact_id == "doc-b")
    assert doc_b_exclusion.reason, "exclusion must carry reason so omission is auditable"


def test_retrieval_context_bundle_does_not_authorize_writeback():
    response = _make_response(["doc-a", "doc-b"])
    result = emit_retrieval_bundle(response, selected_ids=["doc-a", "doc-b"])
    assert result.bundle.authority.may_write is False, (
        "retrieval bundles must never authorize writeback without explicit downstream upgrade"
    )
