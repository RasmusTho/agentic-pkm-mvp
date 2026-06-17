from __future__ import annotations

from typing import Any

from app.tts.cache import (
    assert_safe_cache_root,
    audio_path,
    cache_key_for,
    ensure_cache_dirs,
    is_path_inside,
    repo_root,
    write_plan,
)
from app.tts.config import TTSConfig
from app.tts.language import detect_language, segment_by_language
from app.tts.normalization import normalize_tts_text, tts_normalization_warnings
from app.tts.providers import resolve_voice


class TTSNormalizedTextEmptyError(ValueError):
    """Raised when request text becomes empty after TTS normalization."""


def tts_config_warnings(config: TTSConfig) -> list[str]:
    root = repo_root()
    warnings: list[str] = []
    if is_path_inside(config.model_dir, root):
        warnings.append("model_dir_repo_local")
    if is_path_inside(config.cache_dir, root):
        warnings.append("cache_dir_repo_local")
    if is_path_inside(config.log_dir, root):
        warnings.append("log_dir_repo_local")
    return warnings


def build_tts_plan(
    *,
    text: str,
    config: TTSConfig,
    language: str | None = None,
    rate: float = 1.0,
) -> dict[str, Any]:
    assert_safe_cache_root(config)
    normalized_text = normalize_tts_text(text)
    if not normalized_text:
        raise TTSNormalizedTextEmptyError("text is empty after TTS normalization")
    if len(normalized_text) > config.max_chars_per_request:
        raise ValueError("text exceeds TTS_MAX_CHARS_PER_REQUEST")

    detected_language = detect_language(normalized_text, requested=language)
    segments = segment_by_language(normalized_text, requested=language)
    mixed = len({str(segment["language"]) for segment in segments}) > 1
    voice = resolve_voice(config, detected_language)
    # Per-segment voice/language routing (#2114): resolve each sentence's own
    # voice so a non-dominant-language passage is read in its own voice rather
    # than the single overall voice. Sub-sentence/term switching stays out of
    # scope — granularity is the sentence segment from ``segment_by_language``.
    for segment in segments:
        segment_voice = resolve_voice(config, str(segment["language"]))
        segment["voice_id"] = segment_voice.voice_id
        segment["provider"] = segment_voice.provider
        segment["provider_available"] = segment_voice.available
    warnings = tts_config_warnings(config) + tts_normalization_warnings(text)
    if mixed:
        warnings.append("uncertain mixed-language text")
    if not voice.available:
        warnings.append("local provider or model unavailable")
    payload = {
        "text": normalized_text,
        "language": detected_language,
        "voice_id": voice.voice_id,
        "provider": voice.provider,
        "rate": rate,
        "local_only": config.local_only,
    }
    if mixed:
        # Only mixed plans extend the cache key with the per-segment voice plan.
        # Single-language requests keep the exact payload above, so their cache
        # key is byte-for-byte identical to pre-#2114 behaviour.
        payload["segment_voices"] = [
            {
                "index": segment["index"],
                "language": segment["language"],
                "voice_id": segment["voice_id"],
                "provider": segment["provider"],
            }
            for segment in segments
        ]
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
        "warnings": warnings,
        "cache_key": cache_key,
        "cached": audio_path(config, cache_key).exists(),
        "mixed_language": mixed,
        "segments": segments,
        "audio_url": f"/api/companion/tts/audio/{cache_key}.wav",
    }
    write_plan(config, cache_key, plan)
    return plan
