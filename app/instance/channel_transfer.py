"""Source-owned, replayable channel transfer through the existing owner seams.

The host supplies only its process-stop port; production state transitions,
queue drain, inventory validation, reference repair and ownership stay here.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from app.instance._storage_boundary import _STORAGE_MUTATION_CAPABILITY
from app.instance.binding_effect_lease import BindingEffectLeaseManager
from app.instance.instance_state import (
    DeploymentQuiescenceProof,
    _atomic_private_write,
    _read_private_json,
)
from app.instance.principal_fence import inventory_from_quiescence
from app.instance.settings_rebind import SettingsRebindActivation
from app.instance.vault_registry import (
    CapabilityNotReadyError,
    RegistryError,
    TransferLineage,
    VaultRegistration,
)

if TYPE_CHECKING:
    from app.instance.runtime import InstanceRegistryRuntime

SCHEMA = "agentic-pkm.channel-transfer.v1"
FOREGROUND_FLOOR = "mvr05c.v1"
PHASES = (
    "intent",
    "ingress_closed",
    "rows_drained",
    "compatibility_repaired",
    "producers_stopped",
    "floor_advanced",
    "ownership_reserved",
    "source_retired",
    "destination_registered",
    "ownership_activated",
    "control_released",
    "complete",
)


def _fault_point(phase: str) -> None:
    """Process-failure injection seam, deliberately after each durable phase."""


def require_source_ingress(registry: Any, binding_id: str) -> None:
    intent = registry.load().extensions.get("channelTransfer")
    if isinstance(intent, dict) and intent.get("source_binding_id") == binding_id:
        raise CapabilityNotReadyError("source binding ingress is closed for transfer")


def require_source_root_ingress(root: Path, *, allow_admitted_effect: bool = False) -> None:
    """Fence explicit/native root selectors as well as bearer-selected bindings."""
    from app.instance.vault_registry import VaultRegistryStore

    configured = os.getenv("INSTANCE_VAULT_REGISTRY_PATH", "").strip()
    if not configured:
        return
    registry = VaultRegistryStore(Path(configured))
    snapshot = registry.load()
    intent = snapshot.extensions.get("channelTransfer")
    if not isinstance(intent, dict):
        return
    source_id = intent.get("source_binding_id")
    if not isinstance(source_id, str):
        raise RegistryError("transfer source identity is invalid")
    source = snapshot.registrations.get(source_id) or snapshot.removal_tombstones.get(source_id)
    if source is None:
        raise RegistryError("transfer source root cannot be resolved")
    selected = root.expanduser().resolve(strict=False)
    retired = Path(source.path).expanduser().resolve(strict=False)
    same_root = selected == retired or selected.is_relative_to(retired)
    if not same_root:
        # Case aliases and filesystem aliases must not escape a retired root.
        try:
            same_root = any(
                ancestor.samefile(retired)
                for ancestor in (selected, *selected.parents)
                if ancestor.exists()
            )
        except OSError as exc:
            raise RegistryError("transfer source root identity is unavailable") from exc
    if same_root:
        if allow_admitted_effect:
            from app.instance.scalar_binding_runtime import current_binding_effect_runtime

            admitted = current_binding_effect_runtime()
            if (
                admitted is not None
                and admitted.vault_binding_id == source_id
                and admitted.root.resolve() == retired
            ):
                return
        raise CapabilityNotReadyError("source binding ingress is closed for transfer")


class SourceChannelLifecycle:
    """Reuse the canonical stopped-window proof, never a caller-authored producer list.

    ``stop_and_prove`` is the host process-control port. It must drive the existing
    deployment/native stopped-window protocol and return its canonical proof.
    With no port, only an already established stopped window can be consumed.
    """

    def __init__(
        self, *, stop_and_prove: Callable[[], DeploymentQuiescenceProof] | None = None
    ) -> None:
        self.stop_and_prove = stop_and_prove

    def drain(
        self,
        runtime: InstanceRegistryRuntime,
        source: VaultRegistration,
        *,
        include_compatibility: bool = False,
    ) -> dict[str, Any]:
        from app.workers.outbox_worker import drain_binding_outbox

        try:
            return drain_binding_outbox(
                vault_root=Path(source.path),
                binding_id=source.vault_binding_id,
                include_compatibility=include_compatibility,
            )
        except Exception as exc:
            raise CapabilityNotReadyError(
                "source queues are not drained; ownership is unchanged"
            ) from exc

    def repair_compatibility(
        self, runtime: InstanceRegistryRuntime, source: VaultRegistration
    ) -> None:
        if runtime.registry.load().settings_rebind is not None:
            SettingsRebindActivation.from_environment(runtime.registry).retire_for_transfer(
                source.vault_binding_id
            )

    def quiesce(
        self, runtime: InstanceRegistryRuntime, *, revalidate: bool = False
    ) -> dict[str, Any]:
        from app.instance.runtime import _load_deployment_quiescence_proof

        root = runtime.ledger.root
        proof = (
            self.stop_and_prove()
            if self.stop_and_prove is not None and not revalidate
            else _load_deployment_quiescence_proof(root / "deployment-quiescence-proof.json")
        )
        proof.require_canonical_authority(
            channel_id=runtime.layout.channel_id,
            host_global_root=root,
            owner_receipt_path=root / "legacy-owner-inventory.json",
        )
        repository = Path(__file__).resolve().parents[2]
        inventory = inventory_from_quiescence(
            channel_id=runtime.layout.channel_id,
            quiescence_proof=asdict(proof),
            legacy_owner_inventory=_read_private_json(root / "legacy-owner-inventory.json"),
            compose_path=repository / "docker-compose.yaml",
            repo_root=repository,
        )
        payload = inventory.as_payload()
        payload["quiescence_nonce"] = proof.nonce
        # These effects run inside the discovered source processes. The canonical
        # host inventory proves all Python/Compose producers stopped, including
        # CLI invocations, and the restart fence covers the same population.
        payload["vault_bound_effects"] = {
            "api_cli_ingress": ["api", "cli", "companion-proxy"],
            "compatibility_watcher": ["watcher"],
            "scalar_worker_outbox_ingest": ["worker", "watcher"],
            "settings_reload": ["api", "watcher", "cli"],
            "heimdal_projection": ["heimdal-capture-watch", "worker"],
            "bootstrap_lifecycle": ["bootstrap-init"],
        }
        roles = {producer.role for producer in inventory.producers}
        if any(
            not set(required).issubset(roles)
            for required in payload["vault_bound_effects"].values()
        ):
            raise CapabilityNotReadyError("source lifecycle inventory is incomplete")
        return payload

    def release(self, runtime: InstanceRegistryRuntime, *, nonce: str, transfer_id: str) -> None:
        """Release only this transfer's stopped window after ownership activation.

        The retained source registry intent fences the retired binding after the
        temporary host-wide deployment fence is removed, so destination/global
        startup can proceed. The existing durable cleanup protocol owns deletion.
        """
        from app.instance.runtime import (
            _deployment_admission_locked,
            _deployment_lease_path,
            _legacy_deployment_lease_path,
            _deployment_fence_path,
            _read_deployment_lease,
            _read_legacy_deployment_lease,
            _replace_private_json,
            _compatibility_block_payload,
            _complete_instance_state_deployment_cleanup,
        )

        root = runtime.ledger.root
        with _deployment_admission_locked(root):
            public, compatibility = (
                _deployment_lease_path(root),
                _legacy_deployment_lease_path(root),
            )
            if not public.exists() and not compatibility.exists():
                if _deployment_fence_path(root, runtime.layout.channel_id).exists():
                    raise RegistryError("transfer cleanup has an orphan restart fence")
                return
            lease = (
                _read_deployment_lease(root)
                if public.exists()
                else _read_legacy_deployment_lease(root)
            )
            if lease.get("nonce") != nonce or lease.get("channel_id") != runtime.layout.channel_id:
                raise RegistryError("transfer cannot release another controller's stopped window")
            if lease.get("phase") != "cleanup":
                self.quiesce(runtime, revalidate=True)
                result = {
                    "channel": runtime.layout.channel_id,
                    "restart_fence_cleared": True,
                    "transfer_id": transfer_id,
                    "transfer_complete": True,
                }
                lease = {**lease, "phase": "cleanup", "result": result}
                _replace_private_json(public, lease)
                _replace_private_json(compatibility, _compatibility_block_payload(lease))
            else:
                result_payload = lease.get("result")
                if (
                    not isinstance(result_payload, dict)
                    or result_payload.get("transfer_id") != transfer_id
                ):
                    raise RegistryError("transfer cleanup receipt belongs to another operation")
            _complete_instance_state_deployment_cleanup(root)


class ChannelTransferCoordinator:
    def __init__(
        self,
        source: InstanceRegistryRuntime,
        destination: InstanceRegistryRuntime,
        stop_and_prove: Callable[[], DeploymentQuiescenceProof] | None = None,
    ) -> None:
        self.source, self.destination = source, destination
        self.lifecycle = SourceChannelLifecycle(stop_and_prove=stop_and_prove)
        self.path = source.layout.root / "channel-transfer.json"

    def _validate_participants(self) -> None:
        if (
            self.source.ledger.root.resolve() != self.destination.ledger.root.resolve()
            or self.source.layout.channel_id == self.destination.layout.channel_id
            or self.source.registry.path.resolve() == self.destination.registry.path.resolve()
        ):
            raise RegistryError(
                "transfer requires distinct channels/registries and one host ledger"
            )

    @contextmanager
    def _locked(self) -> Iterator[None]:
        import fcntl

        path = self.path.with_suffix(".lock")
        descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            os.close(descriptor)

    def _save(self, intent: dict[str, Any], phase: str) -> None:
        intent["phase"] = phase
        _atomic_private_write(self.path, json.dumps(intent, sort_keys=True).encode())
        _fault_point(phase)

    def transfer(self, binding_id: str) -> str:
        self._validate_participants()
        with self._locked():
            if self.path.exists():
                intent = self._load()
                if intent["source_binding_id"] != binding_id:
                    raise RegistryError("another source transfer requires reconciliation")
            else:
                if (
                    self.lifecycle.stop_and_prove is None
                    and not (self.source.ledger.root / "deployment-quiescence-proof.json").exists()
                ):
                    raise CapabilityNotReadyError(
                        "source stopped-window lifecycle is required before transfer"
                    )
                source = self.source.require_initialized(binding_id)
                destination_binding_id = f"binding-{uuid4()}"
                self.source.ledger.require_transfer_destination(
                    source_binding_id=binding_id,
                    destination_channel_id=self.destination.layout.channel_id,
                    destination_binding_id=destination_binding_id,
                )
                snapshot = self.source.registry.load()
                if snapshot.registrations.get(binding_id) != source:
                    raise RegistryError("source changed while preparing transfer")
                with self.source.ledger.active_binding_fence(
                    binding_id, channel_id=self.source.layout.channel_id, root=Path(source.path)
                ):
                    if "bindingRevision" not in source.extensions:
                        source = replace(
                            source,
                            extensions={**source.extensions, "bindingRevision": snapshot.revision},
                        )
                        self.source.registry.commit_state(
                            registrations={**snapshot.registrations, binding_id: source},
                            expected_revision=snapshot.revision,
                            _capability=_STORAGE_MUTATION_CAPABILITY,
                        )

                intent = {
                    "schema": SCHEMA,
                    "source_channel": self.source.layout.channel_id,
                    "destination_channel": self.destination.layout.channel_id,
                    "source_instance": self.source.registry.load().app_install_id,
                    "destination_instance": self.destination.registry.load().app_install_id,
                    "source_binding_id": binding_id,
                    "destination_binding_id": destination_binding_id,
                    "source": asdict(source),
                    "compatibility_source": (self.source.registry.load().settings_rebind or {}).get(
                        "candidateBindingId"
                    )
                    == binding_id,
                }
                self._save(intent, "intent")
            return self._resume(intent)

    def recover(self) -> str:
        self._validate_participants()
        with self._locked():
            return self._resume(self._load())

    def _load(self) -> dict[str, Any]:
        intent = _read_private_json(self.path)
        source_record = intent.get("source")
        if not isinstance(source_record, dict):
            raise RegistryError("transfer intent has no source identity")
        if (
            intent.get("schema") != SCHEMA
            or intent.get("phase") not in PHASES
            or intent.get("source_channel") != self.source.layout.channel_id
            or intent.get("destination_channel") != self.destination.layout.channel_id
            or intent.get("source_instance") != self.source.registry.load().app_install_id
            or intent.get("destination_instance") != self.destination.registry.load().app_install_id
            or intent.get("source_binding_id") != source_record.get("vault_binding_id")
        ):
            raise RegistryError("source-owned transfer intent does not match participants")
        return intent

    def _resume(self, intent: dict[str, Any]) -> str:
        source = VaultRegistration(**intent["source"])
        source_id, destination_id = source.vault_binding_id, intent["destination_binding_id"]

        def before(phase: str) -> bool:
            return PHASES.index(intent["phase"]) < PHASES.index(phase)

        if before("ingress_closed"):
            snapshot = self.source.registry.load()
            if snapshot.registrations.get(source_id) != source:
                raise RegistryError("source identity or provenance changed after transfer intent")
            self.source.registry.commit_state(
                registrations=snapshot.registrations,
                extensions={
                    **snapshot.extensions,
                    "channelTransfer": {
                        "schema": SCHEMA,
                        "source_binding_id": source_id,
                        "destination_binding_id": destination_id,
                    },
                },
                expected_revision=snapshot.revision,
                _capability=_STORAGE_MUTATION_CAPABILITY,
            )
            self._save(intent, "ingress_closed")
        if before("rows_drained"):
            intent["drain_receipt"] = self.lifecycle.drain(
                self.source, source, include_compatibility=intent["compatibility_source"]
            )
            self._save(intent, "rows_drained")
        if before("compatibility_repaired"):
            self.lifecycle.repair_compatibility(self.source, source)
            self._save(intent, "compatibility_repaired")
        if before("producers_stopped"):
            intent["inventory"] = self.lifecycle.quiesce(self.source)
            # Compatibility repair and watcher shutdown can emit final source
            # events. Drain them under the original ID before the floor moves.
            intent["final_drain_receipt"] = self.lifecycle.drain(
                self.source, source, include_compatibility=intent["compatibility_source"]
            )
            self._save(intent, "producers_stopped")
        # Revalidate the stopped proof on every resumed run. A missing fence or
        # restarted source never reaches a new ownership transition.
        if before("ownership_activated"):
            self.lifecycle.quiesce(self.source, revalidate=True)
        if before("floor_advanced"):
            for runtime in (self.source, self.destination):
                runtime.registry.advance_foreground_ownership_floor(
                    _capability=_STORAGE_MUTATION_CAPABILITY
                )
            self._save(intent, "floor_advanced")
        if before("ownership_reserved"):
            reservation = self.source.ledger.load().transfer
            if reservation is None:
                if self.source.registry.load().registrations.get(source_id) != source:
                    raise RegistryError(
                        "source identity or provenance changed before ownership reservation"
                    )
                leases = BindingEffectLeaseManager.for_runtime(
                    registry_store=self.source.registry,
                    ownership_root=self.source.ledger.root,
                    state_root=self.source.layout.root / "binding-effect-leases",
                )
                with leases.exclusive_change(
                    source_id, channel_id=self.source.layout.channel_id, root=Path(source.path)
                ):
                    # All shared foreground/worker effects are out before source
                    # ownership is withdrawn. No effect can acquire it afterwards.
                    reservation = self.source.ledger.begin_transfer(
                        source_binding_id=source_id,
                        destination_channel_id=self.destination.layout.channel_id,
                        destination_binding_id=destination_id,
                        _capability=_STORAGE_MUTATION_CAPABILITY,
                    )
            if (
                reservation.source_binding_id != source_id
                or reservation.source_channel_id != self.source.layout.channel_id
                or reservation.destination_binding_id != destination_id
                or reservation.destination_channel_id != self.destination.layout.channel_id
            ):
                raise RegistryError("ownership reservation belongs to another transfer")
            intent["transfer_id"] = reservation.transfer_id
            intent["lineage"] = asdict(
                TransferLineage(
                    source_id,
                    destination_id,
                    source.local_instance_id,
                    source.vault_id,
                    self.source.layout.channel_id,
                    self.destination.layout.channel_id,
                    self.source.registry.load().revision + 1,
                    self.destination.registry.load().revision + 1,
                    reservation.transfer_id,
                )
            )
            self._save(intent, "ownership_reserved")
        lineage = TransferLineage(**intent["lineage"])
        if before("source_retired"):
            snapshot = self.source.registry.load()
            if source_id in snapshot.registrations:
                if snapshot.registrations[source_id] != source:
                    raise RegistryError("source identity or provenance changed before retirement")
                self.source.registry.remove_registration(
                    source_id,
                    clear_default=snapshot.default_vault_binding_id == source_id,
                    transfer_lineage=lineage,
                    expected_revision=snapshot.revision,
                    _capability=_STORAGE_MUTATION_CAPABILITY,
                )
            elif (
                source_id not in snapshot.removal_tombstones
                or lineage not in snapshot.transfer_lineage
            ):
                raise RegistryError("source retirement is not recoverable")
            self._save(intent, "source_retired")
        if before("destination_registered"):
            snapshot = self.destination.registry.load()
            registration = replace(
                source,
                vault_binding_id=destination_id,
                ref=f"transfer:{destination_id}",
                extensions={
                    **source.extensions,
                    "provenance": "channel_transfer",
                    "bindingRevision": 1,
                },
            )
            if destination_id not in snapshot.registrations:
                self.destination.registry.commit_state(
                    registrations={**snapshot.registrations, destination_id: registration},
                    transfer_lineage=(*snapshot.transfer_lineage, lineage),
                    expected_revision=snapshot.revision,
                    _capability=_STORAGE_MUTATION_CAPABILITY,
                )
            elif (
                snapshot.registrations[destination_id] != registration
                or lineage not in snapshot.transfer_lineage
            ):
                raise RegistryError("destination identity or lineage diverged")
            self._save(intent, "destination_registered")
        if before("ownership_activated"):
            owner = self.source.ledger.active_owner(destination_id)
            if owner is None:
                self.source.ledger.activate_transfer(_capability=_STORAGE_MUTATION_CAPABILITY)
            elif owner.channel_id != self.destination.layout.channel_id:
                raise RegistryError("destination ownership diverged")
            self._save(intent, "ownership_activated")
        if before("control_released"):
            self.lifecycle.release(
                self.source,
                nonce=intent["inventory"]["quiescence_nonce"],
                transfer_id=intent["transfer_id"],
            )
            self._save(intent, "control_released")
        if before("complete"):
            self._save(intent, "complete")
        return destination_id
