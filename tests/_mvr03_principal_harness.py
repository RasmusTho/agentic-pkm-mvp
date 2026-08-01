"""Shared MVR-03 harness: run the real principal cutover on top of an MVR-02 registry.

Like the MVR-02 harness this deliberately drives *production* producers rather than seeding
state: the fence inventory is derived from the real `docker-compose.yaml`, the floor is
recorded through `record_principal_floor`, and the delegated role is written through
`LocalOperatorPrincipalStore.bootstrap`. A test that skipped those would prove the ordering
rule against a fiction.
"""

from __future__ import annotations

from pathlib import Path

from app.instance.local_operator_principal import (
    AuthPosture,
    LocalOperatorPrincipalRecord,
    LocalOperatorPrincipalStore,
    preflight_auth_posture,
)
from app.instance.principal_fence import (
    AuthProducer,
    PrincipalFenceInventory,
    build_fence_inventory,
    discover_auth_producers,
    principal_floor_recorded,
    record_principal_floor,
)
from app.instance.runtime import (
    local_operator_principal_path,
    open_default_vault_service,
    open_local_operator_principal_store,
)
from tests._mvr_default_vault_harness import REPO_ROOT, active_runtime
from tests.helpers.instance_storage_capability import STORAGE_MUTATION_CAPABILITY


def quiesced_producers() -> tuple[tuple[AuthProducer, ...], str]:
    """The real production producer set, marked drained/stopped/restart-fenced."""

    producers, digest = discover_auth_producers(
        compose_path=REPO_ROOT / "docker-compose.yaml",
        repo_root=REPO_ROOT,
    )
    quiesced = tuple(
        AuthProducer(
            name=producer.name,
            role=producer.role,
            source=producer.source,
            enabled=producer.enabled,
            stopped=True,
            restart_fenced=True,
            write_handle_released=True,
        )
        for producer in producers
    )
    return quiesced, digest


def complete_inventory(channel_id: str = "prod") -> PrincipalFenceInventory:
    producers, digest = quiesced_producers()
    return build_fence_inventory(
        channel_id=channel_id,
        producers=producers,
        source_digest=digest,
        operations_fenced=True,
        probe_count=2,
    )


def run_principal_cutover(
    runtime,
    *,
    posture: AuthPosture,
    existing_install: bool = True,
    channel_id: str = "prod",
) -> LocalOperatorPrincipalRecord:
    """Fence -> floor -> first durable role write, in that order."""

    record_principal_floor(
        runtime.registry,
        inventory=complete_inventory(channel_id),
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    assert principal_floor_recorded(runtime.registry)
    store = open_local_operator_principal_store(runtime.layout.registry_path)
    return store.bootstrap(
        credential_fingerprint=posture.credential_fingerprint,
        subjects=preflight_auth_posture(posture),
        migration_provenance=posture.migration_provenance(existing_install=existing_install),
        floor_recorded=True,
        _capability=STORAGE_MUTATION_CAPABILITY,
    )


def principal_store(runtime) -> LocalOperatorPrincipalStore:
    return open_local_operator_principal_store(runtime.layout.registry_path)


def principal_record_path(runtime) -> Path:
    return local_operator_principal_path(runtime.layout.registry_path)


def provisioned_instance(
    tmp_path: Path,
    *,
    posture: AuthPosture | None = None,
    extra_roots: tuple[str, ...] = (),
    set_instance_default: bool = True,
):
    """An authoritative registry plus a provisioned delegated operator role.

    The instance default is set through the MVR-02 production service rather than written
    into the registry directly, so the "no selection resolves the explicit default" path is
    exercised against real state.
    """

    runtime, first, extra = active_runtime(tmp_path, extra_roots=extra_roots)
    if set_instance_default:
        open_default_vault_service(runtime.layout.registry_path).set(
            first.vault_binding_id
        )
    record = run_principal_cutover(
        runtime,
        posture=posture
        or AuthPosture(
            configured_credentials=0,
            credential_fingerprint=None,
            loopback_listener_proven=True,
            companion_proxy_configured=False,
        ),
    )
    return runtime, first, extra, record


__all__ = [
    "complete_inventory",
    "principal_record_path",
    "principal_store",
    "provisioned_instance",
    "quiesced_producers",
    "run_principal_cutover",
]
