from pathlib import Path
from types import SimpleNamespace

from app.archival.contracts import ArtifactClass, Liveness, LivenessState, OpaqueReference, PolicyProfile, TransitionStage
from app.operations import InMemoryReceiptStore, OperationContext, OperationExecutionKernel, OperationRequest, OperationStatus, PolicyDecision
from app.operations.execution_kernel import ArchivalOperationReceipt, OwnerExecutionResult
from app.operations.archival_operations import ARCHIVE_OPERATION_ID, RESTORE_OPERATION_ID, ArchivalOperationServerConfig, build_archival_operation_handlers


def _request(operation_id: str, *, request_id: str = "request-1", version: object = 7, artifact_class: ArtifactClass = ArtifactClass.SOURCE) -> OperationRequest:
    return OperationRequest(operation_id, request_id, OperationContext("vault", "gen-1"), targets=({"artifact_class": artifact_class.value, "raw_ref": "raw-ref-raw-1"},), expected_version=version)  # type: ignore[arg-type]


def _delegation(operation_id: str) -> dict[str, object]:
    return {"active_context_ref": "vault", "vault_generation": "gen-1", "operation_ids": [operation_id], "policy_version": "policy-1", "principal": "owner", "client": "test", "surface": "test", "receipt_ref": "delegation-1", "authority_class": "governed_effect", "target_ids": [""], "max_targets": 1, "allowed_effects": [operation_id], "expires_at": 4102444800, "revoked": False}


def _kernel(config: ArchivalOperationServerConfig) -> OperationExecutionKernel:
    return OperationExecutionKernel(context_resolver=lambda _context: True, policy_evaluator=lambda _request, _delegation: PolicyDecision.allowed("policy-1"), handlers=build_archival_operation_handlers(config), receipt_store=InMemoryReceiptStore(), version_checker=lambda _request: True, token_validator=lambda _request, _decision: True)


def _owner_result(stage: TransitionStage) -> object:
    receipt = SimpleNamespace(generation=SimpleNamespace(value=7), artifact=SimpleNamespace(owner_native_id=SimpleNamespace(token="raw-1")), receipt_ref=SimpleNamespace(token="receipt-1"), policy_profile=PolicyProfile.RAW_EVIDENCE, stage=stage, liveness=Liveness(LivenessState.ACTIVE, OpaqueReference("test", "evidence")), representation_refs=(SimpleNamespace(opaque_id=SimpleNamespace(token="representation-1")),))
    return SimpleNamespace(transition=SimpleNamespace(stage=stage, liveness=receipt.liveness, receipt=receipt))


def test_operations_dispatch_to_governed_archival_providers(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr("app.operations.archival_operations.resolve_operation_restore_target", lambda raw_ref, *, service_reader: SimpleNamespace(record=SimpleNamespace(id="raw-1"), generation=7, representation_id="representation-1"))
    monkeypatch.setattr("app.operations.archival_operations.run_single_record_archive_operation", lambda proof, **kwargs: calls.append(kwargs["request_id"]) or _owner_result(TransitionStage.RETIRED))
    config = ArchivalOperationServerConfig(Path("/config"), "dev", Path("/vault"))
    outcome = _kernel(config).execute(_request(ARCHIVE_OPERATION_ID), _delegation(ARCHIVE_OPERATION_ID))
    assert outcome.status is OperationStatus.SUCCEEDED
    assert calls == ["request-1"]


def test_archival_outcomes_preserve_liveness_generation_policy_and_receipts(monkeypatch) -> None:
    monkeypatch.setattr("app.operations.archival_operations.resolve_operation_restore_target", lambda raw_ref, *, service_reader: SimpleNamespace(record=SimpleNamespace(id="raw-1"), generation=7, representation_id="representation-1"))
    monkeypatch.setattr("app.operations.archival_operations.run_single_record_restore_operation", lambda proof, **kwargs: _owner_result(TransitionStage.RESTORED))
    config = ArchivalOperationServerConfig(Path("/config"), "dev", Path("/vault"))
    outcome = _kernel(config).execute(_request(RESTORE_OPERATION_ID), _delegation(RESTORE_OPERATION_ID))
    assert outcome.status is OperationStatus.SUCCEEDED
    assert outcome.receipt is not None
    assert outcome.receipt["archival"] == {"artifact_ref": "raw-1", "receipt_ref": "receipt-1", "generation": 7, "artifact_class": "source", "policy": "raw_evidence", "stage": "restored", "liveness": "active", "recovery_ref": None}


def test_archival_failures_are_typed_and_recoverable(monkeypatch) -> None:
    config = ArchivalOperationServerConfig(Path("/config"), "dev", Path("/vault"))
    kernel = _kernel(config)
    assert kernel.execute(_request(ARCHIVE_OPERATION_ID, request_id="human", artifact_class=ArtifactClass.HUMAN), _delegation(ARCHIVE_OPERATION_ID)).status is OperationStatus.NOT_SUPPORTED
    assert kernel.execute(_request(ARCHIVE_OPERATION_ID, request_id="derived", artifact_class=ArtifactClass.DERIVED), _delegation(ARCHIVE_OPERATION_ID)).status is OperationStatus.NOT_SUPPORTED
    monkeypatch.setattr("app.operations.archival_operations.resolve_operation_restore_target", lambda raw_ref, *, service_reader: SimpleNamespace(record=SimpleNamespace(id="raw-1"), generation=7, representation_id="representation-1"))
    assert kernel.execute(_request(ARCHIVE_OPERATION_ID, request_id="stale", version=6), _delegation(ARCHIVE_OPERATION_ID)).status is OperationStatus.CONFLICTED
    monkeypatch.setattr("app.operations.archival_operations.resolve_operation_restore_target", lambda raw_ref, *, service_reader: (_ for _ in ()).throw(RuntimeError()))
    assert kernel.execute(_request(ARCHIVE_OPERATION_ID, request_id="unknown"), _delegation(ARCHIVE_OPERATION_ID)).status is OperationStatus.RECOVERY_REQUIRED


def test_non_archival_handlers_cannot_persist_an_archival_projection() -> None:
    request = _request("artifact.move", request_id="wrong")
    kernel = OperationExecutionKernel(context_resolver=lambda _context: True, policy_evaluator=lambda _request, _delegation: PolicyDecision.allowed("policy-1"), handlers={"artifact.move": lambda _request: OwnerExecutionResult(OperationStatus.SUCCEEDED, archival_receipt=ArchivalOperationReceipt("artifact", "receipt", 0, ArtifactClass.SOURCE, PolicyProfile.RAW_EVIDENCE, TransitionStage.RETIRED, LivenessState.ACTIVE))}, receipt_store=InMemoryReceiptStore(), version_checker=lambda _request: True, token_validator=lambda _request, _decision: True)
    assert kernel.execute(request, _delegation("artifact.move")).status is OperationStatus.NOT_ACKNOWLEDGED
