from __future__ import annotations
import json, uuid, re
from typing import Any, Iterable
import psycopg
from psycopg.rows import dict_row
from app.memory.store import remember, recall

def _dsn() -> str:
    url = (os.environ.get("DATABASE_URL") or "postgresql+psycopg://app:app@127.0.0.1:15432/app").replace("postgresql+psycopg://","postgresql://")
    return url

import os
def _fetch_payload(object_id: str) -> dict[str, Any]:
    with psycopg.connect(_dsn(), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT payload FROM objects WHERE id=%s", (object_id,))
            row = cur.fetchone()
            return row["payload"] if row else {}

def _text_from_payload(p: dict[str, Any]) -> str:
    title = (p.get("title") or "").strip()
    text = (p.get("text") or p.get("content") or "").strip()
    if title and text:
        return f"{title}\n\n{text}"
    return title or text or ""

def _split_heading_first(text: str) -> list[tuple[str,int,int]]:
    spans = []
    if not text.strip():
        return spans
    lines = text.splitlines(keepends=False)
    idxs = [i for i,l in enumerate(lines) if re.match(r"^\s*#\s+", l)]
    idxs = [0] + idxs if 0 not in idxs else idxs
    idxs = sorted(set(idxs))
    idxs.append(len(lines))
    for a,b in zip(idxs[:-1], idxs[1:]):
        part = "\n".join(lines[a:b]).strip()
        if not part:
            continue
        start = len("\n".join(lines[:a])) + (1 if a>0 else 0)
        end = start + len(part)
        spans.append((part, start, end))
    if not spans:
        spans = [(text, 0, len(text))]
    return spans

def _tokenize(s: str) -> list[str]:
    return re.findall(r"\w+|[^\w\s]", s, re.UNICODE)

def _by_token_limit(spans: list[tuple[str,int,int]], max_tokens: int, overlap: int) -> list[tuple[str,int,int]]:
    if max_tokens <= 0:
        return spans
    out: list[tuple[str,int,int]] = []
    for part, start, end in spans:
        toks = _tokenize(part)
        if len(toks) <= max_tokens:
            out.append((part, start, end))
            continue
        i = 0
        while i < len(toks):
            j = min(i + max_tokens, len(toks))
            window = toks[i:j]
            chunk_text = "".join(window) if all(len(t)==1 and not t.isalnum() for t in window) else " ".join(window)
            # best-effort för att undvika brutna ord: trimma mellanslag
            chunk_text = re.sub(r"\s+\n", "\n", chunk_text).strip()
            # offset-approximation: relativa mot part
            rel_start = len(" ".join(toks[:i]))
            rel_end = rel_start + len(chunk_text)
            abs_start = start + rel_start
            abs_end = start + rel_end
            out.append((chunk_text, abs_start, abs_end))
            if j == len(toks):
                break
            i = max(0, j - overlap)
    return out

def audit_log(*, object_id: str | None, agent: str, action: str, trace_id: str | None, details: dict | None = None) -> None:
    with psycopg.connect(_dsn(), autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO audit(id, object_id, agent, action, ts, trace_id, details) VALUES (%s,%s,%s,%s, now(), %s, %s::jsonb)",
                (str(uuid.uuid4()), object_id, agent, action, trace_id, json.dumps(details or {})),
            )

def _write_chunks(object_id: str, pieces: Iterable[tuple[str,int,int]]) -> int:
    pieces_list = list(pieces)
    if not pieces_list:
        return 0
    with psycopg.connect(_dsn(), autocommit=True) as conn:
        with conn.cursor() as cur:
            idx = 0
            for text, s, e in pieces_list:
                cur.execute(
                    "INSERT INTO chunks(id, object_id, idx, offset_start, offset_end, text) VALUES (%s,%s,%s,%s,%s,%s)",
                    (str(uuid.uuid4()), object_id, idx, int(s), int(e), text),
                )
                idx += 1
    return len(pieces_list)

def chunk(object_id: str, *, max_tokens: int, overlap: int, strategy: str, trace_id: str) -> dict[str, Any]:
    p = _fetch_payload(object_id)
    full = _text_from_payload(p)
    if not full:
        audit_log(object_id=object_id, agent="chunker", action="empty_input", trace_id=trace_id, details={})
        return {"chunks": 0}
    if strategy == "heading_first":
        spans = _split_heading_first(full)
    else:
        spans = [(full, 0, len(full))]
    spans = _by_token_limit(spans, max_tokens=max_tokens, overlap=overlap)
    if not spans:
        spans = [(full, 0, len(full))]
    n = _write_chunks(object_id, spans)
    remember(
        agent="chunker",
        kind="chunked",
        object_id=object_id,
        trace_id=trace_id,
        data={
            "chunks": int(n),
            "max_tokens": int(max_tokens),
            "overlap": int(overlap),
            "strategy": str(strategy),
        },
    )
    audit_log(object_id=object_id, agent="chunker", action="chunk.done", trace_id=trace_id, details={"chunks": n})
    return {"chunks": n}

def run(object_id: str, *, max_tokens: int = 800, overlap: int = 120, strategy: str = "heading_first", trace_id: str) -> dict[str, Any]:
    recall("chunker", "chunked", object_id=None, limit=3)
    return chunk(object_id, max_tokens=max_tokens, overlap=overlap, strategy=strategy, trace_id=trace_id)
