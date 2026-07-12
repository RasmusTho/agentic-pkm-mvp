"""Render/parse episode notes as vault markdown (ADR-0051 OD-2: note-serialized).

One markdown note per episode: YAML frontmatter carries the parsed situation-model fields
(the schema-validated source of truth); a short human-readable body documents the shape
inline, mirroring ``app.heimdal.settings_notes.render_note``/``parse_note`` and reusing the
same shared frontmatter round-trip helper (never hand-rolled YAML).
"""

from __future__ import annotations

from typing import Any

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


def episode_note_rel_path(episode_id: str) -> str:
    return f"{EPISODE_NOTES_DIR}/{episode_id}.md"


def render_episode_note(fields: dict[str, Any]) -> str:
    """Render an episode note: YAML frontmatter (the schema-validated source of truth)
    plus a short human-readable body."""
    fm: dict[str, Any] = {"artifact_class": ARTIFACT_CLASS}
    for name in _FRONTMATTER_FIELDS:
        if name in fields:
            fm[name] = fields[name]

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
    body = "\n".join(lines).rstrip() + "\n"
    return dump_frontmatter(fm, body)


def parse_episode_note(text: str) -> dict[str, Any]:
    """Parse an episode note's frontmatter back into its situation-model fields."""
    data, _body = load_frontmatter(text)
    return {name: data[name] for name in _FRONTMATTER_FIELDS if name in data}


__all__ = [
    "ARTIFACT_CLASS",
    "EPISODE_NOTES_DIR",
    "episode_note_rel_path",
    "parse_episode_note",
    "render_episode_note",
]
