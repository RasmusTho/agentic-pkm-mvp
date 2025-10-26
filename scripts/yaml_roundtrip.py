from __future__ import annotations

from typing import Any, Tuple

import yaml


def load_frontmatter(text: str) -> Tuple[dict[str, Any], str]:
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            fm_block = parts[1]
            body = parts[2]
            data = yaml.safe_load(fm_block) or {}
            if not isinstance(data, dict):
                data = {}
            return data, body.lstrip("\n")
    return {}, text


def dump_frontmatter(frontmatter: dict[str, Any], body: str) -> str:
    fm_dump = yaml.safe_dump(frontmatter or {}, sort_keys=False).strip()
    body_stripped = body.rstrip("\n")
    body_section = f"\n\n{body_stripped}\n" if body_stripped else "\n"
    return f"---\n{fm_dump}\n---{body_section}"
