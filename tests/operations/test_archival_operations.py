from pathlib import Path
from types import SimpleNamespace

from app.archival.contracts import ArtifactClass
from app.operations import InMemoryReceiptStore, OperationContext, OperationExecutionKernel, OperationRequest, OperationStatus, PolicyDecision
from app.operations.archival_operations import ArchivalOperationAdapters, SourceArchiveInvocation, SourceRestoreInvocation


def _request(kind: str, *, request_id: str = "request-1", artifact_class: ArtifactClass = ArtifactClass.SOURCE) -> OperationRequest:
    return OperationRequest(kind, request_id, OperationContext("vault", "gen-1"), targets=({"artifact_id": "raw-1", "artifact_class": artifact_class.value},))


def _delegation(kind: str) -> dict[str, object]:
    return {"active_context_ref": "vault", "vault_generation": "gen-1", "operation_ids": [kind], "policy_version": "policy-1", "principal": "owner", "client": "test", "surface": "test", "receipt_ref": "delegation-1", "authority_class": "governed_effect", "target_ids": ["raw-1"], "max_targets": 1, "allowed_effects": [kind], "expires_at": 4102444800, "revoked": False}


def _kernel(adapters: ArchivalOperationAdapters) -> OperationExecutionKernel:
    return OperationExecutionKernel(context_resolver=lambda _context: True, policy_evaluator=lambda _request, _delegation: PolicyDecision.allowed("policy-1"), handlers=adapters.handlers(), receipt_store=InMemoryReceiptStore(), version_checker=lambda _request: True, token_validator=lambda _request, _decision: True)


def test_operations_dispatch_to_governed_archival_providers(monkeypatch) -> None:
    calls: list[tuple[object, Path, str]] = []
    monkeypatch.setattr("app.heimdal.local_archive.relocate_raw_record", lambda record, *, archive_root, archive_ref, volume_ready: calls.append((record, archive_root, archive_ref)) or SimpleNamespace(receipt=SimpleNamespace(record_id="raw-1", raw_generation=7, receipt_id="archive-r")))
    adapters = ArchivalOperationAdapters.production(lambda _request: SourceArchiveInvocation("record", Path("/archive"), "archive-ref", lambda: object()))
    outcome = _kernel(adapters).execute(_request("archive"), _delegation("archive"))
    assert outcome.status is OperationStatus.SUCCEEDED
    assert calls == [("record", Path("/archive"), "archive-ref")]


def test_archival_outcomes_preserve_liveness_generation_policy_and_receipts(monkeypatch) -> None:
    monkeypatch.setattr("app.heimdal.local_archive.run_restore_drill", lambda raw_ref, *, reader, key: SimpleNamespace(read_receipt_id="restore-r"))
    adapters = ArchivalOperationAdapters.production(lambda _request: SourceRestoreInvocation("opaque-raw-ref", "reader", "raw-1", "g-7", "restored"))
    outcome = _kernel(adapters).execute(_request("restore"), _delegation("restore"))
    assert outcome.status is OperationStatus.SUCCEEDED
    assert outcome.receipt is not None
    assert outcome.receipt["archival_bindings"] == {"artifact_id": "raw-1", "generation": "g-7", "liveness": "restored", "policy": "raw_evidence", "receipt_ref": "restore-r"}
    assert outcome.items[0]["generation"] == "[redacted]"


def test_archival_failures_are_typed_and_recoverable() -> None:
    resolver_calls: list[str] = []
    adapters = ArchivalOperationAdapters.production(lambda request: resolver_calls.append(request.request_id) or SourceRestoreInvocation("opaque", "reader", "raw-1", "g-7", "restored"))
    kernel = _kernel(adapters)
    assert kernel.execute(_request("archive", request_id="derived", artifact_class=ArtifactClass.DERIVED), _delegation("archive")).status is OperationStatus.NOT_SUPPORTED
    human = kernel.execute(_request("archive", request_id="human", artifact_class=ArtifactClass.HUMAN), _delegation("archive"))
    assert human.status is OperationStatus.NOT_SUPPORTED
    assert human.warnings == ("owner_decision_required:#5325",)
    assert kernel.execute(_request("archive", request_id="mismatch"), _delegation("archive")).status is OperationStatus.NOT_ACKNOWLEDGED
    assert resolver_calls == ["mismatch"]
