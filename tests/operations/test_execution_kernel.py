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


def _owner_success() -> OwnerExecutionResult:
    return OwnerExecutionResult.succeeded(
        effect_id="effect-1", effect_receipt={"receipt_id": "owner-receipt-1"}
    )


def test_executor_enforces_all_preconditions_before_owner_handler() -> None:
    calls: list[str] = []
    kernel = OperationExecutionKernel(
        context_resolver=lambda context: context.active_context_ref == "context-1",
        policy_evaluator=lambda request, delegation: PolicyDecision.allowed("policy-7"),
        handlers={
            "artifact.move": lambda request: calls.append(request.request_id)
            or _owner_success()
        },
        receipt_store=InMemoryReceiptStore(),
        version_checker=lambda request: True,
        token_validator=lambda request, decision: True,
    )

    missing_context = kernel.execute(
        _request(context=OperationContext("", "generation-1")), _delegation()
    )
    wrong_delegation = kernel.execute(
        _request(request_id="request-2"), _delegation(operation_ids=[])
    )
    stale_policy = kernel.execute(
        _request(request_id="request-3"), _delegation(policy_version="policy-6")
    )
    denied = OperationExecutionKernel(
        context_resolver=lambda context: True,
        policy_evaluator=lambda request, delegation: PolicyDecision.denied("policy-7", "denied"),
        handlers={
            "artifact.move": lambda request: calls.append("denied")
            or _owner_success()
        },
        receipt_store=InMemoryReceiptStore(),
        version_checker=lambda request: True,
        token_validator=lambda request, decision: True,
    ).execute(_request(request_id="request-4"), _delegation())

    assert [
        missing_context.status,
        wrong_delegation.status,
        stale_policy.status,
        denied.status,
    ] == [
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
        handlers={
            "artifact.move": lambda request: calls.append("stale")
            or _owner_success()
        },
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
        handlers={
            "artifact.move": lambda request: calls.append(request.request_id)
            or _owner_success()
        },
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
        handlers={
            "artifact.move": lambda request: calls.append(request.request_id)
            or OwnerExecutionResult.ambiguous()
        },
        receipt_store=InMemoryReceiptStore(),
        version_checker=lambda request: True,
        token_validator=lambda request, decision: True,
    )

    first = kernel.execute(_request(), _delegation())
    replay = kernel.execute(_request(), _delegation())

    assert first.status is OperationStatus.RECOVERY_REQUIRED
    assert replay == first
    assert first.receipt is not None
    assert first.receipt.payload["recovery"] == "read_receipt_before_retry"
    assert calls == ["request-1"]


def test_success_requires_owner_receipt_before_acknowledgement() -> None:
    kernel = OperationExecutionKernel(
        context_resolver=lambda context: True,
        policy_evaluator=lambda request, delegation: PolicyDecision.allowed("policy-7"),
        handlers={
            "artifact.move": lambda request: OwnerExecutionResult.succeeded(effect_id="effect-1")
        },
        receipt_store=InMemoryReceiptStore(),
        version_checker=lambda request: True,
        token_validator=lambda request, decision: True,
    )

    outcome = kernel.execute(_request(), _delegation())

    assert outcome.status is OperationStatus.RECOVERY_REQUIRED
    assert outcome.receipt is not None
    assert outcome.receipt.payload["state"] == "recovery_required"
    assert outcome.receipt.payload["effect_id"] == "effect-1"

    missing_effect_identity = OperationExecutionKernel(
        context_resolver=lambda context: True,
        policy_evaluator=lambda request, delegation: PolicyDecision.allowed("policy-7"),
        handlers={
            "artifact.move": lambda request: OwnerExecutionResult.succeeded(
                effect_receipt={"receipt_id": "owner-receipt-1"}
            )
        },
        receipt_store=InMemoryReceiptStore(),
        version_checker=lambda request: True,
        token_validator=lambda request, decision: True,
    ).execute(_request(request_id="request-2"), _delegation())

    assert missing_effect_identity.status is OperationStatus.RECOVERY_REQUIRED
    assert missing_effect_identity.receipt is not None
    assert missing_effect_identity.receipt.payload["effect_receipt_ref"] == "owner-receipt-1"


def test_multi_target_request_requires_bound_batch_policy() -> None:
    policy_calls: list[str] = []
    owner_calls: list[str] = []
    owner_batch_policies: list[object] = []
    kernel = OperationExecutionKernel(
        context_resolver=lambda context: True,
        policy_evaluator=lambda request, delegation: policy_calls.append(request.request_id)
        or PolicyDecision.allowed("policy-7"),
        handlers={
            "artifact.move": lambda request: owner_calls.append(request.request_id)
            or owner_batch_policies.append(request.batch_policy)
            or _owner_success()
        },
        receipt_store=InMemoryReceiptStore(),
        version_checker=lambda request: True,
        token_validator=lambda request, decision: True,
    )
    request = _request(
        targets=({"artifact_id": "artifact-1"}, {"artifact_id": "artifact-2"})
    )
    delegation = _delegation(target_ids=["artifact-1", "artifact-2"], max_targets=2)

    outcome = kernel.execute(request, delegation)

    assert outcome.status is OperationStatus.REJECTED
    assert policy_calls == []
    assert owner_calls == []

    admitted = kernel.execute(
        request,
        _delegation(
            target_ids=["artifact-1", "artifact-2"],
            max_targets=2,
            batch_policy={"mode": "atomic"},
        ),
    )

    assert admitted.status is OperationStatus.SUCCEEDED
    assert policy_calls == ["request-1"]
    assert owner_calls == ["request-1"]
    assert owner_batch_policies == [{"mode": "atomic"}]


def test_target_identity_is_required_before_dispatch() -> None:
    policy_calls: list[str] = []
    owner_calls: list[str] = []
    kernel = OperationExecutionKernel(
        context_resolver=lambda context: True,
        policy_evaluator=lambda request, delegation: policy_calls.append(request.request_id)
        or PolicyDecision.allowed("policy-7"),
        handlers={
            "artifact.move": lambda request: owner_calls.append(request.request_id)
            or _owner_success()
        },
        receipt_store=InMemoryReceiptStore(),
        version_checker=lambda request: True,
        token_validator=lambda request, decision: True,
    )

    outcome = kernel.execute(_request(targets=({},)), _delegation(target_ids=[""]))

    assert outcome.status is OperationStatus.REJECTED
    assert policy_calls == []
    assert owner_calls == []
