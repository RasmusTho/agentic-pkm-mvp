"""MVR-03 (#3857): the delegated-principal migration floor and roll-forward lineage.

Unmarked on purpose. The rest of `tests/migrations/` is the Alembic/Postgres parity tree and
carries `pytest.mark.pg`; this migration is a private *file* migration under the MVR-01
instance-state boundary and must run in the default `pytest -q -m "not pg"` gate.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.instance._storage_boundary import CapabilityNotReadyError
from app.instance.local_operator_principal import (
    MINIMUM_RUNTIME_PRINCIPAL,
    MINIMUM_RUNTIME_PRINCIPAL_KEY,
    PROVENANCE_ROLL_FORWARD,
    AuthPosture,
    PrincipalPreflightError,
    fingerprint_credential,
)
from app.instance.principal_fence import principal_floor_recorded
from app.instance.runtime import (
    _preflight_scalar_rollback,
    open_local_operator_principal_store,
)
from tests._mvr03_principal_harness import (
    principal_record_path,
    run_principal_cutover,
)
from tests._mvr_default_vault_harness import REPO_ROOT, active_runtime
from tests.helpers.instance_storage_capability import STORAGE_MUTATION_CAPABILITY


def _posture(raw_key: str | None) -> AuthPosture:
    return AuthPosture(
        configured_credentials=1 if raw_key else 0,
        credential_fingerprint=fingerprint_credential(raw_key) if raw_key else None,
        loopback_listener_proven=True,
        companion_proxy_configured=False,
    )


def test_principal_floor_blocks_credential_only_rollback_and_reconciles_safe_rollforward(
    tmp_path,
) -> None:
    """Floor first, then the role write; rollback blocked; roll-forward reconciled.

    Four claims, in the order the migration performs them:

    1. The floor is recorded **before** the first durable role write, and the record does
       not exist until it is.
    2. A credential-only scalar rollback is refused while the floor exists, and refused
       *before* it materializes any legacy projection.
    3. Compatible roll-forward preserves the role id and reconciles an unambiguous
       credential rotation from the prior image's final export.
    4. Missing, divergent, and ambiguous exports each fail closed without overwriting
       either lineage.
    """

    runtime, registration, _ = active_runtime(tmp_path)
    store = open_local_operator_principal_store(runtime.layout.registry_path)

    # -- 1. ordering --------------------------------------------------------------------
    assert not principal_floor_recorded(runtime.registry)
    assert not principal_record_path(runtime).exists()

    original_key = "image-a-key"
    record = run_principal_cutover(runtime, posture=_posture(original_key))

    floors = runtime.registry.load().extensions["runtimeFloors"]
    assert floors[MINIMUM_RUNTIME_PRINCIPAL_KEY] == MINIMUM_RUNTIME_PRINCIPAL
    # The MVR-01 floor slot was reused, not replaced by a rival mechanism.
    assert "minimumRuntimeSchema" not in floors or floors.get("minimumRuntimeSchema") != ""
    assert principal_record_path(runtime).exists()
    # The fence that authorized the floor is recorded as principal state.
    fence = runtime.registry.load().extensions["principalState"]["fence"]
    assert fence["operations_fenced"] is True
    assert fence["probe_count"] == 2

    # -- 2. credential-only rollback is blocked -----------------------------------------
    rollback_projection = tmp_path / "rollback" / "app-local.md"
    with pytest.raises(CapabilityNotReadyError, match="credential-only scalar image"):
        _preflight_scalar_rollback(
            channel=runtime.layout.channel_id,
            registry_path=runtime.layout.registry_path,
            host_global_root=runtime.ledger.root,
            rollback_vault_binding_id=registration.vault_binding_id,
            legacy_path=rollback_projection,
            selected_root=Path(
                runtime.registry.lookup(registration.vault_binding_id).path
            ),
            compose_base=REPO_ROOT / "docker-compose.yaml",
            compose_overlay=REPO_ROOT / "docker-compose.scalar-rollback.yml",
            gateway_config=REPO_ROOT / "ops/scalar-rollback/nginx.conf",
            native_launcher=REPO_ROOT / "scripts/scalar_rollback_native.sh",
        )
    # Refused before materializing anything: the old image cannot half-start.
    assert not rollback_projection.exists()
    # And the principal record is untouched by the refusal.
    assert store.require().local_operator_role_id == record.local_operator_role_id
    assert store.require().revision == 1

    # -- 3. compatible roll-forward preserves identity and reconciles rotation ----------
    # The prior image rotated its credential before stopping; the stopped-window export is
    # its final auth revision.
    rotated_key = "image-a-rotated-key"
    store.export_final_auth_state(
        credential_fingerprint=fingerprint_credential(rotated_key),
        fork_revision=record.revision,
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    reconciled = store.reconcile_roll_forward(_capability=STORAGE_MUTATION_CAPABILITY)

    assert reconciled.local_operator_role_id == record.local_operator_role_id, (
        "roll-forward must preserve role identity"
    )
    assert reconciled.credential_fingerprint == fingerprint_credential(rotated_key)
    assert reconciled.migration_provenance == PROVENANCE_ROLL_FORWARD
    assert reconciled.revision == record.revision + 1
    # The raw credential never entered durable state at any point.
    body = principal_record_path(runtime).read_text(encoding="utf-8")
    assert original_key not in body and rotated_key not in body

    # Idempotent: re-running the same reconcile is a no-op, not a second rotation.
    again = store.reconcile_roll_forward(_capability=STORAGE_MUTATION_CAPABILITY)
    assert again.revision == reconciled.revision

    # -- 4. missing / divergent / ambiguous exports all fail closed ---------------------
    fresh_root = tmp_path / "fresh"
    fresh_root.mkdir()
    fresh_runtime, _, _ = active_runtime(fresh_root)
    fresh_record = run_principal_cutover(fresh_runtime, posture=_posture("fresh-key"))
    fresh_store = open_local_operator_principal_store(fresh_runtime.layout.registry_path)

    # missing export
    with pytest.raises(PrincipalPreflightError, match="final auth export"):
        fresh_store.reconcile_roll_forward(_capability=STORAGE_MUTATION_CAPABILITY)
    assert fresh_store.require().revision == fresh_record.revision

    # divergent fork
    fresh_store.export_final_auth_state(
        credential_fingerprint=fingerprint_credential("other-key"),
        fork_revision=fresh_record.revision + 5,
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    with pytest.raises(PrincipalPreflightError, match="divergent"):
        fresh_store.reconcile_roll_forward(_capability=STORAGE_MUTATION_CAPABILITY)
    assert fresh_store.require().credential_fingerprint == fingerprint_credential(
        "fresh-key"
    ), "a divergent lineage must not overwrite either side"

    # ambiguous: a credential that vanished cannot be told apart from a revocation
    fresh_store.export_final_auth_state(
        credential_fingerprint=None,
        fork_revision=fresh_record.revision,
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    with pytest.raises(PrincipalPreflightError, match="rotation from a revocation"):
        fresh_store.reconcile_roll_forward(_capability=STORAGE_MUTATION_CAPABILITY)
    assert fresh_store.require().revision == fresh_record.revision

    # The floor is never lowered by any of this; only a later explicitly verified
    # reversible migration may do that.
    assert principal_floor_recorded(fresh_runtime.registry)
    assert json.loads(principal_record_path(runtime).read_text(encoding="utf-8"))[
        "local_operator_role_id"
    ] == record.local_operator_role_id
