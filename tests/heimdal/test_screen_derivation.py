"""SCREEN-02 derivation: one frame bundle -> one governed activity observation (#3344).

AC1 (`test_bundle_derives_and_publishes_observation`) and AC4
(`test_unprovenanced_observation_refuses_publish`). Both drive the production
entrypoint `app.heimdal.screen_derivation.derive_activity_observations` over
frames landed through the real SCREEN-01 ingress -- no hand-built raw rows and
no bypass of the governed publish path.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from app.heimdal import screen_derivation
from app.heimdal.observation_log import count_observations, read_observations_from
from app.heimdal.screen_derivation import (
    UnprovenancedObservationError,
    derive_activity_observations,
)
from tests.heimdal._screen_derivation_fixtures import (
    MACHINE,
    RAW_STORE_KEY,
    SENSOR_ADAPTER,
    SENSOR_VERSION,
    land_frame,
    reset_screen_derivation_state,
    stub_vision_runner,
)

pytestmark = pytest.mark.not_pg


@pytest.fixture(autouse=True)
def reset(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_screen_derivation_state(monkeypatch)


def _payloads() -> List[Dict[str, Any]]:
    return [dict(row.envelope["payload"]) for row in read_observations_from(0)]


def test_bundle_derives_and_publishes_observation(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC1: frame bundle + app metadata -> one observation on the governed path.

    Success path: the derived observation carries a textual activity summary,
    entity mentions, and per-axis confidence, and it reaches the log *through*
    `publish_full_observation` (spied at the production call site), not a
    bespoke insert. Completeness path: re-deriving the identical frame is
    idempotent -- the governed path dedups instead of double-publishing.
    """
    publishes: List[Dict[str, Any]] = []
    real_publish = screen_derivation.publish_full_observation

    def spy_publish(**kwargs: Any) -> Any:
        publishes.append(dict(kwargs))
        return real_publish(**kwargs)

    monkeypatch.setattr(screen_derivation, "publish_full_observation", spy_publish)

    frame = land_frame(frame="frame-a", observed_at="2026-07-11T08:00:00Z")
    runner = stub_vision_runner()

    tick = derive_activity_observations(
        [frame],
        episode_id="screen-session-1",
        vision_runner=runner,
        key=RAW_STORE_KEY,
    )

    assert tick.frames_read == 1
    assert tick.observations_published == 1
    assert tick.route.task_kind == "heimdal.screen_derivation"
    assert tick.route.paid_eligible is False

    # The one publish went through the governed, schema-validating seam.
    assert len(publishes) == 1
    assert publishes[0]["topic"] == "heimdal.observation.published"
    assert publishes[0]["source"] == "heimdal.screen_derivation"

    assert count_observations() == 1
    payload = _payloads()[0]
    assert payload["modality"] == "screen"
    assert payload["episode_id"] == "screen-session-1"
    assert "Obsidian" in str(payload["content"])
    assert payload["observed_at_start"] == "2026-07-11T08:00:00Z"
    assert payload["observed_at_end"] == "2026-07-11T08:00:00Z"

    # Entity mentions surfaced, and honestly unresolved (HEIM-6/HEIM-11:
    # derivation surfaces mentions, it does not mint canonical identities).
    mentions = payload["entity_mentions"]
    assert mentions and {m["resolution"] for m in mentions} == {"unresolved"}
    assert any(m["surface_form"] == "Obsidian" for m in mentions)

    # Per-axis confidence, never a single scalar (FABLE_COMPANION §2).
    confidence = payload["confidence"]
    assert set(confidence) >= {"attribution", "activity_summary", "entity_mention"}
    for axis in confidence.values():
        assert 0.0 <= axis["score"] <= 1.0
        assert axis["calibration"] in {"calibrated", "heuristic", "by_construction"}
    assert confidence["activity_summary"]["model_ref"] == tick.route.model_ref

    provenance = payload["provenance"]
    assert provenance["sensor"] == {
        "adapter": SENSOR_ADAPTER,
        "version": SENSOR_VERSION,
        "machine": MACHINE,
    }
    assert provenance["capture_chain"]
    assert provenance["content_identity"]
    assert provenance["content_hash"]
    assert provenance["stage_versions"]["screen_derivation"].endswith(
        screen_derivation.ENGINE_VERSION
    )
    assert provenance["model_ref"] == tick.route.model_ref
    assert payload["consent"]["grant_ref"]

    # Completeness: the same frame re-derived is idempotent on the governed path.
    replay = derive_activity_observations(
        [frame],
        episode_id="screen-session-1",
        vision_runner=stub_vision_runner(),
        key=RAW_STORE_KEY,
    )
    assert replay.observations_published == 0
    assert count_observations() == 1

    # And the identity is anchored to the EVIDENCE, not to the model's wording:
    # a replay whose local model rewords the summary must land on the same
    # observation_id (a revision of the same frames), never a second unlinked
    # observation that would double-count this activity downstream.
    original_id = _payloads()[0]["observation_id"]
    reworded = derive_activity_observations(
        [frame],
        episode_id="screen-session-1",
        vision_runner=stub_vision_runner(summary="Writing in Obsidian, different wording"),
        key=RAW_STORE_KEY,
    )
    assert reworded.observations_published == 1
    ids = {payload["observation_id"] for payload in _payloads()}
    assert ids == {original_id}, "replayed span must keep one evidence-derived identity"


def test_unprovenanced_observation_refuses_publish() -> None:
    """AC4 (INV-SCREEN-B): text derived, provenance incomplete -> no publish.

    Negative path: a bundle whose sensor cannot name the machine derives its
    activity text (the vision runner is called) but cannot stamp complete
    provenance, so the stage refuses loudly and the observation log stays
    empty -- never a partial write, never a silently unprovenanced row.
    Completeness path: the same frame with a complete sensor publishes.
    """
    unprovenanced = land_frame(
        frame="frame-unprovenanced",
        observed_at="2026-07-11T09:00:00Z",
        machine="",
    )
    runner = stub_vision_runner()

    with pytest.raises(UnprovenancedObservationError, match="machine"):
        derive_activity_observations(
            [unprovenanced],
            episode_id="screen-session-2",
            vision_runner=runner,
            key=RAW_STORE_KEY,
        )

    # The text WAS derived -- the refusal is about stamping, not about reading.
    assert runner.calls
    assert count_observations() == 0

    complete = land_frame(frame="frame-provenanced", observed_at="2026-07-11T09:01:00Z")
    tick = derive_activity_observations(
        [complete],
        episode_id="screen-session-2",
        vision_runner=stub_vision_runner(),
        key=RAW_STORE_KEY,
    )
    assert tick.observations_published == 1
    assert count_observations() == 1
