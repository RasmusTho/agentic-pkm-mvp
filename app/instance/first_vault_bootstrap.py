"""Ephemeral, authenticated first-vault initialization preconditions (MVR-05B)."""

from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass
from pathlib import Path

from app.instance.filesystem_identity import resolve_filesystem_root_identity
from app.instance.vault_registry import RegistrySnapshot, VaultRegistryStore


class BootstrapPreconditionError(RuntimeError):
    pass


@dataclass(frozen=True)
class BootstrapPrecondition:
    token: str
    subject: str
    target_fingerprint: str
    registry_revision: int


class FirstVaultBootstrapStore:
    """One-process single-use tokens; a restart intentionally invalidates them."""

    def __init__(self) -> None:
        self._tokens: dict[str, BootstrapPrecondition] = {}
        self._lock = threading.RLock()

    def issue(self, *, subject: str, target: Path, registry: VaultRegistryStore) -> str:
        snapshot = registry.load()
        if snapshot.registrations or snapshot.default_vault_binding_id is not None:
            raise BootstrapPreconditionError("first_vault_bootstrap_unavailable")
        token = secrets.token_urlsafe(32)
        identity = resolve_filesystem_root_identity(target)
        fingerprint = f"{identity.canonical_path}|{identity.device}|{identity.inode}"
        with self._lock:
            self._tokens[token] = BootstrapPrecondition(
                token=token,
                subject=subject,
                target_fingerprint=fingerprint,
                registry_revision=snapshot.revision,
            )
        return token

    def consume(self, *, token: str, subject: str, target: Path, registry: VaultRegistryStore) -> None:
        with self._lock:
            record = self._tokens.pop(token, None)
        if record is None or record.subject != subject:
            raise BootstrapPreconditionError("first_vault_bootstrap_invalid")
        identity = resolve_filesystem_root_identity(target)
        fingerprint = f"{identity.canonical_path}|{identity.device}|{identity.inode}"
        if fingerprint != record.target_fingerprint:
            raise BootstrapPreconditionError("first_vault_bootstrap_invalid")
        snapshot: RegistrySnapshot = registry.load()
        if (
            snapshot.revision != record.registry_revision
            or snapshot.registrations
            or snapshot.default_vault_binding_id is not None
        ):
            raise BootstrapPreconditionError("first_vault_bootstrap_stale")


_STORE = FirstVaultBootstrapStore()


def get_first_vault_bootstrap_store() -> FirstVaultBootstrapStore:
    return _STORE


__all__ = ["BootstrapPreconditionError", "FirstVaultBootstrapStore", "get_first_vault_bootstrap_store"]
