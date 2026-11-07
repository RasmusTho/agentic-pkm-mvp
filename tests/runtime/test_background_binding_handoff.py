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

    # The shipped deploy step passes no root and may see no vault, or the image's own empty
    # directory at the registered path: durable enrollment and the stopped window suffice.
    from app.instance.background_supervisor import run_compatibility_bridge_handoff

    root = Path(first.path)
    unmounted = tmp_path / "vault-not-mounted"
    root.rename(unmounted)
    root.mkdir()  # a different directory (different inode) than the leased host mount
    try:
        handed = run_compatibility_bridge_handoff(
            runtime.registry,
            channel_id=runtime.layout.channel_id,
            ownership_root=runtime.ledger.root,
            stopped_window_proven=True,
            _capability=STORAGE_MUTATION_CAPABILITY,
        )
    finally:
        root.rmdir()
        unmounted.rename(root)
    receipt = handoff_through_cli(runtime)
    assert receipt["_exit_code"] == 0, receipt
    assert receipt["handed_off"] is False and handed.handed_off is True
    after = runtime.registry.load()
    assert set(after.registrations) == set(before.registrations)
    assert background_ids(runtime) == (first.vault_binding_id,)
    # The shared phase journal adopts the migrated bootstrap, so the watcher stays bound.
    assert after.settings_rebind["candidateBindingId"] == first.vault_binding_id

    restarted = reopen_runtime(runtime, tmp_path)
    lifecycle = supervisor(restarted).start()
    assert lifecycle.status == "running"
    assert lifecycle.binding_id == first.vault_binding_id

    # The real production watcher keeps watching that binding after restart.
    from app.watcher import registry as watcher_registry
    from tests._mvr06b_handoff_harness import configure_watcher, outbox_paths
    from tests.helpers.vault_settings import initialize_test_vault

    initialize_test_vault(Path(first.path))
    bind_runtime_env(monkeypatch, restarted, watcher=True)
    config = configure_watcher(monkeypatch, tmp_path, restarted, Path(first.path))
    note = Path(first.path) / "still-watched-after-upgrade.md"
    note.write_text("env-only install\n", encoding="utf-8")
    watcher_registry.run_registry_once(config)
    assert str(note) in outbox_paths(tmp_path)


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
    from app.instance.background_supervisor import run_compatibility_bridge_handoff

    result: dict = {}

    def live_handoff() -> None:
        # Outside a proved stopped window nothing has stopped the worker: the exclusive
        # lease must drain it before the commit.
        result["receipt"] = run_compatibility_bridge_handoff(
            runtime.registry,
            channel_id=runtime.layout.channel_id,
            ownership_root=runtime.ledger.root,
            _capability=STORAGE_MUTATION_CAPABILITY,
        )

    handoff = threading.Thread(target=live_handoff)
    handoff.start()
    time.sleep(0.5)
    assert durable_background_state(runtime.registry.load()) is None  # still draining
    release.set()
    holder.join(10)
    handoff.join(30)
    assert result["receipt"].handed_off is True

    # The replacement consumes explicit versioned binding state.
    versioned = resolve_background_worker_runtime(vault_root=Path(first.path))
    assert versioned is not None and versioned.background_worker
    state = durable_background_state(runtime.registry.load())
    assert state is not None and versioned.intent_revision == state.intent_revision
    assert versioned.background_context_digest == background_capability_digest(
        instance_identity=runtime.registry.load().app_install_id,
        intent_revision=state.intent_revision,
        binding_id=first.vault_binding_id,
        generation=versioned.background_lifecycle.generation,
    )
    assert versioned.background_lifecycle.context.workspace.state == "no_workspace"
    # Never a worker on another binding: the env/selected root must be durable intent.
    with pytest.raises(Exception, match="not the durable background binding"):
        resolve_background_worker_runtime(vault_root=Path(second.path))
    # Production tick: the env root (still the old one) does not choose the binding. A
    # compatibility rebind moves the worker without a restart.
    from app.workers.outbox_worker import _resolve_optional_vault_root

    assert _resolve_optional_vault_root(None) == Path(first.path).resolve()
    pick(runtime, second.vault_binding_id)
    assert _resolve_optional_vault_root(None) == Path(second.path).resolve()
    rebound = resolve_background_worker_runtime()
    assert rebound is not None and rebound.vault_binding_id == second.vault_binding_id
    with pytest.raises(Exception, match="revision changed before dispatch|truth changed before the effect"):
        validate_frozen_binding_runtime(versioned)
    versioned = rebound

    # A later intent revision invalidates the held worker before its next dispatch, and
    # empty durable intent idles the tick even with an env root configured.
    admin(runtime).remove(second.vault_binding_id)
    assert _resolve_optional_vault_root(None) is None
    from app.workers.outbox_worker import run_once

    assert run_once().state == "no_vault"
    with pytest.raises(Exception, match="revision changed before dispatch|truth changed before the effect"):
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


def test_background_consumer_preflight_starts_supervisor_from_durable_intent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.instance.runtime import _preflight_runtime

    runtime, first, _extra = mvr06b_instance(tmp_path, monkeypatch)
    for consumer in ("watcher", "worker"):
        assert (
            _preflight_runtime(
                channel=runtime.layout.channel_id,
                instance_state_root=runtime.layout.root.parent,
                host_global_root=runtime.ledger.root,
                consumer=consumer,
            )
            == 0
        )
    assert background_ids(runtime) == (first.vault_binding_id,)


def test_explicit_mode_keeps_foreground_compatibility_binding_on_foreground_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Carrier-free foreground effects follow foreground truth, not the background set."""
    from app.instance.compatibility_binding import live_compatibility_binding_id
    from app.instance.settings_rebind import SettingsRebindStore

    runtime, first, (second,) = mvr06b_instance(tmp_path, monkeypatch)
    stub_settings_reload(monkeypatch)
    # Explicit-empty background intent: the journal candidate is cleared ...
    admin(runtime).remove(first.vault_binding_id)
    assert runtime.open_settings_rebind_store().read().candidate_binding_id is None
    # ... but carrier-free foreground work still resolves the instance default.
    assert SettingsRebindStore(runtime.registry).compatibility_binding_id() == first.vault_binding_id
    assert live_compatibility_binding_id() == first.vault_binding_id
    # An ordinary foreground selection moves it; background intent stays empty.
    from app.instance.runtime import open_default_vault_service

    open_default_vault_service(runtime.layout.registry_path).set(second.vault_binding_id)
    assert live_compatibility_binding_id() == second.vault_binding_id
    assert background_ids(runtime) == ()


def test_handoff_refuses_to_persist_no_vault_when_registrations_are_unproven(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests._mvr03_principal_harness import provisioned_instance
    from tests._mvr06_background_harness import (
        record_mvr05_floor,
        run_background_cutover_through_cli,
    )
    from app.instance.settings_rebind import _install_dormant_settings_rebind

    runtime, first, _extra, _principal = provisioned_instance(
        tmp_path, extra_roots=("two",), set_instance_default=False
    )
    record_mvr05_floor(runtime)
    _install_dormant_settings_rebind(runtime.registry, _capability=STORAGE_MUTATION_CAPABILITY)
    assert run_background_cutover_through_cli(runtime)["_exit_code"] == 0
    bind_runtime_env(monkeypatch, runtime)

    refused = handoff_through_cli(runtime)
    assert refused["_exit_code"] == 1 and "cannot prove" in refused["error"]
    assert durable_background_state(runtime.registry.load()) is None
    # The operator names the running root and the handoff completes.
    assert handoff_through_cli(runtime, legacy_bootstrap_root=Path(first.path))["_exit_code"] == 0
    assert background_ids(runtime) == (first.vault_binding_id,)


def test_inventory_enrolled_single_vault_resolves_without_a_mount(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dataclasses import replace

    from app.instance.background_supervisor import _resolve_handoff_binding

    runtime, first, _extra = mvr06a_instance(tmp_path, extra_roots=())
    snapshot = runtime.registry.load()
    enrolled = replace(
        snapshot.registrations[first.vault_binding_id],
        extensions={"provenance": "authenticated_legacy_owner_inventory"},
    )
    unbound = replace(
        snapshot,
        registrations={first.vault_binding_id: enrolled},
        default_vault_binding_id=None,
        default_vault_provenance=None,
        settings_rebind=None,
    )
    assert _resolve_handoff_binding(unbound, None)[0] == first.vault_binding_id


def test_explicit_mode_precondition_follows_foreground_and_honors_the_seal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    from app.api import compatibility_mutation as mutation
    from app.instance.vault_registry import RegistryError

    runtime, first, (second,) = mvr06b_instance(tmp_path, monkeypatch)
    stub_settings_reload(monkeypatch)
    principal = SimpleNamespace(principal=SimpleNamespace(principal_id="operator"))
    monkeypatch.setattr(
        mutation,
        "build_selection_service",
        lambda store: SimpleNamespace(derive=lambda *a, **k: principal),
    )
    monkeypatch.setattr(mutation, "resolve_auth_subject", lambda request, api_key: "trusted_loopback")

    # Explicit background intent on another binding: the foreground token stays valid.
    admin(runtime).remove(first.vault_binding_id)
    admin(runtime).add(second.vault_binding_id)
    token = mutation.issue_compatibility_precondition(
        binding_id=first.vault_binding_id, principal_id="operator", registry=runtime.registry
    )
    proof = mutation._current_proof(token, request=None, api_key=None, registry=runtime.registry)
    assert proof.binding_id == first.vault_binding_id
    assert mutation._registered_root(runtime.registry, first.vault_binding_id) == Path(first.path)

    # A token issued before a seal is refused after it, on the proof and on the root.
    from app.instance.runtime import open_default_vault_service

    open_default_vault_service(runtime.layout.registry_path).set(second.vault_binding_id)
    admin(runtime).remove(second.vault_binding_id)
    token = mutation.issue_compatibility_precondition(
        binding_id=second.vault_binding_id, principal_id="operator", registry=runtime.registry
    )

    class Crash(BaseException):
        pass

    def crash(name: str) -> None:
        if name == "binding-removal:reserved":
            raise Crash(name)

    monkeypatch.setattr("app.instance.binding_removal._fault_point", crash)
    with pytest.raises(Crash):
        runtime.remove(second.vault_binding_id)
    with pytest.raises((mutation.CompatibilityMutationError, RegistryError)):
        mutation._current_proof(token, request=None, api_key=None, registry=runtime.registry)
    with pytest.raises(mutation.CompatibilityMutationError, match="sealed"):
        mutation._registered_root(runtime.registry, second.vault_binding_id)
