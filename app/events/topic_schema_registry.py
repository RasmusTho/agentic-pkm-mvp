"""Versioned per-topic outbox payload schema registry (KERNEL-08, #2770).

``OutboxEvent.payload`` is ``Dict[str, Any]`` and no per-topic contract exists —
consumers parse raw dicts (audit invariants I-E5, CW-4,
``docs/RUNTIME_CORRECTNESS_KERNEL/EVENT_TOPIC_SCHEMA_REGISTRY.md``). This module
is the single registry mapping a dispatched outbox topic to its versioned JSON
Schema file under ``schemas/events/``, plus the validation choke point used at
write (``app/services/outbox.py::write_outbox_event``) and dispatch
(``app/workers/outbox_worker.py::_dispatch_topic``).

Design notes:

- Every registered topic has a baseline ``v1`` schema. The seven kernel topics in
  :data:`_CURRENT_VERSIONS` (#5704, audit #2899 F6) additionally register a
  closed ``v2``; ``current_schema_ref`` is the single source of the version
  stamped onto new writes. Older registered versions stay loadable, so a row
  already tagged ``<topic>.v1`` keeps its original (open) contract at dispatch
  and on worker retry instead of being reinterpreted under the stricter version
  (:func:`dispatch_schema_ref`).
- Registration reuses the same ``jsonschema`` machinery as the LLM
  constrained-completion registry (``app/components/llm/constrained.py``): a
  malformed schema fails loud at load time (``Draft202012Validator.check_schema``),
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

_BASELINE_VERSION = 1

# Topics whose current schema is newer than the v1 baseline (#5704). Every other
# registered topic stays at v1.
_CURRENT_VERSIONS: dict[str, int] = {
    "ingest.object.created": 2,
    "ingest.vault.changed": 2,
    "ingest.object.deleted": 2,
    "panel.scan.requested": 2,
    "promote.intent.created": 2,
    "note.move.workbench": 2,
    "index.embedding.requested": 2,
}

# ``payload_schema`` value used when re-emitting a pre-registry ("v0") row: the
# payload is validated log-only and written without a schema tag, so the
# re-emitted row stays grandfathered instead of being upgraded.
LEGACY_UNTAGGED_V0 = "v0"


class TopicSchemaViolation(Exception):
    """A payload failed validation against its topic's registered schema."""

    def __init__(self, *, topic: str, schema_ref: str, reason: str) -> None:
        super().__init__(f"payload for topic {topic!r} violates schema {schema_ref!r}: {reason}")
        self.topic = topic
        self.schema_ref = schema_ref
        self.reason = reason


class UnregisteredTopicError(LookupError):
    """A topic was validated without a registered schema — a coverage gap."""


def _schema_path(topic: str, version: int = _BASELINE_VERSION) -> Path:
    return _SCHEMAS_DIR / f"{topic}.v{version}.schema.json"


def _current_version(topic: str) -> int:
    return _CURRENT_VERSIONS.get(topic, _BASELINE_VERSION)


def _schema_ref(topic: str, version: int) -> str:
    return f"{topic}.v{version}"


def current_schema_ref(topic: str) -> str:
    """Return the ``<topic>.v<N>`` ref stamped onto newly written payloads."""
    return _schema_ref(topic, _current_version(topic))


def baseline_schema_ref(topic: str) -> str:
    """Return the ``<topic>.v1`` ref every registered topic started with."""
    return _schema_ref(topic, _BASELINE_VERSION)


def is_registered_topic(topic: str) -> bool:
    return _schema_path(topic).is_file()


def registered_schema_version(topic: str, schema_ref: str | None) -> int | None:
    """Return ``N`` when ``schema_ref`` is exactly ``<topic>.v<N>`` and that version is registered."""
    if not schema_ref:
        return None
    prefix = f"{topic}.v"
    if not schema_ref.startswith(prefix):
        return None
    digits = schema_ref[len(prefix):]
    if not digits.isdigit():
        return None
    version = int(digits)
    if version < _BASELINE_VERSION or version > _current_version(topic):
        return None
    return version if _schema_path(topic, version).is_file() else None


_LOADED: dict[tuple[str, int], dict[str, Any]] = {}


def _load_schema(topic: str, version: int = _BASELINE_VERSION) -> dict[str, Any]:
    cached = _LOADED.get((topic, version))
    if cached is not None:
        return cached
    path = _schema_path(topic, version)
    if not path.is_file():
        raise UnregisteredTopicError(
            f"no schema registered for topic {topic!r} (expected {path})"
        )
    schema = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    _LOADED[(topic, version)] = schema
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


def dispatch_schema_ref(topic: str, version: PayloadSchemaVersion) -> str:
    """Return the schema ref a stored row keeps for dispatch and worker retry.

    - Untagged (pre-registry) row: :data:`LEGACY_UNTAGGED_V0` (log-only).
    - Tagged exactly ``<topic>.v<N>`` with a registered schema: that version.
    - Any other tag: the ``v1`` baseline. Before #5704 every tagged row was
      validated against v1 whatever its tag said, so this keeps the meaning of
      already-tagged rows instead of upgrading them to the closed version.
    """
    if version.is_grandfathered:
        return LEGACY_UNTAGGED_V0
    if registered_schema_version(topic, version.raw) is not None:
        return str(version.raw)
    return baseline_schema_ref(topic)


def validate_topic_payload(topic: str, payload: Any, *, schema_ref: str | None = None) -> None:
    """Validate ``payload`` against ``topic``'s registered schema.

    ``schema_ref`` selects a registered version (``<topic>.v<N>``); ``None``
    means the current version stamped onto new writes. Raises
    :class:`UnregisteredTopicError` if the topic (or the requested version) has
    no schema, or :class:`TopicSchemaViolation` if the payload does not conform.
    Returns ``None`` on success (payload is not copied/mutated).
    """
    if schema_ref is None:
        version = _current_version(topic)
    else:
        resolved = registered_schema_version(topic, schema_ref)
        if resolved is None:
            raise UnregisteredTopicError(
                f"no registered schema {schema_ref!r} for topic {topic!r}"
            )
        version = resolved
    schema = _load_schema(topic, version)
    ref = _schema_ref(topic, version)
    if not isinstance(payload, Mapping):
        raise TopicSchemaViolation(
            topic=topic,
            schema_ref=ref,
            reason=f"payload is not a JSON object (got {type(payload).__name__})",
        )
    try:
        Draft202012Validator(schema).validate(dict(payload))
    except _SchemaViolation as exc:
        raise TopicSchemaViolation(
            topic=topic,
            schema_ref=ref,
            reason=exc.message,
        ) from exc


__all__ = [
    "LEGACY_UNTAGGED_V0",
    "PayloadSchemaVersion",
    "TopicSchemaViolation",
    "UnregisteredTopicError",
    "baseline_schema_ref",
    "current_schema_ref",
    "dispatch_schema_ref",
    "is_registered_topic",
    "registered_schema_version",
    "resolve_payload_schema_version",
    "validate_topic_payload",
]
