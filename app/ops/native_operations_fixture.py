"""Explicit fixed native/operator preparation; admission never calls this module.

The operator supplies intent for an existing isolated initialized binding. Native
resolves the original committed candidate; the baked producer rechecks its bytes.
Canonical owners retain all identity, source, GOV, consent and archive authority.
Partial/UNKNOWN effects stay in the existing operation journal and cannot replay.
"""
from __future__ import annotations

from dataclasses import asdict
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
from typing import Any, cast
from uuid import UUID

from app.instance.runtime import open_local_operator_principal_store, local_operator_principal_path
from app.instance.vault_registry import VaultRegistryStore
from app.operations.contracts import (OperationContext, OperationConvergence, OperationItemOutcome,
    OperationOutcome, OperationReceipt, OperationRecovery, OperationStatus, ReceiptStatus, SourceEffectStatus)
from app.operations.execution_kernel import JsonReceiptStore
from app.ops.operations_acceptance import (CONTEXT_FILE, PROFILE, OperationsAcceptanceRefusal,
    digest, file_hash, require_identity)

# One fixed preparation per instance registry, independent of operation UUID or
# later selection. It cannot manufacture another setup or journey allowance.
PREPARATION_REQUEST = "native-operations-fixture-preparation"
PREPARATION_ACTION = "native.operations_fixture.prepare"
RAW_STAGE_REQUEST = "native-operations-fixture-raw-stage"


def _raw_preflight(identity: dict[str, Any], root: Path, principal: str,
                   instance: str, binding: str, *, stage: bool = False) -> dict[str, Any] | None:
    if identity["channel"] != "test":
        return None
    from app.api.native_operations_acceptance import raw_fixture_bytes
    from app.heimdal import local_archive, raw_read_gate, raw_store
    from app.heimdal.consent_ledger import resolve_active_grant
    from app.heimdal.retention import resolve_retention_window_days
    from app.ops.heimdal_cold_volume import load_channel_archive_metadata, require_archive_volume_ready

    content = raw_fixture_bytes(identity["operation_id"])
    record = raw_store.get_raw_record_by_content_identity(raw_store.compute_raw_content_identity(content))
    grant = resolve_active_grant(scope=PROFILE + ":" + identity["operation_id"])
    if (grant is None or grant.granted_by != principal
        or grant.payload.get("instance_identity") != instance
        or grant.payload.get("vault_binding_id") != binding
        or record is not None and record.consent.get("grant_ref") != grant.grant_ref):
        raise OperationsAcceptanceRefusal("existing_operation_raw_consent_required")
    retention = resolve_retention_window_days(root)
    if retention <= local_archive.ARCHIVE_MINIMUM_AGE_DAYS:
        raise OperationsAcceptanceRefusal("retention_has_no_archive_window")
    raw_store.resolve_raw_store_key()
    if local_archive.OPERATION_RESTORE_SERVICE not in raw_read_gate.resolve_read_allowlist():
        raise OperationsAcceptanceRefusal("existing_restore_reader_required")
    config = os.environ.get("PKM_CONFIG_ROOT", "")
    if not config or not Path(config).is_absolute():
        raise OperationsAcceptanceRefusal("qualified_test_archive_required")
    metadata = load_channel_archive_metadata(config_root=Path(config), channel="test")
    require_archive_volume_ready(metadata, expected_channel="test")
    if stage:
        if record is not None:
            raise OperationsAcceptanceRefusal("existing_raw_without_original_staging_receipt")
        return {"consent_ref": grant.grant_ref, "retention_window_days": retention}
    if record is None or not local_archive.archive_eligible(record, now=datetime.now(timezone.utc), retention_window_days=retention):
        raise OperationsAcceptanceRefusal("existing_archive_eligible_raw_required")
    proof = local_archive.resolve_operation_restore_target(raw_read_gate.raw_ref_for(record))
    active = [row for row in raw_store.all_raw_representations(record.id) if row.active]
    if (len(active) != 1 or active[0].storage_kind != "postgres_hot"
        or raw_store.decrypt_raw_bytes(record.ciphertext, record.nonce,
            key=raw_store.resolve_raw_store_key()) != content):
        raise OperationsAcceptanceRefusal("existing_encrypted_hot_fixture_required")
    return {"artifact_id": proof.raw_ref, "content_identity": record.content_identity,
            "consent_ref": grant.grant_ref, "generation": proof.generation}


def _stage_raw(identity: dict[str, Any], qualified: dict[str, Any], journal: JsonReceiptStore,
               intent: str, binding_id: str, binding_revision: int, authorization_epoch: str,
               local_write_check: Callable[[], None]) -> dict[str, Any]:
    from app.api.native_operations_acceptance import raw_fixture_bytes
    from app.heimdal import raw_store, local_archive
    from app.heimdal.consent_ledger import consent_raw_admission
    context = OperationContext("native:" + identity["operation_id"],
        extensions={"identity_sha256": digest(identity), "binding_id": binding_id,
            "binding_revision": binding_revision, "authorization_epoch": authorization_epoch})
    pending = OperationOutcome(RAW_STAGE_REQUEST, OperationStatus.RECOVERY_REQUIRED,
        PREPARATION_ACTION, context, convergence=OperationConvergence(SourceEffectStatus.UNKNOWN),
        receipt=OperationReceipt(RAW_STAGE_REQUEST, ReceiptStatus.PENDING),
        recovery=OperationRecovery("inspect_original_receipts", "Do not repeat uncertain RAW staging."))
    reservation, _ = journal.reserve(RAW_STAGE_REQUEST, intent, pending)
    if reservation != "reserved":
        raise OperationsAcceptanceRefusal("raw_staging_already_reserved")
    # Crash/exception after this reservation is deliberately UNKNOWN, even if
    # the insert committed. The normal RAW owner, not another setup, reconciles.
    with consent_raw_admission(qualified["consent_ref"]):
        content = raw_fixture_bytes(identity["operation_id"])
        key = raw_store.resolve_raw_store_key()
        ciphertext, nonce = raw_store.encrypt_raw_bytes(content, key=key)
        local_write_check()
        record, created = raw_store.insert_raw_record(
            content_identity=raw_store.compute_raw_content_identity(content), capture_chain=[PROFILE, "heimdal"],
            sensor={"sensor_id": PROFILE, "operation_id": identity["operation_id"]},
            consent={"grant_ref": qualified["consent_ref"]}, ciphertext=ciphertext, nonce=nonce,
            key_ref="v1-process-key", key=key, source_path="synthetic-operations-fixture")
        if not created:
            raise OperationsAcceptanceRefusal("raw_staging_conflict_inspect_original_receipts")
        result = OperationOutcome(RAW_STAGE_REQUEST, OperationStatus.CONVERGENCE_PENDING,
            PREPARATION_ACTION, context, convergence=OperationConvergence(SourceEffectStatus.COMMITTED),
            receipt=OperationReceipt(RAW_STAGE_REQUEST, ReceiptStatus.COMMITTED, payload={
                "artifact_id": raw_store.compute_raw_content_identity(content), "raw_record_id": record.id,
                "ingested_at": record.ingested_at.isoformat(),
                "eligible_after": (record.ingested_at + timedelta(days=local_archive.ARCHIVE_MINIMUM_AGE_DAYS)).isoformat(),
                "retention_expires_at": (record.ingested_at + timedelta(days=qualified["retention_window_days"])).isoformat(),
                "readiness": "awaiting_normal_archive_eligibility"}),
            recovery=OperationRecovery("wait_for_archive_eligibility", "Run preparation for the same original operation after owner eligibility passes."))
        journal.finalize(RAW_STAGE_REQUEST, intent, result)
        return result.to_dict()


def _pristine_fixture(root: Path) -> None:
    from app.vault.layout import load_layout
    layout = load_layout(root).note_path
    selected_layout = layout.relative_to(root).as_posix()
    if not layout.is_file():
        raise OperationsAcceptanceRefusal("canonical_fixture_layout_unqualified")
    for path in (root, *root.parents):
        if path.is_symlink():
            raise OperationsAcceptanceRefusal("fixture_path_unqualified")
    for path in root.rglob("*"):
        if path.is_symlink():
            raise OperationsAcceptanceRefusal("fixture_path_unqualified")
        if path.is_file():
            file_hash(path)  # Includes hardlink and special-file refusal.
            relative = path.relative_to(root).as_posix()
            if relative != selected_layout and relative != "_heimdal/settings.md" and not relative.startswith("settings/"):
                raise OperationsAcceptanceRefusal("existing_or_foreign_fixture_source")
        elif not path.is_dir():
            raise OperationsAcceptanceRefusal("fixture_path_unqualified")


def prepare_fixture(request: dict[str, Any], *, registry_path: Path) -> dict[str, Any]:
    """Compose fixed source owners under the existing native/operator authority."""
    from app.instance.scalar_binding_runtime import (resolve_scalar_binding_runtime,
        validate_frozen_binding_runtime, frozen_binding_effect)
    from app.knowledge.write_ops import write_note_relative
    from app.governance.governed_write import GovernedWriteAdapter
    from app.instance.runtime import declare_operations_acceptance_fixture
    from app.vault.manager import VaultManager
    from app.write_guard import DEFAULT_WRITE_GUARD, WriteGuard

    if set(request) != {"identity", "binding_id", "principal_id", "instance_identity", "confirm_synthetic_setup", "stage_raw"}:
        raise OperationsAcceptanceRefusal("explicit_fixed_setup_inputs_required")
    identity = request["identity"]
    require_identity(identity)
    if request["confirm_synthetic_setup"] is not True or str(UUID(identity["operation_id"])) != identity["operation_id"]:
        raise OperationsAcceptanceRefusal("explicit_synthetic_setup_required")
    if type(request["stage_raw"]) is not bool or request["stage_raw"] and identity["channel"] != "test":
        raise OperationsAcceptanceRefusal("raw_staging_is_test_only")
    if os.environ.get("PKM_ENVIRONMENT") != identity["channel"]:
        raise OperationsAcceptanceRefusal("native_setup_channel_mismatch")
    registry = VaultRegistryStore(registry_path)
    snapshot, _ = registry.read_qualification_state()
    principal_store = open_local_operator_principal_store(registry_path)
    principal = principal_store.require()
    registration = snapshot.registrations.get(request["binding_id"])
    if (principal.local_operator_role_id != request["principal_id"]
        or principal.local_operator_role_id == snapshot.app_install_id
        or snapshot.app_install_id != request["instance_identity"]
        or registration is None or registration.extensions.get("status") != "initialized"
        or not registration.vault_id):
        raise OperationsAcceptanceRefusal("existing_operator_instance_binding_required")
    root = Path(registration.path)
    runtime = resolve_scalar_binding_runtime(requested_binding_id=registration.vault_binding_id, vault_root=root)
    if runtime is None or runtime.channel_id != identity["channel"]:
        raise OperationsAcceptanceRefusal("existing_native_binding_authority_required")
    journal = JsonReceiptStore(registry_path.parent / "operation-receipts.json")
    intent = digest({"request": {key: value for key, value in request.items() if key != "stage_raw"},
        "principal_record_sha256": file_hash(local_operator_principal_path(registry_path))})
    with principal_store.read_effect_window(expected_revision=principal.revision), runtime.effect_leases.shared_effect(
        registration.vault_binding_id, channel_id=runtime.channel_id, root=runtime.root), frozen_binding_effect(runtime), journal.effect_window(PREPARATION_REQUEST):
        validate_frozen_binding_runtime(runtime)
        snapshot = registry.load()
        previous = journal.lookup(RAW_STAGE_REQUEST if request["stage_raw"] else PREPARATION_REQUEST)
        if previous is not None:
            if previous.intent_digest != intent:
                raise OperationsAcceptanceRefusal("original_preparation_binding_changed")
            # Observation of original completion/uncertainty, never another effect.
            return previous.outcome.to_dict()
        if ((registry_path.parent / CONTEXT_FILE).exists()
            or any(PROFILE in row.extensions for row in snapshot.registrations.values())):
            raise OperationsAcceptanceRefusal("retained_acceptance_or_foreign_declaration")
        _pristine_fixture(root)
        manager = VaultManager()
        from app.vault.markdown_settings import MarkdownSettingsStore
        settings = MarkdownSettingsStore()
        if (settings.read(root / "settings/vault.md").frontmatter.get("vaultId") != registration.vault_id
            or settings.read(root / "settings/local.md").frontmatter.get("localInstanceId") != registration.local_instance_id):
            raise OperationsAcceptanceRefusal("canonical_fixture_instance_identity_mismatch")
        context = manager.validate_vault(root, heal_identity=False)
        if (context.status != "selected" or context.active_vault_id != registration.vault_id
            or context.local_instance_id != registration.local_instance_id):
            raise OperationsAcceptanceRefusal("canonical_initialized_binding_required")
        def require_local_writes() -> None:
            if not manager.permissions_for_context(context).allow_writes_to_vault:
                raise OperationsAcceptanceRefusal("local_vault_writes_disallowed")
        require_local_writes()
        def write_snapshot() -> dict[str, Any]:
            snapshot = DEFAULT_WRITE_GUARD.snapshot_fn()
            # Consume the current local-clone ceiling after health work too.
            # Canonical HKA/briefing ports reassert this same guard at their
            # existing mutation seams; fixture metadata never overrides it.
            require_local_writes()
            return snapshot
        guard = WriteGuard(write_snapshot, bootstrap_actions=())
        guard.assert_writes_allowed(PREPARATION_ACTION)
        raw = _raw_preflight(identity, root, principal.local_operator_role_id, snapshot.app_install_id,
            registration.vault_binding_id, stage=request["stage_raw"])
        if request["stage_raw"]:
            assert raw is not None
            return _stage_raw(identity, raw, journal, intent, registration.vault_binding_id,
                runtime.binding_revision, runtime.authorization_epoch, require_local_writes)
        if identity["channel"] == "test":
            staged = journal.lookup(RAW_STAGE_REQUEST)
            if (staged is None or staged.intent_digest != intent or staged.outcome.receipt is None
                or staged.outcome.receipt.status is not ReceiptStatus.COMMITTED
                or staged.outcome.context.extensions.get("binding_revision") != runtime.binding_revision
                or staged.outcome.context.extensions.get("authorization_epoch") != runtime.authorization_epoch):
                raise OperationsAcceptanceRefusal("original_raw_staging_receipt_required")
        from app.api.native_operations_acceptance import source_templates
        from app.vault.paths import get_vault_capture_note_rel
        sources = source_templates(identity["operation_id"])
        sources["capture"]["path"] = get_vault_capture_note_rel(root)
        if (len({source["path"] for source in sources.values()}) != len(sources)
            or any((root / source["path"]).exists() for source in sources.values())):
            raise OperationsAcceptanceRefusal("source_target_conflict")
        effects: list[OperationItemOutcome] = []
        pending_effect = "source_seeds"
        def outcome(*, complete: bool = False) -> OperationOutcome:
            return OperationOutcome(PREPARATION_REQUEST,
                OperationStatus.SUCCEEDED if complete else OperationStatus.RECOVERY_REQUIRED,
                PREPARATION_ACTION, OperationContext("native:" + identity["operation_id"],
                    extensions={"identity_sha256": digest(identity), "binding_id": registration.vault_binding_id,
                                "principal_id": principal.local_operator_role_id}),
                convergence=OperationConvergence(SourceEffectStatus.COMMITTED if complete else SourceEffectStatus.UNKNOWN),
                items=tuple(effects), receipt=OperationReceipt(PREPARATION_REQUEST,
                    ReceiptStatus.COMMITTED if complete else ReceiptStatus.PENDING),
                recovery=None if complete else OperationRecovery("inspect_original_receipts", "Do not repeat fixture preparation."),
                extensions={"pending_effect": None if complete else pending_effect})
        reserved, _ = journal.reserve(PREPARATION_REQUEST, intent, outcome())
        if reserved != "reserved":
            raise OperationsAcceptanceRefusal("preparation_already_reserved")
        try:
            gov = GovernedWriteAdapter()
            for source in sources.values():
                pending_effect = source["path"]
                journal.finalize(PREPARATION_REQUEST, intent, outcome())
                grant = gov.issue_decision_token(write_guard=guard, action=PREPARATION_ACTION,
                    write_class="synthetic_fixture_source", actor=principal.local_operator_role_id, resource=source["path"])
                gov.validate_decision_token(decision_token=grant.decision_token, action=PREPARATION_ACTION,
                    write_class="synthetic_fixture_source", actor=principal.local_operator_role_id, resource=source["path"])
                mutation = write_note_relative(source["path"], source["text"], vault_root=root,
                    writer_identity=principal.local_operator_role_id, write_guard=guard, create_once=True)
                written = mutation.outcome == "written"
                authority = gov.record_authority_receipt(decision_token=grant.decision_token,
                    mutation_receipt=cast(Any, mutation), state_owner="HKA", outcome="applied" if written else "failed",
                    effect_id=identity["operation_id"] + ":" + source["artifact_id"])
                effects.append(OperationItemOutcome(source["artifact_id"],
                    OperationStatus.SUCCEEDED if written else OperationStatus.CONFLICTED,
                    payload={"mutation_receipt": asdict(mutation), "authority_receipt": asdict(authority)}))
                journal.finalize(PREPARATION_REQUEST, intent, outcome())
                if not written:
                    raise OperationsAcceptanceRefusal("source_create_once_conflict")
            from app.briefing.trigger import BRIEFING_ENABLED, _local_now
            from app.briefing.compose import compose_briefing
            if BRIEFING_ENABLED:
                pending_effect = "briefing"
                journal.finalize(PREPARATION_REQUEST, intent, outcome())
                from app.knowledge.errors import KnowledgeWriteConflict
                try:
                    receipt = compose_briefing(vault_context=context, for_date=_local_now(None).date(),
                        write_guard=guard, create_once=True)
                except KnowledgeWriteConflict as exc:
                    if exc.receipt is not None:
                        effects.append(OperationItemOutcome("briefing", OperationStatus.CONFLICTED,
                            payload={"mutation_receipt": asdict(exc.receipt)}))
                        journal.finalize(PREPARATION_REQUEST, intent, outcome())
                    raise
                effects.append(OperationItemOutcome("briefing", OperationStatus.SUCCEEDED, payload={"mutation_receipt": asdict(receipt)}))
                journal.finalize(PREPARATION_REQUEST, intent, outcome())
            if any(file_hash(root / source["path"]) != source["seed_sha256"] for source in sources.values()):
                raise OperationsAcceptanceRefusal("source_preparation_readback_conflict")
            # Declare while the source window's frozen binding revision is
            # still current. Both following metadata transitions belong to
            # their normal owners; no source/GOV consumer reuses the old
            # scalar snapshot after these registry revisions advance.
            pending_effect = "fixture_declaration"
            journal.finalize(PREPARATION_REQUEST, intent, outcome())
            revision = declare_operations_acceptance_fixture(registry_path=registry_path,
                binding_id=registration.vault_binding_id, operation_id=identity["operation_id"])
            effects.append(OperationItemOutcome("fixture_declaration", OperationStatus.SUCCEEDED, resulting_version=revision))
            pending_effect = "last_active_restore"
            journal.finalize(PREPARATION_REQUEST, intent, outcome())
            # Reuse the picker's remembered-context producer with the already
            # validated identity. Re-selecting here could heal an identity
            # removed by an intervening writer, which this setup never owns.
            manager._remember_context(context, root)
            if registry.load().last_active_vault_ref != registration.ref:
                raise OperationsAcceptanceRefusal("canonical_fixture_restore_target_unavailable")
            effects.append(OperationItemOutcome("last_active_restore", OperationStatus.SUCCEEDED))
            result = outcome(complete=True)
            journal.finalize(PREPARATION_REQUEST, intent, result)
            return result.to_dict()
        except Exception:
            # A thrown writer can have published bytes. Known receipts remain;
            # the pending attempt stays UNKNOWN. No compensating rewrite/retry.
            journal.finalize(PREPARATION_REQUEST, intent, outcome())
            raise OperationsAcceptanceRefusal("preparation_partial_or_uncertain_inspect_original_receipts") from None


def main() -> int:
    try:
        request = json.load(sys.stdin)
        identity = request["identity"]
        require_identity(identity)
        if (os.environ.get("VCS_REF") != identity["source_sha"]
            or os.environ.get("PKM_ENVIRONMENT") != identity["channel"]
            or os.environ.get("STORE_SCHEMA_AUTOCREATE", "").lower() in {"1", "true", "yes"}
            or not {"app/ops/native_operations_fixture.py", "app/instance/runtime.py", "app/cli/ops.py"}.issubset(identity["resource_hashes"])
            or any(file_hash(Path("/app") / name) != expected for name, expected in identity["resource_hashes"].items())):
            raise OperationsAcceptanceRefusal("actual_baked_candidate_mismatch")
        result = prepare_fixture(request, registry_path=Path(os.environ["INSTANCE_VAULT_REGISTRY_PATH"]))
        print(json.dumps(result, sort_keys=True))
        return 0 if result["status"] in {"succeeded", "convergence_pending"} else 1
    except OperationsAcceptanceRefusal as exc:
        print(json.dumps({"status": "blocked", "reason": exc.reason}))
        return 1
    except Exception:
        print(json.dumps({"status": "blocked", "reason": "native_fixture_preparation_refused_inspect_original_receipts"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
