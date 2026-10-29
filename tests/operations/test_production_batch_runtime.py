from fastapi import Request

from app.api.batch_operation_runtime import build_production_batch_runtime
from app.operations.batch_operations import BatchOperationCoordinator
from app.operations.execution_kernel import JsonReceiptStore, OperationExecutionKernel
from tests._production_batch_harness import batch_action, batch_command, preview_batch, production_batch_host


def test_batch_runtime_uses_qualified_canonical_kernel_and_journal(tmp_path, monkeypatch):
    host, sources = production_batch_host(tmp_path, monkeypatch)
    runtime = build_production_batch_runtime(Request({"type": "http", "method": "GET", "headers": [],
        "client": ("testclient", 5000)}), api_key=None,
        session_bearer=host.selection["context_selection_id"], override_bearer=None)
    assert runtime.supported_kinds == {"artifact.update", "artifact.move", "artifact.rename"}
    discovery = host.client.get("/api/operations/capabilities", headers=host.headers).json()
    batch = next(item["payload"] for item in discovery["items"] if item["resource_id"] == "operation.batch")
    assert batch["support"] == "supported"
    assert set(batch["supported_kinds"]) == runtime.supported_kinds
    assert batch["max_targets"] == 100
    preview = preview_batch(host, batch_command(host, sources))
    coordinator, frozen, admitted = runtime._retained(preview["batch_id"], preview["digest"], for_effect=True)
    assert admitted and isinstance(coordinator, BatchOperationCoordinator)
    assert isinstance(coordinator.kernel, OperationExecutionKernel)
    assert isinstance(coordinator.store, JsonReceiptStore)
    assert coordinator.store is runtime.base.kernel.receipt_store
    assert coordinator.store.path == host.runtime.registry.path.parent / "operation-receipts.json"
    assert frozen["delegation"]["expires_at"] == host.selection["context"]["expires_at"]
    result = batch_action(host, preview)
    assert result.status_code == 200 and result.json()["counts"]["completed"] == 2, result.text
    assert all(item["outcome"]["receipt"]["extensions"]["write"]["authority_receipt"]["receipt_id"]
               for item in result.json()["items"])
