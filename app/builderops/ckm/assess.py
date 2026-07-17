"""Transparent, incremental maturity assessment for CKM capabilities.

No score in this module is inferred by an LLM.  ``FORMULAS`` is the
published/versioned formula table; stored assessments carry the exact formula
ids and evidence-edge citations needed to reproduce every value.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Callable, Mapping, Sequence

from app.builderops.ckm.models import (
    MATURITY_DIMENSIONS,
    CkmArtifact,
    CkmEvidenceEdge,
    CkmValidationError,
)
from app.builderops.ckm.store import CkmStore


@dataclass(frozen=True)
class Formula:
    formula_id: str
    dimension: str
    description: str
    weight: float = 1.0


_DIMENSION_FORMULA_IDS = {
    "functional_completeness": "functional-evidence-balance-v1",
    "test_completeness": "test-evidence-balance-v1",
    "documentation_quality": "current-doc-evidence-v1",
    "integration_completeness": "source-and-surface-span-v1",
    "operational_readiness": "operational-evidence-balance-v1",
    "architectural_stability": "architecture-vs-churn-v1",
    "requirement_coverage": "intent-realization-verification-v1",
}
AGGREGATE_FORMULA_ID = "aggregate-weighted-min-v1"

FORMULAS: dict[str, Formula] = {
    "functional-evidence-balance-v1": Formula(
        "functional-evidence-balance-v1",
        "functional_completeness",
        "Realizing source/merged-PR confidence versus declared spec/requirement intent, reduced by weakening evidence.",
    ),
    "test-evidence-balance-v1": Formula(
        "test-evidence-balance-v1",
        "test_completeness",
        "Confidence-weighted executable test and invariant-registry evidence balance.",
    ),
    "current-doc-evidence-v1": Formula(
        "current-doc-evidence-v1",
        "documentation_quality",
        "Current State:-bearing supporting documentation divided by all cited documentation evidence.",
    ),
    "source-and-surface-span-v1": Formula(
        "source-and-surface-span-v1",
        "integration_completeness",
        "Half credit for source realization and half for another caller/surface artifact kind, reduced by integration weaknesses.",
    ),
    "operational-evidence-balance-v1": Formula(
        "operational-evidence-balance-v1",
        "operational_readiness",
        "Confidence-weighted operational/runbook/health evidence balance.",
    ),
    "architecture-vs-churn-v1": Formula(
        "architecture-vs-churn-v1",
        "architectural_stability",
        "Supporting architectural evidence divided by that evidence plus linked commit churn.",
    ),
    "intent-realization-verification-v1": Formula(
        "intent-realization-verification-v1",
        "requirement_coverage",
        "Intent is covered only to the extent the capability also has realizing and verifying evidence.",
    ),
    AGGREGATE_FORMULA_ID: Formula(
        AGGREGATE_FORMULA_ID,
        "aggregate",
        "Minimum of each dimension score multiplied by its published dimension weight.",
    ),
    "legacy-pre-ckm07": Formula(
        "legacy-pre-ckm07",
        "legacy",
        "Migration marker for assessment rows created before formula metadata existed.",
    ),
}


@dataclass(frozen=True)
class DimensionResult:
    score: float
    edges: tuple[CkmEvidenceEdge, ...]


@dataclass(frozen=True)
class AssessmentRunResult:
    assessed: int
    skipped: int
    assessment_ids: tuple[str, ...]


def _edge_balance(edges: Sequence[CkmEvidenceEdge]) -> float:
    supporting = sum(float(edge.confidence) for edge in edges if edge.polarity == "supports")
    weakening = sum(float(edge.confidence) for edge in edges if edge.polarity == "weakens")
    denominator = supporting + weakening
    return 0.0 if denominator == 0 else supporting / denominator


def _dimension_edges(edges: Sequence[CkmEvidenceEdge], dimension: str) -> tuple[CkmEvidenceEdge, ...]:
    return tuple(edge for edge in edges if edge.maturity_dimension == dimension)


def _artifact_payload(artifact: CkmArtifact) -> Mapping[str, object]:
    try:
        value = json.loads(artifact.provenance)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _is_merged_pull_request(
    edge: CkmEvidenceEdge, artifacts: Mapping[str, CkmArtifact]
) -> bool:
    return edge.evidence_kind == "pull_request" and bool(
        _artifact_payload(artifacts[edge.artifact_id]).get("merged_at")
    )


def _functional(edges: Sequence[CkmEvidenceEdge], artifacts: Mapping[str, CkmArtifact]) -> DimensionResult:
    """Compare realized source/merged-PR evidence with declared intent."""

    relevant_kinds = {"source", "pull_request", "spec", "requirement"}
    selected = tuple(
        edge
        for edge in edges
        if edge.evidence_kind in relevant_kinds
        or (
            edge.maturity_dimension == "functional_completeness"
            and edge.polarity == "weakens"
        )
    )
    realization = sum(
        float(edge.confidence)
        for edge in selected
        if edge.polarity == "supports"
        and (
            edge.evidence_kind == "source"
            or _is_merged_pull_request(edge, artifacts)
        )
    )
    intent = sum(
        float(edge.confidence)
        for edge in selected
        if edge.polarity == "supports" and edge.evidence_kind in {"spec", "requirement"}
    )
    base = min(1.0, realization / max(1.0, intent))
    weakening = sum(float(edge.confidence) for edge in selected if edge.polarity == "weakens")
    score = base * (realization / (realization + weakening) if realization + weakening else 0.0)
    return DimensionResult(score, selected)


def _test_completeness(
    edges: Sequence[CkmEvidenceEdge], artifacts: Mapping[str, CkmArtifact]
) -> DimensionResult:
    """Use executable test evidence plus explicit invariant-registry citations."""

    test_kinds = {"test", "coverage", "benchmark", "ci_result"}
    selected = tuple(
        edge
        for edge in edges
        if edge.maturity_dimension == "test_completeness"
        and (
            edge.evidence_kind in test_kinds
            or edge.source_ref == "docs/testing/invariant-tests.md"
        )
    )
    return DimensionResult(_edge_balance(selected), selected)


def _documentation(
    edges: Sequence[CkmEvidenceEdge], artifacts: Mapping[str, CkmArtifact]
) -> DimensionResult:
    selected = _dimension_edges(edges, "documentation_quality")
    selected = tuple(
        edge
        for edge in selected
        if edge.evidence_kind == "doc"
        and artifacts[edge.artifact_id].artifact_kind == "document"
    )
    if not selected:
        return DimensionResult(0.0, ())
    current = 0.0
    total = 0.0
    for edge in selected:
        total += float(edge.confidence)
        summary = str(_artifact_payload(artifacts[edge.artifact_id]).get("payload_summary", ""))
        if (
            edge.polarity == "supports"
            and "State:" in summary
            and "State: (not declared)" not in summary
        ):
            current += float(edge.confidence)
    return DimensionResult(current / total if total else 0.0, selected)


def _integration(
    edges: Sequence[CkmEvidenceEdge], artifacts: Mapping[str, CkmArtifact]
) -> DimensionResult:
    source_edges = tuple(
        edge
        for edge in edges
        if edge.polarity == "supports" and edge.evidence_kind == "source"
    )
    surface_edges = tuple(
        edge
        for edge in edges
        if edge.polarity == "supports"
        and edge.maturity_dimension == "integration_completeness"
        and edge.evidence_kind != "source"
    )
    weakening_edges = tuple(
        edge for edge in edges if edge.maturity_dimension == "integration_completeness" and edge.polarity == "weakens"
    )
    selected = tuple(dict.fromkeys((*source_edges, *surface_edges, *weakening_edges)))
    source_kinds = {artifacts[edge.artifact_id].artifact_kind for edge in source_edges}
    surface_kinds = {artifacts[edge.artifact_id].artifact_kind for edge in surface_edges}
    score = (0.5 if source_kinds else 0.0) + (0.5 if surface_kinds - source_kinds else 0.0)
    supporting_confidence = sum(
        float(edge.confidence) for edge in selected if edge.polarity == "supports"
    )
    weakening_confidence = sum(float(edge.confidence) for edge in weakening_edges)
    if weakening_confidence:
        score *= supporting_confidence / (supporting_confidence + weakening_confidence)
    return DimensionResult(score, selected)


def _operational(
    edges: Sequence[CkmEvidenceEdge], artifacts: Mapping[str, CkmArtifact]
) -> DimensionResult:
    keywords = ("operat", "runbook", "health", "observab", "deploy")
    selected = tuple(
        edge
        for edge in edges
        if edge.evidence_kind == "doc"
        and artifacts[edge.artifact_id].artifact_kind == "document"
        and (
            edge.maturity_dimension == "operational_readiness"
            or any(keyword in artifacts[edge.artifact_id].source_ref.casefold() for keyword in keywords)
        )
    )
    return DimensionResult(_edge_balance(selected), selected)


def _architectural_stability(
    edges: Sequence[CkmEvidenceEdge], artifacts: Mapping[str, CkmArtifact]
) -> DimensionResult:
    architecture = tuple(
        edge for edge in edges if edge.maturity_dimension == "architectural_stability"
    )
    churn = tuple(edge for edge in edges if artifacts[edge.artifact_id].artifact_kind == "commit")
    selected = tuple(dict.fromkeys((*architecture, *churn)))
    stable = sum(
        float(edge.confidence)
        for edge in architecture
        if edge.polarity == "supports"
        and artifacts[edge.artifact_id].artifact_kind != "commit"
    )
    weakening = sum(
        float(edge.confidence)
        for edge in architecture
        if edge.polarity == "weakens"
        and artifacts[edge.artifact_id].artifact_kind != "commit"
    ) + sum(float(edge.confidence) for edge in churn)
    denominator = stable + weakening
    return DimensionResult(stable / denominator if denominator else 0.0, selected)


def _requirement_coverage(
    edges: Sequence[CkmEvidenceEdge], artifacts: Mapping[str, CkmArtifact]
) -> DimensionResult:
    intent = tuple(edge for edge in edges if edge.evidence_kind in {"requirement", "spec"})
    realization = tuple(
        edge
        for edge in edges
        if edge.polarity == "supports"
        and (edge.evidence_kind == "source" or _is_merged_pull_request(edge, artifacts))
    )
    verification = tuple(
        edge
        for edge in edges
        if edge.polarity == "supports"
        and edge.evidence_kind in {"test", "coverage", "benchmark", "ci_result"}
    )
    selected = tuple(dict.fromkeys((*intent, *realization, *verification)))
    supporting_intent = sum(
        float(edge.confidence) for edge in intent if edge.polarity == "supports"
    )
    if not supporting_intent:
        return DimensionResult(0.0, selected)
    realization_coverage = min(
        1.0, sum(float(edge.confidence) for edge in realization) / supporting_intent
    )
    verification_coverage = min(
        1.0, sum(float(edge.confidence) for edge in verification) / supporting_intent
    )
    score = min(realization_coverage, verification_coverage)
    weakening = sum(float(edge.confidence) for edge in intent if edge.polarity == "weakens")
    if weakening:
        score *= supporting_intent / (supporting_intent + weakening)
    return DimensionResult(score, selected)


_SCORERS: Mapping[
    str,
    Callable[[Sequence[CkmEvidenceEdge], Mapping[str, CkmArtifact]], DimensionResult],
] = {
    "functional_completeness": _functional,
    "test_completeness": _test_completeness,
    "documentation_quality": _documentation,
    "integration_completeness": _integration,
    "operational_readiness": _operational,
    "architectural_stability": _architectural_stability,
    "requirement_coverage": _requirement_coverage,
}


def compute_aggregate(scores: Mapping[str, float]) -> float:
    """Published weighted-min aggregate; the seven scores remain primary."""

    missing = set(MATURITY_DIMENSIONS) - set(scores)
    if missing:
        raise CkmValidationError(f"aggregate missing dimension score(s): {sorted(missing)}")
    return min(
        float(scores[dimension]) * FORMULAS[_DIMENSION_FORMULA_IDS[dimension]].weight
        for dimension in MATURITY_DIMENSIONS
    )


def assessment_fingerprint(
    edges: Sequence[CkmEvidenceEdge],
    artifacts: Mapping[str, CkmArtifact],
    *,
    watermark_set: Mapping[str, str],
) -> str:
    edge_payload = [
        {
            "public_id": edge.public_id,
            "artifact_public_id": artifacts[edge.artifact_id].public_id,
            "basis": edge.basis,
            "kind": edge.evidence_kind,
            "polarity": edge.polarity,
            "dimension": edge.maturity_dimension,
            "confidence": edge.confidence,
            "method": edge.extraction_method,
            "lifecycle": edge.lifecycle,
            "model": edge.model,
            "provider": edge.provider,
            "artifact": {
                "kind": artifacts[edge.artifact_id].artifact_kind,
                "source_ref": artifacts[edge.artifact_id].source_ref,
                "watermark": artifacts[edge.artifact_id].watermark,
                "provenance": artifacts[edge.artifact_id].provenance,
            },
        }
        for edge in sorted(edges, key=lambda item: item.public_id)
    ]
    formula_payload = {
        formula_id: {
            "dimension": FORMULAS[formula_id].dimension,
            "description": FORMULAS[formula_id].description,
            "weight": FORMULAS[formula_id].weight,
        }
        for formula_id in (*_DIMENSION_FORMULA_IDS.values(), AGGREGATE_FORMULA_ID)
    }
    payload = {
        "edges": edge_payload,
        "formulae": formula_payload,
        "watermark_set": dict(sorted(watermark_set.items())),
    }
    return "v2:" + hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def legacy_assessment_fingerprint(
    edges: Sequence[CkmEvidenceEdge],
    artifacts: Mapping[str, CkmArtifact],
) -> str:
    """Reproduce the exact pre-v5 append trigger for migration authentication."""

    edge_payload = [
        {
            "id": edge.id,
            "artifact_id": edge.artifact_id,
            "basis": edge.basis,
            "kind": edge.evidence_kind,
            "polarity": edge.polarity,
            "dimension": edge.maturity_dimension,
            "confidence": edge.confidence,
            "method": edge.extraction_method,
            "lifecycle": edge.lifecycle,
            "model": edge.model,
            "provider": edge.provider,
            "artifact": {
                "kind": artifacts[edge.artifact_id].artifact_kind,
                "source_ref": artifacts[edge.artifact_id].source_ref,
                "watermark": artifacts[edge.artifact_id].watermark,
                "provenance": artifacts[edge.artifact_id].provenance,
            },
        }
        for edge in sorted(
            edges, key=lambda item: (item.artifact_id, item.basis, item.id)
        )
    ]
    formula_payload = {
        formula_id: {
            "dimension": FORMULAS[formula_id].dimension,
            "description": FORMULAS[formula_id].description,
            "weight": FORMULAS[formula_id].weight,
        }
        for formula_id in (*_DIMENSION_FORMULA_IDS.values(), AGGREGATE_FORMULA_ID)
    }
    return hashlib.sha256(
        json.dumps(
            {"edges": edge_payload, "formulae": formula_payload},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _citation(edge: CkmEvidenceEdge, artifact: CkmArtifact) -> dict[str, object]:
    """Freeze the complete evidence input behind one historical score."""

    return {
        "edge_id": edge.id,
        "artifact_id": edge.artifact_id,
        "source_ref": edge.source_ref,
        "evidence_kind": edge.evidence_kind,
        "polarity": edge.polarity,
        "lifecycle": edge.lifecycle,
        "edge": edge.to_dict(),
        "artifact": artifact.to_dict(),
    }


def assess_capabilities(store: CkmStore) -> AssessmentRunResult:
    """Append assessments only for capabilities whose evidence set changed."""

    store.ensure_schema()
    watermarks = store.current_watermark_set()
    if not watermarks:
        raise CkmValidationError("cannot assess before ingestion records a source watermark")
    artifacts = {artifact.id: artifact for artifact in store.list_artifacts()}
    assessed_ids: list[str] = []
    skipped = 0
    for capability in store.list_capabilities():
        edges = store.list_evidence_edges_for_capability(capability.id)
        fingerprint = assessment_fingerprint(
            edges, artifacts, watermark_set=watermarks
        )
        latest = store.latest_assessment_for_capability(capability.id)
        if latest is not None and latest.edge_fingerprint == fingerprint:
            skipped += 1
            continue

        scores: dict[str, float] = {}
        citations: dict[str, list[dict[str, object]]] = {}
        candidate_shares: dict[str, float] = {}
        formula_ids: dict[str, str] = {}
        for dimension in MATURITY_DIMENSIONS:
            result = _SCORERS[dimension](edges, artifacts)
            scores[dimension] = max(0.0, min(1.0, result.score))
            citations[dimension] = [
                _citation(edge, artifacts[edge.artifact_id]) for edge in result.edges
            ]
            supporting = [edge for edge in result.edges if edge.polarity == "supports"]
            candidates = [edge for edge in supporting if edge.lifecycle == "candidate"]
            candidate_shares[dimension] = (
                len(candidates) / len(supporting) if supporting else 0.0
            )
            formula_ids[dimension] = _DIMENSION_FORMULA_IDS[dimension]
        assessment = store.append_assessment(
            capability_id=capability.id,
            scores=scores,
            citations=citations,
            candidate_shares=candidate_shares,
            formula_ids=formula_ids,
            aggregate=compute_aggregate(scores),
            aggregate_formula_id=AGGREGATE_FORMULA_ID,
            low_confidence=any(share > 0.5 for share in candidate_shares.values()),
            edge_fingerprint=fingerprint,
            watermark_set=watermarks,
        )
        assessed_ids.append(assessment.id)
    return AssessmentRunResult(
        assessed=len(assessed_ids),
        skipped=skipped,
        assessment_ids=tuple(assessed_ids),
    )
