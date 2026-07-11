"""JSON Schema validation for episode notes against ``schemas/episode-note.schema.json``
(ADR-0051 OD-1/OD-2 shape; ERE-02 AC1).

Mirrors the cross-file ``$ref``-resolving pattern in
``tests/invariants/_helpers.py::assert_validates`` (registry keyed by each schema's ``$id``)
so ``episode-note.schema.json``'s ``_defs.schema.json#/...`` refs resolve without network
access, but lives in ``app/`` (not ``tests/``) because the store needs it at runtime too.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMAS_DIR = REPO_ROOT / "schemas"
EPISODE_NOTE_SCHEMA_NAME = "episode-note.schema.json"


class EpisodeSchemaValidationError(ValueError):
    """Raised when episode note fields fail the ADR-0051 shape."""


def _load_schema(name: str) -> dict[str, Any]:
    return json.loads((SCHEMAS_DIR / name).read_text(encoding="utf-8"))


def _schema_registry() -> Any:
    from referencing import Registry, Resource

    resources = []
    for path in SCHEMAS_DIR.glob("*.schema.json"):
        contents = json.loads(path.read_text(encoding="utf-8"))
        schema_id = contents.get("$id")
        if schema_id:
            resources.append((schema_id, Resource.from_contents(contents)))
    return Registry().with_resources(resources)


def validate_episode_note_fields(fields: dict[str, Any]) -> None:
    """Validate ``fields`` against ``schemas/episode-note.schema.json``.

    Raises ``EpisodeSchemaValidationError`` (chaining the underlying
    ``jsonschema.ValidationError``) on any shape violation -- missing
    ``time.closed``, an unknown ``segmentation`` value, a malformed
    ``episode_id``, or any other schema-enforced rule.
    """
    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import ValidationError

    schema = _load_schema(EPISODE_NOTE_SCHEMA_NAME)
    validator = Draft202012Validator(schema, registry=_schema_registry())
    try:
        validator.validate(fields)
    except ValidationError as exc:
        raise EpisodeSchemaValidationError(str(exc)) from exc


__all__ = [
    "EPISODE_NOTE_SCHEMA_NAME",
    "EpisodeSchemaValidationError",
    "validate_episode_note_fields",
]
