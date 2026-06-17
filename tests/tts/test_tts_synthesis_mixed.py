"""Per-segment voice/language routing for mixed-language read-back (#2114).

These tests cover the acceptance criteria for synthesizing each sentence in its
own language's voice and concatenating multi-provider segments into one WAV at a
common sample rate without corruption.
"""

from __future__ import annotations

import wave
from array import array
from pathlib import Path

from app.tts.concat import common_sample_rate, concatenate_wavs
from app.tts.config import TTSConfig
from app.tts.planning import build_tts_plan
from app.tts.providers import TTSVoice


def _config(tmp_path: Path) -> TTSConfig:
    model_dir = tmp_path / "models"
    piper_dir = model_dir / "piper" / "sv_SE-lisa-medium"
    kokoro_dir = model_dir / "kokoro"
    piper_dir.mkdir(parents=True, exist_ok=True)
    kokoro_dir.mkdir(parents=True, exist_ok=True)
    (piper_dir / "sv_SE-lisa-medium.onnx").write_bytes(b"model")
    (piper_dir / "sv_SE-lisa-medium.onnx.json").write_text("{}", encoding="utf-8")
    (kokoro_dir / "kokoro-v1.0.int8.onnx").write_bytes(b"model")
    (kokoro_dir / "voices-v1.0.bin").write_bytes(b"voice")
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


def _write_wav(path: Path, *, framerate: int, num_frames: int, value: int = 1000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    samples = array("h", [value]) * num_frames
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(framerate)
        wav.writeframes(samples.tobytes())


def test_each_sentence_uses_its_language_voice(tmp_path: Path, monkeypatch) -> None:
    # A note whose sentences span sv-SE and en is routed so each sentence is
    # planned and synthesized with its own language's resolved voice, not a
    # single overall voice.
    config = _config(tmp_path)
    text = "Hej, jag läser den här anteckningen. Then I continue in English."

    plan = build_tts_plan(text=text, config=config)

    assert plan["mixed_language"] is True
    segment_languages = [seg["language"] for seg in plan["segments"]]
    assert segment_languages == ["sv-SE", "en-US"]
    # Each segment carries its own resolved voice (not the overall voice).
    assert plan["segments"][0]["provider"] == "piper"
    assert plan["segments"][0]["voice_id"] == "sv_SE-lisa-medium"
    assert plan["segments"][1]["provider"] == "kokoro"
    assert plan["segments"][1]["voice_id"] == "bf_isabella"

    # Synthesis routes each segment text to the matching voice.
    calls: list[tuple[str, str, str]] = []

    def fake_synthesize(seg_text: str, voice: TTSVoice, output_path: Path, *, rate: float = 1.0) -> None:
        calls.append((seg_text, voice.provider, voice.voice_id))
        rate_hz = 22050 if voice.provider == "piper" else 24000
        _write_wav(output_path, framerate=rate_hz, num_frames=100)

    monkeypatch.setattr("app.tts.service.synthesize_with_voice", fake_synthesize)
    from app.tts.service import synthesize_tts

    result = synthesize_tts(text=text, config=config)

    assert result["ok"] is True
    assert result["state"] == "generated"
    # Two segments, each synthesized with its own voice.
    assert len(calls) == 2
    assert calls[0][1:] == ("piper", "sv_SE-lisa-medium")
    assert calls[1][1:] == ("kokoro", "bf_isabella")
    assert "Hej" in calls[0][0]
    assert "English" in calls[1][0]


def test_multi_provider_concatenation_normalizes_sample_rate(tmp_path: Path) -> None:
    # Segments produced at different provider sample rates concatenate into one
    # WAV at a single common rate without corruption.
    piper_wav = tmp_path / "piper.wav"   # 22050 Hz, 220 frames
    kokoro_wav = tmp_path / "kokoro.wav"  # 24000 Hz, 240 frames
    _write_wav(piper_wav, framerate=22050, num_frames=220)
    _write_wav(kokoro_wav, framerate=24000, num_frames=240)

    out = tmp_path / "joined.wav"
    target_rate = concatenate_wavs([piper_wav, kokoro_wav], out)

    assert target_rate == common_sample_rate([22050, 24000]) == 24000

    with wave.open(str(out), "rb") as wav:
        assert wav.getnchannels() == 1
        assert wav.getsampwidth() == 2
        assert wav.getframerate() == 24000
        total = wav.getnframes()
        data = wav.readframes(total)

    # 220 frames @ 22050 upsampled to 24000 -> ~239 frames; plus 240 frames.
    upsampled_first = round(220 * 24000 / 22050)
    assert total == upsampled_first + 240
    # Not corrupted: byte length matches frame count for 16-bit mono.
    assert len(data) == total * 2


def test_embedded_terms_stay_in_host_voice(tmp_path: Path) -> None:
    # A Swedish sentence containing an embedded English term stays a single
    # segment in the host (sv-SE) voice — no sub-sentence/term-level switching.
    config = _config(tmp_path)
    text = "Vi använder en feature flag för att styra detta."

    plan = build_tts_plan(text=text, config=config)

    assert plan["mixed_language"] is False
    assert len(plan["segments"]) == 1
    segment = plan["segments"][0]
    assert segment["language"] == "sv-SE"
    assert segment["provider"] == "piper"
    assert segment["voice_id"] == "sv_SE-lisa-medium"
    # The embedded English term did not spawn its own segment/voice.
    assert "feature flag" in str(segment["text"])
