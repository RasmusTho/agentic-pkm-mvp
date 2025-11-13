from __future__ import annotations

import re
from pathlib import Path
from typing import List, Tuple

SECTION_H2 = re.compile(r"(?m)^## +(?P<name>.+?)\s*$")
FENCE = re.compile(r"(?s)```yaml settings\s*(?P<body>.+?)```")


def split_sections(md: str) -> List[Tuple[str, str]]:
    parts: List[Tuple[str, str]] = []
    last = 0
    current = ("root", 0)
    for match in SECTION_H2.finditer(md):
        name = match.group("name").strip()
        start = match.start()
        if current[0] != "root" or match.start() != 0:
            parts.append((current[0], md[current[1]:start]))
        current = (name, match.end())
        last = match.end()
    parts.append((current[0], md[current[1]:]))
    return parts


def find_fenced_settings(md: str) -> str | None:
    found = FENCE.search(md)
    return found.group("body").strip() if found else None


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")
