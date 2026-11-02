"""Native operations qualification at the existing API/instance owner boundary.

There is no fixture/principal/permission initializer here. Native prepares the
private run context only after reading the committed operation and actual
channel resources. The one empty-body admission command narrows an existing
selection and derives all versions from the same production owners as clients.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from time import time
from typing import Any
from uuid import UUID, uuid5

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from app.auth import api_key_header, require_loopback_or_api_key
from app.instance.context_bound_read import context_bound_read_window
from app.instance.runtime import open_local_operator_principal_store, local_operator_principal_path
from app.instance.vault_registry import VaultRegistryStore
from app.knowledge.write_ops import read_note_text_with_version
from app.operations.contracts import OperationRequest
from app.operations.execution_kernel import JsonReceiptStore
from app.ops.operations_acceptance import (
    CONTEXT_FILE, MAX_SECONDS, PROFILE, ROLES, OperationsAcceptanceRefusal,
    digest, file_hash, load_context, public_binding, require_identity, require_native_fixture, require_runtime, write_private,
)

router = APIRouter(prefix="/operations/acceptance", tags=["native-qualification"],
    dependencies=[Depends(require_loopback_or_api_key)])


class FixedAdmission(BaseModel):
    model_config = ConfigDict(extra="forbid")


@router.get("/recovery", include_in_schema=False)
def recovery_observation(request: Request, api_key: str | None = Depends(api_key_header),
    x_active_context_session: str | None = Header(default=None),
    x_active_context_override: str | None = Header(default=None)) -> dict[str, Any]:
    """Current native WSP epoch and original receipt reads; no effect grant."""
    from app.api.routes.operations import _runtime
    runtime = _runtime(request, api_key, x_active_context_session, x_active_context_override)
    context = load_context(runtime.registry.path, required=True, observation_only=True)
    assert context is not None
    fixture = context["fixture"]
    if (runtime.actor != fixture["principal_id"] or runtime.selection_record.instance_identity != fixture["instance_identity"]
        or runtime.selection_record.binding_ids != (fixture["binding_id"],)):
        raise HTTPException(403, "original_acceptance_receipts_unavailable")
    return {"current_wsp_epoch": runtime.carrier.service.selection_store.process_epoch,
            "original_wsp_epoch": context.get("api_process_epoch"),
            "host_principal_id": runtime.actor, "binding_id": fixture["binding_id"], "source_effects": 0}


@router.get("/authority-probe", include_in_schema=False)
def authority_probe(request: Request, api_key: str | None = Depends(api_key_header),
    x_active_context_session: str | None = Header(default=None),
    x_active_context_override: str | None = Header(default=None)) -> dict[str, Any]:
    """Fixed read-only native subject/instance refusals; never issues a role.

    The deliberately wrong principal/instance are inputs to the existing
    selection reader only. They are never installed or used for an effect.
    """
    from dataclasses import replace
    from app.api.routes.operations import _runtime
    from app.instance.context_selection import SelectionPrincipalMismatchError
    runtime = _runtime(request, api_key, x_active_context_session, x_active_context_override)
    context = load_context(runtime.registry.path, required=True)
    assert context is not None
    require_runtime(context, runtime)
    derived = runtime.carrier.derived
    store = runtime.carrier.service.selection_store
    raw = runtime.carrier.override_bearer if runtime.carrier.override_bearer is not None else runtime.carrier.session_bearer
    result = {}
    for name, principal, instance in (
        ("wrong_principal", replace(derived.principal, principal_id="unissued-acceptance-principal"), derived.instance_identity),
        ("wrong_instance", derived.principal, "unissued-acceptance-instance"),
    ):
        try:
            store.inspect(raw or "", principal=principal, instance_identity=instance)
        except SelectionPrincipalMismatchError:
            result[name] = {"status": "refused", "owner": "ContextSelectionStore.inspect"}
        else:
            raise HTTPException(409, "native_authority_probe_not_refused")
    return {"cases": result, "host_principal_id": runtime.actor, "effects": 0}


def source_templates(operation_id: str) -> dict[str, dict[str, Any]]:
    namespace = UUID(operation_id)
    result = {}
    for role in (*ROLES, "capture"):
        identity = str(uuid5(namespace, "operations-acceptance:" + role))
        path = "Notes/operations-acceptance-" + role + ".md"
        text = (f"---\nuuid: {identity}\nartifact_class: human_knowledge\ntrust: human\n---\n"
                f"Synthetic operations acceptance {role}.\n")
        result[role] = {"artifact_id": identity, "path": path, "text": text,
                        "seed_sha256": hashlib.sha256(text.encode()).hexdigest()}
    return result


def raw_fixture_bytes(operation_id: str) -> bytes:
    return ("Synthetic operations raw acceptance " + operation_id + ".").encode()


def prepare_native_context(identity: dict[str, Any], *, registry_path: Path) -> dict[str, Any]:
    """Native-only producer: inspect existing identity, fixture and source bytes.

    The registry declaration names isolated data, not a permission. The normal
    principal, binding ownership, GOV and MVR-05C remain required independently.
    This function never creates a registry, role, vault, source, or grant.
    """
    require_identity(identity)
    registry = VaultRegistryStore(registry_path)
    # Inspect without transaction recovery, lock creation, restore or reload.
    try:
        snapshot, registry_authority_sha256 = registry.read_qualification_state()
    except Exception:
        raise OperationsAcceptanceRefusal("native_registry_state_unqualified") from None
    declared = [row for row in snapshot.registrations.values()
        if row.extensions.get(PROFILE) == {"operation_id": identity["operation_id"]}]
    if len(declared) != 1:
        raise OperationsAcceptanceRefusal("canonical_isolated_fixture_missing")
    registration = declared[0]
    if registration.extensions.get("status") != "initialized":
        raise OperationsAcceptanceRefusal("canonical_initialized_binding_required")
    principal = open_local_operator_principal_store(registry_path).require()
    if principal.local_operator_role_id == snapshot.app_install_id:
        raise OperationsAcceptanceRefusal("principal_is_not_instance_identity")
    root = Path(registration.path).resolve(strict=True)
    from app.ops.native_channel_probe import BINDING_PROBE
    probe_input = {"channel": identity["channel"], "vault_path": str(root), "vault_id": registration.vault_id}
    passive = subprocess.run([sys.executable, "-c", BINDING_PROBE], input=json.dumps(probe_input),
        text=True, capture_output=True, timeout=30, check=False)
    if passive.returncode:
        raise OperationsAcceptanceRefusal("passive_native_binding_restore_refused")
    from app.vault.markdown_settings import MarkdownSettingsStore
    vault_identity = MarkdownSettingsStore().read(root / "settings/vault.md").frontmatter
    local_identity = MarkdownSettingsStore().read(root / "settings/local.md").frontmatter
    if (vault_identity.get("vaultId") != registration.vault_id
        or local_identity.get("localInstanceId") != registration.local_instance_id):
        raise OperationsAcceptanceRefusal("canonical_fixture_instance_identity_mismatch")
    from app.vault.layout import load_layout
    try:
        layout_path = load_layout(root).note_path
        if layout_path.is_symlink() or not layout_path.is_file() or not layout_path.resolve(strict=True).is_relative_to(root):
            raise ValueError("unqualified native layout path")
        layout_relative = layout_path.resolve(strict=True).relative_to(root).as_posix()
        native_configuration = {layout_relative}
    except Exception:
        raise OperationsAcceptanceRefusal("canonical_fixture_layout_unqualified") from None
    passive_paths = {"layout": layout_relative}
    from app.briefing.trigger import BRIEFING_ENABLED, _local_now
    from app.briefing.compose import briefing_note_path, load_briefing
    from app.vault.manager import VaultContext
    passive_derived = set()
    if BRIEFING_ENABLED:
        briefing_context = VaultContext(status="selected", active_vault_path=str(root))
        briefing_date = _local_now(None).date()
        briefing = briefing_note_path(vault_context=briefing_context, for_date=briefing_date)
        if briefing.is_symlink() or not briefing.is_file() or not briefing.resolve(strict=True).is_relative_to(root):
            raise OperationsAcceptanceRefusal("native_navigation_first_contact_not_passive")
        try:
            original_briefing = load_briefing(vault_context=briefing_context, for_date=briefing_date)
        except Exception:
            raise OperationsAcceptanceRefusal("native_navigation_briefing_unqualified") from None
        if original_briefing is None:
            raise OperationsAcceptanceRefusal("native_navigation_first_contact_not_passive")
        passive_derived.add(briefing.relative_to(root).as_posix())
        passive_paths["briefing"] = briefing.relative_to(root).as_posix()
    previous = load_context(registry_path, observation_only=True)
    if previous is not None:
        if (previous["identity"] != identity
            or previous["fixture"]["binding_id"] != registration.vault_binding_id
            or previous["fixture"]["principal_record_sha256"] != file_hash(local_operator_principal_path(registry_path))
            or previous["fixture"]["registry_sha256"] != file_hash(registry_path)):
            raise OperationsAcceptanceRefusal("foreign_or_changed_retained_native_context")
        # Retained context is observation/recovery evidence. It is never
        # reissued, renewed, reset, or returned to the effect driver.
        return public_binding(previous)
    sources = source_templates(identity["operation_id"])
    from app.vault.paths import get_vault_capture_note_rel
    sources["capture"]["path"] = get_vault_capture_note_rel(root)
    for source in sources.values():
        target = root / source["path"]
        if target.is_symlink() or file_hash(target) != source["seed_sha256"]:
            raise OperationsAcceptanceRefusal("canonical_fixture_prestate_mismatch")
        source.pop("text")
    # No undeclared human note, symlink or hardlink can hide in a synthetic
    # label. Settings are observed, never initialized or repaired by the run.
    files = {}
    for target in sorted(root.rglob("*")):
        if target.is_symlink():
            raise OperationsAcceptanceRefusal("fixture_path_unqualified")
        if target.is_file():
            relative = target.relative_to(root).as_posix()
            if (target.suffix == ".md" and relative not in {s["path"] for s in sources.values()}
                and relative not in native_configuration
                and relative not in passive_derived
                and not relative.startswith("settings/") and relative != "_heimdal/settings.md"):
                raise OperationsAcceptanceRefusal("undeclared_fixture_source")
            files[relative] = file_hash(target)
    if not any(name.startswith("settings/") for name in files):
        raise OperationsAcceptanceRefusal("canonical_fixture_configuration_missing")
    # Raw archive/restore are installed conditionally. Their fixture is
    # pre-existing native encrypted evidence with actual consent, never a
    # borrowed capture/journaling grant or a caller-provided raw reference.
    from app.heimdal import raw_store
    from app.heimdal.consent_ledger import resolve_active_grant
    from app.heimdal.raw_read_gate import raw_ref_for
    raw = (raw_store.get_raw_record_by_content_identity(raw_store.compute_raw_content_identity(raw_fixture_bytes(identity["operation_id"])))
           if identity["channel"] == "test" else None)
    raw_source = None
    if raw is not None:
        grant = resolve_active_grant(scope=PROFILE + ":" + identity["operation_id"])
        if (grant is None or grant.granted_by != principal.local_operator_role_id
            or raw.consent.get("grant_ref") != grant.grant_ref
            or grant.payload.get("instance_identity") != snapshot.app_install_id
            or grant.payload.get("vault_binding_id") != registration.vault_binding_id):
            raise OperationsAcceptanceRefusal("canonical_raw_fixture_consent_unqualified")
        raw_source = {"artifact_id": raw_ref_for(raw), "content_identity": raw.content_identity,
                      "consent_ref": grant.grant_ref}
    created_at = time()
    context = {"schema": PROFILE, "identity": identity, "created_at": created_at, "expires_at": created_at + MAX_SECONDS,
        "fixture": {"binding_id": registration.vault_binding_id, "root": str(root),
            "principal_id": principal.local_operator_role_id, "principal_revision": principal.revision,
            "principal_record_sha256": file_hash(local_operator_principal_path(registry_path)),
            "registry_sha256": file_hash(registry_path),
            "registry_authority_sha256": registry_authority_sha256,
            "instance_identity": snapshot.app_install_id, "registry_revision": snapshot.revision,
            "sources": sources, "raw_source": raw_source, "files": files,
            "passive_paths": passive_paths}, "selection": None, "slots": None}
    write_private(registry_path.parent / CONTEXT_FILE, context, create=True)
    return public_binding(context)


def fixed_intents(context: dict[str, Any]) -> list[dict[str, Any]]:
    sources = context["fixture"]["sources"]
    if context["identity"]["channel"] == "dev":
        return [{"id": "dev-smoke", "operation_id": "artifact.update", "targets": [{"artifact_id": sources["edit"]["artifact_id"]}],
                 "arguments": {"body": "Synthetic DEV operations smoke.\n"}}]
    slots = []
    for role in ("edit", "batch-a", "batch-b", "partial-a", "partial-b", "browser", "browser-a", "browser-b", "concurrent", "lost-ack"):
        slots.append({"id": role, "operation_id": "artifact.update",
            "targets": [{"artifact_id": sources[role]["artifact_id"]}],
            "arguments": {"body": "Synthetic operations result " + role + ".\n"}})
    for role, operation_id, arguments in (
        ("capture", "artifact.capture", {"text": "Synthetic operations capture once."}),
        ("move", "artifact.move", {"destination": "Notes/operations-acceptance-moved.md"}),
        ("rename", "artifact.rename", {"name": "operations-acceptance-renamed.md"}),
    ):
        slots.append({"id": role, "operation_id": operation_id,
            "targets": [] if role == "capture" else [{"artifact_id": sources[role]["artifact_id"]}], "arguments": arguments})
    if context["fixture"].get("raw_source"):
        for kind in ("archive", "restore"):
            slots.append({"id": kind, "operation_id": "artifact." + kind,
                "targets": [{"artifact_id": context["fixture"]["raw_source"]["artifact_id"], "artifact_class": "source"}],
                "arguments": {}})
    return slots


@router.post("/admission", include_in_schema=False)
def freeze_admission(body: FixedAdmission, request: Request, api_key: str | None = Depends(api_key_header),
    x_active_context_session: str | None = Header(default=None),
    x_active_context_override: str | None = Header(default=None)) -> dict[str, Any]:
    try:
        from app.api.routes.operations import _runtime
        runtime = _runtime(request, api_key, x_active_context_session, x_active_context_override)
        context = load_context(runtime.registry.path, required=True)
        assert context is not None
        store = runtime.kernel.receipt_store
        if not isinstance(store, JsonReceiptStore):
            raise OperationsAcceptanceRefusal("native_operation_journal_required")
        with store.batch_window("acceptance-freeze:" + context["identity"]["operation_id"]):
            context = load_context(runtime.registry.path, required=True)
            assert context is not None
            require_runtime(context, runtime, frozen=context["selection"] is not None)
            if context["selection"] is not None:
                return public_binding(context)
            assert runtime.active_context is not None
            with runtime.selection_window(), context_bound_read_window(runtime.active_context, registry_store=runtime.registry):
                if context["identity"]["channel"] == "test":
                    capabilities = runtime.discovery()
                    from app.operations.contracts import CapabilitySupport
                    for kind in ("artifact.archive", "artifact.restore"):
                        if capabilities.for_operation(kind).support is not CapabilitySupport.SUPPORTED:
                            raise OperationsAcceptanceRefusal("required_native_archive_environment_unqualified")
                    if context["fixture"].get("raw_source") is None:
                        raise OperationsAcceptanceRefusal("canonical_raw_fixture_missing")
                root = Path(context["fixture"]["root"])
                try:
                    observed_files = {}
                    for path in sorted(root.rglob("*")):
                        if path.is_symlink():
                            raise ValueError("changed fixture path")
                        if path.is_file():
                            observed_files[path.relative_to(root).as_posix()] = file_hash(path)
                except Exception:
                    raise OperationsAcceptanceRefusal("fixture_changed_before_freeze") from None
                if observed_files != context["fixture"]["files"]:
                    raise OperationsAcceptanceRefusal("fixture_changed_before_freeze")
                slots = []
                for template in fixed_intents(context):
                    operation = OperationRequest(template["operation_id"], "freeze:" + template["id"], runtime.context,
                        targets=tuple(template["targets"]), arguments=template["arguments"])
                    owner = _runtime(request, api_key, x_active_context_session, x_active_context_override,
                        operation=operation, target_binding_id=context["fixture"]["binding_id"])
                    # Owner composition adds the selected binding to its context;
                    # preconditions must see exactly that immutable context.
                    from dataclasses import replace
                    observed = owner.preconditions(replace(operation, context=owner.context))
                    if observed["status"] != "observed":
                        raise OperationsAcceptanceRefusal("qualified_owner_preconditions_missing")
                    slots.append({"id": template["id"], "intent": {"operation_id": operation.operation_id,
                        "targets": template["targets"], "arguments": observed["arguments"],
                        "expected_version": observed["expected_version"]}})
                context["selection"] = runtime.selection_record.redacted()
                context["api_process_epoch"] = runtime.carrier.service.selection_store.process_epoch
                context["slots"] = slots
                context["expires_at"] = min(context["expires_at"], runtime.selection_record.expires_at)
                write_private(runtime.registry.path.parent / CONTEXT_FILE, context)
                return public_binding(context)
    except OperationsAcceptanceRefusal as exc:
        raise HTTPException(409, exc.reason) from None


def native_probe(registry_path: Path) -> dict[str, Any]:
    """Read existing sources, durable receipts and each projection separately."""
    context = load_context(registry_path, required=True, observation_only=True)
    assert context is not None
    require_native_fixture(context, VaultRegistryStore(registry_path))
    from app.index.doctor import diagnose_index, inspect_source_projections
    from app.operations.execution_kernel import JsonReceiptStore
    root = Path(context["fixture"]["root"])
    projections = inspect_source_projections(
        tuple(UUID(source["artifact_id"]) for source in context["fixture"]["sources"].values()),
        vault_binding_id=context["fixture"]["binding_id"],
    )
    sources = {}
    def locator(value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        if value.startswith("vault://"):
            value = value.removeprefix("vault://")
        path = Path(value)
        if path.is_absolute():
            try:
                path = path.relative_to(root)
            except ValueError:
                return None
        return path.as_posix() if ".." not in path.parts else None
    for role, source in context["fixture"]["sources"].items():
        # Native placement receipts retain the original stable identity while
        # the normal owner changes its path. No guessed new UUID is accepted.
        matches = []
        for path in root.rglob("*.md"):
            if path.is_symlink():
                raise OperationsAcceptanceRefusal("fixture_path_unqualified")
            text, _ = read_note_text_with_version(path)
            if text.startswith("---\n") and ("\nuuid: " + source["artifact_id"] + "\n") in text.split("---", 2)[1]:
                matches.append(path)
        if len(matches) != 1:
            raise OperationsAcceptanceRefusal("native_identity_path_drift")
        path = matches[0]
        projection = projections[source["artifact_id"]]
        source_text = path.read_text().split("---", 2)[-1].strip()
        object_hash = projection["store_content_hash"]
        index_hash = projection["index_content_hash"]
        neighbors = projection["neighbors"]
        sources[role] = {"artifact_id": source["artifact_id"], "path": path.relative_to(root).as_posix(),
            "source_sha256": file_hash(path), "store_sha256": object_hash, "index_sha256": index_hash,
            "links_sha256": digest({"memberships": projection["memberships"], "neighbors": neighbors}),
            "link_neighbors": neighbors,
            "source_store_match": bool(source_text) and source_text in projection["object_text"],
            "store_index_match": object_hash is not None and object_hash == index_hash,
            "store_locator_match": locator(projection["store_source_ref"]) == path.relative_to(root).as_posix(),
            "index_locator_match": locator(projection["index_source_ref"]) == path.relative_to(root).as_posix(),
            "link_read_checked": not any(neighbors.values()) and "[[" not in source_text}
    store = JsonReceiptStore(registry_path.parent / "operation-receipts.json")
    receipts = {}
    for slot in context.get("slots") or []:
        reservation = store.lookup("ygg.acceptance:" + context["identity"]["operation_id"] + ":" + slot["id"])
        if reservation is not None:
            request_id = reservation.outcome.extensions["native_request_id"]
            original = store.lookup(request_id)
            receipts[request_id] = original.outcome.to_dict() if original else None
    # The real configured-backend doctor is distinct from the selected-source
    # coverage above. Its optional legacy coverage scans COMPATIBILITY_BINDING_ID
    # through PostgreSQL, so it cannot qualify this MVR-selected binding (or a
    # memory fixture). Keep that unrelated optional scan out of this proof.
    doctor = diagnose_index(use_cache=False)
    healthy = all(all(row[key] for key in ("source_store_match", "store_index_match", "store_locator_match", "index_locator_match", "link_read_checked"))
                  for row in sources.values())
    settled = all(value is not None and (value.get("receipt") or {}).get("status") == "committed"
                  for value in receipts.values())
    raw_observation = None
    if context["fixture"].get("raw_source") is not None:
        from app.heimdal import raw_store
        source = context["fixture"]["raw_source"]
        record = raw_store.get_raw_record_by_content_identity(source["content_identity"])
        representations = [] if record is None else raw_store.all_raw_representations(record.id)
        active = [row for row in representations if row.active]
        settled = settled and record is not None and len(active) == 1
        raw_observation = {"artifact_id": source["artifact_id"], "content_identity": source["content_identity"],
            "representation_metadata_sha256": digest([
                {"id": row.id, "storage_kind": row.storage_kind, "active": row.active,
                 "sequence": row.sequence, "generation": row.raw_generation} for row in representations]),
            "active_count": len(active)}
    invariants = {"checked": True, "status": "healthy" if settled else "recovery_required",
                  "receipt_hashes": {key: digest(value) for key, value in receipts.items()},
                  "identity_unique": True, "source_count": len(sources),
                  "consumed_slots": len(receipts), "maximum_slots": len(context.get("slots") or []),
                  "raw_source": raw_observation}
    return {"binding": public_binding(context), "sources": sources, "receipts": receipts,
        "native_doctor": {"checked": True, "status": "healthy" if doctor.get("status") == "ok" else "unhealthy", "observation": doctor},
        "native_invariants": invariants,
        "source_store_index_links": {"checked": True, "status": "healthy" if healthy else "pending", "sources": sources}}


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "probe"))
    args = parser.parse_args(argv)
    try:
        registry = Path(os.environ["INSTANCE_VAULT_REGISTRY_PATH"])
        if args.action == "prepare":
            identity = json.load(sys.stdin)
            require_identity(identity)
            if (os.environ.get("VCS_REF") != identity["source_sha"]
                or os.environ.get("PKM_ENVIRONMENT") != identity["channel"]
                or os.environ.get("STORE_SCHEMA_AUTOCREATE", "").lower() in {"1", "true", "yes"}
                or any(file_hash(Path("/app") / name) != expected
                       for name, expected in identity["resource_hashes"].items())):
                raise OperationsAcceptanceRefusal("actual_baked_candidate_mismatch")
            result = prepare_native_context(identity, registry_path=registry)
        else:
            result = native_probe(registry)
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception:
        print(json.dumps({"status": "blocked", "reason": "native_operations_prerequisite_unavailable"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
