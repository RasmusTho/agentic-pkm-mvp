from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event

import pytest
from fastapi.testclient import TestClient

from app.api.app import _create_app
from app.api.routes import active_context_selection
from app.operations.execution_kernel import JsonReceiptStore
from tests._production_batch_harness import (
    batch_action, batch_command, batch_inspect, preview_batch, production_batch_host,
)


def test_batch_restart_cancel_and_uncertain_recovery_preserve_owner_truth(tmp_path, monkeypatch):
    host, sources = production_batch_host(tmp_path, monkeypatch)
    preview = preview_batch(host, batch_command(host, sources))
    finalize = JsonReceiptStore.finalize
    failed = False

    def disconnected(store, request_id, *args, **kwargs):
        nonlocal failed
        if request_id == "batch-1:0" and not failed:
            failed = True
            raise ConnectionError("lost kernel acknowledgment after durable native/GOV receipts")
        return finalize(store, request_id, *args, **kwargs)

    monkeypatch.setattr(JsonReceiptStore, "finalize", disconnected)
    first = batch_action(host, preview)
    assert first.status_code == 200, first.text
    first = first.json()
    assert first["status"] == "recovery_required"
    assert first["items"][0]["outcome"]["convergence"]["source_effect"] == "committed"
    native = first["items"][0]["outcome"]["receipt"]["extensions"]["write"]
    journal = JsonReceiptStore(host.runtime.registry.path.parent / "operation-receipts.json")
    original_decision = journal.lookup("batch-1:0").outcome.extensions["admission_decision_digest"]
    assert batch_action(host, preview, "cancel").json()["cancel_requested"]
    after = [note.read_bytes() for _, note in sources]
    monkeypatch.setattr(JsonReceiptStore, "finalize", finalize)
    import app.operations.write_operations as writes
    monkeypatch.setattr(writes, "write_note_from_absolute",
        lambda *a, **k: pytest.fail("component restart recovery must read native evidence without repeating body writes"))
    # Recreate the application and all runtime/coordinator/kernel instances;
    # the original WSP selection is still current in this process.
    host.client = TestClient(_create_app())
    recovered = batch_action(host, preview)
    assert recovered.status_code == 200, recovered.text
    recovered = recovered.json()
    assert recovered["status"] == "convergence_pending" and recovered["cancel_requested"]
    assert recovered["counts"]["completed"] == 2
    assert recovered["items"][0]["outcome"]["receipt"]["extensions"]["write"] == native
    assert journal.lookup("batch-1:0").outcome.extensions["admission_decision_digest"] == original_decision
    assert [note.read_bytes() for _, note in sources] == after
    assert batch_action(host, preview).json() == recovered


@pytest.mark.parametrize("known", [True, False])
def test_full_wsp_restart_preserves_retained_truth_without_new_authority(tmp_path, monkeypatch, known):
    host, sources = production_batch_host(tmp_path, monkeypatch)
    command = batch_command(host, sources)
    preview = preview_batch(host, command)
    import app.operations.write_operations as writes
    write = writes.write_note_from_absolute
    finalize = JsonReceiptStore.finalize
    failed = False

    def disconnect_after_native(*args, **kwargs):
        nonlocal failed
        source = write(*args, **kwargs)
        if not failed:
            failed = True
            raise OSError("native effect may have completed before caller observed a receipt")
        return source

    def lost_ack(store, request_id, *args, **kwargs):
        nonlocal failed
        if request_id == "batch-1:0" and not failed:
            failed = True
            raise OSError("kernel acknowledgment lost")
        return finalize(store, request_id, *args, **kwargs)

    if known:
        monkeypatch.setattr(JsonReceiptStore, "finalize", lost_ack)
    else:
        monkeypatch.setattr(writes, "write_note_from_absolute", disconnect_after_native)
    before = batch_action(host, preview)
    assert before.status_code == 200, before.text
    before = before.json()
    assert before["status"] == "recovery_required"
    assert (before["items"][0]["outcome"].get("convergence") or {}).get("source_effect", "unknown") == (
        "committed" if known else "unknown")
    after = [note.read_bytes() for _, note in sources]
    journal = JsonReceiptStore(host.runtime.registry.path.parent / "operation-receipts.json")
    frozen = journal.lookup("ygg.batch:batch-1").outcome.extensions["batch"]["frozen"]
    monkeypatch.setattr(JsonReceiptStore, "finalize", finalize)
    monkeypatch.setattr(writes, "write_note_from_absolute",
        lambda *a, **k: pytest.fail("new selection must never retry old source effects"))
    old_headers = dict(host.headers)
    active_context_selection.reset_selection_store_for_tests()
    host.client = TestClient(_create_app())
    assert host.client.get("/api/operations/batches/batch-1", headers=old_headers,
                          params={"expected_digest": preview["digest"]}).status_code == 401
    selected = host.client.post("/api/companion/active-context/selection",
                               json={"vault_binding_ids": [host.binding_id]})
    assert selected.status_code == 201
    host.selection = selected.json()
    host.headers = {"X-Active-Context-Session": host.selection["context_selection_id"]}
    from app.governance.governed_write import GovernedWriteAdapter
    monkeypatch.setattr(GovernedWriteAdapter, "issue_decision_token",
        lambda *a, **k: pytest.fail("retained inspection/recovery cannot issue replacement authority"))
    inspected = batch_inspect(host, preview)
    assert inspected.status_code == 200, inspected.text
    inspected = inspected.json()
    assert inspected["current_admission"] == "refused" and inspected["status"] == "recovery_required"
    assert inspected["items"][1]["outcome"] == before["items"][1]["outcome"]
    assert batch_action(host, preview, "cancel").json()["cancel_requested"]
    recovered = batch_action(host, preview)
    assert recovered.status_code == 200, recovered.text
    recovered = recovered.json()
    assert recovered["current_admission"] == "refused" and recovered["cancel_requested"]
    assert recovered["status"] == "recovery_required"
    if known:
        assert inspected["items"][0]["outcome"]["extensions"]["owner_readback"]["effect_receipt"]["write"]["authority_receipt"]["receipt_id"]
    else:
        assert "owner_readback" not in inspected["items"][0]["outcome"]["extensions"]
        assert recovered["counts"]["ambiguous"] == 1
    assert journal.lookup("ygg.batch:batch-1").outcome.extensions["batch"]["frozen"] == frozen
    assert [note.read_bytes() for _, note in sources] == after


@pytest.mark.parametrize("phase", ["prepared", "activated"])
def test_placement_component_restart_uses_original_native_intent_and_decision(tmp_path, monkeypatch, phase):
    from app.knowledge.placement import KnowledgePlacementOwner
    host, sources = production_batch_host(tmp_path, monkeypatch)
    preview = preview_batch(host, batch_command(host, sources, kind="artifact.rename"))
    store = KnowledgePlacementOwner._store
    failed = False

    def interrupt(owner, root, state, name, value):
        nonlocal failed
        store(owner, root, state, name, value)
        if value["intent"]["request_id"] == "batch-1:0" and value["phase"] == phase and not failed:
            failed = True
            raise OSError("process lost at durable placement frontier")

    monkeypatch.setattr(KnowledgePlacementOwner, "_store", interrupt)
    initial = batch_action(host, preview)
    assert initial.status_code == 200, initial.text
    assert initial.json()["status"] == "recovery_required"
    journal = JsonReceiptStore(host.runtime.registry.path.parent / "operation-receipts.json")
    original = journal.lookup("batch-1:0").outcome.extensions["admission_decision_digest"]
    monkeypatch.setattr(KnowledgePlacementOwner, "_store", store)
    host.client = TestClient(_create_app())
    recovered = batch_action(host, preview)
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["counts"]["completed"] == 2, recovered.text
    assert journal.lookup("batch-1:0").outcome.extensions["admission_decision_digest"] == original
    for index, (identity, old) in enumerate(sources):
        assert not old.exists()
        assert identity in (host.root / "Notes" / f"renamed-{index}.md").read_text()
    assert batch_action(host, preview).json()["items"] == recovered.json()["items"]


def test_http_cancel_and_queued_consumers_preserve_started_effect(tmp_path, monkeypatch):
    from app.api.batch_operation_runtime import ProductionBatchRuntime
    from app.operations.batch_operations import BatchOperationCoordinator
    import app.operations.write_operations as writes
    host, sources = production_batch_host(tmp_path, monkeypatch, count=3)
    preview = preview_batch(host, batch_command(host, sources))
    cancel_admitted, cancel_now, started, release = Event(), Event(), Event(), Event()
    cancel = ProductionBatchRuntime.cancel
    write = writes.write_note_from_absolute
    calls = []
    consumers = Barrier(2)
    execute = BatchOperationCoordinator.execute

    def admitted_execute(coordinator, *args, **kwargs):
        consumers.wait(timeout=10)
        return execute(coordinator, *args, **kwargs)

    def queued_cancel(runtime, *args, **kwargs):
        cancel_admitted.set()
        assert cancel_now.wait(10)
        return cancel(runtime, *args, **kwargs)

    def paused_write(*args, **kwargs):
        calls.append(args[0])
        started.set()
        assert release.wait(10)
        return write(*args, **kwargs)

    monkeypatch.setattr(ProductionBatchRuntime, "cancel", queued_cancel)
    monkeypatch.setattr(BatchOperationCoordinator, "execute", admitted_execute)
    monkeypatch.setattr(writes, "write_note_from_absolute", paused_write)
    with ThreadPoolExecutor(max_workers=3) as pool:
        cancelled = pool.submit(batch_action, host, preview, "cancel")
        assert cancel_admitted.wait(10)
        executor = pool.submit(batch_action, host, preview)
        queued = pool.submit(batch_action, host, preview)
        assert started.wait(10)
        # The cancel HTTP request was authenticated before the source window;
        # its journal cancellation can persist while that effect is started.
        cancel_now.set()
        cancellation = cancelled.result(10)
        assert cancellation.status_code == 200, cancellation.text
        assert cancellation.json()["cancel_requested"]
        assert cancellation.json()["counts"]["cancelled"] == 2
        release.set()
        result = executor.result(10)
        second = queued.result(10)
    assert result.status_code == second.status_code == 200
    assert result.json()["cancel_requested"] and second.json()["cancel_requested"]
    assert result.json()["counts"]["completed"] == 1
    assert result.json()["counts"]["cancelled"] == 2
    assert second.json()["items"] == result.json()["items"]
    assert len(calls) == 1
    assert sources[0][1].read_text().endswith("HTTP batch body 0.\n")
    assert all("Original" in note.read_text() for _, note in sources[1:])



def test_missing_gov_receipt_keeps_committed_source_recoverable(tmp_path, monkeypatch):
    from app.governance.governed_write import GovernedWriteAdapter
    import app.operations.write_operations as writes
    host, sources = production_batch_host(tmp_path, monkeypatch)
    preview = preview_batch(host, batch_command(host, sources))
    record = GovernedWriteAdapter.record_authority_receipt

    def missing(self, **kwargs):
        if kwargs.get("effect_id") == "batch-1:0":
            raise OSError("GOV receipt is not durably available")
        return record(self, **kwargs)

    monkeypatch.setattr(GovernedWriteAdapter, "record_authority_receipt", missing)
    initial = batch_action(host, preview)
    assert initial.status_code == 200, initial.text
    initial = initial.json()
    assert initial["status"] == "recovery_required" and initial["counts"]["completed"] == 1
    proof = initial["items"][0]["outcome"]
    assert proof["convergence"]["source_effect"] == "committed"
    assert "authority_receipt" not in proof["receipt"]["extensions"]["write"]
    after = [note.read_bytes() for _, note in sources]
    monkeypatch.setattr(GovernedWriteAdapter, "record_authority_receipt", record)
    monkeypatch.setattr(writes, "write_note_from_absolute",
        lambda *a, **k: pytest.fail("missing GOV receipt cannot authorize replay of committed source"))
    host.client = TestClient(_create_app())
    recovered = batch_action(host, preview)
    assert recovered.status_code == 200, recovered.text
    result = recovered.json()
    assert result["status"] == "recovery_required" and result["counts"]["completed"] == 1
    assert result["items"][0]["outcome"]["convergence"]["source_effect"] == "committed"
    assert "authority_receipt" not in result["items"][0]["outcome"]["receipt"]["extensions"]["write"]
    assert [note.read_bytes() for _, note in sources] == after
