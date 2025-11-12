from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence
from uuid import UUID

from app.agents.base.audit import audit_log
from app.stores import get_relation_index
from app.stores.base import RelationIndex

SUPPORTED_RELATION_TYPES = ("supports", "extends", "contradicts", "derived_from")
_LINE_PATTERNS = (
    (re.compile(r"^\s*see also[:\-]\s*(?P<targets>.+)$", re.IGNORECASE), "supports", "body.see_also"),
    (re.compile(r"^\s*extends[:\-]\s*(?P<targets>.+)$", re.IGNORECASE), "extends", "body.extends"),
    (re.compile(r"^\s*contradicts[:\-]\s*(?P<targets>.+)$", re.IGNORECASE), "contradicts", "body.contradicts"),
    (re.compile(r"^\s*derived from[:\-]\s*(?P<targets>.+)$", re.IGNORECASE), "derived_from", "body.derived_from"),
)
_FIELD_RELATION_MAP = {
    "supports": "supports",
    "extends": "extends",
    "contradicts": "contradicts",
    "derived_from": "derived_from",
    "relations": None,
    "related": "supports",
    "see_also": "supports",
}


@dataclass(frozen=True)
class RelationCandidate:
    target: str
    rel: str
    source: str
    evidence: str | None = None


def _normalize_targets(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        raw = [value]
    elif isinstance(value, Sequence):
        raw = list(value)  # type: ignore[list-item]
    else:
        raw = [value]
    normalized: list[str] = []
    for item in raw:
        if item is None:
            continue
        if isinstance(item, str):
            token = item.strip()
            if not token:
                continue
            normalized.append(token)
            continue
        if isinstance(item, Mapping):
            target = item.get("target") or item.get("id") or item.get("doc_id") or item.get("object_id")
            if target:
                normalized.append(str(target).strip())
            continue
        normalized.append(str(item).strip())
    return [t for t in normalized if t]


def _parse_typed_token(token: str) -> tuple[str, str]:
    if ":" in token:
        prefix, suffix = token.split(":", 1)
        rel = prefix.strip().lower()
        candidate = suffix.strip()
        if rel in SUPPORTED_RELATION_TYPES and candidate:
            return rel, candidate
    return "supports", token.strip()


def extract_semantic_relations(metadata: Mapping[str, object] | None, body: str | None) -> list[RelationCandidate]:
    metadata = metadata or {}
    body = body or ""
    candidates: list[RelationCandidate] = []
    seen: set[tuple[str, str]] = set()

    for field, rel_type in _FIELD_RELATION_MAP.items():
        raw = metadata.get(field)
        if raw is None:
            continue
        entries = _normalize_targets(raw)
        for entry in entries:
            entry_rel = rel_type or "supports"
            if rel_type is None:
                entry_rel, entry = _parse_typed_token(entry)
            entry_rel = entry_rel if entry_rel in SUPPORTED_RELATION_TYPES else "supports"
            key = (entry.lower(), entry_rel)
            if not entry or key in seen:
                continue
            seen.add(key)
            candidates.append(RelationCandidate(target=entry, rel=entry_rel, source=f"frontmatter.{field}"))

    tags = metadata.get("tags") or metadata.get("keywords")
    for entry in _normalize_targets(tags):
        rel_name, target = _parse_typed_token(entry)
        key = (target.lower(), rel_name)
        if not target or key in seen:
            continue
        seen.add(key)
        candidates.append(RelationCandidate(target=target, rel=rel_name, source="frontmatter.tags"))

    for line in body.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        for pattern, rel_name, source in _LINE_PATTERNS:
            match = pattern.match(stripped)
            if not match:
                continue
            targets = match.group("targets")
            for token in _split_targets(targets):
                key = (token.lower(), rel_name)
                if not token or key in seen:
                    continue
                seen.add(key)
                candidates.append(RelationCandidate(target=token, rel=rel_name, source=source, evidence=stripped))
            break

    return candidates


def _split_targets(value: str) -> list[str]:
    chunks = re.split(r"[;,]", value)
    results: list[str] = []
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
        _, target = _parse_typed_token(chunk)
        target = target.strip()
        if target:
            results.append(target)
    return results


def register_relation_candidates(
    src: UUID,
    candidates: Iterable[RelationCandidate],
    *,
    relation_index: RelationIndex | None = None,
) -> tuple[int, int]:
    rel_index = relation_index or get_relation_index()
    added = 0
    missing = 0
    seen: set[tuple[UUID, str]] = set()
    for candidate in candidates:
        rel_type = candidate.rel if candidate.rel in SUPPORTED_RELATION_TYPES else "supports"
        try:
            dst = UUID(str(candidate.target))
        except Exception:
            missing += 1
            audit_log(
                object_id=str(src),
                agent="promotion-gate",
                action="relation.missing",
                trace_id=None,
                details={"target": candidate.target, "rel": rel_type, "source": candidate.source},
            )
            continue
        dedupe_key = (dst, rel_type)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        payload = {"source": candidate.source}
        if candidate.evidence:
            payload["evidence"] = candidate.evidence
        rel_index.link(src, dst, rel=rel_type, payload=payload)
        added += 1
        audit_log(
            object_id=str(src),
            agent="promotion-gate",
            action="relation.added",
            trace_id=None,
            details={"dst": str(dst), "rel": rel_type, "source": candidate.source},
        )
    return added, missing


__all__ = [
    "RelationCandidate",
    "SUPPORTED_RELATION_TYPES",
    "extract_semantic_relations",
    "register_relation_candidates",
]
