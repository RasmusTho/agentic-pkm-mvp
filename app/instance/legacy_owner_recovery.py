"""Explicit DEV-only re-attestation of a retained v1 owner in a stopped window.

This is new operator authority, never an alternative legacy authentication rule.
The backup manifest is the convergence receipt; it is not a runtime owner store.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import stat
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any

from app.instance.instance_state import (
    InstanceStateLayout,
    InstanceStatePreflightError,
    _atomic_private_write,
    _read_private_bytes,
    _read_private_json,
)
from app.instance.ownership_ledger import LEGACY_LEDGER_SCHEMA, LEDGER_SCHEMA, OwnershipLedger
from app.instance.vault_registry import VaultRegistryStore

_SCHEMA = "agentic-pkm.dev-owner-reattest-backup.v1"


def _bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _refuse() -> InstanceStatePreflightError:
    return InstanceStatePreflightError("DEV owner re-attestation evidence is incomplete or changed")


def _backup_destination(destination: Path, protected: tuple[Path, ...]) -> Path:
    protected = tuple(root.expanduser().resolve(strict=False) for root in protected)
    absolute = destination.expanduser().absolute()
    if absolute != absolute.resolve() or any(
        absolute == root or absolute.is_relative_to(root) or root.is_relative_to(absolute)
        for root in protected
    ):
        raise _refuse()
    if absolute.exists():
        metadata = absolute.lstat()
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) != 0o700
        ):
            raise _refuse()
    return absolute


def reattest_legacy_owner(
    *, channel: str, instance_state_root: Path, host_global_root: Path,
    backup_root: Path, quiescence_proof_path: Path, owner_receipt_path: Path,
    vault_binding_id: str, expected_ledger_sha256: str, expected_registry_sha256: str,
    acknowledge_new_ownership_epoch: bool,
) -> dict[str, object]:
    # Import at the CLI boundary to avoid coupling normal admission to recovery.
    from app.instance.runtime import (
        _assert_mount_root,
        _deployment_admission_locked,
        _load_deployment_quiescence_proof,
        _load_legacy_owner_inventory,
        _producer_transition_locked,
    )

    if channel != "dev" or not acknowledge_new_ownership_epoch or not vault_binding_id:
        raise _refuse()
    for digest in (expected_ledger_sha256, expected_registry_sha256):
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise _refuse()
    state = _assert_mount_root(instance_state_root, "instance-state")
    ownership = _assert_mount_root(host_global_root, "host-global")
    layout = InstanceStateLayout.for_channel(state, channel)
    layout.require_existing()
    ledger = OwnershipLedger(ownership)
    store = VaultRegistryStore(layout.registry_path)
    proof = _load_deployment_quiescence_proof(quiescence_proof_path)

    # Same ordering as finalization/backup. No normal writer or key rotation can
    # interleave the captured generation or the final ledger replacement.
    with _deployment_admission_locked(ownership), _producer_transition_locked(layout):
        proof.require_canonical_authority(
            channel_id=channel, host_global_root=ownership,
            owner_receipt_path=owner_receipt_path,
        )
        ledger._assert_existing_artifacts()
        if os.path.lexists(ledger.rotation_path) or os.path.lexists(store.transaction_path):
            raise _refuse()
        with ledger._locked(recover_rotation=False), store._locked():
            key = ledger._load_or_create_key_locked(allow_create=False)
            current = ledger._load_or_create_ledger_locked(
                key, allow_create=False, allow_legacy=True,
            )
            registry = store._read_current_locked(recover=False)
            registry_bytes = _read_private_bytes(store.path)
            if (
                _sha(registry_bytes) != expected_registry_sha256
                or registry.authority != "dormant" or registry.revision < 1
                or set(registry.registrations) != {vault_binding_id}
                or registry.removal_tombstones or registry.transfer_lineage
            ):
                raise _refuse()
            owners = _load_legacy_owner_inventory(
                owner_receipt_path, registry=registry, channel=channel,
                quiescence_proof=proof,
            )
            if len(owners) != 1:
                raise _refuse()
            owner = owners[0]
            registered_root = Path(registry.registrations[vault_binding_id].path)
            if (
                owner.channel_id != channel or owner.vault_binding_id != vault_binding_id
                or not owner.root_identity or not owner.root_identity.startswith("inode:")
                or owner.root != registered_root or not owner.root.is_absolute()
                or set(owner.ancestor_identities) != {f"path:{p}" for p in owner.root.parents}
                or len(owner.ancestor_identities) != len(owner.root.parents)
                or owner.receipt_digest != proof.owner_receipt_digest
            ):
                raise _refuse()
            destination = _backup_destination(backup_root, (state, ownership, owner.root))
            manifest_path = destination / "manifest.json"
            manifest = _read_private_json(manifest_path) if os.path.lexists(manifest_path) else None
            original_bytes = (
                _read_private_bytes(destination / "ownership-ledger.json")
                if manifest is not None else _read_private_bytes(ledger.path)
            )
            if _sha(original_bytes) != expected_ledger_sha256:
                raise _refuse()
            original = ledger._parse_ledger_value(json.loads(original_bytes))
            if (
                original.schema != LEGACY_LEDGER_SCHEMA
                or original.key_id != key.key_id or original.generation != key.generation
                or not original.legacy_bootstrap_complete
                or set(original.leases) != {vault_binding_id}
                or original.tombstones or original.transfer or original.transfer_lineage
            ):
                raise _refuse()
            lease = original.leases[vault_binding_id]
            expected = ledger._lease_for_legacy_owner(owner, key=key)
            if (
                lease.channel_id != channel or lease.vault_binding_id != vault_binding_id
                or lease.state != "active" or not lease.ancestor_fingerprints
                or ledger._open_root(lease.sealed_root, key) != str(owner.root)
                or not hmac.compare_digest(lease.root_fingerprint, expected.root_fingerprint)
            ):
                raise _refuse()
            # Preserve retained identity and sealed locator. Only current ancestry
            # and receipt provenance are newly attested; no old chain is invented.
            candidate = replace(original, schema=LEDGER_SCHEMA, leases={vault_binding_id: replace(
                lease, ancestor_fingerprints=expected.ancestor_fingerprints,
                owner_receipt_digest=owner.receipt_digest,
            )})
            candidate_bytes = _bytes(ledger._ledger_value(candidate))
            live_bytes = _read_private_bytes(ledger.path)
            if live_bytes not in (original_bytes, candidate_bytes):
                raise _refuse()
            if current.schema == LEDGER_SCHEMA and manifest is None:
                raise _refuse()
            payloads = {
                "vault-registry.md": registry_bytes,
                "ownership-ledger.json": original_bytes,
                "ownership-key.json": _read_private_bytes(ledger.key_path),
                "vault-registry.md.last-good": _read_private_bytes(store.snapshot_path),
                "vault-registry.md.last-good.sha256": _read_private_bytes(store.snapshot_checksum_path),
                "vault-registry.md.legacy-export": _read_private_bytes(store.rollback_export_path),
            }
            checksums = {name: _sha(data) for name, data in payloads.items()}
            evidence = {
                "schema": _SCHEMA, "channel_id": channel,
                "vault_binding_id": vault_binding_id,
                "registry_revision": registry.revision,
                "checksums": checksums,
                "after_ledger_sha256": _sha(candidate_bytes),
                "deployment_nonce": proof.nonce,
                "owner_receipt_digest": proof.owner_receipt_digest,
                "quiescence_inventory_digest": proof.inventory_digest,
                "decision": "explicit-new-owner-epoch-retained-root-only",
                "prior_effects": "not_inferred", "activation": "inactive_fenced",
            }
            if manifest is not None:
                signed = {k: v for k, v in manifest.items() if k != "authentication"}
                if (
                    any(manifest.get(k) != v for k, v in evidence.items())
                    or not isinstance(manifest.get("epoch_id"), str)
                    or not hmac.compare_digest(str(manifest.get("authentication", "")),
                        hmac.new(key.secret, _bytes(signed), hashlib.sha256).hexdigest())
                ):
                    raise _refuse()
            else:
                manifest = evidence | {"epoch_id": str(uuid.uuid4())}
                manifest["authentication"] = hmac.new(
                    key.secret, _bytes(manifest), hashlib.sha256,
                ).hexdigest()
            # A partial backup is retryable only when every existing byte agrees.
            if destination.exists():
                if set(p.name for p in destination.iterdir()) - {*payloads, "manifest.json"}:
                    raise _refuse()
                for name, data in payloads.items():
                    target = destination / name
                    if os.path.lexists(target) and _read_private_bytes(target) != data:
                        raise _refuse()
            else:
                destination.mkdir(mode=0o700)
                parent_fd = os.open(destination.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
                try:
                    os.fsync(parent_fd)
                finally:
                    os.close(parent_fd)
            for name, data in payloads.items():
                target = destination / name
                if not target.exists():
                    _atomic_private_write(target, data)
                if _sha(_read_private_bytes(target)) != checksums[name]:
                    raise _refuse()
            if not manifest_path.exists():
                _atomic_private_write(manifest_path, _bytes(manifest))
            if _read_private_bytes(manifest_path) != _bytes(manifest):
                raise _refuse()
            # Re-prove under every mutation lock immediately before the sole
            # authority write. Even a receipt-backed retry cannot un-fence itself.
            proof.require_canonical_authority(
                channel_id=channel, host_global_root=ownership,
                owner_receipt_path=owner_receipt_path,
            )
            if live_bytes != candidate_bytes:
                ledger._write_ledger_locked(candidate, key)
            if (
                _read_private_bytes(ledger.path) != candidate_bytes
                or _sha(_read_private_bytes(store.path)) != expected_registry_sha256
            ):
                raise _refuse()
            return {"channel": channel, "reattested": True,
                    "epoch_id": manifest["epoch_id"], "backup_verified": True,
                    "activation": "inactive_fenced", "prior_effects": "not_inferred",
                    "ledger_sha256": _sha(candidate_bytes)}
