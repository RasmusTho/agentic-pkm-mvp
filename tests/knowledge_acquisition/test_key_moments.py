"""YSNV2-09 timestamped key-moment selection tests (#4116).

Every test drives the production entry point ``derive_key_moments`` over durable
transcript/claims artifacts in the memory ObjectStore, not a selection helper in isolation.
"""

from __future__ import annotations

import builtins
import socket
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone

import pytest

from app import objects as object_store_module
from app.knowledge_acquisition import key_moments as key_moments_module
from app.knowledge_acquisition.evidence_synthesis import validate_generated_language
from app.knowledge_acquisition.extraction_persistence import (
    persist_extraction_result,
    persist_normalized_transcript,
)
from app.knowledge_acquisition.extraction_registry import ExtractionResult
from app.knowledge_acquisition.key_moments import (
    KEY_MOMENTS_ARTIFACT_KIND,
    KEY_MOMENTS_STAGE,
    KEY_MOMENTS_STAGE_VERSION,
    derive_key_moments,
)
from app.knowledge_acquisition.normalize import NormalizedSegment, NormalizedTranscript
from app.knowledge_acquisition.raw_record import raw_record_object_id
from app.objects import ObjectStore
from app.stores import reset_store_backends
from tests.invariants._helpers import assert_validates

pytestmark = pytest.mark.not_pg

VIDEO_ID = "abcDEF12345"
CONTENT_IDENTITY = "sha256:moments-fixture"


def _raw_id(content_identity: str) -> str:
    return str(
        raw_record_object_id(source_kind="youtube_url", item_ref=VIDEO_ID, content_identity=content_identity)
    )


RAW_ID = _raw_id(CONTENT_IDENTITY)


@pytest.fixture(autouse=True)
def _memory_store(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("STORE_BACKEND", "memory")
    reset_store_backends()
    object_store_module._MEMORY_STORE.clear()
    yield
    object_store_module._MEMORY_STORE.clear()


def _segments(duration: float, step: float, *, text: str = "Talking about the topic.") -> tuple[NormalizedSegment, ...]:
    count = int(duration // step)
    return tuple(
        NormalizedSegment(start=index * step, end=(index + 1) * step, text=f"{text} {index}")
        for index in range(count)
    )


def _transcript(
    segments: tuple[NormalizedSegment, ...],
    *,
    language: str = "en",
    chapters: tuple[dict, ...] = (),
    content_identity: str = CONTENT_IDENTITY,
):
    normalized = NormalizedTranscript(
        segments=segments,
        language=language,
        language_detected=False,
        acquisition_method="captions_manual",
        quality_note="",
        chapters=chapters,
        source_content_identity=content_identity,
    )
    raw_record = {
        "content_identity": content_identity,
        "acquired_at": "2026-09-30T12:00:00+00:00",
        "scope_id": "scope:external/youtube",
        "sensitivity": "internal",
    }
    return persist_normalized_transcript(
        raw_record_id=_raw_id(content_identity), raw_record=raw_record, normalized=normalized
    ), normalized


def _claims(transcript, normalized, claims: list[dict]):
    result = ExtractionResult(
        extractor_id="claims",
        extractor_version=1,
        source_content_identity=transcript.content_identity,
        output={"claims": claims},
        model_identity={"provider": "fixture", "model": "fixture"},
        created_at=datetime(2026, 9, 30, 12, 5, tzinfo=timezone.utc),
    )
    return persist_extraction_result(
        raw_record_id=transcript.raw_record_id,
        normalized_artifact_id=transcript.object_id,
        normalized=normalized.as_dict(),
        result=result,
    )


def _claim(segment: NormalizedSegment, index: int, *, wording: str, paraphrase: str = "The source makes a claim.") -> dict:
    return {
        "source_wording": wording,
        "system_paraphrase": paraphrase,
        "anchors": [{"segment_index": index, "start": segment.start, "end": segment.end}],
    }


def test_selected_moments_are_timestamped_anchored_and_lineage_bearing() -> None:
    segments = _segments(600.0, 10.0)
    transcript, normalized = _transcript(
        segments,
        chapters=(
            {"start_time": 150.0, "end_time": 300.0, "title": "Setting up the lab"},
            # Malformed chapters are omitted and reported without suppressing healthy evidence.
            {"start_time": True, "title": "Bool start"},
            {"start_time": float("nan"), "title": "NaN start"},
            {"start_time": 9999.0, "title": "After the transcript"},
            {"start_time": 400.0, "title": "   "},
        ),
    )
    claims = _claims(
        transcript,
        normalized,
        [
            _claim(segments[3], 3, wording="Measure twice before cutting."),
            # Unresolvable anchor: omitted and reported, never rendered as an anchorless moment.
            {
                "source_wording": "Ghost claim.",
                "system_paraphrase": "A claim beyond the transcript.",
                "anchors": [{"segment_index": 999, "start": 0.0, "end": 1.0}],
            },
            "not-a-claim",
            {"source_wording": " ", "system_paraphrase": "Empty wording.", "anchors": [{"segment_index": 5, "start": 50.0, "end": 60.0}]},
        ],
    )

    persisted = derive_key_moments(transcript=transcript, item_ref=VIDEO_ID, claims_extraction=claims)

    assert persisted.moments, "supported evidence must produce at least one moment"
    for moment in persisted.moments:
        seconds = moment["timestamp_seconds"]
        assert isinstance(seconds, int) and seconds >= 0
        assert moment["timestamp_link"] == f"https://www.youtube.com/watch?v={VIDEO_ID}&t={seconds}s"
        assert moment["transcript_anchors"]
        for anchor in moment["transcript_anchors"]:
            assert anchor["anchor"] in transcript.anchors
        assert moment["content_identity"] == CONTENT_IDENTITY
        assert moment["stage"] == KEY_MOMENTS_STAGE
        assert moment["stage_version"] == KEY_MOMENTS_STAGE_VERSION
        assert moment["selection_rationale"]
        assert moment["derived_from"] == [RAW_ID, transcript.object_id, claims.object_id]
    by_time = {moment["timestamp_seconds"]: moment for moment in persisted.moments}
    assert set(by_time) == {30, 150}
    assert by_time[150]["evidence"][0] == {"kind": "chapter", "source_wording": "Setting up the lab"}
    assert persisted.dropped == ("chapter_anchor_unresolvable",) * 4 + ("claim_anchor_unresolvable",) * 3

    # Stable identity: re-deriving the same ancestors is an idempotent rebuild.
    replay = derive_key_moments(transcript=transcript, item_ref=VIDEO_ID, claims_extraction=claims)
    assert replay.object_id == persisted.object_id
    assert [m["moment_id"] for m in replay.moments] == [m["moment_id"] for m in persisted.moments]

    stored = ObjectStore().get_object(persisted.object_id)
    assert stored is not None and stored.kind == KEY_MOMENTS_ARTIFACT_KIND
    bundle = dict(stored.payload)
    assert_validates(bundle, "metadata-bundle.schema.json")
    assert bundle["authority_state"] == "derived"
    assert bundle["derived_from"] == [RAW_ID, transcript.object_id, claims.object_id]

    # Negative: an unsafe source identity cannot mint a timestamp link.
    with pytest.raises(key_moments_module.KeyMomentsError):
        derive_key_moments(transcript=transcript, item_ref="../evil?x=1", claims_extraction=claims)
    # Negative: a safe-looking but different video id cannot retarget the timestamp links.
    with pytest.raises(key_moments_module.KeyMomentsError):
        derive_key_moments(transcript=transcript, item_ref="otherVideo1", claims_extraction=claims)
    # Negative: claims from a different content identity cannot be mixed into lineage.
    other_transcript, other_normalized = _transcript(segments, content_identity="sha256:other")
    other_claims = _claims(other_transcript, other_normalized, [_claim(segments[0], 0, wording="Other.")])
    with pytest.raises(key_moments_module.KeyMomentsError):
        derive_key_moments(transcript=transcript, item_ref=VIDEO_ID, claims_extraction=other_claims)


def test_moment_selection_enforces_budget_diversity_and_evidence_relevance() -> None:
    # Long source: one hour, many claims clustered together plus sparse chapters.
    segments = _segments(3600.0, 5.0)
    chapters = tuple(
        {"start_time": float(start), "end_time": float(start + 600), "title": f"Part {n}"}
        for n, start in enumerate(range(0, 3600, 600), start=1)
    )
    transcript, normalized = _transcript(segments, chapters=chapters)
    clustered = [
        _claim(segments[index], index, wording=f"Clustered claim {index}.")
        for index in range(200, 230)  # 1000s..1150s: dense cluster
    ]
    spread = [
        _claim(segments[index], index, wording=f"Spread claim {index}.")
        for index in (60, 300, 500, 700)
    ]
    claims = _claims(transcript, normalized, clustered + spread)

    long_result = derive_key_moments(transcript=transcript, item_ref=VIDEO_ID, claims_extraction=claims)
    budget = long_result.budget
    times = [moment["timestamp_seconds"] for moment in long_result.moments]

    # Budget scales with source duration and is enforced.
    assert 1 <= len(times) <= budget["max_moments"]
    assert budget["max_moments"] >= 6
    # Diversity suppression: no two selected moments within the minimum gap.
    assert all(b - a >= budget["min_gap_seconds"] for a, b in zip(times, times[1:]))
    assert times == sorted(times)
    # The dense cluster yields at most one moment, the rest are suppressed, not selected.
    assert sum(1000 <= t <= 1150 for t in times) == 1
    assert long_result.rejected["diversity"] > 0
    # Relevance: every selected moment is supported by a claim or chapter, never plain timeline sampling.
    assert all(moment["evidence"] for moment in long_result.moments)
    assert long_result.rejected["unsupported"] > 0
    # Organizing structure alone is relevant evidence: an uncontested chapter start is selected.
    assert 3000 in times
    assert long_result.candidate_count > len(times)

    # Short source: tiny budget.
    short_segments = _segments(50.0, 5.0)
    short_transcript, short_normalized = _transcript(short_segments, content_identity="sha256:short")
    short_claims = _claims(
        short_transcript,
        short_normalized,
        [_claim(short_segments[i], i, wording=f"Short claim {i}.") for i in range(10)],
    )
    short_result = derive_key_moments(
        transcript=short_transcript, item_ref=VIDEO_ID, claims_extraction=short_claims
    )
    assert short_result.budget["max_moments"] == 1
    assert len(short_result.moments) == 1

    # Negative: evidence-free talking-head source selects nothing rather than sampling evenly.
    bare_transcript, _ = _transcript(segments, content_identity="sha256:bare")
    bare = derive_key_moments(transcript=bare_transcript, item_ref=VIDEO_ID)
    assert bare.moments == ()
    assert bare.status == "no_supported_moments"
    assert bare.rejected["unsupported"] == len(segments)


def test_timestamp_only_moments_need_no_frame_or_media_egress(monkeypatch: pytest.MonkeyPatch) -> None:
    segments = _segments(300.0, 10.0)
    transcript, normalized = _transcript(
        segments, chapters=({"start_time": 0.0, "end_time": 300.0, "title": "Only chapter"},)
    )
    claims = _claims(transcript, normalized, [_claim(segments[15], 15, wording="A no-visual claim.")])

    def _forbidden(*_args, **_kwargs):
        raise AssertionError("key-moment selection must not perform network or media egress")

    monkeypatch.setattr(socket, "socket", _forbidden)
    monkeypatch.setattr(socket, "create_connection", _forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", _forbidden)
    monkeypatch.setattr(subprocess, "run", _forbidden)
    monkeypatch.setattr(subprocess, "Popen", _forbidden)
    real_open = builtins.open

    def _no_file_writes(file, mode="r", *args, **kwargs):
        if any(flag in str(mode) for flag in ("w", "a", "x", "+")):
            raise AssertionError(f"key-moment selection must not write media files: {file}")
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", _no_file_writes)
    media_modules_before = {name for name in sys.modules if name.split(".")[0] in {"yt_dlp", "cv2", "ffmpeg", "PIL"}}

    persisted = derive_key_moments(transcript=transcript, item_ref=VIDEO_ID, claims_extraction=claims)

    assert persisted.status == "timestamp_only"
    assert persisted.output_mode == "timestamp_only"
    assert len(persisted.moments) == 2
    forbidden_keys = {"frame", "frames", "frame_ref", "media", "media_ref", "thumbnail", "image"}
    for moment in persisted.moments:
        assert forbidden_keys.isdisjoint(moment), moment
    stored = dict(ObjectStore().get_object(persisted.object_id).payload)
    assert forbidden_keys.isdisjoint(stored["extensions"])
    assert stored["extensions"]["output_mode"] == "timestamp_only"
    media_modules_after = {name for name in sys.modules if name.split(".")[0] in {"yt_dlp", "cv2", "ffmpeg", "PIL"}}
    assert media_modules_after == media_modules_before
    # Static seam guard: the module carries no media-acquisition dependency.
    source = open(key_moments_module.__file__, encoding="utf-8").read()
    for token in ("yt_dlp", "subprocess", "urllib", "requests", "httpx", "ffmpeg", "cv2"):
        assert token not in source

    # A source with no timed transcript is still a successful, empty timestamp-only result.
    empty_transcript, _ = _transcript((), content_identity="sha256:empty")
    empty = derive_key_moments(transcript=empty_transcript, item_ref=VIDEO_ID)
    assert empty.moments == () and empty.status == "no_supported_moments"


@pytest.mark.parametrize(
    ("language", "expected"),
    [("en", "en"), ("sv", "sv"), ("sv-SE", "sv"), ("fr", "en"), (None, "en")],
)
def test_moment_rationale_follows_source_language_policy(language: str | None, expected: str) -> None:
    segments = _segments(600.0, 10.0)
    chapter_title = {
        "sv": "Så bygger du en stol",
        "sv-SE": "Så bygger du en stol",
        "fr": "Comment construire une chaise",
    }.get(language or "", "How to build a chair")
    source_wording = {
        "sv": "Mät två gånger innan du sågar.",
        "sv-SE": "Mät två gånger innan du sågar.",
        "fr": "Mesurez deux fois avant de couper.",
    }.get(language or "", "Measure twice before cutting.")
    transcript, normalized = _transcript(
        segments,
        language=language,  # type: ignore[arg-type]
        chapters=({"start_time": 0.0, "end_time": 300.0, "title": chapter_title},),
        content_identity=f"sha256:lang-{language}",
    )
    claims = _claims(
        transcript,
        normalized,
        [
            _claim(segments[0], 0, wording=source_wording),
            _claim(segments[40], 40, wording=source_wording),
        ],
    )

    persisted = derive_key_moments(transcript=transcript, item_ref=VIDEO_ID, claims_extraction=claims)

    assert persisted.rationale_language == expected
    kinds = set()
    for moment in persisted.moments:
        assert moment["rationale_language"] == expected
        assert validate_generated_language(moment["selection_rationale"], expected), moment
        for evidence in moment["evidence"]:
            kinds.add(evidence["kind"])
            # Source wording is preserved verbatim, never translated into the rationale language.
            expected_wording = chapter_title if evidence["kind"] == "chapter" else source_wording
            assert evidence["source_wording"] == expected_wording
            assert evidence["source_wording"] not in moment["selection_rationale"]
    assert kinds == {"chapter", "claim"}
    # Co-supported moment (chapter + claim at t=0) and claim-only moment (t=400) both render.
    assert [m["timestamp_seconds"] for m in persisted.moments] == [0, 400]
