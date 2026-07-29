"""Explicit, secret-safe adapter boundary for BuilderOps model turns."""

from __future__ import annotations

import json
import os
import selectors
import signal
import subprocess
import sys
import tempfile
import time
from ctypes import CDLL, Structure, byref, c_char, c_int32, c_uint32, c_uint64, sizeof
from dataclasses import dataclass
from typing import Any, Mapping, Never

import requests  # type: ignore[import-untyped]  # third-party lib ships no type stubs

from app.builderops.model_access_resolver import (
    BuilderModelAccessResolver,
    DeclaredCredentialUnavailableError,
    ModelAccessResolutionError,
)
from app.builderops.model_inquiry_contract import canonical_hash, canonical_json
from app.builderops.models import BuilderOpsValidationError
from llm_contract import (
    ADAPTER_FAILURE_CLASSES,
    AdapterResult,
    ModelAccessIntent,
    ModelResolutionRequest,
    ModelTurnAdapter,
    ResolvedModelAccess,
    validate_adapter_failure_class,
)

INQUIRY_INTENT_CONFIG_ENV = "BUILDEROPS_INQUIRY_ROLE_INTENT_JSON"
INQUIRY_INTENT_SCHEMA = "builderops.model-inquiry-role-intent.v1"
ROLE_NAMES = ("fable", "gpt_codex")
SUBSCRIPTION_ADAPTER_TIMEOUT_EXIT_CODE = 124
SUBSCRIPTION_ADAPTER_SESSION_EXPIRED_EXIT_CODE = 125
CLEANUP_TIMEOUT_SECONDS = 2.0
HTTP_ADAPTER_KIND = "http"

# Conventional exit codes the still-permitted interactive command path uses to
# report the real cause. Without them an expired session and a genuine command
# failure collapse into one indistinguishable class.
_LOCAL_COMMAND_FAILURE_CLASSES = {
    SUBSCRIPTION_ADAPTER_TIMEOUT_EXIT_CODE: "command_timeout",
    SUBSCRIPTION_ADAPTER_SESSION_EXPIRED_EXIT_CODE: "session_expired",
}

# The intent surface is provider-free by construction: any key that could carry
# a provider, model, transport target, credential value, environment-variable
# name, or host reference is refused before resolution runs.
FORBIDDEN_INTENT_KEYS = frozenset(
    {
        "adapter_id",
        "api_key",
        "api_key_env",
        "argv",
        "command",
        "credential",
        "credential_value",
        "endpoint",
        "environment_allowlist",
        "host",
        "hostname",
        "kind",
        "model",
        "provider",
        "url",
    }
)
_INTENT_FIELDS = frozenset(
    {
        "capability_tier",
        "reasoning_effort",
        "determinism_required",
        "output_schema_ref",
        "independence",
        "fallback_requirement",
        "side_effect_class",
    }
)
_CONFIG_FIELDS = frozenset({"schema", "runtime", "channel", "consumer", "resolution_group_id", "roles"})


class AdapterUnavailableError(RuntimeError):
    pass


class AdapterExecutionError(RuntimeError):
    """An adapter failure carrying only safe, allowlisted diagnostic metadata."""

    def __init__(
        self,
        message: str,
        *,
        failure_class: str = "unexpected_adapter_error",
        exit_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.failure_class = validate_adapter_failure_class(failure_class)
        self.exit_code = (
            exit_code
            if isinstance(exit_code, int) and not isinstance(exit_code, bool) and 1 <= exit_code <= 255
            else None
        )


class CredentialUnavailableError(AdapterExecutionError):
    """A declared credential is absent or unusable; it names only the logical id."""

    def __init__(self, *, adapter_id: str, credential_identity_ref: str) -> None:
        super().__init__(
            f"declared credential unavailable: {credential_identity_ref}",
            failure_class="credential_unavailable",
        )
        self.adapter_id = adapter_id
        self.credential_identity_ref = credential_identity_ref


@dataclass
class ScriptedAdapter:
    """Injected deterministic adapter for tests; never selected by environment fallback."""

    adapter_id: str
    provider: str
    model: str
    responses: list[str]
    calls: list[dict[str, Any]]

    def execute(self, request: Mapping[str, Any]) -> AdapterResult:
        self.calls.append(dict(request))
        if not self.responses:
            raise AdapterExecutionError(f"scripted adapter exhausted: {self.adapter_id}")
        index = len(self.calls) - 1
        return AdapterResult(
            response_text=self.responses.pop(0),
            provider_request_id=f"scripted-{self.adapter_id}-{index}",
        )


@dataclass(frozen=True)
class LocalCommandAdapter:
    adapter_id: str
    provider: str
    model: str
    argv: tuple[str, ...]
    timeout_seconds: float = 60.0
    max_output_bytes: int = 1_000_000
    environment: Mapping[str, str] | None = None

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise BuilderOpsValidationError("local command timeout_seconds must be positive")
        if self.max_output_bytes < 1:
            raise BuilderOpsValidationError("local command max_output_bytes must be positive")

    def execute(self, request: Mapping[str, Any]) -> AdapterResult:
        if not self.argv or not self.argv[0].strip():
            raise AdapterUnavailableError(f"local command unavailable: {self.adapter_id}")
        env = {"PATH": os.environ.get("PATH", "")}
        if self.environment:
            env.update({str(key): str(value) for key, value in self.environment.items()})
        try:
            with tempfile.TemporaryFile() as request_file:
                request_file.write(canonical_json(request).encode("utf-8"))
                request_file.seek(0)
                process = subprocess.Popen(
                    list(self.argv),
                    stdin=request_file,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    shell=False,
                    env=env,
                    start_new_session=True,
                )
                stdout = _read_bounded_process_output(
                    process,
                    timeout_seconds=self.timeout_seconds,
                    max_output_bytes=self.max_output_bytes,
                    adapter_id=self.adapter_id,
                )
        except FileNotFoundError as exc:
            raise AdapterUnavailableError(f"local command unavailable: {self.adapter_id}") from exc
        if process.returncode != 0:
            raise AdapterExecutionError(
                f"local command failed with exit {process.returncode}: {self.adapter_id}",
                failure_class=_LOCAL_COMMAND_FAILURE_CLASSES.get(
                    process.returncode, "command_exit_nonzero"
                ),
                exit_code=process.returncode,
            )
        text = stdout.decode("utf-8", errors="replace").strip()
        if not text:
            raise AdapterExecutionError(
                f"local command returned empty output: {self.adapter_id}",
                failure_class="stdout_empty",
            )
        if self.environment and any(
            value and value in text for value in self.environment.values()
        ):
            raise AdapterExecutionError(
                f"local command output contained an allowed environment value: {self.adapter_id}",
                failure_class="output_contains_allowed_environment",
            )
        return AdapterResult(response_text=text)


@dataclass(frozen=True)
class HttpModelAdapter:
    adapter_id: str
    provider: str
    model: str
    endpoint: str
    api_key: str
    intent: ModelAccessIntent
    timeout_seconds: float = 60.0

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise BuilderOpsValidationError("HTTP adapter timeout_seconds must be positive")
        if self.intent.reasoning_effort != "xhigh":
            raise BuilderOpsValidationError("HTTP adapter requires xhigh reasoning effort")
        if self.intent.determinism_required:
            raise BuilderOpsValidationError(
                "HTTP adapter refuses deterministic Model Inquiry execution"
            )
        if self.intent.output_schema_ref != "builderops.model-turn-response.v1":
            raise BuilderOpsValidationError(
                "HTTP adapter requires the declared Model Inquiry response schema"
            )
        if self.intent.side_effect_class != "advisory_review":
            raise BuilderOpsValidationError("HTTP adapter permits advisory review only")

    def execute(self, request: Mapping[str, Any]) -> AdapterResult:
        if not self.endpoint or not self.api_key:
            raise AdapterUnavailableError(f"HTTP adapter unavailable: {self.adapter_id}")
        if self.provider == "anthropic":
            return self._execute_anthropic(request)
        return self._execute_openai(request)

    def _execute_openai(self, request: Mapping[str, Any]) -> AdapterResult:
        try:
            response = requests.post(
                self.endpoint,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": str(request["system_prompt"])},
                        {"role": "user", "content": canonical_json(request)},
                    ],
                    "response_format": {"type": "json_object"},
                    "reasoning_effort": self.intent.reasoning_effort,
                },
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
        except requests.Timeout as exc:
            raise AdapterExecutionError(f"HTTP adapter timed out: {self.adapter_id}") from exc
        except requests.RequestException as exc:
            raise AdapterExecutionError(f"HTTP adapter request failed: {self.adapter_id}") from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise AdapterExecutionError("OpenAI-compatible response was not JSON") from exc
        try:
            text = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AdapterExecutionError("OpenAI-compatible response omitted content") from exc
        request_id = response.headers.get("x-request-id") or payload.get("id")
        if self.api_key in str(text):
            raise AdapterExecutionError(f"HTTP adapter output contained credential: {self.adapter_id}")
        if request_id and self.api_key in str(request_id):
            raise AdapterExecutionError(
                f"HTTP adapter request ID contained credential: {self.adapter_id}"
            )
        return AdapterResult(str(text), str(request_id) if request_id else None)

    def _execute_anthropic(self, request: Mapping[str, Any]) -> AdapterResult:
        try:
            response = requests.post(
                self.endpoint,
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "max_tokens": 4096,
                    "system": str(request["system_prompt"]),
                    "messages": [{"role": "user", "content": canonical_json(request)}],
                    "output_config": {"effort": self.intent.reasoning_effort},
                },
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
        except requests.Timeout as exc:
            raise AdapterExecutionError(f"HTTP adapter timed out: {self.adapter_id}") from exc
        except requests.RequestException as exc:
            raise AdapterExecutionError(f"HTTP adapter request failed: {self.adapter_id}") from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise AdapterExecutionError("Anthropic response was not JSON") from exc
        try:
            text = "".join(
                str(block["text"])
                for block in payload["content"]
                if isinstance(block, dict) and block.get("type") == "text"
            )
        except (KeyError, TypeError) as exc:
            raise AdapterExecutionError("Anthropic response omitted content") from exc
        if not text.strip():
            raise AdapterExecutionError("Anthropic response returned empty content")
        if self.api_key in text:
            raise AdapterExecutionError(f"HTTP adapter output contained credential: {self.adapter_id}")
        request_id = response.headers.get("request-id") or payload.get("id")
        if request_id and self.api_key in str(request_id):
            raise AdapterExecutionError(
                f"HTTP adapter request ID contained credential: {self.adapter_id}"
            )
        return AdapterResult(text, str(request_id) if request_id else None)


@dataclass(frozen=True)
class InquiryRoleIntentConfig:
    """One parsed, provider-free inquiry-role intent configuration."""

    runtime: str
    channel: str
    consumer: str
    resolution_group_id: str
    requests: tuple[ModelResolutionRequest, ...]


def load_inquiry_intent(
    env: Mapping[str, str] | None = None,
) -> InquiryRoleIntentConfig | None:
    """Parse the value-free inquiry-role intent configuration, or return None.

    The configuration declares only the seven neutral intent fields per role,
    the role independence requirement, and channel/consumer references. Provider,
    model, transport target, credential value, environment-variable name, and
    host references are structurally refused here, before any resolution runs.
    """
    source = dict(os.environ if env is None else env)
    raw = source.get(INQUIRY_INTENT_CONFIG_ENV, "").strip()
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BuilderOpsValidationError(
            f"{INQUIRY_INTENT_CONFIG_ENV} must be valid JSON"
        ) from exc
    return parse_inquiry_intent(payload)


def parse_inquiry_intent(payload: Any) -> InquiryRoleIntentConfig:
    """Validate one inquiry-role intent document into neutral resolution requests."""
    if not isinstance(payload, dict):
        raise BuilderOpsValidationError(
            f"{INQUIRY_INTENT_CONFIG_ENV} must be a JSON object"
        )
    _reject_forbidden_intent_keys(payload)
    if set(payload) != _CONFIG_FIELDS:
        raise BuilderOpsValidationError("inquiry role intent fields are invalid")
    if payload["schema"] != INQUIRY_INTENT_SCHEMA:
        raise BuilderOpsValidationError("inquiry role intent schema is unsupported")
    roles = payload["roles"]
    if not isinstance(roles, dict) or set(roles) != set(ROLE_NAMES):
        raise BuilderOpsValidationError(
            "inquiry role intent must declare exactly the independent review roles"
        )
    group_id = str(payload["resolution_group_id"])
    requests: list[ModelResolutionRequest] = []
    for role in ROLE_NAMES:
        intent_payload = roles[role]
        if not isinstance(intent_payload, dict) or set(intent_payload) != _INTENT_FIELDS:
            raise BuilderOpsValidationError(
                f"inquiry role intent for {role} must declare exactly the neutral fields"
            )
        try:
            intent = ModelAccessIntent(**intent_payload)
            requests.append(
                ModelResolutionRequest(
                    intent=intent,
                    role_profile=role,
                    resolution_group_id=group_id,
                )
            )
        except ValueError as exc:
            raise BuilderOpsValidationError(
                f"inquiry role intent for {role} is not a valid neutral intent"
            ) from exc
    return InquiryRoleIntentConfig(
        runtime=str(payload["runtime"]),
        channel=str(payload["channel"]),
        consumer=str(payload["consumer"]),
        resolution_group_id=group_id,
        requests=tuple(requests),
    )


def _reject_forbidden_intent_keys(value: Any) -> None:
    if isinstance(value, Mapping):
        forbidden = sorted(FORBIDDEN_INTENT_KEYS.intersection(str(key).lower() for key in value))
        if forbidden:
            raise BuilderOpsValidationError(
                "inquiry role intent must not declare provider, model, transport, "
                f"credential, or host fields: {', '.join(forbidden)}"
            )
        for nested in value.values():
            _reject_forbidden_intent_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            _reject_forbidden_intent_keys(nested)


def resolve_inquiry_roles(
    env: Mapping[str, str] | None = None,
    *,
    resolver: BuilderModelAccessResolver | None = None,
) -> tuple[BuilderModelAccessResolver, dict[str, ResolvedModelAccess]]:
    """Resolve both inquiry roles as one group through Builder census policy."""
    source = dict(os.environ if env is None else env)
    config = load_inquiry_intent(source)
    if config is None:
        raise AdapterUnavailableError("inquiry role intent is not configured")
    selected = resolver or BuilderModelAccessResolver.from_declared_sources(env=source)
    resolutions = selected.resolve_group(
        config.requests,
        runtime=config.runtime,
        channel=config.channel,
        consumer=config.consumer,
    )
    return selected, {
        resolution.request.role_profile: resolution for resolution in resolutions
    }


def load_adapter_descriptors(
    env: Mapping[str, str] | None = None,
    *,
    resolver: BuilderModelAccessResolver | None = None,
) -> dict[str, dict[str, Any]]:
    """Project the resolved role targets into sanitized, value-free descriptors."""
    source = dict(os.environ if env is None else env)
    try:
        selected, resolutions = resolve_inquiry_roles(source, resolver=resolver)
    except AdapterUnavailableError:
        return {
            role: {"role": role, "available": False, "reason": "inquiry role intent not configured"}
            for role in ROLE_NAMES
        }
    except ModelAccessResolutionError as exc:
        return {
            role: {"role": role, "available": False, "reason": str(exc)}
            for role in ROLE_NAMES
        }
    descriptors: dict[str, dict[str, Any]] = {}
    for role in ROLE_NAMES:
        resolution = resolutions[role]
        try:
            endpoint = selected.endpoint_for(resolution)
        except ModelAccessResolutionError as exc:
            descriptors[role] = {"role": role, "available": False, "reason": str(exc)}
            continue
        descriptors[role] = {
            "role": role,
            "available": True,
            "role_identity": resolution.request.role_profile,
            "kind": HTTP_ADAPTER_KIND,
            "adapter_id": resolution.adapter_id,
            "provider": resolution.provider,
            "model": resolution.model,
            "credential_identity_ref": resolution.credential_identity_ref,
            "target_fingerprint": canonical_hash(
                {
                    "kind": HTTP_ADAPTER_KIND,
                    "provider": resolution.provider,
                    "model": resolution.model,
                    "target": endpoint,
                }
            ),
        }
        if descriptors[role]["role_identity"] != role:
            descriptors[role]["available"] = False
            descriptors[role]["reason"] = f"role_identity must explicitly attest {role}"
        if str(descriptors[role]["provider"]).lower() in {"mock", "fake", "deterministic"}:
            descriptors[role]["available"] = False
            descriptors[role]["reason"] = "provider-enabled roles cannot use a mock identity"
    available_ids = [
        str(descriptors[role].get("adapter_id"))
        for role in ROLE_NAMES
        if descriptors[role].get("available")
    ]
    if len(available_ids) != len(set(available_ids)):
        for role in ROLE_NAMES:
            descriptors[role]["available"] = False
            descriptors[role]["reason"] = "role adapters must use distinct adapter_id values"
    fingerprints = [
        str(descriptors[role].get("target_fingerprint"))
        for role in ROLE_NAMES
        if descriptors[role].get("available")
    ]
    if len(fingerprints) != len(set(fingerprints)):
        for role in ROLE_NAMES:
            descriptors[role]["available"] = False
            descriptors[role]["reason"] = "role adapters must use distinct runtime targets"
    return descriptors


def load_adapters(
    env: Mapping[str, str] | None = None,
    *,
    resolver: BuilderModelAccessResolver | None = None,
) -> dict[str, ModelTurnAdapter]:
    """Build provider-API adapters with credentials injected at descriptor load.

    Every identity is a resolver output and every credential is resolved through
    the host secret contract. No provider key is read from caller configuration
    or ambient process environment, and no missing credential falls back to a
    subscription CLI, another provider, or a mock identity.
    """
    source = dict(os.environ if env is None else env)
    selected, resolutions = resolve_inquiry_roles(source, resolver=resolver)
    descriptors = load_adapter_descriptors(source, resolver=selected)
    adapters: dict[str, ModelTurnAdapter] = {}
    for role in ROLE_NAMES:
        descriptor = descriptors[role]
        if not descriptor.get("available"):
            raise AdapterUnavailableError(
                f"{role}: {descriptor.get('reason', 'adapter unavailable')}"
            )
        resolution = resolutions[role]
        try:
            api_key = selected.credential_value(resolution)
        except DeclaredCredentialUnavailableError as exc:
            raise CredentialUnavailableError(
                adapter_id=resolution.adapter_id,
                credential_identity_ref=exc.credential_identity_ref,
            ) from None
        adapters[role] = HttpModelAdapter(
            adapter_id=resolution.adapter_id,
            provider=resolution.provider,
            model=resolution.model,
            endpoint=selected.endpoint_for(resolution),
            api_key=api_key,
            intent=resolution.request.intent,
        )
    return adapters


def sanitized_adapter_identity(adapter: ModelTurnAdapter) -> dict[str, str]:
    return {
        "adapter_id": adapter.adapter_id,
        "provider": adapter.provider,
        "model": adapter.model,
    }


def sanitized_adapter_failure(error: Exception, *, adapter_id: str) -> dict[str, str | int]:
    """Project an exception into the only adapter diagnostic that receipts may retain."""
    failure_class = "unexpected_adapter_error"
    exit_code: int | None = None
    if isinstance(error, AdapterExecutionError):
        failure_class = error.failure_class
        exit_code = error.exit_code
    result: dict[str, str | int] = {
        "adapter_id": adapter_id,
        "adapter_failure_class": failure_class,
    }
    if exit_code is not None:
        result["adapter_exit_code"] = exit_code
    if isinstance(error, CredentialUnavailableError):
        # The logical identifier only. It is declared, value-free data from the
        # host secret contract and is the whole point of this failure class.
        result["credential_identity_ref"] = error.credential_identity_ref
    return result


def _read_bounded_process_output(
    process: subprocess.Popen[bytes],
    *,
    timeout_seconds: float,
    max_output_bytes: int,
    adapter_id: str,
) -> bytes:
    if process.stdout is None:
        cleanup_denied = _kill_process_group(process)
        _raise_local_command_failure(
            f"local command stdout unavailable: {adapter_id}",
            failure_class="stdout_unavailable",
            cleanup_denied=cleanup_denied,
        )
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    deadline = time.monotonic() + timeout_seconds
    chunks: list[bytes] = []
    size = 0
    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                cleanup_denied = _kill_process_group(process)
                _raise_local_command_failure(
                    f"local command timed out: {adapter_id}",
                    failure_class="command_timeout",
                    cleanup_denied=cleanup_denied,
                )
            events = selector.select(min(remaining, 0.1))
            if not events and process.poll() is not None:
                events = [(next(iter(selector.get_map().values())), selectors.EVENT_READ)]
            for key, _ in events:
                chunk = os.read(key.fd, min(65_536, max_output_bytes - size + 1))
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                size += len(chunk)
                if size > max_output_bytes:
                    cleanup_denied = _kill_process_group(process)
                    _raise_local_command_failure(
                        f"local command output exceeded limit: {adapter_id}",
                        failure_class="stdout_oversize",
                        cleanup_denied=cleanup_denied,
                    )
                chunks.append(chunk)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            cleanup_denied = _kill_process_group(process)
            _raise_local_command_failure(
                f"local command timed out: {adapter_id}",
                failure_class="command_timeout",
                cleanup_denied=cleanup_denied,
            )
        process.wait(timeout=remaining)
        return b"".join(chunks)
    except subprocess.TimeoutExpired:
        cleanup_denied = _kill_process_group(process)
        _raise_local_command_failure(
            f"local command timed out: {adapter_id}",
            failure_class="command_timeout",
            cleanup_denied=cleanup_denied,
        )
    finally:
        selector.close()


def _raise_local_command_failure(
    message: str,
    *,
    failure_class: str,
    cleanup_denied: bool,
) -> Never:
    if cleanup_denied:
        message += "; process-group cleanup denied"
    raise AdapterExecutionError(message, failure_class=failure_class) from None


def _kill_process_group(process: subprocess.Popen[bytes]) -> bool:
    """Boundedly terminate a command tree; return whether group signaling was denied."""
    if process.poll() is not None:
        return False
    deadline = time.monotonic() + CLEANUP_TIMEOUT_SECONDS
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return False
    except PermissionError:
        descendants = _descendant_process_identities(process.pid, deadline=deadline)
        for pid, identity in reversed(descendants):
            if time.monotonic() >= deadline:
                break
            current_identity = _kernel_process_identity(pid)
            if time.monotonic() >= deadline:
                break
            if current_identity != identity:
                continue
            try:
                os.kill(pid, signal.SIGKILL)
            except (PermissionError, ProcessLookupError):
                pass
        try:
            process.kill()
        except (PermissionError, ProcessLookupError):
            pass
        _bounded_wait(process, deadline=deadline)
        return True
    _bounded_wait(process, deadline=deadline)
    return False


def _bounded_wait(process: subprocess.Popen[bytes], *, deadline: float) -> None:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return
    try:
        process.wait(timeout=remaining)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
        except (PermissionError, ProcessLookupError):
            return
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        try:
            process.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            return


def _descendant_process_identities(
    root_pid: int,
    *,
    deadline: float,
) -> list[tuple[int, tuple[int, int, int]]]:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return []
    try:
        result = subprocess.run(
            ["ps", "-axo", "pid=,ppid="],
            check=False,
            capture_output=True,
            text=True,
            timeout=remaining,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    children: dict[int, list[int]] = {}
    for line in result.stdout.splitlines():
        try:
            pid_text, parent_text = line.split()
            pid, parent = int(pid_text), int(parent_text)
        except (ValueError, TypeError):
            continue
        children.setdefault(parent, []).append(pid)
    descendant_candidates: list[tuple[int, int]] = []
    pending = [(pid, root_pid) for pid in children.get(root_pid, ())]
    while pending:
        pid, captured_parent = pending.pop()
        descendant_candidates.append((pid, captured_parent))
        pending.extend((child, pid) for child in children.get(pid, ()))
    descendants: list[tuple[int, tuple[int, int, int]]] = []
    for pid, captured_parent in descendant_candidates:
        if time.monotonic() >= deadline:
            break
        identity = _kernel_process_identity(pid)
        if identity is not None and identity[0] == captured_parent:
            descendants.append((pid, identity))
    return descendants


def _kernel_process_identity(pid: int) -> tuple[int, int, int] | None:
    if sys.platform.startswith("linux"):
        try:
            with open(f"/proc/{pid}/stat", "rb") as stat_file:
                stat = stat_file.read()
            fields = stat[stat.rfind(b")") + 2 :].split()
            return (int(fields[1]), int(fields[19]), 0)
        except (OSError, IndexError, ValueError):
            return None
    if sys.platform == "darwin":
        return _darwin_process_identity(pid)
    return None


class _DarwinProcBSDInfo(Structure):
    _fields_ = [
        ("flags", c_uint32),
        ("status", c_uint32),
        ("xstatus", c_uint32),
        ("pid", c_uint32),
        ("ppid", c_uint32),
        ("uid", c_uint32),
        ("gid", c_uint32),
        ("ruid", c_uint32),
        ("rgid", c_uint32),
        ("svuid", c_uint32),
        ("svgid", c_uint32),
        ("rfu_1", c_uint32),
        ("comm", c_char * 16),
        ("name", c_char * 32),
        ("nfiles", c_uint32),
        ("pgid", c_uint32),
        ("pjobc", c_uint32),
        ("tdev", c_uint32),
        ("tpgid", c_uint32),
        ("nice", c_int32),
        ("start_tvsec", c_uint64),
        ("start_tvusec", c_uint64),
    ]


def _darwin_process_identity(pid: int) -> tuple[int, int, int] | None:
    try:
        libproc = CDLL("/usr/lib/libproc.dylib")
        info = _DarwinProcBSDInfo()
        read_size = libproc.proc_pidinfo(pid, 3, 0, byref(info), sizeof(info))
    except OSError:
        return None
    if read_size != sizeof(info):
        return None
    return (int(info.ppid), int(info.start_tvsec), int(info.start_tvusec))


def adapter_request_id(request: Mapping[str, Any]) -> str:
    return f"adapter_req_{canonical_hash(request)[:32]}"


__all__ = [
    "ADAPTER_FAILURE_CLASSES",
    "INQUIRY_INTENT_CONFIG_ENV",
    "INQUIRY_INTENT_SCHEMA",
    "AdapterExecutionError",
    "AdapterResult",
    "AdapterUnavailableError",
    "CredentialUnavailableError",
    "HttpModelAdapter",
    "InquiryRoleIntentConfig",
    "LocalCommandAdapter",
    "ModelTurnAdapter",
    "ScriptedAdapter",
    "adapter_request_id",
    "sanitized_adapter_failure",
    "load_adapter_descriptors",
    "load_adapters",
    "load_inquiry_intent",
    "parse_inquiry_intent",
    "resolve_inquiry_roles",
    "sanitized_adapter_identity",
]
