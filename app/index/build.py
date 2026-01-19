from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, List, Tuple
import fnmatch

from app.vault.paths import get_vault_inbox_dir_rel

from .ingest_md import parse_markdown
from .rules import compile_rules, score_for

def walk_markdown_files(root: Path, ignore_glob: List[str]) -> List[Path]:
    files = [p for p in root.rglob("*.md") if p.is_file()]
    if not ignore_glob:
        return files
    out: List[Path] = []
    for p in files:
        rel = str(p.relative_to(root))
        if any(fnmatch.fnmatch(rel, pat) for pat in ignore_glob):
            continue
        out.append(p)
    return out


def _is_inbox_path(rel_path: str, inbox_dir_rel: str) -> bool:
    normalized = rel_path.replace("\\", "/")
    prefix = f"{inbox_dir_rel.strip('/')}/"
    return normalized.startswith(prefix) or f"/{prefix}" in normalized


def infer_meta_defaults(rel_path: str, meta: Dict[str, Any], inbox_dir_rel: str) -> Dict[str, Any]:
    if "review_state" not in meta:
        if _is_inbox_path(rel_path, inbox_dir_rel):
            meta["review_state"] = "inbox"
        elif rel_path.startswith("9_Extras/Archive/") or "/9_Extras/Archive/" in rel_path:
            meta["review_state"] = "archived"
        else:
            meta["review_state"] = "processed"
    return meta


def build_index(root: Path, rules_cfg: List[Dict[str, Any]], ignore_glob: List[str]) -> List[Dict[str, Any]]:
    rules = compile_rules(rules_cfg)
    docs: List[Dict[str, Any]] = []
    inbox_dir_rel = get_vault_inbox_dir_rel(root)
    for p in walk_markdown_files(root, ignore_glob):
        meta, body = parse_markdown(p)
        rel = str(p.relative_to(root))
        meta = infer_meta_defaults(rel, meta or {}, inbox_dir_rel)
        include, weight = score_for(meta, rules)
        if not include:
            continue
        docs.append({"path": str(p), "meta": meta, "body": body, "weight": weight})
    return docs


def query(index: List[Dict[str, Any]], term: str, limit: int = 10) -> List[Tuple[str, float]]:
    term_l = term.lower()
    ranked: List[Tuple[str, float]] = []
    for doc in index:
        if term_l in doc["body"].lower():
            ranked.append((doc["path"], 1.0 * doc["weight"]))
    ranked.sort(key=lambda x: x[1], reverse=True)
    return ranked[:limit]


def build_index_from_settings(settings: Dict[str, Any]) -> List[Dict[str, Any]]:
    root = Path(settings["ingest"]["active_vault_path"])
    rules_cfg = settings["index"]["rules"]
    ignore = settings["ingest"].get("ignore_glob", [])
    return build_index(root, rules_cfg, ignore)
