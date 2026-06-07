from __future__ import annotations

import json
from pathlib import Path

from app.tts.config import TTSConfig
from app.tts.planning import build_tts_plan


def _config(tmp_path: Path, *, enabled: bool = True) -> TTSConfig:
    model_dir = tmp_path / "models"
    piper_dir = model_dir / "piper" / "sv_SE-nst-medium"
    kokoro_dir = model_dir / "kokoro"
    piper_dir.mkdir(parents=True, exist_ok=True)
    kokoro_dir.mkdir(parents=True, exist_ok=True)
    (piper_dir / "sv_SE-nst-medium.onnx").write_bytes(b"model")
    (piper_dir / "sv_SE-nst-medium.onnx.json").write_text("{}", encoding="utf-8")
    (kokoro_dir / "kokoro-v1.0.int8.onnx").write_bytes(b"model")
    (kokoro_dir / "voices-v1.0.bin").write_bytes(b"voice")
    return TTSConfig(
        enabled=enabled,
        local_only=True,
        model_dir=model_dir,
        cache_dir=tmp_path / "cache",
        cache_max_gb=2,
        cache_eviction="lru",
        max_concurrent_jobs=1,
        max_chars_per_request=4000,
        allow_browser_fallback=False,
        allow_cloud_fallback=False,
        piper_command="/bin/echo",
        kokoro_command="/bin/echo",
    )


def test_plan_normalizes_text_and_chooses_swedish_piper(tmp_path: Path) -> None:
    plan = build_tts_plan(
        text="  Hej\u00a0världen,\nnu läser vi.  ",
        config=_config(tmp_path),
    )

    assert plan["normalized_text"] == "Hej världen, nu läser vi."
    assert plan["language"] == "sv-SE"
    assert plan["provider"] == "piper"
    assert plan["voice_id"] == "sv_SE-nst-medium"
    assert plan["provider_available"] is True
    assert plan["allow_browser_fallback"] is False
    assert plan["allow_cloud_fallback"] is False


def test_plan_chooses_kokoro_voice_for_english_variants(tmp_path: Path) -> None:
    us = build_tts_plan(text="Read this note.", config=_config(tmp_path), language="en-US")
    gb = build_tts_plan(text="Read this note.", config=_config(tmp_path), language="en-GB")

    assert us["provider"] == "kokoro"
    assert us["voice_id"] == "af_heart"
    assert gb["provider"] == "kokoro"
    assert gb["voice_id"] == "bf_emma"


def test_plan_segments_mixed_language_fixture(tmp_path: Path) -> None:
    fixture = Path("tests/fixtures/tts/companion_mixed_corpus.json")
    item = json.loads(fixture.read_text(encoding="utf-8"))["items"][0]

    plan = build_tts_plan(text=item["text"], config=_config(tmp_path))

    assert [segment["language"] for segment in plan["segments"]] == item["expected_languages"]
    assert plan["mixed_language"] is True


def test_plan_reports_missing_local_command_without_cloud_fallback(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("PATH", "")
    config = _config(tmp_path)
    config = TTSConfig(
        **{
            **config.__dict__,
            "piper_command": None,
        }
    )

    plan = build_tts_plan(text="Hej världen.", config=config)

    assert plan["provider_available"] is False
    assert "piper command" in plan["provider_reason"]
    assert plan["allow_cloud_fallback"] is False
