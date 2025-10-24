from __future__ import annotations
import os, re, uuid, json
from typing import Any
import psycopg
from psycopg.rows import dict_row
from app.agents.base.audit import audit_log

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.M)
SENT_RE = re.compile(r"(?<=[.!?])\s+")

def _dsn() -> str:
    return (os.environ.get("DATABASE_URL") or "postgresql+psycopg://app:app@127.0.0.1:15432/app").replace("postgresql+psycopg://","postgresql://")

def _fetch_object(oid: str) -> dict[str, Any] | None:
    with psycopg.connect(_dsn(), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, payload FROM objects WHERE id=%s", (oid,))
            return cur.fetchone()

def _tokenize_words(text: str) -> list[tuple[int,int]]:
    spans = []
    i = 0
    for m in re.finditer(r"\S+", text):
        spans.append((m.start(), m.end()))
        i += 1
    return spans

def _split_sentences(text: str) -> list[tuple[int,int]]:
    if not text.strip():
        return []
    parts = []
    idx = 0
    for m in SENT_RE.finditer(text):
        parts.append((idx, m.start()))
        idx = m.end()
    parts.append((idx, len(text)))
    return parts

def _chunk_by_heading(text: str, *, max_tokens: int, overlap: int) -> list[tuple[int,int]]:
    heads = [(m.start(), m.end(), m.group(0)) for m in HEADING_RE.finditer(text)]
    if not heads:
        return _chunk_fallback(text, max_tokens=max_tokens, overlap=overlap)
    bounds: list[tuple[int,int]] = []
    sections = []
    for i, (s, e, _) in enumerate(heads):
        ns = heads[i+1][0] if i+1 < len(heads) else len(text)
        sections.append((s, ns))
    for (s, e) in sections:
        seg = text[s:e]
        seg_bounds = _chunk_fallback(seg, max_tokens=max_tokens, overlap=overlap, base=s)
        bounds.extend(seg_bounds)
    return bounds

def _chunk_fallback(text: str, *, max_tokens: int, overlap: int, base: int = 0) -> list[tuple[int,int]]:
    words = _tokenize_words(text)
    if not words:
        return []
    bounds: list[tuple[int,int]] = []
    start_idx = 0
    while start_idx < len(words):
        end_idx = min(start_idx + max_tokens, len(words))
        start_char = words[start_idx][0]
        end_char = words[end_idx - 1][1]
        sent_bounds = _nearest_sentence_end(text, end_char)
        if sent_bounds is not None and sent_bounds >= end_char:
            end_char = sent_bounds
        bounds.append((base + start_char, base + end_char))
        if end_idx == len(words):
            break
        start_idx = max(0, end_idx - overlap)
    return bounds

def _nearest_sentence_end(text: str, pos: int) -> int | None:
    puncts = ".!?"
    i = pos
    while i < len(text) and text[i] not in puncts:
        i += 1
        if i - pos > 200:
            return None
    if i < len(text) and text[i] in puncts:
        j = i + 1
        while j < len(text) and text[j].isspace():
            j += 1
        return j
    return None

def chunk_object(object_id: str, *, max_tokens: int = 800, overlap: int = 120, strategy: str = "heading_first", trace_id: str) -> dict:
    row = _fetch_object(object_id)
    if not row:
        raise ValueError("object not found")
    text: str = (row["payload"] or {}).get("text") or (row["payload"] or {}).get("content") or ""
    if not text:
        return {"object_id": object_id, "chunks": []}
    if strategy == "heading_first":
        spans = _chunk_by_heading(text, max_tokens=max_tokens, overlap=overlap)
    else:
        spans = _chunk_fallback(text, max_tokens=max_tokens, overlap=overlap)
    with psycopg.connect(_dsn(), autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM chunks WHERE object_id=%s", (object_id,))
            for idx, (a, b) in enumerate(spans):
                cur.execute(
                    "INSERT INTO chunks (id, object_id, idx, text, offset_start, offset_end, created_at) VALUES (%s,%s,%s,%s,%s,%s, now())",
                    (str(uuid.uuid4()), object_id, idx, text[a:b], a, b),
                )
    audit_log(object_id=object_id, agent="chunker", action="chunk", trace_id=trace_id, details={"count": len(spans), "strategy": strategy, "max_tokens": max_tokens, "overlap": overlap})
    return {"object_id": object_id, "count": len(spans), "spans": spans}

def run(object_id: str, *, max_tokens: int = 800, overlap: int = 120, strategy: str = "heading_first", trace_id: str) -> dict:
    return chunk_object(object_id, max_tokens=max_tokens, overlap=overlap, strategy=strategy, trace_id=trace_id)
