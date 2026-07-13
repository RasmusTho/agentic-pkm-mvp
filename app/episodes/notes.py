"""Render/parse episode notes as vault markdown (ADR-0051 OD-2: note-serialized).

One markdown note per episode: YAML frontmatter carries the parsed situation-model fields
(the schema-validated source of truth); a short human-readable body documents the shape
inline, mirroring ``app.heimdal.settings_notes.render_note``/``parse_note`` and reusing the
same shared frontmatter round-trip helper (never hand-rolled YAML).
"""

from __future__ import annotations

from typing import Any

import yaml

from app.episodes.schema import validate_episode_note_fields
from scripts.yaml_roundtrip import dump_frontmatter, load_frontmatter

ARTIFACT_CLASS = "episode_note"

# Vault-relative directory episode notes live under. Matches the locator shape named in the
# capability spec's CLI example: ``vault://episodes/ep-...``.
EPISODE_NOTES_DIR = "episodes"

_FRONTMATTER_FIELDS = (
    "episode_id",
    "scope",
    "title",
    "time",
    "space",
    "protagonists",
    "goal",
    "causation",
    "parent_episode",
    "segmentation",
    "derived_from",
)


class EpisodeFrontmatterParseError(ValueError):
    """Raised when an episode note has syntactically invalid YAML frontmatter."""


def episode_note_rel_path(episode_id: str) -> str:
    return f"{EPISODE_NOTES_DIR}/{episode_id}.md"


def _canonical_body(fields: dict[str, Any]) -> str:
    time_fields = fields.get("time") or {}
    lines: list[str] = [
        f"# Episode: {fields.get('title', '')}",
        "",
        f"**Segmentation:** `{fields.get('segmentation', '')}`",
        f"**Scope:** `{fields.get('scope', '')}`",
        f"**Time:** {time_fields.get('start', '')} -> {time_fields.get('end', '(open)')} "
        f"(closed: {time_fields.get('closed', False)})",
        "",
        "This note is vault-canonical (ADR-0051 OD-1/OD-2) -- the frontmatter above is the "
        "source of record for this episode. Any PG projection derived from it is a "
        "rebuildable query index only, never authoritative.",
        "",
    ]
    return "\n".join(lines).rstrip() + "\n"


def render_episode_note(fields: dict[str, Any], *, body: str | None = None) -> str:
    """Render an episode note: YAML frontmatter (the schema-validated source of truth)
    plus a short human-readable body.

    ``body`` is an explicit preservation path for an existing human-edited body. New notes and
    notes whose body is still machine-generated use the canonical body derived from ``fields``.
    """
    fm: dict[str, Any] = {"artifact_class": ARTIFACT_CLASS}
    for name in _FRONTMATTER_FIELDS:
        if name in fields:
            fm[name] = fields[name]

    return dump_frontmatter(fm, _canonical_body(fields) if body is None else body)


def parse_episode_note_document(text: str) -> tuple[dict[str, Any], str]:
    """Parse both the schema fields and markdown body from an Episode note."""
    data, body = load_frontmatter(text)
    fields = {name: data[name] for name in _FRONTMATTER_FIELDS if name in data}
    return fields, body


def parse_episode_note(text: str) -> dict[str, Any]:
    """Parse an episode note's frontmatter back into its situation-model fields."""
    fields, _body = parse_episode_note_document(text)
    return fields


def parse_validated_episode_note(text: str) -> dict[str, Any]:
    """Return a schema-valid episode note without hiding unknown frontmatter.

    ``artifact_class`` is rendering metadata, not part of the episode schema. All
    other raw frontmatter participates in validation before the projection or any
    other derived consumer accepts the note, so ``additionalProperties: false``
    cannot be bypassed by :func:`parse_episode_note`'s intentionally narrow view.
    """
    raw_fields = _strict_episode_frontmatter(text)
    raw_fields.pop("artifact_class", None)
    validate_episode_note_fields(raw_fields)
    return raw_fields


def _strict_episode_frontmatter(text: str) -> dict[str, Any]:
    """Parse episode frontmatter without the generic reader's YAML-error fallback."""
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != "---":
        return {}
    closing_index = next(
        (index for index, line in enumerate(lines[1:], start=1) if line.rstrip("\r\n") == "---"),
        None,
    )
    if closing_index is None:
        raise EpisodeFrontmatterParseError("unterminated episode frontmatter")
    try:
        fields = yaml.safe_load("".join(lines[1:closing_index])) or {}
    except yaml.YAMLError as exc:
        raise EpisodeFrontmatterParseError("invalid episode frontmatter YAML") from exc
    return fields if isinstance(fields, dict) else {}


__all__ = [
    "ARTIFACT_CLASS",
    "EpisodeFrontmatterParseError",
    "EPISODE_NOTES_DIR",
    "episode_note_rel_path",
    "parse_episode_note",
    "parse_episode_note_document",
    "parse_validated_episode_note",
    "render_episode_note",
]
