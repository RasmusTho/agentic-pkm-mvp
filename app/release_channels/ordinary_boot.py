"""Read-only ordinary-boot compatibility resolver and terminal journal.

The production entrypoint deliberately has no deployment hooks.  It consumes
an already-observed dependency snapshot, resolves it against one exact prod
ChannelManifest, and writes one terminal result for the caller-supplied
operation id.  Starting services or writers is a separate caller action and is
permitted only when the result says ``writers_permitted=true``.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.release_channels.channel_manifest import (
    ArtifactRenderError,
    render_channel_manifest,
)


JOURNAL_VERSION = "ordinary-boot-journal.v1"
_OPERATION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_IMAGE_DIGEST = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9._-]*(?:/[A-Za-z0-9._-]+)+@sha256:[0-9a-f]{64}\Z"
)
_CHANNEL_IDENTITY = re.compile(r"prod-[A-Za-z0-9][A-Za-z0-9._-]*\Z")
_MIGRATION_IDENTITY = re.compile(r"alembic:[A-Za-z0-9._-]+\Z")
_OBSERVATION_FIELDS = {"status", "identity"}
_JOURNAL_FIELDS = {
    "journal_version",
    "operation_id",
    "channel",
    "manifest_identity",
    "terminal_phase",
    "reason_code",
    "dependencies",
    "writers_permitted",
    "mutation_evidence",
}
_DEPENDENCY_FIELDS = {
    "name",
    "policy",
    "classification",
    "expected_identity",
    "identity_matches",
}
_DEPENDENCY_NAMES = {"artifact", "config", "database", "gateway", "llm", "schema", "vault"}
_BASE_DEPENDENCIES = {"artifact", "config", "database", "gateway", "schema", "vault"}


class OrdinaryBootJournalError(RuntimeError):
    """The exactly-one terminal journal could not be preserved."""


@dataclass(frozen=True)
class _Dependency:
    name: str
    policy: str
    expected_identity: str | None


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ArtifactRenderError(
            "invalid_shape",
            "ordinary-boot input must contain only JSON-compatible values",
        ) from exc


def _identity(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _mapping(value: object, *, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise ArtifactRenderError("invalid_shape", f"{path} must be a string-keyed mapping")
    return value


def _required_string(mapping: Mapping[str, Any], key: str, *, path: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        raise ArtifactRenderError("invalid_shape", f"{path}.{key} must be a non-empty string")
    return value


def _dependency_contract(
    manifest: Mapping[str, Any],
    rendered: Mapping[str, Any],
) -> tuple[_Dependency, ...]:
    artifact = _mapping(manifest.get("artifact"), path="manifest.artifact")
    identities = _mapping(manifest.get("identities"), path="manifest.identities")
    gateway = _mapping(manifest.get("gateway"), path="manifest.gateway")
    graph = _mapping(rendered.get("artifact_graph"), path="render.artifact_graph")
    dependencies = [
        _Dependency(
            "artifact",
            "required",
            _required_string(graph, "platform_image", path="render.artifact_graph"),
        ),
        _Dependency(
            "config",
            "required",
            _required_string(identities, "config", path="manifest.identities"),
        ),
        _Dependency(
            "database",
            "required",
            _required_string(identities, "database", path="manifest.identities"),
        ),
        _Dependency(
            "gateway",
            "required",
            _required_string(gateway, "identity", path="manifest.gateway"),
        ),
        _Dependency(
            "schema",
            "required",
            _required_string(identities, "migration", path="manifest.identities"),
        ),
        _Dependency(
            "vault",
            "required",
            _required_string(identities, "vault", path="manifest.identities"),
        ),
    ]
    llm_policy = manifest.get("llm_policy")
    if llm_policy == "declared-required":
        dependencies.append(_Dependency("llm", "required", None))
    elif llm_policy == "declared-optional":
        dependencies.append(_Dependency("llm", "degraded_ok", None))
    elif llm_policy != "disabled":
        raise ArtifactRenderError("llm_policy", "ordinary-boot LLM policy is unsupported")

    repository = _required_string(artifact, "repository", path="manifest.artifact")
    platform_digest = _required_string(
        artifact,
        "platform_digest",
        path="manifest.artifact",
    )
    if dependencies[0].expected_identity != f"{repository}@{platform_digest}":
        raise ArtifactRenderError(
            "artifact_identity_mismatch",
            "resolved platform image does not match the ChannelManifest",
        )
    return tuple(sorted(dependencies, key=lambda item: item.name))


def _classify_dependencies(
    dependencies: Sequence[_Dependency],
    observed: Mapping[str, Any],
) -> tuple[list[dict[str, object]], bool, str]:
    expected_names = {dependency.name for dependency in dependencies}
    unknown = sorted(set(observed) - expected_names)
    if unknown:
        raise ArtifactRenderError(
            "dependency_observation_unknown",
            "ordinary-boot observations contain undeclared dependencies: " + ", ".join(unknown),
        )

    results: list[dict[str, object]] = []
    required_ok = True
    required_failure = ""
    for dependency in dependencies:
        raw_observation = observed.get(dependency.name, {"status": "unavailable"})
        observation = _mapping(
            raw_observation,
            path=f"observed_dependencies.{dependency.name}",
        )
        if not set(observation).issubset(_OBSERVATION_FIELDS):
            raise ArtifactRenderError(
                "dependency_observation_shape",
                f"observation for {dependency.name!r} contains unsupported fields",
            )
        status = observation.get("status")
        identity = observation.get("identity")
        if status not in {"available", "unavailable"}:
            raise ArtifactRenderError(
                "dependency_observation_status",
                f"observation for {dependency.name!r} must be available or unavailable",
            )
        if identity is not None and (not isinstance(identity, str) or not identity):
            raise ArtifactRenderError(
                "dependency_observation_identity",
                f"observation identity for {dependency.name!r} must be a non-empty string",
            )
        if status == "unavailable" and identity is not None:
            raise ArtifactRenderError(
                "dependency_observation_identity",
                f"unavailable dependency {dependency.name!r} cannot claim an identity",
            )

        if status == "unavailable":
            classification = (
                "required_unavailable"
                if dependency.policy == "required"
                else "degraded_unavailable"
            )
        elif dependency.expected_identity is not None and identity != dependency.expected_identity:
            classification = (
                "required_incompatible"
                if dependency.policy == "required"
                else "degraded_incompatible"
            )
        else:
            classification = (
                "required_compatible"
                if dependency.policy == "required"
                else "degraded_compatible"
            )

        if dependency.policy == "required" and classification != "required_compatible":
            required_ok = False
            if not required_failure:
                required_failure = (
                    "required_dependency_unavailable"
                    if classification == "required_unavailable"
                    else "required_dependency_incompatible"
                )

        entry: dict[str, object] = {
            "name": dependency.name,
            "policy": dependency.policy,
            "classification": classification,
        }
        if dependency.expected_identity is not None:
            entry["expected_identity"] = dependency.expected_identity
        if dependency.expected_identity is not None:
            entry["identity_matches"] = identity == dependency.expected_identity
        results.append(entry)
    return results, required_ok, required_failure


def _terminal_result(
    *,
    operation_id: str,
    channel: str,
    manifest_identity: str,
    terminal_phase: str,
    reason_code: str,
    dependencies: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    return {
        "journal_version": JOURNAL_VERSION,
        "operation_id": operation_id,
        "channel": channel,
        "manifest_identity": manifest_identity,
        "terminal_phase": terminal_phase,
        "reason_code": reason_code,
        "dependencies": [dict(entry) for entry in dependencies],
        "writers_permitted": terminal_phase == "ORDINARY_BOOT_PASS",
        "mutation_evidence": False,
    }


def _evaluate(
    manifest: Mapping[str, Any],
    compose: Mapping[str, Any],
    observed_dependencies: Mapping[str, Any],
    *,
    operation_id: str,
) -> dict[str, object]:
    manifest_identity = _identity(manifest)
    channel = "unresolved"
    try:
        if manifest.get("channel") != "prod" or manifest.get("mode") != "promotion":
            raise ArtifactRenderError(
                "ordinary_boot_binding",
                "ordinary boot is restricted to an exact prod promotion-mode manifest",
            )
        rendered = render_channel_manifest(
            manifest,
            compose,
            channel="prod",
            mode="promotion",
            intent="ordinary-boot",
        )
        channel = "prod"
        manifest_identity = str(
            _mapping(rendered.get("artifact_graph"), path="render.artifact_graph")[
                "manifest_identity"
            ]
        )
        dependencies = _dependency_contract(manifest, rendered)
        classifications, required_ok, required_failure = _classify_dependencies(
            dependencies,
            observed_dependencies,
        )
    except ArtifactRenderError as exc:
        return _terminal_result(
            operation_id=operation_id,
            channel=channel,
            manifest_identity=manifest_identity,
            terminal_phase="PRE_MUTATION_FAILURE",
            reason_code=f"compatibility_resolution_failed:{exc.code}",
            dependencies=(),
        )

    if not required_ok:
        return _terminal_result(
            operation_id=operation_id,
            channel=channel,
            manifest_identity=manifest_identity,
            terminal_phase="PRE_MUTATION_FAILURE",
            reason_code=required_failure,
            dependencies=classifications,
        )
    return _terminal_result(
        operation_id=operation_id,
        channel=channel,
        manifest_identity=manifest_identity,
        terminal_phase="ORDINARY_BOOT_PASS",
        reason_code="compatible",
        dependencies=classifications,
    )


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, child in pairs:
        if key in value:
            raise OrdinaryBootJournalError("journal_duplicate_key")
        value[key] = child
    return value


def _validate_dependency_entry(
    value: object,
    *,
    path: Path,
    line_number: int,
) -> dict[str, object]:
    if not isinstance(value, dict) or not set(value).issubset(_DEPENDENCY_FIELDS):
        raise OrdinaryBootJournalError(
            f"journal_corrupt:{path}:line_{line_number}:dependency_shape"
        )
    required = {"name", "policy", "classification"}
    if not required.issubset(value):
        raise OrdinaryBootJournalError(
            f"journal_corrupt:{path}:line_{line_number}:dependency_shape"
        )
    name = value["name"]
    policy = value["policy"]
    classification = value["classification"]
    if (
        not isinstance(name, str)
        or not isinstance(policy, str)
        or not isinstance(classification, str)
        or name not in _DEPENDENCY_NAMES
        or policy not in {"required", "degraded_ok"}
    ):
        raise OrdinaryBootJournalError(
            f"journal_corrupt:{path}:line_{line_number}:dependency_value"
        )
    allowed_classifications = (
        {"required_compatible", "required_unavailable", "required_incompatible"}
        if policy == "required"
        else {"degraded_compatible", "degraded_unavailable", "degraded_incompatible"}
    )
    if classification not in allowed_classifications:
        raise OrdinaryBootJournalError(
            f"journal_corrupt:{path}:line_{line_number}:dependency_classification"
        )
    has_expected = "expected_identity" in value
    has_match = "identity_matches" in value
    if has_expected != has_match:
        raise OrdinaryBootJournalError(
            f"journal_corrupt:{path}:line_{line_number}:dependency_identity_shape"
        )
    if has_expected:
        if not isinstance(value["expected_identity"], str) or not value["expected_identity"]:
            raise OrdinaryBootJournalError(
                f"journal_corrupt:{path}:line_{line_number}:dependency_identity_value"
            )
        if type(value["identity_matches"]) is not bool:
            raise OrdinaryBootJournalError(
                f"journal_corrupt:{path}:line_{line_number}:dependency_identity_value"
            )
        compatible = classification in {"required_compatible", "degraded_compatible"}
        if value["identity_matches"] is not compatible:
            raise OrdinaryBootJournalError(
                f"journal_corrupt:{path}:line_{line_number}:dependency_identity_mismatch"
            )
        identity = value["expected_identity"]
        identity_pattern = {
            "artifact": _IMAGE_DIGEST,
            "config": _DIGEST,
            "database": _CHANNEL_IDENTITY,
            "gateway": _CHANNEL_IDENTITY,
            "schema": _MIGRATION_IDENTITY,
            "vault": _CHANNEL_IDENTITY,
        }.get(str(name))
        if identity_pattern is None or identity_pattern.fullmatch(str(identity)) is None:
            raise OrdinaryBootJournalError(
                f"journal_corrupt:{path}:line_{line_number}:dependency_identity_contract"
            )
    elif name != "llm":
        raise OrdinaryBootJournalError(
            f"journal_corrupt:{path}:line_{line_number}:dependency_identity_missing"
        )
    return value


def _validate_journal_row(row: object, *, path: Path, line_number: int) -> dict[str, object]:
    if not isinstance(row, dict) or set(row) != _JOURNAL_FIELDS:
        raise OrdinaryBootJournalError(
            f"journal_corrupt:{path}:line_{line_number}:invalid_shape"
        )
    operation_id = row["operation_id"]
    phase = row["terminal_phase"]
    reason = row["reason_code"]
    if row["journal_version"] != JOURNAL_VERSION:
        raise OrdinaryBootJournalError(
            f"journal_corrupt:{path}:line_{line_number}:invalid_version"
        )
    if not isinstance(operation_id, str) or _OPERATION_ID.fullmatch(operation_id) is None:
        raise OrdinaryBootJournalError(
            f"journal_corrupt:{path}:line_{line_number}:invalid_operation"
        )
    if not isinstance(row["channel"], str) or row["channel"] not in {"prod", "unresolved"}:
        raise OrdinaryBootJournalError(
            f"journal_corrupt:{path}:line_{line_number}:invalid_channel"
        )
    if not isinstance(row["manifest_identity"], str) or _DIGEST.fullmatch(
        row["manifest_identity"]
    ) is None:
        raise OrdinaryBootJournalError(
            f"journal_corrupt:{path}:line_{line_number}:invalid_manifest_identity"
        )
    if not isinstance(phase, str) or phase not in {"PRE_MUTATION_FAILURE", "ORDINARY_BOOT_PASS"}:
        raise OrdinaryBootJournalError(
            f"journal_corrupt:{path}:line_{line_number}:invalid_terminal_phase"
        )
    if not isinstance(reason, str) or not reason:
        raise OrdinaryBootJournalError(
            f"journal_corrupt:{path}:line_{line_number}:invalid_reason"
        )
    if type(row["writers_permitted"]) is not bool or row["writers_permitted"] is not (
        phase == "ORDINARY_BOOT_PASS"
    ):
        raise OrdinaryBootJournalError(
            f"journal_corrupt:{path}:line_{line_number}:writer_permission_mismatch"
        )
    if row["mutation_evidence"] is not False:
        raise OrdinaryBootJournalError(
            f"journal_corrupt:{path}:line_{line_number}:mutation_evidence_mismatch"
        )
    raw_dependencies = row["dependencies"]
    if not isinstance(raw_dependencies, list):
        raise OrdinaryBootJournalError(
            f"journal_corrupt:{path}:line_{line_number}:dependencies_shape"
        )
    dependencies = [
        _validate_dependency_entry(value, path=path, line_number=line_number)
        for value in raw_dependencies
    ]
    names = [str(entry["name"]) for entry in dependencies]
    if names != sorted(names) or len(names) != len(set(names)):
        raise OrdinaryBootJournalError(
            f"journal_corrupt:{path}:line_{line_number}:dependency_order_or_duplicate"
        )
    dependency_names = set(names)
    if dependencies:
        if row["channel"] != "prod" or (
            dependency_names != _BASE_DEPENDENCIES
            and dependency_names != _BASE_DEPENDENCIES | {"llm"}
        ):
            raise OrdinaryBootJournalError(
                f"journal_corrupt:{path}:line_{line_number}:dependency_set_invariant"
            )
        by_name = {str(entry["name"]): entry for entry in dependencies}
        if any(by_name[name]["policy"] != "required" for name in _BASE_DEPENDENCIES):
            raise OrdinaryBootJournalError(
                f"journal_corrupt:{path}:line_{line_number}:dependency_policy_invariant"
            )
        llm = by_name.get("llm")
        if llm is not None and llm["classification"] in {
            "required_incompatible",
            "degraded_incompatible",
        }:
            raise OrdinaryBootJournalError(
                f"journal_corrupt:{path}:line_{line_number}:llm_classification_invariant"
            )
    required_classes = {
        str(entry["classification"])
        for entry in dependencies
        if entry["policy"] == "required"
    }
    if phase == "ORDINARY_BOOT_PASS":
        if reason != "compatible" or not dependencies or required_classes != {"required_compatible"}:
            raise OrdinaryBootJournalError(
                f"journal_corrupt:{path}:line_{line_number}:pass_invariant"
            )
    elif reason.startswith("compatibility_resolution_failed:"):
        if dependencies or row["channel"] not in {"prod", "unresolved"}:
            raise OrdinaryBootJournalError(
                f"journal_corrupt:{path}:line_{line_number}:resolution_failure_invariant"
            )
    elif reason == "required_dependency_unavailable":
        if "required_unavailable" not in required_classes:
            raise OrdinaryBootJournalError(
                f"journal_corrupt:{path}:line_{line_number}:required_failure_invariant"
            )
    elif reason == "required_dependency_incompatible":
        if "required_incompatible" not in required_classes:
            raise OrdinaryBootJournalError(
                f"journal_corrupt:{path}:line_{line_number}:required_failure_invariant"
            )
    else:
        raise OrdinaryBootJournalError(
            f"journal_corrupt:{path}:line_{line_number}:failure_reason_invariant"
        )
    return row


def _decode_journal(data: bytes, *, path: Path) -> list[dict[str, object]]:
    if not data:
        return []
    if not data.endswith(b"\n"):
        raise OrdinaryBootJournalError(f"journal_corrupt:{path}:unterminated_record")
    rows: list[dict[str, object]] = []
    seen: set[str] = set()
    for line_number, raw_line in enumerate(data.splitlines(), start=1):
        try:
            row = json.loads(raw_line, object_pairs_hook=_reject_duplicate_keys)
        except (json.JSONDecodeError, OrdinaryBootJournalError) as exc:
            raise OrdinaryBootJournalError(
                f"journal_corrupt:{path}:line_{line_number}"
            ) from exc
        if _canonical_bytes(row) != raw_line:
            raise OrdinaryBootJournalError(
                f"journal_corrupt:{path}:line_{line_number}:noncanonical_record"
            )
        validated = _validate_journal_row(row, path=path, line_number=line_number)
        operation_id = str(validated["operation_id"])
        if operation_id in seen:
            raise OrdinaryBootJournalError(
                f"journal_corrupt:{path}:line_{line_number}:duplicate_operation"
            )
        seen.add(operation_id)
        rows.append(validated)
    return rows


def _fsync_parent_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path.parent, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _append_terminal_once(path: Path, result: Mapping[str, object]) -> dict[str, object]:
    if not path.parent.is_dir():
        raise OrdinaryBootJournalError(f"journal_parent_missing:{path.parent}")
    validated_result = _validate_journal_row(dict(result), path=path, line_number=0)
    flags = os.O_RDWR | os.O_APPEND | os.O_CREAT
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as exc:
        raise OrdinaryBootJournalError(f"journal_io_failure:{path}") from exc
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            os.lseek(descriptor, 0, os.SEEK_SET)
            chunks: list[bytes] = []
            while True:
                chunk = os.read(descriptor, 65536)
                if not chunk:
                    break
                chunks.append(chunk)
            rows = _decode_journal(b"".join(chunks), path=path)
            operation_id = validated_result["operation_id"]
            for row in rows:
                if row["operation_id"] != operation_id:
                    continue
                if row != validated_result:
                    raise OrdinaryBootJournalError(
                        f"operation_conflict:{operation_id}:terminal_result_changed"
                    )
                os.fsync(descriptor)
                _fsync_parent_directory(path)
                return row

            encoded = _canonical_bytes(validated_result) + b"\n"
            offset = 0
            while offset < len(encoded):
                written = os.write(descriptor, encoded[offset:])
                if written <= 0:
                    raise OSError("journal write made no progress")
                offset += written
            os.fsync(descriptor)
            _fsync_parent_directory(path)
            return dict(validated_result)
        except OSError as exc:
            raise OrdinaryBootJournalError(f"journal_io_failure:{path}") from exc
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def run_ordinary_boot(
    manifest: Mapping[str, Any],
    compose: Mapping[str, Any],
    observed_dependencies: Mapping[str, Any],
    *,
    operation_id: str,
    journal_path: Path,
) -> dict[str, object]:
    """Resolve one prod ordinary boot and durably return exactly one result.

    This function never starts a runtime writer.  ``writers_permitted`` is an
    admission result for a separate caller and is false for every required
    dependency failure.
    """
    if _OPERATION_ID.fullmatch(operation_id) is None:
        raise OrdinaryBootJournalError("invalid_operation_id")
    if not isinstance(journal_path, Path):
        raise OrdinaryBootJournalError("journal_path_must_be_path")
    result = _evaluate(
        _mapping(manifest, path="manifest"),
        _mapping(compose, path="compose"),
        _mapping(observed_dependencies, path="observed_dependencies"),
        operation_id=operation_id,
    )
    return _append_terminal_once(journal_path, result)


def _read_mapping(path: Path, *, label: str) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OrdinaryBootJournalError(f"{label}_unreadable:{path}") from exc
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise OrdinaryBootJournalError(f"{label}_invalid_shape:{path}")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.release_channels.ordinary_boot",
        description="Resolve prod ordinary-boot compatibility without deployment mutation.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    doctor = subparsers.add_parser("doctor", help="write one read-only terminal result")
    doctor.add_argument("--manifest", type=Path, required=True)
    doctor.add_argument("--compose", type=Path, required=True)
    doctor.add_argument("--dependencies", type=Path, required=True)
    doctor.add_argument("--operation-id", required=True)
    doctor.add_argument("--journal", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = run_ordinary_boot(
            _read_mapping(args.manifest, label="manifest"),
            _read_mapping(args.compose, label="compose"),
            _read_mapping(args.dependencies, label="dependencies"),
            operation_id=args.operation_id,
            journal_path=args.journal,
        )
    except OrdinaryBootJournalError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0 if result["terminal_phase"] == "ORDINARY_BOOT_PASS" else 3


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["OrdinaryBootJournalError", "run_ordinary_boot"]
