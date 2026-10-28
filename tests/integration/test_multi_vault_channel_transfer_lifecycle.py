"""Engine-driven source-owned transfer recovery; no hand-composed registry states."""

import json
import multiprocessing
import os
from pathlib import Path

import pytest

import app.instance.channel_transfer as transfers
from tests._mvr05c_transfer_harness import transfer_pair, reopen


def assert_transferred(source, destination, original, target):
    owners = source.ledger.load()
    assert source.ledger.active_owner(original.vault_binding_id) is None
    assert source.ledger.active_owner(target).channel_id == destination.layout.channel_id
    assert original.vault_binding_id in source.registry.load().removal_tombstones
    assert original.vault_binding_id not in source.registry.load().registrations
    imported = destination.registry.load().registrations[target]
    assert imported.local_instance_id == original.local_instance_id
    assert imported.vault_id == original.vault_id
    assert imported.vault_binding_id != original.vault_binding_id
    lineage = destination.registry.load().transfer_lineage[-1]
    assert lineage.source_binding_id == original.vault_binding_id
    assert lineage.destination_binding_id == target
    assert source.registry.load().transfer_lineage[-1] == lineage
    assert owners.transfer_lineage[-1].source_binding_id == original.vault_binding_id
    assert owners.transfer is None
    assert destination.registry.load().default_vault_binding_id is None


@pytest.mark.parametrize("phase", transfers.PHASES)
def test_production_transfer_recovers_after_every_durable_phase(tmp_path, monkeypatch, phase):
    source, destination, original, lifecycle = transfer_pair(tmp_path, monkeypatch)

    def interrupted_transfer():
        def crash(current):
            if current == phase:
                os._exit(86)

        transfers._fault_point = crash
        source.transfer_to(destination, original.vault_binding_id, stop_and_prove=lifecycle)

    process = multiprocessing.get_context("fork").Process(target=interrupted_transfer)
    process.start()
    process.join(timeout=15)
    assert process.exitcode == 86
    intent = json.loads((source.layout.root / "channel-transfer.json").read_text())
    if transfers.PHASES.index(phase) < transfers.PHASES.index("ownership_activated"):
        assert source.ledger.active_owner(intent["destination_binding_id"]) is None
    monkeypatch.setattr(transfers, "_fault_point", lambda _: None)
    # Reconstruct runtimes after the injected process death over the same stores.
    source, destination = reopen(source), reopen(destination)
    target = source.recover_transfer(destination, stop_and_prove=lifecycle)
    assert target == intent["destination_binding_id"]
    assert_transferred(source, destination, original, target)
    assert source.recover_transfer(destination, stop_and_prove=lifecycle) == target


def test_transfer_drains_and_restart_fences_every_source_lifecycle_before_ownership_move(
    tmp_path, monkeypatch
):
    source, destination, original, lifecycle = transfer_pair(tmp_path, monkeypatch)
    phases = []

    def observe(phase):
        phases.append(phase)
        if phase == "producers_stopped":
            assert source.ledger.active_owner(original.vault_binding_id) is not None
            assert (
                source.ledger.root / f"deployment-{source.layout.channel_id}-restart-fence.json"
            ).exists()
            assert "minimumForegroundOwnership" not in source.registry.load().extensions.get(
                "runtimeFloors", {}
            )

    monkeypatch.setattr(transfers, "_fault_point", observe)
    target = source.transfer_to(destination, original.vault_binding_id, stop_and_prove=lifecycle)
    assert (
        phases.index("rows_drained")
        < phases.index("producers_stopped")
        < phases.index("floor_advanced")
        < phases.index("ownership_reserved")
    )
    assert_transferred(source, destination, original, target)


def test_transfer_source_inventory_covers_every_enabled_vault_bound_producer(tmp_path, monkeypatch):
    source, destination, original, lifecycle = transfer_pair(tmp_path, monkeypatch)
    source.transfer_to(destination, original.vault_binding_id, stop_and_prove=lifecycle)
    intent = json.loads((source.layout.root / "channel-transfer.json").read_text())
    inventory = intent["inventory"]
    assert inventory["channel_id"] == source.layout.channel_id
    assert inventory["vault_bound_effects"].keys() == {
        "api_cli_ingress",
        "compatibility_watcher",
        "scalar_worker_outbox_ingest",
        "settings_reload",
        "heimdal_projection",
        "bootstrap_lifecycle",
    }
    assert all(
        p["stopped"] and p["restart_fenced"] and p["write_handle_released"]
        for p in inventory["producers"]
        if p["enabled"]
    )


def test_transfer_repairs_compatibility_binding_before_source_retirement(tmp_path, monkeypatch):
    from app.instance.settings_rebind import _install_dormant_settings_rebind, SettingsRebindStore
    from tests.helpers.instance_storage_capability import STORAGE_MUTATION_CAPABILITY

    source, destination, original, lifecycle = transfer_pair(tmp_path, monkeypatch)
    _install_dormant_settings_rebind(
        source.registry,
        binding_id=original.vault_binding_id,
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    monkeypatch.setenv("WATCHER_ENABLE", "0")
    target = source.transfer_to(destination, original.vault_binding_id, stop_and_prove=lifecycle)
    record = SettingsRebindStore(source.registry).read()
    assert record.candidate_binding_id is None
    assert record.phase == "no_lifecycle"
    assert record.reload_revision == record.desired_revision
    assert record.prior_binding_id == original.vault_binding_id
    assert_transferred(source, destination, original, target)


def test_transfer_preserves_enabled_watcher_as_idle_without_replacement(tmp_path, monkeypatch):
    from app.instance.settings_rebind import _install_dormant_settings_rebind, SettingsRebindStore
    from tests.helpers.instance_storage_capability import STORAGE_MUTATION_CAPABILITY
    from tests.integration.test_watcher_cross_process_rebind import (
        _configure_watcher,
        _seed_daily_briefing_sentinel,
    )
    from tests.integration.test_multi_vault_picker_context import _running_watcher
    from app.watcher import registry as watcher

    source, destination, original, lifecycle = transfer_pair(tmp_path, monkeypatch)
    _install_dormant_settings_rebind(
        source.registry,
        binding_id=original.vault_binding_id,
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    _seed_daily_briefing_sentinel(Path(original.path))
    config = _configure_watcher(
        monkeypatch, root=tmp_path, runtime=source, vault_a=Path(original.path)
    )
    monkeypatch.setenv("PKM_ENVIRONMENT", source.layout.channel_id)
    watcher.run_registry_once(config)
    running = _running_watcher(config)
    errors = running.__enter__()
    stopped = False
    original_stop = lifecycle

    def stop():
        nonlocal stopped
        if not stopped:
            running.__exit__(None, None, None)
            stopped = True
        return original_stop()

    lifecycle = stop
    try:
        target = source.transfer_to(
            destination, original.vault_binding_id, stop_and_prove=lifecycle
        )
    finally:
        if not stopped:
            running.__exit__(None, None, None)
    assert not errors
    record = SettingsRebindStore(source.registry).read()
    assert record.candidate_binding_id is None
    assert record.phase == "committed" and record.lifecycle_posture == "watcher"
    assert record.reload_revision == record.desired_revision
    # A new watcher cannot rebind from its old environment after a durable CLEAR.
    assert_transferred(source, destination, original, target)


def test_transfer_refuses_source_drift_without_reinstalling_old_registration(tmp_path, monkeypatch):
    from dataclasses import replace
    from tests.helpers.instance_storage_capability import STORAGE_MUTATION_CAPABILITY

    source, destination, original, lifecycle = transfer_pair(tmp_path, monkeypatch)

    class Crash(BaseException):
        pass

    def crash(phase):
        if phase == "intent":
            raise Crash()

    monkeypatch.setattr(transfers, "_fault_point", crash)
    with pytest.raises(Crash):
        source.transfer_to(destination, original.vault_binding_id, stop_and_prove=lifecycle)
    current = source.registry.lookup(original.vault_binding_id)
    changed = replace(
        current, extensions={**current.extensions, "contentEpoch": 91, "bindingRevision": 91}
    )
    source.registry.update_registration(changed, _capability=STORAGE_MUTATION_CAPABILITY)
    monkeypatch.setattr(transfers, "_fault_point", lambda _: None)
    with pytest.raises(RuntimeError, match="source identity or provenance changed"):
        reopen(source).recover_transfer(reopen(destination), stop_and_prove=lifecycle)
    assert source.registry.lookup(original.vault_binding_id) == changed
    assert source.ledger.active_owner(original.vault_binding_id) is not None
    assert not destination.registry.load().transfer_lineage


def test_transfer_rejects_caller_authored_stopped_proof_before_floor(tmp_path, monkeypatch):
    from app.instance.instance_state import DeploymentQuiescenceProof

    source, destination, original, _ = transfer_pair(tmp_path, monkeypatch)
    fake = DeploymentQuiescenceProof(
        channel_id=source.layout.channel_id, nonce="forged", inventory_digest="forged"
    )
    with pytest.raises(RuntimeError, match="quiescence"):
        source.transfer_to(destination, original.vault_binding_id, stop_and_prove=lambda: fake)
    assert source.ledger.active_owner(original.vault_binding_id) is not None
    assert "minimumForegroundOwnership" not in source.registry.load().extensions.get(
        "runtimeFloors", {}
    )


@pytest.mark.parametrize(
    "boundary",
    [
        "ingress",
        "source_floor",
        "destination_floor",
        "source_retirement",
        "destination_registration",
        "ledger_reservation",
        "ledger_activation",
        "rebind_prepare",
        "rebind_commit",
        "rebind_reload",
    ],
)
def test_transfer_recovers_from_internal_durable_boundaries(tmp_path, monkeypatch, boundary):
    from app.instance.vault_registry import VaultRegistryStore
    from app.instance.ownership_ledger import OwnershipLedger
    from app.instance.settings_rebind import SettingsRebindStore, _install_dormant_settings_rebind
    from tests.helpers.instance_storage_capability import STORAGE_MUTATION_CAPABILITY

    source, destination, original, stop = transfer_pair(tmp_path, monkeypatch)
    _install_dormant_settings_rebind(
        source.registry,
        binding_id=original.vault_binding_id,
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    monkeypatch.setenv("WATCHER_ENABLE", "0")

    def interrupted():
        def wrap(cls, name, predicate=lambda *_: True):
            method = getattr(cls, name)

            def call(owner, *args, **kwargs):
                result = method(owner, *args, **kwargs)
                if predicate(owner, result):
                    os._exit(87)
                return result

            setattr(cls, name, call)

        if boundary in {"ingress", "source_floor", "destination_floor", "destination_registration"}:

            def condition(owner, result):
                source_registry = owner.path == source.registry.path
                floors = result.extensions.get("runtimeFloors", {})
                if boundary == "ingress":
                    return source_registry and "channelTransfer" in result.extensions
                if boundary == "source_floor":
                    return source_registry and floors.get("minimumForegroundOwnership")
                if boundary == "destination_floor":
                    return not source_registry and floors.get("minimumForegroundOwnership")
                return not source_registry and bool(result.transfer_lineage)

            wrap(
                VaultRegistryStore,
                "advance_foreground_ownership_floor"
                if boundary in {"source_floor", "destination_floor"}
                else "commit_state",
                condition,
            )
        elif boundary == "source_retirement":
            wrap(VaultRegistryStore, "remove_registration")
        elif boundary.startswith("ledger_"):
            wrap(
                OwnershipLedger,
                "begin_transfer" if boundary.endswith("reservation") else "activate_transfer",
            )
        else:
            name = {
                "rebind_prepare": "prepare",
                "rebind_commit": "commit_selection",
                "rebind_reload": "reload_once",
            }[boundary]
            wrap(SettingsRebindStore, name)
        source.transfer_to(destination, original.vault_binding_id, stop_and_prove=stop)

    child = multiprocessing.get_context("fork").Process(target=interrupted)
    child.start()
    child.join(timeout=15)
    assert child.exitcode == 87
    target = reopen(source).recover_transfer(reopen(destination), stop_and_prove=stop)
    assert_transferred(source, destination, original, target)


@pytest.mark.parametrize("moving", ["parent", "child"])
def test_transfer_refuses_cross_channel_nested_live_owner_before_any_registry_effect(
    tmp_path, monkeypatch, moving
):
    from tests.helpers.vault_settings import initialize_test_vault

    source, destination, parent, stop = transfer_pair(tmp_path, monkeypatch)
    child_root = Path(parent.path) / "child"
    initialize_test_vault(child_root)
    child = source.production_register(child_root, producer="picker")
    selected = parent if moving == "parent" else child
    source_before = source.registry.path.read_bytes()
    destination_before = destination.registry.path.read_bytes()
    ledger_before = source.ledger.load()
    with pytest.raises(RuntimeError, match="overlap"):
        source.transfer_to(destination, selected.vault_binding_id, stop_and_prove=stop)
    assert source.registry.path.read_bytes() == source_before
    assert destination.registry.path.read_bytes() == destination_before
    assert source.ledger.load() == ledger_before
    assert not (source.layout.root / "channel-transfer.json").exists()


def test_ledger_transfer_allows_same_destination_channel_nesting_and_historical_tombstones(
    tmp_path,
):
    from app.instance.ownership_ledger import OwnershipLedger
    from tests.helpers.instance_storage_capability import STORAGE_MUTATION_CAPABILITY as cap

    ledger = OwnershipLedger(tmp_path / "owners")
    root = tmp_path / "parent"
    (root / "child").mkdir(parents=True)
    for binding, path in (("parent", root), ("child", root / "child")):
        ledger.reserve(
            channel_id="source",
            vault_binding_id=binding,
            root=path,
            allow_same_channel_nested=True,
            _capability=cap,
        )
        ledger.activate(binding, _capability=cap)
    ledger.begin_transfer(
        source_binding_id="parent",
        destination_channel_id="source",
        destination_binding_id="parent-replacement",
        _capability=cap,
    )
    ledger.activate_transfer(_capability=cap)
    assert ledger.active_owner("child").channel_id == "source"
    ledger.release_to_tombstone("child", _capability=cap)
    # Historical predecessor roots are history, never a live ownership collision.
    ledger.begin_transfer(
        source_binding_id="parent-replacement",
        destination_channel_id="destination",
        destination_binding_id="destination-parent",
        _capability=cap,
    )
    ledger.activate_transfer(_capability=cap)
    assert ledger.active_owner("destination-parent").channel_id == "destination"


def test_ledger_activation_rechecks_new_live_overlap(tmp_path, monkeypatch):
    from app.instance.ownership_ledger import OwnershipLedger
    from tests.helpers.instance_storage_capability import STORAGE_MUTATION_CAPABILITY as cap

    ledger = OwnershipLedger(tmp_path / "owners")
    root = tmp_path / "parent"
    (root / "child").mkdir(parents=True)
    ledger.reserve(channel_id="source", vault_binding_id="parent", root=root, _capability=cap)
    ledger.activate("parent", _capability=cap)
    ledger.begin_transfer(
        source_binding_id="parent",
        destination_channel_id="destination",
        destination_binding_id="destination-parent",
        _capability=cap,
    )
    original = ledger._assert_no_collision
    # Simulate an independently restored incompatible pending row at the external
    # state boundary; the final activation check must independently reject it.
    monkeypatch.setattr(ledger, "_assert_no_collision", lambda *_args, **_kwargs: None)
    ledger.reserve(
        channel_id="source", vault_binding_id="late-child", root=root / "child", _capability=cap
    )
    monkeypatch.setattr(ledger, "_assert_no_collision", original)
    with pytest.raises(RuntimeError, match="overlap"):
        ledger.activate_transfer(_capability=cap)
    assert ledger.active_owner("destination-parent") is None
    assert ledger.load().transfer is not None


@pytest.mark.parametrize("blocker", ["stale_queue", "missing_inventory", "source_restart"])
def test_transfer_refuses_incomplete_source_proof_without_moving_ownership(
    tmp_path, monkeypatch, blocker
):
    from app.instance import principal_fence
    from app.services import outbox
    from app.workers import outbox_worker as worker

    source, destination, original, stop = transfer_pair(tmp_path, monkeypatch)
    if blocker == "stale_queue":
        stale = [
            {
                "id": "stale-source",
                "vault_binding_id": original.vault_binding_id,
                "payload": {"legacy_key": "unchanged"},
            }
        ]
        monkeypatch.setattr(outbox, "pending_transfer_rows", lambda *_a, **_k: list(stale))
        monkeypatch.setattr(worker, "poll_outbox_one", lambda **_: None)
        monkeypatch.setattr(worker, "count_deferred_outbox_rows", lambda **_: 1)
    elif blocker == "missing_inventory":
        discover = principal_fence.discover_auth_producers

        def incomplete(**kwargs):
            producers, digest = discover(**kwargs)
            return tuple(p for p in producers if p.role != "watcher"), digest

        monkeypatch.setattr(principal_fence, "discover_auth_producers", incomplete)
    else:

        def restart(phase):
            if phase == "producers_stopped":
                (
                    source.ledger.root / f"deployment-{source.layout.channel_id}-restart-fence.json"
                ).unlink()

        monkeypatch.setattr(transfers, "_fault_point", restart)
    with pytest.raises(RuntimeError):
        source.transfer_to(destination, original.vault_binding_id, stop_and_prove=stop)
    assert source.ledger.active_owner(original.vault_binding_id) is not None
    assert not destination.registry.load().transfer_lineage
    assert "minimumForegroundOwnership" not in source.registry.load().extensions.get(
        "runtimeFloors", {}
    )
    if blocker == "stale_queue":
        assert stale == [
            {
                "id": "stale-source",
                "vault_binding_id": original.vault_binding_id,
                "payload": {"legacy_key": "unchanged"},
            }
        ]


def test_foreground_floor_atomically_qualifies_schema_and_old_reader_refuses(tmp_path, monkeypatch):
    import subprocess
    import sys
    import types
    from app.instance.vault_registry import CURRENT_REGISTRY_SCHEMA, FOREGROUND_REGISTRY_SCHEMA

    source, destination, original, stop = transfer_pair(tmp_path, monkeypatch)
    assert source.registry.load().schema == CURRENT_REGISTRY_SCHEMA
    source.transfer_to(destination, original.vault_binding_id, stop_and_prove=stop)
    assert (
        source.registry.load().schema
        == destination.registry.load().schema
        == FOREGROUND_REGISTRY_SCHEMA
    )
    old_source = subprocess.check_output(
        ["git", "show", "fb9d4406d16846b2878edc1f521e1108761ee9ad:app/instance/vault_registry.py"],
        text=True,
    )
    module = types.ModuleType("tests._mvr05c_previous_registry_image")
    monkeypatch.setitem(sys.modules, module.__name__, module)
    exec(compile(old_source, "previous-registry-image.py", "exec"), module.__dict__)
    for runtime in (source, destination):
        before = runtime.registry.path.read_bytes()
        with pytest.raises(RuntimeError, match="schema mismatch"):
            module.VaultRegistryStore(runtime.registry.path).read_existing()
        assert runtime.registry.path.read_bytes() == before
