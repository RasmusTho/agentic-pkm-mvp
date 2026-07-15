from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from app.builderops.cli import builderops
from app.builderops.ckm.assess import assess_capabilities, assessment_fingerprint
from app.builderops.ckm.gaps import GapDetectionConfig, detect_gaps
from app.builderops.ckm.models import MATURITY_DIMENSIONS, CkmValidationError
from app.builderops.ckm.store import CkmStore


@pytest.fixture()
def store(tmp_path: Path) -> CkmStore:
    result = CkmStore(tmp_path / "builderops.sqlite3")
    result.ensure_schema()
    result.set_watermark("fixture", "one")
    return result


def _capability(
    store: CkmStore,
    name: str,
    *,
    boundary_ref: str | None = None,
    seed_ref: str | None = None,
    parent_id: str | None = None,
):
    source_ref = seed_ref or f"docs/{name.replace(' ', '_').upper()}.md"
    store.upsert_artifact(
        source_ref=source_ref,
        artifact_kind="document",
        source="fixture",
        watermark=f"wm:{source_ref}",
        provenance=json.dumps(
            {
                "source_ref": source_ref,
                "payload_summary": "Seed taxonomy — State: baseline",
            },
            sort_keys=True,
        ),
    )
    return store.upsert_capability(
        identity_key=f"fixture:gap:{name}",
        name=name,
        definition=f"Fixture capability {name}.",
        existence_provenance=f"seeded:{source_ref} :: fixture",
        lifecycle="confirmed",
        boundary_ref=boundary_ref,
        parent_id=parent_id,
    )


def _edge(
    store: CkmStore,
    capability_id: str,
    *,
    source_ref: str,
    artifact_kind: str,
    evidence_kind: str,
    dimension: str,
    payload_summary: str = "State: current",
):
    artifact = store.upsert_artifact(
        source_ref=source_ref,
        artifact_kind=artifact_kind,
        source="fixture",
        watermark=f"wm:{source_ref}",
        provenance=json.dumps(
            {"source_ref": source_ref, "payload_summary": payload_summary},
            sort_keys=True,
        ),
    )
    edge = store.upsert_evidence_edge(
        artifact_id=artifact.id,
        capability_id=capability_id,
        evidence_kind=evidence_kind,
        polarity="supports",
        maturity_dimension=dimension,
        confidence=1.0,
        extraction_method="deterministic",
        lifecycle="confirmed",
        source_ref=source_ref,
        basis=f"fixture:{source_ref}:{dimension}",
    )
    return artifact, edge


def _citation(artifact, edge) -> dict[str, object]:
    return {
        "edge_id": edge.id,
        "artifact_id": artifact.id,
        "source_ref": artifact.source_ref,
        "edge": edge.to_dict(),
        "artifact": artifact.to_dict(),
    }


def _assessment(
    store: CkmStore,
    capability_id: str,
    scores: dict[str, float],
    citations: dict[str, list[dict[str, object]]],
    *,
    asserted_at: str,
) -> None:
    artifacts = {artifact.id: artifact for artifact in store.list_artifacts()}
    edges = store.list_evidence_edges_for_capability(capability_id)
    store.append_assessment(
        capability_id=capability_id,
        scores=scores,
        citations=citations,
        aggregate=min(scores.values()),
        watermark_set={"fixture": "one"},
        edge_fingerprint=assessment_fingerprint(edges, artifacts),
        asserted_at=asserted_at,
        valid_from=asserted_at,
    )


def _score_map(default: float, **overrides: float) -> dict[str, float]:
    scores = {dimension: default for dimension in MATURITY_DIMENSIONS}
    scores.update(overrides)
    return scores


def _semantic_findings(store: CkmStore) -> list[tuple[object, ...]]:
    return [
        (
            finding.id,
            finding.kind,
            finding.capability_id,
            finding.dimension,
            finding.statement,
            finding.citations,
        )
        for finding in store.list_findings()
    ]


def _three_family_fixture(store: CkmStore) -> dict[str, object]:
    starved = _capability(store, "Starved capability", boundary_ref=None)
    source_artifact, source_edge = _edge(
        store,
        starved.id,
        source_ref="app/starved.py",
        artifact_kind="source_file",
        evidence_kind="source",
        dimension="functional_completeness",
    )
    test_artifact, test_edge = _edge(
        store,
        starved.id,
        source_ref="tests/test_starved.py",
        artifact_kind="test",
        evidence_kind="test",
        dimension="test_completeness",
    )
    starved_citations = {dimension: [] for dimension in MATURITY_DIMENSIONS}
    starved_citations["functional_completeness"] = [_citation(source_artifact, source_edge)]
    starved_citations["test_completeness"] = [_citation(test_artifact, test_edge)]
    _assessment(
        store,
        starved.id,
        _score_map(0.9, test_completeness=0.2),
        starved_citations,
        asserted_at="2026-07-14T10:00:00Z",
    )

    uncovered = _capability(
        store,
        "Uncovered boundary",
        boundary_ref="VOID",
        seed_ref="docs/SYSTEM_BREAKDOWN_STRUCTURE.md",
    )
    _assessment(
        store,
        uncovered.id,
        _score_map(0.0),
        {dimension: [] for dimension in MATURITY_DIMENSIONS},
        asserted_at="2026-07-14T10:00:01Z",
    )

    tension = _capability(store, "Claiming capability", boundary_ref=None)
    claim_artifact, claim_edge = _edge(
        store,
        tension.id,
        source_ref="docs/CLAIMING_CAPABILITY.md",
        artifact_kind="document",
        evidence_kind="doc",
        dimension="documentation_quality",
        payload_summary="Claiming capability — State: delivered",
    )
    tension_citations = {dimension: [] for dimension in MATURITY_DIMENSIONS}
    tension_citations["documentation_quality"] = [_citation(claim_artifact, claim_edge)]
    _assessment(
        store,
        tension.id,
        _score_map(
            0.1,
            functional_completeness=0.2,
            test_completeness=0.9,
        ),
        tension_citations,
        asserted_at="2026-07-14T10:00:02Z",
    )
    return {
        "starved": starved,
        "uncovered": uncovered,
        "tension": tension,
        "claim_artifact": claim_artifact,
    }


def test_findings_name_capability_dimension_and_citation(store: CkmStore) -> None:
    capability = _capability(store, "Enforced finding")
    artifact = store.get_artifact_by_source_ref("docs/ENFORCED_FINDING.md")
    assert artifact is not None

    with pytest.raises(CkmValidationError, match="citation"):
        store.upsert_finding(
            kind="gap",
            capability_id=capability.id,
            dimension="test_completeness",
            statement="Concrete missing-test statement.",
            citations=[],
        )
    with pytest.raises(CkmValidationError, match="evidence edge or artifact"):
        store.upsert_finding(
            kind="gap",
            capability_id=capability.id,
            dimension="test_completeness",
            statement="Concrete missing-test statement.",
            citations=[{"role": "missing_evidence_class", "dimension": "test_completeness"}],
        )

    finding = store.upsert_finding(
        kind="gap",
        capability_id=capability.id,
        dimension="test_completeness",
        statement="Enforced finding has no executable test evidence.",
        citations=[
            {
                "role": "seed_artifact",
                "artifact_id": artifact.id,
                "source_ref": artifact.source_ref,
                "artifact": artifact.to_dict(),
            }
        ],
    )

    assert finding.capability_id == capability.id
    assert finding.dimension == "test_completeness"
    assert finding.statement.startswith("Enforced finding")
    assert finding.citations[0]["artifact_id"] == artifact.id


def test_three_detector_families_on_fixture(store: CkmStore) -> None:
    fixture = _three_family_fixture(store)

    result = detect_gaps(
        store,
        config=GapDetectionConfig(floor=0.5, healthy_floor=0.75, healthy_sibling_count=2),
    )
    findings = store.list_findings()

    assert result.starved_dimensions == 1
    assert result.uncovered_boundaries == 1
    assert result.claim_exceeds_evidence == 1
    assert len(findings) == 3
    assert {
        (finding.kind, finding.capability_id)
        for finding in findings
    } == {
        ("gap", fixture["starved"].id),
        ("gap", fixture["uncovered"].id),
        ("missing_evidence", fixture["tension"].id),
    }


def test_tension_cites_claim_and_missing_class(store: CkmStore) -> None:
    fixture = _three_family_fixture(store)

    detect_gaps(store)
    tension = next(finding for finding in store.list_findings() if finding.kind == "missing_evidence")

    claim_citation = next(
        citation for citation in tension.citations if citation.get("role") == "claiming_artifact"
    )
    missing_class = next(
        citation
        for citation in tension.citations
        if citation.get("role") == "missing_evidence_class"
    )
    assert claim_citation["artifact_id"] == fixture["claim_artifact"].id
    assert claim_citation["artifact"]["source_ref"] == "docs/CLAIMING_CAPABILITY.md"
    assert missing_class == {
        "role": "missing_evidence_class",
        "dimension": "functional_completeness",
        "evidence_kinds": ["pull_request", "source"],
        "observed_edge_count": 0,
    }
    assert "docs/CLAIMING_CAPABILITY.md" in tension.statement
    assert "functional completeness" in tension.statement


def test_regeneration_deterministic(store: CkmStore) -> None:
    _three_family_fixture(store)
    config = GapDetectionConfig(floor=0.5, healthy_floor=0.75, healthy_sibling_count=2)

    first_result = detect_gaps(store, config=config)
    first = _semantic_findings(store)
    second_result = detect_gaps(store, config=config)
    second = _semantic_findings(store)

    assert first_result == second_result
    assert first == second

    cli = CliRunner().invoke(
        builderops,
        ["--db-path", str(store.db_path), "ckm", "gaps"],
    )
    assert cli.exit_code == 0
    assert cli.output.strip() == (
        "3 findings: 1 starved-dimension, 1 uncovered-boundary, "
        "1 claim-exceeds-evidence"
    )


def test_planned_state_does_not_claim_delivery(store: CkmStore) -> None:
    capability = _capability(store, "Planned capability")
    artifact, edge = _edge(
        store,
        capability.id,
        source_ref="docs/PLANNED.md",
        artifact_kind="document",
        evidence_kind="doc",
        dimension="documentation_quality",
        payload_summary="Planned capability — State: target-state / planned",
    )
    citations = {dimension: [] for dimension in MATURITY_DIMENSIONS}
    citations["documentation_quality"] = [_citation(artifact, edge)]
    _assessment(
        store,
        capability.id,
        _score_map(0.1),
        citations,
        asserted_at="2026-07-14T11:00:00Z",
    )

    result = detect_gaps(store)

    assert result.findings == 0
    assert store.list_findings() == []


def test_candidate_source_does_not_cover_boundary(store: CkmStore) -> None:
    capability = _capability(
        store,
        "Candidate-only boundary",
        boundary_ref="CAND",
        seed_ref="docs/SYSTEM_BREAKDOWN_STRUCTURE.md",
    )
    artifact = store.upsert_artifact(
        source_ref="app/candidate.py",
        artifact_kind="source_file",
        source="fixture",
        watermark="wm:candidate",
        provenance='{"source_ref":"app/candidate.py"}',
    )
    store.upsert_evidence_edge(
        artifact_id=artifact.id,
        capability_id=capability.id,
        evidence_kind="source",
        polarity="supports",
        maturity_dimension="functional_completeness",
        confidence=0.8,
        extraction_method="inferred",
        lifecycle="candidate",
        source_ref=artifact.source_ref,
        basis="fixture:candidate-source",
        model="fixture-model",
        provider="fixture-provider",
    )
    _assessment(
        store,
        capability.id,
        _score_map(0.0),
        {dimension: [] for dimension in MATURITY_DIMENSIONS},
        asserted_at="2026-07-14T11:01:00Z",
    )

    result = detect_gaps(store)

    assert result.uncovered_boundaries == 1
    assert store.list_findings()[0].capability_id == capability.id


def test_confirmed_child_source_covers_whole_boundary(store: CkmStore) -> None:
    parent = _capability(
        store,
        "Covered boundary",
        boundary_ref="COV",
        seed_ref="docs/SYSTEM_BREAKDOWN_STRUCTURE.md",
    )
    child = _capability(
        store,
        "Covered child",
        boundary_ref="COV",
        parent_id=parent.id,
    )
    artifact, edge = _edge(
        store,
        child.id,
        source_ref="app/covered.py",
        artifact_kind="source_file",
        evidence_kind="source",
        dimension="functional_completeness",
    )
    for capability in (parent, child):
        citations = {dimension: [] for dimension in MATURITY_DIMENSIONS}
        if capability.id == child.id:
            citations["functional_completeness"] = [_citation(artifact, edge)]
        _assessment(
            store,
            capability.id,
            _score_map(0.0),
            citations,
            asserted_at=f"2026-07-14T11:02:0{int(capability.id == child.id)}Z",
        )

    result = detect_gaps(store)

    assert result.uncovered_boundaries == 0
    assert store.list_findings() == []


def test_stale_assessment_leaves_existing_findings_untouched(store: CkmStore) -> None:
    _three_family_fixture(store)
    detect_gaps(store)
    before = [finding.to_dict() for finding in store.list_findings()]
    artifact = store.get_artifact_by_source_ref("app/starved.py")
    assert artifact is not None
    store.upsert_artifact(
        source_ref=artifact.source_ref,
        artifact_kind=artifact.artifact_kind,
        source=artifact.source,
        watermark="wm:changed",
        provenance=artifact.provenance,
    )

    with pytest.raises(CkmValidationError, match="does not match current evidence"):
        detect_gaps(store)

    assert [finding.to_dict() for finding in store.list_findings()] == before


@pytest.mark.parametrize(
    "state",
    (
        "not live",
        "not shipped",
        "future baseline target",
        "does not claim shipped runtime behavior",
    ),
)
def test_negative_or_future_state_does_not_claim_delivery(
    store: CkmStore,
    state: str,
) -> None:
    capability = _capability(store, "Explicit non-claim")
    artifact, edge = _edge(
        store,
        capability.id,
        source_ref="docs/NON_CLAIM.md",
        artifact_kind="document",
        evidence_kind="doc",
        dimension="documentation_quality",
        payload_summary=f"Explicit non-claim — State: {state}",
    )
    citations = {dimension: [] for dimension in MATURITY_DIMENSIONS}
    citations["documentation_quality"] = [_citation(artifact, edge)]
    _assessment(
        store,
        capability.id,
        _score_map(0.1),
        citations,
        asserted_at="2026-07-14T11:04:00Z",
    )

    result = detect_gaps(store)

    assert result.claim_exceeds_evidence == 0


def test_open_pr_does_not_satisfy_missing_functional_evidence(store: CkmStore) -> None:
    capability = _capability(store, "Open PR claim")
    claim_artifact, claim_edge = _edge(
        store,
        capability.id,
        source_ref="docs/OPEN_PR_CLAIM.md",
        artifact_kind="document",
        evidence_kind="doc",
        dimension="documentation_quality",
        payload_summary="Open PR claim — State: delivered",
    )
    _edge(
        store,
        capability.id,
        source_ref="github:pull_request:9999",
        artifact_kind="pull_request",
        evidence_kind="pull_request",
        dimension="functional_completeness",
        payload_summary="Open PR",
    )
    citations = {dimension: [] for dimension in MATURITY_DIMENSIONS}
    citations["documentation_quality"] = [_citation(claim_artifact, claim_edge)]
    _assessment(
        store,
        capability.id,
        _score_map(0.1, functional_completeness=0.2, test_completeness=0.9),
        citations,
        asserted_at="2026-07-14T11:05:00Z",
    )

    detect_gaps(store)
    tension = next(finding for finding in store.list_findings() if finding.kind == "missing_evidence")
    missing_class = next(
        citation
        for citation in tension.citations
        if citation.get("role") == "missing_evidence_class"
    )

    assert missing_class["observed_edge_count"] == 0


def test_watermark_only_lag_is_recoverable_and_explicit(store: CkmStore) -> None:
    _three_family_fixture(store)
    first = detect_gaps(store)
    store.set_watermark("fixture", "two")

    assessment_run = assess_capabilities(store)
    second = detect_gaps(store)

    assert assessment_run.assessed == 0
    assert assessment_run.skipped == 3
    assert first.findings == second.findings == 3
    assert second.stale_assessments == 3
    assert all(
        any(
            citation.get("role") == "assessment"
            and citation.get("stale_relative_to_global_evidence") is True
            for citation in finding.citations
        )
        for finding in store.list_findings()
    )
