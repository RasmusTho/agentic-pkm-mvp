from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from app.ingest.vault_alpha import run_vault_alpha_ingest_paths
from app.knowledge import placement
from app.knowledge.placement import KnowledgePlacementOwner
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
from tests.api._vault_test_helpers import bind_initialized_vault


class Interrupted(BaseException):
    """Simulate process death without the owner's ordinary error handler."""


@pytest.fixture
def bound(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "vault"
    root.mkdir()
    manager = bind_initialized_vault(monkeypatch, root, store_dir=tmp_path)
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
        context_ref="fixture-context",
        vault_generation="generation-1",
        actor="owner",
        context_is_current=lambda: manager.context.status == "selected"
        and manager.context.active_vault_path == str(root),
        authority_is_current=lambda intent: intent.artifact_id == identity
        and intent.operation in {"artifact.move", "artifact.rename"},
        filesystem="local-posix-v1",
    )
    yield operations.PlacementOperationServerConfig(
        owner, OperationContext("fixture-context", "generation-1"), identity, "Notes/original.md"
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
        provenance=OperationProvenance("owner", "direct-test", "test"),
    )


def _delegation(config, request):
    return {
        "active_context_ref": config.context.active_context_ref,
        "vault_generation": config.context.vault_generation,
        "operation_ids": [request.operation_id],
        "policy_version": "policy-1",
        "principal": "owner",
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


@pytest.mark.parametrize("phase", ["reserved", "activated", "retiring", "committed"])
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
    assert _record(bound)["phase"] == "prepared"
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
