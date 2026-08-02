"""SCREEN-02 coalescing: spans collapse, boundaries survive (#3344, INV-SCREEN-E).

AC3. Unchanged consecutive frames collapse into ONE span with a real
start/end duration; a shift in ANY of the four segmenter dimensions
(frontmost app, window/document, scope, derived goal) always creates a new
span boundary. Over-segmentation is the preferred failure direction: a merge
across a shift must fail, because a lost boundary is unrecoverable downstream
while a spurious one is a cheap re-cut.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from app.heimdal.observation_log import read_observations_from
from app.heimdal.screen_derivation import derive_activity_observations
from tests.heimdal._screen_derivation_fixtures import (
    RAW_STORE_KEY,
    land_frame,
    reset_screen_derivation_state,
)

pytestmark = pytest.mark.not_pg


@pytest.fixture(autouse=True)
def reset(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_screen_derivation_state(monkeypatch)


def _goal_runner(goals: List[str]) -> Any:
    """A vision runner that returns a scripted goal per successive frame."""
    remaining = list(goals)

    def runner(request: Any) -> Dict[str, Any]:
        dimensions = dict(request.dimensions)
        goal = remaining.pop(0) if remaining else "unchanged goal"
        return {
            "summary": f"Working in {dimensions.get('app', 'an app')}",
            "goal": goal,
            "mentions": [{"surface_form": dimensions.get("app", "unknown"), "kind_hint": "app"}],
            "confidence": 0.6,
        }

    return runner


def _spans() -> List[Dict[str, Any]]:
    payloads = [dict(row.envelope["payload"]) for row in read_observations_from(0)]
    return [
        {
            "start": payload["observed_at_start"],
            "end": payload["observed_at_end"],
            "frame_count": payload["content_structure"]["span"]["frame_count"],
            "dimensions": payload["content_structure"]["span"]["dimensions"],
        }
        for payload in payloads
    ]


SHIFTS: List[tuple[str, Dict[str, Any], List[str]]] = [
    ("app", {"app": "Safari"}, ["same goal", "same goal"]),
    ("window", {"window": "OTHER.md"}, ["same goal", "same goal"]),
    ("scope", {"scope": "private"}, ["same goal", "same goal"]),
    ("goal", {}, ["draft the ERE spec", "review PR #3185"]),
]


def test_span_boundaries_survive_on_dimension_shift(monkeypatch: pytest.MonkeyPatch) -> None:
    """A shift in any single segmenter dimension is never merged away.

    Success path (merge direction): three unchanged frames coalesce into one
    span with a real start/end duration. Completeness path (split direction):
    each of the four dimensions, shifted alone, produces two spans whose
    boundary lands exactly on the shifted frame -- a merge across the shift
    fails the test.
    """
    # --- merge direction: unchanged activity coalesces into ONE span
    frames = [
        land_frame(frame=f"steady-{index}", observed_at=f"2026-07-11T11:0{index}:00Z")
        for index in range(3)
    ]
    tick = derive_activity_observations(
        frames,
        episode_id="screen-session-steady",
        vision_runner=_goal_runner(["draft the ERE spec"] * 3),
        key=RAW_STORE_KEY,
    )
    assert tick.frames_read == 3
    assert tick.coalesced == 2
    assert tick.observations_published == 1

    spans = _spans()
    assert len(spans) == 1
    assert spans[0]["start"] == "2026-07-11T11:00:00Z"
    assert spans[0]["end"] == "2026-07-11T11:02:00Z"
    assert spans[0]["frame_count"] == 3

    # --- split direction: every dimension shift keeps its boundary
    for dimension, shifted_frame_kwargs, goals in SHIFTS:
        reset_screen_derivation_state(monkeypatch)

        first = land_frame(frame=f"{dimension}-1", observed_at="2026-07-11T12:00:00Z")
        second = land_frame(
            frame=f"{dimension}-2",
            observed_at="2026-07-11T12:01:00Z",
            **shifted_frame_kwargs,
        )

        shift_tick = derive_activity_observations(
            [first, second],
            episode_id=f"screen-session-{dimension}",
            vision_runner=_goal_runner(goals),
            key=RAW_STORE_KEY,
        )

        assert shift_tick.coalesced == 0, f"{dimension} shift was merged away"
        assert shift_tick.observations_published == 2, f"{dimension} shift lost a boundary"

        shift_spans = _spans()
        assert len(shift_spans) == 2, f"{dimension} shift did not produce two spans"
        assert shift_spans[0]["frame_count"] == 1 and shift_spans[1]["frame_count"] == 1
        assert shift_spans[0]["start"] == "2026-07-11T12:00:00Z"
        assert shift_spans[0]["end"] == "2026-07-11T12:00:00Z"
        # The boundary is real: the second span starts at the shifted frame and
        # no span reaches across the shift.
        assert shift_spans[1]["start"] == "2026-07-11T12:01:00Z"
        assert shift_spans[1]["end"] == "2026-07-11T12:01:00Z"
        assert (
            shift_spans[0]["dimensions"][dimension] != shift_spans[1]["dimensions"][dimension]
        ), f"{dimension} was not recorded as the shifted dimension"
