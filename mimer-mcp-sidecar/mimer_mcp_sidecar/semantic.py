"""Mimer's fixed, protocol-neutral MCP semantic tool surface.

This module is intentionally a thin client of the existing HTTP contract. It
does not open a listener, touch the vault, import internal MCP tools, retain
write state, or retry an uncertain capture.  Transport packaging belongs to
MIMER-MCP-03; composed protocol acceptance belongs to MIMER-MCP-04.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol
from urllib.parse import urlparse
from uuid import uuid4

import httpx


@dataclass(frozen=True)
class McpToolDefinition:
    """One discoverable MCP tool and its JSON input schema."""

    name: str
    description: str
    input_schema: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
        }


@dataclass(frozen=True)
class McpToolResult:
    """A protocol-neutral MCP result preserving HTTP contract payloads."""

    content: dict[str, Any] | list[Any] | str | None = None
    error: dict[str, Any] | None = None
    trace_id: str | None = None

    @property
    def is_error(self) -> bool:
        return self.error is not None

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"isError": self.is_error}
        if self.is_error:
            result["error"] = self.error
        else:
            result["content"] = self.content
        if self.trace_id:
            result["_meta"] = {"trace_id": self.trace_id}
        return result


class _HttpResponse(Protocol):
    status_code: int

    def json(self) -> Any: ...


class _MimerHttpOperations(Protocol):
    """Private adapter seam over the five existing Mimer HTTP operations."""

    def ask(self, *, question: str, trace_id: str | None) -> _HttpResponse: ...

    def capture(self, *, text: str, trace_id: str | None) -> _HttpResponse: ...

    def retrieve(self, *, query: str, trace_id: str | None) -> _HttpResponse: ...

    def read_note(
        self, *, note_path: str, artifact_id: str | None, trace_id: str | None
    ) -> _HttpResponse: ...

    def health(self, *, trace_id: str | None) -> _HttpResponse: ...


class _GovernedMimerHttpOperations:
    """The fixed allowlist to the existing loopback HTTP client contract."""

    def __init__(self, client: httpx.Client) -> None:
        self._client = client

    @staticmethod
    def _headers(trace_id: str | None) -> dict[str, str] | None:
        return {"x-trace-id": trace_id} if trace_id else None

    def ask(self, *, question: str, trace_id: str | None) -> httpx.Response:
        return self._client.post("/api/ask", json={"question": question}, headers=self._headers(trace_id))

    def capture(self, *, text: str, trace_id: str | None) -> httpx.Response:
        return self._client.post(
            "/api/companion/capture", json={"text": text}, headers=self._headers(trace_id)
        )

    def retrieve(self, *, query: str, trace_id: str | None) -> httpx.Response:
        return self._client.get("/search", params={"q": query}, headers=self._headers(trace_id))

    def read_note(
        self, *, note_path: str, artifact_id: str | None, trace_id: str | None
    ) -> httpx.Response:
        params: dict[str, str] = {"note_path": note_path}
        if artifact_id:
            params["artifact_id"] = artifact_id
        return self._client.get("/api/artifacts/note", params=params, headers=self._headers(trace_id))

    def health(self, *, trace_id: str | None) -> httpx.Response:
        return self._client.get("/healthz", headers=self._headers(trace_id))


_STRING_SCHEMA = {"type": "string", "minLength": 1}
_NO_ARGUMENTS_SCHEMA = {"type": "object", "properties": {}, "additionalProperties": False}
_CAPTURE_ACTION = "companion.capture.append"
_CAPTURE_WRITE_CLASS = "vault_capture_append"
_CAPTURE_ACTOR = "companion.capture"
_CAPTURE_OPERATION = "append_note"
_CAPTURE_STATE_OWNER = "knowledge"
_GOVERNED_WRITE_CONTRACT_VERSION = "governed_write_protocol.v0"

_TOOLS = (
    McpToolDefinition(
        "mimer.ask",
        "Ask Mimer a grounded question; the returned sources retain Mimer provenance.",
        {
            "type": "object",
            "properties": {"question": _STRING_SCHEMA, "trace_id": {"type": "string"}},
            "required": ["question"],
            "additionalProperties": False,
        },
    ),
    McpToolDefinition(
        "mimer.capture",
        "Capture text through Mimer's existing governed inbox-write operation.",
        {
            "type": "object",
            "properties": {"text": _STRING_SCHEMA, "trace_id": {"type": "string"}},
            "required": ["text"],
            "additionalProperties": False,
        },
    ),
    McpToolDefinition(
        "mimer.retrieve",
        "Search Mimer's rebuildable retrieval index; a miss may reflect index lag.",
        {
            "type": "object",
            "properties": {"query": _STRING_SCHEMA, "trace_id": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        },
    ),
    McpToolDefinition(
        "mimer.read_note",
        "Read one vault-relative note through Mimer's traversal-guarded HTTP operation.",
        {
            "type": "object",
            "properties": {
                "note_path": _STRING_SCHEMA,
                "artifact_id": {"type": "string"},
                "trace_id": {"type": "string"},
            },
            "required": ["note_path"],
            "additionalProperties": False,
        },
    ),
    McpToolDefinition("mimer.health", "Read Mimer liveness.", _NO_ARGUMENTS_SCHEMA),
)


class MimerMcpServer:
    """Semantic MCP adapter over Mimer's existing governed HTTP operations."""

    def __init__(self, operations: _MimerHttpOperations) -> None:
        self._operations = operations

    @classmethod
    def for_loopback(cls, base_url: str = "http://127.0.0.1:8000") -> "MimerMcpServer":
        """Build the accepted A2/C1 client; wire/process lifecycle stays elsewhere."""
        hostname = urlparse(base_url).hostname
        if hostname not in {"127.0.0.1", "::1", "localhost"}:
            raise ValueError("Mimer MCP v1 requires a loopback Mimer HTTP endpoint")
        return cls(
            _GovernedMimerHttpOperations(
                httpx.Client(base_url=base_url, timeout=10.0, trust_env=False)
            )
        )

    def list_tools(self) -> tuple[McpToolDefinition, ...]:
        return _TOOLS

    def call_tool(self, name: str, arguments: Mapping[str, Any] | None = None) -> McpToolResult:
        args = dict(arguments or {})
        validation_error = _validate_arguments(name, args)
        if validation_error:
            return McpToolResult(error=validation_error)

        trace_id = _optional_string(args, "trace_id") or uuid4().hex
        try:
            if name == "mimer.ask":
                response = self._operations.ask(question=args["question"], trace_id=trace_id)
            elif name == "mimer.capture":
                response = self._operations.capture(text=args["text"], trace_id=trace_id)
            elif name == "mimer.retrieve":
                response = self._operations.retrieve(query=args["query"], trace_id=trace_id)
            elif name == "mimer.read_note":
                response = self._operations.read_note(
                    note_path=args["note_path"], artifact_id=_optional_string(args, "artifact_id"), trace_id=trace_id
                )
            else:  # mimer.health is validated above and carries no trace input.
                response = self._operations.health(trace_id=trace_id)
        except httpx.TimeoutException as exc:
            return McpToolResult(
                error={"error": "timeout", "message": str(exc), "trace_id": trace_id},
                trace_id=trace_id,
            )
        except httpx.HTTPError as exc:
            return McpToolResult(
                error={"error": "unavailable", "message": str(exc), "trace_id": trace_id},
                trace_id=trace_id,
            )

        payload = _response_payload(response)
        response_trace_id = _response_trace_id(response, payload, fallback=trace_id)
        if 200 <= response.status_code < 300:
            if name == "mimer.capture" and not _complete_capture_envelope(
                payload, outbound_trace_id=trace_id
            ):
                return McpToolResult(
                    error={
                        "error": "invalid_governed_capture_response",
                        "message": "Mimer capture acknowledgement lacked its governed receipt envelope.",
                        "trace_id": response_trace_id,
                    },
                    trace_id=response_trace_id,
                )
            # The capture envelope, including policy decision/token/receipt and trace, is
            # returned unchanged. There is intentionally no retry or local receipt state.
            return McpToolResult(content=payload, trace_id=response_trace_id)
        return McpToolResult(
            error={
                "status_code": response.status_code,
                "detail": payload,
                "trace_id": response_trace_id,
            },
            trace_id=response_trace_id,
        )


def _response_payload(response: _HttpResponse) -> dict[str, Any] | list[Any] | str | None:
    try:
        payload = response.json()
    except (TypeError, ValueError):
        return None
    return payload if isinstance(payload, (dict, list, str)) else None


def _response_trace_id(
    response: _HttpResponse,
    payload: dict[str, Any] | list[Any] | str | None,
    *,
    fallback: str,
) -> str:
    if isinstance(payload, dict) and isinstance(payload.get("trace_id"), str):
        return payload["trace_id"]
    headers = getattr(response, "headers", {})
    return headers.get("x-trace-id") or fallback


def _complete_capture_envelope(payload: object, *, outbound_trace_id: str) -> bool:
    """Fail closed if a 2xx capture response lacks the API's governed receipt."""
    if not isinstance(payload, dict) or payload.get("outcome") != "written":
        return False
    if not _has_nonempty_strings(
        payload, "note_path", "operation", "adapter", "captured_at", "trace_id"
    ) or not isinstance(payload.get("events_emitted"), list):
        return False
    governed_write = payload.get("governed_write")
    if not isinstance(governed_write, dict):
        return False
    policy = governed_write.get("policy_decision")
    token = governed_write.get("decision_token")
    receipt = governed_write.get("authority_receipt")
    if not all(isinstance(item, dict) for item in (policy, token, receipt)):
        return False
    assert isinstance(policy, dict) and isinstance(token, dict) and isinstance(receipt, dict)
    if not _has_nonempty_strings(
        policy,
        "decision_id",
        "action",
        "write_class",
        "actor",
        "resource",
        "reason",
        "issued_at",
        "source",
        "contract_version",
    ) or policy.get("status") != "approved":
        return False
    if not _has_nonempty_strings(
        token,
        "token_id",
        "decision_id",
        "action",
        "write_class",
        "actor",
        "resource",
        "issued_at",
        "contract_version",
    ) or token.get("valid") is not True:
        return False
    if not _has_nonempty_strings(
        receipt,
        "receipt_id",
        "decision_token_id",
        "decision_id",
        "action",
        "write_class",
        "actor",
        "resource",
        "operation",
        "adapter",
        "state_owner",
        "source_receipt_ref",
        "recorded_at",
        "trace_id",
        "contract_version",
    ) or receipt.get("outcome") != "applied" or not isinstance(receipt.get("fallback_used"), bool):
        return False
    bound_fields = ("decision_id", "action", "write_class", "actor", "resource")
    if any(token[field] != policy[field] or receipt[field] != policy[field] for field in bound_fields):
        return False
    if (
        policy["action"] != _CAPTURE_ACTION
        or policy["write_class"] != _CAPTURE_WRITE_CLASS
        or policy["actor"] != _CAPTURE_ACTOR
        or policy["source"] != "WriteGuard"
        or policy["contract_version"] != _GOVERNED_WRITE_CONTRACT_VERSION
        or token["contract_version"] != _GOVERNED_WRITE_CONTRACT_VERSION
        or receipt["operation"] != _CAPTURE_OPERATION
        or receipt["state_owner"] != _CAPTURE_STATE_OWNER
        or receipt["contract_version"] != _GOVERNED_WRITE_CONTRACT_VERSION
        or receipt["fallback_used"] is not False
    ):
        return False
    return (
        receipt["decision_token_id"] == token["token_id"]
        and receipt["trace_id"] == payload["trace_id"]
        and receipt["trace_id"] == outbound_trace_id
        and receipt["operation"] == payload.get("operation")
        and receipt["adapter"] == payload.get("adapter")
        and receipt["resource"] == payload.get("note_path")
        and receipt["source_receipt_ref"]
        == f"{receipt['adapter']}:{receipt['operation']}:{receipt['resource']}"
    )


def _has_nonempty_strings(mapping: Mapping[str, object], *fields: str) -> bool:
    return all(isinstance(mapping.get(field), str) and mapping[field] for field in fields)


def _optional_string(arguments: Mapping[str, Any], field: str) -> str | None:
    value = arguments.get(field)
    return value if isinstance(value, str) else None


def _validate_arguments(name: str, arguments: Mapping[str, Any]) -> dict[str, Any] | None:
    tool = next((candidate for candidate in _TOOLS if candidate.name == name), None)
    if tool is None:
        return {"error": "unknown_tool", "tool": name}
    schema = tool.input_schema
    allowed = set(schema["properties"])
    unexpected = sorted(set(arguments) - allowed)
    if unexpected:
        return {"error": "validation_error", "message": "unexpected argument", "fields": unexpected}
    for field in schema.get("required", []):
        value = arguments.get(field)
        if not isinstance(value, str) or not value.strip():
            return {"error": "validation_error", "message": f"{field} must be a non-empty string"}
    for field in allowed:
        if field in arguments and not isinstance(arguments[field], str):
            return {"error": "validation_error", "message": f"{field} must be a string"}
    return None
