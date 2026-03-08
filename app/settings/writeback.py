from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import yaml

from app.knowledge.write_ops import write_note_from_absolute

from .loader import read_text

FENCE_START = "```yaml settings"
FENCE_END = "```"


def _infer_vault_root(path: Path) -> Path:
    for parent in path.parents:
        if parent.name == "@Settings":
            return parent.parent
    return path.parent


def write_markdown_via_knowledge_port(path: Path, markdown: str, *, vault_root: Path | None = None) -> None:
    resolved = path.expanduser().resolve()
    root = (vault_root or _infer_vault_root(resolved)).expanduser().resolve()
    write_note_from_absolute(resolved, markdown, vault_root=root)


def writeback_settings_block(path: Path, canonical: Dict[str, Any], *, vault_root: Path | None = None) -> None:
    markdown = read_text(path)
    body = yaml.safe_dump(canonical, allow_unicode=True, sort_keys=True)
    replacement = f"{FENCE_START}\n{body}{FENCE_END}"
    if FENCE_START in markdown:
        head, tail = markdown.split(FENCE_START, 1)
        if FENCE_END in tail:
            _, rest = tail.split(FENCE_END, 1)
            markdown = f"{head}{replacement}{rest}"
        else:
            markdown = f"{head}{replacement}"
    else:
        markdown = markdown.rstrip() + "\n\n" + replacement + "\n"
    write_markdown_via_knowledge_port(path, markdown, vault_root=vault_root)
