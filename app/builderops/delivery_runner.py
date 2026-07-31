"""Bounded DDO-04 adapters over the existing delivery authorities.

Nothing in this module decides whether an effect is allowed - that is the
reducer's job - and nothing here reimplements a claim, CI wait, verified merge,
or closure. Each reducer-authorized effect resolves to the governing entrypoint
that already owns that authority, and the runner either shells to it or hands
off to the governing skill that owns the GitHub write.

The worker-execution preflight is deliberately ordered. Strict canonical
re-validation of every replayed sidecar, then the complete worker authority
chain, then the reducer's own authorization all run *before* the first side
effect. Worktree preparation is a side effect, so it happens last: a broken
chain leaves nothing behind to clean up.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, Protocol, TypeAlias, get_args

from app.builderops.delivery_orchestration_contracts import (
    DeliveryPlan,
    EffectClass,
    IssueScope,
    ReducerEffect,
    WorkerContextPack,
    WorkerInvocation,
    WorkerRuntimeObservation,
    WorkerRuntimeState,
)
from app.builderops.delivery_reducer import (
    ContractRef,
    DeliveryRunState,
    ReducerAdmissionError,
    replay_delivery_sidecar,
)

HandoffKind: TypeAlias = Literal["subprocess", "governed_skill"]

WORKER_RUNTIME_STATES: Final[tuple[WorkerRuntimeState, ...]] = get_args(
    WorkerRuntimeState
)

WORKER_RUNTIME_OPERATIONS: Final[tuple[str, ...]] = (
    "start",
    "inspect",
    "heartbeat",
    "interrupt",
    "reattach",
    "await_terminal",
    "cancel",
)

#: The exact repo-relative entrypoints that already own each authority. Every
#: path here is asserted to exist, so a renamed or imagined script cannot be
#: advertised as an adapter.
AUTHORITY_ENTRYPOINTS: Final[Mapping[str, str]] = {
    "claim_issue": "scripts/issue_pickup_claim.sh",
    "workspace_preflight": "scripts/agent_workspace_preflight.sh",
    "worktree_lifecycle": "scripts/agent_worktree.py",
    "await_ci": "scripts/await_pr_checks.sh",
    "verified_delivery_skill": ".codex/skills/verification-and-closure/SKILL.md",
    "verified_merge_planner": "scripts/prepare_verified_issue_set_merge.py",
    "verified_merge_phase": "scripts/build_verified_issue_set_merge_phase.py",
}

_GOVERNED_SKILL: Final[str] = AUTHORITY_ENTRYPOINTS["verified_delivery_skill"]


class DeliveryAuthorityError(RuntimeError):
    """Raised when an effect cannot be routed to a governing authority."""


class WorkerRuntimeUnknownError(RuntimeError):
    """Raised when a runtime readback cannot authorize any further action."""


@dataclass(frozen=True)
class AuthorityInvocation:
    """How one reducer-authorized effect reaches its existing authority."""

    effect_class: EffectClass
    handoff: HandoffKind
    entrypoint: str
    argv: tuple[str, ...]


def resolve_authority_invocation(
    effect: ReducerEffect,
    *,
    agent_id: str,
    session_id: str,
    claim_ttl_minutes: int = 90,
) -> AuthorityInvocation:
    """Route one effect to the entrypoint that already owns its authority.

    ``request_review``, ``merge_pull_request``, ``close_issue``,
    ``record_known_defect``, and ``record_delivery_receipt`` are governed by
    ``verification-and-closure``; that skill owns every GitHub write in the
    verified-delivery ceremony and is not reimplemented here. The planner
    scripts it already uses are named so a caller can prepare the plan without
    inventing a second merge or closure authority.
    """

    issue = effect.issue
    if effect.effect_class == "claim_issue":
        return AuthorityInvocation(
            effect_class=effect.effect_class,
            handoff="subprocess",
            entrypoint=AUTHORITY_ENTRYPOINTS["claim_issue"],
            argv=(
                AUTHORITY_ENTRYPOINTS["claim_issue"],
                "--issue",
                str(issue.issue_number),
                "--repo",
                issue.repository,
                "--agent",
                agent_id,
                "--session",
                session_id,
                "--ttl-minutes",
                str(claim_ttl_minutes),
            ),
        )
    if effect.effect_class == "await_ci":
        if effect.pull_request_number is None or effect.exact_head_sha is None:
            raise DeliveryAuthorityError(
                "await_ci requires the authorized pull request and exact head"
            )
        return AuthorityInvocation(
            effect_class=effect.effect_class,
            handoff="subprocess",
            entrypoint=AUTHORITY_ENTRYPOINTS["await_ci"],
            argv=(
                AUTHORITY_ENTRYPOINTS["await_ci"],
                str(effect.pull_request_number),
                "--repo",
                issue.repository,
            ),
        )
    if effect.effect_class == "launch_worker":
        raise DeliveryAuthorityError(
            "launch_worker is executed through the worker runtime port, not a "
            "governing script"
        )
    if effect.effect_class in {"merge_pull_request", "close_issue"}:
        return AuthorityInvocation(
            effect_class=effect.effect_class,
            handoff="governed_skill",
            entrypoint=_GOVERNED_SKILL,
            argv=(
                "python3",
                AUTHORITY_ENTRYPOINTS["verified_merge_planner"]
                if effect.effect_class == "merge_pull_request"
                else AUTHORITY_ENTRYPOINTS["verified_merge_phase"],
            ),
        )
    return AuthorityInvocation(
        effect_class=effect.effect_class,
        handoff="governed_skill",
        entrypoint=_GOVERNED_SKILL,
        argv=(),
    )


def missing_authority_entrypoints(repo_root: Path) -> tuple[str, ...]:
    """Return every advertised entrypoint that does not exist in the repo."""

    return tuple(
        sorted(
            path
            for path in AUTHORITY_ENTRYPOINTS.values()
            if not (repo_root / path).exists()
        )
    )


class WorktreeAdapter(Protocol):
    """The only side effect the worker preflight is permitted to perform."""

    def register(self, *, worktree_path: str, owner: str) -> tuple[str, ...]: ...


@dataclass(frozen=True)
class SubprocessWorktreeAdapter:
    """Register a worktree through the existing lifecycle registry script."""

    repo_root: Path
    runner: Callable[[Sequence[str]], object]

    def register(self, *, worktree_path: str, owner: str) -> tuple[str, ...]:
        argv = (
            "python3",
            AUTHORITY_ENTRYPOINTS["worktree_lifecycle"],
            "--cwd",
            str(self.repo_root),
            "register",
            "--worktree",
            worktree_path,
            "--owner",
            owner,
        )
        self.runner(argv)
        return argv


@dataclass(frozen=True)
class WorkerExecutionPreparation:
    """A validated, reducer-authorized worker start with its ordered trace."""

    context_pack: WorkerContextPack
    invocation: WorkerInvocation
    worktree_argv: tuple[str, ...]
    trace: tuple[str, ...]


_PREFLIGHT_STEPS: Final[tuple[str, ...]] = (
    "context_pack_revalidated",
    "invocation_revalidated",
    "authority_chain_resolved",
    "reducer_authorization_resolved",
    "worktree_registered",
)


def prepare_worker_execution(
    *,
    raw_context_pack: str | bytes | bytearray | Mapping[str, object],
    raw_invocation: str | bytes | bytearray | Mapping[str, object],
    context_pack_ref: ContractRef,
    invocation_ref: ContractRef,
    launch_effect: ReducerEffect,
    plan: DeliveryPlan,
    state: DeliveryRunState,
    issue: IssueScope,
    worktree_path: str,
    owner_session_id: str,
    worktree_adapter: WorktreeAdapter,
) -> WorkerExecutionPreparation:
    """Validate the full worker authority chain before preparing a worktree.

    The order is the guarantee. Replayed sidecars are strictly re-parsed and
    matched to their references, the pack/invocation/effect/plan/Issue chain is
    resolved, and the reducer's own authorization is confirmed - all before the
    worktree adapter is touched. If any of that fails, no worktree, no preflight,
    and no provider call has happened yet.
    """

    trace: list[str] = []
    pack = replay_delivery_sidecar(raw_context_pack, expected_ref=context_pack_ref)
    if not isinstance(pack, WorkerContextPack):
        raise ReducerAdmissionError("replayed sidecar is not a worker context pack")
    trace.append("context_pack_revalidated")

    invocation = replay_delivery_sidecar(raw_invocation, expected_ref=invocation_ref)
    if not isinstance(invocation, WorkerInvocation):
        raise ReducerAdmissionError("replayed sidecar is not a worker invocation")
    trace.append("invocation_revalidated")

    expected_plan_ref = ContractRef(
        schema_version=plan.schema_version,
        contract_id=plan.plan_id,
        content_hash=plan.content_hash,
    )
    expected_effect_ref = ContractRef(
        schema_version=launch_effect.schema_version,
        contract_id=launch_effect.effect_id,
        content_hash=launch_effect.content_hash,
    )
    if launch_effect.effect_class != "launch_worker":
        raise ReducerAdmissionError(
            "worker preparation requires a launch-worker effect"
        )
    if launch_effect.plan_ref != expected_plan_ref:
        raise ReducerAdmissionError("launch effect does not bind the supplied plan")
    if pack.plan_ref != expected_plan_ref or invocation.plan_ref != expected_plan_ref:
        raise ReducerAdmissionError("worker chain must bind exactly one plan")
    if (
        pack.effect_ref != expected_effect_ref
        or invocation.effect_ref != expected_effect_ref
    ):
        raise ReducerAdmissionError(
            "worker chain must bind exactly one authorizing effect"
        )
    if invocation.context_pack_ref != context_pack_ref:
        raise ReducerAdmissionError("invocation does not resolve this context pack")
    if (
        pack.run_id != state.run_id
        or invocation.run_id != state.run_id
        or launch_effect.run_id != state.run_id
    ):
        raise ReducerAdmissionError("worker chain must bind exactly one run")
    if pack.issue != issue or invocation.issue != issue or launch_effect.issue != issue:
        raise ReducerAdmissionError("worker chain must bind exactly one Issue")
    if pack.base_head_sha != invocation.base_head_sha:
        raise ReducerAdmissionError("worker chain must bind exactly one base head")
    trace.append("authority_chain_resolved")

    issue_state = state.issue_state(issue.scope_key)
    if issue_state is None:
        raise ReducerAdmissionError("Issue is outside the run's bound scope")
    if issue_state.phase != "launching":
        raise ReducerAdmissionError(
            "the reducer has not authorized a worker start in this phase"
        )
    if (
        issue_state.authorized_invocation_effect_key is not None
        and issue_state.authorized_invocation_effect_key
        != launch_effect.idempotency_key
    ):
        raise ReducerAdmissionError(
            "launch effect is not the invocation the reducer authorized"
        )
    trace.append("reducer_authorization_resolved")

    worktree_argv = worktree_adapter.register(
        worktree_path=worktree_path, owner=owner_session_id
    )
    trace.append("worktree_registered")
    return WorkerExecutionPreparation(
        context_pack=pack,
        invocation=invocation,
        worktree_argv=tuple(worktree_argv),
        trace=tuple(trace),
    )


class WorkerRuntimePort(Protocol):
    """Provider-neutral worker runtime seam.

    Every operation is keyed by the invocation's start-once identity and answers
    with a typed :class:`WorkerRuntimeObservation`. No provider session object,
    process handle, or exit status crosses this boundary.
    """

    def start(self, invocation: WorkerInvocation) -> WorkerRuntimeObservation: ...

    def inspect(self, invocation: WorkerInvocation) -> WorkerRuntimeObservation: ...

    def heartbeat(self, invocation: WorkerInvocation) -> WorkerRuntimeObservation: ...

    def interrupt(self, invocation: WorkerInvocation) -> WorkerRuntimeObservation: ...

    def reattach(self, invocation: WorkerInvocation) -> WorkerRuntimeObservation: ...

    def await_terminal(
        self, invocation: WorkerInvocation
    ) -> WorkerRuntimeObservation: ...

    def cancel(self, invocation: WorkerInvocation) -> WorkerRuntimeObservation: ...


#: The single behavioral rule for one invocation identity: only ``not_started``
#: may ever be started, an unknown start reconciles by reattaching, a live
#: runtime is inspected, and a terminal runtime returns its recorded result.
START_ONCE_OPERATION_BY_STATE: Final[Mapping[WorkerRuntimeState, str | None]] = {
    "not_started": "start",
    "starting_unknown": "reattach",
    "running": "inspect",
    "idle": "inspect",
    "terminal": None,
    "unreachable": None,
    "cancelled": None,
}


def resolve_worker_start(
    port: WorkerRuntimePort,
    invocation: WorkerInvocation,
    observed: WorkerRuntimeObservation,
) -> WorkerRuntimeObservation:
    """Advance one invocation identity without ever starting it twice.

    A terminal readback returns the recorded result rather than launching again;
    an unreachable or cancelled runtime cannot be advanced at all, so a retry
    requires a new reducer-authorized effect and a new invocation identity.
    """

    if observed.invocation_idempotency_key != invocation.idempotency_key:
        raise WorkerRuntimeUnknownError(
            "runtime observation does not bind this invocation identity"
        )
    operation = START_ONCE_OPERATION_BY_STATE[observed.runtime_state]
    if operation is None:
        if observed.runtime_state == "terminal":
            return observed
        raise WorkerRuntimeUnknownError(
            f"runtime state {observed.runtime_state!r} cannot authorize a start; "
            "a retry requires a new reducer-authorized invocation identity"
        )
    result: WorkerRuntimeObservation = getattr(port, operation)(invocation)
    if result.invocation_idempotency_key != invocation.idempotency_key:
        raise WorkerRuntimeUnknownError(
            "runtime response does not bind this invocation identity"
        )
    return result


__all__ = [
    "AUTHORITY_ENTRYPOINTS",
    "START_ONCE_OPERATION_BY_STATE",
    "WORKER_RUNTIME_OPERATIONS",
    "WORKER_RUNTIME_STATES",
    "AuthorityInvocation",
    "DeliveryAuthorityError",
    "HandoffKind",
    "SubprocessWorktreeAdapter",
    "WorkerExecutionPreparation",
    "WorkerRuntimePort",
    "WorkerRuntimeUnknownError",
    "WorktreeAdapter",
    "missing_authority_entrypoints",
    "prepare_worker_execution",
    "resolve_authority_invocation",
    "resolve_worker_start",
]
