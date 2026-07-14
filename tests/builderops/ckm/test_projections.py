from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from app.builderops.cli import builderops
from app.builderops.ckm.assess import assess_capabilities
from app.builderops.ckm.projections import (
    PROJECTION_FILENAMES,
    TRACEABILITY_COLUMNS,
    render_capability_show,
    render_projection,
    write_projection,
)
from app.builderops.ckm.seed import seed_capabilities
from app.builderops.ckm.store import CkmStore


@pytest.fixture()
def populated_store(tmp_path: Path) -> CkmStore:
    store = CkmStore(tmp_path / "builderops.sqlite3")
    store.ensure_schema()
    store.set_watermark("github", "2026-07-14T12:00:00Z")
    store.set_watermark("repo", "abc123")
    capability = store.upsert_capability(
        name="Retrieval",
        definition="Retrieve grounded context.",
        existence_provenance="seeded:docs/CAPABILITY_CONTRACT_MODEL.md :: Retrieval",
        lifecycle="confirmed",
        boundary_ref="RCA",
    )

    confirmed_artifact = store.upsert_artifact(
        source_ref="app/retrieval/capability.py",
        artifact_kind="source_file",
        source="repo",
        watermark="abc123",
        provenance='{"source_ref":"app/retrieval/capability.py"}',
    )
    confirmed_edge = store.upsert_evidence_edge(
        artifact_id=confirmed_artifact.id,
        capability_id=capability.id,
        evidence_kind="source",
        polarity="supports",
        maturity_dimension="functional_completeness",
        confidence=1.0,
        extraction_method="deterministic",
        lifecycle="confirmed",
        source_ref=confirmed_artifact.source_ref,
        basis="fixture:confirmed-source",
    )
    candidate_artifact = store.upsert_artifact(
        source_ref="docs/drafts/retrieval-notes.md",
        artifact_kind="document",
        source="repo",
        watermark="abc123",
        provenance='{"source_ref":"docs/drafts/retrieval-notes.md"}',
    )
    store.upsert_evidence_edge(
        artifact_id=candidate_artifact.id,
        capability_id=capability.id,
        evidence_kind="doc",
        polarity="supports",
        maturity_dimension="documentation_quality",
        confidence=0.8,
        extraction_method="inferred",
        lifecycle="candidate",
        source_ref=candidate_artifact.source_ref,
        basis="semantic:retrieval-doc",
        model="fixture-model",
        provider="fixture-provider",
    )
    issue_artifact = store.upsert_artifact(
        source_ref="github:issue:42",
        artifact_kind="issue",
        source="github",
        watermark="2026-07-14T12:00:00Z",
        provenance='{"number":42,"state":"closed"}',
    )
    store.upsert_evidence_edge(
        artifact_id=issue_artifact.id,
        capability_id=capability.id,
        evidence_kind="requirement",
        polarity="supports",
        maturity_dimension="requirement_coverage",
        confidence=1.0,
        extraction_method="deterministic",
        lifecycle="confirmed",
        source_ref=issue_artifact.source_ref,
        basis="fixture:implementation-issue",
    )
    store.upsert_artifact(
        source_ref="docs/unlinked.md",
        artifact_kind="document",
        source="repo",
        watermark="abc123",
        provenance='{"source_ref":"docs/unlinked.md"}',
    )
    assess_capabilities(store)
    store.upsert_finding(
        kind="gap",
        capability_id=capability.id,
        dimension="test_completeness",
        statement="Retrieval lacks confirmed test evidence.",
        citations=[
            {
                "edge_id": confirmed_edge.id,
                "artifact_id": confirmed_artifact.id,
                "source_ref": confirmed_artifact.source_ref,
                "lifecycle": confirmed_edge.lifecycle,
                "edge": confirmed_edge.to_dict(),
                "artifact": confirmed_artifact.to_dict(),
            }
        ],
    )
    return store


def test_all_egress_self_identifies_with_watermark(populated_store: CkmStore) -> None:
    for projection_type in PROJECTION_FILENAMES:
        rendered = render_projection(
            populated_store,
            projection_type,
            generated_at="2026-07-14T12:30:00Z",
        )
        opening = rendered.splitlines()[:8]
        assert opening[0] == "State: Generated projection"
        assert "non-authoritative BuilderOps CKM projection" in opening[1]
        assert "Generated at: 2026-07-14T12:30:00Z" in opening
        assert f"Projection type: {projection_type}" in opening
        assert "Watermarks: github=2026-07-14T12:00:00Z, repo=abc123" in opening

    shown = render_capability_show(
        populated_store,
        "retrieval",
        generated_at="2026-07-14T12:30:00Z",
    )
    assert shown.startswith("State: Generated projection\n")
    assert "Projection type: ckm-show" in shown
    assert "Watermarks: github=2026-07-14T12:00:00Z, repo=abc123" in shown


def test_stale_assessment_flagged_in_render(populated_store: CkmStore) -> None:
    current = render_projection(populated_store, "ckm-maturity")
    assert "Assessment: **current**" in current

    populated_store.set_watermark("repo", "def456")

    stale = render_projection(populated_store, "ckm-maturity")
    shown = render_capability_show(populated_store, "retrieval")
    assert "STALE relative to evidence" in stale
    assert "STALE relative to evidence" in shown


def test_candidate_confirmed_distinction_rendered(populated_store: CkmStore) -> None:
    capability_map = render_projection(populated_store, "ckm-capability-map")
    maturity = render_projection(populated_store, "ckm-maturity")
    shown = render_capability_show(populated_store, "retrieval")

    assert "| Retrieval | confirmed | RCA | 2 | 1 |" in capability_map
    assert "Evidence: **2 confirmed / 1 candidate**" in maturity
    assert "Candidate share" in maturity
    assert "Evidence: **2 confirmed / 1 candidate**" in shown
    assert "**candidate** `doc`" in shown
    assert "**confirmed** `source`" in shown
    assert "basis: semantic:retrieval-doc" in shown


def test_generated_matrix_shape_and_never_overwrites_canonical(
    populated_store: CkmStore,
    tmp_path: Path,
) -> None:
    canonical = Path("docs/architecture/traceability-matrix.md")
    before = canonical.read_bytes()
    canonical_header = next(
        line
        for line in canonical.read_text(encoding="utf-8").splitlines()
        if line.startswith("| # | Principle / finding |")
    )
    canonical_columns = tuple(part.strip() for part in canonical_header.strip("|").split("|"))

    result = write_projection(populated_store, "ckm-traceability-matrix", tmp_path / "generated")
    generated_header = next(
        line
        for line in result.path.read_text(encoding="utf-8").splitlines()
        if line.startswith("| # | Principle / finding |")
    )
    generated_columns = tuple(part.strip() for part in generated_header.strip("|").split("|"))

    assert canonical_columns == TRACEABILITY_COLUMNS == generated_columns
    assert result.path == tmp_path / "generated" / "ckm-traceability-matrix.md"
    assert canonical.read_bytes() == before
    retrieval_row = next(
        line
        for line in result.path.read_text(encoding="utf-8").splitlines()
        if "| Retrieval (confirmed) |" in line
    )
    cells = [part.strip() for part in retrieval_row.strip("|").split("|")]
    assert "github:issue:42 (confirmed)" not in cells[7]
    assert "github:issue:42 (confirmed)" in cells[9]


def test_cli_project_and_show(populated_store: CkmStore, tmp_path: Path) -> None:
    output_dir = tmp_path / "projections"
    runner = CliRunner()
    project = runner.invoke(
        builderops,
        [
            "--db-path",
            str(populated_store.db_path),
            "ckm",
            "project",
            "--type",
            "ckm-capability-map",
            "--out",
            str(output_dir),
        ],
    )
    shown = runner.invoke(
        builderops,
        ["--db-path", str(populated_store.db_path), "ckm", "show", "retrieval"],
    )

    assert project.exit_code == 0, project.output
    assert output_dir.joinpath("ckm-capability-map.md").is_file()
    assert shown.exit_code == 0, shown.output
    assert "Projection type: ckm-show" in shown.output
    assert "basis: fixture:confirmed-source" in shown.output


def test_show_resolves_manifest_slug_and_inferred_fallback(tmp_path: Path) -> None:
    store = CkmStore(tmp_path / "slug-query.sqlite3")
    store.ensure_schema()
    seed_capabilities(store)
    store.upsert_capability(
        name="Novel Inferred Capability",
        definition="A candidate capability outside the reviewed seed manifest.",
        existence_provenance="inferred:fixture",
        lifecycle="candidate",
    )

    boundary = render_capability_show(store, "rca")
    inferred = render_capability_show(store, "novel-inferred-capability")

    assert "# Retrieval & Context Assembly" in boundary
    assert "Boundary: **RCA**" in boundary
    assert "# Novel Inferred Capability" in inferred
    assert "Lifecycle: **candidate**" in inferred
