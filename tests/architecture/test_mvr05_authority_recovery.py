"""Regression coverage for protected ownership recovery at deployment finish."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import app.instance.runtime as runtime_module
from app.instance._storage_boundary import _STORAGE_MUTATION_CAPABILITY
from app.instance.instance_state import InstanceStateLayout, InstanceStatePreflightError
from app.instance.ownership_ledger import LedgerKeyError, OwnershipLedger
from app.instance.runtime import (
    _begin_instance_state_deployment,
    _deployment_fence_path,
    _deployment_lease_path,
    _finish_instance_state_deployment,
    _prove_instance_state_quiescence,
)
from app.instance.vault_registry import VaultRegistration, VaultRegistryStore


REPO_ROOT = Path(__file__).resolve().parents[2]
WRITER_INVENTORY_HELPER = REPO_ROOT / "scripts/instance_state_writer_inventory.py"
pytestmark = pytest.mark.not_pg


def _controller_token() -> str:
    return subprocess.check_output(
        [sys.executable, str(WRITER_INVENTORY_HELPER), "controller-token", "--pid", str(os.getpid())],
        text=True,
    ).strip()


def _owner_inventory(owners: list[dict[str, str]]) -> dict[str, object]:
    identities = []
    for owner in owners:
        metadata = os.stat(owner["root"])
        identities.append(
            {
                "channel_id": owner["channel_id"],
                "root": owner["root"],
                "identity": f"inode:{metadata.st_dev}:{metadata.st_ino}",
                "ancestor_identities": sorted(
                    f"path:{ancestor}" for ancestor in Path(owner["root"]).resolve().parents
                ),
            }
        )
    evidence = {"docker": [], "config": [], "owners": owners, "owner_identities": identities}
    return {
        "schema": "agentic-pkm.legacy-owner-inventory.v1",
        "inventory_complete": True,
        "writers_drained": True,
        "source_probe_count": 2,
        "validated_after_quiescence": True,
        "source_digest": hashlib.sha256(
            json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "source_evidence": evidence,
        "owners": owners,
    }


def _rewrite_ledger_as_authenticated_v1(ledger: OwnershipLedger, root: Path) -> bytes:
    secret = base64.b64decode(
        json.loads(ledger.key_path.read_text(encoding="utf-8"))["secret"], validate=True
    )
    payload = json.loads(ledger.path.read_text(encoding="utf-8"))
    payload["schema"] = "agentic-pkm.host-ownership-ledger.v1"
    for record in payload["leases"].values():
        record["ancestor_fingerprints"] = [
            hmac.new(secret, f"path:{ancestor}".encode(), hashlib.sha256).hexdigest()
            for ancestor in root.resolve().parents
        ]
    encoded = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
    ledger.path.write_bytes(encoded)
    ledger.path.chmod(0o600)
    return encoded


def _prove_empty_quiescence(channel: str, ownership_root: Path):
    lease = json.loads(_deployment_lease_path(ownership_root).read_text(encoding="utf-8"))
    domains = {domain: [] for domain in ("dev", "native", "prod", "test")}
    digest = hashlib.sha256(
        json.dumps(domains, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    inventory = ownership_root / "deployment-quiescence-inventory.json"
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
    inventory.chmod(0o600)
    return _prove_instance_state_quiescence(
        channel=channel, host_global_root=ownership_root, inventory_path=inventory
    )


def _finish(
    *,
    state_root: Path,
    ownership_root: Path,
    backup_root: Path,
    owners: list[dict[str, str]],
    restore_root: Path | None = None,
    remove_restart_fence: bool = False,
) -> dict[str, object]:
    channel = "dev"
    _begin_instance_state_deployment(
        channel=channel,
        instance_state_root=state_root,
        host_global_root=ownership_root,
        legacy_path=state_root / "missing-legacy.md",
        controller_pid=os.getpid(),
        controller_start_token=_controller_token(),
    )
    inventory = ownership_root / "legacy-owner-inventory.json"
    inventory.write_text(json.dumps(_owner_inventory(owners)), encoding="utf-8")
    inventory.chmod(0o600)
    proof = _prove_empty_quiescence(channel, ownership_root)
    if remove_restart_fence:
        _deployment_fence_path(ownership_root, channel).unlink()
    return _finish_instance_state_deployment(
        channel=channel,
        instance_state_root=state_root,
        host_global_root=ownership_root,
        legacy_path=state_root / "missing-legacy.md",
        inventory_path=inventory,
        backup_root=backup_root,
        restore_root=restore_root,
        quiescence_proof=proof,
    )


def _established_owner(state_root: Path, ownership_root: Path) -> tuple[dict[str, str], OwnershipLedger]:
    layout = InstanceStateLayout.for_channel(state_root, "dev")
    registry = VaultRegistryStore(layout.registry_path)
    root = state_root / "content-root"
    root.mkdir()
    registry.register(
        VaultRegistration("binding-a", "path:binding-a", str(root)),
        _capability=_STORAGE_MUTATION_CAPABILITY,
    )
    ledger = OwnershipLedger(ownership_root)
    ledger.reserve(
        channel_id="dev",
        vault_binding_id="binding-a",
        root=root,
        _capability=_STORAGE_MUTATION_CAPABILITY,
    )
    ledger.activate("binding-a", _capability=_STORAGE_MUTATION_CAPABILITY)
    return ({"channel_id": "dev", "vault_binding_id": "binding-a", "root": str(root)}, ledger)


def _fresh_and_established(tmp_path: Path) -> tuple[Path, Path, dict[str, str], OwnershipLedger]:
    state_root = tmp_path / "instance-state"
    ownership_root = tmp_path / "host-global"
    state_root.mkdir()
    ownership_root.mkdir()
    _finish(
        state_root=state_root,
        ownership_root=ownership_root,
        backup_root=tmp_path / "fresh-backup",
        owners=[],
    )
    owner, ledger = _established_owner(state_root, ownership_root)
    return state_root, ownership_root, owner, ledger


def test_fresh_and_intact_registry_paths_preserve_authority_contract(tmp_path: Path) -> None:
    state_root, ownership_root, owner, ledger = _fresh_and_established(tmp_path)
    before = ledger.require_existing()

    result = _finish(
        state_root=state_root,
        ownership_root=ownership_root,
        backup_root=tmp_path / "intact-backup",
        owners=[owner],
    )

    after = ledger.require_existing()
    assert result["restart_fence_cleared"] is True
    assert (after.key_id, after.generation) == (before.key_id, before.generation)


def test_established_registry_missing_ownership_fails_closed(tmp_path: Path) -> None:
    state_root, ownership_root, owner, ledger = _fresh_and_established(tmp_path)
    registry_before = (state_root / "agentic-pkm" / "vault-registry.md").read_bytes()
    ledger.path.unlink()
    ledger.key_path.unlink()

    with pytest.raises(LedgerKeyError):
        _finish(
            state_root=state_root,
            ownership_root=ownership_root,
            backup_root=tmp_path / "blocked-backup",
            owners=[owner],
        )

    assert not ledger.path.exists()
    assert not ledger.key_path.exists()
    assert (state_root / "agentic-pkm" / "vault-registry.md").read_bytes() == registry_before


def test_legacy_ledger_mismatch_fails_closed_before_floor(tmp_path: Path) -> None:
    """The convergence seam must preserve a forged legacy ledger verbatim."""

    ownership_root = tmp_path / "host-global"
    ownership_root.mkdir(mode=0o700)
    root = tmp_path / "vault"
    root.mkdir()
    ledger = OwnershipLedger(ownership_root)
    ledger.reserve(
        channel_id="dev",
        vault_binding_id="binding-a",
        root=root,
        _capability=_STORAGE_MUTATION_CAPABILITY,
    )
    ledger.activate("binding-a", _capability=_STORAGE_MUTATION_CAPABILITY)
    payload = json.loads(_rewrite_ledger_as_authenticated_v1(ledger, root))
    payload["leases"]["binding-a"]["channel_id"] = "prod"
    before = json.dumps(payload, sort_keys=True).encode()
    ledger.path.write_bytes(before)
    ledger.path.chmod(0o600)
    registry = VaultRegistryStore(tmp_path / "instance" / "vault-registry.md").load()

    with pytest.raises(InstanceStatePreflightError, match="consistency"):
        runtime_module._converge_authenticated_legacy_ledger(
            channel="dev",
            registry=registry,
            ledger=ledger,
            owners=(runtime_module.LegacyOwner("dev", "binding-a", root),),
        )

    assert ledger.path.read_bytes() == before


def test_recovery_requires_explicit_fence(tmp_path: Path) -> None:
    state_root, ownership_root, owner, ledger = _fresh_and_established(tmp_path)
    recovery_backup = tmp_path / "recovery-backup"
    _finish(
        state_root=state_root,
        ownership_root=ownership_root,
        backup_root=recovery_backup,
        owners=[owner],
    )
    before = ledger.require_existing()
    ledger.path.unlink()
    ledger.key_path.unlink()

    with pytest.raises(InstanceStatePreflightError, match="restart fence"):
        _finish(
            state_root=state_root,
            ownership_root=ownership_root,
            backup_root=tmp_path / "unfenced-recovery-backup",
            owners=[owner],
            restore_root=recovery_backup,
            remove_restart_fence=True,
        )

    fenced_root = tmp_path / "fenced"
    fenced_root.mkdir()
    state_root, ownership_root, owner, ledger = _fresh_and_established(fenced_root)
    recovery_backup = tmp_path / "fenced-recovery-backup"
    _finish(
        state_root=state_root,
        ownership_root=ownership_root,
        backup_root=recovery_backup,
        owners=[owner],
    )
    before = ledger.require_existing()
    ledger.path.unlink()
    ledger.key_path.unlink()

    result = _finish(
        state_root=state_root,
        ownership_root=ownership_root,
        backup_root=tmp_path / "post-recovery-backup",
        owners=[owner],
        restore_root=recovery_backup,
    )

    restored = ledger.require_existing()
    assert result["restart_fence_cleared"] is True
    assert (restored.key_id, restored.generation) == (before.key_id, before.generation)
