from __future__ import annotations

from typing import Any, Iterable, List

from app.reasoning.models import ReasoningMode
from app.reasoning.provider import run_reasoning
from app.settings.models import AskSettings
from app.settings.runtime import get_settings_bundle


def get_ask_settings() -> AskSettings:
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


def _collect_hit_text(hit: dict[str, Any]) -> str:
    payload = hit.get("payload") or {}
    text_fields = [hit.get("snippet"), payload.get("text"), payload.get("raw_text"), hit.get("text")]
    for candidate in text_fields:
        if candidate:
            return str(candidate)
    return ""


def build_ask_context(question: str, hits: List[dict[str, Any]], ask_settings: AskSettings) -> str:
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


def llm_answer(question: str, context: str, ask_settings: AskSettings) -> str | None:
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


__all__ = [
    "build_ask_context",
    "get_ask_settings",
    "llm_answer",
    "reasoning_enabled",
    "score_hit",
]
