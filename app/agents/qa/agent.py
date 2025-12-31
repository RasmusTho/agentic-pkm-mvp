from __future__ import annotations

import os
from typing import Dict, List, Optional

from app.components.llm.fabric import LLMTaskIntent, get_chat_client
from app.obs.log import span, with_trace_id
from app.quality.guardrails import enforce_quality
from app.retrieval.hybrid import hybrid_search
from app.settings.models import QaSettings, SettingsBundle
from app.settings.runtime import subscribe_settings


_QA_SETTINGS = QaSettings()


def _apply_qa_settings(bundle: SettingsBundle) -> None:
    global _QA_SETTINGS
    candidate = bundle.agents.get("qa") if bundle else None
    if isinstance(candidate, QaSettings):
        _QA_SETTINGS = candidate
    else:
        _QA_SETTINGS = QaSettings()


subscribe_settings(_apply_qa_settings)


def _max_tokens() -> int:
    override = os.getenv("LLM_MAX_TOKENS")
    if override:
        try:
            return int(override)
        except ValueError:
            pass
    return _QA_SETTINGS.llm.max_tokens


def _call_llm(messages: List[Dict[str, str]], *, trace_id: str, max_tokens: int) -> str:
    system = messages[0]["content"] if messages else ""
    user = messages[-1]["content"] if messages else ""
    client = get_chat_client(LLMTaskIntent(task_kind="qa", risk="medium"))
    return client.chat(
        "qa",
        {"system": system, "user": user},
        agent="qa",
        kind="qa.draft",
        trace_id=trace_id,
        max_tokens=max_tokens,
    )


def _format_context(ctx_docs: List[dict]) -> str:
    lines = []
    for idx, doc in enumerate(ctx_docs, start=1):
        snippet = doc.get("snippet") or ""
        lines.append(f"[#{idx}] ({doc.get('doc_id')}) {snippet}")
    return "\n".join(lines)


@span("agent.draft")
def draft_answer(query: str, ctx_docs: List[dict], *, trace_id: Optional[str] = None) -> str:
    trace_id = with_trace_id(trace_id)
    instructions = (
        "Du är en deterministisk QA-agent. Besvara endast med fakta hämtade ur kontexten och "
        "citera källor som [#id]."
    )
    context = _format_context(ctx_docs)
    prompt = (
        f"Instruktioner:\n{instructions}\n\n"
        f"Kontext:\n{context}\n\n"
        f"Fråga:\n{query}\n\n"
        "Krav:\n- Svara på svenska.\n- Ange källor som [#id] i slutet av meningar.\n"
        "- Var kortfattad men komplett."
    )
    messages = [
        {"role": "system", "content": "Du är en hjälpfull assistent som följer instruktionerna strikt."},
        {"role": "user", "content": prompt},
    ]
    response = _call_llm(messages, trace_id=trace_id, max_tokens=_max_tokens())
    return response


@span("agent.self_check")
def self_check(
    query: str,
    ctx_docs: List[dict],
    draft: str,
    *,
    trace_id: Optional[str] = None,
) -> Dict[str, object]:
    trace_id = with_trace_id(trace_id)
    expected_refs = [f"[#{idx}]" for idx in range(1, len(ctx_docs) + 1)]
    has_reference = any(ref in draft for ref in expected_refs)
    word_count = len(draft.split())
    issues = []
    if not has_reference:
        issues.append("missing_references")
    if word_count < 30:
        issues.append("too_short")
    quality_score = max(0.0, 1.0 - 0.3 * len(issues))
    return {
        "issues": issues,
        "quality_score": quality_score,
        "needs_more_context": "missing_references" in issues,
        "word_count": word_count,
        "trace_id": trace_id,
    }


@span("agent.finalize")
def finalize(draft: str, checks: Dict[str, object], *, trace_id: Optional[str] = None) -> str:
    _ = with_trace_id(trace_id)
    if checks.get("needs_more_context"):
        return draft + "\n\n_Notis: begränsad evidens._"
    return draft


@span("agent.answer")
def answer(query: str, *, trace_id: Optional[str] = None) -> Dict[str, object]:
    trace_id = with_trace_id(trace_id)
    if not _QA_SETTINGS.enable:
        return {
            "answer": "QA-agenten är inaktiverad via inställningar.",
            "sources": [],
            "trace_id": trace_id,
        }
    docs = hybrid_search(query, k=max(1, _QA_SETTINGS.search_k))
    if not docs or docs[0]["score"] < 0.15:
        return {
            "answer": "Otillräcklig evidens för att svara på frågan.",
            "sources": [],
            "trace_id": trace_id,
        }
    ctx_docs = docs[: max(1, _QA_SETTINGS.context_docs)]
    draft = draft_answer(query, ctx_docs, trace_id=trace_id)
    checks = self_check(query, ctx_docs, draft, trace_id=trace_id)
    final_text = finalize(draft, checks, trace_id=trace_id)
    sources = [{"doc_id": doc["doc_id"], "source_ref": doc.get("source_ref")} for doc in ctx_docs]
    quality = enforce_quality(final_text, sources)
    return {
        "answer": final_text,
        "sources": sources,
        "trace_id": trace_id,
        "checks": checks,
        "quality": quality,
    }


__all__ = ["answer", "draft_answer", "self_check", "finalize"]
