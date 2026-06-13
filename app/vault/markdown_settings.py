from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml


CONFLICT_MARKERS = ("<<<<<<<", "=======", ">>>>>>>")


class MarkdownSettingsError(ValueError):
    """Raised when a Markdown settings file cannot be applied safely."""


@dataclass(frozen=True)
class MarkdownSettingsDocument:
    path: Path
    frontmatter: dict[str, Any]
    body: str


def has_conflict_markers(text: str) -> bool:
    in_conflict = False
    saw_separator = False
    for line in text.splitlines():
        if line.startswith("<<<<<<<"):
            in_conflict = True
            saw_separator = False
            continue
        if in_conflict and line.startswith("======="):
            saw_separator = True
            continue
        if in_conflict and saw_separator and line.startswith(">>>>>>>"):
            return True
    return False


def split_markdown_settings(text: str, *, path: Path | None = None) -> tuple[dict[str, Any], str]:
    if has_conflict_markers(text):
        raise MarkdownSettingsError(f"settings file contains Git conflict markers: {path or '<memory>'}")
    if not text.startswith("---\n"):
        raise MarkdownSettingsError(f"settings file is missing YAML frontmatter: {path or '<memory>'}")
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise MarkdownSettingsError(f"settings frontmatter is malformed: {path or '<memory>'}")
    try:
        data = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError as exc:
        raise MarkdownSettingsError(f"settings YAML is invalid in {path or '<memory>'}: {exc}") from exc
    if not isinstance(data, dict):
        raise MarkdownSettingsError(f"settings frontmatter must be a mapping: {path or '<memory>'}")
    body = parts[2]
    if body.startswith("\n"):
        body = body[1:]
    return data, body


def render_markdown_settings(frontmatter: Mapping[str, Any], body: str) -> str:
    yaml_block = yaml.safe_dump(dict(frontmatter), sort_keys=False, allow_unicode=True).strip()
    normalized_body = body if body.startswith("\n") else f"\n{body}"
    if not normalized_body.endswith("\n"):
        normalized_body = f"{normalized_body}\n"
    return f"---\n{yaml_block}\n---\n{normalized_body}"


class MarkdownSettingsStore:
    def read(self, path: Path) -> MarkdownSettingsDocument:
        text = path.read_text(encoding="utf-8")
        frontmatter, body = split_markdown_settings(text, path=path)
        return MarkdownSettingsDocument(path=path, frontmatter=frontmatter, body=body)

    def write_missing(self, path: Path, frontmatter: Mapping[str, Any], body: str) -> bool:
        if path.exists():
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_markdown_settings(frontmatter, body), encoding="utf-8")
        return True

    def write_frontmatter(self, path: Path, frontmatter: Mapping[str, Any], *, body: str | None = None) -> None:
        existing_body = body
        if path.exists() and existing_body is None:
            existing_body = self.read(path).body
        if existing_body is None:
            existing_body = ""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_markdown_settings(frontmatter, existing_body), encoding="utf-8")


__all__ = [
    "CONFLICT_MARKERS",
    "MarkdownSettingsDocument",
    "MarkdownSettingsError",
    "MarkdownSettingsStore",
    "has_conflict_markers",
    "render_markdown_settings",
    "split_markdown_settings",
]
