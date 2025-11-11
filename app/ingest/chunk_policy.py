from __future__ import annotations
from typing import List


def split_into_chunks(text: str, max_chars: int = 3000) -> List[str]:
    out: List[str] = []
    cur = ""
    for line in text.splitlines(keepends=True):
        if len(cur) + len(line) > max_chars and cur:
            out.append(cur)
            cur = line
        else:
            cur += line
    if cur:
        out.append(cur)
    return out
