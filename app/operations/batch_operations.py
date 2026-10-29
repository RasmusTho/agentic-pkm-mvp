"""Bounded AUTOOPS-08 sequencing over existing single-operation owners.

Batch snapshots are a bounded extension of the kernel's JSON receipt journal.
They record intent/progress, never source, semantic or GOV authority. The trusted
production HTTP composition lives in app.api; no route, singleton, scheduler
or operation registry is installed by this domain module.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from hashlib import sha256
import json
from typing import Any, Mapping, Sequence

from .contracts import OperationOutcome, OperationRequest, OperationStatus, SourceEffectStatus
from .execution_kernel import JsonReceiptStore, OperationExecutionKernel, OwnerHandler

# Only existing, versioned, single-human-target mutations are admitted. Other
# delivered operations retain their own contracts; registration does not opt
# them into batch semantics or manufacture a missing owner recovery binding.
SUPPORTED_BATCH_OPERATIONS = frozenset({
    "artifact.update", "artifact.move", "artifact.rename", "artifact.classify",
    "artifact.tags.add", "artifact.tags.remove", "collection.reorder",
})
MAX_BATCH_ITEMS = 100
_PREFIX = "ygg.batch:"
_RECOVERABLE = {OperationStatus.RECOVERY_REQUIRED, OperationStatus.NOT_ACKNOWLEDGED}
_APPLIED = {OperationStatus.SUCCEEDED, OperationStatus.CONVERGENCE_PENDING}


class BatchStateUnavailable(RuntimeError):
    """The frozen batch cannot be authenticated; no item may start."""


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value: Any) -> str:
    return sha256(_json(value).encode()).hexdigest()


@dataclass(frozen=True)
class BatchPreview:
    batch_id: str
    digest: str
    operation_id: str
    candidate_digest: str
    selector_digest: str
    argument_digest: str
    delegation_digest: str
    policy_ceiling: Mapping[str, Any]
    cardinality: int
    limit: int
    partial_success_policy: str


@dataclass(frozen=True)
class BatchItem:
    request_id: str
    artifact_id: str
    state: str
    outcome: OperationOutcome | None


@dataclass(frozen=True)
class BatchResult:
    preview: BatchPreview
    cancel_requested: bool
    items: tuple[BatchItem, ...]

    @property
    def counts(self) -> dict[str, int]:
        result = dict.fromkeys(("completed", "conflicted", "refused", "ambiguous",
                                "pending", "cancelled", "recoverable", "convergence_pending"), 0)
        for item in self.items:
            outcome = item.outcome
            if item.state == "cancelled":
                result["cancelled"] += 1
            elif item.state in {"pending", "started"}:
                result["pending"] += 1
            elif outcome is not None and outcome.status in _APPLIED:
                result["completed"] += 1
                result["convergence_pending"] += outcome.status is OperationStatus.CONVERGENCE_PENDING
            elif outcome is not None and outcome.status is OperationStatus.CONFLICTED:
                result["conflicted"] += 1
            elif outcome is not None and outcome.status in _RECOVERABLE:
                result["recoverable"] += 1
                if outcome.convergence is None or outcome.convergence.source_effect is SourceEffectStatus.UNKNOWN:
                    result["ambiguous"] += 1
            else:
                result["refused"] += 1
        return result

    @property
    def status(self) -> str:
        counts = self.counts
        if counts["recoverable"]:
            return "recovery_required"
        if counts["pending"]:
            return "pending"
        if counts["completed"] == len(self.items):
            return "convergence_pending" if counts["convergence_pending"] else "succeeded"
        if counts["cancelled"] == len(self.items):
            return "cancelled"
        return "partial" if counts["completed"] else "not_completed"


class BatchOperationCoordinator:
    """Direct composition for one frozen homogeneous batch at a time.

    A trusted producer supplies an existing kernel and, when available, that
    operation owner's reconciliation seam. The callback is never an ordinary
    mutation retry. Without it, uncertain items remain explicitly recoverable.
    """

    def __init__(self, kernel: OperationExecutionKernel, *, reconcile_owner: OwnerHandler | None = None):
        if not isinstance(kernel.receipt_store, JsonReceiptStore):
            raise ValueError("batch execution requires the existing durable JSON receipt journal")
        self.kernel = kernel
        self.store = kernel.receipt_store
        self.reconcile_owner = reconcile_owner

    def preview(
        self, *, batch_id: str, requests: Sequence[OperationRequest],
        selector: Mapping[str, Any], delegation: Mapping[str, Any], limit: int = MAX_BATCH_ITEMS,
        partial_success_policy: str = "independent",
    ) -> BatchPreview:
        if not isinstance(batch_id, str) or not batch_id.strip() or len(batch_id) > 200:
            raise ValueError("a bounded stable batch identity is required")
        if type(limit) is not int or not 1 <= limit <= MAX_BATCH_ITEMS or not 1 <= len(requests) <= limit:
            raise ValueError("batch cardinality exceeds its explicit bounded limit")
        if partial_success_policy != "independent":
            raise ValueError("only independent per-item partial success is supported")
        first = requests[0]
        if first.operation_id not in SUPPORTED_BATCH_OPERATIONS or first.operation_id not in self.kernel.handlers:
            raise ValueError("operation has no supported direct batch owner binding")
        identities: set[str] = set()
        request_ids: set[str] = set()
        # Roundtrip detaches caller-owned nested mappings, not just dataclasses.
        frozen_requests = json.loads(_json([request.to_dict() for request in requests]))
        frozen_delegation = json.loads(_json(dict(delegation)))
        batch_policy = {"partial_success_policy": partial_success_policy}
        if frozen_delegation.get("batch_policy") not in (None, batch_policy):
            raise ValueError("delegated partial-success policy is not supported")
        for raw in frozen_requests:
            request = OperationRequest.from_dict(raw)
            if (request.operation_id != first.operation_id or request.context != first.context
                    or request.mode != "execute" or request.operation_version != "ygg.operation.v1"
                    or len(request.targets) != 1 or set(request.targets[0]) != {"artifact_id"}
                    or not isinstance(request.expected_version, str) or not request.expected_version
                    or not request.request_id or request.request_id.startswith(_PREFIX)):
                raise ValueError("batch requires homogeneous versioned single-target owner requests")
            if request.operation_id == "artifact.update" and set(request.arguments) != {"body"}:
                raise ValueError("batch body edits cannot select the Panel/proposal owner")
            if (request.batch_policy not in (None, batch_policy)
                    or request.delegation is not None and dict(request.delegation) != frozen_delegation):
                raise ValueError("item delegation/partial-success policy differs from frozen batch")
            identity = request.targets[0]["artifact_id"]
            if not isinstance(identity, str) or not identity.strip() or identity in identities or request.request_id in request_ids:
                raise ValueError("batch target and operation identities must be stable and unique")
            if self.kernel._precondition_refusal(request, frozen_delegation) is not None:
                raise ValueError("frozen delegation/context does not admit every selected item")
            identities.add(identity)
            request_ids.add(request.request_id)
        if (type(delegation.get("max_targets")) is not int or len(requests) > delegation["max_targets"]):
            raise ValueError("batch cardinality exceeds delegated scope")
        policy = {key: frozen_delegation[key] for key in
                  ("policy_version", "authority_class", "allowed_effects", "max_targets", "expires_at")}
        frozen = {
            "batch_id": batch_id, "requests": frozen_requests,
            "selector": json.loads(_json(dict(selector))), "delegation": frozen_delegation,
            "policy_ceiling": policy, "limit": limit, "partial_success_policy": partial_success_policy,
        }
        if len(_json(frozen).encode()) > 1_048_576:
            raise ValueError("batch intent exceeds the bounded durable payload")
        digest = _digest(frozen)
        state = {"frozen": frozen, "cancel_requested": False, "cursor": 0,
                 "items": [{"state": "pending", "outcome": None} for _ in requests]}
        with self.store.batch_window(batch_id):
            record = OperationOutcome(_PREFIX + batch_id, OperationStatus.RECOVERY_REQUIRED,
                                      "batch.preview", first.context, extensions={"batch": state})
            reservation, _ = self.store.reserve(_PREFIX + batch_id, digest, record)
            if reservation == "conflict":
                raise ValueError("batch identity is already bound to another frozen intent")
            return self._result(self._load(batch_id)).preview

    def frozen_intent(self, batch_id: str, *, expected_digest: str) -> Mapping[str, Any]:
        """Read a detached original plan for trusted host owner reconstruction."""
        with self.store.batch_window(batch_id):
            return json.loads(_json(self._load(batch_id, expected_digest)["frozen"]))

    def inspect(self, batch_id: str, *, expected_digest: str) -> BatchResult:
        with self.store.batch_window(batch_id):
            return self._result(self._load(batch_id, expected_digest))

    def cancel(self, batch_id: str, *, expected_digest: str) -> BatchResult:
        with self.store.batch_window(batch_id):
            state = self._load(batch_id, expected_digest)
            state["cancel_requested"] = True
            for request, item in zip(state["frozen"]["requests"], state["items"], strict=True):
                if item["state"] == "pending":
                    # A stable operation may already have kernel history. Do
                    # not label its historical effect as never started.
                    item["state"] = "started" if self.store.lookup(request["request_id"]) is not None else "cancelled"
            self._save(state)
            return self._result(state)

    def execute(self, batch_id: str, *, expected_digest: str) -> BatchResult:
        with self.store.batch_window(batch_id, running=True):
            # Selection is never re-run. Only the immutable captured items can
            # start, and every start observes cancellation after the run wait.
            with self.store.batch_window(batch_id):
                state = self._load(batch_id, expected_digest)
                count = len(state["items"])
            for index in range(count):
                with self.store.batch_window(batch_id):
                    state = self._load(batch_id, expected_digest)
                    item = state["items"][index]
                    if item["state"] in {"terminal", "cancelled"}:
                        continue
                    request = OperationRequest.from_dict(state["frozen"]["requests"][index])
                    # Receipt lookup precedes any restart decision, even when
                    # cancellation arrived after the durable start marker.
                    prior = self.store.lookup(request.request_id)
                    if state["cancel_requested"] and item["state"] == "pending":
                        item["state"] = "cancelled"
                        self._save(state)
                        continue
                    if state["cancel_requested"] and prior is None:
                        item["state"] = "cancelled"
                        self._save(state)
                        continue
                    recovering = item["state"] != "pending"
                    item["state"] = "started"
                    state["cursor"] = index
                    self._save(state)
                    delegation = state["frozen"]["delegation"]
                outcome = self.kernel.execute(
                    request, delegation,
                    reconcile=self.reconcile_owner if recovering else None,
                    bind_owner_delegation=True,
                )
                outcome = _require_owner_evidence(outcome)
                with self.store.batch_window(batch_id):
                    # Re-read so a cancellation recorded during the owner call
                    # cannot be overwritten by an older in-memory snapshot.
                    state = self._load(batch_id, expected_digest)
                    previous = state["items"][index]["outcome"]
                    if previous is not None:
                        outcome = _retain_observed_source(OperationOutcome.from_dict(previous), outcome)
                    state["items"][index] = {
                        "state": "recoverable" if outcome.status in _RECOVERABLE else "terminal",
                        "outcome": outcome.to_dict(),
                    }
                    state["cursor"] = index + 1
                    self._save(state)
            return self.inspect(batch_id, expected_digest=expected_digest)

    def _load(self, batch_id: str, expected_digest: str | None = None) -> dict[str, Any]:
        try:
            stored = self.store.lookup(_PREFIX + batch_id)
            if stored is None:
                raise ValueError("missing frozen batch")
            state = stored.outcome.extensions["batch"]
            frozen = state["frozen"]
            if (frozen["batch_id"] != batch_id or _digest(frozen) != stored.intent_digest
                    or expected_digest is not None and expected_digest != stored.intent_digest
                    or type(state["cancel_requested"]) is not bool
                    or len(state["items"]) != len(frozen["requests"])):
                raise ValueError("frozen batch differs from confirmation")
            for raw, item in zip(frozen["requests"], state["items"], strict=True):
                if item["state"] not in {"pending", "started", "terminal", "recoverable", "cancelled"}:
                    raise ValueError("invalid item progress")
                if item["outcome"] is not None:
                    outcome = OperationOutcome.from_dict(item["outcome"])
                    if (outcome.request_id != raw["request_id"] or outcome.operation_id != raw["operation_id"]
                            or outcome.context.to_dict() != raw["context"]):
                        raise ValueError("item evidence differs from original identity")
                    if (item["state"] == "terminal" and outcome.status in _RECOVERABLE
                            or item["state"] == "recoverable" and outcome.status not in _RECOVERABLE
                            or item["state"] in {"pending", "cancelled"}):
                        raise ValueError("item progress cannot suppress its unresolved outcome")
                elif item["state"] in {"terminal", "recoverable"}:
                    raise ValueError("item outcome is missing")
            return dict(state)
        except Exception as exc:
            raise BatchStateUnavailable("batch state unavailable or inconsistent; no new effect admitted") from exc

    def _save(self, state: Mapping[str, Any]) -> None:
        frozen = state["frozen"]
        first = OperationRequest.from_dict(frozen["requests"][0])
        self.store.finalize(_PREFIX + frozen["batch_id"], _digest(frozen),
                            OperationOutcome(_PREFIX + frozen["batch_id"], OperationStatus.RECOVERY_REQUIRED,
                                             "batch.preview", first.context, extensions={"batch": dict(state)}))

    @staticmethod
    def _result(state: Mapping[str, Any]) -> BatchResult:
        frozen = state["frozen"]
        requests = frozen["requests"]
        preview = BatchPreview(
            frozen["batch_id"], _digest(frozen), requests[0]["operation_id"],
            _digest([{key: raw[key] for key in ("targets", "expected_version", "context", "request_id")}
                     for raw in requests]),
            _digest(frozen["selector"]), _digest([raw["arguments"] for raw in requests]),
            _digest(frozen["delegation"]), dict(frozen["policy_ceiling"]), len(requests),
            frozen["limit"], frozen["partial_success_policy"],
        )
        return BatchResult(preview, state["cancel_requested"], tuple(
            BatchItem(raw["request_id"], raw["targets"][0]["artifact_id"], item["state"],
                      None if item["outcome"] is None else OperationOutcome.from_dict(item["outcome"]))
            for raw, item in zip(requests, state["items"], strict=True)
        ))


def _retain_observed_source(previous: OperationOutcome, current: OperationOutcome) -> OperationOutcome:
    """Keep actual observed native proof across a weaker recovery response.

    This never acknowledges success or creates a receipt. In particular it
    must NOT preserve old NOT_APPLIED across a newly journaled recovery attempt.
    """
    source = previous.convergence.source_effect if previous.convergence else None
    current_source = current.convergence.source_effect if current.convergence else None
    preserve = (source is SourceEffectStatus.COMMITTED and current_source is not SourceEffectStatus.COMMITTED
                or source is SourceEffectStatus.UNKNOWN and current.convergence is None)
    old_native, old_authority, old_source = _native_evidence(previous)
    new_native, new_authority, new_source = _native_evidence(current)
    richer_receipt = (bool(old_native) and
                      (not new_native or bool(old_authority) and not new_authority
                       or bool(old_source) and not new_source))
    if not preserve and not (source in {SourceEffectStatus.COMMITTED, SourceEffectStatus.UNKNOWN} and richer_receipt):
        return current
    return replace(
        current, status=OperationStatus.RECOVERY_REQUIRED,
        convergence=previous.convergence if preserve else current.convergence or previous.convergence,
        receipt=previous.receipt,
        extensions={**previous.extensions, **current.extensions,
                    "recovery_result": current.status.value, "observed_source_retained": True},
        warnings=tuple(dict.fromkeys(previous.warnings + current.warnings +
                                    ("previously observed native source/receipt evidence retained; current recovery is unresolved",))),
    )


def _native_evidence(outcome: OperationOutcome) -> tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]]:
    receipt = outcome.receipt
    evidence = {} if receipt is None else receipt.extensions
    native = evidence.get("write") or evidence.get("placement") or {}
    native = native if isinstance(native, Mapping) else {}
    governed = native.get("governed_write", native)
    governed = governed if isinstance(governed, Mapping) else {}
    authority = governed.get("authority_receipt", {})
    authority = authority if isinstance(authority, Mapping) else {}
    source = native.get("source_receipt", {})
    return native, authority, source if isinstance(source, Mapping) else {}


def _require_owner_evidence(outcome: OperationOutcome) -> OperationOutcome:
    """Require preserved owner proof; kernel summary/diagnostics are insufficient.

    Owners remain responsible for interpreting their receipts and GOV remains
    responsible for authority. This check only refuses absent chain stages.
    """
    if outcome.status not in _APPLIED:
        return outcome
    native, authority, source = _native_evidence(outcome)
    if (source.get("outcome") != "written"
            or not authority.get("receipt_id") or authority.get("effect_id") != outcome.request_id
            or authority.get("outcome") != "applied" or not authority.get("source_receipt_ref")
            or outcome.convergence is None or outcome.convergence.source_effect is not SourceEffectStatus.COMMITTED
            or native.get("effect_state", "source_applied") != "source_applied"):
        return replace(outcome, status=OperationStatus.RECOVERY_REQUIRED,
                       warnings=outcome.warnings + ("native source effect and durable GOV receipt are required; reconcile owner evidence",))
    return outcome
