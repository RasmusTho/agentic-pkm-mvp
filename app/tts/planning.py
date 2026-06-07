from __future__ import annotations

from typing import Any

from app.tts.cache import audio_path, cache_key_for, ensure_cache_dirs, write_plan
from app.tts.config import TTSConfig
from app.tts.language import detect_language, segment_by_language
from app.tts.normalization import normalize_tts_text
from app.tts.providers import resolve_voice


def build_tts_plan(
    *,
    text: str,
    config: TTSConfig,
    language: str | None = None,
    rate: float = 1.0,
) -> dict[str, Any]:
    normalized_text = normalize_tts_text(text)
    if len(normalized_text) > config.max_chars_per_request:
        raise ValueError("text exceeds TTS_MAX_CHARS_PER_REQUEST")

    detected_language = detect_language(normalized_text, requested=language)
    segments = segment_by_language(normalized_text, requested=language)
    mixed = len({str(segment["language"]) for segment in segments}) > 1
    voice = resolve_voice(config, detected_language)
    payload = {
        "text": normalized_text,
        "language": detected_language,
        "voice_id": voice.voice_id,
        "provider": voice.provider,
        "rate": rate,
        "local_only": config.local_only,
    }
    cache_key = cache_key_for(payload)
    ensure_cache_dirs(config)

    plan = {
        "enabled": config.enabled,
        "local_only": config.local_only,
        "allow_browser_fallback": config.allow_browser_fallback,
        "allow_cloud_fallback": config.allow_cloud_fallback,
        "normalized_text": normalized_text,
        "language": detected_language,
        "provider": voice.provider,
        "voice_id": voice.voice_id,
        "provider_available": voice.available,
        "provider_reason": voice.unavailable_reason,
        "cache_key": cache_key,
        "cached": audio_path(config, cache_key).exists(),
        "mixed_language": mixed,
        "segments": segments,
        "audio_url": f"/api/companion/tts/audio/{cache_key}.wav",
    }
    write_plan(config, cache_key, plan)
    return plan
