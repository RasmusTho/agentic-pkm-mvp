"""Fail-closed execution seam for ``ygg.operation.v1`` effects.

The kernel deliberately owns only admission, idempotency, and durable receipt
bookkeeping.  It never implements a domain mutation: each admitted operation
is dispatched once to its registered owner-native handler.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from contextlib import contextmanager
import fcntl
from hashlib import sha256
import json
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import RLock
from time import time
from typing import Any, Callable, Iterator, Mapping, Protocol

from app.archival.contracts import ArtifactClass, LivenessState, PolicyProfile, TransitionStage

from .contracts import OperationOutcome, OperationRequest, OperationStatus


@dataclass(frozen=True)
class PolicyDecision:
    """The minimal policy result needed by the execution boundary."""

    admitted: bool
    policy_version: str
    reason: str | None = None
    decision_token: str | None = None

    @classmethod
    def allowed(cls, policy_version: str, decision_token: str = "verified-token") -> "PolicyDecision":
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
    archival_receipt: "ArchivalOperationReceipt | None" = None

    @classmethod
    def succeeded(cls, *, items: tuple[Mapping[str, Any], ...] = ()) -> "OwnerExecutionResult":
        return cls(OperationStatus.SUCCEEDED, items)

    @classmethod
    def ambiguous(cls) -> "OwnerExecutionResult":
        return cls(OperationStatus.RECOVERY_REQUIRED, warnings=("owner outcome requires receipt reconciliation",))

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
    def reserve(self, request_id: str, intent_digest: str, pending: OperationOutcome) -> tuple[str, _StoredOutcome]: ...

    def finalize(self, request_id: str, intent_digest: str, outcome: OperationOutcome) -> None: ...


class InMemoryReceiptStore:
    """Test/local store with the same replay semantics as the JSON store."""

    def __init__(self) -> None:
        self._records: dict[str, _StoredOutcome] = {}
        self._lock = RLock()

    def reserve(self, request_id: str, intent_digest: str, pending: OperationOutcome) -> tuple[str, _StoredOutcome]:
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

    def reserve(self, request_id: str, intent_digest: str, pending: OperationOutcome) -> tuple[str, _StoredOutcome]:
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
    def _process_lock(self) -> Iterator[None]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with (self.path.parent / f".{self.path.name}.lock").open("a+", encoding="utf-8") as lock_file:
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
                value["intent_digest"], OperationOutcome.from_dict(value["outcome"]), bool(value.get("in_flight", False))
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
        with NamedTemporaryFile("w", encoding="utf-8", dir=self.path.parent, delete=False) as temporary:
            json.dump(payload, temporary, sort_keys=True, separators=(",", ":"))
            temporary.flush()
            Path(temporary.name).replace(self.path)


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
    version_checker: VersionChecker = field(default=lambda request: request.expected_version is None)
    token_validator: TokenValidator = field(default=lambda request, decision: False)

    def execute(self, request: OperationRequest, delegation: Mapping[str, Any] | None = None) -> OperationOutcome:
        delegation = delegation if delegation is not None else request.delegation
        if delegation is None:
            return self._outcome(request, OperationStatus.REJECTED, warnings=("bounded delegation is required",))
        intent_digest = _intent_digest(request, delegation)
        try:
            prior = self.receipt_store.lookup(request.request_id)
        except Exception:
            return self._outcome(request, OperationStatus.RECOVERY_REQUIRED, warnings=("receipt ledger is unavailable; owner effect was not started",))
        if prior is not None:
            if prior.intent_digest == intent_digest:
                return prior.outcome
            return self._outcome(request, OperationStatus.CONFLICTED, warnings=("request_id is already bound to different intent",))
        refusal = self._precondition_refusal(request, delegation)
        if refusal is not None:
            return refusal
        try:
            decision = self.policy_evaluator(request, delegation)
        except Exception:
            return self._outcome(request, OperationStatus.REJECTED, warnings=("policy evaluation is unavailable",))
        if not decision.admitted:
            return self._outcome(request, OperationStatus.REJECTED, warnings=(decision.reason or "policy denied operation",))
        if decision.policy_version != delegation.get("policy_version"):
            return self._outcome(request, OperationStatus.REJECTED, warnings=("delegation policy version is stale",))
        try:
            token_valid = self.token_validator(request, decision)
        except Exception:
            token_valid = False
        if not token_valid:
            return self._outcome(request, OperationStatus.REJECTED, warnings=("decision token is missing or invalid",))
        try:
            version_current = self.version_checker(request)
        except Exception:
            version_current = False
        if not version_current:
            return self._outcome(request, OperationStatus.CONFLICTED, warnings=("version precondition failed",))

        pending = self._outcome(request, OperationStatus.RECOVERY_REQUIRED, receipt=_receipt(request, decision.policy_version, intent_digest, "applied_receipt_pending", delegation), warnings=("owner effect may have started; reconcile receipt before retry",))
        try:
            reservation, stored = self.receipt_store.reserve(request.request_id, intent_digest, pending)
        except Exception:
            return self._outcome(request, OperationStatus.RECOVERY_REQUIRED, warnings=("receipt ledger is unavailable; owner effect was not started",))
        if reservation == "replay":
            return stored.outcome
        if reservation == "conflict":
            return self._outcome(request, OperationStatus.CONFLICTED, warnings=("request_id is already bound to different intent",))

        handler = self.handlers.get(request.operation_id)
        if handler is None:
            outcome = self._outcome(request, OperationStatus.NOT_SUPPORTED, receipt=_receipt(request, decision.policy_version, intent_digest, "not_supported"))
        else:
            try:
                owner_result = handler(request)
            except Exception:
                owner_result = OwnerExecutionResult.ambiguous()
            outcome = self._owner_outcome(request, decision.policy_version, intent_digest, owner_result, delegation)
        try:
            self.receipt_store.finalize(request.request_id, intent_digest, outcome)
        except Exception:
            return self._outcome(request, OperationStatus.RECOVERY_REQUIRED, receipt=_receipt(request, decision.policy_version, intent_digest, "applied_receipt_pending"), warnings=("owner result requires durable receipt reconciliation",))
        return outcome

    def _precondition_refusal(self, request: OperationRequest, delegation: Mapping[str, Any] | None) -> OperationOutcome | None:
        if not request.context.active_context_ref or not request.operation_id or not request.request_id:
            return self._outcome(request, OperationStatus.INVALID, warnings=("operation, request, and explicit context are required",))
        try:
            context_resolved = self.context_resolver(request.context)
        except Exception:
            context_resolved = False
        if not context_resolved:
            return self._outcome(request, OperationStatus.REJECTED, warnings=("active context is unavailable",))
        if delegation is None:
            return self._outcome(request, OperationStatus.REJECTED, warnings=("bounded delegation is required",))
        operation_ids = delegation.get("operation_ids")
        target_ids = tuple(str(target.get("artifact_id", "")) for target in request.targets)
        admitted_targets = delegation.get("target_ids")
        if (
            delegation.get("active_context_ref") != request.context.active_context_ref
            or delegation.get("vault_generation") != request.context.vault_generation
            or not isinstance(operation_ids, (list, tuple, set))
            or request.operation_id not in operation_ids
            or not isinstance(delegation.get("policy_version"), str)
            or not delegation["policy_version"]
            or not all(isinstance(delegation.get(field), str) and delegation[field] for field in ("principal", "client", "surface", "receipt_ref", "authority_class"))
            or not isinstance(admitted_targets, (list, tuple, set))
            or not set(target_ids).issubset({str(item) for item in admitted_targets})
            or not isinstance(delegation.get("max_targets"), int)
            or delegation["max_targets"] < len(target_ids)
            or not isinstance(delegation.get("allowed_effects"), (list, tuple, set))
            or request.operation_id not in delegation["allowed_effects"]
            or not isinstance(delegation.get("expires_at"), (int, float))
            or delegation["expires_at"] <= time()
            or delegation.get("revoked") is not False
        ):
            return self._outcome(request, OperationStatus.REJECTED, warnings=("delegation does not admit this operation",))
        if len(target_ids) > 1 and delegation.get("batch_policy") != request.batch_policy:
            return self._outcome(request, OperationStatus.REJECTED, warnings=("batch policy is not bound by delegation",))
        if request.operation_version != "ygg.operation.v1":
            return self._outcome(request, OperationStatus.NOT_SUPPORTED, warnings=("unsupported operation version",))
        return None

    def _owner_outcome(self, request: OperationRequest, policy_version: str, intent_digest: str, result: OwnerExecutionResult, delegation: Mapping[str, Any]) -> OperationOutcome:
        if result.archival_receipt is not None and request.operation_id not in {"artifact.archive", "artifact.restore"}:
            return self._outcome(request, OperationStatus.NOT_ACKNOWLEDGED, receipt=_receipt(request, policy_version, intent_digest, "not_acknowledged", delegation), warnings=("archival receipt is not admitted for this operation",))
        if result.status is OperationStatus.SUCCEEDED:
            return self._outcome(request, result.status, items=_redact_items(result.items), receipt=_receipt(request, policy_version, intent_digest, "completed", delegation, result.archival_receipt), warnings=result.warnings)
        if result.status is OperationStatus.RECOVERY_REQUIRED:
            return self._outcome(request, result.status, items=_redact_items(result.items), receipt=_receipt(request, policy_version, intent_digest, "recovery_required", delegation), warnings=result.warnings + ("read receipt before retry",))
        return self._outcome(request, result.status, items=_redact_items(result.items), receipt=_receipt(request, policy_version, intent_digest, "not_acknowledged", delegation), warnings=result.warnings)

    @staticmethod
    def _outcome(request: OperationRequest, status: OperationStatus, *, items: tuple[Mapping[str, Any], ...] = (), receipt: Mapping[str, Any] | None = None, warnings: tuple[str, ...] = ()) -> OperationOutcome:
        return OperationOutcome(request.request_id, status, request.operation_id, request.context, items=items, receipt=receipt, warnings=warnings)


def _intent_digest(request: OperationRequest, delegation: Mapping[str, Any]) -> str:
    """Bind replay identity without persisting raw request or delegation payloads."""
    material = {"request": request.to_dict(), "delegation": dict(delegation)}
    encoded = json.dumps(material, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
    return sha256(encoded).hexdigest()


def _receipt(request: OperationRequest, policy_version: str, intent_digest: str, state: str, delegation: Mapping[str, Any] | None = None, archival_receipt: ArchivalOperationReceipt | None = None) -> dict[str, Any]:
    """Receipt projection intentionally excludes arguments, secrets, and raw delegation."""
    receipt = {
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
        "intent_digest": intent_digest,
        "state": state,
        "recovery": "read_receipt_before_retry" if state == "recovery_required" else None,
    }
    if archival_receipt is not None:
        receipt["archival"] = archival_receipt.to_dict()
    return receipt


def _redact_items(items: tuple[Mapping[str, Any], ...]) -> tuple[Mapping[str, Any], ...]:
    allowed = {"artifact_id", "status", "version", "result_version"}
    return tuple({str(key): value if key in allowed else "[redacted]" for key, value in item.items()} for item in items)


__all__ = [
    "InMemoryReceiptStore",
    "JsonReceiptStore",
    "OperationExecutionKernel",
    "ArchivalOperationReceipt",
    "OwnerExecutionResult",
    "PolicyDecision",
    "ReceiptStore",
]
