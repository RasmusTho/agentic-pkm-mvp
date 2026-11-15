"""Shared MVR-06C harness: initialized bindings, relocation targets, and the dormant
multi-binding supervisor, all through shipped producers.

Registrations come from ``production_register`` on an owner-native initialized vault, so
their logical ``vault_id`` and local-clone ``local_instance_id`` are the vault marker's own;
background enrollment goes through the governed admin service; relocation goes through
``InstanceRegistryRuntime.relocate``. Nothing here writes the registry, intent, journal,
or ledger directly.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from app.instance.background_supervisor import (
    _MVR06C_MULTI_BINDING_HARNESS,
    BackgroundLifecycleSupervisor,
)
from app.instance.binding_effect_lease import (
    BindingEffectLeaseError,
    BindingEffectLeaseManager,
)
from app.instance.vault_registry import VaultRegistration
from tests._mvr06b_handoff_harness import admin
from tests.helpers.vault_settings import initialize_test_vault


def initialized_registration(runtime, root: Path) -> VaultRegistration:
    """An owner-native initialized vault registered through the production producer."""

    root.mkdir(parents=True, exist_ok=True)
    initialize_test_vault(root)
    return runtime.production_register(root, producer="api")


def enroll_only(runtime, binding_id: str) -> None:
    """Governed explicit singleton intent naming ``binding_id`` (production admin service)."""

    from app.instance.background_supervisor import stored_intent

    service = admin(runtime)
    for member in stored_intent(runtime.registry.load()).effective_binding_ids():
        if member != binding_id:
            service.remove(member)
    service.add(binding_id)


def copy_vault(source: Path, destination: Path) -> Path:
    """The same vault, cloned byte-for-byte to a new physical root (marker included)."""

    shutil.copytree(source, destination)
    return destination


def leases(runtime) -> BindingEffectLeaseManager:
    return BindingEffectLeaseManager.for_runtime(
        registry_store=runtime.registry,
        ownership_root=runtime.ledger.root,
        state_root=runtime.layout.root / "binding-effect-leases",
    )


def shared_refused(runtime, binding_id: str, root: Path) -> bool:
    try:
        with leases(runtime).shared_effect(
            binding_id, channel_id=runtime.layout.channel_id, root=root, timeout=0.5
        ):
            return False
    except BindingEffectLeaseError:
        return True


def harness_supervisor(
    runtime, binding_ids: tuple[str, ...], consumer: str = "watcher"
) -> BackgroundLifecycleSupervisor:
    """The internal capability-gated many-binding production supervisor."""

    return BackgroundLifecycleSupervisor.for_runtime(
        registry_path=runtime.layout.registry_path,
        ownership_root=runtime.ledger.root,
        channel_id=runtime.layout.channel_id,
        consumer=consumer,
        internal_binding_ids=binding_ids,
        _harness_capability=_MVR06C_MULTI_BINDING_HARNESS,
    )


__all__ = [
    "copy_vault",
    "enroll_only",
    "harness_supervisor",
    "initialized_registration",
    "leases",
    "shared_refused",
]
