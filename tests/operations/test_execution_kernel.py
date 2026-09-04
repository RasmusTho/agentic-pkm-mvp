from __future__ import annotations

from app.operations.execution_kernel import (
    InMemoryReceiptStore,
    OperationExecutionKernel,
    OwnerExecutionResult,
    PolicyDecision,
)
from app.operations.contracts import OperationContext, OperationRequest, OperationStatus


def _request(**overrides: object) -> OperationRequest:
    values: dict[str, object] = {
        "operation_id": "artifact.move",
        "request_id": "request-1",
        "context": OperationContext("context-1", "generation-1"),
        "targets": ({"artifact_id": "artifact-1"},),
        "arguments": {"destination": "archive", "secret": "do-not-persist"},
        "expected_version": 4,
    }
    values.update(overrides)
    return OperationRequest(**values)  # type: ignore[arg-type]


def _delegation(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "active_context_ref": "context-1",
        "vault_generation": "generation-1",
        "operation_ids": ["artifact.move"],
        "policy_version": "policy-7",
        "principal": "human-1",
        "client": "test-client",
        "surface": "test",
        "receipt_ref": "delegation-1",
        "authority_class": "governed_effect",
        "target_ids": ["artifact-1"],
        "max_targets": 1,
        "allowed_effects": ["artifact.move"],
        "expires_at": 4102444800,
        "revoked": False,
    }
    values.update(overrides)
    return values


def test_executor_enforces_all_preconditions_before_owner_handler() -> None:
    calls: list[str] = []
    kernel = OperationExecutionKernel(
        context_resolver=lambda context: context.active_context_ref == "context-1",
        policy_evaluator=lambda request, delegation: PolicyDecision.allowed("policy-7"),
        handlers={"artifact.move": lambda request: calls.append(request.request_id) or OwnerExecutionResult.succeeded()},
        receipt_store=InMemoryReceiptStore(),
        version_checker=lambda request: True,
        token_validator=lambda request, decision: True,
    )

    missing_context = kernel.execute(_request(context=OperationContext("", "generation-1")), _delegation())
    wrong_delegation = kernel.execute(_request(request_id="request-2"), _delegation(operation_ids=[]))
    stale_policy = kernel.execute(_request(request_id="request-3"), _delegation(policy_version="policy-6"))
    denied = OperationExecutionKernel(
        context_resolver=lambda context: True,
        policy_evaluator=lambda request, delegation: PolicyDecision.denied("policy-7", "denied"),
        handlers={"artifact.move": lambda request: calls.append("denied") or OwnerExecutionResult.succeeded()},
        receipt_store=InMemoryReceiptStore(),
        version_checker=lambda request: True,
        token_validator=lambda request, decision: True,
    ).execute(_request(request_id="request-4"), _delegation())

    assert [missing_context.status, wrong_delegation.status, stale_policy.status, denied.status] == [
        OperationStatus.INVALID,
        OperationStatus.REJECTED,
        OperationStatus.REJECTED,
        OperationStatus.REJECTED,
    ]
    assert calls == []

    succeeded = kernel.execute(_request(), _delegation())
    assert succeeded.status is OperationStatus.SUCCEEDED
    assert calls == ["request-1"]

    version_conflict = OperationExecutionKernel(
        context_resolver=lambda context: True,
        policy_evaluator=lambda request, delegation: PolicyDecision.allowed("policy-7"),
        handlers={"artifact.move": lambda request: calls.append("stale") or OwnerExecutionResult.succeeded()},
        receipt_store=InMemoryReceiptStore(),
        version_checker=lambda request: False,
        token_validator=lambda request, decision: True,
    ).execute(_request(request_id="request-5"), _delegation())
    assert version_conflict.status is OperationStatus.CONFLICTED
    assert calls == ["request-1"]


def test_idempotency_replay_is_stable_and_intent_mismatch_conflicts() -> None:
    calls: list[str] = []
    kernel = OperationExecutionKernel(
        context_resolver=lambda context: True,
        policy_evaluator=lambda request, delegation: PolicyDecision.allowed("policy-7"),
        handlers={"artifact.move": lambda request: calls.append(request.request_id) or OwnerExecutionResult.succeeded()},
        receipt_store=InMemoryReceiptStore(),
        version_checker=lambda request: True,
        token_validator=lambda request, decision: True,
    )
    delegation = _delegation()

    first = kernel.execute(_request(), delegation)
    replay = kernel.execute(_request(), delegation)
    mismatch = kernel.execute(_request(arguments={"destination": "different"}), delegation)

    assert first.status is OperationStatus.SUCCEEDED
    assert replay == first
    assert mismatch.status is OperationStatus.CONFLICTED
    assert calls == ["request-1"]


def test_ambiguous_owner_outcome_is_fail_closed_and_recoverable() -> None:
    calls: list[str] = []
    kernel = OperationExecutionKernel(
        context_resolver=lambda context: True,
        policy_evaluator=lambda request, delegation: PolicyDecision.allowed("policy-7"),
        handlers={"artifact.move": lambda request: calls.append(request.request_id) or OwnerExecutionResult.ambiguous()},
        receipt_store=InMemoryReceiptStore(),
        version_checker=lambda request: True,
        token_validator=lambda request, decision: True,
    )

    first = kernel.execute(_request(), _delegation())
    replay = kernel.execute(_request(), _delegation())

    assert first.status is OperationStatus.RECOVERY_REQUIRED
    assert replay == first
    assert first.receipt is not None
    assert first.receipt["recovery"] == "read_receipt_before_retry"
    assert calls == ["request-1"]
