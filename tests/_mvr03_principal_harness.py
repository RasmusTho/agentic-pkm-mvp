"""Shared MVR-03 harness: run the real principal cutover on top of an MVR-02 registry.

Like the MVR-02 harness this deliberately drives *production* producers rather than seeding
state: the fence inventory is derived from the real `docker-compose.yaml`, the floor is
recorded through `record_principal_floor`, and the delegated role is written through
`LocalOperatorPrincipalStore.bootstrap`. A test that skipped those would prove the ordering
rule against a fiction.
"""

from __future__ import annotations

import json
from contextlib import redirect_stdout
from io import StringIO
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
)
from app.instance.runtime import (
    local_operator_principal_path,
    open_default_vault_service,
    open_local_operator_principal_store,
)
from app.instance.runtime import _finish_instance_state_deployment
from app.instance.runtime import main as instance_runtime_main
from tests._mvr_default_vault_harness import (
    REPO_ROOT,
    active_runtime,
    deployment_authority,
)
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


def record_floor_through_cli(runtime, *, channel_id: str = "prod") -> dict:
    """Record the floor through the shipped production producer, not a direct call.

    This drives the real `principal-record-floor` command with the same inputs the
    deployment wrapper passes it: the MVR-01B deployment lease in `proved` phase, that
    window's quiescence proof, its drained legacy-owner inventory, and the mounted compose
    policy path. If the harness called `record_principal_floor` directly, the tests would
    pass while no operator command could ever record the floor -- the exact
    invariant-without-producers defect `AGENTS.md :: Required rules` names.

    The stopped window is left open (no `deployment-finish`) exactly as the wrapper does
    around the MVR-01C cutover, then closed by the caller.
    """

    proof, inventory_path = deployment_authority(
        runtime, runtime.layout.root / "missing-legacy.md"
    )
    buffer = StringIO()
    with redirect_stdout(buffer):
        code = instance_runtime_main(
            [
                "principal-record-floor",
                "--channel",
                channel_id,
                "--registry-path",
                str(runtime.layout.registry_path),
                "--host-global-root",
                str(runtime.ledger.root),
                "--inventory-path",
                str(inventory_path),
                "--quiescence-proof-path",
                str(runtime.ledger.root / "deployment-quiescence-proof.json"),
                "--compose-base",
                str(REPO_ROOT / "docker-compose.yaml"),
                "--native-producer-root",
                str(REPO_ROOT),
                "--consumer",
                "bootstrap-init",
            ]
        )
    payload = json.loads(buffer.getvalue().strip().splitlines()[-1])
    payload["_exit_code"] = code
    _finish_instance_state_deployment(
        channel=channel_id,
        instance_state_root=runtime.layout.root.parent,
        host_global_root=runtime.ledger.root,
        legacy_path=runtime.layout.root / "missing-legacy.md",
        inventory_path=inventory_path,
        backup_root=runtime.layout.root / "principal-cutover-backup",
        restore_root=None,
        quiescence_proof=proof,
    )
    return payload


def run_principal_cutover(
    runtime,
    *,
    posture: AuthPosture,
    existing_install: bool = True,
    channel_id: str = "prod",
) -> LocalOperatorPrincipalRecord:
    """Fence -> floor -> first durable role write, in that order."""

    receipt = record_floor_through_cli(runtime, channel_id=channel_id)
    assert receipt["_exit_code"] == 0, receipt
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
    "record_floor_through_cli",
    "principal_record_path",
    "principal_store",
    "provisioned_instance",
    "quiesced_producers",
    "run_principal_cutover",
]
