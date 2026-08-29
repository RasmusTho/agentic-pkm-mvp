from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Mapping

from app.instance._storage_boundary import (
    RegistryError,
    _StorageMutationCapability,
)

if TYPE_CHECKING:
    from app.instance.vault_registry import VaultRegistryStore


SETTINGS_REBIND_SCHEMA = "settings_rebind.v1"
SETTINGS_REBIND_SCHEMA_REVISION = 1
MINIMUM_SETTINGS_REBIND_RUNTIME_KEY = "minimum_settings_rebind_runtime"
MINIMUM_SETTINGS_REBIND_RUNTIME = "1"

_FIELDS = {
    "schema",
    "schemaRevision",
    "desiredRevision",
    "appliedRevision",
    "phase",
    "lifecyclePosture",
    "priorBindingId",
    "candidateBindingId",
    "checksum",
}
_PHASE_POSTURES = {
    "dormant": "dormant",
    "prepared": "watcher",
    "committed": "watcher",
    "no_lifecycle": "no_lifecycle",
}


def _checksum(payload: Mapping[str, object]) -> str:
    canonical = json.dumps(
        dict(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _revision(value: object, *, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise RegistryError(f"settings rebind {name} must be a non-negative integer")
    return value


def _binding(value: object, *, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise RegistryError(f"settings rebind {name} must be a non-blank binding id")
    return value


@dataclass(frozen=True)
class SettingsRebindRecord:
    schema_revision: int = SETTINGS_REBIND_SCHEMA_REVISION
    desired_revision: int = 0
    applied_revision: int = 0
    phase: str = "dormant"
    lifecycle_posture: str = "dormant"
    prior_binding_id: str | None = None
    candidate_binding_id: str | None = None

    @classmethod
    def dormant(cls, *, binding_id: str | None = None) -> SettingsRebindRecord:
        return cls(prior_binding_id=binding_id, candidate_binding_id=binding_id)

    def as_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema": SETTINGS_REBIND_SCHEMA,
            "schemaRevision": self.schema_revision,
            "desiredRevision": self.desired_revision,
            "appliedRevision": self.applied_revision,
            "phase": self.phase,
            "lifecyclePosture": self.lifecycle_posture,
            "priorBindingId": self.prior_binding_id,
            "candidateBindingId": self.candidate_binding_id,
        }
        payload["checksum"] = _checksum(payload)
        return payload

    @classmethod
    def from_payload(cls, value: object) -> SettingsRebindRecord:
        if not isinstance(value, dict) or set(value) != _FIELDS:
            raise RegistryError("settings rebind record has an invalid shape")
        if value.get("schema") != SETTINGS_REBIND_SCHEMA:
            raise RegistryError("settings rebind record has an invalid schema")
        schema_revision = _revision(value.get("schemaRevision"), name="schema revision")
        if schema_revision != SETTINGS_REBIND_SCHEMA_REVISION:
            raise RegistryError("settings rebind record has an incompatible schema revision")
        desired = _revision(value.get("desiredRevision"), name="desired revision")
        applied = _revision(value.get("appliedRevision"), name="applied revision")
        if applied > desired:
            raise RegistryError("settings rebind applied revision exceeds desired revision")
        phase = value.get("phase")
        posture = value.get("lifecyclePosture")
        if not isinstance(phase, str) or phase not in _PHASE_POSTURES:
            raise RegistryError("settings rebind record has an invalid phase")
        if posture != _PHASE_POSTURES[phase]:
            raise RegistryError("settings rebind phase and lifecycle posture disagree")
        if phase == "dormant" and (desired != 0 or applied != 0):
            raise RegistryError("dormant settings rebind revisions must be zero")
        if phase == "prepared" and not (desired > applied):
            raise RegistryError("prepared settings rebind requires unapplied desired revision")
        if phase in {"committed", "no_lifecycle"} and desired != applied:
            raise RegistryError("completed settings rebind revisions must match")
        prior = _binding(value.get("priorBindingId"), name="prior binding")
        candidate = _binding(value.get("candidateBindingId"), name="candidate binding")
        supplied_checksum = value.get("checksum")
        if (
            not isinstance(supplied_checksum, str)
            or len(supplied_checksum) != 64
            or supplied_checksum != _checksum({key: value[key] for key in value if key != "checksum"})
        ):
            raise RegistryError("settings rebind checksum is invalid")
        return cls(
            schema_revision=schema_revision,
            desired_revision=desired,
            applied_revision=applied,
            phase=phase,
            lifecycle_posture=posture,
            prior_binding_id=prior,
            candidate_binding_id=candidate,
        )


def provisional_binding_id(value: object) -> str | None:
    """Validate the only pre-floor legacy form and return its stable binding id."""

    if not isinstance(value, dict) or value.get("schema") != SETTINGS_REBIND_SCHEMA:
        raise RegistryError("settings rebind record has an invalid pre-floor shape")
    allowed = {"schema", "prior", "candidate", "applied"}
    if not set(value).issubset(allowed):
        raise RegistryError("settings rebind record has an invalid pre-floor shape")
    binding_ids: set[str] = set()
    for name in ("prior", "candidate", "applied"):
        entry = value.get(name)
        if entry is None:
            continue
        if not isinstance(entry, dict):
            raise RegistryError(f"settings rebind {name} must be a mapping")
        binding_id = _binding(entry.get("vaultBindingId"), name=f"{name} binding")
        if binding_id is None:
            raise RegistryError(f"settings rebind {name} has no provisional binding id")
        binding_ids.add(binding_id)
    if len(binding_ids) > 1:
        raise RegistryError("settings rebind provisional bindings disagree")
    return next(iter(binding_ids), None)


class SettingsRebindStore:
    """Read-only facade for the durable dormant SETTINGS-05A record."""

    def __init__(self, registry: VaultRegistryStore) -> None:
        self._registry = registry

    def read(self) -> SettingsRebindRecord:
        value = self._registry.load().settings_rebind
        if value is None:
            raise RegistryError("settings rebind record is not installed")
        return SettingsRebindRecord.from_payload(value)


def _install_dormant_settings_rebind(
    registry: VaultRegistryStore,
    *,
    binding_id: str | None = None,
    _capability: _StorageMutationCapability,
) -> SettingsRebindRecord:
    """Install only from the proved deployment producer or an explicit test fixture."""

    snapshot = registry.install_settings_rebind_dormant(
        binding_id=binding_id,
        _capability=_capability,
    )
    return SettingsRebindRecord.from_payload(snapshot.settings_rebind)
