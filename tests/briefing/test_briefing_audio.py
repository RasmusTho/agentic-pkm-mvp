from __future__ import annotations

from pathlib import Path

from app.briefing.audio import build_briefing_speech_plan
from app.tts.config import TTSConfig


def _config(tmp_path: Path) -> TTSConfig:
    model_dir = tmp_path / "models"
    piper_dir = model_dir / "piper" / "sv_SE-lisa-medium"
    kokoro_dir = model_dir / "kokoro"
    piper_dir.mkdir(parents=True)
    kokoro_dir.mkdir(parents=True)
    (piper_dir / "sv_SE-lisa-medium.onnx").write_bytes(b"model")
    (piper_dir / "sv_SE-lisa-medium.onnx.json").write_text("{}", encoding="utf-8")
    (kokoro_dir / "kokoro-v1.0.int8.onnx").write_bytes(b"model")
    (kokoro_dir / "voices-v1.0.bin").write_bytes(b"voices")
    return TTSConfig(
        enabled=True,
        local_only=True,
        model_dir=model_dir,
        cache_dir=tmp_path / "cache",
        log_dir=tmp_path / "logs",
        cache_max_gb=2,
        cache_eviction="lru",
        max_concurrent_jobs=1,
        max_chars_per_request=4000,
        allow_browser_fallback=False,
        allow_cloud_fallback=False,
        piper_command="/bin/echo",
        kokoro_command="/bin/echo",
    )


def test_briefing_text_produces_valid_speech_plan(tmp_path: Path) -> None:
    plan = build_briefing_speech_plan(
        briefing_text=(
            "# Daglig briefing\n\n"
            "## Åtaganden\nDu behöver svara Anna idag.\n\n"
            "## Decisions\nReview the launch decision before lunch."
        ),
        config=_config(tmp_path),
    )

    assert plan["mixed_language"] is True
    assert [segment["language"] for segment in plan["segments"]] == [
        "sv-SE",
        "en-US",
    ]
    assert [segment["voice_id"] for segment in plan["segments"]] == [
        "sv_SE-lisa-medium",
        "bf_isabella",
    ]
    assert all(segment["provider_available"] for segment in plan["segments"])

