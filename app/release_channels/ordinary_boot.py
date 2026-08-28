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
_OBSERVATION_FIELDS = {"status", "identity"}


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
    channel = manifest.get("channel") if isinstance(manifest.get("channel"), str) else "unresolved"
    try:
        if channel != "prod" or manifest.get("mode") != "promotion":
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


def _decode_journal(data: bytes, *, path: Path) -> list[dict[str, object]]:
    if not data:
        return []
    if not data.endswith(b"\n"):
        raise OrdinaryBootJournalError(f"journal_corrupt:{path}:unterminated_record")
    rows: list[dict[str, object]] = []
    seen: set[str] = set()
    for line_number, raw_line in enumerate(data.splitlines(), start=1):
        try:
            row = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise OrdinaryBootJournalError(
                f"journal_corrupt:{path}:line_{line_number}"
            ) from exc
        if not isinstance(row, dict) or row.get("journal_version") != JOURNAL_VERSION:
            raise OrdinaryBootJournalError(
                f"journal_corrupt:{path}:line_{line_number}:invalid_shape"
            )
        operation_id = row.get("operation_id")
        if not isinstance(operation_id, str) or operation_id in seen:
            raise OrdinaryBootJournalError(
                f"journal_corrupt:{path}:line_{line_number}:duplicate_or_invalid_operation"
            )
        seen.add(operation_id)
        rows.append(row)
    return rows


def _append_terminal_once(path: Path, result: Mapping[str, object]) -> dict[str, object]:
    if not path.parent.is_dir():
        raise OrdinaryBootJournalError(f"journal_parent_missing:{path.parent}")
    flags = os.O_RDWR | os.O_APPEND | os.O_CREAT
    descriptor = os.open(path, flags, 0o600)
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
        operation_id = result["operation_id"]
        for row in rows:
            if row["operation_id"] != operation_id:
                continue
            if row != dict(result):
                raise OrdinaryBootJournalError(
                    f"operation_conflict:{operation_id}:terminal_result_changed"
                )
            return row

        encoded = _canonical_bytes(result) + b"\n"
        offset = 0
        while offset < len(encoded):
            offset += os.write(descriptor, encoded[offset:])
        os.fsync(descriptor)
        return dict(result)
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
