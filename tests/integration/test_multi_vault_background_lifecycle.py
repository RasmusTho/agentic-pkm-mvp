"""MVR-06 (#2143) background lifecycle authority.

`docs/MULTI_VAULT_RUNTIME/BIND_BACKGROUND_LIFECYCLES.md`. MVR-06A (#3863) owns only the
delegated background-runtime role producer and its startup preflight; later MVR-06 children
add their supervisor tests to this module.
"""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest
import yaml

from app.instance.background_authority import (
    BACKGROUND_RUNTIME_SCOPES,
    PROVENANCE_CHANNEL_BOOTSTRAP,
    PROVENANCE_EXISTING_INSTALL,
    PROVENANCE_NATIVE_BOOTSTRAP,
    PROVENANCE_REDELEGATION,
    BackgroundAuthorityFloorError,
    BackgroundAuthorityPreflightError,
    background_role_path,
)
from app.instance.runtime import (
    _preflight_runtime,
    open_background_role_store,
    open_local_operator_principal_store,
)
from tests._mvr06_background_harness import (
    cli,
    mvr06_instance,
    run_background_cutover_through_cli,
)
from tests._mvr_default_vault_harness import REPO_ROOT
from tests.helpers.instance_storage_capability import STORAGE_MUTATION_CAPABILITY


@pytest.fixture(autouse=True)
def _no_env_vault(monkeypatch):
    # The consumer preflight would otherwise bootstrap an ambient env binding.
    for name in ("VAULT_ROOT", "VAULT_ROOT_PROD", "WATCHER_VAULT_PATH"):
        monkeypatch.delenv(name, raising=False)


def _preflight(runtime, consumer: str) -> int:
    return _preflight_runtime(
        channel=runtime.layout.channel_id,
        instance_state_root=runtime.layout.root.parent,
        host_global_root=runtime.ledger.root,
        consumer=consumer,
    )


def _rewrite_role(runtime, **changes) -> None:
    path = background_role_path(runtime.layout.registry_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    for key, value in changes.items():
        if value is _DROP:
            payload.pop(key)
        else:
            payload[key] = value
    path.write_text(json.dumps(payload), encoding="utf-8")
    path.chmod(0o600)


_DROP = object()


def _assert_background_refused(runtime, match: str) -> None:
    for consumer in ("watcher", "worker"):
        with pytest.raises(BackgroundAuthorityPreflightError, match=match):
            _preflight(runtime, consumer)
    # The foreground API needs no background role and keeps its own preflight.
    assert _preflight(runtime, "api") == 0


def test_background_service_role_is_bootstrapped_delegated_and_least_privilege(
    tmp_path: Path,
) -> None:
    """One distinct least-privilege role, delegated from the operator, before startup."""

    # -- existing-install migration through the shipped cutover command -------------------
    runtime, _first, _extra, operator, receipt = mvr06_instance(tmp_path)
    role_store = open_background_role_store(runtime.layout.registry_path)
    role = role_store.require()

    assert receipt["role_created"] is True and receipt["floor_advanced"] is True
    assert role.background_runtime_role_id == receipt["background_runtime_role_id"]
    assert role.delegator_role_id == operator.local_operator_role_id
    assert role.delegation_provenance == PROVENANCE_EXISTING_INSTALL
    assert role.scopes == BACKGROUND_RUNTIME_SCOPES
    assert role.auth_epoch == 1 and role.status == "active"
    # Distinct: never the operator role, an added role, the install id, or a credential.
    snapshot = runtime.registry.load()
    assert role.background_runtime_role_id not in {
        operator.local_operator_role_id,
        snapshot.app_install_id,
    }
    # Private versioned GOV state beside the principal record; receipts carry no path.
    record_path = background_role_path(runtime.layout.registry_path)
    assert record_path.parent == runtime.layout.registry_path.parent
    assert stat.S_IMODE(record_path.stat().st_mode) == 0o600
    assert json.loads(record_path.read_text(encoding="utf-8"))["schema"] == (
        "agentic-pkm.background-runtime-role.v1"
    )
    assert str(tmp_path) not in json.dumps(receipt)

    # Before lifecycle startup the background consumers' preflight accepts the lineage.
    for consumer in ("api", "watcher", "worker"):
        assert _preflight(runtime, consumer) == 0
    # Production compose runs that preflight before every background process starts,
    # so a refused preflight means the worker/watcher never dispatches.
    compose = yaml.safe_load((REPO_ROOT / "docker-compose.yaml").read_text())
    for service in ("worker", "watcher"):
        command = compose["services"][service]["command"]
        text = command if isinstance(command, str) else " ".join(command)
        preflight_at = text.index("app.instance.runtime preflight")
        assert f"--consumer {service}" in text[preflight_at:]

    # A retried cutover reuses the same identity; it never mints a second role.
    retry = run_background_cutover_through_cli(runtime)
    assert retry["_exit_code"] == 0, retry
    assert retry["background_runtime_role_id"] == role.background_runtime_role_id
    assert retry["role_created"] is False and retry["floor_advanced"] is False
    assert retry["intent_installed"] is False

    # Independent of API-key rotation: the delegator's role id, not its credential
    # revision, is pinned.
    principal_store = open_local_operator_principal_store(runtime.layout.registry_path)
    principal_store.rotate_credential(
        credential="rotated-operator-key", _capability=STORAGE_MUTATION_CAPABILITY
    )
    assert _preflight(runtime, "worker") == 0
    assert role_store.require() == role

    # No role or delegation can be written without the floor.
    with pytest.raises(BackgroundAuthorityFloorError):
        role_store.bootstrap(
            delegator=principal_store.require(),
            delegation_provenance=PROVENANCE_EXISTING_INSTALL,
            floor_guard=lambda: False,
            _capability=STORAGE_MUTATION_CAPABILITY,
        )

    # -- missing / stale / ambiguous / over-broad / partial delegation fails preflight ---
    pristine = record_path.read_bytes()

    record_path.unlink()
    _assert_background_refused(runtime, "no delegated background runtime role")
    record_path.write_bytes(pristine)
    record_path.chmod(0o600)

    _rewrite_role(runtime, delegator_role_id="lor_" + "0" * 32)
    _assert_background_refused(runtime, "stale")

    _rewrite_role(
        runtime,
        delegator_role_id=operator.local_operator_role_id,
        background_runtime_role_id=operator.local_operator_role_id,
    )
    _assert_background_refused(runtime, "ambiguous")

    _rewrite_role(
        runtime,
        background_runtime_role_id=role.background_runtime_role_id,
        scopes=sorted([*BACKGROUND_RUNTIME_SCOPES, "instance.admin"]),
    )
    _assert_background_refused(runtime, "over-broad")

    _rewrite_role(runtime, scopes=sorted([*BACKGROUND_RUNTIME_SCOPES, "vault.delete_all"]))
    _assert_background_refused(runtime, "exceeds its delegator")

    _rewrite_role(runtime, scopes=list(BACKGROUND_RUNTIME_SCOPES[:-1]))
    _assert_background_refused(runtime, "partial")

    _rewrite_role(runtime, scopes=list(BACKGROUND_RUNTIME_SCOPES), auth_epoch=_DROP)
    _assert_background_refused(runtime, "partial")

    record_path.write_bytes(pristine)
    record_path.chmod(0o644)
    _assert_background_refused(runtime, "mode is unsafe")
    record_path.chmod(0o600)
    assert _preflight(runtime, "worker") == 0

    # -- GOV revocation advances the auth epoch and blocks the next background start ----
    registry_path = str(runtime.layout.registry_path)
    revoked = cli("background-role-revoke", "--registry-path", registry_path)
    assert revoked["_exit_code"] == 0 and revoked["status"] == "revoked"
    assert revoked["auth_epoch"] == role.auth_epoch + 1
    _assert_background_refused(runtime, "revoked at auth epoch 2")
    redelegated = cli("background-role-redelegate", "--registry-path", registry_path)
    assert redelegated["_exit_code"] == 0, redelegated
    assert redelegated["auth_epoch"] == 3
    assert redelegated["background_runtime_role_id"] != role.background_runtime_role_id
    assert redelegated["delegation_provenance"] == PROVENANCE_REDELEGATION
    assert _preflight(runtime, "worker") == 0
    # An active, valid delegation is never silently replaced.
    assert cli("background-role-redelegate", "--registry-path", registry_path)[
        "_exit_code"
    ] == 1

    # -- channel and native bootstrap use the same producer with their own provenance ---
    for kind, provenance in (
        ("channel", PROVENANCE_CHANNEL_BOOTSTRAP),
        ("native", PROVENANCE_NATIVE_BOOTSTRAP),
    ):
        root = tmp_path / f"{kind}-bootstrap"
        root.mkdir()
        fresh, _, _, fresh_operator, fresh_receipt = mvr06_instance(
            root, bootstrap_kind=kind
        )
        fresh_role = open_background_role_store(fresh.layout.registry_path).require()
        assert fresh_receipt["delegation_provenance"] == provenance
        assert fresh_role.delegator_role_id == fresh_operator.local_operator_role_id
        assert fresh_role.background_runtime_role_id != role.background_runtime_role_id
        assert _preflight(fresh, "watcher") == 0

    # The cutover runs only inside the proved stopped window.
    revision_before = runtime.registry.load().revision
    role_before = record_path.read_bytes()
    outside = cli(
        "background-authority-cutover",
        "--channel",
        runtime.layout.channel_id,
        "--registry-path",
        registry_path,
        "--host-global-root",
        str(runtime.ledger.root),
        "--quiescence-proof-path",
        str(runtime.ledger.root / "deployment-quiescence-proof.json"),
        "--bootstrap-kind",
        "existing-install",
    )
    assert outside["_exit_code"] == 1
    assert runtime.registry.load().revision == revision_before
    assert record_path.read_bytes() == role_before


# -- MVR-06B (#3864): compatibility bridge handoff and the singleton supervisor ---------

from app.instance.background_supervisor import (  # noqa: E402
    BackgroundLifecycleError,
    durable_background_state,
)
from app.instance.vault_registry import CapabilityNotReadyError  # noqa: E402
from tests._mvr06b_handoff_harness import (  # noqa: E402
    admin,
    background_ids,
    bind_runtime_env,
    configure_watcher,
    drive_watcher_during_waits,
    handoff_through_cli,
    mvr06a_instance,
    mvr06b_instance,
    outbox_paths,
    pick,
    stub_settings_reload,
    supervisor,
    watcher_receipt,
)


def _watcher_owner(runtime) -> str:
    """Exactly one owner: the bridge before the handoff generation, the supervisor after."""

    return "supervisor" if durable_background_state(runtime.registry.load()) else "bridge"


def _watched_instance(tmp_path, monkeypatch, *, handoff: bool = True):
    from app.watcher import registry as watcher_registry

    runtime, first, (second,) = mvr06a_instance(tmp_path)
    bind_runtime_env(monkeypatch, runtime, watcher=True)
    config = configure_watcher(monkeypatch, tmp_path, runtime, Path(first.path))
    stub_settings_reload(monkeypatch)
    watcher_registry.run_registry_once(config)
    if handoff:
        assert handoff_through_cli(runtime)["_exit_code"] == 0
    return runtime, first, second, config


@pytest.mark.parametrize("fault", ["before_commit", "registry_write"])
def test_settings_spine_bridge_handoff_is_atomic(tmp_path, monkeypatch, fault) -> None:
    from app.watcher import registry as watcher_registry

    runtime, first, second, config = _watched_instance(tmp_path, monkeypatch, handoff=False)
    journal_before = runtime.registry.load().settings_rebind
    assert _watcher_owner(runtime) == "bridge"

    if fault == "registry_write":
        original = runtime.registry.__class__._write_locked

        def failing(self, snapshot):
            if "backgroundSupervisor" in snapshot.extensions:
                raise OSError("injected registry write failure")
            return original(self, snapshot)

        monkeypatch.setattr(runtime.registry.__class__, "_write_locked", failing)
    else:
        def fail(stage: str) -> None:
            if stage == fault:
                raise RuntimeError("injected handoff failure")

        monkeypatch.setattr("app.instance.background_supervisor._handoff_fault_point", fail)
    with pytest.raises(Exception):
        refused = handoff_through_cli(runtime)
        assert refused["_exit_code"] != 0
        raise RuntimeError("refused")
    monkeypatch.undo()
    bind_runtime_env(monkeypatch, runtime, watcher=True)
    config = configure_watcher(monkeypatch, tmp_path, runtime, Path(first.path))
    stub_settings_reload(monkeypatch)
    # The old bridge stays authoritative: one owner, journal untouched, supervisor sealed.
    assert _watcher_owner(runtime) == "bridge"
    assert runtime.registry.load().settings_rebind == journal_before
    with pytest.raises(CapabilityNotReadyError):
        supervisor(runtime).start()
    watcher_registry.run_registry_once(config)

    # The retried handoff imports the live bridge binding and seats the supervisor.
    receipt = handoff_through_cli(runtime)
    assert receipt["_exit_code"] == 0, receipt
    assert _watcher_owner(runtime) == "supervisor"
    assert background_ids(runtime) == (first.vault_binding_id,)
    lifecycle = supervisor(runtime).start()
    assert lifecycle.status == "running" and lifecycle.binding_id == first.vault_binding_id
    # Bridge retirement is idempotent and never re-imports.
    assert handoff_through_cli(runtime)["handed_off"] is False
    note = Path(first.path) / "after-handoff.md"
    note.write_text("still watched\n", encoding="utf-8")
    watcher_registry.run_registry_once(config)
    assert str(note) in outbox_paths(tmp_path)


def test_picker_rebinds_only_compatibility_mode_after_bridge_handoff(tmp_path, monkeypatch) -> None:
    runtime, first, second, config = _watched_instance(tmp_path, monkeypatch)
    sup = supervisor(runtime)
    assert sup.start().binding_id == first.vault_binding_id
    drive_watcher_during_waits(monkeypatch, config)

    record = pick(runtime, second.vault_binding_id)
    assert record.phase == "committed"
    receipt = watcher_receipt(tmp_path, record.desired_revision)
    assert receipt.stage == "completed"
    assert receipt.prior_binding_id == first.vault_binding_id
    assert receipt.candidate_binding_id == second.vault_binding_id
    assert background_ids(runtime) == (second.vault_binding_id,)
    rotated = sup.reconcile()
    assert rotated.binding_id == second.vault_binding_id and rotated.generation == 2

    # Generic scoped selection never changes background intent.
    from app.instance.default_vault import resolve_vault_selection

    before = durable_background_state(runtime.registry.load())
    resolve_vault_selection(runtime.registry.load(), request_override=first.vault_binding_id)
    assert durable_background_state(runtime.registry.load()) == before

    # After the explicit-mode transition every picker event leaves intent unchanged.
    admin(runtime).add(second.vault_binding_id)
    explicit = durable_background_state(runtime.registry.load())
    from app.instance.settings_rebind import SettingsRebindCandidatePolicyError

    with pytest.raises(SettingsRebindCandidatePolicyError):
        pick(runtime, first.vault_binding_id)
    from app.vault.manager import VaultManager

    context = VaultManager().validate_vault(Path(first.path))
    assert VaultManager()._settings_rebind_selection(context, Path(first.path)) is None
    assert durable_background_state(runtime.registry.load()) == explicit
    assert sup.reconcile().binding_id == second.vault_binding_id


@pytest.mark.parametrize(
    "stage", ["prepare", "acknowledge", "commit", "reload", "reload_complete"]
)
def test_post_handoff_picker_rebind_preserves_two_phase_failure_atomicity(
    tmp_path, monkeypatch, stage
) -> None:
    runtime, first, (second,) = mvr06b_instance(tmp_path, monkeypatch)
    stub_settings_reload(monkeypatch)
    sup = supervisor(runtime)
    sup.start()
    # Every wake-up hint is lost: only durable phase/revision truth may converge.
    from app.services import outbox as outbox_module

    monkeypatch.setattr(
        outbox_module, "write_outbox_event",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("hint lost")),
    )
    tripped = False

    def fail_once(point: str) -> None:
        nonlocal tripped
        if point == stage and not tripped:
            tripped = True
            raise RuntimeError(f"injected {point} fault")

    monkeypatch.setattr("app.instance.settings_rebind._activation_fault_point", fail_once)
    with pytest.raises(RuntimeError, match=f"injected {stage} fault"):
        pick(runtime, second.vault_binding_id)
    pre_commit = stage in {"prepare", "acknowledge"}
    if pre_commit:
        # Pre-commit recovery resumes the old binding; no candidate effect happened.
        assert background_ids(runtime) == (first.vault_binding_id,)
        assert runtime.open_settings_rebind_store().read().phase != "prepared"
        assert sup.reconcile().binding_id == first.vault_binding_id
        with sup.effect() as lifecycle:
            assert lifecycle.binding_id == first.vault_binding_id
    else:
        # Post-commit recovery rolls forward from the durable revision.
        assert background_ids(runtime) == (second.vault_binding_id,)
        assert sup.reconcile().binding_id == second.vault_binding_id
    pick(runtime, second.vault_binding_id)
    record = runtime.open_settings_rebind_store().read()
    assert record.candidate_binding_id == second.vault_binding_id
    assert record.reload_revision == record.desired_revision
    assert background_ids(runtime) == (second.vault_binding_id,)
    with sup.effect() as lifecycle:
        assert lifecycle.binding_id == second.vault_binding_id


def test_handoff_buffers_direct_filesystem_write_through_commit(tmp_path, monkeypatch) -> None:
    runtime, first, second, config = _watched_instance(tmp_path, monkeypatch)
    direct = Path(first.path) / "direct-between-scan-and-commit.md"

    def write_after_final_scan(record) -> None:
        # After the pre-commit reconciliation scan, before the compatibility commit;
        # no filesystem event hint is delivered (the watcher only polls).
        direct.write_text("old root remains authoritative\n", encoding="utf-8")

    drive_watcher_during_waits(monkeypatch, config, after_acknowledged=write_after_final_scan)
    candidate = Path(second.path) / "candidate-before-load.md"
    candidate.write_text("candidate\n", encoding="utf-8")
    record = pick(runtime, second.vault_binding_id)
    receipt = watcher_receipt(tmp_path, record.desired_revision)
    assert receipt.stage == "completed"
    assert receipt.prior_binding_id == first.vault_binding_id
    buffered = {item.relative_path for item in receipt.buffer}
    assert direct.name in buffered  # receipted under A
    assert candidate.name not in buffered
    assert str(direct) in outbox_paths(tmp_path)
    assert background_ids(runtime) == (second.vault_binding_id,)


def test_lifecycle_requires_matching_channel_ownership_lease(tmp_path, monkeypatch) -> None:
    import shutil

    from app.instance.background_supervisor import BackgroundLifecycleSupervisor

    runtime, first, (second,) = mvr06b_instance(tmp_path, monkeypatch)
    stub_settings_reload(monkeypatch)
    assert supervisor(runtime).start().status == "running"

    # A lifecycle in another release channel cannot self-claim this channel's lease.
    foreign = BackgroundLifecycleSupervisor.for_runtime(
        registry_path=runtime.layout.registry_path,
        ownership_root=runtime.ledger.root,
        channel_id="test" if runtime.layout.channel_id != "test" else "dev",
        consumer="watcher",
    )
    refused = foreign.start()
    assert refused.status == "failed" and "another release channel" in refused.failure

    # Relocation of the physical root (a different directory now at the path) is refused
    # at start, at rebind, and after restart.
    root = Path(first.path)
    moved = tmp_path / "moved-away"
    shutil.move(str(root), moved)
    root.mkdir()
    for attempt in (supervisor(runtime).start(), supervisor(runtime).reconcile()):
        assert attempt.status == "failed"
        assert "ownership lease" in attempt.failure
    from tests._mvr_default_vault_harness import reopen_runtime

    restarted = reopen_runtime(runtime, tmp_path)
    assert supervisor(restarted).start().status == "failed"
    shutil.rmtree(root)
    shutil.move(str(moved), root)
    assert supervisor(restarted).start().status == "running"

    # A binding whose lease is retired (removed) is never started.
    admin(restarted).remove(first.vault_binding_id)
    admin(restarted).add(second.vault_binding_id)
    restarted.remove(second.vault_binding_id)
    failed = supervisor(restarted).start()
    assert failed.status == "failed" and failed.binding_id == second.vault_binding_id


def test_default_mutation_rebinds_only_compatibility_lifecycle(tmp_path, monkeypatch) -> None:
    from app.instance.runtime import open_default_vault_service

    runtime, first, second, config = _watched_instance(tmp_path, monkeypatch)
    drive_watcher_during_waits(monkeypatch, config)
    defaults = open_default_vault_service(runtime.layout.registry_path)
    sup = supervisor(runtime)
    sup.start()

    # Replacing the default runs the full prepare/quiesce/commit/resume protocol.
    defaults.set(second.vault_binding_id)
    record = runtime.open_settings_rebind_store().read()
    assert record.phase == "committed" and record.candidate_binding_id == second.vault_binding_id
    assert watcher_receipt(tmp_path, record.desired_revision).stage == "completed"
    state = durable_background_state(runtime.registry.load())
    assert state.binding_ids == (second.vault_binding_id,)
    assert state.intent_provenance == "compatibility_default"
    assert sup.reconcile().binding_id == second.vault_binding_id

    # Clearing falls back to the registered legacy bootstrap before no-vault, so
    # foreground and background resolution stay identical.
    from app.instance.default_vault import resolve_vault_selection

    defaults.clear()
    snapshot = runtime.registry.load()
    foreground = resolve_vault_selection(snapshot, legacy_bootstrap_vault_root=Path(first.path))
    assert foreground.vault_binding_id == first.vault_binding_id
    assert background_ids(runtime) == (first.vault_binding_id,)
    monkeypatch.delenv("WATCHER_VAULT_PATH")
    monkeypatch.setenv("WATCHER_ENABLE", "0")
    defaults.set(second.vault_binding_id)
    defaults.clear()
    assert background_ids(runtime) == ()  # no bootstrap configured: truthful no-vault

    # Explicit intent is never rebound by a default mutation.
    admin(runtime).add(second.vault_binding_id)
    defaults.set(first.vault_binding_id)
    defaults.clear()
    assert background_ids(runtime) == (second.vault_binding_id,)


def test_rebind_reuses_settings_spine_and_is_generation_clean(tmp_path, monkeypatch) -> None:
    import threading

    runtime, first, (second,) = mvr06b_instance(tmp_path, monkeypatch)
    reloads = stub_settings_reload(monkeypatch)
    sup = supervisor(runtime)
    old = sup.start()
    held = threading.Event()
    release = threading.Event()
    finished: list[str] = []

    def in_flight() -> None:
        with sup.effect() as lifecycle:
            held.set()
            release.wait(10)
            finished.append(lifecycle.binding_id)

    worker = threading.Thread(target=in_flight)
    worker.start()
    assert held.wait(5)
    # The rebind goes through #3163's production two-phase journal and SETTINGS-01 reload.
    pick(runtime, second.vault_binding_id)
    assert reloads[-1] == Path(second.path)
    rotated: dict = {}
    rotation = threading.Thread(target=lambda: rotated.update(lifecycle=sup.reconcile()))
    rotation.start()
    rotation.join(0.5)
    assert rotation.is_alive()  # draining the old generation's in-flight effect
    release.set()
    worker.join(10)
    rotation.join(10)
    assert finished == [first.vault_binding_id]  # in-flight work completed on its binding
    new = rotated["lifecycle"]
    assert new.binding_id == second.vault_binding_id
    assert new.generation == old.generation + 1
    assert new.context.context_id != old.context.context_id
    assert new.context.selection_capability_digest != old.context.selection_capability_digest
    with sup.effect() as lifecycle:
        assert lifecycle.binding_id == second.vault_binding_id


def test_registry_revision_rebinds_and_closes_event_crash_window(tmp_path, monkeypatch) -> None:
    from dataclasses import replace as dc_replace

    from app.instance.background_supervisor import BackgroundLifecycleStale

    runtime, first, (second,) = mvr06b_instance(tmp_path, monkeypatch)
    stub_settings_reload(monkeypatch)
    sup = supervisor(runtime)
    gen1 = sup.start()

    # The producer crashes after the registry commit but before event publication.
    from app.services import outbox as outbox_module

    def crash(*args, **kwargs):
        raise SystemExit("producer crashed before event publication")

    monkeypatch.setattr(outbox_module, "write_outbox_event", crash)
    monkeypatch.setattr(
        "app.instance.background_supervisor.emit_background_intent_event",
        lambda *a, **k: None,
    )
    pick(runtime, second.vault_binding_id)
    # The held generation cannot accept later work against the stale binding.
    with pytest.raises(BackgroundLifecycleStale):
        sup.require_current(gen1)
    gen2 = sup.reconcile()  # converges from the durable revision cursor alone
    assert gen2.binding_id == second.vault_binding_id and gen2.generation == 2
    monkeypatch.setattr(outbox_module, "write_outbox_event", lambda *a, **k: "hint")

    # An authority-relevant provenance change rotates and re-authorizes.
    snapshot = runtime.registry.load()
    registration = snapshot.registrations[second.vault_binding_id]
    runtime.registry.commit_state(
        registrations={
            **snapshot.registrations,
            second.vault_binding_id: dc_replace(
                registration,
                extensions={**registration.extensions, "bindingRevision": snapshot.revision + 1},
            ),
        },
        expected_revision=snapshot.revision,
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    gen3 = sup.reconcile()
    assert gen3.generation == 3 and gen3.binding_revision == snapshot.revision + 1

    # Removing the running binding rotates it off the removed binding: compatibility
    # adopts the post-removal MVR-02 default, never the stale binding.
    runtime.remove(second.vault_binding_id)
    rebound = sup.reconcile()
    assert rebound.binding_id == first.vault_binding_id and rebound.generation == 4
    with sup.effect() as lifecycle:
        assert lifecycle.binding_id == first.vault_binding_id


def test_background_effect_fence_closes_authorization_race_window(tmp_path, monkeypatch) -> None:
    import threading

    from app.instance.background_supervisor import revoke_background_role_fenced
    from app.instance.runtime import open_background_role_store

    runtime, first, _extra = mvr06b_instance(tmp_path, monkeypatch)
    sup = supervisor(runtime)
    sup.start()
    role_store = open_background_role_store(runtime.layout.registry_path)
    epoch = role_store.require().auth_epoch
    held = threading.Event()
    release = threading.Event()
    observed: list[int] = []

    def authorized_effect() -> None:
        with sup.effect():
            held.set()
            release.wait(10)
            # Still inside the shared lease: the revocation has not landed yet.
            observed.append(role_store.require().auth_epoch)

    effect = threading.Thread(target=authorized_effect)
    effect.start()
    assert held.wait(5)
    revoked: dict = {}
    revoker = threading.Thread(
        target=lambda: revoked.update(
            record=revoke_background_role_fenced(
                registry=runtime.registry,
                role_store=role_store,
                ownership_root=runtime.ledger.root,
                channel_id=runtime.layout.channel_id,
                _capability=STORAGE_MUTATION_CAPABILITY,
            )
        )
    )
    revoker.start()
    revoker.join(0.5)
    assert revoker.is_alive()  # the exclusive lease waits for the authorized effect
    release.set()
    effect.join(10)
    revoker.join(10)
    assert observed == [epoch]
    assert revoked["record"].auth_epoch == epoch + 1
    # After the revocation the next effect is blocked before any I/O.
    with pytest.raises(Exception):
        with sup.effect():
            raise AssertionError("an effect ran after revocation")
    assert sup.lifecycle.status == "failed"

    # The production CLI uses the same fenced order and refuses an unfenced revoke.
    from tests._mvr06_background_harness import cli

    unfenced = cli(
        "background-role-revoke", "--registry-path", str(runtime.layout.registry_path),
        "--consumer", "cli",
    )
    assert unfenced["_exit_code"] != 0 and "drain the affected lifecycles" in unfenced["error"]


# -- MVR-06B production removal / reactivation -------------------------------------------


class _ProcessCrash(BaseException):
    """A simulated process death: no in-process compensation may run."""


def _shared_refused(runtime, binding_id: str, root: Path) -> bool:
    from app.instance.binding_effect_lease import (
        BindingEffectLeaseError,
        BindingEffectLeaseManager,
    )

    leases = BindingEffectLeaseManager.for_runtime(
        registry_store=runtime.registry,
        ownership_root=runtime.ledger.root,
        state_root=runtime.layout.root / "binding-effect-leases",
    )
    try:
        with leases.shared_effect(
            binding_id, channel_id=runtime.layout.channel_id, root=root, timeout=0.5
        ):
            return False
    except BindingEffectLeaseError:
        return True


def test_registration_removal_activates_after_all_consumer_floors(tmp_path, monkeypatch) -> None:
    import threading

    from app.instance.binding_effect_lease import BindingEffectLeaseManager

    # Before the MVR-06B background floor, production removal stays sealed.
    staged, staged_first, _ = mvr06a_instance(tmp_path / "staged")
    before = staged.registry.load()
    with pytest.raises(CapabilityNotReadyError, match="MVR-06B consumer drain floor"):
        staged.remove(staged_first.vault_binding_id)
    assert staged.registry.load() == before

    runtime, first, (second,) = mvr06b_instance(tmp_path / "live", monkeypatch)
    stub_settings_reload(monkeypatch)
    leases = BindingEffectLeaseManager.for_runtime(
        registry_store=runtime.registry,
        ownership_root=runtime.ledger.root,
        state_root=runtime.layout.root / "binding-effect-leases",
    )
    holding = threading.Event()
    release = threading.Event()

    def foreground_effect() -> None:
        with leases.shared_effect(
            second.vault_binding_id, channel_id=runtime.layout.channel_id, root=Path(second.path)
        ):
            holding.set()
            release.wait(10)

    holder = threading.Thread(target=foreground_effect)
    holder.start()
    assert holding.wait(5)
    result: dict = {}
    remover = threading.Thread(
        target=lambda: result.update(tombstone=runtime.remove(second.vault_binding_id))
    )
    remover.start()
    remover.join(1.0)
    assert remover.is_alive()  # draining the holder
    reserved = runtime.registry.load().registrations[second.vault_binding_id]
    assert reserved.extensions["lifecycleState"] == "draining_removal"
    assert _shared_refused(runtime, second.vault_binding_id, Path(second.path))
    release.set()
    holder.join(10)
    remover.join(30)
    tombstone = result["tombstone"]
    snapshot = runtime.registry.load()
    assert second.vault_binding_id not in snapshot.registrations
    assert snapshot.removal_tombstones[second.vault_binding_id] == tombstone
    assert runtime.ledger.active_owner(second.vault_binding_id) is None
    assert second.vault_binding_id in runtime.ledger.load().tombstones
    assert background_ids(runtime) == (first.vault_binding_id,)


@pytest.mark.parametrize(
    "engine,phase",
    [("removal", phase) for phase in (
        "intent", "reserved", "prepared", "drained", "final_scanned", "committed",
        "buffer_drained", "ownership_released", "resumed",
    )]
    + [("reactivation", phase) for phase in (
        "intent", "ownership_reactivated", "registered_reactivating", "derived_invalidated",
        "rescanned", "rebuild_receipted", "healthy", "rebound",
    )],
)
def test_production_removal_and_reactivation_recover_after_every_durable_phase(
    tmp_path, monkeypatch, engine, phase
) -> None:
    from app.instance.binding_removal import binding_epoch_lineage
    from tests._mvr_default_vault_harness import reopen_runtime

    from app.instance.runtime import open_default_vault_service

    runtime, first, (second,) = mvr06b_instance(tmp_path, monkeypatch)
    stub_settings_reload(monkeypatch)
    # The removed binding is the compatibility binding and the instance default (the
    # first binding is the MVR-01C rollback target, which removal refuses up front).
    open_default_vault_service(runtime.layout.registry_path).set(second.vault_binding_id)
    binding, root = second.vault_binding_id, Path(second.path)
    assert background_ids(runtime) == (binding,)
    point = f"binding-{engine}:{phase}"

    def crash(name: str) -> None:
        if name == point:
            raise _ProcessCrash(name)

    if engine == "reactivation":
        runtime.remove(binding)
    monkeypatch.setattr("app.instance.binding_removal._fault_point", crash)
    with pytest.raises(_ProcessCrash):
        if engine == "removal":
            runtime.remove(binding)
        else:
            runtime.reactivate_removed(root)
    monkeypatch.setattr("app.instance.binding_removal._fault_point", lambda name: None)

    snapshot = runtime.registry.load()
    registration = snapshot.registrations.get(binding)
    lease = runtime.ledger.load().leases.get(binding)
    # No early access and no dual ownership at any crash point, on every write route:
    # effect-leased holders and the carrier-free compatibility ingress alike.
    if registration is not None and registration.extensions.get("lifecycleState"):
        assert _shared_refused(runtime, binding, root)
        from app.instance.settings_rebind import RegistryError, SettingsRebindStore

        try:
            admitted = SettingsRebindStore(runtime.registry).compatibility_binding_id()
        except RegistryError:
            admitted = None
        assert admitted != binding
    if registration is None:
        assert binding in snapshot.removal_tombstones
    assert not (registration is not None and binding in snapshot.removal_tombstones)
    if lease is not None:
        assert lease.channel_id == runtime.layout.channel_id

    restarted = reopen_runtime(runtime, tmp_path)
    if engine == "removal":
        tombstone = restarted.recover_removal()
        final = restarted.registry.load()
        assert tombstone is not None and tombstone == final.removal_tombstones[binding]
        assert binding not in final.registrations
        assert restarted.ledger.active_owner(binding) is None
        assert final.default_vault_binding_id is None
        assert background_ids(restarted) == ()  # enabled idle/no-vault, not a stale binding
        events = [item["event"] for item in binding_epoch_lineage(final, binding)]
        assert events == ["removed"]
        assert _shared_refused(restarted, binding, root)
    else:
        reactivated = restarted.recover_reactivation()
        final = restarted.registry.load()
        assert reactivated is not None
        assert reactivated.extensions["contentEpoch"] == 2
        assert "lifecycleState" not in reactivated.extensions
        assert binding not in final.removal_tombstones
        assert restarted.ledger.active_owner(binding).channel_id == restarted.layout.channel_id
        lineage = binding_epoch_lineage(final, binding)
        assert [item["event"] for item in lineage] == ["removed", "reactivated"]
        assert lineage[1]["predecessorEpoch"] == 1 and lineage[1]["contentEpoch"] == 2
        assert not _shared_refused(restarted, binding, root)
        # Reactivation never re-enrols the binding in background intent.
        assert background_ids(restarted) == ()


def test_tombstone_reactivation_rebuilds_all_derived_state_before_healthy(
    tmp_path, monkeypatch
) -> None:
    import json
    import re

    from app.instance import binding_removal

    # The invalidation inventory classifies every MVR-05 binding-keyed table.
    migrated: set[str] = set()
    versions = REPO_ROOT / "app" / "alembic" / "versions"
    for path in versions.glob("*mvr05a*.py"):
        text = path.read_text(encoding="utf-8")
        migrated.update(
            name
            for name in re.findall(r"(?:ALTER TABLE|UPDATE)\s+(?:public\.)?([a-z_]+)", text)
        )
    classified = set(binding_removal.PG_BINDING_KEYED_DERIVED_TABLES) | set(
        binding_removal.PG_BINDING_KEYED_RETAINED_TABLES
    )
    # Dynamic-SQL tokens (``ALTER TABLE public.%I``, loop aliases) are not tables.
    migrated -= {"public", "so", "action"}
    assert migrated, "no MVR-05 binding-keyed tables were discovered"
    assert migrated <= classified, migrated - classified
    assert not set(binding_removal.PG_BINDING_KEYED_DERIVED_TABLES) & set(
        binding_removal.PG_BINDING_KEYED_RETAINED_TABLES
    )

    runtime, first, (second,) = mvr06b_instance(tmp_path, monkeypatch)
    stub_settings_reload(monkeypatch)
    binding, root = second.vault_binding_id, Path(second.path)
    (root / "note-to-rebuild.md").write_text("derived state source\n", encoding="utf-8")
    runtime.remove(binding)
    retired = runtime.registry.load().removal_tombstones[binding]
    assert retired.content_epoch == 1

    # The rebuild is real production work: every admitted note is re-emitted as a
    # binding-stamped, reactivation-keyed ingest row, settled by worker dispatch while
    # ordinary holders stay sealed.
    from app.services import outbox as outbox_module

    rebuilt: list[tuple[str, str, str]] = []
    sealed_during_rebuild: list[bool] = []
    real_drain = None
    from app.workers import outbox_worker

    real_drain = outbox_worker.drain_binding_outbox

    def capture(event, conn=None, *, idempotency_key, vault_binding_id=None, required_db=False, producer=None):
        rebuilt.append((vault_binding_id, event.payload["relative_path"], producer))
        return idempotency_key

    def drain(*, vault_root, binding_id, include_compatibility=False):
        import threading as _threading

        # A different context (no admission) is still refused while this one rebuilds.
        outcome: list[bool] = []
        probe = _threading.Thread(
            target=lambda: outcome.append(_shared_refused(runtime, binding, root))
        )
        probe.start()
        probe.join(10)
        sealed_during_rebuild.extend(outcome)
        return real_drain(
            vault_root=vault_root,
            binding_id=binding_id,
            include_compatibility=include_compatibility,
        )

    monkeypatch.setattr(outbox_module, "write_outbox_event", capture)
    monkeypatch.setattr(outbox_worker, "drain_binding_outbox", drain)

    calls: list[str] = []
    families = list(binding_removal.DERIVED_PROJECTION_FAMILIES)

    def failing(binding_id: str, path: Path) -> dict:
        calls.append(binding_id)
        raise RuntimeError("derived projection invalidation failed")

    monkeypatch.setattr(
        binding_removal,
        "DERIVED_PROJECTION_FAMILIES",
        tuple(families[:1] + [("context_caches", failing)]),
    )
    with pytest.raises(RuntimeError, match="invalidation failed"):
        runtime.reactivate_removed(root)
    sealed = runtime.registry.load().registrations[binding]
    assert sealed.extensions["lifecycleState"] == "reactivating"
    assert sealed.extensions["contentEpoch"] == 2
    assert _shared_refused(runtime, binding, root)  # no healthy read/effect yet
    admin(runtime).remove(first.vault_binding_id)
    with pytest.raises(BackgroundLifecycleError, match="sealed by its lifecycle"):
        admin(runtime).add(binding)  # no background enrollment before the rebuild

    monkeypatch.setattr(binding_removal, "DERIVED_PROJECTION_FAMILIES", tuple(families))
    healthy = runtime.recover_reactivation()
    assert healthy is not None and "lifecycleState" not in healthy.extensions
    receipt_path = runtime.layout.root / "rebuild-receipts" / f"{binding}-e2.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["retired_epoch"] == 1 and receipt["content_epoch"] == 2
    assert receipt["invalidated_families"] == sorted(name for name, _ in families)
    assert receipt["rescan"]["files"] >= 1
    assert (binding, "note-to-rebuild.md", "shared.instance.binding_reactivation") in rebuilt
    assert sealed_during_rebuild == [True]
    assert healthy.extensions["rebuildReceiptSha256"]
    assert not _shared_refused(runtime, binding, root)
    admin(runtime).add(binding)
    assert supervisor(runtime).start().status == "running"


def test_removed_binding_rehome_preserves_historical_receipt_audit(tmp_path, monkeypatch) -> None:
    from app.instance.binding_removal import binding_epoch_lineage

    runtime, first, (second,) = mvr06b_instance(tmp_path, monkeypatch)
    stub_settings_reload(monkeypatch)
    binding, root = second.vault_binding_id, Path(second.path)
    tombstone = runtime.remove(binding)
    removal = binding_epoch_lineage(runtime.registry.load(), binding)
    assert removal == [
        {
            "bindingId": binding,
            "event": "removed",
            "contentEpoch": 1,
            "removalId": removal[0]["removalId"],
            "registryRevision": removal[0]["registryRevision"],
        }
    ]
    # Ordinary registration cannot silently mint a new binding around the tombstone.
    with pytest.raises(Exception):
        runtime.production_register(root, producer="api")
    assert binding in runtime.registry.load().removal_tombstones

    reactivated = runtime.reactivate_removed(root)
    assert reactivated.vault_binding_id == binding
    assert reactivated.local_instance_id == tombstone.local_instance_id
    lineage = binding_epoch_lineage(runtime.registry.load(), binding)
    # Historical receipts stamped under epoch 1 stay attributable to the same binding's
    # retired epoch; rebuilt rows use epoch 2 and cannot alias them.
    assert [(item["event"], item["contentEpoch"]) for item in lineage] == [
        ("removed", 1),
        ("reactivated", 2),
    ]
    assert lineage[1]["predecessorEpoch"] == 1
    assert lineage[1]["reactivationId"] != lineage[0]["removalId"]
    # A second removal/reactivation cycle extends, never rewrites, the lineage.
    runtime.remove(binding)
    runtime.reactivate_removed(root)
    epochs = [item["contentEpoch"] for item in binding_epoch_lineage(runtime.registry.load(), binding)]
    assert epochs == [1, 2, 2, 3]


def _watched_default_on_second(tmp_path, monkeypatch):
    """Watched compatibility binding == instance default == the removable binding."""

    from app.instance.runtime import open_default_vault_service

    runtime, first, second, config = _watched_instance(tmp_path, monkeypatch)
    drive_watcher_during_waits(monkeypatch, config)
    open_default_vault_service(runtime.layout.registry_path).set(second.vault_binding_id)
    assert background_ids(runtime) == (second.vault_binding_id,)
    return runtime, first, second, config


def test_default_changing_removal_atomically_rebinds_compatibility_lifecycle(
    tmp_path, monkeypatch
) -> None:
    from app.instance import settings_rebind

    runtime, first, second, config = _watched_default_on_second(tmp_path / "ok", monkeypatch)
    sup = supervisor(runtime)
    sup.start()
    observed: list[tuple] = []

    def observe(name: str) -> None:
        snapshot = runtime.registry.load()
        state = durable_background_state(snapshot)
        observed.append((name, snapshot.default_vault_binding_id, state.binding_ids))

    monkeypatch.setattr("app.instance.binding_removal._fault_point", observe)
    tombstone = runtime.remove(
        second.vault_binding_id, replacement_default_binding_id=first.vault_binding_id
    )
    assert tombstone.vault_binding_id == second.vault_binding_id
    # The foreground default and the background binding move in the same generation:
    # never a new default beside an idle or stale background binding.
    for name, default, background in observed:
        assert (default, background) in {
            (second.vault_binding_id, (second.vault_binding_id,)),
            (first.vault_binding_id, (first.vault_binding_id,)),
        }, name
    record = runtime.open_settings_rebind_store().read()
    assert record.candidate_binding_id == first.vault_binding_id
    assert record.reload_revision == record.desired_revision  # replacement resumed
    assert watcher_receipt(tmp_path / "ok", record.desired_revision).stage == "completed"
    assert sup.reconcile().binding_id == first.vault_binding_id

    # Without a replacement the enabled watcher persists idle/no-vault.
    monkeypatch.undo()
    runtime2, first2, second2, _config = _watched_default_on_second(tmp_path / "idle", monkeypatch)
    runtime2.remove(second2.vault_binding_id)
    snapshot = runtime2.registry.load()
    assert snapshot.default_vault_binding_id is None
    assert background_ids(runtime2) == ()
    assert supervisor(runtime2).start().status == "idle"

    # A typed refusal before the commit (the watcher never acknowledges) leaves the
    # source registration, default, and compatibility lifecycle authoritative.
    monkeypatch.undo()
    runtime3, first3, second3, _config = _watched_default_on_second(
        tmp_path / "refused", monkeypatch
    )
    before = runtime3.registry.load()
    monkeypatch.setattr(
        settings_rebind.SettingsRebindActivation,
        "_wait_for_stage",
        lambda self, record, *, required_stage: (_ for _ in ()).throw(
            settings_rebind.RegistryError("watcher did not acknowledge")
        ),
    )
    with pytest.raises(settings_rebind.RegistryError, match="did not acknowledge"):
        runtime3.remove(second3.vault_binding_id)
    after = runtime3.registry.load()
    assert after.registrations[second3.vault_binding_id] == before.registrations[
        second3.vault_binding_id
    ]
    assert after.default_vault_binding_id == second3.vault_binding_id
    assert background_ids(runtime3) == (second3.vault_binding_id,)
    assert runtime3.open_settings_rebind_store().read().phase != "prepared"
    assert runtime3.ledger.active_owner(second3.vault_binding_id) is not None


def test_direct_filesystem_write_during_removal_is_receipted_before_tombstone(
    tmp_path, monkeypatch
) -> None:
    from app.instance.settings_rebind import SettingsRebindActivation
    from app.watcher import registry as watcher_registry

    runtime, first, second, config = _watched_default_on_second(tmp_path, monkeypatch)
    # Re-arm the watcher on the binding being removed (its live compatibility root).
    monkeypatch.setenv("WATCHER_VAULT_PATH", second.path)
    watcher_registry.run_registry_once(config)
    direct = Path(second.path) / "direct-during-removal.md"
    original = SettingsRebindActivation._wait_for_stage

    def wait(activation, record, *, required_stage):
        for _ in range(3):
            watcher_registry.run_registry_once(config)
        original(activation, record, required_stage=required_stage)
        if required_stage == "acknowledged":
            # Racing the drain: after the final pre-commit scan, before the commit.
            direct.write_text("racing direct write\n", encoding="utf-8")

    monkeypatch.setattr(SettingsRebindActivation, "_wait_for_stage", wait)
    order: list[str] = []

    def phase(name: str) -> None:
        order.append(name)
        if name == "binding-removal:buffer_drained":
            # The post-commit old-root drain is receipted under the removed binding
            # while its ownership lease is still held (before the tombstone release).
            record = runtime.open_settings_rebind_store().read()
            receipt = watcher_receipt(tmp_path, record.desired_revision)
            assert receipt.stage == "completed"
            assert receipt.prior_binding_id == second.vault_binding_id
            assert direct.name in {item.relative_path for item in receipt.buffer}
            assert runtime.ledger.active_owner(second.vault_binding_id) is not None

    from app.instance.scalar_binding_runtime import resolve_scalar_binding_runtime

    stamped: dict[str, str] = {}
    real_emit = watcher_registry._emit_watch_event

    def emit(*args, **kwargs):
        stamped[str(args[2] if len(args) > 2 else kwargs.get("rel_path"))] = (
            resolve_scalar_binding_runtime().vault_binding_id
        )
        return real_emit(*args, **kwargs)

    monkeypatch.setattr(watcher_registry, "_emit_watch_event", emit)
    monkeypatch.setattr("app.instance.binding_removal._fault_point", phase)
    runtime.remove(second.vault_binding_id, replacement_default_binding_id=first.vault_binding_id)
    assert order.index("binding-removal:buffer_drained") < order.index(
        "binding-removal:ownership_released"
    )
    # The racing write landed after the tombstone commit's final scan window and is still
    # stamped under the removed binding, although its registration is gone by then.
    assert stamped, "the post-commit drain emitted nothing"
    assert set(stamped.values()) == {second.vault_binding_id}
    assert str(direct) in outbox_paths(tmp_path)
    assert runtime.ledger.active_owner(second.vault_binding_id) is None


def test_removal_commit_refusal_without_watcher_restores_the_source(tmp_path, monkeypatch) -> None:
    from app.instance.runtime import open_default_vault_service
    from app.instance.vault_registry import RegistryRevisionConflict

    runtime, first, (second,) = mvr06b_instance(tmp_path, monkeypatch)
    stub_settings_reload(monkeypatch)
    open_default_vault_service(runtime.layout.registry_path).set(second.vault_binding_id)
    before = runtime.registry.load()

    def race(self, **kwargs):
        raise RegistryRevisionConflict("injected revision race at the removal commit")

    monkeypatch.setattr(type(runtime.registry), "commit_background_transition", race)
    with pytest.raises(RegistryRevisionConflict):
        runtime.remove(second.vault_binding_id)
    monkeypatch.undo()
    bind_runtime_env(monkeypatch, runtime)
    stub_settings_reload(monkeypatch)
    after = runtime.registry.load()
    assert after.registrations[second.vault_binding_id] == before.registrations[second.vault_binding_id]
    assert after.default_vault_binding_id == second.vault_binding_id
    assert background_ids(runtime) == (second.vault_binding_id,)
    record = runtime.open_settings_rebind_store().read()
    assert record.candidate_binding_id == second.vault_binding_id
    assert runtime.ledger.active_owner(second.vault_binding_id) is not None
    assert not _shared_refused(runtime, second.vault_binding_id, Path(second.path))
    # A retry from that restored state completes.
    runtime.remove(second.vault_binding_id)
    assert second.vault_binding_id in runtime.registry.load().removal_tombstones


def test_sealed_binding_cannot_become_a_rebind_candidate(tmp_path, monkeypatch) -> None:
    from app.instance.settings_rebind import SettingsRebindCandidatePolicyError

    runtime, first, (second,) = mvr06b_instance(tmp_path, monkeypatch)
    stub_settings_reload(monkeypatch)
    runtime.remove(second.vault_binding_id)

    class Crash(BaseException):
        pass

    def crash(name: str) -> None:
        if name == "binding-reactivation:registered_reactivating":
            raise Crash(name)

    monkeypatch.setattr("app.instance.binding_removal._fault_point", crash)
    with pytest.raises(Crash):
        runtime.reactivate_removed(Path(second.path))
    with pytest.raises(SettingsRebindCandidatePolicyError):
        pick(runtime, second.vault_binding_id)
    assert background_ids(runtime) == (first.vault_binding_id,)


def test_production_worker_and_watcher_are_blocked_by_gov_revocation(tmp_path, monkeypatch) -> None:
    """The fence is the production path: worker dispatch and the watcher cycle both honor it."""
    from app.instance.runtime import open_background_role_store
    from app.instance.scalar_binding_runtime import (
        resolve_background_worker_runtime,
        validate_frozen_binding_runtime,
    )
    from app.watcher import registry as watcher_registry

    runtime, first, second, config = _watched_instance(tmp_path, monkeypatch)
    watcher_registry.run_registry_once(config)
    worker = resolve_background_worker_runtime()
    assert worker is not None and worker.background_worker
    validate_frozen_binding_runtime(worker)
    before_note = Path(first.path) / "before-revocation.md"
    before_note.write_text("before\n", encoding="utf-8")
    watcher_registry.run_registry_once(config)
    assert str(before_note) in outbox_paths(tmp_path)

    open_background_role_store(runtime.layout.registry_path).revoke(
        _capability=STORAGE_MUTATION_CAPABILITY
    )
    with pytest.raises(Exception):
        validate_frozen_binding_runtime(worker)
    with pytest.raises(Exception, match="background lifecycle is failed"):
        resolve_background_worker_runtime()
    after_note = Path(first.path) / "after-revocation.md"
    after_note.write_text("after\n", encoding="utf-8")
    watcher_registry.run_registry_once(config)
    assert str(after_note) not in outbox_paths(tmp_path)  # no vault effect this cycle


def test_binding_lifecycle_cli_removes_recovers_and_reactivates(tmp_path, monkeypatch) -> None:
    from tests._mvr06_background_harness import cli

    runtime, first, (second,) = mvr06b_instance(tmp_path, monkeypatch)
    stub_settings_reload(monkeypatch)
    common = (
        "--registry-path", str(runtime.layout.registry_path),
        "--channel", runtime.layout.channel_id,
        "--host-global-root", str(runtime.ledger.root),
        "--consumer", "cli",
        "--watcher-posture", "absent",
    )
    # A stated running watcher needs its state dir; the posture is never inherited or guessed.
    no_state_dir = cli(
        "binding-remove", *common[:-1], "running", "--vault-binding-id", second.vault_binding_id
    )
    assert no_state_dir["_exit_code"] != 0 and "watcher-state-dir" in no_state_dir["error"]
    assert second.vault_binding_id in runtime.registry.load().registrations
    removed = cli("binding-remove", *common, "--vault-binding-id", second.vault_binding_id)
    assert removed["_exit_code"] == 0, removed
    assert removed["state"] == "removed" and second.path not in str(removed)
    recovered = cli("binding-lifecycle-recover", *common)
    assert recovered["_exit_code"] == 0 and recovered["recovered_removal"] is None
    reactivated = cli("binding-reactivate", *common, "--root", second.path)
    assert reactivated["_exit_code"] == 0, reactivated
    assert reactivated["content_epoch"] == 2 and second.path not in str(reactivated)


def test_removal_recovery_after_prepare_crash_compensates_to_the_true_prior_revision(
    tmp_path, monkeypatch
) -> None:
    from app.instance import binding_removal
    from app.instance.binding_effect_lease import BindingEffectLeaseTimeout
    from app.instance.runtime import open_default_vault_service
    from tests._mvr_default_vault_harness import reopen_runtime

    runtime, first, (second,) = mvr06b_instance(tmp_path, monkeypatch)
    stub_settings_reload(monkeypatch)
    open_default_vault_service(runtime.layout.registry_path).set(second.vault_binding_id)
    binding = second.vault_binding_id

    # Crash after the journal prepare but before its phase is saved.
    original_save = binding_removal._Journal.save

    def crash_on_prepared(self, intent, phase):
        if phase == "prepared":
            raise _ProcessCrash(phase)
        original_save(self, intent, phase)

    monkeypatch.setattr(binding_removal._Journal, "save", crash_on_prepared)
    with pytest.raises(_ProcessCrash):
        runtime.remove(binding)
    monkeypatch.setattr(binding_removal._Journal, "save", original_save)

    # Recovery then meets a typed drain refusal: the source must be fully restored.
    def refuse(self, source):
        raise BindingEffectLeaseTimeout("injected drain refusal")

    monkeypatch.setattr(binding_removal.BindingRemovalCoordinator, "_drain", refuse)
    restarted = reopen_runtime(runtime, tmp_path)
    with pytest.raises(BindingEffectLeaseTimeout):
        restarted.recover_removal()
    assert background_ids(restarted) == (binding,)
    record = restarted.open_settings_rebind_store().read()
    assert record.candidate_binding_id == binding
    lifecycle = supervisor(restarted).start()
    assert lifecycle.status == "running" and lifecycle.binding_id == binding


def test_failure_after_durable_tombstone_rolls_forward_and_never_compensates(
    tmp_path, monkeypatch
) -> None:
    from app.instance import binding_removal
    from app.instance.binding_effect_lease import (
        BindingEffectLeaseError,
        BindingEffectLeaseManager,
    )
    from app.instance.runtime import open_default_vault_service

    runtime, first, (second,) = mvr06b_instance(tmp_path, monkeypatch)
    stub_settings_reload(monkeypatch)
    open_default_vault_service(runtime.layout.registry_path).set(second.vault_binding_id)
    binding = second.vault_binding_id

    def refuse(self, binding_id):
        raise BindingEffectLeaseError("injected retirement refusal")

    monkeypatch.setattr(BindingEffectLeaseManager, "retire_binding_state", refuse)
    tombstone = runtime.remove(binding)
    assert tombstone.vault_binding_id == binding
    assert runtime.ledger.active_owner(binding) is None
    assert background_ids(runtime) == ()
    assert binding_removal.BindingRemovalCoordinator(runtime).recover() is None

    # A commit that became durable and then raised also rolls forward on recovery.
    monkeypatch.undo()
    bind_runtime_env(monkeypatch, runtime)
    stub_settings_reload(monkeypatch)
    runtime.reactivate_removed(Path(second.path))
    open_default_vault_service(runtime.layout.registry_path).set(binding)
    registry_cls = type(runtime.registry)
    original = registry_cls.commit_background_transition

    def commit_then_raise(self, **kwargs):
        original(self, **kwargs)
        from app.instance.settings_rebind import RegistryError

        raise RegistryError("injected failure after the durable commit")

    monkeypatch.setattr(registry_cls, "commit_background_transition", commit_then_raise)
    with pytest.raises(Exception, match="after the durable commit"):
        runtime.remove(binding)
    monkeypatch.setattr(registry_cls, "commit_background_transition", original)
    assert binding in runtime.registry.load().removal_tombstones
    assert runtime.recover_removal() is not None
    assert runtime.ledger.active_owner(binding) is None


def test_reactivation_refused_during_incomplete_removal(tmp_path, monkeypatch) -> None:
    from app.instance.settings_rebind import RegistryError

    runtime, first, (second,) = mvr06b_instance(tmp_path, monkeypatch)
    stub_settings_reload(monkeypatch)

    def crash(name: str) -> None:
        if name == "binding-removal:committed":
            raise _ProcessCrash(name)

    monkeypatch.setattr("app.instance.binding_removal._fault_point", crash)
    with pytest.raises(_ProcessCrash):
        runtime.remove(second.vault_binding_id)
    monkeypatch.setattr("app.instance.binding_removal._fault_point", lambda name: None)
    with pytest.raises(RegistryError, match="requires recovery first"):
        runtime.reactivate_removed(Path(second.path))
    assert runtime.recover_removal() is not None
    assert runtime.reactivate_removed(Path(second.path)).extensions["contentEpoch"] == 2


def test_unreachable_configured_database_leaves_reactivation_sealed(tmp_path, monkeypatch) -> None:
    from app.instance.binding_removal import BindingReactivationCoordinator

    runtime, first, (second,) = mvr06b_instance(tmp_path, monkeypatch)
    stub_settings_reload(monkeypatch)
    binding, root = second.vault_binding_id, Path(second.path)
    runtime.remove(binding)
    monkeypatch.setenv("DATABASE_URL", "postgresql://nobody@127.0.0.1:1/unreachable")
    with pytest.raises(Exception):
        runtime.reactivate_removed(root)
    registration = runtime.registry.load().registrations[binding]
    assert registration.extensions["lifecycleState"] == "reactivating"
    assert BindingReactivationCoordinator(runtime).journal.load()["phase"] == "registered_reactivating"
    assert _shared_refused(runtime, binding, root)


def test_empty_intent_to_a_different_binding_runs_under_an_enabled_watcher(
    tmp_path, monkeypatch
) -> None:
    """Production posture (WATCHER_ENABLE=1): no re-arm refusal against the boot env root."""
    from app.instance.runtime import open_default_vault_service
    from app.watcher import registry as watcher_registry

    runtime, first, second, config = _watched_instance(tmp_path, monkeypatch)
    drive_watcher_during_waits(monkeypatch, config)
    assert admin(runtime).remove(first.vault_binding_id)["explicit_empty"] is True
    watcher_registry.run_registry_once(config)
    silent = Path(first.path) / "while-explicit-empty.md"
    silent.write_text("nobody watches this\n", encoding="utf-8")
    watcher_registry.run_registry_once(config)
    assert str(silent) not in outbox_paths(tmp_path)

    # A governed add of a binding that is not the boot env root takes effect and survives
    # a process restart (fresh config) without moving foreground selection.
    added = admin(runtime).add(second.vault_binding_id)
    assert added["background_vault_binding_ids"] == [second.vault_binding_id]
    note = Path(second.path) / "watched-after-add.md"
    note.write_text("adopted from durable intent\n", encoding="utf-8")
    watcher_registry.run_registry_once(config)
    assert str(note) in outbox_paths(tmp_path)
    restarted_note = Path(second.path) / "watched-after-restart.md"
    restarted_note.write_text("still durable\n", encoding="utf-8")
    watcher_registry.run_registry_forever(config, max_ticks=1)
    assert str(restarted_note) in outbox_paths(tmp_path)
    assert str(silent) not in outbox_paths(tmp_path)

    # Compatibility no-vault to a default on another binding, same posture.
    monkeypatch.undo()
    runtime2, first2, second2, config2 = _watched_instance(tmp_path / "compat", monkeypatch)
    drive_watcher_during_waits(monkeypatch, config2)
    defaults = open_default_vault_service(runtime2.layout.registry_path)
    defaults.set(second2.vault_binding_id)
    runtime2.remove(second2.vault_binding_id)
    assert background_ids(runtime2) == ()
    runtime2.reactivate_removed(Path(second2.path))
    defaults.set(second2.vault_binding_id)
    assert background_ids(runtime2) == (second2.vault_binding_id,)
    note2 = Path(second2.path) / "watched-after-default.md"
    note2.write_text("default-driven\n", encoding="utf-8")
    watcher_registry.run_registry_once(config2)
    assert str(note2) in outbox_paths(tmp_path / "compat")


def test_explicit_member_reactivation_resumes_its_watcher(tmp_path, monkeypatch) -> None:
    from app.instance.runtime import _preflight_runtime
    from app.watcher import registry as watcher_registry

    runtime, first, second, config = _watched_instance(tmp_path, monkeypatch)
    drive_watcher_during_waits(monkeypatch, config)
    admin(runtime).remove(first.vault_binding_id)
    admin(runtime).add(second.vault_binding_id)
    watcher_registry.run_registry_once(config)
    runtime.remove(second.vault_binding_id)
    # Loudly failed member: retained, never silently dropped.
    assert background_ids(runtime) == (second.vault_binding_id,)
    assert supervisor(runtime).start().status == "failed"

    runtime.reactivate_removed(Path(second.path))
    assert runtime.open_settings_rebind_store().read().candidate_binding_id == second.vault_binding_id
    assert _preflight_runtime(
        channel=runtime.layout.channel_id,
        instance_state_root=runtime.layout.root.parent,
        host_global_root=runtime.ledger.root,
        consumer="watcher",
    ) == 0
    note = Path(second.path) / "watched-after-reactivation.md"
    note.write_text("running again\n", encoding="utf-8")
    watcher_registry.run_registry_once(config)
    assert str(note) in outbox_paths(tmp_path)


def test_unbracketed_candidate_is_not_scanned_before_commit(tmp_path, monkeypatch) -> None:
    """Re-adding the boot root from empty intent: nothing is emitted until the commit."""
    from app.instance.settings_rebind import SettingsRebindActivation
    from app.watcher import registry as watcher_registry

    runtime, first, second, config = _watched_instance(tmp_path, monkeypatch)
    drive_watcher_during_waits(monkeypatch, config)
    admin(runtime).remove(first.vault_binding_id)
    watcher_registry.run_registry_once(config)
    note = Path(first.path) / "written-while-empty.md"
    note.write_text("not bound yet\n", encoding="utf-8")
    original_store_ack = type(SettingsRebindActivation(runtime.registry).store).acknowledge_no_lifecycle
    observed_before_commit: list[bool] = []

    def tick_then_ack(self, *, desired_revision):
        # A watcher tick lands exactly inside the prepared window.
        watcher_registry.run_registry_once(config)
        observed_before_commit.append(str(note) in outbox_paths(tmp_path))
        return original_store_ack(self, desired_revision=desired_revision)

    monkeypatch.setattr(
        type(SettingsRebindActivation(runtime.registry).store),
        "acknowledge_no_lifecycle",
        tick_then_ack,
    )
    admin(runtime).add(first.vault_binding_id)
    assert observed_before_commit == [False]
    watcher_registry.run_registry_once(config)
    assert str(note) in outbox_paths(tmp_path)  # adopted only after the durable commit


def test_revocation_waits_for_an_effect_on_a_draining_binding(tmp_path, monkeypatch) -> None:
    import threading

    from app.instance.background_supervisor import revoke_background_role_fenced
    from app.instance.runtime import open_background_role_store, open_default_vault_service

    runtime, first, (second,) = mvr06b_instance(tmp_path, monkeypatch)
    stub_settings_reload(monkeypatch)
    open_default_vault_service(runtime.layout.registry_path).set(second.vault_binding_id)
    sup = supervisor(runtime)
    sup.start()
    role_store = open_background_role_store(runtime.layout.registry_path)
    held, release = threading.Event(), threading.Event()

    def effect() -> None:
        with sup.effect():
            held.set()
            release.wait(10)

    in_flight = threading.Thread(target=effect)
    in_flight.start()
    assert held.wait(5)

    def crash(name: str) -> None:
        if name == "binding-removal:reserved":
            raise _ProcessCrash(name)

    monkeypatch.setattr("app.instance.binding_removal._fault_point", crash)
    with pytest.raises(_ProcessCrash):
        runtime.remove(second.vault_binding_id)  # sealed, effect still in flight
    done: dict = {}
    revoker = threading.Thread(
        target=lambda: done.update(
            record=revoke_background_role_fenced(
                registry=runtime.registry,
                role_store=role_store,
                ownership_root=runtime.ledger.root,
                channel_id=runtime.layout.channel_id,
                _capability=STORAGE_MUTATION_CAPABILITY,
            )
        )
    )
    revoker.start()
    revoker.join(0.5)
    assert revoker.is_alive() and not done  # waits for the in-flight effect
    release.set()
    in_flight.join(10)
    revoker.join(10)
    assert done["record"].status == "revoked"


def test_watcher_rows_are_stamped_with_the_durable_binding_after_rebind_without_restart(
    tmp_path, monkeypatch
) -> None:
    from app.instance.scalar_binding_runtime import resolve_scalar_binding_runtime
    from app.watcher import registry as watcher_registry

    runtime, first, second, config = _watched_instance(tmp_path, monkeypatch)
    drive_watcher_during_waits(monkeypatch, config)
    pick(runtime, second.vault_binding_id)  # the boot env root stays the first binding
    assert Path(__import__("os").environ["WATCHER_VAULT_PATH"]) == Path(first.path)
    stamped: list[tuple[str, str]] = []
    real_emit = watcher_registry._emit_watch_event

    def emit(*args, **kwargs):
        current = resolve_scalar_binding_runtime()
        stamped.append((current.vault_binding_id, str(current.root)))
        return real_emit(*args, **kwargs)

    monkeypatch.setattr(watcher_registry, "_emit_watch_event", emit)
    note = Path(second.path) / "stamped-under-b.md"
    note.write_text("after rebind\n", encoding="utf-8")
    watcher_registry.run_registry_once(config)
    assert str(note) in outbox_paths(tmp_path)
    assert stamped and {item[0] for item in stamped} == {second.vault_binding_id}
    assert {item[1] for item in stamped} == {str(Path(second.path).resolve())}


def test_failed_lifecycle_idles_the_worker_and_reconciles_without_a_crash(
    tmp_path, monkeypatch
) -> None:
    from app.instance.runtime import (
        open_background_role_store,
        open_local_operator_principal_store,
    )
    from app.workers import outbox_worker

    runtime, first, _extra = mvr06b_instance(tmp_path, monkeypatch)
    role_store = open_background_role_store(runtime.layout.registry_path)
    role_store.revoke(_capability=STORAGE_MUTATION_CAPABILITY)
    assert outbox_worker.run_once().state == "background_lifecycle_failed"
    assert outbox_worker.run_once().state == "background_lifecycle_failed"
    role_store.redelegate(
        delegator=open_local_operator_principal_store(runtime.layout.registry_path).require(),
        floor_guard=lambda: True,
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    monkeypatch.setattr(outbox_worker, "poll_outbox_one", lambda **_k: None)
    monkeypatch.setattr(outbox_worker, "count_deferred_outbox_rows", lambda **_k: 0)
    assert outbox_worker.run_once().state == "idle"  # reconciled: the tick polls again


def test_worker_recompiles_settings_when_its_durable_binding_moves(tmp_path, monkeypatch) -> None:
    from app.workers import outbox_worker

    runtime, first, (second,) = mvr06b_instance(tmp_path, monkeypatch)
    reloads = stub_settings_reload(monkeypatch)
    outbox_worker._SETTINGS_BINDING.clear()
    outbox_worker._resolve_worker_binding_runtime(None)
    assert reloads == [Path(first.path).resolve()]
    outbox_worker._resolve_worker_binding_runtime(None)
    assert len(reloads) == 1  # an unchanged binding recompiles nothing
    pick(runtime, second.vault_binding_id)
    del reloads[:]
    outbox_worker._resolve_worker_binding_runtime(None)
    assert reloads == [Path(second.path).resolve()]


def test_sealed_dispatch_is_deferred_and_the_next_tick_blocks_without_a_crash(
    tmp_path, monkeypatch
) -> None:
    from app.instance.scalar_binding_runtime import resolve_background_worker_runtime
    from app.workers.outbox_binding_gate import OutboxBindingDeferred, worker_effect_window

    runtime, first, (second,) = mvr06b_instance(tmp_path, monkeypatch)
    stub_settings_reload(monkeypatch)
    worker = resolve_background_worker_runtime()
    message = {"vault_binding_id": first.vault_binding_id, "topic": "x", "payload": {}}

    def crash(name: str) -> None:
        if name == "binding-removal:reserved":
            raise _ProcessCrash(name)

    # The first binding is the rollback target; seal the second through its own runtime.
    from app.instance.runtime import open_default_vault_service

    open_default_vault_service(runtime.layout.registry_path).set(second.vault_binding_id)
    worker = resolve_background_worker_runtime()
    message["vault_binding_id"] = second.vault_binding_id
    monkeypatch.setattr("app.instance.binding_removal._fault_point", crash)
    with pytest.raises(_ProcessCrash):
        runtime.remove(second.vault_binding_id)
    with pytest.raises(OutboxBindingDeferred, match="sealed"):
        with worker_effect_window(message, runtime=worker):
            raise AssertionError("a sealed binding admitted a dispatch")
    # The deferred row stays queued for the restarted worker, whose next tick is a blocked
    # idle rather than a crash loop while the binding stays sealed.
    from app.workers import outbox_worker

    assert outbox_worker.run_once().state == "background_lifecycle_failed"


def test_journal_disagreement_is_loud_but_does_not_wedge_consumer_startup(
    tmp_path, monkeypatch, caplog
) -> None:
    from app.instance.runtime import _preflight_runtime
    from app.instance.vault_registry import RegistryRevisionConflict

    runtime, first, (second,) = mvr06b_instance(tmp_path, monkeypatch)
    stub_settings_reload(monkeypatch)
    registry_cls = type(runtime.registry)
    original = registry_cls.commit_settings_rebind_selection

    def refuse(self, **kwargs):
        raise RegistryRevisionConflict("injected commit race")

    # An acknowledged revision whose commit never ran: journal second, intent first.
    monkeypatch.setattr(registry_cls, "commit_settings_rebind_selection", refuse)
    with pytest.raises(RegistryRevisionConflict):
        pick(runtime, second.vault_binding_id)
    monkeypatch.setattr(registry_cls, "commit_settings_rebind_selection", original)
    assert runtime.open_settings_rebind_store().read().candidate_binding_id == second.vault_binding_id
    assert background_ids(runtime) == (first.vault_binding_id,)
    assert _preflight_runtime(
        channel=runtime.layout.channel_id,
        instance_state_root=runtime.layout.root.parent,
        host_global_root=runtime.ledger.root,
        consumer="worker",
    ) == 0
    assert "disagrees with durable background intent" in caplog.text


def test_failed_durable_member_is_reported_failed_not_healthy_idle(tmp_path, monkeypatch) -> None:
    from app.workers import outbox_worker

    runtime, first, (second,) = mvr06b_instance(tmp_path, monkeypatch)
    stub_settings_reload(monkeypatch)
    admin(runtime).remove(first.vault_binding_id)
    assert outbox_worker.run_once().state == "no_vault"  # truthful explicit-empty idle
    admin(runtime).add(second.vault_binding_id)
    runtime.remove(second.vault_binding_id)  # retained as loudly failed intent
    assert outbox_worker.run_once().state == "background_lifecycle_failed"
    admin(runtime).remove(second.vault_binding_id)
    assert outbox_worker.run_once().state == "no_vault"


def test_gov_verdict_change_rotates_rather_than_stalling_the_lifecycle(
    tmp_path, monkeypatch
) -> None:
    from app.governance.binding_authority import RegistryBindingAuthorizer
    from app.governance import binding_authority

    runtime, first, _extra = mvr06b_instance(tmp_path, monkeypatch)
    sup = supervisor(runtime)
    held = sup.start()
    original = RegistryBindingAuthorizer.authorize

    def moved_epoch(self, request):
        return binding_authority.BindingVerdict(
            **{**original(self, request).__dict__, "epoch": "moved-epoch"}
        )

    monkeypatch.setattr(RegistryBindingAuthorizer, "authorize", moved_epoch)
    rotated = sup.reconcile()
    assert rotated.generation == held.generation + 1
    assert rotated.status == "running" and rotated.authorization_epoch.startswith("moved-epoch|")
    with sup.effect() as lifecycle:
        assert lifecycle.generation == rotated.generation


def test_reactivation_refuses_another_roots_incomplete_journal(tmp_path, monkeypatch) -> None:
    from app.instance.settings_rebind import RegistryError

    runtime, first, extras = mvr06a_instance(tmp_path, extra_roots=("two", "three"))
    bind_runtime_env(monkeypatch, runtime)
    assert handoff_through_cli(runtime)["_exit_code"] == 0
    stub_settings_reload(monkeypatch)
    second, third = extras
    runtime.remove(second.vault_binding_id)
    runtime.remove(third.vault_binding_id)

    def crash(name: str) -> None:
        if name == "binding-reactivation:derived_invalidated":
            raise _ProcessCrash(name)

    monkeypatch.setattr("app.instance.binding_removal._fault_point", crash)
    with pytest.raises(_ProcessCrash):
        runtime.reactivate_removed(Path(second.path))
    monkeypatch.setattr("app.instance.binding_removal._fault_point", lambda name: None)
    with pytest.raises(RegistryError, match="another binding reactivation"):
        runtime.reactivate_removed(Path(third.path))
    assert third.vault_binding_id in runtime.registry.load().removal_tombstones
    # The same root resumes, and only then can the other root proceed.
    assert runtime.reactivate_removed(Path(second.path)).vault_binding_id == second.vault_binding_id
    assert runtime.reactivate_removed(Path(third.path)).vault_binding_id == third.vault_binding_id


# -- MVR-06C production relocation and the dormant multi-binding supervisor ---------------


def _relocation_instance(tmp_path, monkeypatch):
    """06B instance + an owner-native initialized binding enrolled as background intent."""

    from tests._mvr06c_relocation_harness import enroll_only, initialized_registration

    runtime, first, (second,) = mvr06b_instance(tmp_path, monkeypatch)
    stub_settings_reload(monkeypatch)
    third = initialized_registration(runtime, tmp_path / "three")
    enroll_only(runtime, third.vault_binding_id)
    assert background_ids(runtime) == (third.vault_binding_id,)
    return runtime, first, second, third


def test_relocation_activates_only_after_all_consumer_effect_leases(tmp_path, monkeypatch) -> None:
    import shutil
    import threading

    from app.instance.binding_removal import binding_epoch_lineage
    from tests._mvr06c_relocation_harness import copy_vault, leases, shared_refused

    # Before the MVR-06B background floor the production relocation stays sealed.
    staged, staged_first, _ = mvr06a_instance(tmp_path / "staged")
    before = staged.registry.load()
    with pytest.raises(CapabilityNotReadyError, match="MVR-06C consumer effect-lease floor"):
        staged.relocate(staged_first.vault_binding_id, tmp_path / "staged-target")
    assert staged.registry.load() == before
    assert not (staged.layout.root / "binding-relocation.json").exists()

    runtime, _first, _second, third = _relocation_instance(tmp_path / "live", monkeypatch)
    binding, old_root = third.vault_binding_id, Path(third.path)
    sup = supervisor(runtime, "worker")
    assert sup.start().root == old_root
    target = copy_vault(old_root, tmp_path / "live" / "relocated")
    holding, release = threading.Event(), threading.Event()

    def authorized_foreground_effect() -> None:
        with leases(runtime).shared_effect(
            binding, channel_id=runtime.layout.channel_id, root=old_root
        ):
            holding.set()
            release.wait(10)

    holder = threading.Thread(target=authorized_foreground_effect)
    holder.start()
    assert holding.wait(5)
    result: dict = {}
    relocator = threading.Thread(
        target=lambda: result.update(registration=runtime.relocate(binding, target))
    )
    relocator.start()
    relocator.join(1.0)
    # The exclusive relocation waits for the authorized effect under its reservation,
    # which already refuses every new holder on either root.
    assert relocator.is_alive()
    reserved = runtime.registry.load().registrations[binding]
    assert reserved.extensions["lifecycleState"] == "relocating"
    assert reserved.path == str(old_root.resolve())
    assert shared_refused(runtime, binding, old_root)
    assert shared_refused(runtime, binding, target)
    release.set()
    holder.join(10)
    relocator.join(30)
    relocated = result["registration"]
    assert relocated.path == str(target.resolve())
    assert "lifecycleState" not in relocated.extensions
    assert (relocated.vault_id, relocated.local_instance_id) == (third.vault_id, third.local_instance_id)
    assert runtime.ledger.lease_locator_names(
        binding, channel_id=runtime.layout.channel_id, root=target
    )
    # No later effect can touch the old root; the new root is admitted.
    assert shared_refused(runtime, binding, old_root)
    assert not shared_refused(runtime, binding, target)
    with sup.effect() as lifecycle:
        assert lifecycle.root == target.resolve()
        assert lifecycle.generation == 2
        assert lifecycle.binding_revision == relocated.extensions["bindingRevision"]
    events = binding_epoch_lineage(runtime.registry.load(), binding)
    assert [item["event"] for item in events] == ["relocated"]
    assert str(target) not in json.dumps(events) and str(old_root) not in json.dumps(events)

    # A renamed (moved) directory relocates too: the lease's physical identity follows it.
    renamed = tmp_path / "live" / "renamed"
    shutil.move(str(target), renamed)
    receipt = cli(
        "binding-relocate",
        "--registry-path", str(runtime.layout.registry_path),
        "--channel", runtime.layout.channel_id,
        "--host-global-root", str(runtime.ledger.root),
        "--consumer", "cli",
        "--watcher-posture", "absent",
        "--vault-binding-id", binding,
        "--destination", str(renamed),
    )
    assert receipt["_exit_code"] == 0, receipt
    assert receipt["state"] == "relocated" and str(renamed) not in json.dumps(receipt)
    assert runtime.registry.load().registrations[binding].path == str(renamed.resolve())
    assert not shared_refused(runtime, binding, renamed)
    assert sup.reconcile().root == renamed.resolve()


def test_relocation_rejects_different_initialized_vault_identity_before_commit(
    tmp_path, monkeypatch
) -> None:
    from app.instance.binding_relocation import (
        BindingRelocationRefused,
        RelocationIdentityError,
    )
    from tests._mvr06c_relocation_harness import copy_vault, shared_refused
    from tests.helpers.vault_settings import initialize_test_vault

    runtime, first, second, third = _relocation_instance(tmp_path, monkeypatch)
    binding, old_root = third.vault_binding_id, Path(third.path)
    impostor = initialize_test_vault(tmp_path / "impostor")
    unmarked = tmp_path / "unmarked"
    unmarked.mkdir()
    other_clone = copy_vault(old_root, tmp_path / "other-clone")
    local_marker = other_clone / "settings" / "local.md"
    local_marker.write_text(
        local_marker.read_text(encoding="utf-8").replace(
            third.local_instance_id, "local-someone-else"
        ),
        encoding="utf-8",
    )
    ambiguous = copy_vault(old_root, tmp_path / "ambiguous")
    (ambiguous / "settings" / "vault.md").write_text("---\nvaultId: [\n---\n", encoding="utf-8")
    nested = copy_vault(old_root, Path(second.path) / "nested")

    cases = [
        (binding, impostor, RelocationIdentityError, "different initialized vault"),
        (binding, unmarked, RelocationIdentityError, "no durable vault marker"),
        (binding, other_clone, RelocationIdentityError, "different local clone"),
        (binding, ambiguous, RelocationIdentityError, "ambiguous"),
        (binding, tmp_path / "missing", BindingRelocationRefused, "does not exist"),
        (binding, nested, BindingRelocationRefused, "overlaps another registered"),
        (binding, old_root, BindingRelocationRefused, "current root"),
        # An uninitialized binding has no logical identity to prove.
        (second.vault_binding_id, impostor, RelocationIdentityError, "initialized binding"),
    ]
    for target_binding, target, error, match in cases:
        registry_before, ledger_before = runtime.registry.load(), runtime.ledger.load()
        with pytest.raises(error, match=match):
            runtime.relocate(target_binding, target)
        assert runtime.registry.load() == registry_before
        assert runtime.ledger.load() == ledger_before
        assert not (runtime.layout.root / "binding-relocation.json").exists()
    assert not shared_refused(runtime, binding, old_root)

    # The MVR-01C scalar rollback target is refused before any reservation.
    from app.instance.vault_registry import RegistryDefaultConflict

    with pytest.raises(RegistryDefaultConflict, match="scalar rollback target"):
        runtime.relocate(first.vault_binding_id, impostor)

    # The target is proven again after the drain: a different vault swapped in while
    # holders drained fails before the ownership move and compensates to the source.
    from app.instance import binding_relocation

    target = copy_vault(old_root, tmp_path / "swapped")
    original_drain = binding_relocation.BindingRelocationCoordinator._drain

    def drain_then_swap(coordinator, intent):
        label = original_drain(coordinator, intent)
        import shutil

        shutil.rmtree(target)
        shutil.copytree(impostor, target)
        return label

    monkeypatch.setattr(binding_relocation.BindingRelocationCoordinator, "_drain", drain_then_swap)
    ledger_before = runtime.ledger.load()
    with pytest.raises(RelocationIdentityError, match="different initialized vault"):
        runtime.relocate(binding, target)
    after = runtime.registry.load().registrations[binding]
    assert after.path == str(old_root.resolve()) and "lifecycleState" not in after.extensions
    assert runtime.ledger.load() == ledger_before
    assert not (runtime.layout.root / "binding-relocation.json").exists()
    assert not shared_refused(runtime, binding, old_root)


@pytest.mark.parametrize(
    "phase",
    (
        "intent",
        "identity_validated",
        "reserved",
        "drained",
        "ownership_relocated",
        "committed",
        "consumers_reconciled",
    ),
)
def test_production_relocation_recovers_after_every_durable_phase(
    tmp_path, monkeypatch, phase
) -> None:
    from app.instance.binding_removal import binding_epoch_lineage
    from app.instance.context_bound_read import resolve_context_read_roots
    from tests._mvr06c_relocation_harness import copy_vault, shared_refused
    from tests._mvr_default_vault_harness import reopen_runtime

    runtime, _first, _second, third = _relocation_instance(tmp_path, monkeypatch)
    binding, old_root = third.vault_binding_id, Path(third.path)
    target = copy_vault(old_root, tmp_path / "relocated")
    point = f"binding-relocation:{phase}"

    def crash(name: str) -> None:
        if name == point:
            raise _ProcessCrash(name)

    monkeypatch.setattr("app.instance.binding_removal._fault_point", crash)
    with pytest.raises(_ProcessCrash):
        runtime.relocate(binding, target)
    monkeypatch.setattr("app.instance.binding_removal._fault_point", lambda name: None)

    # No mixed authority at any crash point: the registry names exactly one root, and
    # whenever registry and ledger could disagree the binding is sealed on both roots.
    registration = runtime.registry.load().registrations[binding]
    ledger_names_target = runtime.ledger.lease_locator_names(
        binding, channel_id=runtime.layout.channel_id, root=target
    )
    registry_names_target = registration.path == str(target.resolve())
    if registration.extensions.get("lifecycleState") is not None:
        assert shared_refused(runtime, binding, old_root)
        assert shared_refused(runtime, binding, target)
    else:
        assert registry_names_target == ledger_names_target
    if registry_names_target:
        assert ledger_names_target
        assert shared_refused(runtime, binding, old_root)

    restarted = reopen_runtime(runtime, tmp_path)
    recovered = restarted.recover_relocation()
    assert recovered is not None and recovered.vault_binding_id == binding
    assert restarted.recover_relocation() is None  # idempotent once complete
    final = restarted.registry.load()
    converged = final.registrations[binding]
    assert converged.path == str(target.resolve())
    assert "lifecycleState" not in converged.extensions
    assert restarted.ledger.lease_locator_names(
        binding, channel_id=restarted.layout.channel_id, root=target
    )
    assert [item["event"] for item in binding_epoch_lineage(final, binding)] == ["relocated"]
    # Foreground and background consumers converge on the one authorized root/revision.
    assert shared_refused(restarted, binding, old_root)
    assert not shared_refused(restarted, binding, target)
    lifecycle = supervisor(restarted, "worker").start()
    assert lifecycle.status == "running" and lifecycle.root == target.resolve()
    assert lifecycle.binding_revision == converged.extensions["bindingRevision"]
    assert [root.root for root in resolve_context_read_roots(lifecycle.context, registry_store=restarted.registry)] == [target.resolve()]


def test_mvr06c_dormant_supervisor_isolates_two_internal_bindings(tmp_path, monkeypatch) -> None:
    import shutil

    from app.instance.background_supervisor import (
        BackgroundLifecycleError,
        BackgroundLifecycleStale,
        BackgroundLifecycleSupervisor,
        stored_intent,
    )
    from tests._mvr06c_relocation_harness import (
        copy_vault,
        harness_supervisor,
        initialized_registration,
        leases,
    )

    runtime, _first, (_second,) = mvr06b_instance(tmp_path, monkeypatch)
    stub_settings_reload(monkeypatch)
    a = initialized_registration(runtime, tmp_path / "alpha")
    b = initialized_registration(runtime, tmp_path / "beta")
    pair = (a.vault_binding_id, b.vault_binding_id)
    intent_before = stored_intent(runtime.registry.load())

    # Production cannot construct it: the harness capability is private.
    with pytest.raises(CapabilityNotReadyError, match="dormant until MVR-06D"):
        BackgroundLifecycleSupervisor.for_runtime(
            registry_path=runtime.layout.registry_path,
            ownership_root=runtime.ledger.root,
            channel_id=runtime.layout.channel_id,
            consumer="watcher",
            internal_binding_ids=pair,
        )

    watcher = harness_supervisor(runtime, pair, "watcher")
    worker = harness_supervisor(runtime, pair, "worker")
    started = {item.binding_id: item for item in watcher.start_all()}
    assert set(started) == set(pair) and all(item.status == "running" for item in started.values())
    contexts = [started[item].context for item in pair]
    assert len({context.context_id for context in contexts}) == 2
    assert len({context.selection_capability_digest for context in contexts}) == 2
    assert [context.binding_ids for context in contexts] == [(pair[0],), (pair[1],)]
    health = watcher.health()
    assert health["many_binding"] == "internal_harness" and health["binding_capacity"] == 2
    assert [item["status"] for item in health["lifecycles"]] == ["running", "running"]
    assert a.path not in json.dumps(health) and b.path not in json.dumps(health)

    # Effects are isolated per binding: A's shared lease never blocks B's exclusive change.
    with watcher.effect(a.vault_binding_id) as held:
        assert held.root == Path(a.path)
        with leases(runtime).exclusive_change(
            b.vault_binding_id, channel_id=runtime.layout.channel_id, root=Path(b.path), timeout=2
        ):
            pass

    # Cross-process context handoff: the receiver re-resolves its own generation.
    handoff_b = watcher.lifecycle_for(b.vault_binding_id).handoff("watcher").as_payload()
    accepted = worker.accept_handoff(json.loads(json.dumps(handoff_b)))
    assert accepted.lifecycle.binding_id == b.vault_binding_id
    assert accepted.producer_context_id == handoff_b["contextId"]
    assert accepted.lifecycle.context.context_id != handoff_b["contextId"]

    # Independent revision reconciliation: relocating B rotates only B.
    a_before = watcher.lifecycle_for(a.vault_binding_id)
    moved_b = copy_vault(Path(b.path), tmp_path / "beta-relocated")
    runtime.relocate(b.vault_binding_id, moved_b)
    rotated = {item.binding_id: item for item in watcher.reconcile_all()}
    assert rotated[a.vault_binding_id] is a_before
    assert rotated[b.vault_binding_id].generation == 2
    assert rotated[b.vault_binding_id].root == moved_b.resolve()
    with pytest.raises(BackgroundLifecycleStale, match="superseded"):
        worker.accept_handoff(handoff_b)  # a pre-relocation handoff is stale
    fresh = rotated[b.vault_binding_id].handoff("watcher").as_payload()
    assert worker.accept_handoff(fresh).lifecycle.root == moved_b.resolve()

    # Independent auth reconciliation and failure containment: denying B fails only B.
    from app.governance.binding_authority import RegistryBindingAuthorizer
    from tests.helpers.revoked_binding_authorizer import RevokedBindingAuthorizer

    original = RegistryBindingAuthorizer.authorize

    def authorize(self, request):
        if request.vault_binding_id != b.vault_binding_id:
            return original(self, request)
        revoked = RevokedBindingAuthorizer(self)
        revoked.revoke_for_test(b.vault_binding_id)
        return revoked.authorize(request)

    monkeypatch.setattr(RegistryBindingAuthorizer, "authorize", authorize)
    denied = {item.binding_id: item for item in watcher.reconcile_all()}
    assert denied[b.vault_binding_id].status == "failed"
    assert denied[a.vault_binding_id] is a_before
    with watcher.effect(a.vault_binding_id) as still_running:
        assert still_running.generation == a_before.generation
    with pytest.raises(BackgroundLifecycleError):
        with watcher.effect(b.vault_binding_id):
            raise AssertionError("a denied binding performed an effect")
    monkeypatch.setattr(RegistryBindingAuthorizer, "authorize", original)
    assert watcher.lifecycle_for(b.vault_binding_id).status == "failed"
    assert {item.binding_id: item.status for item in watcher.reconcile_all()} == {
        a.vault_binding_id: "running",
        b.vault_binding_id: "running",
    }

    # A broken ownership root fails only A, never redirecting it to B.
    root_a = Path(a.path)
    parked = tmp_path / "alpha-parked"
    shutil.move(str(root_a), parked)
    root_a.mkdir()
    broken = {item.binding_id: item for item in watcher.reconcile_all()}
    assert broken[a.vault_binding_id].status == "failed"
    assert "ownership lease" in broken[a.vault_binding_id].failure
    assert broken[b.vault_binding_id].status == "running"
    with watcher.effect(b.vault_binding_id) as unaffected:
        assert unaffected.root == moved_b.resolve()
    shutil.rmtree(root_a)
    shutil.move(str(parked), root_a)
    assert all(item.status == "running" for item in watcher.reconcile_all())

    # Production stayed sealed throughout: durable intent never changed, and the process
    # supervisor is still the dormant singleton.
    assert stored_intent(runtime.registry.load()) == intent_before
    production = supervisor(runtime, "worker")
    production.start()
    assert production.health()["many_binding"] == "dormant"
    assert production.health()["binding_capacity"] == 1
