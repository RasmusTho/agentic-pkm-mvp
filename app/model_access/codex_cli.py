"""Version-pinned, bounded Codex CLI transport for no-tools model turns."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import re
import selectors
import signal
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
import uuid
from typing import Any, IO, Literal

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from llm_contract import validate_schema_payload


SAFE_PROFILE_REF = "profile.codex_cli_no_tools_v2"
TOOL_SURFACE_CATALOG_VERSION = "codex_cli_tool_surfaces.v2"
MODEL_CATALOG_SCHEMA_VERSION = "codex_cli_model_catalog.v1"
_MAX_BUNDLED_CATALOG_BYTES = 2_000_000
_MAX_SCHEMA_BYTES = 128_000
_MAX_SCHEMA_NODES = 2_048
_MAX_SCHEMA_DEPTH = 32
_MAX_CONFIGURED_INPUT_BYTES = 8_000_000
_MAX_CONFIGURED_OUTPUT_BYTES = 8_000_000
_MAX_CODEX_CONFIG_BYTES = 1_000_000
_MAX_TRUNCATION_LIMIT = 100_000_000
_PROCESS_SUPERVISOR_PATH = Path(__file__).with_name("process_supervisor.py")
_REASONING_EFFORTS = frozenset(
    {"minimal", "low", "medium", "high", "xhigh", "max", "ultra"}
)
_MODEL_DESCRIPTOR_REQUIRED_KEYS = frozenset(
    {
        "additional_speed_tiers",
        "apply_patch_tool_type",
        "availability_nux",
        "base_instructions",
        "context_window",
        "default_reasoning_level",
        "default_reasoning_summary",
        "default_verbosity",
        "description",
        "display_name",
        "effective_context_window_percent",
        "experimental_supported_tools",
        "include_apps_usage_instructions",
        "include_plugin_usage_instructions",
        "include_skills_usage_instructions",
        "input_modalities",
        "max_context_window",
        "model_messages",
        "node_repl_auto_review_required",
        "node_repl_disabled",
        "priority",
        "service_tiers",
        "shell_type",
        "slug",
        "support_verbosity",
        "supported_in_api",
        "supported_reasoning_levels",
        "supports_experimental_context",
        "supports_image_detail_original",
        "supports_search_tool",
        "truncation_policy",
        "upgrade",
        "use_responses_lite",
        "visibility",
        "web_search_tool_type",
    }
)
_MODEL_DESCRIPTOR_OPTIONAL_KEYS = frozenset(
    {
        "comp_hash",
        "model_specialty",
        "multi_agent_reasoning_effort",
        "multi_agent_version",
        "tool_mode",
    }
)
_MODEL_DESCRIPTOR_KEYS = (
    _MODEL_DESCRIPTOR_REQUIRED_KEYS | _MODEL_DESCRIPTOR_OPTIONAL_KEYS
)
_MODEL_DESCRIPTOR_STRING_FIELDS = frozenset(
    {
        "base_instructions",
        "default_reasoning_summary",
        "display_name",
        "slug",
        "visibility",
    }
)
_MODEL_DESCRIPTOR_NULLABLE_STRING_FIELDS = frozenset(
    {
        "apply_patch_tool_type",
        "default_reasoning_level",
        "default_verbosity",
        "description",
        "model_specialty",
        "multi_agent_reasoning_effort",
        "multi_agent_version",
        "web_search_tool_type",
    }
)
_MODEL_DESCRIPTOR_INTEGER_FIELDS = frozenset(
    {
        "context_window",
        "effective_context_window_percent",
        "max_context_window",
        "priority",
    }
)
_MODEL_DESCRIPTOR_BOOLEAN_FIELDS = frozenset(
    {
        "include_apps_usage_instructions",
        "include_plugin_usage_instructions",
        "include_skills_usage_instructions",
        "node_repl_auto_review_required",
        "node_repl_disabled",
        "support_verbosity",
        "supported_in_api",
        "supports_experimental_context",
        "supports_image_detail_original",
        "supports_search_tool",
        "use_responses_lite",
    }
)
_MODEL_DESCRIPTOR_STRING_LIST_FIELDS = frozenset(
    {
        "additional_speed_tiers",
        "experimental_supported_tools",
        "input_modalities",
    }
)
_MODEL_DESCRIPTOR_OBJECT_LIST_FIELDS = frozenset(
    {"service_tiers", "supported_reasoning_levels"}
)
_DISABLED_CONFIG: tuple[tuple[str, Any], ...] = (
    ("agents.enabled", False),
    ("apps", {}),
    ("approval_policy", "never"),
    ("browser_use.allow_history_access", False),
    ("features.apps", False),
    ("features.auth_elicitation", False),
    ("features.browser_use", False),
    ("features.browser_use_external", False),
    ("features.browser_use_full_cdp_access", False),
    ("features.code_mode.enabled", False),
    ("features.collaboration_modes", False),
    ("features.computer_use", False),
    ("features.connectors", False),
    ("features.context_management.experimental_mode", False),
    ("features.current_time_reminder", False),
    ("features.default_mode_request_user_input", False),
    ("features.deferred_executor", False),
    ("features.exec_permission_approvals", False),
    ("features.goals", False),
    ("features.hooks", False),
    ("features.image_generation", False),
    ("features.in_app_browser", False),
    ("features.memories", False),
    ("features.multi_agent", False),
    ("features.plugin_sharing", False),
    ("features.plugins", False),
    ("features.remote_plugin", False),
    ("features.request_permissions_tool", False),
    ("features.send_message_to_user_async", False),
    ("features.shell_snapshot", False),
    ("features.shell_tool", False),
    ("features.skill_mcp_dependency_install", False),
    ("features.skill_search", False),
    ("features.sleep_tool", False),
    ("features.standalone_web_search", False),
    ("features.tool_call_mcp_elicitation", False),
    ("features.tool_search", False),
    ("features.tool_search_always_defer_mcp_tools", False),
    ("features.tool_suggest", False),
    ("features.token_budget", False),
    ("features.unified_exec", False),
    ("features.view_image", False),
    ("features.web_search", False),
    ("features.web_search_cached", False),
    ("features.web_search_request", False),
    ("history.persistence", "none"),
    ("mcp_servers", {}),
    ("plugins", {}),
    ("tools.view_image", False),
    ("tools.web_search", False),
    ("web_search", "disabled"),
)
_REQUIRED_EXEC_FLAGS = (
    "--ephemeral",
    "--ignore-rules",
    "--ignore-user-config",
    "--model",
    "--output-last-message",
    "--sandbox",
)
_ENVIRONMENT_ALLOWLIST = frozenset(
    {"PATH", "HOME", "CODEX_HOME", "TMPDIR", "LANG", "LC_ALL", "NO_COLOR"}
)
_SESSION_EXPIRED_MARKERS = (
    "please run /login",
    "please log in",
    "not logged in",
    "session expired",
    "session has expired",
    "authentication required",
    "unauthorized",
    "invalid credentials",
)
_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+-]{0,255}$")
_PROFILE_VERSION = re.compile(r"^codex-cli [0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?$")


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON constant: {value}")


def _is_json_value(value: Any, *, depth: int = 0) -> bool:
    if depth > 32:
        return False
    if value is None or type(value) in {str, bool, int}:
        return True
    if type(value) is float:
        return math.isfinite(value)
    if isinstance(value, list):
        return all(_is_json_value(item, depth=depth + 1) for item in value)
    if isinstance(value, dict):
        return all(
            isinstance(key, str) and _is_json_value(item, depth=depth + 1)
            for key, item in value.items()
        )
    return False


def _valid_model_descriptor(descriptor: Mapping[str, Any]) -> bool:
    keys = set(descriptor)
    if not _MODEL_DESCRIPTOR_REQUIRED_KEYS.issubset(keys):
        return False
    if not keys.issubset(_MODEL_DESCRIPTOR_KEYS):
        return False
    if any(
        not isinstance(descriptor[key], str)
        for key in _MODEL_DESCRIPTOR_STRING_FIELDS.intersection(keys)
    ):
        return False
    if any(
        descriptor[key] is not None and not isinstance(descriptor[key], str)
        for key in _MODEL_DESCRIPTOR_NULLABLE_STRING_FIELDS.intersection(keys)
    ):
        return False
    if any(
        type(descriptor[key]) is not int
        for key in _MODEL_DESCRIPTOR_INTEGER_FIELDS
    ):
        return False
    if any(
        type(descriptor[key]) is not bool
        for key in _MODEL_DESCRIPTOR_BOOLEAN_FIELDS
    ):
        return False
    if any(
        not isinstance(descriptor[key], list)
        or any(not isinstance(item, str) for item in descriptor[key])
        for key in _MODEL_DESCRIPTOR_STRING_LIST_FIELDS
    ):
        return False
    if any(
        not isinstance(descriptor[key], list)
        or any(not isinstance(item, dict) for item in descriptor[key])
        for key in _MODEL_DESCRIPTOR_OBJECT_LIST_FIELDS
    ):
        return False
    reasoning_levels = descriptor["supported_reasoning_levels"]
    if any(
        set(item) != {"effort", "description"}
        or not isinstance(item["effort"], str)
        or item["effort"] not in _REASONING_EFFORTS
        or not isinstance(item["description"], str)
        for item in reasoning_levels
    ):
        return False
    if len({item["effort"] for item in reasoning_levels}) != len(reasoning_levels):
        return False
    service_tiers = descriptor["service_tiers"]
    if any(
        set(item) != {"id", "name", "description"}
        or any(not isinstance(item[key], str) for key in ("id", "name", "description"))
        for item in service_tiers
    ):
        return False
    if not isinstance(descriptor["model_messages"], dict):
        return False
    truncation_policy = descriptor["truncation_policy"]
    if (
        not isinstance(truncation_policy, dict)
        or set(truncation_policy) != {"mode", "limit"}
        or not isinstance(truncation_policy.get("mode"), str)
        or truncation_policy.get("mode") not in {"tokens", "bytes"}
        or type(truncation_policy.get("limit")) is not int
        or not 0 < truncation_policy["limit"] <= _MAX_TRUNCATION_LIMIT
    ):
        return False
    availability_nux = descriptor["availability_nux"]
    if availability_nux is not None and (
        not isinstance(availability_nux, dict)
        or set(availability_nux) != {"message"}
        or not isinstance(availability_nux["message"], str)
    ):
        return False
    if not isinstance(descriptor["shell_type"], str):
        return False
    if descriptor.get("comp_hash") is not None and not isinstance(
        descriptor["comp_hash"], str
    ):
        return False
    if descriptor.get("tool_mode") is not None and not isinstance(descriptor["tool_mode"], str):
        return False
    if descriptor.get("upgrade") is not None and not isinstance(
        descriptor["upgrade"], dict
    ):
        return False
    upgrade = descriptor.get("upgrade")
    if upgrade is not None:
        upgrade_shapes = (
            {"model", "migration_markdown", "retirement_at"},
            {
                "id",
                "migration_config_key",
                "model_link",
                "upgrade_copy",
                "migration_markdown",
                "retirement_at",
            },
        )
        if set(upgrade) not in upgrade_shapes:
            return False
        if any(
            value is not None and not isinstance(value, str)
            for value in upgrade.values()
        ):
            return False
    if any(
        isinstance(descriptor.get(key), int) and descriptor[key] < 0
        for key in ("context_window", "max_context_window", "priority")
    ):
        return False
    if not 0 <= descriptor["effective_context_window_percent"] <= 100:
        return False
    return all(_is_json_value(value) for value in descriptor.values())


def _schema_tree_is_bounded(value: Any) -> bool:
    allowed_keywords = frozenset(
        {
            "type",
            "properties",
            "required",
            "additionalProperties",
            "items",
            "enum",
            "const",
            "minimum",
            "maximum",
            "exclusiveMinimum",
            "exclusiveMaximum",
            "multipleOf",
            "minLength",
            "maxLength",
            "minItems",
            "maxItems",
            "minProperties",
            "maxProperties",
        }
    )
    pending: list[tuple[Any, int]] = [(value, 0)]
    visited = 0
    while pending:
        current, depth = pending.pop()
        visited += 1
        if (
            depth > _MAX_SCHEMA_DEPTH
            or visited > _MAX_SCHEMA_NODES
            or not isinstance(current, dict)
            or not set(current).issubset(allowed_keywords)
        ):
            return False
        properties = current.get("properties", {})
        if not isinstance(properties, dict):
            return False
        pending.extend((item, depth + 1) for item in properties.values())
        for keyword in ("items", "additionalProperties"):
            nested = current.get(keyword)
            if isinstance(nested, dict):
                pending.append((nested, depth + 1))
            elif nested is not None and not isinstance(nested, bool):
                return False
        for keyword in ("enum", "const"):
            if keyword in current and not _is_json_value(current[keyword]):
                return False
    return True


def _bounded_schema_snapshot(
    schema_ref: str,
    schema: Mapping[str, Any],
    *,
    max_bytes: int,
) -> tuple[dict[str, Any], str]:
    try:
        schema_value = dict(schema)
        if not _schema_tree_is_bounded(schema_value):
            raise ValueError("schema tree exceeds bounds or uses references")
        serialized = json.dumps(
            schema_value,
            ensure_ascii=False,
            sort_keys=True,
            allow_nan=False,
        )
        encoded = serialized.encode("utf-8")
        if len(encoded) > max_bytes:
            raise ValueError("schema exceeds byte bound")
        snapshot = json.loads(
            serialized,
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
        if not isinstance(snapshot, dict):
            raise ValueError("schema root must be an object")
        Draft202012Validator.check_schema(snapshot)
    except (TypeError, ValueError, OverflowError, RecursionError, SchemaError) as exc:
        raise CodexCliError("schema_violation") from exc
    return snapshot, serialized


def _executable_identity(path: Path) -> tuple[int, int, int, int, int]:
    stat = path.stat()
    return (
        stat.st_dev,
        stat.st_ino,
        stat.st_size,
        stat.st_mtime_ns,
        stat.st_ctime_ns,
    )


class CodexCliError(RuntimeError):
    """Receipt-safe transport error; it intentionally carries no raw CLI output."""

    def __init__(
        self,
        failure_code: Literal[
            "unsupported_profile",
            "cli_missing",
            "cli_version_unsupported",
            "tool_surface_unknown",
            "authentication_unavailable",
            "session_expired",
            "command_timeout",
            "command_exit_nonzero",
            "stdout_oversize",
            "input_oversize",
            "model_unavailable",
            "stdout_empty",
            "schema_violation",
        ],
    ) -> None:
        self.failure_code = failure_code
        super().__init__(failure_code)


@dataclass(frozen=True)
class CodexCliSafeProfile:
    """Host-local review attestation for one exact CLI build and model catalog schema."""

    cli_version: str
    output_schema_supported: bool
    tool_surface_catalog_version: str = TOOL_SURFACE_CATALOG_VERSION
    model_catalog_schema_version: str = MODEL_CATALOG_SCHEMA_VERSION
    profile_ref: str = SAFE_PROFILE_REF

    def __post_init__(self) -> None:
        if self.profile_ref != SAFE_PROFILE_REF:
            raise CodexCliError("unsupported_profile")
        if not _PROFILE_VERSION.fullmatch(self.cli_version):
            raise CodexCliError("unsupported_profile")
        if self.tool_surface_catalog_version != TOOL_SURFACE_CATALOG_VERSION:
            raise CodexCliError("unsupported_profile")
        if self.model_catalog_schema_version != MODEL_CATALOG_SCHEMA_VERSION:
            raise CodexCliError("tool_surface_unknown")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "CodexCliSafeProfile":
        expected = {
            "schema_version",
            "profile_ref",
            "cli_version",
            "output_schema_supported",
            "tool_surface_catalog_version",
            "model_catalog_schema_version",
        }
        if set(value) != expected or value.get("schema_version") != "codex-cli-safe-profile.v2":
            raise CodexCliError("unsupported_profile")
        if not all(
            isinstance(value.get(field), str)
            for field in (
                "profile_ref",
                "cli_version",
                "tool_surface_catalog_version",
                "model_catalog_schema_version",
            )
        ):
            raise CodexCliError("unsupported_profile")
        if not isinstance(value.get("output_schema_supported"), bool):
            raise CodexCliError("unsupported_profile")
        return cls(
            cli_version=value["cli_version"],
            output_schema_supported=value["output_schema_supported"],
            tool_surface_catalog_version=value["tool_surface_catalog_version"],
            model_catalog_schema_version=value["model_catalog_schema_version"],
            profile_ref=value["profile_ref"],
        )

    @classmethod
    def load(cls, path: Path) -> "CodexCliSafeProfile":
        try:
            if not path.is_file() or path.stat().st_size > 16_384:
                raise CodexCliError("unsupported_profile")
            raw = json.loads(
                path.read_text(encoding="utf-8"),
                object_pairs_hook=_unique_json_object,
            )
        except (OSError, ValueError, UnicodeError, RecursionError) as exc:
            raise CodexCliError("unsupported_profile") from exc
        if not isinstance(raw, dict):
            raise CodexCliError("unsupported_profile")
        return cls.from_mapping(raw)


@dataclass(frozen=True)
class CodexCliPreflight:
    cli_version: str
    authentication_status: Literal["chatgpt_subscription"]
    output_schema_supported: bool
    safe_profile_ref: str


@dataclass(frozen=True)
class CodexCliResult:
    response_text: str
    cli_version: str
    safe_profile_ref: str


class CodexCliExecutor:
    """Execute a single exact target after safe-profile, version, and auth checks."""

    def __init__(
        self,
        *,
        safe_profile_path: Path | str | None = None,
        process_group_mode: Literal["isolated", "inherited"] = "isolated",
        environment: Mapping[str, str] | None = None,
        executable_name: str = "codex",
        preflight_timeout_seconds: float = 10.0,
        execution_timeout_seconds: float = 1200.0,
        max_output_bytes: int = 1_000_000,
        max_input_bytes: int = 2_000_000,
        caller_liveness_fd: int | None = None,
    ) -> None:
        self._safe_profile_path = (
            Path(safe_profile_path) if safe_profile_path is not None else None
        )
        if process_group_mode not in {"isolated", "inherited"}:
            raise ValueError("Codex CLI process_group_mode is unsupported")
        self._process_group_mode = process_group_mode
        self._environment = dict(os.environ if environment is None else environment)
        self._executable_name = executable_name
        self._preflight_timeout_seconds = preflight_timeout_seconds
        self._execution_timeout_seconds = execution_timeout_seconds
        self._max_output_bytes = max_output_bytes
        self._max_input_bytes = max_input_bytes
        if caller_liveness_fd is not None and (
            type(caller_liveness_fd) is not int or caller_liveness_fd < 0
        ):
            raise ValueError("Codex CLI caller-liveness descriptor is invalid")
        self._caller_liveness_fd = caller_liveness_fd
        if min(
            preflight_timeout_seconds,
            execution_timeout_seconds,
            max_output_bytes,
            max_input_bytes,
        ) <= 0:
            raise ValueError("Codex CLI bounds must be positive")
        if max_output_bytes > _MAX_CONFIGURED_OUTPUT_BYTES or max_input_bytes > _MAX_CONFIGURED_INPUT_BYTES:
            raise ValueError("Codex CLI byte bounds exceed the hard maximum")

    def preflight(self, *, model: str) -> CodexCliPreflight:
        preflight, _safe_catalog, _cli_path, _cli_identity, _credential_store = (
            self._preflight(model=model)
        )
        return preflight

    def _preflight(
        self, *, model: str, reasoning_effort: str | None = None
    ) -> tuple[CodexCliPreflight, bytes, str, tuple[int, int, int, int, int], str]:
        profile = self._require_profile()
        credential_store = self._credential_store()
        cli_path = shutil.which(
            self._executable_name,
            path=self._environment.get("PATH", ""),
        )
        if cli_path is None:
            raise CodexCliError("cli_missing")
        try:
            cli_path = str(Path(cli_path).resolve(strict=True))
            cli_identity = _executable_identity(Path(cli_path))
        except OSError as exc:
            raise CodexCliError("cli_missing") from exc

        version_result = self._run_bounded(
            [cli_path, "--version"],
            cwd=None,
            input_text=None,
            timeout_seconds=self._preflight_timeout_seconds,
            expected_executable_identity=cli_identity,
        )
        version_text = version_result.stdout.decode("utf-8", errors="replace").strip()
        if version_result.returncode != 0 or version_text != profile.cli_version:
            raise CodexCliError("cli_version_unsupported")

        help_result = self._run_bounded(
            [cli_path, "exec", "--help"],
            cwd=None,
            input_text=None,
            timeout_seconds=self._preflight_timeout_seconds,
            expected_executable_identity=cli_identity,
        )
        help_text = (
            help_result.stdout + b"\n" + help_result.stderr
        ).decode("utf-8", errors="replace")
        if help_result.returncode != 0 or not all(
            flag in help_text for flag in _REQUIRED_EXEC_FLAGS
        ):
            raise CodexCliError("tool_surface_unknown")
        if profile.output_schema_supported and "--output-schema" not in help_text:
            raise CodexCliError("cli_version_unsupported")

        auth_result = self._run_bounded(
            [
                cli_path,
                "-c",
                f"cli_auth_credentials_store={json.dumps(credential_store)}",
                "login",
                "status",
            ],
            cwd=None,
            input_text=None,
            timeout_seconds=self._preflight_timeout_seconds,
            expected_executable_identity=cli_identity,
        )
        auth_text = (auth_result.stdout + b"\n" + auth_result.stderr).decode(
            "utf-8", errors="replace"
        )
        if any(marker in auth_text.lower() for marker in _SESSION_EXPIRED_MARKERS):
            raise CodexCliError("session_expired")
        auth_streams = [
            stream.decode("utf-8", errors="replace").strip()
            for stream in (auth_result.stdout, auth_result.stderr)
            if stream.strip()
        ]
        if auth_result.returncode != 0 or auth_streams != ["Logged in using ChatGPT"]:
            raise CodexCliError("authentication_unavailable")

        if not _MODEL_ID.fullmatch(model):
            raise CodexCliError("model_unavailable")
        catalog_result = self._run_bounded(
            [cli_path, "debug", "models", "--bundled"],
            cwd=None,
            input_text=None,
            timeout_seconds=self._preflight_timeout_seconds,
            max_output_bytes=_MAX_BUNDLED_CATALOG_BYTES,
            expected_executable_identity=cli_identity,
        )
        if catalog_result.returncode != 0:
            raise CodexCliError("tool_surface_unknown")
        safe_catalog = self._sanitize_model_catalog(
            catalog_result.stdout,
            model=model,
            reasoning_effort=reasoning_effort,
        )

        try:
            if _executable_identity(Path(cli_path)) != cli_identity:
                raise CodexCliError("cli_version_unsupported")
        except OSError as exc:
            raise CodexCliError("cli_missing") from exc

        return (
            CodexCliPreflight(
                cli_version=profile.cli_version,
                authentication_status="chatgpt_subscription",
                output_schema_supported=profile.output_schema_supported,
                safe_profile_ref=profile.profile_ref,
            ),
            safe_catalog,
            cli_path,
            cli_identity,
            credential_store,
        )

    def _credential_store(self) -> str:
        home = self._environment.get("HOME")
        if home is None:
            try:
                home = str(Path.home())
            except RuntimeError as exc:
                raise CodexCliError("authentication_unavailable") from exc
        if not home or not Path(home).is_absolute():
            raise CodexCliError("authentication_unavailable")
        configured_home = self._environment.get("CODEX_HOME")
        if configured_home:
            codex_home = Path(configured_home)
            if not codex_home.is_absolute():
                raise CodexCliError("authentication_unavailable")
            config_path = codex_home / "config.toml"
        elif "CODEX_HOME" in self._environment:
            raise CodexCliError("authentication_unavailable")
        else:
            config_path = Path(home) / ".codex" / "config.toml"
        try:
            with config_path.open("rb") as config_file:
                config_bytes = config_file.read(_MAX_CODEX_CONFIG_BYTES + 1)
        except FileNotFoundError:
            return "file"
        except OSError as exc:
            raise CodexCliError("authentication_unavailable") from exc
        if len(config_bytes) > _MAX_CODEX_CONFIG_BYTES:
            raise CodexCliError("authentication_unavailable")
        try:
            config = tomllib.loads(config_bytes.decode("utf-8"))
        except (UnicodeError, ValueError) as exc:
            raise CodexCliError("authentication_unavailable") from exc
        credential_store = config.get("cli_auth_credentials_store", "file")
        if not isinstance(credential_store, str) or credential_store not in {
            "file",
            "keyring",
        }:
            raise CodexCliError("authentication_unavailable")
        return credential_store

    @staticmethod
    def _sanitize_model_catalog(
        raw: bytes, *, model: str, reasoning_effort: str | None = None
    ) -> bytes:
        try:
            catalog = json.loads(
                raw.decode("utf-8", errors="strict"),
                object_pairs_hook=_unique_json_object,
                parse_constant=_reject_json_constant,
            )
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
            ValueError,
            RecursionError,
        ) as exc:
            raise CodexCliError("tool_surface_unknown") from exc
        if not isinstance(catalog, dict) or set(catalog) != {"models"}:
            raise CodexCliError("tool_surface_unknown")
        models = catalog.get("models")
        if not isinstance(models, list) or not models:
            raise CodexCliError("tool_surface_unknown")

        slugs: set[str] = set()
        selected_matches = 0
        safe_models: list[dict[str, Any]] = []
        for descriptor in models:
            if not isinstance(descriptor, dict) or not _valid_model_descriptor(
                descriptor
            ):
                raise CodexCliError("tool_surface_unknown")
            slug = descriptor.get("slug")
            if not isinstance(slug, str) or not _MODEL_ID.fullmatch(slug) or slug in slugs:
                raise CodexCliError("tool_surface_unknown")
            slugs.add(slug)
            if slug == model:
                selected_matches += 1

            safe_descriptor = dict(descriptor)
            safe_descriptor.update(
                {
                    "apply_patch_tool_type": None,
                    "experimental_supported_tools": [],
                    "include_apps_usage_instructions": False,
                    "include_plugin_usage_instructions": False,
                    "include_skills_usage_instructions": False,
                    "multi_agent_reasoning_effort": None,
                    "multi_agent_version": None,
                    "model_messages": {},
                    "node_repl_auto_review_required": False,
                    "node_repl_disabled": True,
                    "shell_type": "disabled",
                    "supports_search_tool": False,
                    "tool_mode": None,
                    "web_search_tool_type": None,
                }
            )
            if slug == model and reasoning_effort is not None:
                supported_efforts = {
                    item["effort"]
                    for item in descriptor["supported_reasoning_levels"]
                }
                if reasoning_effort not in supported_efforts:
                    raise CodexCliError("model_unavailable")
            safe_models.append(safe_descriptor)
        if selected_matches != 1:
            raise CodexCliError("model_unavailable")
        return json.dumps(
            {"models": safe_models}, ensure_ascii=False, sort_keys=True
        ).encode("utf-8")

    def execute(
        self,
        *,
        model: str,
        reasoning_effort: str,
        developer_instructions: str,
        user_prompt: str,
        output_schema_ref: str | None = None,
        output_schema: Mapping[str, Any] | None = None,
        literal_system_role_required: bool = False,
    ) -> CodexCliResult:
        self._require_profile()
        if literal_system_role_required:
            raise CodexCliError("unsupported_profile")
        if not _MODEL_ID.fullmatch(model) or reasoning_effort not in _REASONING_EFFORTS:
            raise CodexCliError("unsupported_profile")
        if (output_schema_ref is None) != (output_schema is None):
            raise CodexCliError("schema_violation")
        if output_schema_ref is not None and not output_schema_ref.strip():
            raise CodexCliError("schema_violation")
        if len(user_prompt.encode("utf-8")) > self._max_input_bytes:
            raise CodexCliError("input_oversize")
        if len(developer_instructions.encode("utf-8")) > self._max_input_bytes:
            raise CodexCliError("input_oversize")

        normalized_schema: dict[str, Any] | None = None
        schema_text: str | None = None
        if output_schema is not None:
            normalized_schema, schema_text = _bounded_schema_snapshot(
                output_schema_ref or "",
                output_schema,
                max_bytes=min(_MAX_SCHEMA_BYTES, self._max_input_bytes),
            )

        preflight, safe_catalog, cli_path, cli_identity, credential_store = (
            self._preflight(model=model, reasoning_effort=reasoning_effort)
        )

        with tempfile.TemporaryDirectory(prefix="model-access-codex-") as temp_root:
            root = Path(temp_root)
            workdir = root / "empty-workspace"
            workdir.mkdir()
            output_path = root / "final-response.json"
            model_catalog_path = root / "safe-model-catalog.json"
            model_catalog_path.write_bytes(safe_catalog)
            argv = self._execution_argv(
                cli_path=cli_path,
                model=model,
                reasoning_effort=reasoning_effort,
                developer_instructions=developer_instructions,
                credential_store=credential_store,
                output_path=output_path,
                model_catalog_path=model_catalog_path,
                output_schema_path=(root / "output.schema.json")
                if normalized_schema is not None and preflight.output_schema_supported
                else None,
            )
            schema_path = root / "output.schema.json"
            if schema_text is not None and preflight.output_schema_supported:
                schema_path.write_text(schema_text, encoding="utf-8")
            env = self._child_environment(temp_root=root)
            try:
                result = self._run_bounded(
                    argv,
                    cwd=workdir,
                    input_text=user_prompt,
                    timeout_seconds=self._execution_timeout_seconds,
                    environment=env,
                    expected_executable_identity=cli_identity,
                    max_file_bytes=self._max_output_bytes,
                )
            except CodexCliError:
                raise
            if result.returncode != 0:
                error_text = result.stderr.decode("utf-8", errors="replace").lower()
                if "file too large" in error_text or "file size limit" in error_text:
                    raise CodexCliError("stdout_oversize")
                try:
                    output_was_limited = (
                        output_path.stat().st_size >= self._max_output_bytes
                    )
                except OSError:
                    output_was_limited = False
                if output_was_limited or result.returncode == -getattr(
                    signal, "SIGXFSZ", -1
                ):
                    raise CodexCliError("stdout_oversize")
                if any(
                    marker in error_text
                    for marker in _SESSION_EXPIRED_MARKERS
                ):
                    raise CodexCliError("session_expired")
                raise CodexCliError("command_exit_nonzero")
            try:
                if output_path.stat().st_size > self._max_output_bytes:
                    raise CodexCliError("stdout_oversize")
                with output_path.open("rb") as response_file:
                    response_bytes = response_file.read(self._max_output_bytes + 1)
            except OSError as exc:
                raise CodexCliError("stdout_empty") from exc
            if len(response_bytes) > self._max_output_bytes:
                raise CodexCliError("stdout_oversize")
            try:
                response_text = response_bytes.decode("utf-8", errors="strict").strip()
            except UnicodeDecodeError as exc:
                raise CodexCliError("schema_violation") from exc
            if not response_text:
                raise CodexCliError("stdout_empty")
            if normalized_schema is not None:
                try:
                    payload = json.loads(
                        response_text,
                        object_pairs_hook=_unique_json_object,
                        parse_constant=_reject_json_constant,
                    )
                    if not _is_json_value(payload):
                        raise ValueError("response JSON exceeds depth or value limits")
                    validate_schema_payload(
                        output_schema_ref or "", normalized_schema, payload
                    )
                except (
                    json.JSONDecodeError,
                    UnicodeError,
                    ValueError,
                    TypeError,
                    OverflowError,
                    RecursionError,
                ) as exc:
                    raise CodexCliError("schema_violation") from exc

        return CodexCliResult(
            response_text=response_text,
            cli_version=preflight.cli_version,
            safe_profile_ref=preflight.safe_profile_ref,
        )

    def _require_profile(self) -> CodexCliSafeProfile:
        if self._safe_profile_path is None:
            raise CodexCliError("unsupported_profile")
        return CodexCliSafeProfile.load(self._safe_profile_path)

    def _execution_argv(
        self,
        *,
        cli_path: str,
        model: str,
        reasoning_effort: str,
        developer_instructions: str,
        credential_store: str,
        output_path: Path,
        model_catalog_path: Path,
        output_schema_path: Path | None,
    ) -> list[str]:
        argv = [
            cli_path,
            "exec",
            "--ephemeral",
            "--ignore-user-config",
            "--ignore-rules",
            "--skip-git-repo-check",
            "--sandbox",
            "read-only",
            "--model",
            model,
            "--output-last-message",
            str(output_path),
            "-c",
            f"model_reasoning_effort={json.dumps(reasoning_effort)}",
            "-c",
            f"developer_instructions={json.dumps(developer_instructions, ensure_ascii=False)}",
            "-c",
            f"cli_auth_credentials_store={json.dumps(credential_store)}",
            "-c",
            f"model_catalog_json={json.dumps(str(model_catalog_path))}",
        ]
        for key, value in _DISABLED_CONFIG:
            argv.extend(("-c", f"{key}={json.dumps(value, ensure_ascii=False)}"))
        if output_schema_path is not None:
            argv.extend(("--output-schema", str(output_schema_path)))
        argv.append("-")
        return argv

    def _child_environment(self, *, temp_root: Path) -> dict[str, str]:
        allowed = {
            key: value
            for key, value in self._environment.items()
            if key in _ENVIRONMENT_ALLOWLIST and isinstance(value, str)
        }
        allowed.setdefault("PATH", "")
        if "HOME" not in allowed:
            allowed["HOME"] = str(Path.home())
        allowed["TMPDIR"] = str(temp_root)
        allowed["NO_COLOR"] = "1"
        return allowed

    def _run_bounded(
        self,
        argv: list[str],
        *,
        cwd: Path | None,
        input_text: str | None,
        timeout_seconds: float,
        environment: Mapping[str, str] | None = None,
        max_output_bytes: int | None = None,
        expected_executable_identity: tuple[int, int, int, int, int] | None = None,
        max_file_bytes: int | None = None,
    ) -> subprocess.CompletedProcess[bytes]:
        input_bytes = None if input_text is None else input_text.encode("utf-8")
        if input_bytes is not None and len(input_bytes) > self._max_input_bytes:
            raise CodexCliError("input_oversize")
        if (
            os.name != "posix"
            or not hasattr(os, "fork")
            or expected_executable_identity is None
            or not _PROCESS_SUPERVISOR_PATH.is_file()
        ):
            raise CodexCliError("unsupported_profile")
        if max_file_bytes is not None and max_file_bytes <= 0:
            raise CodexCliError("unsupported_profile")
        if self._caller_liveness_fd is not None:
            try:
                os.fstat(self._caller_liveness_fd)
            except OSError as exc:
                raise CodexCliError("unsupported_profile") from exc
        stdin_context = tempfile.TemporaryFile()
        process: subprocess.Popen[bytes] | None = None
        selector = selectors.DefaultSelector()
        started = time.monotonic()
        stdout = bytearray()
        stderr = bytearray()
        output_limit = self._max_output_bytes if max_output_bytes is None else max_output_bytes
        parent_read_fd, parent_write_fd = os.pipe()
        status_read_fd, status_write_fd = os.pipe()
        status_read_open = True
        snapshot_path: str | None = None
        status_buffer = bytearray()
        terminal_status: dict[str, Any] | None = None
        cli_process_group: int | None = None
        try:
            stdin_source: int | IO[bytes]
            if input_bytes is not None:
                stdin_context.write(input_bytes)
                stdin_context.seek(0)
                stdin_source = stdin_context
            else:
                stdin_source = subprocess.DEVNULL
            try:
                try:
                    current_identity = _executable_identity(Path(argv[0]))
                except OSError as exc:
                    raise CodexCliError("cli_missing") from exc
                if current_identity != expected_executable_identity:
                    raise CodexCliError("cli_version_unsupported")
                source_path = Path(argv[0])
                snapshot_path = str(
                    source_path.parent
                    / f".{source_path.name}.model-access-{uuid.uuid4().hex}"
                )
                launch_argv = [
                    sys.executable,
                    "-I",
                    str(_PROCESS_SUPERVISOR_PATH),
                    "--parent-fd",
                    str(parent_read_fd),
                    "--caller-liveness-fd",
                    str(
                        self._caller_liveness_fd
                        if self._caller_liveness_fd is not None
                        else -1
                    ),
                    "--status-fd",
                    str(status_write_fd),
                    "--timeout-ms",
                    str(max(1, round(timeout_seconds * 1000))),
                    "--file-limit",
                    str(max_file_bytes or 0),
                    "--staging-path",
                    snapshot_path,
                    "--expected-identity",
                    json.dumps(expected_executable_identity),
                    "--",
                    *argv,
                ]
                process = subprocess.Popen(
                    launch_argv,
                    cwd=cwd,
                    stdin=stdin_source,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=dict(environment) if environment is not None else self._child_environment(
                        temp_root=Path(tempfile.gettempdir())
                    ),
                    shell=False,
                    start_new_session=True,
                    pass_fds=(
                        (parent_read_fd, status_write_fd)
                        if self._caller_liveness_fd is None
                        else (
                            parent_read_fd,
                            status_write_fd,
                            self._caller_liveness_fd,
                        )
                    ),
                )
            except FileNotFoundError as exc:
                raise CodexCliError("cli_missing") from exc
            os.close(parent_read_fd)
            parent_read_fd = -1
            os.close(status_write_fd)
            status_write_fd = -1
            assert process.stdout is not None and process.stderr is not None
            os.set_blocking(process.stdout.fileno(), False)
            os.set_blocking(process.stderr.fileno(), False)
            os.set_blocking(status_read_fd, False)
            selector.register(process.stdout, selectors.EVENT_READ, "stdout")
            selector.register(process.stderr, selectors.EVENT_READ, "stderr")
            selector.register(status_read_fd, selectors.EVENT_READ, "status")
            while selector.get_map():
                remaining = timeout_seconds - (time.monotonic() - started)
                if remaining <= 0:
                    raise CodexCliError("command_timeout")
                for key, _ in selector.select(min(remaining, 0.1)):
                    if key.data == "status":
                        chunk = os.read(status_read_fd, 4096)
                        if not chunk:
                            selector.unregister(key.fileobj)
                            os.close(status_read_fd)
                            status_read_fd = -1
                            status_read_open = False
                            if terminal_status is None:
                                self._kill_process_group(cli_process_group)
                                raise CodexCliError("command_exit_nonzero")
                            continue
                        status_buffer.extend(chunk)
                        if len(status_buffer) > 4096:
                            self._kill_process_group(cli_process_group)
                            raise CodexCliError("command_exit_nonzero")
                        while b"\n" in status_buffer:
                            line, _, remainder = status_buffer.partition(b"\n")
                            status_buffer = bytearray(remainder)
                            try:
                                message = json.loads(line.decode("utf-8", errors="strict"))
                            except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
                                self._kill_process_group(cli_process_group)
                                raise CodexCliError("command_exit_nonzero") from exc
                            if not isinstance(message, dict):
                                self._kill_process_group(cli_process_group)
                                raise CodexCliError("command_exit_nonzero")
                            if message.get("kind") == "started":
                                process_group = message.get("process_group")
                                if type(process_group) is not int or process_group <= 1:
                                    raise CodexCliError("command_exit_nonzero")
                                cli_process_group = process_group
                            elif terminal_status is None:
                                terminal_status = message
                            else:
                                raise CodexCliError("command_exit_nonzero")
                        continue
                    chunk = os.read(key.fd, 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    target = stdout if key.data == "stdout" else stderr
                    target.extend(chunk)
                    if len(stdout) + len(stderr) > output_limit:
                        raise CodexCliError("stdout_oversize")
            remaining = timeout_seconds - (time.monotonic() - started)
            if remaining <= 0:
                raise CodexCliError("command_timeout")
            process.wait(timeout=remaining)
            status = terminal_status
            if status is None or status_buffer:
                self._kill_process_group(cli_process_group)
                raise CodexCliError("command_exit_nonzero")
            status_kind = status.get("kind")
            if status_kind == "identity_mismatch":
                raise CodexCliError("cli_version_unsupported")
            if status_kind == "unsupported":
                raise CodexCliError("unsupported_profile")
            if status_kind == "limit_unavailable":
                raise CodexCliError("unsupported_profile")
            if status_kind in {"timeout", "parent_lost"}:
                raise CodexCliError("command_timeout")
            if status_kind != "completed" or type(status.get("returncode")) is not int:
                raise CodexCliError("command_exit_nonzero")
            return subprocess.CompletedProcess(
                argv,
                status["returncode"],
                bytes(stdout),
                bytes(stderr),
            )
        except subprocess.TimeoutExpired as exc:
            raise CodexCliError("command_timeout") from exc
        finally:
            selector.close()
            if process is not None:
                if parent_write_fd >= 0:
                    os.close(parent_write_fd)
                    parent_write_fd = -1
                if terminal_status is None or terminal_status.get("kind") not in {
                    "completed",
                    "timeout",
                    "parent_lost",
                }:
                    self._kill_process_group(cli_process_group)
                try:
                    process.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    self._terminate(process)
                for stream in (process.stdout, process.stderr):
                    if stream is not None:
                        try:
                            stream.close()
                        except OSError:
                            pass
            for fd in (parent_read_fd, parent_write_fd, status_write_fd):
                if fd >= 0:
                    try:
                        os.close(fd)
                    except OSError:
                        pass
            if status_read_open:
                try:
                    os.close(status_read_fd)
                except OSError:
                    pass
            if snapshot_path is not None:
                self._remove_snapshot_path(snapshot_path)
            stdin_context.close()

    @staticmethod
    def _remove_snapshot_path(path: str) -> None:
        try:
            Path(path).unlink()
        except OSError:
            pass

    @staticmethod
    def _kill_process_group(process_group: int | None) -> None:
        if process_group is None:
            return
        try:
            os.killpg(process_group, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass

    def _terminate(self, process: subprocess.Popen[bytes]) -> None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except PermissionError:
            try:
                process.kill()
            except ProcessLookupError:
                pass
        try:
            process.wait(timeout=0.25)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            process.wait()
        except ChildProcessError:
            pass


__all__ = (
    "CodexCliError",
    "CodexCliExecutor",
    "CodexCliPreflight",
    "CodexCliResult",
    "CodexCliSafeProfile",
    "SAFE_PROFILE_REF",
)
