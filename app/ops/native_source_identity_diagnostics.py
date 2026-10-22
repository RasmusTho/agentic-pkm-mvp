"""Count-only Product database witness for source-identity diagnostics.

The source observer and this witness are deliberately separate actors.  The
source observer stays network-isolated; this witness has database connectivity
but no source mounts.  Its stdin request is private transport material and its
only public output is a fixed aggregate receipt.
"""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import shlex
import signal
import subprocess
import sys
import threading
from typing import Any, Callable


REQUEST_CONTRACT = "native-source-identity-database-witness-request.v1"
RECEIPT_CONTRACT = "native-source-identity-database-witness.v1"
SOURCE_PREPARE_CONTRACT = "native-source-identity-source-prepare.v1"
SOURCE_RECEIPT_CONTRACT = "native-source-identity-diagnostic.v1"
DATABASE_WITNESS_SERVICE = "source-identity-db-witness"
OWNER_LABEL = "com.agentic-pkm.source-identity-diagnostic-owner"
MAX_REQUEST_BYTES = 64 * 1024
MAX_PRIVATE_FRAME_BYTES = 128 * 1024
MAX_RECEIPT_BYTES = 16 * 1024
MAX_OBSERVATIONS = 4096
COUNT_FIELDS = (
    "selected_count",
    "product_filesystem_complete_count",
    "product_absent_count",
    "product_conflict_count",
    "locator_or_body_mismatch_count",
    "duplicate_or_foreign_claim_count",
)
OUTCOME_FIELDS = COUNT_FIELDS[1:]
REASONS = {None, "database_witness_refused"}
_SHA256 = re.compile(r"[0-9a-f]{64}")
_REVISION = re.compile(r"[0-9a-f]{40}")
_DATABASE_ENVIRONMENT_KEYS = frozenset({
    "DATABASE_URL",
    "DB_DSN",
    "PGDATABASE",
    "PGHOST",
    "PGOPTIONS",
    "PGPASSWORD",
    "PGPORT",
    "PGSERVICE",
    "PGUSER",
})
_NON_DATABASE_ENVIRONMENT_KEYS = frozenset({
    "LANG",
    "LC_ALL",
    "PATH",
    "PYTHONPATH",
    "SSL_CERT_DIR",
    "SSL_CERT_FILE",
})
SOURCE_COUNT_FIELDS = (
    "registry_selected_count",
    "registry_persisted_count",
    "registry_missing_count",
    "registry_invalid_count",
    "registry_ambiguous_count",
    "authority_candidate_count",
    "protected_authority_candidate_count",
    "source_observation_unknown_count",
)
_SOURCE_CONFIGURATION_KEYS = (
    "PKM_SETTINGS_PROFILE",
    "VAULT_INBOX_DIR_REL",
    "VAULT_SYSTEM_DIR_REL",
    "WATCHER_SCOPE_GLOB",
)


class SourceIdentityDiagnosticRefusal(RuntimeError):
    """Content-free refusal for the bounded diagnostic boundary."""


def _valid_channel_revision(channel: Any, revision: Any) -> bool:
    return (
        channel in {"dev", "test"}
        and isinstance(revision, str)
        and _REVISION.fullmatch(revision) is not None
    )


def _empty_counts() -> dict[str, int]:
    return {field: 0 for field in COUNT_FIELDS}


def _receipt(
    *,
    channel: str,
    revision: str,
    reason: str | None,
    counts: dict[str, int] | None = None,
) -> dict[str, Any]:
    values = _empty_counts()
    if counts is not None:
        values.update(counts)
    return validate_receipt({
        "contract": RECEIPT_CONTRACT,
        "channel": channel,
        "revision": revision,
        "terminal_state": "observed" if reason is None else "refused",
        "reason": reason,
        **values,
    })


def validate_receipt(payload: Any) -> dict[str, Any]:
    required = {
        "contract", "channel", "revision", "terminal_state", "reason",
        *COUNT_FIELDS,
    }
    if not isinstance(payload, dict) or set(payload) != required:
        raise SourceIdentityDiagnosticRefusal("database_witness_refused")
    if (
        payload["contract"] != RECEIPT_CONTRACT
        or not _valid_channel_revision(payload["channel"], payload["revision"])
        or payload["terminal_state"] not in {"observed", "refused"}
        or payload["reason"] not in REASONS
        or any(
            type(payload[field]) is not int or payload[field] < 0
            for field in COUNT_FIELDS
        )
    ):
        raise SourceIdentityDiagnosticRefusal("database_witness_refused")
    if payload["terminal_state"] == "observed":
        if (
            payload["reason"] is not None
            or sum(payload[field] for field in OUTCOME_FIELDS)
            != payload["selected_count"]
        ):
            raise SourceIdentityDiagnosticRefusal("database_witness_refused")
    elif (
        payload["reason"] != "database_witness_refused"
        or any(payload[field] for field in COUNT_FIELDS)
    ):
        raise SourceIdentityDiagnosticRefusal("database_witness_refused")
    return payload


def _validate_request(payload: Any, *, channel: str, revision: str) -> tuple[dict[str, str], ...]:
    if (
        not isinstance(payload, dict)
        or set(payload) != {"contract", "channel", "revision", "observations"}
        or payload.get("contract") != REQUEST_CONTRACT
        or payload.get("channel") != channel
        or payload.get("revision") != revision
        or not isinstance(payload.get("observations"), list)
        or not 1 <= len(payload["observations"]) <= MAX_OBSERVATIONS
    ):
        raise SourceIdentityDiagnosticRefusal("database_witness_refused")
    observations: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in payload["observations"]:
        if (
            not isinstance(item, dict)
            or set(item) != {
                "source_ref", "body_sha256", "source_version_sha256",
            }
            or not isinstance(item.get("source_ref"), str)
            or not item["source_ref"]
            or "\x00" in item["source_ref"]
            or not os.path.isabs(item["source_ref"])
            or os.path.normpath(item["source_ref"]) != item["source_ref"]
            or not isinstance(item.get("body_sha256"), str)
            or _SHA256.fullmatch(item["body_sha256"]) is None
            or not isinstance(item.get("source_version_sha256"), str)
            or _SHA256.fullmatch(item["source_version_sha256"]) is None
            or item["source_ref"] in seen
        ):
            raise SourceIdentityDiagnosticRefusal("database_witness_refused")
        seen.add(item["source_ref"])
        observations.append(item)
    return tuple(observations)


def _read_only_requested() -> bool:
    try:
        tokens = shlex.split(os.environ.get("PGOPTIONS", ""))
    except ValueError:
        return False
    return any(
        token == "default_transaction_read_only=on"
        and index > 0
        and tokens[index - 1] == "-c"
        for index, token in enumerate(tokens)
    )


def closed_witness_environment(environment: dict[str, str]) -> dict[str, str]:
    """Retain only connection and interpreter inputs for the witness child."""
    return {
        key: value
        for key, value in environment.items()
        if key in _DATABASE_ENVIRONMENT_KEYS
        or key in _NON_DATABASE_ENVIRONMENT_KEYS
        or key.startswith("PG")
    }


def _row_value(row: Any, key: str, index: int) -> Any:
    return row.get(key) if isinstance(row, dict) else row[index]


def _query_source_rows(connection: Any, source_ref: str) -> tuple[Any, ...]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT vault_binding_id, object_id::text, source_ref, payload "
            "FROM store_objects WHERE source_ref = %s "
            "ORDER BY vault_binding_id, object_id",
            (source_ref,),
        )
        return tuple(cursor.fetchall())


def _query_identity_rows(
    connection: Any,
    *,
    source_ref: str,
    retained_identity: str,
    resolved_identity: str,
) -> tuple[Any, ...]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT vault_binding_id, object_id::text, source_ref, payload "
            "FROM store_objects WHERE object_id = %s::uuid "
            "OR payload->>'vault_uuid' = %s OR source_ref = %s "
            "ORDER BY vault_binding_id, object_id",
            (resolved_identity, retained_identity, source_ref),
        )
        return tuple(cursor.fetchall())


def _connection_is_read_only(connection: Any) -> bool:
    with connection.cursor() as cursor:
        cursor.execute("SHOW default_transaction_read_only")
        row = cursor.fetchone()
    value = _row_value(row, "default_transaction_read_only", 0)
    return str(value).lower() in {"on", "true"}


def _production_connection() -> Any:
    from app.ops.native_operator_identity_restoration import _connect_worker_database

    return _connect_worker_database()


def _production_dependencies() -> tuple[
    Callable[[Any], str | None],
    Callable[[str], str],
    Callable[[Any, str], str],
    str,
]:
    from app.instance.binding_ids import COMPATIBILITY_BINDING_ID
    from app.objects.identity import resolve_vault_uuid_with_connection
    from app.ops.native_source_identity_persistence import _canonical_uuid
    from app.rebuildability.product_total_loss import canonical_product_body_text

    return (
        _canonical_uuid,
        canonical_product_body_text,
        lambda connection, identity: resolve_vault_uuid_with_connection(
            connection,
            identity,
            vault_binding_id=COMPATIBILITY_BINDING_ID,
        ),
        COMPATIBILITY_BINDING_ID,
    )


def run_database_witness(
    payload: Any,
    *,
    channel: str,
    revision: str,
    connection_factory: Callable[[], Any] = _production_connection,
    dependencies: tuple[
        Callable[[Any], str | None],
        Callable[[str], str],
        Callable[[Any, str], str],
        str,
    ] | None = None,
) -> dict[str, Any]:
    """Return fixed aggregate counts or a content-free refusal."""
    if not _valid_channel_revision(channel, revision):
        raise SourceIdentityDiagnosticRefusal("database_witness_refused")
    try:
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            observations = _validate_request(
                payload,
                channel=channel,
                revision=revision,
            )
            if not _read_only_requested():
                raise SourceIdentityDiagnosticRefusal("database_witness_refused")
            canonical_uuid, canonical_body, resolve_identity, binding_id = (
                dependencies or _production_dependencies()
            )
            counts = _empty_counts()
            counts["selected_count"] = len(observations)
            connection = connection_factory()
            try:
                if not _connection_is_read_only(connection):
                    raise SourceIdentityDiagnosticRefusal(
                        "database_witness_refused",
                    )
                for observation in observations:
                    source_ref = observation["source_ref"]
                    rows = _query_source_rows(connection, source_ref)
                    if not rows:
                        counts["product_absent_count"] += 1
                        continue
                    if len(rows) != 1:
                        counts["product_conflict_count"] += 1
                        continue
                    row = rows[0]
                    row_binding = _row_value(row, "vault_binding_id", 0)
                    object_id = str(_row_value(row, "object_id", 1))
                    row_source_ref = _row_value(row, "source_ref", 2)
                    row_payload = _row_value(row, "payload", 3)
                    retained_identity = (
                        canonical_uuid(row_payload.get("vault_uuid"))
                        if isinstance(row_payload, dict)
                        else None
                    )
                    resolved_identity = (
                        resolve_identity(connection, retained_identity)
                        if retained_identity is not None
                        else None
                    )
                    if (
                        row_binding != binding_id
                        or retained_identity is None
                        or not isinstance(row_payload, dict)
                        or row_payload.get("vault_uuid") != retained_identity
                        or resolved_identity is None
                        or canonical_uuid(resolved_identity) != resolved_identity
                        or object_id != resolved_identity
                        or row_source_ref != source_ref
                        or not isinstance(row_payload.get("text"), str)
                    ):
                        counts["product_conflict_count"] += 1
                        continue
                    body_sha256 = hashlib.sha256(
                        canonical_body(row_payload["text"]).encode("utf-8"),
                    ).hexdigest()
                    if body_sha256 != observation["body_sha256"]:
                        counts["locator_or_body_mismatch_count"] += 1
                        continue
                    global_rows = _query_identity_rows(
                        connection,
                        source_ref=source_ref,
                        retained_identity=retained_identity,
                        resolved_identity=resolved_identity,
                    )
                    if len(global_rows) != 1 or global_rows[0] != row:
                        counts["duplicate_or_foreign_claim_count"] += 1
                        continue
                    counts["product_filesystem_complete_count"] += 1
            finally:
                connection.close()
        return _receipt(
            channel=channel,
            revision=revision,
            reason=None,
            counts=counts,
        )
    except Exception:
        return _receipt(
            channel=channel,
            revision=revision,
            reason="database_witness_refused",
        )


def validate_source_observation_create_argv(
    argv: tuple[str, ...],
    *,
    image_environment: tuple[str, ...],
) -> tuple[str, ...]:
    """Fail closed unless a source-observation container has no DB route."""
    networks: list[str] = []
    for index, item in enumerate(argv):
        if item == "--network":
            if index + 1 >= len(argv):
                raise SourceIdentityDiagnosticRefusal("database_witness_refused")
            networks.append(argv[index + 1])
        elif item.startswith("--network="):
            networks.append(item.removeprefix("--network="))
        elif item == "--net" or item.startswith("--net="):
            raise SourceIdentityDiagnosticRefusal("database_witness_refused")
    if networks != ["none"]:
        raise SourceIdentityDiagnosticRefusal("database_witness_refused")
    def database_key(value: str) -> bool:
        key = value.split("=", 1)[0]
        return key in {"DATABASE_URL", "DB_DSN"} or key.startswith("PG")

    for item in image_environment:
        if not isinstance(item, str) or database_key(item):
            raise SourceIdentityDiagnosticRefusal("database_witness_refused")
    for index, item in enumerate(argv):
        if item in {"-e", "--env"}:
            if index + 1 >= len(argv) or database_key(argv[index + 1]):
                raise SourceIdentityDiagnosticRefusal(
                    "database_witness_refused",
                )
        if item.startswith("--env=") and database_key(item.removeprefix("--env=")):
            raise SourceIdentityDiagnosticRefusal("database_witness_refused")
        if item.startswith("-e") and item != "-e" and database_key(item[2:]):
            raise SourceIdentityDiagnosticRefusal("database_witness_refused")
        if item == "--env-file" or item.startswith("--env-file="):
            raise SourceIdentityDiagnosticRefusal("database_witness_refused")
        if item in {"--device", "-v", "--volume"} or item.startswith((
            "--device=", "--volume=", "-v",
        )):
            raise SourceIdentityDiagnosticRefusal("database_witness_refused")
        mount: str | None = None
        if item == "--mount":
            if index + 1 >= len(argv):
                raise SourceIdentityDiagnosticRefusal("database_witness_refused")
            mount = argv[index + 1]
        elif item.startswith("--mount="):
            mount = item.removeprefix("--mount=")
        if mount is not None:
            fields = dict(
                part.split("=", 1) for part in mount.split(",") if "=" in part
            )
            target = fields.get("target", fields.get("dst", fields.get("destination", "")))
            source = fields.get("source", fields.get("src", ""))
            if (
                fields.get("type") not in {"bind", "volume"}
                or not target.startswith("/")
                or target == "/run"
                or target.startswith("/run/")
                or target == "/var/run"
                or target.startswith("/var/run/")
                or ".s.PGSQL" in target
                or "docker.sock" in target
                or ".s.PGSQL" in source
                or "docker.sock" in source
            ):
                raise SourceIdentityDiagnosticRefusal("database_witness_refused")
    return argv


def _source_capture(
    vault_root: Path,
    *,
    source_ref_root: str,
    channel: str,
    revision: str,
) -> dict[str, Any]:
    """Capture one private canonical registry snapshot without source mutation."""
    from app.knowledge.profile_authority_store import is_profile_note_source_read_only
    from app.knowledge.write_ops import read_recovery_snapshot_relative
    from app.ops.native_source_identity_persistence import (
        _canonical_uuid,
        _registry_plan,
        registry_identity_inventory,
    )
    from app.rebuildability.product_total_loss import (
        canonical_product_body_text,
        parse_bounded_frontmatter,
    )
    from app.services.note_uuid import is_read_only_derived_artifact

    root = vault_root.expanduser().resolve(strict=True)
    canonical_ref_root = PurePosixPath(source_ref_root)
    if (
        not canonical_ref_root.is_absolute()
        or str(canonical_ref_root) != source_ref_root
    ):
        raise SourceIdentityDiagnosticRefusal("database_witness_refused")
    policy, observations = _registry_plan(root)
    inventory = registry_identity_inventory(root, observations)
    request_observations: list[dict[str, str]] = []
    protected_count = 0
    unknown_count = 0
    authority_candidate_count = 0
    all_source_versions: list[tuple[str, str]] = []
    for observation in observations:
        relative = observation.path.relative_to(root).as_posix()
        raw, identity = read_recovery_snapshot_relative(relative, vault_root=root)
        version_payload = json.dumps(
            {
                "raw_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
                "identity": identity,
            },
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        source_version_sha256 = hashlib.sha256(version_payload).hexdigest()
        all_source_versions.append((relative, source_version_sha256))
        frontmatter, body, error = parse_bounded_frontmatter(raw)
        if error is not None:
            unknown_count += 1
            continue
        declared_raw = frontmatter.get("uuid")
        if declared_raw in (None, "") or _canonical_uuid(declared_raw) is not None:
            continue
        authority_candidate_count += 1
        try:
            if (
                is_profile_note_source_read_only(root, relative, None)
                or is_read_only_derived_artifact(frontmatter)
            ):
                protected_count += 1
                continue
            body_sha256 = hashlib.sha256(
                canonical_product_body_text(body).encode("utf-8"),
            ).hexdigest()
            request_observations.append({
                "source_ref": str(canonical_ref_root / relative),
                "body_sha256": body_sha256,
                "source_version_sha256": source_version_sha256,
            })
        except Exception:
            unknown_count += 1
    request = {
        "contract": REQUEST_CONTRACT,
        "channel": channel,
        "revision": revision,
        "observations": request_observations,
    }
    _validate_request(request, channel=channel, revision=revision)
    counts = {
        "registry_selected_count": inventory.selected_count,
        "registry_persisted_count": inventory.persisted_count,
        "registry_missing_count": inventory.missing_count,
        "registry_invalid_count": inventory.invalid_count,
        "registry_ambiguous_count": inventory.ambiguous_count,
        "authority_candidate_count": authority_candidate_count,
        "protected_authority_candidate_count": protected_count,
        "source_observation_unknown_count": unknown_count,
    }
    if (
        len(observations) != inventory.selected_count
        or authority_candidate_count != len(request_observations) + protected_count
        or authority_candidate_count > inventory.invalid_count
    ):
        raise SourceIdentityDiagnosticRefusal("database_witness_refused")
    snapshot_payload = json.dumps(
        {
            "policy_registry_digest": policy.registry_digest,
            "counts": counts,
            "request": request,
            "all_source_versions": all_source_versions,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        "contract": SOURCE_PREPARE_CONTRACT,
        "channel": channel,
        "revision": revision,
        "source_snapshot_sha256": hashlib.sha256(snapshot_payload).hexdigest(),
        "counts": counts,
        "request": request,
    }


def _validate_source_prepare(payload: Any, *, channel: str, revision: str) -> dict[str, Any]:
    if (
        not isinstance(payload, dict)
        or set(payload) != {
            "contract", "channel", "revision", "source_snapshot_sha256",
            "counts", "request",
        }
        or payload.get("contract") != SOURCE_PREPARE_CONTRACT
        or payload.get("channel") != channel
        or payload.get("revision") != revision
        or not isinstance(payload.get("source_snapshot_sha256"), str)
        or _SHA256.fullmatch(payload["source_snapshot_sha256"]) is None
        or not isinstance(payload.get("counts"), dict)
        or set(payload["counts"]) != set(SOURCE_COUNT_FIELDS)
        or any(
            type(payload["counts"][field]) is not int
            or payload["counts"][field] < 0
            for field in SOURCE_COUNT_FIELDS
        )
    ):
        raise SourceIdentityDiagnosticRefusal("database_witness_refused")
    observations = _validate_request(
        payload.get("request"), channel=channel, revision=revision,
    )
    counts = payload["counts"]
    if (
        counts["registry_selected_count"]
        != counts["registry_persisted_count"]
        + counts["registry_missing_count"]
        + counts["registry_invalid_count"]
        or counts["registry_ambiguous_count"] > counts["registry_persisted_count"]
        or counts["authority_candidate_count"] != (
            len(observations)
            + counts["protected_authority_candidate_count"]
        )
        or counts["authority_candidate_count"]
        + counts["source_observation_unknown_count"]
        > counts["registry_invalid_count"]
    ):
        raise SourceIdentityDiagnosticRefusal("database_witness_refused")
    return payload


def finalize_source_observation(
    prepare: Any,
    database_receipt: Any,
    *,
    vault_root: Path,
    source_ref_root: str,
    channel: str,
    revision: str,
) -> dict[str, Any]:
    """Re-fence the private source snapshot and return fixed public counts."""
    prepared = _validate_source_prepare(prepare, channel=channel, revision=revision)
    receipt = validate_receipt(database_receipt)
    if (
        receipt["terminal_state"] != "observed"
        or receipt["channel"] != channel
        or receipt["revision"] != revision
        or receipt["selected_count"] != len(prepared["request"]["observations"])
        or _source_capture(
            vault_root,
            source_ref_root=source_ref_root,
            channel=channel,
            revision=revision,
        ) != prepared
    ):
        raise SourceIdentityDiagnosticRefusal("database_witness_refused")
    result = {
        "contract": SOURCE_RECEIPT_CONTRACT,
        "channel": channel,
        "revision": revision,
        "terminal_state": "observed",
        "reason": None,
        **prepared["counts"],
        **{field: receipt[field] for field in COUNT_FIELDS},
    }
    return validate_source_receipt(result)


def validate_source_receipt(payload: Any) -> dict[str, Any]:
    required = {
        "contract", "channel", "revision", "terminal_state", "reason",
        *SOURCE_COUNT_FIELDS, *COUNT_FIELDS,
    }
    if (
        not isinstance(payload, dict)
        or set(payload) != required
        or payload.get("contract") != SOURCE_RECEIPT_CONTRACT
        or not _valid_channel_revision(payload.get("channel"), payload.get("revision"))
        or payload.get("terminal_state") != "observed"
        or payload.get("reason") is not None
        or any(
            type(payload[field]) is not int or payload[field] < 0
            for field in (*SOURCE_COUNT_FIELDS, *COUNT_FIELDS)
        )
        or payload["registry_selected_count"] != (
            payload["registry_persisted_count"]
            + payload["registry_missing_count"]
            + payload["registry_invalid_count"]
        )
        or payload["registry_ambiguous_count"] > payload["registry_persisted_count"]
        or payload["authority_candidate_count"] != (
            payload["selected_count"]
            + payload["protected_authority_candidate_count"]
        )
        or payload["authority_candidate_count"]
        + payload["source_observation_unknown_count"]
        > payload["registry_invalid_count"]
        or sum(payload[field] for field in OUTCOME_FIELDS) != payload["selected_count"]
    ):
        raise SourceIdentityDiagnosticRefusal("database_witness_refused")
    return payload


def _kill_process_group(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return


def _run_bounded_status(
    argv: tuple[str, ...],
    *,
    input_bytes: bytes,
    max_output_bytes: int,
    timeout_seconds: float = 120.0,
) -> tuple[int, bytes]:
    """Run one child while retaining at most the explicit stdout bound."""
    process = subprocess.Popen(
        argv,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    output = bytearray()
    exceeded = threading.Event()
    write_failed = threading.Event()

    def drain() -> None:
        assert process.stdout is not None
        while True:
            chunk = process.stdout.read(8192)
            if not chunk:
                return
            remaining = max_output_bytes - len(output)
            if len(chunk) > remaining:
                output.extend(chunk[:max(remaining, 0)])
                exceeded.set()
                _kill_process_group(process)
                return
            output.extend(chunk)

    def supply() -> None:
        assert process.stdin is not None
        try:
            process.stdin.write(input_bytes)
            process.stdin.close()
        except BrokenPipeError:
            return
        except Exception:
            write_failed.set()
            _kill_process_group(process)

    reader = threading.Thread(target=drain, daemon=True)
    writer = threading.Thread(target=supply, daemon=True)
    reader.start()
    writer.start()
    try:
        returncode = process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        _kill_process_group(process)
        process.wait()
        raise SourceIdentityDiagnosticRefusal("database_witness_refused") from None
    finally:
        reader.join(timeout=5.0)
        writer.join(timeout=5.0)
    if (
        reader.is_alive()
        or writer.is_alive()
        or exceeded.is_set()
        or write_failed.is_set()
    ):
        raise SourceIdentityDiagnosticRefusal("database_witness_refused")
    return returncode, bytes(output)


def _run_bounded_child(
    argv: tuple[str, ...],
    *,
    input_bytes: bytes,
    max_output_bytes: int,
    timeout_seconds: float = 120.0,
) -> bytes:
    returncode, output = _run_bounded_status(
        argv,
        input_bytes=input_bytes,
        max_output_bytes=max_output_bytes,
        timeout_seconds=timeout_seconds,
    )
    if returncode != 0:
        raise SourceIdentityDiagnosticRefusal("database_witness_refused")
    return output


def _assert_owned_container_absent(name: str) -> None:
    returncode, output = _run_bounded_status(
        (
            "docker", "container", "ls", "--all", "--filter",
            f"name=^/{name}$", "--format", "{{.Names}}",
        ),
        input_bytes=b"",
        max_output_bytes=1024,
        timeout_seconds=30.0,
    )
    if returncode != 0 or output.strip():
        raise SourceIdentityDiagnosticRefusal("database_witness_refused")


def _cleanup_owned_container(name: str, owner_token: str) -> None:
    if re.fullmatch(r"[0-9a-f]{32}", owner_token) is None:
        raise SourceIdentityDiagnosticRefusal("database_witness_refused")
    inspect_format = (
        f'{{{{.Id}}}}\t{{{{ index .Config.Labels "{OWNER_LABEL}" }}}}'
    )
    returncode, ownership = _run_bounded_status(
        (
            "docker", "container", "inspect", "--format",
            inspect_format, name,
        ),
        input_bytes=b"",
        max_output_bytes=1024,
        timeout_seconds=30.0,
    )
    if returncode == 1:
        _assert_owned_container_absent(name)
        return
    try:
        container_id_raw, observed_owner = ownership.strip().split(b"\t", 1)
        container_id = container_id_raw.decode("ascii")
    except Exception:
        raise SourceIdentityDiagnosticRefusal("database_witness_refused") from None
    if (
        returncode != 0
        or re.fullmatch(r"[0-9a-f]{64}", container_id) is None
        or observed_owner != owner_token.encode("ascii")
    ):
        raise SourceIdentityDiagnosticRefusal("database_witness_refused")
    remove_returncode, _output = _run_bounded_status(
        ("docker", "container", "rm", "--force", container_id),
        input_bytes=b"",
        max_output_bytes=1024,
        timeout_seconds=30.0,
    )
    if remove_returncode != 0:
        raise SourceIdentityDiagnosticRefusal("database_witness_refused")
    after_returncode, replacement = _run_bounded_status(
        (
            "docker", "container", "inspect", "--format",
            inspect_format, name,
        ),
        input_bytes=b"",
        max_output_bytes=1024,
        timeout_seconds=30.0,
    )
    if after_returncode == 1:
        _assert_owned_container_absent(name)
        return
    if after_returncode == 0 and replacement.strip():
        # A replacement now owns the deterministic name. Never remove it, and
        # refuse the diagnostic because the collision invalidates provenance.
        raise SourceIdentityDiagnosticRefusal("database_witness_refused")
    raise SourceIdentityDiagnosticRefusal("database_witness_refused")


def _immutable_image_reference(value: str) -> bool:
    digest = value.split("@", 1)[1] if "@" in value else value
    return digest.startswith("sha256:") and _SHA256.fullmatch(digest[7:]) is not None


def source_observation_run_argv(
    *,
    mode: str,
    source_image: str,
    source_root: Path,
    container_source_root: str,
    source_environment: tuple[str, ...],
    channel: str,
    revision: str,
    container_name: str,
    owner_token: str,
) -> tuple[str, ...]:
    """Build the exact immutable, network-none source actor invocation."""
    if (
        mode not in {"source-prepare", "source-finalize"}
        or not _immutable_image_reference(source_image)
        or not _valid_channel_revision(channel, revision)
        or re.fullmatch(r"pkm-source-id-(?:prepare|finalize)-[0-9a-f]{12}", container_name)
        is None
        or re.fullmatch(r"[0-9a-f]{32}", owner_token) is None
    ):
        raise SourceIdentityDiagnosticRefusal("database_witness_refused")
    container_root = PurePosixPath(container_source_root)
    if (
        not container_root.is_absolute()
        or str(container_root) != container_source_root
        or container_source_root in {"/", "/run", "/var/run"}
        or container_source_root.startswith(("/run/", "/var/run/"))
        or "," in container_source_root
    ):
        raise SourceIdentityDiagnosticRefusal("database_witness_refused")
    root = source_root.expanduser().resolve(strict=True)
    if "," in str(root):
        raise SourceIdentityDiagnosticRefusal("database_witness_refused")
    argv = (
        "docker", "run", "--rm", "--name", container_name,
        "--label", f"{OWNER_LABEL}={owner_token}",
        "--network", "none", "--read-only", "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges:true",
        *(item for entry in source_environment for item in ("--env", entry)),
        "--mount",
        f"type=bind,source={root},target={container_source_root},readonly",
        source_image,
        "python", "-m", "app.ops.native_source_identity_diagnostics",
        mode, channel, revision, container_source_root,
    )
    validate_source_observation_create_argv(argv, image_environment=())
    return argv


def _closed_source_environment(
    environment: dict[str, str],
    *,
    container_source_root: str,
) -> tuple[str, ...]:
    """Retain canonical non-DB registry inputs for the isolated source actor."""
    values = {
        "WATCHER_ENABLE": "1",
        "WATCHER_VAULT_PATH": container_source_root,
    }
    for key in _SOURCE_CONFIGURATION_KEYS:
        value = environment.get(key)
        if value is not None:
            values[key] = value
    return tuple(f"{key}={values[key]}" for key in sorted(values))


def _inspect_image_environment(
    source_image: str,
    *,
    child_runner: Callable[..., bytes],
) -> tuple[str, ...]:
    raw = child_runner(
        (
            "docker", "image", "inspect", "--format",
            "{{json .Config.Env}}", source_image,
        ),
        input_bytes=b"",
        max_output_bytes=MAX_RECEIPT_BYTES,
    )
    try:
        payload = json.loads(raw)
    except Exception:
        raise SourceIdentityDiagnosticRefusal("database_witness_refused") from None
    if not isinstance(payload, list) or not all(isinstance(item, str) for item in payload):
        raise SourceIdentityDiagnosticRefusal("database_witness_refused")
    return tuple(payload)


def _prove_same_witness_image(
    source_image: str,
    compose_prefix: tuple[str, ...],
    *,
    child_runner: Callable[..., bytes],
) -> None:
    source_id = child_runner(
        ("docker", "image", "inspect", "--format", "{{.Id}}", source_image),
        input_bytes=b"",
        max_output_bytes=1024,
    ).strip()
    configured = child_runner(
        (*compose_prefix, "config", "--format", "json", DATABASE_WITNESS_SERVICE),
        input_bytes=b"",
        max_output_bytes=MAX_PRIVATE_FRAME_BYTES,
    )
    try:
        configured_model = json.loads(configured, object_pairs_hook=_unique_json_object)
        services = configured_model["services"]
        witness_service = services[DATABASE_WITNESS_SERVICE]
        witness_image = witness_service["image"]
    except (KeyError, TypeError, ValueError, UnicodeDecodeError):
        raise SourceIdentityDiagnosticRefusal("database_witness_refused") from None
    if not isinstance(witness_image, str) or not _immutable_image_reference(witness_image):
        raise SourceIdentityDiagnosticRefusal("database_witness_refused")
    witness_id = child_runner(
        ("docker", "image", "inspect", "--format", "{{.Id}}", witness_image),
        input_bytes=b"",
        max_output_bytes=1024,
    ).strip()
    if (
        not source_id
        or source_id != witness_id
        or not source_id.startswith(b"sha256:")
        or _SHA256.fullmatch(source_id[7:].decode("ascii", errors="ignore")) is None
    ):
        raise SourceIdentityDiagnosticRefusal("database_witness_refused")


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def run_production_diagnostic(
    *,
    source_image: str,
    source_root: Path,
    container_source_root: str,
    compose_prefix: tuple[str, ...],
    channel: str,
    revision: str,
    child_runner: Callable[..., bytes] = _run_bounded_child,
    container_absence: Callable[[str], None] = _assert_owned_container_absent,
    container_cleanup: Callable[[str, str], None] = _cleanup_owned_container,
) -> dict[str, Any]:
    """Coordinate source prepare, DB witness, and exact source re-fence."""
    if (
        not _valid_channel_revision(channel, revision)
        or not _immutable_image_reference(source_image)
    ):
        raise SourceIdentityDiagnosticRefusal("database_witness_refused")
    image_environment = _inspect_image_environment(
        source_image, child_runner=child_runner,
    )
    _prove_same_witness_image(
        source_image, compose_prefix, child_runner=child_runner,
    )
    names = {
        "prepare": f"pkm-source-id-prepare-{revision[:12]}",
        "witness": f"pkm-source-id-witness-{revision[:12]}",
        "finalize": f"pkm-source-id-finalize-{revision[:12]}",
    }
    owner_token = secrets.token_hex(16)
    source_environment = _closed_source_environment(
        dict(os.environ), container_source_root=container_source_root,
    )
    source_prepare_argv = source_observation_run_argv(
        mode="source-prepare",
        source_image=source_image,
        source_root=source_root,
        container_source_root=container_source_root,
        source_environment=source_environment,
        channel=channel,
        revision=revision,
        container_name=names["prepare"],
        owner_token=owner_token,
    )
    source_finalize_argv = source_observation_run_argv(
        mode="source-finalize",
        source_image=source_image,
        source_root=source_root,
        container_source_root=container_source_root,
        source_environment=source_environment,
        channel=channel,
        revision=revision,
        container_name=names["finalize"],
        owner_token=owner_token,
    )
    for argv in (source_prepare_argv, source_finalize_argv):
        validate_source_observation_create_argv(
            argv, image_environment=image_environment,
        )
    container_absence(names["prepare"])
    try:
        prepare_raw = child_runner(
            source_prepare_argv,
            input_bytes=b"",
            max_output_bytes=MAX_PRIVATE_FRAME_BYTES,
        )
    finally:
        container_cleanup(names["prepare"], owner_token)
    try:
        prepare = _validate_source_prepare(
            json.loads(prepare_raw), channel=channel, revision=revision,
        )
        request_raw = json.dumps(
            prepare["request"], sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
        if len(request_raw) > MAX_REQUEST_BYTES:
            raise ValueError
    except Exception:
        raise SourceIdentityDiagnosticRefusal("database_witness_refused") from None
    container_absence(names["witness"])
    try:
        database_raw = child_runner(
            database_witness_compose_argv(
                compose_prefix,
                container_name=names["witness"],
                owner_token=owner_token,
            ),
            input_bytes=request_raw,
            max_output_bytes=MAX_RECEIPT_BYTES,
        )
    finally:
        container_cleanup(names["witness"], owner_token)
    try:
        database_receipt = validate_receipt(json.loads(database_raw))
        finalize_input = json.dumps(
            {"prepare": prepare, "database_receipt": database_receipt},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(finalize_input) > MAX_PRIVATE_FRAME_BYTES:
            raise ValueError
    except Exception:
        raise SourceIdentityDiagnosticRefusal("database_witness_refused") from None
    container_absence(names["finalize"])
    try:
        final_raw = child_runner(
            source_finalize_argv,
            input_bytes=finalize_input,
            max_output_bytes=MAX_RECEIPT_BYTES,
        )
    finally:
        container_cleanup(names["finalize"], owner_token)
    try:
        return validate_source_receipt(json.loads(final_raw))
    except Exception:
        raise SourceIdentityDiagnosticRefusal("database_witness_refused") from None


def database_witness_compose_argv(
    compose_prefix: tuple[str, ...],
    *,
    container_name: str | None = None,
    owner_token: str | None = None,
) -> tuple[str, ...]:
    """Build the only supported ephemeral database-witness invocation."""
    if (
        len(compose_prefix) < 2
        or compose_prefix[:2] != ("docker", "compose")
        or (
            container_name is not None
            and re.fullmatch(r"pkm-source-id-witness-[0-9a-f]{12}", container_name)
            is None
        )
        or ((container_name is None) != (owner_token is None))
        or (
            owner_token is not None
            and re.fullmatch(r"[0-9a-f]{32}", owner_token) is None
        )
    ):
        raise SourceIdentityDiagnosticRefusal("database_witness_refused")
    return (
        *compose_prefix,
        "run",
        "--rm",
        "--no-deps",
        "-T",
        *(("--name", container_name) if container_name is not None else ()),
        *(("--label", f"{OWNER_LABEL}={owner_token}") if owner_token is not None else ()),
        DATABASE_WITNESS_SERVICE,
    )


def worker_main(argv: list[str]) -> int:
    if (
        len(argv) == 6
        and argv[0] == "coordinate"
        and _valid_channel_revision(argv[1], argv[2])
    ):
        (
            _mode, channel, revision, source_image, vault_root_raw,
            container_source_root,
        ) = argv
        try:
            receipt = run_production_diagnostic(
                source_image=source_image,
                source_root=Path(vault_root_raw),
                container_source_root=container_source_root,
                compose_prefix=(
                    "docker", "compose", "--profile",
                    "native-source-diagnostics",
                ),
                channel=channel,
                revision=revision,
            )
        except Exception:
            return 78
        print(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
        return 0
    if (
        len(argv) == 4
        and argv[0] in {"source-prepare", "source-finalize"}
        and _valid_channel_revision(argv[1], argv[2])
    ):
        mode, channel, revision, vault_root_raw = argv
        try:
            vault_root = Path(vault_root_raw)
            if mode == "source-prepare":
                result = _source_capture(
                    vault_root,
                    source_ref_root=vault_root_raw,
                    channel=channel,
                    revision=revision,
                )
            else:
                raw = sys.stdin.buffer.read(MAX_PRIVATE_FRAME_BYTES + 1)
                if len(raw) > MAX_PRIVATE_FRAME_BYTES:
                    raise SourceIdentityDiagnosticRefusal(
                        "database_witness_refused",
                    )
                payload = json.loads(raw)
                if not isinstance(payload, dict) or set(payload) != {
                    "prepare", "database_receipt",
                }:
                    raise SourceIdentityDiagnosticRefusal(
                        "database_witness_refused",
                    )
                result = finalize_source_observation(
                    payload["prepare"],
                    payload["database_receipt"],
                    vault_root=vault_root,
                    source_ref_root=vault_root_raw,
                    channel=channel,
                    revision=revision,
                )
        except Exception:
            return 78
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0
    if (
        len(argv) != 3
        or argv[0] != "database-witness"
        or not _valid_channel_revision(argv[1], argv[2])
    ):
        return 78
    channel, revision = argv[1:]
    closed_environment = closed_witness_environment(dict(os.environ))
    os.environ.clear()
    os.environ.update(closed_environment)
    try:
        raw = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
        if len(raw) > MAX_REQUEST_BYTES:
            raise SourceIdentityDiagnosticRefusal("database_witness_refused")
        payload = json.loads(raw)
    except Exception:
        payload = None
    receipt = run_database_witness(
        payload,
        channel=channel,
        revision=revision,
    )
    print(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
    return 0 if receipt["terminal_state"] == "observed" else 78


if __name__ == "__main__":
    raise SystemExit(worker_main(sys.argv[1:]))


__all__ = [
    "COUNT_FIELDS",
    "DATABASE_WITNESS_SERVICE",
    "MAX_PRIVATE_FRAME_BYTES",
    "MAX_RECEIPT_BYTES",
    "RECEIPT_CONTRACT",
    "REQUEST_CONTRACT",
    "SOURCE_COUNT_FIELDS",
    "SOURCE_PREPARE_CONTRACT",
    "SOURCE_RECEIPT_CONTRACT",
    "SourceIdentityDiagnosticRefusal",
    "closed_witness_environment",
    "database_witness_compose_argv",
    "finalize_source_observation",
    "run_production_diagnostic",
    "run_database_witness",
    "validate_receipt",
    "source_observation_run_argv",
    "validate_source_receipt",
    "validate_source_observation_create_argv",
    "worker_main",
]
