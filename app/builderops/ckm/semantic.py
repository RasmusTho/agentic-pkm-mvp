"""Fenced semantic association for otherwise-unlinked CKM artifacts.

This is the MVP's only inferred evidence writer.  It deliberately keeps the
provider seam injectable, validates structured output, discards low-confidence
proposals, and writes every accepted edge as an inferred candidate.  Explicit
confirmation is represented by a BuilderOps receipt so it survives rebuilding
the derived ``ckm_*`` tables.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from typing import Any, Callable, Protocol, Sequence

from app.builderops.ckm.models import (
    EVIDENCE_KINDS,
    MATURITY_DIMENSIONS,
    CkmArtifact,
    CkmCapability,
    CkmValidationError,
    utc_now,
)
from app.builderops.ckm.store import CkmStore
from app.components.llm.constrained import register_schema, validate_payload
from app.components.llm.fabric import LLMTaskIntent, get_chat_client

SEMANTIC_SCHEMA_REF = "builderops.ckm.semantic-association.v1"
SEMANTIC_ASSOCIATION_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["proposals"],
    "additionalProperties": False,
    "properties": {
        "proposals": {
            "type": "array",
            "items": {
                "type": "object",
                "required": [
                    "artifact_id",
                    "capability_id",
                    "evidence_kind",
                    "maturity_dimension",
                    "confidence",
                    "rationale",
                ],
                "additionalProperties": False,
                "properties": {
                    "artifact_id": {"type": "string", "minLength": 1},
                    "capability_id": {"type": "string", "minLength": 1},
                    "evidence_kind": {"type": "string", "minLength": 1},
                    "maturity_dimension": {"type": "string", "minLength": 1},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "rationale": {"type": "string", "minLength": 1},
                },
            },
        }
    },
}
register_schema(SEMANTIC_SCHEMA_REF, SEMANTIC_ASSOCIATION_SCHEMA)


class SemanticAssociationError(RuntimeError):
    """The semantic stage ran but its response was not usable."""


class SemanticProviderUnavailable(SemanticAssociationError):
    """No configured provider could execute the bounded association call."""


@dataclass(frozen=True)
class SemanticProposal:
    artifact_id: str
    capability_id: str
    evidence_kind: str
    maturity_dimension: str
    confidence: float
    rationale: str


@dataclass(frozen=True)
class SemanticBatch:
    provider: str
    model: str
    proposals: list[SemanticProposal]


@dataclass(frozen=True)
class SemanticAssociationResult:
    status: str
    proposed: int
    discarded: int
    no_match: int
    provider: str | None
    model: str | None


class SemanticAssociator(Protocol):
    provider: str
    model: str

    def propose(
        self,
        *,
        artifacts: Sequence[CkmArtifact],
        capabilities: Sequence[CkmCapability],
    ) -> SemanticBatch: ...


class FabricSemanticAssociator:
    """Production adapter over the repo's existing routed chat fabric."""

    def __init__(self) -> None:
        try:
            self._client = get_chat_client(
                LLMTaskIntent(
                    # Semantic association is a bounded classification task;
                    # this route is the configured cheap-model tier.
                    task_kind="classify",
                    complexity_hint="low",
                    budget="low",
                    json_schema_required=True,
                )
            )
        except Exception as exc:  # route/config failures are the unavailable path
            raise SemanticProviderUnavailable(str(exc)) from exc
        self.provider = self._client.route.provider
        self.model = self._client.route.model
        if self.provider == "mock":
            raise SemanticProviderUnavailable("mock route is not a semantic association provider")

    def propose(
        self,
        *,
        artifacts: Sequence[CkmArtifact],
        capabilities: Sequence[CkmCapability],
    ) -> SemanticBatch:
        user = json.dumps(
            {
                "artifacts": [
                    {
                        "id": item.id,
                        "source_ref": item.source_ref,
                        "artifact_kind": item.artifact_kind,
                        "provenance": item.provenance[:1000],
                    }
                    for item in artifacts
                ],
                "capabilities": [
                    {"id": item.id, "name": item.name, "definition": item.definition}
                    for item in capabilities
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        try:
            raw = self._client.chat(
                SEMANTIC_SCHEMA_REF,
                {
                    "system": (
                        "Associate only artifacts that clearly evidence an existing capability. "
                        "Return no proposal for uncertainty; never invent capabilities."
                    ),
                    "user": user,
                },
                kind="ckm_associate",
                max_tokens=3000,
                response_format=SEMANTIC_ASSOCIATION_SCHEMA,
            )
        except Exception as exc:
            raise SemanticProviderUnavailable(str(exc)) from exc
        try:
            payload = validate_payload(SEMANTIC_SCHEMA_REF, json.loads(raw))
            proposals = [SemanticProposal(**item) for item in payload["proposals"]]
        except (TypeError, ValueError, KeyError) as exc:
            raise SemanticAssociationError(f"invalid semantic association response: {exc}") from exc
        return SemanticBatch(provider=self.provider, model=self.model, proposals=proposals)


def _unlinked_artifacts(store: CkmStore, limit: int) -> list[CkmArtifact]:
    linked_ids = {edge.artifact_id for edge in store.list_evidence_edges()}
    return [item for item in store.list_artifacts() if item.id not in linked_ids][:limit]


def associate_unlinked_artifacts(
    store: CkmStore,
    *,
    limit: int = 200,
    confidence_floor: float = 0.6,
    client: SemanticAssociator | None = None,
    client_factory: Callable[[], SemanticAssociator | None] = FabricSemanticAssociator,
) -> SemanticAssociationResult:
    if limit <= 0:
        raise ValueError("limit must be positive")
    if not 0 <= confidence_floor <= 1:
        raise ValueError("confidence_floor must be in [0, 1]")
    store.ensure_schema()
    artifacts = _unlinked_artifacts(store, limit)
    if not artifacts:
        return SemanticAssociationResult("ok", 0, 0, 0, None, None)
    capabilities = store.list_capabilities()
    if not capabilities:
        return SemanticAssociationResult("ok", 0, 0, len(artifacts), None, None)
    if client is None:
        try:
            client = client_factory()
        except SemanticProviderUnavailable:
            client = None
    if client is None:
        return SemanticAssociationResult(
            "skipped (llm unavailable)", 0, 0, len(artifacts), None, None
        )
    try:
        batch = client.propose(artifacts=artifacts, capabilities=capabilities)
    except SemanticProviderUnavailable:
        return SemanticAssociationResult(
            "skipped (llm unavailable)", 0, 0, len(artifacts), client.provider, client.model
        )

    artifact_by_id = {item.id: item for item in artifacts}
    capability_ids = {item.id for item in capabilities}
    for proposal in batch.proposals:
        if proposal.artifact_id not in artifact_by_id:
            raise SemanticAssociationError(
                f"proposal references artifact outside the bounded batch: {proposal.artifact_id}"
            )
        if proposal.capability_id not in capability_ids:
            raise SemanticAssociationError(
                f"proposal references unknown capability: {proposal.capability_id}"
            )
        if proposal.evidence_kind not in EVIDENCE_KINDS:
            raise SemanticAssociationError(
                f"proposal has invalid evidence kind: {proposal.evidence_kind}"
            )
        if proposal.maturity_dimension not in MATURITY_DIMENSIONS:
            raise SemanticAssociationError(
                f"proposal has invalid maturity dimension: {proposal.maturity_dimension}"
            )
        if not 0 <= proposal.confidence <= 1:
            raise SemanticAssociationError("proposal confidence must be in [0, 1]")
        if not proposal.rationale.strip():
            raise SemanticAssociationError("proposal rationale must not be empty")

    proposed = 0
    discarded = 0
    matched_artifacts: set[str] = set()
    for proposal in batch.proposals:
        artifact = artifact_by_id.get(proposal.artifact_id)
        if artifact is None:  # pragma: no cover - guarded above
            raise SemanticAssociationError("validated artifact disappeared")
        matched_artifacts.add(proposal.artifact_id)
        if proposal.confidence < confidence_floor:
            discarded += 1
            continue
        before = len(store.list_evidence_edges())
        store.upsert_evidence_edge(
            artifact_id=proposal.artifact_id,
            capability_id=proposal.capability_id,
            evidence_kind=proposal.evidence_kind,
            polarity="supports",
            maturity_dimension=proposal.maturity_dimension,
            confidence=proposal.confidence,
            extraction_method="inferred",
            lifecycle="candidate",
            source_ref=artifact.source_ref,
            basis=proposal.rationale,
            provider=batch.provider,
            model=batch.model,
        )
        proposed += int(len(store.list_evidence_edges()) > before)

    watermark = sha256(
        "\n".join(sorted(item.watermark for item in artifacts)).encode("utf-8")
    ).hexdigest()
    store.set_watermark("semantic_association", f"batch:{watermark}")
    return SemanticAssociationResult(
        status="ok",
        proposed=proposed,
        discarded=discarded,
        no_match=len({item.id for item in artifacts} - matched_artifacts),
        provider=batch.provider,
        model=batch.model,
    )


def _confirmation_payload(store: CkmStore, edge_id: str) -> tuple[dict[str, Any], str, str]:
    edge = store.get_evidence_edge_by_id(edge_id)
    if edge is None:
        raise CkmValidationError(f"evidence edge not found: {edge_id}")
    if edge.extraction_method != "inferred":
        raise CkmValidationError("only inferred evidence edges require confirmation")
    artifact = next(item for item in store.list_artifacts() if item.id == edge.artifact_id)
    capability = store.get_capability(edge.capability_id)
    if capability is None:  # pragma: no cover - foreign keys make this defensive
        raise CkmValidationError(f"capability not found: {edge.capability_id}")
    payload = asdict(edge)
    payload["artifact_source_ref"] = artifact.source_ref
    payload["capability_name"] = capability.name
    return payload, artifact.source_ref, capability.name


def confirm_edge(store: CkmStore, edge_id: str) -> dict[str, Any]:
    payload, artifact_ref, capability_name = _confirmation_payload(store, edge_id)
    payload["lifecycle"] = "confirmed"
    receipt = store.append_builderops_receipt(
        source_refs=[{"ref_type": "ckm_evidence_edge", "ref": edge_id}],
        summary=f"Confirmed inferred CKM edge for {capability_name}",
        event_type="ckm_edge_confirmed",
        actor={"actor_type": "human", "id": "operator"},
        occurred_at=utc_now(),
        target_refs=[
            {"ref_type": "repo_artifact", "ref": artifact_ref},
            {"ref_type": "ckm_capability", "ref": capability_name},
        ],
        action="confirm_edge",
        receipt_body=json.dumps(payload, ensure_ascii=False, sort_keys=True),
        idempotency_key=(
            f"ckm-confirm:{artifact_ref}:{capability_name}:{payload['basis']}"
        ),
    )
    # Receipt first: if the derived-row update fails, the durable confirmation
    # intent still exists and the normal rebuild/reapply path can restore it.
    store.confirm_inferred_edge(edge_id)
    return receipt


def reapply_confirmation_receipts(store: CkmStore) -> int:
    restored = 0
    artifacts = {item.source_ref: item for item in store.list_artifacts()}
    capabilities = {item.name: item for item in store.list_capabilities()}
    for receipt in store.list_builderops_receipts("ckm_edge_confirmed"):
        try:
            payload = json.loads(receipt["receipt_body"])
            artifact = artifacts[payload["artifact_source_ref"]]
            capability = capabilities[payload["capability_name"]]
        except (KeyError, TypeError, ValueError):
            continue
        edge = store.upsert_evidence_edge(
            artifact_id=artifact.id,
            capability_id=capability.id,
            evidence_kind=payload["evidence_kind"],
            polarity=payload["polarity"],
            maturity_dimension=payload["maturity_dimension"],
            confidence=payload["confidence"],
            extraction_method="inferred",
            lifecycle="candidate",
            source_ref=artifact.source_ref,
            basis=payload["basis"],
            provider=payload["provider"],
            model=payload["model"],
        )
        if store.confirm_inferred_edge(edge.id).lifecycle == "confirmed":
            restored += 1
    return restored


__all__ = [
    "FabricSemanticAssociator",
    "SemanticAssociationError",
    "SemanticAssociationResult",
    "SemanticBatch",
    "SemanticProposal",
    "associate_unlinked_artifacts",
    "confirm_edge",
    "reapply_confirmation_receipts",
]
