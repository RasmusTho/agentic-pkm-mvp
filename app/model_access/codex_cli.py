"""Version-pinned, bounded Codex CLI transport for no-tools model turns."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import selectors
import signal
import shutil
import subprocess
import tempfile
import time
from typing import Any, IO, Literal

from llm_contract import validate_schema_payload


SAFE_PROFILE_REF = "profile.codex_cli_no_tools_v2"
TOOL_SURFACE_CATALOG_VERSION = "codex_cli_tool_surfaces.v2"
MODEL_CATALOG_SCHEMA_VERSION = "codex_cli_model_catalog.v1"
_MAX_BUNDLED_CATALOG_BYTES = 2_000_000
_MODEL_DESCRIPTOR_KEYS = frozenset(
    {
        "additional_speed_tiers",
        "apply_patch_tool_type",
        "availability_nux",
        "base_instructions",
        "comp_hash",
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
        "model_specialty",
        "multi_agent_reasoning_effort",
        "multi_agent_version",
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
        "tool_mode",
        "truncation_policy",
        "upgrade",
        "use_responses_lite",
        "visibility",
        "web_search_tool_type",
    }
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
_REASONING_EFFORTS = frozenset({"minimal", "low", "medium", "high", "xhigh"})
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
        except (OSError, ValueError, UnicodeError) as exc:
            raise CodexCliError("unsupported_profile") from exc
        if not isinstance(raw, dict):
            raise CodexCliError("unsupported_profile")
        return cls.from_mapping(raw)


@dataclass(frozen=True)
class CodexCliPreflight:
    cli_version: str
    authentication_status: Literal["logged_in"]
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
        if min(
            preflight_timeout_seconds,
            execution_timeout_seconds,
            max_output_bytes,
            max_input_bytes,
        ) <= 0:
            raise ValueError("Codex CLI bounds must be positive")

    def preflight(self, *, model: str) -> CodexCliPreflight:
        preflight, _safe_catalog, _cli_path, _cli_identity = self._preflight(model=model)
        return preflight

    def _preflight(
        self, *, model: str
    ) -> tuple[CodexCliPreflight, bytes, str, tuple[int, int, int, int, int]]:
        profile = self._require_profile()
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
            [cli_path, "login", "status"],
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
        if auth_result.returncode != 0 or not re.search(
            r"\blogged[ -]in\b", auth_text, re.IGNORECASE
        ):
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
        safe_catalog = self._sanitize_model_catalog(catalog_result.stdout, model=model)

        try:
            if _executable_identity(Path(cli_path)) != cli_identity:
                raise CodexCliError("cli_version_unsupported")
        except OSError as exc:
            raise CodexCliError("cli_missing") from exc

        return (
            CodexCliPreflight(
                cli_version=profile.cli_version,
                authentication_status="logged_in",
                output_schema_supported=profile.output_schema_supported,
                safe_profile_ref=profile.profile_ref,
            ),
            safe_catalog,
            cli_path,
            cli_identity,
        )

    @staticmethod
    def _sanitize_model_catalog(raw: bytes, *, model: str) -> bytes:
        try:
            catalog = json.loads(
                raw.decode("utf-8", errors="strict"),
                object_pairs_hook=_unique_json_object,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
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
            if (
                not isinstance(descriptor, dict)
                or "slug" not in descriptor
                or not set(descriptor).issubset(_MODEL_DESCRIPTOR_KEYS)
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
                    "node_repl_auto_review_required": False,
                    "node_repl_disabled": True,
                    "shell_type": "disabled",
                    "supports_search_tool": False,
                    "tool_mode": None,
                    "web_search_tool_type": None,
                }
            )
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

        preflight, safe_catalog, cli_path, cli_identity = self._preflight(model=model)

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
                output_path=output_path,
                model_catalog_path=model_catalog_path,
                output_schema_path=(root / "output.schema.json")
                if output_schema is not None and preflight.output_schema_supported
                else None,
            )
            schema_path = root / "output.schema.json"
            if output_schema is not None and preflight.output_schema_supported:
                schema_path.write_text(
                    json.dumps(output_schema, ensure_ascii=False, sort_keys=True),
                    encoding="utf-8",
                )
            env = self._child_environment(temp_root=root)
            try:
                result = self._run_bounded(
                    argv,
                    cwd=workdir,
                    input_text=user_prompt,
                    timeout_seconds=self._execution_timeout_seconds,
                    environment=env,
                    expected_executable_identity=cli_identity,
                )
            except CodexCliError:
                raise
            if result.returncode != 0:
                error_for_auth = result.stderr.decode(
                    "utf-8", errors="replace"
                )
                if any(
                    marker in error_for_auth.lower()
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
            if output_schema is not None:
                try:
                    payload = json.loads(
                        response_text,
                        object_pairs_hook=_unique_json_object,
                    )
                    validate_schema_payload(output_schema_ref or "", output_schema, payload)
                except (json.JSONDecodeError, UnicodeError, ValueError) as exc:
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
    ) -> subprocess.CompletedProcess[bytes]:
        input_bytes = None if input_text is None else input_text.encode("utf-8")
        if input_bytes is not None and len(input_bytes) > self._max_input_bytes:
            raise CodexCliError("input_oversize")
        stdin_context = tempfile.TemporaryFile()
        process: subprocess.Popen[bytes] | None = None
        selector = selectors.DefaultSelector()
        started = time.monotonic()
        stdout = bytearray()
        stderr = bytearray()
        output_limit = self._max_output_bytes if max_output_bytes is None else max_output_bytes
        try:
            stdin_source: int | IO[bytes]
            if input_bytes is not None:
                stdin_context.write(input_bytes)
                stdin_context.seek(0)
                stdin_source = stdin_context
            else:
                stdin_source = subprocess.DEVNULL
            try:
                if expected_executable_identity is not None:
                    try:
                        current_identity = _executable_identity(Path(argv[0]))
                    except OSError as exc:
                        raise CodexCliError("cli_missing") from exc
                    if current_identity != expected_executable_identity:
                        raise CodexCliError("cli_version_unsupported")
                process = subprocess.Popen(
                    argv,
                    cwd=cwd,
                    stdin=stdin_source,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=dict(environment) if environment is not None else self._child_environment(
                        temp_root=Path(tempfile.gettempdir())
                    ),
                    shell=False,
                    start_new_session=self._process_group_mode == "isolated",
                )
            except FileNotFoundError as exc:
                raise CodexCliError("cli_missing") from exc
            assert process.stdout is not None and process.stderr is not None
            os.set_blocking(process.stdout.fileno(), False)
            os.set_blocking(process.stderr.fileno(), False)
            selector.register(process.stdout, selectors.EVENT_READ, "stdout")
            selector.register(process.stderr, selectors.EVENT_READ, "stderr")
            while selector.get_map():
                remaining = timeout_seconds - (time.monotonic() - started)
                if remaining <= 0:
                    self._terminate(process)
                    raise CodexCliError("command_timeout")
                for key, _ in selector.select(min(remaining, 0.1)):
                    chunk = os.read(key.fd, 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    target = stdout if key.data == "stdout" else stderr
                    target.extend(chunk)
                    if len(stdout) + len(stderr) > output_limit:
                        self._terminate(process)
                        raise CodexCliError("stdout_oversize")
            remaining = timeout_seconds - (time.monotonic() - started)
            if remaining <= 0:
                self._terminate(process)
                raise CodexCliError("command_timeout")
            return_code = process.wait(timeout=remaining)
            return subprocess.CompletedProcess(argv, return_code, bytes(stdout), bytes(stderr))
        except subprocess.TimeoutExpired as exc:
            if process is not None:
                self._terminate(process)
            raise CodexCliError("command_timeout") from exc
        finally:
            selector.close()
            if process is not None:
                for stream in (process.stdout, process.stderr):
                    if stream is not None:
                        stream.close()
                if process.poll() is None:
                    self._terminate(process)
            stdin_context.close()

    def _terminate(self, process: subprocess.Popen[bytes]) -> None:
        if self._process_group_mode == "isolated":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except PermissionError:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
        else:
            try:
                process.terminate()
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
