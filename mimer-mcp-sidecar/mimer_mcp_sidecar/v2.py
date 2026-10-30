"""ADR-0069's opt-in, capability-derived shared-HTTP protocol mapping.

The runtime supplies schemas, support and all operation outcomes. This module
owns neither an operation registry nor a policy, identity, receipt or retry path.
"""
from __future__ import annotations

from typing import Any, Mapping
from urllib.parse import quote, urlparse

import httpx
import jsonschema

from .semantic import McpToolDefinition, McpToolResult

# This is the accepted external-profile fence, never an installation registry.
# In particular, discovery of Panel/settings/memory operations cannot admit them.
_ADMITTED = frozenset({
    "operation.discovery", "operation.batch", "artifact.list", "artifact.read",
    "artifact.search", "artifact.related", "artifact.capture", "artifact.create",
    "artifact.update", "artifact.move", "artifact.rename", "artifact.classify",
    "artifact.tags.add", "artifact.tags.remove", "collection.reorder",
    "artifact.archive", "artifact.restore",
})
_PREFIX = "mimer.v2."
_DISCOVER = _PREFIX + "operation.discovery"
_PRECONDITIONS = _PREFIX + "operation.preconditions"
_RECEIPT = _PREFIX + "operation.receipt"
_BATCH = _PREFIX + "batch."
# The bootstrap discovery tool has no client authority or operation payload.
_EMPTY = {"type": "object", "properties": {}, "additionalProperties": False}


class MimerMcpV2Server:
    """A request-scoped wire adapter over the existing authenticated API."""
    profile = "v2"

    def __init__(self, client: httpx.Client) -> None:
        self._client = client

    @classmethod
    def for_loopback(cls, base_url="http://127.0.0.1:8000", *, runtime_read_deadline_seconds=75.0):
        parsed = urlparse(base_url)
        if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "::1", "localhost"}
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in {"", "/"}):
            raise ValueError("Mimer MCP v2 requires a credential-free loopback HTTP origin")
        from .semantic import _build_runtime_managed_timeout
        return cls(httpx.Client(base_url=base_url, trust_env=False, follow_redirects=False,
            timeout=_build_runtime_managed_timeout(runtime_read_deadline_seconds)))

    @staticmethod
    def _headers(meta: Mapping[str, Any] | None) -> dict[str, str]:
        # Request-local relay only. Presence matters: an empty override must
        # reach the native validator and never fall back to a valid session.
        headers = {}
        for key, header in (("mimer/active-context-session", "X-Active-Context-Session"),
                            ("mimer/active-context-override", "X-Active-Context-Override")):
            if meta is not None and key in meta:
                value = meta[key]
                if not isinstance(value, str) or any(ord(char) < 32 or ord(char) > 126 for char in value):
                    raise ValueError("invalid context carrier")
                headers[header] = value
        return headers

    def _request(self, method, path, *, meta=None, body=None, params=None, effect=False, reference=None):
        try:
            headers = self._headers(meta)
        except ValueError:
            return McpToolResult(error={"error": "invalid_context_carrier"})
        try:
            response = self._client.request(method, path, headers=headers, json=body, params=params)
        except httpx.HTTPError:
            return self._unacknowledged(reference) if effect else McpToolResult(error={"error": "operation_unavailable"})
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if effect and (response.status_code >= 500 or not isinstance(payload, dict)):
            return self._unacknowledged(reference)
        if not 200 <= response.status_code < 300:
            return McpToolResult(error={"status_code": response.status_code, "detail": payload})
        if not isinstance(payload, dict):
            return McpToolResult(error={"error": "operation_response_unavailable"})
        return McpToolResult(content=payload)

    @staticmethod
    def _unacknowledged(reference):
        # Transport truth only: no owner receipt or source success is invented.
        return McpToolResult(error={"error": "operation_not_acknowledged", "source_effect": "unknown",
            "retryable": False, "reference": reference,
            "message": "Read back the durable operation or batch through the shared API before considering retry."})

    def discover(self, meta=None):
        return self._request("GET", "/api/operations/capabilities", meta=meta)

    def _catalog(self, meta):
        result = self.discover(meta)
        if result.is_error:
            return result, {}, {}
        payload = result.content
        if not isinstance(payload, dict) or payload.get("status") != "succeeded":
            return McpToolResult(error={"error": "operation_discovery_unavailable"}), {}, {}
        try:
            catalog = {item["resource_id"]: item["payload"] for item in payload["items"]}
            schemas = payload["extensions"]["transport_schemas"]
            for name, capability in catalog.items():
                if name not in _ADMITTED:
                    continue
                if capability["operation_version"] != "ygg.operation.v1":
                    raise ValueError("unsupported operation version")
                for field in ("input_schema", "authority_class", "side_effect_class", "preview_support", "maturity", "support"):
                    if field not in capability:
                        raise ValueError("missing native capability contract")
                if capability["support"] not in {"supported", "unavailable", "policy_disabled"}:
                    raise ValueError("invalid support state")
                jsonschema.Draft202012Validator.check_schema(capability["input_schema"])
            for field in ("preconditions", "receipt", "batch_reference", "batch_preview", "outcome"):
                jsonschema.Draft202012Validator.check_schema(schemas[field])
        except (KeyError, TypeError, ValueError, jsonschema.SchemaError):
            return McpToolResult(error={"error": "operation_discovery_contract_incomplete"}), {}, {}
        return result, catalog, schemas

    @staticmethod
    def _definition(operation_id, capability):
        metadata = {key: capability[key] for key in (
            "operation_version", "authority_class", "side_effect_class", "preview_support", "maturity")}
        return McpToolDefinition(_PREFIX + operation_id, "Invoke the runtime-owned " + operation_id + " operation.",
            capability["input_schema"], output_schema=capability.get("output_schema"), metadata=metadata)

    def list_tools(self, meta=None):
        result, catalog, schemas = self._catalog(meta)
        discovery = McpToolDefinition(_DISCOVER, "Discover native supported and unavailable operations.", _EMPTY)
        if result.is_error:
            # Discovery remains callable and returns the exact typed HTTP refusal.
            return (discovery,)
        return self._definitions(catalog, schemas)

    def _definitions(self, catalog, schemas):
        tools = [self._definition(name, cap) for name, cap in catalog.items()
                 if name in _ADMITTED and name != "operation.batch" and cap["support"] == "supported"]
        tools.append(McpToolDefinition(_RECEIPT, "Read the original durable operation receipt; never replay an effect.",
            schemas["receipt"], output_schema=schemas["outcome"]))
        effects = [name for name, cap in catalog.items() if name in _ADMITTED
                   and cap["support"] == "supported" and cap["preview_support"] and name != "operation.batch"]
        if effects:
            original = schemas["preconditions"]
            narrowed = {**original, "properties": {**original["properties"],
                "operation_id": {"type": "string", "enum": effects}}}
            tools.append(McpToolDefinition(_PRECONDITIONS, "Observe native preconditions without applying an effect.", narrowed))
        batch = catalog.get("operation.batch", {})
        if batch.get("support") == "supported":
            schema = schemas["batch_preview"]
            narrowed = {**schema, "properties": {**schema["properties"], "operation_id": {
                "type": "string", "enum": batch["supported_kinds"]}}}
            tools.append(McpToolDefinition(_BATCH + "preview", "Freeze a finite native batch without source effects.", narrowed))
            tools.extend(McpToolDefinition(_BATCH + action, "Use the native frozen-batch " + action + " lifecycle.",
                schemas["batch_reference"]) for action in ("inspect", "execute", "cancel"))
        return tuple(tools)

    def call_tool(self, name, arguments=None, *, meta=None):
        args = dict(arguments or {})
        if name == _DISCOVER:
            if args:
                return McpToolResult(error={"error": "validation_error"})
            return self.discover(meta)
        if not name.startswith(_PREFIX):
            return McpToolResult(error={"error": "unknown_tool", "tool": name})
        result, catalog, schemas = self._catalog(meta)
        if result.is_error:
            return result
        definitions = {tool.name: tool for tool in self._definitions(catalog, schemas)}
        operation_id = name.removeprefix(_PREFIX)
        # Unavailable admitted operations remain callable only for the native
        # typed disposition; they are never advertised as installed tools.
        if operation_id in _ADMITTED and operation_id not in {"operation.discovery", "operation.batch"} and operation_id in catalog:
            definitions[name] = self._definition(operation_id, catalog[operation_id])
        definition = definitions.get(name)
        if definition is None:
            return McpToolResult(error={"error": "unknown_tool", "tool": name})
        try:
            jsonschema.validate(args, definition.input_schema)
        except (jsonschema.ValidationError, jsonschema.SchemaError):
            return McpToolResult(error={"error": "validation_error"})
        if name == _RECEIPT:
            return self._request("GET", "/api/operations/receipts/" + _segment(args["request_id"]), meta=meta)
        if name == _PRECONDITIONS:
            return self._request("POST", "/api/operations/preconditions", meta=meta, body=args)
        if name == _BATCH + "preview":
            return self._request("POST", "/api/operations/batches/preview", meta=meta, body=args,
                effect=True, reference=args["batch_id"])
        if name.startswith(_BATCH):
            action = name.removeprefix(_BATCH)
            path = "/api/operations/batches/" + _segment(args["batch_id"])
            if action == "inspect":
                return self._request("GET", path, meta=meta, params={"expected_digest": args["expected_digest"]})
            return self._request("POST", path + "/" + action, meta=meta,
                body={"expected_digest": args["expected_digest"]}, effect=True, reference=args["batch_id"])
        effect = catalog[operation_id]["authority_class"] == "governed_effect"
        result = self._request("POST", "/api/operations", meta=meta, body=args, effect=effect, reference=args["request_id"])
        if not result.is_error and definition.output_schema is not None:
            try:
                jsonschema.validate(result.content, definition.output_schema)
            except (jsonschema.ValidationError, jsonschema.SchemaError):
                return self._unacknowledged(args["request_id"]) if effect else McpToolResult(error={"error": "operation_response_unavailable"})
        return result


def _segment(value):
    # Even the admitted dot-only identifiers must remain opaque path segments.
    return quote(value, safe=":").replace(".", "%2E")
