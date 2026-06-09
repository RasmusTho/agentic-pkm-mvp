from __future__ import annotations

import pytest
from pathlib import Path

from app.tts.cache import enforce_cache_limit, write_tts_log_event
from app.tts.config import TTSConfig


def _config(tmp_path: Path, *, cache_dir: Path | None = None, cache_max_gb: float = 2) -> TTSConfig:
    return TTSConfig(
        enabled=True,
        local_only=True,
        model_dir=tmp_path / "models",
        cache_dir=cache_dir or tmp_path / "cache",
        log_dir=tmp_path / "logs",
        cache_max_gb=cache_max_gb,
        cache_eviction="lru",
        max_concurrent_jobs=1,
        max_chars_per_request=4000,
        allow_browser_fallback=False,
        allow_cloud_fallback=False,
        piper_command="/bin/echo",
        kokoro_command="/bin/echo",
    )


def test_tts_cache_lru_evicts_when_size_limit_exceeded(tmp_path: Path) -> None:
    config = _config(tmp_path, cache_max_gb=5 / (1024 * 1024 * 1024))
    audio_dir = config.audio_cache_dir
    plan_dir = config.plan_cache_dir
    audio_dir.mkdir(parents=True)
    plan_dir.mkdir(parents=True)
    oldest = audio_dir / (("0" * 64) + ".wav")
    newest = audio_dir / (("1" * 64) + ".wav")
    plan = plan_dir / (("2" * 64) + ".json")
    oldest.write_bytes(b"aaa")
    newest.write_bytes(b"bbb")
    plan.write_text("{}", encoding="utf-8")
    oldest.touch()
    newest.touch()
    plan.touch()

    result = enforce_cache_limit(config)

    assert result["eviction_policy"] == "lru"
    assert result["evicted_count"] == 1
    assert not oldest.exists()
    assert newest.exists()
    assert plan.exists()
    assert result["size_bytes"] <= result["max_bytes"]


def test_tts_cache_cleanup_rejects_repo_local_cache_root(tmp_path: Path) -> None:
    config = _config(tmp_path, cache_dir=Path.cwd() / "tmp" / "unsafe-tts-cache")

    with pytest.raises(ValueError, match="repo-local"):
        enforce_cache_limit(config)


def test_tts_log_path_is_configurable_outside_repo(tmp_path: Path) -> None:
    config = _config(tmp_path)

    path = write_tts_log_event(config, {"event": "tts.status.receipt", "ok": True})

    assert path == config.log_dir / "tts-runtime.jsonl"
    assert path.exists()
    assert Path.cwd() not in path.resolve().parents
    assert "tts.status.receipt" in path.read_text(encoding="utf-8")
