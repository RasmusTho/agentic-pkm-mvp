from __future__ import annotations

import threading
from typing import Any

from app.tts.cache import (
    audio_path,
    enforce_audio_cache_limit,
    touch,
)
from app.tts.config import TTSConfig
from app.tts.planning import build_tts_plan
from app.tts.providers import resolve_voice, synthesize_with_voice


_semaphore_lock = threading.Lock()
_semaphores: dict[int, threading.BoundedSemaphore] = {}


def _semaphore(limit: int) -> threading.BoundedSemaphore:
    with _semaphore_lock:
        if limit not in _semaphores:
            _semaphores[limit] = threading.BoundedSemaphore(limit)
        return _semaphores[limit]


def synthesize_tts(
    *,
    text: str,
    config: TTSConfig,
    language: str | None = None,
    rate: float = 1.0,
) -> dict[str, Any]:
    plan = build_tts_plan(text=text, config=config, language=language, rate=rate)
    output_path = audio_path(config, str(plan["cache_key"]))
    if output_path.exists():
        touch(output_path)
        plan["cached"] = True
        return {
            "ok": True,
            "state": "cached",
            "cached": True,
            "cache_key": plan["cache_key"],
            "audio_url": plan["audio_url"],
            "content_type": "audio/wav",
            "provider": plan["provider"],
            "language": plan["language"],
            "voice_id": plan["voice_id"],
            "reason": None,
        }

    if not config.enabled:
        return _unavailable(plan, "tts_disabled")
    if not config.local_only:
        return _unavailable(plan, "local_only_required")
    if bool(plan["mixed_language"]):
        return _unavailable(plan, "mixed_language_synthesis_not_supported")
    if config.allow_cloud_fallback:
        return _unavailable(plan, "cloud_fallback_forbidden")

    voice = resolve_voice(config, str(plan["language"]))
    if not voice.available:
        return _unavailable(plan, voice.unavailable_reason or "provider_unavailable")

    acquired = _semaphore(config.max_concurrent_jobs).acquire(blocking=False)
    if not acquired:
        return _unavailable(plan, "tts_concurrency_limit_reached")
    try:
        synthesize_with_voice(str(plan["normalized_text"]), voice, output_path, rate=rate)
    except Exception as exc:
        return _unavailable(plan, f"provider_execution_failed: {exc}")
    finally:
        _semaphore(config.max_concurrent_jobs).release()
    if not output_path.exists() or output_path.stat().st_size == 0:
        return _unavailable(plan, "provider_did_not_write_audio")
    enforce_audio_cache_limit(config)
    return {
        "ok": True,
        "state": "generated",
        "cached": False,
        "cache_key": plan["cache_key"],
        "audio_url": plan["audio_url"],
        "content_type": "audio/wav",
        "provider": plan["provider"],
        "language": plan["language"],
        "voice_id": plan["voice_id"],
        "reason": None,
    }


def _unavailable(plan: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "ok": False,
        "state": "unavailable",
        "cached": False,
        "cache_key": plan["cache_key"],
        "audio_url": None,
        "content_type": "audio/wav",
        "provider": plan["provider"],
        "language": plan["language"],
        "voice_id": plan["voice_id"],
        "reason": reason,
    }
