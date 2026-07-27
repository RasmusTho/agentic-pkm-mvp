from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
import subprocess
from dataclasses import replace
from html import unescape
from html.parser import HTMLParser
from pathlib import Path

import pytest
from click.testing import CliRunner

from app.builderops.__main__ import _root
import app.builderops.cli as builderops_cli_module
import app.builderops.ckm.overview_html as overview_html_module
from app.builderops.cli import builderops
from app.builderops.ckm import comparison as comparison_module
from app.builderops.ckm.contracts import CkmContractError, ResultEnvelope, canonical_digest
from app.builderops.ckm.metrics import MetricRetentionStore
from app.builderops.ckm.models import MATURITY_DIMENSIONS, CkmCapability, CkmFinding
from app.builderops.ckm.overview_html import CockpitRenderContext, render_overview_html
from app.builderops.ckm.query_service import CkmQueryService
from app.builderops.ckm.store import CkmProjectionBatch, CkmStore


@pytest.fixture()
def overview_store(tmp_path: Path) -> CkmStore:
    store = CkmStore(tmp_path / "overview.sqlite3")
    store.ensure_schema()
    store.set_watermark("fixture", "one")
    parent = store.upsert_capability(
        identity_key="fixture:overview:retrieval",
        name="Retrieval",
        definition="Retrieve grounded context.",
        existence_provenance="seeded:fixture",
        lifecycle="confirmed",
        boundary_ref="RCA",
    )
    store.upsert_capability(
        identity_key="fixture:overview:context-assembly",
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
    scores = {dimension: 0.8 for dimension in MATURITY_DIMENSIONS}
    citations = {dimension: [citation] for dimension in MATURITY_DIMENSIONS}
    dimension_status = {dimension: "measured" for dimension in MATURITY_DIMENSIONS}
    scores["operational_readiness"] = 0.0
    citations["operational_readiness"] = []
    dimension_status["operational_readiness"] = "missing"
    scores["documentation_quality"] = 0.0
    citations["documentation_quality"] = []
    dimension_status["documentation_quality"] = "unassessed"
    store.append_assessment(
        capability_id=parent.id,
        scores=scores,
        citations=citations,
        dimension_status=dimension_status,
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


def _make_snapshot_exceed_default(store: CkmStore) -> None:
    """Add enough real fixture artifacts to exceed the default class bound."""
    existing = len(store.list_artifacts())
    for index in range(existing, 501):
        store.upsert_artifact(
            source_ref=f"fixture/oversized-{index}.md",
            artifact_kind="document",
            source="fixture",
            watermark="one",
            provenance=f'{{"source_ref":"fixture/oversized-{index}.md"}}',
        )


@pytest.fixture()
def fanout_overview_store(tmp_path: Path) -> CkmStore:
    store = CkmStore(tmp_path / "fanout-overview.sqlite3")
    store.ensure_schema()
    subsystem = store.upsert_capability(
        identity_key="fixture:counts:subsystem",
        name="Retrieval subsystem",
        definition="Fixture subsystem.",
        existence_provenance="seeded:fixture",
        lifecycle="confirmed",
        boundary_ref="RCA",
    )
    child = store.upsert_capability(
        identity_key="fixture:counts:child",
        name="Retrieval",
        definition="Fixture child capability.",
        existence_provenance="seeded:fixture-child",
        lifecycle="confirmed",
        parent_id=subsystem.id,
        boundary_ref="RCA",
    )
    other = store.upsert_capability(
        identity_key="fixture:counts:other",
        name="Observability subsystem",
        definition="Fixture second subsystem.",
        existence_provenance="seeded:fixture-other",
        lifecycle="confirmed",
        boundary_ref="OEF",
    )
    shared = store.upsert_artifact(
        source_ref="docs/shared.md",
        artifact_kind="document",
        source="fixture",
        watermark="one",
        provenance='{"source_ref":"docs/shared.md"}',
    )
    subsystem_only = store.upsert_artifact(
        source_ref="app/retrieval.py",
        artifact_kind="source_file",
        source="fixture",
        watermark="one",
        provenance='{"source_ref":"app/retrieval.py"}',
    )
    child_only = store.upsert_artifact(
        source_ref="tests/test_retrieval.py",
        artifact_kind="test",
        source="fixture",
        watermark="one",
        provenance='{"source_ref":"tests/test_retrieval.py"}',
    )

    def edge(*, artifact_id: str, capability_id: str, basis: str) -> None:
        store.upsert_evidence_edge(
            artifact_id=artifact_id,
            capability_id=capability_id,
            evidence_kind="source",
            polarity="supports",
            maturity_dimension="functional_completeness",
            confidence=1.0,
            extraction_method="deterministic",
            lifecycle="confirmed",
            source_ref=f"fixture:{artifact_id}",
            basis=basis,
        )

    edge(artifact_id=shared.id, capability_id=subsystem.id, basis="fixture:fanout")
    edge(artifact_id=shared.id, capability_id=subsystem.id, basis="fixture:second-edge")
    edge(
        artifact_id=subsystem_only.id,
        capability_id=subsystem.id,
        basis="fixture:subsystem-only",
    )
    edge(artifact_id=shared.id, capability_id=child.id, basis="fixture:fanout")
    edge(artifact_id=child_only.id, capability_id=child.id, basis="fixture:child-only")
    edge(artifact_id=shared.id, capability_id=other.id, basis="fixture:fanout")
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
    assert "data-aggregate-band" not in first
    assert "band-critical" not in first
    assert "band-watch" not in first
    assert "band-healthy" not in first
    assert first.count('class="dimension-bar"') == len(MATURITY_DIMENSIONS) - 1
    summary = first.split("</summary>", maxsplit=1)[0]
    assert summary.count('class="mini-dimension ') == len(MATURITY_DIMENSIONS)
    assert '<details class="drilldown"><summary>Evidence and basis</summary>' in first
    assert "Retrieval needs stronger test evidence." in first


def test_honesty_markers_render(overview_store: CkmStore) -> None:
    rendered = render_overview_html(overview_store)

    assert "STALE relative to evidence" in rendered
    assert "LOW CONFIDENCE" in rendered
    assert "candidate share 75.0%" in rendered
    assert "candidate share unavailable" in rendered
    assert rendered.count("mini-dimension mini-unassessed") == len(MATURITY_DIMENSIONS) + 1
    assert "2 confirmed / 1 candidate" not in rendered
    assert "1 confirmed / 1 candidate" in rendered
    assert '<span class="badge evidence-status">candidate</span>' in rendered
    assert "Basis: semantic:retrieval-draft" in rendered

    retrieval_summary = rendered.split('<article id="cap-', maxsplit=1)[1].split(
        "</summary>", maxsplit=1
    )[0]
    assert "STALE" in retrieval_summary
    assert "LOW CONF" in retrieval_summary


def test_dimension_cells_render_three_states_and_proportional_fill(
    overview_store: CkmStore,
) -> None:
    rendered = render_overview_html(overview_store)

    assert rendered.count('class="mini-dimension ') == 2 * len(MATURITY_DIMENSIONS)
    assert 'class="mini-dimension mini-scored"' in rendered
    assert 'style="--score:80.0%"' in rendered
    assert 'class="mini-dimension mini-starved"' in rendered
    assert (
        '<section class="dimension dimension-unassessed" '
        'data-dimension="documentation_quality" data-cell-state="unassessed">' in rendered
    )
    unassessed_section = rendered.split(
        'data-dimension="documentation_quality" data-cell-state="unassessed">',
        maxsplit=1,
    )[1].split("</section>", maxsplit=1)[0]
    assert "<strong>—</strong>" in unassessed_section
    assert "dimension-track" not in unassessed_section
    assert "dimension-bar" not in unassessed_section
    unknown_cells = re.findall(
        r'<span class="mini-dimension mini-unassessed"[^>]*>—</span>', rendered
    )
    assert len(unknown_cells) == len(MATURITY_DIMENSIONS) + 1
    assert all("--score" not in cell for cell in unknown_cells)


def test_candidate_chip_conditional(overview_store: CkmStore) -> None:
    rendered = render_overview_html(overview_store)
    summaries = re.findall(r"<summary class=\"capability-summary\">(.*?)</summary>", rendered, re.S)

    assert "CAND 75.0%" in summaries[0]
    assert "CAND" not in summaries[1]


def test_gap_capability_crosslinks(overview_store: CkmStore) -> None:
    rendered = render_overview_html(overview_store)

    assert 'id="cap-' in rendered
    assert re.search(r'href="#gaps-[^"]+"[^>]*>1 gap', rendered)
    gap_ids = set(re.findall(r'id="gaps-([^"]+)" class="gap-group"', rendered))
    capability_links = set(re.findall(r'href="#cap-([^"]+)"', rendered))
    assert gap_ids == capability_links


def test_aggregate_demoted_label(overview_store: CkmStore) -> None:
    rendered = render_overview_html(overview_store)

    assert 'class="aggregate"' not in rendered
    assert "Minimum of seven maturity dimensions" not in rendered
    assert "data-aggregate-band" not in rendered
    assert 'class="band-label"' not in rendered
    assert 'class="band-dot"' not in rendered


def test_legend_dimension_mapping(overview_store: CkmStore) -> None:
    rendered = render_overview_html(overview_store)

    for dimension in MATURITY_DIMENSIONS:
        assert dimension.replace("_", " ") in rendered
    for state in ("scored", "evidence-starved", "unassessed"):
        assert f'data-cell-state="{state}"' in rendered


def test_no_scripts_or_external_references(overview_store: CkmStore) -> None:
    rendered = render_overview_html(overview_store)

    assert not re.search(r"<(?:script|link|img|iframe|object|embed)\b", rendered, re.I)
    assert not re.search(r"\bon[a-z]+\s*=", rendered, re.I)
    assert not re.search(r"(?:https?:)?//", rendered, re.I)
    assert "url(" not in rendered.lower()


def test_empty_store_page_state(tmp_path: Path) -> None:
    store = CkmStore(tmp_path / "empty.sqlite3")
    store.ensure_schema()
    rendered = render_overview_html(store, generated_at="2026-07-14T15:00:00Z")

    assert "Generated projection — not source of truth" in rendered
    assert "0 capabilities" in rendered
    assert "No capabilities in the CKM store." in rendered
    assert "No current findings." in rendered
    assert '<footer class="projection-footer">' in rendered


def test_accessibility_and_responsive_contract(overview_store: CkmStore) -> None:
    rendered = render_overview_html(overview_store)

    assert '<details class="capability-details">' in rendered
    assert '<summary class="capability-summary">' in rendered
    assert ":focus-visible" in rendered
    assert "summary::before" in rendered and "details[open] > summary::before" in rendered
    assert "@media (max-width:680px)" in rendered
    assert "font-size:1rem" in rendered
    assert 'role="img"' in rendered
    assert "Citations — operational readiness (0)" in rendered
    assert 'class="band-dot"' not in rendered


def test_node_lifecycle_and_evidence_confirmation_are_distinct(
    overview_store: CkmStore,
) -> None:
    rendered = render_overview_html(overview_store)

    assert "node: confirmed" in rendered
    assert 'class="badge evidence-status">confirmed</span>' in rendered
    assert 'class="badge evidence-status">candidate</span>' in rendered


def test_expanded_honesty_prose_names_trust_state(overview_store: CkmStore) -> None:
    rendered = render_overview_html(overview_store)

    assert "Assessment is available." in rendered
    assert "Assessment is stale relative to current evidence." in rendered
    assert "Maximum candidate-evidence share is 75.0%." in rendered
    assert "Assessment is unavailable; unavailable is not a zero score." in rendered


def test_provenance_banner_precedes_map_and_footer_remains(
    tmp_path: Path, overview_store: CkmStore
) -> None:
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
        assert rendered.index("Generated projection — not source of truth") < rendered.index(
            'id="map-heading"'
        )


def test_subsystem_counts_distinct_artifacts(
    fanout_overview_store: CkmStore,
) -> None:
    rendered = render_overview_html(fanout_overview_store)

    subsystem = re.search(
        r'<section class="subsystem-counts-card"[^>]*data-subsystem-name="Retrieval subsystem"'
        r'[^>]*data-capability-count="2"[^>]*data-distinct-artifacts="3"',
        rendered,
    )
    assert subsystem is not None
    root = re.search(
        r'<li class="capability-count"[^>]*data-capability-name="Retrieval subsystem"'
        r'[^>]*data-distinct-artifacts="2"[^>]*data-edge-count="3"',
        rendered,
    )
    child = re.search(
        r'<li class="capability-count"[^>]*data-capability-name="Retrieval"'
        r'[^>]*data-distinct-artifacts="2"[^>]*data-edge-count="2"',
        rendered,
    )
    assert root is not None
    assert child is not None
    assert (
        "distinct artifacts: <strong>3</strong>"
        in subsystem.group(0) + rendered[subsystem.end() : subsystem.end() + 300]
    )


def test_subsystem_counts_shared_evidence_indicator(
    fanout_overview_store: CkmStore,
) -> None:
    rendered = render_overview_html(fanout_overview_store)

    assert re.search(
        r'data-subsystem-name="Retrieval subsystem"[^>]*data-shared-edge-count="2"'
        r'[^>]*data-edge-count="5"[^>]*data-shared-evidence="40.0%"',
        rendered,
    )
    assert re.search(
        r'data-capability-name="Retrieval subsystem"[^>]*data-shared-edge-count="1"'
        r'[^>]*data-edge-count="3"[^>]*data-shared-evidence="33.3%"',
        rendered,
    )
    assert re.search(
        r'data-capability-name="Retrieval"[^>]*data-shared-edge-count="1"'
        r'[^>]*data-edge-count="2"[^>]*data-shared-evidence="50.0%"',
        rendered,
    )
    assert rendered.count("shared evidence:") == 6


def test_subsystem_counts_global_masthead(
    fanout_overview_store: CkmStore,
) -> None:
    rendered = render_overview_html(fanout_overview_store)

    assert re.search(
        r'class="linkage-masthead" data-denominator="global" '
        r'data-distinct-artifacts="3" data-capability-count="3" '
        r'data-shared-edge-count="3" data-edge-count="6" '
        r'data-shared-evidence="50.0%"',
        rendered,
    )
    assert "3 distinct artifacts across 3 capabilities" in rendered
    assert "50.0%</strong> of all 6 edges (global)" in rendered


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


def test_cli_overview_accepts_explicit_capture_bounds(
    overview_store: CkmStore,
    tmp_path: Path,
) -> None:
    _make_snapshot_exceed_default(overview_store)
    default_output = tmp_path / "default-refused" / "ckm-overview.html"
    default_result = CliRunner().invoke(
        builderops,
        ["--db-path", str(overview_store.db_path), "ckm", "overview", "--out", str(default_output)],
    )
    assert default_result.exit_code != 0
    assert "snapshot" in default_result.output
    assert not default_output.exists()

    output = tmp_path / "bounded" / "ckm-overview.html"
    result = CliRunner().invoke(
        builderops,
        [
            "--db-path",
            str(overview_store.db_path),
            "ckm",
            "overview",
            "--out",
            str(output),
            "--class-capture-limit",
            "501",
            "--aggregate-capture-limit",
            "3001",
        ],
    )

    assert result.exit_code == 0, result.output
    assert output.is_file()


def test_cli_overview_preserves_default_and_insufficient_bound_refusal(
    overview_store: CkmStore,
    tmp_path: Path,
) -> None:
    _make_snapshot_exceed_default(overview_store)
    output = tmp_path / "refused" / "ckm-overview.html"
    result = CliRunner().invoke(
        builderops,
        [
            "--db-path",
            str(overview_store.db_path),
            "ckm",
            "overview",
            "--out",
            str(output),
            "--class-capture-limit",
            "1",
            "--aggregate-capture-limit",
            "1",
        ],
    )

    assert result.exit_code != 0
    assert "snapshot" in result.output
    assert not output.exists()

    insufficient = tmp_path / "insufficient" / "ckm-overview.html"
    insufficient_result = CliRunner().invoke(
        builderops,
        [
            "--db-path",
            str(overview_store.db_path),
            "ckm",
            "overview",
            "--out",
            str(insufficient),
            "--class-capture-limit",
            "1",
            "--aggregate-capture-limit",
            "1",
        ],
    )
    assert insufficient_result.exit_code != 0
    assert "snapshot" in insufficient_result.output
    assert not insufficient.exists()


def test_cli_overview_rejects_non_positive_capture_bounds(
    overview_store: CkmStore,
    tmp_path: Path,
) -> None:
    for value in ("0", "-1"):
        output = tmp_path / f"invalid-{value.replace('-', 'negative-')}" / "ckm-overview.html"
        result = CliRunner().invoke(
            builderops,
            [
                "--db-path",
                str(overview_store.db_path),
                "ckm",
                "overview",
                "--out",
                str(output),
                "--class-capture-limit",
                value,
            ],
        )
        assert result.exit_code != 0
        assert "Invalid value" in result.output
        assert not output.exists()


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


def test_cli_cockpit_is_opt_in_and_default_remains_direction_a(
    overview_store: CkmStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    default_output = tmp_path / "default.html"
    cockpit_output = tmp_path / "cockpit.html"
    monkeypatch.setattr(
        builderops_cli_module,
        "newest_active_retained_sample_ids",
        lambda *_: pytest.fail("Direction A must not access retention storage"),
    )
    default = CliRunner().invoke(
        builderops,
        ["--db-path", str(overview_store.db_path), "ckm", "overview", "--out", str(default_output)],
    )
    monkeypatch.undo()
    cockpit = CliRunner().invoke(
        builderops,
        [
            "--db-path",
            str(overview_store.db_path),
            "ckm",
            "overview",
            "--cockpit",
            "--out",
            str(cockpit_output),
        ],
    )
    assert default.exit_code == cockpit.exit_code == 0
    assert "Cockpit trust frame" not in default_output.read_text(encoding="utf-8")
    assert "Cockpit trust frame" in cockpit_output.read_text(encoding="utf-8")


def test_cockpit_uses_existing_overview_renderer_call_site(overview_store: CkmStore) -> None:
    context = CockpitRenderContext(batch=overview_store.load_projection_batch())
    rendered = render_overview_html(
        overview_store, generated_at="2026-07-25T10:00:00Z", cockpit=context
    )
    assert "Cockpit trust frame" in rendered
    assert "Capability map" in rendered


class _CockpitHtmlSafetyParser(HTMLParser):
    """Record the parser-normalized script and inline-handler surface of generated HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.script_count = 0
        self.script_bodies: list[str] = []
        self.script_sources: list[str] = []
        self.inline_handlers: list[str] = []
        self._script_parts: list[str] | None = None

    def _record_start(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
        *,
        capture_script_body: bool,
    ) -> None:
        normalized_tag = tag.lower()
        normalized_attrs = [(name.lower(), value) for name, value in attrs]
        self.inline_handlers.extend(name for name, _ in normalized_attrs if name.startswith("on"))
        if normalized_tag == "script":
            self.script_count += 1
            self.script_sources.extend(
                value or "" for name, value in normalized_attrs if name == "src"
            )
            if capture_script_body:
                self._script_parts = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._record_start(tag, attrs, capture_script_body=True)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._record_start(tag, attrs, capture_script_body=False)

    def handle_data(self, data: str) -> None:
        if self._script_parts is not None:
            self._script_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "script" and self._script_parts is not None:
            self.script_bodies.append("".join(self._script_parts))
            self._script_parts = None


def _parse_cockpit_html_safety(rendered: str) -> _CockpitHtmlSafetyParser:
    parser = _CockpitHtmlSafetyParser()
    parser.feed(rendered)
    parser.close()
    return parser


def _cockpit_filter_script(rendered: str) -> str:
    parser = _parse_cockpit_html_safety(rendered)
    assert parser.script_count == 1
    assert len(parser.script_bodies) == 1
    return parser.script_bodies[0]


def _require_node_for_cockpit_script_execution() -> str:
    node = shutil.which("node")
    assert node is not None, (
        "Node.js is a required test dependency for the CKM generated-HTML JavaScript regression."
    )
    return node


def test_cockpit_has_exactly_one_filtering_script_and_default_has_none(
    overview_store: CkmStore,
) -> None:
    context = CockpitRenderContext(batch=overview_store.load_projection_batch())
    default = render_overview_html(overview_store)
    cockpit = render_overview_html(overview_store, cockpit=context)
    default_safety = _parse_cockpit_html_safety(default)
    cockpit_safety = _parse_cockpit_html_safety(cockpit)

    assert default_safety.script_count == 0
    assert default_safety.script_bodies == []
    assert cockpit_safety.script_count == 1
    assert len(cockpit_safety.script_bodies) == 1
    assert cockpit_safety.script_sources == []
    assert cockpit_safety.inline_handlers == []
    assert not re.search(r"(?:https?:)?//", cockpit, re.I)
    synthetic_safety = _parse_cockpit_html_safety(
        '<script TYPE="text/javascript" onload="blocked()">lower</script>'
        '<SCRIPT SRC="blocked.js" ONLOAD="blocked()">upper</SCRIPT>'
        '<button ONCLICK="blocked()" onfocus="blocked()">blocked</button>'
    )
    assert synthetic_safety.script_bodies == ["lower", "upper"]
    assert synthetic_safety.script_sources == ["blocked.js"]
    assert synthetic_safety.inline_handlers == ["onload", "onload", "onclick", "onfocus"]
    unmatched_safety = _parse_cockpit_html_safety(
        "<script>closed production body</script><SCRIPT>"
    )
    assert unmatched_safety.script_count == 2
    assert unmatched_safety.script_bodies == ["closed production body"]
    with pytest.raises(AssertionError):
        _cockpit_filter_script("<script>closed production body</script><SCRIPT>")
    self_closing_safety = _parse_cockpit_html_safety(
        '<ScRiPt SRC="blocked.js" OnLoAd="blocked()" />'
    )
    assert self_closing_safety.script_count == 1
    assert self_closing_safety.script_bodies == []
    assert self_closing_safety.script_sources == ["blocked.js"]
    assert self_closing_safety.inline_handlers == ["onload"]
    assert _cockpit_filter_script(cockpit).lstrip().startswith("(() => {")
    assert cockpit.count('<h2 id="filters-heading">Filters</h2>') == 1
    assert cockpit.count('id="filters-heading"') == 1
    assert "Unavailable in this framing slice. All capability rows are shown." not in cockpit
    assert cockpit.index("Comparison") < cockpit.index("Filters") < cockpit.index("Capability map")


def test_cockpit_progressive_enhancement_keeps_full_source_content(
    overview_store: CkmStore,
) -> None:
    batch = overview_store.load_projection_batch()
    rendered = render_overview_html(overview_store, cockpit=CockpitRenderContext(batch=batch))

    assert rendered.count('class="capability"') == len(batch.capabilities)
    assert rendered.count('class="capability-body"') == len(batch.capabilities)
    for name in (
        "filter-search",
        "filter-assessment",
        "filter-confidence",
        "filter-findings",
        "filter-evidence",
    ):
        assert re.search(rf'name="{name}"[^>]* disabled', rendered)
    assert f"Showing {len(batch.capabilities)} of {len(batch.capabilities)} capabilities." in rendered
    assert "Filtering is unavailable; all capability rows are shown." in rendered
    assert rendered.index("<noscript>") < rendered.index("<script>")
    assert "Retrieve grounded context." in rendered


def test_cockpit_script_has_closed_filter_only_capability(overview_store: CkmStore) -> None:
    rendered = render_overview_html(
        overview_store,
        cockpit=CockpitRenderContext(batch=overview_store.load_projection_batch()),
    )
    script = _cockpit_filter_script(rendered)
    row_openings = re.findall(r'<article[^>]+class="capability"[^>]*>', rendered)
    expected_attributes = {
        "data-filter-name",
        "data-filter-definition",
        "data-filter-public-id",
        "data-filter-boundary",
        "data-filter-assessment",
        "data-filter-confidence",
        "data-filter-findings",
        "data-filter-evidence",
    }

    assert row_openings
    assert all(
        {attribute.split("=", 1)[0] for attribute in re.findall(r"data-filter-[^=]+=", opening)}
        == expected_attributes
        for opening in row_openings
    )
    assert 'data-filter-assessment="available stale"' in rendered
    assert 'data-filter-confidence="low"' in rendered
    assert 'data-filter-findings="present"' in rendered
    assert 'data-filter-evidence="confirmed candidate"' in rendered
    for token in (
        "fetch",
        "XMLHttpRequest",
        "WebSocket",
        "clipboard",
        "localStorage",
        "sessionStorage",
        "cookie",
        "history",
        "location",
        "eval",
        "setTimeout",
        "setInterval",
        "innerHTML",
        "outerHTML",
        "insertAdjacentHTML",
        "createElement",
    ):
        assert token not in script
    for token in (
        "document.querySelector",
        "document.querySelectorAll",
        "row.dataset",
        "row.hidden",
        "control.disabled",
        "control.addEventListener",
        "count.textContent",
    ):
        assert token in script


def test_cockpit_filters_rendered_rows_with_deterministic_and_semantics(
    overview_store: CkmStore,
) -> None:
    rendered = render_overview_html(
        overview_store,
        cockpit=CockpitRenderContext(batch=overview_store.load_projection_batch()),
    )
    script = _cockpit_filter_script(rendered)
    node = _require_node_for_cockpit_script_execution()
    harness = r'''
const assert = (condition, message) => { if (!condition) throw new Error(message); };
class Control {
  constructor() { this.value = ''; this.disabled = true; this.listeners = {}; }
  addEventListener(type, handler) { this.listeners[type] = handler; }
  emit(type) { this.listeners[type]({ type }); }
}
const search = new Control();
const assessment = new Control();
const confidence = new Control();
const findings = new Control();
const evidence = new Control();
const count = { textContent: '' };
const rows = [
  { dataset: { filterName: 'Retrieval', filterDefinition: 'Retrieve grounded context', filterPublicId: 'CKM-1', filterBoundary: 'RCA', filterAssessment: 'available current', filterConfidence: 'low', filterFindings: 'present', filterEvidence: 'candidate' }, hidden: false },
  { dataset: { filterName: 'Context Assembly', filterDefinition: 'Assemble a bounded context bundle', filterPublicId: 'CKM-2', filterBoundary: 'RCA', filterAssessment: 'unavailable', filterConfidence: 'unavailable', filterFindings: 'absent', filterEvidence: 'none' }, hidden: false },
  { dataset: { filterName: 'Observability', filterDefinition: 'Draft telemetry coverage', filterPublicId: 'CKM-3', filterBoundary: 'OEF', filterAssessment: 'available stale', filterConfidence: 'standard', filterFindings: 'absent', filterEvidence: 'confirmed' }, hidden: false },
  { dataset: { filterName: 'Mixed Evidence', filterDefinition: 'Confirmed and candidate evidence', filterPublicId: 'CKM-4', filterBoundary: 'OEF', filterAssessment: 'available stale', filterConfidence: 'standard', filterFindings: 'present', filterEvidence: 'confirmed candidate' }, hidden: false }
];
const bySelector = {
  '[name="filter-search"]': search,
  '[name="filter-assessment"]': assessment,
  '[name="filter-confidence"]': confidence,
  '[name="filter-findings"]': findings,
  '[name="filter-evidence"]': evidence,
  '#filter-count': count
};
const document = {
  querySelector: (selector) => bySelector[selector],
  querySelectorAll: (selector) => { assert(selector === '#capability-map > .capability[data-filter-name]', 'row selector'); return rows; }
};
''' + script + r'''
const visible = () => rows.filter((row) => !row.hidden).length;
const setSearch = (value) => { search.value = value; search.emit('input'); };
const setFacet = (control, value) => { control.value = value; control.emit('change'); };
const reset = () => {
  search.value = ''; assessment.value = ''; confidence.value = ''; findings.value = ''; evidence.value = '';
  search.emit('input'); assessment.emit('change'); confidence.emit('change'); findings.emit('change'); evidence.emit('change');
};
assert([search, assessment, confidence, findings, evidence].every((control) => !control.disabled), 'controls enabled');
assert(visible() === 4 && count.textContent === 'Showing 4 of 4 capabilities.', 'initial count');
setSearch('cKm-3'); assert(visible() === 1 && !rows[2].hidden, 'public ID text filter');
setSearch('draft'); assert(visible() === 1 && !rows[2].hidden, 'definition text filter');
setFacet(assessment, 'available current'); assert(visible() === 0, 'assessment AND text');
reset();
setFacet(assessment, 'available current'); assert(visible() === 1 && !rows[0].hidden, 'current assessment');
setFacet(assessment, 'available stale'); assert(visible() === 2 && !rows[2].hidden && !rows[3].hidden, 'stale assessment');
setFacet(assessment, 'unavailable'); assert(visible() === 1 && !rows[1].hidden, 'unavailable assessment');
reset();
setFacet(confidence, 'low'); assert(visible() === 1 && !rows[0].hidden, 'low confidence');
setFacet(confidence, 'standard'); assert(visible() === 2 && !rows[2].hidden && !rows[3].hidden, 'standard confidence');
setFacet(confidence, 'unavailable'); assert(visible() === 1 && !rows[1].hidden, 'unavailable confidence');
reset();
setFacet(findings, 'present'); assert(visible() === 2 && !rows[0].hidden && !rows[3].hidden, 'findings present');
setFacet(findings, 'absent'); assert(visible() === 2, 'findings absent');
setFacet(evidence, 'confirmed'); assert(visible() === 1 && !rows[2].hidden, 'combined facets');
reset();
setFacet(evidence, 'confirmed'); assert(visible() === 2 && !rows[2].hidden && !rows[3].hidden, 'confirmed evidence');
setFacet(findings, 'present'); assert(visible() === 1 && !rows[3].hidden, 'mixed evidence AND findings');
reset();
setFacet(evidence, 'candidate'); assert(visible() === 2 && !rows[0].hidden && !rows[3].hidden, 'candidate evidence');
setFacet(evidence, 'none'); assert(visible() === 1 && !rows[1].hidden, 'no evidence');
setSearch('not-present'); assert(visible() === 0 && count.textContent === 'No capabilities match the selected filters. Showing 0 of 4 capabilities.', 'zero result');
reset(); assert(visible() === 4 && count.textContent === 'Showing 4 of 4 capabilities.', 'reset count');
'''

    result = subprocess.run([node, "-e", harness], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr

    empty_harness = r'''
const assert = (condition, message) => { if (!condition) throw new Error(message); };
class Control {
  constructor() { this.value = ''; this.disabled = true; this.listeners = {}; }
  addEventListener(type, handler) { this.listeners[type] = handler; }
}
const search = new Control();
const assessment = new Control();
const confidence = new Control();
const findings = new Control();
const evidence = new Control();
const count = { textContent: '' };
const document = {
  querySelector: (selector) => ({
    '[name="filter-search"]': search,
    '[name="filter-assessment"]': assessment,
    '[name="filter-confidence"]': confidence,
    '[name="filter-findings"]': findings,
    '[name="filter-evidence"]': evidence,
    '#filter-count': count
  })[selector],
  querySelectorAll: (selector) => {
    assert(selector === '#capability-map > .capability[data-filter-name]', 'row selector');
    return [];
  }
};
''' + script + r'''
assert([search, assessment, confidence, findings, evidence].every((control) => !control.disabled), 'controls enabled');
assert(count.textContent === 'Showing 0 of 0 capabilities.', 'empty source count');
'''
    empty_result = subprocess.run(
        [node, "-e", empty_harness], capture_output=True, text=True, check=False
    )
    assert empty_result.returncode == 0, empty_result.stderr


def test_cockpit_filter_never_hides_trust_or_gap_context(overview_store: CkmStore) -> None:
    batch = overview_store.load_projection_batch()
    rendered = render_overview_html(overview_store, cockpit=CockpitRenderContext(batch=batch))
    script = _cockpit_filter_script(rendered)

    assert script.count("#capability-map > .capability[data-filter-name]") == 1
    assert script.count("row.hidden") == 1
    assert f"Showing {len(batch.capabilities)} of {len(batch.capabilities)} capabilities." in rendered
    for marker in (
        'class="cockpit-trust"',
        'class="cockpit-hazards"',
        'class="cockpit-comparison',
        'class="subsystem-counts"',
        'class="gaps-panel"',
        'id="proposals-heading"',
    ):
        section = rendered.split(marker, 1)[1].split("</section>", 1)[0]
        assert "data-filter-" not in section
    footer = rendered.split('class="projection-footer"', 1)[1].split("</footer>", 1)[0]
    assert "data-filter-" not in footer


def test_cockpit_filter_controls_are_accessible_and_honest(overview_store: CkmStore) -> None:
    rendered = render_overview_html(
        overview_store,
        cockpit=CockpitRenderContext(batch=overview_store.load_projection_batch()),
    )

    for control_id, label in (
        ("filter-search", "Search name, definition, public ID, or boundary"),
        ("filter-assessment", "Assessment freshness"),
        ("filter-confidence", "Confidence"),
        ("filter-findings", "Findings"),
        ("filter-evidence", "Evidence lifecycle"),
    ):
        assert f'<label for="{control_id}">{label}</label>' in rendered
        assert re.search(rf'id="{control_id}"[^>]* disabled[^>]*aria-controls="capability-map"', rendered)
    assert '<p id="filter-count" aria-live="polite" aria-atomic="true">' in rendered
    assert "No capabilities match the selected filters." in _cockpit_filter_script(rendered)
    assert "Filter capability rows only; trust, hazards, comparison, gaps, proposals, and provenance remain visible." in rendered


def test_cockpit_preserves_evidence_profile_count_context(
    fanout_overview_store: CkmStore,
) -> None:
    context = CockpitRenderContext(batch=fanout_overview_store.load_projection_batch())
    cockpit = render_overview_html(
        fanout_overview_store,
        generated_at="2026-07-25T10:00:00Z",
        cockpit=context,
    )
    default = render_overview_html(
        fanout_overview_store,
        generated_at="2026-07-25T10:00:00Z",
    )

    for rendered in (cockpit, default):
        assert 'data-subsystem-name="Retrieval subsystem"' in rendered
        assert 'data-distinct-artifacts="3"' in rendered
        assert 'data-shared-evidence="40.0%"' in rendered
    assert "Cockpit trust frame" in cockpit
    assert "Cockpit trust frame" not in default


def test_cockpit_uses_one_projection_batch_without_mutation(
    overview_store: CkmStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    batch = overview_store.load_projection_batch()
    calls = 0

    def load_once(**_: int) -> object:
        nonlocal calls
        calls += 1
        return batch

    monkeypatch.setattr(overview_store, "load_projection_batch", load_once)
    before = overview_store.state_identity()
    render_overview_html(overview_store, cockpit=CockpitRenderContext(batch=batch))
    assert calls == 0
    assert overview_store.state_identity() == before


def test_cockpit_trust_frame_binds_complete_projection_identity(overview_store: CkmStore) -> None:
    batch = overview_store.load_projection_batch()
    rendered = render_overview_html(
        overview_store,
        generated_at="2026-07-25T10:00:00Z",
        cockpit=CockpitRenderContext(batch=batch),
    )
    for value in (
        batch.state_identity.epoch,
        str(batch.state_identity.state_revision),
        str(batch.state_identity.schema_version),
        "fixture=two",
    ):
        assert value in rendered
    for label in (
        "capabilities",
        "artifacts",
        "evidence edges",
        "assessments",
        "findings",
        "projection-input digest",
    ):
        assert label in rendered


def test_cockpit_empty_store_keeps_fixed_information_architecture(tmp_path: Path) -> None:
    store = CkmStore(tmp_path / "empty-cockpit.sqlite3")
    store.ensure_schema()
    rendered = render_overview_html(
        store,
        generated_at="2026-07-25T10:00:00Z",
        cockpit=CockpitRenderContext(batch=store.load_projection_batch()),
    )
    headings = (
        "Cockpit trust frame",
        "Interpretation hazards",
        "Comparison",
        "Filters",
        "Capability map",
        "Current gaps",
        "Proposal drafts",
    )
    assert all(heading in rendered for heading in headings)
    assert (
        rendered.index("Cockpit trust frame")
        < rendered.index("Interpretation hazards")
        < rendered.index("Comparison")
        < rendered.index("Filters")
        < rendered.index("Capability map")
        < rendered.index("Current gaps")
        < rendered.index("Proposal drafts")
    )
    assert "Is this projection fresh and complete enough to inspect?" in rendered
    assert "What differs between the two newest active retained observation records" in rendered
    assert "Where is evidence weakest?" in rendered
    assert "What should not be taken at face value?" in rendered


def test_cockpit_cli_fails_closed_before_writing_partial_output(
    overview_store: CkmStore, tmp_path: Path
) -> None:
    database = tmp_path / "missing" / "ckm.sqlite3"
    output = tmp_path / "cockpit.html"
    result = CliRunner().invoke(
        builderops,
        ["--db-path", str(database), "ckm", "overview", "--cockpit", "--out", str(output)],
    )
    assert result.exit_code != 0
    assert not database.exists()
    assert not output.exists()

    _make_snapshot_exceed_default(overview_store)
    oversized_output = tmp_path / "oversized.html"
    oversized = CliRunner().invoke(
        builderops,
        [
            "--db-path",
            str(overview_store.db_path),
            "ckm",
            "overview",
            "--cockpit",
            "--out",
            str(oversized_output),
        ],
    )
    assert oversized.exit_code != 0
    assert "snapshot" in oversized.output
    assert not oversized_output.exists()

    with sqlite3.connect(overview_store.db_path) as conn:
        conn.execute("UPDATE ckm_state SET schema_version = 999 WHERE singleton = 1")
    unsupported_output = tmp_path / "unsupported.html"
    unsupported = CliRunner().invoke(
        builderops,
        [
            "--db-path",
            str(overview_store.db_path),
            "ckm",
            "overview",
            "--cockpit",
            "--out",
            str(unsupported_output),
        ],
    )
    assert unsupported.exit_code != 0
    assert not unsupported_output.exists()


def test_cockpit_render_is_byte_deterministic(overview_store: CkmStore) -> None:
    batch = overview_store.load_projection_batch()
    context = CockpitRenderContext(batch=batch)
    assert render_overview_html(
        overview_store, generated_at="2026-07-25T10:00:00Z", cockpit=context
    ) == render_overview_html(overview_store, generated_at="2026-07-25T10:00:00Z", cockpit=context)


def test_cockpit_hazards_are_snapshot_bound_and_deterministic(
    overview_store: CkmStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    batch = overview_store.load_projection_batch()
    monkeypatch.setattr(
        overview_store, "load_projection_batch", lambda **_: pytest.fail("extra store read")
    )
    context = CockpitRenderContext(batch=batch)
    first = render_overview_html(
        overview_store, generated_at="2026-07-25T10:00:00Z", cockpit=context
    )
    second = render_overview_html(
        overview_store, generated_at="2026-07-25T10:00:00Z", cockpit=context
    )
    assert first == second
    hazards = first.split('<section class="cockpit-hazards"', 1)[1].split("</section>", 1)[0]
    assert (
        hazards.index('data-hazard-kind="stale"')
        < hazards.index('data-hazard-kind="unassessed"')
        < hazards.index('data-hazard-kind="candidate-heavy"')
    )


def test_cockpit_hazards_render_observed_states_without_coercion(
    overview_store: CkmStore, fanout_overview_store: CkmStore
) -> None:
    original = next(
        iter(overview_store.load_projection_batch().assessments_by_capability.values())
    ).assessment
    second_capability = next(
        capability
        for capability in overview_store.list_capabilities()
        if capability.id != original.capability_id
    )
    second_statuses = dict(original.dimension_status)
    second_statuses["documentation_quality"] = "unsupported"
    overview_store.append_assessment(
        capability_id=second_capability.id,
        scores=original.scores,
        citations=original.citations,
        dimension_status=second_statuses,
        candidate_shares=original.candidate_shares,
        formula_ids=original.formula_ids,
        aggregate=original.aggregate,
        aggregate_formula_id=original.aggregate_formula_id,
        low_confidence=original.low_confidence,
        edge_fingerprint="hazard-second-fingerprint",
        watermark_set=original.watermark_set,
    )
    rendered = render_overview_html(
        overview_store, cockpit=CockpitRenderContext(batch=overview_store.load_projection_batch())
    )
    assert 'data-hazard-kind="stale"' in rendered
    assert 'data-hazard-kind="unassessed"' in rendered
    assert 'data-hazard-kind="unsupported" data-value-state="unsupported"' in rendered
    assert 'data-hazard-kind="candidate-heavy"' in rendered
    assert 'data-hazard-kind="unassessed" data-value-state="unassessed"' in rendered
    assert "documentation quality: unassessed for 1 assessed capability:" in rendered
    assert "documentation quality: unsupported for 1 assessed capability:" in rendered
    assert "functional completeness: candidate-heavy for 2 assessed capabilities:" in rendered
    assert "fixture: assessment=one → current=two" in rendered
    assert "Unassessed is not a zero score." in rendered
    shared = render_overview_html(
        fanout_overview_store,
        cockpit=CockpitRenderContext(batch=fanout_overview_store.load_projection_batch()),
    )
    assert 'data-hazard-kind="shared-evidence"' in shared
    assert "Shared evidence indicator applies to 3 capabilities:" in shared


def test_snapshot_wide_zero_is_descriptive_not_diagnostic(overview_store: CkmStore) -> None:
    original = next(
        iter(overview_store.load_projection_batch().assessments_by_capability.values())
    ).assessment
    unavailable = next(
        capability
        for capability in overview_store.list_capabilities()
        if capability.id != original.capability_id
    )

    def append_state(name: str, operational_state: str) -> CkmCapability:
        capability = overview_store.upsert_capability(
            identity_key=f"hazard:zero:{name}",
            name=name,
            definition="Fixture.",
            existence_provenance="fixture",
            lifecycle="confirmed",
        )
        statuses = dict(original.dimension_status)
        statuses["operational_readiness"] = operational_state
        overview_store.append_assessment(
            capability_id=capability.id,
            scores=original.scores,
            citations=original.citations,
            dimension_status=statuses,
            candidate_shares=original.candidate_shares,
            formula_ids=original.formula_ids,
            aggregate=original.aggregate,
            aggregate_formula_id=original.aggregate_formula_id,
            low_confidence=original.low_confidence,
            edge_fingerprint=f"hazard-zero-{name}",
            watermark_set=original.watermark_set,
        )
        return capability

    second_zero = append_state("Second zero", "measured")
    unsupported = append_state("Unsupported zero", "unsupported")
    unassessed = append_state("Unassessed zero", "unassessed")
    rendered = render_overview_html(
        overview_store,
        cockpit=CockpitRenderContext(batch=overview_store.load_projection_batch()),
    )
    zero_row = re.search(
        r'<li[^>]*data-hazard-kind="snapshot-wide-zero"[^>]*>(.*?)</li>',
        rendered,
        re.S,
    )
    assert zero_row is not None
    row = zero_row.group(1)
    caveat = (
        "Snapshot-wide zero: operational readiness is 0.00 for every assessed capability in this snapshot. "
        "CKM cannot determine whether that reflects missing evidence, current metric coverage, or portfolio state."
    )
    assert caveat in row
    assert row.index(caveat) < row.index("Affected: 2 assessed capabilities:")
    original_capability = overview_store.get_capability(original.capability_id)
    assert original_capability is not None
    expected = sorted(
        (original_capability, second_zero),
        key=lambda capability: (capability.public_id.casefold(), capability.id),
    )
    assert [
        (f"#cap-{capability.id}", capability.public_id) for capability in expected
    ] == re.findall(r'href="([^"]+)">([^<]+)</a>', row)
    assert unavailable.public_id not in row
    assert unsupported.public_id not in row
    assert unassessed.public_id not in row


def test_new_cockpit_interpretation_copy_avoids_banned_rhetoric(overview_store: CkmStore) -> None:
    rendered = render_overview_html(
        overview_store, cockpit=CockpitRenderContext(batch=overview_store.load_projection_batch())
    )
    authored = " ".join(
        re.findall(
            r'<(?:section|li)[^>]*data-renderer-authored="interpretation"[^>]*>(.*?)</(?:section|li)>',
            rendered,
            re.S,
        )
    )
    assert authored
    assert not re.search(
        r"\b(rank|cause|regression|trend|forecast|urgent|priority|action|diagnos)\w*\b",
        authored,
        re.I,
    )


def test_cockpit_hazard_empty_and_unavailable_states_are_explicit(tmp_path: Path) -> None:
    empty = CkmStore(tmp_path / "hazard-empty.sqlite3")
    empty.ensure_schema()
    rendered = render_overview_html(
        empty, cockpit=CockpitRenderContext(batch=empty.load_projection_batch())
    )
    assert "No listed interpretation hazards for this captured projection." in rendered
    unavailable = CkmStore(tmp_path / "hazard-unavailable.sqlite3")
    unavailable.ensure_schema()
    capability = unavailable.upsert_capability(
        identity_key="hazard:unavailable",
        name="Unavailable",
        definition="Fixture.",
        existence_provenance="fixture",
        lifecycle="confirmed",
    )
    output = render_overview_html(
        unavailable, cockpit=CockpitRenderContext(batch=unavailable.load_projection_batch())
    )
    assert "Assessment unavailable for 1 capability" in output
    assert capability.public_id in output
    unavailable.upsert_capability(
        identity_key="hazard:unavailable-second",
        name="Unavailable second",
        definition="Fixture.",
        existence_provenance="fixture",
        lifecycle="confirmed",
    )
    plural_output = render_overview_html(
        unavailable,
        cockpit=CockpitRenderContext(batch=unavailable.load_projection_batch()),
    )
    assert "Assessment unavailable for 2 capabilities:" in plural_output


def test_cockpit_hazard_links_preserve_map_and_gap_order(overview_store: CkmStore) -> None:
    rendered = render_overview_html(
        overview_store, cockpit=CockpitRenderContext(batch=overview_store.load_projection_batch())
    )
    hazards = rendered.split('<section class="cockpit-hazards"', 1)[1].split("</section>", 1)[0]
    assert re.search(r'href="#cap-[^"]+"', hazards)
    assert rendered.index("Capability map") < rendered.index("Current gaps")
    assert 'href="#gaps-' in rendered


def _retain_for_cockpit(
    overview_store: CkmStore, *, retained_at: str, metric_id: str = "capability_population"
) -> tuple[MetricRetentionStore, object]:
    result = CkmQueryService(overview_store.db_path).list_capabilities()
    assert isinstance(result, ResultEnvelope)
    retention = MetricRetentionStore(
        overview_store.db_path.with_name(f"{overview_store.db_path.stem}-metric-samples.sqlite")
    )
    return retention, retention.retain(result, retained_at=retained_at, metric_id=metric_id)


def _cockpit_cli(overview_store: CkmStore, output: Path) -> object:
    return CliRunner().invoke(
        builderops,
        ["--db-path", str(overview_store.db_path), "ckm", "overview", "--cockpit", "--out", str(output)],
    )


def _valid_o1b_payload(
    *, states: list[dict[str, object]] | None = None, sample_ids: tuple[str, str] = ("older", "newer")
) -> dict[str, object]:
    values = states or [
        {"state": "measured", "value": 2},
        {"state": "measured", "value": 5},
    ]
    return {
        "kind": "ckm_compatible_observation_comparison_v1",
        "inputs": [
            {"sample_id": sample_ids[0], "observation_id": "older-observation", "semantic_digest": "a"},
            {"sample_id": sample_ids[1], "observation_id": "newer-observation", "semantic_digest": "b"},
        ],
        "compatibility": {"compatible": True, "bindings": {"metric.id": "fixture"}},
        "components": [
            {
                "component": "fixture",
                "states": values,
                "numeric_delta": comparison_module._component_delta(values),
                "state_transition": [str(value["state"]) for value in values],
            }
        ],
        "provenance": [[], []],
        "freshness": [{}, {}],
        "aggregate": {"label": "human_advisory_only"},
        "limitations": ["fixture limitation"],
        "comparison_digest": "fixture-digest",
    }


def _retention_storage_identity(path: Path) -> tuple[tuple[object, ...], tuple[tuple[object, ...], ...]]:
    siblings = tuple(
        sorted(
            (
                item.name,
                item.stat().st_mode,
                item.stat().st_ino,
                item.stat().st_size,
                item.stat().st_mtime_ns,
            )
            for item in path.parent.iterdir()
            if item.name == path.name
            or item.name
            in {
                f"{path.name}-journal",
                f"{path.name}-shm",
                f"{path.name}-wal",
            }
        )
    )
    if not path.exists():
        return (), siblings
    with sqlite3.connect(
        f"{path.resolve().as_uri()}?mode=ro&immutable=1", uri=True
    ) as connection:
        schema = tuple(
            connection.execute(
                "SELECT type, name, tbl_name, sql FROM sqlite_schema "
                "ORDER BY type, name, tbl_name"
            ).fetchall()
        )
    return schema, siblings


def test_cockpit_cli_compares_exact_newest_pair_oldest_first(
    overview_store: CkmStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, oldest = _retain_for_cockpit(overview_store, retained_at="2026-07-20T00:00:00Z")
    _, older = _retain_for_cockpit(overview_store, retained_at="2026-07-21T00:00:00Z")
    _, newer = _retain_for_cockpit(overview_store, retained_at="2026-07-22T00:00:00Z")
    retention_path = overview_store.db_path.with_name(f"{overview_store.db_path.stem}-metric-samples.sqlite")
    with sqlite3.connect(retention_path) as conn:
        conn.execute(
            "UPDATE ckm_metric_sample_v1 SET retained_at = '2026-07-22T00:00:00Z' "
            "WHERE sample_id IN (?, ?)",
            (older.sample_id, newer.sample_id),
        )
    observed: list[tuple[str, ...]] = []

    def compare_once(_: MetricRetentionStore, sample_ids: tuple[str, ...]) -> dict[str, object]:
        observed.append(sample_ids)
        return _valid_o1b_payload(sample_ids=(sample_ids[0], sample_ids[1]))

    monkeypatch.setattr(builderops_cli_module, "compare_retained_observations", compare_once)
    output = tmp_path / "cockpit.html"

    result = _cockpit_cli(overview_store, output)

    assert result.exit_code == 0
    rendered = output.read_text(encoding="utf-8")
    selected = tuple(sorted((older.sample_id, newer.sample_id), reverse=True))
    assert observed == [(selected[1], selected[0])]
    assert rendered.index(selected[1]) < rendered.index(selected[0])
    assert oldest.sample_id not in rendered
    assert 'data-component="fixture"' in rendered
    assert 'numeric delta: <span class="comparison-delta">3</span>' in rendered


def test_cockpit_cli_selects_chronological_pair_across_valid_iso_variants(
    overview_store: CkmStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, deceptive_offset = _retain_for_cockpit(
        overview_store,
        retained_at="2026-07-22T00:00:00+02:00",
    )
    _, fractional_oldest = _retain_for_cockpit(
        overview_store,
        retained_at="2026-07-21T22:30:00.00000000000000000001+00:00",
    )
    _, fractional_older = _retain_for_cockpit(
        overview_store,
        retained_at="2026-07-21T22:30:00.00000000000000000002Z",
    )
    _, fractional_newer = _retain_for_cockpit(
        overview_store,
        retained_at="2026-07-21T22:30:00.00000000000000000003+00:00",
    )
    retention_path = overview_store.db_path.with_name(
        f"{overview_store.db_path.stem}-metric-samples.sqlite"
    )
    renamed_ids = {
        deceptive_offset.sample_id: "sample-offset-deceptive",
        fractional_oldest.sample_id: "sample-z-fraction-oldest",
        fractional_older.sample_id: "sample-y-fraction-older",
        fractional_newer.sample_id: "sample-a-fraction-newer",
    }
    with sqlite3.connect(retention_path) as conn:
        for original_id, renamed_id in renamed_ids.items():
            conn.execute(
                "UPDATE ckm_metric_sample_v1 SET sample_id = ? WHERE sample_id = ?",
                (renamed_id, original_id),
            )
    observed: list[tuple[str, ...]] = []

    def compare_once(_: MetricRetentionStore, sample_ids: tuple[str, ...]) -> dict[str, object]:
        observed.append(sample_ids)
        return _valid_o1b_payload(sample_ids=(sample_ids[0], sample_ids[1]))

    monkeypatch.setattr(builderops_cli_module, "compare_retained_observations", compare_once)
    output = tmp_path / "chronological-cockpit.html"

    result = _cockpit_cli(overview_store, output)

    assert result.exit_code == 0
    assert observed == [
        (
            renamed_ids[fractional_older.sample_id],
            renamed_ids[fractional_newer.sample_id],
        )
    ]
    rendered = output.read_text(encoding="utf-8")
    assert renamed_ids[deceptive_offset.sample_id] not in rendered
    assert renamed_ids[fractional_oldest.sample_id] not in rendered

    with sqlite3.connect(retention_path) as conn:
        conn.execute(
            "UPDATE ckm_metric_sample_v1 "
            "SET retained_at = '2026-07-22T00:30:00.00000000000000000003+02:00' "
            "WHERE sample_id = ?",
            (renamed_ids[fractional_older.sample_id],),
        )
    newest_first = sorted(
        (
            renamed_ids[fractional_older.sample_id],
            renamed_ids[fractional_newer.sample_id],
        ),
        reverse=True,
    )
    assert comparison_module.newest_active_retained_sample_ids(
        MetricRetentionStore(retention_path)
    ) == (newest_first[1], newest_first[0])


def test_cockpit_does_not_search_older_compatible_pair(
    overview_store: CkmStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, oldest = _retain_for_cockpit(overview_store, retained_at="2026-07-20T00:00:00Z")
    _, older = _retain_for_cockpit(overview_store, retained_at="2026-07-21T00:00:00Z")
    _, newer = _retain_for_cockpit(
        overview_store, retained_at="2026-07-22T00:00:00Z", metric_id="provenance_coverage"
    )
    observed: list[str] = []
    original = comparison_module._observation

    def record(store: MetricRetentionStore, sample_id: str) -> dict[str, object]:
        observed.append(sample_id)
        return original(store, sample_id)

    monkeypatch.setattr(comparison_module, "_observation", record)
    output = tmp_path / "cockpit.html"
    result = _cockpit_cli(overview_store, output)

    assert result.exit_code == 0
    assert observed == [older.sample_id, newer.sample_id]
    assert oldest.sample_id not in observed
    rendered = output.read_text(encoding="utf-8")
    assert "incompatible_observations" in rendered
    assert "No older retained row was searched." in rendered


def test_cockpit_chronology_repair_preserves_limit_two_and_no_fallback(
    overview_store: CkmStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    retention, deceptive_oldest = _retain_for_cockpit(
        overview_store,
        retained_at="2026-07-22T00:00:00+02:00",
    )
    _, chronological_older = _retain_for_cockpit(
        overview_store,
        retained_at="2026-07-21T22:30:00.000001Z",
    )
    _, chronological_newer = _retain_for_cockpit(
        overview_store,
        retained_at="2026-07-21T22:30:00.000002+00:00",
        metric_id="provenance_coverage",
    )
    before = _retention_storage_identity(retention.path)
    selected_reads: list[str] = []
    statements: list[str] = []
    original_connect = sqlite3.connect
    original_observation = comparison_module._observation

    def traced_connect(*args: object, **kwargs: object) -> sqlite3.Connection:
        connection = original_connect(*args, **kwargs)
        connection.set_trace_callback(statements.append)
        return connection

    def record_observation(
        store: MetricRetentionStore,
        sample_id: str,
    ) -> dict[str, object]:
        selected_reads.append(sample_id)
        return original_observation(store, sample_id)

    monkeypatch.setattr(comparison_module.sqlite3, "connect", traced_connect)
    monkeypatch.setattr(comparison_module, "_observation", record_observation)
    output = tmp_path / "chronology-no-fallback.html"

    result = _cockpit_cli(overview_store, output)

    assert result.exit_code == 0
    selector_statements = [
        statement
        for statement in statements
        if "SELECT sample_id FROM ckm_metric_sample_v1" in statement
    ]
    assert len(selector_statements) == 1
    assert "LIMIT 2" in selector_statements[0]
    assert selected_reads == [
        chronological_older.sample_id,
        chronological_newer.sample_id,
    ]
    assert deceptive_oldest.sample_id not in selected_reads
    rendered = output.read_text(encoding="utf-8")
    assert "incompatible_observations" in rendered
    assert 'class="comparison-component"' not in rendered
    assert "No older retained row was searched." in rendered
    assert _retention_storage_identity(retention.path) == before


@pytest.mark.parametrize(
    "invalid_retained_at",
    ["not-an-iso-instant", "2026-07-22T00:00:00"],
)
def test_cockpit_invalid_retained_timestamp_refuses_typed(
    overview_store: CkmStore,
    tmp_path: Path,
    invalid_retained_at: str,
) -> None:
    retention, _ = _retain_for_cockpit(
        overview_store,
        retained_at="2026-07-21T00:00:00Z",
    )
    _, selected = _retain_for_cockpit(
        overview_store,
        retained_at="2026-07-22T00:00:00Z",
    )
    with sqlite3.connect(retention.path) as conn:
        conn.execute(
            "UPDATE ckm_metric_sample_v1 SET retained_at = ? WHERE sample_id = ?",
            (invalid_retained_at, selected.sample_id),
        )
    before = _retention_storage_identity(retention.path)
    output = tmp_path / "invalid-retained-at.html"

    result = _cockpit_cli(overview_store, output)

    assert result.exit_code == 0
    assert result.exception is None
    rendered = output.read_text(encoding="utf-8")
    assert "source_unavailable" in rendered
    assert 'class="comparison-component"' not in rendered
    assert "No older retained row was searched." in rendered
    assert _retention_storage_identity(retention.path) == before


def test_cockpit_retention_absent_and_insufficient_states_are_read_only(
    overview_store: CkmStore, tmp_path: Path
) -> None:
    output = tmp_path / "missing.html"
    retention_path = overview_store.db_path.with_name(f"{overview_store.db_path.stem}-metric-samples.sqlite")
    missing_before = _retention_storage_identity(retention_path)
    result = _cockpit_cli(overview_store, output)
    assert result.exit_code == 0
    assert "source_unavailable" in output.read_text(encoding="utf-8")
    assert not retention_path.exists()
    assert _retention_storage_identity(retention_path) == missing_before

    with sqlite3.connect(retention_path) as conn:
        conn.execute("CREATE TABLE incomplete (id TEXT)")
    incomplete_before = _retention_storage_identity(retention_path)
    incomplete = tmp_path / "incomplete.html"
    result = _cockpit_cli(overview_store, incomplete)
    assert result.exit_code == 0
    assert "source_unavailable" in incomplete.read_text(encoding="utf-8")
    assert _retention_storage_identity(retention_path) == incomplete_before

    retention_path.unlink()
    MetricRetentionStore(retention_path).initialize()
    empty_before = _retention_storage_identity(retention_path)
    empty = tmp_path / "empty.html"
    result = _cockpit_cli(overview_store, empty)
    assert result.exit_code == 0
    assert "insufficient_retained_samples" in empty.read_text(encoding="utf-8")
    assert "&quot;count&quot;:0" in empty.read_text(encoding="utf-8")
    assert _retention_storage_identity(retention_path) == empty_before

    retention, _ = _retain_for_cockpit(overview_store, retained_at="2026-07-21T00:00:00Z")
    before = _retention_storage_identity(retention.path)
    insufficient = tmp_path / "insufficient.html"
    result = _cockpit_cli(overview_store, insufficient)
    assert result.exit_code == 0
    rendered = insufficient.read_text(encoding="utf-8")
    assert "insufficient_retained_samples" in rendered and "&quot;count&quot;:1" in rendered
    assert _retention_storage_identity(retention.path) == before


@pytest.mark.parametrize(
    "mutation, expected",
    [
        ("UPDATE ckm_metric_sample_v1 SET expires_at = '2000-01-01T00:00:00Z' WHERE sample_id = ?", "source_unavailable"),
        ("UPDATE ckm_metric_sample_v1 SET source_payload = NULL WHERE sample_id = ?", "tampered_retained_source"),
        ("UPDATE ckm_metric_sample_v1 SET source_payload = 'not-a-blob' WHERE sample_id = ?", "tampered_retained_source"),
        ("UPDATE ckm_metric_sample_v1 SET source_payload = x'7B7D' WHERE sample_id = ?", "corrupt_retained_observation"),
    ],
)
def test_cockpit_selected_source_refusal_is_all_or_nothing(
    overview_store: CkmStore, tmp_path: Path, mutation: str, expected: str
) -> None:
    retention, _ = _retain_for_cockpit(overview_store, retained_at="2026-07-21T00:00:00Z")
    _, selected = _retain_for_cockpit(overview_store, retained_at="2026-07-22T00:00:00Z")
    with sqlite3.connect(retention.path) as conn:
        conn.execute(mutation, (selected.sample_id,))
    output = tmp_path / "refusal.html"

    result = _cockpit_cli(overview_store, output)

    assert result.exit_code == 0
    rendered = output.read_text(encoding="utf-8")
    assert expected in rendered
    assert 'class="comparison-component"' not in rendered
    assert "No older retained row was searched." in rendered


def test_cockpit_selected_observation_source_mismatch_refuses(
    overview_store: CkmStore, tmp_path: Path
) -> None:
    retention, _ = _retain_for_cockpit(overview_store, retained_at="2026-07-21T00:00:00Z")
    _, selected = _retain_for_cockpit(overview_store, retained_at="2026-07-22T00:00:00Z")
    with sqlite3.connect(retention.path) as conn:
        raw = conn.execute(
            "SELECT observation_json FROM ckm_metric_sample_v1 WHERE sample_id = ?", (selected.sample_id,)
        ).fetchone()[0]
        forged = json.loads(raw)
        forged["snapshot"]["snapshot_digest"] = "forged"
        conn.execute(
            "UPDATE ckm_metric_sample_v1 SET observation_json = ? WHERE sample_id = ?",
            (json.dumps(forged, sort_keys=True, separators=(",", ":")), selected.sample_id),
        )
    output = tmp_path / "mismatch-refusal.html"
    result = _cockpit_cli(overview_store, output)

    assert result.exit_code == 0
    rendered = output.read_text(encoding="utf-8")
    assert "observation_source_mismatch" in rendered
    assert 'class="comparison-component"' not in rendered


def test_cockpit_selected_malformed_nested_payload_refuses_typed(
    overview_store: CkmStore, tmp_path: Path
) -> None:
    retention, _ = _retain_for_cockpit(
        overview_store,
        retained_at="2026-07-21T00:00:00Z",
    )
    _, selected = _retain_for_cockpit(
        overview_store,
        retained_at="2026-07-22T00:00:00Z",
    )
    with sqlite3.connect(retention.path) as conn:
        source_bytes = conn.execute(
            "SELECT source_payload FROM ckm_metric_sample_v1 WHERE sample_id = ?",
            (selected.sample_id,),
        ).fetchone()[0]
        source = json.loads(bytes(source_bytes).decode("utf-8"))
        assert source["resources"]
        source["resources"][0]["values"] = []
        canonical_source = json.dumps(
            source,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        conn.execute(
            "UPDATE ckm_metric_sample_v1 "
            "SET source_payload = ?, source_digest = ? WHERE sample_id = ?",
            (
                sqlite3.Binary(canonical_source),
                canonical_digest(source),
                selected.sample_id,
            ),
        )
    output = tmp_path / "malformed-nested-refusal.html"

    result = _cockpit_cli(overview_store, output)

    assert result.exit_code == 0
    assert result.exception is None
    rendered = output.read_text(encoding="utf-8")
    assert "corrupt_retained_observation" in rendered
    assert 'class="comparison-component"' not in rendered
    assert "No older retained row was searched." in rendered
    assert "Traceback" not in result.output


def test_cockpit_selected_source_refusal_race_is_all_or_nothing(
    overview_store: CkmStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    retention, _ = _retain_for_cockpit(overview_store, retained_at="2026-07-21T00:00:00Z")
    _, selected = _retain_for_cockpit(overview_store, retained_at="2026-07-22T00:00:00Z")
    original = comparison_module.compare_retained_observations

    def prune_after_selection(store: MetricRetentionStore, sample_ids: tuple[str, ...]) -> dict[str, object]:
        with sqlite3.connect(retention.path) as conn:
            conn.execute(
                "UPDATE ckm_metric_sample_v1 SET lifecycle = 'required_deletion', source_payload = NULL "
                "WHERE sample_id = ?",
                (selected.sample_id,),
            )
        return original(store, sample_ids)

    monkeypatch.setattr(builderops_cli_module, "compare_retained_observations", prune_after_selection)
    output = tmp_path / "raced-refusal.html"
    result = _cockpit_cli(overview_store, output)

    assert result.exit_code == 0
    rendered = output.read_text(encoding="utf-8")
    assert "source_unavailable" in rendered
    assert 'class="comparison-component"' not in rendered
    assert "No older retained row was searched." in rendered


def test_cockpit_renders_bound_o1b_delta_and_fixed_disclaimer(
    overview_store: CkmStore, tmp_path: Path
) -> None:
    _retain_for_cockpit(overview_store, retained_at="2026-07-21T00:00:00Z")
    _retain_for_cockpit(overview_store, retained_at="2026-07-22T00:00:00Z")
    output = tmp_path / "bound.html"

    result = _cockpit_cli(overview_store, output)

    assert result.exit_code == 0
    rendered = output.read_text(encoding="utf-8")
    for marker in (
        "comparison-inputs",
        "comparison-result",
        "comparison-bindings",
        "comparison-provenance",
        "comparison-freshness",
        "comparison-limitations",
        "Difference between two snapshots. Not a trend, cause, or forecast.",
    ):
        assert marker in rendered


def test_cockpit_comparison_preserves_tagged_state_transitions(overview_store: CkmStore) -> None:
    tagged = _valid_o1b_payload(
        states=[
            {"state": "missing", "reason": "not captured"},
            {"state": "unsupported", "reason": "not defined"},
        ]
    )
    rendered = render_overview_html(
        overview_store,
        cockpit=CockpitRenderContext(
            batch=overview_store.load_projection_batch(),
            comparison=tagged,
        ),
    )
    assert "missing: not captured" in rendered
    assert "unsupported: not defined" in rendered
    assert "numeric delta" not in rendered
    assert "comparison-result" in rendered

    exact_kind_incomplete = {"kind": "ckm_compatible_observation_comparison_v1"}
    mixed = dict(tagged)
    mixed["error"] = CkmContractError(
        "source_unavailable", "mixed envelope must refuse", {}
    ).to_dict()
    for comparison in (
        None,
        {},
        {"kind": "unknown"},
        exact_kind_incomplete,
        mixed,
        {"error": {}},
    ):
        refusal = render_overview_html(
            overview_store,
            cockpit=CockpitRenderContext(
                batch=overview_store.load_projection_batch(), comparison=comparison
            ),
        )
        assert "source_unavailable" in refusal
        assert "comparison-result" not in refusal
        assert 'class="comparison-component"' not in refusal
    valid_refusal = {"error": CkmContractError("incompatible_observations", "incompatible", {}).to_dict()}
    assert "incompatible_observations" in render_overview_html(
        overview_store,
        cockpit=CockpitRenderContext(batch=overview_store.load_projection_batch(), comparison=valid_refusal),
    )


def test_cockpit_recovery_commands_match_click_help(overview_store: CkmStore) -> None:
    rendered = render_overview_html(
        overview_store, cockpit=CockpitRenderContext(batch=overview_store.load_projection_batch())
    )
    database = str(overview_store.db_path)
    measure_help = CliRunner().invoke(
        _root, ["builderops", "--db-path", database, "ckm", "measure", "--help"]
    )
    compare_help = CliRunner().invoke(
        _root,
        [
            "builderops",
            "--db-path",
            database,
            "ckm",
            "compare",
            "--sample-id",
            "older",
            "--sample-id",
            "newer",
            "--help",
        ],
    )
    invalid_former_ordering = CliRunner().invoke(
        _root, ["--db-path", database, "ckm", "measure", "--help"]
    )
    assert measure_help.exit_code == compare_help.exit_code == 0
    assert invalid_former_ordering.exit_code == 2
    assert "No such option: --db-path" in invalid_former_ordering.output
    assert "--retain" in measure_help.output
    assert "--sample-id" in compare_help.output
    comparison = rendered.split('<section class="cockpit-comparison"', 1)[1].split(
        "</section>", 1
    )[0]
    assert re.findall(r"<code>(python -m app\.builderops[^<]+)</code>", comparison) == [
        "python -m app.builderops builderops --db-path &lt;db&gt; ckm measure --retain",
        "python -m app.builderops builderops --db-path &lt;db&gt; ckm compare "
        "--sample-id &lt;older&gt; --sample-id &lt;newer&gt;",
    ]


def _proposal_section(rendered: str) -> str:
    return rendered.split('<section class="cockpit-proposals"', 1)[1].split("</section>", 1)[0]


def _visible_html_text(markup: str) -> str:
    return unescape(re.sub(r"<[^>]+>", "", markup))


def _finding_with(
    finding: CkmFinding,
    *,
    public_id: str | None = None,
    kind: str | None = None,
    dimension: str | None = None,
    statement: str | None = None,
    citations: list[dict[str, object]] | None = None,
) -> CkmFinding:
    return replace(
        finding,
        public_id=public_id or finding.public_id,
        kind=kind or finding.kind,
        dimension=dimension or finding.dimension,
        statement=statement or finding.statement,
        citations=citations if citations is not None else finding.citations,
    )


def _first_batch_finding(batch: CkmProjectionBatch) -> tuple[CkmCapability, CkmFinding]:
    capability_id, findings = next(iter(batch.findings_by_capability.items()))
    capability = next(item for item in batch.capabilities if item.id == capability_id)
    return capability, findings[0]


def test_cockpit_drafts_require_cited_current_finding(overview_store: CkmStore) -> None:
    batch = overview_store.load_projection_batch()
    capability, cited = _first_batch_finding(batch)
    uncited = _finding_with(
        cited,
        public_id="CKM-FIND-UNRESOLVABLE",
        statement="This finding has no resolvable captured source.",
        citations=[{"source_ref": "", "lifecycle": "confirmed"}],
    )
    rendered = render_overview_html(
        overview_store,
        cockpit=CockpitRenderContext(
            batch=replace(batch, findings_by_capability={capability.id: (uncited, cited)})
        ),
    )
    proposals = _proposal_section(rendered)

    assert proposals.count('<pre class="proposal-draft">') == 1
    assert "Eligible drafts: 1 · Ineligible findings: 1 · Total findings: 2." in proposals
    assert cited.statement in proposals
    assert uncited.statement not in proposals

    assessment = batch.assessments_by_capability[capability.id]
    assert assessment.stale_relative_to_evidence
    assert assessment.assessment.scores["operational_readiness"] == 0.0
    no_findings = render_overview_html(
        overview_store,
        cockpit=CockpitRenderContext(
            batch=replace(batch, findings_by_capability={}),
            comparison=_valid_o1b_payload(),
        ),
    )
    no_finding_proposals = _proposal_section(no_findings)
    assert "Interpretation hazards" in no_findings
    assert "comparison-result" in no_findings
    assert "Eligible drafts: 0 · Ineligible findings: 0 · Total findings: 0." in no_finding_proposals
    assert "<pre" not in no_finding_proposals


def test_cockpit_drafts_bind_identity_watermarks_and_verbatim_evidence(
    overview_store: CkmStore,
) -> None:
    batch = overview_store.load_projection_batch()
    capability, finding = _first_batch_finding(batch)
    source_bound = _finding_with(
        finding,
        statement="Verbatim <finding> statement.",
        citations=[
            {"source_ref": "zeta.md", "lifecycle": "confirmed"},
            {"source_ref": "alpha.md", "lifecycle": "candidate"},
            {"source_ref": "zeta.md", "lifecycle": "confirmed"},
            {"source_ref": "source.md", "lifecycle": "candidate"},
            {"source_ref": " source.md ", "lifecycle": "confirmed"},
            {"source_ref": "source.md", "lifecycle": "candidate"},
            {"source_ref": "no-lifecycle.md"},
            {"edge": {"source_ref": "edge-source.md", "lifecycle": "confirmed"}},
            {"artifact": {"source_ref": "artifact-source.md"}},
            {"source_ref": "untrusted-lifecycle.md", "lifecycle": "untrusted"},
            {"source_ref": "list-lifecycle.md", "lifecycle": ["confirmed"]},
            {"source_ref": "dict-lifecycle.md", "lifecycle": {"state": "candidate"}},
            {
                "source_ref": "edge-lifecycle-wins.md",
                "lifecycle": "untrusted",
                "edge": {"source_ref": "edge-lifecycle-wins.md", "lifecycle": "candidate"},
            },
            {
                "source_ref": "mismatched-top.md",
                "lifecycle": "candidate",
                "edge": {"source_ref": "mismatched-edge.md", "lifecycle": "confirmed"},
            },
        ],
    )
    projection = replace(
        batch,
        findings_by_capability={capability.id: (source_bound,)},
        current_watermark_set={"zeta": "3", "alpha": "1", "middle": "2"},
    )
    rendered = render_overview_html(
        overview_store,
        cockpit=CockpitRenderContext(batch=projection),
    )
    draft = re.search(r'<pre class="proposal-draft">(.*?)</pre>', rendered, re.S)
    assert draft is not None
    lines = _visible_html_text(draft.group(1)).splitlines()

    assert lines == [
        "Draft only — not an Issue contract, priority, decision, or ready work.",
        re.fullmatch(r"Projection input digest: [0-9a-f]{64}", lines[1]).group(0),
        f"CKM state: epoch={projection.state_identity.epoch}; revision={projection.state_identity.state_revision}; schema={projection.state_identity.schema_version}",
        "Watermarks: alpha=1, middle=2, zeta=3",
        f"Capability public ID: {capability.public_id}",
        "Observed finding (verbatim): Verbatim <finding> statement.",
        f"Dimension/kind: {source_bound.dimension} / {source_bound.kind}",
        "Cited source(s):  source.md  [confirmed], alpha.md [candidate], artifact-source.md [not captured], dict-lifecycle.md [not captured], edge-lifecycle-wins.md [candidate], edge-source.md [confirmed], list-lifecycle.md [not captured], mismatched-edge.md [confirmed], mismatched-top.md [candidate], no-lifecycle.md [not captured], source.md [candidate], untrusted-lifecycle.md [not captured], zeta.md [confirmed]",
        "Manual review question: Does this cited finding justify a separate governed Issue?",
    ]
    assert re.findall(
        r'<span class="proposal-source-value">(.*?)</span>', draft.group(1), re.S
    ) == [
        "Verbatim &lt;finding&gt; statement.",
        " source.md  [confirmed], alpha.md [candidate], artifact-source.md [not captured], dict-lifecycle.md [not captured], edge-lifecycle-wins.md [candidate], edge-source.md [confirmed], list-lifecycle.md [not captured], mismatched-edge.md [confirmed], mismatched-top.md [candidate], no-lifecycle.md [not captured], source.md [candidate], untrusted-lifecycle.md [not captured], zeta.md [confirmed]",
    ]
    trust_digest = re.search(
        r'projection-input digest: <code>([0-9a-f]{64})</code>', rendered
    )
    assert trust_digest is not None
    assert lines[1] == f"Projection input digest: {trust_digest.group(1)}"


def test_cockpit_draft_order_and_text_are_deterministic(overview_store: CkmStore) -> None:
    batch = overview_store.load_projection_batch()
    capability, original = _first_batch_finding(batch)
    multi_citations = [
        {"source_ref": "zeta.md", "lifecycle": "confirmed"},
        {"source_ref": "source.md", "lifecycle": "candidate"},
        {"source_ref": " source.md ", "lifecycle": "confirmed"},
        {"source_ref": "source.md", "lifecycle": "candidate"},
        {"source_ref": "alpha.md", "lifecycle": "candidate"},
        {"source_ref": "zeta.md", "lifecycle": "confirmed"},
    ]
    first = _finding_with(original, citations=multi_citations)
    reversed_first = _finding_with(original, citations=list(reversed(multi_citations)))
    second = _finding_with(
        first,
        public_id="CKM-FIND-SECOND",
        kind="missing_evidence",
        dimension="functional_completeness",
        statement="A second deterministic finding.",
        citations=list(reversed(multi_citations)),
    )
    forward = replace(batch, findings_by_capability={capability.id: (second, first)})
    reverse = replace(batch, findings_by_capability={capability.id: (reversed_first, second)})
    context = lambda projection: CockpitRenderContext(batch=projection)
    first_render = render_overview_html(
        overview_store, generated_at="2026-07-27T10:00:00Z", cockpit=context(forward)
    )
    second_render = render_overview_html(
        overview_store, generated_at="2026-07-27T10:00:00Z", cockpit=context(reverse)
    )

    assert _proposal_section(first_render) == _proposal_section(second_render)
    assert "Cited source(s):  source.md  [confirmed]" in _visible_html_text(
        _proposal_section(first_render)
    )
    drafts = re.findall(r'<pre class="proposal-draft">(.*?)</pre>', first_render, re.S)
    assert [_visible_html_text(draft).splitlines()[5] for draft in drafts] == [
        f"Observed finding (verbatim): {first.statement}",
        "Observed finding (verbatim): A second deterministic finding.",
    ]


def test_cockpit_drafts_cannot_be_mistaken_for_ready_issue_contracts(
    overview_store: CkmStore,
) -> None:
    batch = overview_store.load_projection_batch()
    capability, finding = _first_batch_finding(batch)
    source_text = _finding_with(
        finding,
        statement="Fixes #123:\n<em>priority implementation direction.</em>",
        citations=[{"source_ref": "<ready>\nwork.md", "lifecycle": "confirmed"}],
    )
    proposals = _proposal_section(
        render_overview_html(
            overview_store,
            cockpit=CockpitRenderContext(
                batch=replace(batch, findings_by_capability={capability.id: (source_text,)})
            ),
        )
    )
    source_values = re.findall(
        r'<span class="proposal-source-value">(.*?)</span>', proposals, re.S
    )
    authored_markup = re.sub(
        r'<span class="proposal-source-value">.*?</span>', "", proposals, flags=re.S
    )
    authored = _visible_html_text(authored_markup)
    authored = authored.replace(
        "Draft only — not an Issue contract, priority, decision, or ready work.", ""
    ).replace("Manual review question: Does this cited finding justify a separate governed Issue?", "")

    assert "Draft only — not an Issue contract, priority, decision, or ready work." in proposals
    assert "Manual review question: Does this cited finding justify a separate governed Issue?" in proposals
    assert [_visible_html_text(value) for value in source_values] == [
        "Fixes #123:\n<em>priority implementation direction.</em>",
        "<ready>\nwork.md [confirmed]",
    ]
    assert "&lt;em&gt;priority implementation direction.&lt;/em&gt;" in source_values[0]
    assert "&lt;ready&gt;\nwork.md [confirmed]" in source_values[1]
    assert not re.search(
        r"\b(?:fixes|closes|resolves|title|label|assignee|rank(?:ing)?|priority|ready|urgent|cause|causal|diagnos(?:is|tic)|recommend(?:ation)?|implementation|direction)\b",
        authored,
        re.I,
    )
    assert "Fixes #123:" in proposals
    assert "&lt;ready&gt;" in proposals


def test_cockpit_drafts_are_inert_and_network_free(overview_store: CkmStore) -> None:
    rendered = render_overview_html(
        overview_store,
        cockpit=CockpitRenderContext(batch=overview_store.load_projection_batch()),
    )
    proposals = _proposal_section(rendered)

    assert proposals.count('<pre class="proposal-draft">') == 1
    assert not re.search(
        r"<(?:a|button|input|textarea|form|script)\b|\b(?:action|data-|on\w+)=",
        proposals,
        re.I,
    )
    assert all(token not in proposals.lower() for token in ("clipboard", "fetch", "github", "prefill", "url"))
    assert rendered.count("<script>") == 1

    direction_a = render_overview_html(overview_store)
    assert 'class="cockpit-proposals"' not in direction_a
    assert "<script" not in direction_a


def test_cockpit_draft_empty_and_uncited_states_are_honest(tmp_path: Path) -> None:
    empty = CkmStore(tmp_path / "empty-drafts.sqlite3")
    empty.ensure_schema()
    empty_proposals = _proposal_section(
        render_overview_html(empty, cockpit=CockpitRenderContext(batch=empty.load_projection_batch()))
    )
    assert "Eligible drafts: 0 · Ineligible findings: 0 · Total findings: 0." in empty_proposals
    assert "<pre" not in empty_proposals

    source = CkmStore(tmp_path / "uncited-drafts.sqlite3")
    source.ensure_schema()
    capability = source.upsert_capability(
        identity_key="fixture:uncited",
        name="Uncited",
        definition="Fixture.",
        existence_provenance="fixture",
        lifecycle="confirmed",
    )
    invalid = CkmFinding(
        id="finding-uncited",
        public_id="CKM-FIND-UNCITED",
        kind="gap",
        capability_id=capability.id,
        dimension="test_completeness",
        statement="Unresolvable source.",
        citations=[{"source_ref": ""}],
        created_at="2026-07-27T00:00:00Z",
        updated_at="2026-07-27T00:00:00Z",
    )
    batch = source.load_projection_batch()
    proposals = _proposal_section(
        render_overview_html(
            source,
            cockpit=CockpitRenderContext(
                batch=replace(batch, findings_by_capability={capability.id: (invalid,)})
            ),
        )
    )
    assert "Eligible drafts: 0 · Ineligible findings: 1 · Total findings: 1." in proposals
    assert "<pre" not in proposals


def test_cockpit_filters_do_not_mutate_proposal_drafts(overview_store: CkmStore) -> None:
    rendered = render_overview_html(
        overview_store,
        cockpit=CockpitRenderContext(batch=overview_store.load_projection_batch()),
    )
    proposals = _proposal_section(rendered)
    script = _cockpit_filter_script(rendered)
    node = _require_node_for_cockpit_script_execution()
    harness = r'''
class Control {
  constructor() { this.value = ''; this.disabled = true; this.listeners = {}; }
  addEventListener(type, handler) { this.listeners[type] = handler; }
  emit(type) { this.listeners[type]({ type }); }
}
const search = new Control(); const assessment = new Control(); const confidence = new Control();
const findings = new Control(); const evidence = new Control(); const count = { textContent: '' };
const proposals = { hidden: false, textContent: 'proposal text is stable' };
const rows = [{ dataset: { filterName: 'Retrieval', filterDefinition: '', filterPublicId: '', filterBoundary: '', filterAssessment: 'available current', filterConfidence: 'standard', filterFindings: 'present', filterEvidence: 'confirmed' }, hidden: false }];
const document = {
  querySelector: (selector) => ({ '[name="filter-search"]': search, '[name="filter-assessment"]': assessment, '[name="filter-confidence"]': confidence, '[name="filter-findings"]': findings, '[name="filter-evidence"]': evidence, '#filter-count': count, '#proposals-heading': proposals })[selector],
  querySelectorAll: (selector) => selector === '#capability-map > .capability[data-filter-name]' ? rows : []
};
''' + script + r'''
const before = proposals.textContent;
search.value = 'no-match'; search.emit('input');
if (!rows[0].hidden || proposals.hidden || proposals.textContent !== before) process.exit(1);
'''
    result = subprocess.run([node, "-e", harness], capture_output=True, text=True, check=False)

    assert result.returncode == 0, result.stderr
    assert proposals.count('<pre class="proposal-draft">') == 1
    assert "proposal" not in script.lower()


def _cockpit_print_css(rendered: str) -> str:
    """Return the generated print block, failing if the style surface is ambiguous."""

    styles = re.findall(r"<style>(.*?)</style>", rendered, re.S)
    assert len(styles) == 1
    print_blocks = styles[0].split("@media print {")
    assert len(print_blocks) == 2
    return print_blocks[1]


def _print_rule(css: str, selector: str) -> str:
    match = re.search(rf"{re.escape(selector)}\s*\{{([^}}]+)\}}", css)
    assert match is not None, f"missing print rule for {selector}"
    return re.sub(r"\s+", "", match.group(1))


class _CockpitPrintStructureParser(HTMLParser):
    """Capture normalized generated-element structure without relying on CSS substrings."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.elements: list[tuple[str, dict[str, str | None]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.elements.append((tag.lower(), {name.lower(): value for name, value in attrs}))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)


def _cockpit_print_structure(rendered: str) -> _CockpitPrintStructureParser:
    parser = _CockpitPrintStructureParser()
    parser.feed(rendered)
    parser.close()
    return parser


def _elements_with_class(
    parser: _CockpitPrintStructureParser, class_name: str
) -> list[tuple[str, dict[str, str | None]]]:
    return [
        (tag, attrs)
        for tag, attrs in parser.elements
        if class_name in (attrs.get("class") or "").split()
    ]


def _section_markup(rendered: str, class_name: str) -> str:
    opening = f'<section class="{class_name}"'
    start = rendered.index(opening)
    return rendered[start : rendered.index("</section>", start) + len("</section>")]


def test_cockpit_print_css_reveals_hidden_rows_and_closed_details(
    overview_store: CkmStore,
) -> None:
    context = CockpitRenderContext(batch=overview_store.load_projection_batch())
    cockpit = render_overview_html(overview_store, cockpit=context)
    direction_a = render_overview_html(overview_store)
    print_css = _cockpit_print_css(cockpit)
    structure = _cockpit_print_structure(cockpit)
    details = [attrs for tag, attrs in structure.elements if tag == "details"]
    safety = _parse_cockpit_html_safety(cockpit)

    assert "@media print" not in direction_a
    assert "@media print" in cockpit
    assert len(_elements_with_class(structure, "capability")) == len(context.batch.capabilities)
    assert details
    assert all("open" not in attrs for attrs in details)
    assert {"capability-details", "drilldown", "citations"} <= {
        class_name
        for _, attrs in structure.elements
        for class_name in (attrs.get("class") or "").split()
    }
    assert safety.script_count == 1
    script = _cockpit_filter_script(cockpit)
    assert "row.hidden" in script
    assert "open" not in script and "print" not in script.lower()
    assert "display:block!important;" in _print_rule(print_css, "[hidden]")
    assert "display:block!important;" in _print_rule(
        print_css, "details > :not(summary)"
    )
    assert "content-visibility:visible!important;" in _print_rule(
        print_css, "details::details-content"
    )


def test_cockpit_print_hides_controls_not_semantics(overview_store: CkmStore) -> None:
    rendered = render_overview_html(
        overview_store,
        cockpit=CockpitRenderContext(batch=overview_store.load_projection_batch()),
    )
    print_css = _cockpit_print_css(rendered)
    structure = _cockpit_print_structure(rendered)

    controls = _elements_with_class(structure, "cockpit-filter-controls")
    assert controls == [("div", {"class": "filter-controls cockpit-filter-controls"})]
    assert any(
        tag == "p" and attrs.get("id") == "filter-count" for tag, attrs in structure.elements
    )
    assert any(tag == "noscript" for tag, _ in structure.elements)
    assert "display:none!important;" in _print_rule(
        print_css, ".cockpit-filter-controls,#filter-count,noscript"
    )
    assert "list-style:none!important;" in _print_rule(print_css, "summary")
    glyph_rule = _print_rule(print_css, "summary::before")
    assert "content:none!important;" in glyph_rule
    assert "display:none!important;" in glyph_rule
    assert 'content:""!important;' in _print_rule(print_css, "summary::marker")
    assert "display:none!important;" in _print_rule(
        print_css, "summary::-webkit-details-marker"
    )
    semantic_classes = {
        "cockpit-trust",
        "cockpit-hazards",
        "cockpit-comparison",
        "capability-tree",
        "gaps-panel",
        "cockpit-proposals",
        "projection-footer",
    }
    rendered_classes = {
        class_name
        for _, attrs in structure.elements
        for class_name in (attrs.get("class") or "").split()
    }
    assert semantic_classes <= rendered_classes
    assert "Generated projection — not source of truth." in rendered
    assert "Filtering is unavailable; all capability rows are shown." in rendered


def test_cockpit_print_contract_covers_every_final_section(overview_store: CkmStore) -> None:
    batch = overview_store.load_projection_batch()
    variants = {
        "compatible": CockpitRenderContext(batch=batch, comparison=_valid_o1b_payload()),
        "refusal": CockpitRenderContext(batch=batch, comparison=None),
    }

    for state, context in variants.items():
        rendered = render_overview_html(overview_store, cockpit=context)
        print_css = _cockpit_print_css(rendered)
        structure = _cockpit_print_structure(rendered)
        assert len(_elements_with_class(structure, "capability-body")) == len(batch.capabilities)
        assert len(_elements_with_class(structure, "capability-details")) == len(batch.capabilities)
        assert len(_elements_with_class(structure, "drilldown")) == 2 * len(batch.capabilities)
        assert _elements_with_class(structure, "citations")
        assert _elements_with_class(structure, "evidence-list")
        assert _elements_with_class(structure, "finding-list")
        for edge in batch.edges_by_capability[next(iter(batch.edges_by_capability))]:
            assert f"Basis: {edge.basis}" in rendered
        for findings in batch.findings_by_capability.values():
            for finding in findings:
                assert finding.statement in rendered
                for citation in finding.citations:
                    assert str(citation["source_ref"]) in rendered
        assert "Generated projection — not source of truth." in rendered
        assert "projection-input digest:" in _section_markup(rendered, "cockpit-trust")
        assert "Draft only — not an Issue contract" in _section_markup(
            rendered, "cockpit-proposals"
        )
        assert "Candidate and confirmed evidence remain distinct." in rendered
        assert "details > :not(summary)" in print_css
        assert "details::details-content" in print_css
        if state == "compatible":
            assert 'class="comparison-result"' in rendered
            assert "source_unavailable" not in rendered
        else:
            assert 'class="comparison-refusal"' in rendered
            assert "source_unavailable" in rendered


def test_cockpit_print_styles_preserve_text_and_section_integrity(
    overview_store: CkmStore,
) -> None:
    batch = overview_store.load_projection_batch()
    capability = next(
        item for item in batch.capabilities if item.id in batch.findings_by_capability
    )
    long_identity = "CKM-IDENTITY-" + "x" * 320
    long_metadata = "BOUNDARY-" + "m" * 320
    long_basis = "basis-" + "b" * 320
    long_finding = "finding-" + "f" * 320
    long_citation = "citation-" + "c" * 320 + ".md"
    long_watermark = "watermark-" + "w" * 320
    long_epoch = "epoch-" + "e" * 320
    finding = batch.findings_by_capability[capability.id][0]
    assessment_projection = batch.assessments_by_capability[capability.id]
    long_citations = {
        dimension: [{"source_ref": long_citation, "lifecycle": "confirmed"}]
        for dimension in MATURITY_DIMENSIONS
    }
    projection = replace(
        batch,
        state_identity=replace(batch.state_identity, epoch=long_epoch),
        current_watermark_set={"fixture": long_watermark},
        capabilities=tuple(
            replace(item, public_id=long_identity, boundary_ref=long_metadata)
            if item.id == capability.id
            else item
            for item in batch.capabilities
        ),
        edges_by_capability={
            **batch.edges_by_capability,
            capability.id: tuple(
                replace(edge, basis=long_basis, source_ref=long_citation)
                for edge in batch.edges_by_capability[capability.id]
            ),
        },
        assessments_by_capability={
            **batch.assessments_by_capability,
            capability.id: replace(
                assessment_projection,
                assessment=replace(assessment_projection.assessment, citations=long_citations),
            ),
        },
        findings_by_capability={
            **batch.findings_by_capability,
            capability.id: (
                replace(
                    finding,
                    statement=long_finding,
                    citations=[{"source_ref": long_citation, "lifecycle": "confirmed"}],
                ),
            ),
        },
    )
    rendered = render_overview_html(
        overview_store,
        cockpit=CockpitRenderContext(batch=projection, comparison=_valid_o1b_payload()),
    )
    print_css = _cockpit_print_css(rendered)

    trust = _section_markup(rendered, "cockpit-trust")
    proposals = _section_markup(rendered, "cockpit-proposals")
    footer = rendered.split('<footer class="projection-footer">', 1)[1].split("</footer>", 1)[0]
    for value in (long_identity, long_metadata, long_basis, long_finding, long_citation):
        assert value in rendered
    assert long_epoch in trust and long_epoch in footer
    assert long_watermark in trust and long_watermark in footer and long_watermark in proposals
    assert re.search(r"projection-input digest: <code>[0-9a-f]{64}</code>", trust)
    assert long_finding in proposals and long_citation in proposals
    root = _print_rule(print_css, ":root")
    assert "--bg-base:#fff;" in root and "--fg-1:#111;" in root
    assert "background:#fff;" in _print_rule(print_css, "body")
    assert "text-decoration:underline;" in _print_rule(print_css, "a")
    assert "border:1pxsolid#333;" in _print_rule(
        print_css,
        ".projection-banner,.cockpit-trust,.cockpit-hazards,.cockpit-comparison,.subsystem-counts-card,.cockpit-filters,.gaps-panel,.cockpit-proposals,.capability,.dimension",
    )
    wrapping = _print_rule(
        print_css,
        ".tree-name,.capability-body,.meta,code,.basis,.citations,.finding-list,.evidence-list,.proposal-draft,.cockpit-trust,.cockpit-comparison,.cockpit-hazards,.cockpit-proposals,.projection-footer",
    )
    assert "overflow:visible;" in wrapping
    assert "overflow-wrap:anywhere;" in wrapping
    assert "word-break:break-word;" in wrapping
    assert "white-space:pre-wrap;" in _print_rule(print_css, "pre,.proposal-draft")
    assert "flex-wrap:wrap;" in _print_rule(
        print_css,
        ".summary-flags,.badge,.flag,.lifecycle,.capability-summary,.trust-strip,.subsystem-counts-grid",
    )
    assert "break-after:avoid-page;" in _print_rule(print_css, "h1,h2,h3,summary")
    compact = _print_rule(
        print_css,
        ".capability-summary,.dimension-label,.mini-dimensions,.summary-flags,.trust-strip a",
    )
    assert "break-inside:avoid-page;" in compact
    assert "page-break-inside:avoid;" in compact
    splittable = _print_rule(
        print_css,
        ".capability,.cockpit-comparison,.cockpit-comparison > *,.proposal-draft",
    )
    assert "break-inside:auto;" in splittable
    assert "page-break-inside:auto;" in splittable
    assert '<div class="proposal-intro">' in proposals
    orphan_rule = _print_rule(print_css, ".proposal-intro")
    assert "break-after:avoid-page;" in orphan_rule
    assert "page-break-after:avoid;" in orphan_rule
    typography = _print_rule(print_css, "p,li")
    assert "widows:3;" in typography and "orphans:3;" in typography


def test_cockpit_answers_fixed_owner_questions_without_authority(
    overview_store: CkmStore,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixed_now = "2026-07-27T12:00:00Z"
    monkeypatch.setattr(overview_html_module, "utc_now", lambda: fixed_now)
    refusal_first = tmp_path / "cockpit-refusal-first.html"
    refusal_second = tmp_path / "cockpit-refusal-second.html"
    assert _cockpit_cli(overview_store, refusal_first).exit_code == 0
    assert _cockpit_cli(overview_store, refusal_second).exit_code == 0
    _retain_for_cockpit(overview_store, retained_at="2026-07-21T00:00:00Z")
    _retain_for_cockpit(overview_store, retained_at="2026-07-22T00:00:00Z")
    compatible_first = tmp_path / "cockpit-compatible-first.html"
    compatible_second = tmp_path / "cockpit-compatible-second.html"
    assert _cockpit_cli(overview_store, compatible_first).exit_code == 0
    assert _cockpit_cli(overview_store, compatible_second).exit_code == 0

    artifacts = {
        "refusal": (refusal_first, refusal_second),
        "compatible": (compatible_first, compatible_second),
    }
    rendered_by_state: dict[str, str] = {}
    for state, (first, second) in artifacts.items():
        assert first.read_bytes() == second.read_bytes()
        assert hashlib.sha256(first.read_bytes()).hexdigest() == hashlib.sha256(
            second.read_bytes()
        ).hexdigest()
        rendered_by_state[state] = first.read_text(encoding="utf-8")
    assert "source_unavailable" in rendered_by_state["refusal"]
    assert 'class="comparison-refusal"' in rendered_by_state["refusal"]
    assert 'class="comparison-result"' in rendered_by_state["compatible"]

    for rendered in rendered_by_state.values():
        for question in (
            "Is this projection fresh and complete enough to inspect?",
            "What should not be taken at face value?",
            "What differs between the two newest active retained observation records",
            "Where is evidence weakest?",
        ):
            assert question in rendered
        assert "Generated projection — not source of truth." in rendered
        assert "Draft only — not an Issue contract, priority, decision, or ready work." in rendered
        assert "<form" not in rendered.lower()
        assert "clipboard" not in rendered.lower()
        assert not re.search(r"<(?:form|button|textarea)\b", rendered, re.I)
        safety = _parse_cockpit_html_safety(rendered)
        assert safety.script_count == 1
        assert safety.script_sources == [] and safety.inline_handlers == []
        source_values_removed = re.sub(
            r"<(?:style|script)\b[^>]*>.*?</(?:style|script)\s*>",
            "",
            rendered,
            flags=re.S | re.I,
        )
        source_values_removed = re.sub(
            r'<span class="proposal-source-value">.*?</span>',
            "",
            source_values_removed,
            flags=re.S,
        )
        source_values_removed = re.sub(
            r'<p class="comparison-disclaimer">.*?</p>',
            "",
            source_values_removed,
            flags=re.S,
        )
        source_values_removed = re.sub(
            r'<pre class="comparison-(?:result|inputs|bindings|provenance|freshness|limitations|details)">.*?</pre>',
            "",
            source_values_removed,
            flags=re.S,
        )
        authored = _visible_html_text(source_values_removed)
        for negating_disclaimer in (
            "Generated projection — not source of truth.",
            "Generated projection (BuilderOps CKM). Not source of truth.",
            "Difference between two snapshots. Not a trend, cause, or forecast.",
            "Draft only — not an Issue contract, priority, decision, or ready work.",
            "Candidate and confirmed evidence remain distinct. Regenerate from the CKM store; do not edit this file as authority.",
        ):
            authored = authored.replace(negating_disclaimer, "")
        assert not re.search(
            r"\b(?:rank(?:ing)?|prioriti[sz](?:e|ed|ing)|trend|cause|forecast|authority|action|write|network|clipboard|prefill)\b",
            authored,
            re.I,
        )
