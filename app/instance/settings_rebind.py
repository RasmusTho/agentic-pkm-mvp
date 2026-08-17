"""Dormant, durable SETTINGS-05 rebind record.

This module deliberately owns persistence and recovery only.  It has no picker,
API, watcher, or vault-root side effects; SETTINGS-05B/05C own those activation
paths.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping


SETTINGS_REBIND_SCHEMA = "settings_rebind.v1"
MINIMUM_SETTINGS_REBIND_RUNTIME_KEY = "minimum_settings_rebind_runtime"
MINIMUM_SETTINGS_REBIND_RUNTIME = "1"
_PHASES = frozenset({"dormant", "prepared", "committed", "no_lifecycle"})
_POSTURES = frozenset({"dormant", "watcher", "no_lifecycle"})


class SettingsRebindError(RuntimeError):
    """A SETTINGS-05 protected-state record is malformed or unsafe."""


def _canonical_payload(value: Mapping[str, object]) -> bytes:
    payload = dict(value)
    payload.pop("checksum", None)
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def checksum_for(value: Mapping[str, object]) -> str:
    return hashlib.sha256(_canonical_payload(value)).hexdigest()


@dataclass(frozen=True)
class SettingsRebindRecord:
    desired_revision: int
    applied_revision: int
    phase: str
    lifecycle_posture: str
    prior_binding_id: str | None
    candidate_binding_id: str | None

    def as_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema": SETTINGS_REBIND_SCHEMA,
            "desiredRevision": self.desired_revision,
            "appliedRevision": self.applied_revision,
            "phase": self.phase,
            "lifecyclePosture": self.lifecycle_posture,
            "priorBindingId": self.prior_binding_id,
            "candidateBindingId": self.candidate_binding_id,
        }
        payload["checksum"] = checksum_for(payload)
        return payload

    @classmethod
    def dormant(cls, *, binding_id: str | None = None) -> "SettingsRebindRecord":
        return cls(0, 0, "dormant", "dormant", binding_id, binding_id)

    @classmethod
    def from_payload(cls, value: Mapping[str, object]) -> "SettingsRebindRecord":
        required = {
            "schema", "desiredRevision", "appliedRevision", "phase", "lifecyclePosture",
            "priorBindingId", "candidateBindingId", "checksum",
        }
        if set(value) != required or value.get("schema") != SETTINGS_REBIND_SCHEMA:
            raise SettingsRebindError("settings rebind record schema is invalid")
        desired, applied = value.get("desiredRevision"), value.get("appliedRevision")
        if (
            not isinstance(desired, int) or isinstance(desired, bool) or desired < 0
            or not isinstance(applied, int) or isinstance(applied, bool) or applied < 0
            or applied > desired
        ):
            raise SettingsRebindError("settings rebind revisions are invalid")
        phase, posture = value.get("phase"), value.get("lifecyclePosture")
        if phase not in _PHASES or posture not in _POSTURES:
            raise SettingsRebindError("settings rebind phase or lifecycle posture is invalid")
        if phase == "dormant" and (desired != applied or posture != "dormant"):
            raise SettingsRebindError("dormant settings rebind state must be fully applied")
        if phase == "prepared" and (desired != applied + 1 or posture != "watcher"):
            raise SettingsRebindError("prepared settings rebind state is not one revision ahead")
        if phase == "committed" and (desired != applied or posture != "watcher"):
            raise SettingsRebindError("committed settings rebind state must be fully applied")
        if phase == "no_lifecycle" and (desired != applied or posture != "no_lifecycle"):
            raise SettingsRebindError("no_lifecycle settings rebind state must be fully applied")
        prior, candidate = value.get("priorBindingId"), value.get("candidateBindingId")
        if prior is not None and (not isinstance(prior, str) or not prior.strip()):
            raise SettingsRebindError("settings rebind prior binding is invalid")
        if candidate is not None and (not isinstance(candidate, str) or not candidate.strip()):
            raise SettingsRebindError("settings rebind candidate binding is invalid")
        checksum = value.get("checksum")
        if not isinstance(checksum, str) or checksum != checksum_for(value):
            raise SettingsRebindError("settings rebind checksum is invalid")
        return cls(desired, applied, str(phase), str(posture), prior, candidate)


def validate_settings_rebind_payload(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise SettingsRebindError("settings rebind record must be a mapping")
    record = SettingsRebindRecord.from_payload(value)
    return record.as_payload()


class SettingsRebindStore:
    """Narrow facade over the already-authoritative protected registry store."""

    def __init__(self, registry_store: Any, *, capability: Any) -> None:
        self._registry = registry_store
        self._capability = capability

    def install_dormant(self, *, binding_id: str | None = None) -> SettingsRebindRecord:
        """Atomically install the floor and first authoritative dormant record."""
        self._registry.install_settings_rebind_dormant(
            SettingsRebindRecord.dormant(binding_id=binding_id).as_payload(),
            _capability=self._capability,
        )
        return self.read()

    def read(self) -> SettingsRebindRecord:
        snapshot = self._registry.load()
        if snapshot.settings_rebind is None:
            raise SettingsRebindError("settings rebind record has not been installed")
        return SettingsRebindRecord.from_payload(copy.deepcopy(snapshot.settings_rebind))
