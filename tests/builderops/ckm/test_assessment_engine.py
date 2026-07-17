from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from click.testing import CliRunner

from app.builderops.cli import builderops
from app.builderops.ckm import assess as assess_module
from app.builderops.ckm.assess import (
    AGGREGATE_FORMULA_ID,
    FORMULAS,
    Formula,
    assess_capabilities,
    compute_aggregate,
)
from app.builderops.ckm.ingest_repo import iter_docs, iter_schemas, iter_source, iter_tests
from app.builderops.ckm.linkers import link_deterministic
from app.builderops.ckm.models import (
    MATURITY_DIMENSIONS,
    CkmArtifact,
    CkmEvidenceEdge,
)
from app.builderops.ckm.seed import seed_capabilities
from app.builderops.ckm.store import CkmStore

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture()
def store(tmp_path: Path) -> CkmStore:
    result = CkmStore(tmp_path / "builderops.sqlite3")
    result.ensure_schema()
    result.set_watermark("docs", "docs-one")
    result.set_watermark("source", "source-one")
    return result


def _capability(store: CkmStore, name: str = "Retrieval"):
    return store.upsert_capability(
        identity_key=f"fixture:assessment:{name}",
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
        for citation in assessment.citations[dimension]:
            assert CkmEvidenceEdge.from_row(citation["edge"]).validate().id == citation["edge_id"]
            assert CkmArtifact.from_row(citation["artifact"]).validate().id == citation["artifact_id"]


def test_assessment_public_id_survives_real_rebuild_producer(
    store: CkmStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    capability = _capability(store)
    _fully_evidenced(store, capability.id)
    assert assess_capabilities(store).assessed == 1
    first = store.latest_assessment_for_capability(capability.id)
    assert first is not None

    store.rebuild(retained_public_ids=store.active_public_ids())
    store.set_watermark("docs", "docs-one")
    store.set_watermark("source", "source-one")
    rebuilt_capability = _capability(store)
    _fully_evidenced(store, rebuilt_capability.id)
    monkeypatch.setattr("app.builderops.ckm.store.utc_now", lambda: "2099-01-01T00:00:00Z")

    assert assess_capabilities(store).assessed == 1
    rebuilt = store.latest_assessment_for_capability(rebuilt_capability.id)
    assert rebuilt is not None
    assert rebuilt.asserted_at != first.asserted_at
    assert rebuilt.public_id == first.public_id


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


@pytest.mark.parametrize(
    ("dimension", "artifact_kind", "evidence_kind", "source_ref"),
    (
        ("functional_completeness", "source_file", "source", "app/missing.py"),
        ("test_completeness", "test", "test", "tests/test_missing.py"),
        ("documentation_quality", "document", "doc", "docs/STALE.md"),
        ("integration_completeness", "issue", "requirement", "github:issue:dormant"),
        ("operational_readiness", "document", "doc", "docs/OPERATIONS_GAP.md"),
        ("architectural_stability", "adr", "adr", "docs/adr/ADR-GAP.md"),
        ("requirement_coverage", "spec", "spec", "docs/MISSING_SPEC.md"),
    ),
)
def test_published_dimension_formula_inputs_and_weakening(
    store: CkmStore,
    dimension: str,
    artifact_kind: str,
    evidence_kind: str,
    source_ref: str,
) -> None:
    capability = _capability(store)
    _fully_evidenced(store, capability.id)
    assess_capabilities(store)
    baseline = store.latest_assessment_for_capability(capability.id)
    assert baseline is not None
    assert baseline.scores[dimension] == 1.0

    weakening = _edge(
        store,
        capability.id,
        source_ref=source_ref,
        artifact_kind=artifact_kind,
        evidence_kind=evidence_kind,
        dimension=dimension,
        polarity="weakens",
    )
    assess_capabilities(store)
    weakened = store.latest_assessment_for_capability(capability.id)

    assert weakened is not None
    assert 0.0 < weakened.scores[dimension] < baseline.scores[dimension]
    assert weakening.id in {
        citation["edge_id"] for citation in weakened.citations[dimension]
    }


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
    watermark_only_run = assess_capabilities(store)
    assert watermark_only_run.assessed == 0
    assert watermark_only_run.skipped == 1
    assert store.assessment_for_projection(capability.id).stale_relative_to_evidence is True

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


def test_artifact_or_watermark_change_reassesses(store: CkmStore) -> None:
    capability = _capability(store)
    edge = _edge(
        store,
        capability.id,
        source_ref="docs/RETRIEVAL.md",
        artifact_kind="document",
        evidence_kind="doc",
        dimension="documentation_quality",
    )
    first = assess_capabilities(store)

    store.upsert_artifact(
        source_ref="docs/RETRIEVAL.md",
        artifact_kind="document",
        source="fixture",
        watermark="wm:docs-two",
        provenance=json.dumps({"payload_summary": "State: superseded"}),
    )
    store.set_watermark("docs", "docs-two")
    second = assess_capabilities(store)
    history = store.list_assessments_for_capability(capability.id)

    assert edge.artifact_id == store.list_artifacts()[0].id
    assert first.assessed == 1
    assert second.assessed == 1
    assert len(history) == 2
    assert history[0].edge_fingerprint != history[1].edge_fingerprint
    assert store.assessment_for_projection(capability.id).stale_relative_to_evidence is False


def test_equal_scores_with_replaced_evidence_append_distinct_assessments(
    store: CkmStore,
) -> None:
    capability = _capability(store)
    first_edge = _edge(
        store,
        capability.id,
        source_ref="docs/FIRST.md",
        artifact_kind="document",
        evidence_kind="doc",
        dimension="documentation_quality",
    )
    assert assess_capabilities(store).assessed == 1
    first = store.latest_assessment_for_capability(capability.id)
    assert first is not None

    store.delete_evidence_edge(first_edge.id)
    _edge(
        store,
        capability.id,
        source_ref="docs/SECOND.md",
        artifact_kind="document",
        evidence_kind="doc",
        dimension="documentation_quality",
    )
    assert assess_capabilities(store).assessed == 1
    history = store.list_assessments_for_capability(capability.id)

    assert len(history) == 2
    assert history[0].scores == history[1].scores
    assert history[0].public_id != history[1].public_id
    assert history[0].edge_fingerprint != history[1].edge_fingerprint


def test_historical_citations_survive_edge_change_and_artifact_cleanup(
    store: CkmStore,
) -> None:
    capability = _capability(store)
    edge = _edge(
        store,
        capability.id,
        source_ref="app/retrieval.py",
        artifact_kind="source_file",
        evidence_kind="source",
        dimension="functional_completeness",
    )
    assess_capabilities(store)
    first = store.latest_assessment_for_capability(capability.id)
    assert first is not None
    first_citation = first.citations["functional_completeness"][0]

    store.upsert_evidence_edge(
        artifact_id=edge.artifact_id,
        capability_id=edge.capability_id,
        evidence_kind=edge.evidence_kind,
        polarity=edge.polarity,
        maturity_dimension=edge.maturity_dimension,
        confidence=0.25,
        extraction_method=edge.extraction_method,
        lifecycle=edge.lifecycle,
        source_ref=edge.source_ref,
        basis=edge.basis,
    )
    assess_capabilities(store)
    second = store.latest_assessment_for_capability(capability.id)
    assert second is not None
    second_citation = second.citations["functional_completeness"][0]

    assert first_citation["edge"]["confidence"] == 1.0
    assert second_citation["edge"]["confidence"] == 0.25
    assert first_citation["artifact"]["provenance"] == "{}"
    assert store.delete_artifacts_not_in("fixture", set()) == 1
    assess_capabilities(store)

    history = store.list_assessments_for_capability(capability.id)
    assert len(history) == 3
    for assessment in history[:2]:
        citation = assessment.citations["functional_completeness"][0]
        assert store.get_evidence_edge_by_id(citation["edge_id"]) is not None
        assert CkmEvidenceEdge.from_row(citation["edge"]).validate()
        assert CkmArtifact.from_row(citation["artifact"]).validate()
    assert store.list_evidence_edges() == []
    assert store.list_artifacts() == []


def test_formula_version_change_reassesses(store: CkmStore, monkeypatch: pytest.MonkeyPatch) -> None:
    capability = _capability(store)
    _fully_evidenced(store, capability.id)
    first = assess_capabilities(store)

    formula_id = "functional-evidence-balance-v2"
    monkeypatch.setitem(
        FORMULAS,
        formula_id,
        Formula(
            formula_id,
            "functional_completeness",
            "Fixture version change with the same inputs.",
        ),
    )
    monkeypatch.setitem(
        assess_module._DIMENSION_FORMULA_IDS,
        "functional_completeness",
        formula_id,
    )
    second = assess_capabilities(store)
    history = store.list_assessments_for_capability(capability.id)

    assert first.assessed == 1
    assert second.assessed == 1
    assert len(history) == 2
    assert history[0].edge_fingerprint != history[1].edge_fingerprint
    assert history[1].formula_ids["functional_completeness"] == formula_id


def test_integration_weakening_edge_reduces_score_and_is_cited(store: CkmStore) -> None:
    capability = _capability(store)
    _edge(
        store,
        capability.id,
        source_ref="app/retrieval.py",
        artifact_kind="source_file",
        evidence_kind="source",
        dimension="functional_completeness",
    )
    _edge(
        store,
        capability.id,
        source_ref="docs/SURFACE.md",
        artifact_kind="document",
        evidence_kind="doc",
        dimension="integration_completeness",
    )
    weakening = _edge(
        store,
        capability.id,
        source_ref="github:issue:built-but-dormant",
        artifact_kind="issue",
        evidence_kind="requirement",
        dimension="integration_completeness",
        polarity="weakens",
    )

    assess_capabilities(store)
    assessment = store.latest_assessment_for_capability(capability.id)

    assert assessment is not None
    assert assessment.scores["integration_completeness"] == pytest.approx(2 / 3)
    assert weakening.id in {
        citation["edge_id"] for citation in assessment.citations["integration_completeness"]
    }


def test_functional_completeness_counts_only_merged_pull_requests(store: CkmStore) -> None:
    capability = _capability(store)
    _edge(
        store,
        capability.id,
        source_ref="docs/SPEC.md",
        artifact_kind="spec",
        evidence_kind="spec",
        dimension="requirement_coverage",
    )
    pull = store.upsert_artifact(
        source_ref="github:pull:1",
        artifact_kind="pull_request",
        source="fixture",
        watermark="open",
        provenance=json.dumps({"merged_at": None}),
    )
    store.upsert_evidence_edge(
        artifact_id=pull.id,
        capability_id=capability.id,
        evidence_kind="pull_request",
        polarity="supports",
        maturity_dimension="functional_completeness",
        confidence=1.0,
        extraction_method="deterministic",
        lifecycle="confirmed",
        source_ref=pull.source_ref,
        basis="fixture:pull",
    )

    assess_capabilities(store)
    open_assessment = store.latest_assessment_for_capability(capability.id)
    assert open_assessment is not None
    assert open_assessment.scores["functional_completeness"] == 0.0

    store.upsert_artifact(
        source_ref=pull.source_ref,
        artifact_kind="pull_request",
        source="fixture",
        watermark="merged",
        provenance=json.dumps({"merged_at": "2026-07-14T00:00:00Z"}),
    )
    assess_capabilities(store)
    merged_assessment = store.latest_assessment_for_capability(capability.id)
    assert merged_assessment is not None
    assert merged_assessment.scores["functional_completeness"] == 1.0


def test_architectural_stability_treats_commits_as_churn_only(store: CkmStore) -> None:
    capability = _capability(store)
    _edge(
        store,
        capability.id,
        source_ref="docs/adr/ADR-9000.md",
        artifact_kind="adr",
        evidence_kind="adr",
        dimension="architectural_stability",
    )
    assess_capabilities(store)
    baseline = store.latest_assessment_for_capability(capability.id)
    assert baseline is not None
    assert baseline.scores["architectural_stability"] == 1.0

    for index, expected in ((1, 0.5), (2, 1 / 3)):
        _edge(
            store,
            capability.id,
            source_ref=f"git:commit-{index}",
            artifact_kind="commit",
            evidence_kind="commit",
            dimension="architectural_stability",
        )
        assess_capabilities(store)
        assessment = store.latest_assessment_for_capability(capability.id)
        assert assessment is not None
        assert assessment.scores["architectural_stability"] == pytest.approx(expected)


def test_schema_v2_assessment_migrates_with_legacy_formula_provenance(tmp_path: Path) -> None:
    db_path = tmp_path / "builderops.sqlite3"
    store = CkmStore(db_path)
    store.ensure_schema()
    capability = _capability(store)
    citations = json.dumps([])
    scores = {dimension: 0.25 for dimension in MATURITY_DIMENSIONS}
    with sqlite3.connect(db_path) as conn:
        conn.execute("DROP TABLE ckm_assessment")
        dimension_columns = ",\n".join(
            f"{dimension} REAL NOT NULL, {dimension}_citations TEXT NOT NULL"
            for dimension in MATURITY_DIMENSIONS
        )
        conn.execute(
            f"""
            CREATE TABLE ckm_assessment (
                id TEXT PRIMARY KEY,
                capability_id TEXT NOT NULL REFERENCES ckm_capability(id),
                {dimension_columns},
                aggregate REAL NOT NULL,
                watermark_set TEXT NOT NULL,
                valid_from TEXT NOT NULL,
                asserted_at TEXT NOT NULL
            )
            """
        )
        columns = ["id", "capability_id"]
        values: list[object] = ["assessment-v2", capability.id]
        for dimension in MATURITY_DIMENSIONS:
            columns.extend((dimension, f"{dimension}_citations"))
            values.extend((scores[dimension], citations))
        columns.extend(("aggregate", "watermark_set", "valid_from", "asserted_at"))
        values.extend((0.25, json.dumps({"docs": "one"}), "2026-01-01", "2026-01-01"))
        conn.execute(
            f"INSERT INTO ckm_assessment ({','.join(columns)}) VALUES ({','.join('?' for _ in values)})",
            values,
        )
        conn.execute("DROP TABLE ckm_identity_successor")
        conn.execute("DROP TABLE ckm_public_identity")
        conn.execute("DROP TABLE ckm_state")

    store.ensure_schema()
    migrated = store.latest_assessment_for_capability(capability.id)

    assert migrated is not None
    assert migrated.id == "assessment-v2"
    assert dict(migrated.scores) == scores
    assert all(migrated.citations[dimension] == [] for dimension in MATURITY_DIMENSIONS)
    assert migrated.aggregate == 0.25
    assert set(migrated.formula_ids.values()) == {"legacy-pre-ckm07"}
    assert migrated.aggregate_formula_id == "legacy-pre-ckm07"
    assert set(migrated.candidate_shares.values()) == {0.0}
    assert migrated.low_confidence is False
    assert migrated.edge_fingerprint == "legacy"
    assert dict(migrated.watermark_set) == {"docs": "one"}
    assert migrated.valid_from == "2026-01-01"
    assert migrated.asserted_at == "2026-01-01"

    store.ensure_schema()
    assert store.latest_assessment_for_capability(capability.id) == migrated


def test_live_retrieval_outscores_planned_context(tmp_path: Path) -> None:
    store = CkmStore(tmp_path / "builderops.sqlite3")
    store.ensure_schema()
    seed_capabilities(store, repo_root=REPO_ROOT)
    for artifact in (*iter_docs(REPO_ROOT), *iter_tests(REPO_ROOT), *iter_source(REPO_ROOT), *iter_schemas(REPO_ROOT)):
        store.upsert_artifact(
            source_ref=artifact.natural_key,
            artifact_kind=artifact.artifact_kind,
            source=artifact.source,
            watermark=artifact.source_watermark,
            provenance=artifact.provenance,
        )
    store.set_watermark("repo", "live-fixture")
    link_deterministic(store, REPO_ROOT)

    assess_capabilities(store)
    capabilities = {item.name: item for item in store.list_capabilities()}
    retrieval = store.latest_assessment_for_capability(capabilities["Retrieval"].id)
    context = store.latest_assessment_for_capability(capabilities["Context building"].id)

    assert retrieval is not None
    assert context is not None
    assert retrieval.scores["functional_completeness"] > context.scores["functional_completeness"]
    artifacts = {item.id: item for item in store.list_artifacts()}
    retrieval_sources = {
        artifacts[citation["artifact_id"]].source_ref
        for citation in retrieval.citations["functional_completeness"]
        if artifacts[citation["artifact_id"]].artifact_kind == "source_file"
    }
    context_sources = {
        artifacts[citation["artifact_id"]].source_ref
        for citation in context.citations["functional_completeness"]
        if artifacts[citation["artifact_id"]].artifact_kind == "source_file"
    }
    assert "app/retrieval/capability.py" in retrieval_sources
    assert "app/retrieval/capability.py" not in context_sources


def test_assessment_has_no_capability_name_or_lifecycle_prior(store: CkmStore) -> None:
    first = _capability(store, "Retrieval")
    second = store.upsert_capability(
        identity_key="fixture:assessment:planned-neutral-twin",
        name="Planned neutral twin",
        definition=first.definition,
        existence_provenance="fixture:neutral",
        lifecycle="candidate",
        boundary_ref=first.boundary_ref,
    )
    fixtures = (
        ("app/shared.py", "source_file", "source", "functional_completeness"),
        ("tests/test_shared.py", "test", "test", "test_completeness"),
        ("docs/SHARED.md", "document", "doc", "documentation_quality"),
        ("docs/SURFACE_SHARED.md", "document", "doc", "integration_completeness"),
        ("docs/OPERATIONS_SHARED.md", "document", "doc", "operational_readiness"),
        ("docs/adr/ADR-SHARED.md", "adr", "adr", "architectural_stability"),
        ("docs/SPEC_SHARED.md", "spec", "spec", "requirement_coverage"),
    )
    for capability in (first, second):
        for source_ref, artifact_kind, evidence_kind, dimension in fixtures:
            _edge(
                store,
                capability.id,
                source_ref=source_ref,
                artifact_kind=artifact_kind,
                evidence_kind=evidence_kind,
                dimension=dimension,
                basis=f"fixture:{source_ref}:{dimension}",
            )

    assess_capabilities(store)
    first_assessment = store.latest_assessment_for_capability(first.id)
    second_assessment = store.latest_assessment_for_capability(second.id)
    assert first_assessment is not None
    assert second_assessment is not None
    assert dict(first_assessment.scores) == dict(second_assessment.scores)


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
