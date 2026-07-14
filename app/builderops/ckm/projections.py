"""Non-authoritative Markdown projections over the Capability Evidence Graph."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from app.builderops.ckm.models import (
    MATURITY_DIMENSIONS,
    CkmAssessmentProjection,
    CkmCapability,
    CkmEvidenceEdge,
    CkmFinding,
    CkmValidationError,
    utc_now,
)
from app.builderops.ckm.store import CkmStore


TRACEABILITY_COLUMNS = (
    "#",
    "Principle / finding",
    "Canonical doc",
    "ADR",
    "Ontology concepts",
    "Semantic distinctions",
    "Control boundaries",
    "Contract / schema",
    "Required tests / evals",
    "Implementation issues",
)

PROJECTION_FILENAMES = {
    "ckm-capability-map": "ckm-capability-map.md",
    "ckm-maturity": "ckm-maturity.md",
    "ckm-gaps": "ckm-gaps.md",
    "ckm-traceability-matrix": "ckm-traceability-matrix.md",
}


@dataclass(frozen=True)
class CkmProjectionResult:
    projection_type: str
    path: Path
    generated_at: str


def _markdown(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ").strip()


def _watermark_text(watermarks: Mapping[str, str]) -> str:
    if not watermarks:
        return "none"
    return ", ".join(f"{key}={value}" for key, value in sorted(watermarks.items()))


def _header(
    projection_type: str,
    *,
    generated_at: str,
    watermarks: Mapping[str, str],
) -> list[str]:
    return [
        "State: Generated projection",
        "Authority: non-authoritative BuilderOps CKM projection",
        "Source of truth: CKM evidence store; this file is not source of truth.",
        f"Generated at: {generated_at}",
        f"Projection type: {projection_type}",
        f"Watermarks: {_watermark_text(watermarks)}",
        "Evidence lifecycle: confirmed and candidate evidence are shown separately.",
        "Do not edit: regenerate from the CKM store.",
        "",
    ]


def _edge_counts(edges: Iterable[CkmEvidenceEdge]) -> tuple[int, int]:
    confirmed = 0
    candidate = 0
    for edge in edges:
        if edge.lifecycle == "candidate":
            candidate += 1
        else:
            confirmed += 1
    return confirmed, candidate


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")


def _capability_by_slug(store: CkmStore, slug: str) -> CkmCapability:
    normalized = _slug(slug)
    matches = [item for item in store.list_capabilities() if _slug(item.name) == normalized]
    if not matches:
        raise CkmValidationError(f"unknown capability slug: {slug}")
    if len(matches) > 1:
        raise CkmValidationError(f"ambiguous capability slug: {slug}")
    return matches[0]


def _forest_order(capabilities: Sequence[CkmCapability]) -> list[tuple[int, CkmCapability]]:
    by_parent: dict[str | None, list[CkmCapability]] = {}
    known_ids = {item.id for item in capabilities}
    for item in capabilities:
        parent = item.parent_id if item.parent_id in known_ids else None
        by_parent.setdefault(parent, []).append(item)
    for children in by_parent.values():
        children.sort(key=lambda item: (item.name.casefold(), item.id))

    ordered: list[tuple[int, CkmCapability]] = []
    visited: set[str] = set()

    def visit(item: CkmCapability, depth: int) -> None:
        if item.id in visited:
            return
        visited.add(item.id)
        ordered.append((depth, item))
        for child in by_parent.get(item.id, []):
            visit(child, depth + 1)

    for root in by_parent.get(None, []):
        visit(root, 0)
    # A damaged or mid-migration store must not make capabilities disappear
    # from an observability surface. Render cycles/orphans as additional roots.
    for item in sorted(capabilities, key=lambda value: (value.name.casefold(), value.id)):
        visit(item, 0)
    return ordered


def _render_capability_map(store: CkmStore) -> list[str]:
    capabilities = store.list_capabilities()
    all_edges = store.list_evidence_edges()
    edges_by_capability: dict[str, list[CkmEvidenceEdge]] = {}
    linked_artifacts: set[str] = set()
    for edge in all_edges:
        edges_by_capability.setdefault(edge.capability_id, []).append(edge)
        linked_artifacts.add(edge.artifact_id)
    unlinked = sum(artifact.id not in linked_artifacts for artifact in store.list_artifacts())
    lines = [
        "# CKM Capability Map",
        "",
        f"Unlinked artifacts: **{unlinked}**",
        "",
        "| Capability | Lifecycle | Boundary | Confirmed evidence | Candidate evidence |",
        "| --- | --- | --- | ---: | ---: |",
    ]
    for depth, capability in _forest_order(capabilities):
        confirmed, candidate = _edge_counts(edges_by_capability.get(capability.id, []))
        name = f"{'↳ ' * depth}{capability.name}"
        lines.append(
            f"| {_markdown(name)} | {capability.lifecycle} | "
            f"{_markdown(capability.boundary_ref or '—')} | {confirmed} | {candidate} |"
        )
    return lines


def _assessment_or_none(store: CkmStore, capability_id: str) -> CkmAssessmentProjection | None:
    if store.latest_assessment_for_capability(capability_id) is None:
        return None
    return store.assessment_for_projection(capability_id)


def _render_maturity(store: CkmStore) -> list[str]:
    lines = ["# CKM Maturity", ""]
    for capability in store.list_capabilities():
        edges = store.list_evidence_edges_for_capability(capability.id)
        confirmed, candidate = _edge_counts(edges)
        projection = _assessment_or_none(store, capability.id)
        lines.extend([f"## {_markdown(capability.name)}", ""])
        lines.append(
            f"Evidence: **{confirmed} confirmed / {candidate} candidate**. "
            f"Lifecycle: **{capability.lifecycle}**."
        )
        if projection is None:
            lines.extend(["Assessment: **missing**.", ""])
            continue
        assessment = projection.assessment
        freshness = "STALE relative to evidence" if projection.stale_relative_to_evidence else "current"
        confidence = "LOW CONFIDENCE" if assessment.low_confidence else "normal confidence"
        lines.extend([
            f"Assessment: **{freshness}**; **{confidence}**; "
            f"aggregate convenience score **{assessment.aggregate:.3f}** "
            f"(`{assessment.aggregate_formula_id}`).",
            "",
            "| Dimension | Score | Citations | Candidate share | Formula |",
            "| --- | ---: | ---: | ---: | --- |",
        ])
        for dimension in MATURITY_DIMENSIONS:
            lines.append(
                f"| {dimension} | {assessment.scores[dimension]:.3f} | "
                f"{len(assessment.citations[dimension])} | "
                f"{assessment.candidate_shares[dimension]:.1%} | "
                f"{_markdown(assessment.formula_ids[dimension])} |"
            )
        lines.append("")
    return lines


def _citation_text(citation: Mapping[str, object]) -> str:
    lifecycle = citation.get("lifecycle")
    edge = citation.get("edge")
    if lifecycle is None and isinstance(edge, Mapping):
        lifecycle = edge.get("lifecycle")
    source_ref = citation.get("source_ref")
    artifact = citation.get("artifact")
    if source_ref is None and isinstance(artifact, Mapping):
        source_ref = artifact.get("source_ref")
    role = citation.get("role")
    parts = [str(source_ref or citation.get("missing_evidence_class") or "snapshot")]
    if lifecycle in {"candidate", "confirmed"}:
        parts.append(str(lifecycle))
    elif role:
        parts.append(str(role))
    return " — ".join(parts)


def _render_gaps(store: CkmStore) -> list[str]:
    capabilities = {item.id: item for item in store.list_capabilities()}
    grouped: dict[str, list[CkmFinding]] = {"gap": [], "missing_evidence": []}
    for finding in store.list_findings():
        grouped.setdefault(finding.kind, []).append(finding)
    lines = ["# CKM Gaps and Missing Evidence", ""]
    for kind in ("gap", "missing_evidence"):
        lines.extend([f"## {kind.replace('_', ' ').title()}", ""])
        findings = grouped.get(kind, [])
        if not findings:
            lines.extend(["No current findings.", ""])
            continue
        for finding in findings:
            capability = capabilities.get(finding.capability_id)
            name = capability.name if capability else finding.capability_id
            lines.append(
                f"- **{_markdown(name)} / {finding.dimension}:** {_markdown(finding.statement)}"
            )
            for citation in finding.citations:
                lines.append(f"  - Citation: {_markdown(_citation_text(citation))}")
        lines.append("")
    return lines


def _refs_for_kind(edges: Sequence[CkmEvidenceEdge], kinds: set[str]) -> str:
    values = [
        f"{edge.source_ref} ({edge.lifecycle})"
        for edge in edges
        if edge.evidence_kind in kinds
    ]
    return ", ".join(sorted(set(values))) or "—"


def _render_traceability_matrix(store: CkmStore) -> list[str]:
    lines = [
        "# Generated CKM Traceability Matrix",
        "",
        "This projection is for side-by-side comparison with the canonical, hand-authored matrix.",
        "It never edits `docs/architecture/traceability-matrix.md`.",
        "",
        "| " + " | ".join(TRACEABILITY_COLUMNS) + " |",
        "| " + " | ".join("---" for _ in TRACEABILITY_COLUMNS) + " |",
    ]
    for index, capability in enumerate(store.list_capabilities(), start=1):
        edges = store.list_evidence_edges_for_capability(capability.id)
        row = (
            str(index),
            f"{capability.name} ({capability.lifecycle})",
            capability.existence_provenance,
            _refs_for_kind(edges, {"adr"}),
            capability.name,
            "candidate evidence distinguished from confirmed evidence",
            capability.boundary_ref or "—",
            _refs_for_kind(edges, {"spec", "requirement", "design_doc"}),
            _refs_for_kind(edges, {"test", "coverage", "benchmark", "ci_result"}),
            _refs_for_kind(edges, {"issue", "pull_request", "commit", "source"}),
        )
        lines.append("| " + " | ".join(_markdown(value) for value in row) + " |")
    return lines


def render_projection(
    store: CkmStore,
    projection_type: str,
    *,
    generated_at: str | None = None,
) -> str:
    normalized = projection_type.strip().lower().replace("_", "-")
    if normalized not in PROJECTION_FILENAMES:
        allowed = ", ".join(sorted(PROJECTION_FILENAMES))
        raise CkmValidationError(f"unsupported CKM projection type: {projection_type}; allowed: {allowed}")
    store.ensure_schema()
    timestamp = generated_at or utc_now()
    body = {
        "ckm-capability-map": _render_capability_map,
        "ckm-maturity": _render_maturity,
        "ckm-gaps": _render_gaps,
        "ckm-traceability-matrix": _render_traceability_matrix,
    }[normalized](store)
    return "\n".join(
        _header(normalized, generated_at=timestamp, watermarks=store.current_watermark_set())
        + body
        + [""]
    )


def write_projection(
    store: CkmStore,
    projection_type: str,
    output_dir: Path,
    *,
    generated_at: str | None = None,
) -> CkmProjectionResult:
    normalized = projection_type.strip().lower().replace("_", "-")
    filename = PROJECTION_FILENAMES.get(normalized)
    if filename is None:
        allowed = ", ".join(sorted(PROJECTION_FILENAMES))
        raise CkmValidationError(f"unsupported CKM projection type: {projection_type}; allowed: {allowed}")
    timestamp = generated_at or utc_now()
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / filename
    canonical = Path("docs/architecture/traceability-matrix.md").resolve()
    if path.resolve() == canonical:
        raise CkmValidationError("refusing to overwrite the canonical traceability matrix")
    path.write_text(render_projection(store, normalized, generated_at=timestamp), encoding="utf-8")
    return CkmProjectionResult(normalized, path, timestamp)


def render_capability_show(
    store: CkmStore,
    capability_slug: str,
    *,
    generated_at: str | None = None,
) -> str:
    store.ensure_schema()
    capability = _capability_by_slug(store, capability_slug)
    timestamp = generated_at or utc_now()
    edges = store.list_evidence_edges_for_capability(capability.id)
    confirmed, candidate = _edge_counts(edges)
    lines = _header(
        "ckm-show",
        generated_at=timestamp,
        watermarks=store.current_watermark_set(),
    )
    lines.extend([
        f"# {_markdown(capability.name)}",
        "",
        f"Lifecycle: **{capability.lifecycle}**. Boundary: **{_markdown(capability.boundary_ref or '—')}**.",
        f"Evidence: **{confirmed} confirmed / {candidate} candidate**.",
        "",
    ])
    projection = _assessment_or_none(store, capability.id)
    if projection is None:
        lines.extend(["Assessment: **missing**.", ""])
    else:
        assessment = projection.assessment
        freshness = "STALE relative to evidence" if projection.stale_relative_to_evidence else "current"
        lines.extend([
            f"Assessment: **{freshness}**; aggregate convenience score **{assessment.aggregate:.3f}**.",
            "",
            "| Dimension | Score | Citations | Candidate share |",
            "| --- | ---: | ---: | ---: |",
        ])
        for dimension in MATURITY_DIMENSIONS:
            lines.append(
                f"| {dimension} | {assessment.scores[dimension]:.3f} | "
                f"{len(assessment.citations[dimension])} | "
                f"{assessment.candidate_shares[dimension]:.1%} |"
            )
        lines.append("")
    lines.extend(["## Evidence", ""])
    if not edges:
        lines.append("No linked evidence.")
    for edge in sorted(edges, key=lambda item: (item.lifecycle, item.source_ref, item.id)):
        lines.append(
            f"- **{edge.lifecycle}** `{_markdown(edge.evidence_kind)}` "
            f"[{_markdown(edge.maturity_dimension)}] {_markdown(edge.source_ref)} — "
            f"basis: {_markdown(edge.basis)}"
        )
    return "\n".join(lines + [""])
