from __future__ import annotations

import pytest

from app.events.topic_schema_registry import validate_topic_payload

pytestmark = pytest.mark.not_pg


def test_screen_observation_validates_and_publishes() -> None:
    validate_topic_payload("heimdal.observation.published", {
        "observation_id": "screen-1", "episode_id": "session-1", "sequence": 0,
        "observed_at_start": "2026-07-11T08:00:00Z", "observed_at_end": "2026-07-11T08:01:00Z",
        "clock_basis": "device_metadata", "attributions": [{"mention_id": "operator", "role": "recorder", "resolution": "resolved", "basis": "capture_context"}],
        "modality": "screen", "content": "Editing a note", "confidence": {"attribution": {"score": 1.0, "calibration": "by_construction"}},
        "provenance": {"sensor": {"adapter": "macos", "version": "v1", "machine": "mac-1"}, "capture_chain": ["macos_screen_observer"], "content_hash": "h", "content_identity": "i"},
        "sensitivity": "private", "consent": {"basis": "screen_always_on", "grant_ref": "screen-grant", "third_party": "none"},
    })
