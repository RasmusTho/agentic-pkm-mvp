from __future__ import annotations

import os

import pytest

from app.agents.pipeline import ingest_and_chunk
from app.ingest.chunk_policy import speaker_aware_chunks
from app.ingest.deduper import Deduper

pytestmark = pytest.mark.not_pg


def test_speaker_chunks_respect_boundaries() -> None:
    segments = [
        {"speaker": "beta", "text": "beta follow up details", "start": 5.0, "end": 7.0},
        {"speaker": "alpha", "text": "alpha opens the call", "start": 0.0, "end": 2.0},
        {"speaker": "alpha", "text": "alpha hands over context", "start": 2.0, "end": 4.0},
    ]
    chunks = speaker_aware_chunks(segments, max_chars=60)
    assert [chunk["speaker"] for chunk in chunks] == ["alpha", "beta"]
    assert chunks[0]["speaker_segments"] == 2
    assert chunks[0]["start"] <= chunks[0]["end"]


def test_pipeline_flag_off_matches_legacy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DIARIZE_ENABLE", "0")
    monkeypatch.setattr("app.agents.pipeline._deduper", Deduper())
    obj = {
        "uuid": "flag-off",
        "text": "single speaker transcript.",
        "segments": [
            {"speaker": "alpha", "text": "alpha start"},
            {"speaker": "beta", "text": "beta follow"},
        ],
    }
    chunks = ingest_and_chunk(obj)
    assert all("speaker" not in chunk for chunk in chunks if chunk["kind"] == "chunk")


def test_pipeline_flag_on_emits_speaker_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DIARIZE_ENABLE", "1")
    monkeypatch.setattr("app.agents.pipeline._deduper", Deduper())
    obj = {
        "uuid": "flag-on",
        "text": "",
        "segments": [
            {"speaker": "alpha", "text": "alpha intro", "start": 0.0, "end": 1.0},
            {"speaker": "beta", "text": "beta reply", "start": 1.0, "end": 2.0},
        ],
    }
    chunks = ingest_and_chunk(obj)
    speaker_chunks = [chunk for chunk in chunks if chunk["kind"] == "chunk"]
    assert speaker_chunks[0]["speaker"] == "alpha"
    assert speaker_chunks[0]["start"] == pytest.approx(0.0)

    # reset env for other tests
    os.environ.pop("DIARIZE_ENABLE", None)


def test_long_segment_is_split(monkeypatch: pytest.MonkeyPatch) -> None:
    long_text = "alpha segment " * 120
    segments = [
        {"speaker": "alpha", "text": long_text, "start": 0.0, "end": 12.0},
    ]
    chunks = speaker_aware_chunks(segments, max_chars=80)
    assert len(chunks) >= 2
    assert all(len(chunk["text"]) <= 80 for chunk in chunks)
    starts = [chunk["start"] for chunk in chunks]
    assert starts == sorted(starts)


def test_boundary_split_for_same_speaker(monkeypatch: pytest.MonkeyPatch) -> None:
    segments = [
        {"speaker": "alpha", "text": "short intro", "start": 0.0, "end": 1.0},
        {"speaker": "alpha", "text": "alpha " * 120, "start": 1.0, "end": 5.0},
    ]
    chunks = speaker_aware_chunks(segments, max_chars=50)
    assert all(len(chunk["text"]) <= 50 for chunk in chunks)
    assert len(chunks) >= 3
