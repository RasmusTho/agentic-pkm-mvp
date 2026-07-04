"""Versioned per-topic outbox payload schema registry (KERNEL-08, #2770).

``OutboxEvent.payload`` is ``Dict[str, Any]`` and no per-topic contract exists —
consumers parse raw dicts (audit invariants I-E5, CW-4,
``docs/RUNTIME_CORRECTNESS_KERNEL/EVENT_TOPIC_SCHEMA_REGISTRY.md``). This module
is the single registry mapping a dispatched outbox topic to its versioned JSON
Schema file under ``schemas/events/``, plus the validation choke point used at
write (``app/services/outbox.py::write_outbox_event``) and dispatch
(``app/workers/outbox_worker.py::_dispatch_topic``).

Design notes:

- One registered schema version per topic today (``v1``); ``current_schema_ref``
  is the single source of the "latest" version stamped onto new writes.
- Registration reuses the same ``jsonschema`` machinery as the LLM
  constrained-completion registry (``app/components/llm/constrained.py``): a
  malformed schema fails loud at import time (``Draft202012Validator.check_schema``),
  not silently at validation time.
- Grandfathering (cross-task invariant #1, ``docs/RUNTIME_CORRECTNESS_KERNEL/README.md``):
  a payload with no recognizable schema tag (pre-registry row) is a distinct,
  named case (:class:`PayloadSchemaVersion` ``.is_grandfathered``) so callers can
  choose log-only validation instead of hard failure without re-deriving the
  "is this an old row" rule themselves.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as _SchemaViolation

# schemas/events/ lives at the repo root, two levels above app/events/.
_SCHEMAS_DIR = Path(__file__).resolve().parents[2] / "schemas" / "events"

_SCHEMA_VERSION = 1


class TopicSchemaViolation(Exception):
    """A payload failed validation against its topic's registered schema."""

    def __init__(self, *, topic: str, schema_ref: str, reason: str) -> None:
        super().__init__(f"payload for topic {topic!r} violates schema {schema_ref!r}: {reason}")
        self.topic = topic
        self.schema_ref = schema_ref
        self.reason = reason


class UnregisteredTopicError(LookupError):
    """A topic was validated without a registered schema — a coverage gap."""


def _schema_path(topic: str) -> Path:
    return _SCHEMAS_DIR / f"{topic}.v{_SCHEMA_VERSION}.schema.json"


def current_schema_ref(topic: str) -> str:
    """Return the ``<topic>.v<N>`` ref stamped onto newly written payloads."""
    return f"{topic}.v{_SCHEMA_VERSION}"


def is_registered_topic(topic: str) -> bool:
    return _schema_path(topic).is_file()


_LOADED: dict[str, dict[str, Any]] = {}


def _load_schema(topic: str) -> dict[str, Any]:
    cached = _LOADED.get(topic)
    if cached is not None:
        return cached
    path = _schema_path(topic)
    if not path.is_file():
        raise UnregisteredTopicError(
            f"no schema registered for topic {topic!r} (expected {path})"
        )
    schema = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    _LOADED[topic] = schema
    return schema


@dataclass(frozen=True)
class PayloadSchemaVersion:
    """The resolved ``payload_schema``/``schema_version`` tag on an outbox row.

    ``is_grandfathered`` is True exactly when the row predates the registry
    (no recognizable version tag): cross-task invariant #1 requires these rows
    be validated log-only, never dead-lettered retroactively.
    """

    raw: str | None
    is_grandfathered: bool


def resolve_payload_schema_version(meta: Mapping[str, Any] | None) -> PayloadSchemaVersion:
    """Resolve the schema-version tag from an outbox row's ``meta``.

    Absence of both ``meta.payload_schema`` and ``meta.schema_version`` means
    the row was written before the registry existed — grandfathered ``v0``.
    """
    if not isinstance(meta, Mapping):
        return PayloadSchemaVersion(raw=None, is_grandfathered=True)
    raw = meta.get("payload_schema") or meta.get("schema_version")
    if not raw:
        return PayloadSchemaVersion(raw=None, is_grandfathered=True)
    return PayloadSchemaVersion(raw=str(raw), is_grandfathered=False)


def validate_topic_payload(topic: str, payload: Any) -> None:
    """Validate ``payload`` against ``topic``'s registered schema.

    Raises :class:`UnregisteredTopicError` if the topic has no schema, or
    :class:`TopicSchemaViolation` if the payload does not conform. Returns
    ``None`` on success (payload is not copied/mutated).
    """
    schema = _load_schema(topic)
    if not isinstance(payload, Mapping):
        raise TopicSchemaViolation(
            topic=topic,
            schema_ref=current_schema_ref(topic),
            reason=f"payload is not a JSON object (got {type(payload).__name__})",
        )
    try:
        Draft202012Validator(schema).validate(dict(payload))
    except _SchemaViolation as exc:
        raise TopicSchemaViolation(
            topic=topic,
            schema_ref=current_schema_ref(topic),
            reason=exc.message,
        ) from exc


__all__ = [
    "PayloadSchemaVersion",
    "TopicSchemaViolation",
    "UnregisteredTopicError",
    "current_schema_ref",
    "is_registered_topic",
    "resolve_payload_schema_version",
    "validate_topic_payload",
]
