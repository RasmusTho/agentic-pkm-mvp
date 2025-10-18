from __future__ import annotations

import re
from pathlib import Path
from typing import Optional


SLUG_PATTERN = re.compile(r"[^a-z0-9]+")


def slugify(title: str) -> str:
    slug = SLUG_PATTERN.sub("-", title.lower()).strip("-")
    return slug or "untitled"


def ensure_vault_file(
    vault_root: Path,
    title: str,
    body: str,
    frontmatter: Optional[str] = None,
) -> Path:
    """
    Persist a markdown document under the given vault.

    Returns the path relative to the vault root.
    """
    vault_root.mkdir(parents=True, exist_ok=True)
    slug = slugify(title)
    rel_path = Path(f"{slug}.md")
    target = vault_root / rel_path
    parts = [frontmatter or "", body.strip(), ""]
    content = "\n".join(part for part in parts if part)
    target.write_text(content, encoding="utf-8")
    return rel_path
