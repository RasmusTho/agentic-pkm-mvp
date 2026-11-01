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


@pytest.mark.parametrize("fault", ["drain", "before_commit", "registry_write"])
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
