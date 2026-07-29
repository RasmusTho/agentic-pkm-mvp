from __future__ import annotations

import json
from pathlib import Path
import threading

import pytest
import yaml

import app.instance.ownership_ledger as ownership_ledger_module
import app.instance.runtime as runtime_module
from app.instance._storage_boundary import CapabilityNotReadyError
from app.instance.filesystem_identity import FilesystemRootIdentity
from app.instance.ownership_ledger import LedgerError, LedgerKeyError
from app.instance.instance_state import InstanceStateLayout
from app.instance.runtime import (
    InstanceRegistryRuntime,
    _begin_instance_state_deployment,
    _finish_instance_state_deployment,
    _preflight_scalar_rollback,
)
from app.instance.scalar_rollback_guard import (
    _ComposeLoader,
    preflight_scalar_rollback_guard,
    require_native_scalar_launcher,
)
from app.instance.vault_registry import AppLocalSettingsStore, RegistryError
from app.vault.manager import VaultManager
from tests.helpers.instance_storage_capability import STORAGE_MUTATION_CAPABILITY
from tests.helpers.mvr01c_authority import (
    establish_authority_window,
    finish_authority_window,
)


REPO_ROOT = Path(__file__).resolve().parents[2]


def _runtime(tmp_path):
    runtime = InstanceRegistryRuntime.for_paths(
        InstanceStateLayout.for_channel(tmp_path / "instance-state", "prod"),
        tmp_path / "host-global",
    )
    root = tmp_path / "selected"
    root.mkdir()
    registration = runtime.bootstrap_env_binding(vault_root=root, watcher_vault_path=root)
    receipt = preflight_scalar_rollback_guard(
        compose_overlay=REPO_ROOT / "docker-compose.scalar-rollback.yml",
        gateway_config=REPO_ROOT / "ops/scalar-rollback/nginx.conf",
        native_launcher=REPO_ROOT / "scripts/scalar_rollback_native.sh",
        rollback_vault_binding_id=registration.vault_binding_id,
        selected_root=root,
    )
    proof, inventory = establish_authority_window(runtime, tmp_path)
    runtime.activate_authority(
        guard_receipt=receipt,
        inventory_path=inventory,
        quiescence_proof=proof,
    )
    finish_authority_window(runtime, tmp_path, proof, inventory)
    return runtime, registration, root


def _scalar_preflight(runtime, registration, root, rollback_path) -> None:
    _preflight_scalar_rollback(
        channel=runtime.layout.channel_id,
        registry_path=runtime.layout.registry_path,
        host_global_root=runtime.ledger.root,
        rollback_vault_binding_id=registration.vault_binding_id,
        legacy_path=rollback_path,
        selected_root=root,
        compose_base=REPO_ROOT / "docker-compose.yaml",
        compose_overlay=REPO_ROOT / "docker-compose.scalar-rollback.yml",
        gateway_config=REPO_ROOT / "ops/scalar-rollback/nginx.conf",
        native_launcher=REPO_ROOT / "scripts/scalar_rollback_native.sh",
    )


def test_rollback_gateway_and_mounts_enforce_selected_binding(
    tmp_path,
    monkeypatch,
) -> None:
    runtime, registration, root = _runtime(tmp_path)

    receipt = preflight_scalar_rollback_guard(
        compose_overlay=REPO_ROOT / "docker-compose.scalar-rollback.yml",
        gateway_config=REPO_ROOT / "ops/scalar-rollback/nginx.conf",
        native_launcher=REPO_ROOT / "scripts/scalar_rollback_native.sh",
        rollback_vault_binding_id=registration.vault_binding_id,
        selected_root=root,
    )

    assert receipt.gateway_authenticated
    assert receipt.mutation_filtering
    assert receipt.direct_api_port_absent
    assert receipt.selected_mount_only
    wrong_root = tmp_path / "wrong-selected-root"
    wrong_root.mkdir()
    with pytest.raises(
        LedgerError,
        match="registration ownership is inconsistent",
    ):
        _preflight_scalar_rollback(
            channel=runtime.layout.channel_id,
            registry_path=runtime.layout.registry_path,
            host_global_root=runtime.ledger.root,
            rollback_vault_binding_id=registration.vault_binding_id,
            legacy_path=tmp_path / "wrong" / "app-local.md",
            selected_root=wrong_root,
            compose_base=REPO_ROOT / "docker-compose.yaml",
            compose_overlay=REPO_ROOT / "docker-compose.scalar-rollback.yml",
            gateway_config=REPO_ROOT / "ops/scalar-rollback/nginx.conf",
            native_launcher=REPO_ROOT / "scripts/scalar_rollback_native.sh",
        )
    assert not (tmp_path / "wrong" / "app-local.md").exists()

    host_policy = tmp_path / "host-policy"
    host_policy.mkdir()
    compose_base = host_policy / "docker-compose.yaml"
    compose_overlay = host_policy / "docker-compose.scalar-rollback.yml"
    gateway_config = host_policy / "nginx.conf"
    compose_base.write_bytes((REPO_ROOT / "docker-compose.yaml").read_bytes())
    compose_overlay.write_bytes(
        (REPO_ROOT / "docker-compose.scalar-rollback.yml").read_bytes()
    )
    gateway_config.write_bytes(
        (REPO_ROOT / "ops/scalar-rollback/nginx.conf").read_bytes() + b"\n"
    )
    with pytest.raises(
        RegistryError,
        match="gateway policy is incomplete",
    ):
        preflight_scalar_rollback_guard(
            compose_base=compose_base,
            compose_overlay=compose_overlay,
            gateway_config=gateway_config,
            native_launcher=REPO_ROOT / "scripts/scalar_rollback_native.sh",
            rollback_vault_binding_id=registration.vault_binding_id,
            selected_root=root,
        )
    gateway = (REPO_ROOT / "ops/scalar-rollback/nginx.conf").read_text(
        encoding="utf-8"
    )
    assert "location = /api/companion/vault/select" in gateway
    assert "location = /api/companion/vault/initialize" in gateway
    overlay = (REPO_ROOT / "docker-compose.scalar-rollback.yml").read_text(
        encoding="utf-8"
    )
    assert 'companion-ui:\n    profiles: ["scalar-rollback-disabled"]' in overlay
    deployment = (REPO_ROOT / "scripts/lib/instance_state_deployment.sh").read_text(
        encoding="utf-8"
    )
    assert "python -m app.instance.runtime authority-cutover" in deployment
    assert "--rollback-vault-binding-id" in deployment
    assert "--quiescence-proof-path" in deployment
    assert deployment.index(
        "python -m app.instance.runtime authority-cutover"
    ) < deployment.index(
        "python -m app.instance.runtime deployment-finish"
    )
    compose = yaml.safe_load(
        (REPO_ROOT / "docker-compose.yaml").read_text(encoding="utf-8")
    )
    rollback_compose = yaml.load(
        (REPO_ROOT / "docker-compose.scalar-rollback.yml").read_text(
            encoding="utf-8"
        ),
        Loader=_ComposeLoader,
    )
    guard_ownership_mount = next(
        mount
        for mount in rollback_compose["services"]["scalar-rollback-guard"][
            "volumes"
        ]
        if isinstance(mount, dict)
        and mount.get("target") == "/app/instance-ownership"
    )
    assert guard_ownership_mount["read_only"] is False
    assert all(
        not (
            isinstance(mount, dict)
            and mount.get("target") == "/app/instance-ownership"
        )
        and not (
            isinstance(mount, str)
            and "/app/instance-ownership" in mount
        )
        for mount in rollback_compose["services"]["api"]["volumes"]
    )
    for producer in ("api", "worker", "watcher", "heimdal-capture-watch"):
        environment = compose["services"][producer]["environment"]
        rendered = (
            environment
            if isinstance(environment, dict)
            else {
                entry.split("=", 1)[0]: entry.split("=", 1)[1]
                for entry in environment
            }
        )
        assert (
            rendered["INSTANCE_VAULT_REGISTRY_PATH"]
            == "/app/instance-state/agentic-pkm/vault-registry.md"
        )
        assert rendered["INSTANCE_OWNERSHIP_ROOT"] == "/app/instance-ownership"

    selected_mount = tmp_path / "selected-mount"
    selected_mount.mkdir()
    selected_identity = ownership_ledger_module.resolve_filesystem_root_identity(
        root
    )
    original_resolve = ownership_ledger_module.resolve_filesystem_root_identity
    original_material = ownership_ledger_module._identity_material

    def bind_aware_resolve(value):
        if Path(value) == selected_mount:
            return FilesystemRootIdentity(
                str(selected_mount),
                selected_identity.device,
                selected_identity.inode,
            )
        return original_resolve(value)

    def bind_aware_material(value):
        if Path(value) == selected_mount:
            return (
                f"inode:{selected_identity.device}:{selected_identity.inode}",
                ("inode:container-parent:alias",),
            )
        return original_material(value)

    monkeypatch.setattr(
        ownership_ledger_module,
        "resolve_filesystem_root_identity",
        bind_aware_resolve,
    )
    monkeypatch.setattr(
        ownership_ledger_module,
        "_identity_material",
        bind_aware_material,
    )
    rollback_path = tmp_path / "rollback" / "app-local.md"
    _scalar_preflight(runtime, registration, selected_mount, rollback_path)
    projected = AppLocalSettingsStore(rollback_path).load()
    assert projected.known_vaults[registration.ref].path == str(selected_mount)
    context = VaultManager(
        app_local_store=AppLocalSettingsStore(rollback_path)
    ).load_last_active()
    assert context.status == "uninitialized"
    assert context.active_vault_path == str(selected_mount)
    before = runtime.layout.registry_path.read_bytes()
    with pytest.raises(
        CapabilityNotReadyError,
        match="scalar rollback session blocks",
    ):
        runtime.registry.set_extension_state(
            default_vault_binding_id=None,
            dimensions={},
            principal_state={},
            background_state={},
            runtime_floors={},
            _capability=STORAGE_MUTATION_CAPABILITY,
        )
    assert runtime.layout.registry_path.read_bytes() == before

    session = runtime.registry.scalar_rollback_session_path
    document = json.loads(session.read_text(encoding="utf-8"))
    authentic_document = json.loads(session.read_text(encoding="utf-8"))
    document["payload"]["forkRegistryRevision"] -= 1
    session.write_text(json.dumps(document), encoding="utf-8")
    session.chmod(0o600)
    with pytest.raises(LedgerKeyError, match="authentication failed"):
        runtime.merge_previous_scalar_image(rollback_path)
    assert runtime.layout.registry_path.read_bytes() == before

    forged_payload = dict(authentic_document["payload"])
    forged_payload["initialExportSha256"] = "0" * 64
    forged_authentication = runtime.ledger.authenticate_scalar_rollback_session(
        forged_payload,
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    session.write_text(
        json.dumps(
            {
                "payload": forged_payload,
                "authentication": forged_authentication,
            }
        ),
        encoding="utf-8",
    )
    session.chmod(0o600)
    with pytest.raises(RegistryError, match="stale, ambiguous, or divergent"):
        runtime.merge_previous_scalar_image(rollback_path)
    assert runtime.layout.registry_path.read_bytes() == before

    with pytest.raises(CapabilityNotReadyError, match="private MVR storage"):
        runtime.ledger.authenticate_scalar_rollback_session(forged_payload)


def test_native_scalar_rollback_launcher_enforces_selected_binding_or_fails_closed(
    tmp_path,
) -> None:
    _, _, root = _runtime(tmp_path)

    with pytest.raises(CapabilityNotReadyError, match="root-owned"):
        require_native_scalar_launcher(
            launcher=REPO_ROOT / "scripts/scalar_rollback_native.sh",
            selected_root=root,
            effective_uid=1000,
        )
    launcher = (REPO_ROOT / "scripts/scalar_rollback_native.sh").read_text(
        encoding="utf-8"
    )
    assert "launcher must be root-owned mode 0755" in launcher
    assert "authenticated mutation filter unavailable; refusing startup" in launcher
    assert "exec /usr/bin/sandbox-exec" not in launcher
    assert "exec bwrap" not in launcher


def test_binding_keyed_database_floor_blocks_scalar_runtime(tmp_path) -> None:
    runtime, registration, _ = _runtime(tmp_path)
    runtime.registry.set_extension_state(
        default_vault_binding_id=None,
        dimensions={},
        principal_state={},
        background_state={},
        runtime_floors={"minimumRuntimeSchema": "mvr-05"},
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    rollback_path = tmp_path / "rollback" / "app-local.md"

    with pytest.raises(CapabilityNotReadyError, match="before database or queue startup"):
        _preflight_scalar_rollback(
            channel=runtime.layout.channel_id,
            registry_path=runtime.layout.registry_path,
            host_global_root=runtime.ledger.root,
            rollback_vault_binding_id=registration.vault_binding_id,
            legacy_path=rollback_path,
            selected_root=Path(
                runtime.registry.lookup(registration.vault_binding_id).path
            ),
            compose_base=REPO_ROOT / "docker-compose.yaml",
            compose_overlay=REPO_ROOT / "docker-compose.scalar-rollback.yml",
            gateway_config=REPO_ROOT / "ops/scalar-rollback/nginx.conf",
            native_launcher=REPO_ROOT / "scripts/scalar_rollback_native.sh",
        )
    assert not rollback_path.exists()

    pending_runtime, pending_registration, pending_root = _runtime(
        tmp_path / "pending"
    )
    orphan_root = tmp_path / "pending-orphan"
    orphan_root.mkdir()
    pending_runtime.ledger.reserve(
        channel_id="prod",
        vault_binding_id="pending-orphan",
        root=orphan_root,
        allow_same_channel_nested=False,
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    pending_rollback = tmp_path / "pending-rollback" / "app-local.md"
    with pytest.raises(LedgerError, match="no pending ownership transition"):
        _scalar_preflight(
            pending_runtime,
            pending_registration,
            pending_root,
            pending_rollback,
        )
    assert not pending_rollback.exists()
    assert not pending_runtime.registry.scalar_rollback_session_path.exists()


def test_deployment_begin_wins_scalar_admission_and_blocks_session_install(
    tmp_path,
    monkeypatch,
) -> None:
    runtime, registration, root = _runtime(tmp_path)
    entered_begin = threading.Event()
    release_begin = threading.Event()
    scalar_finished = threading.Event()
    begin_failures: list[BaseException] = []
    scalar_failures: list[BaseException] = []
    original_write = runtime_module._write_private_json

    def held_startup_fence(path, payload):
        if path.name == "scalar-rollback-startup-fence.json":
            entered_begin.set()
            assert release_begin.wait(timeout=5)
        return original_write(path, payload)

    monkeypatch.setattr(runtime_module, "_write_private_json", held_startup_fence)

    def begin() -> None:
        try:
            _begin_instance_state_deployment(
                channel="prod",
                instance_state_root=runtime.layout.root.parent,
                host_global_root=runtime.ledger.root,
                legacy_path=tmp_path / "missing-legacy.md",
                controller_pid=123,
                controller_start_token=f"linux:{'0' * 64}",
            )
        except BaseException as exc:
            begin_failures.append(exc)

    def scalar() -> None:
        try:
            _scalar_preflight(
                runtime,
                registration,
                root,
                tmp_path / "rollback" / "app-local.md",
            )
        except BaseException as exc:
            scalar_failures.append(exc)
        finally:
            scalar_finished.set()

    begin_thread = threading.Thread(target=begin)
    scalar_thread = threading.Thread(target=scalar)
    begin_thread.start()
    assert entered_begin.wait(timeout=5)
    scalar_thread.start()
    assert not scalar_finished.wait(timeout=0.1)
    release_begin.set()
    begin_thread.join(timeout=5)
    scalar_thread.join(timeout=5)

    assert not begin_thread.is_alive()
    assert not scalar_thread.is_alive()
    assert begin_failures == []
    assert len(scalar_failures) == 1
    assert isinstance(scalar_failures[0], RegistryError)
    assert "deployment lease or restart fence" in str(scalar_failures[0])
    assert not runtime.registry.scalar_rollback_session_path.exists()


def test_scalar_admission_wins_then_cross_channel_api_handoff_observes_deployment_fence(
    tmp_path,
    monkeypatch,
) -> None:
    runtime, registration, root = _runtime(tmp_path)
    dev_state = tmp_path / "dev-state"
    dev_state.mkdir()
    entered_scalar = threading.Event()
    begin_finished = threading.Event()
    failures: list[BaseException] = []
    original_store = runtime_module.VaultRegistryStore

    def observed_store(path):
        entered_scalar.set()
        return original_store(path)

    monkeypatch.setattr(runtime_module, "VaultRegistryStore", observed_store)

    def scalar() -> None:
        try:
            _scalar_preflight(
                runtime,
                registration,
                root,
                tmp_path / "rollback" / "app-local.md",
            )
        except BaseException as exc:
            failures.append(exc)

    def begin() -> None:
        try:
            _begin_instance_state_deployment(
                channel="dev",
                instance_state_root=dev_state,
                host_global_root=runtime.ledger.root,
                legacy_path=tmp_path / "missing-legacy.md",
                controller_pid=123,
                controller_start_token=f"linux:{'0' * 64}",
            )
        except BaseException as exc:
            failures.append(exc)
        finally:
            begin_finished.set()

    with runtime_module._producer_transition_locked(runtime.layout):
        scalar_thread = threading.Thread(target=scalar)
        begin_thread = threading.Thread(target=begin)
        scalar_thread.start()
        assert entered_scalar.wait(timeout=5)
        begin_thread.start()
        assert not begin_finished.wait(timeout=0.1)

    scalar_thread.join(timeout=5)
    begin_thread.join(timeout=5)

    assert not scalar_thread.is_alive()
    assert not begin_thread.is_alive()
    assert failures == []
    assert runtime.registry.scalar_rollback_session_path.is_file()
    assert (
        runtime.ledger.root
        / "deployment-public"
        / "scalar-rollback-startup-fence.json"
    ).is_file()
    rollback_compose = yaml.load(
        (REPO_ROOT / "docker-compose.scalar-rollback.yml").read_text(
            encoding="utf-8"
        ),
        Loader=_ComposeLoader,
    )
    api_command = rollback_compose["services"]["api"]["command"][-1]
    marker_check = (
        "test ! -e "
        "/app/deployment-control/scalar-rollback-startup-fence.json"
    )
    assert marker_check in api_command
    assert api_command.index(marker_check) < api_command.index(
        "exec bash /app/scripts/start_api.sh"
    )


def test_authority_cutover_rejects_pending_ownership(tmp_path) -> None:
    runtime = InstanceRegistryRuntime.for_paths(
        InstanceStateLayout.for_channel(tmp_path / "instance-state", "prod"),
        tmp_path / "host-global",
    )
    selected_root = tmp_path / "selected"
    pending_root = tmp_path / "pending"
    selected_root.mkdir()
    pending_root.mkdir()
    registration = runtime.bootstrap_env_binding(
        vault_root=selected_root,
        watcher_vault_path=selected_root,
    )
    proof, inventory = establish_authority_window(runtime, tmp_path)
    runtime.ledger.reserve(
        channel_id="prod",
        vault_binding_id="pending-binding",
        root=pending_root,
        allow_same_channel_nested=False,
        _capability=STORAGE_MUTATION_CAPABILITY,
    )

    with pytest.raises(LedgerError, match="no pending ownership transition"):
        runtime.activate_authority(
            guard_receipt=preflight_scalar_rollback_guard(
                compose_overlay=REPO_ROOT / "docker-compose.scalar-rollback.yml",
                gateway_config=REPO_ROOT / "ops/scalar-rollback/nginx.conf",
                native_launcher=REPO_ROOT / "scripts/scalar_rollback_native.sh",
                rollback_vault_binding_id=registration.vault_binding_id,
                selected_root=selected_root,
            ),
            inventory_path=inventory,
            quiescence_proof=proof,
        )

    assert runtime.registry.load().authority == "dormant"


def test_authority_cutover_requires_stopped_window_at_core_boundary(
    tmp_path,
) -> None:
    runtime = InstanceRegistryRuntime.for_paths(
        InstanceStateLayout.for_channel(tmp_path / "instance-state", "prod"),
        tmp_path / "host-global",
    )
    selected_root = tmp_path / "selected"
    selected_root.mkdir()
    registration = runtime.bootstrap_env_binding(
        vault_root=selected_root,
        watcher_vault_path=selected_root,
    )
    receipt = preflight_scalar_rollback_guard(
        compose_overlay=REPO_ROOT / "docker-compose.scalar-rollback.yml",
        gateway_config=REPO_ROOT / "ops/scalar-rollback/nginx.conf",
        native_launcher=REPO_ROOT / "scripts/scalar_rollback_native.sh",
        rollback_vault_binding_id=registration.vault_binding_id,
        selected_root=selected_root,
    )

    with pytest.raises(TypeError, match="inventory_path.*quiescence_proof"):
        runtime.activate_authority(guard_receipt=receipt)  # type: ignore[call-arg]

    assert runtime.registry.load().authority == "dormant"


def test_authority_cutover_serializes_against_deployment_finish(
    tmp_path,
    monkeypatch,
) -> None:
    runtime = InstanceRegistryRuntime.for_paths(
        InstanceStateLayout.for_channel(tmp_path / "instance-state", "prod"),
        tmp_path / "host-global",
    )
    selected_root = tmp_path / "selected"
    selected_root.mkdir()
    registration = runtime.bootstrap_env_binding(
        vault_root=selected_root,
        watcher_vault_path=selected_root,
    )
    proof, inventory = establish_authority_window(runtime, tmp_path)
    receipt = preflight_scalar_rollback_guard(
        compose_overlay=REPO_ROOT / "docker-compose.scalar-rollback.yml",
        gateway_config=REPO_ROOT / "ops/scalar-rollback/nginx.conf",
        native_launcher=REPO_ROOT / "scripts/scalar_rollback_native.sh",
        rollback_vault_binding_id=registration.vault_binding_id,
        selected_root=selected_root,
    )
    entered_cutover = threading.Event()
    release_cutover = threading.Event()
    entered_finish = threading.Event()
    failures: list[BaseException] = []
    original_bind = runtime_module._bind_legacy_owner_inventory_to_proof

    def held_bind(**kwargs):
        entered_cutover.set()
        assert release_cutover.wait(timeout=5)
        return original_bind(**kwargs)

    def observed_finish(**kwargs):
        del kwargs
        entered_finish.set()
        return {}

    monkeypatch.setattr(
        runtime_module,
        "_bind_legacy_owner_inventory_to_proof",
        held_bind,
    )
    monkeypatch.setattr(
        runtime_module,
        "_finish_instance_state_deployment_locked",
        observed_finish,
    )

    def activate() -> None:
        try:
            runtime.activate_authority(
                guard_receipt=receipt,
                inventory_path=inventory,
                quiescence_proof=proof,
            )
        except BaseException as exc:
            failures.append(exc)

    def finish() -> None:
        try:
            _finish_instance_state_deployment(
                channel="prod",
                instance_state_root=runtime.layout.root.parent,
                host_global_root=runtime.ledger.root,
                legacy_path=tmp_path / "missing-legacy.md",
                inventory_path=inventory,
                backup_root=tmp_path / "backup",
                restore_root=None,
                quiescence_proof=proof,
            )
        except BaseException as exc:
            failures.append(exc)

    cutover_thread = threading.Thread(target=activate)
    finish_thread = threading.Thread(target=finish)
    cutover_thread.start()
    assert entered_cutover.wait(timeout=5)
    finish_thread.start()
    assert not entered_finish.wait(timeout=0.1)
    release_cutover.set()
    cutover_thread.join(timeout=5)
    finish_thread.join(timeout=5)

    assert not cutover_thread.is_alive()
    assert not finish_thread.is_alive()
    assert failures == []
    assert entered_finish.is_set()
    assert runtime.registry.load().authority == "active"
