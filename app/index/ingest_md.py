from __future__ import annotations
from pathlib import Path
from typing import Dict, Any, Tuple

import yaml

def parse_markdown(path: Path) -> Tuple[Dict[str, Any], str]:
    text = path.read_text(encoding="utf-8")
    if text.startswith("---"):
        _, fm, body = text.split("---", 2)
        meta = yaml.safe_load(fm) or {}
        return meta, body.strip()
    return {}, text.strip()
