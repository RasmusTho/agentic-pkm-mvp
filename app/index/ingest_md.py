from __future__ import annotations
from pathlib import Path
from typing import Dict, Any, Tuple

import yaml

def _split_frontmatter(text: str) -> Tuple[Dict[str, Any], str]:
    if not text.startswith("---"):
        return {}, text.strip()
    lines = text.splitlines()
    if not lines:
        return {}, ""
    if lines[0].strip() != "---":
        return {}, text.strip()
    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        return {}, text.strip()
    fm_text = "\n".join(lines[1:end_idx])
    body = "\n".join(lines[end_idx + 1 :])
    try:
        meta = yaml.safe_load(fm_text) or {}
        if not isinstance(meta, dict):
            meta = {}
    except Exception:
        meta = {}
    return meta, body.strip()

def parse_markdown(path: Path) -> Tuple[Dict[str, Any], str]:
    text = path.read_text(encoding="utf-8")
    meta, body = _split_frontmatter(text)
    return meta, body
