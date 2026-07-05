"""KA-03 tests for the deterministic raw -> normalized transcript stage.

Pure fixtures, no network, no store. Exercises the rolling-cue dedup pattern real yt-dlp
auto-captions exhibit (a 2-line rolling window where each cue repeats the previous cue's
trailing line and adds one new line — the yt-dlp #1734 pattern
`docs/KNOWLEDGE_ACQUISITION/RESEARCH_2026-07.md` §3 names), determinism, and schema parity
between the caption path and the ASR path.
"""

from __future__ import annotations

import copy

from app.knowledge_acquisition.normalize import (
    NormalizedSegment,
    dedup_rolling_cues,
    normalize,
    parse_caption_cues,
)

# A realistic rolling auto-caption VTT body: each cue is a 2-line rolling window. Cue 2's first
# line repeats cue 1's second line; cue 3's first line repeats cue 2's second line; etc. This is
# exactly the yt-dlp #1734 duplication pattern - a normalizer that doesn't dedup would emit every
# line twice.
ROLLING_AUTO_CAPTION_VTT = """WEBVTT
Kind: captions
Language: en

00:00:00.000 --> 00:00:02.000 align:start position:0%
Hello<00:00:00.500><c> world</c>
this is a rolling

00:00:01.500 --> 00:00:04.000 align:start position:0%
this is a rolling
caption test in action

00:00:03.500 --> 00:00:06.000 align:start position:0%
caption test in action
with three total lines
"""

MANUAL_CAPTION_VTT = """WEBVTT

00:00:00.000 --> 00:00:02.000
Hello manual world.

00:00:02.000 --> 00:00:04.000
No duplication here.
"""


def _raw_record(**overrides):
    record = {
        "source_kind": "youtube_url",
        "item_ref": "abcdefghijk",
        "content_identity": "sha256:deadbeef",
        "acquisition_method": "captions_auto",
        "caption_language": "en",
        "caption_body": ROLLING_AUTO_CAPTION_VTT,
        "metadata": {
            "title": "A Test Video",
            "language": "en",
            "chapters": [],
        },
    }
    record.update(overrides)
    return record


def test_rolling_cue_dedup_preserves_timestamps():
    result = normalize(_raw_record())

    texts = [seg.text for seg in result.segments]
    # Every genuinely new line survives exactly once, in order; no consecutive duplicate lines.
    # (Cue 1 contributes both of its lines since neither repeats a prior emitted line; cue 2's
    # first line is the rolling repeat of cue 1's second line and is dropped; cue 3's first line
    # is the rolling repeat of cue 2's second line and is dropped.)
    assert texts == [
        "Hello world",
        "this is a rolling",
        "caption test in action",
        "with three total lines",
    ]
    for a, b in zip(texts, texts[1:]):
        assert a != b

    # Timestamps are preserved from the cue that introduced each line (not zeroed/collapsed).
    assert result.segments[0].start == 0.0
    assert result.segments[0].end == 2.0
    assert result.segments[1].start == 0.0
    assert result.segments[1].end == 2.0
    assert result.segments[2].start == 1.5
    assert result.segments[2].end == 4.0
    assert result.segments[3].start == 3.5
    assert result.segments[3].end == 6.0


def test_dedup_rolling_cues_unit_behavior():
    # Direct unit check of the dedup helper against parsed cues, independent of normalize().
    cues = parse_caption_cues(ROLLING_AUTO_CAPTION_VTT)
    assert len(cues) == 3  # three rolling cues in the fixture

    segments = dedup_rolling_cues(cues)
    assert segments == (
        NormalizedSegment(start=0.0, end=2.0, text="Hello world"),
        NormalizedSegment(start=0.0, end=2.0, text="this is a rolling"),
        NormalizedSegment(start=1.5, end=4.0, text="caption test in action"),
        NormalizedSegment(start=3.5, end=6.0, text="with three total lines"),
    )


def test_asr_and_caption_paths_share_schema():
    caption_result = normalize(_raw_record())

    asr_record = {
        "source_kind": "youtube_url",
        "item_ref": "abcdefghijk",
        "content_identity": "sha256:asrbeef",
        "acquisition_method": "asr",
        "language": "en",
        "segments": [
            {"start": 0.0, "end": 2.0, "text": "  Hello   world  "},
            {"start": 2.0, "end": 4.5, "text": "this is asr output"},
        ],
        "metadata": {"title": "A Test Video", "language": "en", "chapters": []},
    }
    asr_result = normalize(asr_record)

    # Same field set / same dict shape from as_dict() for both paths.
    assert set(caption_result.as_dict().keys()) == set(asr_result.as_dict().keys())
    for seg in caption_result.segments + asr_result.segments:
        assert set(seg.as_dict().keys()) == {"start", "end", "text", "speaker"}

    # ASR segments pass through with whitespace normalized, same NormalizedSegment shape.
    assert asr_result.segments[0].text == "Hello world"
    assert asr_result.segments[1].text == "this is asr output"
    assert asr_result.acquisition_method == "asr"
    assert asr_result.language_detected is True


def test_normalize_is_deterministic():
    record = _raw_record()
    # Normalize the *same* raw record twice (a fresh deep copy each time, so no aliasing/mutation
    # of the input across calls) and assert byte-identical output.
    first = normalize(copy.deepcopy(record))
    second = normalize(copy.deepcopy(record))

    assert first.as_dict() == second.as_dict()
    assert first == second

    # Also deterministic across an ASR-shaped record.
    asr_record = {
        "source_kind": "youtube_url",
        "item_ref": "zzz",
        "content_identity": "sha256:asr2",
        "acquisition_method": "asr",
        "language": "sv",
        "segments": [{"start": 0.0, "end": 1.0, "text": "hej"}],
        "metadata": {"title": "T", "language": "sv", "chapters": []},
    }
    asr_first = normalize(copy.deepcopy(asr_record))
    asr_second = normalize(copy.deepcopy(asr_record))
    assert asr_first.as_dict() == asr_second.as_dict()


def test_language_detected_and_method_propagated():
    for method in ("captions_manual", "captions_auto"):
        record = _raw_record(
            acquisition_method=method,
            caption_body=MANUAL_CAPTION_VTT if method == "captions_manual" else ROLLING_AUTO_CAPTION_VTT,
        )
        result = normalize(record)
        assert result.acquisition_method == method
        assert result.language_detected is True
        assert result.language == "en"
        assert result.quality_note  # non-empty, deterministic string per method

    asr_record = {
        "source_kind": "youtube_url",
        "item_ref": "abcdefghijk",
        "content_identity": "sha256:asrbeef",
        "acquisition_method": "asr",
        "language": "sv",
        "segments": [{"start": 0.0, "end": 1.0, "text": "hej"}],
        "metadata": {"title": "A Test Video", "language": "sv", "chapters": []},
    }
    asr_result = normalize(asr_record)
    assert asr_result.acquisition_method == "asr"
    assert asr_result.language_detected is True
    assert asr_result.language == "sv"


def test_manual_captions_no_dedup_needed_pass_through_unchanged():
    result = normalize(_raw_record(acquisition_method="captions_manual", caption_body=MANUAL_CAPTION_VTT))
    texts = [seg.text for seg in result.segments]
    assert texts == ["Hello manual world.", "No duplication here."]


def test_lineage_stamps_content_identity_and_stage_version():
    result = normalize(_raw_record())
    assert result.source_content_identity == "sha256:deadbeef"
    assert result.stage == "normalize"
    assert result.stage_version == 1
