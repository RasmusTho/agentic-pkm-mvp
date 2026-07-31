"""Pure DDO-04 delivery-run reducer over canonical delivery contracts.

This module contains no GitHub, dispatcher, subprocess, filesystem, network, or
provider call. It turns strictly validated, version-fenced canonical evidence
into typed effect proposals for the existing authorities to execute. Every input
the reducer accepts is a delivered contract from
``delivery_orchestration_contracts``; the reducer never defines a second,
unauthenticated event or effect model of its own.

Three boundaries are deliberate and load-bearing:

* **Admission is the only door.** :class:`AdmittedEvent` cannot be constructed
  directly. :func:`admit_reducer_event` canonically re-parses every supplied
  contract, runs ``validate_reducer_event_evidence``, and resolves the complete
  worker authority chain before an event can reach the transition matrix. Free
  text, a process exit code, or provider session state therefore has no path in.
* **Effects are proposals, not writes.** The reducer emits
  :class:`EffectProposal` values. :func:`materialize_effect` turns a proposal
  into a canonical ``ReducerEffect`` using only the delivered identity
  derivations and then re-validates it with ``validate_reducer_effect_evidence``.
* **Cancellation never claims to undo.** Per INV-DDO-15 and the DDO-04 task
  contract, ``pause``/``resume``/``cancel``/``supersede`` emit no compensating
  effect. A committed external effect is recorded as an
  ``OutstandingEffectObligation`` for BuilderOps reconciliation (DDO-05), which
  owns unknown-state reconciliation. :data:`COMPENSATING_EFFECT_CLASSES` is
  empty by contract, not by omission.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from itertools import product
from typing import Final, Literal, TypeAlias, TypeVar, get_args

from app.builderops.delivery_orchestration_contracts import (
    ACCEPTANCE_EVIDENCE_BY_EFFECT_OUTCOME,
    AcceptanceEvidenceKind,
    ActorIdentity,
    AuthoritySnapshot,
    CanonicalDeliveryContract,
    ContractRef,
    DeliveryAcceptanceProfile,
    DeliveryPlan,
    EffectClass,
    EffectOutcomeState,
    IssueScope,
    OutstandingEffectObligation,
    Provenance,
    ReducerEffect,
    ReducerEvent,
    ReviewResult,
    StructuredWorkerResult,
    WorkerContextPack,
    WorkerInvocation,
    WorkerResultV2,
    canonical_hash,
    delivery_effect_expected_outcome_keys,
    delivery_effect_idempotency_key,
    delivery_effect_input_hash,
    parse_delivery_contract,
    validate_reducer_effect_evidence,
    validate_reducer_event_evidence,
    validate_worker_authority_chain,
)

RunPhase: TypeAlias = Literal[
    "admitted",
    "claiming",
    "launching",
    "working",
    "awaiting_ci",
    "awaiting_review",
    "repairing",
    "recording_defect",
    "merging",
    "closing",
    "recording_receipt",
    "delivered",
    "blocked",
    "owner_decision",
    "system_blocked",
    "cancelled",
    "superseded",
]

ReducerSignal: TypeAlias = Literal[
    "run_started",
    "timer_elapsed",
    "claim_succeeded",
    "worker_launched",
    "checks_passed",
    "review_recorded",
    "known_defect_recorded",
    "merge_succeeded",
    "closure_succeeded",
    "receipt_recorded",
    "effect_failed",
    "authority_changed",
    "worker_result_recorded",
    "review_result_recorded",
    "exception_recorded",
]

RefusalReason: TypeAlias = Literal[
    "duplicate_event",
    "duplicate_command",
    "foreign_run",
    "stale_run_version",
    "stale_plan_binding",
    "terminal_run",
    "paused_run",
    "illegal_transition",
    "pull_request_identity_conflict",
    "head_evidence_conflict",
    "unauthorized_command",
    "unauthorized_effect",
]

LifecycleState: TypeAlias = Literal["active", "paused", "cancelled", "superseded"]

RUN_PHASES: Final[tuple[RunPhase, ...]] = get_args(RunPhase)
REDUCER_SIGNALS: Final[tuple[ReducerSignal, ...]] = get_args(ReducerSignal)

TERMINAL_PHASES: Final[frozenset[RunPhase]] = frozenset(
    {
        "delivered",
        "blocked",
        "repairing",
        "owner_decision",
        "system_blocked",
        "cancelled",
        "superseded",
    }
)

ACTIVE_PHASES: Final[tuple[RunPhase, ...]] = tuple(
    phase for phase in RUN_PHASES if phase not in TERMINAL_PHASES
)

#: INV-DDO-15: cancellation and supersession do not claim to undo an already
#: committed external effect, and the delivered ``EffectClass`` vocabulary
#: intentionally contains no compensating class. DDO-05 owns reconciliation of
#: committed effects; this reducer records obligations and stops.
COMPENSATING_EFFECT_CLASSES: Final[frozenset[EffectClass]] = frozenset()

_SUCCESS_SIGNAL_BY_OUTCOME: Final[dict[EffectOutcomeState, ReducerSignal]] = {
    "claimed": "claim_succeeded",
    "worker_launched": "worker_launched",
    "checks_passed": "checks_passed",
    "review_recorded": "review_recorded",
    "known_defect_recorded": "known_defect_recorded",
    "merged": "merge_succeeded",
    "closed": "closure_succeeded",
    "receipt_recorded": "receipt_recorded",
}

_OWNER_DECISION_EXCEPTIONS: Final[frozenset[str]] = frozenset(
    {"authority_conflict"}
)
_SYSTEM_BLOCK_EXCEPTIONS: Final[frozenset[str]] = frozenset(
    {"dependency_blocked", "external_state_unknown"}
)

#: Evidence that only survives while the reviewed head is unchanged (INV-DDO-7).
_HEAD_BOUND_EVIDENCE: Final[frozenset[AcceptanceEvidenceKind]] = frozenset(
    {"required_checks_green", "review_accepted"}
)

_CONTRACT_IDENTITY_FIELDS: Final[tuple[str, ...]] = (
    "plan_id",
    "effect_id",
    "event_id",
    "result_id",
    "receipt_id",
    "profile_id",
    "context_pack_id",
    "invocation_id",
    "observation_id",
    "initiation_id",
)

_ContractT = TypeVar("_ContractT", bound=CanonicalDeliveryContract)


class ReducerAdmissionError(ValueError):
    """Raised when supplied evidence cannot become an admitted reducer event."""


@dataclass(frozen=True)
class TransitionRule:
    """One cell of the exhaustive (phase, signal) transition matrix."""

    legal: bool
    target_phase: RunPhase | None
    emits: tuple[EffectClass, ...]
    prerequisites: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.legal and not self.prerequisites:
            raise ValueError("a legal transition must name its prerequisites")
        if not self.legal and (
            self.target_phase is not None or self.emits or self.prerequisites
        ):
            raise ValueError("an illegal transition carries no target or effect")


_ILLEGAL: Final[TransitionRule] = TransitionRule(
    legal=False, target_phase=None, emits=(), prerequisites=()
)


def _legal(
    target_phase: RunPhase | None,
    *prerequisites: str,
    emits: tuple[EffectClass, ...] = (),
) -> TransitionRule:
    return TransitionRule(
        legal=True,
        target_phase=target_phase,
        emits=emits,
        prerequisites=tuple(prerequisites),
    )


def _build_transition_matrix() -> (
    Mapping[tuple[RunPhase, ReducerSignal], TransitionRule]
):
    """Return a total map over every (phase, signal) pair.

    Exhaustiveness is structural rather than asserted: the matrix starts fully
    refusing and legal transitions are overlaid, so no pair can be silently
    undefined and every terminal phase keeps refusing every signal.
    """

    matrix: dict[tuple[RunPhase, ReducerSignal], TransitionRule] = {
        (phase, signal): _ILLEGAL
        for phase, signal in product(RUN_PHASES, REDUCER_SIGNALS)
    }

    opening_signals: tuple[ReducerSignal, ...] = ("run_started", "timer_elapsed")
    for opening_signal in opening_signals:
        matrix[("admitted", opening_signal)] = _legal(
            "claiming",
            "the Issue's dependency wave is open",
            "every earlier wave Issue reached delivered terminality",
            emits=("claim_issue",),
        )
    matrix[("claiming", "claim_succeeded")] = _legal(
        "launching",
        "claim_issue succeeded with a truthful ready-to-claimed readback",
        emits=("launch_worker",),
    )
    matrix[("launching", "worker_launched")] = _legal(
        "working",
        "launch_worker succeeded for the authorized invocation identity",
    )
    # A worker result is admissible only from working. A repair must first be
    # re-launched under its own attempt identity, so a result cannot re-enter the
    # run straight from a terminal deferral.
    matrix[("working", "worker_result_recorded")] = _legal(
        None,
        "the worker result resolves the full pack/invocation/effect chain",
        "the result names the launch effect this run authorized",
        "the result repeats the reducer-authorized pull-request identity",
        emits=("await_ci",),
    )
    matrix[("awaiting_ci", "checks_passed")] = _legal(
        "awaiting_review",
        "await_ci succeeded at the authorized pull request and exact head",
        emits=("request_review",),
    )
    matrix[("awaiting_review", "review_recorded")] = _legal(
        "awaiting_review",
        "request_review succeeded; the structured verdict is still pending",
    )
    matrix[("awaiting_review", "review_result_recorded")] = _legal(
        None,
        "the structured verdict binds the authorized pull request and head",
        "severity routing resolves from the verdict, never from prose",
        emits=("merge_pull_request", "record_known_defect"),
    )
    matrix[("recording_defect", "known_defect_recorded")] = _legal(
        "merging",
        "record_known_defect succeeded for the exact registry and finding",
        emits=("merge_pull_request",),
    )
    matrix[("merging", "merge_succeeded")] = _legal(
        "closing",
        "merge_pull_request succeeded at the authorized exact head",
        emits=("close_issue",),
    )
    matrix[("closing", "closure_succeeded")] = _legal(
        "recording_receipt",
        "close_issue succeeded with an observed closed Issue",
        emits=("record_delivery_receipt",),
    )
    matrix[("recording_receipt", "receipt_recorded")] = _legal(
        "delivered",
        "record_delivery_receipt succeeded",
        "the bound acceptance profile is satisfied by lower-level evidence",
    )

    for phase in ACTIVE_PHASES:
        matrix[(phase, "effect_failed")] = _legal(
            None,
            "the failed effect resolves its exact idempotency and outcome keys",
            "the failed effect names the authorized pull request and head",
            "only a red required check awaited in awaiting_ci defers to repair",
        )
        matrix[(phase, "authority_changed")] = _legal(
            None,
            "the observed authority change resolves against the immutable plan",
        )
        matrix[(phase, "exception_recorded")] = _legal(
            None,
            "the typed exception kind selects owner-decision, system-block, "
            "or block",
        )
        if phase != "admitted":
            matrix[(phase, "timer_elapsed")] = _legal(
                phase,
                "a timer tick re-derives due effects and never invents evidence",
            )
    return matrix


REDUCER_TRANSITION_MATRIX: Final[
    Mapping[tuple[RunPhase, ReducerSignal], TransitionRule]
] = _build_transition_matrix()


@dataclass(frozen=True)
class EffectProposal:
    """A next-effect decision. It is not an effect and performs nothing."""

    effect_class: EffectClass
    issue: IssueScope
    expected_authorities: tuple[AuthoritySnapshot, ...]
    pull_request_number: int | None = None
    exact_head_sha: str | None = None
    known_defect_registry_ref: str | None = None
    known_defect_finding_hash: str | None = None


@dataclass(frozen=True)
class EffectLedgerEntry:
    """One effect this run authorized, and the last outcome it observed.

    ``outcome_state`` is ``None`` while the effect is authorized but its typed
    outcome has not been observed. That is an *unknown* external state, not an
    absent one: the adapter may already have removed ``agent:ready``, taken a
    dispatcher lease, or opened a pull request. Cancellation therefore reports
    unknown entries as obligations exactly like committed ones.
    """

    effect_class: EffectClass
    idempotency_key: str
    outcome_keys: tuple[str, ...]
    outcome_state: EffectOutcomeState | None = None
    #: The exact proposal that was authorized. Resume replays this rather than
    #: re-deriving one, so a benign authority relabel between authorization and
    #: resume cannot split one logical effect into two identities.
    proposal: EffectProposal | None = None

    @property
    def is_resolved_uncommitted(self) -> bool:
        """True only when a truthful failure proved the effect did not commit."""

        return self.outcome_state == "failed"


@dataclass(frozen=True)
class IssueRunState:
    """Per-Issue delivery state inside one run."""

    issue: IssueScope
    wave_index: int
    current_authority: AuthoritySnapshot
    phase: RunPhase = "admitted"
    authorized_pull_request: int | None = None
    authorized_head_sha: str | None = None
    authorized_invocation_effect_key: str | None = None
    pending_known_defect_ref: str | None = None
    pending_known_defect_finding_hash: str | None = None
    acceptance_evidence: tuple[AcceptanceEvidenceKind, ...] = ()
    effect_ledger: tuple[EffectLedgerEntry, ...] = ()
    blocked_reason: str | None = None

    @property
    def observed_evidence(self) -> frozenset[AcceptanceEvidenceKind]:
        return frozenset(self.acceptance_evidence)

    @property
    def unreconciled_effects(self) -> tuple[EffectLedgerEntry, ...]:
        """Authorized effects whose external state is committed or unknown."""

        return tuple(
            entry
            for entry in self.effect_ledger
            if not entry.is_resolved_uncommitted
        )


@dataclass(frozen=True)
class DeliveryRunState:
    """Immutable reducer state for one approved delivery run.

    ``plan_ref``, ``acceptance_profile_ref``, and ``acceptance_profile_hash`` are
    bound once at admission and are never rewritten by any transition, so the
    acceptance meaning of the run cannot drift (INV-DDO-17).
    """

    run_id: str
    plan_ref: ContractRef
    acceptance_profile_ref: ContractRef
    acceptance_profile_hash: str
    required_acceptance_evidence: tuple[AcceptanceEvidenceKind, ...]
    required_check_names: tuple[str, ...]
    authorized_control_scopes: tuple[str, ...]
    version: int = 0
    lifecycle: LifecycleState = "active"
    issues: tuple[IssueRunState, ...] = ()
    seen_event_ids: tuple[str, ...] = ()
    seen_command_ids: tuple[str, ...] = ()
    superseding_initiation_ref: ContractRef | None = None

    def issue_state(self, scope_key: tuple[str, int]) -> IssueRunState | None:
        return next(
            (item for item in self.issues if item.issue.scope_key == scope_key),
            None,
        )

    @property
    def is_terminal(self) -> bool:
        return self.lifecycle in {"cancelled", "superseded"} or all(
            item.phase in TERMINAL_PHASES for item in self.issues
        )


@dataclass(frozen=True)
class Reduction:
    """The total result of one reduction step."""

    state: DeliveryRunState
    effects: tuple[EffectProposal, ...] = ()
    refusal: RefusalReason | None = None
    obligations: tuple[OutstandingEffectObligation, ...] = ()


@dataclass(frozen=True)
class LifecycleCommand:
    """A typed, authenticated, version-fenced lifecycle control command.

    Authentication is an :class:`ActorIdentity` whose ``authority_scope`` must
    appear in the run's immutable ``authorized_control_scopes``. A boolean flag
    on the message would be self-asserted and is therefore not accepted.
    """

    command: Literal["pause", "resume", "cancel", "supersede"]
    command_id: str
    run_id: str
    expected_run_version: int
    issued_by: ActorIdentity
    issued_at: str
    superseding_initiation_ref: ContractRef | None = None


_ADMISSION_TOKEN: Final[object] = object()


@dataclass(frozen=True)
class AdmittedEvent:
    """A canonical reducer event whose referenced evidence fully resolved.

    Construction is restricted to :func:`admit_reducer_event`; holding a value of
    this type is proof that strict canonical re-parsing and evidence resolution
    already ran.
    """

    event: ReducerEvent
    signal: ReducerSignal
    effect: ReducerEffect | None
    worker_result: WorkerResultV2 | None
    review_result: ReviewResult | None
    subject_issue: IssueScope | None
    admission_token: object = None

    def __post_init__(self) -> None:
        if self.admission_token is not _ADMISSION_TOKEN:
            raise ReducerAdmissionError(
                "admitted reducer events may only be produced by "
                "admit_reducer_event"
            )


def _contract_identity(contract: CanonicalDeliveryContract) -> str:
    for field in _CONTRACT_IDENTITY_FIELDS:
        value = getattr(contract, field, None)
        if isinstance(value, str):
            return value
    raise ValueError("delivery contract does not expose a canonical identity")


def _typed(
    contract: CanonicalDeliveryContract,
    expected: type[_ContractT],
) -> _ContractT:
    if not isinstance(contract, expected):
        raise ReducerAdmissionError(
            f"canonical re-parse produced {type(contract).__name__}, "
            f"expected {expected.__name__}"
        )
    return contract


def replay_delivery_sidecar(
    raw: str | bytes | bytearray | Mapping[str, object],
    *,
    expected_ref: ContractRef,
) -> CanonicalDeliveryContract:
    """Strictly re-validate one persisted sidecar before it may be replayed.

    A worker or runtime sidecar read back from storage is untrusted bytes. It is
    re-parsed through ``parse_delivery_contract`` - strict, extra-forbidding,
    duplicate-key rejecting - and then its schema version, canonical content
    hash, and canonical identity must all match the reference that claimed it.
    Anything weaker would let a mutated replay payload re-enter the run under a
    reference that no longer describes it, before state assignment, worktree
    preparation, preflight, or any provider call.
    """

    contract = parse_delivery_contract(raw)
    if contract.schema_version != expected_ref.schema_version:
        raise ReducerAdmissionError(
            "replayed sidecar schema version does not match its reference"
        )
    if contract.content_hash != expected_ref.content_hash:
        raise ReducerAdmissionError(
            "replayed sidecar content hash does not match its reference"
        )
    if _contract_identity(contract) != expected_ref.contract_id:
        raise ReducerAdmissionError(
            "replayed sidecar identity does not match its reference"
        )
    return contract


def _revalidate_canonically(
    contract: CanonicalDeliveryContract,
    expected: type[_ContractT],
) -> _ContractT:
    """Round-trip an in-memory contract through strict canonical parsing."""

    reparsed = parse_delivery_contract(contract.canonical_bytes())
    if reparsed.content_hash != contract.content_hash:
        raise ReducerAdmissionError(
            "canonical re-parse changed the contract content hash"
        )
    return _typed(reparsed, expected)


def _issue_for_authority(
    plan: DeliveryPlan,
    authority_id: str,
) -> IssueScope | None:
    return next(
        (item for item in plan.final_scope if item.authority_id == authority_id),
        None,
    )


def admit_reducer_event(
    event: ReducerEvent,
    *,
    plan: DeliveryPlan,
    effect: ReducerEffect | None = None,
    worker_result: WorkerResultV2 | None = None,
    review_result: ReviewResult | None = None,
    context_pack: WorkerContextPack | None = None,
    invocation: WorkerInvocation | None = None,
    launch_effect: ReducerEffect | None = None,
    prior_effects: Sequence[ReducerEffect] = (),
    prior_events: Sequence[ReducerEvent] = (),
    worker_results: Sequence[StructuredWorkerResult] = (),
    review_results: Sequence[ReviewResult] = (),
) -> AdmittedEvent:
    """Resolve one canonical event and its evidence into an admissible input.

    Every supplied contract is canonically re-parsed first, so a mutated or
    non-canonical in-memory object cannot bypass strict validation. Worker
    evidence additionally resolves the complete context-pack to invocation to
    result to authorizing-effect chain before any state assignment can consider
    it.
    """

    plan = _revalidate_canonically(plan, DeliveryPlan)
    event = _revalidate_canonically(event, ReducerEvent)
    if event.event_type == "worker_result_recorded" and worker_result is None:
        raise ReducerAdmissionError(
            "a worker-result event requires the carrier-neutral worker result "
            "envelope; delivery-domain bytes alone cannot advance the reducer"
        )
    if effect is not None:
        effect = _revalidate_canonically(effect, ReducerEffect)
    if review_result is not None:
        review_result = _revalidate_canonically(review_result, ReviewResult)

    domain_result: StructuredWorkerResult | None = None
    if worker_result is not None:
        worker_result = _revalidate_canonically(worker_result, WorkerResultV2)
        if context_pack is None or invocation is None or launch_effect is None:
            raise ReducerAdmissionError(
                "worker evidence requires its context pack, invocation, and "
                "authorizing launch effect"
            )
        validate_worker_authority_chain(
            worker_result,
            context_pack=_revalidate_canonically(context_pack, WorkerContextPack),
            invocation=_revalidate_canonically(invocation, WorkerInvocation),
            effect=_revalidate_canonically(launch_effect, ReducerEffect),
            plan=plan,
        )
        domain_result = worker_result.delivery_result

    validate_reducer_event_evidence(
        event,
        plan=plan,
        effect=effect,
        worker_result=domain_result,
        review_result=review_result,
        prior_effects=tuple(prior_effects),
        prior_events=tuple(prior_events),
        worker_results=tuple(worker_results),
        review_results=tuple(review_results),
    )

    signal, subject_issue = _resolve_signal(
        event,
        plan=plan,
        effect=effect,
        worker_result=worker_result,
        review_result=review_result,
    )
    return AdmittedEvent(
        event=event,
        signal=signal,
        effect=effect,
        worker_result=worker_result,
        review_result=review_result,
        subject_issue=subject_issue,
        admission_token=_ADMISSION_TOKEN,
    )


def _resolve_signal(
    event: ReducerEvent,
    *,
    plan: DeliveryPlan,
    effect: ReducerEffect | None,
    worker_result: WorkerResultV2 | None,
    review_result: ReviewResult | None,
) -> tuple[ReducerSignal, IssueScope | None]:
    if event.event_type == "run_started":
        return "run_started", None
    if event.event_type == "timer_elapsed":
        return "timer_elapsed", None
    if event.event_type == "exception_recorded":
        return "exception_recorded", None
    if event.event_type == "authority_changed":
        assert event.subject_authority is not None
        return "authority_changed", _issue_for_authority(
            plan, event.subject_authority.authority_id
        )
    if event.event_type == "worker_result_recorded":
        if worker_result is None:
            raise ReducerAdmissionError(
                "a worker-result event requires the carrier-neutral worker "
                "result envelope; delivery-domain bytes alone cannot advance "
                "the reducer"
            )
        return "worker_result_recorded", worker_result.issue
    if event.event_type == "review_result_recorded":
        assert review_result is not None
        return "review_result_recorded", review_result.issue
    if effect is None:
        raise ReducerAdmissionError(
            "an effect-result event requires its resolved reducer effect"
        )
    if event.event_type == "effect_failed":
        return "effect_failed", effect.issue
    outcome = event.effect_outcome
    assert outcome is not None
    return _SUCCESS_SIGNAL_BY_OUTCOME[outcome.outcome_state], effect.issue


def initial_delivery_run_state(
    *,
    run_id: str,
    plan: DeliveryPlan,
    acceptance_profile: DeliveryAcceptanceProfile,
    authorized_control_scopes: Sequence[str],
) -> DeliveryRunState:
    """Bind one plan and one acceptance profile into immutable initial state."""

    if not authorized_control_scopes:
        raise ValueError("a run must bind at least one lifecycle control scope")
    plan_ref = ContractRef(
        schema_version=plan.schema_version,
        contract_id=plan.plan_id,
        content_hash=plan.content_hash,
    )
    profile_ref = ContractRef(
        schema_version=acceptance_profile.schema_version,
        contract_id=acceptance_profile.profile_id,
        content_hash=acceptance_profile.content_hash,
    )
    wave_by_scope = {
        issue.scope_key: wave.wave_index
        for wave in plan.dependency_waves
        for issue in wave.issues
    }
    authority_by_id = {item.authority_id: item for item in plan.input_authorities}
    issues: list[IssueRunState] = []
    for issue in plan.final_scope:
        planned_authority = authority_by_id.get(issue.authority_id)
        if planned_authority is None or issue.scope_key not in wave_by_scope:
            raise ValueError(
                "plan scope must bind one dependency wave and one input authority"
            )
        issues.append(
            IssueRunState(
                issue=issue,
                wave_index=wave_by_scope[issue.scope_key],
                current_authority=planned_authority,
            )
        )
    return DeliveryRunState(
        run_id=run_id,
        plan_ref=plan_ref,
        acceptance_profile_ref=profile_ref,
        acceptance_profile_hash=acceptance_profile.content_hash,
        required_acceptance_evidence=acceptance_profile.required_evidence,
        required_check_names=plan.policy_profile.required_check_names,
        authorized_control_scopes=tuple(sorted(set(authorized_control_scopes))),
        issues=tuple(sorted(issues, key=lambda item: item.issue.scope_key)),
    )


def _replace_issue(
    issues: tuple[IssueRunState, ...],
    updated: IssueRunState,
) -> tuple[IssueRunState, ...]:
    return tuple(
        updated if item.issue.scope_key == updated.issue.scope_key else item
        for item in issues
    )


def _with_evidence(
    issue_state: IssueRunState,
    *evidence: AcceptanceEvidenceKind,
) -> tuple[AcceptanceEvidenceKind, ...]:
    return tuple(sorted(set(issue_state.acceptance_evidence) | set(evidence)))


def _effect_evidence(
    admitted: AdmittedEvent,
) -> tuple[AcceptanceEvidenceKind, ...]:
    """Derive acceptance evidence from a typed post-effect outcome only."""

    outcome = admitted.event.effect_outcome
    if outcome is None:
        return ()
    kind = ACCEPTANCE_EVIDENCE_BY_EFFECT_OUTCOME.get(outcome.outcome_state)
    return (kind,) if kind is not None else ()


def _open_wave_index(issues: tuple[IssueRunState, ...]) -> int:
    """Return the lowest wave index that still has undelivered Issues."""

    pending = [item.wave_index for item in issues if item.phase != "delivered"]
    return min(pending) if pending else 0


def _open_due_claims(
    issues: tuple[IssueRunState, ...],
    signal: ReducerSignal,
) -> tuple[tuple[IssueRunState, ...], tuple[EffectProposal, ...]]:
    """Open every Issue whose wave is due and still awaiting its claim.

    The wave boundary is resolved by the reducer alone: no coordinator turn, no
    model decision, and no external input beyond the tick that asked.
    """

    open_wave = _open_wave_index(issues)
    updated = issues
    proposals: list[EffectProposal] = []
    for item in issues:
        if item.wave_index != open_wave:
            continue
        if not REDUCER_TRANSITION_MATRIX[(item.phase, signal)].legal:
            continue
        if item.phase != "admitted":
            continue
        updated = _replace_issue(updated, replace(item, phase="claiming"))
        proposals.append(
            EffectProposal(
                effect_class="claim_issue",
                issue=item.issue,
                expected_authorities=(item.current_authority,),
            )
        )
    return updated, tuple(proposals)


@dataclass(frozen=True)
class EffectIdentity:
    """The derived canonical identity of one proposed effect."""

    input_hash: str
    idempotency_key: str
    outcome_keys: tuple[str, ...]


def proposal_effect_identity(
    state: DeliveryRunState,
    proposal: EffectProposal,
) -> EffectIdentity:
    """Derive the canonical identity of one proposal.

    :func:`materialize_effect` uses this same derivation, so the ledger the
    reducer writes and the canonical effect an executor receives can never name
    different identities for the same decision.
    """

    outcome_keys = delivery_effect_expected_outcome_keys(
        effect_class=proposal.effect_class,
        run_id=state.run_id,
        issue=proposal.issue,
        pull_request_number=proposal.pull_request_number,
        required_check_names=state.required_check_names,
        known_defect_registry_ref=proposal.known_defect_registry_ref,
        known_defect_finding_hash=proposal.known_defect_finding_hash,
    )
    input_hash = delivery_effect_input_hash(
        run_id=state.run_id,
        plan_ref=state.plan_ref,
        effect_class=proposal.effect_class,
        issue=proposal.issue,
        pull_request_number=proposal.pull_request_number,
        exact_head_sha=proposal.exact_head_sha,
        expected_authorities=proposal.expected_authorities,
        expected_outcome_keys=outcome_keys,
        known_defect_registry_ref=proposal.known_defect_registry_ref,
        known_defect_finding_hash=proposal.known_defect_finding_hash,
    )
    return EffectIdentity(
        input_hash=input_hash,
        idempotency_key=delivery_effect_idempotency_key(input_hash),
        outcome_keys=outcome_keys,
    )


def _record_authorizations(
    state: DeliveryRunState,
    issues: tuple[IssueRunState, ...],
    proposals: tuple[EffectProposal, ...],
) -> tuple[IssueRunState, ...]:
    """Ledger every proposed effect the moment the reducer authorizes it.

    Recording at authorization rather than at acknowledgement is what makes
    cancellation honest: an effect whose outcome never arrived is an unknown
    external state that reconciliation must resolve, not an effect that can be
    assumed never to have happened.
    """

    updated = issues
    for proposal in proposals:
        issue_state = next(
            (
                item
                for item in updated
                if item.issue.scope_key == proposal.issue.scope_key
            ),
            None,
        )
        if issue_state is None:
            continue
        identity = proposal_effect_identity(state, proposal)
        existing = next(
            (
                entry
                for entry in issue_state.effect_ledger
                if entry.idempotency_key == identity.idempotency_key
            ),
            None,
        )
        if existing is not None and not existing.is_resolved_uncommitted:
            continue
        # Re-authorizing a key whose previous attempt truthfully failed reopens
        # that entry. Leaving it resolved would let a genuinely in-flight effect
        # inherit the earlier failure and vanish from cancellation obligations.
        entry = EffectLedgerEntry(
            effect_class=proposal.effect_class,
            idempotency_key=identity.idempotency_key,
            outcome_keys=identity.outcome_keys,
            proposal=proposal,
        )
        updated = _replace_issue(
            updated,
            replace(
                issue_state,
                effect_ledger=tuple(
                    sorted(
                        (
                            *(
                                item
                                for item in issue_state.effect_ledger
                                if item.idempotency_key != entry.idempotency_key
                            ),
                            entry,
                        ),
                        key=lambda item: item.idempotency_key,
                    )
                ),
            ),
        )
    return updated


def _advance(
    state: DeliveryRunState,
    admitted: AdmittedEvent,
    issues: tuple[IssueRunState, ...],
    effects: tuple[EffectProposal, ...] = (),
) -> Reduction:
    return Reduction(
        state=replace(
            state,
            version=state.version + 1,
            issues=_record_authorizations(state, issues, effects),
            seen_event_ids=tuple(
                sorted({*state.seen_event_ids, admitted.event.event_id})
            ),
        ),
        effects=effects,
    )


def _refuse(state: DeliveryRunState, reason: RefusalReason) -> Reduction:
    return Reduction(state=state, refusal=reason)


def reduce_delivery_run(
    state: DeliveryRunState,
    admitted: AdmittedEvent,
) -> Reduction:
    """Advance one delivery run by exactly one admitted canonical event.

    The function is pure and total: every (phase, signal) pair resolves through
    :data:`REDUCER_TRANSITION_MATRIX`, and any pair the matrix refuses returns
    the unchanged state with a typed refusal reason.
    """

    event = admitted.event
    if event.run_id != state.run_id:
        return _refuse(state, "foreign_run")
    # The lifecycle gate dominates: a terminated or paused run refuses every
    # event, including one it has already seen, so a replay can never look like
    # ordinary de-duplication on a run that is no longer advancing.
    if state.lifecycle in {"cancelled", "superseded"}:
        return _refuse(state, "terminal_run")
    if state.lifecycle == "paused":
        return _refuse(state, "paused_run")
    if event.event_id in state.seen_event_ids:
        return _refuse(state, "duplicate_event")
    if event.plan_ref != state.plan_ref:
        return _refuse(state, "stale_plan_binding")

    if admitted.signal in {"run_started", "timer_elapsed"}:
        return _reduce_tick(state, admitted)
    if admitted.signal == "exception_recorded":
        return _reduce_exception(state, admitted)

    issue = admitted.subject_issue
    if issue is None:
        return _refuse(state, "illegal_transition")
    issue_state = state.issue_state(issue.scope_key)
    if issue_state is None:
        return _refuse(state, "foreign_run")
    if not REDUCER_TRANSITION_MATRIX[(issue_state.phase, admitted.signal)].legal:
        return _refuse(state, "illegal_transition")
    # An effect-outcome event may only report on an effect this run actually
    # authorized. Without this gate an adapter could report success for a
    # launch, merge, or closure the reducer never emitted, and the reducer would
    # bind that foreign identity as its own.
    if admitted.effect is not None and not _is_authorized_effect(
        issue_state, admitted.effect
    ):
        return _refuse(state, "unauthorized_effect")
    return _ISSUE_HANDLERS[admitted.signal](state, admitted, issue_state)


def _is_authorized_effect(
    issue_state: IssueRunState,
    effect: ReducerEffect,
) -> bool:
    """True when this run ledgered the exact effect identity being reported."""

    return any(
        entry.idempotency_key == effect.idempotency_key
        and entry.effect_class == effect.effect_class
        for entry in issue_state.effect_ledger
    )


def _reduce_tick(
    state: DeliveryRunState,
    admitted: AdmittedEvent,
) -> Reduction:
    issues, proposals = _open_due_claims(state.issues, admitted.signal)
    return _advance(state, admitted, issues, proposals)


def _reduce_exception(
    state: DeliveryRunState,
    admitted: AdmittedEvent,
) -> Reduction:
    exception = admitted.event.exception
    assert exception is not None
    if exception.kind in _OWNER_DECISION_EXCEPTIONS:
        target: RunPhase = "owner_decision"
    elif exception.kind in _SYSTEM_BLOCK_EXCEPTIONS:
        target = "system_blocked"
    else:
        target = "blocked"
    issues = tuple(
        item
        if not REDUCER_TRANSITION_MATRIX[(item.phase, "exception_recorded")].legal
        else replace(item, phase=target, blocked_reason=exception.kind)
        for item in state.issues
    )
    return _advance(state, admitted, issues)


def _committed(
    issue_state: IssueRunState,
    admitted: AdmittedEvent,
) -> tuple[EffectLedgerEntry, ...]:
    """Resolve the ledger entry for the effect this event reports on."""

    effect = admitted.effect
    outcome = admitted.event.effect_outcome
    if effect is None or outcome is None:
        return issue_state.effect_ledger
    authorized = next(
        (
            entry
            for entry in issue_state.effect_ledger
            if entry.idempotency_key == effect.idempotency_key
        ),
        None,
    )
    record = EffectLedgerEntry(
        effect_class=effect.effect_class,
        idempotency_key=effect.idempotency_key,
        outcome_keys=tuple(outcome.outcome_keys),
        outcome_state=outcome.outcome_state,
        proposal=authorized.proposal if authorized is not None else None,
    )
    remaining = tuple(
        item
        for item in issue_state.effect_ledger
        if item.idempotency_key != record.idempotency_key
    )
    return tuple(
        sorted(
            (*remaining, record),
            key=lambda item: item.idempotency_key,
        )
    )


def _authority_of(
    admitted: AdmittedEvent,
    issue_state: IssueRunState,
) -> AuthoritySnapshot:
    return admitted.event.subject_authority or issue_state.current_authority


def _authorized_target_matches(
    issue_state: IssueRunState,
    admitted: AdmittedEvent,
) -> bool:
    effect = admitted.effect
    if effect is None:
        return False
    return (
        effect.exact_head_sha == issue_state.authorized_head_sha
        and effect.pull_request_number == issue_state.authorized_pull_request
    )


def _reduce_claim_succeeded(
    state: DeliveryRunState,
    admitted: AdmittedEvent,
    issue_state: IssueRunState,
) -> Reduction:
    authority = _authority_of(admitted, issue_state)
    updated = replace(
        issue_state,
        phase="launching",
        current_authority=authority,
        effect_ledger=_committed(issue_state, admitted),
    )
    proposal = EffectProposal(
        effect_class="launch_worker",
        issue=issue_state.issue,
        expected_authorities=(authority,),
    )
    return _advance(
        state, admitted, _replace_issue(state.issues, updated), (proposal,)
    )


def _reduce_worker_launched(
    state: DeliveryRunState,
    admitted: AdmittedEvent,
    issue_state: IssueRunState,
) -> Reduction:
    assert admitted.effect is not None
    updated = replace(
        issue_state,
        phase="working",
        current_authority=_authority_of(admitted, issue_state),
        authorized_invocation_effect_key=admitted.effect.idempotency_key,
        effect_ledger=_committed(issue_state, admitted),
    )
    return _advance(state, admitted, _replace_issue(state.issues, updated))


def _reduce_worker_result(
    state: DeliveryRunState,
    admitted: AdmittedEvent,
    issue_state: IssueRunState,
) -> Reduction:
    result = admitted.worker_result
    assert result is not None
    # working is reachable only through a committed launch, so a
    # result must name the exact launch effect this run authorized. Treating an
    # unset key as permissive would leave a hole rather than a defensive branch.
    if (
        issue_state.authorized_invocation_effect_key is None
        or result.effect_ref.contract_id
        != issue_state.authorized_invocation_effect_key
    ):
        return _refuse(state, "illegal_transition")
    domain = result.delivery_result
    if domain.status != "completed":
        updated = replace(
            issue_state,
            phase="blocked",
            blocked_reason=f"worker_{domain.status}",
        )
        return _advance(state, admitted, _replace_issue(state.issues, updated))
    if result.exact_head_sha is None or result.pull_request_number is None:
        return _refuse(state, "head_evidence_conflict")
    if (
        issue_state.authorized_pull_request is not None
        and result.pull_request_number != issue_state.authorized_pull_request
    ):
        # A repair round may produce a new head, but it can never move the run
        # to a different pull request: the reducer-authorized PR identity is
        # bound on first admission and is not rewritable by later evidence.
        return _refuse(state, "pull_request_identity_conflict")
    head_changed = result.exact_head_sha != issue_state.authorized_head_sha
    evidence = (
        tuple(
            kind
            for kind in issue_state.acceptance_evidence
            if kind not in _HEAD_BOUND_EVIDENCE
        )
        if head_changed
        else issue_state.acceptance_evidence
    )
    authority = _authority_of(admitted, issue_state)
    updated = replace(
        issue_state,
        phase="awaiting_ci",
        authorized_pull_request=result.pull_request_number,
        authorized_head_sha=result.exact_head_sha,
        acceptance_evidence=evidence,
        current_authority=authority,
    )
    proposal = EffectProposal(
        effect_class="await_ci",
        issue=issue_state.issue,
        expected_authorities=(authority,),
        pull_request_number=result.pull_request_number,
        exact_head_sha=result.exact_head_sha,
    )
    return _advance(
        state, admitted, _replace_issue(state.issues, updated), (proposal,)
    )


def _reduce_checks_passed(
    state: DeliveryRunState,
    admitted: AdmittedEvent,
    issue_state: IssueRunState,
) -> Reduction:
    if not _authorized_target_matches(issue_state, admitted):
        return _refuse(state, "head_evidence_conflict")
    authority = _authority_of(admitted, issue_state)
    updated = replace(
        issue_state,
        phase="awaiting_review",
        acceptance_evidence=_with_evidence(issue_state, *_effect_evidence(admitted)),
        effect_ledger=_committed(issue_state, admitted),
        current_authority=authority,
    )
    proposal = EffectProposal(
        effect_class="request_review",
        issue=issue_state.issue,
        expected_authorities=(authority,),
        pull_request_number=issue_state.authorized_pull_request,
        exact_head_sha=issue_state.authorized_head_sha,
    )
    return _advance(
        state, admitted, _replace_issue(state.issues, updated), (proposal,)
    )


def _reduce_review_recorded(
    state: DeliveryRunState,
    admitted: AdmittedEvent,
    issue_state: IssueRunState,
) -> Reduction:
    if not _authorized_target_matches(issue_state, admitted):
        return _refuse(state, "head_evidence_conflict")
    updated = replace(
        issue_state,
        effect_ledger=_committed(issue_state, admitted),
        current_authority=_authority_of(admitted, issue_state),
    )
    return _advance(state, admitted, _replace_issue(state.issues, updated))


def _reduce_review_result(
    state: DeliveryRunState,
    admitted: AdmittedEvent,
    issue_state: IssueRunState,
) -> Reduction:
    review = admitted.review_result
    assert review is not None
    if review.pull_request_number != issue_state.authorized_pull_request:
        return _refuse(state, "pull_request_identity_conflict")
    if review.exact_head_sha != issue_state.authorized_head_sha:
        return _refuse(state, "head_evidence_conflict")
    authority = _authority_of(admitted, issue_state)
    blocking = any(
        finding.severity in {"P0", "P1"}
        or finding.protected_risk
        or finding.false_green
        for finding in review.findings
    )
    if review.disposition == "reject" or blocking:
        # INV-DDO-8: P0/P1, protected risk, false-green, malformed, and
        # low-confidence verdicts block. Repairing a blocking verdict is
        # governed work outside this reducer, not a transition it may take.
        updated = replace(
            issue_state,
            phase="blocked",
            blocked_reason="review_blocking",
            current_authority=authority,
        )
        return _advance(state, admitted, _replace_issue(state.issues, updated))
    if review.disposition == "accept":
        updated = replace(
            issue_state,
            phase="merging",
            acceptance_evidence=_with_evidence(issue_state, "review_accepted"),
            current_authority=authority,
        )
        proposal = EffectProposal(
            effect_class="merge_pull_request",
            issue=issue_state.issue,
            expected_authorities=(authority,),
            pull_request_number=issue_state.authorized_pull_request,
            exact_head_sha=issue_state.authorized_head_sha,
        )
        return _advance(
            state, admitted, _replace_issue(state.issues, updated), (proposal,)
        )

    # accept_with_risk: exactly one deferred P2 disposition, no synchronous
    # repair, and no merge authorization until the durable write is observed.
    deferred = tuple(
        finding for finding in review.findings if finding.severity == "P2"
    )
    if len(deferred) != 1 or len(review.known_defect_refs) != 1:
        updated = replace(
            issue_state,
            phase="blocked",
            blocked_reason="review_disposition_not_one_deferred_p2",
            current_authority=authority,
        )
        return _advance(state, admitted, _replace_issue(state.issues, updated))
    finding_hash = canonical_hash(deferred[0])
    updated = replace(
        issue_state,
        phase="recording_defect",
        acceptance_evidence=_with_evidence(issue_state, "review_accepted"),
        pending_known_defect_ref=review.known_defect_refs[0],
        pending_known_defect_finding_hash=finding_hash,
        current_authority=authority,
    )
    proposal = EffectProposal(
        effect_class="record_known_defect",
        issue=issue_state.issue,
        expected_authorities=(authority,),
        pull_request_number=issue_state.authorized_pull_request,
        exact_head_sha=issue_state.authorized_head_sha,
        known_defect_registry_ref=review.known_defect_refs[0],
        known_defect_finding_hash=finding_hash,
    )
    return _advance(
        state, admitted, _replace_issue(state.issues, updated), (proposal,)
    )


def _reduce_known_defect_recorded(
    state: DeliveryRunState,
    admitted: AdmittedEvent,
    issue_state: IssueRunState,
) -> Reduction:
    if not _authorized_target_matches(issue_state, admitted):
        return _refuse(state, "head_evidence_conflict")
    effect = admitted.effect
    assert effect is not None
    if (
        effect.known_defect_registry_ref != issue_state.pending_known_defect_ref
        or effect.known_defect_finding_hash
        != issue_state.pending_known_defect_finding_hash
    ):
        return _refuse(state, "illegal_transition")
    authority = _authority_of(admitted, issue_state)
    updated = replace(
        issue_state,
        phase="merging",
        acceptance_evidence=_with_evidence(issue_state, *_effect_evidence(admitted)),
        effect_ledger=_committed(issue_state, admitted),
        current_authority=authority,
    )
    proposal = EffectProposal(
        effect_class="merge_pull_request",
        issue=issue_state.issue,
        expected_authorities=(authority,),
        pull_request_number=issue_state.authorized_pull_request,
        exact_head_sha=issue_state.authorized_head_sha,
    )
    return _advance(
        state, admitted, _replace_issue(state.issues, updated), (proposal,)
    )


def _reduce_merge_succeeded(
    state: DeliveryRunState,
    admitted: AdmittedEvent,
    issue_state: IssueRunState,
) -> Reduction:
    if not _authorized_target_matches(issue_state, admitted):
        return _refuse(state, "head_evidence_conflict")
    authority = _authority_of(admitted, issue_state)
    updated = replace(
        issue_state,
        phase="closing",
        acceptance_evidence=_with_evidence(issue_state, *_effect_evidence(admitted)),
        effect_ledger=_committed(issue_state, admitted),
        current_authority=authority,
    )
    proposal = EffectProposal(
        effect_class="close_issue",
        issue=issue_state.issue,
        expected_authorities=(authority,),
        pull_request_number=issue_state.authorized_pull_request,
        exact_head_sha=issue_state.authorized_head_sha,
    )
    return _advance(
        state, admitted, _replace_issue(state.issues, updated), (proposal,)
    )


def _reduce_closure_succeeded(
    state: DeliveryRunState,
    admitted: AdmittedEvent,
    issue_state: IssueRunState,
) -> Reduction:
    if not _authorized_target_matches(issue_state, admitted):
        return _refuse(state, "head_evidence_conflict")
    authority = _authority_of(admitted, issue_state)
    updated = replace(
        issue_state,
        phase="recording_receipt",
        acceptance_evidence=_with_evidence(issue_state, *_effect_evidence(admitted)),
        effect_ledger=_committed(issue_state, admitted),
        current_authority=authority,
    )
    proposal = EffectProposal(
        effect_class="record_delivery_receipt",
        issue=issue_state.issue,
        expected_authorities=(authority,),
        pull_request_number=issue_state.authorized_pull_request,
        exact_head_sha=issue_state.authorized_head_sha,
    )
    return _advance(
        state, admitted, _replace_issue(state.issues, updated), (proposal,)
    )


def _reduce_receipt_recorded(
    state: DeliveryRunState,
    admitted: AdmittedEvent,
    issue_state: IssueRunState,
) -> Reduction:
    if not _authorized_target_matches(issue_state, admitted):
        return _refuse(state, "head_evidence_conflict")
    committed = _committed(issue_state, admitted)
    observed = frozenset(
        _with_evidence(issue_state, *_effect_evidence(admitted))
    )
    unmet = tuple(
        kind
        for kind in state.required_acceptance_evidence
        if kind not in observed
    )
    if unmet:
        # The receipt effect succeeding is not delivery. Terminality follows the
        # bound acceptance profile, so a run that never proved every required
        # lower-level fact fails closed instead of recording a clean receipt.
        updated = replace(
            issue_state,
            phase="blocked",
            blocked_reason="acceptance_evidence_unmet:" + ",".join(unmet),
            effect_ledger=committed,
            acceptance_evidence=tuple(sorted(observed)),
            current_authority=_authority_of(admitted, issue_state),
        )
        return _advance(state, admitted, _replace_issue(state.issues, updated))
    updated = replace(
        issue_state,
        phase="delivered",
        effect_ledger=committed,
        acceptance_evidence=tuple(sorted(observed)),
        current_authority=_authority_of(admitted, issue_state),
    )
    # Completing the last Issue of a wave opens the next wave's Issues for
    # claiming, but the claim effect itself is not proposed here. A delivered
    # reducer effect must bind the subject authority of its causal event, and
    # this event's subject is the Issue that just closed - never the next wave's
    # Issue. The next subjectless timer tick is therefore the only legitimate
    # cause, and it involves no coordinator turn or model decision.
    return _advance(state, admitted, _replace_issue(state.issues, updated))


def _reduce_effect_failed(
    state: DeliveryRunState,
    admitted: AdmittedEvent,
    issue_state: IssueRunState,
) -> Reduction:
    effect = admitted.effect
    assert effect is not None
    # A failure report about a pull request or head this run does not currently
    # authorize is stale evidence, exactly as a success report would be. Without
    # this fence a late failure could regress an already-reviewed run and burn a
    # repair round against evidence for a superseded head.
    if effect.pull_request_number is not None and not _authorized_target_matches(
        issue_state, admitted
    ):
        return _refuse(state, "head_evidence_conflict")
    authority = _authority_of(admitted, issue_state)
    ledger = _committed(issue_state, admitted)
    # Only the check the run is currently awaiting defers to repair. A late
    # failure report for an effect the run already moved past is still refused
    # evidence, not a reason to reopen a merged or closed Issue.
    if effect.effect_class != "await_ci" or issue_state.phase != "awaiting_ci":
        updated = replace(
            issue_state,
            phase="blocked",
            blocked_reason=f"effect_failed:{effect.effect_class}",
            effect_ledger=ledger,
            current_authority=authority,
        )
        return _advance(state, admitted, _replace_issue(state.issues, updated))
    # A red required check routes to the typed terminal `repairing` deferral, not
    # to an autonomous retry loop.
    #
    # An autonomous retry needs a durable, replayable effect and invocation
    # identity: `ReducerEffect.content_hash` binds the causal event and
    # provenance, and `WorkerInvocation` binds the effect reference, so an effect
    # re-derived on a later tick or after a restart yields a different start-once
    # identity and could start a second worker against the same Issue. Making
    # that safe requires persisting and replaying the authorized effect, which is
    # durable effect binding - DDO-05 (#4168), and named Out of Scope for this
    # slice. Deferring is therefore fail-closed and honest; the retry loop lands
    # with the durability that makes it correct.
    updated = replace(
        issue_state,
        phase="repairing",
        blocked_reason="ci_failed_repair_deferred",
        acceptance_evidence=tuple(
            kind
            for kind in issue_state.acceptance_evidence
            if kind not in _HEAD_BOUND_EVIDENCE
        ),
        effect_ledger=ledger,
        current_authority=authority,
    )
    return _advance(state, admitted, _replace_issue(state.issues, updated))


def _reduce_authority_changed(
    state: DeliveryRunState,
    admitted: AdmittedEvent,
    issue_state: IssueRunState,
) -> Reduction:
    observed = admitted.event.subject_authority
    assert observed is not None
    if observed.content_hash != issue_state.issue.contract_hash:
        # The Issue contract itself moved under the run. No deterministic rule
        # may resolve that, so it is an owner decision rather than a block.
        updated = replace(
            issue_state,
            phase="owner_decision",
            blocked_reason="authority_contract_drift",
        )
        return _advance(state, admitted, _replace_issue(state.issues, updated))
    updated = replace(issue_state, current_authority=observed)
    return _advance(state, admitted, _replace_issue(state.issues, updated))


_IssueHandler = Callable[
    [DeliveryRunState, AdmittedEvent, IssueRunState], Reduction
]

_ISSUE_HANDLERS: Final[dict[ReducerSignal, _IssueHandler]] = {
    "claim_succeeded": _reduce_claim_succeeded,
    "worker_launched": _reduce_worker_launched,
    "worker_result_recorded": _reduce_worker_result,
    "checks_passed": _reduce_checks_passed,
    "review_recorded": _reduce_review_recorded,
    "review_result_recorded": _reduce_review_result,
    "known_defect_recorded": _reduce_known_defect_recorded,
    "merge_succeeded": _reduce_merge_succeeded,
    "closure_succeeded": _reduce_closure_succeeded,
    "receipt_recorded": _reduce_receipt_recorded,
    "effect_failed": _reduce_effect_failed,
    "authority_changed": _reduce_authority_changed,
}


def outstanding_effect_obligations(
    state: DeliveryRunState,
) -> tuple[OutstandingEffectObligation, ...]:
    """Return every effect this run authorized and will not attempt to undo.

    Both committed and unknown-outcome effects are reported. An effect the
    reducer authorized but never saw acknowledged may already have removed
    ``agent:ready``, taken a dispatcher lease, or opened a pull request, so
    omitting it would let a cancelled run assert that nothing is outstanding
    while live pickup authority is orphaned. Only an effect whose truthful
    failure proved the guarded authority unchanged is excluded.
    """

    records = {
        item.idempotency_key: item
        for issue_state in state.issues
        for item in issue_state.unreconciled_effects
    }
    return tuple(
        OutstandingEffectObligation(
            effect_class=record.effect_class,
            effect_idempotency_key=record.idempotency_key,
            outcome_keys=tuple(sorted(record.outcome_keys)),
            last_observed_outcome_state=record.outcome_state,
        )
        for _, record in sorted(records.items())
    )


#: Phases whose pending effect a resume may safely re-propose. ``launching`` is
#: deliberately absent: a re-derived launch keeps its idempotency key but not its
#: content hash, and ``WorkerInvocation`` binds the effect *reference*, so
#: re-proposing an in-flight launch would mint a second start-once identity and
#: could start a second worker on one Issue. Every class listed here is
#: identified purely by its idempotency key downstream, so a re-proposal
#: collapses to one logical effect. Replaying an in-flight launch safely needs
#: durable effect binding - DDO-05 (#4168) and #4466.
_RESUMABLE_EFFECT_BY_PHASE: Final[dict[RunPhase, EffectClass]] = {
    "claiming": "claim_issue",
    "awaiting_ci": "await_ci",
    "awaiting_review": "request_review",
    "recording_defect": "record_known_defect",
    "merging": "merge_pull_request",
    "closing": "close_issue",
    "recording_receipt": "record_delivery_receipt",
}


def pending_effect_proposals(
    state: DeliveryRunState,
) -> tuple[EffectProposal, ...]:
    """Return the effects a resumed run is still waiting on.

    Resume continues the gate the run was actually paused at. It never resets a
    run to claiming, so an already-committed claim or worker launch is not
    repeated. Where an effect is re-proposed its semantic idempotency key is
    unchanged, so execution collapses to one logical effect.
    """

    open_wave = _open_wave_index(state.issues)
    proposals: list[EffectProposal] = []
    for item in state.issues:
        if item.phase in TERMINAL_PHASES:
            continue
        if item.phase == "admitted":
            if item.wave_index == open_wave:
                proposals.append(
                    EffectProposal(
                        effect_class="claim_issue",
                        issue=item.issue,
                        expected_authorities=(item.current_authority,),
                    )
                )
            continue
        effect_class = _RESUMABLE_EFFECT_BY_PHASE.get(item.phase)
        if effect_class is None:
            # working waits on an external structured result, and launching
            # waits on its in-flight launch outcome rather than minting a second
            # start-once identity for the same worker.
            continue
        # Replay the exact authorization from the ledger. Re-deriving one from
        # the run's *current* authority would change the semantic input, and a
        # benign relabel between authorization and resume would then split one
        # logical effect into two identities.
        pending = next(
            (
                entry.proposal
                for entry in item.effect_ledger
                if entry.effect_class == effect_class
                and entry.outcome_state is None
                and entry.proposal is not None
            ),
            None,
        )
        if pending is not None:
            proposals.append(pending)
    return tuple(proposals)


def reduce_lifecycle_command(
    state: DeliveryRunState,
    command: LifecycleCommand,
) -> Reduction:
    """Apply one authenticated, version-fenced lifecycle control command.

    No lifecycle command emits a compensating effect. ``cancel`` and
    ``supersede`` terminate the run and return the exact committed-effect
    obligations that BuilderOps reconciliation must resolve, because claiming to
    reverse a committed GitHub, dispatcher, or label effect from here would be a
    false receipt (INV-DDO-15).
    """

    if command.run_id != state.run_id:
        return _refuse(state, "foreign_run")
    if command.command_id in state.seen_command_ids:
        return _refuse(state, "duplicate_command")
    if command.issued_by.authority_scope not in state.authorized_control_scopes:
        return _refuse(state, "unauthorized_command")
    if command.expected_run_version != state.version:
        return _refuse(state, "stale_run_version")
    if state.lifecycle in {"cancelled", "superseded"}:
        return _refuse(state, "terminal_run")
    if command.command == "supersede" and command.superseding_initiation_ref is None:
        return _refuse(state, "unauthorized_command")
    if command.command != "supersede" and command.superseding_initiation_ref is not None:
        return _refuse(state, "unauthorized_command")
    if command.command == "pause" and state.lifecycle != "active":
        return _refuse(state, "illegal_transition")
    if command.command == "resume" and state.lifecycle != "paused":
        return _refuse(state, "illegal_transition")

    seen = tuple(sorted({*state.seen_command_ids, command.command_id}))
    if command.command == "pause":
        # Every Issue phase is preserved verbatim, so resume continues the
        # pending gate instead of re-deriving an earlier one.
        return Reduction(
            state=replace(
                state,
                version=state.version + 1,
                lifecycle="paused",
                seen_command_ids=seen,
            )
        )
    if command.command == "resume":
        resumed = replace(
            state,
            version=state.version + 1,
            lifecycle="active",
            seen_command_ids=seen,
        )
        # Resume is the one path that authorizes effects without reducing an
        # event, so it must ledger them itself. Without this an effect resume
        # authorized would be invisible to cancellation, which is exactly the
        # orphaned-pickup-authority failure the ledger exists to prevent.
        proposals = pending_effect_proposals(resumed)
        return Reduction(
            state=replace(
                resumed,
                issues=_record_authorizations(resumed, resumed.issues, proposals),
            ),
            effects=proposals,
        )

    is_cancel = command.command == "cancel"
    terminal_lifecycle: LifecycleState = "cancelled" if is_cancel else "superseded"
    terminal_phase: RunPhase = "cancelled" if is_cancel else "superseded"
    issues = tuple(
        item
        if item.phase in TERMINAL_PHASES
        else replace(item, phase=terminal_phase, blocked_reason=command.command)
        for item in state.issues
    )
    return Reduction(
        state=replace(
            state,
            version=state.version + 1,
            lifecycle=terminal_lifecycle,
            issues=issues,
            seen_command_ids=seen,
            superseding_initiation_ref=command.superseding_initiation_ref,
        ),
        effects=(),
        obligations=outstanding_effect_obligations(state),
    )


def resolve_terminal_delivery(
    state: DeliveryRunState,
    issue: IssueScope,
    acceptance_profile: DeliveryAcceptanceProfile,
) -> tuple[bool, tuple[AcceptanceEvidenceKind, ...]]:
    """Resolve terminality for one Issue from explicit lower-level evidence.

    Terminality is never inferred from a phase name alone. The bound acceptance
    profile decides, and it decides only from evidence kinds this run observed
    through typed post-effect outcomes and structured verdicts.
    """

    if acceptance_profile.content_hash != state.acceptance_profile_hash:
        raise ValueError(
            "acceptance profile does not match the immutable run binding"
        )
    issue_state = state.issue_state(issue.scope_key)
    if issue_state is None:
        raise ValueError("Issue is outside the run's bound scope")
    unmet = acceptance_profile.unmet_evidence(issue_state.observed_evidence)
    return (not unmet and issue_state.phase == "delivered"), unmet


def materialize_effect(
    proposal: EffectProposal,
    *,
    state: DeliveryRunState,
    plan: DeliveryPlan,
    causal_event: ReducerEvent,
    sequence: int,
    provenance: Provenance,
    prior_effects: Sequence[ReducerEffect] = (),
    prior_events: Sequence[ReducerEvent] = (),
    worker_results: Sequence[StructuredWorkerResult] = (),
    review_results: Sequence[ReviewResult] = (),
) -> ReducerEffect:
    """Turn one proposal into a canonical, re-validated reducer effect.

    Identity, idempotency key, and logical outcome keys all come from the
    delivered derivations, and the finished effect is passed straight back
    through ``validate_reducer_effect_evidence``, so the reducer cannot author an
    effect the contract layer would reject.
    """

    if state.plan_ref.contract_id != plan.plan_id:
        raise ValueError("effect materialization must use the run's bound plan")
    if plan.policy_profile.required_check_names != state.required_check_names:
        raise ValueError(
            "effect materialization must use the run's bound required checks"
        )
    identity = proposal_effect_identity(state, proposal)
    idempotency_key = identity.idempotency_key
    outcome_keys = identity.outcome_keys
    input_hash = identity.input_hash
    effect = ReducerEffect(
        effect_id=idempotency_key,
        run_id=state.run_id,
        plan_ref=state.plan_ref,
        causal_event=causal_event,
        sequence=sequence,
        effect_class=proposal.effect_class,
        issue=proposal.issue,
        pull_request_number=proposal.pull_request_number,
        exact_head_sha=proposal.exact_head_sha,
        expected_authorities=proposal.expected_authorities,
        expected_outcome_keys=outcome_keys,
        known_defect_registry_ref=proposal.known_defect_registry_ref,
        known_defect_finding_hash=proposal.known_defect_finding_hash,
        idempotency_key=idempotency_key,
        input_hash=input_hash,
        provenance=provenance,
    )
    return validate_reducer_effect_evidence(
        effect,
        plan=plan,
        prior_effects=tuple(prior_effects),
        prior_events=tuple(prior_events),
        worker_results=tuple(worker_results),
        review_results=tuple(review_results),
    )


__all__ = [
    "ACTIVE_PHASES",
    "COMPENSATING_EFFECT_CLASSES",
    "REDUCER_SIGNALS",
    "REDUCER_TRANSITION_MATRIX",
    "RUN_PHASES",
    "TERMINAL_PHASES",
    "AdmittedEvent",
    "EffectLedgerEntry",
    "DeliveryRunState",
    "EffectIdentity",
    "EffectProposal",
    "IssueRunState",
    "LifecycleCommand",
    "LifecycleState",
    "ReducerAdmissionError",
    "ReducerSignal",
    "Reduction",
    "RefusalReason",
    "RunPhase",
    "TransitionRule",
    "admit_reducer_event",
    "initial_delivery_run_state",
    "materialize_effect",
    "outstanding_effect_obligations",
    "proposal_effect_identity",
    "pending_effect_proposals",
    "reduce_delivery_run",
    "reduce_lifecycle_command",
    "replay_delivery_sidecar",
    "resolve_terminal_delivery",
]
