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
    ]


def test_unknown_denominator_cannot_render_complete() -> None:
    manifest = _manifest()
    manifest["denominator"] = {
        "status": "unknown",
        "horizon": "current",
        "requested_coverage": "complete",
    }
    with pytest.raises(SoIEvidenceContractError, match="complete claim"):
        compose_soi_evidence_view(manifest)


def test_unknown_expected_child_prevents_complete_parent_coverage() -> None:
    manifest = _manifest()
    manifest["denominator"]["expected_children"][1]["coverage"] = "unknown"
    with pytest.raises(SoIEvidenceContractError, match="complete claim"):
        compose_soi_evidence_view(manifest)


def test_indexed_document_does_not_satisfy_missing_nfr_responsibility() -> None:
    result = compose_soi_evidence_view(_manifest())
    nfr_claim = next(claim for claim in result["claims"] if claim["responsibility"] == "nfr")
    assert nfr_claim["evidence"]["document_index_coverage"] == "indexed"
    assert nfr_claim["source_state"]["coverage"] == "missing"


def test_target_claim_never_counts_as_current_evidence() -> None:
    result = compose_soi_evidence_view(_manifest())
    assert result["current_claim_ids"] == ["finding-current-delivery"]
    assert "context-bundles-target-nfr" not in result["current_claim_ids"]


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
    result = compose_soi_evidence_view(manifest)
    assert result["claims"][0]["source_state"]["cardinality"] == "not_measured"


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


def test_aggregate_cannot_control_order_color_scope_priority_or_next_action() -> None:
    manifest = _manifest()
    manifest["diagnostics"]["source_aggregate"] = {
        "maturity": "red",
        "priority": "urgent",
        "next_action": "do-not-use",
    }
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
