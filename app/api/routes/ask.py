from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter
from pydantic import AliasChoices, BaseModel, Field

from app.observability.status_service import record_ask_query
from app.retrieval.hybrid import hybrid_search
from app.retrieval.hybrid import get_store as get_hybrid_store
from app.reasoning.models import ReasoningMode
from app.reasoning.provider import run_reasoning
from app.settings.models import AskSettings
from app.settings.runtime import get_settings_bundle
from app.stores import get_object_store

_HYBRID_WARMED = False
TOP_K_INITIAL = 40
TOP_K_LLM_DEFAULT = 10


def _load_pg_documents(store, hybrid, seen: set[str]) -> int:
    try:
        from app.stores.pg import PgObjectStore, _connect  # type: ignore
    except Exception:
        return 0

    if not isinstance(store, PgObjectStore):
        return 0

    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT object_id, payload, source_ref FROM store_objects")
                rows = cur.fetchall()
    except Exception:
        return 0

    docs_added = 0
    for row in rows or []:
        payload = row.get("payload") or {}
        text = payload.get("text") or payload.get("content")
        if not text:
            continue
        doc_id = str(row.get("object_id"))
        if doc_id in seen:
            continue
        hybrid.add_document(doc_id=doc_id, text=str(text), source_ref=row.get("source_ref"), payload=payload)
        seen.add(doc_id)
        docs_added += 1
    return docs_added


def _ensure_hybrid_store_loaded() -> None:
    global _HYBRID_WARMED
    hybrid = get_hybrid_store()
    if hybrid.all():
        _HYBRID_WARMED = True
        return

    store = get_object_store()
    docs_added = 0
    seen: set[str] = set()

    # Memory store path
    try:
        objs = getattr(store, "_objects", {})
        if isinstance(objs, dict) and objs:
            for oid, rec in objs.items():
                payload = rec.get("payload") or {}
                text = payload.get("text") or payload.get("content")
                if not text:
                    continue
                doc_id = str(oid)
                hybrid.add_document(
                    doc_id=doc_id,
                    text=str(text),
                    source_ref=rec.get("source_ref"),
                    payload=payload,
                )
                seen.add(doc_id)
                docs_added += 1
    except Exception:
        pass

    docs_added += _load_pg_documents(store, hybrid, seen)
    if docs_added > 0:
        _HYBRID_WARMED = True

router = APIRouter()


class AskRequest(BaseModel):
    question: str = Field(validation_alias=AliasChoices("question", "query"))
    zone_strategy: str | None = "default"


class AskSource(BaseModel):
    uuid: str
    title: str
    origin: str
    zone: str | None = None
    path: str | None = None


class AskResponse(BaseModel):
    answer: str
    sources: list[AskSource]
    latency_ms: int


def _to_source(hit: dict[str, Any]) -> AskSource:
    payload = hit.get("payload") or {}
    origin = str(payload.get("origin") or "vault")
    path = hit.get("source_ref") or payload.get("source_ref")
    title = payload.get("title") or hit.get("title") or ""
    raw_zone = payload.get("zone")
    zone = str(raw_zone) if raw_zone not in (None, "") else None
    return AskSource(
        uuid=str(hit.get("id") or hit.get("doc_id") or payload.get("uuid") or ""),
        title=str(title),
        origin=origin,
        zone=zone,
        path=str(path) if path else None,
    )


def _get_ask_settings() -> AskSettings:
    try:
        bundle = get_settings_bundle()
        raw = getattr(bundle, "agents", {}).get("ask") if hasattr(bundle, "agents") else None
        if isinstance(raw, AskSettings):
            return raw
        if isinstance(raw, dict):
            return AskSettings(**raw)
    except Exception:
        pass
    return AskSettings()


def _reasoning_enabled() -> bool:
    import os

    return os.getenv("REASONING_ENABLE", "").strip().lower() in {"1", "true", "yes", "on"}


def _collect_hit_text(hit: dict[str, Any]) -> str:
    payload = hit.get("payload") or {}
    text_fields = [
        hit.get("snippet"),
        payload.get("text"),
        payload.get("raw_text"),
        hit.get("text"),
    ]
    for candidate in text_fields:
        if candidate:
            return str(candidate)
    return ""


def _build_ask_context(question: str, hits: list[dict[str, Any]], ask_settings: AskSettings) -> str:
    max_chars = max(0, int(ask_settings.max_context_chars or 0))
    remaining = max_chars if max_chars > 0 else None
    parts: list[str] = [f"Question: {question}", ""]
    for idx, hit in enumerate(hits, start=1):
        payload = hit.get("payload") or {}
        origin = str(payload.get("origin") or "vault")
        zone_raw = payload.get("zone")
        zone = str(zone_raw) if zone_raw not in (None, "") else "unspecified"
        title = payload.get("title") or hit.get("title") or payload.get("source_ref") or hit.get("source_ref") or ""
        text = _collect_hit_text(hit)
        if remaining is not None and remaining <= 0:
            break
        snippet = text if remaining is None else text[:remaining]
        parts.append(f"[SOURCE {idx}] origin={origin} zone={zone} title=\"{title}\"")
        parts.append(snippet.strip())
        parts.append("")
        if remaining is not None:
            remaining -= len(snippet)
    return "\n".join(parts).strip()


def _llm_answer(question: str, context: str, ask_settings: AskSettings) -> str | None:
    try:
        run = run_reasoning(
            ReasoningMode.ASK_ANSWER,
            [],
            question=question,
            context=context,
            system_prompt=ask_settings.system_prompt,
            answer_style=ask_settings.answer_style,
            agent="ask.api",
            kind="ask.answer",
        )
    except Exception:
        return None
    if run.status != "ok":
        return None
    result = run.result
    if isinstance(result, dict):
        answer = result.get("answer")
    else:
        answer = result
    return str(answer) if answer else None


def score_hit(hit: dict[str, Any]) -> float:
    try:
        base = float(hit.get("score") or 0.0)
    except (TypeError, ValueError):
        base = 0.0

    payload = hit.get("payload") or {}
    origin = str(payload.get("origin") or "vault").lower()
    zone_raw = payload.get("zone")
    zone = str(zone_raw).lower().strip() if zone_raw not in (None, "") else None
    trust_raw = payload.get("trust")
    trust = str(trust_raw).lower().strip() if trust_raw not in (None, "") else None

    origin_boost = 0.4 if origin == "vault" else 0.0
    if origin.startswith("external"):
        origin_boost = 0.0

    zone_boost = 0.3 if zone == "hot" else 0.15 if zone == "warm" else 0.0

    trust_boost = 0.2 if trust in {"own_reviewed", "evergreen"} else 0.1 if trust in {"own_raw"} else 0.0

    return base + origin_boost + zone_boost + trust_boost


@router.post("/ask", response_model=AskResponse)
async def ask(req: AskRequest) -> AskResponse:
    if not _HYBRID_WARMED:
        _ensure_hybrid_store_loaded()
    ask_settings = _get_ask_settings()
    try:
        top_k_llm = max(1, int(ask_settings.max_context_docs or TOP_K_LLM_DEFAULT))
    except Exception:
        top_k_llm = TOP_K_LLM_DEFAULT
    start = time.perf_counter()
    hits = hybrid_search(req.question, k=TOP_K_INITIAL)
    scored = []
    for hit in hits:
        total = score_hit(hit)
        hit["ask_score"] = total
        scored.append((total, hit))

    reranked_hits = [hit for _, hit in sorted(scored, key=lambda pair: pair[0], reverse=True)]
    top_hits = reranked_hits[:top_k_llm]

    if top_hits:
        answer_text = top_hits[0].get("snippet") or top_hits[0].get("text") or ""
    else:
        answer_text = "No results found."
    if top_hits and _reasoning_enabled():
        context = _build_ask_context(req.question, top_hits, ask_settings)
        llm_answer = _llm_answer(req.question, context, ask_settings)
        if llm_answer:
            answer_text = llm_answer
    latency_ms = int((time.perf_counter() - start) * 1000)
    record_ask_query(float(latency_ms))
    sources = [_to_source(hit) for hit in top_hits]
    return AskResponse(answer=answer_text, sources=sources, latency_ms=latency_ms)


__all__ = ["router", "AskRequest", "AskResponse"]
