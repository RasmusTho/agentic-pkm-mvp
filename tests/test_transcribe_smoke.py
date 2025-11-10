from __future__ import annotations

from app.media import transcribe


def test_transcribe_smoke(monkeypatch, tmp_path):
    fake_audio = tmp_path / "input.mp3"
    fake_audio.write_bytes(b"fake audio bytes")
    outbox = tmp_path / "index-outbox.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox))

    monkeypatch.setattr(transcribe, "download_audio", lambda source: fake_audio)
    monkeypatch.setattr(transcribe, "ffmpeg_to_wav", lambda path: fake_audio)

    class DummySeg:
        start = 0.0
        end = 1.5
        text = "Hej världen"

    class DummyInfo:
        language = "sv"

    class DummyModel:
        def transcribe(self, *_a, **_k):
            return iter([DummySeg()]), DummyInfo()

    monkeypatch.setattr(transcribe, "_get_model", lambda: DummyModel())

    result = transcribe.transcribe_source("fake-source", trace_id="T123")

    assert result["payload"]["text"] == "Hej världen"
    assert outbox.exists()
    lines = outbox.read_text(encoding="utf-8").strip().splitlines()
    assert lines and "transcript" in lines[-1]
