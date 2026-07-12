"""Object model for the Capability Evidence Graph (CEG).

Mirrors the shape of ``app/builderops/models.py``: this module owns constants,
validation, and lightweight row dataclasses for the ``ckm_*`` tables. It does
not touch SQLite directly (``app/builderops/ckm/schema.py`` owns DDL,
``app/builderops/ckm/store.py`` owns persistence).

Cross-task invariants preserved here (see
``docs/CAPABILITY_KNOWLEDGE_MODEL/README.md``):

- INV-CKM-1 (provenance everywhere): every dataclass below carries a
  provenance-bearing field plus timestamps.
- INV-CKM-3 (candidate vs confirmed, OD-K5): capability and evidence-edge
  lifecycle both distinguish ``candidate`` from ``confirmed``.
- INV-CKM-6 (orthogonality, OD-K3): ``evidence_kind`` is a builder-plane
  analytical type. It never reads, writes, or maps onto the runtime
  ``evidence_role`` / ``authority_state`` / ``source_role`` fields.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping
from uuid import uuid4

JsonDict = dict[str, Any]

# --- Capability -------------------------------------------------------------

CAPABILITY_LIFECYCLE_STATES = frozenset({"candidate", "confirmed", "deprecated"})

# --- Artifact -----------------------------------------------------------------

ARTIFACT_KINDS = frozenset({
    "requirement",
    "adr",
    "document",
    "source_file",
    "test",
    "pull_request",
    "issue",
    "commit",
    "repository",
    "agent_session",
    "decision",
    "diagram",
    "ci_result",
    "coverage",
    "benchmark",
    "learning_signal",
})

# --- Evidence edge --------------------------------------------------------

EVIDENCE_KINDS = frozenset({
    "requirement",
    "spec",
    "adr",
    "design_doc",
    "diagram",
    "source",
    "commit",
    "pull_request",
    "test",
    "coverage",
    "benchmark",
    "ci_result",
    "ai_session",
    "learning_signal",
    "doc",
})

EVIDENCE_POLARITIES = frozenset({"supports", "weakens"})

EXTRACTION_METHODS = frozenset({"deterministic", "inferred"})

# INV-CKM-3: inferred edges are candidate until a human confirmation receipt
# promotes them; deterministic-linker edges are confirmed by construction.
EVIDENCE_EDGE_LIFECYCLE_STATES = frozenset({"candidate", "confirmed"})

# The seven-dimension maturity vector (docs/research/DEVELOPMENT_KNOWLEDGE_MODEL.md :: 6).
MATURITY_DIMENSIONS = (
    "functional_completeness",
    "test_completeness",
    "documentation_quality",
    "integration_completeness",
    "operational_readiness",
    "architectural_stability",
    "requirement_coverage",
)

# --- Finding -----------------------------------------------------------------

FINDING_KINDS = frozenset({"gap", "missing_evidence"})


class CkmValidationError(ValueError):
    """Raised when a CKM object does not satisfy the CEG object-model contract."""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:16]}"


def _require_nonempty_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CkmValidationError(f"{field_name} must be a non-empty string")
    return value


def _require_choice(value: Any, choices: frozenset[str], field_name: str) -> str:
    if value not in choices:
        allowed = ", ".join(sorted(choices))
        raise CkmValidationError(f"{field_name} must be one of: {allowed} (got {value!r})")
    return value


@dataclass(frozen=True)
class CkmCapability:
    """A node in the Capability Evidence Graph: the primary entity."""

    id: str
    name: str
    definition: str
    lifecycle: str
    existence_provenance: str
    created_at: str
    updated_at: str
    parent_id: str | None = None
    boundary_ref: str | None = None

    def validate(self) -> "CkmCapability":
        _require_nonempty_str(self.id, "id")
        _require_nonempty_str(self.name, "name")
        _require_nonempty_str(self.definition, "definition")
        _require_choice(self.lifecycle, CAPABILITY_LIFECYCLE_STATES, "lifecycle")
        _require_nonempty_str(self.existence_provenance, "existence_provenance")
        _require_nonempty_str(self.created_at, "created_at")
        _require_nonempty_str(self.updated_at, "updated_at")
        return self

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "CkmCapability":
        return cls(
            id=row["id"],
            name=row["name"],
            definition=row["definition"],
            parent_id=row["parent_id"],
            lifecycle=row["lifecycle"],
            existence_provenance=row["existence_provenance"],
            boundary_ref=row["boundary_ref"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def to_dict(self) -> JsonDict:
        return {
            "id": self.id,
            "name": self.name,
            "definition": self.definition,
            "parent_id": self.parent_id,
            "lifecycle": self.lifecycle,
            "existence_provenance": self.existence_provenance,
            "boundary_ref": self.boundary_ref,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class CkmArtifact:
    """A normalized reference to a source item (the evidence's other end)."""

    id: str
    source_ref: str
    artifact_kind: str
    source: str
    watermark: str
    provenance: str
    created_at: str
    updated_at: str

    def validate(self) -> "CkmArtifact":
        _require_nonempty_str(self.id, "id")
        _require_nonempty_str(self.source_ref, "source_ref")
        _require_choice(self.artifact_kind, ARTIFACT_KINDS, "artifact_kind")
        _require_nonempty_str(self.source, "source")
        _require_nonempty_str(self.watermark, "watermark")
        _require_nonempty_str(self.provenance, "provenance")
        _require_nonempty_str(self.created_at, "created_at")
        _require_nonempty_str(self.updated_at, "updated_at")
        return self

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "CkmArtifact":
        return cls(
            id=row["id"],
            source_ref=row["source_ref"],
            artifact_kind=row["artifact_kind"],
            source=row["source"],
            watermark=row["watermark"],
            provenance=row["provenance"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def to_dict(self) -> JsonDict:
        return {
            "id": self.id,
            "source_ref": self.source_ref,
            "artifact_kind": self.artifact_kind,
            "source": self.source,
            "watermark": self.watermark,
            "provenance": self.provenance,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class CkmEvidenceEdge:
    """A typed edge linking an Artifact to a Capability.

    ``evidence_kind`` is a builder-plane analytical typing (INV-CKM-6): it is
    never the same field, value space, or meaning as the runtime
    ``evidence_role`` dimension.
    """

    id: str
    artifact_id: str
    capability_id: str
    evidence_kind: str
    polarity: str
    maturity_dimension: str
    confidence: float
    extraction_method: str
    lifecycle: str
    source_ref: str
    created_at: str
    updated_at: str
    model: str | None = None
    provider: str | None = None

    def validate(self) -> "CkmEvidenceEdge":
        _require_nonempty_str(self.id, "id")
        _require_nonempty_str(self.artifact_id, "artifact_id")
        _require_nonempty_str(self.capability_id, "capability_id")
        _require_choice(self.evidence_kind, EVIDENCE_KINDS, "evidence_kind")
        _require_choice(self.polarity, EVIDENCE_POLARITIES, "polarity")
        _require_choice(self.maturity_dimension, frozenset(MATURITY_DIMENSIONS), "maturity_dimension")
        if not isinstance(self.confidence, (int, float)) or not (0.0 <= float(self.confidence) <= 1.0):
            raise CkmValidationError("confidence must be a number in [0.0, 1.0]")
        _require_choice(self.extraction_method, EXTRACTION_METHODS, "extraction_method")
        _require_choice(self.lifecycle, EVIDENCE_EDGE_LIFECYCLE_STATES, "lifecycle")
        if self.extraction_method == "inferred" and not (self.model and self.provider):
            raise CkmValidationError("inferred evidence edges require model and provider")
        _require_nonempty_str(self.source_ref, "source_ref")
        _require_nonempty_str(self.created_at, "created_at")
        _require_nonempty_str(self.updated_at, "updated_at")
        return self

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "CkmEvidenceEdge":
        return cls(
            id=row["id"],
            artifact_id=row["artifact_id"],
            capability_id=row["capability_id"],
            evidence_kind=row["evidence_kind"],
            polarity=row["polarity"],
            maturity_dimension=row["maturity_dimension"],
            confidence=row["confidence"],
            extraction_method=row["extraction_method"],
            model=row["model"],
            provider=row["provider"],
            lifecycle=row["lifecycle"],
            source_ref=row["source_ref"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def to_dict(self) -> JsonDict:
        return {
            "id": self.id,
            "artifact_id": self.artifact_id,
            "capability_id": self.capability_id,
            "evidence_kind": self.evidence_kind,
            "polarity": self.polarity,
            "maturity_dimension": self.maturity_dimension,
            "confidence": self.confidence,
            "extraction_method": self.extraction_method,
            "model": self.model,
            "provider": self.provider,
            "lifecycle": self.lifecycle,
            "source_ref": self.source_ref,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class CkmAssessment:
    """A bitemporal, append-only seven-dimension maturity judgment.

    Never patched in place (INV-CKM-5): a re-assessment is always a new row,
    ordered by ``asserted_at``.
    """

    id: str
    capability_id: str
    scores: Mapping[str, float]
    citations: Mapping[str, list[JsonDict]]
    aggregate: float
    watermark_set: Mapping[str, str]
    valid_from: str
    asserted_at: str

    def validate(self) -> "CkmAssessment":
        _require_nonempty_str(self.id, "id")
        _require_nonempty_str(self.capability_id, "capability_id")
        missing_dims = set(MATURITY_DIMENSIONS) - set(self.scores)
        if missing_dims:
            raise CkmValidationError(f"assessment missing dimension score(s): {sorted(missing_dims)}")
        for dimension in MATURITY_DIMENSIONS:
            score = self.scores[dimension]
            if not isinstance(score, (int, float)) or not (0.0 <= float(score) <= 1.0):
                raise CkmValidationError(f"{dimension} score must be a number in [0.0, 1.0]")
            if dimension not in self.citations or not self.citations[dimension]:
                raise CkmValidationError(f"{dimension} must cite at least one evidence edge")
        if not isinstance(self.aggregate, (int, float)) or not (0.0 <= float(self.aggregate) <= 1.0):
            raise CkmValidationError("aggregate must be a number in [0.0, 1.0]")
        if not self.watermark_set:
            raise CkmValidationError("watermark_set must not be empty")
        _require_nonempty_str(self.valid_from, "valid_from")
        _require_nonempty_str(self.asserted_at, "asserted_at")
        return self

    @classmethod
    def from_row(cls, row: Mapping[str, Any], *, scores, citations, watermark_set) -> "CkmAssessment":
        return cls(
            id=row["id"],
            capability_id=row["capability_id"],
            scores=scores,
            citations=citations,
            aggregate=row["aggregate"],
            watermark_set=watermark_set,
            valid_from=row["valid_from"],
            asserted_at=row["asserted_at"],
        )

    def to_dict(self) -> JsonDict:
        return {
            "id": self.id,
            "capability_id": self.capability_id,
            "scores": dict(self.scores),
            "citations": {k: list(v) for k, v in self.citations.items()},
            "aggregate": self.aggregate,
            "watermark_set": dict(self.watermark_set),
            "valid_from": self.valid_from,
            "asserted_at": self.asserted_at,
        }


@dataclass(frozen=True)
class CkmFinding:
    """A derived gap / missing-evidence finding node."""

    id: str
    kind: str
    capability_id: str
    dimension: str
    statement: str
    citations: list[JsonDict] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""

    def validate(self) -> "CkmFinding":
        _require_nonempty_str(self.id, "id")
        _require_choice(self.kind, FINDING_KINDS, "kind")
        _require_nonempty_str(self.capability_id, "capability_id")
        _require_choice(self.dimension, frozenset(MATURITY_DIMENSIONS), "dimension")
        _require_nonempty_str(self.statement, "statement")
        if not self.citations:
            raise CkmValidationError("citations must not be empty")
        _require_nonempty_str(self.created_at, "created_at")
        _require_nonempty_str(self.updated_at, "updated_at")
        return self

    @classmethod
    def from_row(cls, row: Mapping[str, Any], *, citations: list[JsonDict]) -> "CkmFinding":
        return cls(
            id=row["id"],
            kind=row["kind"],
            capability_id=row["capability_id"],
            dimension=row["dimension"],
            statement=row["statement"],
            citations=citations,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def to_dict(self) -> JsonDict:
        return {
            "id": self.id,
            "kind": self.kind,
            "capability_id": self.capability_id,
            "dimension": self.dimension,
            "statement": self.statement,
            "citations": list(self.citations),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
