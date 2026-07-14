"""Fenced semantic association for otherwise-unlinked CKM artifacts.

This is the MVP's only inferred evidence writer.  It deliberately keeps the
provider seam injectable, validates structured output, discards low-confidence
proposals, and writes every accepted edge as an inferred candidate.  Explicit
confirmation is represented by a BuilderOps receipt so it survives rebuilding
the derived ``ckm_*`` tables.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import hmac
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
from app.components.llm.constrained import (
    ConstrainedCompletionError,
    register_schema,
    validate_payload,
)
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
        except ConstrainedCompletionError as exc:
            raise SemanticAssociationError(
                f"invalid semantic association response: {exc}"
            ) from exc
        except Exception as exc:
            raise SemanticProviderUnavailable(str(exc)) from exc
        try:
            payload = validate_payload(SEMANTIC_SCHEMA_REF, json.loads(raw))
            proposals = [SemanticProposal(**item) for item in payload["proposals"]]
        except ConstrainedCompletionError as exc:
            raise SemanticAssociationError(
                f"invalid semantic association response: {exc}"
            ) from exc
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


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _confirmation_payload(store: CkmStore, edge_id: str) -> tuple[dict[str, Any], str, str]:
    edge = store.get_active_evidence_edge_by_id(edge_id)
    if edge is None:
        raise CkmValidationError(f"evidence edge not found: {edge_id}")
    if edge.extraction_method != "inferred":
        raise CkmValidationError("only inferred evidence edges require confirmation")
    artifact = next(item for item in store.list_artifacts() if item.id == edge.artifact_id)
    capability = store.get_capability(edge.capability_id)
    if capability is None:  # pragma: no cover - foreign keys make this defensive
        raise CkmValidationError(f"capability not found: {edge.capability_id}")
    payload = {
        "edge_id": edge.id,
        "artifact_source_ref": artifact.source_ref,
        "capability_name": capability.name,
        "evidence_kind": edge.evidence_kind,
        "polarity": edge.polarity,
        "maturity_dimension": edge.maturity_dimension,
        "confidence": edge.confidence,
        "extraction_method": edge.extraction_method,
        "lifecycle": "confirmed",
        "source_ref": edge.source_ref,
        "basis": edge.basis,
        "provider": edge.provider,
        "model": edge.model,
    }
    stable_claim = {key: value for key, value in payload.items() if key != "edge_id"}
    payload["confirmation_key"] = sha256(
        _canonical_json(stable_claim).encode("utf-8")
    ).hexdigest()
    return payload, artifact.source_ref, capability.name


def _binding_document(receipt: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    unsigned_payload = {key: value for key, value in payload.items() if key != "binding"}
    return {
        "object_type": "BuilderOpsReceipt",
        "event_type": receipt.get("event_type"),
        "action": receipt.get("action"),
        "actor": receipt.get("actor"),
        "source_refs": receipt.get("source_refs"),
        "target_refs": receipt.get("target_refs"),
        "payload": unsigned_payload,
    }


def _sign_confirmation(
    store: CkmStore, envelope: dict[str, Any], payload: dict[str, Any]
) -> str:
    key = store._confirmation_signing_key(create=True)
    if key is None:  # pragma: no cover - create=True guarantees a key
        raise CkmValidationError("CKM confirmation signing key is unavailable")
    return hmac.new(
        key,
        _canonical_json(_binding_document(envelope, payload)).encode("utf-8"),
        sha256,
    ).hexdigest()


def _validated_confirmation_receipt(
    store: CkmStore,
    receipt: dict[str, Any],
    *,
    expected_edge_id: str | None = None,
) -> tuple[dict[str, Any], CkmArtifact, CkmCapability]:
    """Validate that a durable receipt authorizes exactly one edge promotion."""

    if receipt.get("object_type") != "BuilderOpsReceipt":
        raise CkmValidationError("confirmation record must be a BuilderOpsReceipt")
    if receipt.get("event_type") != "ckm_edge_confirmed":
        raise CkmValidationError("confirmation receipt has an invalid event type")
    if receipt.get("action") != "confirm_edge":
        raise CkmValidationError("confirmation receipt has an invalid action")
    actor = receipt.get("actor")
    if not isinstance(actor, dict) or actor.get("actor_type") != "human":
        raise CkmValidationError("confirmation receipt requires a human actor")
    if not isinstance(actor.get("id"), str) or not actor["id"].strip():
        raise CkmValidationError("confirmation receipt requires a named human actor")
    try:
        payload = json.loads(receipt["receipt_body"])
    except (KeyError, TypeError, ValueError) as exc:
        raise CkmValidationError("confirmation receipt body must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise CkmValidationError("confirmation receipt body must be an object")

    edge_id = payload.get("edge_id")
    if not isinstance(edge_id, str) or not edge_id:
        raise CkmValidationError("confirmation receipt payload requires an edge id")
    if expected_edge_id is not None and edge_id != expected_edge_id:
        raise CkmValidationError("confirmation receipt does not bind the requested edge")
    if receipt.get("source_refs") != [
        {"ref_type": "ckm_evidence_edge", "ref": edge_id}
    ]:
        raise CkmValidationError("confirmation receipt source does not bind its payload edge")
    if payload.get("extraction_method") != "inferred" or payload.get("lifecycle") != "confirmed":
        raise CkmValidationError("confirmation receipt must promote one inferred edge")
    for field in (
        "basis",
        "provider",
        "model",
        "artifact_source_ref",
        "capability_name",
        "confirmation_key",
        "binding",
    ):
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip():
            raise CkmValidationError(
                f"confirmation receipt payload requires non-empty {field}"
            )
    if payload.get("source_ref") != payload["artifact_source_ref"]:
        raise CkmValidationError("confirmation payload artifact source binding is inconsistent")

    artifact = next(
        (item for item in store.list_artifacts() if item.source_ref == payload["artifact_source_ref"]),
        None,
    )
    capability = next(
        (item for item in store.list_capabilities() if item.name == payload["capability_name"]),
        None,
    )
    if artifact is None or capability is None:
        raise CkmValidationError("confirmation receipt target is absent from the current graph")
    expected_targets = [
        {"ref_type": "repo_artifact", "ref": artifact.source_ref},
        {"ref_type": "ckm_capability", "ref": capability.name},
    ]
    if receipt.get("target_refs") != expected_targets:
        raise CkmValidationError("confirmation receipt targets do not bind its payload")

    key = store._confirmation_signing_key()
    if key is None:
        raise CkmValidationError("confirmation receipt has no trusted signing key")
    expected_binding = hmac.new(
        key,
        _canonical_json(_binding_document(receipt, payload)).encode("utf-8"),
        sha256,
    ).hexdigest()
    if not hmac.compare_digest(payload["binding"], expected_binding):
        raise CkmValidationError("confirmation receipt trusted binding is invalid")

    current = store.get_active_evidence_edge_by_id(edge_id)
    if current is not None:
        expected_payload, _, _ = _confirmation_payload(store, current.id)
        for field, value in expected_payload.items():
            if field != "binding" and payload.get(field) != value:
                raise CkmValidationError(
                    "confirmation receipt payload does not match its source edge"
                )
        if payload.get("confirmation_key") != expected_payload["confirmation_key"]:
            raise CkmValidationError("confirmation receipt payload does not match its source edge")
    return payload, artifact, capability


def _confirm_edge_from_cli(store: CkmStore, edge_id: str) -> dict[str, Any]:
    """Execute the human-operated CLI confirmation boundary."""

    payload, artifact_ref, capability_name = _confirmation_payload(store, edge_id)
    for existing in store.list_builderops_receipts("ckm_edge_confirmed"):
        try:
            existing_payload, _, _ = _validated_confirmation_receipt(store, existing)
        except CkmValidationError:
            continue
        if existing_payload["confirmation_key"] == payload["confirmation_key"]:
            store._set_inferred_edge_confirmed(edge_id)
            return existing

    envelope = {
        "event_type": "ckm_edge_confirmed",
        "action": "confirm_edge",
        "actor": {"actor_type": "human", "id": "operator"},
        "source_refs": [{"ref_type": "ckm_evidence_edge", "ref": edge_id}],
        "target_refs": [
            {"ref_type": "repo_artifact", "ref": artifact_ref},
            {"ref_type": "ckm_capability", "ref": capability_name},
        ],
    }
    payload["binding"] = _sign_confirmation(store, envelope, payload)
    receipt = store.append_builderops_receipt(
        source_refs=envelope["source_refs"],
        summary=f"Confirmed inferred CKM edge for {capability_name}",
        event_type=envelope["event_type"],
        actor=envelope["actor"],
        occurred_at=utc_now(),
        target_refs=envelope["target_refs"],
        action=envelope["action"],
        receipt_body=json.dumps(payload, ensure_ascii=False, sort_keys=True),
        idempotency_key=f"ckm-confirm:{payload['confirmation_key']}",
    )
    # Receipt first: if the derived-row update fails, the durable confirmation
    # intent still exists and the normal rebuild/reapply path can restore it.
    _validated_confirmation_receipt(store, receipt, expected_edge_id=edge_id)
    store._set_inferred_edge_confirmed(edge_id)
    return receipt


def reapply_confirmation_receipts(store: CkmStore) -> int:
    restored = 0
    artifacts = {item.source_ref: item for item in store.list_artifacts()}
    capabilities = {item.name: item for item in store.list_capabilities()}
    for receipt in store.list_builderops_receipts("ckm_edge_confirmed"):
        try:
            payload, artifact, capability = _validated_confirmation_receipt(store, receipt)
            # The lookup maps make the rebuild dependency explicit and reject
            # receipts whose targets do not belong to this rebuilt graph.
            artifact = artifacts[artifact.source_ref]
            capability = capabilities[capability.name]
        except (CkmValidationError, KeyError, TypeError, ValueError):
            continue
        active = store.get_active_evidence_edge_by_id(payload["edge_id"])
        if active is None and store.has_retired_evidence_edge(payload["edge_id"]):
            # Explicit retirement in the current derived graph is not a partial
            # rebuild. Replaying the older confirmation would resurrect evidence
            # that cleanup intentionally removed. A true rebuild drops both the
            # active and history tables, so the normal restoration path remains.
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
        if store._set_inferred_edge_confirmed(edge.id).lifecycle == "confirmed":
            restored += 1
    return restored


__all__ = [
    "FabricSemanticAssociator",
    "SemanticAssociationError",
    "SemanticAssociationResult",
    "SemanticBatch",
    "SemanticProposal",
    "associate_unlinked_artifacts",
    "reapply_confirmation_receipts",
]
