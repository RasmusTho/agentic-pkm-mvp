from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Mapping

from app.instance._storage_boundary import (
    RegistryError,
    _StorageMutationCapability,
)

if TYPE_CHECKING:
    from app.instance.vault_registry import KnownVaultRef, VaultRegistryStore


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
    "reloadRevision",
    "checksum",
}
_LEGACY_FIELDS = _FIELDS - {"reloadRevision"}
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
    reload_revision: int | None = 0

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
            "reloadRevision": 0 if self.reload_revision is None else self.reload_revision,
        }
        payload["checksum"] = _checksum(payload)
        return payload

    @classmethod
    def from_payload(cls, value: object) -> SettingsRebindRecord:
        if not isinstance(value, dict) or set(value) not in (_FIELDS, _LEGACY_FIELDS):
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
        if "reloadRevision" not in value:
            # Records written before reload completion became durable are
            # intentionally treated as unknown and replayed once on retry.
            reload_revision = None
        else:
            reload_revision = _revision(value.get("reloadRevision"), name="reload revision")
            if reload_revision > applied:
                raise RegistryError("settings rebind reload revision exceeds applied revision")
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
            reload_revision=reload_revision,
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
    """Narrow facade for the durable SETTINGS-05 compatibility record.

    The watcher owns acknowledgement/drain.  The foreground activation owner
    owns prepare and the one locked selection+binding commit.  Keeping those
    operations here prevents a caller from composing two independent registry
    writes and accidentally exposing a new selection before its rebind phase.
    """

    def __init__(self, registry: VaultRegistryStore) -> None:
        self._registry = registry

    def read(self) -> SettingsRebindRecord:
        value = self._registry.load().settings_rebind
        if value is None:
            raise RegistryError("settings rebind record is not installed")
        return SettingsRebindRecord.from_payload(value)

    def prepare(self, *, candidate_binding_id: str | None) -> SettingsRebindRecord:
        """Prepare the next monotonic compatibility revision.

        The current candidate is the only durable prior binding.  A prepared
        or committed revision cannot be replaced underneath its watcher; the
        caller must wait for that revision to finish and retry from its durable
        result.
        """

        from app.instance._storage_boundary import _STORAGE_MUTATION_CAPABILITY

        snapshot = self._registry.load()
        current = self.read()
        if current.phase == "prepared":
            if current.candidate_binding_id == candidate_binding_id:
                return current
            raise RegistryError("settings rebind already has a prepared revision")
        if current.phase == "committed":
            if current.reload_revision != current.desired_revision:
                raise RegistryError(
                    "settings rebind committed revision is awaiting reload completion"
                )
            # The activation owner checks the watcher receipt before starting
            # the next transition. Once the foreground reload marker is
            # durable, a later selection may prepare the next revision.
        prior = current.candidate_binding_id
        if prior == candidate_binding_id:
            return current
        prepared = SettingsRebindRecord(
            desired_revision=max(current.desired_revision, current.applied_revision) + 1,
            applied_revision=current.applied_revision,
            phase="prepared",
            lifecycle_posture="watcher",
            prior_binding_id=prior,
            candidate_binding_id=candidate_binding_id,
            reload_revision=0,
        )
        updated = self._registry.set_settings_rebind_state(
            prepared.as_payload(),
            expected_revision=snapshot.revision,
            _capability=_STORAGE_MUTATION_CAPABILITY,
        )
        return SettingsRebindRecord.from_payload(updated.settings_rebind)

    def commit_selection(
        self,
        *,
        desired_revision: int,
        selection: KnownVaultRef,
    ) -> SettingsRebindRecord:
        """Atomically commit the prepared binding and compatibility selection."""

        from app.instance._storage_boundary import _STORAGE_MUTATION_CAPABILITY

        snapshot = self._registry.commit_settings_rebind_selection(
            desired_revision=desired_revision,
            selection=selection,
            _capability=_STORAGE_MUTATION_CAPABILITY,
        )
        return SettingsRebindRecord.from_payload(snapshot.settings_rebind)

    def acknowledge_no_lifecycle(
        self,
        *,
        desired_revision: int,
    ) -> SettingsRebindRecord:
        """Complete one already-prepared revision as intentionally unwatched."""

        from app.instance._storage_boundary import _STORAGE_MUTATION_CAPABILITY

        snapshot = self._registry.load()
        if snapshot.settings_rebind is None:
            raise RegistryError("settings rebind record is not installed")
        current = SettingsRebindRecord.from_payload(snapshot.settings_rebind)
        if current.phase == "no_lifecycle":
            if current.desired_revision != desired_revision:
                raise RegistryError("settings rebind no_lifecycle revision mismatch")
            return current
        if current.phase != "prepared":
            raise RegistryError(
                "settings rebind no_lifecycle acknowledgement requires a prepared revision"
            )
        if current.desired_revision != desired_revision:
            raise RegistryError("settings rebind prepared revision changed before acknowledgement")
        acknowledged = replace(
            current,
            applied_revision=current.desired_revision,
            phase="no_lifecycle",
            lifecycle_posture="no_lifecycle",
        )
        updated = self._registry.set_settings_rebind_state(
            acknowledged.as_payload(),
            expected_revision=snapshot.revision,
            _capability=_STORAGE_MUTATION_CAPABILITY,
        )
        return SettingsRebindRecord.from_payload(updated.settings_rebind)

    def reload_once(
        self,
        *,
        desired_revision: int,
        reload_callback: Callable[[], object],
    ) -> SettingsRebindRecord:
        """Run and durably record one SETTINGS-01 reload under the store lock."""

        from app.instance._storage_boundary import _STORAGE_MUTATION_CAPABILITY

        stored = self._registry.complete_settings_rebind_reload(
            desired_revision=desired_revision,
            reload_callback=reload_callback,
            _capability=_STORAGE_MUTATION_CAPABILITY,
        )
        return SettingsRebindRecord.from_payload(stored.settings_rebind)

    def reconcile_no_lifecycle(self) -> SettingsRebindRecord:
        """Converge an absent watcher without preparing or committing a revision."""

        current = self.read()
        if current.phase in {"dormant", "no_lifecycle"}:
            return current
        if current.phase == "prepared":
            return self.acknowledge_no_lifecycle(
                desired_revision=current.desired_revision,
            )
        raise RegistryError(
            "absent watcher cannot reconcile a committed settings rebind revision"
        )


def _activation_fault_point(stage: str) -> None:
    """Test seam for foreground crash recovery; production is a no-op."""

    del stage


class SettingsRebindActivation:
    """Production choose/open transaction for the compatibility binding.

    The API never calls the watcher helper directly.  It records ``prepared``
    and waits for the separately running watcher to publish its durable
    acknowledgement.  The watcher-disabled posture is explicit
    ``no_lifecycle``.  After the locked selection commit, the API waits for a
    completed watcher receipt when a watcher exists, then reloads through the
    existing SETTINGS-01 ingestion entrypoint.
    """

    def __init__(
        self,
        registry: VaultRegistryStore,
        *,
        watcher_state_dir: Path | None = None,
        watcher_enabled: bool | None = None,
        wait_timeout_seconds: float | None = None,
        poll_seconds: float = 0.05,
    ) -> None:
        self.store = SettingsRebindStore(registry)
        self._watcher_state_dir = watcher_state_dir
        self._watcher_enabled_override = watcher_enabled
        self._wait_timeout_seconds = (
            wait_timeout_seconds
            if wait_timeout_seconds is not None
            else float(os.getenv("SETTINGS_REBIND_WAIT_TIMEOUT_SECONDS", "5"))
        )
        self._poll_seconds = max(poll_seconds, 0.01)

    @classmethod
    def from_environment(cls, registry: VaultRegistryStore) -> "SettingsRebindActivation":
        state_dir_raw = os.getenv("WATCHER_STATE_DIR", "").strip()
        state_dir = Path(state_dir_raw).expanduser() if state_dir_raw else None
        enabled_raw = os.getenv("WATCHER_ENABLE", "").strip().lower()
        watcher_path = os.getenv("WATCHER_VAULT_PATH", "").strip()
        enabled = enabled_raw in {"1", "true", "yes", "on"} and bool(watcher_path)
        return cls(registry, watcher_state_dir=state_dir, watcher_enabled=enabled)

    def activate(
        self,
        *,
        selection: KnownVaultRef,
        candidate_binding_id: str,
        candidate_root: Path,
    ) -> SettingsRebindRecord:
        current = self.store.read()
        if current.candidate_binding_id == candidate_binding_id:
            if current.phase in {"dormant", "no_lifecycle"}:
                if current.phase == "no_lifecycle":
                    return self._reload_if_needed(current, candidate_root)
                return current
            if current.phase == "committed":
                self._wait_for_completed_if_enabled(current)
                return self._reload_if_needed(current, candidate_root)

        if current.phase == "committed":
            # A completed committed record is the normal steady state while the
            # watcher remains deployed. Quiesce that prior transition before
            # allowing a new candidate to replace it.
            self._wait_for_completed_if_enabled(current)

        _activation_fault_point("prepare")
        try:
            prepared = self.store.prepare(candidate_binding_id=candidate_binding_id)
        except RegistryError:
            # Another foreground request may have committed this exact target
            # between the read above and prepare.  Its durable commit is the
            # only success receipt the losing request may return.
            observed = self.store.read()
            if (
                observed.phase in {"prepared", "committed"}
                and observed.candidate_binding_id == candidate_binding_id
            ):
                if observed.phase == "committed":
                    self._wait_for_completed_if_enabled(observed)
                    return self._reload_if_needed(observed, candidate_root)
                prepared = observed
            else:
                raise
        if prepared.phase != "prepared":
            return prepared

        if self.watcher_enabled:
            _activation_fault_point("acknowledge")
            self._wait_for_stage(prepared, required_stage="acknowledged")
        else:
            _activation_fault_point("acknowledge")
            prepared = self.store.acknowledge_no_lifecycle(
                desired_revision=prepared.desired_revision
            )

        try:
            committed = self.store.commit_selection(
                desired_revision=prepared.desired_revision,
                selection=selection,
            )
        except RegistryError:
            # A same-target request can win the lock after both callers have
            # observed the prepared revision.  Do not report API success until
            # that winner's commit and watcher resume are durable.
            observed = self.store.read()
            if (
                observed.phase == "committed"
                and observed.candidate_binding_id == candidate_binding_id
                and observed.desired_revision == prepared.desired_revision
            ):
                self._wait_for_completed_if_enabled(observed)
                return self._reload_if_needed(observed, candidate_root)
            raise
        # A commit fault is post-commit: recovery must observe the durable B
        # binding and roll forward, matching the watcher transaction seam.
        _activation_fault_point("commit")

        self._wait_for_completed_if_enabled(committed)
        committed = self._reload_if_needed(committed, candidate_root)
        return committed

    def _wait_for_completed_if_enabled(self, record: SettingsRebindRecord) -> None:
        if self.watcher_enabled:
            _activation_fault_point("resume")
            self._wait_for_stage(record, required_stage="completed")

    def _reload_if_needed(
        self,
        record: SettingsRebindRecord,
        candidate_root: Path,
    ) -> SettingsRebindRecord:
        # Re-read after any watcher wait or commit race.  A concurrent winner
        # may have completed the reload while this caller was waiting.
        current = self.store.read()
        if (
            current.desired_revision == record.desired_revision
            and current.candidate_binding_id == record.candidate_binding_id
        ):
            record = current
        if record.reload_revision == record.desired_revision:
            return record
        # This is deliberately the existing production SETTINGS-01 call site,
        # not a second settings loader.  The registry lock serializes this
        # side effect with same-target callers and records completion durably.
        from app.settings.ingestion import STATE_OK, ingest_settings

        def reload_selected_settings() -> None:
            state = ingest_settings(
                reason="vault_selection_rebind",
                vault_root=candidate_root,
                publish_signal=False,
            )
            if state.state != STATE_OK:
                raise RegistryError(
                    "SETTINGS-01 reload did not complete successfully: "
                    f"state={state.state} error={state.error or 'unknown'}"
                )

        _activation_fault_point("reload")
        completed = self.store.reload_once(
            desired_revision=record.desired_revision,
            reload_callback=reload_selected_settings,
        )
        _activation_fault_point("reload_complete")
        return completed

    @property
    def watcher_enabled(self) -> bool:
        if self._watcher_enabled_override is not None:
            return self._watcher_enabled_override
        return bool(os.getenv("WATCHER_VAULT_PATH", "").strip())

    def _wait_for_stage(
        self,
        record: SettingsRebindRecord,
        *,
        required_stage: str,
    ) -> None:
        if self._watcher_state_dir is None:
            raise RegistryError("enabled settings rebind watcher has no state directory")
        from app.watcher.settings_rebind import (
            load_settings_rebind_watcher_receipt,
            settings_rebind_watcher_receipt_path,
        )

        receipt_path = settings_rebind_watcher_receipt_path(
            self._watcher_state_dir,
            record.desired_revision,
        )
        deadline = time.monotonic() + max(self._wait_timeout_seconds, 0.0)
        while True:
            try:
                receipt = load_settings_rebind_watcher_receipt(receipt_path)
            except FileNotFoundError:
                receipt = None
            if receipt is not None:
                if (
                    receipt.desired_revision != record.desired_revision
                    or receipt.prior_binding_id != record.prior_binding_id
                    or receipt.candidate_binding_id != record.candidate_binding_id
                ):
                    raise RegistryError(
                        "settings rebind watcher receipt does not match durable authority"
                    )
                if required_stage == "acknowledged" or receipt.stage == "completed":
                    return
                if receipt.stage in {"acknowledged", "drained"} and required_stage == "completed":
                    pass
            if time.monotonic() >= deadline:
                raise RegistryError(
                    "settings rebind watcher did not reach "
                    f"{required_stage} for revision {record.desired_revision}"
                )
            time.sleep(self._poll_seconds)


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
