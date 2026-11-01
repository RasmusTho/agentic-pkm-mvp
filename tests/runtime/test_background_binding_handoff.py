"""MVR-06B (#3864): durable compatibility handoff, restart, and worker replacement.

`docs/MULTI_VAULT_RUNTIME/BIND_BACKGROUND_LIFECYCLES.md` (MVR-06B). Every state here is
produced by shipped producers (see ``tests/_mvr06b_handoff_harness.py``); restart is a
fresh runtime/supervisor over the same durable instance-state volume.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from app.instance.background_authority import BackgroundIntentNotReadyError
from app.instance.background_supervisor import (
    BackgroundBindingIdle,
    background_capability_digest,
    durable_background_state,
)
from app.instance.binding_effect_lease import BindingEffectLeaseManager
from app.instance.context_selection import ContextSelectionStore
from app.instance.runtime import (
    open_background_role_store,
    open_default_vault_service,
)
from app.instance.scalar_binding_runtime import (
    resolve_background_worker_runtime,
    validate_frozen_binding_runtime,
)
from app.vault.active_context_v1 import PrincipalContext, WorkspaceState
from tests._mvr06b_handoff_harness import (
    admin,
    background_ids,
    bind_runtime_env,
    handoff_through_cli,
    mvr06a_instance,
    mvr06b_instance,
    pick,
    stub_settings_reload,
    supervisor,
)
from tests._mvr_default_vault_harness import reopen_runtime
from tests.helpers.instance_storage_capability import STORAGE_MUTATION_CAPABILITY

pytestmark = pytest.mark.not_pg


def test_compatibility_handoff_binding_survives_restart_without_default_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, first, (second,) = mvr06a_instance(tmp_path)
    bind_runtime_env(monkeypatch, runtime)
    reloads = stub_settings_reload(monkeypatch)
    # The live bridge binding differs from the instance default before the handoff.
    pick(runtime, second.vault_binding_id)
    assert runtime.registry.load().default_vault_binding_id == first.vault_binding_id

    receipt = handoff_through_cli(runtime)
    assert receipt["_exit_code"] == 0, receipt
    assert receipt["compatibility_binding_id"] == second.vault_binding_id

    restarted = reopen_runtime(runtime, tmp_path)
    lifecycle = supervisor(restarted).start()
    assert lifecycle.status == "running"
    assert lifecycle.binding_id == second.vault_binding_id  # not the default
    assert background_ids(restarted) == (second.vault_binding_id,)

    # Compatibility mode: a legacy choose/open picker event moves it ...
    pick(restarted, first.vault_binding_id)
    assert background_ids(restarted) == (first.vault_binding_id,)
    # ... and so does an explicit MVR-02 default set, and a clear (truthful no-vault:
    # no legacy bootstrap env is configured).
    defaults = open_default_vault_service(restarted.layout.registry_path)
    defaults.set(second.vault_binding_id)
    assert background_ids(restarted) == (second.vault_binding_id,)
    defaults.clear()
    assert background_ids(restarted) == ()
    state = durable_background_state(restarted.registry.load())
    assert state is not None and state.mode == "compatibility"
    assert reloads  # every committed rebind reloaded through SETTINGS-01

    # Governed background administration enters explicit mode.
    receipt_add = admin(restarted).add(first.vault_binding_id)
    assert receipt_add["mode"] == "explicit"
    assert background_ids(restarted) == (first.vault_binding_id,)
    from app.instance.settings_rebind import SettingsRebindCandidatePolicyError

    with pytest.raises(SettingsRebindCandidatePolicyError):
        pick(restarted, second.vault_binding_id)
    defaults.set(second.vault_binding_id)
    assert background_ids(restarted) == (first.vault_binding_id,)


def test_env_only_single_vault_upgrade_preserves_compatibility_watcher(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests._mvr03_principal_harness import provisioned_instance
    from tests._mvr06_background_harness import (
        record_mvr05_floor,
        run_background_cutover_through_cli,
    )
    from app.instance.settings_rebind import _install_dormant_settings_rebind

    # A headless one-vault install: only the env bootstrap, no default, no picker binding.
    runtime, first, _extra, _principal = provisioned_instance(
        tmp_path, set_instance_default=False
    )
    record_mvr05_floor(runtime)
    _install_dormant_settings_rebind(runtime.registry, _capability=STORAGE_MUTATION_CAPABILITY)
    assert run_background_cutover_through_cli(runtime)["_exit_code"] == 0
    bind_runtime_env(monkeypatch, runtime)
    before = runtime.registry.load()
    assert before.default_vault_binding_id is None
    assert before.settings_rebind["candidateBindingId"] is None

    # An unregistered bootstrap root is refused: MVR-06 never creates a binding.
    stray = tmp_path / "stray"
    stray.mkdir()
    refused = handoff_through_cli(runtime, legacy_bootstrap_root=stray)
    assert refused["_exit_code"] == 1
    assert durable_background_state(runtime.registry.load()) is None
    assert runtime.registry.load().registrations == before.registrations

    receipt = handoff_through_cli(runtime, legacy_bootstrap_root=Path(first.path))
    assert receipt["_exit_code"] == 0, receipt
    after = runtime.registry.load()
    assert set(after.registrations) == set(before.registrations)
    assert background_ids(runtime) == (first.vault_binding_id,)
    # The shared phase journal adopts the migrated bootstrap, so the watcher stays bound.
    assert after.settings_rebind["candidateBindingId"] == first.vault_binding_id

    restarted = reopen_runtime(runtime, tmp_path)
    lifecycle = supervisor(restarted).start()
    assert lifecycle.status == "running"
    assert lifecycle.binding_id == first.vault_binding_id


def test_remove_last_then_restart_preserves_explicit_empty_intent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, first, _extra = mvr06b_instance(tmp_path, monkeypatch)
    stub_settings_reload(monkeypatch)
    assert background_ids(runtime) == (first.vault_binding_id,)

    receipt = admin(runtime).remove(first.vault_binding_id)
    assert receipt["explicit_empty"] is True

    restarted = reopen_runtime(runtime, tmp_path)
    listing = admin(restarted).list()
    assert listing["mode"] == "explicit"
    assert listing["explicit_empty"] is True
    assert listing["background_vault_binding_ids"] == []
    # The instance default still names the binding, yet it is never re-enrolled.
    assert restarted.registry.load().default_vault_binding_id == first.vault_binding_id
    lifecycle = supervisor(restarted).start()
    assert lifecycle.status == "idle" and lifecycle.binding_id is None
    assert lifecycle.context is not None and lifecycle.context.is_no_vault
    with pytest.raises(BackgroundBindingIdle):
        resolve_background_worker_runtime(vault_root=Path(first.path))
    # Idempotent: removing again commits no new revision.
    assert admin(restarted).remove(first.vault_binding_id)["changed"] is False


def test_mvr06b_restart_uses_only_durable_authorized_singleton_or_empty_intent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, first, (second,) = mvr06b_instance(tmp_path, monkeypatch)
    stub_settings_reload(monkeypatch)
    before = durable_background_state(runtime.registry.load())

    # A retained session selection and a request override name another binding.
    store = ContextSelectionStore()
    snapshot = runtime.registry.load()
    store.create(
        principal=PrincipalContext(
            principal_id="local-operator", principal_kind="delegated_operator_role",
            subject="trusted_loopback",
        ),
        instance_identity=snapshot.app_install_id,
        workspace=WorkspaceState.none(),
        scope="default",
        sphere_memberships=(),
        situated_identity=None,
        binding_ids=(second.vault_binding_id,),
    )
    from app.instance.default_vault import resolve_vault_selection

    foreground = resolve_vault_selection(snapshot, session_selection=second.vault_binding_id)
    assert foreground.vault_binding_id == second.vault_binding_id

    restarted = reopen_runtime(runtime, tmp_path)
    assert durable_background_state(restarted.registry.load()) == before
    lifecycle = supervisor(restarted).start()
    assert lifecycle.binding_id == first.vault_binding_id

    # Every member is re-authorized at start: a revoked background role fails loudly
    # rather than silently redirecting or running unauthorized.
    open_background_role_store(restarted.layout.registry_path).revoke(
        _capability=STORAGE_MUTATION_CAPABILITY
    )
    failed = supervisor(restarted).start()
    assert failed.status == "failed" and "authorization" in (failed.failure or "")
    assert failed.binding_id is None or failed.binding_id == first.vault_binding_id

    # Explicit-empty intent is also exactly reconstructed.
    open_background_role_store(restarted.layout.registry_path).redelegate(
        delegator=__import__(
            "app.instance.runtime", fromlist=["open_local_operator_principal_store"]
        ).open_local_operator_principal_store(restarted.layout.registry_path).require(),
        floor_guard=lambda: True,
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    admin(restarted).remove(first.vault_binding_id)
    again = reopen_runtime(restarted, tmp_path)
    assert supervisor(again).start().status == "idle"


def test_scalar_worker_handoff_is_atomic_versioned_and_intent_gated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, first, (second,) = mvr06a_instance(tmp_path)
    bind_runtime_env(monkeypatch, runtime)
    stub_settings_reload(monkeypatch)
    monkeypatch.setenv("VAULT_ROOT", first.path)

    # Before the handoff the MVR-05 scalar worker resolves the env root and intent
    # mutation is sealed.
    scalar = resolve_background_worker_runtime(vault_root=Path(first.path))
    assert scalar is not None and scalar.intent_revision is None
    assert not scalar.background_worker
    with pytest.raises(BackgroundIntentNotReadyError):
        admin(runtime).add(first.vault_binding_id)

    # A failed handoff leaves the old worker/bridge authoritative and mutation sealed.
    def fail(stage: str) -> None:
        if stage == "before_commit":
            raise RuntimeError("injected handoff failure")

    monkeypatch.setattr("app.instance.background_supervisor._handoff_fault_point", fail)
    with pytest.raises(RuntimeError, match="injected handoff failure"):
        handoff_through_cli(runtime)
    assert durable_background_state(runtime.registry.load()) is None
    with pytest.raises(BackgroundIntentNotReadyError):
        admin(runtime).add(first.vault_binding_id)
    monkeypatch.setattr(
        "app.instance.background_supervisor._handoff_fault_point", lambda stage: None
    )

    # The handoff drains the in-flight scalar worker effect before it commits.
    leases = BindingEffectLeaseManager.for_runtime(
        registry_store=runtime.registry,
        ownership_root=runtime.ledger.root,
        state_root=runtime.layout.root / "binding-effect-leases",
    )
    in_flight = threading.Event()
    release = threading.Event()

    def worker_effect() -> None:
        with leases.shared_effect(
            first.vault_binding_id, channel_id=runtime.layout.channel_id, root=Path(first.path)
        ):
            in_flight.set()
            release.wait(10)

    holder = threading.Thread(target=worker_effect)
    holder.start()
    assert in_flight.wait(5)
    result: dict = {}
    handoff = threading.Thread(target=lambda: result.update(handoff_through_cli(runtime)))
    handoff.start()
    time.sleep(0.5)
    assert durable_background_state(runtime.registry.load()) is None  # still draining
    release.set()
    holder.join(10)
    handoff.join(30)
    assert result.get("_exit_code") == 0, result

    # The replacement consumes explicit versioned binding state.
    versioned = resolve_background_worker_runtime(vault_root=Path(first.path))
    assert versioned is not None and versioned.background_worker
    state = durable_background_state(runtime.registry.load())
    assert state is not None and versioned.intent_revision == state.intent_revision
    assert versioned.background_context_digest == background_capability_digest(
        instance_identity=runtime.registry.load().app_install_id,
        intent_revision=state.intent_revision,
        binding_id=first.vault_binding_id,
        generation=1,
    )
    # Never a worker on another binding: the env/selected root must be durable intent.
    with pytest.raises(Exception, match="not the durable background binding"):
        resolve_background_worker_runtime(vault_root=Path(second.path))
    # A later intent revision invalidates the held worker before its next dispatch.
    admin(runtime).remove(first.vault_binding_id)
    with pytest.raises(Exception, match="revision changed before dispatch|background worker binding"):
        validate_frozen_binding_runtime(versioned)


def test_background_context_has_explicit_workspace_and_capability_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, first, _extra = mvr06b_instance(tmp_path, monkeypatch)
    for consumer in ("watcher", "worker", "settings"):
        lifecycle = supervisor(runtime, consumer).start()
        context = lifecycle.context
        assert context is not None
        assert context.workspace.state == "no_workspace"
        assert context.principal_context.principal_kind == "background_runtime_role"
        assert context.principal_context.subject == "instance_background_runtime"
        role = open_background_role_store(runtime.layout.registry_path).require()
        assert context.principal_context.principal_id == role.background_runtime_role_id
        assert context.binding_ids == (first.vault_binding_id,)
        assert context.selection_provenance == "compatibility_handoff"
        state = durable_background_state(runtime.registry.load())
        assert state is not None
        expected = background_capability_digest(
            instance_identity=runtime.registry.load().app_install_id,
            intent_revision=state.intent_revision,
            binding_id=first.vault_binding_id,
            generation=lifecycle.generation,
        )
        assert context.selection_capability_digest == expected
        assert f"selection_capability_digest={expected}" in context.context_identity_components()
        # Domain-separated and bound to generation: never a reusable bearer.
        assert expected != background_capability_digest(
            instance_identity=runtime.registry.load().app_install_id,
            intent_revision=state.intent_revision,
            binding_id=first.vault_binding_id,
            generation=lifecycle.generation + 1,
        )
    # The digest grants nothing: revoking the role blocks effects though it is unchanged.
    sup = supervisor(runtime)
    held = sup.start()
    with sup.effect() as effecting:
        assert effecting.binding_id == first.vault_binding_id
    open_background_role_store(runtime.layout.registry_path).revoke(
        _capability=STORAGE_MUTATION_CAPABILITY
    )
    with pytest.raises(Exception):
        with sup.effect():
            pass
    assert held.context is not None and held.context.selection_capability_digest
