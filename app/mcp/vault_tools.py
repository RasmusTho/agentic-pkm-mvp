from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from app.knowledge.write_ops import write_note_relative


class VaultToolError(Exception):
    """Raised when vault-backed MCP actions cannot proceed."""


def _as_path(value: Any) -> Path | None:
    if isinstance(value, Path):
        return value
    if isinstance(value, str) and value.strip():
        return Path(value).expanduser()
    return None


def get_vault_root(settings: Mapping[str, Any] | None = None) -> Path:
    """Return the configured vault root directory."""

    candidates: list[Any] = []
    if settings:
        for key in ("vault_root", "root", "path"):
            if key in settings:
                candidates.append(settings[key])
        vault_settings = settings.get("vault")
        if isinstance(vault_settings, Mapping):
            for key in ("root", "path"):
                if key in vault_settings:
                    candidates.append(vault_settings[key])
    env_root = os.getenv("MCP_VAULT_ROOT") or os.getenv("VAULT_DIR")
    if env_root:
        candidates.append(env_root)
    default = Path("vault")
    if default.exists():
        candidates.append(default)
    for candidate in candidates:
        path = _as_path(candidate)
        if path:
            return path
    raise VaultToolError("Vault root is not configured")


def _slugify(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return normalized or "note"


def _next_available_path(directory: Path, slug: str) -> Path:
    candidate = directory / f"{slug}.md"
    counter = 2
    while candidate.exists():
        candidate = directory / f"{slug}-{counter}.md"
        counter += 1
    return candidate


def append_note(
    *,
    title: str,
    body: str,
    tags: Sequence[str] | None = None,
    metadata: Mapping[str, Any] | None = None,
    vault_root: Path | str | None = None,
    settings: Mapping[str, Any] | None = None,
    relative_dir: str = "_mcp",
) -> Path:
    """Create a markdown note with frontmatter inside the vault."""

    if not isinstance(title, str) or not title.strip():
        raise VaultToolError("title is required")
    if not isinstance(body, str) or not body.strip():
        raise VaultToolError("body is required")
    root = _as_path(vault_root) if vault_root else get_vault_root(settings)
    if root is None:
        raise VaultToolError("vault root is required")
    target_dir = root / relative_dir
    target_dir.mkdir(parents=True, exist_ok=True)
    slug = _slugify(title)
    note_path = _next_available_path(target_dir, slug)
    note_tags = [tag for tag in (tags or []) if isinstance(tag, str) and tag.strip()]
    frontmatter: dict[str, Any] = {"title": title.strip()}
    if note_tags:
        frontmatter["tags"] = note_tags
    if metadata:
        frontmatter["metadata"] = metadata
    yaml_block = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True).strip()
    body_block = body.rstrip()
    content = f"---\n{yaml_block}\n---\n\n{body_block}\n"
    write_note_relative(note_path.relative_to(root).as_posix(), content, vault_root=root)
    return note_path


__all__ = ["VaultToolError", "append_note", "get_vault_root"]
