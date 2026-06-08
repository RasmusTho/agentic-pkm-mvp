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


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def is_path_inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _cache_files(config: TTSConfig) -> list[Path]:
    files: list[Path] = []
    for directory, pattern in ((config.audio_cache_dir, "*.wav"), (config.plan_cache_dir, "*.json")):
        if directory.exists():
            files.extend(path for path in directory.glob(pattern) if path.is_file())
    return files


def _assert_safe_cache_root(config: TTSConfig) -> None:
    if is_path_inside(config.cache_dir, repo_root()):
        raise ValueError(f"TTS cache root is repo-local and unsafe for cleanup: {config.cache_dir}")


def cache_status(config: TTSConfig) -> dict[str, Any]:
    files = _cache_files(config)
    return {
        "cache_dir": str(config.cache_dir),
        "audio_dir": str(config.audio_cache_dir),
        "plan_dir": str(config.plan_cache_dir),
        "eviction_policy": config.cache_eviction,
        "max_gb": config.cache_max_gb,
        "max_bytes": int(config.cache_max_gb * 1024 * 1024 * 1024),
        "size_bytes": sum(path.stat().st_size for path in files),
        "audio_file_count": sum(1 for path in files if path.suffix == ".wav"),
        "plan_file_count": sum(1 for path in files if path.suffix == ".json"),
    }


def enforce_cache_limit(config: TTSConfig) -> dict[str, Any]:
    _assert_safe_cache_root(config)
    if config.cache_eviction != "lru":
        result = cache_status(config)
        result["evicted_count"] = 0
        return result
    max_bytes = int(config.cache_max_gb * 1024 * 1024 * 1024)
    files = _cache_files(config)
    total = sum(path.stat().st_size for path in files)
    evicted = 0
    for path in sorted(files, key=lambda item: (item.stat().st_mtime, str(item))):
        if total <= max_bytes:
            break
        size = path.stat().st_size
        path.unlink(missing_ok=True)
        total -= size
        evicted += 1
    result = cache_status(config)
    result["evicted_count"] = evicted
    return result


def enforce_audio_cache_limit(config: TTSConfig) -> None:
    enforce_cache_limit(config)


def write_tts_log_event(config: TTSConfig, event: dict[str, Any]) -> Path:
    if is_path_inside(config.log_dir, repo_root()):
        raise ValueError(f"TTS log root is repo-local and unsafe for runtime logs: {config.log_dir}")
    config.log_dir.mkdir(parents=True, exist_ok=True)
    path = config.log_dir / "tts-runtime.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
    return path
