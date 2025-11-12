from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

RELATIONS_PATH = Path("data") / "golden" / "relations.json"
SUPPORTED_RELATIONS = {"supports", "extends", "contradicts", "derived_from"}


def _load_promoted() -> List[Dict[str, Any]]:
    if not RELATIONS_PATH.exists():
        return []
    try:
        data = json.loads(RELATIONS_PATH.read_text(encoding="utf-8")) or {}
    except json.JSONDecodeError:
        return []
    promoted = data.get("promoted") or []
    return [entry for entry in promoted if isinstance(entry, dict)]


def _normalized_relations(entry: Dict[str, Any]) -> List[Dict[str, str]]:
    rels = entry.get("relations") or []
    normalized: List[Dict[str, str]] = []
    for item in rels:
        if isinstance(item, dict):
            target = str(item.get("target") or item.get("id") or "").strip()
            rel_type = str(item.get("type") or item.get("rel") or "supports").strip().lower()
        else:
            target = str(item).strip()
            rel_type = "supports"
        if rel_type not in SUPPORTED_RELATIONS:
            rel_type = "supports"
        normalized.append({"target": target, "type": rel_type})
    return normalized


def relation_metrics() -> dict[str, float]:
    promoted = _load_promoted()
    total_objects = len(promoted)
    if total_objects == 0:
        return {"coverage": 0.0, "validity": 0.0, "total_objects": 0, "total_relations": 0}
    objects_with_relations = 0
    valid_pairs = 0
    total_pairs = 0
    for entry in promoted:
        normalized = _normalized_relations(entry)
        total_pairs += len(normalized)
        if any(rel["target"] and rel["type"] in SUPPORTED_RELATIONS for rel in normalized):
            objects_with_relations += 1
        for rel in normalized:
            if rel["target"] and rel["type"] in SUPPORTED_RELATIONS:
                valid_pairs += 1
    coverage = (objects_with_relations / total_objects) * 100.0 if total_objects else 0.0
    validity = (valid_pairs / total_pairs) * 100.0 if total_pairs else 0.0
    return {
        "coverage": coverage,
        "validity": validity,
        "total_objects": float(total_objects),
        "total_relations": float(total_pairs),
    }


def promotion_relation_coverage() -> float:
    return relation_metrics()["coverage"]


__all__ = ["promotion_relation_coverage", "relation_metrics", "RELATIONS_PATH"]
