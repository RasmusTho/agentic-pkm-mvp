"""Fixed operations acceptance facts and evidence; never Product authority.

The private context is an operation-owned narrowing of an already authorized
isolated binding. Selection, GOV, CAS and the native owners still authorize
every call. Slot reservations use the existing operation journal, including
its UNKNOWN/no-replay behavior; there is no acceptance permission store.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
from tempfile import NamedTemporaryFile
from time import time
from typing import Any

from app.operations.contracts import OperationOutcome, OperationStatus
from app.operations.execution_kernel import JsonReceiptStore

PROFILE = "native-operations-acceptance.v1"
CONTEXT_FILE = "native-operations-acceptance.json"
RECEIPT = "yggdrasil-autonomous-operations-acceptance.v1"
MAX_SECONDS = 3600
ROLES = ("read", "edit", "move", "rename", "batch-a", "batch-b", "partial-a", "partial-b",
         "browser", "browser-a", "browser-b", "collision", "concurrent", "lost-ack")
FAMILIES = ("artifact.list", "artifact.read", "artifact.search", "artifact.related", "artifact.capture",
            "artifact.create", "artifact.update", "artifact.move", "artifact.rename", "artifact.classify",
            "artifact.tags.add", "artifact.tags.remove", "collection.reorder", "artifact.archive", "artifact.restore")
TEST_SCENARIOS = ("native_admission", "sdk_profiles", "qualified_families", "operation_receipt_parity",
    "browser_discovery", "browser_selected_preflight", "browser_confirmation_progress", "browser_cancel",
    "browser_receipt_recovery", "browser_conflict", "authority_refusals", "hostile_collision_cas",
    "concurrent_refusal", "partial_batch", "dropped_acknowledgement", "client_restart",
    "backend_wsp_restart", "projection_lag", "native_doctor", "native_invariants", "source_store_index_links")
DEV_SCENARIOS = ("native_admission", "sdk_profiles", "qualified_reads", "dev_operation_receipt",
                 "native_doctor", "native_invariants", "source_store_index_links")
SELECTION_HASH = hashlib.sha256(json.dumps([PROFILE, ROLES, FAMILIES, TEST_SCENARIOS, DEV_SCENARIOS,
                                           MAX_SECONDS], separators=(",", ":")).encode()).hexdigest()


class OperationsAcceptanceRefusal(RuntimeError):
    """Only fixed, content-free causes cross a CLI or HTTP boundary."""
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__("operations acceptance refused: " + reason)


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def file_hash(path: Path, *, max_bytes: int = 128 * 1024 * 1024) -> str:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > max_bytes:
            raise OperationsAcceptanceRefusal("artifact_unqualified")
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_private(path: Path, *, max_bytes: int = 64 * 1024 * 1024) -> dict[str, Any]:
    try:
        if any(parent.is_symlink() for parent in path.parents):
            raise ValueError()
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "r") as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > max_bytes):
                raise ValueError()
            value = json.load(stream)
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (OSError, ValueError, TypeError):
        raise OperationsAcceptanceRefusal("private_evidence_unqualified") from None


def write_private(path: Path, value: dict[str, Any], *, create: bool = False) -> None:
    if any(parent.is_symlink() for parent in (path.parent, *path.parents)):
        raise OperationsAcceptanceRefusal("private_evidence_unqualified")
    info = path.parent.stat()
    if stat.S_IMODE(info.st_mode) != 0o700 or info.st_uid != os.geteuid():
        raise OperationsAcceptanceRefusal("private_evidence_unqualified")
    with NamedTemporaryFile(dir=path.parent, mode="w", delete=False) as stream:
        temporary = Path(stream.name)
        try:
            json.dump(value, stream, sort_keys=True, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
            if create:
                os.link(temporary, path, follow_symlinks=False)
            else:
                read_private(path)
                os.replace(temporary, path)
            directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            temporary.unlink(missing_ok=True)


def inventory(channel: str) -> tuple[str, ...]:
    if channel not in {"dev", "test"}:
        raise OperationsAcceptanceRefusal("nonproduction_channel_required")
    return TEST_SCENARIOS if channel == "test" else DEV_SCENARIOS


def require_identity(value: dict[str, Any], *, channel: str | None = None) -> None:
    try:
        if (value["channel"] not in {"dev", "test"} or channel is not None and value["channel"] != channel
            or re.fullmatch(r"[0-9a-f]{40}", value["source_sha"]) is None
            or re.fullmatch(r"sha256:[0-9a-f]{64}", value["image_digest"]) is None
            or re.fullmatch(r"[0-9a-f]{40}", value["resource_tree"]) is None
            or value["profile"] != PROFILE or value["selection_hash"] != SELECTION_HASH
            or value["execution_kind"] not in {"deployed", "premerge"}
            or value["activation_scope"] != "full"
            or not all(value.get(key) for key in ("operation_id", "api_container_id", "ui_container_id",
                                                   "resource_hashes", "producer_hashes", "sidecar", "native_receipt_sha256"))):
            raise ValueError()
        package = value["sidecar"]
        if (package["source_sha"] != value["source_sha"] or package["distribution"] != "mimer-mcp-sidecar"
            or not package["files"] or not package["sdk_files"] or not package["runtime"]
            or any(re.fullmatch(r"[0-9a-f]{64}", h) is None for h in
                   [*package["files"].values(), *package["sdk_files"].values()])):
            raise ValueError()
        if value["execution_kind"] == "deployed" and (
            not package.get("browser", {}).get("playwright")
            or re.fullmatch(r"[0-9a-f]{64}", str(package.get("browser", {}).get("executable_sha256"))) is None
        ):
            raise ValueError()
    except (KeyError, TypeError, ValueError):
        raise OperationsAcceptanceRefusal("candidate_or_separate_sdk_unqualified") from None


def public_binding(context: dict[str, Any]) -> dict[str, Any]:
    fixture = context["fixture"]
    return {"identity": context["identity"], "native_context_sha256": digest(context),
        "fixture_sha256": digest(fixture), "principal_id": fixture["principal_id"],
        "instance_identity": fixture["instance_identity"], "binding_id": fixture["binding_id"],
        "source_inventory": {role: {key: row[key] for key in ("artifact_id", "path", "seed_sha256")}
                             for role, row in fixture["sources"].items()},
        "selection": context.get("selection"), "slots": context.get("slots"),
        "api_process_epoch": context.get("api_process_epoch"),
        "expires_at": context["expires_at"], "required_scenarios": list(inventory(context["identity"]["channel"]))}


def load_context(registry_path: Path, *, required: bool = False, observation_only: bool = False) -> dict[str, Any] | None:
    path = registry_path.parent / CONTEXT_FILE
    if not path.exists() and not path.is_symlink() and not required:
        return None
    value = read_private(path, max_bytes=1024 * 1024)
    require_identity(value.get("identity", {}))
    expires = value.get("expires_at")
    created = value.get("created_at")
    if (not isinstance(expires, (int, float)) or isinstance(expires, bool)
        or not isinstance(created, (int, float)) or isinstance(created, bool)
        or not math.isfinite(expires) or not math.isfinite(created) or not created < expires <= created + MAX_SECONDS
        or value.get("schema") != PROFILE or not observation_only and expires <= time()
        or not isinstance(value.get("fixture"), dict)):
        raise OperationsAcceptanceRefusal("native_admission_unavailable")
    return value


def require_native_fixture(context: dict[str, Any], registry: Any) -> None:
    """Current native fixture facts for effects and observation-only recovery."""
    fixture = context["fixture"]
    try:
        snapshot, authority_sha256 = registry.read_qualification_state()
    except Exception:
        raise OperationsAcceptanceRefusal("native_registry_state_unqualified") from None
    registration = snapshot.registrations.get(fixture["binding_id"])
    from app.instance.runtime import local_operator_principal_path, open_local_operator_principal_store
    principal = open_local_operator_principal_store(registry.path).require()
    if (principal.local_operator_role_id != fixture["principal_id"] or principal.revision != fixture["principal_revision"]
        or snapshot.app_install_id != fixture["instance_identity"]
        or registration is None or registration.extensions.get("status") != "initialized"
        or registration.extensions.get(PROFILE) != {"operation_id": context["identity"]["operation_id"]}
        or str(Path(registration.path).resolve(strict=True)) != fixture["root"]
        or snapshot.revision != fixture["registry_revision"]):
        raise OperationsAcceptanceRefusal("native_actor_instance_binding_changed")
    if (authority_sha256 != fixture.get("registry_authority_sha256")
        or file_hash(local_operator_principal_path(registry.path)) != fixture["principal_record_sha256"]):
        raise OperationsAcceptanceRefusal("native_principal_registry_generation_changed")
    identity = context["identity"]
    if identity["execution_kind"] == "deployed":
        if (os.environ.get("VCS_REF") != identity["source_sha"] or os.environ.get("PKM_ENVIRONMENT") != identity["channel"]
            or any(file_hash(Path("/app") / name) != expected for name, expected in identity["resource_hashes"].items())):
            raise OperationsAcceptanceRefusal("actual_native_candidate_changed")
    settings = Path(fixture["root"]) / "settings"
    current_settings = {path.relative_to(Path(fixture["root"])).as_posix(): file_hash(path)
                        for path in settings.rglob("*") if path.is_file()}
    heimdal = Path(fixture["root"]) / "_heimdal/settings.md"
    if heimdal.exists():
        current_settings["_heimdal/settings.md"] = file_hash(heimdal)
    if current_settings != {name: value for name, value in fixture["files"].items() if name.startswith("settings/") or name == "_heimdal/settings.md"}:
        raise OperationsAcceptanceRefusal("frozen_source_configuration_changed")
    # Derive the same fixed passive facts from their current native owners;
    # the private context records original identity/bytes, never permission.
    try:
        from app.vault.layout import load_layout
        from app.vault.manager import VaultContext
        from app.briefing.compose import briefing_note_path
        from app.briefing.trigger import BRIEFING_ENABLED, _local_now
        root = Path(fixture["root"])
        current_passive = {"layout": load_layout(root).note_path}
        if BRIEFING_ENABLED:
            current_passive["briefing"] = briefing_note_path(
                vault_context=VaultContext(status="selected", active_vault_path=str(root)),
                for_date=_local_now(None).date())
        observed_paths = {}
        for kind, target in current_passive.items():
            if any(path.is_symlink() for path in (target, *target.parents) if path.is_relative_to(root)):
                raise ValueError("aliased passive path")
            relative = target.resolve(strict=True).relative_to(root).as_posix()
            if file_hash(target) != fixture["files"].get(relative):
                raise ValueError("changed passive prestate")
            observed_paths[kind] = relative
        if observed_paths != fixture.get("passive_paths"):
            raise ValueError("changed native passive selection")
    except Exception:
        raise OperationsAcceptanceRefusal("frozen_source_configuration_changed") from None


def require_runtime(context: dict[str, Any], runtime: Any, *, frozen: bool = True) -> None:
    require_native_fixture(context, runtime.registry)
    fixture = context["fixture"]
    if (runtime.actor != fixture["principal_id"] or runtime.selection_record.instance_identity != fixture["instance_identity"]
        or runtime.active_context.principal_context.revision != fixture["principal_revision"]
        or runtime.selection_record.binding_ids != (fixture["binding_id"],)):
        raise OperationsAcceptanceRefusal("native_actor_instance_binding_changed")
    if frozen and context.get("selection") != runtime.selection_record.redacted():
        raise OperationsAcceptanceRefusal("frozen_selection_changed")


def require_effect(runtime: Any, operation: Any, *, consume: bool = True) -> None:
    """Additional narrowing at the actual owner seam, after native GOV checks.

    A slot is reserved durably before the first source effect. An interrupted
    or unknown attempt consumes it too. Only the same native request may reenter
    checks; kernel recovery, never this hook, decides whether it can reconcile.
    """
    context = load_context(runtime.registry.path, observation_only=True)
    if context is None:
        return
    fixture = context["fixture"]
    target = runtime.context.extensions.get("target_binding_id")
    if target != fixture["binding_id"]:
        return
    if context["expires_at"] <= time():
        raise OperationsAcceptanceRefusal("native_admission_expired")
    require_runtime(context, runtime)
    selected = {"operation_id": operation.operation_id, "targets": list(operation.targets),
                "arguments": dict(operation.arguments), "expected_version": operation.expected_version}
    slots = [slot for slot in context.get("slots", []) if slot["intent"] == selected]
    if len(slots) != 1:
        raise OperationsAcceptanceRefusal("outside_frozen_operations_budget")
    if operation.operation_id == "artifact.capture":
        from app.vault.paths import get_vault_capture_note_rel
        source = fixture["sources"]["capture"]
        if (get_vault_capture_note_rel(Path(fixture["root"])) != source["path"]
            or file_hash(Path(fixture["root"]) / source["path"]) != source["seed_sha256"]):
            raise OperationsAcceptanceRefusal("frozen_capture_prestate_changed")
    if not consume:
        return
    slot = slots[0]
    store = runtime.kernel.receipt_store
    if not isinstance(store, JsonReceiptStore):
        raise OperationsAcceptanceRefusal("native_operation_journal_required")
    key = "ygg.acceptance:" + context["identity"]["operation_id"] + ":" + slot["id"]
    reservation = OperationOutcome(key, OperationStatus.RECOVERY_REQUIRED, operation.operation_id, operation.context,
        extensions={"native_request_id": operation.request_id, "slot": slot["id"],
                    "native_context_sha256": digest(context)})
    result, _ = store.reserve(key, digest([selected, operation.request_id, digest(context)]), reservation)
    if result == "conflict":
        raise OperationsAcceptanceRefusal("operations_slot_already_consumed")


def produce_receipt(binding: dict[str, Any], observations: list[dict[str, Any]], directory: Path,
                    *, started_at: float, finished_at: float, test_receipt: dict[str, Any] | None = None) -> dict[str, Any]:
    """Admit original per-scenario observations and actual private artifacts."""
    identity = binding["identity"]
    require_identity(identity)
    expected = inventory(identity["channel"])
    if (not started_at <= finished_at <= started_at + MAX_SECONDS
        or [row.get("id") for row in observations] != list(expected)):
        raise OperationsAcceptanceRefusal("required_inventory_incomplete")
    if identity["channel"] == "dev":
        expected_status = "PASS" if identity["execution_kind"] == "deployed" else "PREMERGE_PASS"
        if (test_receipt is None or test_receipt.get("schema") != RECEIPT or test_receipt.get("status") != expected_status
            or test_receipt.get("binding", {}).get("identity", {}).get("channel") != "test"
            or any(test_receipt["binding"]["identity"].get(key) != identity[key]
                   for key in ("source_sha", "image_digest", "resource_tree", "resource_hashes", "producer_hashes", "sidecar", "execution_kind"))):
            raise OperationsAcceptanceRefusal("same_candidate_test_receipt_required")
    hashes: dict[str, str] = {}
    for row in observations:
        if (row.get("status") != "passed" or row.get("binding_sha256") != digest(binding)
            or row.get("producer") != "original_observer" or not row.get("proof")
            or not isinstance(row.get("observed_at"), (int, float))
            or not started_at <= row["observed_at"] <= finished_at
            or not isinstance(row.get("artifacts"), dict) or not row["artifacts"]):
            raise OperationsAcceptanceRefusal("required_observation_not_passed")
        for name, expected_hash in row["artifacts"].items():
            relative = Path(name)
            if (relative.is_absolute() or ".." in relative.parts or not relative.parts
                or any(p.is_symlink() for p in [directory / relative, *(directory / relative).parents])
                or file_hash(directory / relative) != expected_hash):
                raise OperationsAcceptanceRefusal("original_artifact_binding_mismatch")
            hashes[name] = expected_hash
    # Native probes must be actual, separate observations. Missing/lagged
    # projections cannot be inferred from a committed source receipt.
    rows = {row["id"]: row for row in observations}
    if rows["native_admission"]["proof"].get("native") != binding:
        raise OperationsAcceptanceRefusal("original_native_admission_binding_mismatch")
    for row in observations:
        path = directory / (row["id"] + ".json")
        if path.name not in row["artifacts"] or read_private(path) != row["proof"]:
            raise OperationsAcceptanceRefusal("original_observer_artifact_mismatch")
    for name in ("native_doctor", "native_invariants", "source_store_index_links"):
        proof = rows[name]["proof"]
        if proof.get("checked") is not True or proof.get("status") != "healthy":
            raise OperationsAcceptanceRefusal("native_probe_missing_or_lagged")
    invariants = rows["native_invariants"]["proof"]
    required_slots = 15 if identity["channel"] == "test" else 1
    if (invariants.get("consumed_slots") != required_slots or invariants.get("maximum_slots") != required_slots
        or not invariants.get("identity_unique") or invariants.get("source_count") != len(ROLES) + 1):
        raise OperationsAcceptanceRefusal("original_finite_effect_inventory_incomplete")
    if identity["channel"] == "test":
        families = rows["qualified_families"]["proof"].get("families", {})
        if set(families) != set(FAMILIES) or any(
            row.get("status") != "succeeded" if row.get("support") == "supported" else
            row.get("status") != "not_supported" or not row.get("native_reason")
            for row in families.values()
        ):
            raise OperationsAcceptanceRefusal("qualified_family_success_missing")
        required = {"artifact.list", "artifact.read", "artifact.search", "artifact.related", "artifact.capture",
                    "artifact.update", "artifact.move", "artifact.rename", "artifact.archive", "artifact.restore"}
        if any(families[kind].get("support") != "supported" for kind in required):
            raise OperationsAcceptanceRefusal("required_native_family_unqualified")
        profiles = rows["sdk_profiles"]["proof"]
        if (profiles.get("v1") != identity["sidecar"].get("v1_contract")
            or not profiles.get("v2", {}).get("items") or not profiles.get("tools")):
            raise OperationsAcceptanceRefusal("original_sdk_discovery_missing")
        parity = rows["operation_receipt_parity"]["proof"].get("receipts", {})
        if set(parity) != {"capture", "edit", "move", "rename", "archive", "restore"} or any(
            not value.get("sdk") or value.get("sdk") != value.get("http") or value.get("sdk") != value.get("native")
            or value["sdk"].get("receipt", {}).get("status") != "committed" for value in parity.values()
        ):
            raise OperationsAcceptanceRefusal("original_receipt_parity_missing")
        refusals = rows["authority_refusals"]["proof"]
        if (len(refusals.get("cases", {})) != 12
            or any(value.get("status") != "refused" for value in refusals["cases"].values())
            or not refusals.get("source_hashes") or refusals["source_hashes"] != refusals.get("after_source_hashes")):
            raise OperationsAcceptanceRefusal("original_authority_refusals_missing")
        hostile = rows["hostile_collision_cas"]["proof"]
        if (set(hostile.get("cases", {})) != {"traversal", "absolute", "protected", "collision", "stale_cas"}
            or not hostile.get("source_hashes") or hostile["source_hashes"] != hostile.get("after_source_hashes")):
            raise OperationsAcceptanceRefusal("original_path_refusals_missing")
        concurrent = rows["concurrent_refusal"]["proof"].get("outcomes", [])
        if len(concurrent) != 2 or sum(value.get("convergence", {}).get("source_effect") == "committed" for value in concurrent) != 1:
            raise OperationsAcceptanceRefusal("original_concurrent_refusal_missing")
        partial = rows["partial_batch"]["proof"]
        if (partial.get("partial", {}).get("counts", {}).get("completed") != 1
            or partial.get("successful_batch", {}).get("counts", {}).get("completed") != 2
            or any([item.get("outcome") for item in partial.get(key, {}).get("items", [])]
                   != [item.get("outcome") for item in partial["partial"].get("items", [])] for key in ("retained", "cancelled"))):
            raise OperationsAcceptanceRefusal("original_partial_recovery_missing")
        for name in ("dropped_acknowledgement", "client_restart"):
            proof = rows[name]["proof"]
            if (proof.get("source_posts") != 1 or proof.get("source_replays") != 0
                or proof.get("pre_sha256") == proof.get("post_sha256") or not proof.get("original")):
                raise OperationsAcceptanceRefusal("original_no_replay_recovery_missing")
        if not rows["projection_lag"]["proof"].get("lagged_count", 0) > 0:
            raise OperationsAcceptanceRefusal("original_projection_lag_missing")
        if rows["backend_wsp_restart"]["proof"].get("separate_native_authority") is not True:
            raise OperationsAcceptanceRefusal("separate_restart_authority_missing")
        for name in ("browser_discovery", "browser_selected_preflight", "browser_confirmation_progress",
                     "browser_cancel", "browser_receipt_recovery", "browser_conflict"):
            if not rows[name]["proof"].get("observed") or "browser-actions.json" not in rows[name]["artifacts"]:
                raise OperationsAcceptanceRefusal("original_served_browser_observation_missing")
    deployed = identity["execution_kind"] == "deployed"
    return {"schema": RECEIPT, "status": "PASS" if deployed else "PREMERGE_PASS",
        "execution_kind": identity["execution_kind"], "binding": binding,
        "required_scenarios": list(expected), "observations": observations,
        "started_at": started_at, "finished_at": finished_at, "artifact_hashes": hashes,
        "test_receipt_sha256": digest(test_receipt) if test_receipt is not None else None}


def read_original_test_receipt(path: Path) -> dict[str, Any]:
    """Recheck the original complete TEST report and its original artifacts.

    A report is evidence, never a native effect grant. DEV admission still
    derives its own current native principal, candidate and finite effects.
    """
    original = read_private(path)
    try:
        if original["binding"]["identity"]["channel"] != "test":
            raise ValueError()
        checked = produce_receipt(original["binding"], original["observations"], path.parent,
            started_at=original["started_at"], finished_at=original["finished_at"])
        if checked != original:
            raise ValueError()
        return checked
    except (KeyError, TypeError, ValueError):
        raise OperationsAcceptanceRefusal("original_test_receipt_unqualified") from None
