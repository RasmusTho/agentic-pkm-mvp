from fastapi.testclient import TestClient

from app.api.app import _create_app
from app.api.routes import active_context_selection
from app.operations.execution_kernel import JsonReceiptStore
from tests._production_operation_harness import production_operation_host


def test_disconnect_and_restart_reconcile_durable_operation_receipt(tmp_path, monkeypatch):
    host = production_operation_host(tmp_path, monkeypatch)
    command = host.command()
    original_finalize = JsonReceiptStore.finalize

    def disconnected(self, *args, **kwargs):
        raise ConnectionError("disconnect after native effect and receipt")

    monkeypatch.setattr(JsonReceiptStore, "finalize", disconnected)
    result = host.client.post("/api/operations", headers=host.headers, json=command)
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "recovery_required", result.text
    assert result.json()["convergence"]["source_effect"] == "committed"
    assert result.json()["extensions"]["owner_readback"]["effect_receipt_ref"]
    after = host.note.read_bytes()
    monkeypatch.setattr(JsonReceiptStore, "finalize", original_finalize)
    retry = host.client.post("/api/operations", headers=host.headers, json=command)
    assert retry.json()["status"] == "recovery_required"
    assert host.note.read_bytes() == after
    active_context_selection.reset_selection_store_for_tests()
    restarted = TestClient(_create_app())
    assert restarted.post("/api/operations", headers=host.headers, json=command).status_code == 401
    selection = restarted.post("/api/companion/active-context/selection",
        json={"vault_binding_ids": [host.binding_id]}).json()
    readback = restarted.get("/api/operations/receipts/update-1",
        headers={"X-Active-Context-Session": selection["context_selection_id"]})
    assert readback.status_code == 200, readback.text
    assert readback.json()["status"] == "recovery_required"
    assert host.note.read_bytes() == after
