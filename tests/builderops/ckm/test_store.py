from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.builderops.ckm.models import MATURITY_DIMENSIONS, CkmValidationError
from app.builderops.ckm.schema import CKM_TABLE_NAMES
from app.builderops.ckm.store import CkmStore
from app.builderops.store import SqliteBuilderOpsStore


@pytest.fixture()
def store(tmp_path: Path) -> CkmStore:
    s = CkmStore(tmp_path / "builderops.sqlite3")
    s.ensure_schema()
    return s


def _upsert_capability(store: CkmStore, name: str = "semantic-search"):
    return store.upsert_capability(
        name=name,
        definition="Retrieve relevant vault content by meaning, not keyword.",
        existence_provenance="docs/CAPABILITY_CONTRACT_MODEL.md#semantic-search",
    )


def _upsert_artifact(store: CkmStore, source_ref: str = "docs/adr/ADR-0059.md"):
    return store.upsert_artifact(
        source_ref=source_ref,
        artifact_kind="adr",
        source="repo_artifact_ingestion",
        watermark="commit:abc123",
        provenance="repo:agentic-pkm-mvp@abc123",
    )


def _upsert_evidence_edge(store: CkmStore, artifact_id: str, capability_id: str):
    return store.upsert_evidence_edge(
        artifact_id=artifact_id,
        capability_id=capability_id,
        evidence_kind="adr",
        polarity="supports",
        maturity_dimension="requirement_coverage",
        confidence=0.9,
        extraction_method="deterministic",
        lifecycle="confirmed",
        source_ref="docs/adr/ADR-0059.md",
    )


def _assessment_scores_and_citations(citation_ref: str = "docs/adr/ADR-0059.md"):
    scores = {dimension: 0.5 for dimension in MATURITY_DIMENSIONS}
    citations = {
        dimension: [{"ref_type": "repo_doc", "ref": citation_ref}] for dimension in MATURITY_DIMENSIONS
    }
    return scores, citations


# --- AC: upsert idempotency + rebuild ----------------------------------------


def test_upsert_idempotent_and_rebuild(store: CkmStore) -> None:
    first = _upsert_capability(store)
    second = _upsert_capability(store)
    assert first.id == second.id
    assert len(store.list_capabilities()) == 1

    artifact_first = _upsert_artifact(store)
    artifact_second = _upsert_artifact(store)
    assert artifact_first.id == artifact_second.id
    assert len(store.list_artifacts()) == 1

    edge_first = _upsert_evidence_edge(store, artifact_first.id, first.id)
    edge_second = _upsert_evidence_edge(store, artifact_first.id, first.id)
    assert edge_first.id == edge_second.id
    assert len(store.list_evidence_edges_for_capability(first.id)) == 1
    with sqlite3.connect(store.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM ckm_evidence_edge_history").fetchone()[0] == 0

    assert store.table_names() == sorted(CKM_TABLE_NAMES)

    store.rebuild()

    assert store.table_names() == sorted(CKM_TABLE_NAMES)
    assert store.list_capabilities() == []
    assert store.list_artifacts() == []


def test_schema_migrates_edge_basis_without_losing_rows(tmp_path: Path) -> None:
    store = CkmStore(tmp_path / "builderops.sqlite3")
    store.ensure_schema()
    capability = _upsert_capability(store)
    artifact = _upsert_artifact(store)
    with sqlite3.connect(store.db_path) as conn:
        conn.execute("DROP TABLE ckm_evidence_edge")
        conn.execute(
            """
            CREATE TABLE ckm_evidence_edge (
                id TEXT PRIMARY KEY,
                artifact_id TEXT NOT NULL REFERENCES ckm_artifact(id),
                capability_id TEXT NOT NULL REFERENCES ckm_capability(id),
                evidence_kind TEXT NOT NULL,
                polarity TEXT NOT NULL,
                maturity_dimension TEXT NOT NULL,
                confidence REAL NOT NULL,
                extraction_method TEXT NOT NULL,
                model TEXT,
                provider TEXT,
                lifecycle TEXT NOT NULL,
                source_ref TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE (artifact_id, capability_id, evidence_kind, maturity_dimension)
            )
            """
        )
        conn.execute(
            """
            INSERT INTO ckm_evidence_edge VALUES
            (?, ?, ?, 'adr', 'supports', 'requirement_coverage', 0.9,
             'deterministic', NULL, NULL, 'confirmed', ?, 't', 't')
            """,
            ("edge_legacy", artifact.id, capability.id, artifact.source_ref),
        )
        conn.execute(
            """
            INSERT INTO ckm_evidence_edge VALUES
            (?, ?, ?, 'doc', 'supports', 'documentation_quality', 0.8,
             'deterministic', NULL, NULL, 'confirmed', ?, 't', 't')
            """,
            ("edge_legacy_second", artifact.id, capability.id, artifact.source_ref),
        )
        conn.commit()

    store.ensure_schema()

    edges = store.list_evidence_edges()
    assert {edge.id for edge in edges} == {"edge_legacy", "edge_legacy_second"}
    assert len({edge.basis for edge in edges}) == 2
    assert all(edge.source_ref == artifact.source_ref for edge in edges)
    with sqlite3.connect(store.db_path) as conn:
        indexes = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'ckm_evidence_edge'"
            )
        }
    assert {"idx_ckm_evidence_edge_capability", "idx_ckm_evidence_edge_artifact"} <= indexes


# --- AC: provenance-bearing NOT NULL columns ---------------------------------


def test_provenance_columns_required(tmp_path: Path) -> None:
    store = CkmStore(tmp_path / "builderops.sqlite3")
    store.ensure_schema()

    with sqlite3.connect(store.db_path) as conn:
        # ckm_capability.existence_provenance is the provenance column.
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO ckm_capability
                    (id, name, definition, lifecycle, created_at, updated_at)
                VALUES ('cap_x', 'x', 'def', 'candidate', 't', 't')
                """
            )

        # ckm_artifact.provenance.
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO ckm_artifact
                    (id, source_ref, artifact_kind, source, watermark, created_at, updated_at)
                VALUES ('art_x', 'ref', 'adr', 'src', 'wm', 't', 't')
                """
            )

        # ckm_evidence_edge.extraction_method (extraction method NOT NULL) and source_ref.
        conn.execute(
            """
            INSERT INTO ckm_capability
                (id, public_id, identity_key, name, definition, lifecycle,
                 existence_provenance, created_at, updated_at)
            VALUES ('cap_y', 'pub_cap_y', 'fixture:cap_y', 'y', 'def', 'candidate',
                    'prov', 't', 't')
            """
        )
        conn.execute(
            """
            INSERT INTO ckm_artifact
                (id, public_id, source_ref, artifact_kind, source, watermark, provenance,
                 created_at, updated_at)
            VALUES ('art_y', 'pub_art_y', 'ref_y', 'adr', 'src', 'wm', 'prov', 't', 't')
            """
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO ckm_evidence_edge
                    (id, artifact_id, capability_id, evidence_kind, polarity,
                     maturity_dimension, confidence, lifecycle, source_ref, created_at, updated_at)
                VALUES ('edge_x', 'art_y', 'cap_y', 'adr', 'supports',
                        'requirement_coverage', 0.5, 'confirmed', 'ref', 't', 't')
                """
            )

        # ckm_assessment.watermark_set.
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO ckm_assessment
                    (id, capability_id,
                     functional_completeness, functional_completeness_citations,
                     test_completeness, test_completeness_citations,
                     documentation_quality, documentation_quality_citations,
                     integration_completeness, integration_completeness_citations,
                     operational_readiness, operational_readiness_citations,
                     architectural_stability, architectural_stability_citations,
                     requirement_coverage, requirement_coverage_citations,
                     aggregate, valid_from, asserted_at)
                VALUES ('assess_x', 'cap_y',
                        0.5, '[]', 0.5, '[]', 0.5, '[]', 0.5, '[]',
                        0.5, '[]', 0.5, '[]', 0.5, '[]',
                        0.5, 't', 't')
                """
            )

        # ckm_finding.citations.
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO ckm_finding
                    (id, kind, capability_id, dimension, statement, created_at, updated_at)
                VALUES ('find_x', 'gap', 'cap_y', 'requirement_coverage', 'no tests', 't', 't')
                """
            )


# --- AC: assessments are append-only and bitemporal --------------------------


def test_assessment_append_only_bitemporal(store: CkmStore) -> None:
    capability = _upsert_capability(store)
    scores, citations = _assessment_scores_and_citations()

    first = store.append_assessment(
        capability_id=capability.id,
        scores=scores,
        citations=citations,
        aggregate=0.5,
        watermark_set={"repo_artifact_ingestion": "commit:abc123"},
        valid_from="2026-07-01T00:00:00Z",
        asserted_at="2026-07-01T00:00:00Z",
    )

    later_scores = {dimension: 0.9 for dimension in MATURITY_DIMENSIONS}
    second = store.append_assessment(
        capability_id=capability.id,
        scores=later_scores,
        citations=citations,
        aggregate=0.9,
        watermark_set={"repo_artifact_ingestion": "commit:def456"},
        valid_from="2026-07-08T00:00:00Z",
        asserted_at="2026-07-08T00:00:00Z",
    )

    assert first.id != second.id

    history = store.list_assessments_for_capability(capability.id)
    assert [a.id for a in history] == [first.id, second.id]
    assert [a.asserted_at for a in history] == ["2026-07-01T00:00:00Z", "2026-07-08T00:00:00Z"]

    # The first assessment's values are preserved, not overwritten in place.
    preserved_first = history[0]
    assert preserved_first.scores["functional_completeness"] == 0.5
    assert history[1].scores["functional_completeness"] == 0.9

    latest = store.latest_assessment_for_capability(capability.id)
    assert latest.id == second.id


def test_append_assessment_requires_all_dimension_citations(store: CkmStore) -> None:
    capability = _upsert_capability(store)
    scores = {dimension: 0.5 for dimension in MATURITY_DIMENSIONS}
    incomplete_citations = {MATURITY_DIMENSIONS[0]: [{"ref_type": "repo_doc", "ref": "x"}]}

    with pytest.raises(CkmValidationError):
        store.append_assessment(
            capability_id=capability.id,
            scores=scores,
            citations=incomplete_citations,
            aggregate=0.5,
            watermark_set={"repo_artifact_ingestion": "commit:abc123"},
        )


# --- AC: schema creation/rebuild emits a BuilderOps receipt -------------------


def test_schema_events_emit_receipt(tmp_path: Path) -> None:
    db_path = tmp_path / "builderops.sqlite3"
    store = CkmStore(db_path)

    ensure_response = store.ensure_schema()
    rebuild_response = store.rebuild()

    assert ensure_response["event_type"] == "ckm_schema_ensured"
    assert rebuild_response["event_type"] == "ckm_schema_rebuilt"

    receipts = SqliteBuilderOpsStore(db_path).list_records("BuilderOpsReceipt")
    event_types = {r["event_type"] for r in receipts}
    assert {"ckm_schema_ensured", "ckm_schema_rebuilt"} <= event_types


def test_open_default_uses_builderops_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BUILDEROPS_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.delenv("BUILDEROPS_DB_PATH", raising=False)
    monkeypatch.delenv("BUILDEROPS_VAULT_ROOT", raising=False)

    store = CkmStore.open_default()
    store.ensure_schema()

    assert store.db_path == tmp_path / "state" / "builderops.sqlite3"
    assert store.db_path.exists()
