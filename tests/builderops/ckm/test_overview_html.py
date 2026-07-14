from __future__ import annotations

import re
from pathlib import Path

import pytest
from click.testing import CliRunner

from app.builderops.cli import builderops
from app.builderops.ckm.models import MATURITY_DIMENSIONS
from app.builderops.ckm.overview_html import render_overview_html
from app.builderops.ckm.store import CkmStore


@pytest.fixture()
def overview_store(tmp_path: Path) -> CkmStore:
    store = CkmStore(tmp_path / "overview.sqlite3")
    store.ensure_schema()
    store.set_watermark("fixture", "one")
    parent = store.upsert_capability(
        name="Retrieval",
        definition="Retrieve grounded context.",
        existence_provenance="seeded:fixture",
        lifecycle="confirmed",
        boundary_ref="RCA",
    )
    store.upsert_capability(
        name="Context Assembly",
        definition="Assemble a bounded context bundle.",
        existence_provenance="seeded:fixture-child",
        lifecycle="confirmed",
        parent_id=parent.id,
        boundary_ref="RCA",
    )
    confirmed_artifact = store.upsert_artifact(
        source_ref="app/retrieval.py",
        artifact_kind="source_file",
        source="fixture",
        watermark="one",
        provenance='{"source_ref":"app/retrieval.py"}',
    )
    confirmed_edge = store.upsert_evidence_edge(
        artifact_id=confirmed_artifact.id,
        capability_id=parent.id,
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
        source_ref="docs/retrieval-draft.md",
        artifact_kind="document",
        source="fixture",
        watermark="one",
        provenance='{"source_ref":"docs/retrieval-draft.md"}',
    )
    store.upsert_evidence_edge(
        artifact_id=candidate_artifact.id,
        capability_id=parent.id,
        evidence_kind="doc",
        polarity="supports",
        maturity_dimension="documentation_quality",
        confidence=0.7,
        extraction_method="inferred",
        lifecycle="candidate",
        source_ref=candidate_artifact.source_ref,
        basis="semantic:retrieval-draft",
        model="fixture-model",
        provider="fixture-provider",
    )
    citation = {
        "edge_id": confirmed_edge.id,
        "artifact_id": confirmed_artifact.id,
        "source_ref": confirmed_artifact.source_ref,
        "lifecycle": confirmed_edge.lifecycle,
        "edge": confirmed_edge.to_dict(),
        "artifact": confirmed_artifact.to_dict(),
    }
    store.append_assessment(
        capability_id=parent.id,
        scores={dimension: 0.8 for dimension in MATURITY_DIMENSIONS},
        citations={dimension: [citation] for dimension in MATURITY_DIMENSIONS},
        candidate_shares={dimension: 0.75 for dimension in MATURITY_DIMENSIONS},
        formula_ids={dimension: "fixture-formula" for dimension in MATURITY_DIMENSIONS},
        aggregate=0.8,
        aggregate_formula_id="fixture-aggregate",
        low_confidence=True,
        edge_fingerprint="fixture-fingerprint",
        watermark_set={"fixture": "one"},
    )
    store.upsert_finding(
        kind="gap",
        capability_id=parent.id,
        dimension="test_completeness",
        statement="Retrieval needs stronger test evidence.",
        citations=[citation],
    )
    store.set_watermark("fixture", "two")
    return store


def test_pure_render_over_fixture_graph(overview_store: CkmStore) -> None:
    before = (
        overview_store.list_capabilities(),
        overview_store.list_evidence_edges(),
        overview_store.list_findings(),
    )
    first = render_overview_html(
        overview_store,
        generated_at="2026-07-14T15:00:00Z",
    )
    second = render_overview_html(
        overview_store,
        generated_at="2026-07-14T15:00:00Z",
    )

    assert first == second
    assert before == (
        overview_store.list_capabilities(),
        overview_store.list_evidence_edges(),
        overview_store.list_findings(),
    )
    assert '<div class="capability-tree">' in first
    assert "Retrieval" in first and "Context Assembly" in first
    assert 'style="--depth:1"' in first
    assert 'data-aggregate-band="healthy"' in first
    assert first.count('class="dimension-bar"') == len(MATURITY_DIMENSIONS)
    summary = first.split("</summary>", maxsplit=1)[0]
    assert summary.count('class="mini-dimension"') == len(MATURITY_DIMENSIONS)
    assert '<details class="drilldown"><summary>Evidence and basis</summary>' in first
    assert "Retrieval needs stronger test evidence." in first


def test_honesty_markers_render(overview_store: CkmStore) -> None:
    rendered = render_overview_html(overview_store)

    assert "STALE relative to evidence" in rendered
    assert "LOW CONFIDENCE" in rendered
    assert "candidate share 75.0%" in rendered
    assert "candidate share unavailable" in rendered
    assert rendered.count('mini-dimension mini-unknown') == len(MATURITY_DIMENSIONS)
    assert "2 confirmed / 1 candidate" not in rendered
    assert "1 confirmed / 1 candidate" in rendered
    assert '<span class="badge">candidate</span>' in rendered
    assert "Basis: semantic:retrieval-draft" in rendered


def test_projection_footer_always_present(tmp_path: Path, overview_store: CkmStore) -> None:
    empty = CkmStore(tmp_path / "empty.sqlite3")
    empty.ensure_schema()

    for store in (overview_store, empty):
        rendered = render_overview_html(
            store,
            generated_at="2026-07-14T15:00:00Z",
        )
        assert '<footer class="projection-footer">' in rendered
        assert "Generated projection (BuilderOps CKM). Not source of truth." in rendered
        assert "Generated: 2026-07-14T15:00:00Z" in rendered
        assert "Watermarks:" in rendered
        assert "Candidate and confirmed evidence remain distinct." in rendered

def test_no_external_references(overview_store: CkmStore) -> None:
    rendered = render_overview_html(overview_store)

    assert not re.search(r"<(?:script|link|img)\b", rendered, flags=re.IGNORECASE)
    assert not re.search(
        r"(?:src|href)\s*=\s*['\"](?:https?:)?//",
        rendered,
        flags=re.IGNORECASE,
    )
    assert "<style>" in rendered


def test_cli_writes_overview(overview_store: CkmStore, tmp_path: Path) -> None:
    output = tmp_path / "delivery" / "ckm-overview.html"
    result = CliRunner().invoke(
        builderops,
        [
            "--db-path",
            str(overview_store.db_path),
            "ckm",
            "overview",
            "--out",
            str(output),
        ],
    )

    assert result.exit_code == 0, result.output
    assert output.is_file()
    assert "Development Overview" in output.read_text(encoding="utf-8")


def test_cli_rejects_missing_database_without_creating_it(tmp_path: Path) -> None:
    database = tmp_path / "missing" / "ckm.sqlite3"
    output = tmp_path / "ckm-overview.html"

    result = CliRunner().invoke(
        builderops,
        ["--db-path", str(database), "ckm", "overview", "--out", str(output)],
    )

    assert result.exit_code != 0
    assert "CKM database does not exist" in result.output
    assert not database.exists()
    assert not output.exists()
