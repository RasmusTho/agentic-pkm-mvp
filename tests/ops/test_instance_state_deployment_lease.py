from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from app.instance.runtime import (
    InstanceStatePreflightError,
    RegistryError,
    _any_deployment_lease_exists,
    _begin_instance_state_deployment,
    _deployment_fence_path,
    _deployment_lease_path,
    _legacy_deployment_lease_path,
    _preflight_runtime,
    _release_instance_state_deployment_lease,
)
from app.instance import ownership_ledger as ownership_ledger_module
from app.instance import runtime as runtime_module
from app.instance.filesystem_identity import FilesystemRootIdentity, resolve_filesystem_root_identity
from app.instance.instance_state import InstanceStateLayout
from app.instance.ownership_ledger import LegacyOwner, OwnershipLedger
from app.instance.vault_registry import VaultRegistration, VaultRegistryStore
from tests.helpers.instance_storage_capability import STORAGE_MUTATION_CAPABILITY

REPO_ROOT = Path(__file__).resolve().parents[2]
WRITER_INVENTORY_HELPER = REPO_ROOT / "scripts/instance_state_writer_inventory.py"


def _controller_token(pid: int) -> str:
    return subprocess.check_output(
        [
            sys.executable,
            str(WRITER_INVENTORY_HELPER),
            "controller-token",
            "--pid",
            str(pid),
        ],
        text=True,
    ).strip()


def _begin(
    tmp_path: Path,
    *,
    channel: str,
    controller_pid: int,
    controller_start_token: str,
) -> tuple[Path, Path, dict[str, object]]:
    state = tmp_path / "state"
    ownership = tmp_path / "ownership"
    state.mkdir(exist_ok=True)
    ownership.mkdir(exist_ok=True)
    fence = _begin_instance_state_deployment(
        channel=channel,
        instance_state_root=state,
        host_global_root=ownership,
        legacy_path=tmp_path / "legacy.md",
        controller_pid=controller_pid,
        controller_start_token=controller_start_token,
    )
    return state, ownership, fence


def test_failed_deployment_releases_host_global_lease(tmp_path: Path) -> None:
    """AC: a deployment that fails between begin and finish leaves no residue."""

    channel = "prod"
    controller_pid = os.getpid()
    controller_token = _controller_token(controller_pid)
    _state, ownership, _fence = _begin(
        tmp_path,
        channel=channel,
        controller_pid=controller_pid,
        controller_start_token=controller_token,
    )
    assert _deployment_lease_path(ownership).exists()
    assert _deployment_fence_path(ownership, channel).exists()
    assert _legacy_deployment_lease_path(ownership).exists()

    receipt = _release_instance_state_deployment_lease(
        channel=channel,
        host_global_root=ownership,
        controller_pid=controller_pid,
        controller_start_token=controller_token,
    )

    assert receipt["released"] is True
    assert not _deployment_lease_path(ownership).exists()
    assert not _deployment_fence_path(ownership, channel).exists()
    assert not _legacy_deployment_lease_path(ownership).exists()
    assert not _any_deployment_lease_exists(ownership)


def test_release_after_successful_finish_is_a_noop(tmp_path: Path) -> None:
    """A release attempt must not run after deployment-finish already cleared the lease."""

    channel = "prod"
    controller_pid = os.getpid()
    controller_token = _controller_token(controller_pid)
    _state, ownership, _fence = _begin(
        tmp_path,
        channel=channel,
        controller_pid=controller_pid,
        controller_start_token=controller_token,
    )
    # Simulate deployment-finish already having cleared the lease and fence.
    _deployment_lease_path(ownership).unlink()
    _deployment_fence_path(ownership, channel).unlink()
    _legacy_deployment_lease_path(ownership).unlink()

    receipt = _release_instance_state_deployment_lease(
        channel=channel,
        host_global_root=ownership,
        controller_pid=controller_pid,
        controller_start_token=controller_token,
    )

    assert receipt["released"] is False
    assert receipt["reason"] == "no-active-lease"


def test_release_ignores_a_lease_owned_by_a_different_controller(tmp_path: Path) -> None:
    """Release must never clear a lease it did not itself claim, even a live one."""

    channel = "prod"
    owner_pid = os.getpid()
    owner_token = _controller_token(owner_pid)
    _state, ownership, _fence = _begin(
        tmp_path,
        channel=channel,
        controller_pid=owner_pid,
        controller_start_token=owner_token,
    )

    receipt = _release_instance_state_deployment_lease(
        channel=channel,
        host_global_root=ownership,
        controller_pid=999_999_998,
        controller_start_token=f"linux:{'6' * 64}",
    )

    assert receipt["released"] is False
    assert receipt["reason"] == "controller-mismatch"
    assert _deployment_lease_path(ownership).exists()
    assert _deployment_fence_path(ownership, channel).exists()
    lease = json.loads(_deployment_lease_path(ownership).read_text(encoding="utf-8"))
    assert lease["controller"] == {"pid": owner_pid, "start_token": owner_token}


def test_release_ignores_a_lease_from_a_different_channel(tmp_path: Path) -> None:
    """Release must never clear another channel's lease, even with a matching controller."""

    channel = "prod"
    controller_pid = os.getpid()
    controller_token = _controller_token(controller_pid)
    _state, ownership, _fence = _begin(
        tmp_path,
        channel=channel,
        controller_pid=controller_pid,
        controller_start_token=controller_token,
    )

    receipt = _release_instance_state_deployment_lease(
        channel="test",
        host_global_root=ownership,
        controller_pid=controller_pid,
        controller_start_token=controller_token,
    )

    assert receipt["released"] is False
    assert receipt["reason"] == "channel-mismatch"
    assert _deployment_lease_path(ownership).exists()
    assert _deployment_fence_path(ownership, channel).exists()


def test_dead_controller_lease_is_reclaimable(tmp_path: Path) -> None:
    """AC: a lease whose controller process no longer exists is reclaimable."""

    channel = "prod"
    dead_pid = 999_999_998
    dead_token = f"linux:{'3' * 64}"
    state, ownership, _fence = _begin(
        tmp_path,
        channel=channel,
        controller_pid=dead_pid,
        controller_start_token=dead_token,
    )

    live_pid = os.getpid()
    live_token = _controller_token(live_pid)
    recovered = _begin_instance_state_deployment(
        channel=channel,
        instance_state_root=state,
        host_global_root=ownership,
        legacy_path=tmp_path / "legacy.md",
        controller_pid=live_pid,
        controller_start_token=live_token,
    )

    assert recovered["controller"] == {"pid": live_pid, "start_token": live_token}
    lease = json.loads(_deployment_lease_path(ownership).read_text(encoding="utf-8"))
    assert lease["controller"] == {"pid": live_pid, "start_token": live_token}


def test_live_controller_lease_still_blocks(tmp_path: Path) -> None:
    """AC: a live controller with a matching start token still blocks, via the
    production begin path rather than the liveness helper alone."""

    channel = "prod"
    controller_pid = os.getpid()
    controller_token = _controller_token(controller_pid)
    state, ownership, _fence = _begin(
        tmp_path,
        channel=channel,
        controller_pid=controller_pid,
        controller_start_token=controller_token,
    )

    with pytest.raises(InstanceStatePreflightError, match="controller is active"):
        _begin_instance_state_deployment(
            channel=channel,
            instance_state_root=state,
            host_global_root=ownership,
            legacy_path=tmp_path / "legacy.md",
            controller_pid=999_999_998,
            controller_start_token=f"linux:{'4' * 64}",
        )


def test_recycled_pid_is_not_treated_as_live(tmp_path: Path) -> None:
    """AC: a recycled pid whose start token differs from the recorded lease is dead."""

    channel = "prod"
    recycled_pid = os.getpid()
    stale_token = f"linux:{'5' * 64}"
    state, ownership, _fence = _begin(
        tmp_path,
        channel=channel,
        controller_pid=recycled_pid,
        controller_start_token=stale_token,
    )

    live_token = _controller_token(recycled_pid)
    assert live_token != stale_token
    recovered = _begin_instance_state_deployment(
        channel=channel,
        instance_state_root=state,
        host_global_root=ownership,
        legacy_path=tmp_path / "legacy.md",
        controller_pid=recycled_pid,
        controller_start_token=live_token,
    )

    assert recovered["controller"] == {"pid": recycled_pid, "start_token": live_token}


def test_runtime_consumer_unblocked_after_abandoned_deployment(tmp_path: Path) -> None:
    """AC: a runtime consumer started after an abandoned deployment is not
    blocked by residue from that deployment."""

    channel = "prod"
    controller_pid = os.getpid()
    controller_token = _controller_token(controller_pid)
    state, ownership, _fence = _begin(
        tmp_path,
        channel=channel,
        controller_pid=controller_pid,
        controller_start_token=controller_token,
    )

    with pytest.raises(RegistryError, match="blocks every runtime consumer"):
        _preflight_runtime(
            channel=channel,
            instance_state_root=state,
            host_global_root=ownership,
            consumer="api",
        )

    _release_instance_state_deployment_lease(
        channel=channel,
        host_global_root=ownership,
        controller_pid=controller_pid,
        controller_start_token=controller_token,
    )

    assert not _any_deployment_lease_exists(ownership)
    assert not _deployment_fence_path(ownership, channel).exists()

    # Residue is gone: the preflight now fails later in the chain (the
    # registry producer was never initialized in this test), never on the
    # lease/fence guards the abandoned deployment used to trip.
    with pytest.raises(
        InstanceStatePreflightError,
        match="instance-state registry producer has not initialized",
    ):
        _preflight_runtime(
            channel=channel,
            instance_state_root=state,
            host_global_root=ownership,
            consumer="api",
        )


def _remounted_runtime_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, pending: bool = False
) -> tuple[Path, Path, Path, bytes, bytes]:
    """Build an established binding plus the private host receipt it authenticates."""

    channel = "dev"
    state = tmp_path / "state"
    ownership = tmp_path / "ownership"
    vault = tmp_path / "vault"
    state.mkdir(mode=0o700)
    ownership.mkdir(mode=0o700)
    vault.mkdir()
    layout = InstanceStateLayout.for_channel(state, channel)
    layout.ensure()
    registration = VaultRegistration("binding-remounted", f"path:{vault}", str(vault))
    VaultRegistryStore(layout.registry_path).register(
        registration, _capability=STORAGE_MUTATION_CAPABILITY
    )

    identity = resolve_filesystem_root_identity(vault)
    root_identity = f"inode:{identity.device}:{identity.inode}"
    ancestors = tuple(f"path:{ancestor}" for ancestor in vault.resolve().parents)
    legacy_ancestors = tuple(
        f"inode:{ancestor.stat().st_dev}:{ancestor.stat().st_ino}"
        for ancestor in vault.resolve().parents
    )
    owner = LegacyOwner(
        channel,
        registration.vault_binding_id,
        vault,
        root_identity,
        ancestors,
        legacy_ancestors,
    )
    ledger = OwnershipLedger(ownership)
    owner_row = {
        "channel_id": channel,
        "vault_binding_id": registration.vault_binding_id,
        "root": str(vault),
    }
    source_evidence = {
        "docker": [],
        "config": [],
        "owners": [owner_row],
        "owner_identities": [
            {
                "channel_id": channel,
                "root": str(vault),
                "identity": root_identity,
                "ancestor_identities": sorted(ancestors),
                "legacy_ancestor_identities": list(legacy_ancestors),
            }
        ],
    }
    receipt = {
        "schema": "agentic-pkm.legacy-owner-inventory.v1",
        "inventory_complete": True,
        "writers_drained": True,
        "source_probe_count": 2,
        "validated_after_quiescence": True,
        "source_digest": runtime_module._canonical_json_digest(source_evidence),
        "source_evidence": source_evidence,
        "owners": [owner_row],
    }
    receipt["receipt_digest"] = runtime_module._legacy_owner_receipt_digest(receipt)
    owner = LegacyOwner(
        channel,
        registration.vault_binding_id,
        vault,
        root_identity,
        ancestors,
        legacy_ancestors,
        receipt["receipt_digest"],
    )
    ledger.bootstrap_legacy_owners(
        [] if pending else [owner],
        inventory_complete=True,
        writers_drained=True,
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    if pending:
        ledger.reserve(
            channel_id=channel,
            vault_binding_id=registration.vault_binding_id,
            root=vault,
            _capability=STORAGE_MUTATION_CAPABILITY,
        )
        with ledger._locked():
            key = ledger._load_or_create_key_locked(allow_create=False)
            current = ledger._load_or_create_ledger_locked(key, allow_create=False)
            pending_lease = current.leases[registration.vault_binding_id]
            ledger._write_ledger_locked(
                replace(
                    current,
                    leases={
                        **current.leases,
                        registration.vault_binding_id: replace(
                            pending_lease,
                            owner_receipt_digest=receipt["receipt_digest"],
                        ),
                    },
                ),
                key,
            )
    receipt_path = ownership / "legacy-owner-inventory.json"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    receipt_path.chmod(0o600)
    monkeypatch.setenv("VAULT_ROOT", str(vault))
    monkeypatch.setenv("WATCHER_VAULT_PATH", str(vault))
    return state, ownership, receipt_path, layout.registry_path.read_bytes(), OwnershipLedger(ownership).path.read_bytes()


def _simulate_container_remount(monkeypatch: pytest.MonkeyPatch, vault: Path) -> None:
    """Make direct ledger materialization see the same path with another inode."""

    original = ownership_ledger_module.resolve_filesystem_root_identity

    def remounted(value: str | Path) -> FilesystemRootIdentity:
        resolved = Path(value).expanduser().resolve(strict=False)
        identity = original(resolved)
        if resolved == vault.resolve():
            return FilesystemRootIdentity(identity.canonical_path, identity.device, (identity.inode or 0) + 1)
        return identity

    monkeypatch.setattr(ownership_ledger_module, "resolve_filesystem_root_identity", remounted)


def test_runtime_preflight_accepts_authenticated_remounted_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC: the production consumer admits only the receipt-authenticated remount."""

    state, ownership, _receipt, registry_before, ledger_before = _remounted_runtime_fixture(
        tmp_path, monkeypatch
    )
    _simulate_container_remount(monkeypatch, tmp_path / "vault")

    assert _preflight_runtime(
        channel="dev",
        instance_state_root=state,
        host_global_root=ownership,
        consumer="api",
    ) == 0
    assert InstanceStateLayout.for_channel(state, "dev").registry_path.read_bytes() == registry_before
    assert OwnershipLedger(ownership).path.read_bytes() == ledger_before

    pending_root = tmp_path / "pending"
    pending_root.mkdir()
    pending_state, pending_ownership, _receipt, _registry_before, pending_ledger_before = (
        _remounted_runtime_fixture(pending_root, monkeypatch, pending=True)
    )
    _simulate_container_remount(monkeypatch, tmp_path / "pending" / "vault")
    with pytest.raises((InstanceStatePreflightError, RegistryError)):
        _preflight_runtime(
            channel="dev",
            instance_state_root=pending_state,
            host_global_root=pending_ownership,
            consumer="api",
        )
    assert OwnershipLedger(pending_ownership).require_existing().leases[
        "binding-remounted"
    ].state == "pending"
    assert OwnershipLedger(pending_ownership).path.read_bytes() == pending_ledger_before


def test_remounted_receipt_checkpoint_survives_key_rotation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC: key rotation preserves the producer checkpoint used by remount admission."""

    _state, ownership, receipt_path, _registry_before, _ledger_before = (
        _remounted_runtime_fixture(tmp_path, monkeypatch)
    )
    receipt_digest = json.loads(receipt_path.read_bytes())["receipt_digest"]
    ledger = OwnershipLedger(ownership)
    assert (
        ledger.require_existing().leases["binding-remounted"].owner_receipt_digest
        == receipt_digest
    )

    ledger.rotate_key(
        precondition=lambda _snapshot, _live_roots: None,
        _capability=STORAGE_MUTATION_CAPABILITY,
    )

    assert (
        ledger.require_existing().leases["binding-remounted"].owner_receipt_digest
        == receipt_digest
    )
    _simulate_container_remount(monkeypatch, tmp_path / "vault")
    assert _preflight_runtime(
        channel="dev",
        instance_state_root=_state,
        host_global_root=ownership,
        consumer="api",
    ) == 0


def test_runtime_preflight_rejects_invalid_remounted_root_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC: invalid receipt variants fail before either authoritative store mutates."""

    state, ownership, receipt_path, registry_before, ledger_before = _remounted_runtime_fixture(
        tmp_path, monkeypatch
    )
    _simulate_container_remount(monkeypatch, tmp_path / "vault")
    original = receipt_path.read_bytes()
    for invalid in (
        "missing",
        "forged",
        "stale",
        "foreign",
        "mismatched",
        "unbound",
        "ambiguous",
    ):
        receipt_path.write_bytes(original)
        if invalid == "missing":
            receipt_path.unlink()
        else:
            payload = json.loads(original)
            if invalid == "forged":
                payload["receipt_digest"] = "0" * 64
            elif invalid == "stale":
                payload["deployment_nonce"] = "stale-deployment"
                payload["receipt_digest"] = runtime_module._legacy_owner_receipt_digest(
                    payload
                )
            elif invalid == "foreign":
                payload["owners"][0]["channel_id"] = "prod"
                payload["source_evidence"]["owners"][0]["channel_id"] = "prod"
                payload["source_evidence"]["owner_identities"][0]["channel_id"] = (
                    "prod"
                )
                payload["source_digest"] = runtime_module._canonical_json_digest(
                    payload["source_evidence"]
                )
                payload["receipt_digest"] = runtime_module._legacy_owner_receipt_digest(
                    payload
                )
            elif invalid == "mismatched":
                payload["owners"][0]["vault_binding_id"] = "binding-other"
                payload["source_evidence"]["owners"][0]["vault_binding_id"] = (
                    "binding-other"
                )
                payload["source_digest"] = runtime_module._canonical_json_digest(
                    payload["source_evidence"]
                )
                payload["receipt_digest"] = runtime_module._legacy_owner_receipt_digest(
                    payload
                )
            elif invalid == "unbound":
                payload["owners"][0].pop("vault_binding_id")
                payload["source_evidence"]["owners"][0].pop("vault_binding_id")
                payload["source_digest"] = runtime_module._canonical_json_digest(
                    payload["source_evidence"]
                )
                payload["receipt_digest"] = runtime_module._legacy_owner_receipt_digest(
                    payload
                )
            else:
                payload["source_evidence"]["owners"].append(
                    dict(payload["owners"][0])
                )
                payload["source_evidence"]["owner_identities"].append(
                    dict(payload["source_evidence"]["owner_identities"][0])
                )
                payload["owners"].append(dict(payload["owners"][0]))
                payload["source_digest"] = runtime_module._canonical_json_digest(
                    payload["source_evidence"]
                )
                payload["receipt_digest"] = runtime_module._legacy_owner_receipt_digest(
                    payload
                )
            receipt_path.write_text(json.dumps(payload), encoding="utf-8")
            receipt_path.chmod(0o600)
        with pytest.raises((InstanceStatePreflightError, RegistryError)):
            _preflight_runtime(
                channel="dev",
                instance_state_root=state,
                host_global_root=ownership,
                consumer="api",
            )
        assert InstanceStateLayout.for_channel(state, "dev").registry_path.read_bytes() == registry_before
        assert OwnershipLedger(ownership).path.read_bytes() == ledger_before

    pending_root = tmp_path / "pending"
    pending_root.mkdir()
    pending_state, pending_ownership, pending_receipt, _registry, pending_ledger = (
        _remounted_runtime_fixture(pending_root, monkeypatch, pending=True)
    )
    _simulate_container_remount(monkeypatch, pending_root / "vault")
    pending_payload = json.loads(pending_receipt.read_bytes())
    pending_payload["source_evidence"]["owner_identities"][0]["identity"] = (
        "inode:999999:999999"
    )
    pending_payload["source_digest"] = runtime_module._canonical_json_digest(
        pending_payload["source_evidence"]
    )
    pending_payload["receipt_digest"] = runtime_module._legacy_owner_receipt_digest(
        pending_payload
    )
    pending_receipt.write_text(json.dumps(pending_payload), encoding="utf-8")
    pending_receipt.chmod(0o600)
    with pytest.raises((InstanceStatePreflightError, RegistryError)):
        _preflight_runtime(
            channel="dev",
            instance_state_root=pending_state,
            host_global_root=pending_ownership,
            consumer="api",
        )
    assert OwnershipLedger(pending_ownership).path.read_bytes() == pending_ledger
