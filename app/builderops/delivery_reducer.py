"""Pure DDO-04 delivery-run reducer and carrier-neutral worker seam.

This module deliberately contains no GitHub, dispatcher, subprocess, or provider calls.  It
turns typed, version-fenced evidence into typed requests for the existing authorities to execute.
DDO-05 owns durable effect binding and reconciliation.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal, Protocol

from pydantic import ConfigDict, model_validator

from app.builderops.delivery_orchestration_contracts import (
    CanonicalDeliveryContract,
    ContractRef,
    IssueScope,
    NonEmptyStr,
    Sha256,
    canonical_hash,
)


class _FrozenContract(CanonicalDeliveryContract):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class DeliveryAcceptanceProfile(_FrozenContract):
    """Immutable, hash-addressed meaning of terminal delivery for one run."""

    contract_family = "acceptance_profile"
    schema_version: Literal["builderops.delivery-acceptance-profile.v1"] = (
        "builderops.delivery-acceptance-profile.v1"
    )
    profile_id: NonEmptyStr
    required_evidence: tuple[
        Literal["issue_closed", "pr_merged", "ci_green", "review_accepted"] , ...
    ]

    @model_validator(mode="after")
    def _canonical_evidence(self) -> "DeliveryAcceptanceProfile":
        if not self.required_evidence:
            raise ValueError("acceptance profile requires lower-level evidence")
        if len(self.required_evidence) != len(set(self.required_evidence)):
            raise ValueError("acceptance profile evidence must be unique")
        if self.required_evidence != tuple(sorted(self.required_evidence)):
            raise ValueError("acceptance profile evidence must be sorted")
        return self


class WorkerContextPack(_FrozenContract):
    contract_family = "worker_context_pack"
    schema_version: Literal["builderops.worker-context-pack.v1"] = (
        "builderops.worker-context-pack.v1"
    )
    context_pack_id: NonEmptyStr
    run_id: NonEmptyStr
    plan_ref: ContractRef
    effect_ref: ContractRef
    issue: IssueScope
    exact_head_sha: NonEmptyStr | None = None
    required_skills: tuple[NonEmptyStr, ...]
    verify_targets: tuple[NonEmptyStr, ...]


class WorkerInvocation(_FrozenContract):
    contract_family = "worker_invocation"
    schema_version: Literal["builderops.worker-invocation.v1"] = (
        "builderops.worker-invocation.v1"
    )
    invocation_id: NonEmptyStr
    context_pack_ref: ContractRef
    context_pack_hash: Sha256
    run_id: NonEmptyStr
    plan_ref: ContractRef
    effect_ref: ContractRef
    idempotency_key: NonEmptyStr
    runtime_target: NonEmptyStr

    @model_validator(mode="after")
    def _bind_context_hash(self) -> "WorkerInvocation":
        if self.context_pack_ref.schema_version != "builderops.worker-context-pack.v1":
            raise ValueError("worker invocation must bind worker-context-pack.v1")
        if self.context_pack_ref.content_hash != self.context_pack_hash:
            raise ValueError("worker invocation must bind the exact context-pack hash")
        return self


class WorkerResultV2(_FrozenContract):
    contract_family = "worker_result"
    schema_version: Literal["builderops.worker-result.v2"] = "builderops.worker-result.v2"
    result_id: NonEmptyStr
    invocation_ref: ContractRef
    context_pack_ref: ContractRef
    context_pack_hash: Sha256
    run_id: NonEmptyStr
    plan_ref: ContractRef
    effect_ref: ContractRef
    issue: IssueScope
    exact_head_sha: NonEmptyStr | None
    status: Literal["completed", "blocked", "failed", "cancelled"]
    carrier: NonEmptyStr
    provider: NonEmptyStr
    model: NonEmptyStr
    session_ref: NonEmptyStr
    usage_ref: NonEmptyStr
    provenance_ref: NonEmptyStr

    @model_validator(mode="after")
    def _bind_authority_chain(self) -> "WorkerResultV2":
        if self.context_pack_ref.schema_version != "builderops.worker-context-pack.v1":
            raise ValueError("worker result must bind worker-context-pack.v1")
        if self.invocation_ref.schema_version != "builderops.worker-invocation.v1":
            raise ValueError("worker result must bind worker-invocation.v1")
        if self.context_pack_ref.content_hash != self.context_pack_hash:
            raise ValueError("worker result must bind the exact context-pack hash")
        return self


WorkerRuntimeState = Literal[
    "not_started", "starting_unknown", "running", "idle", "terminal", "unreachable", "cancelled"
]


class WorkerRuntimePort(Protocol):
    """Provider-neutral port; adapters translate this to their existing runtime."""

    def start(self, invocation: WorkerInvocation) -> WorkerRuntimeState: ...
    def inspect(self, invocation: WorkerInvocation) -> WorkerRuntimeState: ...
    def heartbeat(self, invocation: WorkerInvocation) -> WorkerRuntimeState: ...
    def interrupt(self, invocation: WorkerInvocation) -> WorkerRuntimeState: ...
    def reattach(self, invocation: WorkerInvocation) -> WorkerRuntimeState: ...
    def await_terminal(self, invocation: WorkerInvocation) -> WorkerRuntimeState: ...
    def cancel(self, invocation: WorkerInvocation) -> WorkerRuntimeState: ...


@dataclass(frozen=True)
class DeliveryReceiptV2:
    """Additive v2 receipt binding; v1 parsing remains owned by its existing contract."""

    receipt_id: str
    receipt_v1_hash: str
    acceptance_profile_ref: ContractRef
    acceptance_profile_hash: str
    terminal_outcome: Literal["delivered", "blocked", "cancelled", "superseded"]
    superseded_run_id: str | None = None
    superseding_initiation_ref: ContractRef | None = None

    def __post_init__(self) -> None:
        if self.acceptance_profile_ref.content_hash != self.acceptance_profile_hash:
            raise ValueError("receipt v2 must repeat the exact acceptance profile hash")
        if self.terminal_outcome == "superseded":
            if self.superseded_run_id is None or self.superseding_initiation_ref is None:
                raise ValueError("superseded receipt requires both identities")
        elif self.superseded_run_id is not None or self.superseding_initiation_ref is not None:
            raise ValueError("only superseded receipt carries supersession identities")


RunPhase = Literal[
    "new", "claiming", "working", "awaiting_ci", "awaiting_review", "repairing",
    "merging", "closing", "delivered", "blocked", "paused", "cancelled", "superseded",
    "owner_decision", "system_blocked",
]
RunEventKind = Literal[
    "admit", "claimed", "worker_completed", "ci_passed", "review_accepted", "review_p2",
    "review_blocking", "repair_completed", "merged", "closed", "pause", "resume", "cancel",
    "supersede", "authority_ambiguous", "system_missing",
]
EffectKind = Literal[
    "claim_issue", "launch_worker", "await_ci", "request_review", "repair", "merge_pull_request",
    "close_issue", "record_known_defect", "record_delivery_receipt", "cancel_worker",
]


@dataclass(frozen=True)
class DeliveryRunState:
    run_id: str
    plan_ref: ContractRef
    acceptance_profile_ref: ContractRef
    acceptance_profile_hash: str
    version: int = 0
    phase: RunPhase = "new"
    seen_event_ids: frozenset[str] = frozenset()
    worker_head_sha: str | None = None
    repair_count: int = 0


@dataclass(frozen=True)
class DeliveryRunEvent:
    event_id: str
    kind: RunEventKind
    run_id: str
    expected_version: int
    exact_head_sha: str | None = None
    authenticated: bool = True
    protected: bool = False
    confidence_basis_points: int = 10_000


@dataclass(frozen=True)
class EffectRequest:
    kind: EffectKind
    run_id: str
    run_version: int
    idempotency_key: str
    exact_head_sha: str | None = None


@dataclass(frozen=True)
class Reduction:
    state: DeliveryRunState
    effects: tuple[EffectRequest, ...] = ()


_TERMINAL: frozenset[RunPhase] = frozenset({"delivered", "blocked", "cancelled", "superseded", "owner_decision", "system_blocked"})


def _effect(state: DeliveryRunState, kind: EffectKind, head: str | None = None) -> EffectRequest:
    key = canonical_hash({"run": state.run_id, "version": state.version + 1, "kind": kind, "head": head})
    return EffectRequest(kind, state.run_id, state.version + 1, f"ddo04:{key}", head)


def _advance(state: DeliveryRunState, event: DeliveryRunEvent, phase: RunPhase, *effects: EffectRequest) -> Reduction:
    return Reduction(replace(state, version=state.version + 1, phase=phase, seen_event_ids=state.seen_event_ids | {event.event_id}), effects)


def reduce_delivery_run(state: DeliveryRunState, event: DeliveryRunEvent) -> Reduction:
    """Pure total reducer. Unknown, duplicate, stale, and unsafe input never advances state."""
    if event.run_id != state.run_id or event.event_id in state.seen_event_ids:
        return Reduction(state)
    if event.expected_version != state.version or state.phase in _TERMINAL:
        return Reduction(state)
    if event.kind in {"pause", "resume", "cancel", "supersede"} and not event.authenticated:
        return _advance(state, event, "owner_decision")
    if event.kind == "authority_ambiguous":
        return _advance(state, event, "owner_decision")
    if event.kind == "system_missing":
        return _advance(state, event, "system_blocked")
    if event.kind == "pause" and state.phase != "paused":
        return _advance(state, event, "paused")
    if event.kind == "resume" and state.phase == "paused":
        return _advance(state, event, "claiming", _effect(state, "claim_issue"))
    if event.kind == "cancel":
        return _advance(state, event, "cancelled", _effect(state, "cancel_worker"))
    if event.kind == "supersede":
        return _advance(state, event, "superseded", _effect(state, "record_delivery_receipt"))
    if state.phase == "new" and event.kind == "admit":
        return _advance(state, event, "claiming", _effect(state, "claim_issue"))
    if state.phase == "claiming" and event.kind == "claimed":
        return _advance(state, event, "working", _effect(state, "launch_worker"))
    if state.phase == "working" and event.kind == "worker_completed" and event.exact_head_sha:
        updated = replace(state, worker_head_sha=event.exact_head_sha)
        return _advance(updated, event, "awaiting_ci", _effect(updated, "await_ci", event.exact_head_sha))
    if state.phase == "awaiting_ci" and event.kind == "ci_passed" and event.exact_head_sha == state.worker_head_sha:
        return _advance(state, event, "awaiting_review", _effect(state, "request_review", event.exact_head_sha))
    if state.phase == "awaiting_review" and event.kind == "review_accepted" and event.exact_head_sha == state.worker_head_sha:
        return _advance(state, event, "merging", _effect(state, "merge_pull_request", event.exact_head_sha))
    if state.phase == "awaiting_review" and event.kind == "review_p2" and not event.protected and event.confidence_basis_points >= 9000:
        return _advance(state, event, "merging", _effect(state, "record_known_defect", state.worker_head_sha))
    if state.phase == "awaiting_review" and event.kind in {"review_blocking", "review_p2"}:
        return _advance(state, event, "blocked")
    if state.phase == "repairing" and event.kind == "repair_completed" and event.exact_head_sha:
        updated = replace(state, worker_head_sha=event.exact_head_sha)
        return _advance(updated, event, "awaiting_ci", _effect(updated, "await_ci", event.exact_head_sha))
    if state.phase == "merging" and event.kind == "merged" and event.exact_head_sha == state.worker_head_sha:
        return _advance(state, event, "closing", _effect(state, "close_issue", event.exact_head_sha))
    if state.phase == "closing" and event.kind == "closed" and event.exact_head_sha == state.worker_head_sha:
        return _advance(state, event, "delivered", _effect(state, "record_delivery_receipt", event.exact_head_sha))
    return Reduction(state)


EXISTING_ADAPTER_PATHS = {
    "claim_issue": "scripts/issue_pickup_claim.sh",
    "await_ci": "scripts/wait_for_pr_checks.py",
    "request_review": ".codex/skills/verification-and-closure/SKILL.md",
    "merge_pull_request": ".codex/skills/verification-and-closure/SKILL.md",
    "close_issue": ".codex/skills/verification-and-closure/SKILL.md",
}


__all__ = [
    "DeliveryAcceptanceProfile", "DeliveryReceiptV2", "DeliveryRunEvent", "DeliveryRunState",
    "EffectRequest", "EXISTING_ADAPTER_PATHS", "Reduction", "WorkerContextPack", "WorkerInvocation",
    "WorkerResultV2", "WorkerRuntimePort", "WorkerRuntimeState", "reduce_delivery_run",
]
