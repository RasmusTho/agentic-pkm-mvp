"""One supervised DEV operator restoration of an already-established source identity.

This is deliberately not an ordinary producer and not a generic repair surface.  The
private command is bound into a root-owned request before writer isolation.  A durable
attempt marker is written before the worker can start, so a dispatched or uncertain
worker can only enter cleanup; it can never replay the CAS.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
from typing import Any
from uuid import UUID

from app.instance.binding_ids import COMPATIBILITY_BINDING_ID


REQUEST_CONTRACT = "native-operator-identity-restoration-request.v1"
RECEIPT_CONTRACT = "native-operator-identity-restoration.v1"
OWNER_KIND = "operator-identity-restoration"
ACTION = "operator.restore-established-source-identity"
WRITER_IDENTITY = "operator.identity-restoration"
WRITE_PHASES = frozenset({"not_started", "not_written", "written", "indeterminate"})
REASONS = frozenset({
    "context_refused",
    "authority_refused",
    "lock_acquisition_failed",
    "locked_guard_failed",
    "writer_stop_failed",
    "worker_refused",
    "worker_transport_failed",
    "worker_quiesce_failed",
    "writer_restore_failed",
    "lock_retirement_failed",
    "cleanup_only_recovery",
})


class OperatorIdentityRestorationRefusal(RuntimeError):
    def __init__(self, reason: str) -> None:
        if reason not in REASONS:
            reason = "context_refused"
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class PreparedRewrite:
    original_sha256: str
    candidate_sha256: str
    expected_old_scalar: str
    replacement_uuid: str
    scalar_start: int
    scalar_end: int
    candidate_text: str


_COMMAND_KEYS = {
    "target_rel",
    "expected_old_scalar",
    "replacement_uuid",
}


def validate_command(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) != _COMMAND_KEYS:
        raise OperatorIdentityRestorationRefusal("context_refused")
    try:
        relative = PurePosixPath(payload["target_rel"])
        replacement = str(UUID(payload["replacement_uuid"]))
        if (
            not relative.parts
            or relative.is_absolute()
            or ".." in relative.parts
            or replacement != payload["replacement_uuid"]
            or not isinstance(payload["expected_old_scalar"], str)
            or not payload["expected_old_scalar"].strip()
        ):
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise OperatorIdentityRestorationRefusal("context_refused") from None
    return dict(payload)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _frontmatter_bounds(raw: str) -> tuple[int, int]:
    lines = raw.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        raise OperatorIdentityRestorationRefusal("context_refused")
    closing = next(
        (index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---"),
        None,
    )
    if closing is None:
        raise OperatorIdentityRestorationRefusal("context_refused")
    return len(lines[0]), sum(len(line) for line in lines[:closing])


def prepare_uuid_scalar_rewrite(
    raw: str, *, expected_old_scalar: str, replacement_uuid: str,
) -> PreparedRewrite:
    """Prepare one scalar-only representation repair; never select a new identity."""
    import yaml
    from yaml.nodes import MappingNode, ScalarNode
    from yaml.tokens import AliasToken, AnchorToken

    replacement = str(UUID(replacement_uuid))
    if replacement != replacement_uuid:
        raise OperatorIdentityRestorationRefusal("context_refused")
    try:
        existing_identity = str(UUID(expected_old_scalar))
    except (ValueError, AttributeError, TypeError):
        existing_identity = None
    if existing_identity is not None:
        if existing_identity != replacement or expected_old_scalar == replacement:
            raise OperatorIdentityRestorationRefusal("authority_refused")
    header_start, header_end = _frontmatter_bounds(raw)
    header = raw[header_start:header_end]
    try:
        tokens = tuple(yaml.scan(header))
        root = yaml.compose(header)
        before = yaml.safe_load(header)
    except yaml.YAMLError as exc:
        raise OperatorIdentityRestorationRefusal("context_refused") from exc
    if any(isinstance(token, (AliasToken, AnchorToken)) for token in tokens):
        raise OperatorIdentityRestorationRefusal("authority_refused")
    if not isinstance(root, MappingNode) or not isinstance(before, dict):
        raise OperatorIdentityRestorationRefusal("authority_refused")
    entries = [
        (key, value)
        for key, value in root.value
        if isinstance(key, ScalarNode) and key.value == "uuid"
    ]
    if len(entries) != 1:
        raise OperatorIdentityRestorationRefusal("authority_refused")
    key_node, value_node = entries[0]
    if (
        key_node.tag != "tag:yaml.org,2002:str"
        or not isinstance(value_node, ScalarNode)
        or value_node.tag != "tag:yaml.org,2002:str"
        or value_node.style not in {None, "'", '"'}
        or value_node.value != expected_old_scalar
    ):
        raise OperatorIdentityRestorationRefusal("authority_refused")
    rendered = replacement
    if value_node.style == "'":
        rendered = f"'{replacement}'"
    elif value_node.style == '"':
        rendered = f'"{replacement}"'
    start = header_start + value_node.start_mark.index
    end = header_start + value_node.end_mark.index
    if not (header_start <= start < end <= header_end):
        raise OperatorIdentityRestorationRefusal("authority_refused")
    candidate = raw[:start] + rendered + raw[end:]
    adjusted_end = header_end - (end - start) + len(rendered)
    try:
        after = yaml.safe_load(candidate[header_start:adjusted_end])
    except yaml.YAMLError as exc:
        raise OperatorIdentityRestorationRefusal("authority_refused") from exc
    if not isinstance(after, dict) or after.get("uuid") != replacement:
        raise OperatorIdentityRestorationRefusal("authority_refused")
    before_other = dict(before)
    after_other = dict(after)
    before_other.pop("uuid", None)
    after_other.pop("uuid", None)
    if before_other != after_other:
        raise OperatorIdentityRestorationRefusal("authority_refused")
    return PreparedRewrite(
        original_sha256=_sha256_text(raw),
        candidate_sha256=_sha256_text(candidate),
        expected_old_scalar=expected_old_scalar,
        replacement_uuid=replacement,
        scalar_start=start,
        scalar_end=end,
        candidate_text=candidate,
    )


def _receipt(
    *, operation_id: str, revision: str, result: str, write_phase: str,
    cleanup: str, reason: str | None,
) -> dict[str, Any]:
    payload = {
        "contract": RECEIPT_CONTRACT,
        "operation_id": operation_id,
        "channel": "dev",
        "revision": revision,
        "result": result,
        "write_phase": write_phase,
        "cleanup": cleanup,
        "reason": reason,
        "automatic_producer_started": False,
        "automatic_deployment_started": False,
    }
    return validate_receipt(payload)


def validate_receipt(payload: Any) -> dict[str, Any]:
    expected = {
        "contract", "operation_id", "channel", "revision", "result",
        "write_phase", "cleanup", "reason", "automatic_producer_started",
        "automatic_deployment_started",
    }
    try:
        if (
            not isinstance(payload, dict)
            or set(payload) != expected
            or payload["contract"] != RECEIPT_CONTRACT
            or str(UUID(payload["operation_id"])) != payload["operation_id"]
            or payload["channel"] != "dev"
            or re.fullmatch(r"[0-9a-f]{40}", payload["revision"]) is None
            or payload["result"] not in {"committed", "failed", "unknown"}
            or payload["write_phase"] not in WRITE_PHASES
            or payload["cleanup"] not in {"not_started", "complete", "retained", "unknown"}
            or payload["reason"] not in ({None} | REASONS)
            or payload["automatic_producer_started"] is not False
            or payload["automatic_deployment_started"] is not False
            or (payload["result"] == "committed" and (
                payload["write_phase"] != "written"
                or payload["cleanup"] != "complete"
                or payload["reason"] is not None
            ))
            or (payload["write_phase"] == "indeterminate" and payload["result"] == "committed")
        ):
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise OperatorIdentityRestorationRefusal("context_refused") from None
    return dict(payload)


def _prove_inventory_and_product(
    conn: Any, *, root: Path, target: Path, current: str,
    command: dict[str, Any],
) -> dict[str, tuple[str, tuple[Any, ...], Any]]:
    from app.ingest.vault_alpha import select_source_backed_rebuild_candidates
    from app.knowledge.profile_authority_store import is_profile_note_source
    from app.knowledge.write_ops import read_recovery_snapshot_relative
    from app.objects.identity import resolve_vault_uuid_with_connection
    from app.ops.native_source_identity_persistence import _canonical_uuid
    from app.rebuildability.product_total_loss import canonical_product_body_text
    from app.rebuildability.product_total_loss import parse_bounded_frontmatter
    from app.services.companion_note import read_companion
    from app.services.note_uuid import is_read_only_derived_artifact

    selected = select_source_backed_rebuild_candidates(root)
    selected_rel = tuple(path.resolve().relative_to(root).as_posix() for path in selected)
    target_rel = target.relative_to(root).as_posix()
    if len(selected_rel) != 13 or selected_rel.count(target_rel) != 1:
        raise OperatorIdentityRestorationRefusal("authority_refused")
    snapshots: dict[str, tuple[str, tuple[Any, ...], Any]] = {}
    claims: set[str] = set()
    invalid_targets = 0
    target_body: str | None = None
    for relative in selected_rel:
        raw, identity = read_recovery_snapshot_relative(relative, vault_root=root)
        frontmatter, body, error = parse_bounded_frontmatter(raw)
        if error is not None:
            raise OperatorIdentityRestorationRefusal("authority_refused")
        if relative == target_rel:
            if raw != current or frontmatter.get("uuid") != command["expected_old_scalar"]:
                raise OperatorIdentityRestorationRefusal("authority_refused")
            if _canonical_uuid(frontmatter.get("uuid")) is not None:
                raise OperatorIdentityRestorationRefusal("authority_refused")
            if (
                is_profile_note_source(root, relative, command["replacement_uuid"])
                or is_read_only_derived_artifact(frontmatter)
            ):
                raise OperatorIdentityRestorationRefusal("authority_refused")
            invalid_targets += 1
            companion = None
            target_body = canonical_product_body_text(body)
        else:
            declared = _canonical_uuid(frontmatter.get("uuid"))
            if declared is None or declared in claims:
                raise OperatorIdentityRestorationRefusal("authority_refused")
            companion = read_companion(root, declared)
            if companion is not None and _canonical_uuid(companion.uuid) != declared:
                raise OperatorIdentityRestorationRefusal("authority_refused")
            claims.add(declared)
        snapshots[relative] = (raw, identity, companion)
    if (
        invalid_targets != 1
        or target_body is None
        or command["replacement_uuid"] in claims
    ):
        raise OperatorIdentityRestorationRefusal("authority_refused")
    if tuple(
        path.resolve().relative_to(root).as_posix()
        for path in select_source_backed_rebuild_candidates(root)
    ) != selected_rel:
        raise OperatorIdentityRestorationRefusal("authority_refused")
    for relative, expected in snapshots.items():
        raw, identity = read_recovery_snapshot_relative(relative, vault_root=root)
        companion = expected[2]
        if relative != target_rel:
            frontmatter, _body, error = parse_bounded_frontmatter(raw)
            declared = _canonical_uuid(frontmatter.get("uuid")) if error is None else None
            current_companion = read_companion(root, declared) if declared is not None else None
        else:
            current_companion = None
        if (raw, identity, current_companion) != expected:
            raise OperatorIdentityRestorationRefusal("authority_refused")
    canonical = resolve_vault_uuid_with_connection(
        conn, command["replacement_uuid"], vault_binding_id=COMPATIBILITY_BINDING_ID,
    )
    with conn.cursor() as cursor:
        cursor.execute("SHOW default_transaction_read_only")
        read_only = cursor.fetchone()
        value = read_only.get("default_transaction_read_only") if isinstance(read_only, dict) else read_only[0]
        if str(value).lower() not in {"on", "true"}:
            raise OperatorIdentityRestorationRefusal("authority_refused")
        cursor.execute(
            "SELECT vault_binding_id, object_id::text, source_ref, payload "
            "FROM store_objects WHERE object_id = %s::uuid "
            "OR payload->>'vault_uuid' = %s OR source_ref = %s ORDER BY vault_binding_id, object_id",
            (canonical, command["replacement_uuid"], str(target)),
        )
        rows = cursor.fetchall()
    if len(rows) != 1:
        raise OperatorIdentityRestorationRefusal("authority_refused")
    row = rows[0]
    binding_id = row.get("vault_binding_id") if isinstance(row, dict) else row[0]
    object_id = str(row.get("object_id") if isinstance(row, dict) else row[1])
    source_ref = row.get("source_ref") if isinstance(row, dict) else row[2]
    payload = row.get("payload") if isinstance(row, dict) else row[3]
    if (
        binding_id != COMPATIBILITY_BINDING_ID
        or object_id != canonical
        or source_ref != str(target)
        or not isinstance(payload, dict)
        or payload.get("vault_uuid") != command["replacement_uuid"]
        or not isinstance(payload.get("text"), str)
        or canonical_product_body_text(payload["text"]) != target_body
    ):
        raise OperatorIdentityRestorationRefusal("authority_refused")
    return snapshots


def _prove_other_sources_preserved(
    *, root: Path, target: Path,
    snapshots: dict[str, tuple[str, tuple[Any, ...], Any]],
) -> None:
    from app.ingest.vault_alpha import select_source_backed_rebuild_candidates
    from app.knowledge.write_ops import read_recovery_snapshot_relative
    from app.ops.native_source_identity_persistence import _canonical_uuid
    from app.rebuildability.product_total_loss import parse_bounded_frontmatter
    from app.services.companion_note import read_companion

    target_rel = target.relative_to(root).as_posix()
    if tuple(
        path.resolve().relative_to(root).as_posix()
        for path in select_source_backed_rebuild_candidates(root)
    ) != tuple(snapshots):
        raise OperatorIdentityRestorationRefusal("worker_refused")
    for relative, expected in snapshots.items():
        if relative == target_rel:
            continue
        raw, identity = read_recovery_snapshot_relative(relative, vault_root=root)
        frontmatter, _body, error = parse_bounded_frontmatter(raw)
        declared = _canonical_uuid(frontmatter.get("uuid")) if error is None else None
        companion = read_companion(root, declared) if declared is not None else None
        if (raw, identity, companion) != expected:
            raise OperatorIdentityRestorationRefusal("worker_refused")


def run_worker(
    *, operation_id: str, revision: str, vault_root: Path,
    command: dict[str, Any], connection: Any | None = None,
) -> dict[str, Any]:
    """Run one worker. Once the KnowledgePort call begins, failure is indeterminate."""
    from app.knowledge.multiwriter import NoteClass, WriteOperation, classify_note_in_vault
    from app.knowledge.write_ops import read_note_text_with_version, write_note_from_absolute
    from app.vault.paths import get_vault_capture_note_rel, get_vault_sources_dir_rel
    from app.write_guard import DEFAULT_WRITE_GUARD

    command = validate_command(command)
    root = vault_root.resolve(strict=True)
    target = root.joinpath(*PurePosixPath(command["target_rel"]).parts).resolve(strict=True)
    target.relative_to(root)
    current, expected_version = read_note_text_with_version(target)
    prepared = prepare_uuid_scalar_rewrite(
        current,
        expected_old_scalar=command["expected_old_scalar"],
        replacement_uuid=command["replacement_uuid"],
    )
    relative = target.relative_to(root)
    if classify_note_in_vault(
        relative,
        WriteOperation.WRITE,
        vault_root=root,
        capture_note_rel=get_vault_capture_note_rel(root),
        sources_root_rel=get_vault_sources_dir_rel(root),
    ) is not NoteClass.REWRITTEN:
        raise OperatorIdentityRestorationRefusal("authority_refused")
    owns_connection = connection is None
    if connection is None:
        from app.stores.pg import _connect

        if "default_transaction_read_only=on" not in os.environ.get("PGOPTIONS", ""):
            raise OperatorIdentityRestorationRefusal("authority_refused")
        connection = _connect()
    try:
        snapshots = _prove_inventory_and_product(
            connection, root=root, target=target, current=current, command=command,
        )
    finally:
        if owns_connection:
            connection.close()
    DEFAULT_WRITE_GUARD.assert_writes_allowed(ACTION)
    try:
        receipt = write_note_from_absolute(
            target,
            prepared.candidate_text,
            vault_root=root,
            action=ACTION,
            expected_version=expected_version,
            writer_identity=WRITER_IDENTITY,
        )
    except Exception:
        return _receipt(
            operation_id=operation_id, revision=revision, result="unknown",
            write_phase="indeterminate", cleanup="not_started",
            reason="worker_transport_failed",
        )
    if receipt.outcome != "written" or receipt.note_class != NoteClass.REWRITTEN.value:
        return _receipt(
            operation_id=operation_id, revision=revision, result="unknown",
            write_phase="indeterminate", cleanup="not_started",
            reason="worker_refused",
        )
    try:
        observed, observed_version = read_note_text_with_version(target)
        if observed != prepared.candidate_text or observed_version != prepared.candidate_sha256:
            raise RuntimeError
        _prove_other_sources_preserved(
            root=root, target=target, snapshots=snapshots,
        )
    except Exception:
        return _receipt(
            operation_id=operation_id, revision=revision, result="unknown",
            write_phase="indeterminate", cleanup="not_started",
            reason="worker_refused",
        )
    return _receipt(
        operation_id=operation_id, revision=revision, result="unknown",
        write_phase="written", cleanup="not_started", reason=None,
    )


def worker_main(argv: list[str]) -> int:
    if len(argv) != 4:
        return 78
    operation_id, channel, revision, root_value = argv
    try:
        if channel != "dev" or str(UUID(operation_id)) != operation_id:
            raise ValueError
        command = json.load(os.fdopen(os.dup(0), "r", encoding="utf-8"))
        result = run_worker(
            operation_id=operation_id,
            revision=revision,
            vault_root=Path(root_value),
            command=command,
        )
    except Exception:
        result = _receipt(
            operation_id=operation_id,
            revision=revision,
            result="failed",
            write_phase="not_written",
            cleanup="not_started",
            reason="worker_refused",
        )
    print(json.dumps(result, sort_keys=True))
    # A fixed failed/not-written receipt is still a successfully transported
    # worker result.  The host owns cleanup and the final terminal verdict.
    return 0


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    from app.ops.postgres_deploy_linux import _atomic_private_json

    _atomic_private_json(path, payload)


def _read_private_json(path: Path) -> Any:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as exc:
        raise OperatorIdentityRestorationRefusal("context_refused") from exc
    try:
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_nlink != 1
            or not 0 < info.st_size <= 65536
        ):
            raise OperatorIdentityRestorationRefusal("context_refused")
        with os.fdopen(descriptor, "r", encoding="utf-8") as source:
            descriptor = -1
            return json.load(source, object_pairs_hook=_unique_object)
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = dict(pairs)
    if len(result) != len(pairs):
        raise OperatorIdentityRestorationRefusal("context_refused")
    return result


def _private_entry_present(path: Path) -> bool:
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise OperatorIdentityRestorationRefusal("context_refused") from exc
    if not stat.S_ISREG(info.st_mode):
        raise OperatorIdentityRestorationRefusal("context_refused")
    return True


def _cleanup(
    effects: Any, *, operation_id: str, revision: str, image_digest: str,
    selected: Any, owner: dict[str, str], request: dict[str, Any],
) -> bool:
    """Cleanup only; never invokes the worker or the CAS."""
    expected_owner = (json.dumps(owner, sort_keys=True) + "\n").encode()
    observed_owner = effects.channel_lock_owner()
    if observed_owner not in {None, expected_owner}:
        raise OperatorIdentityRestorationRefusal("cleanup_only_recovery")
    if observed_owner is None:
        from app.ops.postgres_deploy_linux import _installed_fingerprint_matches
        from app.ops.native_source_bootstrap import quiesce_owned_container

        effects.qualify_source_identity_authority(revision, image_digest, selected)
        runtime = effects.source_identity_runtime_snapshot(
            selected, require_running_capture=True,
        )
        if (
            not _installed_fingerprint_matches(runtime, request["installed_fingerprint"])
            or runtime.container_root != request["container_root"]
            or runtime.vault_overlay != request["vault_overlay"]
            or tuple(sorted(request["writers"])) != runtime.running_writers
            or not set(request["writers"]) <= set(runtime.existing_writers)
        ):
            raise OperatorIdentityRestorationRefusal("cleanup_only_recovery")
        name = f"pkm-dev-operator-identity-restoration-{operation_id}"
        if not quiesce_owned_container("dev", name, operation_id, revision):
            raise OperatorIdentityRestorationRefusal("worker_quiesce_failed")
        restored = effects.source_identity_runtime_snapshot(
            selected, require_running_capture=True,
        )
        if (
            tuple(sorted(request["writers"])) != restored.running_writers
            or not _installed_fingerprint_matches(restored, request["installed_fingerprint"])
            or effects.channel_lock_owner() is not None
        ):
            raise OperatorIdentityRestorationRefusal("cleanup_only_recovery")
        return True
    with effects.failed_reconciliation_lock(expected_owner=owner) as handle:
        from app.ops.native_source_bootstrap import quiesce_owned_container

        name = f"pkm-dev-operator-identity-restoration-{operation_id}"
        if not quiesce_owned_container("dev", name, operation_id, revision):
            raise OperatorIdentityRestorationRefusal("worker_quiesce_failed")
        effects.qualify_source_identity_authority(revision, image_digest, selected)
        runtime = effects.source_identity_runtime_snapshot(
            selected, require_running_capture=False,
        )
        writers = request["writers"]
        from app.ops.postgres_deploy_linux import _installed_fingerprint_matches

        if (
            not _installed_fingerprint_matches(runtime, request["installed_fingerprint"])
            or runtime.container_root != request["container_root"]
            or runtime.vault_overlay != request["vault_overlay"]
            or not set(writers) <= set(runtime.existing_writers)
            or set(runtime.running_writers) - set(writers)
        ):
            raise OperatorIdentityRestorationRefusal("cleanup_only_recovery")
        effects.compose(
            "start", *writers, cutover=selected, timeout=120,
            source_snapshot=runtime,
        )
        restored = effects.source_identity_runtime_snapshot(
            selected, require_running_capture=True,
        )
        if (
            tuple(sorted(writers)) != restored.running_writers
            or not _installed_fingerprint_matches(restored, request["installed_fingerprint"])
            or restored.container_root != request["container_root"]
            or restored.vault_overlay != request["vault_overlay"]
        ):
            raise OperatorIdentityRestorationRefusal("writer_restore_failed")
        effects.retire_reconciled_channel_lock(handle, expected_owner=owner)
    return True


def run_host_operation(
    effects: Any, *, operation_id: str, revision: str, image_digest: str,
    selected: Any, command: dict[str, Any], resume_unattempted: bool = False,
) -> dict[str, Any]:
    """Run once or perform exact cleanup-only reconciliation."""
    from app.ops.postgres_deploy_linux import PostgresDeployError, _source_worker_user

    command = validate_command(command)
    command_sha256 = hashlib.sha256(
        json.dumps(command, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    try:
        if (
            effects.config.channel != "dev"
            or str(UUID(operation_id)) != operation_id
            or re.fullmatch(r"[0-9a-f]{40}", revision) is None
            or re.fullmatch(r"sha256:[0-9a-f]{64}", image_digest) is None
            or type(resume_unattempted) is not bool
        ):
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise PostgresDeployError() from None
    selected.validate()
    directory = effects.config.journal.directory
    prefix = f"dev-operator-identity-restoration-{operation_id}"
    request_path = directory / f"{prefix}.request.json"
    attempt_path = directory / f"{prefix}.attempt.json"
    worker_path = directory / f"{prefix}.worker.json"
    receipt_path = directory / f"{prefix}.json"
    owner = {"kind": OWNER_KIND, "channel": "dev", "operation_id": operation_id}

    def operation_receipt(payload: Any) -> dict[str, Any]:
        receipt = validate_receipt(payload)
        if receipt["operation_id"] != operation_id or receipt["revision"] != revision:
            raise PostgresDeployError()
        return receipt

    def validate_request(payload: Any) -> dict[str, Any]:
        expected = {
            "contract", "operation_id", "channel", "revision", "image_digest",
            "authority_cutover", "installed_fingerprint", "execution_fingerprint",
            "writers", "container_root", "vault_overlay", "command_sha256",
        }
        authority = payload.get("authority_cutover") if isinstance(payload, dict) else None
        if (
            not isinstance(payload, dict) or set(payload) != expected
            or payload["contract"] != REQUEST_CONTRACT
            or payload["operation_id"] != operation_id or payload["channel"] != "dev"
            or payload["revision"] != revision or payload["image_digest"] != image_digest
            or authority != {
                "binding_id": selected.binding_id, "root": selected.root,
                "ownership_root": selected.ownership_root,
            }
            or payload["command_sha256"] != command_sha256
            or not isinstance(payload["writers"], list)
            or any(not isinstance(item, str) for item in payload["writers"])
            or any(not isinstance(payload[key], str) or not payload[key] for key in {
                "installed_fingerprint", "execution_fingerprint", "container_root", "vault_overlay",
            })
        ):
            raise PostgresDeployError()
        return payload

    present = {
        "request": _private_entry_present(request_path),
        "attempt": _private_entry_present(attempt_path),
        "worker": _private_entry_present(worker_path),
        "receipt": _private_entry_present(receipt_path),
    }
    if (
        (present["attempt"] or present["worker"] or present["receipt"])
        and not present["request"]
    ) or (present["worker"] and not present["attempt"]):
        raise PostgresDeployError()
    request_evidence = (
        validate_request(_read_private_json(request_path)) if present["request"] else None
    )
    attempt_evidence = _read_private_json(attempt_path) if present["attempt"] else None
    if attempt_evidence is not None and (
        not isinstance(attempt_evidence, dict)
        or set(attempt_evidence) != {"contract", "operation_id", "dispatch_staged"}
        or attempt_evidence["contract"]
        != "native-operator-identity-restoration-attempt.v1"
        or attempt_evidence["operation_id"] != operation_id
        or attempt_evidence["dispatch_staged"] is not True
    ):
        raise PostgresDeployError()
    worker_evidence = (
        operation_receipt(_read_private_json(worker_path)) if present["worker"] else None
    )
    terminal_evidence = (
        operation_receipt(_read_private_json(receipt_path)) if present["receipt"] else None
    )
    if (
        terminal_evidence is not None
        and terminal_evidence["write_phase"] in {"written", "indeterminate"}
        and attempt_evidence is None
    ):
        raise PostgresDeployError()
    if terminal_evidence is not None:
        receipt = terminal_evidence
        if request_evidence is None:
            raise PostgresDeployError()
        request = request_evidence
        _cleanup(
            effects, operation_id=operation_id, revision=revision,
            image_digest=image_digest, selected=selected, owner=owner, request=request,
        )
        if worker_evidence is not None:
            receipt = worker_evidence
        if receipt["cleanup"] != "complete":
            receipt = {**receipt, "cleanup": "complete"}
            if receipt["write_phase"] == "written" and receipt["reason"] is None:
                receipt["result"] = "committed"
            receipt = validate_receipt(receipt)
            _atomic_json(receipt_path, receipt)
        return receipt

    if request_evidence is not None:
        request = request_evidence
        if attempt_evidence is not None:
            # A durable attempt marker means the worker may have crossed the CAS.
            # Cleanup is the only permitted continuation.
            _cleanup(
                effects, operation_id=operation_id, revision=revision,
                image_digest=image_digest, selected=selected, owner=owner, request=request,
            )
            retained = (
                worker_evidence
                if worker_evidence is not None
                else _receipt(
                    operation_id=operation_id, revision=revision, result="unknown",
                    write_phase="indeterminate", cleanup="complete",
                    reason="cleanup_only_recovery",
                )
            )
            terminal = {**retained, "cleanup": "complete"}
            if terminal["write_phase"] == "written" and terminal["reason"] is None:
                terminal["result"] = "committed"
            _atomic_json(receipt_path, validate_receipt(terminal))
            return validate_receipt(terminal)
        observed_owner = effects.channel_lock_owner()
        expected_owner = (json.dumps(owner, sort_keys=True) + "\n").encode()
        if observed_owner not in {None, expected_owner} or present["worker"]:
            raise PostgresDeployError()
        if observed_owner == expected_owner:
            _cleanup(
                effects, operation_id=operation_id, revision=revision,
                image_digest=image_digest, selected=selected, owner=owner,
                request=request,
            )
            if effects.channel_lock_owner() is not None:
                raise PostgresDeployError()
        if not resume_unattempted:
            # The exact pre-dispatch lock has been cleaned up, but only an
            # explicit reviewed resume may proceed to a worker dispatch.
            raise PostgresDeployError()
    else:
        runtime = effects.source_identity_runtime_snapshot(
            selected, require_running_capture=True,
        )
        writers = list(runtime.running_writers)
        if not {"api", "worker", "watcher"} <= set(writers):
            raise PostgresDeployError()
        request = {
            "contract": REQUEST_CONTRACT,
            "operation_id": operation_id,
            "channel": "dev",
            "revision": revision,
            "image_digest": image_digest,
            "authority_cutover": {
                "binding_id": selected.binding_id,
                "root": selected.root,
                "ownership_root": selected.ownership_root,
            },
            "installed_fingerprint": runtime.installed_fingerprint,
            "execution_fingerprint": runtime.execution_fingerprint,
            "writers": writers,
            "container_root": runtime.container_root,
            "vault_overlay": runtime.vault_overlay,
            "command_sha256": command_sha256,
        }
        _atomic_json(request_path, request)

    plan = effects.qualify_source_identity_authority(revision, image_digest, selected)
    effects.require_source_identity_candidate(
        plan, selected, acquire=True,
        source_snapshot=effects.source_identity_runtime_snapshot(
            selected, require_running_capture=True,
        ),
    )
    effects.operation_id = operation_id
    lock_acquired = False
    cleanup_complete = False
    worker_receipt: dict[str, Any] | None = None
    attempt_written = False
    failure_reason = "lock_acquisition_failed"
    try:
        with effects.channel_lock(
            journal=effects.config.journal, owner_marker=owner, retire_terminal=False,
        ):
            lock_acquired = True
            runtime = effects.source_identity_runtime_snapshot(
                selected, require_running_capture=True,
            )
            if (
                runtime.installed_fingerprint != request["installed_fingerprint"]
                or runtime.execution_fingerprint != request["execution_fingerprint"]
                or tuple(sorted(request["writers"])) != runtime.running_writers
            ):
                raise PostgresDeployError()
            effects.require_source_identity_candidate(
                plan, selected, acquire=False, source_snapshot=runtime,
            )
            failure_reason = "writer_stop_failed"
            effects.compose(
                "stop", *request["writers"], cutover=selected, timeout=120,
                source_snapshot=runtime,
            )
            # Durable before dispatch: from this point, retry is cleanup-only.
            _atomic_json(attempt_path, {
                "contract": "native-operator-identity-restoration-attempt.v1",
                "operation_id": operation_id,
                "dispatch_staged": True,
            })
            attempt_written = True
            name = f"pkm-dev-operator-identity-restoration-{operation_id}"
            raw = effects.compose(
                "run", "--no-deps", "-T", "--name", name,
                "--label", f"yggdrasil.native.operation={operation_id}",
                "--label", f"yggdrasil.native.revision={revision}",
                "--user", _source_worker_user(effects.config),
                *[
                    item
                    for key, _value in runtime.child_environment
                    for item in ("-e", key)
                ],
                *[
                    item
                    for key in runtime.unset_environment
                    for item in ("-e", key)
                ],
                "-e", "PGOPTIONS=-c default_transaction_read_only=on",
                "--entrypoint", "python", "api", "-m",
                "app.ops.native_operator_identity_restoration",
                operation_id, "dev", revision, runtime.container_root,
                cutover=selected, candidate=plan, timeout=7200,
                source_snapshot=runtime,
                input_text=json.dumps(command, sort_keys=True) + "\n",
            )
            worker_receipt = operation_receipt(json.loads(raw))
            _atomic_json(worker_path, worker_receipt)
    except Exception:
        if worker_receipt is None and attempt_written:
            worker_receipt = _receipt(
                operation_id=operation_id, revision=revision, result="unknown",
                write_phase="indeterminate", cleanup="retained",
                reason="worker_transport_failed",
            )
    finally:
        if not lock_acquired:
            cleanup_complete = True
        else:
            try:
                cleanup_complete = _cleanup(
                    effects, operation_id=operation_id, revision=revision,
                    image_digest=image_digest, selected=selected, owner=owner,
                    request=request,
                )
            except Exception:
                cleanup_complete = False
    if worker_receipt is None:
        worker_receipt = _receipt(
            operation_id=operation_id, revision=revision, result="failed",
            write_phase="not_written", cleanup="not_started",
            reason=failure_reason,
        )
    terminal = {
        **worker_receipt,
        "cleanup": "complete" if cleanup_complete else "retained",
    }
    if cleanup_complete and terminal["write_phase"] == "written" and terminal["reason"] is None:
        terminal["result"] = "committed"
    if not cleanup_complete:
        terminal["result"] = "unknown" if terminal["write_phase"] in {"written", "indeterminate"} else "failed"
        terminal["reason"] = "writer_restore_failed"
    terminal = validate_receipt(terminal)
    _atomic_json(receipt_path, terminal)
    return terminal


if __name__ == "__main__":
    import sys

    raise SystemExit(worker_main(sys.argv[1:]))


__all__ = [
    "ACTION",
    "OWNER_KIND",
    "OperatorIdentityRestorationRefusal",
    "PreparedRewrite",
    "RECEIPT_CONTRACT",
    "prepare_uuid_scalar_rewrite",
    "run_host_operation",
    "run_worker",
    "validate_command",
    "validate_receipt",
    "worker_main",
]
