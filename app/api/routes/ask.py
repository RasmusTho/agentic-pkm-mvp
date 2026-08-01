from __future__ import annotations

import time
import re
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import AliasChoices, BaseModel, Field

from app.agents.ask.graph import run_ask_graph
from app.agents.ask.utils import get_ask_settings
from app.components.llm.fabric import LLMBackendTimeout
from app.events.models import new_trace_id
from app.observability.status_service import record_ask_error, record_ask_query
from app.retrieval.hybrid import get_store as get_hybrid_store
from app.retrieval.hybrid import rebuild_from_durable_index
from app.tts.config import load_tts_config
from app.tts.planning import build_tts_plan
from app.tts.service import synthesize_tts
from app.voice.transcription import transcribe_voice_audio

_HYBRID_WARMED = False


def _ensure_hybrid_store_loaded() -> None:
    """Warm the in-process retrieval cache from the durable vector index.

    The primary production init call site is the FastAPI lifespan warm in
    ``app/api/app.py::_warm_retrieval_cache`` (audit F2 / #2900), which covers
    every retrieval entrypoint sharing the module-level ``_STORE``, not just
    ``/api/ask``. This per-request call is a defensive fallback for contexts
    where the ASGI lifespan did not run (e.g. a route invoked directly in a
    test without app startup) — the cache is populated ONLY by a load/rebuild
    from ``store_vector_index`` (KERNEL-05, audit invariant I-D3), never by
    scanning the object store or any other ad-hoc fan-in. Safe to call on
    every request; the rebuild itself is a no-op once the process has already
    warmed.
    """
    global _HYBRID_WARMED
    hybrid = get_hybrid_store()
    if hybrid.all():
        _HYBRID_WARMED = True
        return

    docs_added = rebuild_from_durable_index()
    if docs_added > 0:
        _HYBRID_WARMED = True

router = APIRouter()

# A voice turn is a query, not a recording. Keep the limit deliberately small
# and reject it before handing bytes to the shared ASR engine.
VOICE_ASK_MAX_AUDIO_BYTES = 5 * 1024 * 1024
VOICE_ASK_ACCEPTED_CONTENT_TYPES = {
    "audio/wav", "audio/x-wav", "audio/wave", "audio/m4a", "audio/mp4",
    "audio/webm", "audio/ogg", "application/ogg",
}
VOICE_ASK_SUFFIX_BY_CONTENT_TYPE = {
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/wave": ".wav",
    "audio/m4a": ".m4a",
    "audio/mp4": ".mp4",
    "audio/webm": ".webm",
    "audio/ogg": ".ogg",
    "application/ogg": ".ogg",
}


class AskRequest(BaseModel):
    question: str = Field(validation_alias=AliasChoices("question", "query"))
    zone_strategy: str | None = "default"
    # The caller's active scope for this turn (#2921). This is the production binding that
    # activates the scope prefilter; omitted, the ambient `ASK_DOMAIN_SCOPE` process default
    # applies and behaviour is unchanged. Binding context is not granting access: cross-scope
    # admission remains a governed CrossScopeFlow decision, never something a scope string widens.
    scope: str | None = None


class AskSource(BaseModel):
    uuid: str
    title: str
    origin: str
    plane: str
    zone: str | None = None
    path: str | None = None


class RecallAttribution(BaseModel):
    """Structured provenance for a memory the ASK answer recalled (#1972)."""

    memory_id: str
    title: str
    why_now: str
    receipt_id: str


class AskResponse(BaseModel):
    answer: str
    sources: list[AskSource]
    latency_ms: int
    llm_route: dict[str, Any] | None = None
    # Treatment A: the attribution footer lives in `answer`; this is the same
    # provenance in structured form (keyed to the recall receipt). None when recall
    # did not fire.
    recalled: list[RecallAttribution] | None = None
    # Expansion Activation Gate (#2026): receipt id for an admitted ASK answer
    # synthesis plus the grounded sources the gate admitted into it. None/empty
    # when the gate blocked synthesis and the literal snippet was served.
    synthesis_receipt_id: str | None = None
    synthesis_source_ids: list[str] | None = None


class VoiceAskResponse(BaseModel):
    """One client-agnostic, read-only voice ASK turn (VOICE-01)."""

    transcript: str
    detected_language: str
    answer: str
    sources: list[AskSource]
    speech_plan: dict[str, Any]
    audio_url: str | None = None
    degraded: bool = False
    reason: str | None = None
    session_id: str | None = None
    trace_id: str


def _looks_like_decodable_audio(audio: bytes) -> bool:
    """Cheap container validation before ASR; the engine handles actual decode."""

    return (
        audio.startswith(b"RIFF") and audio[8:12] == b"WAVE"
    ) or audio.startswith(b"OggS") or audio.startswith(b"\x1aE\xdf\xa3") or audio[4:8] == b"ftyp"


def _capture_intent_suggestion(transcript: str) -> str | None:
    """Surface obvious capture wording without granting this read route write power.

    This is intentionally only a suggestion classifier.  It never imports a
    capture/write adapter, so a classifier error or false positive cannot
    mutate the vault.  A richer model classifier may replace it without
    changing that deterministic authority boundary.
    """

    normalized = transcript.strip().casefold()
    # Only an imperative at the start of the utterance is a capture request.
    # Retrieval questions may legitimately quote or discuss capture wording.
    if re.match(r"(?:remember|add|save|spara|kom ihåg)\b", normalized):
        return "That sounds like something to capture — use the capture surface to save it."
    return None


def _to_source(hit: Any) -> AskSource:
    raw: dict[str, Any]
    if hasattr(hit, "model_dump"):
        raw = hit.model_dump()
    elif isinstance(hit, dict):
        raw = hit
    else:
        raw = {}
    payload = raw.get("payload") or {}
    origin = str(payload.get("origin") or "vault")
    plane = str(payload.get("plane") or origin)
    path = raw.get("source_ref") or payload.get("source_ref") or raw.get("path")
    title = payload.get("title") or raw.get("title") or ""
    # Zone is derived, not read from stored artifact payload
    zone = None
    return AskSource(
        uuid=str(raw.get("id") or raw.get("doc_id") or raw.get("object_id") or payload.get("uuid") or ""),
        title=str(title),
        origin=origin,
        plane=plane,
        zone=zone,
        path=str(path) if path else None,
    )


@router.post("/ask", response_model=AskResponse)
async def ask(req: AskRequest, request: Request) -> AskResponse:
    if not _HYBRID_WARMED:
        _ensure_hybrid_store_loaded()
    start = time.perf_counter()
    ask_settings = get_ask_settings()
    trace_id = getattr(request.state, "trace_id", None) or request.headers.get("x-trace-id") or new_trace_id()
    try:
        state = run_ask_graph(
            req.question, trace_id=trace_id, ask_settings=ask_settings, active_scope=req.scope
        )
    except LLMBackendTimeout as exc:
        record_ask_error()
        raise HTTPException(
            status_code=504,
            detail={
                "error": "llm_backend_timeout",
                "provider": exc.provider,
                "timeout_seconds": exc.timeout_seconds,
                "trace_id": trace_id,
                "message": str(exc),
            },
        ) from exc
    except Exception:
        record_ask_error()
        raise
    answer_text = state.answer or "No results found."
    top_hits = state.hits
    latency_ms = int((time.perf_counter() - start) * 1000)
    record_ask_query(float(latency_ms))
    sources = [_to_source(hit) for hit in top_hits]
    recalled = [
        RecallAttribution(
            memory_id=exp.artifact_id,
            title=exp.title or "",
            why_now=exp.why_now or "",
            receipt_id=exp.receipt_reference or "",
        )
        for exp in (getattr(state, "recalled", None) or [])
        if exp.receipt_reference
    ]
    synthesis_source_ids = list(getattr(state, "synthesis_source_ids", None) or [])
    return AskResponse(
        answer=answer_text,
        sources=sources,
        latency_ms=latency_ms,
        llm_route=getattr(state, "llm_route", None),
        recalled=recalled or None,
        synthesis_receipt_id=getattr(state, "synthesis_receipt_id", None),
        synthesis_source_ids=synthesis_source_ids or None,
    )


@router.post("/ask/voice", response_model=VoiceAskResponse)
async def ask_voice(
    request: Request,
    audio: UploadFile = File(...),
    session_id: str | None = Form(None),
    zone_strategy: str | None = Form("default"),
    # Same per-request active-scope binding as `/api/ask` (#2921); a voice turn must not be a
    # scope-isolation hole just because it arrives as form data.
    scope: str | None = Form(None),
) -> VoiceAskResponse | JSONResponse:
    """Turn transient client audio into a grounded, optionally spoken answer.

    The route is deliberately composed only from read-only seams: shared ASR,
    ASK, and the derived TTS cache.  It must never become a capture shortcut.
    """

    trace_id = getattr(request.state, "trace_id", None) or request.headers.get("x-trace-id") or new_trace_id()
    content_type = (audio.content_type or "").split(";", 1)[0].casefold()
    if content_type and content_type not in VOICE_ASK_ACCEPTED_CONTENT_TYPES:
        raise HTTPException(status_code=415, detail={"error": "audio_undecodable", "trace_id": trace_id})
    audio_bytes = await audio.read()
    if len(audio_bytes) > VOICE_ASK_MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail={"error": "audio_too_large", "trace_id": trace_id})
    if not _looks_like_decodable_audio(audio_bytes):
        raise HTTPException(status_code=415, detail={"error": "audio_undecodable", "trace_id": trace_id})

    try:
        # The validated MIME type, not an optional client filename, governs
        # decoding. Browser FormData blobs commonly arrive as a generic name.
        suffix = VOICE_ASK_SUFFIX_BY_CONTENT_TYPE.get(content_type, ".wav")
        transcription = transcribe_voice_audio(audio_bytes, suffix=suffix)
    except Exception as exc:
        # Do not invent an answer when the local-only engine is unavailable.
        raise HTTPException(status_code=503, detail={"error": "stt_unavailable", "trace_id": trace_id}) from exc

    transcript = str(transcription.get("text") or "").strip()
    detected_language = str(transcription.get("language") or "unknown")
    if not transcript:
        raise HTTPException(status_code=503, detail={"error": "stt_unavailable", "trace_id": trace_id})

    suggestion = _capture_intent_suggestion(transcript)
    if suggestion is not None:
        plan = build_tts_plan(text=suggestion, config=load_tts_config(), language=detected_language)
        return VoiceAskResponse(
            transcript=transcript,
            detected_language=detected_language,
            answer=suggestion,
            sources=[],
            speech_plan=plan,
            session_id=session_id,
            trace_id=trace_id,
            degraded=True,
            reason="capture_intent_surfaced",
        )

    try:
        if not _HYBRID_WARMED:
            _ensure_hybrid_store_loaded()
        state = run_ask_graph(
            transcript,
            trace_id=trace_id,
            ask_settings=get_ask_settings(),
            active_scope=scope,
        )
    except Exception:
        # The heard text is still useful, but no ungrounded substitute answer is.
        return JSONResponse(
            status_code=503,
            content={
                "error": "ask_unavailable",
                "message": "Grounded ASK is temporarily unavailable.",
                "transcript": transcript,
                "detected_language": detected_language,
                "session_id": session_id,
                "trace_id": trace_id,
            },
        )

    answer_text = state.answer or "No results found."
    sources = [_to_source(hit) for hit in state.hits]
    config = load_tts_config()
    plan = build_tts_plan(text=answer_text, config=config, language=detected_language)
    if not config.enabled:
        return VoiceAskResponse(
            transcript=transcript,
            detected_language=detected_language,
            answer=answer_text,
            sources=sources,
            speech_plan=plan,
            session_id=session_id,
            trace_id=trace_id,
            degraded=True,
            reason="tts_unavailable",
        )
    result = synthesize_tts(text=answer_text, config=config, language=detected_language)
    if not bool(result.get("ok")):
        return VoiceAskResponse(
            transcript=transcript,
            detected_language=detected_language,
            answer=answer_text,
            sources=sources,
            speech_plan=plan,
            session_id=session_id,
            trace_id=trace_id,
            degraded=True,
            reason="tts_unavailable",
        )
    return VoiceAskResponse(
        transcript=transcript,
        detected_language=detected_language,
        answer=answer_text,
        sources=sources,
        speech_plan=plan,
        audio_url=str(result.get("audio_url") or plan["audio_url"]),
        session_id=session_id,
        trace_id=trace_id,
    )


__all__ = ["router", "AskRequest", "AskResponse", "RecallAttribution", "VoiceAskResponse"]
