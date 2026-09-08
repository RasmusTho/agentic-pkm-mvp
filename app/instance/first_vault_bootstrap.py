"""Authenticated, single-use first-vault initialization preconditions.

The first-vault journey is deliberately split into two authorities:

* this store authenticates the request precondition and its short-lived replay fence;
* :class:`InstanceRegistryRuntime` owns the ownership/registry transaction and recovery.

The store never selects a vault and never grants general write authority.  It carries only
the facts needed to prove that the request which asked for the first-vault operation is the
same request that reaches the locked owner transaction.
"""

from __future__ import annotations

import fcntl
import hashlib
import hmac
import json
import os
import secrets
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping

from app.instance.vault_registry import RegistrySnapshot


FIRST_VAULT_BOOTSTRAP_SCHEMA = "agentic-pkm.first-vault-bootstrap.v1"
FIRST_VAULT_BOOTSTRAP_TTL_SECONDS = 90.0


class FirstVaultBootstrapError(RuntimeError):
    """The authenticated first-vault precondition cannot be accepted."""


def canonical_target(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def target_fingerprint(path: Path) -> str:
    return hashlib.sha256(str(canonical_target(path)).encode("utf-8")).hexdigest()


def request_fingerprint(
    path: Path,
    *,
    vault_name: str | None,
    machine_role: str,
    remember: bool,
    confirm: bool,
) -> str:
    payload = {
        "target": str(canonical_target(path)),
        "vault_name": vault_name,
        "machine_role": machine_role,
        "remember": remember,
        "confirm": confirm,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class FirstVaultPrecondition:
    token_digest: str
    principal_id: str
    target_fingerprint: str
    request_fingerprint: str
    registry_revision: int
    compatibility_revision: int
    confirmation: bool
    issued_at: float
    expires_at: float
    state: str
    binding_id: str | None = None
    vault_id: str | None = None
    local_instance_id: str | None = None

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> FirstVaultPrecondition:
        if payload.get("schema") != FIRST_VAULT_BOOTSTRAP_SCHEMA:
            raise FirstVaultBootstrapError("first-vault bootstrap precondition schema is invalid")
        try:
            result = cls(
                token_digest=str(payload["token_digest"]),
                principal_id=str(payload["principal_id"]),
                target_fingerprint=str(payload["target_fingerprint"]),
                request_fingerprint=str(payload["request_fingerprint"]),
                registry_revision=int(payload["registry_revision"]),
                compatibility_revision=int(payload["compatibility_revision"]),
                confirmation=bool(payload["confirmation"]),
                issued_at=float(payload["issued_at"]),
                expires_at=float(payload["expires_at"]),
                state=str(payload["state"]),
                binding_id=(str(payload["binding_id"]) if payload.get("binding_id") else None),
                vault_id=(str(payload["vault_id"]) if payload.get("vault_id") else None),
                local_instance_id=(
                    str(payload["local_instance_id"])
                    if payload.get("local_instance_id")
                    else None
                ),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise FirstVaultBootstrapError("first-vault bootstrap precondition is malformed") from exc
        if result.state not in {"issued", "reserved", "content_effected", "consumed", "failed"}:
            raise FirstVaultBootstrapError("first-vault bootstrap precondition state is invalid")
        return result

    def as_payload(self) -> dict[str, Any]:
        return {
            "schema": FIRST_VAULT_BOOTSTRAP_SCHEMA,
            "token_digest": self.token_digest,
            "principal_id": self.principal_id,
            "target_fingerprint": self.target_fingerprint,
            "request_fingerprint": self.request_fingerprint,
            "registry_revision": self.registry_revision,
            "compatibility_revision": self.compatibility_revision,
            "compatibility_state_empty": True,
            "confirmation": self.confirmation,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "state": self.state,
            "binding_id": self.binding_id,
            "vault_id": self.vault_id,
            "local_instance_id": self.local_instance_id,
        }

    def validate_for_runtime(
        self,
        snapshot: RegistrySnapshot,
        path: Path,
    ) -> FirstVaultPrecondition:
        """Revalidate the durable facts while the owner lock is held."""

        if self.state not in {"issued", "reserved", "content_effected"}:
            raise FirstVaultBootstrapError("first-vault bootstrap precondition is not executable")
        if time.time() >= self.expires_at:
            raise FirstVaultBootstrapError("first-vault bootstrap precondition expired")
        if self.target_fingerprint != target_fingerprint(path):
            raise FirstVaultBootstrapError("first-vault bootstrap target changed")
        if snapshot.settings_rebind is not None:
            raise FirstVaultBootstrapError("first-vault bootstrap compatibility state changed")
        if not snapshot.registrations:
            if snapshot.revision != self.registry_revision:
                raise FirstVaultBootstrapError("first-vault bootstrap registry revision changed")
            return self
        if (
            self.binding_id is None
            or set(snapshot.registrations) != {self.binding_id}
            or snapshot.default_vault_binding_id != self.binding_id
            or snapshot.revision != self.registry_revision + 1
        ):
            raise FirstVaultBootstrapError("first-vault bootstrap recovery state is not exact")
        return self


class FirstVaultPreconditionStore:
    """One private durable attempt record next to the authoritative registry."""

    def __init__(self, registry_path: Path, *, clock: Any = time.time) -> None:
        self.path = Path(registry_path).with_suffix(".first-vault-bootstrap.json")
        self.lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        self._clock = clock

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(
            self.lock_path,
            os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "a+b", closefd=True) as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def load(self) -> FirstVaultPrecondition | None:
        with self._locked():
            if not self.path.exists():
                return None
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError) as exc:
                raise FirstVaultBootstrapError(
                    "first-vault bootstrap precondition cannot be read safely"
                ) from exc
            if not isinstance(payload, dict):
                raise FirstVaultBootstrapError("first-vault bootstrap precondition is not an object")
            return FirstVaultPrecondition.from_payload(payload)

    def issue(
        self,
        *,
        principal_id: str,
        path: Path,
        vault_name: str | None,
        machine_role: str,
        remember: bool,
        confirm: bool,
        snapshot: RegistrySnapshot,
    ) -> tuple[str, FirstVaultPrecondition]:
        if not confirm:
            raise FirstVaultBootstrapError(
                "explicit initialization confirmation is required before bootstrap"
            )
        if snapshot.registrations or snapshot.default_vault_binding_id is not None:
            raise FirstVaultBootstrapError("first-vault bootstrap requires an empty registry")
        if snapshot.settings_rebind is not None:
            raise FirstVaultBootstrapError(
                "first-vault bootstrap requires no compatibility state"
            )
        now = float(self._clock())
        token = secrets.token_urlsafe(32)
        record = FirstVaultPrecondition(
            token_digest=hashlib.sha256(token.encode("utf-8")).hexdigest(),
            principal_id=principal_id,
            target_fingerprint=target_fingerprint(path),
            request_fingerprint=request_fingerprint(
                path,
                vault_name=vault_name,
                machine_role=machine_role,
                remember=remember,
                confirm=confirm,
            ),
            registry_revision=snapshot.revision,
            compatibility_revision=snapshot.revision,
            confirmation=confirm,
            issued_at=now,
            expires_at=now + FIRST_VAULT_BOOTSTRAP_TTL_SECONDS,
            state="issued",
        )
        with self._locked():
            self._write_locked(record)
        return token, record

    def require(
        self,
        token: str,
        *,
        principal_id: str,
        path: Path,
        vault_name: str | None,
        machine_role: str,
        remember: bool,
        confirm: bool,
        snapshot: RegistrySnapshot,
        allow_recovery: bool = True,
    ) -> FirstVaultPrecondition:
        if not token or not token.strip():
            raise FirstVaultBootstrapError("first-vault bootstrap precondition is required")
        record = self.load()
        if record is None:
            raise FirstVaultBootstrapError("first-vault bootstrap precondition is unknown")
        expected_digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        if not hmac.compare_digest(expected_digest, record.token_digest):
            raise FirstVaultBootstrapError("first-vault bootstrap precondition is invalid")
        if record.state == "consumed":
            raise FirstVaultBootstrapError("first-vault bootstrap precondition was already consumed")
        if record.state == "failed" and not allow_recovery:
            raise FirstVaultBootstrapError("first-vault bootstrap precondition was rejected")
        if float(self._clock()) >= record.expires_at:
            raise FirstVaultBootstrapError("first-vault bootstrap precondition expired")
        if record.principal_id != principal_id:
            raise FirstVaultBootstrapError("first-vault bootstrap principal mismatch")
        if record.target_fingerprint != target_fingerprint(path):
            raise FirstVaultBootstrapError("first-vault bootstrap target mismatch")
        if record.request_fingerprint != request_fingerprint(
            path,
            vault_name=vault_name,
            machine_role=machine_role,
            remember=remember,
            confirm=confirm,
        ):
            raise FirstVaultBootstrapError("first-vault bootstrap request mismatch")
        if not confirm or not record.confirmation:
            raise FirstVaultBootstrapError("explicit initialization confirmation is required")
        if snapshot.registrations or snapshot.default_vault_binding_id is not None:
            if not (
                allow_recovery
                and record.state in {"reserved", "content_effected"}
                and record.binding_id is not None
                and set(snapshot.registrations) == {record.binding_id}
                and snapshot.default_vault_binding_id == record.binding_id
                and snapshot.revision == record.registry_revision + 1
            ):
                raise FirstVaultBootstrapError("first-vault bootstrap registry is no longer empty")
        elif snapshot.revision != record.registry_revision:
            raise FirstVaultBootstrapError("first-vault bootstrap registry revision changed")
        if snapshot.settings_rebind is not None:
            raise FirstVaultBootstrapError("first-vault bootstrap compatibility state changed")
        return record

    def runtime_view(self, record: FirstVaultPrecondition) -> FirstVaultRuntimeView:
        return FirstVaultRuntimeView(self, record)

    def bind(self, record: FirstVaultPrecondition, binding_id: str) -> FirstVaultPrecondition:
        updated = FirstVaultPrecondition(**{**record.__dict__, "state": "reserved", "binding_id": binding_id})
        with self._locked():
            current = self._load_locked()
            self._assert_same_attempt(current, record)
            self._write_locked(updated)
        return updated

    def content_effected(
        self,
        record: FirstVaultPrecondition,
        *,
        vault_id: str,
        local_instance_id: str,
    ) -> FirstVaultPrecondition:
        updated = FirstVaultPrecondition(
            **{
                **record.__dict__,
                "state": "content_effected",
                "vault_id": vault_id,
                "local_instance_id": local_instance_id,
            }
        )
        with self._locked():
            current = self._load_locked()
            self._assert_same_attempt(current, record)
            self._write_locked(updated)
        return updated

    def complete(
        self,
        record: FirstVaultPrecondition,
        *,
        vault_id: str,
        local_instance_id: str,
    ) -> FirstVaultPrecondition:
        updated = FirstVaultPrecondition(
            **{
                **record.__dict__,
                "state": "consumed",
                "vault_id": vault_id,
                "local_instance_id": local_instance_id,
            }
        )
        with self._locked():
            current = self._load_locked()
            self._assert_same_attempt(current, record)
            self._write_locked(updated)
        return updated

    def fail(self, record: FirstVaultPrecondition) -> None:
        updated = FirstVaultPrecondition(**{**record.__dict__, "state": "failed"})
        with self._locked():
            current = self._load_locked()
            self._assert_same_attempt(current, record)
            self._write_locked(updated)

    def _load_locked(self) -> FirstVaultPrecondition | None:
        if not self.path.exists():
            return None
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise FirstVaultBootstrapError("first-vault bootstrap precondition is not an object")
        return FirstVaultPrecondition.from_payload(payload)

    def _assert_same_attempt(
        self,
        current: FirstVaultPrecondition | None,
        expected: FirstVaultPrecondition,
    ) -> None:
        if current is None or current.token_digest != expected.token_digest:
            raise FirstVaultBootstrapError("first-vault bootstrap attempt changed concurrently")

    def _write_locked(self, record: FirstVaultPrecondition) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, raw_path = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=self.path.parent)
        temporary = Path(raw_path)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(record.as_payload(), handle, sort_keys=True, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            directory_fd = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            temporary.unlink(missing_ok=True)


@dataclass(frozen=True)
class FirstVaultRuntimeView:
    """Small adapter passed into the owner runtime; it carries no write authority."""

    store: FirstVaultPreconditionStore
    record: FirstVaultPrecondition

    def validate_for_runtime(
        self, snapshot: RegistrySnapshot, path: Path
    ) -> FirstVaultPrecondition:
        return self.record.validate_for_runtime(snapshot, path)

    def bind(self, record: FirstVaultPrecondition, binding_id: str) -> FirstVaultPrecondition:
        return self.store.bind(record, binding_id)

    def content_effected(
        self,
        record: FirstVaultPrecondition,
        *,
        vault_id: str,
        local_instance_id: str,
    ) -> FirstVaultPrecondition:
        return self.store.content_effected(
            record,
            vault_id=vault_id,
            local_instance_id=local_instance_id,
        )

    def complete(
        self,
        record: FirstVaultPrecondition,
        *,
        vault_id: str,
        local_instance_id: str,
    ) -> FirstVaultPrecondition:
        return self.store.complete(
            record,
            vault_id=vault_id,
            local_instance_id=local_instance_id,
        )

    def fail(self, record: FirstVaultPrecondition) -> None:
        self.store.fail(record)


__all__ = [
    "FIRST_VAULT_BOOTSTRAP_SCHEMA",
    "FIRST_VAULT_BOOTSTRAP_TTL_SECONDS",
    "FirstVaultBootstrapError",
    "FirstVaultPrecondition",
    "FirstVaultPreconditionStore",
    "FirstVaultRuntimeView",
    "canonical_target",
    "request_fingerprint",
    "target_fingerprint",
]
