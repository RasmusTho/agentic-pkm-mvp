from __future__ import annotations

import uuid
from pathlib import Path

from app.write_guard import DEFAULT_WRITE_GUARD
from scripts.yaml_roundtrip import dump_frontmatter, load_frontmatter


def ensure_note_uuid(path: Path) -> str:
    resolved = Path(path).resolve()
    text = resolved.read_text(encoding="utf-8")
    frontmatter, body = load_frontmatter(text)
    existing = str(frontmatter.get("uuid") or "").strip()
    if existing:
        return existing

    new_uuid = str(uuid.uuid4())
    frontmatter["uuid"] = new_uuid
    DEFAULT_WRITE_GUARD.assert_writes_allowed("ensure uuid")
    resolved.write_text(dump_frontmatter(frontmatter, body), encoding="utf-8")
    return new_uuid


__all__ = ["ensure_note_uuid"]
