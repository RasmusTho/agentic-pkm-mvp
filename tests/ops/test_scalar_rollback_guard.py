from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest
import yaml

import app.instance.ownership_ledger as ownership_ledger_module
import app.instance.runtime as runtime_module
from app.instance._storage_boundary import CapabilityNotReadyError
from app.instance.filesystem_identity import FilesystemRootIdentity
from app.instance.ownership_ledger import LedgerError, LedgerKeyError
from app.instance.instance_state import (
    InstanceStateLayout,
    InstanceStatePreflightError,
)
from app.instance.runtime import (
    InstanceRegistryRuntime,
    _begin_instance_state_deployment,
    _finish_instance_state_deployment,
    _preflight_scalar_rollback,
    _roll_forward_scalar_rollback,
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


def _resume_authority_window(
    runtime: InstanceRegistryRuntime,
    scratch_root: Path,
    inventory_path: Path,
):
    controller = {
        "pid": 999_999_997,
        "start_token": "linux:" + "1" * 64,
    }
    _begin_instance_state_deployment(
        channel=runtime.layout.channel_id,
        instance_state_root=runtime.layout.root.parent,
        host_global_root=runtime.ledger.root,
        legacy_path=scratch_root / "missing-legacy.md",
        controller_pid=controller["pid"],
        controller_start_token=controller["start_token"],
    )
    domains = {domain: [] for domain in ("dev", "native", "prod", "test")}
    empty_digest = hashlib.sha256(
        json.dumps(domains, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    quiescence_inventory = (
        runtime.ledger.root / "deployment-quiescence-inventory.json"
    )
    quiescence_inventory.write_text(
        json.dumps(
            {
                "schema": "agentic-pkm.host-deployment-quiescence.v2",
                "inventory_complete": True,
                "all_consumers_stopped": True,
                "probe_count": 2,
                "controller": controller,
                "domains": domains,
                "snapshot_digests": [empty_digest, empty_digest],
            }
        ),
        encoding="utf-8",
    )
    quiescence_inventory.chmod(0o600)
    proof = runtime_module._prove_instance_state_quiescence(
        channel=runtime.layout.channel_id,
        host_global_root=runtime.ledger.root,
        inventory_path=quiescence_inventory,
    )
    owner_inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    for field in (
        "deployment_nonce",
        "controller",
        "quiescence_inventory_digest",
        "receipt_digest",
    ):
        owner_inventory.pop(field, None)
    inventory_path.write_text(json.dumps(owner_inventory), encoding="utf-8")
    inventory_path.chmod(0o600)
    return runtime_module._bind_legacy_owner_inventory_to_proof(
        inventory_path=inventory_path,
        quiescence_proof=proof,
        channel=runtime.layout.channel_id,
        host_global_root=runtime.ledger.root,
    )


def test_scalar_preflight_adopts_only_an_exact_persisted_session(
    tmp_path,
) -> None:
    runtime, registration, root = _runtime(tmp_path)
    rollback_path = tmp_path / "rollback" / "app-local.md"
    _scalar_preflight(runtime, registration, root, rollback_path)
    session_path = runtime.registry.scalar_rollback_session_path
    original = session_path.read_bytes()
    original_projection = rollback_path.read_bytes()

    _scalar_preflight(runtime, registration, root, rollback_path)
    assert session_path.read_bytes() == original

    rollback_path.unlink()
    with pytest.raises(RegistryError, match="projection is missing"):
        _scalar_preflight(runtime, registration, root, rollback_path)
    assert not rollback_path.exists()

    rollback_path.write_text(
        "---\nappInstallId: app-test\nknownVaults: {}\n---\n",
        encoding="utf-8",
    )
    rollback_path.chmod(0o600)
    with pytest.raises(RegistryError, match="escaped the selected binding"):
        _scalar_preflight(runtime, registration, root, rollback_path)

    rollback_path.write_bytes(original_projection)
    rollback_path.chmod(0o600)
    document = json.loads(original)
    document["payload"]["legacySelectedPath"] = str(tmp_path / "foreign")
    document["authentication"] = runtime.ledger.authenticate_scalar_rollback_session(
        document["payload"],
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    session_path.write_text(
        json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    session_path.chmod(0o600)

    with pytest.raises(
        RegistryError,
        match="existing scalar rollback session does not match this retry",
    ):
        _scalar_preflight(runtime, registration, root, rollback_path)


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
    gateway_config.write_bytes(
        (REPO_ROOT / "ops/scalar-rollback/nginx.conf").read_bytes()
    )
    compose_overlay.write_text(
        (REPO_ROOT / "docker-compose.scalar-rollback.yml")
        .read_text(encoding="utf-8")
        .replace("      WATCHER_VAULT_PATH: /app/selected-vault\n", "", 1),
        encoding="utf-8",
    )
    with pytest.raises(
        RegistryError,
        match="selectors are not selected-binding-only",
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
    assert rollback_compose["services"]["api"]["environment"] | {
        "VAULT_ROOT": "/app/selected-vault",
        "VAULT_ROOT_DEV": "/app/selected-vault",
        "VAULT_ROOT_TEST": "/app/selected-vault",
        "WATCHER_VAULT_PATH": "/app/selected-vault",
    } == rollback_compose["services"]["api"]["environment"]
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

    def held_deployment_lease(path, payload):
        if path.name == "deployment-host-global-lease.json":
            entered_begin.set()
            assert release_begin.wait(timeout=5)
        return original_write(path, payload)

    monkeypatch.setattr(runtime_module, "_write_private_json", held_deployment_lease)

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


def test_legacy_deployment_lease_blocks_scalar_guard_before_old_api_start(
    tmp_path,
) -> None:
    runtime, registration, root = _runtime(tmp_path)
    legacy_lease = runtime.ledger.root / "deployment-host-global-lease.json"
    legacy_lease.write_text(
        json.dumps(
            {
                "schema": "agentic-pkm.host-deployment-lease.v2",
                "channel_id": "dev",
                "nonce": "legacy-claimed",
                "phase": "claimed",
                "controller": {
                    "pid": 999_999_995,
                    "start_token": f"linux:{'1' * 64}",
                },
            }
        ),
        encoding="utf-8",
    )
    legacy_lease.chmod(0o600)

    with pytest.raises(
        RegistryError,
        match="deployment lease or restart fence",
    ):
        _scalar_preflight(
            runtime,
            registration,
            root,
            tmp_path / "rollback" / "app-local.md",
        )
    assert not runtime.registry.scalar_rollback_session_path.exists()


def test_previous_api_handoff_holds_runtime_admission_across_exec(
    tmp_path,
) -> None:
    rollback_compose = yaml.load(
        (REPO_ROOT / "docker-compose.scalar-rollback.yml").read_text(
            encoding="utf-8"
        ),
        Loader=_ComposeLoader,
    )
    command = rollback_compose["services"]["api"]["command"]
    assert command[:2] == ["python", "-c"]
    program = command[2]
    control_root = tmp_path / "deployment-control"
    control_root.mkdir()
    runtime_lock = control_root / "scalar-rollback-runtime.lock"
    runtime_lock.write_bytes(b"")
    runtime_lock.chmod(0o600)
    rollback_session = tmp_path / "scalar-rollback-session.json"
    rollback_session.write_text("{}", encoding="utf-8")
    ready = tmp_path / "old-api-ready"
    fake_start = tmp_path / "start_api.sh"
    fake_start.write_text(
        "#!/bin/bash\n"
        f"printf ready > '{ready}'\n"
        "while true; do sleep 1; done\n",
        encoding="utf-8",
    )
    fake_start.chmod(0o755)
    test_program = program.replace(
        "/app/deployment-control",
        str(control_root),
    ).replace(
        "/app/instance-state/agentic-pkm/vault-registry.md.scalar-rollback-session.json",
        str(rollback_session),
    ).replace(
        "/app/scripts/start_api.sh",
        str(fake_start),
    )
    process = subprocess.Popen(
        [sys.executable, "-c", test_program],
        env={**os.environ, "INSTANCE_STATE_LEGACY_ROLLBACK": "1"},
    )
    try:
        deadline = time.monotonic() + 5
        while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready.is_file()
        descriptor = os.open(runtime_lock, os.O_RDWR)
        try:
            with pytest.raises(BlockingIOError):
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(descriptor)
    finally:
        process.terminate()
        process.wait(timeout=5)

    ready.unlink()
    (control_root / "deployment-host-global-lease.json").write_text(
        "{}",
        encoding="utf-8",
    )
    blocked = subprocess.run(
        [sys.executable, "-c", test_program],
        env={**os.environ, "INSTANCE_STATE_LEGACY_ROLLBACK": "1"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert blocked.returncode == 75
    assert not ready.exists()


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
        / "deployment-host-global-lease.json"
    ).is_file()
    rollback_compose = yaml.load(
        (REPO_ROOT / "docker-compose.scalar-rollback.yml").read_text(
            encoding="utf-8"
        ),
        Loader=_ComposeLoader,
    )
    api_command = rollback_compose["services"]["api"]["command"][-1]
    lease_check = "/app/deployment-control/deployment-host-global-lease.json"
    runtime_lock = "/app/deployment-control/scalar-rollback-runtime.lock"
    assert lease_check in api_command
    assert runtime_lock in api_command
    assert api_command.index("fcntl.LOCK_SH") < api_command.index(lease_check)
    assert api_command.index(lease_check) < api_command.index("os.execv")


def test_scalar_roll_forward_serializes_against_deployment_finish(
    tmp_path,
    monkeypatch,
) -> None:
    runtime, registration, root = _runtime(tmp_path)
    rollback_path = tmp_path / "rollback" / "app-local.md"
    _scalar_preflight(runtime, registration, root, rollback_path)
    proof, inventory = establish_authority_window(runtime, tmp_path / "window")
    entered_roll_forward = threading.Event()
    release_roll_forward = threading.Event()
    entered_finish = threading.Event()
    failures: list[BaseException] = []
    original_bind = runtime_module._bind_legacy_owner_inventory_to_proof

    def held_bind(**kwargs):
        result = original_bind(**kwargs)
        entered_roll_forward.set()
        assert release_roll_forward.wait(timeout=5)
        return result

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

    def roll_forward() -> None:
        try:
            _roll_forward_scalar_rollback(
                channel="prod",
                instance_state_root=runtime.layout.root.parent,
                host_global_root=runtime.ledger.root,
                legacy_path=rollback_path,
                inventory_path=inventory,
                quiescence_proof_path=(
                    runtime.ledger.root / "deployment-quiescence-proof.json"
                ),
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

    roll_forward_thread = threading.Thread(target=roll_forward)
    finish_thread = threading.Thread(target=finish)
    roll_forward_thread.start()
    assert entered_roll_forward.wait(timeout=5)
    finish_thread.start()
    assert not entered_finish.wait(timeout=0.1)
    release_roll_forward.set()
    roll_forward_thread.join(timeout=5)
    finish_thread.join(timeout=5)

    assert not roll_forward_thread.is_alive()
    assert not finish_thread.is_alive()
    assert failures == []
    assert entered_finish.is_set()


def test_scalar_roll_forward_uses_lease_coverage_without_opening_vault_roots(
    tmp_path,
    monkeypatch,
) -> None:
    runtime, registration, selected_root = _runtime(tmp_path)
    nonselected_root = tmp_path / "nonselected"
    nonselected_root.mkdir()
    runtime.production_register(nonselected_root, producer="api")
    rollback_path = tmp_path / "rollback" / "app-local.md"
    _scalar_preflight(runtime, registration, selected_root, rollback_path)
    proof, inventory = establish_authority_window(runtime, tmp_path / "window")
    selected_root.rename(tmp_path / "selected-sealed")
    nonselected_root.rename(tmp_path / "nonselected-sealed")

    original_receipt_writer = runtime_module._write_scalar_roll_forward_receipt

    def interrupt_after_merge(host_global_root, lease, receipt):
        if receipt.get("status") == "merged":
            raise RuntimeError("simulated post-merge interruption")
        return original_receipt_writer(host_global_root, lease, receipt)

    monkeypatch.setattr(
        runtime_module,
        "_write_scalar_roll_forward_receipt",
        interrupt_after_merge,
    )
    with pytest.raises(RuntimeError, match="post-merge interruption"):
        _roll_forward_scalar_rollback(
            channel="prod",
            instance_state_root=runtime.layout.root.parent,
            host_global_root=runtime.ledger.root,
            legacy_path=rollback_path,
            inventory_path=inventory,
            quiescence_proof_path=(
                runtime.ledger.root / "deployment-quiescence-proof.json"
            ),
        )
    assert not runtime.registry.scalar_rollback_session_path.exists()
    monkeypatch.setattr(
        runtime_module,
        "_controller_identity_is_live",
        lambda controller: False,
    )
    proof = _resume_authority_window(
        runtime,
        tmp_path / "window",
        inventory,
    )
    monkeypatch.setattr(
        runtime_module,
        "_write_scalar_roll_forward_receipt",
        original_receipt_writer,
    )
    assert (
        _roll_forward_scalar_rollback(
            channel="prod",
            instance_state_root=runtime.layout.root.parent,
            host_global_root=runtime.ledger.root,
            legacy_path=rollback_path,
            inventory_path=inventory,
            quiescence_proof_path=(
                runtime.ledger.root / "deployment-quiescence-proof.json"
            ),
        )
        == 0
    )
    merged_registry = runtime.registry.load()
    with pytest.raises(
        InstanceStatePreflightError,
        match="cannot restore instance state",
    ):
        _finish_instance_state_deployment(
            channel="prod",
            instance_state_root=runtime.layout.root.parent,
            host_global_root=runtime.ledger.root,
            legacy_path=tmp_path / "missing-legacy.md",
            inventory_path=inventory,
            backup_root=tmp_path / "rejected-restore-backup",
            restore_root=tmp_path / "authority-backup",
            quiescence_proof=proof,
        )
    assert runtime.registry.load() == merged_registry
    assert not (tmp_path / "rejected-restore-backup").exists()

    ledger_path = runtime.ledger.path
    original_ledger = ledger_path.read_bytes()
    corrupted_ledger = json.loads(original_ledger)
    corrupted_ledger["leases"][registration.vault_binding_id][
        "sealed_root"
    ] = "not-an-authenticated-root"
    ledger_path.write_text(
        json.dumps(corrupted_ledger),
        encoding="utf-8",
    )
    ledger_path.chmod(0o600)
    with pytest.raises(
        InstanceStatePreflightError,
        match="backup registry/ledger consistency verification failed",
    ):
        _finish_instance_state_deployment(
            channel="prod",
            instance_state_root=runtime.layout.root.parent,
            host_global_root=runtime.ledger.root,
            legacy_path=tmp_path / "missing-legacy.md",
            inventory_path=inventory,
            backup_root=tmp_path / "rejected-corrupt-backup",
            restore_root=None,
            quiescence_proof=proof,
        )
    assert not (tmp_path / "rejected-corrupt-backup").exists()
    ledger_path.write_bytes(original_ledger)
    ledger_path.chmod(0o600)

    receipt = _finish_instance_state_deployment(
        channel="prod",
        instance_state_root=runtime.layout.root.parent,
        host_global_root=runtime.ledger.root,
        legacy_path=tmp_path / "missing-legacy.md",
        inventory_path=inventory,
        backup_root=tmp_path / "backup",
        restore_root=None,
        quiescence_proof=proof,
    )
    assert receipt["scalar_roll_forward_merged"] is True


def test_scalar_roll_forward_recovers_partial_receipt_persistence(
    tmp_path,
    monkeypatch,
) -> None:
    runtime, registration, selected_root = _runtime(tmp_path)
    rollback_path = tmp_path / "rollback" / "app-local.md"
    _scalar_preflight(runtime, registration, selected_root, rollback_path)
    proof, inventory = establish_authority_window(runtime, tmp_path / "window")
    root_lease_path = runtime_module._legacy_deployment_lease_path(
        runtime.ledger.root
    )
    original_replace = runtime_module._replace_private_json
    interrupted = False

    def interrupt_root_receipt(path, payload):
        nonlocal interrupted
        receipt = payload.get("scalar_roll_forward")
        if (
            not interrupted
            and path == root_lease_path
            and isinstance(receipt, dict)
            and receipt.get("status") == "prepared"
        ):
            interrupted = True
            raise OSError("simulated compatibility-block interruption")
        return original_replace(path, payload)

    monkeypatch.setattr(
        runtime_module,
        "_replace_private_json",
        interrupt_root_receipt,
    )
    with pytest.raises(OSError, match="compatibility-block interruption"):
        _roll_forward_scalar_rollback(
            channel="prod",
            instance_state_root=runtime.layout.root.parent,
            host_global_root=runtime.ledger.root,
            legacy_path=rollback_path,
            inventory_path=inventory,
            quiescence_proof_path=(
                runtime.ledger.root / "deployment-quiescence-proof.json"
            ),
        )
    monkeypatch.setattr(
        runtime_module,
        "_replace_private_json",
        original_replace,
    )
    monkeypatch.setattr(
        runtime_module,
        "_controller_identity_is_live",
        lambda controller: False,
    )
    proof = _resume_authority_window(
        runtime,
        tmp_path / "window",
        inventory,
    )
    assert (
        _roll_forward_scalar_rollback(
            channel="prod",
            instance_state_root=runtime.layout.root.parent,
            host_global_root=runtime.ledger.root,
            legacy_path=rollback_path,
            inventory_path=inventory,
            quiescence_proof_path=(
                runtime.ledger.root / "deployment-quiescence-proof.json"
            ),
        )
        == 0
    )
    receipt = _finish_instance_state_deployment(
        channel="prod",
        instance_state_root=runtime.layout.root.parent,
        host_global_root=runtime.ledger.root,
        legacy_path=tmp_path / "missing-legacy.md",
        inventory_path=inventory,
        backup_root=tmp_path / "backup",
        restore_root=None,
        quiescence_proof=proof,
    )
    assert receipt["scalar_roll_forward_merged"] is True


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


def test_authority_cutover_uses_selected_alias_without_opening_registry_path(
    tmp_path,
) -> None:
    runtime = InstanceRegistryRuntime.for_paths(
        InstanceStateLayout.for_channel(tmp_path / "instance-state", "prod"),
        tmp_path / "host-global",
    )
    selected_root = tmp_path / "srv-selected"
    selected_root.mkdir()
    registration = runtime.bootstrap_env_binding(
        vault_root=selected_root,
        watcher_vault_path=selected_root,
    )
    proof, inventory = establish_authority_window(runtime, tmp_path)
    selected_alias = tmp_path / "selected-container-alias"
    selected_root.rename(selected_alias)
    receipt = preflight_scalar_rollback_guard(
        compose_overlay=REPO_ROOT / "docker-compose.scalar-rollback.yml",
        gateway_config=REPO_ROOT / "ops/scalar-rollback/nginx.conf",
        native_launcher=REPO_ROOT / "scripts/scalar_rollback_native.sh",
        rollback_vault_binding_id=registration.vault_binding_id,
        selected_root=selected_alias,
    )

    activated = runtime.activate_authority(
        guard_receipt=receipt,
        inventory_path=inventory,
        quiescence_proof=proof,
    )

    assert activated.authority == "active"
    assert not selected_root.exists()
    assert selected_alias.is_dir()


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


def test_authority_cutover_keeps_the_v2_observable_block_through_commit(
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
    original_activate = runtime.registry.require_authoritative_activation
    old_v2_begin_was_blocked = False

    def observed_activate(*args, **kwargs):
        nonlocal old_v2_begin_was_blocked
        with pytest.raises(FileExistsError):
            runtime_module._write_private_json(
                runtime.ledger.root / "deployment-host-global-lease.json",
                {
                    "schema": "agentic-pkm.host-deployment-lease.v2",
                    "channel_id": "prod",
                    "nonce": "late-v2",
                    "phase": "claimed",
                    "controller": {
                        "pid": os.getpid(),
                        "start_token": f"linux:{'1' * 64}",
                    },
                },
            )
        old_v2_begin_was_blocked = True
        return original_activate(*args, **kwargs)

    monkeypatch.setattr(
        runtime.registry,
        "require_authoritative_activation",
        observed_activate,
    )
    activated = runtime.activate_authority(
        guard_receipt=receipt,
        inventory_path=inventory,
        quiescence_proof=proof,
    )

    assert activated.authority == "active"
    assert old_v2_begin_was_blocked
    root_block = json.loads(
        (
            runtime.ledger.root / "deployment-host-global-lease.json"
        ).read_text(encoding="utf-8")
    )
    assert (
        root_block["schema"]
        == "agentic-pkm.host-deployment-compatibility-block.v1"
    )


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
