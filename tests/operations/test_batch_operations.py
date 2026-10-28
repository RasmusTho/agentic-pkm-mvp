from dataclasses import replace
import json

import pytest

from app.knowledge import semantic
from app.operations import JsonReceiptStore, OperationStatus, OwnerExecutionResult
from app.operations.batch_operations import (
    BatchOperationCoordinator, BatchStateUnavailable, SUPPORTED_BATCH_OPERATIONS,
)
from app.operations import placement_operations, write_operations
from app.operations.contracts import SourceEffectStatus
from tests.operations import test_semantic_operations, test_placement_operations, test_write_operations
from tests.operations.test_placement_operations import (
    _request as placement_request, _kernel as placement_kernel,
    _restart as placement_restart,
)
from tests.operations.test_write_operations import (
    _request as write_request, _kernel as write_kernel,
)

semantic_bound = test_semantic_operations.bound
placement_bound = test_placement_operations.bound
write_bound = test_write_operations.bound
from tests.operations._batch_harness import (
    Interrupted, coordinator, delegation_for, execute, native_receipt, preview, requests_for, source_tags,
)


def test_batch_preview_binds_scope_digest_policy_and_limit(semantic_bound):
    requests, paths = requests_for(semantic_bound, 2)
    batch = coordinator(semantic_bound)
    selector = {"ids": [r.targets[0]["artifact_id"] for r in requests]}
    delegation = delegation_for(requests)
    frozen = batch.preview(batch_id="frozen", requests=requests, selector=selector,
                           delegation=delegation, limit=2)
    assert frozen.cardinality == frozen.limit == 2
    assert frozen.operation_id == "artifact.tags.add"
    assert frozen.policy_ceiling["policy_version"] == "policy-1"
    assert frozen.partial_success_policy == "independent"
    assert len({frozen.digest, frozen.candidate_digest, frozen.selector_digest,
                frozen.argument_digest, frozen.delegation_digest}) == 5
    with pytest.raises(ValueError, match="cardinality"):
        batch.preview(batch_id="oversized", requests=requests, selector=selector,
                      delegation=delegation, limit=1)
    with pytest.raises(ValueError, match="cardinality"):
        batch.preview(batch_id="grant-limit", requests=requests, selector=selector,
                      delegation={**delegation, "max_targets": 1}, limit=2)
    selector["ids"].append("another-target")
    delegation["target_ids"].clear()
    requests[0].arguments["tags"].append("unconfirmed")
    with pytest.raises(BatchStateUnavailable):
        batch.execute("frozen", expected_digest="0" * 64)
    result = execute(batch, frozen)
    assert result.counts["completed"] == 2
    assert all(source_tags(path) == ["reviewed"] for path in paths)
    assert batch.inspect("frozen", expected_digest=frozen.digest).preview == frozen
    assert frozen.digest not in paths[0].read_text()


def test_batch_execution_preserves_every_item_outcome_and_aggregate_truth(semantic_bound):
    requests, paths = requests_for(semantic_bound)
    batch = coordinator(semantic_bound)
    frozen = preview(batch, requests)
    paths[1].write_text(paths[1].read_text() + "A later human edit.\n")
    semantic_bound.revoke_approval(requests[2].request_id)
    result = execute(batch, frozen)
    assert [item.outcome.status for item in result.items] == [
        OperationStatus.CONVERGENCE_PENDING, OperationStatus.CONFLICTED, OperationStatus.REJECTED]
    assert result.status == "partial"
    assert result.counts == {"completed": 1, "conflicted": 1, "refused": 1, "ambiguous": 0,
                             "pending": 0, "cancelled": 0, "recoverable": 0, "convergence_pending": 1}
    receipt = native_receipt(result.items[0])
    assert receipt["source_receipt"]["outcome"] == "written"
    assert receipt["authority_receipt"]["effect_id"] == requests[0].request_id
    assert receipt["authority_receipt"]["receipt_id"] == semantic_bound.records()[0]["receipt_id"]
    assert [source_tags(path) for path in paths] == [["reviewed"], [], []]
    assert execute(coordinator(semantic_bound, restart=True), frozen) == result


def test_batch_candidate_drift_conflicts_without_scope_expansion(semantic_bound):
    requests, paths = requests_for(semantic_bound, 2)
    batch = coordinator(semantic_bound)
    frozen = preview(batch, requests)
    paths[1].write_text(paths[1].read_text().replace("tags: []", "tags: [human]"))
    extra = semantic_bound.owner.root / "Notes/new-candidate.md"
    extra.write_text("---\ntags: []\n---\nNew selector match after confirmation.\n")
    with pytest.raises(ValueError, match="already bound"):
        preview(batch, [requests[0]])
    result = execute(batch, frozen)
    assert result.counts["completed"] == result.counts["conflicted"] == 1
    assert source_tags(paths[1]) == ["human"] and source_tags(extra) == []
    assert len(result.items) == 2 and result.preview.candidate_digest == frozen.candidate_digest


def test_batch_production_owner_receipt_is_required_before_success(semantic_bound, monkeypatch):
    requests, paths = requests_for(semantic_bound, 1)
    batch = coordinator(semantic_bound)
    frozen = preview(batch, requests)
    calls = []
    source_write = semantic.write_note_from_absolute

    def observed(*args, **kwargs):
        calls.append(kwargs["expected_version"])
        return source_write(*args, **kwargs)

    monkeypatch.setattr(semantic, "write_note_from_absolute", observed)
    with monkeypatch.context() as patch:
        patch.setattr(semantic, "append_jsonl_outbox_event", lambda *_a, **_k: False)
        first = execute(batch, frozen)
    assert first.status == "recovery_required" and first.counts["completed"] == 0
    assert first.items[0].outcome.convergence.source_effect is SourceEffectStatus.COMMITTED
    assert native_receipt(first.items[0])["source_receipt"]["outcome"] == "written"
    assert not semantic_bound.owner.receipt_path.exists()
    resumed = execute(coordinator(semantic_bound, restart=True), frozen)
    assert resumed.status == "recovery_required" and resumed.counts["completed"] == 0
    assert resumed.items[0].outcome.convergence.source_effect is SourceEffectStatus.COMMITTED
    assert calls == [requests[0].expected_version] and source_tags(paths[0]) == ["reviewed"]


def test_durable_semantic_receipt_repairs_a_lost_kernel_finalization(semantic_bound, monkeypatch):
    requests, paths = requests_for(semantic_bound, 1)
    batch = coordinator(semantic_bound)
    frozen = preview(batch, requests)
    finalize = batch.store.finalize

    def lose_result(request_id, *args):
        if request_id == requests[0].request_id:
            raise OSError("kernel result persistence interrupted")
        return finalize(request_id, *args)

    with monkeypatch.context() as patch:
        patch.setattr(batch.store, "finalize", lose_result)
        first = execute(batch, frozen)
    assert first.status == "recovery_required"
    raw = paths[0].read_bytes()
    recovered = execute(coordinator(semantic_bound, restart=True), frozen)
    assert recovered.status == "convergence_pending" and recovered.counts["completed"] == 1
    assert paths[0].read_bytes() == raw and len(semantic_bound.records()) == 1
    assert native_receipt(recovered.items[0])["authority_receipt"]["receipt_id"] == native_receipt(first.items[0])["authority_receipt"]["receipt_id"]


@pytest.mark.parametrize("operation", ["artifact.classify", "artifact.tags.add", "artifact.tags.remove", "collection.reorder"])
def test_each_supported_semantic_kind_preserves_real_owner_receipts(semantic_bound, operation):
    options = {
        "artifact.classify": ({"artifact_type": "concept_note"}, {"artifact_type": "concept_note"}),
        "artifact.tags.add": ({"tags": ["new"]}, {"tags": ["new", "research"]}),
        "artifact.tags.remove": ({"tags": ["Research"]}, {"tags": []}),
        "collection.reorder": ({"ordered_ids": semantic_bound.members[::-1]}, {"member_order": semantic_bound.members[::-1]}),
    }
    arguments, changes = options[operation]
    request = semantic_bound.approve(semantic_bound.request(operation, arguments), changes)
    batch = coordinator(semantic_bound)
    result = execute(batch, preview(batch, [request]))
    assert result.counts["completed"] == 1
    native = native_receipt(result.items[0])
    assert native["source_receipt"]["outcome"] == "written"
    assert native["authority_receipt"]["action"] == "operation." + operation
    assert native["input_version"] == request.expected_version
    assert native["authority_receipt"]["receipt_id"] == semantic_bound.records()[0]["receipt_id"]


def test_diagnostic_or_kernel_summary_cannot_acknowledge_batch_success(semantic_bound):
    requests, _ = requests_for(semantic_bound, 1)
    batch = coordinator(semantic_bound)
    batch.kernel.handlers = {requests[0].operation_id: lambda _: OwnerExecutionResult.succeeded(
        effect_id=requests[0].request_id, effect_receipt={"receipt_id": "diagnostic-only"})}
    frozen = preview(batch, requests)
    result = execute(batch, frozen)
    assert result.status == "recovery_required" and result.counts["completed"] == 0


def test_batch_body_edit_uses_and_recovers_the_real_write_owner(write_bound, tmp_path, monkeypatch):
    request = write_request(write_bound, "artifact.update", arguments={"body": "Batch body.\n"})
    kernel = write_kernel(write_bound)
    kernel.receipt_store = JsonReceiptStore(tmp_path / "batch.json")
    batch = BatchOperationCoordinator(kernel, reconcile_owner=lambda r: write_operations.reconcile_write_operation(r, write_bound))
    frozen = preview(batch, [request])
    finalize = kernel.receipt_store.finalize

    def crash(request_id, *args):
        if request_id == request.request_id:
            raise Interrupted()
        return finalize(request_id, *args)

    with monkeypatch.context() as patch:
        patch.setattr(kernel.receipt_store, "finalize", crash)
        with pytest.raises(Interrupted):
            execute(batch, frozen)
    recovered = execute(batch, frozen)
    assert recovered.status == "convergence_pending"
    assert write_bound.note_path.read_text().endswith("Batch body.\n")
    assert native_receipt(recovered.items[0])["owner"] == "knowledge.governed_body_edit"
    assert execute(batch, frozen) == recovered


def test_batch_body_edit_cannot_route_to_a_panel_diagnostic(write_bound, tmp_path):
    request = write_request(write_bound, "artifact.update", arguments={"proposal_id": "queued-semantic-effect"})
    kernel = write_kernel(write_bound)
    kernel.receipt_store = JsonReceiptStore(tmp_path / "batch.json")
    with pytest.raises(ValueError, match="Panel/proposal"):
        preview(BatchOperationCoordinator(kernel), [request])


def test_recovery_persistence_failure_retains_newly_verified_native_evidence(semantic_bound, monkeypatch):
    requests, paths = requests_for(semantic_bound, 1)
    batch = coordinator(semantic_bound)
    frozen = preview(batch, requests)
    finalize = batch.store.finalize

    def interrupted(request_id, *args):
        if request_id == requests[0].request_id:
            raise Interrupted()
        return finalize(request_id, *args)

    with monkeypatch.context() as patch:
        patch.setattr(batch.store, "finalize", interrupted)
        with pytest.raises(Interrupted):
            execute(batch, frozen)
    restarted = coordinator(semantic_bound, restart=True)
    durable_finalize = restarted.store.finalize

    def unavailable(request_id, *args):
        if request_id == requests[0].request_id:
            raise OSError("kernel still unavailable after native receipt read")
        return durable_finalize(request_id, *args)

    with monkeypatch.context() as patch:
        patch.setattr(restarted.store, "finalize", unavailable)
        result = execute(restarted, frozen)
    assert result.status == "recovery_required" and result.counts["completed"] == 0
    assert result.items[0].outcome.convergence.source_effect is SourceEffectStatus.COMMITTED
    assert native_receipt(result.items[0])["authority_receipt"]["receipt_id"] == semantic_bound.records()[0]["receipt_id"]
    assert source_tags(paths[0]) == ["reviewed"] and len(semantic_bound.records()) == 1


@pytest.mark.parametrize("operation", ["artifact.move", "artifact.rename"])
def test_batch_placement_resumes_proven_native_preparation(placement_bound, operation, monkeypatch):
    destination = "Projects/moved.md" if operation == "artifact.move" else "renamed.md"
    request = placement_request(placement_bound, operation=operation, destination=destination)
    batch = BatchOperationCoordinator(placement_kernel(placement_bound))
    frozen = preview(batch, [request])
    source = placement_bound.owner.root / placement_bound.source
    original = source.read_bytes()
    store = placement_bound.owner._store

    def crash(root, state, name, value):
        store(root, state, name, value)
        if value["phase"] == "prepared":
            raise Interrupted()

    with monkeypatch.context() as patch:
        patch.setattr(placement_bound.owner, "_store", crash)
        with pytest.raises(Interrupted):
            execute(batch, frozen)
    restarted = placement_restart(placement_bound)
    resumed = BatchOperationCoordinator(placement_kernel(restarted), reconcile_owner=lambda r:
                                       placement_operations.reconcile_placement_operation(r, restarted))
    result = execute(resumed, frozen)
    assert result.status == "convergence_pending" and result.counts["completed"] == 1
    receipt = result.items[0].outcome.receipt.extensions["placement"]
    assert receipt["source_generation"] == request.expected_version
    assert receipt["governed_write"]["authority_receipt"]["effect_id"] == request.request_id
    assert (restarted.owner.root / receipt["destination_locator"]).read_bytes() == original
    assert not source.exists() and execute(resumed, frozen) == result


@pytest.mark.parametrize("operation", ["artifact.capture", "artifact.create", "proposal.apply",
                                       "artifact.archive", "artifact.restore", "artifact.read", "artifact.search"])
def test_unbound_batch_kinds_refuse_before_any_effect(semantic_bound, operation):
    requests, _ = requests_for(semantic_bound, 1)
    assert operation not in SUPPORTED_BATCH_OPERATIONS
    with pytest.raises(ValueError, match="supported"):
        preview(coordinator(semantic_bound), [replace(requests[0], operation_id=operation)])


def test_missing_or_corrupt_batch_state_never_rebuilds_a_selection(semantic_bound):
    requests, paths = requests_for(semantic_bound, 1)
    batch = coordinator(semantic_bound)
    frozen = preview(batch, requests)
    raw = json.loads(batch.store.path.read_text())
    raw["ygg.batch:batch-1"]["outcome"]["extensions"]["batch"]["frozen"]["requests"][0]["expected_version"] = "new-version"
    batch.store.path.write_text(json.dumps(raw))
    with pytest.raises(BatchStateUnavailable):
        execute(batch, frozen)
    assert source_tags(paths[0]) == []


def test_preview_refuses_conflicting_partial_success_policy(semantic_bound):
    requests, paths = requests_for(semantic_bound, 1)
    batch = coordinator(semantic_bound)
    grant = {**delegation_for(requests), "batch_policy": {"atomic": True}}
    with pytest.raises(ValueError, match="partial-success"):
        batch.preview(batch_id="atomic", requests=requests, selector={}, delegation=grant)
    assert source_tags(paths[0]) == []


def test_failed_preview_durability_cannot_admit_an_effect(semantic_bound, monkeypatch):
    requests, paths = requests_for(semantic_bound, 1)
    batch = coordinator(semantic_bound)
    from app.operations import execution_kernel

    with monkeypatch.context() as patch:
        patch.setattr(execution_kernel.os, "fsync", lambda _: (_ for _ in ()).throw(OSError("journal synchronization failed")))
        with pytest.raises(OSError, match="synchronization"):
            preview(batch, requests)
    assert source_tags(paths[0]) == []
    with pytest.raises(BatchStateUnavailable):
        batch.inspect("batch-1", expected_digest="0" * 64)
