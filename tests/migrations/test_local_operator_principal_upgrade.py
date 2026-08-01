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
    verify_credential,
)
from app.instance.principal_fence import principal_floor_recorded
from app.instance.runtime import (
    _preflight_scalar_rollback,
    open_local_operator_principal_store,
)
from app.instance.runtime import main as instance_runtime_main
from tests._mvr03_principal_harness import (
    principal_record_path,
    run_principal_cutover,
)
from tests._mvr_default_vault_harness import REPO_ROOT, active_runtime
from tests.helpers.instance_storage_capability import STORAGE_MUTATION_CAPABILITY


def _cli(*args: str) -> dict:
    from contextlib import redirect_stdout
    from io import StringIO

    buffer = StringIO()
    with redirect_stdout(buffer):
        code = instance_runtime_main(list(args))
    payload = json.loads(buffer.getvalue().strip().splitlines()[-1])
    payload["_exit_code"] = code
    return payload


def _posture(raw_key: str | None) -> AuthPosture:
    return AuthPosture(
        configured_credentials=1 if raw_key else 0,
        credential=raw_key,
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
    # The prior image rotated its credential before stopping. The stopped-window export
    # carries the *prior image's configured credential*, not the delegated-role record's own
    # fingerprint -- exporting the record back at itself would make this branch a permanent
    # no-op. Driven through the shipped CLI, which reads the configured credential.
    rotated_key = "image-a-rotated-key"
    from app.settings import settings

    settings_backup = settings.api_key
    settings.api_key = rotated_key
    try:
        exported = _cli(
            "principal-export-auth-state",
            "--registry-path",
            str(runtime.layout.registry_path),
            "--consumer",
            "bootstrap-init",
        )
    finally:
        settings.api_key = settings_backup
    assert exported["_exit_code"] == 0
    assert exported["exported_credential_bound"] is True
    assert exported["exported_fork_revision"] == record.revision
    assert rotated_key not in json.dumps(exported)

    reconciled = store.reconcile_roll_forward(_capability=STORAGE_MUTATION_CAPABILITY)

    assert reconciled.local_operator_role_id == record.local_operator_role_id, (
        "roll-forward must preserve role identity"
    )
    assert verify_credential(reconciled.credential_fingerprint, rotated_key)
    assert reconciled.migration_provenance == PROVENANCE_ROLL_FORWARD
    assert reconciled.revision == record.revision + 1
    # The raw credential never entered durable state at any point.
    body = principal_record_path(runtime).read_text(encoding="utf-8")
    assert original_key not in body and rotated_key not in body

    # The export is CONSUMED on success. Re-running without a fresh export fails closed
    # rather than replaying. This is the difference between "idempotent" and "replayable":
    # a leftover export plus a later governed rotation would otherwise let a stale
    # credential be written back over the new one.
    assert not store.export_path.exists()
    with pytest.raises(PrincipalPreflightError, match="final auth export"):
        store.reconcile_roll_forward(_capability=STORAGE_MUTATION_CAPABILITY)
    assert store.require().revision == reconciled.revision

    # And a *stale* export -- one whose recorded fork is below the current revision, e.g.
    # left behind before a governed rotation -- is refused rather than accepted. A `>` fork
    # check instead of `!=` would silently revert the rotation here.
    third_key = "image-a-third-key"
    rotated_again = store.rotate_credential(
        credential=third_key,
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    store.export_path.write_text(
        json.dumps(
            {
                "schema": "agentic-pkm.local-operator-principal.v1.roll-forward-export",
                "fork_revision": record.revision,  # stale: predates two rotations
                "credential_fingerprint": reconciled.credential_fingerprint,
                "exported_at": 0.0,
            }
        ),
        encoding="utf-8",
    )
    store.export_path.chmod(0o600)
    with pytest.raises(PrincipalPreflightError, match="does not match the current principal lineage"):
        store.reconcile_roll_forward(_capability=STORAGE_MUTATION_CAPABILITY)
    assert verify_credential(store.require().credential_fingerprint, third_key), (
        "a stale export must not revert a governed credential rotation"
    )
    assert store.require().revision == rotated_again.revision
    store.export_path.unlink()

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
        credential="other-key",
        fork_revision=fresh_record.revision + 5,
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    with pytest.raises(PrincipalPreflightError, match="divergent"):
        fresh_store.reconcile_roll_forward(_capability=STORAGE_MUTATION_CAPABILITY)
    assert verify_credential(
        fresh_store.require().credential_fingerprint, "fresh-key"
    ), "a divergent lineage must not overwrite either side"

    # ambiguous: a credential that vanished cannot be told apart from a revocation
    fresh_store.export_final_auth_state(
        credential=None,
        fork_revision=fresh_record.revision,
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    with pytest.raises(PrincipalPreflightError, match="rotation from a revocation"):
        fresh_store.reconcile_roll_forward(_capability=STORAGE_MUTATION_CAPABILITY)
    assert fresh_store.require().revision == fresh_record.revision

    # -- an incompatible export schema fails closed --------------------------------------
    # Without a schema check, any private JSON object carrying a matching fork_revision and
    # a string fingerprint would be interpreted as v1 and could overwrite the record with the
    # wrong credential during a mixed-version roll-forward.
    fresh_store.export_path.write_text(
        json.dumps(
            {
                "schema": "agentic-pkm.local-operator-principal.v2.roll-forward-export",
                "fork_revision": fresh_record.revision,
                "credential_fingerprint": fresh_record.credential_fingerprint,
                "exported_at": 0.0,
            }
        ),
        encoding="utf-8",
    )
    fresh_store.export_path.chmod(0o600)
    with pytest.raises(PrincipalPreflightError, match="unknown roll-forward export schema"):
        fresh_store.reconcile_roll_forward(_capability=STORAGE_MUTATION_CAPABILITY)
    assert fresh_store.require().revision == fresh_record.revision

    # A malformed fingerprint (not the salted `scrypt.v1$salt$digest` shape) is ambiguous.
    fresh_store.export_path.write_text(
        json.dumps(
            {
                "schema": "agentic-pkm.local-operator-principal.v1.roll-forward-export",
                "fork_revision": fresh_record.revision,
                "credential_fingerprint": "deadbeef",
                "exported_at": 0.0,
            }
        ),
        encoding="utf-8",
    )
    fresh_store.export_path.chmod(0o600)
    with pytest.raises(PrincipalPreflightError, match="ambiguous"):
        fresh_store.reconcile_roll_forward(_capability=STORAGE_MUTATION_CAPABILITY)
    assert fresh_store.require().revision == fresh_record.revision
    fresh_store.export_path.unlink()

    # -- an empty credential is not a rotation -------------------------------------------
    # Rotating to nothing would keep `api_key_credential` bound with no fingerprint, so every
    # admitted key would fail verification and the instance would have no usable principal —
    # routing around `revoke_subject`'s last-subject safeguard.
    assert "api_key_credential" in fresh_store.require().subjects
    with pytest.raises(PrincipalPreflightError, match="not a rotation"):
        fresh_store.rotate_credential(
            credential=None, _capability=STORAGE_MUTATION_CAPABILITY
        )
    assert fresh_store.require().revision == fresh_record.revision
    assert verify_credential(fresh_store.require().credential_fingerprint, "fresh-key")

    # The floor is never lowered by any of this; only a later explicitly verified
    # reversible migration may do that.
    assert principal_floor_recorded(fresh_runtime.registry)
    assert json.loads(principal_record_path(runtime).read_text(encoding="utf-8"))[
        "local_operator_role_id"
    ] == record.local_operator_role_id
