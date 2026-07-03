"""Schema-constrained LLM completion at the shared LLM seam (KERNEL-07, #2769).

LLM output that code branches on must be schema-constrained and validated
before it is returned to the caller (audit invariants I-A1/I-A2,
``docs/RUNTIME_CORRECTNESS_KERNEL/STRUCTURED_INTENT_OUTPUT_WITH_UNKNOWN.md``).
This module owns that boundary:

- a process-local **schema registry** (``register_schema`` /
  ``registered_schema``) so control-path schemas are named, checked artifacts;
- ``constrained_completion(schema_ref, ...)`` which requests
  schema-constrained decoding from the provider (Ollama ``format`` /
  OpenAI-style ``response_format``) via the existing ``ChatClient`` seam and
  **validates the raw completion against the registered schema before
  returning** it as a parsed object;
- a typed failure, ``ConstrainedCompletionError``, on any invalid output —
  empty completions, provider failures, non-JSON text, JSON non-objects, and
  schema violations all surface loudly. There is **no regex extraction** and
  no silent default: JSON embedded in prose is rejected, not fished out.

The raw completion function is injectable (``complete=``) so tests and callers
with their own provider seam can substitute a deterministic stub — validation
always runs on this side of the seam, below any injection point.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Mapping

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as _SchemaViolation

from app.components.llm.router import LLMTaskIntent

# Raw completion function: returns the provider's raw text for a prompt.
# Keyword-only so stubs and real routes stay signature-compatible.
CompletionFn = Callable[..., str]


class ConstrainedCompletionError(Exception):
    """Typed failure from :func:`constrained_completion`.

    Raised when the provider call fails or the completion does not validate
    against the registered schema. Callers on control paths must map this to an
    explicit degraded state (e.g. the intent classifier's ``UNKNOWN``), never
    to a silently defaulted, action-capable value.
    """

    def __init__(self, *, schema_ref: str, reason: str, raw: str | None = None) -> None:
        super().__init__(f"constrained completion failed for schema {schema_ref!r}: {reason}")
        self.schema_ref = schema_ref
        self.reason = reason
        self.raw = raw


class UnknownSchemaRefError(LookupError):
    """A ``schema_ref`` was used without being registered — a programming error."""


_SCHEMA_REGISTRY: dict[str, dict[str, Any]] = {}


def register_schema(schema_ref: str, schema: Mapping[str, Any]) -> None:
    """Register ``schema`` (a JSON Schema object) under ``schema_ref``.

    The schema itself is checked at registration time so a malformed schema
    fails loud at import, not silently at validation time. Re-registering the
    identical schema is a no-op; re-registering a different schema under the
    same ref is refused (one authority per ref).
    """
    normalized = dict(schema)
    Draft202012Validator.check_schema(normalized)
    existing = _SCHEMA_REGISTRY.get(schema_ref)
    if existing is not None and existing != normalized:
        raise ValueError(f"schema ref {schema_ref!r} is already registered with a different schema")
    _SCHEMA_REGISTRY[schema_ref] = normalized


def registered_schema(schema_ref: str) -> dict[str, Any]:
    """Return the registered schema for ``schema_ref`` (raises if unregistered)."""
    schema = _SCHEMA_REGISTRY.get(schema_ref)
    if schema is None:
        raise UnknownSchemaRefError(f"no schema registered under ref {schema_ref!r}")
    return dict(schema)


def validate_payload(schema_ref: str, payload: Any) -> dict[str, Any]:
    """Validate ``payload`` against the schema registered under ``schema_ref``.

    Returns the payload on success; raises :class:`ConstrainedCompletionError`
    on any violation. This is the single validation choke point — it runs for
    every :func:`constrained_completion` call, injected stub or real provider.
    """
    schema = registered_schema(schema_ref)
    if not isinstance(payload, dict):
        raise ConstrainedCompletionError(
            schema_ref=schema_ref,
            reason=f"completion is not a JSON object (got {type(payload).__name__})",
        )
    try:
        Draft202012Validator(schema).validate(payload)
    except _SchemaViolation as exc:
        raise ConstrainedCompletionError(
            schema_ref=schema_ref,
            reason=f"schema violation: {exc.message}",
        ) from exc
    return payload


def _default_complete(*, schema_ref: str, task_kind: str) -> CompletionFn:
    """Real provider route: ``ChatClient`` with schema-constrained decoding."""
    # Local import: fabric pulls in the embeddings stack; keep the module
    # importable (and the injectable path dependency-free) without it.
    from app.components.llm.fabric import get_chat_client

    schema = registered_schema(schema_ref)
    client = get_chat_client(LLMTaskIntent(task_kind=task_kind, json_schema_required=True))

    def complete(
        *,
        system: str,
        user: str,
        trace_id: str | None = None,
        max_tokens: int | None = None,
    ) -> str:
        return client.chat(
            schema_ref,
            {"system": system, "user": user},
            kind=task_kind,
            trace_id=trace_id,
            max_tokens=max_tokens,
            response_format=schema,
        )

    return complete


def constrained_completion(
    schema_ref: str,
    *,
    system: str = "",
    user: str,
    task_kind: str = "decide",
    trace_id: str | None = None,
    max_tokens: int | None = None,
    complete: CompletionFn | None = None,
) -> dict[str, Any]:
    """Run a completion constrained to — and validated against — a registered schema.

    Returns the parsed, schema-valid JSON object. Raises
    :class:`ConstrainedCompletionError` on provider failure or any output that
    does not strictly parse and validate. The whole completion must be one JSON
    object: prose-wrapped JSON is invalid by design (no regex extraction).
    """
    # Resolve the schema first: an unregistered ref must fail loud even when a
    # custom ``complete`` is injected.
    registered_schema(schema_ref)
    if complete is None:
        complete = _default_complete(schema_ref=schema_ref, task_kind=task_kind)
    try:
        raw = complete(system=system, user=user, trace_id=trace_id, max_tokens=max_tokens)
    except Exception as exc:
        raise ConstrainedCompletionError(
            schema_ref=schema_ref,
            reason=f"provider call failed: {exc}",
        ) from exc
    if not isinstance(raw, str) or not raw.strip():
        raise ConstrainedCompletionError(schema_ref=schema_ref, reason="empty completion", raw=raw)
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        raise ConstrainedCompletionError(
            schema_ref=schema_ref,
            reason=f"completion is not valid JSON: {exc}",
            raw=raw,
        ) from exc
    return validate_payload(schema_ref, payload)


__all__ = [
    "CompletionFn",
    "ConstrainedCompletionError",
    "UnknownSchemaRefError",
    "constrained_completion",
    "register_schema",
    "registered_schema",
    "validate_payload",
]
