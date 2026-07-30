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
import os
import re
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
from app.builderops.ckm.store import CkmEvidenceEdgeWrite
from app.builderops.model_access_resolver import (
    BUILDER_RUNTIME,
    CKM_SEMANTIC_CONSUMER,
    CKM_SEMANTIC_RESOLUTION_GROUP,
    CKM_SEMANTIC_ROLE,
    BuilderModelAccessResolver,
    DeclaredCredentialUnavailableError,
    ModelAccessResolutionError,
)
from app.builderops.model_inquiry_adapters import (
    AdapterExecutionError,
    AdapterUnavailableError,
    HttpModelAdapter,
)
from app.config.environment import active_environment
from llm_contract import (
    ModelAccessIntent,
    ModelCapabilityRequirements,
    ModelResolutionRequest,
    ModelTurnAdapter,
    ResolvedModelAccess,
    SchemaValidationError,
    validate_schema_payload,
)

SEMANTIC_SCHEMA_REF = "builderops.ckm.semantic-association.v1"
_SEMANTIC_SIDE_EFFECT_CLASS = "derived_candidate_evidence"
_NON_PROVIDER_IDENTITIES = frozenset({"mock", "fake", "deterministic", "test"})
_SEMANTIC_HTTP_TIMEOUT_SECONDS = 120.0
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


class SemanticAssociationError(RuntimeError):
    """The semantic stage ran but its response was not usable."""


class SemanticProviderUnavailable(SemanticAssociationError):
    """No configured provider could execute the bounded association call."""

    def __init__(
        self,
        reason: str,
        *,
        provider: str | None = None,
        model: str | None = None,
    ) -> None:
        super().__init__(reason)
        self.reason = reason
        self.provider = provider
        self.model = model


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
    reason: str | None = None


class SemanticAssociator(Protocol):
    provider: str
    model: str

    def propose(
        self,
        *,
        artifacts: Sequence[CkmArtifact],
        capabilities: Sequence[CkmCapability],
    ) -> SemanticBatch: ...


def _semantic_resolution_request() -> ModelResolutionRequest:
    return ModelResolutionRequest(
        intent=ModelAccessIntent(
            capability_tier="frontier",
            reasoning_effort="low",
            determinism_required=False,
            output_schema_ref=SEMANTIC_SCHEMA_REF,
            independence="none",
            fallback_requirement="fallback_forbidden",
            side_effect_class=_SEMANTIC_SIDE_EFFECT_CLASS,
        ),
        role_profile=CKM_SEMANTIC_ROLE,
        resolution_group_id=CKM_SEMANTIC_RESOLUTION_GROUP,
        requirements=ModelCapabilityRequirements(
            structured_output=True,
            system_prompt_channel=True,
        ),
    )


def _is_non_provider_identity(*values: str) -> bool:
    return any(
        _NON_PROVIDER_IDENTITIES.intersection(
            token for token in re.split(r"[^a-z0-9]+", value.lower()) if token
        )
        for value in values
    )


def _http_adapter_factory(
    resolved: ResolvedModelAccess,
    endpoint: str,
    credential: str,
) -> ModelTurnAdapter:
    """Build only the metered provider-API adapter selected by Builder policy.

    The Model Inquiry subscription command adapter is deliberately unreachable
    from this factory. Under the owner-cost ruling the declared credential is
    absent, so production exits before this function runs.
    """

    return HttpModelAdapter(
        adapter_id=resolved.adapter_id,
        provider=resolved.provider,
        model=resolved.model,
        endpoint=endpoint,
        api_key=credential,
        intent=resolved.request.intent,
        timeout_seconds=_SEMANTIC_HTTP_TIMEOUT_SECONDS,
        required_reasoning_effort="low",
        required_output_schema_ref=SEMANTIC_SCHEMA_REF,
        required_side_effect_class=_SEMANTIC_SIDE_EFFECT_CLASS,
    )


class BuilderSemanticAssociator:
    """CKM semantic adapter resolved only through Builder model authority."""

    def __init__(
        self,
        *,
        resolver: BuilderModelAccessResolver | None = None,
        env: dict[str, str] | None = None,
        adapter_factory: Callable[
            [ResolvedModelAccess, str, str], ModelTurnAdapter
        ] = _http_adapter_factory,
    ) -> None:
        source = dict(os.environ if env is None else env)
        try:
            selected = resolver or BuilderModelAccessResolver.from_declared_sources(env=source)
            resolved = selected.resolve(
                _semantic_resolution_request(),
                runtime=BUILDER_RUNTIME,
                channel=active_environment(source),
                consumer=CKM_SEMANTIC_CONSUMER,
            )
        except (ModelAccessResolutionError, OSError, ValueError) as exc:
            raise SemanticProviderUnavailable(str(exc)) from None
        if _is_non_provider_identity(
            resolved.provider,
            resolved.model,
            resolved.adapter_id,
            resolved.effective_identity,
        ):
            raise SemanticProviderUnavailable(
                "mock identity is forbidden for CKM semantic association",
                provider=resolved.provider,
                model=resolved.model,
            )
        if resolved.degraded:
            raise SemanticProviderUnavailable(
                "degraded Builder route: " + (resolved.degradation_reason or "reason unavailable"),
                provider=resolved.provider,
                model=resolved.model,
            )
        try:
            credential = selected.credential_value(resolved)
            endpoint = selected.endpoint_for(resolved)
        except DeclaredCredentialUnavailableError as exc:
            raise SemanticProviderUnavailable(
                str(exc),
                provider=resolved.provider,
                model=resolved.model,
            ) from None
        except (ModelAccessResolutionError, OSError, ValueError) as exc:
            raise SemanticProviderUnavailable(
                str(exc),
                provider=resolved.provider,
                model=resolved.model,
            ) from None
        try:
            adapter = adapter_factory(resolved, endpoint, credential)
        except (AdapterUnavailableError, ModelAccessResolutionError, ValueError) as exc:
            raise SemanticProviderUnavailable(
                "Builder adapter unavailable",
                provider=resolved.provider,
                model=resolved.model,
            ) from exc
        self.provider = resolved.provider
        self.model = resolved.model
        self._adapter = adapter

    def propose(
        self,
        *,
        artifacts: Sequence[CkmArtifact],
        capabilities: Sequence[CkmCapability],
    ) -> SemanticBatch:
        request = {
            "system_prompt": (
                "Associate only artifacts that clearly evidence an existing capability. "
                "Return no proposal for uncertainty; never invent capabilities."
            ),
            "schema_ref": SEMANTIC_SCHEMA_REF,
            "schema": SEMANTIC_ASSOCIATION_SCHEMA,
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
        }
        try:
            result = self._adapter.execute(request)
        except AdapterUnavailableError as exc:
            raise SemanticProviderUnavailable(
                "Builder adapter unavailable",
                provider=self.provider,
                model=self.model,
            ) from exc
        except AdapterExecutionError as exc:
            raise SemanticProviderUnavailable(
                f"Builder adapter failed: {exc.failure_class}",
                provider=self.provider,
                model=self.model,
            ) from None
        try:
            raw_payload = json.loads(result.response_text)
            payload = validate_schema_payload(
                SEMANTIC_SCHEMA_REF,
                SEMANTIC_ASSOCIATION_SCHEMA,
                raw_payload,
            )
            proposals = [SemanticProposal(**item) for item in payload["proposals"]]
        except (json.JSONDecodeError, SchemaValidationError) as exc:
            raise SemanticAssociationError(f"invalid semantic association response: {exc}") from exc
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
    client_factory: Callable[[], SemanticAssociator | None] = BuilderSemanticAssociator,
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
        except SemanticProviderUnavailable as exc:
            return SemanticAssociationResult(
                status="skipped",
                proposed=0,
                discarded=0,
                no_match=len(artifacts),
                provider=exc.provider,
                model=exc.model,
                reason=exc.reason,
            )
    if client is None:
        return SemanticAssociationResult(
            "skipped (llm unavailable)",
            0,
            0,
            len(artifacts),
            None,
            None,
            "semantic provider unavailable",
        )
    try:
        batch = client.propose(artifacts=artifacts, capabilities=capabilities)
    except SemanticProviderUnavailable as exc:
        return SemanticAssociationResult(
            status="skipped",
            proposed=0,
            discarded=0,
            no_match=len(artifacts),
            provider=exc.provider or client.provider,
            model=exc.model or client.model,
            reason=exc.reason,
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

    discarded = 0
    matched_artifacts: set[str] = set()
    accepted: list[CkmEvidenceEdgeWrite] = []
    for proposal in batch.proposals:
        artifact = artifact_by_id.get(proposal.artifact_id)
        if artifact is None:  # pragma: no cover - guarded above
            raise SemanticAssociationError("validated artifact disappeared")
        matched_artifacts.add(proposal.artifact_id)
        if proposal.confidence < confidence_floor:
            discarded += 1
            continue
        accepted.append(
            CkmEvidenceEdgeWrite(
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
        )

    watermark = sha256(
        "\n".join(sorted(item.watermark for item in artifacts)).encode("utf-8")
    ).hexdigest()
    proposed = store.upsert_evidence_edges_with_watermark(
        accepted,
        watermark_source="semantic_association",
        watermark_value=f"batch:{watermark}",
    )
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


def _confirmation_payload(store: CkmStore, edge_id: str) -> tuple[dict[str, Any], str, str, str]:
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
        "edge_public_id": edge.public_id,
        "artifact_public_id": artifact.public_id,
        "capability_public_id": capability.public_id,
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
    payload["confirmation_key"] = sha256(_canonical_json(stable_claim).encode("utf-8")).hexdigest()
    return payload, artifact.public_id, capability.public_id, capability.name


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


def _sign_confirmation(store: CkmStore, envelope: dict[str, Any], payload: dict[str, Any]) -> str:
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
    edge_public_id = payload.get("edge_public_id")
    if not isinstance(edge_public_id, str) or not edge_public_id:
        raise CkmValidationError("confirmation receipt payload requires an edge public id")
    if receipt.get("source_refs") != [{"ref_type": "ckm_evidence_edge", "ref": edge_public_id}]:
        raise CkmValidationError("confirmation receipt source does not bind its payload edge")
    if payload.get("extraction_method") != "inferred" or payload.get("lifecycle") != "confirmed":
        raise CkmValidationError("confirmation receipt must promote one inferred edge")
    for field in (
        "basis",
        "provider",
        "model",
        "artifact_public_id",
        "capability_public_id",
        "confirmation_key",
        "binding",
    ):
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip():
            raise CkmValidationError(f"confirmation receipt payload requires non-empty {field}")
    artifact = next(
        (
            item
            for item in store.list_artifacts()
            if item.public_id == payload["artifact_public_id"]
        ),
        None,
    )
    capability = next(
        (
            item
            for item in store.list_capabilities()
            if item.public_id == payload["capability_public_id"]
        ),
        None,
    )
    if artifact is None or capability is None:
        raise CkmValidationError("confirmation receipt target is absent from the current graph")
    expected_targets = [
        {"ref_type": "ckm_artifact", "ref": artifact.public_id},
        {"ref_type": "ckm_capability", "ref": capability.public_id},
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
        expected_payload, _, _, _ = _confirmation_payload(store, current.id)
        for field, value in expected_payload.items():
            if field != "binding" and payload.get(field) != value:
                raise CkmValidationError(
                    "confirmation receipt payload does not match its source edge"
                )
        if payload.get("confirmation_key") != expected_payload["confirmation_key"]:
            raise CkmValidationError("confirmation receipt payload does not match its source edge")
    return payload, artifact, capability


def _validated_legacy_confirmation_receipt(
    store: CkmStore, receipt: dict[str, Any]
) -> tuple[dict[str, Any], CkmArtifact, CkmCapability]:
    """Authenticate the pre-public-ID receipt format for one-time migration."""

    if receipt.get("object_type") != "BuilderOpsReceipt":
        raise CkmValidationError("legacy confirmation must be a BuilderOpsReceipt")
    if receipt.get("event_type") != "ckm_edge_confirmed" or receipt.get("action") != "confirm_edge":
        raise CkmValidationError("legacy confirmation has an invalid event/action")
    actor = receipt.get("actor")
    if (
        not isinstance(actor, dict)
        or actor.get("actor_type") != "human"
        or not isinstance(actor.get("id"), str)
        or not actor["id"].strip()
    ):
        raise CkmValidationError("legacy confirmation requires a named human actor")
    try:
        payload = json.loads(receipt["receipt_body"])
    except (KeyError, TypeError, ValueError) as exc:
        raise CkmValidationError("legacy confirmation body must be valid JSON") from exc
    if not isinstance(payload, dict) or "edge_public_id" in payload:
        raise CkmValidationError("not a legacy confirmation payload")
    for field in (
        "edge_id",
        "artifact_source_ref",
        "capability_name",
        "basis",
        "provider",
        "model",
        "confirmation_key",
        "binding",
    ):
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip():
            raise CkmValidationError(f"legacy confirmation requires non-empty {field}")
    if payload.get("extraction_method") != "inferred" or payload.get("lifecycle") != "confirmed":
        raise CkmValidationError("legacy confirmation must promote one inferred edge")
    if payload.get("source_ref") != payload["artifact_source_ref"]:
        raise CkmValidationError("legacy confirmation artifact binding is inconsistent")
    if receipt.get("source_refs") != [{"ref_type": "ckm_evidence_edge", "ref": payload["edge_id"]}]:
        raise CkmValidationError("legacy confirmation source does not bind its edge")
    artifact = next(
        (
            item
            for item in store.list_artifacts()
            if item.source_ref == payload["artifact_source_ref"]
        ),
        None,
    )
    capability = next(
        (item for item in store.list_capabilities() if item.name == payload["capability_name"]),
        None,
    )
    if artifact is None or capability is None:
        raise CkmValidationError("legacy confirmation target is absent from the current graph")
    if receipt.get("target_refs") != [
        {"ref_type": "repo_artifact", "ref": artifact.source_ref},
        {"ref_type": "ckm_capability", "ref": capability.name},
    ]:
        raise CkmValidationError("legacy confirmation targets do not bind its payload")
    key = store._confirmation_signing_key()
    if key is None:
        raise CkmValidationError("legacy confirmation has no trusted signing key")
    expected_binding = hmac.new(
        key,
        _canonical_json(_binding_document(receipt, payload)).encode("utf-8"),
        sha256,
    ).hexdigest()
    if not hmac.compare_digest(payload["binding"], expected_binding):
        raise CkmValidationError("legacy confirmation trusted binding is invalid")
    current_payload, _, _, _ = _confirmation_payload(store, payload["edge_id"])
    for field in (
        "evidence_kind",
        "polarity",
        "maturity_dimension",
        "confidence",
        "extraction_method",
        "lifecycle",
        "source_ref",
        "basis",
        "provider",
        "model",
    ):
        if payload.get(field) != current_payload.get(field):
            raise CkmValidationError("legacy confirmation does not match its source edge")
    return payload, artifact, capability


def migrate_legacy_confirmation_receipts(store: CkmStore) -> int:
    """Promote authenticated pre-v5 receipts into the public-ID-bound format."""

    migrated = 0
    receipts = store.list_builderops_receipts("ckm_edge_confirmed")
    current_keys: set[str] = set()
    for receipt in receipts:
        try:
            payload, _, _ = _validated_confirmation_receipt(store, receipt)
        except CkmValidationError:
            continue
        current_keys.add(str(payload["confirmation_key"]))
    for receipt in receipts:
        try:
            legacy, artifact, capability = _validated_legacy_confirmation_receipt(store, receipt)
        except CkmValidationError:
            continue
        payload, _, _, capability_name = _confirmation_payload(store, legacy["edge_id"])
        if payload["confirmation_key"] in current_keys:
            continue
        envelope = {
            "event_type": "ckm_edge_confirmed",
            "action": "confirm_edge",
            "actor": receipt["actor"],
            "source_refs": [{"ref_type": "ckm_evidence_edge", "ref": payload["edge_public_id"]}],
            "target_refs": [
                {"ref_type": "ckm_artifact", "ref": artifact.public_id},
                {"ref_type": "ckm_capability", "ref": capability.public_id},
            ],
        }
        payload["binding"] = _sign_confirmation(store, envelope, payload)
        migrated_receipt = store.append_builderops_receipt(
            source_refs=envelope["source_refs"],
            summary=f"Migrated legacy CKM confirmation for {capability_name}",
            event_type=envelope["event_type"],
            actor=envelope["actor"],
            occurred_at=str(receipt.get("occurred_at") or utc_now()),
            target_refs=envelope["target_refs"],
            action=envelope["action"],
            receipt_body=json.dumps(payload, ensure_ascii=False, sort_keys=True),
            idempotency_key=f"ckm-confirm:{payload['confirmation_key']}",
        )
        _validated_confirmation_receipt(store, migrated_receipt)
        current_keys.add(str(payload["confirmation_key"]))
        migrated += 1
    return migrated


def _confirm_edge_from_cli(store: CkmStore, edge_id: str) -> dict[str, Any]:
    """Execute the human-operated CLI confirmation boundary."""

    payload, artifact_public_id, capability_public_id, capability_name = _confirmation_payload(
        store, edge_id
    )
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
        "source_refs": [{"ref_type": "ckm_evidence_edge", "ref": payload["edge_public_id"]}],
        "target_refs": [
            {"ref_type": "ckm_artifact", "ref": artifact_public_id},
            {"ref_type": "ckm_capability", "ref": capability_public_id},
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
    artifacts = {item.public_id: item for item in store.list_artifacts()}
    capabilities = {item.public_id: item for item in store.list_capabilities()}
    for receipt in store.list_builderops_receipts("ckm_edge_confirmed"):
        try:
            payload, artifact, capability = _validated_confirmation_receipt(store, receipt)
            # The lookup maps make the rebuild dependency explicit and reject
            # receipts whose targets do not belong to this rebuilt graph.
            artifact = artifacts[artifact.public_id]
            capability = capabilities[capability.public_id]
        except (CkmValidationError, KeyError, TypeError, ValueError):
            continue
        active = store.get_active_evidence_edge_by_id(payload["edge_id"])
        if active is None and store.has_retired_evidence_edge(payload["edge_id"]):
            # Explicit retirement in the current derived graph is not a partial
            # rebuild. Replaying the older confirmation would resurrect evidence
            # that cleanup intentionally removed.
            continue
        public_id = store._edge_public_id_from_refs(
            artifact_public_id=artifact.public_id,
            capability_public_id=capability.public_id,
            basis=payload["basis"],
        )
        if public_id != payload["edge_public_id"]:
            continue
        lifecycle = store.identity_lifecycle(public_id)
        if lifecycle is not None and lifecycle["status"] == "tombstone":
            # Rebuild drops disposable edge/history rows but deliberately keeps
            # the content-free public-identity tombstone. Durable confirmation
            # intent cannot override the accepted never-reuse policy.
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
    "BuilderSemanticAssociator",
    "CKM_SEMANTIC_CONSUMER",
    "CKM_SEMANTIC_RESOLUTION_GROUP",
    "CKM_SEMANTIC_ROLE",
    "SEMANTIC_SCHEMA_REF",
    "SemanticAssociationError",
    "SemanticAssociationResult",
    "SemanticBatch",
    "SemanticProposal",
    "SemanticProviderUnavailable",
    "associate_unlinked_artifacts",
    "reapply_confirmation_receipts",
]
