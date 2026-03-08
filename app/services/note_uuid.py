from __future__ import annotations

import uuid
from pathlib import Path

from app.knowledge.locators import make_note_locator_from_absolute
from app.knowledge.service import resolve_knowledge_port
from app.write_guard import DEFAULT_WRITE_GUARD
from scripts.yaml_roundtrip import dump_frontmatter, load_frontmatter


def ensure_note_uuid(path: Path, *, preferred_uuid: str | None = None) -> str:
    resolved = Path(path).resolve()
    text = resolved.read_text(encoding="utf-8")
    frontmatter, body = load_frontmatter(text)
    existing = str(frontmatter.get("uuid") or "").strip()
    if existing:
        return existing

    candidate = str(preferred_uuid or "").strip()
    if not candidate:
        candidate = str(uuid.uuid4())
    frontmatter["uuid"] = candidate
    DEFAULT_WRITE_GUARD.assert_writes_allowed("ensure uuid")
    root = Path(resolved.anchor) if resolved.anchor else Path("/")
    locator = make_note_locator_from_absolute(resolved, vault_root=root)
    port = resolve_knowledge_port(vault_root=root)
    port.write_note(locator, dump_frontmatter(frontmatter, body))
    return candidate


__all__ = ["ensure_note_uuid"]
