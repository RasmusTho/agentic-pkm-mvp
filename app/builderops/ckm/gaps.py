"""Deterministic, cited CKM gap and missing-evidence detection."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from app.builderops.ckm.assess import assessment_fingerprint
from app.builderops.ckm.models import (
    MATURITY_DIMENSIONS,
    CkmArtifact,
    CkmAssessment,
    CkmCapability,
    CkmEvidenceEdge,
    CkmValidationError,
)
from app.builderops.ckm.store import CkmStore


_DELIVERED_STATE = re.compile(r"\b(delivered|implemented|shipped|live|baseline)\b", re.I)
_NON_CURRENT_STATE = re.compile(
    r"\b(?:future|planned|target(?:[- ]state)?|draft|candidate|historical|superseded|advisory|not yet|unimplemented)\b"
    r"|\b(?:does\s+not|doesn't|not|no|never|without)\s+(?:\w+\s+){0,3}"
    r"(?:delivered|implemented|shipped|live|baseline)\b",
    re.I,
)


@dataclass(frozen=True)
class GapDetectionConfig:
    floor: float = 0.5
    healthy_floor: float = 0.75
    healthy_sibling_count: int = 2

    def validate(self) -> "GapDetectionConfig":
        if not 0.0 <= self.floor <= 1.0:
            raise CkmValidationError("gap floor must be between 0 and 1")
        if not 0.0 <= self.healthy_floor <= 1.0:
            raise CkmValidationError("healthy sibling floor must be between 0 and 1")
        if self.healthy_sibling_count < 1:
            raise CkmValidationError("healthy sibling count must be positive")
        return self


@dataclass(frozen=True)
class GapDetectionResult:
    findings: int
    starved_dimensions: int
    uncovered_boundaries: int
    claim_exceeds_evidence: int
    stale_assessments: int = 0


def _artifact_payload(artifact: CkmArtifact) -> Mapping[str, object]:
    try:
        value = json.loads(artifact.provenance)
    except (json.JSONDecodeError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def _artifact_citation(artifact: CkmArtifact, *, role: str) -> dict[str, object]:
    return {
        "role": role,
        "artifact_id": artifact.id,
        "source_ref": artifact.source_ref,
        "artifact": artifact.to_dict(),
    }


def _edge_citation(
    edge: CkmEvidenceEdge,
    artifact: CkmArtifact,
    *,
    role: str,
) -> dict[str, object]:
    return {
        "role": role,
        "edge_id": edge.id,
        "artifact_id": artifact.id,
        "source_ref": edge.source_ref,
        "edge": edge.to_dict(),
        "artifact": artifact.to_dict(),
    }


def _dedupe_citations(citations: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    seen: set[str] = set()
    for citation in citations:
        normalized = dict(citation)
        key = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
        if key not in seen:
            seen.add(key)
            result.append(normalized)
    return result


def _state_claim(artifact: CkmArtifact) -> str | None:
    summary = str(_artifact_payload(artifact).get("payload_summary", ""))
    match = re.search(r"state:\s*(.+)$", summary, flags=re.I)
    if match is None:
        return None
    state = match.group(1).strip()
    if _NON_CURRENT_STATE.search(state) or not _DELIVERED_STATE.search(state):
        return None
    return state


def _seed_source_ref(capability: CkmCapability) -> str | None:
    marker = "seeded:"
    if not capability.existence_provenance.startswith(marker):
        return None
    source = capability.existence_provenance[len(marker) :].split("::", 1)[0].strip()
    return source or None


def _is_merged_pr(edge: CkmEvidenceEdge, artifact: CkmArtifact) -> bool:
    return (
        edge.evidence_kind == "pull_request"
        and artifact.artifact_kind == "pull_request"
        and bool(_artifact_payload(artifact).get("merged_at"))
    )


def _counts_as_missing_class_evidence(
    edge: CkmEvidenceEdge,
    artifact: CkmArtifact,
    dimension: str,
) -> bool:
    if edge.lifecycle != "confirmed" or edge.polarity != "supports":
        return False
    if dimension == "functional_completeness":
        return edge.evidence_kind == "source" or _is_merged_pr(edge, artifact)
    return edge.evidence_kind in {"benchmark", "ci_result", "coverage", "test"}


def _validate_assessment_snapshot(
    store: CkmStore,
    capabilities: Sequence[CkmCapability],
    artifacts: Mapping[str, CkmArtifact],
    edges_by_capability: Mapping[str, list[CkmEvidenceEdge]],
) -> tuple[dict[str, CkmAssessment], set[str], dict[str, str]]:
    current_watermarks = store.current_watermark_set()
    if not current_watermarks:
        raise CkmValidationError("cannot detect gaps before ingestion records a watermark")
    latest: dict[str, CkmAssessment] = {}
    stale_assessments: set[str] = set()
    for capability in capabilities:
        if capability.lifecycle != "confirmed" or _seed_source_ref(capability) is None:
            continue
        assessment = store.latest_assessment_for_capability(capability.id)
        if assessment is None:
            raise CkmValidationError(
                f"cannot detect gaps before assessing seeded capability: {capability.name}"
            )
        if dict(assessment.watermark_set) != current_watermarks:
            stale_assessments.add(capability.id)
        current_fingerprint = assessment_fingerprint(
            edges_by_capability.get(capability.id, []), artifacts
        )
        if assessment.edge_fingerprint != current_fingerprint:
            raise CkmValidationError(
                f"assessment does not match current evidence for capability: {capability.name}"
            )
        latest[capability.id] = assessment
    return latest, stale_assessments, current_watermarks


def _assessment_citation(
    assessment: CkmAssessment,
    *,
    detector: str,
    stale: bool,
    current_watermarks: Mapping[str, str],
    **details: object,
) -> dict[str, object]:
    return {
        "role": "assessment",
        "detector": detector,
        "assessment_id": assessment.id,
        "assessment_watermark_set": dict(assessment.watermark_set),
        "current_watermark_set": dict(current_watermarks),
        "stale_relative_to_global_evidence": stale,
        **details,
    }


def detect_gaps(
    store: CkmStore,
    *,
    config: GapDetectionConfig | None = None,
) -> GapDetectionResult:
    """Replace current findings from one coherent assessment/evidence snapshot."""

    resolved = (config or GapDetectionConfig()).validate()
    store.ensure_schema()
    capabilities = store.list_capabilities()
    artifacts = {artifact.id: artifact for artifact in store.list_artifacts()}
    artifacts_by_ref = {artifact.source_ref: artifact for artifact in artifacts.values()}
    edges = store.list_evidence_edges()
    edges_by_capability: dict[str, list[CkmEvidenceEdge]] = {}
    for edge in edges:
        edges_by_capability.setdefault(edge.capability_id, []).append(edge)
    assessments, stale_assessments, current_watermarks = _validate_assessment_snapshot(
        store, capabilities, artifacts, edges_by_capability
    )
    findings: dict[tuple[str, str, str], dict[str, Any]] = {}

    # Starved dimensions compare one weak score with a genuinely healthy sibling set.
    for capability in capabilities:
        assessment = assessments.get(capability.id)
        if assessment is None:
            continue
        scores = assessment.scores
        for dimension in MATURITY_DIMENSIONS:
            score = float(scores[dimension])
            if score >= resolved.floor:
                continue
            healthy = sorted(
                (
                    sibling
                    for sibling in MATURITY_DIMENSIONS
                    if sibling != dimension
                    and float(scores[sibling]) >= resolved.healthy_floor
                ),
                key=lambda sibling: (-float(scores[sibling]), sibling),
            )
            if len(healthy) < resolved.healthy_sibling_count:
                continue
            strongest = healthy[0]
            evidence = list(assessment.citations[dimension])
            if not evidence:
                evidence = list(assessment.citations[strongest])
            if not evidence:
                raise CkmValidationError(
                    f"healthy assessment lacks cited evidence for capability: {capability.name}"
                )
            citations = _dedupe_citations(
                [
                    *evidence,
                    _assessment_citation(
                        assessment,
                        detector="starved_dimension",
                        stale=capability.id in stale_assessments,
                        current_watermarks=current_watermarks,
                        formula_id=assessment.formula_ids[dimension],
                    ),
                ]
            )
            statement = (
                f"{capability.name}: {dimension.replace('_', ' ')} is {score:.2f}, below "
                f"the {resolved.floor:.2f} floor, while {strongest.replace('_', ' ')} is "
                f"{float(scores[strongest]):.2f}; "
                f"{len(assessment.citations[dimension])} cited evidence item(s) support the weak dimension."
            )
            findings[("gap", capability.id, dimension)] = {
                "kind": "gap",
                "capability_id": capability.id,
                "dimension": dimension,
                "statement": statement,
                "citations": citations,
                "detector": "starved_dimension",
            }

    # Boundary coverage is aggregated across the seeded boundary and all mapped capabilities.
    boundary_groups: dict[str, list[CkmCapability]] = {}
    for capability in capabilities:
        if (
            capability.lifecycle == "confirmed"
            and capability.boundary_ref
            and _seed_source_ref(capability) is not None
        ):
            boundary_groups.setdefault(capability.boundary_ref, []).append(capability)
    for boundary_ref, members in sorted(boundary_groups.items()):
        member_ids = {member.id for member in members}
        covered = False
        for member in members:
            for edge in edges_by_capability.get(member.id, []):
                artifact = artifacts[edge.artifact_id]
                if edge.lifecycle != "confirmed" or edge.polarity != "supports":
                    continue
                if edge.evidence_kind == "source" or _is_merged_pr(edge, artifact):
                    covered = True
                    break
            if covered:
                break
        if covered:
            continue
        anchor = next(
            (member for member in members if member.id in {item.parent_id for item in members}),
            min(members, key=lambda item: item.name),
        )
        source_ref = _seed_source_ref(anchor)
        seed_artifact = artifacts_by_ref.get(source_ref or "")
        if seed_artifact is None:
            raise CkmValidationError(
                f"seed source artifact is missing for uncovered boundary: {boundary_ref}"
            )
        key = ("gap", anchor.id, "functional_completeness")
        prior = findings.get(key)
        citations = [_artifact_citation(seed_artifact, role="seed_artifact")]
        if prior is not None:
            citations.extend(prior["citations"])
        anchor_assessment = assessments[anchor.id]
        citations.append(
            _assessment_citation(
                anchor_assessment,
                detector="uncovered_boundary",
                stale=anchor.id in stale_assessments,
                current_watermarks=current_watermarks,
                boundary_ref=boundary_ref,
                mapped_capability_ids=sorted(member_ids),
            )
        )
        findings[key] = {
            "kind": "gap",
            "capability_id": anchor.id,
            "dimension": "functional_completeness",
            "statement": (
                f"{anchor.name}: functional completeness has an uncovered {boundary_ref} boundary; "
                f"{len(members)} mapped capability/capabilities have zero confirmed source or merged-PR evidence."
            ),
            "citations": _dedupe_citations(citations),
            "detector": "uncovered_boundary",
        }

    # Delivered-state claims are grouped per capability and missing evidence class.
    claim_groups: dict[tuple[str, str], list[tuple[CkmArtifact, CkmEvidenceEdge, str]]] = {}
    for edge in edges:
        artifact = artifacts[edge.artifact_id]
        if (
            edge.lifecycle != "confirmed"
            or edge.polarity != "supports"
            or artifact.artifact_kind not in {"document", "spec"}
        ):
            continue
        claim = _state_claim(artifact)
        assessment = assessments.get(edge.capability_id)
        if claim is None or assessment is None:
            continue
        for dimension in ("functional_completeness", "test_completeness"):
            if float(assessment.scores[dimension]) < resolved.floor:
                claim_groups.setdefault((edge.capability_id, dimension), []).append(
                    (artifact, edge, claim)
                )
    capability_by_id = {capability.id: capability for capability in capabilities}
    missing_kinds = {
        "functional_completeness": ["pull_request", "source"],
        "test_completeness": ["benchmark", "ci_result", "coverage", "test"],
    }
    for (capability_id, dimension), claims in sorted(claim_groups.items()):
        capability = capability_by_id[capability_id]
        assessment = assessments[capability_id]
        evidence_kinds = missing_kinds[dimension]
        observed = sum(
            1
            for edge in edges_by_capability.get(capability_id, [])
            if _counts_as_missing_class_evidence(
                edge, artifacts[edge.artifact_id], dimension
            )
        )
        unique_claims = {
            (artifact.id, edge.id): (artifact, edge, claim)
            for artifact, edge, claim in claims
        }
        citations = [
            _edge_citation(edge, artifact, role="claiming_artifact")
            for artifact, edge, _claim in sorted(
                unique_claims.values(), key=lambda item: (item[0].source_ref, item[1].id)
            )
        ]
        citations.append(
            {
                "role": "missing_evidence_class",
                "dimension": dimension,
                "evidence_kinds": evidence_kinds,
                "observed_edge_count": observed,
            }
        )
        citations.append(
            _assessment_citation(
                assessment,
                detector="claim_exceeds_evidence",
                stale=capability_id in stale_assessments,
                current_watermarks=current_watermarks,
                formula_id=assessment.formula_ids[dimension],
            )
        )
        source_refs = sorted({artifact.source_ref for artifact, _edge, _claim in claims})
        findings[("missing_evidence", capability_id, dimension)] = {
            "kind": "missing_evidence",
            "capability_id": capability_id,
            "dimension": dimension,
            "statement": (
                f"{capability.name}: {', '.join(source_refs)} claims delivered/live/baseline state, "
                f"but {dimension.replace('_', ' ')} is {float(assessment.scores[dimension]):.2f}; "
                f"missing evidence class {', '.join(evidence_kinds)} has {observed} confirmed edge(s)."
            ),
            "citations": _dedupe_citations(citations),
            "detector": "claim_exceeds_evidence",
        }

    ordered = [findings[key] for key in sorted(findings)]
    persisted = store.replace_findings(
        [
            {field: finding[field] for field in ("kind", "capability_id", "dimension", "statement", "citations")}
            for finding in ordered
        ]
    )
    detectors = [finding["detector"] for finding in ordered]
    return GapDetectionResult(
        findings=len(persisted),
        starved_dimensions=detectors.count("starved_dimension"),
        uncovered_boundaries=detectors.count("uncovered_boundary"),
        claim_exceeds_evidence=detectors.count("claim_exceeds_evidence"),
        stale_assessments=len(stale_assessments),
    )
