"""Self-contained, non-authoritative HTML overview for the CKM."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Mapping, Sequence

from app.builderops.ckm.models import (
    MATURITY_DIMENSIONS,
    CkmAssessment,
    CkmCapability,
    CkmEvidenceEdge,
    CkmFinding,
    CkmAssessmentProjection,
    utc_now,
)
from app.builderops.ckm.contracts import canonical_digest
from app.builderops.ckm.store import CkmProjectionBatch, CkmStore


DIMENSION_LABELS = {
    "functional_completeness": ("FUN", "functional completeness"),
    "test_completeness": ("TST", "test completeness"),
    "documentation_quality": ("DOC", "documentation quality"),
    "integration_completeness": ("INT", "integration completeness"),
    "operational_readiness": ("OPS", "operational readiness"),
    "architectural_stability": ("ARC", "architectural stability"),
    "requirement_coverage": ("REQ", "requirement coverage"),
}


@dataclass(frozen=True)
class CockpitRenderContext:
    """Immutable, data-only input captured before cockpit rendering begins."""

    batch: CkmProjectionBatch


def _cockpit_digest(batch: CkmProjectionBatch) -> str:
    """Bind cockpit provenance to every captured projection input deterministically."""

    return canonical_digest(
        {
            "state_identity": batch.state_identity.to_dict(),
            "object_counts": dict(sorted(batch.object_counts.items())),
            "capabilities": [item.to_dict() for item in batch.capabilities],
            "artifacts": [item.to_dict() for item in batch.artifacts],
            "edges": [
                edge.to_dict()
                for capability_id in sorted(batch.edges_by_capability)
                for edge in batch.edges_by_capability[capability_id]
            ],
            "assessments": [
                batch.assessments_by_capability[capability_id].assessment.to_dict()
                for capability_id in sorted(batch.assessments_by_capability)
            ],
            "findings": [
                finding.to_dict()
                for capability_id in sorted(batch.findings_by_capability)
                for finding in batch.findings_by_capability[capability_id]
            ],
            "watermarks": dict(sorted(batch.current_watermark_set.items())),
        }
    )


def _cockpit_trust_markup(batch: CkmProjectionBatch, timestamp: str) -> str:
    identity = batch.state_identity
    counts = batch.object_counts
    count_text = " · ".join(
        f"{_e(label)}: {counts.get(key, 0)}"
        for key, label in (
            ("capability", "capabilities"),
            ("artifact", "artifacts"),
            ("evidence_edge", "evidence edges"),
            ("assessment", "assessments"),
            ("finding", "findings"),
            ("watermark", "watermarks"),
        )
    )
    return f"""<header class="cockpit-header"><h1>CKM Cockpit</h1><p class="subtitle">Portfolio-first, generated, non-authoritative inspection surface.</p></header>
    <section class="cockpit-trust" aria-labelledby="cockpit-trust-heading">
      <h2 id="cockpit-trust-heading">Cockpit trust frame</h2>
      <p>Is this projection fresh and complete enough to inspect?</p>
      <p>Generated: {_e(timestamp)} · epoch: {_e(identity.epoch)} · state revision: {identity.state_revision} · schema version: {identity.schema_version}</p>
      <p>Watermarks: {_watermarks(batch.current_watermark_set)}</p>
      <p>Bounded counts: {count_text}</p>
      <p>projection-input digest: <code>{_cockpit_digest(batch)}</code></p>
    </section>"""


def _hazard_capability_links(capabilities: Sequence[CkmCapability]) -> str:
    """Render stable capability links without treating their definitions as interpretation."""

    return ", ".join(
        f'<a href="#cap-{_e(capability.id)}">{_e(capability.public_id)}</a>'
        for capability in sorted(
            capabilities, key=lambda item: (item.public_id.casefold(), item.id)
        )
    )


def _capability_noun(count: int) -> str:
    """Use the complete noun form for a count in renderer-authored copy."""

    return "capability" if count == 1 else "capabilities"


def _stale_source_markers(projection: CkmAssessmentProjection) -> str:
    """Render only captured watermark differences that make an assessment stale."""

    assessment_markers = projection.assessment.watermark_set
    current_markers = projection.current_watermark_set
    differences = [
        source
        for source in sorted(set(assessment_markers) | set(current_markers))
        if assessment_markers.get(source) != current_markers.get(source)
    ]
    if not differences:
        return ""
    return "; ".join(
        f'{_e(source)}: assessment={_e(assessment_markers.get(source, "absent"))} '
        f'→ current={_e(current_markers.get(source, "absent"))}'
        for source in differences
    )


def _cockpit_hazards_markup(batch: CkmProjectionBatch) -> str:
    """Render only observed, snapshot-bound interpretation caveats.

    This intentionally consumes the caller-provided batch rather than the store: hazards must
    describe the same captured projection as the trust frame, map, and gaps panel.
    """

    capabilities = {capability.id: capability for capability in batch.capabilities}
    rows: list[tuple[int, int, str, str, str | None]] = []

    def add(
        kind_order: int,
        dimension_order: int,
        kind: str,
        body: str,
        value_state: str | None = None,
    ) -> None:
        rows.append((kind_order, dimension_order, kind, body, value_state))

    stale = [
        (capabilities[capability_id], _stale_source_markers(projection))
        for capability_id, projection in batch.assessments_by_capability.items()
        if projection.stale_relative_to_evidence and capability_id in capabilities
    ]
    if stale:
        stale.sort(key=lambda item: (item[0].public_id.casefold(), item[0].id))
        stale_links = ", ".join(
            f'<a href="#cap-{_e(capability.id)}">{_e(capability.public_id)}</a>'
            + (f" ({markers})" if markers else "")
            for capability, markers in stale
        )
        add(
            0,
            0,
            "stale",
            f"{len(stale)} stale assessment{'s' if len(stale) != 1 else ''}: " f"{stale_links}.",
        )

    unavailable = [
        capability
        for capability in batch.capabilities
        if capability.id not in batch.assessments_by_capability
    ]
    if unavailable:
        add(
            1,
            0,
            "assessment-unavailable",
            f"Assessment unavailable for {len(unavailable)} {_capability_noun(len(unavailable))}: "
            f"{_hazard_capability_links(unavailable)}. Unavailable is not a zero score.",
        )

    for dimension_order, dimension in enumerate(MATURITY_DIMENSIONS):
        unassessed = [
            capabilities[capability_id]
            for capability_id, projection in batch.assessments_by_capability.items()
            if capability_id in capabilities
            and projection.assessment.dimension_status.get(dimension) == "unassessed"
        ]
        if unassessed:
            add(
                1,
                dimension_order + 1,
                "unassessed",
                f"{_e(DIMENSION_LABELS[dimension][1])}: unassessed for {len(unassessed)} "
                f"assessed {_capability_noun(len(unassessed))}: "
                f"{_hazard_capability_links(unassessed)}. Unassessed is not a zero score.",
                "unassessed",
            )

        unsupported = [
            capabilities[capability_id]
            for capability_id, projection in batch.assessments_by_capability.items()
            if capability_id in capabilities
            and projection.assessment.dimension_status.get(dimension) == "unsupported"
        ]
        if unsupported:
            add(
                1,
                dimension_order + 1,
                "unsupported",
                f"{_e(DIMENSION_LABELS[dimension][1])}: unsupported for {len(unsupported)} "
                f"assessed {_capability_noun(len(unsupported))}: "
                f"{_hazard_capability_links(unsupported)}. Unsupported is not a zero score.",
                "unsupported",
            )

        candidate_heavy = [
            (capabilities[capability_id], projection.assessment.candidate_shares[dimension])
            for capability_id, projection in batch.assessments_by_capability.items()
            if capability_id in capabilities
            and projection.assessment.dimension_status.get(dimension)
            not in {"unassessed", "unsupported"}
            and float(projection.assessment.candidate_shares[dimension]) >= 0.5
        ]
        if candidate_heavy:
            candidate_heavy.sort(key=lambda item: (item[0].public_id.casefold(), item[0].id))
            links = ", ".join(
                f'<a href="#cap-{_e(capability.id)}">{_e(capability.public_id)} '
                f"({_e(f'{share:.1%}')})</a>"
                for capability, share in candidate_heavy
            )
            add(
                2,
                dimension_order,
                "candidate-heavy",
                f"{_e(DIMENSION_LABELS[dimension][1])}: candidate-heavy for "
                f"{len(candidate_heavy)} assessed {_capability_noun(len(candidate_heavy))}: {links}.",
            )

    shared_pairs = _shared_evidence_pairs(batch.edges_by_capability)
    shared = [
        capabilities[capability_id]
        for capability_id, edges in batch.edges_by_capability.items()
        if capability_id in capabilities
        and any((edge.artifact_id, edge.basis) in shared_pairs for edge in edges)
    ]
    if shared:
        add(
            3,
            0,
            "shared-evidence",
            f"Shared evidence indicator applies to {len(shared)} {_capability_noun(len(shared))}: "
            f"{_hazard_capability_links(shared)}.",
        )

    assessed = tuple(batch.assessments_by_capability.items())
    for dimension_order, dimension in enumerate(MATURITY_DIMENSIONS):
        zero_assessed = [
            (capability_id, projection)
            for capability_id, projection in assessed
            if projection.assessment.dimension_status.get(dimension)
            not in {"unassessed", "unsupported"}
        ]
        if zero_assessed and all(
            float(projection.assessment.scores[dimension]) == 0.0 for _, projection in zero_assessed
        ):
            zero_capabilities = [
                capabilities[capability_id]
                for capability_id, _ in zero_assessed
                if capability_id in capabilities
            ]
            add(
                4,
                dimension_order,
                "snapshot-wide-zero",
                f"Snapshot-wide zero: {_e(DIMENSION_LABELS[dimension][1])} is 0.00 for every "
                "assessed capability in this snapshot. CKM cannot determine whether that reflects "
                "missing evidence, current metric coverage, or portfolio state. "
                f"Affected: {len(zero_capabilities)} assessed {_capability_noun(len(zero_capabilities))}: "
                f"{_hazard_capability_links(zero_capabilities)}.",
            )

    if not rows:
        content = "<p>No listed interpretation hazards for this captured projection.</p>"
    else:
        content = (
            '<ul class="hazard-list">'
            + "".join(
                f'<li class="hazard hazard-{kind}" data-hazard-kind="{kind}"'
                + (f' data-value-state="{value_state}"' if value_state else "")
                + " "
                'data-renderer-authored="interpretation">'
                f"{body}</li>"
                for _, _, kind, body, value_state in sorted(rows)
            )
            + "</ul>"
        )
    return f"""<section class="cockpit-hazards" aria-labelledby="hazards-heading" data-renderer-authored="interpretation">
      <h2 id="hazards-heading">Interpretation hazards</h2><p>What should not be taken at face value?</p>{content}</section>"""


def _cockpit_reserved_markup() -> str:
    return """<section class="cockpit-reserved" aria-labelledby="comparison-heading"><h2 id="comparison-heading">Comparison</h2><p>What differs between the two newest active retained observation records, when O1b says they are compatible?</p><p>Unavailable in this framing slice. No retained-observation comparison was read.</p></section>
    <section class="cockpit-reserved" aria-labelledby="filters-heading"><h2 id="filters-heading">Filters</h2><p>Unavailable in this framing slice. All capability rows are shown.</p></section>"""


def _cockpit_proposals_markup() -> str:
    return '<section class="cockpit-reserved" aria-labelledby="proposals-heading"><h2 id="proposals-heading">Proposal drafts</h2><p>Unavailable in this framing slice. No proposal content is generated.</p></section>'


def _e(value: object) -> str:
    return escape(str(value), quote=True)


def _watermarks(values: Mapping[str, str]) -> str:
    if not values:
        return "none"
    return ", ".join(f"{_e(key)}={_e(value)}" for key, value in sorted(values.items()))


def _forest(capabilities: Sequence[CkmCapability]) -> list[tuple[int, CkmCapability]]:
    known = {item.id for item in capabilities}
    children: dict[str | None, list[CkmCapability]] = {}
    for item in capabilities:
        parent = item.parent_id if item.parent_id in known else None
        children.setdefault(parent, []).append(item)
    for values in children.values():
        values.sort(key=lambda item: (item.name.casefold(), item.id))
    result: list[tuple[int, CkmCapability]] = []
    visited: set[str] = set()

    def visit(item: CkmCapability, depth: int) -> None:
        if item.id in visited:
            return
        visited.add(item.id)
        result.append((depth, item))
        for child in children.get(item.id, []):
            visit(child, depth + 1)

    for root in children.get(None, []):
        visit(root, 0)
    for item in sorted(capabilities, key=lambda value: (value.name.casefold(), value.id)):
        visit(item, 0)
    return result


def _edge_counts(edges: Sequence[CkmEvidenceEdge]) -> tuple[int, int]:
    return (
        sum(edge.lifecycle == "confirmed" for edge in edges),
        sum(edge.lifecycle == "candidate" for edge in edges),
    )


def _shared_evidence_pairs(
    edges_by_capability: Mapping[str, Sequence[CkmEvidenceEdge]],
) -> frozenset[tuple[str, str]]:
    capability_ids_by_pair: dict[tuple[str, str], set[str]] = defaultdict(set)
    for edges in edges_by_capability.values():
        for edge in edges:
            capability_ids_by_pair[(edge.artifact_id, edge.basis)].add(edge.capability_id)
    return frozenset(
        pair for pair, capability_ids in capability_ids_by_pair.items() if len(capability_ids) >= 2
    )


def _evidence_count_values(
    edges: Sequence[CkmEvidenceEdge],
    shared_pairs: frozenset[tuple[str, str]],
) -> tuple[int, int, int, str]:
    distinct_artifacts = len({edge.artifact_id for edge in edges})
    edge_count = len(edges)
    shared_edge_count = sum((edge.artifact_id, edge.basis) in shared_pairs for edge in edges)
    shared_percentage = f"{shared_edge_count / edge_count:.1%}" if edge_count else "0.0%"
    return distinct_artifacts, edge_count, shared_edge_count, shared_percentage


def _subsystem_counts_markup(
    forest: Sequence[tuple[int, CkmCapability]],
    edges_by_capability: Mapping[str, Sequence[CkmEvidenceEdge]],
) -> str:
    shared_pairs = _shared_evidence_pairs(edges_by_capability)
    all_edges = tuple(
        edge for _, capability in forest for edge in edges_by_capability.get(capability.id, ())
    )
    (
        global_artifacts,
        global_edges,
        global_shared_edges,
        global_shared_percentage,
    ) = _evidence_count_values(all_edges, shared_pairs)

    groups: list[list[tuple[int, CkmCapability]]] = []
    current: list[tuple[int, CkmCapability]] = []
    for depth, capability in forest:
        if depth == 0:
            if current:
                groups.append(current)
            current = [(depth, capability)]
        else:
            current.append((depth, capability))
    if current:
        groups.append(current)

    cards: list[str] = []
    for group in groups:
        root = group[0][1]
        group_edges = tuple(
            edge for _, capability in group for edge in edges_by_capability.get(capability.id, ())
        )
        distinct_artifacts, edge_count, shared_edge_count, shared_percentage = (
            _evidence_count_values(group_edges, shared_pairs)
        )
        capability_rows: list[str] = []
        for depth, capability in group:
            capability_edges = edges_by_capability.get(capability.id, ())
            (
                capability_artifacts,
                capability_edge_count,
                capability_shared_edges,
                capability_shared_percentage,
            ) = _evidence_count_values(capability_edges, shared_pairs)
            capability_rows.append(
                f"""<li class="capability-count" data-capability-name="{_e(capability.name)}" data-distinct-artifacts="{capability_artifacts}" data-shared-edge-count="{capability_shared_edges}" data-edge-count="{capability_edge_count}" data-shared-evidence="{capability_shared_percentage}" style="--count-depth:{depth}">
              <span class="count-name">{_e(capability.name)}</span>
              <span>distinct artifacts: <strong>{capability_artifacts}</strong></span>
              <span class="secondary">edges: {capability_edge_count}</span>
              <span>shared evidence: <strong>{capability_shared_percentage}</strong> ({capability_shared_edges} of {capability_edge_count} edges)</span>
            </li>"""
            )
        cards.append(
            f"""<section class="subsystem-counts-card" data-subsystem-name="{_e(root.name)}" data-capability-count="{len(group)}" data-distinct-artifacts="{distinct_artifacts}" data-shared-edge-count="{shared_edge_count}" data-edge-count="{edge_count}" data-shared-evidence="{shared_percentage}">
          <h3>{_e(root.name)} subsystem</h3>
          <p>capabilities: <strong>{len(group)}</strong> · distinct artifacts: <strong>{distinct_artifacts}</strong> · shared evidence: <strong>{shared_percentage}</strong> ({shared_edge_count} of {edge_count} edges)</p>
          <ul>{"".join(capability_rows)}</ul>
        </section>"""
        )

    cards_markup = "".join(cards) or '<p class="empty">No subsystems in the CKM store.</p>'
    return f"""<section class="subsystem-counts" aria-labelledby="subsystem-counts-heading">
      <h2 id="subsystem-counts-heading">Evidence counts by subsystem</h2>
      <p class="linkage-masthead" data-denominator="global" data-distinct-artifacts="{global_artifacts}" data-capability-count="{len(forest)}" data-shared-edge-count="{global_shared_edges}" data-edge-count="{global_edges}" data-shared-evidence="{global_shared_percentage}"><strong>Linkage masthead:</strong> {global_artifacts} distinct artifacts across {len(forest)} capabilities · shared evidence: <strong>{global_shared_percentage}</strong> of all {global_edges} edges (global).</p>
      <div class="subsystem-counts-grid">{cards_markup}</div>
    </section>"""


def _citation_source(citation: Mapping[str, object]) -> str:
    source_ref = citation.get("source_ref")
    artifact = citation.get("artifact")
    if source_ref is None and isinstance(artifact, Mapping):
        source_ref = artifact.get("source_ref")
    lifecycle = citation.get("lifecycle")
    edge = citation.get("edge")
    if lifecycle is None and isinstance(edge, Mapping):
        lifecycle = edge.get("lifecycle")
    suffix = f" · {lifecycle}" if lifecycle in {"candidate", "confirmed"} else ""
    return f"{source_ref or 'evidence snapshot'}{suffix}"


def _dimension_markup(
    dimension: str,
    score: float,
    citations: Sequence[Mapping[str, object]],
    candidate_share: float,
    status: str | None,
) -> str:
    _, label = DIMENSION_LABELS[dimension]
    if status in {"unassessed", "unsupported"}:
        state_label = (
            "unassessed — no selected evidence"
            if status == "unassessed"
            else "unsupported by this assessment formula"
        )
        return f"""
      <section class="dimension dimension-unassessed" data-dimension="{_e(dimension)}" data-cell-state="unassessed">
        <div class="dimension-label"><span>{_e(label)}</span><strong>—</strong></div>
        <small>{_e(state_label)}</small>
      </section>"""
    percent = max(0.0, min(100.0, score * 100.0))
    starved = score == 0 and not citations
    citation_items = (
        "".join(f"<li>{_e(_citation_source(citation))}</li>" for citation in citations)
        or "<li>No selected citations.</li>"
    )
    low_conf = '<span class="flag flag-low">LOW CONF</span>' if candidate_share > 0.5 else ""
    return f"""
      <section class="dimension{' dimension-starved' if starved else ''}" data-dimension="{_e(dimension)}">
        <div class="dimension-label"><span>{_e(label)}</span><strong>{score:.2f}</strong>{low_conf}</div>
        <div class="dimension-track" role="progressbar" aria-label="{_e(label)}" aria-valuemin="0" aria-valuemax="1" aria-valuenow="{score:.3f}">
          <span class="dimension-bar" style="width:{percent:.1f}%"></span>
        </div>
        <small>{len(citations)} citation(s) · candidate share {candidate_share:.1%}</small>
        <details class="citations"><summary>Citations — {_e(label)} ({len(citations)})</summary><ul>{citation_items}</ul></details>
      </section>"""


def _mini_dimensions_markup(assessment: CkmAssessment | None) -> str:
    cells: list[str] = []
    aria_parts: list[str] = []
    for dimension in MATURITY_DIMENSIONS:
        abbreviation, label = DIMENSION_LABELS[dimension]
        if assessment is None:
            aria_parts.append(f"{label} not assessed")
            cells.append(
                f'<span class="mini-dimension mini-unassessed" data-cell-state="unassessed" data-abbr="{abbreviation}" title="{_e(label)}: not assessed">—</span>'
            )
            continue
        score = float(assessment.scores[dimension])
        citations = assessment.citations[dimension]
        status = assessment.dimension_status.get(dimension)
        if status in {"unassessed", "unsupported"}:
            aria_parts.append(f"{label} {status}")
            cells.append(
                f'<span class="mini-dimension mini-unassessed" data-cell-state="unassessed" '
                f'data-abbr="{abbreviation}" title="{_e(label)}: {_e(status)}">—</span>'
            )
            continue
        percent = max(0.0, min(100.0, score * 100.0))
        starved = status == "missing" or (status is None and score == 0 and not citations)
        state = "starved" if starved else "scored"
        state_label = "evidence-starved" if starved else "scored"
        aria_parts.append(f"{label} {score:.2f}, {len(citations)} citations")
        cells.append(
            f'<span class="mini-dimension mini-{state}" data-cell-state="{state_label}" '
            f'title="{_e(label)}: {score:.2f}, {len(citations)} citations" '
            f'data-abbr="{abbreviation}" style="--score:{percent:.1f}%"></span>'
        )
    return (
        '<span class="mini-dimensions" role="img" aria-label="Seven-dimension maturity: '
        + _e(", ".join(aria_parts))
        + '">'
        + "".join(cells)
        + "</span>"
    )


def _evidence_markup(edges: Sequence[CkmEvidenceEdge]) -> str:
    if not edges:
        return '<p class="empty">No linked evidence.</p>'
    items = []
    order = {"candidate": 0, "confirmed": 1}
    for edge in sorted(
        edges, key=lambda item: (order.get(item.lifecycle, 2), item.source_ref, item.id)
    ):
        items.append(
            f"""<li class="evidence evidence-{_e(edge.lifecycle)}">
              <span class="badge evidence-status">{_e(edge.lifecycle)}</span>
              <code>{_e(edge.evidence_kind)}</code> · {_e(edge.source_ref)}
              <div class="basis">Basis: {_e(edge.basis)}</div>
            </li>"""
        )
    return f'<ul class="evidence-list">{"".join(items)}</ul>'


def _finding_markup(findings: Sequence[CkmFinding]) -> str:
    if not findings:
        return '<p class="empty">No current findings.</p>'
    return (
        '<ul class="finding-list">'
        + "".join(
            f'<li><span class="badge">{_e(item.kind)}</span> '
            f'<strong>{_e(item.dimension.replace("_", " "))}</strong>: {_e(item.statement)} '
            f'<small>({len(item.citations)} citation(s))</small></li>'
            for item in findings
        )
        + "</ul>"
    )


def _honesty_markup(
    assessment: CkmAssessment | None,
    projection: CkmAssessmentProjection | None,
) -> str:
    if assessment is None:
        return (
            '<aside class="honesty"><p>Assessment is unavailable; unavailable is not a zero score.</p>'
            "<p>candidate share unavailable.</p></aside>"
        )
    stale = bool(projection and projection.stale_relative_to_evidence)
    max_share = max(float(value) for value in assessment.candidate_shares.values())
    return (
        '<aside class="honesty"><p>Assessment is available.</p><p>Assessment is '
        + ("stale relative to current evidence." if stale else "current with known evidence.")
        + f"</p><p>Maximum candidate-evidence share is {max_share:.1%}.</p></aside>"
    )


def _capability_markup(
    capability: CkmCapability,
    *,
    depth: int,
    edges: Sequence[CkmEvidenceEdge],
    findings: Sequence[CkmFinding],
    projection: CkmAssessmentProjection | None,
) -> str:
    confirmed, candidate = _edge_counts(edges)
    assessment = projection.assessment if projection else None
    summary_flags: list[str] = []
    if projection and projection.stale_relative_to_evidence:
        summary_flags.append('<span class="flag flag-stale">STALE relative to evidence</span>')
    if assessment and assessment.low_confidence:
        summary_flags.append('<span class="flag flag-low">LOW CONFIDENCE</span>')
    if assessment:
        max_candidate_share = max(float(v) for v in assessment.candidate_shares.values())
        if max_candidate_share > 0:
            summary_flags.append(
                f'<span class="flag flag-candidate">CAND {max_candidate_share:.1%}</span>'
            )
    if findings:
        summary_flags.append(
            f'<a class="flag gap-link" href="#gaps-{_e(capability.id)}">{len(findings)} gap{"s" if len(findings) != 1 else ""}</a>'
        )
    dimensions = (
        "".join(
            _dimension_markup(
                dimension,
                float(assessment.scores[dimension]),
                assessment.citations[dimension],
                float(assessment.candidate_shares[dimension]),
                assessment.dimension_status.get(dimension),
            )
            for dimension in MATURITY_DIMENSIONS
        )
        if assessment
        else '<p class="empty">Assessment missing.</p>'
    )
    return f"""
    <article id="cap-{_e(capability.id)}" class="capability" data-capability-id="{_e(capability.id)}" style="--depth:{depth}" aria-label="{_e(capability.name)}, depth {depth}">
      <details class="capability-details">
        <summary class="capability-summary">
          <span class="tree-name">{_e(capability.name)}</span>
          <span class="summary-flags">{"".join(summary_flags)}</span>
          {_mini_dimensions_markup(assessment)}
          <span class="lifecycle">node: {_e(capability.lifecycle)}</span>
        </summary>
        <div class="capability-body">
          <p>{_e(capability.definition)}</p>
          <p class="meta">ID: <code>{_e(capability.id)}</code> · Boundary: <strong>{_e(capability.boundary_ref or '—')}</strong> · Evidence: <strong>{confirmed} confirmed / {candidate} candidate</strong></p>
          {_honesty_markup(assessment, projection)}
          <div class="dimensions">{dimensions}</div>
          <details class="drilldown"><summary>Evidence and basis</summary>{_evidence_markup(edges)}</details>
          <details class="drilldown"><summary>Findings</summary>{_finding_markup(findings)}</details>
        </div>
      </details>
    </article>"""


def _legend() -> str:
    dimensions = "".join(
        f"<li><code>{abbr}</code> {_e(label)}</li>" for abbr, label in DIMENSION_LABELS.values()
    )
    return f"""<aside class="legend" aria-label="Maturity legend">
      <div><strong>Dimensions</strong><ul>{dimensions}</ul></div>
      <div><strong>Cell states</strong><ul>
        <li data-cell-state="scored"><span class="legend-cell scored"></span>scored — proportional fill</li>
        <li data-cell-state="evidence-starved"><span class="legend-cell starved"></span>evidence-starved — zero with no citations</li>
        <li data-cell-state="unassessed"><span class="legend-cell unassessed">—</span>unassessed — unavailable, not zero</li>
      </ul></div>
    </aside>"""


def _trust_strip(
    capabilities: Sequence[CkmCapability],
    assessments: Mapping[str, tuple[CkmAssessment | None, CkmAssessmentProjection | None]],
    finding_count: int,
) -> str:
    assessed = sum(assessment is not None for assessment, _ in assessments.values())
    stale = sum(
        bool(projection and projection.stale_relative_to_evidence)
        for _, projection in assessments.values()
    )
    low = sum(
        bool(assessment and assessment.low_confidence) for assessment, _ in assessments.values()
    )
    return f"""<nav class="trust-strip" aria-label="Projection trust summary">
      <a href="#map-heading">{len(capabilities)} capabilities</a>
      <a href="#map-heading">{assessed} assessed</a>
      <a href="#map-heading">{stale} stale</a>
      <a href="#map-heading">{low} low confidence</a>
      <a href="#gaps-heading">{finding_count} gaps</a>
    </nav>"""


def render_overview_html(
    store: CkmStore,
    *,
    generated_at: str | None = None,
    class_capture_limit: int | None = None,
    aggregate_capture_limit: int | None = None,
    cockpit: CockpitRenderContext | None = None,
) -> str:
    """Render one self-contained CKM projection without mutating the store."""

    timestamp = generated_at or utc_now()
    capture_limits: dict[str, int] = {}
    if class_capture_limit is not None:
        capture_limits["class_capture_limit"] = class_capture_limit
    if aggregate_capture_limit is not None:
        capture_limits["aggregate_capture_limit"] = aggregate_capture_limit
    batch = cockpit.batch if cockpit is not None else store.load_projection_batch(**capture_limits)
    capabilities = batch.capabilities
    capability_by_id = {item.id: item for item in capabilities}
    all_findings = tuple(
        finding for findings in batch.findings_by_capability.values() for finding in findings
    )
    assessments = {
        capability.id: (
            projection.assessment
            if (projection := batch.assessments_by_capability.get(capability.id))
            else None,
            projection,
        )
        for capability in capabilities
    }
    forest = _forest(capabilities)
    cards = (
        "".join(
            _capability_markup(
                capability,
                depth=depth,
                edges=batch.edges_by_capability.get(capability.id, ()),
                findings=batch.findings_by_capability.get(capability.id, ()),
                projection=batch.assessments_by_capability.get(capability.id),
            )
            for depth, capability in forest
        )
        or '<p class="empty">No capabilities in the CKM store.</p>'
    )
    grouped: dict[str, list[CkmFinding]] = defaultdict(list)
    for finding in all_findings:
        grouped[finding.capability_id].append(finding)
    gap_groups = (
        "".join(
            f'<li id="gaps-{_e(capability_id)}" class="gap-group"><a href="#cap-{_e(capability_id)}"><strong>{_e(capability_by_id[capability_id].name)}</strong></a>'
            + _finding_markup(findings)
            + "</li>"
            for capability_id, findings in sorted(grouped.items())
            if capability_id in capability_by_id
        )
        or "<li>No current findings.</li>"
    )
    watermark_text = _watermarks(batch.current_watermark_set)
    cockpit_header = _cockpit_trust_markup(batch, timestamp) if cockpit else ""
    cockpit_reserved = (
        _cockpit_hazards_markup(batch) + _cockpit_reserved_markup() if cockpit else ""
    )
    cockpit_proposals = _cockpit_proposals_markup() if cockpit else ""
    cockpit_gap_prompt = "<p>Where is evidence weakest?</p>" if cockpit else ""
    overview_header = (
        cockpit_header
        if cockpit
        else '<header><h1>Development Overview</h1><p class="subtitle">Capability Knowledge Model maturity, trust, and cited drill-down.</p></header>'
    )
    subsystem_counts = _subsystem_counts_markup(forest, batch.edges_by_capability)
    footer_identity = (
        f"<br>State identity: epoch {_e(batch.state_identity.epoch)} · revision {batch.state_identity.state_revision} · schema {batch.state_identity.schema_version}<br>projection-input digest: <code>{_cockpit_digest(batch)}</code>"
        if cockpit
        else ""
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>CKM Development Overview</title>
  <style>
    :root {{ --bg-base:#070b12; --bg-surface:#0c1220; --bg-raised:#111a2e; --bg-overlay:#162038; --fg-1:#dce8f0; --fg-2:#7a9ab8; --fg-3:#527190; --border:#152030; --border-strong:#1e3050; --accent:#d4a843; --agent:#4a9eff; --amber:#f09030; --destructive:#ff3d3d; --healthy:#39e87d; --unknown:#527190; }}
    * {{ box-sizing:border-box; }} html {{ font-size:1rem; }} body {{ margin:0; background:var(--bg-base); color:var(--fg-1); font:0.875rem/1.5 ui-sans-serif,system-ui,sans-serif; }}
    main,footer {{ width:min(74rem,calc(100% - 2rem)); margin:0 auto; }} a {{ color:inherit; }} summary:focus-visible,a:focus-visible {{ outline:2px solid var(--accent); outline-offset:2px; }}
    .projection-banner {{ border-left:0.25rem solid var(--amber); background:var(--bg-raised); padding:0.75rem 1rem; color:var(--fg-2); }} header {{ padding:1.75rem 0 0.75rem; }} h1 {{ font:400 1.75rem/1.2 ui-serif,Georgia,serif; }} h2 {{ margin-top:1.5rem; }} .subtitle,.empty,small,.meta {{ color:var(--fg-2); }}
    .trust-strip {{ display:grid; grid-template-columns:repeat(5,1fr); border:1px solid var(--border-strong); background:var(--bg-surface); }} .trust-strip a {{ padding:0.625rem; text-decoration:none; border-right:1px solid var(--border); }}
    .linkage-masthead {{ padding:0.75rem; border-left:0.25rem solid var(--agent); background:var(--bg-raised); }} .subsystem-counts-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(22rem,1fr)); gap:0.75rem; }} .subsystem-counts-card {{ border:1px solid var(--border); background:var(--bg-surface); padding:0.75rem; }} .subsystem-counts-card h3 {{ margin:0; }} .subsystem-counts-card ul {{ list-style:none; margin:0.75rem 0 0; padding:0; }} .capability-count {{ display:grid; grid-template-columns:minmax(10rem,1fr) repeat(3,auto); gap:0.5rem 1rem; margin-left:calc(var(--count-depth) * 0.75rem); padding:0.45rem 0; border-top:1px solid var(--border); }} .count-name {{ font-weight:600; }} .secondary {{ color:var(--fg-2); }}
    .legend {{ display:grid; grid-template-columns:2fr 1fr; gap:1rem; margin:1rem 0; padding:0.75rem; border:1px solid var(--border); background:var(--bg-surface); }} .legend ul {{ display:flex; gap:0.5rem 1rem; flex-wrap:wrap; list-style:none; padding:0; margin:0.35rem 0 0; }} .legend-cell {{ display:inline-block; width:1.5rem; height:0.5rem; margin-right:0.3rem; background:var(--agent); }} .legend-cell.starved {{ border:1px dotted var(--amber); background:transparent; }} .legend-cell.unassessed {{ height:auto; background:none; color:var(--fg-3); }}
    .dimension-rail {{ position:sticky; top:0; z-index:2; display:grid; grid-template-columns:repeat(7,1fr); gap:0.25rem; margin-left:auto; width:13rem; padding:0.25rem; background:var(--bg-base); color:var(--fg-2); font:0.7rem ui-monospace,monospace; text-align:center; }}
    .capability {{ margin:0.5rem 0 0.5rem calc(var(--depth) * 1.375rem); border:1px solid var(--border); border-left:0.25rem solid var(--unknown); border-radius:0.25rem; background:var(--bg-surface); }}
    summary {{ cursor:pointer; }} summary::before {{ content:"+"; color:var(--fg-2); font-family:ui-monospace,monospace; }} details[open] > summary::before {{ content:"−"; }} .capability-summary {{ min-height:2.75rem; display:flex; gap:0.5rem; align-items:center; padding:0.625rem 0.75rem; }} .capability-summary:hover {{ background:var(--bg-overlay); }} .tree-name {{ flex:1; font-weight:600; }}
    .summary-flags {{ display:flex; gap:0.25rem; }} .flag,.badge,.lifecycle {{ border:1px solid var(--border-strong); border-radius:0.1875rem; padding:0.125rem 0.375rem; font:0.7rem ui-monospace,monospace; white-space:nowrap; }} .flag-stale {{ background:var(--amber); color:var(--bg-base); }} .flag-low {{ border-color:var(--amber); color:var(--amber); }} .flag-candidate {{ border-color:var(--agent); color:var(--agent); }} .gap-link {{ color:var(--accent); text-decoration:none; }}
    .mini-dimensions {{ display:grid; grid-template-columns:repeat(7,1.625rem); gap:0.25rem; }} .mini-dimension {{ position:relative; width:1.625rem; height:0.75rem; border:1px solid var(--border-strong); overflow:hidden; }} .mini-scored {{ background:linear-gradient(to right,var(--agent) var(--score),var(--bg-overlay) var(--score)); }} .mini-starved {{ border:1px dotted var(--amber); background:transparent; }} .mini-unassessed {{ color:var(--fg-3); text-align:center; line-height:0.55rem; }}
    .capability-body {{ border-top:1px solid var(--border); padding:1rem; background:var(--bg-raised); }} .honesty {{ border-left:0.2rem solid var(--amber); padding-left:0.75rem; color:var(--fg-2); }} .honesty p {{ margin:0.2rem 0; }} .dimensions {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(14rem,1fr)); gap:0.625rem; margin:0.875rem 0; }} .dimension {{ border:1px solid var(--border-strong); padding:0.625rem; }} .dimension-label {{ display:flex; gap:0.5rem; justify-content:space-between; }} .dimension-label span {{ flex:1; }} .dimension-track {{ height:0.5rem; margin:0.4rem 0; background:var(--bg-overlay); overflow:hidden; }} .dimension-starved .dimension-track {{ border:1px dotted var(--amber); background:none; }} .dimension-bar {{ display:block; height:100%; background:var(--agent); }}
    .drilldown,.citations {{ margin-top:0.625rem; }} .evidence-list,.finding-list {{ padding-left:1.25rem; }} .evidence-list li,.finding-list li {{ margin:0.45rem 0; }} .evidence-candidate {{ border-left:0.15rem solid var(--agent); padding-left:0.5rem; }} .basis {{ color:var(--fg-2); margin-left:0.5rem; }} .gaps-panel {{ margin:1.5rem 0; padding:1rem; border:1px solid var(--border); background:var(--bg-surface); }} .gap-group {{ margin:0.75rem 0; }}
    footer {{ margin-top:1.75rem; padding:1rem 0 2.25rem; border-top:1px solid var(--border); color:var(--fg-2); overflow-wrap:anywhere; }}
    @media (max-width:680px) {{ main,footer {{ width:min(100% - 1rem,74rem); }} .trust-strip {{ grid-template-columns:1fr 1fr; }} .subsystem-counts-grid {{ grid-template-columns:1fr; }} .capability-count {{ grid-template-columns:1fr; gap:0.15rem; }} .legend {{ grid-template-columns:1fr; }} .dimension-rail {{ display:none; }} .capability {{ margin-left:calc(var(--depth) * 0.5rem); }} .capability-summary {{ flex-wrap:wrap; align-items:flex-start; }} .tree-name {{ min-width:65%; }} .summary-flags {{ flex-wrap:wrap; }} .mini-dimensions {{ order:6; width:100%; grid-template-columns:repeat(7,minmax(1.5rem,1fr)); }} .mini-dimension {{ width:auto; min-height:1.5rem; }} .mini-dimension::before {{ content:attr(data-abbr); display:block; font:0.55rem ui-monospace,monospace; color:var(--fg-2); }} }}
  </style>
</head>
<body>
  <div class="projection-banner"><strong>Generated projection — not source of truth.</strong> Read watermarks and trust states before maturity values.</div>
  <main>
    {overview_header}
    {"" if cockpit else _trust_strip(capabilities, assessments, len(all_findings))}
    {cockpit_reserved}
    {subsystem_counts}
    <section aria-labelledby="map-heading">
      <h2 id="map-heading">Capability map</h2>
      {_legend()}
      <div class="dimension-rail" aria-hidden="true">{"".join(f"<span>{abbr}</span>" for abbr, _ in DIMENSION_LABELS.values())}</div>
      <div class="capability-tree">{cards}</div>
    </section>
    <section class="gaps-panel" aria-labelledby="gaps-heading"><h2 id="gaps-heading">Current gaps</h2>{cockpit_gap_prompt}<ul>{gap_groups}</ul></section>
    {cockpit_proposals}
  </main>
  <footer class="projection-footer">
    <strong>Generated projection (BuilderOps CKM). Not source of truth.</strong><br>
    Generated: {_e(timestamp)}<br>
    Watermarks: {watermark_text}<br>
    {footer_identity}
    Candidate and confirmed evidence remain distinct. Regenerate from the CKM store; do not edit this file as authority.
  </footer>
</body>
</html>
"""


def write_overview_html(
    store: CkmStore,
    output_path: Path,
    *,
    generated_at: str | None = None,
    class_capture_limit: int | None = None,
    aggregate_capture_limit: int | None = None,
    cockpit: CockpitRenderContext | None = None,
) -> Path:
    if cockpit is None:
        store.ensure_schema()
    rendered = render_overview_html(
        store,
        generated_at=generated_at,
        class_capture_limit=class_capture_limit,
        aggregate_capture_limit=aggregate_capture_limit,
        cockpit=cockpit,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8")
    return output_path
