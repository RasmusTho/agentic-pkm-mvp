"""Fail-closed execution seam for ``ygg.operation.v1`` effects.

The kernel deliberately owns only admission, idempotency, and durable receipt
bookkeeping.  It never implements a domain mutation: each admitted operation
is dispatched once to its registered owner-native handler.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from contextlib import contextmanager
import fcntl
from hashlib import sha256
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import RLock
from time import time
from typing import Any, Callable, Iterator, Mapping, Protocol

from app.archival.contracts import ArtifactClass, LivenessState, PolicyProfile, TransitionStage

from .contracts import (
    ConvergenceState,
    OperationItemOutcome,
    OperationConvergence,
    OperationOutcome,
    OperationReceipt,
    OperationRequest,
    OperationStatus,
    ReceiptStatus,
    SourceEffectStatus,
)


@dataclass(frozen=True)
class PolicyDecision:
    """The minimal policy result needed by the execution boundary."""

    admitted: bool
    policy_version: str
    reason: str | None = None
    decision_token: str | None = None

    @classmethod
    def allowed(
        cls, policy_version: str, decision_token: str = "verified-token"
    ) -> "PolicyDecision":
        return cls(True, policy_version, decision_token=decision_token)

    @classmethod
    def denied(cls, policy_version: str, reason: str) -> "PolicyDecision":
        return cls(False, policy_version, reason)


@dataclass(frozen=True)
class OwnerExecutionResult:
    """Owner-native effect state; ambiguous states are never acknowledged."""

    status: OperationStatus
    items: tuple[Mapping[str, Any], ...] = ()
    warnings: tuple[str, ...] = ()
    effect_id: str | None = None
    effect_receipt: Mapping[str, Any] | None = None
    convergence: OperationConvergence | None = None

    @classmethod
    def succeeded(
        cls,
        *,
        items: tuple[Mapping[str, Any], ...] = (),
        effect_id: str | None = None,
        effect_receipt: Mapping[str, Any] | None = None,
    ) -> "OwnerExecutionResult":
        return cls(
            OperationStatus.SUCCEEDED,
            items,
            effect_id=effect_id,
            effect_receipt=effect_receipt,
        )

    @classmethod
    def ambiguous(cls) -> "OwnerExecutionResult":
        return cls(
            OperationStatus.RECOVERY_REQUIRED,
            warnings=("owner outcome requires receipt reconciliation",),
        )

    @classmethod
    def failed(cls, warning: str) -> "OwnerExecutionResult":
        return cls(OperationStatus.NOT_ACKNOWLEDGED, warnings=(warning,))


@dataclass(frozen=True)
class ArchivalOperationReceipt:
    """Small, redacted projection of an already validated GAF receipt."""

    artifact_ref: str
    receipt_ref: str
    generation: int
    artifact_class: ArtifactClass
    policy: PolicyProfile
    stage: TransitionStage
    liveness: LivenessState
    recovery_ref: str | None = None

    def __post_init__(self) -> None:
        if type(self.generation) is not int or self.generation < 0:
            raise ValueError("archival receipt generation must be a non-negative integer")
        for value in (self.artifact_ref, self.receipt_ref, self.recovery_ref):
            if value is not None and (not isinstance(value, str) or not value or "/" in value or "\\" in value):
                raise ValueError("archival receipt references must be opaque tokens")

    def to_dict(self) -> dict[str, Any]:
        return {"artifact_ref": self.artifact_ref, "receipt_ref": self.receipt_ref, "generation": self.generation, "artifact_class": self.artifact_class.value, "policy": self.policy.value, "stage": self.stage.value, "liveness": self.liveness.value, "recovery_ref": self.recovery_ref}


@dataclass(frozen=True)
class _StoredOutcome:
    intent_digest: str
    outcome: OperationOutcome
    in_flight: bool = False


class ReceiptStore(Protocol):
    def lookup(self, request_id: str) -> _StoredOutcome | None: ...
    def reserve(
        self, request_id: str, intent_digest: str, pending: OperationOutcome
    ) -> tuple[str, _StoredOutcome]: ...

    def finalize(self, request_id: str, intent_digest: str, outcome: OperationOutcome) -> None: ...


class InMemoryReceiptStore:
    """Test/local store with the same replay semantics as the JSON store."""

    def __init__(self) -> None:
        self._records: dict[str, _StoredOutcome] = {}
        self._lock = RLock()

    def reserve(
        self, request_id: str, intent_digest: str, pending: OperationOutcome
    ) -> tuple[str, _StoredOutcome]:
        with self._lock:
            prior = self._records.get(request_id)
            if prior is not None:
                return ("conflict" if prior.intent_digest != intent_digest else "replay"), prior
            stored = _StoredOutcome(intent_digest, pending, in_flight=True)
            self._records[request_id] = stored
            return "reserved", stored

    def lookup(self, request_id: str) -> _StoredOutcome | None:
        with self._lock:
            return self._records.get(request_id)

    def finalize(self, request_id: str, intent_digest: str, outcome: OperationOutcome) -> None:
        with self._lock:
            self._records[request_id] = _StoredOutcome(intent_digest, outcome)


class JsonReceiptStore:
    """Small atomic receipt ledger; it persists redacted outcomes only.

    A companion lock file serializes reservation across processes.  A crash
    after reservation intentionally leaves an in-flight record, which the
    kernel exposes as recovery-required rather than re-running the effect.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = RLock()

    def reserve(
        self, request_id: str, intent_digest: str, pending: OperationOutcome
    ) -> tuple[str, _StoredOutcome]:
        with self._lock:
            with self._process_lock():
                records = self._read()
                prior = records.get(request_id)
                if prior is not None:
                    return ("conflict" if prior.intent_digest != intent_digest else "replay"), prior
                stored = _StoredOutcome(intent_digest, pending, in_flight=True)
                records[request_id] = stored
                self._write(records)
                return "reserved", stored

    def lookup(self, request_id: str) -> _StoredOutcome | None:
        with self._lock:
            with self._process_lock():
                return self._read().get(request_id)

    def finalize(self, request_id: str, intent_digest: str, outcome: OperationOutcome) -> None:
        with self._lock:
            with self._process_lock():
                records = self._read()
                records[request_id] = _StoredOutcome(intent_digest, outcome)
                self._write(records)

    @contextmanager
    def batch_window(self, batch_id: str, *, running: bool = False) -> Iterator[None]:
        """Bounded AUTOOPS-08 snapshot/run exclusion; no domain or retry authority.

        The run fence is independent of snapshot exclusion, so cancellation can
        persist while an already-started owner holds its own effect window.
        Process loss releases both fences without guessing whether an effect ran.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        identity = sha256(batch_id.encode()).hexdigest()
        suffix = "run" if running else "state"
        with (self.path.parent / f".{self.path.name}.batch-{identity}.{suffix}.lock").open(
            "a+", encoding="utf-8"
        ) as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    @contextmanager
    def effect_window(self, request_id: str) -> Iterator[None]:
        """Serialize one batch effect and its recovery, including across batches.

        The global journal lock is never held through owner work/cancellation.
        Process loss releases this fence; the durable UNKNOWN attempt remains.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        identity = sha256(request_id.encode()).hexdigest()
        with (self.path.parent / f".{self.path.name}.effect-{identity}.lock").open(
            "a+", encoding="utf-8"
        ) as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    @contextmanager
    def _process_lock(self) -> Iterator[None]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with (self.path.parent / f".{self.path.name}.lock").open(
            "a+", encoding="utf-8"
        ) as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _read(self) -> dict[str, _StoredOutcome]:
        if not self.path.exists():
            return {}
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        return {
            request_id: _StoredOutcome(
                value["intent_digest"],
                OperationOutcome.from_dict(value["outcome"]),
                bool(value.get("in_flight", False)),
            )
            for request_id, value in raw.items()
        }

    def _write(self, records: Mapping[str, _StoredOutcome]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            request_id: {
                "intent_digest": record.intent_digest,
                "outcome": record.outcome.to_dict(),
                "in_flight": record.in_flight,
            }
            for request_id, record in records.items()
        }
        with NamedTemporaryFile(
            "w", encoding="utf-8", dir=self.path.parent, delete=False
        ) as temporary:
            json.dump(payload, temporary, sort_keys=True, separators=(",", ":"))
            temporary.flush()
            os.fsync(temporary.fileno())
            Path(temporary.name).replace(self.path)
        directory = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)


ContextResolver = Callable[[OperationRequest], bool]
PolicyEvaluator = Callable[[OperationRequest, Mapping[str, Any]], PolicyDecision]
VersionChecker = Callable[[OperationRequest], bool]
TokenValidator = Callable[[OperationRequest, PolicyDecision], bool]
OwnerHandler = Callable[[OperationRequest], OwnerExecutionResult]


@dataclass
class OperationExecutionKernel:
    """Execute one bounded, owner-native operation after every admission gate."""

    context_resolver: Callable[[Any], bool]
    policy_evaluator: PolicyEvaluator
    handlers: Mapping[str, OwnerHandler]
    receipt_store: ReceiptStore
    version_checker: VersionChecker = field(
        default=lambda request: request.expected_version is None
    )
    token_validator: TokenValidator = field(default=lambda request, decision: False)

    def execute(
        self, request: OperationRequest, delegation: Mapping[str, Any] | None = None,
        *, reconcile: OwnerHandler | None = None, bind_owner_delegation: bool = False,
    ) -> OperationOutcome:
        if isinstance(self.receipt_store, JsonReceiptStore) and (bind_owner_delegation or reconcile is not None):
            # One existing-journal effect fence spans initial reservation,
            # owner work and finalization as well as recovery. A waiter reads
            # the current record only after the prior invocation has exited.
            with self.receipt_store.effect_window(request.request_id):
                return self._execute(request, delegation, reconcile=reconcile,
                                     bind_owner_delegation=bind_owner_delegation)
        return self._execute(request, delegation, reconcile=reconcile,
                             bind_owner_delegation=bind_owner_delegation)

    def _execute(
        self, request: OperationRequest, delegation: Mapping[str, Any] | None = None,
        *, reconcile: OwnerHandler | None = None, bind_owner_delegation: bool = False,
    ) -> OperationOutcome:
        delegation = delegation if delegation is not None else request.delegation
        if delegation is None:
            return self._outcome(
                request, OperationStatus.REJECTED, warnings=("bounded delegation is required",)
            )
        request = _with_delegated_batch_policy(request, delegation)
        intent_digest = _intent_digest(request, delegation)
        # Opt-in batch composition hands the original immutable ceiling to the
        # native owner's final checks. Historical single-operation inputs and
        # replay digests retain their default semantics.
        owner_request = replace(request, delegation=dict(delegation)) if bind_owner_delegation else request
        try:
            prior = self.receipt_store.lookup(request.request_id)
        except Exception:
            return self._outcome(
                request,
                OperationStatus.RECOVERY_REQUIRED,
                warnings=("receipt ledger is unavailable; owner effect was not started",),
            )
        if prior is not None:
            if prior.intent_digest == intent_digest:
                if reconcile is None or prior.outcome.status not in {
                    OperationStatus.RECOVERY_REQUIRED, OperationStatus.NOT_ACKNOWLEDGED
                }:
                    return prior.outcome
                return self._reconcile(request, delegation, prior, reconcile, owner_request)
            return self._outcome(
                request,
                OperationStatus.CONFLICTED,
                warnings=("request_id is already bound to different intent",),
            )
        refusal = self._precondition_refusal(request, delegation)
        if refusal is not None:
            return refusal
        try:
            decision = self.policy_evaluator(request, delegation)
        except Exception:
            return self._outcome(
                request, OperationStatus.REJECTED, warnings=("policy evaluation is unavailable",)
            )
        if not decision.admitted:
            return self._outcome(
                request,
                OperationStatus.REJECTED,
                warnings=(decision.reason or "policy denied operation",),
            )
        if decision.policy_version != delegation.get("policy_version"):
            return self._outcome(
                request, OperationStatus.REJECTED, warnings=("delegation policy version is stale",)
            )
        try:
            token_valid = self.token_validator(request, decision)
        except Exception:
            token_valid = False
        if not token_valid:
            return self._outcome(
                request,
                OperationStatus.REJECTED,
                warnings=("decision token is missing or invalid",),
            )
        try:
            version_current = self.version_checker(request)
        except Exception:
            version_current = False
        if not version_current:
            return self._outcome(
                request, OperationStatus.CONFLICTED, warnings=("version precondition failed",)
            )

        pending = self._outcome(
            request,
            OperationStatus.RECOVERY_REQUIRED,
            receipt=_receipt(
                request,
                decision.policy_version,
                intent_digest,
                "applied_receipt_pending",
                delegation,
            ),
            warnings=("owner effect may have started; reconcile receipt before retry",),
        )
        if bind_owner_delegation:
            pending = replace(pending, extensions={"admission_decision_digest": _decision_digest(decision)})
        try:
            reservation, stored = self.receipt_store.reserve(
                request.request_id, intent_digest, pending
            )
        except Exception:
            return self._outcome(
                request,
                OperationStatus.RECOVERY_REQUIRED,
                warnings=("receipt ledger is unavailable; owner effect was not started",),
            )
        if reservation == "replay":
            return stored.outcome
        if reservation == "conflict":
            return self._outcome(
                request,
                OperationStatus.CONFLICTED,
                warnings=("request_id is already bound to different intent",),
            )

        handler = self.handlers.get(request.operation_id)
        if handler is None:
            outcome = self._outcome(
                request,
                OperationStatus.NOT_SUPPORTED,
                receipt=_receipt(request, decision.policy_version, intent_digest, "not_supported"),
            )
        else:
            try:
                owner_result = handler(owner_request)
            except Exception:
                owner_result = OwnerExecutionResult.ambiguous()
            outcome = self._owner_outcome(
                request, decision.policy_version, intent_digest, owner_result, delegation
            )
            outcome = replace(outcome, convergence=owner_result.convergence)
        if bind_owner_delegation:
            outcome = replace(outcome, extensions={**outcome.extensions,
                                                   "admission_decision_digest": _decision_digest(decision)})
        try:
            self.receipt_store.finalize(request.request_id, intent_digest, outcome)
        except Exception:
            return replace(
                outcome, status=OperationStatus.RECOVERY_REQUIRED,
                receipt=replace(outcome.receipt, status=ReceiptStatus.PENDING, payload={**outcome.receipt.payload, "state": "applied_receipt_pending", "recovery": "read_receipt_before_retry"}) if outcome.receipt else None,
                warnings=outcome.warnings + ("owner result requires durable receipt reconciliation",),
            )
        return outcome

    def _reconcile(
        self, request: OperationRequest, delegation: Mapping[str, Any],
        prior: _StoredOutcome, reconcile: OwnerHandler, owner_request: OperationRequest,
    ) -> OperationOutcome:
        """Owner recovery after current admission, retaining original intent/CAS.

        A version checker for a new effect cannot validate an already-applied
        effect. The owner must verify its original source/effect evidence; this
        seam never clears a reservation or invokes the ordinary handler again.
        """
        if not isinstance(self.receipt_store, JsonReceiptStore):
            return replace(prior.outcome, status=OperationStatus.RECOVERY_REQUIRED,
                           warnings=prior.outcome.warnings + ("native recovery requires the durable receipt journal",))
        refusal = self._precondition_refusal(request, delegation)
        try:
            decision = self.policy_evaluator(request, delegation) if refusal is None else None
            admitted = (
                decision is not None and decision.admitted
                and decision.policy_version == delegation.get("policy_version")
                and self.token_validator(request, decision)
            )
        except Exception:
            admitted = False
        if not admitted:
            return replace(prior.outcome, status=OperationStatus.RECOVERY_REQUIRED,
                           extensions={**prior.outcome.extensions, "recovery_admission": "refused"},
                           warnings=prior.outcome.warnings + ("current recovery admission refused; historical effect truth retained",))
        if (not prior.outcome.extensions.get("admission_decision_digest")
                or decision is None
                or _decision_digest(decision) != prior.outcome.extensions["admission_decision_digest"]):
            return replace(prior.outcome, status=OperationStatus.RECOVERY_REQUIRED,
                           extensions={**prior.outcome.extensions, "recovery_admission": "decision_rebinding_refused"},
                           warnings=prior.outcome.warnings + ("recovery cannot replace the originally captured kernel decision",))
        # A new native recovery may itself perform proven namespace effects.
        # Record uncertainty BEFORE handing off. An older NOT_APPLIED result
        # cannot describe this new attempt after a crash. Already COMMITTED
        # source/receipts remain immutable historical facts.
        convergence = prior.outcome.convergence
        if convergence is None:
            convergence = OperationConvergence(SourceEffectStatus.UNKNOWN,
                                               store=ConvergenceState.REBUILD_REQUIRED,
                                               index=ConvergenceState.REBUILD_REQUIRED,
                                               link=ConvergenceState.REBUILD_REQUIRED)
        elif convergence.source_effect is not SourceEffectStatus.COMMITTED:
            convergence = replace(convergence, source_effect=SourceEffectStatus.UNKNOWN,
                                  store=ConvergenceState.REBUILD_REQUIRED,
                                  index=ConvergenceState.REBUILD_REQUIRED,
                                  link=ConvergenceState.REBUILD_REQUIRED)
        pending = replace(prior.outcome, status=OperationStatus.RECOVERY_REQUIRED,
                          convergence=convergence,
                          receipt=replace(prior.outcome.receipt, status=ReceiptStatus.PENDING)
                          if prior.outcome.receipt else None,
                          warnings=tuple(dict.fromkeys(prior.outcome.warnings +
                              ("native recovery may start; reconcile its current receipt before another attempt",))))
        try:
            self.receipt_store.finalize(request.request_id, prior.intent_digest, pending)
        except Exception:
            return replace(prior.outcome, status=OperationStatus.RECOVERY_REQUIRED,
                           warnings=prior.outcome.warnings + ("recovery attempt was not durably reserved; owner was not called",))
        prior = replace(prior, outcome=pending, in_flight=True)
        try:
            result = reconcile(owner_request)
            outcome = self._owner_outcome(
                request, str(delegation["policy_version"]), prior.intent_digest, result, delegation
            )
            outcome = replace(outcome, convergence=result.convergence,
                              extensions={**outcome.extensions, "admission_decision_digest": prior.outcome.extensions["admission_decision_digest"]})
            if result.status in {OperationStatus.REJECTED, OperationStatus.INVALID,
                                 OperationStatus.NOT_FOUND, OperationStatus.NOT_SUPPORTED}:
                return replace(prior.outcome, status=OperationStatus.RECOVERY_REQUIRED,
                               extensions={**prior.outcome.extensions, "recovery_admission": result.status.value},
                               warnings=prior.outcome.warnings + result.warnings)
            if (result.effect_receipt is None or prior.outcome.convergence is not None
                    and prior.outcome.convergence.source_effect.value == "committed"
                    and (outcome.convergence is None or outcome.convergence.source_effect.value != "committed")):
                return replace(prior.outcome, status=OperationStatus.RECOVERY_REQUIRED,
                               warnings=prior.outcome.warnings + result.warnings)
        except Exception:
            return replace(prior.outcome, status=OperationStatus.RECOVERY_REQUIRED,
                           warnings=prior.outcome.warnings + ("owner receipt reconciliation remains unresolved",))
        try:
            self.receipt_store.finalize(request.request_id, prior.intent_digest, outcome)
        except Exception:
            return replace(
                outcome, status=OperationStatus.RECOVERY_REQUIRED,
                receipt=replace(outcome.receipt, status=ReceiptStatus.PENDING) if outcome.receipt else None,
                warnings=outcome.warnings + ("reconciled owner evidence is known; kernel persistence remains pending",),
            )
        return outcome

    def _precondition_refusal(
        self, request: OperationRequest, delegation: Mapping[str, Any] | None
    ) -> OperationOutcome | None:
        if (
            not request.context.active_context_ref
            or not request.operation_id
            or not request.request_id
        ):
            return self._outcome(
                request,
                OperationStatus.INVALID,
                warnings=("operation, request, and explicit context are required",),
            )
        try:
            context_resolved = self.context_resolver(request.context)
        except Exception:
            context_resolved = False
        if not context_resolved:
            return self._outcome(
                request, OperationStatus.REJECTED, warnings=("active context is unavailable",)
            )
        if delegation is None:
            return self._outcome(
                request, OperationStatus.REJECTED, warnings=("bounded delegation is required",)
            )
        operation_ids = delegation.get("operation_ids")
        target_ids = tuple(target.get("artifact_id") for target in request.targets)
        if not all(_stable_nonempty_identity(target_id) for target_id in target_ids):
            return self._outcome(
                request,
                OperationStatus.REJECTED,
                warnings=("every target requires a stable artifact identity",),
            )
        stable_target_ids = tuple(str(target_id) for target_id in target_ids)
        admitted_targets = delegation.get("target_ids")
        if (
            delegation.get("active_context_ref") != request.context.active_context_ref
            or delegation.get("vault_generation") != request.context.vault_generation
            or not isinstance(operation_ids, (list, tuple, set))
            or request.operation_id not in operation_ids
            or not isinstance(delegation.get("policy_version"), str)
            or not delegation["policy_version"]
            or not all(
                isinstance(delegation.get(field), str) and delegation[field]
                for field in ("principal", "client", "surface", "receipt_ref", "authority_class")
            )
            or not isinstance(admitted_targets, (list, tuple, set))
            or not set(stable_target_ids).issubset({str(item) for item in admitted_targets})
            or not isinstance(delegation.get("max_targets"), int)
            or delegation["max_targets"] < len(stable_target_ids)
            or not isinstance(delegation.get("allowed_effects"), (list, tuple, set))
            or request.operation_id not in delegation["allowed_effects"]
            or not isinstance(delegation.get("expires_at"), (int, float))
            or delegation["expires_at"] <= time()
            or delegation.get("revoked") is not False
        ):
            return self._outcome(
                request,
                OperationStatus.REJECTED,
                warnings=("delegation does not admit this operation",),
            )
        if len(stable_target_ids) > 1:
            request_batch_policy = request.batch_policy
            delegation_batch_policy = delegation.get("batch_policy")
            if not (
                _valid_batch_policy(request_batch_policy)
                or _valid_batch_policy(delegation_batch_policy)
            ):
                return self._outcome(
                    request,
                    OperationStatus.REJECTED,
                    warnings=("a valid batch policy is required for multiple targets",),
                )
            if (
                _valid_batch_policy(request_batch_policy)
                and _valid_batch_policy(delegation_batch_policy)
                and request_batch_policy != delegation_batch_policy
            ):
                return self._outcome(
                    request,
                    OperationStatus.REJECTED,
                    warnings=("batch policy is not bound by delegation",),
                )
        if request.operation_version != "ygg.operation.v1":
            return self._outcome(
                request, OperationStatus.NOT_SUPPORTED, warnings=("unsupported operation version",)
            )
        return None

    def _owner_outcome(
        self,
        request: OperationRequest,
        policy_version: str,
        intent_digest: str,
        result: OwnerExecutionResult,
        delegation: Mapping[str, Any],
    ) -> OperationOutcome:
        if result.status in {OperationStatus.SUCCEEDED, OperationStatus.CONVERGENCE_PENDING}:
            if not _has_durable_owner_effect_receipt(result):
                return self._outcome(
                    request,
                    OperationStatus.RECOVERY_REQUIRED,
                    items=_redact_items(result.items),
                    receipt=_receipt(
                        request,
                        policy_version,
                        intent_digest,
                        "recovery_required",
                        delegation,
                        result.effect_id,
                        result.effect_receipt,
                    ),
                    warnings=result.warnings
                    + (
                        "owner success is missing a durable effect receipt or stable effect identity",
                        "read receipt before retry",
                    ),
                )
            return self._outcome(
                request,
                result.status,
                items=_redact_items(result.items),
                receipt=_receipt(
                    request,
                    policy_version,
                    intent_digest,
                    "completed" if result.status is OperationStatus.SUCCEEDED else "convergence_pending",
                    delegation,
                    result.effect_id,
                    result.effect_receipt,
                ),
                warnings=result.warnings,
            )
        if result.status is OperationStatus.RECOVERY_REQUIRED:
            return self._outcome(
                request,
                result.status,
                items=_redact_items(result.items),
                receipt=_receipt(
                    request, policy_version, intent_digest, "recovery_required", delegation,
                    result.effect_id, result.effect_receipt,
                ),
                warnings=result.warnings + ("read receipt before retry",),
            )
        return self._outcome(
            request,
            result.status,
            items=_redact_items(result.items),
            receipt=_receipt(
                request, policy_version, intent_digest, "not_acknowledged", delegation,
                result.effect_id, result.effect_receipt,
            ),
            warnings=result.warnings,
        )

    @staticmethod
    def _outcome(
        request: OperationRequest,
        status: OperationStatus,
        *,
        items: tuple[OperationItemOutcome, ...] = (),
        receipt: OperationReceipt | None = None,
        warnings: tuple[str, ...] = (),
    ) -> OperationOutcome:
        return OperationOutcome(
            request.request_id,
            status,
            request.operation_id,
            request.context,
            provenance=request.provenance,
            items=items,
            receipt=receipt,
            warnings=warnings,
        )


def _intent_digest(request: OperationRequest, delegation: Mapping[str, Any]) -> str:
    """Bind replay identity without persisting raw request or delegation payloads."""
    material = {"request": request.to_dict(), "delegation": dict(delegation)}
    encoded = json.dumps(material, sort_keys=True, default=str, separators=(",", ":")).encode(
        "utf-8"
    )
    return sha256(encoded).hexdigest()


def _decision_digest(decision: PolicyDecision) -> str:
    """Non-secret original admission identity, not a token or new authority."""
    return sha256(json.dumps({"policy_version": decision.policy_version,
                              "decision_token": decision.decision_token},
                             sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _receipt(
    request: OperationRequest,
    policy_version: str,
    intent_digest: str,
    state: str,
    delegation: Mapping[str, Any] | None = None,
    effect_id: str | None = None,
    effect_receipt: Mapping[str, Any] | None = None,
) -> OperationReceipt:
    """Receipt projection intentionally excludes arguments, secrets, and raw delegation."""
    return OperationReceipt(
        receipt_id=None
        if delegation is None or delegation.get("receipt_ref") is None
        else str(delegation["receipt_ref"]),
        status=ReceiptStatus.COMMITTED if state in {"completed", "convergence_pending"} else ReceiptStatus.PENDING,
        payload={
            "request_id": request.request_id,
            "operation_id": request.operation_id,
            "operation_version": request.operation_version,
            "context_ref": request.context.active_context_ref,
            "vault_generation": request.context.vault_generation,
            "policy_version": policy_version,
            "principal": None if delegation is None else delegation.get("principal"),
            "client": None if delegation is None else delegation.get("client"),
            "surface": None if delegation is None else delegation.get("surface"),
            "delegation_ref": None if delegation is None else delegation.get("receipt_ref"),
            "effect_id": effect_id if _stable_nonempty_identity(effect_id) else None,
            "effect_receipt_ref": _effect_receipt_ref(effect_receipt),
            "intent_digest": intent_digest,
            "state": state,
            "recovery": "read_receipt_before_retry" if state == "recovery_required" else None,
        },
        extensions=_effect_receipt_extensions(effect_receipt),
    )


def _stable_nonempty_identity(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _valid_batch_policy(value: object) -> bool:
    return isinstance(value, Mapping) and bool(value)


def _with_delegated_batch_policy(
    request: OperationRequest, delegation: Mapping[str, Any]
) -> OperationRequest:
    if (
        len(request.targets) > 1
        and not _valid_batch_policy(request.batch_policy)
        and _valid_batch_policy(delegation.get("batch_policy"))
    ):
        return replace(request, batch_policy=delegation["batch_policy"])
    return request


def _effect_receipt_ref(value: Mapping[str, Any] | None) -> str | None:
    if not isinstance(value, Mapping):
        return None
    receipt_id = value.get("receipt_id")
    return str(receipt_id) if _stable_nonempty_identity(receipt_id) else None


def _effect_receipt_extensions(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    """Preserve only the bounded, redacted owner projection in the receipt.

    Effect receipts are otherwise opaque and must not be copied into the
    generic kernel receipt. Archival handlers explicitly provide this safe
    projection so generation, policy, stage, and liveness remain auditable.
    """
    if not isinstance(value, Mapping):
        return {}
    extensions: dict[str, Any] = {}
    archival = value.get("archival")
    if isinstance(archival, Mapping):
        extensions["archival"] = dict(archival)
    placement = value.get("placement")
    if isinstance(placement, Mapping):
        extensions["placement"] = dict(placement)
    write = value.get("write")
    if isinstance(write, Mapping):
        # Only server-composed, content-free owner metadata crosses into the
        # kernel summary. Arguments and bodies are never copied here.
        fields = {"owner", "source_receipt", "policy_decision", "decision_token", "authority_receipt", "input_version", "resulting_version", "projection_repair", "effect_state", "intent_digest"}
        extensions["write"] = {key: write[key] for key in fields if key in write}
    return extensions


def _has_durable_owner_effect_receipt(result: OwnerExecutionResult) -> bool:
    return (
        _stable_nonempty_identity(result.effect_id)
        and isinstance(result.effect_receipt, Mapping)
        and _effect_receipt_ref(result.effect_receipt) is not None
    )


def _redact_items(items: tuple[Mapping[str, Any], ...]) -> tuple[OperationItemOutcome, ...]:
    allowed = {"artifact_id", "status", "version", "result_version"}
    return tuple(
        OperationItemOutcome(
            resource_id=None if item.get("artifact_id") is None else str(item["artifact_id"]),
            status=_operation_status(item.get("status")),
            input_version=item.get("version"),
            resulting_version=item.get("result_version"),
            payload={
                str(key): value if key in allowed else "[redacted]" for key, value in item.items()
            },
        )
        for item in items
    )


def _operation_status(value: object) -> OperationStatus | None:
    try:
        return None if value is None else OperationStatus(str(value))
    except ValueError:
        return None


__all__ = [
    "InMemoryReceiptStore",
    "JsonReceiptStore",
    "OperationExecutionKernel",
    "ArchivalOperationReceipt",
    "OwnerExecutionResult",
    "PolicyDecision",
    "ReceiptStore",
]
