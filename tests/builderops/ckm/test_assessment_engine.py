from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from app.builderops.cli import builderops
from app.builderops.ckm.assess import (
    AGGREGATE_FORMULA_ID,
    FORMULAS,
    assess_capabilities,
    compute_aggregate,
)
from app.builderops.ckm.models import MATURITY_DIMENSIONS
from app.builderops.ckm.store import CkmStore


@pytest.fixture()
def store(tmp_path: Path) -> CkmStore:
    result = CkmStore(tmp_path / "builderops.sqlite3")
    result.ensure_schema()
    result.set_watermark("docs", "docs-one")
    result.set_watermark("source", "source-one")
    return result


def _capability(store: CkmStore, name: str = "Retrieval"):
    return store.upsert_capability(
        name=name,
        definition="Retrieve grounded context.",
        existence_provenance="seeded:docs/CAPABILITY_CONTRACT_MODEL.md :: Retrieval",
        lifecycle="confirmed",
        boundary_ref="RCA",
    )


def _edge(
    store: CkmStore,
    capability_id: str,
    *,
    source_ref: str,
    artifact_kind: str,
    evidence_kind: str,
    dimension: str,
    lifecycle: str = "confirmed",
    polarity: str = "supports",
    basis: str | None = None,
):
    artifact = store.upsert_artifact(
        source_ref=source_ref,
        artifact_kind=artifact_kind,
        source="fixture",
        watermark=f"wm:{source_ref}",
        provenance=(
            '{"payload_summary":"State: current"}'
            if artifact_kind in {"document", "adr", "spec"}
            else "{}"
        ),
    )
    return store.upsert_evidence_edge(
        artifact_id=artifact.id,
        capability_id=capability_id,
        evidence_kind=evidence_kind,
        polarity=polarity,
        maturity_dimension=dimension,
        confidence=1.0,
        extraction_method="deterministic" if lifecycle == "confirmed" else "inferred",
        lifecycle=lifecycle,
        source_ref=source_ref,
        basis=basis or f"fixture:{source_ref}:{dimension}",
        model=None if lifecycle == "confirmed" else "fixture-model",
        provider=None if lifecycle == "confirmed" else "fixture-provider",
    )


def _fully_evidenced(store: CkmStore, capability_id: str) -> None:
    fixtures = (
        ("app/retrieval.py", "source_file", "source", "functional_completeness"),
        ("tests/test_retrieval.py", "test", "test", "test_completeness"),
        ("docs/RETRIEVAL.md", "document", "doc", "documentation_quality"),
        ("docs/SURFACE.md", "document", "doc", "integration_completeness"),
        ("docs/OPERATIONS.md", "document", "doc", "operational_readiness"),
        ("docs/adr/ADR-9000.md", "adr", "adr", "architectural_stability"),
        ("docs/SPEC.md", "spec", "spec", "requirement_coverage"),
    )
    for source_ref, artifact_kind, evidence_kind, dimension in fixtures:
        _edge(
            store,
            capability_id,
            source_ref=source_ref,
            artifact_kind=artifact_kind,
            evidence_kind=evidence_kind,
            dimension=dimension,
        )


def test_every_dimension_cites_evidence(store: CkmStore) -> None:
    capability = _capability(store)
    _fully_evidenced(store, capability.id)

    run = assess_capabilities(store)
    assessment = store.latest_assessment_for_capability(capability.id)

    assert run.assessed == 1
    assert assessment is not None
    assert set(assessment.scores) == set(MATURITY_DIMENSIONS)
    assert set(assessment.citations) == set(MATURITY_DIMENSIONS)
    assert set(assessment.formula_ids) == set(MATURITY_DIMENSIONS)
    assert all(formula_id in FORMULAS for formula_id in assessment.formula_ids.values())
    edge_ids = {edge.id for edge in store.list_evidence_edges()}
    for dimension in MATURITY_DIMENSIONS:
        assert isinstance(assessment.citations[dimension], list)
        assert all(citation["edge_id"] in edge_ids for citation in assessment.citations[dimension])


def test_aggregate_transparent_and_min_capped(store: CkmStore) -> None:
    capability = _capability(store)
    _fully_evidenced(store, capability.id)
    # Remove the sole operational edge so this dimension is transparently starved.
    operational = next(
        edge
        for edge in store.list_evidence_edges()
        if edge.maturity_dimension == "operational_readiness"
    )
    store.delete_evidence_edge(operational.id)

    assess_capabilities(store)
    assessment = store.latest_assessment_for_capability(capability.id)

    assert assessment is not None
    assert assessment.scores["operational_readiness"] == 0.0
    assert assessment.aggregate == compute_aggregate(assessment.scores)
    assert assessment.aggregate <= assessment.scores["operational_readiness"]
    assert assessment.aggregate_formula_id == AGGREGATE_FORMULA_ID
    assert assessment.aggregate_formula_id in FORMULAS


def test_candidate_share_and_low_confidence_flag(store: CkmStore) -> None:
    capability = _capability(store)
    for index, lifecycle in enumerate(("candidate", "candidate", "confirmed"), 1):
        _edge(
            store,
            capability.id,
            source_ref=f"tests/test_candidate_{index}.py",
            artifact_kind="test",
            evidence_kind="test",
            dimension="test_completeness",
            lifecycle=lifecycle,
        )

    assess_capabilities(store)
    assessment = store.latest_assessment_for_capability(capability.id)

    assert assessment is not None
    assert assessment.candidate_shares["test_completeness"] == pytest.approx(2 / 3)
    assert assessment.low_confidence is True


def test_staleness_detectable_from_projection_read_path(store: CkmStore) -> None:
    capability = _capability(store)
    _edge(
        store,
        capability.id,
        source_ref="app/retrieval.py",
        artifact_kind="source_file",
        evidence_kind="source",
        dimension="functional_completeness",
    )
    first_run = assess_capabilities(store)
    first = store.latest_assessment_for_capability(capability.id)
    assert first_run.assessed == 1
    assert first is not None
    assert store.assessment_for_projection(capability.id).stale_relative_to_evidence is False

    store.set_watermark("source", "source-two")
    stale = store.assessment_for_projection(capability.id)
    assert stale.assessment.id == first.id
    assert stale.stale_relative_to_evidence is True

    _edge(
        store,
        capability.id,
        source_ref="tests/test_retrieval.py",
        artifact_kind="test",
        evidence_kind="test",
        dimension="test_completeness",
    )
    second_run = assess_capabilities(store)
    history = store.list_assessments_for_capability(capability.id)
    assert second_run.assessed == 1
    assert len(history) == 2
    assert history[0].id == first.id
    assert store.assessment_for_projection(capability.id).stale_relative_to_evidence is False


def test_incremental_skip_unchanged(store: CkmStore) -> None:
    capability = _capability(store)
    _edge(
        store,
        capability.id,
        source_ref="app/retrieval.py",
        artifact_kind="source_file",
        evidence_kind="source",
        dimension="functional_completeness",
    )

    first = assess_capabilities(store)
    assessment = store.latest_assessment_for_capability(capability.id)
    second = assess_capabilities(store)

    assert first.assessed == 1
    assert second.assessed == 0
    assert second.skipped == 1
    assert [item.id for item in store.list_assessments_for_capability(capability.id)] == [
        assessment.id
    ]


def test_cli_assess_reports_assessed_and_skipped(tmp_path: Path) -> None:
    db_path = tmp_path / "builderops.sqlite3"
    store = CkmStore(db_path)
    store.ensure_schema()
    store.set_watermark("docs", "docs-one")
    _capability(store)

    runner = CliRunner()
    first = runner.invoke(builderops, ["--db-path", str(db_path), "ckm", "assess"])
    second = runner.invoke(builderops, ["--db-path", str(db_path), "ckm", "assess"])

    assert first.exit_code == 0, first.output
    assert "assessed 1 capabilities (0 unchanged, skipped)" in first.output
    assert second.exit_code == 0, second.output
    assert "assessed 0 capabilities (1 unchanged, skipped)" in second.output
