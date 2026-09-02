from __future__ import annotations

import uuid
from pathlib import Path

from app.knowledge.write_ops import read_note_text_with_version, write_note_from_absolute
from app.rebuildability.product_total_loss import parse_bounded_frontmatter
from app.write_guard import DEFAULT_WRITE_GUARD
from scripts.yaml_roundtrip import dump_frontmatter


def _new_note_uuid() -> str:
    """Allocate a fresh note-identity UUID.

    This is the single, single-purpose allocation seam for a *note's* identity
    (#3622). Infrastructure UUIDs generated elsewhere on the write path — e.g.
    the knowledge adapter's ``.rewrite-swap`` staging name and the
    ``concurrent-save-*`` conflict-artifact writer identity — are a separate
    concern and are deliberately not routed through here, so a test that counts
    note-identity allocations by patching this seam is not confounded by them.
    """
    return str(uuid.uuid4())


def ensure_note_uuid(
    path: Path,
    *,
    vault_root: Path | str,
    preferred_uuid: str | None = None,
    write_action: str = "ensure uuid",
) -> str:
    resolved = Path(path).resolve()
    root = Path(vault_root).expanduser().resolve()
    resolved.relative_to(root)
    text, expected_version = read_note_text_with_version(resolved)
    frontmatter, body, _ = parse_bounded_frontmatter(text)
    existing = str(frontmatter.get("uuid") or "").strip()
    if existing:
        return existing

    candidate = str(preferred_uuid or "").strip()
    if not candidate:
        candidate = _new_note_uuid()
    frontmatter["uuid"] = candidate
    DEFAULT_WRITE_GUARD.assert_writes_allowed(write_action)
    write_note_from_absolute(
        resolved,
        dump_frontmatter(frontmatter, body),
        vault_root=root,
        action=write_action,
        expected_version=expected_version,
    )
    return candidate


__all__ = ["ensure_note_uuid"]
