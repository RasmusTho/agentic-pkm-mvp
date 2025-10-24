from __future__ import annotations
import os, json, uuid, re
from typing import Any, Iterable
from uuid import UUID
import psycopg
from psycopg.rows import dict_row
from app.agents.base.audit import audit_log
from app.search.embeddings import embed_text

_MD_RE = re.compile(r"^#{1,6}\s+", re.M)
_CLEAN_RE = re.compile(r"[^\w\s]", re.UNICODE)

def _dsn() -> str:
    return (os.environ.get("DATABASE_URL") or "postgresql+psycopg://app:app@127.0.0.1:15432/app").replace("postgresql+psycopg://","postgresql://")

def _fetch_texts(oids: Iterable[str]) -> dict[str, str]:
    items: dict[str,str] = {}
    ids = list(oids)
    if not ids:
        return items
    with psycopg.connect(_dsn(), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            ids_uuid = [UUID(x) for x in ids]
            cur.execute("SELECT id, payload FROM objects WHERE id = ANY(%s)", (ids_uuid,))
            for row in cur.fetchall():
                payload = row["payload"] or {}
                text = payload.get("text") or payload.get("content") or ""
                if isinstance(text, str):
                    items[str(row["id"])] = text
    return items

def _prep(text: str) -> str:
    t = _MD_RE.sub("", text)
    t = t.lower()
    t = _CLEAN_RE.sub(" ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t

def _cosine(a: list[float], b: list[float]) -> float:
    s = 0.0
    for i in range(min(len(a), len(b))):
        s += a[i] * b[i]
    return float(s)

def _shingles(tokens: list[str], k: int = 2) -> set[tuple[str, ...]]:
    if not tokens:
        return set()
    if k <= 1:
        return set((tok,) for tok in tokens)
    out = set()
    for i in range(len(tokens) - k + 1):
        out.add(tuple(tokens[i:i+k]))
    return out

def _jaccard(a: list[str], b: list[str], k: int = 2) -> float:
    sa = _shingles(a, k=k)
    sb = _shingles(b, k=k)
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    inter = len(sa & sb)
    union = len(sa | sb)
    return inter / union if union else 0.0

def _overlap_ratio(a: list[str], b: list[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    sa = set(a)
    sb = set(b)
    inter = len(sa & sb)
    denom = min(len(sa), len(sb))
    return inter / denom if denom else 0.0

def _score_pair(text_i: str, text_j: str) -> float:
    p_i = _prep(text_i)
    p_j = _prep(text_j)
    cos = _cosine(embed_text(p_i), embed_text(p_j))
    toks_i = p_i.split()
    toks_j = p_j.split()
    jac = _jaccard(toks_i, toks_j, k=2)
    ovl = _overlap_ratio(toks_i, toks_j)
    return max(cos, jac, ovl)

def _pick_canonical(a: str, b: str) -> tuple[str,str]:
    return (a, b) if a < b else (b, a)

def dedupe(object_ids: list[str], *, threshold: float, trace_id: str) -> dict[str, Any]:
    texts = _fetch_texts(object_ids)
    ids = [k for k in object_ids if k in texts]
    if len(ids) < 2:
        return {"pairs": [], "decisions": 0}
    pairs: list[tuple[str,str,float]] = []
    for i in range(len(ids)):
        for j in range(i+1, len(ids)):
            oi, oj = ids[i], ids[j]
            sim = _score_pair(texts[oi], texts[oj])
            if sim >= threshold:
                pairs.append((oi, oj, sim))
    writes = 0
    with psycopg.connect(_dsn(), autocommit=True) as conn:
        with conn.cursor() as cur:
            for a, b, score in pairs:
                canon, dup = _pick_canonical(a, b)
                value = {"canonical_id": canon, "score": score}
                cur.execute(
                    "INSERT INTO decisions (id, object_id, key, value, created_at) VALUES (%s,%s,%s,%s::jsonb, now())",
                    (str(uuid.uuid4()), dup, "duplicate_of", json.dumps(value)),
                )
                writes += 1
    for a, b, score in pairs:
        canon, dup = _pick_canonical(a, b)
        audit_log(object_id=dup, agent="deduper", action="mark.duplicate", trace_id=trace_id, details={"canonical_id": canon, "score": score})
    return {"pairs": pairs, "decisions": writes}

def run(object_ids: list[str], *, threshold: float = 0.92, trace_id: str) -> dict[str, Any]:
    return dedupe(object_ids, threshold=threshold, trace_id=trace_id)
