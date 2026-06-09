from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from app.tts.cache import cache_status, is_path_inside, repo_root
from app.tts.config import TTSConfig
from app.tts.planning import tts_config_warnings
from app.tts.providers import resolve_voice


def _writable(path: Path) -> bool:
    """Return True if *path* already exists and appears writable.

    This function is observational: it never creates directories or files.
    A non-existent path is reported as not writable; a caller that needs the
    directory to exist must create it explicitly before invoking the status
    endpoint.
    """
    if not path.exists():
        return False
    return path.is_dir() and os.access(path, os.W_OK)


def _path_status(path: Path) -> dict[str, Any]:
    root = repo_root()
    return {
        "path": str(path),
        "exists": path.exists(),
        "outside_repo": not is_path_inside(path, root),
        "writable": _writable(path),
    }


def _voice_status(config: TTSConfig, language: str) -> dict[str, Any]:
    voice = resolve_voice(config, language)
    return {
        "language": language,
        "provider": voice.provider,
        "voice_id": voice.voice_id,
        "available": voice.available,
        "reason": voice.unavailable_reason,
        "model_path": str(voice.model_path),
        "config_path": str(voice.config_path) if voice.config_path is not None else None,
        "voice_path": str(voice.voice_path) if voice.voice_path is not None else None,
        "command": voice.command,
    }


def tts_runtime_status(config: TTSConfig) -> dict[str, Any]:
    cache = cache_status(config)
    receipt_path = config.log_dir / "tts-runtime-status-receipt.json"
    return {
        "environment": {
            "TTS_ENABLED": config.enabled,
            "TTS_LOCAL_ONLY": config.local_only,
            "TTS_ALLOW_BROWSER_FALLBACK": config.allow_browser_fallback,
            "TTS_ALLOW_CLOUD_FALLBACK": config.allow_cloud_fallback,
        },
        "config": {
            "enabled": config.enabled,
            "local_only": config.local_only,
            "allow_browser_fallback": config.allow_browser_fallback,
            "allow_cloud_fallback": config.allow_cloud_fallback,
            "model_dir": str(config.model_dir),
            "cache_dir": str(config.cache_dir),
            "log_dir": str(config.log_dir),
            "warnings": tts_config_warnings(config),
        },
        "paths": {
            "model_dir": _path_status(config.model_dir),
            "cache_dir": _path_status(config.cache_dir),
            "audio_cache_dir": _path_status(config.audio_cache_dir),
            "plan_cache_dir": _path_status(config.plan_cache_dir),
            "log_dir": _path_status(config.log_dir),
        },
        "providers": {
            "sv-SE": _voice_status(config, "sv-SE"),
            "en-US": _voice_status(config, "en-US"),
            "en-GB": _voice_status(config, "en-GB"),
        },
        "cache": cache,
        "operator_receipt": {
            "path": str(receipt_path),
            "outside_repo": not is_path_inside(receipt_path, repo_root()),
            "records_audio": False,
            "requires_operator_runtime": True,
        },
    }
