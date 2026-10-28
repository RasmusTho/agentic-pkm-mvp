from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import replace
import fcntl
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
from threading import Event
import time
from uuid import UUID, uuid4

import pytest

from app.ingest.vault_alpha import run_vault_alpha_ingest_paths
from app.knowledge import placement
from app.knowledge.errors import KnowledgeCapabilityError
from app.knowledge.placement import KnowledgePlacementOwner
from app.instance.active_context_service import ActiveContextSelectionService
from app.instance.context_selection import ContextSelectionStore
from app.operations import (
    JsonReceiptStore,
    OperationContext,
    OperationExecutionKernel,
    OperationRequest,
    OperationStatus,
    PolicyDecision,
)
from app.operations.contracts import ConvergenceState, OperationProvenance, SourceEffectStatus
from app.operations import placement_operations as operations
from app.services.companion_note import read_companion
from app.stores import get_object_store, reset_store_backends
from app.vault.paths import get_vault_capture_note_rel, get_vault_system_dir_rel
from tests.api._vault_test_helpers import bind_initialized_vault
from tests._mvr03_principal_harness import provisioned_instance
from tests.helpers.instance_storage_capability import STORAGE_MUTATION_CAPABILITY


class Interrupted(BaseException):
    """Simulate process death without the owner's ordinary error handler."""


@pytest.fixture
def bound(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    runtime, registration, _, principal = provisioned_instance(tmp_path / "instance")
    root = Path(registration.path)
    manager = bind_initialized_vault(
        monkeypatch, root, store_dir=tmp_path, channel=runtime.layout.channel_id
    )
    runtime.complete_initialization(
        registration.vault_binding_id,
        vault_id="vault-" + registration.vault_binding_id,
        local_instance_id=registration.local_instance_id,
    )
    monkeypatch.setenv("INSTANCE_VAULT_REGISTRY_PATH", str(runtime.registry.path))
    monkeypatch.setenv("INSTANCE_OWNERSHIP_ROOT", str(runtime.ledger.root))
    service = ActiveContextSelectionService(
        registry_store=runtime.registry,
        principal_record=principal,
        selection_store=ContextSelectionStore(),
    )
    derived = service.derive("trusted_loopback")
    bearer, _ = service.create(derived=derived, binding_ids=[registration.vault_binding_id])
    context = service.resolve_request_context(
        derived=derived,
        session_bearer=bearer,
        override_bearer=None,
        action="operation.artifact.move",
        write_class="vault_placement",
        required_permission="write",
    ).snapshot
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(tmp_path / "outbox.jsonl"))
    monkeypatch.setenv("COMPANION_CREATE_COOLDOWN_SECONDS", "0")
    monkeypatch.setenv("COMPANION_RENAME_COOLDOWN_SECONDS", "0")
    reset_store_backends()
    (root / "Notes").mkdir()
    (root / "Projects").mkdir()
    # The real ingest owner consumes its ordinary selected-vault layout.
    (root / "⚙️ System" / "vault.layout.md").write_text(
        "---\nversion: '1'\nsystem_folder: '⚙️ System'\ninbox_folder: 'Inbox'\n"
        "desk_folder: 'Projects'\ninclude_folders:\n  - Notes\n  - Projects\n---\n"
    )
    identity = str(uuid4())
    (root / "Notes/original.md").write_text(
        f"---\nuuid: {identity}\nkind: note\norigin: human\ncreated: 2026-09-04\n---\n"
        "\nHuman meaning and provenance stay byte-for-byte intact.\n"
    )
    owner = KnowledgePlacementOwner(
        vault_root=root,
        context_ref=context.context_id,
        vault_generation=str(context.generation),
        actor=context.principal_context.principal_id,
        active_context=context,
        target_binding_id=registration.vault_binding_id,
        registry_store=runtime.registry,
        context_is_current=lambda: manager.context.status == "selected"
        and manager.context.active_vault_path == str(root),
        authority_is_current=lambda intent: intent.artifact_id == identity
        and intent.operation in {"artifact.move", "artifact.rename"},
        filesystem="local-posix-v1",
    )
    yield operations.PlacementOperationServerConfig(
        owner,
        OperationContext(context.context_id, str(context.generation)),
        identity,
        "Notes/original.md",
    )
    reset_store_backends()


def _request(
    config,
    *,
    operation="artifact.move",
    destination="Projects/moved.md",
    request_id="placement-1",
    version=None,
):
    target = (
        str(Path(config.source).with_name(destination))
        if operation == "artifact.rename"
        else destination
    )
    key = "name" if operation == "artifact.rename" else "destination"
    return OperationRequest(
        operation,
        request_id,
        config.context,
        targets=({"artifact_id": config.artifact_id},),
        expected_version=version
        or config.owner.source_generation(config.source, config.artifact_id),
        arguments={
            key: destination,
            "destination_generation": config.owner.destination_generation(target),
        },
        provenance=OperationProvenance(config.owner.actor, "direct-test", "test"),
    )


def _delegation(config, request):
    return {
        "active_context_ref": config.context.active_context_ref,
        "vault_generation": config.context.vault_generation,
        "operation_ids": [request.operation_id],
        "policy_version": "policy-1",
        "principal": config.owner.actor,
        "client": "test",
        "surface": "test",
        "receipt_ref": "delegation-1",
        "authority_class": "governed_effect",
        "target_ids": [config.artifact_id],
        "max_targets": 1,
        "allowed_effects": [request.operation_id],
        "expires_at": 4102444800,
        "revoked": False,
    }


def _kernel(config, *, policy=None):
    return OperationExecutionKernel(
        context_resolver=lambda _: config.owner.context_is_current(),
        policy_evaluator=policy or (lambda *_: PolicyDecision.allowed("policy-1")),
        handlers=operations.build_placement_operation_handlers(config),
        receipt_store=JsonReceiptStore(config.owner.root.parent / "operations.json"),
        version_checker=lambda _: True,
        token_validator=lambda *_: True,
    )


def _run(config, request, *, kernel=None):
    return (kernel or _kernel(config)).execute(request, _delegation(config, request))


def _restart(config):
    previous = config.owner
    return replace(
        config,
        owner=KnowledgePlacementOwner(
            vault_root=previous.root,
            context_ref=previous.context_ref,
            vault_generation=previous.vault_generation,
            actor=previous.actor,
            active_context=previous.active_context,
            target_binding_id=previous.target_binding_id,
            registry_store=previous.registry_store,
            context_is_current=previous.context_is_current,
            authority_is_current=previous.authority_is_current,
            filesystem=previous.filesystem,
        ),
    )


def _record(config, request_id="placement-1"):
    name = sha256(request_id.encode()).hexdigest() + ".json"
    return json.loads((config.owner.root / ".pkm-placement" / name).read_text())


@pytest.mark.usefixtures("product_model_access_gateway")
def test_move_and_rename_preserve_identity_and_converge_locators(bound):
    original = bound.owner.root / bound.source
    raw = original.read_bytes()
    inode = original.stat().st_ino
    run_vault_alpha_ingest_paths(bound.owner.root, [original])
    before = read_companion(bound.owner.root, bound.artifact_id)
    assert before is not None and before.source_ref == bound.source
    request = _request(bound)
    moved = _run(bound, request)
    destination = bound.owner.root / "Projects/moved.md"
    assert moved.status is OperationStatus.CONVERGENCE_PENDING
    assert moved.convergence.source_effect is SourceEffectStatus.COMMITTED
    assert moved.convergence.store is ConvergenceState.REBUILD_REQUIRED
    assert not original.exists() and destination.read_bytes() == raw
    assert destination.stat().st_ino == inode and destination.stat().st_nlink == 1
    record = _record(bound)
    assert record["phase"] == "committed" and record["cleanup_complete"]
    receipt = record["receipt"]
    assert receipt["artifact_id"] == bound.artifact_id
    assert receipt["destination_locator"] == "Projects/moved.md"
    assert receipt["projection_repair"] == ["locator", "store", "index", "link"]
    assert receipt["governed_write"]["authority_receipt"]["effect_id"] == request.request_id
    authority = receipt["governed_write"]["authority_receipt"]
    assert authority["target_binding_id"] == bound.owner.target_binding_id
    assert authority["active_context"]["context_id"] == bound.context.active_context_ref
    assert authority["active_context"]["principal_context"]["principal_id"] == bound.owner.actor
    # Projection lag has durable repair evidence. The existing real ingest owner
    # repairs from the destination, never from a mutable path-only cache.
    summary = run_vault_alpha_ingest_paths(bound.owner.root, [destination])
    assert summary.ingested == 1
    companion = read_companion(bound.owner.root, bound.artifact_id)
    assert companion is not None and companion.source_ref == "Projects/moved.md"
    stored = get_object_store().get(UUID(bound.artifact_id))
    assert stored is not None and stored["source_ref"] == str(destination)
    renamed_config = replace(bound, source="Projects/moved.md")
    rename = _request(
        renamed_config, operation="artifact.rename", destination="renamed.md", request_id="rename-1"
    )
    renamed = _run(renamed_config, rename)
    assert renamed.status is OperationStatus.CONVERGENCE_PENDING
    final = bound.owner.root / "Projects/renamed.md"
    assert final.read_bytes() == raw and final.stat().st_ino == inode
    assert not destination.exists()
    run_vault_alpha_ingest_paths(bound.owner.root, [final])
    assert read_companion(bound.owner.root, bound.artifact_id).source_ref == "Projects/renamed.md"
    assert get_object_store().get(UUID(bound.artifact_id))["source_ref"] == str(final)
    assert _run(_restart(renamed_config), rename) == renamed


def test_placement_refuses_collision_stale_generation_and_scope_mismatch(bound):
    source = bound.owner.root / bound.source
    original = source.read_bytes()
    request = _request(bound)
    destination = bound.owner.root / "Projects/moved.md"
    destination.write_text("Another human artifact")
    assert _run(bound, request).status is OperationStatus.CONFLICTED
    assert destination.read_text() == "Another human artifact"
    destination.unlink()
    stale = _request(bound, request_id="stale")
    source.write_bytes(original + b"A newer edit.\n")
    assert _run(bound, stale).status is OperationStatus.CONFLICTED
    assert source.read_bytes() == original + b"A newer edit.\n"
    wrong_context = replace(
        _request(bound, request_id="scope"),
        context=OperationContext("another-vault", "generation-1"),
    )
    assert (
        operations.build_placement_operation_handlers(bound)["artifact.move"](wrong_context).status
        is OperationStatus.REJECTED
    )
    assert not destination.exists()
    for destination_name in (
        "../escape.md",
        "/absolute.md",
        "Projects/../escape.md",
        "Projects//bad.md",
        "Projects\\bad.md",
    ):
        invalid = replace(
            _request(bound, request_id=destination_name),
            arguments={"destination": destination_name, "destination_generation": "absent"},
        )
        assert _run(bound, invalid).status is OperationStatus.NOT_SUPPORTED
    child = bound.owner.root / "Projects/private"
    (child / "settings").mkdir(parents=True)
    (child / "settings/vault.md").write_text("---\nvaultId: child-vault\n---\n")
    nested = replace(
        _request(bound, request_id="nested"),
        arguments={"destination": "Projects/private/note.md", "destination_generation": "absent"},
    )
    assert _run(bound, nested).status is OperationStatus.NOT_SUPPORTED
    assert not (child / "note.md").exists()


def test_partial_move_preserves_original_and_recovers_idempotently(bound, monkeypatch):
    request = _request(bound)
    source = bound.owner.root / bound.source
    raw = source.read_bytes()
    store = bound.owner._store

    def interrupt(root, state, name, value):
        store(root, state, name, value)
        if value["phase"] == "prepared":
            raise Interrupted()

    monkeypatch.setattr(bound.owner, "_store", interrupt)
    with pytest.raises(Interrupted):
        _run(bound, request)
    assert source.read_bytes() == raw and not (bound.owner.root / "Projects/moved.md").exists()
    assert _record(bound)["phase"] == "prepared"
    restarted = _restart(bound)
    # Kernel replay remains the observed recovery record, never a second move.
    assert _run(restarted, request).status is OperationStatus.RECOVERY_REQUIRED
    recovered = operations.reconcile_placement_operation(request, restarted)
    assert recovered.status is OperationStatus.CONVERGENCE_PENDING
    assert not source.exists() and (bound.owner.root / "Projects/moved.md").read_bytes() == raw
    assert operations.reconcile_placement_operation(request, _restart(bound)) == recovered


@pytest.mark.parametrize("phase", ["reserved", "publishing", "activated", "retiring", "committed"])
def test_restart_at_each_durable_transition_uses_exact_evidence(bound, monkeypatch, phase):
    request = _request(bound)
    raw = (bound.owner.root / bound.source).read_bytes()
    store = bound.owner._store
    crashed = False

    def interrupt(root, state, name, value):
        nonlocal crashed
        store(root, state, name, value)
        if value["phase"] == phase and not crashed:
            crashed = True
            raise Interrupted()

    monkeypatch.setattr(bound.owner, "_store", interrupt)
    with pytest.raises(Interrupted):
        _run(bound, request)
    recovered = operations.reconcile_placement_operation(request, _restart(bound))
    assert recovered.status is OperationStatus.CONVERGENCE_PENDING
    assert (bound.owner.root / "Projects/moved.md").read_bytes() == raw
    assert not (bound.owner.root / bound.source).exists()


@pytest.mark.parametrize("effect", ["retain", "activate", "retire"])
def test_ambiguous_syscall_return_reconciles_without_repeating_a_move(bound, monkeypatch, effect):
    request = _request(bound)
    real_link = placement.os.link
    real_rename = placement._atomic_rename_noreplace_at
    calls = 0

    def link(source, destination, **kwargs):
        nonlocal calls
        real_link(source, destination, **kwargs)
        if (effect == "retain" and destination == "original") or (
            effect == "activate" and source == "original"
        ):
            calls += 1
            raise Interrupted()

    def rename(src, source, dst, destination):
        nonlocal calls
        real_rename(src, source, dst, destination)
        if effect == "retire" and destination == "retired":
            calls += 1
            raise Interrupted()

    monkeypatch.setattr(placement.os, "link", link)
    monkeypatch.setattr(placement, "_atomic_rename_noreplace_at", rename)
    with pytest.raises(Interrupted):
        _run(bound, request)
    monkeypatch.setattr(placement.os, "link", real_link)
    monkeypatch.setattr(placement, "_atomic_rename_noreplace_at", real_rename)
    assert (
        operations.reconcile_placement_operation(request, _restart(bound)).status
        is OperationStatus.CONVERGENCE_PENDING
    )
    assert calls == 1


def test_destination_winner_and_source_replacement_are_never_clobbered(bound, monkeypatch):
    request = _request(bound)
    source = bound.owner.root / bound.source
    destination = bound.owner.root / "Projects/moved.md"
    raw = source.read_bytes()
    real_link = placement.os.link

    def race(source_name, destination_name, **kwargs):
        if source_name == "original":
            destination.write_text("racing destination winner")
        return real_link(source_name, destination_name, **kwargs)

    monkeypatch.setattr(placement.os, "link", race)
    outcome = _run(bound, request)
    assert outcome.status is OperationStatus.RECOVERY_REQUIRED
    assert source.read_bytes() == raw and destination.read_text() == "racing destination winner"
    monkeypatch.setattr(placement.os, "link", real_link)
    assert (
        operations.reconcile_placement_operation(request, _restart(bound)).status
        is OperationStatus.RECOVERY_REQUIRED
    )
    assert destination.read_text() == "racing destination winner"
    # A new request cannot bypass the outstanding durable reservation.
    bypass = replace(request, request_id="bypass")
    assert _run(bound, bypass).status is OperationStatus.CONFLICTED


def test_source_replacement_at_retirement_is_restored_without_overwrite(bound, monkeypatch):
    request = _request(bound)
    source = bound.owner.root / bound.source
    original = source.read_bytes()
    real_rename = placement._atomic_rename_noreplace_at

    def race(src, name, dst, destination):
        if destination == "retired":
            replacement = source.with_suffix(".new")
            replacement.write_text("concurrent source replacement")
            replacement.replace(source)
        real_rename(src, name, dst, destination)

    monkeypatch.setattr(placement, "_atomic_rename_noreplace_at", race)
    outcome = _run(bound, request)
    assert outcome.status is OperationStatus.RECOVERY_REQUIRED
    assert source.read_text() == "concurrent source replacement"
    assert (bound.owner.root / "Projects/moved.md").read_bytes() == original
    monkeypatch.setattr(placement, "_atomic_rename_noreplace_at", real_rename)
    assert (
        operations.reconcile_placement_operation(request, _restart(bound)).status
        is OperationStatus.RECOVERY_REQUIRED
    )
    assert source.read_text() == "concurrent source replacement"


def test_generation_includes_inode_and_destination_parent_identity(bound):
    source = bound.owner.root / bound.source
    request = _request(bound)
    fresh = source.with_suffix(".new")
    fresh.write_bytes(source.read_bytes())
    fresh.replace(source)
    assert _run(bound, request).status is OperationStatus.CONFLICTED
    request = _request(bound, request_id="parent")
    projects = bound.owner.root / "Projects"
    projects.rename(bound.owner.root / "PreviousProjects")
    projects.mkdir()
    assert _run(bound, request).status is OperationStatus.CONFLICTED
    assert source.exists() and not (projects / "moved.md").exists()


def test_two_owners_serialize_destination_reservations(bound):
    other_id = str(uuid4())
    (bound.owner.root / "Notes/other.md").write_text(
        f"---\nuuid: {other_id}\n---\nOther artifact.\n"
    )
    other = replace(_restart(bound), artifact_id=other_id, source="Notes/other.md")
    other.owner.authority_is_current = lambda intent: intent.artifact_id == other_id
    first, second = _request(bound), _request(other, request_id="placement-2")
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda pair: _run(*pair), [(bound, first), (other, second)]))
    assert sorted(outcome.status for outcome in outcomes) == sorted(
        [OperationStatus.CONFLICTED, OperationStatus.CONVERGENCE_PENDING]
    ), outcomes
    assert sum((bound.owner.root / name).exists() for name in (bound.source, other.source)) == 1
    assert (bound.owner.root / "Projects/moved.md").exists()


def test_missing_qualification_authority_and_unsafe_names_refuse_before_source_effect(
    bound, monkeypatch
):
    request = _request(bound)
    source = bound.owner.root / bound.source
    raw = source.read_bytes()
    unqualified = _restart(bound)
    unqualified.owner.filesystem = None
    assert _run(unqualified, request).status is OperationStatus.NOT_SUPPORTED
    assert not list((bound.owner.root / ".pkm-placement").glob("*.json"))
    denied = _kernel(bound, policy=lambda *_: PolicyDecision.denied("policy-1", "not delegated"))
    assert (
        _run(bound, replace(request, request_id="denied"), kernel=denied).status
        is OperationStatus.REJECTED
    )
    monkeypatch.setattr(bound.owner, "context_is_current", lambda: False)
    direct = operations.build_placement_operation_handlers(bound)["artifact.move"](
        replace(request, request_id="stale-context")
    )
    assert direct.status is OperationStatus.REJECTED
    assert source.read_bytes() == raw and not (bound.owner.root / "Projects/moved.md").exists()


def test_revoked_context_after_reservation_preserves_source(bound, monkeypatch):
    request = _request(bound)
    source = bound.owner.root / bound.source
    store = bound.owner._store
    allowed = True

    def persist(root, state, name, value):
        nonlocal allowed
        store(root, state, name, value)
        if value["phase"] == "prepared":
            allowed = False

    monkeypatch.setattr(bound.owner, "_store", persist)
    monkeypatch.setattr(bound.owner, "context_is_current", lambda: allowed)
    assert _run(bound, request).status is OperationStatus.RECOVERY_REQUIRED
    assert source.exists() and not (bound.owner.root / "Projects/moved.md").exists()


def test_revoked_delegation_cannot_resume_a_reserved_placement(bound, monkeypatch):
    request = _request(bound)
    store = bound.owner._store

    def interrupt(root, state, name, value):
        store(root, state, name, value)
        if value["phase"] == "prepared":
            raise Interrupted()

    monkeypatch.setattr(bound.owner, "_store", interrupt)
    with pytest.raises(Interrupted):
        _run(bound, request)
    restarted = _restart(bound)
    monkeypatch.setattr(restarted.owner, "authority_is_current", lambda _: False)
    refused = operations.reconcile_placement_operation(request, restarted)
    assert refused.status is OperationStatus.REJECTED
    assert (bound.owner.root / bound.source).exists()
    assert not (bound.owner.root / "Projects/moved.md").exists()


def test_symlink_mount_and_identity_mismatch_never_authorize_a_move(bound):
    source = bound.owner.root / bound.source
    request = _request(bound)
    alternate = bound.owner.root.parent / "outside"
    alternate.mkdir()
    (bound.owner.root / "linked").symlink_to(alternate, target_is_directory=True)
    invalid = replace(
        request, arguments={"destination": "linked/escape.md", "destination_generation": "absent"}
    )
    assert _run(bound, invalid).status in {
        OperationStatus.RECOVERY_REQUIRED,
        OperationStatus.NOT_SUPPORTED,
    }
    assert not (alternate / "escape.md").exists()
    wrong_identity = replace(
        request, targets=({"artifact_id": str(uuid4())},), request_id="identity"
    )
    assert _run(bound, wrong_identity).status is OperationStatus.REJECTED
    assert source.exists()


def test_malformed_recovery_evidence_fails_closed_without_suppressing_source(bound):
    request = _request(bound)
    state = bound.owner.root / ".pkm-placement"
    state.mkdir(mode=0o700)
    (state / "broken.json").write_text('{"schema":"hka.placement.v1","phase":"unknown"}')
    assert _run(bound, request).status is OperationStatus.CONFLICTED
    assert (bound.owner.root / bound.source).exists()
    assert not (bound.owner.root / "Projects/moved.md").exists()


@pytest.mark.parametrize("failure", ["prepared_fsync", "authority_receipt"])
def test_persistence_and_accountability_failure_never_acknowledge_placement(
    bound, monkeypatch, failure
):
    request = _request(bound)
    raw = (bound.owner.root / bound.source).read_bytes()
    store = bound.owner._store
    receipt = placement.GovernedWriteAdapter.record_authority_receipt

    def fail_store(root, state, name, record):
        store(root, state, name, record)
        if record["phase"] == "prepared":
            raise OSError("simulated directory fsync failure")

    def fail_receipt(*args, **kwargs):
        raise RuntimeError("AuthorityReceipt is unavailable")

    if failure == "prepared_fsync":
        monkeypatch.setattr(bound.owner, "_store", fail_store)
    else:
        monkeypatch.setattr(
            placement.GovernedWriteAdapter, "record_authority_receipt", fail_receipt
        )
    outcome = _run(bound, request)
    assert outcome.status is OperationStatus.RECOVERY_REQUIRED
    record = _record(bound)
    retained = (
        bound.owner.root
        / ".pkm-placement"
        / sha256(request.request_id.encode()).hexdigest()
        / "original"
    )
    assert retained.read_bytes() == raw and record["receipt"] is None
    monkeypatch.setattr(placement.GovernedWriteAdapter, "record_authority_receipt", receipt)
    recovered = operations.reconcile_placement_operation(request, _restart(bound))
    assert recovered.status is OperationStatus.CONVERGENCE_PENDING
    assert (bound.owner.root / "Projects/moved.md").read_bytes() == raw


def test_in_place_save_during_activation_remains_authoritative_at_source(bound, monkeypatch):
    request = _request(bound)
    source = bound.owner.root / bound.source
    saved = source.read_bytes() + b"Late human save.\n"
    link = placement.os.link

    def save_before_link(source_name, destination_name, **kwargs):
        if source_name == "original":
            source.write_bytes(saved)
        link(source_name, destination_name, **kwargs)

    monkeypatch.setattr(placement.os, "link", save_before_link)
    assert _run(bound, request).status is OperationStatus.RECOVERY_REQUIRED
    assert _record(bound)["phase"] == "publishing"
    assert source.read_bytes() == saved
    assert (bound.owner.root / "Projects/moved.md").read_bytes() == saved
    monkeypatch.setattr(placement.os, "link", link)
    assert (
        operations.reconcile_placement_operation(request, _restart(bound)).status
        is OperationStatus.RECOVERY_REQUIRED
    )
    assert source.read_bytes() == saved


def test_missing_source_and_changed_semantic_replay_are_not_success(bound, monkeypatch):
    request = _request(bound)
    store = bound.owner._store

    def interrupt(root, state, name, value):
        store(root, state, name, value)
        if value["phase"] == "prepared":
            raise Interrupted()

    monkeypatch.setattr(bound.owner, "_store", interrupt)
    with pytest.raises(Interrupted):
        _run(bound, request)
    restarted = _restart(bound)
    changed = replace(request, arguments={**request.arguments, "destination": "Projects/other.md"})
    assert (
        operations.build_placement_operation_handlers(restarted)["artifact.move"](changed).status
        is OperationStatus.CONFLICTED
    )
    (bound.owner.root / bound.source).unlink()
    assert (
        operations.reconcile_placement_operation(request, restarted).status
        is OperationStatus.RECOVERY_REQUIRED
    )
    assert not (bound.owner.root / "Projects/moved.md").exists()


def test_canvas_and_retained_artifacts_cannot_borrow_placement_authority(bound):
    request = _request(bound)
    source = bound.owner.root / bound.source
    source.write_text(f"---\nuuid: {bound.artifact_id}\ntype: chat-session\n---\nSession.\n")
    # A current generation still cannot admit a different artifact authority class.
    fd = placement.os.open(source, placement._READ)
    try:
        version = placement._digest(placement._snapshot(fd)[1])
    finally:
        placement.os.close(fd)
    refused = _run(bound, replace(request, request_id="canvas", expected_version=version))
    assert refused.status is OperationStatus.NOT_SUPPORTED
    assert source.exists() and not (bound.owner.root / "Projects/moved.md").exists()


def test_filesystem_aliases_cannot_enter_system_or_capture_authority(bound):
    root = bound.owner.root
    system = get_vault_system_dir_rel(root)
    alias = system.swapcase()
    if not (root / alias).is_dir() or not (root / alias).samefile(root / system):
        pytest.skip("actual case-insensitive lookup is required for this platform boundary")
    source = root / bound.source
    raw = source.read_bytes()
    request = _request(bound)
    # Both the read/preflight API and actual operation owner refuse the alias.
    with pytest.raises(KnowledgeCapabilityError):
        bound.owner.destination_generation(f"{alias}/moved.md")
    for destination in (f"{system}/moved.md", f"{alias}/moved.md"):
        wrong = replace(
            request,
            request_id=destination,
            arguments={"destination": destination, "destination_generation": "absent"},
        )
        assert _run(bound, wrong).status is OperationStatus.NOT_SUPPORTED
    # Source membership uses the same physical-zone rule.
    system_source = root / system / "human.md"
    system_source.write_bytes(raw)
    source_alias = replace(bound, source=f"{alias}/human.md")
    assert (
        _run(source_alias, replace(request, request_id="system-source")).status
        is OperationStatus.NOT_SUPPORTED
    )
    assert system_source.read_bytes() == raw
    capture = PurePosixPath(get_vault_capture_note_rel(root))
    root.joinpath(*capture.parent.parts).mkdir(parents=True, exist_ok=True)
    capture_alias = str(capture.with_name(capture.name.swapcase()))
    # The capture leaf need not exist: filesystem lookup semantics still protect
    # its reserved name from a normal human-note placement.
    wrong = replace(
        request,
        request_id="capture-alias",
        arguments={"destination": capture_alias, "destination_generation": "absent"},
    )
    assert _run(bound, wrong).status is OperationStatus.NOT_SUPPORTED
    assert source.read_bytes() == raw and not (root / system / "moved.md").exists()
    assert not root.joinpath(*capture.parts).exists()
    assert not list((root / ".pkm-placement").glob("*.json"))


def test_parent_and_source_leaf_aliases_refuse_before_reservation(bound):
    root = bound.owner.root
    if not (root / "pROJECTS").is_dir() or not (root / "pROJECTS").samefile(root / "Projects"):
        pytest.skip("actual case-insensitive lookup is required for this platform boundary")
    request = _request(bound)
    with pytest.raises(KnowledgeCapabilityError):
        bound.owner.destination_generation("pROJECTS/moved.md")
    with pytest.raises(KnowledgeCapabilityError):
        bound.owner.source_generation("Notes/ORIGINAL.md", bound.artifact_id)
    destination_alias = replace(
        request, arguments={**request.arguments, "destination": "pROJECTS/moved.md"}
    )
    assert _run(bound, destination_alias).status is OperationStatus.NOT_SUPPORTED
    source_alias = replace(bound, source="Notes/ORIGINAL.md")
    assert (
        _run(source_alias, replace(request, request_id="source-leaf-alias")).status
        is OperationStatus.NOT_SUPPORTED
    )
    assert (root / bound.source).exists() and not (root / "Projects/moved.md").exists()
    assert not list((root / ".pkm-placement").glob("*.json"))


def test_reserved_destination_alias_cannot_bypass_restart_reservation(bound, monkeypatch):
    root = bound.owner.root
    if not (root / "pROJECTS").is_dir() or not (root / "pROJECTS").samefile(root / "Projects"):
        pytest.skip("actual case-insensitive lookup is required for this platform boundary")
    request = _request(bound, destination="Projects/Moved.md")
    store = bound.owner._store

    def interrupt(root, state, name, record):
        store(root, state, name, record)
        if record["phase"] == "prepared":
            raise Interrupted()

    monkeypatch.setattr(bound.owner, "_store", interrupt)
    with pytest.raises(Interrupted):
        _run(bound, request)
    other_id = str(uuid4())
    (root / "Notes/other.md").write_text(f"---\nuuid: {other_id}\n---\nAnother artifact.\n")
    other = replace(_restart(bound), artifact_id=other_id, source="Notes/other.md")
    other.owner.authority_is_current = lambda intent: intent.artifact_id == other_id
    alias = _request(other, destination="Projects/moved.md", request_id="another-request")
    assert _run(other, alias).status is OperationStatus.CONFLICTED
    assert (root / bound.source).exists() and (root / other.source).exists()
    assert not (root / "Projects/Moved.md").exists()


def test_post_publication_fsync_failure_preserves_unknown_effect_and_repair(bound, monkeypatch):
    request = _request(bound)
    source = bound.owner.root / bound.source
    destination = bound.owner.root / "Projects/moved.md"
    raw = source.read_bytes()
    fsync = placement.os.fsync
    fail_once = True

    def fail_published_directory(fd):
        nonlocal fail_once
        if (
            fail_once
            and destination.exists()
            and placement.os.fstat(fd).st_ino == destination.parent.stat().st_ino
        ):
            fail_once = False
            raise OSError("destination-directory fsync failed after real link publication")
        return fsync(fd)

    monkeypatch.setattr(placement.os, "fsync", fail_published_directory)
    outcome = _run(bound, request)
    assert outcome.status is OperationStatus.RECOVERY_REQUIRED
    assert source.samefile(destination) and source.read_bytes() == raw
    assert _record(bound)["phase"] == "publishing"
    assert outcome.convergence.source_effect is SourceEffectStatus.UNKNOWN
    assert all(
        getattr(outcome.convergence, item) is ConvergenceState.REBUILD_REQUIRED
        for item in ("store", "index", "link")
    )
    assert outcome.convergence.extensions["locator_repair"] != "not_required"
    assert _run(_restart(bound), request) == outcome
    recovered = operations.reconcile_placement_operation(request, _restart(bound))
    assert recovered.status is OperationStatus.CONVERGENCE_PENDING
    assert recovered.convergence.source_effect is SourceEffectStatus.COMMITTED
    assert not source.exists() and destination.read_bytes() == raw


@pytest.mark.parametrize("operation", ["artifact.move", "artifact.rename"])
@pytest.mark.parametrize("failed_directory", ["source", "recovery"])
def test_recovered_retirement_reasserts_both_directory_syncs(
    bound, monkeypatch, operation, failed_directory
):
    destination_name = "renamed.md" if operation == "artifact.rename" else "Projects/moved.md"
    request = _request(bound, operation=operation, destination=destination_name)
    source = bound.owner.root / bound.source
    destination = (
        source.with_name(destination_name)
        if operation == "artifact.rename"
        else bound.owner.root / destination_name
    )
    transaction = (
        bound.owner.root / ".pkm-placement" / sha256(request.request_id.encode()).hexdigest()
    )
    source_parent = source.parent.stat().st_ino
    raw = source.read_bytes()
    fsync, rename = placement.os.fsync, placement._atomic_rename_noreplace_at
    failures = captures = 0

    def unavailable(fd):
        nonlocal failures
        if not source.exists() and destination.exists():
            barrier = source_parent if failed_directory == "source" else transaction.stat().st_ino
            if placement.os.fstat(fd).st_ino == barrier:
                failures += 1
                raise OSError("retirement namespace synchronization remains unavailable")
        return fsync(fd)

    def capture_once(src, source_name, dst, destination_name):
        nonlocal captures
        rename(src, source_name, dst, destination_name)
        if destination_name == "retired":
            captures += 1

    monkeypatch.setattr(placement.os, "fsync", unavailable)
    monkeypatch.setattr(placement, "_atomic_rename_noreplace_at", capture_once)
    initial = _run(bound, request)
    assert initial.status is OperationStatus.RECOVERY_REQUIRED
    assert _record(bound)["phase"] == "retiring" and _record(bound)["receipt"] is None
    assert (transaction / "retired").read_bytes() == raw
    assert not source.exists() and destination.read_bytes() == raw
    blocked_recovery = operations.reconcile_placement_operation(request, _restart(bound))
    assert blocked_recovery.status is OperationStatus.RECOVERY_REQUIRED
    record = _record(bound)
    assert record["phase"] == "retiring" and record["receipt"] is None
    assert not record["cleanup_complete"] and failures == 2 and captures == 1
    monkeypatch.setattr(placement.os, "fsync", fsync)
    recovered = operations.reconcile_placement_operation(request, _restart(bound))
    assert recovered.status is OperationStatus.CONVERGENCE_PENDING
    assert _record(bound)["cleanup_complete"] and captures == 1
    assert destination.read_bytes() == raw and not source.exists()
    assert operations.reconcile_placement_operation(request, _restart(bound)) == recovered


def test_recovered_original_link_requires_its_directory_sync(bound, monkeypatch):
    request = _request(bound)
    source = bound.owner.root / bound.source
    destination = bound.owner.root / "Projects/moved.md"
    transaction = (
        bound.owner.root / ".pkm-placement" / sha256(request.request_id.encode()).hexdigest()
    )
    fsync = placement.os.fsync
    failures = 0

    def unavailable(fd):
        nonlocal failures
        if (
            (transaction / "original").exists()
            and not destination.exists()
            and placement.os.fstat(fd).st_ino == transaction.stat().st_ino
        ):
            failures += 1
            raise OSError("retained-source directory synchronization remains unavailable")
        return fsync(fd)

    monkeypatch.setattr(placement.os, "fsync", unavailable)
    assert _run(bound, request).status is OperationStatus.RECOVERY_REQUIRED
    assert _record(bound)["phase"] == "reserved"
    assert (
        operations.reconcile_placement_operation(request, _restart(bound)).status
        is OperationStatus.RECOVERY_REQUIRED
    )
    assert _record(bound)["phase"] == "reserved" and failures == 2
    assert source.exists() and not destination.exists()
    monkeypatch.setattr(placement.os, "fsync", fsync)
    assert (
        operations.reconcile_placement_operation(request, _restart(bound)).status
        is OperationStatus.CONVERGENCE_PENDING
    )


def test_existing_recovery_root_requires_parent_sync_before_new_effect(bound, monkeypatch):
    request = _request(bound)
    root = bound.owner.root
    source, destination = root / bound.source, root / "Projects/moved.md"
    root_inode = root.stat().st_ino
    fsync = placement.os.fsync
    failures = 0

    def unavailable(fd):
        nonlocal failures
        if (root / ".pkm-placement").exists() and placement.os.fstat(fd).st_ino == root_inode:
            failures += 1
            raise OSError("recovery-root parent synchronization remains unavailable")
        return fsync(fd)

    monkeypatch.setattr(placement.os, "fsync", unavailable)
    assert _run(bound, request).status is OperationStatus.RECOVERY_REQUIRED
    assert source.exists() and not destination.exists()
    retry = _request(bound, request_id="fresh-authorized-request")
    assert _run(_restart(bound), retry).status is OperationStatus.RECOVERY_REQUIRED
    assert failures == 2 and not list((root / ".pkm-placement").glob("*.json"))
    assert source.exists() and not destination.exists()
    monkeypatch.setattr(placement.os, "fsync", fsync)
    assert (
        _run(_restart(bound), _request(bound, request_id="after-storage-recovery")).status
        is OperationStatus.CONVERGENCE_PENDING
    )


def test_mvr_missing_expired_and_unselected_context_cannot_borrow_callbacks(bound, monkeypatch):
    request = _request(bound)
    source = bound.owner.root / bound.source
    original = bound.owner.active_context
    handler = operations.build_placement_operation_handlers(bound)["artifact.move"]
    monkeypatch.setattr(bound.owner, "active_context", None)
    assert handler(request).status is OperationStatus.REJECTED
    monkeypatch.setattr(bound.owner, "active_context", replace(original, expires_at=1.0))
    assert handler(request).status is OperationStatus.REJECTED
    monkeypatch.setattr(bound.owner, "active_context", original)
    monkeypatch.setattr(bound.owner, "target_binding_id", "not-in-selected-set")
    assert handler(request).status is OperationStatus.REJECTED
    assert source.exists() and not (bound.owner.root / "Projects/moved.md").exists()
    assert not (bound.owner.root / ".pkm-placement").exists()


def test_mvr_selected_binding_cannot_be_repointed_by_a_server_callback(bound, monkeypatch):
    from app.write_guard import WritesBlockedError

    request = _request(bound)
    root = bound.owner.root
    another = root.parent / "unselected-root"
    another.mkdir()
    wrong = _restart(bound)
    wrong.owner.root = another
    wrong.owner.root_identity = placement._inode(another.stat())
    monkeypatch.setattr(wrong.owner, "context_is_current", lambda: True)
    monkeypatch.setattr(wrong.owner, "authority_is_current", lambda _: True)
    with pytest.raises(WritesBlockedError):
        wrong.owner.source_generation(bound.source, bound.artifact_id)
    assert _run(wrong, request).status is OperationStatus.REJECTED
    assert not (another / ".pkm-placement").exists()
    assert (root / bound.source).exists()


def test_mvr_unbound_recovery_token_never_resumes_the_source(bound, monkeypatch):
    request = _request(bound)
    store = bound.owner._store

    def interrupt(root, state, name, record):
        store(root, state, name, record)
        if record["phase"] == "prepared":
            raise Interrupted()

    monkeypatch.setattr(bound.owner, "_store", interrupt)
    with pytest.raises(Interrupted):
        _run(bound, request)
    record = _record(bound)
    record["grant"]["decision_token"]["active_context"] = None
    path = (
        bound.owner.root
        / ".pkm-placement"
        / (sha256(request.request_id.encode()).hexdigest() + ".json")
    )
    path.write_text(json.dumps(record))
    refused = operations.reconcile_placement_operation(request, _restart(bound))
    assert refused.status is OperationStatus.RECOVERY_REQUIRED
    assert (bound.owner.root / bound.source).exists()
    assert not (bound.owner.root / "Projects/moved.md").exists()


def test_mvr_revoked_principal_refuses_before_placement(bound):
    from app.instance.runtime import open_local_operator_principal_store

    request = _request(bound)
    principal = open_local_operator_principal_store(bound.owner.registry_store.path)
    principal.rotate_credential(
        credential="synthetic-placement-rotation", _capability=STORAGE_MUTATION_CAPABILITY
    )
    assert _run(bound, request).status is OperationStatus.REJECTED
    assert (bound.owner.root / bound.source).exists()
    assert not (bound.owner.root / ".pkm-placement").exists()


@pytest.mark.parametrize("phase", ["activated", "committed"])
def test_denied_recovery_cannot_claim_historical_effect_was_not_applied(
    bound, monkeypatch, phase
):
    from app.instance.runtime import open_local_operator_principal_store

    request = _request(bound)
    store = bound.owner._store

    def interrupt(root, state, name, record):
        store(root, state, name, record)
        if record["phase"] == phase:
            raise Interrupted()

    monkeypatch.setattr(bound.owner, "_store", interrupt)
    with pytest.raises(Interrupted):
        _run(bound, request)
    destination = bound.owner.root / "Projects/moved.md"
    assert destination.exists() and _record(bound)["phase"] == phase
    before = _record(bound)
    principal = open_local_operator_principal_store(bound.owner.registry_store.path)
    principal.rotate_credential(
        credential="synthetic-placement-recovery-rotation", _capability=STORAGE_MUTATION_CAPABILITY
    )
    refused = operations.reconcile_placement_operation(request, _restart(bound))
    assert refused.status is OperationStatus.REJECTED
    assert refused.convergence.source_effect is SourceEffectStatus.UNKNOWN
    assert all(
        getattr(refused.convergence, item) is ConvergenceState.REBUILD_REQUIRED
        for item in ("store", "index", "link")
    )
    assert refused.convergence.extensions["locator_repair"] != "not_required"
    assert _record(bound) == before and destination.exists()
    assert (bound.owner.root / bound.source).exists() == (phase == "activated")


def test_mvr_effect_window_covers_source_and_durable_authority_receipt(bound, monkeypatch):
    from app.instance.binding_effect_lease import BindingEffectLeaseManager
    from app.instance.runtime import open_local_operator_principal_store
    import os

    request = _request(bound)
    entered, release = Event(), Event()
    store = bound.owner._store

    def pause_after_receipt(root, state, name, record):
        store(root, state, name, record)
        if record["phase"] == "committed" and not entered.is_set():
            entered.set()
            assert release.wait(timeout=5)

    monkeypatch.setattr(bound.owner, "_store", pause_after_receipt)
    leases = BindingEffectLeaseManager.for_runtime(
        registry_store=bound.owner.registry_store,
        ownership_root=Path(os.environ["INSTANCE_OWNERSHIP_ROOT"]),
        state_root=bound.owner.registry_store.path.parent / "binding-effect-leases",
    )
    principal = open_local_operator_principal_store(bound.owner.registry_store.path)

    def exclusive():
        with leases.exclusive_change(
            bound.owner.target_binding_id,
            channel_id=os.environ["PKM_ENVIRONMENT"],
            root=bound.owner.root,
        ):
            return True

    with ThreadPoolExecutor(max_workers=3) as pool:
        placed = pool.submit(_run, bound, request)
        assert entered.wait(timeout=5)
        changed = pool.submit(exclusive)
        revoked = pool.submit(
            principal.rotate_credential,
            credential="synthetic-placement-rotation",
            _capability=STORAGE_MUTATION_CAPABILITY,
        )
        try:
            for pending in (changed, revoked):
                with pytest.raises(TimeoutError):
                    pending.result(timeout=0.1)
        finally:
            release.set()
        assert placed.result(timeout=5).status is OperationStatus.CONVERGENCE_PENDING
        assert changed.result(timeout=5)
        revoked.result(timeout=5)
    assert (
        _record(bound)["receipt"]["governed_write"]["authority_receipt"]["active_context"][
            "principal_context"
        ]["revision"]
        == bound.owner.active_context.principal_context.revision
    )
    assert not (bound.owner.root / bound.source).exists()


@pytest.mark.parametrize("recover", [False, True])
def test_context_expiry_during_real_placement_lock_wait_refuses_effect(
    bound, monkeypatch, recover
):
    # Only shorten the real server-derived snapshot. Real GOV/MVR authority,
    # filesystem locking and the clock remain in the production path.
    expiry = time.time() + 5
    bound.owner.active_context = replace(bound.owner.active_context, expires_at=expiry)
    request = _request(bound)
    source = bound.owner.root / bound.source
    destination = bound.owner.root / "Projects/moved.md"
    raw = source.read_bytes()
    prior = None
    if recover:
        store = bound.owner._store

        def interrupt(root, state, name, record):
            store(root, state, name, record)
            if record["phase"] == "prepared":
                raise Interrupted()

        monkeypatch.setattr(bound.owner, "_store", interrupt)
        with pytest.raises(Interrupted):
            _run(bound, request)
        prior = _record(bound)
        bound = _restart(bound)

    state = bound.owner.root / ".pkm-placement"
    state.mkdir(mode=0o700, exist_ok=True)
    holder = os.open(state / "lock", os.O_RDWR | os.O_CREAT, 0o600)
    flock = fcntl.flock
    flock(holder, fcntl.LOCK_EX)
    lock_inode = os.fstat(holder).st_ino
    queued = Event()
    arrived = []

    def observe_wait(fd, operation):
        if fd != holder and os.fstat(fd).st_ino == lock_inode:
            arrived.append(time.time())
            queued.set()
        return flock(fd, operation)

    monkeypatch.setattr(placement.fcntl, "flock", observe_wait)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            call = operations.reconcile_placement_operation if recover else lambda r, c: _run(c, r)
            pending = pool.submit(call, request, bound)
            try:
                assert queued.wait(timeout=4), "production request never reached the held flock"
                assert arrived[0] < expiry
                time.sleep(max(0, expiry - time.time()) + 0.05)
            finally:
                flock(holder, fcntl.LOCK_UN)
            outcome = pending.result(timeout=5)
    finally:
        os.close(holder)

    assert source.read_bytes() == raw and not destination.exists()
    assert outcome.status is OperationStatus.REJECTED
    if recover:
        assert _record(bound) == prior
        assert outcome.convergence.source_effect is SourceEffectStatus.UNKNOWN
        assert outcome.convergence.store is ConvergenceState.REBUILD_REQUIRED
    else:
        assert not list(state.glob("*.json"))
        assert outcome.convergence.source_effect is SourceEffectStatus.NOT_APPLIED


@pytest.mark.parametrize("phase", ["prepared", "publishing", "retiring", "committed"])
def test_context_expiry_at_later_effect_seams_preserves_observed_truth(
    bound, monkeypatch, phase
):
    expiry = time.time() + 3
    bound.owner.active_context = replace(bound.owner.active_context, expires_at=expiry)
    request = _request(bound)
    source = bound.owner.root / bound.source
    destination = bound.owner.root / "Projects/moved.md"
    raw = source.read_bytes()
    store, fsync = bound.owner._store, placement.os.fsync
    waited = False

    def expire():
        nonlocal waited
        if not waited:
            assert time.time() < expiry, "fixture did not reach the selected live effect seam"
            waited = True
            time.sleep(max(0, expiry - time.time()) + 0.05)

    def persist(root, state, name, record):
        store(root, state, name, record)
        if phase in {"prepared", "committed"} and record["phase"] == phase:
            expire()

    def synchronize(fd):
        fsync(fd)
        inode = os.fstat(fd).st_ino
        if phase == "publishing" and destination.exists() and inode == destination.parent.stat().st_ino:
            expire()
        if phase == "retiring" and not source.exists() and inode == source.parent.stat().st_ino:
            expire()

    monkeypatch.setattr(bound.owner, "_store", persist)
    monkeypatch.setattr(placement.os, "fsync", synchronize)
    outcome = _run(bound, request)
    assert waited and outcome.status is OperationStatus.RECOVERY_REQUIRED
    record = _record(bound)
    assert record["phase"] == phase
    assert bool(record["receipt"]) == (phase == "committed")
    assert not record["cleanup_complete"]
    assert source.exists() == (phase in {"prepared", "publishing"})
    assert destination.exists() == (phase != "prepared")
    assert (source if source.exists() else destination).read_bytes() == raw
    expected = {
        "prepared": SourceEffectStatus.NOT_APPLIED,
        "publishing": SourceEffectStatus.UNKNOWN,
        "retiring": SourceEffectStatus.COMMITTED,
        "committed": SourceEffectStatus.COMMITTED,
    }
    assert outcome.convergence.source_effect is expected[phase]
    transaction = bound.owner.root / ".pkm-placement" / sha256(request.request_id.encode()).hexdigest()
    assert (transaction / "original").exists()
    assert (transaction / "retired").exists() == (phase in {"retiring", "committed"})
    if phase != "prepared":
        assert outcome.convergence.store is ConvergenceState.REBUILD_REQUIRED
        assert outcome.convergence.extensions["locator_repair"] != "not_required"
