from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

import scripts.instance_state_writer_inventory as writer_inventory

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
    InventoryError,
    PF_KTHREAD,
    _linux_record,
    _parse_linux_stat,
    _parse_macos_ps_row,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
WRITER_INVENTORY_HELPER = REPO_ROOT / "scripts/instance_state_writer_inventory.py"


def _legacy_owner_inventory_payload(
    owners: list[dict[str, str]],
    *,
    inventory_complete: bool = True,
    writers_drained: bool = True,
    validated_after_quiescence: bool = True,
) -> dict[str, object]:
    owner_identities = []
    for owner in owners:
        root = Path(owner["root"])
        if root.is_dir():
            metadata = os.stat(root)
            identity = f"inode:{metadata.st_dev}:{metadata.st_ino}"
        else:
            identity = f"missing:{hashlib.sha256(str(root).encode()).hexdigest()}"
        owner_identities.append(
            {
                "channel_id": owner["channel_id"],
                "root": owner["root"],
                "identity": identity,
            }
        )
    source_evidence = {
        "docker": [],
        "config": [],
        "owners": owners,
        "owner_identities": owner_identities,
    }
    source_digest = hashlib.sha256(
        json.dumps(source_evidence, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "schema": "agentic-pkm.legacy-owner-inventory.v1",
        "inventory_complete": inventory_complete,
        "writers_drained": writers_drained,
        "source_probe_count": 2,
        "validated_after_quiescence": validated_after_quiescence,
        "source_digest": source_digest,
        "source_evidence": source_evidence,
        "owners": owners,
    }


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


def _linux_stat_fixture(
    pid: int,
    *,
    state: str = "S",
    flags: int = 0,
    ppid: int = 1,
    pgid: int | None = None,
    start_ticks: int = 456,
) -> str:
    fields = ["0"] * 20
    fields[0] = state
    fields[1] = str(ppid)
    fields[2] = str(pid if pgid is None else pgid)
    fields[6] = str(flags)
    fields[19] = str(start_ticks)
    return f"{pid} (fixture worker) {' '.join(fields)}"


def _scripted_linux_read(values):
    iterator = iter(values)

    def read(_pid: int):
        value = next(iterator)
        if isinstance(value, BaseException):
            raise value
        return value

    return read


def _install_linux_proc_fixture(
    monkeypatch: pytest.MonkeyPatch,
    *,
    stats,
    cmdlines,
    executables=None,
    gone: bool = False,
) -> None:
    monkeypatch.setattr(
        writer_inventory,
        "_read_linux_stat",
        _scripted_linux_read(stats),
    )
    monkeypatch.setattr(
        writer_inventory,
        "_read_linux_cmdline",
        _scripted_linux_read(cmdlines),
    )
    if executables is not None:
        monkeypatch.setattr(
            writer_inventory,
            "_read_linux_exe",
            _scripted_linux_read(executables),
        )
    monkeypatch.setattr(writer_inventory, "_linux_pid_is_gone", lambda _pid: gone)


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
            _legacy_owner_inventory_payload(
                [
                    {"channel_id": "test", "root": str(first)},
                    {"channel_id": "test", "root": str(second)},
                ]
            )
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
        json.dumps(_legacy_owner_inventory_payload([], inventory_complete=False)),
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


def test_deployment_producer_rejects_inventory_not_revalidated_after_quiescence(
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
            _legacy_owner_inventory_payload(
                [],
                writers_drained=False,
                validated_after_quiescence=False,
            )
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


def test_finalizer_rejects_legacy_digest_only_owner_receipt_before_state_mutation(
    tmp_path,
) -> None:
    instance_state_root = tmp_path / "instance-state"
    host_global_root = tmp_path / "host-global"
    instance_state_root.mkdir()
    host_global_root.mkdir()
    legacy_path = tmp_path / "missing-legacy.md"
    env = {**os.environ, "PATH": _empty_docker_path(tmp_path)}
    controller_pid = os.getpid()
    controller_token = _controller_token(controller_pid, env=env)
    _begin_instance_state_deployment(
        channel="prod",
        instance_state_root=instance_state_root,
        host_global_root=host_global_root,
        legacy_path=legacy_path,
        controller_pid=controller_pid,
        controller_start_token=controller_token,
    )
    result, quiescence_inventory = _run_quiescence_helper(
        tmp_path,
        controller_pid=controller_pid,
        controller_token=controller_token,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    proof = _prove_instance_state_quiescence(
        channel="prod",
        host_global_root=host_global_root,
        inventory_path=quiescence_inventory,
    )
    owner_inventory = host_global_root / "legacy-owner-inventory.json"
    legacy_payload = _legacy_owner_inventory_payload([])
    legacy_payload.pop("source_evidence")
    owner_inventory.write_text(json.dumps(legacy_payload), encoding="utf-8")
    os.chmod(owner_inventory, 0o600)
    state_before = {
        path.relative_to(instance_state_root): path.read_bytes()
        for path in instance_state_root.rglob("*")
        if path.is_file()
    }

    with pytest.raises(InstanceStatePreflightError, match="complete drained"):
        _finish_instance_state_deployment(
            channel="prod",
            instance_state_root=instance_state_root,
            host_global_root=host_global_root,
            legacy_path=legacy_path,
            inventory_path=owner_inventory,
            backup_root=host_global_root / "backups" / "prod" / "latest",
            restore_root=None,
            quiescence_proof=proof,
        )

    assert {
        path.relative_to(instance_state_root): path.read_bytes()
        for path in instance_state_root.rglob("*")
        if path.is_file()
    } == state_before
    assert _deployment_fence_path(host_global_root, "prod").is_file()
    assert not (host_global_root / "ownership-ledger.json").exists()
    assert not (host_global_root / "ownership-key.json").exists()
    assert not (host_global_root / "ownership-key-rotation.json").exists()


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
        json.dumps(_legacy_owner_inventory_payload([])),
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


def test_real_deployment_wrapper_produces_owner_inventory_before_mutation_window(
    tmp_path,
) -> None:
    """A fresh rollout derives owners before init, lease, fence, or writer stop."""

    event_log = tmp_path / "events.log"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    python = fake_bin / "python3"
    python.write_text(
        "#!/usr/bin/env bash\n"
        'printf \'python:%s\\n\' "$*" >> "$EVENT_LOG"\n'
        'case " $* " in\n'
        "  *' produce-legacy-owners '*)\n"
        '    while [ "$#" -gt 0 ]; do\n'
        '      if [ "$1" = --output ]; then printf \'{"writers_drained":false}\\n\' > "$2"; exit 0; fi\n'
        "      shift\n"
        "    done\n"
        "    exit 2 ;;\n"
        "  *' controller-token '*) printf 'linux:%064d\\n' 0; exit 0 ;;\n"
        "  *' prove-quiescent '*)\n"
        '    while [ "$#" -gt 0 ]; do\n'
        '      if [ "$1" = --output ]; then printf \'{}\\n\' > "$2"; exit 0; fi\n'
        "      shift\n"
        "    done\n"
        "    exit 2 ;;\n"
        "  *' validate-legacy-owners '*)\n"
        '    while [ "$#" -gt 0 ]; do\n'
        '      if [ "$1" = --output ]; then printf \'{"writers_drained":true}\\n\' > "$2"; exit 0; fi\n'
        "      shift\n"
        "    done\n"
        "    exit 2 ;;\n"
        "esac\n"
        "exit 2\n",
        encoding="utf-8",
    )
    python.chmod(0o755)
    harness = tmp_path / "run-wrapper.sh"
    harness.write_text(
        "#!/usr/bin/env bash\n"
        "set -u\n"
        f"source '{REPO_ROOT / 'scripts/lib/instance_state_deployment.sh'}'\n"
        "fake_compose() {\n"
        "  printf 'compose:%s\\n' \"$*\" >> \"$EVENT_LOG\"\n"
        "  return 0\n"
        "}\n"
        "prepare_instance_state_deployment fake_compose prod\n",
        encoding="utf-8",
    )
    harness.chmod(0o755)
    result = subprocess.run(
        ["bash", str(harness)],
        env={
            **os.environ,
            "EVENT_LOG": str(event_log),
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    events = event_log.read_text(encoding="utf-8").splitlines()
    assert "produce-legacy-owners" in events[0]
    assert "instance-state-init" in events[1]
    produce_index = next(i for i, event in enumerate(events) if "produce-legacy-owners" in event)
    begin_index = next(i for i, event in enumerate(events) if "deployment-begin" in event)
    stop_index = next(i for i, event in enumerate(events) if event.startswith("compose:stop "))
    proof_index = next(i for i, event in enumerate(events) if "deployment-prove" in event)
    validate_index = next(i for i, event in enumerate(events) if "validate-legacy-owners" in event)
    finish_index = next(i for i, event in enumerate(events) if "deployment-finish" in event)
    assert produce_index < begin_index < stop_index < proof_index < validate_index < finish_index


def _legacy_owner_source_fixture(tmp_path: Path) -> tuple[Path, dict[str, Path]]:
    repo_root = tmp_path / "repo"
    (repo_root / "config" / "deploy").mkdir(parents=True)
    roots: dict[str, Path] = {}
    for channel in ("dev", "test", "prod", "native"):
        root = tmp_path / f"vault-{channel}"
        root.mkdir()
        roots[channel] = root
        (repo_root / f".env.{channel}.local").write_text(
            f"VAULT_ROOT={root}\nWATCHER_VAULT_PATH={root}\n",
            encoding="utf-8",
        )
    return repo_root, roots


def test_legacy_owner_producer_derives_all_domains_without_preseeded_inventory(
    tmp_path,
) -> None:
    repo_root, roots = _legacy_owner_source_fixture(tmp_path)
    exported_dev_root = tmp_path / "vault-dev-exported"
    exported_dev_root.mkdir()
    native_scalar_root = tmp_path / "vault-native-scalar"
    native_scalar_root.mkdir()
    blocked_xdg = tmp_path / "blocked-xdg"
    blocked_xdg.write_text("not a directory\n", encoding="utf-8")
    native_home = tmp_path / "home"
    native_store = (
        native_home / "Library" / "Application Support" / "Agentic PKM" / "app-local.md"
    )
    native_store.parent.mkdir(parents=True)
    native_store.write_text(
        "---\n"
        "schema: agentic-pkm.app-local.v1\n"
        "knownVaults:\n"
        "  native-scalar:\n"
        f"    path: {native_scalar_root}\n"
        "---\n",
        encoding="utf-8",
    )
    inventory = tmp_path / "legacy-owner-inventory.json"
    env = {
        **os.environ,
        "PATH": _empty_docker_path(tmp_path),
        "HOME": str(native_home),
        "XDG_DATA_HOME": str(blocked_xdg / "child"),
        # A governed caller may export bindings for more than the channel it is
        # deploying. Non-active bindings are owner sources too and cannot be
        # silently omitted from the host-wide baseline.
        "VAULT_ROOT_DEV": str(exported_dev_root),
    }

    produced = subprocess.run(
        [
            sys.executable,
            str(WRITER_INVENTORY_HELPER),
            "produce-legacy-owners",
            "--repo-root",
            str(repo_root),
            "--active-channel",
            "prod",
            "--output",
            str(inventory),
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert produced.returncode == 0, produced.stderr
    payload = json.loads(inventory.read_text(encoding="utf-8"))
    assert payload["inventory_complete"] is True
    assert payload["writers_drained"] is False
    assert payload["owners"] == [
        {"channel_id": "dev", "root": str(roots["dev"].resolve())},
        {"channel_id": "dev", "root": str(exported_dev_root.resolve())},
        {"channel_id": "native", "root": str(roots["native"].resolve())},
        {"channel_id": "native", "root": str(native_scalar_root.resolve())},
        {"channel_id": "prod", "root": str(roots["prod"].resolve())},
        {"channel_id": "test", "root": str(roots["test"].resolve())},
    ]
    assert payload["source_evidence"]["owners"] == payload["owners"]
    assert payload["source_digest"] == hashlib.sha256(
        json.dumps(
            payload["source_evidence"], sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    validated = subprocess.run(
        [
            sys.executable,
            str(WRITER_INVENTORY_HELPER),
            "validate-legacy-owners",
            "--repo-root",
            str(repo_root),
            "--active-channel",
            "prod",
            "--inventory",
            str(inventory),
            "--output",
            str(inventory),
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert validated.returncode == 0, validated.stderr
    validated_payload = json.loads(inventory.read_text(encoding="utf-8"))
    assert validated_payload["writers_drained"] is True
    assert validated_payload["source_evidence"] == payload["source_evidence"]


def test_legacy_owner_producer_rejects_racing_config_source(tmp_path) -> None:
    repo_root, roots = _legacy_owner_source_fixture(tmp_path)
    inventory = tmp_path / "legacy-owner-inventory.json"
    ready_r, ready_w = os.pipe()
    continue_r, continue_w = os.pipe()
    env = {
        **os.environ,
        "PATH": _empty_docker_path(tmp_path),
        "XDG_DATA_HOME": str(tmp_path / "xdg"),
        "INSTANCE_STATE_OWNER_INVENTORY_TEST_BETWEEN_READY_FD": str(ready_w),
        "INSTANCE_STATE_OWNER_INVENTORY_TEST_BETWEEN_CONTINUE_FD": str(continue_r),
    }
    helper = subprocess.Popen(
        [
            sys.executable,
            str(WRITER_INVENTORY_HELPER),
            "produce-legacy-owners",
            "--repo-root",
            str(repo_root),
            "--active-channel",
            "prod",
            "--output",
            str(inventory),
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
        (repo_root / ".env.test.local").write_text(
            f"VAULT_ROOT={roots['test']}\n# raced\n", encoding="utf-8"
        )
        os.write(continue_w, b"C")
        _, stderr = helper.communicate(timeout=10)
    finally:
        os.close(ready_r)
        os.close(continue_w)
        if helper.poll() is None:
            helper.kill()
            helper.wait(timeout=5)
    assert helper.returncode != 0
    assert stderr == "legacy owner sources are incomplete or racing\n"
    assert not inventory.exists()


def test_legacy_owner_validation_rejects_source_change_after_preflight(tmp_path) -> None:
    repo_root, roots = _legacy_owner_source_fixture(tmp_path)
    inventory = tmp_path / "legacy-owner-inventory.json"
    env = {
        **os.environ,
        "PATH": _empty_docker_path(tmp_path),
        "XDG_DATA_HOME": str(tmp_path / "xdg"),
    }
    command = [
        sys.executable,
        str(WRITER_INVENTORY_HELPER),
        "produce-legacy-owners",
        "--repo-root",
        str(repo_root),
        "--active-channel",
        "prod",
        "--output",
        str(inventory),
    ]
    produced = subprocess.run(command, env=env, capture_output=True, text=True, check=False)
    assert produced.returncode == 0, produced.stderr
    (repo_root / ".env.dev.local").write_text(
        f"VAULT_ROOT={roots['dev']}\n# changed after preflight\n", encoding="utf-8"
    )

    validated = subprocess.run(
        [
            *command[:2],
            "validate-legacy-owners",
            *command[3:-2],
            "--inventory",
            str(inventory),
            "--output",
            str(inventory),
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert validated.returncode != 0
    assert validated.stderr == "legacy owner sources are incomplete or racing\n"
    assert json.loads(inventory.read_text(encoding="utf-8"))["writers_drained"] is False


def test_legacy_owner_validation_rejects_root_identity_change_after_preflight(tmp_path) -> None:
    repo_root, roots = _legacy_owner_source_fixture(tmp_path)
    inventory = tmp_path / "legacy-owner-inventory.json"
    env = {
        **os.environ,
        "PATH": _empty_docker_path(tmp_path),
        "XDG_DATA_HOME": str(tmp_path / "xdg"),
    }
    command = [
        sys.executable,
        str(WRITER_INVENTORY_HELPER),
        "produce-legacy-owners",
        "--repo-root",
        str(repo_root),
        "--active-channel",
        "prod",
        "--output",
        str(inventory),
    ]
    produced = subprocess.run(command, env=env, capture_output=True, text=True, check=False)
    assert produced.returncode == 0, produced.stderr
    replaced = tmp_path / "vault-test-replaced"
    roots["test"].rename(replaced)
    roots["test"].mkdir()

    validated = subprocess.run(
        [
            *command[:2],
            "validate-legacy-owners",
            *command[3:-2],
            "--inventory",
            str(inventory),
            "--output",
            str(inventory),
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert validated.returncode != 0
    assert validated.stderr == "legacy owner sources are incomplete or racing\n"
    assert json.loads(inventory.read_text(encoding="utf-8"))["writers_drained"] is False


def test_legacy_owner_producer_rejects_missing_explicit_source_before_output(
    tmp_path,
) -> None:
    repo_root, _ = _legacy_owner_source_fixture(tmp_path)
    inventory = tmp_path / "legacy-owner-inventory.json"
    env = {
        **os.environ,
        "PATH": _empty_docker_path(tmp_path),
        "XDG_DATA_HOME": str(tmp_path / "xdg"),
        "INSTANCE_LEGACY_OWNER_CONFIG_PATHS": str(tmp_path / "missing.env"),
    }

    result = subprocess.run(
        [
            sys.executable,
            str(WRITER_INVENTORY_HELPER),
            "produce-legacy-owners",
            "--repo-root",
            str(repo_root),
            "--active-channel",
            "prod",
            "--output",
            str(inventory),
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert result.stderr == "required legacy owner config source is missing\n"
    assert not inventory.exists()


def test_legacy_owner_producer_reads_stopped_compose_config_and_scalar_store(
    tmp_path, monkeypatch
) -> None:
    mounted = tmp_path / "mounted-vault"
    selected = tmp_path / "selected-vault"
    mounted.mkdir()
    selected.mkdir()
    container_id = "a" * 64
    inspected = [
        {
            "Id": container_id,
            "Config": {
                "Labels": {
                    "com.docker.compose.project": "pkm-test",
                    "com.docker.compose.service": "api",
                },
                "Env": [
                    "VAULT_ROOT=/app/vault",
                    "WATCHER_VAULT_PATH=/app/vault",
                    "DESIGN_HANDOFF_APP_LOCAL_SETTINGS=/app/tmp-test/agentic-pkm/app-local.md",
                ],
            },
            "Mounts": [
                {
                    "Type": "bind",
                    "Source": str(mounted),
                    "Destination": "/app/vault",
                },
                {
                    "Type": "bind",
                    "Source": str(tmp_path),
                    "Destination": "/Users/tester",
                },
            ],
        }
    ]

    def fake_checked(command, *, label, env=None):
        del label, env
        if command[:3] == ["docker", "ps", "-a"]:
            return f"{container_id}\n"
        if command[:2] == ["docker", "inspect"]:
            return json.dumps(inspected)
        raise AssertionError(command)

    app_local = (
        "---\n"
        "schema: agentic-pkm.app-local.v1\n"
        "knownVaults:\n"
        "  selected:\n"
        "    path: /Users/tester/selected-vault\n"
        "---\n"
        "# App Local Settings\n"
    ).encode()
    monkeypatch.setattr(writer_inventory, "_run_checked", fake_checked)
    monkeypatch.setattr(writer_inventory, "_docker_copy_file", lambda *_: app_local)

    owners, fingerprints = writer_inventory._docker_legacy_owner_sources()

    assert owners == [
        writer_inventory.LegacyOwnerRecord("test", str(mounted.resolve())),
        writer_inventory.LegacyOwnerRecord("test", str(selected.resolve())),
    ]
    assert len(fingerprints) == 1


def test_legacy_owner_producer_parses_canonical_quoted_app_local_paths() -> None:
    raw = (
        "---\n"
        "schema: agentic-pkm.app-local.v1\n"
        "knownVaults:\n"
        "  path:/private/example:\n"
        "    path: '/Users/operator/Vault #1'\n"
        "  quote-ref:\n"
        '    path: "/Users/operator/Vault \\u2603"\n'
        "---\n"
    ).encode()

    assert writer_inventory._parse_app_local_roots(raw) == [
        "/Users/operator/Vault #1",
        "/Users/operator/Vault ☃",
    ]


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
        "S",
        0,
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


def test_linux_record_preserves_empty_argv_positions(monkeypatch) -> None:
    pid = 321
    stat = _linux_stat_fixture(pid)
    _install_linux_proc_fixture(
        monkeypatch,
        stats=[stat, stat],
        cmdlines=[b"\0python\0\0tail\0\0"] * 2,
        executables=["/usr/bin/python3"] * 2,
    )

    record = _linux_record(pid, "boot-fixture")

    assert record is not None
    assert record.argv == ("", "python", "", "tail", "")
    assert record.executable_hint == "/usr/bin/python3"


def test_linux_empty_argv0_uses_executable_hint_for_launcher_role(monkeypatch) -> None:
    pid = 331
    stat = _linux_stat_fixture(pid)
    _install_linux_proc_fixture(
        monkeypatch,
        stats=[stat, stat],
        cmdlines=[b"\0/opt/pkm/scripts/start_full_system.sh\0"] * 2,
        executables=["/bin/bash"] * 2,
    )

    record = _linux_record(pid, "boot-fixture")

    assert record is not None
    assert writer_inventory._native_role(
        record.argv,
        executable_hint=record.executable_hint,
    ) == "start_full_system"


def test_linux_empty_argv0_harmless_executable_has_no_writer_role(monkeypatch) -> None:
    pid = 332
    stat = _linux_stat_fixture(pid)
    _install_linux_proc_fixture(
        monkeypatch,
        stats=[stat, stat],
        cmdlines=[b"\0" + b"30\0"] * 2,
        executables=["/usr/bin/sleep"] * 2,
    )

    record = _linux_record(pid, "boot-fixture")

    assert record is not None
    assert (
        writer_inventory._native_role(
            record.argv,
            executable_hint=record.executable_hint,
        )
        is None
    )


@pytest.mark.parametrize(
    "python_executable",
    ("python", "python3", "python3.12", "/usr/bin/python3"),
)
def test_native_outbox_worker_blocks_quiescence_for_supported_python_aliases(
    monkeypatch, python_executable: str
) -> None:
    controller_pid = 338
    controller_start_token = "linux:" + "a" * 64
    writer_start_token = "linux:" + "b" * 64
    processes = [
        writer_inventory.ProcessRecord(
            pid=controller_pid,
            ppid=1,
            pgid=controller_pid,
            start_token=writer_start_token,
            argv=(python_executable, "-m", "app.workers.outbox_worker"),
        )
    ]
    monkeypatch.setattr(
        writer_inventory,
        "_native_processes",
        lambda *, linux_boot_id: processes,
    )

    assert writer_inventory._native_writers(
        controller_pid=controller_pid,
        controller_start_token=controller_start_token,
        linux_boot_id="boot-fixture",
    ) == [
        {
            "domain": "native",
            "role": "outbox-worker",
            "pid": controller_pid,
            "start_token": writer_start_token,
        }
    ]

    processes[0] = writer_inventory.ProcessRecord(
        pid=controller_pid,
        ppid=1,
        pgid=controller_pid,
        start_token=controller_start_token,
        argv=(python_executable, "-m", "app.workers.outbox_worker"),
    )
    assert writer_inventory._native_writers(
        controller_pid=controller_pid,
        controller_start_token=controller_start_token,
        linux_boot_id="boot-fixture",
    ) == []


def test_linux_same_start_exec_transition_retries_to_stable_writer_pair(
    monkeypatch,
) -> None:
    pid = 336
    stat = _linux_stat_fixture(pid)
    harmless = b"\0" + b"30\0"
    writer = b"\0/opt/pkm/scripts/start_full_system.sh\0"
    _install_linux_proc_fixture(
        monkeypatch,
        stats=[stat, stat, stat, stat],
        cmdlines=[harmless, writer, writer, writer],
        executables=["/usr/bin/sleep", "/bin/bash", "/bin/bash", "/bin/bash"],
    )

    record = _linux_record(pid, "boot-fixture")

    assert record is not None
    assert writer_inventory._native_role(
        record.argv,
        executable_hint=record.executable_hint,
    ) == "start_full_system"


def test_linux_same_start_exec_pair_churn_fails_closed(monkeypatch) -> None:
    pid = 337
    stat = _linux_stat_fixture(pid)
    harmless = b"\0" + b"30\0"
    writer = b"\0/opt/pkm/scripts/start_full_system.sh\0"
    _install_linux_proc_fixture(
        monkeypatch,
        stats=[stat, stat] * 3,
        cmdlines=[harmless, writer] * 3,
        executables=["/usr/bin/sleep", "/bin/bash"] * 3,
    )

    with pytest.raises(InventoryError, match="exec identity changed"):
        _linux_record(pid, "boot-fixture")


@pytest.mark.parametrize(
    ("state", "flags"),
    [("Z", 0), ("S", PF_KTHREAD)],
)
def test_linux_record_skips_only_stable_inert_empty_processes(
    monkeypatch, state: str, flags: int
) -> None:
    pid = 322
    stat = _linux_stat_fixture(pid, state=state, flags=flags)
    _install_linux_proc_fixture(
        monkeypatch,
        stats=[stat, stat],
        cmdlines=[b""],
    )

    assert _linux_record(pid, "boot-fixture") is None


@pytest.mark.parametrize(
    ("state", "flags"),
    [("Z", 0), ("S", PF_KTHREAD)],
)
def test_linux_controller_lookup_never_skips_inert_processes(
    monkeypatch, state: str, flags: int
) -> None:
    pid = 329
    stat = _linux_stat_fixture(pid, state=state, flags=flags)
    _install_linux_proc_fixture(
        monkeypatch,
        stats=[stat, stat],
        cmdlines=[b""],
    )

    with pytest.raises(InventoryError, match="controller process identity is unavailable"):
        _linux_record(pid, "boot-fixture", strict_controller=True)


def test_linux_record_disappearance_is_skipped_only_after_final_proven_absence(
    monkeypatch,
) -> None:
    pid = 323
    stat = _linux_stat_fixture(pid)
    missing = FileNotFoundError()
    _install_linux_proc_fixture(
        monkeypatch,
        stats=[stat, stat, missing],
        cmdlines=[missing, missing],
        gone=True,
    )

    assert _linux_record(pid, "boot-fixture") is None


def test_linux_record_snapshot_disappearance_fails_closed(monkeypatch) -> None:
    pid = 338
    stat = _linux_stat_fixture(pid)
    missing = FileNotFoundError()
    _install_linux_proc_fixture(
        monkeypatch,
        stats=[stat, stat, missing],
        cmdlines=[missing, missing],
        gone=True,
    )

    with pytest.raises(InventoryError, match="enumeration failed"):
        _linux_record(pid, "boot-fixture", fail_closed_on_gone=True)


def test_linux_record_pid_reuse_returns_only_the_new_identity_pair(monkeypatch) -> None:
    pid = 324
    old = _linux_stat_fixture(pid, start_ticks=100)
    new = _linux_stat_fixture(pid, start_ticks=200)
    _install_linux_proc_fixture(
        monkeypatch,
        stats=[old, new, new, new],
        cmdlines=[
            b"/bin/bash\0start_full_system.sh\0",
            b"/usr/bin/sleep\0" + b"10\0",
        ],
    )

    record = _linux_record(pid, "boot-fixture")

    assert record is not None
    assert record.argv == ("/usr/bin/sleep", "10")
    assert record.start_token == writer_inventory._digest_token(
        "linux", "boot-fixture", pid, "200"
    )


def test_linux_record_stable_live_empty_cmdline_fails_closed(monkeypatch) -> None:
    pid = 325
    stat = _linux_stat_fixture(pid)
    _install_linux_proc_fixture(
        monkeypatch,
        stats=[stat, stat] * 3,
        cmdlines=[b""] * 3,
    )

    with pytest.raises(InventoryError, match="argv is unavailable"):
        _linux_record(pid, "boot-fixture")


def test_linux_record_stable_missing_terminal_nul_fails_closed(monkeypatch) -> None:
    pid = 326
    stat = _linux_stat_fixture(pid)
    _install_linux_proc_fixture(
        monkeypatch,
        stats=[stat, stat] * 3,
        cmdlines=[b"python"] * 3,
    )

    with pytest.raises(InventoryError, match="argv is malformed"):
        _linux_record(pid, "boot-fixture")


def test_linux_record_missing_nul_then_final_proven_absence_is_skipped(
    monkeypatch,
) -> None:
    pid = 333
    stat = _linux_stat_fixture(pid)
    missing = FileNotFoundError()
    _install_linux_proc_fixture(
        monkeypatch,
        stats=[stat, stat, stat, stat, missing],
        cmdlines=[b"python", b"python"],
        gone=True,
    )

    assert _linux_record(pid, "boot-fixture") is None


def test_linux_record_three_identity_changes_while_present_fail_closed(
    monkeypatch,
) -> None:
    pid = 334
    stats = [
        _linux_stat_fixture(pid, start_ticks=start_ticks)
        for start_ticks in (100, 200, 200, 300, 300, 400)
    ]
    _install_linux_proc_fixture(
        monkeypatch,
        stats=stats,
        cmdlines=[b"/usr/bin/sleep\0"] * 3,
    )

    with pytest.raises(InventoryError, match="identity changed"):
        _linux_record(pid, "boot-fixture")


@pytest.mark.parametrize(
    "executable",
    [PermissionError(), "relative/bash"],
)
def test_linux_record_empty_argv0_requires_stable_executable_identity(
    monkeypatch, executable
) -> None:
    pid = 335
    stat = _linux_stat_fixture(pid)
    _install_linux_proc_fixture(
        monkeypatch,
        stats=[stat, stat] * 3,
        cmdlines=[b"\0/opt/pkm/scripts/start_full_system.sh\0"] * 3,
        executables=[executable, executable, executable],
    )

    with pytest.raises(InventoryError, match="executable identity"):
        _linux_record(pid, "boot-fixture")


def test_linux_record_malformed_then_proven_exit_is_skipped(monkeypatch) -> None:
    pid = 327
    missing = FileNotFoundError()
    _install_linux_proc_fixture(
        monkeypatch,
        stats=["malformed", missing, missing],
        cmdlines=[],
        gone=True,
    )

    assert _linux_record(pid, "boot-fixture") is None


def test_linux_record_stable_permission_failure_fails_closed(monkeypatch) -> None:
    pid = 328
    stat = _linux_stat_fixture(pid)
    denied = PermissionError()
    _install_linux_proc_fixture(
        monkeypatch,
        stats=[stat, stat, stat],
        cmdlines=[denied, denied, denied],
    )

    with pytest.raises(InventoryError, match="enumeration failed"):
        _linux_record(pid, "boot-fixture")


def test_linux_snapshot_reads_boot_id_once(monkeypatch) -> None:
    pid = 330
    token = writer_inventory._digest_token("linux", "boot-fixture", pid, "456")
    reads: list[str] = []
    monkeypatch.setattr(writer_inventory.sys, "platform", "linux")
    monkeypatch.setattr(
        writer_inventory,
        "_read_linux_boot_id",
        lambda: reads.append("boot") or "boot-fixture",
    )
    monkeypatch.setattr(
        writer_inventory,
        "_record_for_pid",
        lambda controller_pid, *, linux_boot_id: writer_inventory.ProcessRecord(
            pid=controller_pid,
            ppid=1,
            pgid=controller_pid,
            start_token=token,
            argv=("deploy_channel.sh",),
        ),
    )
    monkeypatch.setattr(writer_inventory, "_docker_writers", lambda: [])

    def native_writers(*, controller_pid, controller_start_token, linux_boot_id):
        assert controller_pid == pid
        assert controller_start_token == token
        assert linux_boot_id == "boot-fixture"
        return []

    monkeypatch.setattr(writer_inventory, "_native_writers", native_writers)

    assert writer_inventory._snapshot(
        controller_pid=pid,
        controller_start_token=token,
    ) == {"dev": [], "native": [], "prod": [], "test": []}
    assert reads == ["boot"]


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux /proc contract")
def test_linux_actual_unreaped_zombie_is_inert(tmp_path) -> None:
    child = os.fork()
    if child == 0:
        os._exit(0)
    try:
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            raw = (Path("/proc") / str(child) / "stat").read_text(encoding="utf-8")
            if _parse_linux_stat(child, raw)[0] == "Z":
                break
            time.sleep(0.01)
        else:
            pytest.fail("child did not become a zombie within 5 seconds")
        env = {**os.environ, "PATH": _empty_docker_path(tmp_path)}
        controller_pid = os.getpid()
        result, _ = _run_quiescence_helper(
            tmp_path,
            controller_pid=controller_pid,
            controller_token=_controller_token(controller_pid, env=env),
            env=env,
        )
        assert result.returncode == 0, result.stderr
    finally:
        os.waitpid(child, 0)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux /proc contract")
def test_linux_actual_harmless_process_with_empty_argv_is_enumerated(tmp_path) -> None:
    process = subprocess.Popen(
        ["", "-c", "import time; time.sleep(30)", "", "tail", ""],
        executable=sys.executable,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        env = {**os.environ, "PATH": _empty_docker_path(tmp_path)}
        controller_pid = os.getpid()
        result, _ = _run_quiescence_helper(
            tmp_path,
            controller_pid=controller_pid,
            controller_token=_controller_token(controller_pid, env=env),
            env=env,
        )
        assert result.returncode == 0, result.stderr
    finally:
        process.terminate()
        process.wait(timeout=5)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux /proc contract")
def test_linux_actual_empty_argv0_shell_launcher_blocks(tmp_path) -> None:
    env = {**os.environ, "PATH": _empty_docker_path(tmp_path)}
    controller_pid = os.getpid()
    token = _controller_token(controller_pid, env=env)
    launcher = _write_blocking_launcher(tmp_path)
    process = subprocess.Popen(
        ["", str(launcher)],
        executable="/bin/bash",
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert process.stdout is not None
    assert process.stdout.read(1) == b"R"
    try:
        result, output = _run_quiescence_helper(
            tmp_path,
            controller_pid=controller_pid,
            controller_token=token,
            env=env,
        )
        assert result.returncode != 0
        assert result.stderr == "host-wide writer inventory is live or racing\n"
        assert not output.exists()
    finally:
        _stop_blocking_launcher(process)


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
