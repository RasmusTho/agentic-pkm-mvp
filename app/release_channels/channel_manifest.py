"""Deterministic ChannelManifest artifact and Compose rendering.

The renderer is deliberately side-effect free.  It consumes an already selected
ChannelManifest plus a Compose model, returns a content-addressed artifact graph,
and never builds, pulls, publishes, pins, starts, or mutates a runtime channel.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml


SCHEMA_VERSION = "startup-artifact-render.v1"
CANDIDATE_VERSION = "startup-promotion-candidate.v1"
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_SOURCE_SHA = re.compile(r"[0-9a-f]{40}\Z")
_SOURCE_IDENTITY = re.compile(r"git:[0-9a-f]{40}\Z")
_MIGRATION_IDENTITY = re.compile(r"alembic:[A-Za-z0-9._-]+\Z")
_CHANNEL_IDENTITY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
_COMPOSE_PROJECT = re.compile(r"pkm-[a-z0-9-]+\Z")
_REPOSITORY = re.compile(r"ghcr\.io/[A-Za-z0-9._/-]+\Z")
_SECRET_REFERENCE = re.compile(r"(?:keychain|vault|secret)://[A-Za-z0-9._/-]+\Z")
_SENSITIVE_FIELD = re.compile(
    r"(?:password|token|credential|private[_-]?key|api[_-]?key|"
    r"access[_-]?key|client[_-]?secret)",
    re.IGNORECASE,
)
_CREDENTIAL_URI = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://[^/@\s:]+:[^/@\s]+@")
_API_KEY_VALUE = re.compile(r"\bsk-[A-Za-z0-9][A-Za-z0-9_-]*")
_DIGEST_IMAGE = re.compile(
    r"(?P<repository>[A-Za-z0-9][A-Za-z0-9._-]*(?::[0-9]+)?"
    r"(?:/[A-Za-z0-9._-]+)+)@(?P<digest>sha256:[0-9a-f]{64})\Z"
)
_MANIFEST_FIELDS = {
    "schema_version",
    "channel",
    "mode",
    "intent",
    "compose_project",
    "artifact",
    "identities",
    "llm_policy",
    "gateway",
    "secret_references",
}
_ARTIFACT_FIELDS = {
    "repository",
    "image_index_digest",
    "platform_digest",
    "source_sha",
}
_IDENTITY_FIELDS = {"database", "vault", "config", "migration"}
_GATEWAY_FIELDS = {"port", "identity"}
_CHANNELS = {"dev", "local-test", "promotion-test", "prod"}
_LLM_POLICIES = {"declared-required", "declared-optional", "disabled"}
_COMPOSE_IDENTITY_EXTENSION = "x-startup-identities"
_PROMOTION_COMPOSE_FIELDS = {"services", "volumes", _COMPOSE_IDENTITY_EXTENSION}
_PROMOTION_SERVICE_SHAPES = {
    "api": {"image", "read_only", "volumes"},
    "database": {"image", "volumes"},
}
_PROTECTED_VOLUME_TARGETS = {
    "/app/vault": "vault",
    "/var/lib/postgresql/data": "database",
}


class ArtifactRenderError(ValueError):
    """Typed, fail-closed refusal from render or candidate admission."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code

    def as_dict(self) -> dict[str, object]:
        return {"ok": False, "error": self.code, "message": str(self)}


def _mapping(value: object, *, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ArtifactRenderError("invalid_shape", f"{path} must be a mapping")
    if not all(isinstance(key, str) for key in value):
        raise ArtifactRenderError("invalid_shape", f"{path} keys must be strings")
    return value


def _required_string(mapping: Mapping[str, Any], key: str, *, path: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        raise ArtifactRenderError("invalid_shape", f"{path}.{key} must be a non-empty string")
    return value


def _canonical_bytes(value: object, *, error_code: str) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ArtifactRenderError(error_code, "input must contain only JSON-compatible values") from exc


def _identity(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical_bytes(value, error_code="invalid_shape")).hexdigest()


def _validate_secret_free(value: object, *, path: str) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise ArtifactRenderError("invalid_shape", f"{path} keys must be strings")
            child_path = f"{path}.{key}"
            if key == "secret_references":
                if (
                    not isinstance(child, Sequence)
                    or isinstance(child, (str, bytes, bytearray))
                    or not child
                    or any(
                        not isinstance(reference, str)
                        or _SECRET_REFERENCE.fullmatch(reference) is None
                        for reference in child
                    )
                ):
                    raise ArtifactRenderError(
                        "secret_reference_invalid",
                        f"{child_path} must contain non-secret secret references only",
                    )
                continue
            if _SENSITIVE_FIELD.search(key):
                raise ArtifactRenderError(
                    "secret_value_forbidden",
                    f"secret-bearing field is forbidden in artifact render input: {child_path}",
                )
            _validate_secret_free(child, path=child_path)
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, child in enumerate(value):
            _validate_secret_free(child, path=f"{path}[{index}]")
        return
    if isinstance(value, str) and (
        _CREDENTIAL_URI.search(value) is not None or _API_KEY_VALUE.search(value) is not None
    ):
        raise ArtifactRenderError(
            "secret_value_forbidden",
            f"inline secret value is forbidden in artifact render input: {path}",
        )


def _validate_manifest_shape(manifest: Mapping[str, Any]) -> None:
    if set(manifest) != _MANIFEST_FIELDS:
        raise ArtifactRenderError("manifest_shape", "ChannelManifest fields do not match v1")
    artifact = _mapping(manifest.get("artifact"), path="manifest.artifact")
    identities = _mapping(manifest.get("identities"), path="manifest.identities")
    expected_artifact_fields = set(_ARTIFACT_FIELDS)
    if manifest.get("mode") == "local-source":
        expected_artifact_fields.update({"dirty_state", "promotion_eligible"})
    if set(artifact) != expected_artifact_fields:
        raise ArtifactRenderError("manifest_shape", "ChannelManifest artifact fields do not match mode")
    if set(identities) != _IDENTITY_FIELDS:
        raise ArtifactRenderError("manifest_shape", "ChannelManifest identity fields do not match v1")
    if manifest.get("schema_version") != "channel-manifest.v1":
        raise ArtifactRenderError("manifest_version", "unsupported ChannelManifest version")
    channel = manifest.get("channel")
    mode = manifest.get("mode")
    intent = manifest.get("intent")
    if channel not in _CHANNELS:
        raise ArtifactRenderError("manifest_channel", "ChannelManifest channel is unsupported")
    if mode not in {"local-source", "promotion"}:
        raise ArtifactRenderError("manifest_mode", "ChannelManifest mode is unsupported")
    if intent not in {"ordinary-boot", "promotion"}:
        raise ArtifactRenderError("manifest_intent", "ChannelManifest intent is unsupported")
    if mode == "local-source" and (
        channel not in {"dev", "local-test"} or intent != "ordinary-boot"
    ):
        raise ArtifactRenderError(
            "manifest_binding_mismatch",
            "local-source manifest must bind dev/local-test ordinary boot",
        )
    if mode == "promotion" and channel not in {"promotion-test", "prod"}:
        raise ArtifactRenderError(
            "manifest_binding_mismatch",
            "promotion manifest must bind promotion-test or prod",
        )
    compose_project = manifest.get("compose_project")
    if (
        not isinstance(compose_project, str)
        or _COMPOSE_PROJECT.fullmatch(compose_project) is None
        or compose_project != f"pkm-{channel}"
    ):
        raise ArtifactRenderError(
            "compose_project_mismatch",
            "ChannelManifest compose project must be explicitly bound to its channel",
        )
    repository = artifact.get("repository")
    if not isinstance(repository, str) or _REPOSITORY.fullmatch(repository) is None:
        raise ArtifactRenderError(
            "repository_identity",
            "ChannelManifest repository must be an explicit ghcr.io repository",
        )
    for digest_field in ("image_index_digest", "platform_digest"):
        digest_value = artifact.get(digest_field)
        if not isinstance(digest_value, str) or _DIGEST.fullmatch(digest_value) is None:
            raise ArtifactRenderError(
                "digest_required",
                f"ChannelManifest {digest_field} must be an exact sha256 digest",
            )
    if manifest.get("llm_policy") not in _LLM_POLICIES:
        raise ArtifactRenderError("llm_policy", "ChannelManifest LLM policy is unsupported")
    gateway = _mapping(manifest.get("gateway"), path="manifest.gateway")
    if set(gateway) != _GATEWAY_FIELDS:
        raise ArtifactRenderError("gateway_shape", "ChannelManifest gateway fields do not match v1")
    gateway_port = gateway.get("port")
    gateway_identity = gateway.get("identity")
    if type(gateway_port) is not int or not 1 <= gateway_port <= 65535:
        raise ArtifactRenderError("gateway_port", "ChannelManifest gateway port is invalid")
    if (
        not isinstance(gateway_identity, str)
        or _CHANNEL_IDENTITY.fullmatch(gateway_identity) is None
        or not gateway_identity.startswith(f"{channel}-")
    ):
        raise ArtifactRenderError(
            "gateway_identity",
            "ChannelManifest gateway identity must be explicitly scoped to its channel",
        )
    _validate_secret_free(manifest, path="manifest")
    secret_references = manifest.get("secret_references")
    if not isinstance(secret_references, Sequence) or isinstance(
        secret_references, (str, bytes, bytearray)
    ):
        raise ArtifactRenderError(
            "secret_reference_invalid",
            "ChannelManifest secret references must be a list",
        )
    for reference in secret_references:
        if not isinstance(reference, str):
            raise ArtifactRenderError(
                "secret_reference_invalid",
                "ChannelManifest secret references must be strings",
            )
        reference_path = reference.split("://", 1)[1]
        scoped_channels = set(reference_path.split("/")) & _CHANNELS
        if scoped_channels != {channel}:
            raise ArtifactRenderError(
                "secret_reference_channel",
                "every secret reference must be scoped to the selected channel",
            )


def _channel_resource_prefix(channel: str) -> str:
    return f"{channel}-"


def _validate_channel_resources(
    identities: Mapping[str, Any],
    compose: Mapping[str, Any],
    *,
    channel: str,
    mode: str,
) -> None:
    expected = {
        field: _required_string(identities, field, path="manifest.identities")
        for field in sorted(_IDENTITY_FIELDS)
    }
    prefix = _channel_resource_prefix(channel)
    for field in ("database", "vault"):
        value = expected[field]
        if _CHANNEL_IDENTITY.fullmatch(value) is None or not value.startswith(prefix):
            raise ArtifactRenderError(
                "channel_resource_identity",
                f"manifest {field} identity must be explicitly scoped to channel {channel!r}",
            )
    if mode != "promotion":
        return
    declared = _mapping(
        compose.get(_COMPOSE_IDENTITY_EXTENSION),
        path=f"compose.{_COMPOSE_IDENTITY_EXTENSION}",
    )
    if set(declared) != _IDENTITY_FIELDS or dict(declared) != expected:
        raise ArtifactRenderError(
            "resource_identity_mismatch",
            "Compose resource identities must exactly match the ChannelManifest",
        )

    if set(compose) != _PROMOTION_COMPOSE_FIELDS:
        raise ArtifactRenderError(
            "compose_field_forbidden",
            "promotion Compose may contain only services, volumes, and x-startup-identities",
        )
    services = _mapping(compose.get("services"), path="compose.services")
    if set(services) != set(_PROMOTION_SERVICE_SHAPES):
        raise ArtifactRenderError(
            "compose_service_set_forbidden",
            "promotion Compose services must be exactly api and database",
        )
    declared_volumes = _mapping(compose.get("volumes"), path="compose.volumes")
    protected_seen: set[str] = set()
    for service_name, raw_service in services.items():
        service = _mapping(raw_service, path=f"compose.services.{service_name}")
        if service.get("build") is not None:
            raise ArtifactRenderError(
                "build_forbidden",
                f"promotion service {service_name!r} may not declare build",
            )
        if set(service) != _PROMOTION_SERVICE_SHAPES[service_name]:
            raise ArtifactRenderError(
                "compose_service_field_forbidden",
                f"promotion service {service_name!r} does not match its exact artifact shape",
            )
        if service_name == "api" and service.get("read_only") is not True:
            raise ArtifactRenderError(
                "compose_service_field_forbidden",
                "promotion api service must be read-only",
            )
        raw_volumes = service.get("volumes", [])
        if not isinstance(raw_volumes, Sequence) or isinstance(
            raw_volumes, (str, bytes, bytearray)
        ):
            raise ArtifactRenderError(
                "invalid_mount",
                f"service {service_name!r} volumes must be a list",
            )
        for entry in raw_volumes:
            if isinstance(entry, str):
                source, target, mount_read_only = _short_mount(
                    entry, service=service_name
                )
                mount_type = "bind" if source.startswith((".", "/")) else "volume"
            elif isinstance(entry, Mapping):
                if set(entry) != {"type", "source", "target"}:
                    raise ArtifactRenderError(
                        "invalid_mount",
                        f"service {service_name!r} mount contains an unsupported field",
                    )
                source, target, mount_read_only, mount_type = _long_mount(
                    entry, service=service_name
                )
            else:
                raise ArtifactRenderError(
                    "invalid_mount",
                    f"service {service_name!r} contains an unsupported mount",
                )
            normalized_source = source.rstrip("/") or "/"
            normalized_target = target.rstrip("/") or "/"
            if mount_type != "volume":
                if normalized_target == "/app":
                    code = "source_bind_forbidden"
                elif normalized_source in {"/Users", "/Volumes"} and not mount_read_only:
                    code = "broad_writable_mount_forbidden"
                else:
                    code = "promotion_bind_forbidden"
                raise ArtifactRenderError(
                    code,
                    f"promotion service {service_name!r} may not use host bind "
                    f"{normalized_source}:{normalized_target}",
                )
            protected_field = _PROTECTED_VOLUME_TARGETS.get(normalized_target)
            if protected_field is None:
                raise ArtifactRenderError(
                    "promotion_mount_forbidden",
                    f"promotion service {service_name!r} contains an unsupported mount target",
                )
            if source != expected[protected_field]:
                raise ArtifactRenderError(
                    "resource_identity_mismatch",
                    f"Compose {protected_field} mount must use the manifest identity",
                )
            expected_field_for_service = "vault" if service_name == "api" else "database"
            if protected_field != expected_field_for_service:
                raise ArtifactRenderError(
                    "resource_identity_mismatch",
                    f"promotion service {service_name!r} has the wrong protected resource role",
                )
            protected_seen.add(protected_field)

        expected_mount_count = 1
        if len(raw_volumes) != expected_mount_count:
            raise ArtifactRenderError(
                "promotion_mount_forbidden",
                f"promotion service {service_name!r} must have exactly one protected mount",
            )

    if protected_seen != {"database", "vault"}:
        raise ArtifactRenderError(
            "resource_identity_missing",
            "promotion Compose must materialize the manifest database and vault identities",
        )
    expected_volume_names = {expected["database"], expected["vault"]}
    if set(declared_volumes) != expected_volume_names:
        raise ArtifactRenderError(
            "promotion_volume_forbidden",
            "promotion Compose volumes must be exactly the manifest database and vault identities",
        )
    for field in ("database", "vault"):
        volume_name = expected[field]
        declaration = declared_volumes.get(volume_name)
        if not isinstance(declaration, Mapping) or declaration:
            raise ArtifactRenderError(
                "resource_identity_mismatch",
                f"Compose volume {volume_name!r} must be an explicit empty named-volume declaration",
            )
def _contains_fallback(value: object) -> bool:
    if isinstance(value, str):
        return "${" in value
    if isinstance(value, Mapping):
        return any(_contains_fallback(key) or _contains_fallback(child) for key, child in value.items())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return any(_contains_fallback(child) for child in value)
    return False


def _short_mount(entry: str, *, service: str) -> tuple[str, str, bool]:
    parts = entry.split(":")
    if len(parts) not in {2, 3} or not parts[0] or not parts[1]:
        raise ArtifactRenderError(
            "invalid_mount",
            f"service {service!r} has an invalid short-syntax volume",
        )
    source, target = parts[0], parts[1]
    options = parts[2].split(",") if len(parts) > 2 else []
    if not set(options).issubset({"ro", "rw"}):
        raise ArtifactRenderError(
            "invalid_mount",
            f"service {service!r} has unsupported short-syntax mount options",
        )
    return source, target, "ro" in options


def _long_mount(entry: Mapping[str, Any], *, service: str) -> tuple[str, str, bool, str]:
    source = _required_string(entry, "source", path=f"services.{service}.volumes[]")
    target = _required_string(entry, "target", path=f"services.{service}.volumes[]")
    mount_type = entry.get("type", "volume")
    if not isinstance(mount_type, str):
        raise ArtifactRenderError("invalid_mount", f"service {service!r} has an invalid mount type")
    read_only = entry.get("read_only", False)
    if not isinstance(read_only, bool):
        raise ArtifactRenderError(
            "invalid_mount",
            f"service {service!r} mount read_only must be boolean",
        )
    return source, target, read_only, mount_type


def _validate_promotion_mounts(service_name: str, service: Mapping[str, Any]) -> None:
    raw_volumes = service.get("volumes", [])
    if raw_volumes is None:
        return
    if not isinstance(raw_volumes, Sequence) or isinstance(raw_volumes, (str, bytes, bytearray)):
        raise ArtifactRenderError(
            "invalid_mount",
            f"service {service_name!r} volumes must be a list",
        )

    for entry in raw_volumes:
        if isinstance(entry, str):
            source, target, read_only = _short_mount(entry, service=service_name)
            mount_type = "bind" if source.startswith(('.', '/')) else "volume"
        elif isinstance(entry, Mapping):
            source, target, read_only, mount_type = _long_mount(entry, service=service_name)
        else:
            raise ArtifactRenderError(
                "invalid_mount",
                f"service {service_name!r} contains an unsupported mount",
            )

        normalized_target = target.rstrip("/") or "/"
        normalized_source = source.rstrip("/") or "/"
        if mount_type == "bind" and normalized_target == "/app":
            raise ArtifactRenderError(
                "source_bind_forbidden",
                f"promotion service {service_name!r} may not bind source over /app",
            )
        if (
            mount_type == "bind"
            and normalized_source in {"/Users", "/Volumes"}
            and not read_only
        ):
            raise ArtifactRenderError(
                "broad_writable_mount_forbidden",
                f"promotion service {service_name!r} may not write through broad host mount "
                f"{normalized_source}",
            )


def _validate_promotion_compose(
    compose: Mapping[str, Any],
    *,
    expected_platform_image: str,
) -> None:
    if _contains_fallback(compose):
        raise ArtifactRenderError(
            "fallback_forbidden",
            "promotion Compose must be fully resolved without interpolation fallbacks",
        )
    services = _mapping(compose.get("services"), path="compose.services")
    if not services:
        raise ArtifactRenderError("invalid_shape", "compose.services must not be empty")

    for service_name, raw_service in services.items():
        service = _mapping(raw_service, path=f"compose.services.{service_name}")
        if service.get("build") is not None:
            raise ArtifactRenderError(
                "build_forbidden",
                f"promotion service {service_name!r} may not declare build",
            )
        image = service.get("image")
        if not isinstance(image, str) or _DIGEST_IMAGE.fullmatch(image) is None:
            raise ArtifactRenderError(
                "digest_required",
                f"promotion service {service_name!r} must use repository@sha256 digest identity",
            )
        if service_name == "api" and image != expected_platform_image:
            raise ArtifactRenderError(
                "platform_digest_missing",
                "promotion api service does not run the manifest's exact platform digest",
            )
        _validate_promotion_mounts(service_name, service)


def render_channel_manifest(
    manifest: Mapping[str, Any],
    compose: Mapping[str, Any],
    *,
    channel: str,
    mode: str,
    intent: str,
) -> dict[str, Any]:
    """Render one immutable artifact graph without changing external state."""
    _validate_manifest_shape(manifest)
    for key, expected in (("channel", channel), ("mode", mode), ("intent", intent)):
        if manifest.get(key) != expected:
            raise ArtifactRenderError(
                "manifest_binding_mismatch",
                f"manifest {key} does not match the explicit render request",
            )

    artifact = _mapping(manifest.get("artifact"), path="manifest.artifact")
    identities = _mapping(manifest.get("identities"), path="manifest.identities")
    repository = _required_string(artifact, "repository", path="manifest.artifact")
    source_sha = _required_string(artifact, "source_sha", path="manifest.artifact")
    migration_identity = _required_string(identities, "migration", path="manifest.identities")
    config_identity = _required_string(identities, "config", path="manifest.identities")
    if _SOURCE_SHA.fullmatch(source_sha) is None:
        raise ArtifactRenderError("source_identity", "manifest source_sha must be a full commit SHA")
    if _DIGEST.fullmatch(config_identity) is None:
        raise ArtifactRenderError(
            "config_identity",
            "manifest config identity must be an exact sha256 digest",
        )
    if _MIGRATION_IDENTITY.fullmatch(migration_identity) is None:
        raise ArtifactRenderError(
            "migration_identity",
            "manifest migration identity must use the alembic:<revision> form",
        )

    compose_copy = copy.deepcopy(dict(compose))
    _validate_secret_free(compose_copy, path="compose")
    _validate_channel_resources(identities, compose_copy, channel=channel, mode=mode)
    compose_identity = _identity(compose_copy)
    graph: dict[str, Any] = {
        "manifest_identity": _identity(manifest),
        "source_identity": f"git:{source_sha}",
        "compose_identity": compose_identity,
        "migration_identity": migration_identity,
        "config_identity": config_identity,
    }

    if mode == "promotion":
        if channel not in {"promotion-test", "prod"}:
            raise ArtifactRenderError(
                "promotion_channel",
                "promotion mode is restricted to promotion-test and prod",
            )
        image_index_digest = _required_string(
            artifact,
            "image_index_digest",
            path="manifest.artifact",
        )
        platform_digest = _required_string(
            artifact,
            "platform_digest",
            path="manifest.artifact",
        )
        if _DIGEST.fullmatch(image_index_digest) is None or _DIGEST.fullmatch(platform_digest) is None:
            raise ArtifactRenderError(
                "digest_required",
                "promotion artifacts require exact image-index and platform digests",
            )
        platform_image = f"{repository}@{platform_digest}"
        _validate_promotion_compose(compose_copy, expected_platform_image=platform_image)
        graph.update(
            {
                "image_index": f"{repository}@{image_index_digest}",
                "platform_image": platform_image,
            }
        )
        promotion_eligible = intent == "promotion"
    elif mode == "local-source":
        if channel not in {"dev", "local-test"} or intent != "ordinary-boot":
            raise ArtifactRenderError(
                "local_source_binding",
                "local-source is restricted to dev/local-test ordinary boot",
            )
        dirty_state = artifact.get("dirty_state")
        if dirty_state not in {"clean", "dirty"}:
            raise ArtifactRenderError(
                "source_identity",
                "local-source artifact requires dirty_state=clean|dirty",
            )
        if artifact.get("promotion_eligible") is not False:
            raise ArtifactRenderError(
                "local_source_not_promotable",
                "local-source artifact must declare promotion_eligible=false",
            )
        graph["source_identity"] = f"git:{source_sha}:{dirty_state}"
        promotion_eligible = False
    else:
        raise ArtifactRenderError("mode", f"unsupported delivery mode: {mode!r}")

    return {
        "schema_version": SCHEMA_VERSION,
        "channel": channel,
        "mode": mode,
        "intent": intent,
        "promotion_eligible": promotion_eligible,
        "artifact_graph": graph,
        "compose": compose_copy,
    }


def create_promotion_candidate(
    rendered: Mapping[str, Any],
    manifest: Mapping[str, Any],
) -> dict[str, Any]:
    """Admit only a promotion-mode render as an immutable candidate."""
    if rendered.get("schema_version") != SCHEMA_VERSION:
        raise ArtifactRenderError("render_version", "unsupported artifact render version")
    if rendered.get("mode") == "local-source":
        raise ArtifactRenderError(
            "local_source_not_promotable",
            "local-source output can never create a promotion candidate",
        )
    if rendered.get("mode") != "promotion" or rendered.get("intent") != "promotion":
        raise ArtifactRenderError(
            "promotion_intent_required",
            "promotion candidate admission requires promotion mode and intent",
        )
    if rendered.get("promotion_eligible") is not True:
        raise ArtifactRenderError(
            "promotion_not_eligible",
            "artifact render is not promotion eligible",
        )
    channel = rendered.get("channel")
    if channel not in {"promotion-test", "prod"}:
        raise ArtifactRenderError(
            "promotion_channel",
            "promotion candidate channel must be promotion-test or prod",
        )
    graph = _mapping(rendered.get("artifact_graph"), path="render.artifact_graph")
    for field in (
        "image_index",
        "platform_image",
        "source_identity",
        "compose_identity",
        "migration_identity",
        "config_identity",
        "manifest_identity",
    ):
        _required_string(graph, field, path="render.artifact_graph")

    compose = _mapping(rendered.get("compose"), path="render.compose")
    expected_render = render_channel_manifest(
        manifest,
        compose,
        channel=str(channel),
        mode="promotion",
        intent="promotion",
    )
    if dict(rendered) != expected_render:
        raise ArtifactRenderError(
            "render_binding_mismatch",
            "promotion candidate render does not match the independently supplied ChannelManifest",
        )

    image_index = str(graph["image_index"])
    platform_image = str(graph["platform_image"])
    image_index_match = _DIGEST_IMAGE.fullmatch(image_index)
    platform_match = _DIGEST_IMAGE.fullmatch(platform_image)
    if image_index_match is None or platform_match is None:
        raise ArtifactRenderError(
            "digest_required",
            "promotion candidate requires exact image-index and platform digest identities",
        )
    if image_index_match.group("repository") != platform_match.group("repository"):
        raise ArtifactRenderError(
            "repository_mismatch",
            "image-index and platform identities must use the same repository",
        )
    if _SOURCE_IDENTITY.fullmatch(str(graph["source_identity"])) is None:
        raise ArtifactRenderError(
            "source_identity",
            "promotion candidate source identity must bind one full commit SHA",
        )
    for field in ("compose_identity", "config_identity"):
        if _DIGEST.fullmatch(str(graph[field])) is None:
            raise ArtifactRenderError(
                field,
                f"promotion candidate {field} must be an exact sha256 digest",
            )
    if _MIGRATION_IDENTITY.fullmatch(str(graph["migration_identity"])) is None:
        raise ArtifactRenderError(
            "migration_identity",
            "promotion candidate migration identity must use the alembic:<revision> form",
        )

    if _identity(compose) != graph["compose_identity"]:
        raise ArtifactRenderError(
            "compose_identity_mismatch",
            "promotion candidate Compose content does not match its recorded identity",
        )
    _validate_promotion_compose(compose, expected_platform_image=platform_image)

    return {
        "candidate_version": CANDIDATE_VERSION,
        "channel": channel,
        "artifact_graph": copy.deepcopy(dict(graph)),
        "candidate_identity": _identity(graph),
    }


def _read_manifest(path: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ArtifactRenderError("manifest_unreadable", f"cannot read manifest: {path}") from exc
    return _mapping(value, path="manifest")


def _read_compose(path: Path) -> Mapping[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ArtifactRenderError("compose_unreadable", f"cannot read Compose model: {path}") from exc
    return _mapping(value, path="compose")


def _read_render(path: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ArtifactRenderError("render_unreadable", f"cannot read artifact render: {path}") from exc
    return _mapping(value, path="render")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.release_channels.channel_manifest",
        description="Render and admit immutable startup artifact identities.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    render = subparsers.add_parser("render", help="render a ChannelManifest and Compose model")
    render.add_argument("--manifest", type=Path, required=True)
    render.add_argument("--compose", type=Path, required=True)
    render.add_argument("--channel", required=True)
    render.add_argument("--mode", choices=("local-source", "promotion"), required=True)
    render.add_argument("--intent", choices=("ordinary-boot", "promotion"), required=True)

    candidate = subparsers.add_parser("candidate", help="admit an immutable promotion candidate")
    candidate.add_argument("--rendered", type=Path, required=True)
    candidate.add_argument("--manifest", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "render":
            result = render_channel_manifest(
                _read_manifest(args.manifest),
                _read_compose(args.compose),
                channel=args.channel,
                mode=args.mode,
                intent=args.intent,
            )
        else:
            result = create_promotion_candidate(
                _read_render(args.rendered),
                _read_manifest(args.manifest),
            )
    except ArtifactRenderError as exc:
        print(json.dumps(exc.as_dict(), sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ArtifactRenderError",
    "create_promotion_candidate",
    "render_channel_manifest",
]
