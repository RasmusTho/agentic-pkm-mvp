"""Conformance tests for retrieval-emitted ContextBundles (#2359)."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.context_bundles.schema import (
    AuthorityFlags,
    BundleScope,
    BundleTrigger,
    ContextBundle,
    ExpiryPosture,
)
from app.retrieval.bundle_emission import RetrievalBundleResult
from app.retrieval.capability import RetrievalHit, RetrievalResponse
from app.retrieval.context_bundle_conformance import (
    RetrievalContextBundleConformanceError,
    assert_retrieval_context_bundle_conformant,
    validate_retrieval_context_bundle,
)
from app.retrieval.production_bundle import emit_bundle_from_response


def _response() -> RetrievalResponse:
    return RetrievalResponse(
        query="contract query",
        trace_id="trace-contract",
        hits=[
            RetrievalHit(
                object_id="art-1",
                doc_id="doc-engine-1",
                text="engine-local body text",
                score=0.91,
                snippet="engine-local snippet",
                source_ref="vault/source.md",
                payload={"engine": "hybrid", "raw_rank": 1},
            )
        ],
    )


def test_production_retrieval_bundle_conforms_to_context_bundle_contract():
    result, _receipt = emit_bundle_from_response(
        _response(),
        selected_ids=["art-1"],
        scope=BundleScope(project="contract-project", vaults=["vault-alpha"]),
        bundle_id="cb-contract",
    )

    assert validate_retrieval_context_bundle(result) == []
    bundle = result.bundle
    assert bundle.id == "cb-contract"
    assert bundle.trigger.type == "retrieval"
    assert bundle.intended_use == ["answer"]
    assert bundle.scope.project == "contract-project"
    assert bundle.authority.may_write is False
    assert bundle.expiry.reason

    included = bundle.included[0]
    assert included.artifact_id == "art-1"
    assert included.reason
    assert included.source_role == "retrieval_candidate"
    assert included.retrieval_score == pytest.approx(0.91)
    assert included.provenance is not None
    assert included.provenance.origin == "retrieval"


def test_engine_specific_fields_remain_adapter_local_or_diagnostic():
    result, _receipt = emit_bundle_from_response(
        _response(),
        selected_ids=["art-1"],
        bundle_id="cb-diagnostics",
    )

    serialized = result.bundle.model_dump(mode="json")
    assert "doc_id" not in serialized
    assert "payload" not in serialized
    assert "score" not in serialized
    assert result.ranked_candidates == [
        {
            "artifact_id": "art-1",
            "doc_id": "doc-engine-1",
            "score": 0.91,
            "source_ref": "vault/source.md",
        }
    ]
    assert validate_retrieval_context_bundle(result) == []


def test_conformance_check_rejects_write_authority_on_retrieval_bundle():
    result, _receipt = emit_bundle_from_response(
        _response(),
        selected_ids=["art-1"],
        bundle_id="cb-no-write",
    )
    mutated = result.bundle.model_copy(
        update={
            "authority": AuthorityFlags(
                may_answer=True,
                may_orient=False,
                may_resurface=False,
                may_propose=False,
                may_write=True,
            )
        },
        deep=True,
    )

    with pytest.raises(RetrievalContextBundleConformanceError) as exc:
        assert_retrieval_context_bundle_conformant(
            RetrievalBundleResult(
                bundle=mutated,
                ranked_candidates=result.ranked_candidates,
            )
        )

    assert "authority.may_write must remain false" in str(exc.value)


def test_conformance_check_rejects_missing_retrieval_posture():
    malformed = ContextBundle(
        id="cb-malformed",
        created_at=datetime(2026, 6, 21, tzinfo=timezone.utc),
        trigger=BundleTrigger(type="retrieval"),
        intended_use=["answer"],
        scope=BundleScope(),
        authority=AuthorityFlags(may_answer=True, may_write=False),
        expiry=ExpiryPosture(),
    )

    errors = validate_retrieval_context_bundle(
        RetrievalBundleResult(bundle=malformed, ranked_candidates=[])
    )

    assert "expiry.reason must state freshness or uncertainty posture" in errors
