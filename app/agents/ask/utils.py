from __future__ import annotations

from typing import Any, Iterable, List

from app.agent_memory.recall_explanation import RecallExplanation
from app.reasoning.models import ReasoningMode
from app.reasoning.provider import run_reasoning
from app.settings.models import AskSettings, DEFAULT_ASK_SYSTEM_PROMPT, build_ask_system_prompt
from app.settings.runtime import get_settings_bundle


def get_ask_settings() -> AskSettings:
    try:
        bundle = get_settings_bundle()
        raw = getattr(bundle, "agents", {}).get("ask") if hasattr(bundle, "agents") else None
        ask: AskSettings | None = None
        if isinstance(raw, AskSettings):
            ask = raw
        elif isinstance(raw, dict):
            ask = AskSettings(**raw)
        if ask is not None:
            if ask.system_prompt == DEFAULT_ASK_SYSTEM_PROMPT:
                owner_name = getattr(getattr(getattr(bundle, "instance", None), "vault", None), "owner_name", None)
                if owner_name:
                    ask = ask.model_copy(update={"system_prompt": build_ask_system_prompt(owner_name)})
            return ask
    except Exception:
        pass
    return AskSettings()


def reasoning_enabled() -> bool:
    import os

    return os.getenv("REASONING_ENABLE", "").strip().lower() in {"1", "true", "yes", "on"}


def score_hit(hit: dict[str, Any]) -> float:
    try:
        base = float(hit.get("score") or 0.0)
    except (TypeError, ValueError):
        base = 0.0

    payload = hit.get("payload") or {}
    origin = str(payload.get("origin") or "vault").lower()
    trust_raw = payload.get("trust")
    trust = str(trust_raw).lower().strip() if trust_raw not in (None, "") else None

    origin_boost = 0.4 if origin == "vault" else 0.0
    if origin.startswith("external"):
        origin_boost = 0.0

    # Zone is a derived signal, not a stored payload field.
    # Zone-based salience boosts removed; zone should be computed from runtime signals.

    trust_boost = 0.2 if trust in {"own_reviewed", "evergreen"} else 0.1 if trust in {"own_raw"} else 0.0

    return base + origin_boost + trust_boost


def _collect_hit_text(hit: dict[str, Any]) -> str:
    payload = hit.get("payload") or {}
    text_fields = [hit.get("snippet"), payload.get("text"), payload.get("raw_text"), hit.get("text")]
    for candidate in text_fields:
        if candidate:
            return str(candidate)
    return ""


def build_ask_context(
    question: str,
    hits: List[dict[str, Any]],
    ask_settings: AskSettings,
    recalled: List[RecallExplanation] | None = None,
) -> str:
    max_chars = max(0, int(ask_settings.max_context_chars or 0))
    remaining = max_chars if max_chars > 0 else None
    parts: list[str] = [f"Question: {question}", ""]
    for idx, explanation in enumerate(recalled or [], start=1):
        parts.append(f"[RECALLED MEMORY {idx}] title=\"{explanation.title}\"")
        parts.append(f"why_now={explanation.why_now}")
        parts.append("authority_limits=" + ", ".join(explanation.authority_limits))
        parts.append("")
    for idx, hit in enumerate(hits, start=1):
        payload = hit.get("payload") or {}
        origin = str(payload.get("origin") or "vault")
        # Zone is derived, not read from stored artifact payload
        title = payload.get("title") or hit.get("title") or payload.get("source_ref") or hit.get("source_ref") or ""
        text = _collect_hit_text(hit)
        if remaining is not None and remaining <= 0:
            break
        snippet = text if remaining is None else text[:remaining]
        parts.append(f"[SOURCE {idx}] origin={origin} title=\"{title}\"")
        parts.append(snippet.strip())
        parts.append("")
        if remaining is not None:
            remaining -= len(snippet)
    return "\n".join(parts).strip()


def llm_answer(question: str, context: str, ask_settings: AskSettings) -> tuple[str | None, dict[str, Any] | None]:
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
        return None, None
    route = run.llm_route if hasattr(run, "llm_route") else None
    if run.status != "ok":
        return None, route
    result = run.result
    if isinstance(result, dict):
        answer = result.get("answer")
    else:
        answer = result
    return (str(answer) if answer else None), route


__all__ = [
    "build_ask_context",
    "get_ask_settings",
    "llm_answer",
    "reasoning_enabled",
    "score_hit",
]
