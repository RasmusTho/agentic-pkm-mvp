from __future__ import annotations

import multiprocessing
import os
from pathlib import Path

import pytest

import app.instance.binding_effect_lease as lease_module
from app.instance.binding_effect_lease import BindingEffectLeaseError
from app.instance.vault_registry import RegistryError
from tests.instance.test_binding_effect_lease import _build_manager, _manager_for_existing


def _crash_inside_shared(root: str, acquired) -> None:
    manager = _manager_for_existing(root)
    vault = Path(root) / "vaults" / "binding-a"
    with manager.shared_effect("binding-a", channel_id="dev", root=vault, timeout=5):
        acquired.set()
        os._exit(17)


def _crash_inside_exclusive(root: str, acquired) -> None:
    manager = _manager_for_existing(root)
    vault = Path(root) / "vaults" / "binding-a"
    with manager.exclusive_change("binding-a", channel_id="dev", root=vault, timeout=5):
        acquired.set()
        os._exit(19)


def test_crashed_holder_recovers_without_deadlock_or_false_completion(tmp_path) -> None:
    _build_manager(tmp_path, "binding-a")
    context = multiprocessing.get_context("spawn")
    acquired = context.Event()
    process = context.Process(target=_crash_inside_shared, args=(str(tmp_path), acquired))
    process.start()
    assert acquired.wait(3)
    process.join(5)
    assert process.exitcode == 17

    manager = _manager_for_existing(str(tmp_path))
    vault = tmp_path / "vaults" / "binding-a"
    with manager.exclusive_change("binding-a", channel_id="dev", root=vault, timeout=2):
        observation = manager.observe("binding-a")
        assert observation.shared_count == 0
        assert observation.exclusive_held

    persisted = manager.persisted_state("binding-a")
    assert "completed" not in persisted
    assert "completion" not in persisted


def test_crashed_exclusive_holder_recovers_for_a_later_shared_effect(tmp_path) -> None:
    _build_manager(tmp_path, "binding-a")
    context = multiprocessing.get_context("spawn")
    acquired = context.Event()
    process = context.Process(target=_crash_inside_exclusive, args=(str(tmp_path), acquired))
    process.start()
    assert acquired.wait(3)
    process.join(5)
    assert process.exitcode == 19

    manager = _manager_for_existing(str(tmp_path))
    vault = tmp_path / "vaults" / "binding-a"
    with manager.shared_effect("binding-a", channel_id="dev", root=vault, timeout=2):
        assert manager.observe("binding-a").shared_count == 1


@pytest.mark.parametrize("crash_point", ["journal", "state"])
def test_pre_registry_commit_crash_rolls_back_from_the_separate_journal(
    tmp_path, monkeypatch, crash_point
) -> None:
    manager = _build_manager(tmp_path, "binding-a")
    vault = tmp_path / "vaults" / "binding-a"
    state_path = manager._state_path("binding-a")
    journal_path = manager._journal_path("binding-a")
    real_write = manager._atomic_private_json

    def interrupt_during_outer_commit(path, value) -> None:
        real_write(path, value)
        if path == journal_path and crash_point == "journal":
            raise KeyboardInterrupt("crash after lease journal prepare")
        if path == state_path and crash_point == "state" and value.get("generation") == 1:
            raise KeyboardInterrupt("crash after lease state write")

    monkeypatch.setattr(manager, "_atomic_private_json", interrupt_during_outer_commit)
    with pytest.raises(KeyboardInterrupt, match="crash after lease"):
        with manager.shared_effect("binding-a", channel_id="dev", root=vault, timeout=1):
            pytest.fail("the interrupted acquisition cannot expose an effect window")
    assert journal_path.exists()

    recovered = _manager_for_existing(str(tmp_path))
    observation = recovered.observe("binding-a")
    assert observation.shared_count == 0
    assert not observation.exclusive_held
    assert not journal_path.exists()


def test_registry_post_commit_error_converges_to_committed_journal_endpoint(
    tmp_path, monkeypatch
) -> None:
    manager = _build_manager(tmp_path, "binding-a")
    vault = tmp_path / "vaults" / "binding-a"
    real_verify = manager.registry_store._verify_generation
    calls = 0

    def fail_first_post_commit_verification(generation) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RegistryError("post-commit verification failed")
        real_verify(generation)

    monkeypatch.setattr(
        manager.registry_store,
        "_verify_generation",
        fail_first_post_commit_verification,
    )
    with manager.shared_effect("binding-a", channel_id="dev", root=vault, timeout=1):
        assert manager.observe("binding-a").shared_count == 1

    assert not manager._journal_path("binding-a").exists()
    assert (
        manager.persisted_state("binding-a")
        == manager.registry_store.load().extensions["bindingEffectLeases"]["binding-a"]
    )


def test_journal_less_registry_state_divergence_fails_closed(tmp_path) -> None:
    manager = _build_manager(tmp_path, "binding-a")
    vault = tmp_path / "vaults" / "binding-a"
    with manager.shared_effect("binding-a", channel_id="dev", root=vault, timeout=1):
        pass
    state = manager.persisted_state("binding-a")
    manager._atomic_private_json(
        manager._state_path("binding-a"),
        {**state, "generation": int(state["generation"]) + 1},
    )

    with pytest.raises(BindingEffectLeaseError, match="diverges from registry"):
        manager.observe("binding-a")


def test_unreadable_registry_retains_outer_journal_until_recovery(tmp_path, monkeypatch) -> None:
    manager = _build_manager(tmp_path, "binding-a")
    vault = tmp_path / "vaults" / "binding-a"
    real_registry_state = manager._registry_state
    producer_failed = False

    def fail_before_registry_commit(*args, **kwargs) -> None:
        nonlocal producer_failed
        producer_failed = True
        raise RegistryError("registry unavailable")

    def unreadable_after_failure(binding_id):
        if producer_failed:
            raise RegistryError("registry still unavailable")
        return real_registry_state(binding_id)

    monkeypatch.setattr(
        manager.registry_store,
        "set_binding_effect_lease_state",
        fail_before_registry_commit,
    )
    monkeypatch.setattr(manager, "_registry_state", unreadable_after_failure)
    with pytest.raises(RegistryError, match="still unavailable"):
        with manager.shared_effect("binding-a", channel_id="dev", root=vault, timeout=1):
            pytest.fail("an indeterminate commit cannot expose an effect window")
    assert manager._journal_path("binding-a").exists()

    recovered = _manager_for_existing(str(tmp_path))
    assert recovered.observe("binding-a").shared_count == 0
    assert not recovered._journal_path("binding-a").exists()


def test_third_registry_endpoint_retains_journal_and_fails_closed(tmp_path, monkeypatch) -> None:
    manager = _build_manager(tmp_path, "binding-a")
    vault = tmp_path / "vaults" / "binding-a"
    real_producer = manager.registry_store.set_binding_effect_lease_state

    def commit_third_endpoint(binding_id, state, **kwargs) -> None:
        third = {**state, "generation": int(state["generation"]) + 1}
        real_producer(binding_id, third, **kwargs)
        raise RegistryError("ambiguous registry outcome")

    monkeypatch.setattr(
        manager.registry_store,
        "set_binding_effect_lease_state",
        commit_third_endpoint,
    )
    with pytest.raises(BindingEffectLeaseError, match="both journal endpoints"):
        with manager.shared_effect("binding-a", channel_id="dev", root=vault, timeout=1):
            pytest.fail("a third endpoint cannot expose an effect window")
    assert manager._journal_path("binding-a").exists()

    recovered = _manager_for_existing(str(tmp_path))
    with pytest.raises(BindingEffectLeaseError, match="diverges from registry"):
        recovered.observe("binding-a")
    assert recovered._journal_path("binding-a").exists()


def test_process_identity_refuses_untrustworthy_fallback_and_pid_reuse(
    tmp_path, monkeypatch
) -> None:
    manager = _build_manager(tmp_path, "binding-a")
    start, _ = manager._process_identity(os.getpid())
    stale = {
        "holderId": "stale",
        "pid": os.getpid(),
        "processStart": f"{start}-previous-incarnation",
        "ticket": 1,
        "mode": "pending",
    }
    assert not manager._holder_alive(stale)

    def no_procfs(*args, **kwargs):
        raise OSError("procfs unavailable")

    def no_ps(*args, **kwargs):
        raise FileNotFoundError("ps unavailable")

    monkeypatch.setattr(Path, "read_text", no_procfs)
    monkeypatch.setattr(lease_module.subprocess, "run", no_ps)
    with pytest.raises(BindingEffectLeaseError, match="trustworthy process-incarnation"):
        manager._process_identity(os.getpid())
