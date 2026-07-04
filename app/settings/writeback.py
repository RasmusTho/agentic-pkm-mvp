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
    # Guard-at-seam (#2809, formal-model.md Divergence F-B): this is the single
    # physical write function behind both `writeback_settings_block` and the
    # `_update_reference` auto-heal call site in app/settings/compiler.py — one
    # assert here covers every settings-compile writeback caller. Assert
    # before any file mutation so a blocked write never leaves a partially
    # compiled settings file on disk.
    #
    # Imported lazily (not at module level): app.write_guard -> health_contract
    # -> events.outbox -> outbox.events -> events.schema -> settings.runtime
    # -> settings.compiler -> settings.writeback closes a circular import back
    # to this module. Every other WriteGuard call site in the repo imports it
    # top-level; this module is the one exception forced by that cycle.
    from app.write_guard import DEFAULT_WRITE_GUARD

    DEFAULT_WRITE_GUARD.assert_writes_allowed("settings.compile.writeback")
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
