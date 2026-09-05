from app.operations import OperationContext, OperationRequest, OperationStatus
from app.operations.archival_operations import ArchivalOperationAdapters


def _request(kind: str, artifact_class: str = "media") -> OperationRequest:
    return OperationRequest(kind, "request-1", OperationContext("vault", "gen-1"), targets=({"artifact_class": artifact_class},))


def test_operations_dispatch_to_governed_archival_providers() -> None:
    calls = []
    adapters = ArchivalOperationAdapters({"media": lambda request: calls.append(request.operation_id) or {"state": "complete"}})
    assert adapters.execute(_request("archive")).status is OperationStatus.SUCCEEDED
    assert adapters.execute(_request("restore")).status is OperationStatus.SUCCEEDED
    assert calls == ["archive", "restore"]


def test_archival_outcomes_preserve_liveness_generation_policy_and_receipts() -> None:
    payload = {"state": "complete", "liveness": "retired", "generation": "g-7", "policy": "retain", "receipt": {"id": "r-1"}}
    outcome = ArchivalOperationAdapters({"media": lambda _request: payload}).execute(_request("archive"))
    assert outcome.items == (payload,)


def test_archival_failures_are_typed_and_recoverable() -> None:
    adapters = ArchivalOperationAdapters({"media": lambda _request: {"state": "stale", "recovery": "reload"}})
    assert adapters.execute(_request("restore")).status is OperationStatus.RECOVERY_REQUIRED
    assert adapters.execute(_request("archive", "hka")).status is OperationStatus.NOT_SUPPORTED
    assert adapters.execute(_request("archive", "unknown")).status is OperationStatus.NOT_SUPPORTED
