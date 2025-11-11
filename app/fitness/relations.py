from __future__ import annotations

import json
from pathlib import Path

RELATIONS_PATH = Path("data") / "golden" / "relations.json"


def promotion_relation_coverage() -> float:
    """
    Returns the percent of promoted items that have at least one relation in the golden sample.
    """
    if not RELATIONS_PATH.exists():
        return 0.0
    data = json.loads(RELATIONS_PATH.read_text(encoding="utf-8")) or {}
    promoted = data.get("promoted") or []
    if not promoted:
        return 0.0
    total = len(promoted)
    with_links = sum(1 for entry in promoted if entry.get("relations"))
    return (with_links / total) * 100.0


__all__ = ["promotion_relation_coverage"]
