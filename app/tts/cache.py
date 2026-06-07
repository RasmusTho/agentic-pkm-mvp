from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from app.tts.config import TTSConfig


def cache_key_for(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def audio_path(config: TTSConfig, cache_key: str) -> Path:
    return config.audio_cache_dir / f"{cache_key}.wav"


def plan_path(config: TTSConfig, cache_key: str) -> Path:
    return config.plan_cache_dir / f"{cache_key}.json"


def ensure_cache_dirs(config: TTSConfig) -> None:
    config.audio_cache_dir.mkdir(parents=True, exist_ok=True)
    config.plan_cache_dir.mkdir(parents=True, exist_ok=True)


def read_plan(config: TTSConfig, cache_key: str) -> dict[str, Any] | None:
    path = plan_path(config, cache_key)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def write_plan(config: TTSConfig, cache_key: str, plan: dict[str, Any]) -> None:
    ensure_cache_dirs(config)
    plan_path(config, cache_key).write_text(
        json.dumps(plan, ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )


def touch(path: Path) -> None:
    if path.exists():
        path.touch()


def enforce_audio_cache_limit(config: TTSConfig) -> None:
    if config.cache_eviction != "lru":
        return
    max_bytes = config.cache_max_gb * 1024 * 1024 * 1024
    files = [path for path in config.audio_cache_dir.glob("*.wav") if path.is_file()]
    total = sum(path.stat().st_size for path in files)
    if total <= max_bytes:
        return
    for path in sorted(files, key=lambda item: item.stat().st_mtime):
        if total <= max_bytes:
            break
        size = path.stat().st_size
        path.unlink(missing_ok=True)
        total -= size

