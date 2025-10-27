from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .ingest_md import parse_markdown
from .rules import compile_rules, score_for

def walk_markdown_files(root: Path) -> List[Path]:
    return [p for p in root.rglob("*.md") if p.is_file()]

def build_index(root: Path, rules_cfg: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rules = compile_rules(rules_cfg)
    docs: List[Dict[str, Any]] = []
    for p in walk_markdown_files(root):
        meta, body = parse_markdown(p)
        include, weight = score_for(meta, rules)
        if not include:
            continue
        docs.append({"path": str(p), "meta": meta, "body": body, "weight": weight})
    return docs

def query(index: List[Dict[str, Any]], term: str, limit: int = 10) -> List[Tuple[str, float]]:
    term_l = term.lower()
    ranked: List[Tuple[str, float]] = []
    for doc in index:
        body = doc["body"].lower()
        hit = term_l in body
        if hit:
            ranked.append((doc["path"], 1.0 * doc["weight"]))
    ranked.sort(key=lambda x: x[1], reverse=True)
    return ranked[:limit]
