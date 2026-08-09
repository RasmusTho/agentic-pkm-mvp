"""Proof-contract tests for the read-only devUI SoI Evidence View v0 (#4710)."""

from __future__ import annotations

import inspect
import json
from copy import deepcopy
from pathlib import Path

import pytest

from app.builderops.devui_soi_evidence import (
    SoIEvidenceContractError,
    compose_soi_evidence_view,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = REPO_ROOT / "tests/fixtures/soi_evidence/soi_evidence_view_v0_manifest.json"


def _manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def test_manifest_requires_source_owned_refs_and_explicit_relations() -> None:
    manifest = _manifest()
    manifest["claims"][0]["source"].pop("revision")
    with pytest.raises(SoIEvidenceContractError, match="source ownership"):
        compose_soi_evidence_view(manifest)

    manifest = _manifest()
    manifest["unlinked_subject_refs"].pop()
    with pytest.raises(SoIEvidenceContractError, match="explicitly linked or unlinked"):
        compose_soi_evidence_view(manifest)


def test_unowned_relation_remains_unlinked() -> None:
    result = compose_soi_evidence_view(_manifest())
    assert result["relations"] == []
    assert result["unlinked_subject_refs"] == [
        "mimer-product-runtime-soi",
        "finding-reorienting-capability",
        "context-bundles-capability",
        "soi-evidence-view-v0-contract",
    ]
    assert result["denominator"]["status"] == "unknown"
    assert "coverage" not in result["denominator"]


def test_unknown_denominator_does_not_render_partial() -> None:
    result = compose_soi_evidence_view(_manifest())
    assert result["denominator"]["status"] == "unknown"
    assert "coverage" not in result["denominator"]


def test_unknown_denominator_cannot_render_complete() -> None:
    manifest = _manifest()
    manifest["denominator"] = {
        "status": "unknown",
        "horizon": "current",
        "requested_coverage": "complete",
        "limitations": {
            "excluded_subject_refs": [],
            "unknown_subject_refs": ["mimer-product-runtime-capability-denominator"],
            "unread_subject_refs": [],
            "unavailable_subject_refs": [],
            "refused_subject_refs": [],
            "not_applicable_subject_refs": [],
        },
    }
    with pytest.raises(SoIEvidenceContractError, match="complete claim"):
        compose_soi_evidence_view(manifest)


def test_unknown_expected_child_prevents_complete_parent_coverage() -> None:
    manifest = _manifest()
    manifest["denominator"] = {
        "status": "known",
        "scope_ref": "mimer-product-runtime-soi",
        "source": manifest["scope"]["source"],
        "observed_at": "2026-08-09T19:20:04+00:00",
        "expected_subject_refs": ["finding-reorienting-capability"],
        "required_responsibilities": ["delivery"],
        "expected_children": [
            {"subject_ref": "finding-reorienting-capability", "coverage": "unknown"}
        ],
        "horizon": "current",
        "requested_coverage": "complete",
        "limitations": {
            "excluded_subject_refs": [],
            "unknown_subject_refs": ["finding-reorienting-capability"],
            "unread_subject_refs": [],
            "unavailable_subject_refs": [],
            "refused_subject_refs": [],
            "not_applicable_subject_refs": [],
        },
    }
    with pytest.raises(SoIEvidenceContractError, match="complete claim"):
        compose_soi_evidence_view(manifest)


def test_indexed_document_does_not_satisfy_missing_nfr_responsibility() -> None:
    manifest = _manifest()
    nfr_claim = manifest["claims"][1]
    nfr_claim["responsibility"] = "nfr"
    nfr_claim["source_state"]["coverage"] = "missing"
    nfr_claim["evidence"] = {"document_index_coverage": "indexed"}
    manifest["expected_result"]["claims"][1] = deepcopy(nfr_claim)
    result = compose_soi_evidence_view(manifest)
    nfr_claim = next(claim for claim in result["claims"] if claim["responsibility"] == "nfr")
    assert nfr_claim["evidence"]["document_index_coverage"] == "indexed"
    assert nfr_claim["source_state"]["coverage"] == "missing"


def test_target_claim_never_counts_as_current_evidence() -> None:
    result = compose_soi_evidence_view(_manifest())
    assert result["current_claim_ids"] == [
        "finding-current-delivery",
        "context-bundles-current-delivery",
    ]
    assert "soi-evidence-view-target-proof" not in result["current_claim_ids"]


@pytest.mark.parametrize(
    ("availability", "freshness", "coverage"),
    [
        ("unavailable", "fresh", "complete"),
        ("refused", "fresh", "complete"),
        ("available", "stale", "complete"),
        ("available", "fresh", "unread"),
    ],
)
def test_unavailable_refused_stale_or_unread_never_renders_as_zero_or_measured_empty(
    availability: str, freshness: str, coverage: str
) -> None:
    manifest = _manifest()
    state = manifest["claims"][0]["source_state"]
    state.update(
        availability=availability,
        freshness=freshness,
        coverage=coverage,
        cardinality="measured_empty",
    )
    expected_state = manifest["expected_result"]["claims"][0]["source_state"]
    expected_state.update(state)
    expected_state["cardinality"] = "not_measured"
    if availability != "available":
        expected_state["coverage"] = "unread"
    result = compose_soi_evidence_view(manifest)
    rendered = result["claims"][0]["source_state"]
    assert rendered["cardinality"] == "not_measured"
    if availability != "available":
        assert rendered["coverage"] == "unread"
    assert rendered["coverage"] != "missing"


def test_delivery_availability_ready_to_try_trial_and_acceptance_remain_distinct() -> None:
    result = compose_soi_evidence_view(_manifest())
    facts = result["claims"][0]["evidence"]
    assert facts == {
        "delivery": "delivered-docs-specification",
        "availability": "not_asserted",
        "ready_to_try": "not_asserted",
        "owner_tried": "unsupported",
        "owner_accepted": "unsupported",
    }
    manifest = _manifest()
    manifest["claims"][0]["evidence"]["owner_accepted"] = "accepted"
    with pytest.raises(SoIEvidenceContractError, match="owner outcomes"):
        compose_soi_evidence_view(manifest)


def test_claim_linkage_and_expected_result_must_match_the_manifest() -> None:
    manifest = _manifest()
    manifest["claims"][0]["source_state"]["linkage"] = "linked"
    with pytest.raises(SoIEvidenceContractError, match="explicit owned relation"):
        compose_soi_evidence_view(manifest)

    manifest = _manifest()
    manifest["expected_result"]["denominator"]["coverage"] = "complete"
    with pytest.raises(SoIEvidenceContractError, match="expected result"):
        compose_soi_evidence_view(manifest)

    manifest = _manifest()
    manifest["expected_result"]["claims"][2]["horizon"] = "advisory"
    with pytest.raises(SoIEvidenceContractError, match="expected result"):
        compose_soi_evidence_view(manifest)

    manifest = _manifest()
    manifest["expected_result"]["claims"][2]["evidence"]["status_at_source_revision"] = "delivered"
    with pytest.raises(SoIEvidenceContractError, match="expected result"):
        compose_soi_evidence_view(manifest)


def test_aggregate_cannot_control_order_color_scope_priority_or_next_action() -> None:
    manifest = _manifest()
    manifest["diagnostics"]["source_aggregate"] = {
        "maturity": "red",
        "priority": "urgent",
        "next_action": "do-not-use",
    }
    manifest["expected_result"]["diagnostics"] = deepcopy(manifest["diagnostics"])
    result = compose_soi_evidence_view(manifest)
    assert result["diagnostics"] == manifest["diagnostics"]
    assert result["presentation"] == {
        "ordering_basis": "manifest_source_order",
        "aggregate_controls": [],
    }
    assert not {"color", "scope", "priority", "next_action"}.intersection(result["presentation"])


def test_read_has_no_task_graph_lifecycle_registry_or_persistence_write() -> None:
    manifest = _manifest()
    original = deepcopy(manifest)
    first = compose_soi_evidence_view(manifest)
    second = compose_soi_evidence_view(manifest)
    source = inspect.getsource(compose_soi_evidence_view)

    assert manifest == original
    assert first == second
    assert all(
        token not in source
        for token in ("open(", "write", "store", "registry", "lifecycle", "graph", "task")
    )
