"""Contract tests for the conservative content router (YSNV2-07, #4114).

Enforcement assertions drive the production path: a raw record through ``assemble_candidate``
(normalize -> route) and ``render_candidate_note``. No model is consulted by the router.
"""

from __future__ import annotations

import re

import pytest
import yaml

from app.knowledge_acquisition import content_router
from app.knowledge_acquisition.candidate_writeback import assemble_candidate, render_candidate_note
from app.knowledge_acquisition.content_router import (
    GENERIC_PROFILE,
    MAX_PROFILES,
    ProfileDefinition,
    RouterConfig,
    route_content,
)
from app.knowledge_acquisition.evidence_synthesis import validate_resolvable_anchor
from app.knowledge_acquisition.extraction_registry import ExtractionResult

DECISION_LINES = (
    "There are two options on the table today.",
    "The first alternative is to rent, the other is to buy.",
    "My criteria are cost, flexibility and risk.",
    "The trade-off is between stability and freedom.",
    "Here is the framework I use to decide.",
    "Thanks for watching.",
)
SCIENCE_LINES = (
    "A new study followed ten thousand people.",
    "The researchers measured sleep with wrist sensors.",
    "The data from the control group looked different.",
    "They found that short sleep raised risk.",
    "The results show a clear pattern, but the hypothesis is still uncertain.",
    "Subscribe for more.",
)
GENERIC_LINES = (
    "Welcome back to the channel.",
    "Today we cook pasta with tomatoes.",
    "You might decide to add basil at the end.",
    "Enjoy your meal.",
)


def _vtt(lines: tuple[str, ...]) -> str:
    cues = [
        f"00:00:{2 * i:02d}.000 --> 00:00:{2 * i + 2:02d}.000\n{line}\n"
        for i, line in enumerate(lines)
    ]
    return "WEBVTT\n\n" + "\n".join(cues)


def _raw(lines: tuple[str, ...], *, language: str = "en", identity: str = "sha256:router") -> dict:
    return {
        "source_kind": "youtube_url",
        "item_ref": "router-video",
        "url": "https://youtube.com/watch?v=router-video",
        "content_identity": identity,
        "acquisition_method": "captions_manual",
        "caption_language": language,
        "caption_body": _vtt(lines),
        "metadata": {"title": "Router fixture", "channel": "Fixture", "publish_date": "20260101", "chapters": []},
        "provenance": {"source_kind": "youtube_url", "url": "https://youtube.com/watch?v=router-video"},
    }


def _synthesis(identity: str) -> tuple[ExtractionResult, ...]:
    anchor = {"segment_index": 0, "start": 0.0, "end": 2.0}
    return (
        ExtractionResult(
            extractor_id="synthesis",
            extractor_version=1,
            source_content_identity=identity,
            output={
                "synthesis_sentences": [{"text": "The video weighs renting against buying.", "anchors": [anchor]}],
                "model_confidence": 0.8,
            },
            model_identity={"provider": "fixture", "model": "fixture"},
        ),
    )


def _normalized(lines: tuple[str, ...]) -> dict:
    return {
        "language": "en",
        "segments": [
            {"start": float(2 * i), "end": float(2 * i + 2), "text": line}
            for i, line in enumerate(lines)
        ],
    }


def _frontmatter(note: str) -> dict:
    return yaml.safe_load(note.split("---\n", 2)[1])


def test_router_is_bounded_and_falls_back_to_generic_on_uncertainty_or_failure(monkeypatch) -> None:
    # Success: a decision-framework source routes to that profile with inspectable, anchored evidence.
    route = route_content(_normalized(DECISION_LINES))
    assert not route.is_generic and route.fallback_reason is None
    assert [p.profile_id for p in route.profiles] == ["decision_framework"]
    ranked = route.profiles[0]
    assert len(ranked.cue_families) >= RouterConfig().min_cue_families
    assert ranked.evidence and len({e.segment_index for e in ranked.evidence}) >= RouterConfig().min_evidence_segments
    segments = _normalized(DECISION_LINES)["segments"]
    for item in ranked.evidence:
        assert validate_resolvable_anchor(
            {"segment_index": item.segment_index, "start": item.start, "end": item.end}, segments
        )
        assert item.cue_family in ranked.cue_families

    # Multi-label but ranked: a mixed source admits both initial profiles, highest score first.
    mixed = route_content(_normalized(SCIENCE_LINES + DECISION_LINES[:5]))
    assert {p.profile_id for p in mixed.profiles} == {"decision_framework", "documentary_science"}
    assert [p.score for p in mixed.profiles] == sorted((p.score for p in mixed.profiles), reverse=True)

    # Bounded: even with three qualifying profiles and a config asking for more, at most two return.
    cues = content_router.INITIAL_PROFILES[0].cue_families
    three = tuple(ProfileDefinition(profile_id=f"p{i}", cue_families=cues) for i in range(3))
    bounded = route_content(_normalized(DECISION_LINES), profiles=three, config=RouterConfig(max_profiles=5))
    assert len(bounded.profiles) == MAX_PROFILES == 2

    # Uncertainty: a single incidental cue (``decide``) is not enough evidence for a profile.
    for weak in (_normalized(GENERIC_LINES), {"segments": "not-a-list"}, {}):
        generic = route_content(weak)
        assert generic.is_generic and generic.profiles == ()
        assert generic.fallback_reason == "insufficient_confidence"
        assert not generic.failed
        assert generic.describe().startswith(GENERIC_PROFILE)

    # Failure: an exception inside routing never escapes; it falls back to generic, visibly failed.
    def _boom(*_args, **_kwargs):
        raise RuntimeError("cue table corrupted")

    monkeypatch.setattr(content_router, "_score_profile", _boom)
    failed = route_content(_normalized(DECISION_LINES))
    assert failed.is_generic and failed.failed
    assert failed.fallback_reason is not None and failed.fallback_reason.startswith("routing_failed")

    # Production call site: assembly routes, falls back on failure, and the note stays generic,
    # visibly degraded, with the universal spine intact and no module section.
    identity = "sha256:router-failure"
    candidate = assemble_candidate(
        _raw(DECISION_LINES, identity=identity), extraction_results=_synthesis(identity)
    )
    assert candidate.content_route is not None and candidate.content_route.failed
    note = render_candidate_note(candidate)
    frontmatter = _frontmatter(note)
    assert frontmatter["degraded"] is True
    assert frontmatter["content_route"] == {"profiles": [], "fallback": "routing_failed"}
    assert "### Evidence-anchored synthesis" in note
    assert "Decision framework" not in note
    assert re.search(r"\*\*Content route:\*\* generic \(routing_failed", note)
    assert "Content routing failed" in note
    monkeypatch.undo()

    # Production call site, success and insufficient-confidence paths.
    routed = assemble_candidate(_raw(DECISION_LINES, identity="sha256:router-ok"), extraction_results=())
    assert routed.content_route is not None
    assert [p.profile_id for p in routed.content_route.profiles] == ["decision_framework"]
    routed_note = render_candidate_note(routed)
    assert _frontmatter(routed_note)["content_route"]["profiles"] == ["decision_framework"]
    assert "degraded" not in _frontmatter(routed_note)

    plain = assemble_candidate(_raw(GENERIC_LINES, identity="sha256:router-generic"), extraction_results=())
    assert plain.content_route is not None and plain.content_route.is_generic
    plain_note = render_candidate_note(plain)
    assert _frontmatter(plain_note)["content_route"] == {"profiles": [], "fallback": "insufficient_confidence"}
    assert "degraded" not in _frontmatter(plain_note)
    assert "**Content route:** generic (insufficient_confidence)" in plain_note


def test_router_config_rejects_unsafe_bounds() -> None:
    with pytest.raises(ValueError):
        RouterConfig(max_profiles=0)
    with pytest.raises(ValueError):
        RouterConfig(min_cue_families=1)
