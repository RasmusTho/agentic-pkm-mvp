from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _truthy_env(name: str, *, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int_env(name: str, *, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


@dataclass(frozen=True)
class TTSConfig:
    enabled: bool
    local_only: bool
    model_dir: Path
    cache_dir: Path
    log_dir: Path
    cache_max_gb: float
    cache_eviction: str
    max_concurrent_jobs: int
    max_chars_per_request: int
    allow_browser_fallback: bool
    allow_cloud_fallback: bool
    piper_command: str | None
    kokoro_command: str | None

    @property
    def audio_cache_dir(self) -> Path:
        return self.cache_dir / "audio"

    @property
    def plan_cache_dir(self) -> Path:
        return self.cache_dir / "plans"


def load_tts_config() -> TTSConfig:
    default_root = Path.home() / ".local" / "share" / "agentic-pkm" / "tts"
    model_dir = Path(os.getenv("TTS_MODEL_DIR") or default_root / "models")
    cache_dir = Path(os.getenv("TTS_CACHE_DIR") or default_root / "cache")
    log_dir = Path(os.getenv("TTS_LOG_DIR") or default_root / "logs")
    return TTSConfig(
        enabled=_truthy_env("TTS_ENABLED"),
        local_only=_truthy_env("TTS_LOCAL_ONLY", default=True),
        model_dir=model_dir,
        cache_dir=cache_dir,
        log_dir=log_dir,
        cache_max_gb=_int_env("TTS_CACHE_MAX_GB", default=2),
        cache_eviction=(os.getenv("TTS_CACHE_EVICTION") or "lru").strip().lower(),
        max_concurrent_jobs=_int_env("TTS_MAX_CONCURRENT_JOBS", default=1),
        max_chars_per_request=_int_env("TTS_MAX_CHARS_PER_REQUEST", default=4000),
        allow_browser_fallback=_truthy_env("TTS_ALLOW_BROWSER_FALLBACK"),
        allow_cloud_fallback=_truthy_env("TTS_ALLOW_CLOUD_FALLBACK"),
        piper_command=(os.getenv("TTS_PIPER_COMMAND") or "").strip() or None,
        kokoro_command=(os.getenv("TTS_KOKORO_COMMAND") or "").strip() or None,
    )
