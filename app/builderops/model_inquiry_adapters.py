"""Explicit, secret-safe adapter boundary for BuilderOps model turns."""

from __future__ import annotations

import json
import os
import selectors
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

import requests  # type: ignore[import-untyped]  # third-party lib ships no type stubs

from app.builderops.model_inquiry_contract import canonical_hash, canonical_json
from app.builderops.models import BuilderOpsValidationError

ADAPTER_CONFIG_ENV = "BUILDEROPS_INQUIRY_ADAPTERS_JSON"
ROLE_NAMES = ("fable", "gpt_codex")
SUBSCRIPTION_ADAPTER_TIMEOUT_EXIT_CODE = 124
ADAPTER_FAILURE_CLASSES = frozenset(
    {
        "command_exit_nonzero",
        "command_timeout",
        "stdout_empty",
        "stdout_oversize",
        "stdout_unavailable",
        "output_contains_allowed_environment",
        "unexpected_adapter_error",
    }
)


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
        self.failure_class = (
            failure_class
            if failure_class in ADAPTER_FAILURE_CLASSES
            else "unexpected_adapter_error"
        )
        self.exit_code = (
            exit_code
            if isinstance(exit_code, int) and not isinstance(exit_code, bool) and 1 <= exit_code <= 255
            else None
        )


@dataclass(frozen=True)
class AdapterResult:
    response_text: str
    provider_request_id: str | None = None


class ModelTurnAdapter(Protocol):
    @property
    def adapter_id(self) -> str: ...

    @property
    def provider(self) -> str: ...

    @property
    def model(self) -> str: ...

    def execute(self, request: Mapping[str, Any]) -> AdapterResult: ...


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
                failure_class=(
                    "command_timeout"
                    if process.returncode == SUBSCRIPTION_ADAPTER_TIMEOUT_EXIT_CODE
                    else "command_exit_nonzero"
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
    timeout_seconds: float = 60.0

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise BuilderOpsValidationError("HTTP adapter timeout_seconds must be positive")

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


def load_adapter_descriptors(env: Mapping[str, str] | None = None) -> dict[str, dict[str, Any]]:
    source = dict(os.environ if env is None else env)
    raw = source.get(ADAPTER_CONFIG_ENV, "").strip()
    if not raw:
        return {
            role: {"role": role, "available": False, "reason": "explicit adapter not configured"}
            for role in ROLE_NAMES
        }
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BuilderOpsValidationError(f"{ADAPTER_CONFIG_ENV} must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise BuilderOpsValidationError(f"{ADAPTER_CONFIG_ENV} must be a JSON object")
    descriptors: dict[str, dict[str, Any]] = {}
    for role in ROLE_NAMES:
        config = payload.get(role)
        if not isinstance(config, dict):
            descriptors[role] = {
                "role": role,
                "available": False,
                "reason": "explicit adapter not configured",
            }
            continue
        kind = str(config.get("kind", "")).strip().lower()
        descriptors[role] = {
            "role": role,
            "available": kind in {"command", "openai", "anthropic"},
            "role_identity": str(config.get("role_identity", "")).strip(),
            "kind": kind,
            "adapter_id": str(config.get("adapter_id", "")).strip(),
            "provider": str(config.get("provider", "")).strip(),
            "model": str(config.get("model", "")).strip(),
            "target_fingerprint": canonical_hash(
                {
                    "kind": kind,
                    "provider": str(config.get("provider", "")).strip(),
                    "model": str(config.get("model", "")).strip(),
                    "target": config.get("argv") if kind == "command" else config.get("endpoint"),
                }
            ),
        }
        if not all(descriptors[role].get(key) for key in ("adapter_id", "provider", "model")):
            descriptors[role]["available"] = False
            descriptors[role]["reason"] = "adapter identity is incomplete"
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


def load_adapters(env: Mapping[str, str] | None = None) -> dict[str, ModelTurnAdapter]:
    source = dict(os.environ if env is None else env)
    descriptors = load_adapter_descriptors(source)
    raw = source.get(ADAPTER_CONFIG_ENV, "").strip()
    payload = json.loads(raw) if raw else {}
    adapters: dict[str, ModelTurnAdapter] = {}
    for role in ROLE_NAMES:
        descriptor = descriptors[role]
        if not descriptor.get("available"):
            raise AdapterUnavailableError(f"{role}: {descriptor.get('reason', 'adapter unavailable')}")
        config = payload[role]
        common = {
            "adapter_id": descriptor["adapter_id"],
            "provider": descriptor["provider"],
            "model": descriptor["model"],
        }
        kind = descriptor["kind"]
        if kind == "command":
            argv = config.get("argv")
            if not isinstance(argv, list) or not all(isinstance(item, str) for item in argv):
                raise BuilderOpsValidationError(f"{role} command argv must be a list of strings")
            allow_names = config.get("environment_allowlist", [])
            if not isinstance(allow_names, list) or not all(
                isinstance(item, str) for item in allow_names
            ):
                raise BuilderOpsValidationError(f"{role} environment_allowlist is invalid")
            adapters[role] = LocalCommandAdapter(
                **common,
                argv=tuple(argv),
                timeout_seconds=_positive_float(config.get("timeout_seconds", 60), role, "timeout_seconds"),
                max_output_bytes=_positive_int(
                    config.get("max_output_bytes", 1_000_000), role, "max_output_bytes"
                ),
                environment={name: source[name] for name in allow_names if name in source},
            )
        else:
            key_env = str(config.get("api_key_env", "")).strip()
            endpoint = str(config.get("endpoint", "")).strip()
            api_key = source.get(key_env, "") if key_env else ""
            if not endpoint or not api_key:
                raise AdapterUnavailableError(f"{role}: HTTP endpoint or API key unavailable")
            adapters[role] = HttpModelAdapter(
                **common,
                endpoint=endpoint,
                api_key=api_key,
                timeout_seconds=_positive_float(config.get("timeout_seconds", 60), role, "timeout_seconds"),
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
    return result


def _positive_float(value: Any, role: str, field: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise BuilderOpsValidationError(f"{role} {field} must be numeric") from exc
    if parsed <= 0:
        raise BuilderOpsValidationError(f"{role} {field} must be positive")
    return parsed


def _positive_int(value: Any, role: str, field: str) -> int:
    if isinstance(value, bool):
        raise BuilderOpsValidationError(f"{role} {field} must be an integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise BuilderOpsValidationError(f"{role} {field} must be an integer") from exc
    if parsed <= 0:
        raise BuilderOpsValidationError(f"{role} {field} must be positive")
    return parsed


def _read_bounded_process_output(
    process: subprocess.Popen[bytes],
    *,
    timeout_seconds: float,
    max_output_bytes: int,
    adapter_id: str,
) -> bytes:
    if process.stdout is None:
        _kill_process_group(process, adapter_id=adapter_id)
        raise AdapterExecutionError(
            f"local command stdout unavailable: {adapter_id}",
            failure_class="stdout_unavailable",
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
                _kill_process_group(process, adapter_id=adapter_id)
                raise AdapterExecutionError(
                    f"local command timed out: {adapter_id}",
                    failure_class="command_timeout",
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
                    _kill_process_group(process, adapter_id=adapter_id)
                    raise AdapterExecutionError(
                        f"local command output exceeded limit: {adapter_id}",
                        failure_class="stdout_oversize",
                    )
                chunks.append(chunk)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            _kill_process_group(process, adapter_id=adapter_id)
            raise AdapterExecutionError(
                f"local command timed out: {adapter_id}",
                failure_class="command_timeout",
            )
        process.wait(timeout=remaining)
        return b"".join(chunks)
    except subprocess.TimeoutExpired as exc:
        _kill_process_group(process, adapter_id=adapter_id)
        raise AdapterExecutionError(
            f"local command timed out: {adapter_id}",
            failure_class="command_timeout",
        ) from exc
    finally:
        selector.close()


def _kill_process_group(process: subprocess.Popen[bytes], *, adapter_id: str) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    except PermissionError:
        try:
            process.kill()
        except ProcessLookupError:
            return
        except PermissionError as exc:
            raise AdapterExecutionError(
                f"local command cleanup failed: {adapter_id}"
            ) from exc
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired as exc:
            raise AdapterExecutionError(
                f"local command cleanup failed: {adapter_id}"
            ) from exc
        raise AdapterExecutionError(f"local command cleanup denied: {adapter_id}")
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
        except ProcessLookupError:
            return
        except PermissionError as exc:
            raise AdapterExecutionError(
                f"local command cleanup failed: {adapter_id}"
            ) from exc
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired as exc:
            raise AdapterExecutionError(
                f"local command cleanup failed: {adapter_id}"
            ) from exc


def adapter_request_id(request: Mapping[str, Any]) -> str:
    return f"adapter_req_{canonical_hash(request)[:32]}"


__all__ = [
    "ADAPTER_CONFIG_ENV",
    "ADAPTER_FAILURE_CLASSES",
    "AdapterExecutionError",
    "AdapterResult",
    "AdapterUnavailableError",
    "HttpModelAdapter",
    "LocalCommandAdapter",
    "ModelTurnAdapter",
    "ScriptedAdapter",
    "adapter_request_id",
    "sanitized_adapter_failure",
    "load_adapter_descriptors",
    "load_adapters",
    "sanitized_adapter_identity",
]
