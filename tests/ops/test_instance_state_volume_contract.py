from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from dataclasses import replace
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
from app.instance.ownership_ledger import LedgerCollisionError, LedgerError
from app.instance.runtime import (
    InstanceRegistryRuntime,
    _begin_instance_state_deployment,
    _bind_legacy_owner_inventory_to_proof,
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
from tests.helpers.instance_storage_capability import STORAGE_MUTATION_CAPABILITY


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


def _prove_empty_quiescence(
    *, channel: str, host_global_root: Path
) -> DeploymentQuiescenceProof:
    lease = json.loads(
        (host_global_root / "deployment-host-global-lease.json").read_text(
            encoding="utf-8"
        )
    )
    domains = {domain: [] for domain in ("dev", "native", "prod", "test")}
    digest = hashlib.sha256(
        json.dumps(domains, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    inventory = host_global_root / "deployment-quiescence-inventory.json"
    inventory.write_text(
        json.dumps(
            {
                "schema": "agentic-pkm.host-deployment-quiescence.v2",
                "inventory_complete": True,
                "all_consumers_stopped": True,
                "probe_count": 2,
                "controller": lease["controller"],
                "domains": domains,
                "snapshot_digests": [digest, digest],
            }
        ),
        encoding="utf-8",
    )
    os.chmod(inventory, 0o600)
    return _prove_instance_state_quiescence(
        channel=channel,
        host_global_root=host_global_root,
        inventory_path=inventory,
    )


def _durable_test_quiescence_proof(
    tmp_path: Path, channel: str
) -> DeploymentQuiescenceProof:
    root = tmp_path / f"{channel}-proof"
    root.mkdir(mode=0o700)
    lease_path = root / "deployment-host-global-lease.json"
    nonce = f"{channel}-test-nonce"
    inventory_digest = hashlib.sha256(channel.encode()).hexdigest()
    lease_path.write_text(
        json.dumps(
            {
                "schema": "agentic-pkm.host-deployment-lease.v2",
                "channel_id": channel,
                "nonce": nonce,
                "phase": "proved",
                "inventory_digest": inventory_digest,
                "all_consumers_stopped": True,
            }
        ),
        encoding="utf-8",
    )
    os.chmod(lease_path, 0o600)
    return DeploymentQuiescenceProof(
        channel_id=channel,
        nonce=nonce,
        inventory_digest=inventory_digest,
        lease_path=lease_path,
    )


def _canonical_test_quiescence_authority(
    *,
    layout: InstanceStateLayout,
    host_global_root: Path,
    legacy_path: Path,
    owners: list[dict[str, str]],
) -> tuple[DeploymentQuiescenceProof, Path]:
    layout.root.parent.mkdir(parents=True, exist_ok=True)
    host_global_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(host_global_root, 0o700)
    _begin_instance_state_deployment(
        channel=layout.channel_id,
        instance_state_root=layout.root.parent,
        host_global_root=host_global_root,
        legacy_path=legacy_path,
        controller_pid=os.getpid(),
        controller_start_token="linux:" + "0" * 64,
    )
    proof = _prove_empty_quiescence(
        channel=layout.channel_id,
        host_global_root=host_global_root,
    )
    owner_inventory = host_global_root / "legacy-owner-inventory.json"
    owner_inventory.write_text(
        json.dumps(_legacy_owner_inventory_payload(owners)),
        encoding="utf-8",
    )
    os.chmod(owner_inventory, 0o600)
    return (
        _bind_legacy_owner_inventory_to_proof(
            inventory_path=owner_inventory,
            quiescence_proof=proof,
            channel=layout.channel_id,
            host_global_root=host_global_root,
        ),
        owner_inventory,
    )


def _current_registry_owners(
    runtime: InstanceRegistryRuntime,
) -> list[dict[str, str]]:
    return [
        {
            "channel_id": runtime.layout.channel_id,
            "vault_binding_id": binding_id,
            "root": registration.path,
        }
        for binding_id, registration in runtime.registry.load().registrations.items()
    ]


def _create_canonical_backup(
    *,
    runtime: InstanceRegistryRuntime,
    backup_root: Path,
    legacy_path: Path,
) -> tuple[DeploymentQuiescenceProof, Path]:
    proof, owner_receipt = _canonical_test_quiescence_authority(
        layout=runtime.layout,
        host_global_root=runtime.ledger.root,
        legacy_path=legacy_path,
        owners=_current_registry_owners(runtime),
    )
    InstanceStateBackup(runtime.layout, runtime.ledger).create(
        backup_root,
        quiescence_proof=proof,
        owner_receipt_path=owner_receipt,
    )
    return proof, owner_receipt


def _refresh_backup_checksums(backup_root: Path) -> None:
    manifest_path = backup_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["checksums"] = {
        name: hashlib.sha256((backup_root / name).read_bytes()).hexdigest()
        for name in manifest["checksums"]
    }
    manifest["registry_checksum"] = manifest["checksums"]["vault-registry.md"]
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    os.chmod(manifest_path, 0o600)


def _clear_test_deployment_authority(
    *, layout: InstanceStateLayout, host_global_root: Path
) -> None:
    for path in (
        host_global_root / "deployment-host-global-lease.json",
        host_global_root / "deployment-quiescence-inventory.json",
        host_global_root / "deployment-quiescence-proof.json",
        host_global_root / "legacy-owner-inventory.json",
        _deployment_fence_path(host_global_root, layout.channel_id),
        host_global_root
        / "deployment-public"
        / "scalar-rollback-startup-fence.json",
    ):
        path.unlink(missing_ok=True)


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
    store.register(
        VaultRegistration("binding-a", "path:/a", "/a"),
        _capability=STORAGE_MUTATION_CAPABILITY,
    )

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
            host_global_root=tmp_path / "host-global",
            owner_receipt_path=tmp_path / "host-global" / "legacy-owner-inventory.json",
        )
    proof, owner_receipt = _canonical_test_quiescence_authority(
        layout=layout,
        host_global_root=tmp_path / "host-global",
        legacy_path=legacy.path,
        owners=[],
    )
    final = exporter.export_final_after_stop(
        legacy.path,
        quiescence_proof=proof,
        host_global_root=tmp_path / "host-global",
        owner_receipt_path=owner_receipt,
    )
    assert final.fingerprint != diagnostic.fingerprint

    legacy.upsert_known_vault(KnownVaultRef("racing", str(tmp_path / "racing")))
    with pytest.raises(InstanceStatePreflightError, match="changed after final export"):
        exporter.import_final_export(
            final,
            quiescence_proof=proof,
            host_global_root=tmp_path / "host-global",
            owner_receipt_path=owner_receipt,
        )

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


def test_diagnostic_export_cannot_be_imported_as_final_authority_without_mutation(
    tmp_path,
) -> None:
    layout = InstanceStateLayout.for_channel(tmp_path / "instance-state", "prod")
    legacy = AppLocalSettingsStore(tmp_path / "legacy" / "app-local.md")
    legacy.upsert_known_vault(KnownVaultRef("path:one", str(tmp_path / "one")))
    exporter = LegacyRegistryFinalExport(layout)
    diagnostic = exporter.capture_diagnostic_snapshot(legacy.path)
    before = {
        path.relative_to(tmp_path): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }

    with pytest.raises(InstanceStatePreflightError, match="final export authority"):
        exporter.import_final_export(diagnostic)

    assert {
        path.relative_to(tmp_path): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    } == before


def test_final_import_rejects_copied_quiescence_authority_without_mutation(
    tmp_path,
) -> None:
    layout = InstanceStateLayout.for_channel(tmp_path / "instance-state", "prod")
    legacy = AppLocalSettingsStore(tmp_path / "legacy" / "app-local.md")
    legacy.upsert_known_vault(KnownVaultRef("path:one", str(tmp_path / "one")))
    proof, owner_receipt = _canonical_test_quiescence_authority(
        layout=layout,
        host_global_root=tmp_path / "host-global",
        legacy_path=legacy.path,
        owners=[],
    )
    exporter = LegacyRegistryFinalExport(layout)
    final_export = exporter.export_final_after_stop(
        legacy.path,
        quiescence_proof=proof,
        host_global_root=tmp_path / "host-global",
        owner_receipt_path=owner_receipt,
    )
    copied_root = tmp_path / "copied-authority"
    copied_root.mkdir(mode=0o700)
    copied_lease = copied_root / "deployment-host-global-lease.json"
    assert proof.lease_path is not None
    copied_lease.write_bytes(proof.lease_path.read_bytes())
    os.chmod(copied_lease, 0o600)
    copied_proof = replace(proof, lease_path=copied_lease)
    protected_roots = (layout.root, tmp_path / "host-global")
    before = {
        path.relative_to(tmp_path): path.read_bytes()
        for protected_root in protected_roots
        for path in protected_root.rglob("*")
        if path.is_file()
    }

    with pytest.raises(InstanceStatePreflightError, match="canonical quiescence authority"):
        exporter.import_final_export(
            final_export,
            quiescence_proof=copied_proof,
            host_global_root=tmp_path / "host-global",
            owner_receipt_path=owner_receipt,
        )

    assert {
        path.relative_to(tmp_path): path.read_bytes()
        for protected_root in protected_roots
        for path in protected_root.rglob("*")
        if path.is_file()
    } == before


@pytest.mark.parametrize("operation", ["import", "preserve"])
def test_final_import_rejects_rewritten_final_export_without_mutation(
    tmp_path, operation: str
) -> None:
    layout = InstanceStateLayout.for_channel(tmp_path / "instance-state", "prod")
    layout.ensure()
    registry = VaultRegistryStore(layout.registry_path)
    registry.load()
    host_global_root = tmp_path / "host-global"
    ledger = InstanceRegistryRuntime.for_paths(
        layout,
        host_global_root,
    ).ledger
    ledger.load()
    legacy = AppLocalSettingsStore(tmp_path / "legacy" / "app-local.md")
    legacy.upsert_known_vault(KnownVaultRef("path:one", str(tmp_path / "one")))
    replacement = AppLocalSettingsStore(tmp_path / "replacement" / "app-local.md")
    replacement.upsert_known_vault(
        KnownVaultRef("path:forged", str(tmp_path / "forged"))
    )
    proof, owner_receipt = _canonical_test_quiescence_authority(
        layout=layout,
        host_global_root=host_global_root,
        legacy_path=legacy.path,
        owners=[],
    )
    exporter = LegacyRegistryFinalExport(layout)
    with pytest.raises(InstanceStatePreflightError, match="canonical quiescence authority"):
        exporter.export_final_after_stop(
            replacement.path,
            quiescence_proof=proof,
            host_global_root=host_global_root,
            owner_receipt_path=owner_receipt,
        )
    final_export = exporter.export_final_after_stop(
        legacy.path,
        quiescence_proof=proof,
        host_global_root=host_global_root,
        owner_receipt_path=owner_receipt,
    )
    replacement_payload = replacement.path.read_bytes()
    rewritten = replace(
        final_export,
        source_path=replacement.path.resolve(),
        payload=replacement_payload,
        fingerprint=hashlib.sha256(replacement_payload).hexdigest(),
    )
    payload_rewritten = replace(
        final_export,
        payload=replacement_payload,
        fingerprint=hashlib.sha256(replacement_payload).hexdigest(),
    )
    revision_before = registry.load().revision
    generation_before = ledger.load().generation
    scalar_before = legacy.path.read_bytes()
    before = {
        path.relative_to(tmp_path): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }

    for candidate, diagnostic in (
        (rewritten, "canonical quiescence authority"),
        (payload_rewritten, "final export binding"),
    ):
        mutation = (
            exporter.import_final_export
            if operation == "import"
            else exporter.preserve_final_export
        )
        with pytest.raises(InstanceStatePreflightError, match=diagnostic):
            mutation(
                candidate,
                quiescence_proof=proof,
                host_global_root=host_global_root,
                owner_receipt_path=owner_receipt,
            )

    assert {
        path.relative_to(tmp_path): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    } == before
    assert registry.load().revision == revision_before
    assert ledger.load().generation == generation_before
    assert legacy.path.read_bytes() == scalar_before
    assert not ledger.rotation_path.exists()


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
    with pytest.raises(RegistryError, match="host-global deployment lease"):
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
        quiescence_proof=_prove_empty_quiescence(
            channel="test", host_global_root=host_global_root
        ),
    )

    assert receipt["final_fingerprint"] != diagnostic["diagnostic_fingerprint"]
    assert receipt["restart_fence_cleared"] is True
    assert not fence.exists()
    assert not (
        host_global_root
        / "deployment-public"
        / "scalar-rollback-startup-fence.json"
    ).exists()
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
            quiescence_proof=_prove_empty_quiescence(
                channel="prod", host_global_root=host_global_root
            ),
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
            quiescence_proof=_prove_empty_quiescence(
                channel="prod", host_global_root=host_global_root
            ),
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
    _create_canonical_backup(
        runtime=runtime,
        backup_root=tmp_path / "backup",
        legacy_path=tmp_path / "missing-legacy.md",
    )
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
    assert any(
        isinstance(mount, dict)
        and mount.get("target") == "/app/instance-ownership"
        for mount in init["volumes"]
    )
    for consumer in receipt.consumers:
        service = compose["services"][consumer]
        assert "instance-state:/app/instance-state" in service["volumes"]
        assert any(
            isinstance(mount, dict)
            and mount.get("target") == "/app/instance-ownership"
            for mount in service["volumes"]
        )
        assert "app.instance.runtime preflight" in service["command"][2]
        assert "INSTANCE_STATE_LEGACY_ROLLBACK" in service["command"][2]
        assert f"--consumer {consumer}" in service["command"][2]
        assert service["depends_on"]["instance-state-init"]["condition"] == "service_completed_successfully"


def test_runtime_preflight_rejects_foreign_channel_host_global_lease_without_mutation(
    tmp_path,
) -> None:
    host_global_root = tmp_path / "host-global"
    prod_state_root = tmp_path / "prod-state"
    prod_layout = InstanceStateLayout.for_channel(prod_state_root, "prod")
    prod_runtime = InstanceRegistryRuntime.for_paths(prod_layout, host_global_root)
    prod_vault = tmp_path / "prod-vault"
    prod_vault.mkdir()
    prod_runtime.bootstrap_env_binding(
        vault_root=prod_vault,
        watcher_vault_path=prod_vault,
    )
    prod_runtime.ledger.bootstrap_legacy_owners(
        [], inventory_complete=True, writers_drained=True,
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    dev_state_root = tmp_path / "dev-state"
    dev_state_root.mkdir()
    _begin_instance_state_deployment(
        channel="dev",
        instance_state_root=dev_state_root,
        host_global_root=host_global_root,
        legacy_path=tmp_path / "legacy.md",
        controller_pid=os.getpid(),
        controller_start_token="linux:" + "0" * 64,
    )
    protected_paths = tuple(
        path
        for path in (
            prod_layout.registry_path,
            prod_runtime.ledger.key_path,
            prod_runtime.ledger.path,
            host_global_root / "deployment-host-global-lease.json",
            _deployment_fence_path(host_global_root, "dev"),
        )
        if path.exists()
    )
    before = {path: path.read_bytes() for path in protected_paths}

    with pytest.raises(RegistryError, match="host-global deployment lease"):
        _preflight_runtime(
            channel="prod",
            instance_state_root=prod_state_root,
            host_global_root=host_global_root,
            consumer="worker",
        )

    assert {path: path.read_bytes() for path in protected_paths} == before
    (host_global_root / "deployment-host-global-lease.json").unlink()
    _deployment_fence_path(host_global_root, "dev").unlink()
    assert (
        _preflight_runtime(
            channel="prod",
            instance_state_root=prod_state_root,
            host_global_root=host_global_root,
            consumer="worker",
        )
        == 0
    )


def test_previous_image_without_runtime_preflight_module_uses_only_explicit_safe_rollback(
    tmp_path,
) -> None:
    compose = _load_compose(REPO_ROOT / "docker-compose.yaml")
    command = compose["services"]["api"]["command"][2]
    ownership = tmp_path / "ownership"
    runtime_tmp = tmp_path / "runtime-tmp"
    ownership.mkdir()
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_python = fake_bin / "python"
    fake_python.write_text(
        "#!/usr/bin/env bash\n"
        "if [ \"${1:-}\" = -c ]; then exit 1; fi\n"
        "exit 91\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)
    executable = command.replace("$$", "$").replace("/app/tmp", str(runtime_tmp)).replace(
        "/app/instance-ownership", str(ownership)
    ).replace("exec bash /app/scripts/start_api.sh", "printf rollback-started")
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "PKM_ENVIRONMENT": "prod",
        "INSTANCE_STATE_LEGACY_ROLLBACK": "1",
    }

    ordinary_start = subprocess.run(
        ["/bin/bash", "-c", executable],
        env={**env, "INSTANCE_STATE_LEGACY_ROLLBACK": "0"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert ordinary_start.returncode != 0
    assert "unavailable outside an explicit rollback" in ordinary_start.stderr

    safe = subprocess.run(
        ["/bin/bash", "-c", executable],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert safe.returncode == 0, safe.stderr
    assert safe.stdout == "rollback-started"

    for blocked_name in (
        "deployment-host-global-lease.json",
        "deployment-dev-restart-fence.json",
    ):
        blocked_path = ownership / blocked_name
        blocked_path.write_text("{}", encoding="utf-8")
        blocked = subprocess.run(
            ["/bin/bash", "-c", executable],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert blocked.returncode != 0
        assert blocked.stdout == ""
        blocked_path.unlink()


def test_host_global_bind_source_resolves_identically_across_checkouts_and_channels(
    tmp_path,
) -> None:
    resolver = REPO_ROOT / "scripts/lib/instance_ownership_host_state.sh"
    assert resolver.is_file()
    home = tmp_path / "home"
    home.mkdir()
    resolved = []
    for checkout in (tmp_path / "checkout-a", tmp_path / "checkout-b"):
        checkout.mkdir()
        result = subprocess.run(
            [
                "/bin/bash",
                "-c",
                f"source '{resolver}'; prepare_instance_ownership_host_state_dir; printf %s \"$INSTANCE_OWNERSHIP_HOST_STATE_DIR\"",
            ],
            cwd=checkout,
            env={**os.environ, "HOME": str(home), "XDG_STATE_HOME": ""},
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        resolved.append(result.stdout)
    assert resolved == [
        str(home / ".local/state/agentic-pkm/instance-ownership"),
        str(home / ".local/state/agentic-pkm/instance-ownership"),
    ]
    relative = subprocess.run(
        [
            "/bin/bash",
            "-c",
            f"source '{resolver}'; resolve_instance_ownership_host_state_dir",
        ],
        env={**os.environ, "INSTANCE_OWNERSHIP_HOST_STATE_DIR": "relative/state"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert relative.returncode == 64
    assert "must be an absolute host path" in relative.stderr
    for launcher in (
        "scripts/deploy_channel.sh",
        "scripts/start_full_system.sh",
        "scripts/cold_boot.sh",
        "scripts/dev_bootstrap.sh",
        "scripts/run_alpha_stack.sh",
        "scripts/verify_runtime_chain.sh",
    ):
        assert "prepare_instance_ownership_host_state_dir" in (
            REPO_ROOT / launcher
        ).read_text(encoding="utf-8")
    shared_root = Path(resolved[0])
    assert shared_root.stat().st_mode & 0o777 == 0o700
    dev_runtime = InstanceRegistryRuntime.for_paths(
        InstanceStateLayout.for_channel(tmp_path / "dev-state", "dev"), shared_root
    )
    prod_runtime = InstanceRegistryRuntime.for_paths(
        InstanceStateLayout.for_channel(tmp_path / "prod-state", "prod"), shared_root
    )
    dev_vault = tmp_path / "vault"
    prod_overlap = dev_vault / "nested"
    prod_overlap.mkdir(parents=True)
    dev_runtime.bootstrap_env_binding(
        vault_root=dev_vault, watcher_vault_path=dev_vault
    )
    with pytest.raises(LedgerCollisionError):
        prod_runtime.bootstrap_env_binding(
            vault_root=prod_overlap, watcher_vault_path=prod_overlap
        )

    compose = _load_compose(REPO_ROOT / "docker-compose.yaml")
    for service_name in (
        "instance-state-init",
        "api",
        "worker",
        "watcher",
        "heimdal-capture-watch",
    ):
        ownership_mounts = [
            mount
            for mount in compose["services"][service_name]["volumes"]
            if isinstance(mount, dict) and mount.get("target") == "/app/instance-ownership"
        ]
        assert ownership_mounts == [
            {
                "type": "bind",
                "source": "${INSTANCE_OWNERSHIP_HOST_STATE_DIR:?absolute host-global state directory must be resolved by the launcher}",
                "target": "/app/instance-ownership",
                "bind": {"create_host_path": False},
            }
        ]


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


def test_backup_create_requires_canonical_quiescence_authority(tmp_path) -> None:
    layout = InstanceStateLayout.for_channel(tmp_path / "prod-state", "prod")
    runtime = InstanceRegistryRuntime.for_paths(layout, tmp_path / "host-global")
    root = tmp_path / "vault"
    root.mkdir()
    runtime.bootstrap_env_binding(vault_root=root, watcher_vault_path=root)
    proof, owner_receipt = _canonical_test_quiescence_authority(
        layout=layout,
        host_global_root=runtime.ledger.root,
        legacy_path=tmp_path / "missing-legacy.md",
        owners=_current_registry_owners(runtime),
    )

    for name, candidate, receipt in (
        ("missing", None, owner_receipt),
        ("noncanonical", _durable_test_quiescence_proof(tmp_path, "prod"), None),
    ):
        backup_root = tmp_path / f"{name}-backup"
        with pytest.raises(
            InstanceStatePreflightError,
            match="canonical quiescence authority",
        ):
            InstanceStateBackup(layout, runtime.ledger).create(
                backup_root,
                quiescence_proof=candidate,
                owner_receipt_path=receipt,
            )
        assert not backup_root.exists()

    receipt = InstanceStateBackup(layout, runtime.ledger).create(
        tmp_path / "canonical-backup",
        quiescence_proof=proof,
        owner_receipt_path=owner_receipt,
    )
    assert receipt.manifest_path.is_file()


def test_backup_resolves_foreign_binding_ids_omitted_by_owner_producer(tmp_path) -> None:
    layout = InstanceStateLayout.for_channel(tmp_path / "prod-state", "prod")
    runtime = InstanceRegistryRuntime.for_paths(layout, tmp_path / "host-global")
    prod_root = tmp_path / "prod-vault"
    foreign_root = tmp_path / "dev-vault"
    prod_root.mkdir()
    foreign_root.mkdir()
    runtime.bootstrap_env_binding(
        vault_root=prod_root,
        watcher_vault_path=prod_root,
    )
    foreign_binding = "binding-foreign-nonlegacy"
    runtime.ledger.reserve(
        channel_id="dev",
        vault_binding_id=foreign_binding,
        root=foreign_root,
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    runtime.ledger.activate(
        foreign_binding,
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    proof, owner_receipt = _canonical_test_quiescence_authority(
        layout=layout,
        host_global_root=runtime.ledger.root,
        legacy_path=tmp_path / "missing-legacy.md",
        owners=[
            {"channel_id": "prod", "root": str(prod_root)},
            {"channel_id": "dev", "root": str(foreign_root)},
        ],
    )

    receipt = InstanceStateBackup(layout, runtime.ledger).create(
        tmp_path / "backup",
        quiescence_proof=proof,
        owner_receipt_path=owner_receipt,
    )

    assert receipt.manifest_path.is_file()
    backup_ledger = json.loads(
        (receipt.manifest_path.parent / "ownership-ledger.json").read_text(
            encoding="utf-8"
        )
    )
    assert foreign_binding in backup_ledger["leases"]


def test_restore_derives_key_identity_for_existing_v1_manifest(tmp_path) -> None:
    layout = InstanceStateLayout.for_channel(tmp_path / "prod-state", "prod")
    runtime = InstanceRegistryRuntime.for_paths(layout, tmp_path / "host-global")
    root = tmp_path / "vault"
    root.mkdir()
    runtime.bootstrap_env_binding(vault_root=root, watcher_vault_path=root)
    backup_root = tmp_path / "backup"
    proof, owner_receipt = _create_canonical_backup(
        runtime=runtime,
        backup_root=backup_root,
        legacy_path=tmp_path / "missing-legacy.md",
    )
    manifest_path = backup_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema"] == "agentic-pkm.instance-state-backup.v1"
    expected_key_id = manifest.pop("ownership_key_id")
    expected_generation = manifest.pop("ownership_generation")
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    receipt = InstanceStateBackup(layout, runtime.ledger).restore(
        backup_root,
        quiescence_proof=proof,
        owner_receipt_path=owner_receipt,
    )

    assert receipt.ownership_key_id == expected_key_id
    assert receipt.ownership_generation == expected_generation


@pytest.mark.parametrize("omitted_field", ("ownership_key_id", "ownership_generation"))
def test_restore_rejects_partial_key_identity_in_v1_manifest(
    tmp_path,
    omitted_field,
) -> None:
    layout = InstanceStateLayout.for_channel(tmp_path / "prod-state", "prod")
    runtime = InstanceRegistryRuntime.for_paths(layout, tmp_path / "host-global")
    root = tmp_path / "vault"
    root.mkdir()
    runtime.bootstrap_env_binding(vault_root=root, watcher_vault_path=root)
    backup_root = tmp_path / "backup"
    proof, owner_receipt = _create_canonical_backup(
        runtime=runtime,
        backup_root=backup_root,
        legacy_path=tmp_path / "missing-legacy.md",
    )
    manifest_path = backup_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.pop(omitted_field)
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        InstanceStatePreflightError,
        match="backup key identity is inconsistent",
    ):
        InstanceStateBackup(layout, runtime.ledger).restore(
            backup_root,
            quiescence_proof=proof,
            owner_receipt_path=owner_receipt,
        )


@pytest.mark.parametrize("writer_kind", ("key-rotation", "registry-mutation"))
def test_backup_capture_blocks_concurrent_writer_until_generation_is_captured(
    tmp_path,
    monkeypatch,
    writer_kind,
) -> None:
    layout = InstanceStateLayout.for_channel(tmp_path / "prod-state", "prod")
    runtime = InstanceRegistryRuntime.for_paths(layout, tmp_path / "host-global")
    root = tmp_path / "vault"
    root.mkdir()
    runtime.bootstrap_env_binding(vault_root=root, watcher_vault_path=root)
    proof, owner_receipt = _canonical_test_quiescence_authority(
        layout=layout,
        host_global_root=runtime.ledger.root,
        legacy_path=tmp_path / "missing-legacy.md",
        owners=_current_registry_owners(runtime),
    )
    initial = runtime.ledger.require_existing()
    initial_registry = runtime.registry.load()
    second_root = tmp_path / "second-vault"
    second_root.mkdir()
    second_binding = "binding-concurrent-mutation"
    backup_root = tmp_path / "backup"
    capture_reached = threading.Event()
    allow_capture = threading.Event()
    writer_started = threading.Event()
    writer_done = threading.Event()
    backup_errors: list[BaseException] = []
    writer_errors: list[BaseException] = []
    original_read_bytes = Path.read_bytes
    capture_path = (
        runtime.ledger.path
        if writer_kind == "key-rotation"
        else runtime.layout.registry_path
    )

    def pause_first_generation_capture(path: Path) -> bytes:
        if path == capture_path and not capture_reached.is_set():
            capture_reached.set()
            if not allow_capture.wait(timeout=5):
                raise AssertionError("timed out waiting to release backup capture")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", pause_first_generation_capture)

    def create_backup() -> None:
        try:
            InstanceStateBackup(layout, runtime.ledger).create(
                backup_root,
                quiescence_proof=proof,
                owner_receipt_path=owner_receipt,
            )
        except BaseException as exc:
            backup_errors.append(exc)

    def mutate_state() -> None:
        writer_started.set()
        try:
            if writer_kind == "key-rotation":
                runtime.rotate_ledger_key(
                    quiescence_proof=proof,
                    legacy_owner_inventory_path=owner_receipt,
                )
            else:
                runtime.registry.register(
                    VaultRegistration(
                        vault_binding_id=second_binding,
                        ref=f"path:{second_root}",
                        path=str(second_root.resolve()),
                    ),
                    expected_revision=initial_registry.revision,
                    _capability=STORAGE_MUTATION_CAPABILITY,
                )
        except BaseException as exc:
            writer_errors.append(exc)
        finally:
            writer_done.set()

    backup_thread = threading.Thread(target=create_backup)
    writer_thread = threading.Thread(target=mutate_state)
    backup_thread.start()
    assert capture_reached.wait(timeout=5)
    writer_thread.start()
    assert writer_started.wait(timeout=5)
    writer_blocked = not writer_done.wait(timeout=1)
    allow_capture.set()
    backup_thread.join(timeout=5)
    writer_thread.join(timeout=5)

    assert writer_blocked
    assert not backup_thread.is_alive()
    assert not writer_thread.is_alive()
    assert backup_errors == []
    assert writer_errors == []
    if writer_kind == "key-rotation":
        manifest = json.loads((backup_root / "manifest.json").read_text(encoding="utf-8"))
        backup_key = json.loads(
            (backup_root / "ownership-key.json").read_text(encoding="utf-8")
        )
        backup_ledger = json.loads(
            (backup_root / "ownership-ledger.json").read_text(encoding="utf-8")
        )
        assert manifest["ownership_key_id"] == initial.key_id == backup_key["key_id"]
        assert (
            manifest["ownership_generation"]
            == initial.generation
            == backup_key["generation"]
        )
        assert backup_ledger["key_id"] == initial.key_id
        assert backup_ledger["generation"] == initial.generation
    else:
        backup_registry = VaultRegistryStore(backup_root / "vault-registry.md").load()
        assert second_binding not in backup_registry.registrations
        assert second_binding in runtime.registry.load().registrations


def test_backup_rejects_registry_ledger_divergence_bidirectionally(tmp_path) -> None:
    for divergence in ("registration-without-lease", "lease-without-registration"):
        case_root = tmp_path / divergence
        layout = InstanceStateLayout.for_channel(case_root / "prod-state", "prod")
        runtime = InstanceRegistryRuntime.for_paths(layout, case_root / "host-global")
        root = case_root / "vault"
        root.mkdir(parents=True)
        runtime.bootstrap_env_binding(vault_root=root, watcher_vault_path=root)
        second_root = case_root / "second-vault"
        second_root.mkdir()
        second_binding = f"binding-{divergence}"
        if divergence == "registration-without-lease":
            current = runtime.registry.load()
            runtime.registry.register(
                VaultRegistration(
                    vault_binding_id=second_binding,
                    ref=f"path:{second_root}",
                    path=str(second_root.resolve()),
                ),
                expected_revision=current.revision,
                _capability=STORAGE_MUTATION_CAPABILITY,
            )
        else:
            runtime.ledger.reserve(
                channel_id="prod",
                vault_binding_id=second_binding,
                root=second_root,
                _capability=STORAGE_MUTATION_CAPABILITY,
            )
            runtime.ledger.activate(
                second_binding,
                _capability=STORAGE_MUTATION_CAPABILITY,
            )
        proof, owner_receipt = _canonical_test_quiescence_authority(
            layout=layout,
            host_global_root=runtime.ledger.root,
            legacy_path=case_root / "missing-legacy.md",
            owners=_current_registry_owners(runtime),
        )
        rejected_backup = case_root / "rejected-backup"
        with pytest.raises(
            InstanceStatePreflightError,
            match="registry/ledger consistency",
        ):
            InstanceStateBackup(layout, runtime.ledger).create(
                rejected_backup,
                quiescence_proof=proof,
                owner_receipt_path=owner_receipt,
            )
        assert not rejected_backup.exists()

        valid_root = case_root / "valid"
        valid_layout = InstanceStateLayout.for_channel(
            valid_root / "prod-state",
            "prod",
        )
        valid_runtime = InstanceRegistryRuntime.for_paths(
            valid_layout,
            valid_root / "host-global",
        )
        valid_vault = valid_root / "vault"
        valid_vault.mkdir(parents=True)
        valid_runtime.bootstrap_env_binding(
            vault_root=valid_vault,
            watcher_vault_path=valid_vault,
        )
        backup_root = valid_root / "backup"
        valid_proof, valid_owner_receipt = _create_canonical_backup(
            runtime=valid_runtime,
            backup_root=backup_root,
            legacy_path=valid_root / "missing-legacy.md",
        )
        tampered_root = valid_root / "tampered-vault"
        tampered_root.mkdir()
        if divergence == "registration-without-lease":
            backup_registry = VaultRegistryStore(backup_root / "vault-registry.md")
            backup_snapshot = backup_registry.load()
            backup_registry.register(
                VaultRegistration(
                    vault_binding_id=second_binding,
                    ref=f"path:{tampered_root}",
                    path=str(tampered_root.resolve()),
                ),
                expected_revision=backup_snapshot.revision,
                _capability=STORAGE_MUTATION_CAPABILITY,
            )
        else:
            backup_ledger = InstanceRegistryRuntime.for_paths(
                InstanceStateLayout.for_channel(
                    backup_root / "scratch-state",
                    "prod",
                ),
                backup_root,
            ).ledger
            backup_ledger.reserve(
                channel_id="prod",
                vault_binding_id=second_binding,
                root=tampered_root,
                _capability=STORAGE_MUTATION_CAPABILITY,
            )
            backup_ledger.activate(
                second_binding,
                _capability=STORAGE_MUTATION_CAPABILITY,
            )
        _refresh_backup_checksums(backup_root)
        protected_roots = (valid_layout.root, valid_runtime.ledger.root)
        before = {
            path.relative_to(valid_root): path.read_bytes()
            for protected_root in protected_roots
            for path in protected_root.rglob("*")
            if path.is_file()
        }

        with pytest.raises(
            InstanceStatePreflightError,
            match="registry/ledger consistency",
        ):
            InstanceStateBackup(valid_layout, valid_runtime.ledger).restore(
                backup_root,
                quiescence_proof=valid_proof,
                owner_receipt_path=valid_owner_receipt,
            )

        assert {
            path.relative_to(valid_root): path.read_bytes()
            for protected_root in protected_roots
            for path in protected_root.rglob("*")
            if path.is_file()
        } == before

    for divergence in (
        "cross-channel-corrupt-live",
        "cross-channel-orphan-live",
        "cross-channel-wrong-binding",
        "cross-channel-corrupt-tombstone",
        "cross-channel-corrupt-lineage",
        "cross-channel-self-lineage",
        "cross-channel-blank-lineage-id",
        "cross-channel-nonstring-lineage-id",
    ):
        case_root = tmp_path / divergence
        layout = InstanceStateLayout.for_channel(case_root / "prod-state", "prod")
        runtime = InstanceRegistryRuntime.for_paths(layout, case_root / "host-global")
        prod_root = case_root / "prod-vault"
        foreign_root = case_root / "foreign-vault"
        prod_root.mkdir(parents=True)
        foreign_root.mkdir()
        runtime.bootstrap_env_binding(
            vault_root=prod_root,
            watcher_vault_path=prod_root,
        )
        foreign_binding = f"binding-{divergence}"
        runtime.ledger.reserve(
            channel_id="dev",
            vault_binding_id=foreign_binding,
            root=foreign_root,
            _capability=STORAGE_MUTATION_CAPABILITY,
        )
        runtime.ledger.activate(
            foreign_binding,
            _capability=STORAGE_MUTATION_CAPABILITY,
        )
        live_channel = "dev"
        live_binding = foreign_binding
        if divergence.endswith("tombstone") or "lineage" in divergence:
            destination_binding = f"destination-{divergence}"
            runtime.ledger.begin_transfer(
                source_binding_id=foreign_binding,
                destination_channel_id="test",
                destination_binding_id=destination_binding,
                _capability=STORAGE_MUTATION_CAPABILITY,
            )
            runtime.ledger.activate_transfer(
                _capability=STORAGE_MUTATION_CAPABILITY,
            )
            live_channel = "test"
            live_binding = destination_binding
        if divergence == "cross-channel-self-lineage":
            final_binding = f"final-{divergence}"
            runtime.ledger.begin_transfer(
                source_binding_id=destination_binding,
                destination_channel_id="native",
                destination_binding_id=final_binding,
                _capability=STORAGE_MUTATION_CAPABILITY,
            )
            runtime.ledger.activate_transfer(
                _capability=STORAGE_MUTATION_CAPABILITY,
            )
            live_channel = "native"
            live_binding = final_binding

        complete_owners = _current_registry_owners(runtime) + [
            {
                "channel_id": live_channel,
                "vault_binding_id": live_binding,
                "root": str(foreign_root.resolve()),
            }
        ]
        if divergence == "cross-channel-orphan-live":
            authority_owners = _current_registry_owners(runtime)
        elif divergence == "cross-channel-wrong-binding":
            authority_owners = [
                *complete_owners[:-1],
                complete_owners[-1]
                | {"vault_binding_id": f"wrong-{live_binding}"},
            ]
        else:
            authority_owners = complete_owners
        proof, owner_receipt = _canonical_test_quiescence_authority(
            layout=layout,
            host_global_root=runtime.ledger.root,
            legacy_path=case_root / "missing-legacy.md",
            owners=authority_owners,
        )
        ledger_payload = json.loads(
            runtime.ledger.path.read_text(encoding="utf-8")
        )
        if divergence == "cross-channel-corrupt-live":
            ledger_payload["leases"][foreign_binding]["root_fingerprint"] = "0" * 64
        elif divergence == "cross-channel-corrupt-tombstone":
            ledger_payload["tombstones"][foreign_binding]["root_fingerprint"] = "0" * 64
        elif divergence == "cross-channel-corrupt-lineage":
            ledger_payload["transfer_lineage"][0]["root_fingerprint"] = "0" * 64
        elif divergence == "cross-channel-self-lineage":
            ledger_payload["transfer_lineage"][0] |= {
                "source_channel_id": "test",
                "source_binding_id": destination_binding,
                "destination_channel_id": "test",
                "destination_binding_id": destination_binding,
            }
        elif divergence == "cross-channel-blank-lineage-id":
            ledger_payload["transfer_lineage"][0]["transfer_id"] = "   "
        elif divergence == "cross-channel-nonstring-lineage-id":
            ledger_payload["transfer_lineage"][0]["transfer_id"] = 7
        runtime.ledger.path.write_text(
            json.dumps(ledger_payload),
            encoding="utf-8",
        )

        with pytest.raises(
            InstanceStatePreflightError,
            match="registry/ledger consistency",
        ):
            InstanceStateBackup(layout, runtime.ledger).create(
                case_root / "rejected-backup",
                quiescence_proof=proof,
                owner_receipt_path=owner_receipt,
            )
        assert not (case_root / "rejected-backup").exists()

        restore_root = tmp_path / f"{divergence}-restore"
        restore_layout = InstanceStateLayout.for_channel(
            restore_root / "prod-state",
            "prod",
        )
        restore_runtime = InstanceRegistryRuntime.for_paths(
            restore_layout,
            restore_root / "host-global",
        )
        restore_prod_root = restore_root / "prod-vault"
        restore_foreign_root = restore_root / "foreign-vault"
        restore_prod_root.mkdir(parents=True)
        restore_foreign_root.mkdir()
        restore_runtime.bootstrap_env_binding(
            vault_root=restore_prod_root,
            watcher_vault_path=restore_prod_root,
        )
        restore_foreign_binding = f"restore-{foreign_binding}"
        restore_runtime.ledger.reserve(
            channel_id="dev",
            vault_binding_id=restore_foreign_binding,
            root=restore_foreign_root,
            _capability=STORAGE_MUTATION_CAPABILITY,
        )
        restore_runtime.ledger.activate(
            restore_foreign_binding,
            _capability=STORAGE_MUTATION_CAPABILITY,
        )
        restore_live_channel = "dev"
        restore_live_binding = restore_foreign_binding
        if divergence.endswith("tombstone") or "lineage" in divergence:
            restore_destination = f"restore-destination-{divergence}"
            restore_runtime.ledger.begin_transfer(
                source_binding_id=restore_foreign_binding,
                destination_channel_id="test",
                destination_binding_id=restore_destination,
                _capability=STORAGE_MUTATION_CAPABILITY,
            )
            restore_runtime.ledger.activate_transfer(
                _capability=STORAGE_MUTATION_CAPABILITY,
            )
            restore_live_channel = "test"
            restore_live_binding = restore_destination
        if divergence == "cross-channel-self-lineage":
            restore_final = f"restore-final-{divergence}"
            restore_runtime.ledger.begin_transfer(
                source_binding_id=restore_destination,
                destination_channel_id="native",
                destination_binding_id=restore_final,
                _capability=STORAGE_MUTATION_CAPABILITY,
            )
            restore_runtime.ledger.activate_transfer(
                _capability=STORAGE_MUTATION_CAPABILITY,
            )
            restore_live_channel = "native"
            restore_live_binding = restore_final
        restore_complete_owners = _current_registry_owners(restore_runtime) + [
            {
                "channel_id": restore_live_channel,
                "vault_binding_id": restore_live_binding,
                "root": str(restore_foreign_root.resolve()),
            }
        ]
        backup_root = restore_root / "backup"
        restore_proof, restore_owner_receipt = _canonical_test_quiescence_authority(
            layout=restore_layout,
            host_global_root=restore_runtime.ledger.root,
            legacy_path=restore_root / "missing-legacy.md",
            owners=restore_complete_owners,
        )
        InstanceStateBackup(
            restore_layout,
            restore_runtime.ledger,
        ).create(
            backup_root,
            quiescence_proof=restore_proof,
            owner_receipt_path=restore_owner_receipt,
        )
        backup_ledger_payload = json.loads(
            (backup_root / "ownership-ledger.json").read_text(encoding="utf-8")
        )
        if divergence == "cross-channel-corrupt-live":
            backup_ledger_payload["leases"][restore_foreign_binding][
                "root_fingerprint"
            ] = "0" * 64
        elif divergence in {
            "cross-channel-orphan-live",
            "cross-channel-wrong-binding",
        }:
            _clear_test_deployment_authority(
                layout=restore_layout,
                host_global_root=restore_runtime.ledger.root,
            )
            restore_authority_owners = _current_registry_owners(restore_runtime)
            if divergence == "cross-channel-wrong-binding":
                restore_authority_owners += [
                    restore_complete_owners[-1]
                    | {"vault_binding_id": f"wrong-{restore_live_binding}"}
                ]
            restore_proof, restore_owner_receipt = _canonical_test_quiescence_authority(
                layout=restore_layout,
                host_global_root=restore_runtime.ledger.root,
                legacy_path=restore_root / "missing-legacy.md",
                owners=restore_authority_owners,
            )
        elif divergence == "cross-channel-corrupt-tombstone":
            backup_ledger_payload["tombstones"][restore_foreign_binding][
                "root_fingerprint"
            ] = "0" * 64
        elif divergence == "cross-channel-corrupt-lineage":
            backup_ledger_payload["transfer_lineage"][0][
                "root_fingerprint"
            ] = "0" * 64
        elif divergence == "cross-channel-self-lineage":
            backup_ledger_payload["transfer_lineage"][0] |= {
                "source_channel_id": "test",
                "source_binding_id": restore_destination,
                "destination_channel_id": "test",
                "destination_binding_id": restore_destination,
            }
        elif divergence == "cross-channel-blank-lineage-id":
            backup_ledger_payload["transfer_lineage"][0]["transfer_id"] = "   "
        elif divergence == "cross-channel-nonstring-lineage-id":
            backup_ledger_payload["transfer_lineage"][0]["transfer_id"] = 7
        (backup_root / "ownership-ledger.json").write_text(
            json.dumps(backup_ledger_payload),
            encoding="utf-8",
        )
        _refresh_backup_checksums(backup_root)
        before = {
            path.relative_to(restore_root): path.read_bytes()
            for protected_root in (restore_layout.root, restore_runtime.ledger.root)
            for path in protected_root.rglob("*")
            if path.is_file()
        }
        with pytest.raises(
            InstanceStatePreflightError,
            match="registry/ledger consistency",
        ):
            InstanceStateBackup(
                restore_layout,
                restore_runtime.ledger,
            ).restore(
                backup_root,
                quiescence_proof=restore_proof,
                owner_receipt_path=restore_owner_receipt,
            )
        assert {
            path.relative_to(restore_root): path.read_bytes()
            for protected_root in (restore_layout.root, restore_runtime.ledger.root)
            for path in protected_root.rglob("*")
            if path.is_file()
        } == before


@pytest.mark.parametrize("key_failure", ["missing", "mismatched"])
def test_prod_volume_loss_requires_fenced_rekey_and_ledger_reconstruction(
    tmp_path,
    key_failure,
) -> None:
    layout = InstanceStateLayout.for_channel(tmp_path / "prod-state", "prod")
    runtime = InstanceRegistryRuntime.for_paths(layout, tmp_path / "host-global")
    root = tmp_path / "vault"
    root.mkdir()
    runtime.bootstrap_env_binding(vault_root=root, watcher_vault_path=root)
    backup_root = tmp_path / "backup"
    proof, owner_receipt = _create_canonical_backup(
        runtime=runtime,
        backup_root=backup_root,
        legacy_path=tmp_path / "missing-legacy.md",
    )
    if key_failure == "missing":
        (backup_root / "ownership-key.json").unlink()
    else:
        foreign = InstanceRegistryRuntime.for_paths(
            InstanceStateLayout.for_channel(tmp_path / "foreign-state", "prod"),
            tmp_path / "foreign-host-global",
        )
        foreign.ledger.load()
        (backup_root / "ownership-key.json").write_bytes(
            foreign.ledger.key_path.read_bytes()
        )
        os.chmod(backup_root / "ownership-key.json", 0o600)
        _refresh_backup_checksums(backup_root)

    for path in layout.root.iterdir():
        if path.is_file():
            path.unlink()
    runtime.ledger.path.unlink()
    runtime.ledger.key_path.unlink()

    with pytest.raises(
        (InstanceStatePreflightError, LedgerError),
        match="re-key and ledger reconstruction",
    ):
        _finish_instance_state_deployment(
            channel="prod",
            instance_state_root=layout.root.parent,
            host_global_root=runtime.ledger.root,
            legacy_path=tmp_path / "missing-legacy.md",
            inventory_path=owner_receipt,
            backup_root=tmp_path / "new-backup",
            restore_root=backup_root,
            quiescence_proof=proof,
        )

    assert _deployment_fence_path(runtime.ledger.root, "prod").is_file()
    assert (runtime.ledger.root / "deployment-host-global-lease.json").is_file()
    assert not layout.registry_path.exists()
    assert not runtime.ledger.path.exists()
    assert not runtime.ledger.key_path.exists()
    with pytest.raises(RegistryError, match="host-global deployment lease"):
        _preflight_runtime(
            channel="prod",
            instance_state_root=layout.root.parent,
            host_global_root=runtime.ledger.root,
            consumer="api",
        )


def test_prod_volume_loss_restore_verifies_key_identity_before_api_or_worker_start(
    tmp_path,
) -> None:
    layout = InstanceStateLayout.for_channel(tmp_path / "prod-state", "prod")
    runtime = InstanceRegistryRuntime.for_paths(layout, tmp_path / "host-global")
    root = tmp_path / "vault"
    root.mkdir()
    runtime.bootstrap_env_binding(vault_root=root, watcher_vault_path=root)
    backup_root = tmp_path / "backup"
    proof, owner_receipt = _create_canonical_backup(
        runtime=runtime,
        backup_root=backup_root,
        legacy_path=tmp_path / "missing-legacy.md",
    )
    expected_key = json.loads(
        (backup_root / "ownership-key.json").read_text(encoding="utf-8")
    )
    foreign = InstanceRegistryRuntime.for_paths(
        InstanceStateLayout.for_channel(tmp_path / "foreign-state", "prod"),
        tmp_path / "foreign-host-global",
    )
    foreign.ledger.load()
    (backup_root / "ownership-key.json").write_bytes(foreign.ledger.key_path.read_bytes())
    os.chmod(backup_root / "ownership-key.json", 0o600)
    _refresh_backup_checksums(backup_root)
    protected_roots = (layout.root, runtime.ledger.root)
    before = {
        path.relative_to(tmp_path): path.read_bytes()
        for protected_root in protected_roots
        for path in protected_root.rglob("*")
        if path.is_file()
    }

    with pytest.raises(
        InstanceStatePreflightError,
        match="re-key and ledger reconstruction",
    ):
        InstanceStateBackup(layout, runtime.ledger).restore(
            backup_root,
            quiescence_proof=proof,
            owner_receipt_path=owner_receipt,
        )

    assert {
        path.relative_to(tmp_path): path.read_bytes()
        for protected_root in protected_roots
        for path in protected_root.rglob("*")
        if path.is_file()
    } == before
    deploy = (REPO_ROOT / "scripts/deploy_channel.sh").read_text(encoding="utf-8")
    start = (REPO_ROOT / "scripts/start_full_system.sh").read_text(encoding="utf-8")
    assert deploy.index("prepare_instance_state_deployment compose") < deploy.index(
        'run_postmutation_gate "service recreate/liveness gate failed"'
    )
    assert start.index("prepare_instance_state_deployment run_docker_compose") < start.index(
        'start_startup_watchdog "$STARTUP_TIMEOUT_SECONDS"'
    )
    assert expected_key["key_id"] != json.loads(
        (backup_root / "ownership-key.json").read_text(encoding="utf-8")
    )["key_id"]


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
    registration = runtime.bootstrap_env_binding(
        vault_root=root,
        watcher_vault_path=root,
    )
    runtime.registry.set_extension_state(
        default_vault_binding_id="binding-default",
        dimensions={"d": ["binding-default"]},
        principal_state={"operator": "local"},
        background_state={"mode": "compatibility"},
        runtime_floors={"registry": "01b"},
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    _create_canonical_backup(
        runtime=runtime,
        backup_root=tmp_path / "backup",
        legacy_path=tmp_path / "missing-legacy.md",
    )
    expected = json.loads(
        (tmp_path / "backup" / "manifest.json").read_text(encoding="utf-8")
    )
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
    restore_proof, owner_receipt = _canonical_test_quiescence_authority(
        layout=layout,
        host_global_root=runtime.ledger.root,
        legacy_path=tmp_path / "missing-legacy.md",
        owners=[
            {
                "channel_id": "prod",
                "vault_binding_id": registration.vault_binding_id,
                "root": str(root),
            }
        ],
    )
    restored = InstanceStateBackup(layout, runtime.ledger).restore(
        tmp_path / "backup",
        quiescence_proof=restore_proof,
        owner_receipt_path=owner_receipt,
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
        InstanceStateBackup(layout, runtime.ledger).restore(
            tmp_path / "backup",
            quiescence_proof=restore_proof,
            owner_receipt_path=owner_receipt,
        )


@pytest.mark.parametrize(
    "lease_kind",
    [
        "arbitrary",
        "copied",
        "missing-fence",
        "wrong-fence-nonce",
        "changed-inventory",
        "changed-owner-receipt",
        "wrong-controller",
    ],
)
def test_prod_restore_rejects_noncanonical_quiescence_authority_without_mutation(
    tmp_path,
    lease_kind,
) -> None:
    layout = InstanceStateLayout.for_channel(tmp_path / "prod-state", "prod")
    runtime = InstanceRegistryRuntime.for_paths(layout, tmp_path / "host-global")
    root = tmp_path / "vault"
    root.mkdir()
    registration = runtime.bootstrap_env_binding(
        vault_root=root,
        watcher_vault_path=root,
    )
    backup_root = tmp_path / "backup"
    _create_canonical_backup(
        runtime=runtime,
        backup_root=backup_root,
        legacy_path=tmp_path / "missing-legacy.md",
    )
    _clear_test_deployment_authority(
        layout=layout,
        host_global_root=runtime.ledger.root,
    )
    runtime.registry.set_extension_state(
        default_vault_binding_id="new-default",
        dimensions={"new": [registration.vault_binding_id]},
        principal_state={"operator": "changed"},
        background_state={"mode": "changed"},
        runtime_floors={"registry": "changed"},
        _capability=STORAGE_MUTATION_CAPABILITY,
    )

    owner_receipt = None
    if lease_kind == "arbitrary":
        proof = _durable_test_quiescence_proof(tmp_path, "prod")
    else:
        _begin_instance_state_deployment(
            channel="prod",
            instance_state_root=layout.root.parent,
            host_global_root=runtime.ledger.root,
            legacy_path=tmp_path / "missing-legacy.md",
            controller_pid=os.getpid(),
            controller_start_token="linux:" + "0" * 64,
        )
        proof = _prove_empty_quiescence(
            channel="prod",
            host_global_root=runtime.ledger.root,
        )
        owner_inventory = runtime.ledger.root / "legacy-owner-inventory.json"
        owner_inventory.write_text(
            json.dumps(
                _legacy_owner_inventory_payload(
                    [
                        {
                            "channel_id": "prod",
                            "vault_binding_id": registration.vault_binding_id,
                            "root": str(root),
                        }
                    ]
                )
            ),
            encoding="utf-8",
        )
        os.chmod(owner_inventory, 0o600)
        proof = _bind_legacy_owner_inventory_to_proof(
            inventory_path=owner_inventory,
            quiescence_proof=proof,
            channel="prod",
            host_global_root=runtime.ledger.root,
        )
        owner_receipt = owner_inventory
        if lease_kind == "copied":
            copied_root = tmp_path / "copied-authority"
            copied_root.mkdir(mode=0o700)
            copied_lease = copied_root / "deployment-host-global-lease.json"
            assert proof.lease_path is not None
            copied_lease.write_bytes(proof.lease_path.read_bytes())
            os.chmod(copied_lease, 0o600)
            proof = replace(proof, lease_path=copied_lease)
        elif lease_kind == "missing-fence":
            _deployment_fence_path(runtime.ledger.root, "prod").unlink()
        elif lease_kind == "wrong-fence-nonce":
            fence_path = _deployment_fence_path(runtime.ledger.root, "prod")
            fence = json.loads(fence_path.read_text(encoding="utf-8"))
            fence["deployment_nonce"] = "wrong-nonce"
            fence_path.write_text(json.dumps(fence), encoding="utf-8")
            os.chmod(fence_path, 0o600)
        elif lease_kind == "changed-inventory":
            inventory_path = runtime.ledger.root / "deployment-quiescence-inventory.json"
            inventory_path.write_bytes(inventory_path.read_bytes() + b"\n")
            os.chmod(inventory_path, 0o600)
        elif lease_kind == "changed-owner-receipt":
            owner_payload = json.loads(owner_inventory.read_text(encoding="utf-8"))
            owner_payload["writers_drained"] = False
            owner_inventory.write_text(json.dumps(owner_payload), encoding="utf-8")
            os.chmod(owner_inventory, 0o600)
        elif lease_kind == "wrong-controller":
            proof = replace(proof, controller_pid=os.getpid() + 1)

    protected_roots = (layout.root, runtime.ledger.root)
    before = {
        path.relative_to(tmp_path): path.read_bytes()
        for protected_root in protected_roots
        for path in protected_root.rglob("*")
        if path.is_file()
    }
    revision_before = runtime.registry.load().revision
    generation_before = runtime.ledger.load().generation

    with pytest.raises(InstanceStatePreflightError, match="canonical quiescence authority"):
        InstanceStateBackup(layout, runtime.ledger).restore(
            backup_root,
            quiescence_proof=proof,
            owner_receipt_path=owner_receipt,
        )

    assert {
        path.relative_to(tmp_path): path.read_bytes()
        for protected_root in protected_roots
        for path in protected_root.rglob("*")
        if path.is_file()
    } == before
    assert runtime.registry.load().revision == revision_before
    assert runtime.ledger.load().generation == generation_before


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
    _create_canonical_backup(
        runtime=source_runtime,
        backup_root=tmp_path / "dev-backup",
        legacy_path=tmp_path / "missing-dev-legacy.md",
    )

    target_layout = InstanceStateLayout.for_channel(tmp_path / "prod-state", "prod")
    target_runtime = InstanceRegistryRuntime.for_paths(
        target_layout,
        tmp_path / "prod-host-global",
    )
    target_root = tmp_path / "prod-vault"
    target_root.mkdir()
    target_registration = target_runtime.bootstrap_env_binding(
        vault_root=target_root,
        watcher_vault_path=target_root,
    )
    target_runtime.registry.set_extension_state(
        default_vault_binding_id="prod-default",
        dimensions={"prod": ["prod-default"]},
        principal_state={"operator": "prod"},
        background_state={"mode": "prod"},
        runtime_floors={"registry": "prod"},
        _capability=STORAGE_MUTATION_CAPABILITY,
    )

    proof, owner_receipt = _canonical_test_quiescence_authority(
        layout=target_layout,
        host_global_root=target_runtime.ledger.root,
        legacy_path=tmp_path / "missing-prod-legacy.md",
        owners=[
            {
                "channel_id": "prod",
                "vault_binding_id": target_registration.vault_binding_id,
                "root": str(target_root),
            }
        ],
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
            quiescence_proof=proof,
            owner_receipt_path=owner_receipt,
        )

    after = {
        path.relative_to(tmp_path): path.read_bytes()
        for root in target_roots
        for path in root.iterdir()
        if path.is_file()
    }
    assert after == before
