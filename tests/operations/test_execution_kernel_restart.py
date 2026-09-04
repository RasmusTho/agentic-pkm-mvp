from __future__ import annotations

from app.operations.execution_kernel import JsonReceiptStore, OperationExecutionKernel, OwnerExecutionResult, PolicyDecision
from app.operations.contracts import OperationContext, OperationRequest, OperationStatus


def test_receipts_survive_restart_without_sensitive_payloads(tmp_path) -> None:
    ledger = tmp_path / "operation-receipts.json"
    request = OperationRequest(
        "artifact.move",
        "request-1",
        OperationContext("context-1", "generation-1"),
        targets=({"artifact_id": "artifact-1"},),
        arguments={"destination": "archive", "access_token": "secret-value"},
    )
    delegation = {
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
    first = OperationExecutionKernel(
        context_resolver=lambda context: True,
        policy_evaluator=lambda request, delegation: PolicyDecision.allowed("policy-7"),
        handlers={"artifact.move": lambda request: OwnerExecutionResult.succeeded()},
        receipt_store=JsonReceiptStore(ledger),
    ).execute(request, delegation)
    restarted = OperationExecutionKernel(
        context_resolver=lambda context: True,
        policy_evaluator=lambda request, delegation: PolicyDecision.allowed("policy-7"),
        handlers={"artifact.move": lambda request: (_ for _ in ()).throw(AssertionError("must replay"))},
        receipt_store=JsonReceiptStore(ledger),
    ).execute(request, delegation)

    assert first.status is OperationStatus.SUCCEEDED
    assert restarted == first
    assert restarted.receipt is not None
    assert restarted.receipt["request_id"] == "request-1"
    assert "secret-value" not in ledger.read_text()
    assert "access_token" not in ledger.read_text()
