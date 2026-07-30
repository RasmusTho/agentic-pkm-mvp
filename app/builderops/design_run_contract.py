"""Provider-neutral, immutable contracts for BuilderOps design runs.

This module deliberately contains no adapter, provider, policy evaluation, persistence, or
command semantics.  It is the small vocabulary those later layers must agree on.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import datetime
from typing import Annotated, Any, Final, Literal, TypeAlias, cast

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)

from app.builderops.delivery_orchestration_contracts import canonical_hash, canonical_json

DESIGN_RUN_CONTRACT_VERSION: Final[Literal["builderops.design-run-contract.v1"]] = (
    "builderops.design-run-contract.v1"
)

_UTC_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_ID = r"^[a-z][a-z0-9_.:-]{2,127}$"
_FORBIDDEN_DETAIL = re.compile(
    r"(?:api[_-]?key|authorization|bearer\s+|password|secret|raw[_ -]?stderr|"
    r"raw[_ -]?stdout|\bcommand\b|/users/|/home/|/tmp/|~[/\\]|[a-z]:\\)",
    re.IGNORECASE,
)
_AMBIENT_CONTEXT = re.compile(
    r"(?:whole[ _-]?(?:repo|vault)|implicit[ _-]?(?:cwd|context)|ambient|"
    r"chat[ _-]?history|unbounded|\bcwd\b)",
    re.IGNORECASE,
)


def _utc_timestamp(value: str) -> str:
    if not _UTC_TIMESTAMP.fullmatch(value):
        raise ValueError("timestamp must be second-precision RFC 3339 UTC ending in Z")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise ValueError("timestamp must be a real UTC calendar value") from exc
    return value


def _normalized_identifier(value: Any) -> Any:
    return value.strip() if isinstance(value, str) else value


def is_safe_design_run_identifier(value: object) -> bool:
    """Return whether a caller identity is safe to include in descriptor provenance."""

    return (
        isinstance(value, str)
        and value == value.strip()
        and re.fullmatch(_ID, value) is not None
        and _FORBIDDEN_DETAIL.search(value) is None
    )


NonEmpty = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Identifier = Annotated[
    str,
    BeforeValidator(_normalized_identifier),
    StringConstraints(strip_whitespace=True, pattern=_ID),
]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
UtcTimestamp = Annotated[str, AfterValidator(_utc_timestamp)]
DesignDeliverableKind: TypeAlias = Literal[
    "visual_handoff",
    "interaction_specification",
    "content_review",
]
DesignRunStatusValue: TypeAlias = Literal[
    "unknown",
    "unavailable",
    "denied",
    "approval_pending",
    "malformed",
    "timed_out",
    "failed",
    "running",
    "succeeded",
]
DesignAgentLimitationCode: TypeAlias = Literal[
    "model_access_unavailable",
    "headless_adapter_unavailable",
    "adapter_identity_mismatch",
    "interactive_subscription_only",
]
RefusalCode: TypeAlias = Literal[
    "unknown_adapter",
    "adapter_unavailable",
    "admission_denied",
    "approval_pending",
    "approval_mismatch",
    "malformed_request",
    "timed_out",
    "execution_failed",
    "yggdrasil_gate_missing",
    "yggdrasil_gate_stale",
    "yggdrasil_token_drift",
]


def _require_sorted_unique(values: tuple[Any, ...], label: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{label} must not contain duplicates")
    if values != tuple(sorted(values)):
        raise ValueError(f"{label} must use canonical sorted order")


class _StrictFrozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, str_min_length=1)


class CanonicalDesignRunContract(_StrictFrozen):
    schema_version: Literal["builderops.design-run-contract.v1"] = DESIGN_RUN_CONTRACT_VERSION

    def canonical_json(self) -> str:
        return canonical_json(self)

    @property
    def content_hash(self) -> str:
        return canonical_hash(self)


class DesignSourceRef(_StrictFrozen):
    source_type: Literal["ckm_observation", "github_issue", "repo_document", "builderops_receipt"]
    source_id: NonEmpty
    content_hash: Sha256

    @model_validator(mode="after")
    def _validate_explicit_source(self) -> "DesignSourceRef":
        if _AMBIENT_CONTEXT.search(self.source_id) or _FORBIDDEN_DETAIL.search(self.source_id):
            raise ValueError("source ref must be explicit and must not contain ambient or host-local context")
        return self

    @property
    def identity(self) -> tuple[str, str]:
        return (self.source_type, self.source_id)


class DigestBoundAttachmentRef(_StrictFrozen):
    attachment_id: Identifier
    media_type: Literal["image/png", "image/jpeg", "application/pdf", "text/html", "text/markdown"]
    content_hash: Sha256


class ContractIdentityRef(_StrictFrozen):
    schema_version: NonEmpty
    contract_id: Identifier
    content_hash: Sha256


class YggdrasilGateReceipt(_StrictFrozen):
    receipt_id: Identifier
    system_name: NonEmpty
    system_id: Identifier
    selection_mechanism: Literal["live_selection", "explicit_attachment"]
    repo_token_source: NonEmpty
    live_token_hash: Sha256
    repo_token_hash: Sha256
    parity_passed: Literal[True]
    verified_at: UtcTimestamp
    expires_at: UtcTimestamp
    preview_refs: tuple[DigestBoundAttachmentRef, ...]

    @model_validator(mode="after")
    def _validate_complete_current_parity(self) -> "YggdrasilGateReceipt":
        if self.live_token_hash != self.repo_token_hash:
            raise ValueError("Yggdrasil live and repo token hashes must match")
        if not self.preview_refs:
            raise ValueError("Yggdrasil gate receipt requires referenced previews")
        _require_sorted_unique(tuple(item.attachment_id for item in self.preview_refs), "preview refs")
        if self.verified_at > self.expires_at:
            raise ValueError("Yggdrasil gate receipt expiry must not precede verification")
        return self

    def valid_at(self, evaluated_at: UtcTimestamp) -> bool:
        return self.verified_at <= evaluated_at <= self.expires_at


class DesignAgentDescriptor(CanonicalDesignRunContract):
    contract_kind: Literal["descriptor"] = "descriptor"
    descriptor_id: Identifier
    display_name: NonEmpty
    role_profile_id: Identifier
    supported_deliverables: tuple[DesignDeliverableKind, ...]
    descriptor_revision: NonEmpty

    @model_validator(mode="after")
    def _validate_deliverables(self) -> "DesignAgentDescriptor":
        if not self.supported_deliverables:
            raise ValueError("design agent descriptor requires supported deliverables")
        _require_sorted_unique(self.supported_deliverables, "supported deliverables")
        return self


class DesignAgentAvailabilityDescriptor(_StrictFrozen):
    """Secret-safe CKM projection of one registered design-agent route."""

    design_agent_id: Identifier
    display_name: NonEmpty
    role_profile_id: Identifier
    supported_deliverables: tuple[DesignDeliverableKind, ...]
    available: bool
    provider_identity: NonEmpty | None = None
    model_identity: NonEmpty | None = None
    effective_identity: NonEmpty | None = None
    capabilities: tuple[NonEmpty, ...] = ()
    resolution_group_id: NonEmpty | None = None
    limitation_code: DesignAgentLimitationCode | None = None
    limitation_detail: NonEmpty | None = None

    @model_validator(mode="after")
    def _validate_availability(self) -> "DesignAgentAvailabilityDescriptor":
        if not self.supported_deliverables:
            raise ValueError("design agent descriptor requires supported deliverables")
        _require_sorted_unique(self.supported_deliverables, "supported deliverables")
        _require_sorted_unique(self.capabilities, "capabilities")
        resolved = (
            self.provider_identity,
            self.model_identity,
            self.effective_identity,
            self.resolution_group_id,
        )
        variable_text = (
            self.provider_identity,
            self.model_identity,
            self.effective_identity,
            self.resolution_group_id,
            *self.capabilities,
        )
        if any(
            value is not None and _FORBIDDEN_DETAIL.search(value)
            for value in variable_text
        ):
            raise ValueError("design agent descriptor contains unsafe identity detail")
        if self.available:
            if any(value is None for value in resolved):
                raise ValueError("available design agent requires resolved identity")
            if self.limitation_code is not None or self.limitation_detail is not None:
                raise ValueError("available design agent must not carry a limitation")
        elif self.limitation_code is None or self.limitation_detail is None:
            raise ValueError("unavailable design agent requires a safe limitation")
        if self.limitation_detail and _FORBIDDEN_DETAIL.search(self.limitation_detail):
            raise ValueError("design agent limitation contains unsafe detail")
        return self


class CuratedDesignBrief(CanonicalDesignRunContract):
    contract_kind: Literal["brief"] = "brief"
    brief_id: Identifier
    projection_id: Identifier
    requested_deliverable: DesignDeliverableKind
    source_refs: tuple[DesignSourceRef, ...]
    attachment_refs: tuple[DigestBoundAttachmentRef, ...] = ()
    constraints: tuple[NonEmpty, ...]
    yggdrasil_gate_receipt: YggdrasilGateReceipt | None = None
    non_visual_exemption: Literal[True] | None = None

    @model_validator(mode="after")
    def _validate_bounded_brief(self) -> "CuratedDesignBrief":
        if not self.source_refs:
            raise ValueError("brief requires explicit source refs")
        identities = tuple(ref.identity for ref in self.source_refs)
        if len(identities) != len(set(identities)):
            raise ValueError("brief source refs must not contain duplicates")
        if self.source_refs != tuple(sorted(self.source_refs, key=lambda ref: ref.identity)):
            raise ValueError("brief source refs must use canonical sorted order")
        _require_sorted_unique(tuple(ref.attachment_id for ref in self.attachment_refs), "brief attachment refs")
        _require_sorted_unique(self.constraints, "brief constraints")
        if any(_AMBIENT_CONTEXT.search(constraint) for constraint in self.constraints):
            raise ValueError("brief constraints must not request ambient or unbounded context")
        is_visual = self.requested_deliverable == "visual_handoff"
        if is_visual and (self.yggdrasil_gate_receipt is None or self.non_visual_exemption is not None):
            raise ValueError("visual briefs require a Yggdrasil gate receipt and no exemption")
        if not is_visual and (self.yggdrasil_gate_receipt is not None or self.non_visual_exemption is not True):
            raise ValueError("non-visual briefs require an explicit exemption and no Yggdrasil receipt")
        return self


class DesignRunPolicyProfile(CanonicalDesignRunContract):
    contract_kind: Literal["policy"] = "policy"
    profile_id: Identifier
    profile_version: NonEmpty
    allowed_deliverables: tuple[DesignDeliverableKind, ...]
    max_source_refs: Annotated[int, Field(gt=0)]
    max_attachment_refs: Annotated[int, Field(ge=0)]
    approval_required: bool
    visual_yggdrasil_receipt_required: bool

    @model_validator(mode="after")
    def _validate_profile(self) -> "DesignRunPolicyProfile":
        if not self.allowed_deliverables:
            raise ValueError("design-run policy requires allowed deliverables")
        _require_sorted_unique(self.allowed_deliverables, "allowed deliverables")
        return self


class DesignRunRequest(CanonicalDesignRunContract):
    contract_kind: Literal["request"] = "request"
    request_id: Identifier
    brief_ref: ContractIdentityRef
    adapter_ref: ContractIdentityRef
    policy_ref: ContractIdentityRef
    requested_at: UtcTimestamp


class DesignRunAdmission(CanonicalDesignRunContract):
    contract_kind: Literal["admission"] = "admission"
    admission_id: Identifier
    request_ref: ContractIdentityRef
    brief_ref: ContractIdentityRef
    adapter_ref: ContractIdentityRef
    policy_ref: ContractIdentityRef
    evaluated_at: UtcTimestamp
    repo_token_hash_observed: Sha256 | None = None
    outcome: Literal["allow", "deny", "approval_required"]
    refusal: "DesignRunRefusalDetail | None" = None

    @model_validator(mode="after")
    def _validate_admission(self) -> "DesignRunAdmission":
        if self.outcome == "allow" and self.refusal is not None:
            raise ValueError("allowed admission must not carry refusal detail")
        if self.outcome != "allow" and self.refusal is None:
            raise ValueError("non-allowed admission requires refusal detail")
        return self


class DesignRunApprovalEvidence(CanonicalDesignRunContract):
    contract_kind: Literal["approval"] = "approval"
    approval_id: Identifier
    request_ref: ContractIdentityRef
    admission_ref: ContractIdentityRef
    brief_ref: ContractIdentityRef
    adapter_ref: ContractIdentityRef
    policy_ref: ContractIdentityRef
    approved_at: UtcTimestamp
    state: Literal["approved", "revoked"]


class DesignRunRefusalDetail(_StrictFrozen):
    code: RefusalCode
    public_message: NonEmpty
    retryable: bool

    @model_validator(mode="after")
    def _reject_sensitive_detail(self) -> "DesignRunRefusalDetail":
        if _FORBIDDEN_DETAIL.search(self.public_message):
            raise ValueError("refusal detail must not contain secret, command, stderr, or host-path material")
        return self


_ALLOWED_TRANSITIONS: Final[dict[DesignRunStatusValue, frozenset[DesignRunStatusValue]]] = {
    "unknown": frozenset({"unavailable", "denied", "approval_pending", "malformed", "running"}),
    "approval_pending": frozenset({"unavailable", "denied", "malformed", "running"}),
    "running": frozenset({"timed_out", "failed", "succeeded"}),
    "unavailable": frozenset(), "denied": frozenset(),
    "malformed": frozenset(), "timed_out": frozenset(), "failed": frozenset(), "succeeded": frozenset(),
}


class DesignRunStatus(_StrictFrozen):
    run_id: Identifier
    state: DesignRunStatusValue
    previous_state: DesignRunStatusValue | None = None
    observed_at: UtcTimestamp

    @model_validator(mode="after")
    def _validate_transition(self) -> "DesignRunStatus":
        if self.previous_state is None:
            if self.state != "unknown":
                raise ValueError("initial design-run status must be unknown")
        elif self.state not in _ALLOWED_TRANSITIONS[self.previous_state]:
            raise ValueError("invalid design-run status transition")
        return self


class DesignHandoffRef(_StrictFrozen):
    handoff_id: Identifier
    content_hash: Sha256
    source_refs: tuple[DesignSourceRef, ...]
    adapter_ref: ContractIdentityRef
    run_id: Identifier
    receipt_ref: ContractIdentityRef
    limitations: tuple[NonEmpty, ...]
    produced_at: UtcTimestamp
    acceptance_state: Literal["unaccepted_builder_material"] = "unaccepted_builder_material"

    @model_validator(mode="after")
    def _validate_handoff(self) -> "DesignHandoffRef":
        if not self.source_refs:
            raise ValueError("handoff requires source refs")
        if self.source_refs != tuple(sorted(self.source_refs, key=lambda ref: ref.identity)):
            raise ValueError("handoff source refs must use canonical sorted order")
        _require_sorted_unique(tuple(ref.identity for ref in self.source_refs), "handoff source refs")
        _require_sorted_unique(self.limitations, "handoff limitations")
        return self


class DesignRunResult(CanonicalDesignRunContract):
    contract_kind: Literal["result"] = "result"
    result_id: Identifier
    run_id: Identifier
    request_ref: ContractIdentityRef
    final_status: Literal["succeeded", "failed", "timed_out", "malformed"]
    completed_at: UtcTimestamp
    handoff: DesignHandoffRef | None = None
    refusal: DesignRunRefusalDetail | None = None

    @model_validator(mode="after")
    def _validate_result(self) -> "DesignRunResult":
        if self.final_status == "succeeded":
            if self.handoff is None or self.refusal is not None:
                raise ValueError("successful result requires exactly one validated handoff")
        elif self.handoff is not None or self.refusal is None:
            raise ValueError("non-success result requires refusal and no handoff")
        return self


def contract_ref(contract: CanonicalDesignRunContract, contract_id: Identifier) -> ContractIdentityRef:
    """Return the exact identity used to bind an immutable design-run envelope."""

    return ContractIdentityRef(
        schema_version=contract.schema_version,
        contract_id=contract_id,
        content_hash=contract.content_hash,
    )


def validate_request_bindings(
    request: DesignRunRequest,
    *,
    brief: CuratedDesignBrief,
    adapter: DesignAgentDescriptor,
    policy: DesignRunPolicyProfile,
) -> None:
    """Fail closed unless a request names exactly these immutable inputs."""

    expected = (
        ("brief", request.brief_ref, contract_ref(brief, brief.brief_id)),
        ("adapter", request.adapter_ref, contract_ref(adapter, adapter.descriptor_id)),
        ("policy", request.policy_ref, contract_ref(policy, policy.profile_id)),
    )
    for label, actual, required in expected:
        if actual != required:
            raise ValueError(f"design-run request {label} ref does not bind the exact contract")
    if brief.requested_deliverable not in adapter.supported_deliverables:
        raise ValueError("design-run adapter does not support requested deliverable")
    if brief.requested_deliverable not in policy.allowed_deliverables:
        raise ValueError("design-run policy does not allow requested deliverable")
    if len(brief.source_refs) > policy.max_source_refs or len(brief.attachment_refs) > policy.max_attachment_refs:
        raise ValueError("design-run brief exceeds policy context bounds")


def validate_admission_bindings(
    admission: DesignRunAdmission,
    *,
    request: DesignRunRequest,
    brief: CuratedDesignBrief,
    adapter: DesignAgentDescriptor,
    policy: DesignRunPolicyProfile,
    current_repo_token_hash: Sha256 | None = None,
) -> None:
    """Require admission to name the exact request and all inputs it admits."""

    validate_request_bindings(request, brief=brief, adapter=adapter, policy=policy)
    expected = (
        ("request", admission.request_ref, contract_ref(request, request.request_id)),
        ("brief", admission.brief_ref, contract_ref(brief, brief.brief_id)),
        ("adapter", admission.adapter_ref, contract_ref(adapter, adapter.descriptor_id)),
        ("policy", admission.policy_ref, contract_ref(policy, policy.profile_id)),
    )
    for label, actual, required in expected:
        if actual != required:
            raise ValueError(f"design-run admission {label} ref does not bind the exact contract")
    if brief.requested_deliverable == "visual_handoff":
        receipt = brief.yggdrasil_gate_receipt
        if receipt is None or not policy.visual_yggdrasil_receipt_required:
            raise ValueError("visual admission requires Yggdrasil receipt policy")
        if current_repo_token_hash is None or receipt.repo_token_hash != current_repo_token_hash:
            raise ValueError("visual admission Yggdrasil repo token hash drifted")
        if admission.repo_token_hash_observed != current_repo_token_hash:
            raise ValueError(
                "visual admission does not bind the observed repo token hash"
            )
        if not receipt.valid_at(admission.evaluated_at):
            raise ValueError("visual admission Yggdrasil receipt is stale")
    elif admission.repo_token_hash_observed is not None:
        raise ValueError(
            "non-visual admission must not bind a repo token hash"
        )


def validate_approval_bindings(
    approval: DesignRunApprovalEvidence,
    *,
    request: DesignRunRequest,
    admission: DesignRunAdmission,
    brief: CuratedDesignBrief,
    adapter: DesignAgentDescriptor,
    policy: DesignRunPolicyProfile,
) -> None:
    """Ensure approval cannot be replayed for an expanded or substituted request."""

    expected = (
        ("request", approval.request_ref, contract_ref(request, request.request_id)),
        ("admission", approval.admission_ref, contract_ref(admission, admission.admission_id)),
        ("brief", approval.brief_ref, contract_ref(brief, brief.brief_id)),
        ("adapter", approval.adapter_ref, contract_ref(adapter, adapter.descriptor_id)),
        ("policy", approval.policy_ref, contract_ref(policy, policy.profile_id)),
    )
    for label, actual, required in expected:
        if actual != required:
            raise ValueError(f"design-run approval {label} ref does not bind the exact contract")


DesignRunContract: TypeAlias = (
    DesignAgentDescriptor | CuratedDesignBrief | DesignRunPolicyProfile | DesignRunRequest |
    DesignRunAdmission | DesignRunApprovalEvidence | DesignRunResult
)

def parse_design_run_contract(raw: str | bytes | bytearray | Mapping[str, Any]) -> DesignRunContract:
    """Parse one strict contract object, refusing duplicate JSON keys and unknown fields."""
    try:
        if isinstance(raw, Mapping):
            payload = dict(raw)
        else:
            source = raw.encode("utf-8") if isinstance(raw, str) else bytes(raw)
            payload = json.loads(source, object_pairs_hook=_reject_duplicate_keys)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("design-run contract must be one JSON object") from exc
    if not isinstance(payload, dict):
        raise ValueError("design-run contract must be one JSON object")
    contract_type = _contract_type_from_payload(payload)
    try:
        # JSON arrays are the canonical representation of immutable tuples; validate them through
        # Pydantic's JSON path while retaining strict Python-value validation for programmatic use.
        return cast(DesignRunContract, contract_type.model_validate_json(canonical_json(payload)))
    except ValidationError:
        raise


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate design-run contract JSON key: {key}")
        result[key] = value
    return result


def _contract_type_from_payload(payload: Mapping[str, Any]) -> type[CanonicalDesignRunContract]:
    # A typed discriminator belongs to every public contract so one shared schema version cannot
    # silently turn a brief into an admission or result.
    kind = payload.get("contract_kind")
    types: dict[str, type[CanonicalDesignRunContract]] = {
        "descriptor": DesignAgentDescriptor, "brief": CuratedDesignBrief,
        "policy": DesignRunPolicyProfile, "request": DesignRunRequest,
        "admission": DesignRunAdmission, "approval": DesignRunApprovalEvidence,
        "result": DesignRunResult,
    }
    if payload.get("schema_version") != DESIGN_RUN_CONTRACT_VERSION or kind not in types:
        raise ValueError("unsupported design-run contract schema_version or contract_kind")
    return types[cast(str, kind)]


__all__ = [
    "CanonicalDesignRunContract", "ContractIdentityRef", "CuratedDesignBrief",
    "DESIGN_RUN_CONTRACT_VERSION", "DesignAgentAvailabilityDescriptor",
    "DesignAgentDescriptor", "DesignAgentLimitationCode", "DesignDeliverableKind",
    "DesignHandoffRef", "DesignRunAdmission", "DesignRunApprovalEvidence",
    "DesignRunPolicyProfile", "DesignRunRefusalDetail", "DesignRunRequest", "DesignRunResult",
    "DesignRunStatus", "DigestBoundAttachmentRef", "DesignSourceRef", "YggdrasilGateReceipt",
    "canonical_hash", "canonical_json", "contract_ref", "parse_design_run_contract",
    "is_safe_design_run_identifier",
    "validate_admission_bindings", "validate_approval_bindings", "validate_request_bindings",
]
