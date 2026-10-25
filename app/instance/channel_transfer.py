"""Read-only source ingress plus transfer phase/fault identifiers.

Private transfer effects remain in the approved InstanceRegistryRuntime owner.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from app.instance.vault_registry import CapabilityNotReadyError, RegistryError

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
    # Admission is a read, including for cached filesystem ports. It must never
    # initialize missing authority or repair a last-good registry behind a probe.
    snapshot = registry.read_existing()
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
