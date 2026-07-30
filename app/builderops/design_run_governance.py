"""Governed, append-only lifecycle for Builder design runs.

The service persists one causal chain of generic ``BuilderOpsReceipt`` records.
It adds no BuilderOps object type or storage table. Provider execution remains
behind the design-agent registry and is reachable only after exact policy,
admission, optional approval, and durable-start checks succeed.
"""

from __future__ import annotations

import hashlib
import json
import os
import pwd
import secrets
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Final, Literal, Protocol, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    StringConstraints,
    model_validator,
)

from app.builderops.design_agent_adapters import (
    DesignAgentAdapterRegistry,
    ResolvedDesignAgentAdapter,
)
from app.builderops.design_run_contract import (
    CanonicalDesignRunContract,
    ContractIdentityRef,
    CuratedDesignBrief,
    DESIGN_AGENT_HANDOFF_OUTPUT_VERSION,
    DESIGN_RUN_CONTRACT_VERSION,
    DesignAgentAvailabilityDescriptor,
    DesignAgentDescriptor,
    DesignAgentHandoffOutput,
    DesignHandoffRef,
    DesignRunAdmission,
    DesignRunApprovalEvidence,
    DesignRunPolicyProfile,
    DesignRunRefusalDetail,
    DesignRunRequest,
    DesignRunResult,
    DesignRunStatus,
    DesignRunStatusValue,
    canonical_hash,
    canonical_json,
    contract_ref,
    is_safe_design_run_identifier,
    parse_design_agent_handoff_output,
    parse_design_run_contract,
    validate_admission_bindings,
    validate_approval_bindings,
)
from app.builderops.models import (
    BuilderOpsConflictError,
    BuilderOpsLeaseError,
    BuilderOpsValidationError,
)


DESIGN_RUN_POLICY_PATH: Final = Path(
    "config/builderops/design_run_policy.json"
)
DESIGN_RUN_EVENT_VERSION: Final = "builderops.design-run-receipt-event.v1"
DESIGN_RUN_RECEIPT_EVENT_TYPE: Final = "design_run_event"
_SERVICE_ACTOR_ID: Final = "builderops-design-run"
_UNACCEPTED_HANDOFF_LIMITATIONS: Final = (
    "Unaccepted Builder material; governed promotion is required.",
)
_YGGDRASIL_REPO_TOKEN_SOURCE: Final = (
    "companion-ui/companion-app/colors_and_type.css"
)
_SOURCE_REFS: Final = (
    {
        "ref_type": "repo_doc",
        "ref": (
            "docs/CKM_DESIGN_AGENT_INTEGRATION/"
            "GOVERN_DESIGN_RUN_LIFECYCLE.md"
        ),
    },
)
_RECEIPT_FIELDS: Final = frozenset(
    {
        "action",
        "actor",
        "authority_class",
        "created_at",
        "created_by",
        "event_type",
        "id",
        "idempotency_key",
        "lifecycle_state",
        "object_type",
        "occurred_at",
        "promotion_status",
        "receipt_body",
        "source_refs",
        "summary",
        "target_refs",
        "updated_at",
    }
)

Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
NonEmpty = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
EventType = Literal[
    "request_persisted",
    "admission_recorded",
    "approval_recorded",
    "approval_revoked",
    "start_accepted",
    "run_refused",
    "run_succeeded",
    "run_failed",
    "recovery_failed",
]
ArtifactKind = Literal[
    "request_bundle",
    "admission",
    "approval",
    "resolution",
    "refusal",
    "result",
]


class DesignRunGovernanceError(BuilderOpsValidationError):
    """The design-run lifecycle refused a request before unsafe execution."""


class DesignRunEvidenceError(DesignRunGovernanceError):
    """Durable design-run evidence is incomplete, conflicting, or tampered."""


class DesignRunApprovalRequiredError(DesignRunGovernanceError):
    """The exact current admission lacks usable local approval."""


class DesignRunUnavailableError(DesignRunGovernanceError):
    """The exact selected design agent is unavailable; no fallback was tried."""


class DesignRunIncompleteError(DesignRunGovernanceError):
    """A durable accepted start has no terminal receipt and cannot be replayed."""


class DesignRunPersistenceError(DesignRunGovernanceError):
    """A required receipt was not made durable."""


class DesignRunReceiptStore(Protocol):
    """Existing BuilderOps receipt, list, and lease primitives used by the service."""

    def append_receipt(self, **fields: Any) -> dict[str, Any]: ...

    def list_records(
        self, object_type: str | None = None
    ) -> list[dict[str, Any]]: ...

    def acquire_lease(
        self,
        resource_id: str,
        *,
        actor: Mapping[str, Any] | str,
        ttl_seconds: int = 5400,
    ) -> dict[str, Any]: ...

    def release_lease(
        self,
        lease_id: str,
        *,
        actor: Mapping[str, Any] | str,
    ) -> dict[str, Any]: ...


class DesignAgentRegistry(Protocol):
    def select(
        self,
        design_agent_id: str,
        *,
        run_id: str,
    ) -> ResolvedDesignAgentAdapter: ...


class DesignRunReceiptEvent(BaseModel):
    """Hashable domain event stored inside the generic receipt envelope."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal[
        "builderops.design-run-receipt-event.v1"
    ] = DESIGN_RUN_EVENT_VERSION
    run_id: NonEmpty
    event_type: EventType
    occurred_at: NonEmpty
    artifact_kind: ArtifactKind
    artifact: dict[str, Any]
    artifact_hash: Sha256
    previous_receipt_id: NonEmpty | None = None
    previous_receipt_hash: Sha256 | None = None
    state: DesignRunStatusValue | None = None
    previous_state: DesignRunStatusValue | None = None
    actor_type: Literal["agent", "human"]
    actor_id: NonEmpty

    @model_validator(mode="after")
    def _validate_event(self) -> "DesignRunReceiptEvent":
        if not is_safe_design_run_identifier(self.run_id):
            raise ValueError("invalid design-run event identifier")
        if (self.previous_receipt_id is None) != (
            self.previous_receipt_hash is None
        ):
            raise ValueError("previous receipt identity and hash must be paired")
        if self.state is None and self.previous_state is not None:
            raise ValueError("a non-status event cannot name previous state")
        expected_kinds: dict[EventType, ArtifactKind] = {
            "request_persisted": "request_bundle",
            "admission_recorded": "admission",
            "approval_recorded": "approval",
            "approval_revoked": "approval",
            "start_accepted": "resolution",
            "run_refused": "refusal",
            "run_succeeded": "result",
            "run_failed": "result",
            "recovery_failed": "result",
        }
        if self.artifact_kind != expected_kinds[self.event_type]:
            raise ValueError("design-run event artifact kind is invalid")
        if self.artifact_hash != _mapping_hash(self.artifact):
            raise ValueError("design-run event artifact hash mismatch")
        return self

    @property
    def content_hash(self) -> str:
        return canonical_hash(self)


@dataclass(frozen=True)
class DesignRunProjection:
    """Read-only status reconstructed from the validated receipt chain."""

    run_id: str
    state: DesignRunStatusValue
    latest_receipt_id: str
    latest_receipt_hash: str
    admission: DesignRunAdmission | None
    approval: DesignRunApprovalEvidence | None
    result: DesignRunResult | None
    refusal: DesignRunRefusalDetail | None


@dataclass(frozen=True)
class _ReceiptNode:
    record: Mapping[str, Any]
    event: DesignRunReceiptEvent
    event_hash: str

    @property
    def receipt_id(self) -> str:
        return cast(str, self.record["id"])


@dataclass(frozen=True)
class _RunBundle:
    request: DesignRunRequest
    brief: CuratedDesignBrief
    adapter: DesignAgentDescriptor
    policy: DesignRunPolicyProfile

    def artifact(self) -> dict[str, Any]:
        return {
            "adapter": self.adapter.model_dump(mode="json"),
            "brief": self.brief.model_dump(mode="json"),
            "policy": self.policy.model_dump(mode="json"),
            "request": self.request.model_dump(mode="json"),
        }


def _mapping_hash(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(dict(value)).encode("utf-8")).hexdigest()


def _authenticated_local_principal() -> str:
    """Resolve the effective OS account without trusting caller/environment input."""

    principal = pwd.getpwuid(os.geteuid()).pw_name.strip()
    if not principal:
        raise DesignRunGovernanceError(
            "authenticated local operator is unavailable"
        )
    return principal


def load_design_run_policy(repo_root: Path) -> DesignRunPolicyProfile:
    """Load the one repo-governed policy path and reject every invalid state."""

    root = Path(repo_root).resolve()
    policy_path = (root / DESIGN_RUN_POLICY_PATH).resolve()
    try:
        policy_path.relative_to(root)
        raw = policy_path.read_bytes()
    except (OSError, ValueError) as exc:
        raise DesignRunGovernanceError(
            "repo-governed design-run policy is unavailable"
        ) from exc
    try:
        parsed = parse_design_run_contract(raw)
    except (TypeError, ValueError) as exc:
        raise DesignRunGovernanceError(
            "repo-governed design-run policy is malformed"
        ) from exc
    if not isinstance(parsed, DesignRunPolicyProfile):
        raise DesignRunGovernanceError(
            "repo-governed design-run policy has the wrong contract kind"
        )
    return parsed


class DesignRunGovernance:
    """One governed design-run aggregate over existing BuilderOps receipts."""

    def __init__(
        self,
        *,
        store: DesignRunReceiptStore,
        registry: DesignAgentRegistry,
        repo_root: Path,
        lease_ttl_seconds: int = 300,
    ) -> None:
        if lease_ttl_seconds <= 0:
            raise ValueError("lease_ttl_seconds must be positive")
        self.store = store
        self.registry = registry
        self.repo_root = Path(repo_root).resolve()
        self.lease_ttl_seconds = lease_ttl_seconds
        self._execution_actor = {
            "actor_type": "agent",
            "id": f"{_SERVICE_ACTOR_ID}:{secrets.token_hex(8)}",
        }
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    @classmethod
    def from_declared_sources(
        cls,
        *,
        store: DesignRunReceiptStore,
        channel: str,
        repo_root: Path,
        model_turn_adapters: Mapping[str, Any] | None = None,
    ) -> "DesignRunGovernance":
        """Compose production only from repo policy and the declared registry."""

        load_design_run_policy(repo_root)
        return cls(
            store=store,
            registry=DesignAgentAdapterRegistry.from_declared_sources(
                channel=channel,
                model_turn_adapters=model_turn_adapters,
            ),
            repo_root=repo_root,
        )

    def build_request(
        self,
        *,
        request_id: str,
        brief: CuratedDesignBrief,
        adapter: DesignAgentDescriptor,
        requested_at: str,
    ) -> DesignRunRequest:
        policy = load_design_run_policy(self.repo_root)
        return DesignRunRequest(
            request_id=request_id,
            brief_ref=contract_ref(brief, brief.brief_id),
            adapter_ref=contract_ref(adapter, adapter.descriptor_id),
            policy_ref=contract_ref(policy, policy.profile_id),
            requested_at=requested_at,
        )

    def submit(
        self,
        *,
        run_id: str,
        request: DesignRunRequest,
        brief: CuratedDesignBrief,
        adapter: DesignAgentDescriptor,
        evaluated_at: str,
    ) -> DesignRunAdmission:
        """Persist the exact request bundle, then record deterministic admission."""

        self._require_run_id(run_id)
        policy = load_design_run_policy(self.repo_root)
        bundle = _RunBundle(request, brief, adapter, policy)
        with self._run_lock(run_id):
            chain = self._load_chain(
                run_id,
                allow_missing=True,
                allow_incomplete_admission=True,
            )
            if chain:
                stored = self._bundle(chain)
                if stored.artifact() != bundle.artifact():
                    raise BuilderOpsConflictError(
                        "design-run identifier already binds a different request"
                    )
                admission = self._admission(chain)
                if admission is not None:
                    return admission
            else:
                root = self._append_event(
                    run_id=run_id,
                    chain=(),
                    event_type="request_persisted",
                    occurred_at=request.requested_at,
                    artifact_kind="request_bundle",
                    artifact=bundle.artifact(),
                    state="unknown",
                    previous_state=None,
                    actor=self._service_actor(),
                )
                chain = (root,)

            root = self._root(chain)
            lease = self._acquire_run_lease(root.receipt_id)
            try:
                chain = self._load_chain(
                    run_id,
                    allow_incomplete_admission=True,
                )
                stored = self._bundle(chain)
                if stored.artifact() != bundle.artifact():
                    raise BuilderOpsConflictError(
                        "design-run identifier already binds a different request"
                    )
                existing_admission = self._admission(chain)
                if existing_admission is not None:
                    return existing_admission
                admission = self._evaluate_admission(
                    run_id=run_id,
                    bundle=bundle,
                    evaluated_at=evaluated_at,
                    repo_token_hash=self._trusted_repo_token_hash(brief),
                )
                state = self._admission_state(admission)
                current = self._current_state(chain)
                self._append_event(
                    run_id=run_id,
                    chain=chain,
                    event_type="admission_recorded",
                    occurred_at=evaluated_at,
                    artifact_kind="admission",
                    artifact=admission.model_dump(mode="json"),
                    state=state,
                    previous_state=current if state is not None else None,
                    actor=self._service_actor(),
                )
                return admission
            finally:
                self._release_run_lease(lease)

    def approve(
        self,
        *,
        run_id: str,
        approval_id: str,
        approved_at: str,
    ) -> DesignRunApprovalEvidence:
        """Append exact approval from the authenticated effective OS principal."""

        return self._record_approval(
            run_id=run_id,
            approval_id=approval_id,
            occurred_at=approved_at,
            state="approved",
        )

    def revoke(
        self,
        *,
        run_id: str,
        revocation_id: str,
        revoked_at: str,
    ) -> DesignRunApprovalEvidence:
        """Append revocation from the authenticated effective OS principal."""

        return self._record_approval(
            run_id=run_id,
            approval_id=revocation_id,
            occurred_at=revoked_at,
            state="revoked",
        )

    def execute(
        self,
        *,
        run_id: str,
        started_at: str,
        completed_at: str,
    ) -> DesignRunResult:
        """Execute one exact approved adapter after a durable accepted-start fence."""

        self._require_run_id(run_id)
        self._require_causal_execution_times(
            started_at=started_at,
            completed_at=completed_at,
        )
        with self._run_lock(run_id):
            initial = self._load_chain(run_id)
            existing_result = self._result(initial)
            if existing_result is not None:
                return existing_result
            if self._current_state(initial) == "running":
                raise DesignRunIncompleteError(
                    "design run has an incomplete durable execution attempt"
                )
            self._raise_if_refused(initial)
            root = self._root(initial)
            lease: Mapping[str, Any] | None = self._acquire_run_lease(
                root.receipt_id
            )
            try:
                chain = self._load_chain(run_id)
                existing_result = self._result(chain)
                if existing_result is not None:
                    return existing_result
                if self._current_state(chain) == "running":
                    raise DesignRunIncompleteError(
                        "design run has an incomplete durable execution attempt"
                    )
                self._raise_if_refused(chain)
                bundle = self._bundle(chain)
                admission = self._required_admission(chain)
                current_policy = load_design_run_policy(self.repo_root)
                if current_policy != bundle.policy:
                    self._record_refusal(
                        run_id=run_id,
                        chain=chain,
                        occurred_at=started_at,
                        code="admission_denied",
                        message="The repo-governed design-run policy changed.",
                    )
                    raise DesignRunGovernanceError(
                        "design-run policy changed after admission"
                    )
                approval = self._usable_approval(
                    chain,
                    admission=admission,
                    bundle=bundle,
                    started_at=started_at,
                )
                refusal = self._visual_refusal(
                    bundle=bundle,
                    evaluated_at=started_at,
                    repo_token_hash=self._trusted_repo_token_hash(
                        bundle.brief
                    ),
                )
                if refusal is not None:
                    self._record_refusal_from_detail(
                        run_id=run_id,
                        chain=chain,
                        occurred_at=started_at,
                        refusal=refusal,
                    )
                    raise DesignRunGovernanceError(
                        "visual design-run admission is no longer current"
                    )
                try:
                    selected = self.registry.select(
                        bundle.adapter.descriptor_id,
                        run_id=run_id,
                    )
                    self._validate_selected_adapter(
                        selected,
                        bundle.adapter,
                        run_id=run_id,
                    )
                except Exception as exc:
                    self._record_refusal(
                        run_id=run_id,
                        chain=chain,
                        occurred_at=started_at,
                        code="adapter_unavailable",
                        message="The selected design agent is unavailable.",
                        state="unavailable",
                    )
                    raise DesignRunUnavailableError(
                        "selected design agent is unavailable"
                    ) from exc
                start = self._append_event(
                    run_id=run_id,
                    chain=chain,
                    event_type="start_accepted",
                    occurred_at=started_at,
                    artifact_kind="resolution",
                    artifact=selected.descriptor.model_dump(mode="json"),
                    state="running",
                    previous_state=self._current_state(chain),
                    actor=self._execution_actor,
                )
                chain = (*chain, start)
                start_receipt_ref = ContractIdentityRef(
                    schema_version=DESIGN_RUN_EVENT_VERSION,
                    contract_id=start.receipt_id,
                    content_hash=start.event_hash,
                )
                handoff_binding = {
                    "acceptance_state": "unaccepted_builder_material",
                    "adapter_ref": bundle.request.adapter_ref.model_dump(
                        mode="json"
                    ),
                    "handoff_id": f"{run_id}.handoff",
                    "limitations": list(_UNACCEPTED_HANDOFF_LIMITATIONS),
                    "produced_at": completed_at,
                    "receipt_ref": start_receipt_ref.model_dump(mode="json"),
                    "run_id": run_id,
                    "source_refs": [
                        source.model_dump(mode="json")
                        for source in bundle.brief.source_refs
                    ],
                }
                payload = {
                    "admission": admission.model_dump(mode="json"),
                    "approval": (
                        approval.model_dump(mode="json")
                        if approval is not None
                        else None
                    ),
                    "brief": bundle.brief.model_dump(mode="json"),
                    "handoff_binding": handoff_binding,
                    "handoff_output_schema_version": (
                        DESIGN_AGENT_HANDOFF_OUTPUT_VERSION
                    ),
                    "request": bundle.request.model_dump(mode="json"),
                    "run_id": run_id,
                    "schema_version": DESIGN_RUN_CONTRACT_VERSION,
                }
                terminal_failure: tuple[
                    Literal["failed", "timed_out"],
                    Literal["execution_failed", "timed_out"],
                    str,
                ] | None = None
                handoff: DesignHandoffRef | None = None
                try:
                    adapter_result = selected.execute(payload)
                    output = parse_design_agent_handoff_output(
                        adapter_result.response_text
                    )
                    handoff = self._validate_returned_handoff(
                        output=output,
                        binding=handoff_binding,
                    )
                except TimeoutError:
                    terminal_failure = (
                        "timed_out",
                        "timed_out",
                        "The selected design agent timed out.",
                    )
                except Exception:
                    terminal_failure = (
                        "failed",
                        "execution_failed",
                        "The selected design agent failed.",
                    )

                # The provider turn may outlive the original lease. Re-fence
                # against the durable chain before claiming any terminal
                # outcome so recovery and a late provider return cannot branch.
                lease = None
                lease = self._acquire_run_lease(root.receipt_id)
                chain = self._load_chain(run_id)
                if (
                    self._current_state(chain) != "running"
                    or chain[-1].receipt_id != start.receipt_id
                ):
                    raise DesignRunIncompleteError(
                        "design run changed before terminal persistence"
                    )
                if terminal_failure is not None:
                    state, code, message = terminal_failure
                    return self._record_terminal_failure(
                        run_id=run_id,
                        chain=chain,
                        bundle=bundle,
                        completed_at=completed_at,
                        state=state,
                        code=code,
                        message=message,
                    )
                if handoff is None:
                    raise DesignRunIncompleteError(
                        "design run adapter returned no validated handoff"
                    )

                result = DesignRunResult(
                    result_id=f"{run_id}.result",
                    run_id=run_id,
                    request_ref=contract_ref(
                        bundle.request, bundle.request.request_id
                    ),
                    final_status="succeeded",
                    completed_at=completed_at,
                    handoff=handoff,
                )
                self._append_event(
                    run_id=run_id,
                    chain=chain,
                    event_type="run_succeeded",
                    occurred_at=completed_at,
                    artifact_kind="result",
                    artifact=result.model_dump(mode="json"),
                    state="succeeded",
                    previous_state="running",
                    actor=self._execution_actor,
                )
                return result
            finally:
                if lease is not None:
                    self._release_run_lease(lease)

    @staticmethod
    def _validate_returned_handoff(
        *,
        output: DesignAgentHandoffOutput,
        binding: Mapping[str, Any],
    ) -> DesignHandoffRef:
        handoff = output.handoff
        returned = handoff.model_dump(
            mode="json",
            exclude={"content_hash"},
        )
        if returned != dict(binding):
            raise ValueError(
                "design-agent handoff does not bind the exact run"
            )
        return handoff

    def recover_incomplete(
        self,
        *,
        run_id: str,
        recovered_at: str,
    ) -> DesignRunResult:
        """Explicitly terminalize a durable start that cannot be resumed safely."""

        self._require_run_id(run_id)
        with self._run_lock(run_id):
            chain = self._load_chain(run_id)
            existing = self._result(chain)
            if existing is not None:
                return existing
            if self._current_state(chain) != "running":
                raise DesignRunIncompleteError(
                    "design run has no incomplete accepted start"
                )
            root = self._root(chain)
            lease = self._acquire_run_lease(root.receipt_id)
            try:
                chain = self._load_chain(run_id)
                if self._current_state(chain) != "running":
                    raise DesignRunIncompleteError(
                        "design run no longer has an incomplete accepted start"
                    )
                bundle = self._bundle(chain)
                refusal = DesignRunRefusalDetail(
                    code="execution_failed",
                    public_message=(
                        "A prior accepted execution ended without terminal evidence."
                    ),
                    retryable=False,
                )
                result = self._failed_result(
                    bundle=bundle,
                    run_id=run_id,
                    completed_at=recovered_at,
                    status="failed",
                    refusal=refusal,
                )
                self._append_event(
                    run_id=run_id,
                    chain=chain,
                    event_type="recovery_failed",
                    occurred_at=recovered_at,
                    artifact_kind="result",
                    artifact=result.model_dump(mode="json"),
                    state="failed",
                    previous_state="running",
                    actor=self._execution_actor,
                )
                return result
            finally:
                self._release_run_lease(lease)

    def projection(self, run_id: str) -> DesignRunProjection:
        """Validate the complete chain before returning any observable state."""

        self._require_run_id(run_id)
        chain = self._load_chain(run_id)
        latest = chain[-1]
        admission = self._admission(chain)
        approval = self._latest_approval(chain)
        result = self._result(chain)
        state = self._current_state(chain)
        if result is not None:
            refusal = result.refusal
        else:
            refusal = self._terminal_refusal(chain)
            if (
                refusal is None
                and state
                in {"approval_pending", "denied", "malformed"}
                and admission is not None
            ):
                refusal = admission.refusal
        return DesignRunProjection(
            run_id=run_id,
            state=state,
            latest_receipt_id=latest.receipt_id,
            latest_receipt_hash=latest.event_hash,
            admission=admission,
            approval=approval,
            result=result,
            refusal=refusal,
        )

    def _record_approval(
        self,
        *,
        run_id: str,
        approval_id: str,
        occurred_at: str,
        state: Literal["approved", "revoked"],
    ) -> DesignRunApprovalEvidence:
        self._require_run_id(run_id)
        principal = _authenticated_local_principal()
        actor = {"actor_type": "human", "id": principal}
        lease_actor = {
            "actor_type": "human",
            "id": f"{principal}:{secrets.token_hex(8)}",
        }
        with self._run_lock(run_id):
            chain = self._load_chain(run_id)
            root = self._root(chain)
            lease = self._acquire_run_lease(
                root.receipt_id,
                actor=lease_actor,
            )
            try:
                chain = self._load_chain(run_id)
                bundle = self._bundle(chain)
                admission = self._required_admission(chain)
                if admission.outcome != "approval_required":
                    raise DesignRunApprovalRequiredError(
                        "design-run admission does not require approval"
                    )
                if occurred_at < admission.evaluated_at:
                    raise DesignRunApprovalRequiredError(
                        "design-run approval evidence is stale"
                    )
                latest = self._latest_approval(chain)
                if (
                    state == "revoked"
                    and (latest is None or latest.state != "approved")
                ):
                    raise DesignRunApprovalRequiredError(
                        "design-run approval cannot be revoked"
                    )
                evidence = DesignRunApprovalEvidence(
                    approval_id=approval_id,
                    request_ref=contract_ref(
                        bundle.request, bundle.request.request_id
                    ),
                    admission_ref=contract_ref(
                        admission, admission.admission_id
                    ),
                    brief_ref=contract_ref(bundle.brief, bundle.brief.brief_id),
                    adapter_ref=contract_ref(
                        bundle.adapter, bundle.adapter.descriptor_id
                    ),
                    policy_ref=contract_ref(
                        bundle.policy, bundle.policy.profile_id
                    ),
                    approved_at=occurred_at,
                    state=state,
                )
                validate_approval_bindings(
                    evidence,
                    request=bundle.request,
                    admission=admission,
                    brief=bundle.brief,
                    adapter=bundle.adapter,
                    policy=bundle.policy,
                )
                if latest == evidence:
                    return evidence
                self._append_event(
                    run_id=run_id,
                    chain=chain,
                    event_type=(
                        "approval_recorded"
                        if state == "approved"
                        else "approval_revoked"
                    ),
                    occurred_at=occurred_at,
                    artifact_kind="approval",
                    artifact=evidence.model_dump(mode="json"),
                    state=None,
                    previous_state=None,
                    actor=actor,
                )
                return evidence
            finally:
                self._release_run_lease(lease, actor=lease_actor)

    def _evaluate_admission(
        self,
        *,
        run_id: str,
        bundle: _RunBundle,
        evaluated_at: str,
        repo_token_hash: str | None,
    ) -> DesignRunAdmission:
        if (
            bundle.brief.requested_deliverable != "visual_handoff"
            and repo_token_hash is not None
        ):
            raise ValueError(
                "non-visual admission cannot observe repo tokens"
            )
        receipt = bundle.brief.yggdrasil_gate_receipt
        if (
            bundle.brief.requested_deliverable == "visual_handoff"
            and repo_token_hash is not None
            and (
                receipt is None
                or receipt.repo_token_source
                != _YGGDRASIL_REPO_TOKEN_SOURCE
            )
        ):
            raise ValueError(
                "visual admission token observation is not repo-governed"
            )
        refusal = self._request_refusal(
            bundle=bundle,
            evaluated_at=evaluated_at,
            repo_token_hash=repo_token_hash,
        )
        if refusal is not None:
            outcome: Literal["allow", "deny", "approval_required"] = "deny"
        elif bundle.policy.approval_required:
            outcome = "approval_required"
            refusal = DesignRunRefusalDetail(
                code="approval_pending",
                public_message="Authenticated local operator approval is required.",
                retryable=False,
            )
        else:
            outcome = "allow"
        admission = DesignRunAdmission(
            admission_id=f"{run_id}.admission",
            request_ref=contract_ref(bundle.request, bundle.request.request_id),
            brief_ref=contract_ref(bundle.brief, bundle.brief.brief_id),
            adapter_ref=contract_ref(
                bundle.adapter, bundle.adapter.descriptor_id
            ),
            policy_ref=contract_ref(bundle.policy, bundle.policy.profile_id),
            evaluated_at=evaluated_at,
            repo_token_hash_observed=repo_token_hash,
            outcome=outcome,
            refusal=refusal,
        )
        if outcome != "deny":
            validate_admission_bindings(
                admission,
                request=bundle.request,
                brief=bundle.brief,
                adapter=bundle.adapter,
                policy=bundle.policy,
                current_repo_token_hash=repo_token_hash,
            )
        return admission

    def _request_refusal(
        self,
        *,
        bundle: _RunBundle,
        evaluated_at: str,
        repo_token_hash: str | None,
    ) -> DesignRunRefusalDetail | None:
        expected_refs = (
            contract_ref(bundle.brief, bundle.brief.brief_id),
            contract_ref(bundle.adapter, bundle.adapter.descriptor_id),
            contract_ref(bundle.policy, bundle.policy.profile_id),
        )
        if (
            bundle.request.brief_ref,
            bundle.request.adapter_ref,
            bundle.request.policy_ref,
        ) != expected_refs:
            return DesignRunRefusalDetail(
                code="malformed_request",
                public_message="The request does not bind its exact inputs.",
                retryable=False,
            )
        if (
            bundle.brief.requested_deliverable
            not in bundle.adapter.supported_deliverables
            or bundle.brief.requested_deliverable
            not in bundle.policy.allowed_deliverables
            or len(bundle.brief.source_refs) > bundle.policy.max_source_refs
            or len(bundle.brief.attachment_refs)
            > bundle.policy.max_attachment_refs
        ):
            return DesignRunRefusalDetail(
                code="admission_denied",
                public_message="The repo-governed policy denies this request.",
                retryable=False,
            )
        return self._visual_refusal(
            bundle=bundle,
            evaluated_at=evaluated_at,
            repo_token_hash=repo_token_hash,
        )

    def _visual_refusal(
        self,
        *,
        bundle: _RunBundle,
        evaluated_at: str,
        repo_token_hash: str | None,
    ) -> DesignRunRefusalDetail | None:
        if bundle.brief.requested_deliverable != "visual_handoff":
            return None
        receipt = bundle.brief.yggdrasil_gate_receipt
        if (
            receipt is None
            or not bundle.policy.visual_yggdrasil_receipt_required
        ):
            return DesignRunRefusalDetail(
                code="yggdrasil_gate_missing",
                public_message="Current Yggdrasil evidence is required.",
                retryable=False,
            )
        if repo_token_hash is None:
            return DesignRunRefusalDetail(
                code="yggdrasil_gate_missing",
                public_message="Repo-governed Yggdrasil tokens are unavailable.",
                retryable=False,
            )
        if receipt.repo_token_hash != repo_token_hash:
            return DesignRunRefusalDetail(
                code="yggdrasil_token_drift",
                public_message="Yggdrasil token parity is not current.",
                retryable=False,
            )
        if not receipt.valid_at(evaluated_at):
            return DesignRunRefusalDetail(
                code="yggdrasil_gate_stale",
                public_message="Yggdrasil evidence is stale.",
                retryable=False,
            )
        return None

    def _trusted_repo_token_hash(
        self,
        brief: CuratedDesignBrief,
    ) -> str | None:
        """Read the one admitted Yggdrasil token source from this repo."""

        receipt = brief.yggdrasil_gate_receipt
        if (
            receipt is None
            or receipt.repo_token_source != _YGGDRASIL_REPO_TOKEN_SOURCE
        ):
            return None
        token_path = (
            self.repo_root / _YGGDRASIL_REPO_TOKEN_SOURCE
        ).resolve()
        try:
            token_path.relative_to(self.repo_root)
            content = token_path.read_bytes()
        except (OSError, ValueError):
            return None
        return hashlib.sha256(content).hexdigest()

    @staticmethod
    def _admission_state(
        admission: DesignRunAdmission,
    ) -> DesignRunStatusValue | None:
        if admission.outcome == "approval_required":
            return "approval_pending"
        if admission.outcome == "deny":
            return (
                "malformed"
                if admission.refusal is not None
                and admission.refusal.code == "malformed_request"
                else "denied"
            )
        return None

    @classmethod
    def _raise_if_refused(
        cls,
        chain: Sequence[_ReceiptNode],
    ) -> None:
        state = cls._current_state(chain)
        if state == "unavailable":
            raise DesignRunUnavailableError(
                "selected design agent is unavailable"
            )
        if state in {"denied", "malformed"}:
            raise DesignRunGovernanceError(
                "design run is already terminally refused"
            )

    def _usable_approval(
        self,
        chain: Sequence[_ReceiptNode],
        *,
        admission: DesignRunAdmission,
        bundle: _RunBundle,
        started_at: str,
    ) -> DesignRunApprovalEvidence | None:
        if admission.outcome == "deny":
            raise DesignRunGovernanceError("design-run admission was denied")
        if admission.outcome == "allow":
            return None
        approval = self._latest_approval(chain)
        if (
            approval is None
            or approval.state != "approved"
            or approval.approved_at < admission.evaluated_at
            or approval.approved_at > started_at
        ):
            raise DesignRunApprovalRequiredError(
                "exact current design-run approval is required"
            )
        try:
            validate_approval_bindings(
                approval,
                request=bundle.request,
                admission=admission,
                brief=bundle.brief,
                adapter=bundle.adapter,
                policy=bundle.policy,
            )
        except ValueError as exc:
            raise DesignRunApprovalRequiredError(
                "design-run approval does not bind exact inputs"
            ) from exc
        return approval

    def _record_terminal_failure(
        self,
        *,
        run_id: str,
        chain: Sequence[_ReceiptNode],
        bundle: _RunBundle,
        completed_at: str,
        state: Literal["failed", "timed_out"],
        code: Literal["execution_failed", "timed_out"],
        message: str,
    ) -> DesignRunResult:
        refusal = DesignRunRefusalDetail(
            code=code,
            public_message=message,
            retryable=False,
        )
        result = self._failed_result(
            bundle=bundle,
            run_id=run_id,
            completed_at=completed_at,
            status=state,
            refusal=refusal,
        )
        self._append_event(
            run_id=run_id,
            chain=chain,
            event_type="run_failed",
            occurred_at=completed_at,
            artifact_kind="result",
            artifact=result.model_dump(mode="json"),
            state=state,
            previous_state="running",
            actor=self._execution_actor,
        )
        return result

    @staticmethod
    def _failed_result(
        *,
        bundle: _RunBundle,
        run_id: str,
        completed_at: str,
        status: Literal["failed", "timed_out"],
        refusal: DesignRunRefusalDetail,
    ) -> DesignRunResult:
        return DesignRunResult(
            result_id=f"{run_id}.result",
            run_id=run_id,
            request_ref=contract_ref(bundle.request, bundle.request.request_id),
            final_status=status,
            completed_at=completed_at,
            refusal=refusal,
        )

    def _record_refusal(
        self,
        *,
        run_id: str,
        chain: Sequence[_ReceiptNode],
        occurred_at: str,
        code: Literal["admission_denied", "adapter_unavailable"],
        message: str,
        state: Literal["denied", "unavailable"] = "denied",
    ) -> _ReceiptNode:
        return self._record_refusal_from_detail(
            run_id=run_id,
            chain=chain,
            occurred_at=occurred_at,
            refusal=DesignRunRefusalDetail(
                code=code,
                public_message=message,
                retryable=False,
            ),
            state=state,
        )

    def _record_refusal_from_detail(
        self,
        *,
        run_id: str,
        chain: Sequence[_ReceiptNode],
        occurred_at: str,
        refusal: DesignRunRefusalDetail,
        state: Literal["denied", "unavailable", "malformed"] = "denied",
    ) -> _ReceiptNode:
        return self._append_event(
            run_id=run_id,
            chain=chain,
            event_type="run_refused",
            occurred_at=occurred_at,
            artifact_kind="refusal",
            artifact=refusal.model_dump(mode="json"),
            state=state,
            previous_state=self._current_state(chain),
            actor=self._service_actor(),
        )

    @staticmethod
    def _validate_selected_adapter(
        selected: ResolvedDesignAgentAdapter,
        expected: DesignAgentDescriptor,
        *,
        run_id: str,
    ) -> None:
        descriptor = selected.descriptor
        if (
            selected.design_agent_id != expected.descriptor_id
            or descriptor.design_agent_id != expected.descriptor_id
            or descriptor.role_profile_id != expected.role_profile_id
            or descriptor.resolution_group_id
            != f"design-run:{run_id}"
            or selected.model_turn_adapter.provider
            != descriptor.provider_identity
            or selected.model_turn_adapter.model
            != descriptor.model_identity
            or not descriptor.available
            or not set(expected.supported_deliverables).issubset(
                descriptor.supported_deliverables
            )
        ):
            raise DesignRunUnavailableError(
                "resolved design agent does not match the admitted descriptor"
            )

    def _append_event(
        self,
        *,
        run_id: str,
        chain: Sequence[_ReceiptNode],
        event_type: EventType,
        occurred_at: str,
        artifact_kind: ArtifactKind,
        artifact: Mapping[str, Any],
        state: DesignRunStatusValue | None,
        previous_state: DesignRunStatusValue | None,
        actor: Mapping[str, str],
    ) -> _ReceiptNode:
        previous = chain[-1] if chain else None
        if (
            previous is not None
            and occurred_at < previous.event.occurred_at
        ):
            raise DesignRunGovernanceError(
                "design-run receipt time precedes its causal predecessor"
            )
        event = DesignRunReceiptEvent(
            run_id=run_id,
            event_type=event_type,
            occurred_at=occurred_at,
            artifact_kind=artifact_kind,
            artifact=dict(artifact),
            artifact_hash=_mapping_hash(artifact),
            previous_receipt_id=(
                previous.receipt_id if previous is not None else None
            ),
            previous_receipt_hash=(
                previous.event_hash if previous is not None else None
            ),
            state=state,
            previous_state=previous_state,
            actor_type=cast(Literal["agent", "human"], actor["actor_type"]),
            actor_id=actor["id"],
        )
        event_hash = event.content_hash
        key = (
            f"design-run:{run_id}:{event_type}:{event.artifact_hash}:"
            f"{event.previous_receipt_hash or 'root'}"
        )
        fields: dict[str, Any] = {
            "summary": f"Design run {event_type.replace('_', ' ')}",
            "event_type": DESIGN_RUN_RECEIPT_EVENT_TYPE,
            "actor": dict(actor),
            "occurred_at": occurred_at,
            "target_refs": [
                {
                    "ref_type": "design_run",
                    "ref": run_id,
                    "authority_surface": "builderops",
                }
            ],
            "action": event_type,
            "receipt_body": canonical_json(event),
            "idempotency_key": key,
            "source_refs": [dict(ref) for ref in _SOURCE_REFS],
            "created_by": dict(actor),
        }
        fields["id"] = self._receipt_id(
            run_id,
            previous_receipt_id=event.previous_receipt_id,
            previous_receipt_hash=event.previous_receipt_hash,
        )
        try:
            record = self.store.append_receipt(**fields)
        except (BuilderOpsValidationError, OSError) as exc:
            raise DesignRunPersistenceError(
                f"design-run {event_type} receipt was not durable"
            ) from exc
        node = self._node(record, expected_run_id=run_id)
        if node.event != event or node.event_hash != event_hash:
            raise DesignRunPersistenceError(
                "design-run receipt readback does not match the event"
            )
        return node

    def _load_chain(
        self,
        run_id: str,
        *,
        allow_missing: bool = False,
        allow_incomplete_admission: bool = False,
    ) -> tuple[_ReceiptNode, ...]:
        try:
            records = self.store.list_records("BuilderOpsReceipt")
        except (BuilderOpsValidationError, OSError) as exc:
            raise DesignRunEvidenceError(
                "design-run receipt store is unavailable"
            ) from exc
        decoded: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for record in records:
            if record.get("event_type") != DESIGN_RUN_RECEIPT_EVENT_TYPE:
                continue
            try:
                payload = json.loads(cast(str, record.get("receipt_body")))
            except (TypeError, json.JSONDecodeError):
                raise DesignRunEvidenceError(
                    "design-run receipt event is malformed"
                ) from None
            if not isinstance(payload, dict):
                raise DesignRunEvidenceError(
                    "design-run receipt event is malformed"
                )
            decoded.append((record, payload))
        selected = [
            record
            for record, payload in decoded
            if payload.get("run_id") == run_id
        ]
        if not selected:
            if allow_missing:
                return ()
            raise DesignRunEvidenceError("design-run evidence is missing")
        selected_ids = {
            record.get("id")
            for record in selected
            if isinstance(record.get("id"), str)
        }
        if any(
            payload.get("run_id") != run_id
            and payload.get("previous_receipt_id") in selected_ids
            for _, payload in decoded
        ):
            raise DesignRunEvidenceError(
                "foreign design-run receipt extends the causal chain"
            )
        nodes = [
            self._node(record, expected_run_id=run_id) for record in selected
        ]
        by_id = {node.receipt_id: node for node in nodes}
        if len(by_id) != len(nodes):
            raise DesignRunEvidenceError("design-run receipt identities repeat")
        roots = [
            node for node in nodes if node.event.previous_receipt_id is None
        ]
        if len(roots) != 1:
            raise DesignRunEvidenceError(
                "design-run receipt chain requires exactly one root"
            )
        children: dict[str, _ReceiptNode] = {}
        for node in nodes:
            previous_id = node.event.previous_receipt_id
            if previous_id is None:
                continue
            previous = by_id.get(previous_id)
            if previous is None:
                raise DesignRunEvidenceError(
                    "design-run receipt predecessor is missing"
                )
            if node.event.previous_receipt_hash != previous.event_hash:
                raise DesignRunEvidenceError(
                    "design-run receipt predecessor hash mismatch"
                )
            if previous_id in children:
                raise DesignRunEvidenceError(
                    "design-run receipt chain branches"
                )
            children[previous_id] = node
        ordered: list[_ReceiptNode] = []
        current = roots[0]
        while True:
            if current in ordered:
                raise DesignRunEvidenceError("design-run receipt chain is cyclic")
            ordered.append(current)
            child = children.get(current.receipt_id)
            if child is None:
                break
            current = child
        if len(ordered) != len(nodes):
            raise DesignRunEvidenceError(
                "design-run receipt chain is cyclic or disconnected"
            )
        self._validate_chain(
            tuple(ordered),
            require_admission=not allow_incomplete_admission,
        )
        return tuple(ordered)

    def _node(
        self,
        record: Mapping[str, Any],
        *,
        expected_run_id: str,
    ) -> _ReceiptNode:
        try:
            receipt_body = record.get("receipt_body")
            if not isinstance(receipt_body, str):
                raise TypeError
            event = DesignRunReceiptEvent.model_validate_json(receipt_body)
        except (TypeError, ValueError) as exc:
            raise DesignRunEvidenceError(
                "design-run receipt event is malformed"
            ) from exc
        event_hash = event.content_hash
        actor = record.get("actor")
        expected_actor = {
            "actor_type": event.actor_type,
            "id": event.actor_id,
        }
        target_refs = record.get("target_refs")
        receipt_id = record.get("id")
        created_at = record.get("created_at")
        expected_idempotency_key = (
            f"design-run:{expected_run_id}:{event.event_type}:"
            f"{event.artifact_hash}:"
            f"{event.previous_receipt_hash or 'root'}"
        )
        if (
            set(record) != _RECEIPT_FIELDS
            or record.get("object_type") != "BuilderOpsReceipt"
            or record.get("authority_class") != "receipt"
            or record.get("lifecycle_state") != "active"
            or record.get("promotion_status") != "not_promotable"
            or not isinstance(created_at, str)
            or record.get("updated_at") != created_at
            or record.get("event_type") != DESIGN_RUN_RECEIPT_EVENT_TYPE
            or event.run_id != expected_run_id
            or record.get("action") != event.event_type
            or record.get("occurred_at") != event.occurred_at
            or actor != expected_actor
            or record.get("created_by") != expected_actor
            or record.get("summary")
            != f"Design run {event.event_type.replace('_', ' ')}"
            or record.get("idempotency_key")
            != expected_idempotency_key
            or record.get("source_refs")
            != [dict(ref) for ref in _SOURCE_REFS]
            or not isinstance(receipt_id, str)
            or not receipt_id
            or receipt_id
            != self._receipt_id(
                expected_run_id,
                previous_receipt_id=event.previous_receipt_id,
                previous_receipt_hash=event.previous_receipt_hash,
            )
            or not isinstance(target_refs, list)
            or target_refs
            != [
                {
                    "ref_type": "design_run",
                    "ref": expected_run_id,
                    "authority_surface": "builderops",
                }
            ]
        ):
            raise DesignRunEvidenceError(
                "design-run receipt envelope does not match its event"
            )
        return _ReceiptNode(record=dict(record), event=event, event_hash=event_hash)

    def _validate_chain(
        self,
        chain: Sequence[_ReceiptNode],
        *,
        require_admission: bool = True,
    ) -> None:
        if chain[0].event.event_type != "request_persisted":
            raise DesignRunEvidenceError(
                "design-run receipt chain root is not the request"
            )
        bundle = self._parse_bundle(chain[0].event.artifact)
        counts: dict[str, int] = {}
        status: DesignRunStatusValue | None = None
        terminal = False
        admission: DesignRunAdmission | None = None
        approval: DesignRunApprovalEvidence | None = None
        start_node: _ReceiptNode | None = None
        start_actor_id: str | None = None
        previous_occurred_at: str | None = None
        for index, node in enumerate(chain):
            event = node.event
            if (
                previous_occurred_at is not None
                and event.occurred_at < previous_occurred_at
            ):
                raise DesignRunEvidenceError(
                    "design-run receipt time is not causal"
                )
            previous_occurred_at = event.occurred_at
            counts[event.event_type] = counts.get(event.event_type, 0) + 1
            if event.event_type == "request_persisted":
                if index != 0 or counts[event.event_type] != 1:
                    raise DesignRunEvidenceError(
                        "design-run request receipt repeats"
                    )
                if (
                    event.actor_type != "agent"
                    or event.actor_id != _SERVICE_ACTOR_ID
                    or event.occurred_at != bundle.request.requested_at
                    or event.state != "unknown"
                    or event.previous_state is not None
                ):
                    raise DesignRunEvidenceError(
                        "design-run request receipt is invalid"
                    )
            elif event.event_type == "admission_recorded":
                if admission is not None or start_node is not None or terminal:
                    raise DesignRunEvidenceError(
                        "design-run admission ordering is invalid"
                    )
                admission = cast(
                    DesignRunAdmission,
                    self._parse_contract(
                        event.artifact,
                        DesignRunAdmission,
                    ),
                )
                try:
                    expected_admission = self._evaluate_admission(
                        run_id=event.run_id,
                        bundle=bundle,
                        evaluated_at=event.occurred_at,
                        repo_token_hash=(
                            admission.repo_token_hash_observed
                        ),
                    )
                except ValueError as exc:
                    raise DesignRunEvidenceError(
                        "design-run admission semantics are invalid"
                    ) from exc
                if (
                    admission != expected_admission
                    or event.state != self._admission_state(admission)
                    or event.actor_type != "agent"
                    or event.actor_id != _SERVICE_ACTOR_ID
                ):
                    raise DesignRunEvidenceError(
                        "design-run admission semantics are invalid"
                    )
                if admission.outcome == "deny":
                    terminal = True
            elif event.event_type in {
                "approval_recorded",
                "approval_revoked",
            }:
                if admission is None or start_node is not None or terminal:
                    raise DesignRunEvidenceError(
                        "design-run approval ordering is invalid"
                    )
                candidate = cast(
                    DesignRunApprovalEvidence,
                    self._parse_contract(
                        event.artifact,
                        DesignRunApprovalEvidence,
                    ),
                )
                expected_state = (
                    "approved"
                    if event.event_type == "approval_recorded"
                    else "revoked"
                )
                try:
                    validate_approval_bindings(
                        candidate,
                        request=bundle.request,
                        admission=admission,
                        brief=bundle.brief,
                        adapter=bundle.adapter,
                        policy=bundle.policy,
                    )
                except ValueError as exc:
                    raise DesignRunEvidenceError(
                        "design-run approval bindings are invalid"
                    ) from exc
                if (
                    admission.outcome != "approval_required"
                    or candidate.state != expected_state
                    or candidate.approved_at != event.occurred_at
                    or candidate.approved_at < admission.evaluated_at
                    or event.actor_type != "human"
                    or event.state is not None
                    or event.previous_state is not None
                    or (
                        candidate.state == "revoked"
                        and (
                            approval is None
                            or approval.state != "approved"
                        )
                    )
                ):
                    raise DesignRunEvidenceError(
                        "design-run approval receipt is invalid"
                    )
                approval = candidate
            elif event.event_type == "start_accepted":
                if admission is None or start_node is not None or terminal:
                    raise DesignRunEvidenceError(
                        "design-run accepted-start ordering is invalid"
                    )
                if (
                    admission.outcome == "deny"
                    or (
                        admission.outcome == "approval_required"
                        and (
                            approval is None
                            or approval.state != "approved"
                            or approval.approved_at > event.occurred_at
                        )
                    )
                ):
                    raise DesignRunEvidenceError(
                        "design-run accepted start lacks exact approval"
                    )
                try:
                    resolution = (
                        DesignAgentAvailabilityDescriptor.model_validate_json(
                            canonical_json(event.artifact)
                        )
                    )
                except ValueError as exc:
                    raise DesignRunEvidenceError(
                        "design-run resolution evidence is malformed"
                    ) from exc
                if (
                    event.actor_type != "agent"
                    or not self._is_execution_actor_id(event.actor_id)
                    or event.state != "running"
                    or not resolution.available
                    or resolution.design_agent_id
                    != bundle.adapter.descriptor_id
                    or resolution.role_profile_id
                    != bundle.adapter.role_profile_id
                    or resolution.resolution_group_id
                    != f"design-run:{event.run_id}"
                    or not set(
                        bundle.adapter.supported_deliverables
                    ).issubset(resolution.supported_deliverables)
                ):
                    raise DesignRunEvidenceError(
                        "design-run resolution does not bind the request"
                    )
                start_node = node
                start_actor_id = event.actor_id
            elif event.event_type == "run_refused":
                if admission is None or start_node is not None or terminal:
                    raise DesignRunEvidenceError(
                        "design-run refusal ordering is invalid"
                    )
                terminal = True
                try:
                    refusal = DesignRunRefusalDetail.model_validate(
                        event.artifact
                    )
                except ValueError as exc:
                    raise DesignRunEvidenceError(
                        "design-run refusal artifact is malformed"
                    ) from exc
                expected_refusal_state = (
                    "unavailable"
                    if refusal.code == "adapter_unavailable"
                    else "denied"
                )
                if (
                    event.actor_type != "agent"
                    or event.actor_id != _SERVICE_ACTOR_ID
                    or refusal.code
                    not in {
                        "adapter_unavailable",
                        "admission_denied",
                        "yggdrasil_gate_missing",
                        "yggdrasil_gate_stale",
                        "yggdrasil_token_drift",
                    }
                    or event.state != expected_refusal_state
                ):
                    raise DesignRunEvidenceError(
                        "design-run refusal semantics are invalid"
                    )
            elif event.event_type in {
                "run_succeeded",
                "run_failed",
                "recovery_failed",
            }:
                if start_node is None or terminal:
                    raise DesignRunEvidenceError(
                        "design-run terminal ordering is invalid"
                    )
                terminal = True
                result = self._parse_contract(
                    event.artifact, DesignRunResult
                )
                if (
                    event.event_type == "run_succeeded"
                    and result.final_status != "succeeded"
                ) or (
                    event.event_type == "run_failed"
                    and result.final_status not in {"failed", "timed_out"}
                ) or (
                    event.event_type == "recovery_failed"
                    and result.final_status != "failed"
                ):
                    raise DesignRunEvidenceError(
                        "design-run result does not match its event"
                    )
                if (
                    event.actor_type != "agent"
                    or (
                        event.event_type
                        in {"run_succeeded", "run_failed"}
                        and event.actor_id != start_actor_id
                    )
                    or (
                        event.event_type == "recovery_failed"
                        and not self._is_execution_actor_id(
                            event.actor_id
                        )
                    )
                    or result.result_id != f"{event.run_id}.result"
                    or result.run_id != event.run_id
                    or result.completed_at != event.occurred_at
                    or result.request_ref
                    != contract_ref(
                        bundle.request,
                        bundle.request.request_id,
                    )
                    or event.state != result.final_status
                ):
                    raise DesignRunEvidenceError(
                        "design-run result bindings are invalid"
                    )
                expected_failure: DesignRunRefusalDetail | None = None
                if (
                    event.event_type == "run_failed"
                    and result.final_status == "failed"
                ):
                    expected_failure = DesignRunRefusalDetail(
                        code="execution_failed",
                        public_message="The selected design agent failed.",
                        retryable=False,
                    )
                elif (
                    event.event_type == "run_failed"
                    and result.final_status == "timed_out"
                ):
                    expected_failure = DesignRunRefusalDetail(
                        code="timed_out",
                        public_message="The selected design agent timed out.",
                        retryable=False,
                    )
                elif event.event_type == "recovery_failed":
                    expected_failure = DesignRunRefusalDetail(
                        code="execution_failed",
                        public_message=(
                            "A prior accepted execution ended without "
                            "terminal evidence."
                        ),
                        retryable=False,
                    )
                if (
                    event.event_type != "run_succeeded"
                    and result.refusal != expected_failure
                ):
                    raise DesignRunEvidenceError(
                        "design-run failure semantics are invalid"
                    )
                if result.final_status == "succeeded":
                    handoff = result.handoff
                    if (
                        handoff is None
                        or handoff.handoff_id
                        != f"{event.run_id}.handoff"
                        or handoff.run_id != event.run_id
                        or handoff.adapter_ref
                        != bundle.request.adapter_ref
                        or handoff.source_refs != bundle.brief.source_refs
                        or handoff.receipt_ref
                        != ContractIdentityRef(
                            schema_version=DESIGN_RUN_EVENT_VERSION,
                            contract_id=start_node.receipt_id,
                            content_hash=start_node.event_hash,
                        )
                        or handoff.produced_at != result.completed_at
                        or handoff.limitations
                        != _UNACCEPTED_HANDOFF_LIMITATIONS
                    ):
                        raise DesignRunEvidenceError(
                            "design-run handoff lineage is invalid"
                        )

            if event.state is not None:
                try:
                    DesignRunStatus(
                        run_id=event.run_id,
                        state=event.state,
                        previous_state=event.previous_state,
                        observed_at=event.occurred_at,
                    )
                except ValueError as exc:
                    raise DesignRunEvidenceError(
                        "design-run status transition is invalid"
                    ) from exc
                if event.previous_state != status:
                    raise DesignRunEvidenceError(
                        "design-run status ancestry is invalid"
                    )
                status = event.state
        if require_admission and admission is None:
            raise DesignRunEvidenceError("design-run admission receipt is missing")

    @staticmethod
    def _parse_contract(
        payload: Mapping[str, Any],
        expected_type: type[CanonicalDesignRunContract],
    ) -> Any:
        try:
            parsed = parse_design_run_contract(payload)
        except (TypeError, ValueError) as exc:
            raise DesignRunEvidenceError(
                "design-run contract artifact is malformed"
            ) from exc
        if not isinstance(parsed, expected_type):
            raise DesignRunEvidenceError(
                "design-run receipt contains the wrong contract kind"
            )
        return parsed

    @classmethod
    def _parse_bundle(cls, payload: Mapping[str, Any]) -> _RunBundle:
        if set(payload) != {"adapter", "brief", "policy", "request"}:
            raise DesignRunEvidenceError("design-run request bundle is malformed")
        return _RunBundle(
            request=cast(
                DesignRunRequest,
                cls._parse_contract(payload["request"], DesignRunRequest),
            ),
            brief=cast(
                CuratedDesignBrief,
                cls._parse_contract(payload["brief"], CuratedDesignBrief),
            ),
            adapter=cast(
                DesignAgentDescriptor,
                cls._parse_contract(payload["adapter"], DesignAgentDescriptor),
            ),
            policy=cast(
                DesignRunPolicyProfile,
                cls._parse_contract(payload["policy"], DesignRunPolicyProfile),
            ),
        )

    @classmethod
    def _bundle(cls, chain: Sequence[_ReceiptNode]) -> _RunBundle:
        return cls._parse_bundle(chain[0].event.artifact)

    @classmethod
    def _admission(
        cls, chain: Sequence[_ReceiptNode]
    ) -> DesignRunAdmission | None:
        for node in chain:
            if node.event.event_type == "admission_recorded":
                return cast(
                    DesignRunAdmission,
                    cls._parse_contract(
                        node.event.artifact, DesignRunAdmission
                    ),
                )
        return None

    @classmethod
    def _required_admission(
        cls, chain: Sequence[_ReceiptNode]
    ) -> DesignRunAdmission:
        admission = cls._admission(chain)
        if admission is None:
            raise DesignRunEvidenceError("design-run admission is missing")
        return admission

    @classmethod
    def _latest_approval(
        cls, chain: Sequence[_ReceiptNode]
    ) -> DesignRunApprovalEvidence | None:
        latest: DesignRunApprovalEvidence | None = None
        for node in chain:
            if node.event.event_type in {
                "approval_recorded",
                "approval_revoked",
            }:
                latest = cast(
                    DesignRunApprovalEvidence,
                    cls._parse_contract(
                        node.event.artifact, DesignRunApprovalEvidence
                    ),
                )
        return latest

    @classmethod
    def _result(
        cls, chain: Sequence[_ReceiptNode]
    ) -> DesignRunResult | None:
        for node in reversed(chain):
            if node.event.event_type in {
                "run_succeeded",
                "run_failed",
                "recovery_failed",
            }:
                return cast(
                    DesignRunResult,
                    cls._parse_contract(node.event.artifact, DesignRunResult),
                )
        return None

    @staticmethod
    def _terminal_refusal(
        chain: Sequence[_ReceiptNode],
    ) -> DesignRunRefusalDetail | None:
        for node in reversed(chain):
            if node.event.event_type == "run_refused":
                try:
                    return DesignRunRefusalDetail.model_validate(
                        node.event.artifact
                    )
                except ValueError as exc:
                    raise DesignRunEvidenceError(
                        "design-run refusal artifact is malformed"
                    ) from exc
        return None

    @staticmethod
    def _current_state(
        chain: Sequence[_ReceiptNode],
    ) -> DesignRunStatusValue:
        for node in reversed(chain):
            if node.event.state is not None:
                return node.event.state
        raise DesignRunEvidenceError("design-run status evidence is missing")

    @staticmethod
    def _root(chain: Sequence[_ReceiptNode]) -> _ReceiptNode:
        if not chain:
            raise DesignRunEvidenceError("design-run evidence is missing")
        return chain[0]

    def _acquire_run_lease(
        self,
        root_receipt_id: str,
        *,
        actor: Mapping[str, str] | None = None,
    ) -> Mapping[str, Any]:
        selected_actor = actor or self._execution_actor
        try:
            return self.store.acquire_lease(
                root_receipt_id,
                actor=selected_actor,
                ttl_seconds=self.lease_ttl_seconds,
            )
        except BuilderOpsLeaseError as exc:
            raise DesignRunIncompleteError(
                "another governed design-run mutation is active"
            ) from exc

    def _release_run_lease(
        self,
        lease: Mapping[str, Any],
        *,
        actor: Mapping[str, str] | None = None,
    ) -> None:
        lease_id = lease.get("lease_id")
        if not isinstance(lease_id, str):
            raise DesignRunPersistenceError("design-run lease receipt is malformed")
        try:
            self.store.release_lease(
                lease_id,
                actor=actor or self._execution_actor,
            )
        except BuilderOpsLeaseError as exc:
            raise DesignRunPersistenceError(
                "design-run lease release failed"
            ) from exc

    def _run_lock(self, run_id: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(run_id, threading.Lock())

    @staticmethod
    def _require_run_id(run_id: str) -> None:
        if not is_safe_design_run_identifier(run_id):
            raise DesignRunGovernanceError("invalid design-run identifier")

    @staticmethod
    def _require_causal_execution_times(
        *,
        started_at: str,
        completed_at: str,
    ) -> None:
        try:
            started = datetime.strptime(
                started_at,
                "%Y-%m-%dT%H:%M:%SZ",
            )
            completed = datetime.strptime(
                completed_at,
                "%Y-%m-%dT%H:%M:%SZ",
            )
        except ValueError as exc:
            raise DesignRunGovernanceError(
                "design-run execution times must be RFC 3339 UTC"
            ) from exc
        if completed < started:
            raise DesignRunGovernanceError(
                "design-run completion precedes its accepted start"
            )

    @staticmethod
    def _service_actor() -> dict[str, str]:
        return {"actor_type": "agent", "id": _SERVICE_ACTOR_ID}

    @staticmethod
    def _is_execution_actor_id(actor_id: str) -> bool:
        prefix = f"{_SERVICE_ACTOR_ID}:"
        token = actor_id.removeprefix(prefix)
        return (
            actor_id.startswith(prefix)
            and len(token) == 16
            and all(character in "0123456789abcdef" for character in token)
        )

    @staticmethod
    def _receipt_id(
        run_id: str,
        *,
        previous_receipt_id: str | None,
        previous_receipt_hash: str | None,
    ) -> str:
        predecessor = (
            f"{previous_receipt_id}:{previous_receipt_hash}"
            if previous_receipt_id is not None
            and previous_receipt_hash is not None
            else "root"
        )
        digest = hashlib.sha256(
            f"{run_id}:{predecessor}".encode("utf-8")
        ).hexdigest()[:24]
        return f"receipt_design_run_{digest}"


__all__ = [
    "DESIGN_RUN_EVENT_VERSION",
    "DESIGN_RUN_POLICY_PATH",
    "DESIGN_RUN_RECEIPT_EVENT_TYPE",
    "DesignRunApprovalRequiredError",
    "DesignRunEvidenceError",
    "DesignRunGovernance",
    "DesignRunGovernanceError",
    "DesignRunIncompleteError",
    "DesignRunPersistenceError",
    "DesignRunProjection",
    "DesignRunReceiptEvent",
    "DesignRunUnavailableError",
    "load_design_run_policy",
]
