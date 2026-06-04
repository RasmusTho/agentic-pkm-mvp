"""Production retrieval bundle emission tests (#1562).

These cover wiring ``emit_retrieval_bundle`` into the real retrieval capability
so production retrieval emits an inspectable ``ContextBundle`` and records a
runtime creation receipt, while keeping ranked candidates distinct from the
selected included items and never upgrading write authority.
"""
from __future__ import annotations

from app.context_bundles.schema import ContextBundle
from app.retrieval.capability import RetrievalHit, RetrievalRequest, RetrievalResponse


def _response(n: int = 3) -> RetrievalResponse:
    hits = [
        RetrievalHit(
            object_id=f"art-{i}",
            doc_id=f"doc-{i}",
            text=f"text {i}",
            score=1.0 - i * 0.1,
            snippet=None,
            source_ref=f"vault/note-{i}.md",
            payload={},
        )
        for i in range(n)
    ]
    return RetrievalResponse(query="real query", hits=hits, trace_id="trace-xyz")


def test_real_retrieval_emits_bundle(monkeypatch):
    import app.retrieval.production_bundle as pb

    # Exercise the production path end-to-end with a real RetrievalResponse,
    # stubbing only the index adapter (retrieve) so the test is deterministic.
    resp = _response(3)
    monkeypatch.setattr(pb, "retrieve", lambda request: resp)

    result, receipt = pb.retrieve_and_emit_bundle(
        RetrievalRequest(query="real query"), selected_ids=["art-0", "art-1"]
    )

    assert isinstance(result.bundle, ContextBundle)
    assert result.bundle.trigger.type == "retrieval"
    assert {item.artifact_id for item in result.bundle.included} == {"art-0", "art-1"}
    assert receipt.event == "created"


def test_candidates_distinct_from_selected():
    from app.retrieval.production_bundle import emit_bundle_from_response

    resp = _response(3)
    result, _ = emit_bundle_from_response(resp, selected_ids=["art-0"])

    candidate_ids = {c["artifact_id"] for c in result.ranked_candidates}
    included_ids = {item.artifact_id for item in result.bundle.included}

    # All ranked candidates are preserved; only the selected one is included.
    assert candidate_ids == {"art-0", "art-1", "art-2"}
    assert included_ids == {"art-0"}
    # Unselected candidates are not silently folded into the selected set.
    assert candidate_ids - included_ids == {"art-1", "art-2"}


def test_emitted_bundle_not_write_authoritative():
    from app.retrieval.production_bundle import emit_bundle_from_response

    resp = _response(2)
    result, _ = emit_bundle_from_response(resp, selected_ids=["art-0"])
    assert result.bundle.authority.may_write is False


def test_emission_records_creation_receipt(monkeypatch):
    import app.retrieval.production_bundle as pb

    real = pb.record_creation_receipt
    calls: dict[str, str] = {}

    def spy(bundle, **kwargs):
        calls["bundle_id"] = bundle.id
        return real(bundle, **kwargs)

    monkeypatch.setattr(pb, "record_creation_receipt", spy)

    resp = _response(2)
    result, receipt = pb.emit_bundle_from_response(resp, selected_ids=["art-0"])

    # The real-vault emission path records a creation receipt for the bundle.
    assert calls.get("bundle_id") == result.bundle.id
    assert receipt.event == "created"
    assert receipt.bundle_id == result.bundle.id


def test_emission_can_preserve_requested_bundle_id():
    from app.retrieval.production_bundle import emit_bundle_from_response

    result, receipt = emit_bundle_from_response(
        _response(2),
        selected_ids=["art-0"],
        bundle_id="cb-requested",
    )

    assert result.bundle.id == "cb-requested"
    assert receipt.bundle_id == "cb-requested"
