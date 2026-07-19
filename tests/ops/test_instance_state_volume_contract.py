from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.instance.instance_state import (
    DeploymentQuiescenceProof,
    InstanceStateBackup,
    InstanceStateLayout,
    InstanceStatePreflightError,
    LegacyRegistryFinalExport,
    preflight_instance_state,
    validate_registry_disjoint_from_content,
)
from app.instance.runtime import (
    InstanceRegistryRuntime,
    _begin_instance_state_deployment,
    _deployment_fence_path,
    _finish_instance_state_deployment,
    _preflight_runtime,
    _prove_instance_state_quiescence,
)
from app.instance.vault_registry import (
    AppLocalSettingsStore,
    CapabilityNotReadyError,
    KnownVaultRef,
    RegistryActivationProof,
    RegistryError,
    VaultRegistration,
    VaultRegistryStore,
)
from app.release_channels.channel_isolation_preflight import _load_compose
from app.vault.manager import VaultManager
from scripts.instance_state_writer_inventory import (
    _parse_linux_stat,
    _parse_macos_ps_row,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
WRITER_INVENTORY_HELPER = REPO_ROOT / "scripts/instance_state_writer_inventory.py"


def _empty_docker_path(tmp_path: Path) -> str:
    fake_bin = tmp_path / "docker-bin"
    fake_bin.mkdir()
    docker = fake_bin / "docker"
    docker.write_text(
        "#!/usr/bin/env bash\n"
        "case \"${1:-}\" in\n"
        "  ps) exit 0 ;;\n"
        "  inspect) printf '[]\\n'; exit 0 ;;\n"
        "  *) exit 64 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    docker.chmod(0o755)
    return f"{fake_bin}:{os.environ['PATH']}"


def _controller_token(pid: int, *, env: dict[str, str] | None = None) -> str:
    return subprocess.check_output(
        [
            sys.executable,
            str(WRITER_INVENTORY_HELPER),
            "controller-token",
            "--pid",
            str(pid),
        ],
        env=env,
        text=True,
    ).strip()


def _write_blocking_launcher(tmp_path: Path, name: str = "start_full_system.sh") -> Path:
    script = tmp_path / name
    script.write_text(
        "#!/usr/bin/env bash\n"
        "printf 'R'\n"
        "IFS= read -r _\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


def _start_blocking_launcher(
    script: Path, *, separate_session: bool
) -> subprocess.Popen[bytes]:
    process = subprocess.Popen(
        [str(script)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=separate_session,
    )
    assert process.stdout is not None
    assert process.stdout.read(1) == b"R"
    return process


def _stop_blocking_launcher(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    assert process.stdin is not None
    process.stdin.write(b"\n")
    process.stdin.flush()
    process.wait(timeout=5)


def _run_quiescence_helper(
    tmp_path: Path,
    *,
    controller_pid: int,
    controller_token: str,
    env: dict[str, str] | None = None,
) -> tuple[subprocess.CompletedProcess[str], Path]:
    output = tmp_path / "inventory.json"
    result = subprocess.run(
        [
            sys.executable,
            str(WRITER_INVENTORY_HELPER),
            "prove-quiescent",
            "--controller-pid",
            str(controller_pid),
            "--controller-start-token",
            controller_token,
            "--output",
            str(output),
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return result, output


def test_mvr01a_schema_activation_requires_rollback_capability(tmp_path) -> None:
    registry_path = tmp_path / "vault-registry.md"
    store = VaultRegistryStore(registry_path)
    store.register(VaultRegistration("binding-a", "path:/a", "/a"))

    with pytest.raises(CapabilityNotReadyError, match="MVR-01B rollback exporter/transformer"):
        store.require_authoritative_activation(RegistryActivationProof())

    with pytest.raises(CapabilityNotReadyError, match="MVR-01C authority cutover"):
        store.require_authoritative_activation(
            RegistryActivationProof(
                rollback_exporter=True,
                rollback_transformer=True,
                previous_image_preflight=True,
            )
        )

    assert store.load().authority == "dormant"

    legacy_path = tmp_path / "app-local.md"
    vault_path = tmp_path / "vault"
    manager = VaultManager(app_local_store=AppLocalSettingsStore(legacy_path))
    manager.initialize_vault(vault_path, remember=True)
    assert AppLocalSettingsStore(legacy_path).load().known_vaults
    assert VaultRegistryStore(registry_path).load().revision == 1


def test_legacy_registry_export_happens_after_writer_quiescence(tmp_path) -> None:
    layout = InstanceStateLayout.for_channel(tmp_path / "instance-state", "test")
    legacy = AppLocalSettingsStore(tmp_path / "legacy" / "app-local.md")
    manager = VaultManager(app_local_store=legacy)
    manager.initialize_vault(tmp_path / "vault-one", remember=True)
    exporter = LegacyRegistryFinalExport(layout)
    diagnostic = exporter.capture_diagnostic_snapshot(legacy.path)
    manager.initialize_vault(tmp_path / "vault-two", remember=True)

    with pytest.raises(InstanceStatePreflightError, match="quiescence proof"):
        exporter.export_final_after_stop(
            legacy.path,
            quiescence_proof=None,
        )
    final = exporter.export_final_after_stop(
        legacy.path,
        quiescence_proof=DeploymentQuiescenceProof.for_test(),
    )
    assert final.fingerprint != diagnostic.fingerprint

    legacy.upsert_known_vault(KnownVaultRef("racing", str(tmp_path / "racing")))
    with pytest.raises(InstanceStatePreflightError, match="changed after final export"):
        exporter.import_final_export(final)

    repo_root = Path(__file__).resolve().parents[2]
    deploy = (repo_root / "scripts/deploy_channel.sh").read_text(encoding="utf-8")
    start = (repo_root / "scripts/start_full_system.sh").read_text(encoding="utf-8")
    producer = (repo_root / "scripts/lib/instance_state_deployment.sh").read_text(
        encoding="utf-8"
    )
    assert "prepare_instance_state_deployment compose" in deploy
    assert "prepare_instance_state_deployment run_docker_compose" in start
    assert producer.index("deployment-begin") < producer.index(" stop api worker watcher")
    assert producer.index(" stop api worker watcher") < producer.index("deployment-finish")
    assert "deployment-prove" in producer
    assert "probe_count" in WRITER_INVENTORY_HELPER.read_text(encoding="utf-8")


def test_deployment_producer_imports_final_state_bootstraps_owners_and_backs_up(
    tmp_path,
) -> None:
    instance_state_root = tmp_path / "instance-state"
    host_global_root = tmp_path / "host-global"
    instance_state_root.mkdir()
    host_global_root.mkdir()
    legacy_store = AppLocalSettingsStore(tmp_path / "legacy" / "app-local.md")
    manager = VaultManager(app_local_store=legacy_store)
    first = tmp_path / "vault-one"
    second = tmp_path / "vault-two"
    manager.initialize_vault(first, remember=True)

    diagnostic = _begin_instance_state_deployment(
        channel="test",
        instance_state_root=instance_state_root,
        host_global_root=host_global_root,
        legacy_path=legacy_store.path,
        controller_pid=os.getpid(),
        controller_start_token=_controller_token(os.getpid()),
    )
    fence = _deployment_fence_path(host_global_root, "test")
    assert fence.is_file()
    with pytest.raises(RegistryError, match="restart is fenced"):
        _preflight_runtime(
            channel="test",
            instance_state_root=instance_state_root,
            host_global_root=host_global_root,
            consumer="api",
        )

    # This post-diagnostic write represents the last old-image update. Only
    # the export captured after the wrapper stops writers may be imported.
    manager.initialize_vault(second, remember=True)
    inventory_path = host_global_root / "legacy-owner-inventory.json"
    inventory_path.write_text(
        json.dumps(
            {
                "schema": "agentic-pkm.legacy-owner-inventory.v1",
                "inventory_complete": True,
                "writers_drained": True,
                "owners": [
                    {"channel_id": "test", "root": str(first)},
                    {"channel_id": "test", "root": str(second)},
                ],
            }
        ),
        encoding="utf-8",
    )
    os.chmod(inventory_path, 0o600)
    receipt = _finish_instance_state_deployment(
        channel="test",
        instance_state_root=instance_state_root,
        host_global_root=host_global_root,
        legacy_path=legacy_store.path,
        inventory_path=inventory_path,
        backup_root=host_global_root / "backups" / "test" / "latest",
        restore_root=None,
        quiescence_proof=DeploymentQuiescenceProof.for_test("test"),
    )

    assert receipt["final_fingerprint"] != diagnostic["diagnostic_fingerprint"]
    assert receipt["restart_fence_cleared"] is True
    assert not fence.exists()
    layout = InstanceStateLayout.for_channel(instance_state_root, "test")
    registry = VaultRegistryStore(layout.registry_path).load()
    assert {Path(item.path) for item in registry.registrations.values()} == {
        first.resolve(),
        second.resolve(),
    }
    ledger = InstanceRegistryRuntime.for_paths(
        layout,
        host_global_root,
        initialize_layout=False,
    ).ledger.load()
    assert ledger.legacy_bootstrap_complete is True
    assert set(ledger.leases) == set(registry.registrations)
    backup_manifest = Path(str(receipt["backup_manifest"]))
    assert backup_manifest.is_file()
    assert {
        "legacy-final-export.md",
        "legacy-final-export.md.sha256",
    } <= json.loads(backup_manifest.read_text(encoding="utf-8"))["checksums"].keys()
    assert _preflight_runtime(
        channel="test",
        instance_state_root=instance_state_root,
        host_global_root=host_global_root,
        consumer="api",
    ) == 0


def test_deployment_producer_keeps_restart_fenced_on_incomplete_inventory(
    tmp_path,
) -> None:
    instance_state_root = tmp_path / "instance-state"
    host_global_root = tmp_path / "host-global"
    instance_state_root.mkdir()
    host_global_root.mkdir()
    legacy_path = tmp_path / "missing-legacy.md"
    _begin_instance_state_deployment(
        channel="prod",
        instance_state_root=instance_state_root,
        host_global_root=host_global_root,
        legacy_path=legacy_path,
        controller_pid=os.getpid(),
        controller_start_token=_controller_token(os.getpid()),
    )
    inventory_path = host_global_root / "legacy-owner-inventory.json"
    inventory_path.write_text(
        json.dumps(
            {
                "schema": "agentic-pkm.legacy-owner-inventory.v1",
                "inventory_complete": False,
                "writers_drained": True,
                "owners": [],
            }
        ),
        encoding="utf-8",
    )
    os.chmod(inventory_path, 0o600)

    with pytest.raises(InstanceStatePreflightError, match="complete drained"):
        _finish_instance_state_deployment(
            channel="prod",
            instance_state_root=instance_state_root,
            host_global_root=host_global_root,
            legacy_path=legacy_path,
            inventory_path=inventory_path,
            backup_root=host_global_root / "backups" / "prod" / "latest",
            restore_root=None,
            quiescence_proof=DeploymentQuiescenceProof.for_test("prod"),
        )

    assert _deployment_fence_path(host_global_root, "prod").is_file()
    assert not (host_global_root / "ownership-ledger.json").exists()
    assert not (host_global_root / "ownership-key.json").exists()


def test_finalizer_rejects_caller_booleans_without_a_durable_quiescence_proof(tmp_path) -> None:
    """AC5/AC14: a caller assertion is never a production stop proof."""

    state = tmp_path / "state"
    ownership = tmp_path / "ownership"
    state.mkdir()
    ownership.mkdir()
    _begin_instance_state_deployment(
        channel="dev",
        instance_state_root=state,
        host_global_root=ownership,
        legacy_path=tmp_path / "legacy.md",
        controller_pid=os.getpid(),
        controller_start_token=_controller_token(os.getpid()),
    )
    inventory = ownership / "legacy-owner-inventory.json"
    inventory.write_text(
        json.dumps(
            {
                "schema": "agentic-pkm.host-deployment-quiescence.v1",
                "inventory_complete": True,
                "writers_drained": True,
                "owners": [],
            }
        ),
        encoding="utf-8",
    )
    os.chmod(inventory, 0o600)

    with pytest.raises(InstanceStatePreflightError, match="quiescence proof"):
        _finish_instance_state_deployment(
            channel="dev",
            instance_state_root=state,
            host_global_root=ownership,
            legacy_path=tmp_path / "legacy.md",
            inventory_path=inventory,
            backup_root=ownership / "backup",
            restore_root=None,
            quiescence_proof=None,
        )


def test_restore_rejects_missing_durable_quiescence_proof_before_writes(tmp_path) -> None:
    layout = InstanceStateLayout.for_channel(tmp_path / "state", "prod")
    runtime = InstanceRegistryRuntime.for_paths(layout, tmp_path / "ownership")
    root = tmp_path / "vault"
    root.mkdir()
    runtime.bootstrap_env_binding(vault_root=root, watcher_vault_path=root)
    InstanceStateBackup(layout, runtime.ledger).create(tmp_path / "backup")
    before = {path.name: path.read_bytes() for path in layout.root.iterdir() if path.is_file()}

    with pytest.raises(InstanceStatePreflightError, match="quiescence proof"):
        InstanceStateBackup(layout, runtime.ledger).restore(
            tmp_path / "backup", quiescence_proof=None
        )

    assert {path.name: path.read_bytes() for path in layout.root.iterdir() if path.is_file()} == before


def test_host_wide_proof_rejects_live_or_racing_domains(tmp_path) -> None:
    state = tmp_path / "state"
    ownership = tmp_path / "ownership"
    state.mkdir()
    ownership.mkdir()
    _begin_instance_state_deployment(
        channel="prod",
        instance_state_root=state,
        host_global_root=ownership,
        legacy_path=tmp_path / "legacy.md",
        controller_pid=os.getpid(),
        controller_start_token=_controller_token(os.getpid()),
    )
    inventory = ownership / "legacy-owner-inventory.json"
    inventory.write_text(
        json.dumps(
            {
                "schema": "agentic-pkm.host-deployment-quiescence.v1",
                "inventory_complete": True,
                "probe_count": 2,
                "all_consumers_stopped": True,
                "domains": {"dev": [], "test": ["pkm-test-api"], "prod": [], "native": []},
                "owners": [],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(InstanceStatePreflightError, match="two-pass host-wide"):
        _prove_instance_state_quiescence(
            channel="prod", host_global_root=ownership, inventory_path=inventory
        )


def test_real_deployment_wrapper_probes_all_domains_twice_before_proof() -> None:
    producer = (Path(__file__).resolve().parents[2] / "scripts/lib/instance_state_deployment.sh").read_text(
        encoding="utf-8"
    )
    assert "instance_state_writer_inventory.py" in producer
    assert "prove-quiescent" in producer
    assert "pgrep" not in producer
    assert producer.index(" stop api worker watcher") < producer.index("deployment-prove")
    assert producer.index("deployment-prove") < producer.index("deployment-finish")


def test_foreground_controller_inventory_helper_passes_without_self_observation(tmp_path) -> None:
    path = _empty_docker_path(tmp_path)
    controller = tmp_path / "deploy_channel.sh"
    output = tmp_path / "inventory.json"
    controller.write_text(
        "#!/usr/bin/env bash\n"
        "set -eu\n"
        'token="$(\"$PYTHON\" \"$HELPER\" controller-token --pid \"$$\")"\n'
        '"$PYTHON" "$HELPER" prove-quiescent --controller-pid "$$" '
        '--controller-start-token "$token" --output "$OUTPUT"\n',
        encoding="utf-8",
    )
    controller.chmod(0o755)
    result = subprocess.run(
        [str(controller)],
        env={
            **os.environ,
            "PATH": path,
            "PYTHON": sys.executable,
            "HELPER": str(WRITER_INVENTORY_HELPER),
            "OUTPUT": str(output),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema"] == "agentic-pkm.host-deployment-quiescence.v2"
    assert payload["probe_count"] == 2
    assert payload["domains"] == {"dev": [], "native": [], "prod": [], "test": []}
    assert len(payload["snapshot_digests"]) == 2
    assert payload["snapshot_digests"][0] == payload["snapshot_digests"][1]


@pytest.mark.parametrize("separate_session", [True, False])
def test_actual_native_launcher_blocks_regardless_of_session_or_ancestry(
    tmp_path, separate_session
) -> None:
    env = {**os.environ, "PATH": _empty_docker_path(tmp_path)}
    controller_pid = os.getpid()
    token = _controller_token(controller_pid, env=env)
    launcher = _start_blocking_launcher(
        _write_blocking_launcher(tmp_path), separate_session=separate_session
    )
    try:
        result, output = _run_quiescence_helper(
            tmp_path,
            controller_pid=controller_pid,
            controller_token=token,
            env=env,
        )
    finally:
        _stop_blocking_launcher(launcher)
    assert result.returncode != 0
    assert result.stderr == "host-wide writer inventory is live or racing\n"
    assert not output.exists()


def test_actual_launcher_appearing_between_real_probes_blocks_without_sleep(tmp_path) -> None:
    env = {**os.environ, "PATH": _empty_docker_path(tmp_path)}
    controller_pid = os.getpid()
    token = _controller_token(controller_pid, env=env)
    output = tmp_path / "inventory.json"
    ready_r, ready_w = os.pipe()
    continue_r, continue_w = os.pipe()
    helper_env = {
        **env,
        "INSTANCE_STATE_INVENTORY_TEST_BETWEEN_READY_FD": str(ready_w),
        "INSTANCE_STATE_INVENTORY_TEST_BETWEEN_CONTINUE_FD": str(continue_r),
    }
    helper = subprocess.Popen(
        [
            sys.executable,
            str(WRITER_INVENTORY_HELPER),
            "prove-quiescent",
            "--controller-pid",
            str(controller_pid),
            "--controller-start-token",
            token,
            "--output",
            str(output),
        ],
        env=helper_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        pass_fds=(ready_w, continue_r),
        text=True,
    )
    os.close(ready_w)
    os.close(continue_r)
    launcher: subprocess.Popen[bytes] | None = None
    try:
        assert os.read(ready_r, 1) == b"R"
        launcher = _start_blocking_launcher(
            _write_blocking_launcher(tmp_path), separate_session=True
        )
        os.write(continue_w, b"C")
        _, stderr = helper.communicate(timeout=10)
    finally:
        os.close(ready_r)
        os.close(continue_w)
        if launcher is not None:
            _stop_blocking_launcher(launcher)
        if helper.poll() is None:
            helper.kill()
            helper.wait(timeout=5)
    assert helper.returncode != 0
    assert stderr == "host-wide writer inventory is live or racing\n"
    assert not output.exists()


def test_docker_enumeration_error_fails_closed_without_proof(tmp_path) -> None:
    fake_bin = tmp_path / "docker-bin"
    fake_bin.mkdir()
    docker = fake_bin / "docker"
    docker.write_text("#!/usr/bin/env bash\nexit 71\n", encoding="utf-8")
    docker.chmod(0o755)
    env = {**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}"}
    controller_pid = os.getpid()
    result, output = _run_quiescence_helper(
        tmp_path,
        controller_pid=controller_pid,
        controller_token=_controller_token(controller_pid, env=env),
        env=env,
    )
    assert result.returncode != 0
    assert "docker process enumeration failed" in result.stderr
    assert not output.exists()


def test_native_process_enumeration_error_fails_closed_without_proof(tmp_path) -> None:
    controller_pid = os.getpid()
    controller_token = _controller_token(controller_pid)
    output = tmp_path / "inventory.json"
    if sys.platform.startswith("linux"):
        env = {**os.environ, "PATH": _empty_docker_path(tmp_path)}
        ready_r, ready_w = os.pipe()
        continue_r, continue_w = os.pipe()
        env |= {
            "INSTANCE_STATE_INVENTORY_TEST_PROC_LIST_READY_FD": str(ready_w),
            "INSTANCE_STATE_INVENTORY_TEST_PROC_LIST_CONTINUE_FD": str(continue_r),
        }
        launcher = _start_blocking_launcher(
            _write_blocking_launcher(tmp_path), separate_session=True
        )
        helper = subprocess.Popen(
            [
                sys.executable,
                str(WRITER_INVENTORY_HELPER),
                "prove-quiescent",
                "--controller-pid",
                str(controller_pid),
                "--controller-start-token",
                controller_token,
                "--output",
                str(output),
            ],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            pass_fds=(ready_w, continue_r),
            text=True,
        )
        os.close(ready_w)
        os.close(continue_r)
        try:
            assert os.read(ready_r, 1) == b"R"
            _stop_blocking_launcher(launcher)
            os.write(continue_w, b"C")
            _, stderr = helper.communicate(timeout=10)
        finally:
            os.close(ready_r)
            os.close(continue_w)
            _stop_blocking_launcher(launcher)
            if helper.poll() is None:
                helper.kill()
                helper.wait(timeout=5)
    else:
        fake_bin = tmp_path / "native-bin"
        fake_bin.mkdir()
        docker = fake_bin / "docker"
        docker.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        docker.chmod(0o755)
        ps = fake_bin / "ps"
        ps.write_text(
            "#!/usr/bin/env bash\n"
            "case \" $* \" in\n"
            "  *\" -p \"*) exec /bin/ps \"$@\" ;;\n"
            "  *) exit 72 ;;\n"
            "esac\n",
            encoding="utf-8",
        )
        ps.chmod(0o755)
        result, _ = _run_quiescence_helper(
            tmp_path,
            controller_pid=controller_pid,
            controller_token=controller_token,
            env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}"},
        )
        helper = None
        stderr = result.stderr
    assert (helper.returncode if helper is not None else result.returncode) != 0
    assert "native process enumeration failed" in stderr
    assert not output.exists()


def test_linux_and_macos_process_identity_parsers_are_strict() -> None:
    fields = ["S", "1", "123", "123", *("0" for _ in range(15)), "456"]
    assert _parse_linux_stat(123, f"123 (bash worker) {' '.join(fields)}") == (
        1,
        123,
        "456",
    )
    mac = _parse_macos_ps_row(
        "  123     1   123 Sun Jul 19 05:36:50 2026     "
        "/bin/bash /opt/pkm/scripts/start_full_system.sh"
    )
    assert mac.pid == 123
    assert mac.ppid == 1
    assert mac.pgid == 123
    assert mac.argv == ("/bin/bash", "/opt/pkm/scripts/start_full_system.sh")
    with pytest.raises(RuntimeError, match="malformed"):
        _parse_macos_ps_row("123 malformed")


def test_proof_rejects_inventory_controller_identity_not_bound_to_active_lease(tmp_path) -> None:
    state = tmp_path / "state"
    ownership = tmp_path / "ownership"
    state.mkdir()
    ownership.mkdir()
    env = {**os.environ, "PATH": _empty_docker_path(tmp_path)}
    controller_pid = os.getpid()
    controller_token = _controller_token(controller_pid, env=env)
    _begin_instance_state_deployment(
        channel="prod",
        instance_state_root=state,
        host_global_root=ownership,
        legacy_path=tmp_path / "legacy.md",
        controller_pid=controller_pid,
        controller_start_token=controller_token,
    )
    result, inventory = _run_quiescence_helper(
        tmp_path,
        controller_pid=controller_pid,
        controller_token=controller_token,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(inventory.read_text(encoding="utf-8"))
    payload["controller"]["start_token"] = "linux:" + "0" * 64
    inventory.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(InstanceStatePreflightError, match="two-pass host-wide"):
        _prove_instance_state_quiescence(
            channel="prod", host_global_root=ownership, inventory_path=inventory
        )


def test_v2_inventory_proof_is_accepted_by_the_production_proof_consumer(tmp_path) -> None:
    state = tmp_path / "state"
    ownership = tmp_path / "ownership"
    state.mkdir()
    ownership.mkdir()
    env = {**os.environ, "PATH": _empty_docker_path(tmp_path)}
    controller_pid = os.getpid()
    controller_token = _controller_token(controller_pid, env=env)
    _begin_instance_state_deployment(
        channel="prod",
        instance_state_root=state,
        host_global_root=ownership,
        legacy_path=tmp_path / "legacy.md",
        controller_pid=controller_pid,
        controller_start_token=controller_token,
    )
    result, inventory = _run_quiescence_helper(
        tmp_path,
        controller_pid=controller_pid,
        controller_token=controller_token,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    proof = _prove_instance_state_quiescence(
        channel="prod", host_global_root=ownership, inventory_path=inventory
    )
    proof.require_valid(channel_id="prod")


def test_registry_volume_and_preflight_cover_all_consumers(tmp_path) -> None:
    layout = InstanceStateLayout.for_channel(tmp_path / "instance-state", "dev")
    layout.ensure()
    VaultRegistryStore(layout.registry_path).load()
    receipt = preflight_instance_state(
        layout,
        consumer_paths={
            "api": layout.registry_path,
            "worker": layout.registry_path,
            "watcher": layout.registry_path,
            "heimdal-capture-watch": layout.registry_path,
        },
    )
    assert set(receipt.consumers) == {"api", "worker", "watcher", "heimdal-capture-watch"}
    with pytest.raises(InstanceStatePreflightError):
        preflight_instance_state(layout, consumer_paths={"api": layout.registry_path})
    with pytest.raises(InstanceStatePreflightError, match="resolve identically"):
        preflight_instance_state(
            layout,
            consumer_paths={name: layout.registry_path for name in receipt.consumers} | {"worker": tmp_path / "elsewhere"},
        )

    compose = _load_compose(Path(__file__).resolve().parents[2] / "docker-compose.yaml")
    assert "instance-state" in compose["volumes"]
    init = compose["services"]["instance-state-init"]
    assert "instance-state:/app/instance-state" in init["volumes"]
    assert any("/app/instance-ownership" in mount for mount in init["volumes"])
    for consumer in receipt.consumers:
        service = compose["services"][consumer]
        assert "instance-state:/app/instance-state" in service["volumes"]
        assert any("/app/instance-ownership" in mount for mount in service["volumes"])
        assert "app.instance.runtime preflight" in service["command"][2]
        assert f"--consumer {consumer}" in service["command"][2]
        assert service["depends_on"]["instance-state-init"]["condition"] == "service_completed_successfully"


def test_runtime_preflight_rejects_missing_mounts_before_mutation(tmp_path) -> None:
    instance_state_root = tmp_path / "missing-instance-state"
    host_global_root = tmp_path / "missing-host-global"

    with pytest.raises(RegistryError, match="must already exist"):
        _preflight_runtime(
            channel="prod",
            instance_state_root=instance_state_root,
            host_global_root=host_global_root,
            consumer="api",
        )

    assert not instance_state_root.exists()
    assert not host_global_root.exists()


def test_registry_override_cannot_become_content_owned(tmp_path) -> None:
    root = tmp_path / "vault"
    root.mkdir()
    alias = tmp_path / "vault-alias"
    alias.symlink_to(root, target_is_directory=True)
    with pytest.raises(InstanceStatePreflightError, match="content root"):
        validate_registry_disjoint_from_content(root / "private" / "registry.md", [alias])

    safe = tmp_path / "instance-state" / "registry.md"
    validate_registry_disjoint_from_content(safe, [])
    with pytest.raises(InstanceStatePreflightError, match="content root"):
        validate_registry_disjoint_from_content(safe, [tmp_path])

    content_state = root / "private-state"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.instance.runtime",
            "preflight",
            "--channel",
            "dev",
            "--instance-state-root",
            str(content_state),
            "--host-global-root",
            str(tmp_path / "host-global"),
            "--consumer",
            "api",
        ],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "LLM_PROVIDER": "mock", "VAULT_ROOT": str(alias)},
    )
    assert result.returncode != 0
    assert "content root" in result.stderr
    assert not content_state.joinpath("agentic-pkm").exists()


def test_prod_instance_state_and_ledger_survive_volume_loss_with_verified_restore(tmp_path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    prod = _load_compose(repo_root / "docker-compose.prod.yml")
    assert prod["volumes"]["instance-state"] == {
        "external": True,
        "name": "pkm-prod_instance-state",
    }
    for producer in ("scripts/deploy_channel.sh", "scripts/start_full_system.sh"):
        text = (repo_root / producer).read_text(encoding="utf-8")
        assert "ensure_prod_instance_state_volume" in text
        assert "docker volume create" in text

    layout = InstanceStateLayout.for_channel(tmp_path / "prod-state", "prod")
    runtime = InstanceRegistryRuntime.for_paths(layout, tmp_path / "host-global")
    root = tmp_path / "vault"
    root.mkdir()
    runtime.bootstrap_env_binding(vault_root=root, watcher_vault_path=root)
    runtime.registry.set_extension_state(
        default_vault_binding_id="binding-default",
        dimensions={"d": ["binding-default"]},
        principal_state={"operator": "local"},
        background_state={"mode": "compatibility"},
        runtime_floors={"registry": "01b"},
    )
    backup = InstanceStateBackup(layout, runtime.ledger).create(tmp_path / "backup")
    expected = json.loads(backup.manifest_path.read_text(encoding="utf-8"))
    assert {
        "vault-registry.md.last-good",
        "vault-registry.md.last-good.sha256",
    } <= expected["checksums"].keys()

    for path in layout.root.iterdir():
        if path.is_file():
            path.unlink()
    for path in runtime.ledger.root.iterdir():
        if path.is_file():
            path.unlink()
    stale_final = layout.root / "legacy-final-export.md"
    stale_checksum = layout.root / "legacy-final-export.md.sha256"
    stale_final.write_text("stale", encoding="utf-8")
    stale_checksum.write_text("stale", encoding="ascii")
    os.chmod(stale_final, 0o600)
    os.chmod(stale_checksum, 0o600)
    restored = InstanceStateBackup(layout, runtime.ledger).restore(
        tmp_path / "backup",
        quiescence_proof=DeploymentQuiescenceProof.for_test("prod"),
    )
    assert restored.registry_checksum == expected["registry_checksum"]
    assert runtime.registry.load().extensions["runtimeFloors"] == {"registry": "01b"}
    assert runtime.ledger.load().leases
    assert not stale_final.exists()
    assert not stale_checksum.exists()

    layout.registry_path.unlink()
    assert runtime.registry.load().extensions["runtimeFloors"] == {"registry": "01b"}
    layout.registry_path.write_bytes(b"torn registry write")
    os.chmod(layout.registry_path, 0o600)
    assert runtime.registry.load().extensions["runtimeFloors"] == {"registry": "01b"}

    (tmp_path / "backup" / "ownership-key.json").unlink()
    with pytest.raises(InstanceStatePreflightError, match="complete ledger/key"):
        InstanceStateBackup(layout, runtime.ledger).restore(tmp_path / "backup", quiescence_proof=DeploymentQuiescenceProof.for_test("prod"))


def test_prod_restore_rejects_foreign_channel_before_writing_target_state(tmp_path) -> None:
    source_layout = InstanceStateLayout.for_channel(tmp_path / "dev-state", "dev")
    source_runtime = InstanceRegistryRuntime.for_paths(
        source_layout,
        tmp_path / "dev-host-global",
    )
    source_root = tmp_path / "dev-vault"
    source_root.mkdir()
    source_runtime.bootstrap_env_binding(
        vault_root=source_root,
        watcher_vault_path=source_root,
    )
    InstanceStateBackup(source_layout, source_runtime.ledger).create(
        tmp_path / "dev-backup"
    )

    target_layout = InstanceStateLayout.for_channel(tmp_path / "prod-state", "prod")
    target_runtime = InstanceRegistryRuntime.for_paths(
        target_layout,
        tmp_path / "prod-host-global",
    )
    target_root = tmp_path / "prod-vault"
    target_root.mkdir()
    target_runtime.bootstrap_env_binding(
        vault_root=target_root,
        watcher_vault_path=target_root,
    )
    target_runtime.registry.set_extension_state(
        default_vault_binding_id="prod-default",
        dimensions={"prod": ["prod-default"]},
        principal_state={"operator": "prod"},
        background_state={"mode": "prod"},
        runtime_floors={"registry": "prod"},
    )

    target_roots = (target_layout.root, target_runtime.ledger.root)
    before = {
        path.relative_to(tmp_path): path.read_bytes()
        for root in target_roots
        for path in root.iterdir()
        if path.is_file()
    }

    with pytest.raises(InstanceStatePreflightError, match="channel_id"):
        InstanceStateBackup(target_layout, target_runtime.ledger).restore(
            tmp_path / "dev-backup",
            quiescence_proof=DeploymentQuiescenceProof.for_test("prod"),
        )

    after = {
        path.relative_to(tmp_path): path.read_bytes()
        for root in target_roots
        for path in root.iterdir()
        if path.is_file()
    }
    assert after == before
