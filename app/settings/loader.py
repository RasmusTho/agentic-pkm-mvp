from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import List, Tuple

SECTION_H2 = re.compile(r"(?m)^## +(?P<name>.+?)\s*$")


@lru_cache(maxsize=None)
def _fence_pattern(tag: str) -> re.Pattern[str]:
    """Compile the fenced ```yaml <tag>`` block pattern for one fence tag.

    The closing fence is line-anchored (a ``` alone at the start of a line)
    so an embedded triple-backtick inside the YAML body cannot silently
    truncate the block -- a truncated match would otherwise load a partial
    document without any error. Both fence lines tolerate CRLF line
    endings: in multiline mode `$` anchors *before* the `\n`, leaving a
    stray `\r` unconsumed, so the closing fence must explicitly allow
    `\r?` before end-of-line or a well-formed CRLF document silently
    fails to match.
    """
    return re.compile(rf"(?ms)^```yaml {re.escape(tag)}[ \t]*\r?\n(?P<body>.*?)^```[ \t]*\r?$")


FENCE = _fence_pattern("settings")


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


def find_fenced_block(md: str, tag: str) -> str | None:
    """Find the body of a fenced ```yaml <tag>`` block, or None if absent.

    Shared by the settings substrate (tag ``settings``) and the Episode
    stream registry (tag ``stream-registry``, `app.episodes.stream_registry`)
    -- one fence grammar, parameterized by tag, never per-caller regex forks.
    """
    found = _fence_pattern(tag).search(md)
    return found.group("body").strip() if found else None


def find_fenced_blocks(md: str, tag: str) -> List[str]:
    """Return every complete fenced block for callers that must prove uniqueness."""
    return [match.group("body").strip() for match in _fence_pattern(tag).finditer(md)]


def find_fenced_settings(md: str) -> str | None:
    return find_fenced_block(md, "settings")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")
