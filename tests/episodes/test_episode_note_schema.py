"""AC1 (#3177, ERE-02): episode notes validate against ``schemas/episode-note.schema.json``
(ADR-0051 OD-1/OD-2 note-serialized situation model shape).

Verify: ``tests/episodes/test_episode_note_schema.py::test_episode_note_schema_validates_adr0051_shape``
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from app.episodes.schema import EpisodeSchemaValidationError, validate_episode_note_fields

pytestmark = pytest.mark.not_pg

_VALID_EPISODE_ID = "ep-11111111-2222-4333-8444-555555555555"


def _valid_fields(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "episode_id": _VALID_EPISODE_ID,
        "scope": "work",
        "title": "Debugging session",
        "time": {"start": "2026-07-11T10:00:00+00:00", "closed": False},
        "space": ["home-office"],
        "protagonists": ["rasmus"],
        "goal": ["ship-ere-02"],
        "causation": [],
        "parent_episode": None,
        "segmentation": "proposed",
        "derived_from": ["heimdal-session-abc123"],
    }
    base.update(overrides)
    return base


def test_episode_note_schema_validates_adr0051_shape() -> None:
    # A well-formed note validates cleanly.
    validate_episode_note_fields(_valid_fields())

    # Missing time.closed fails (closure is the load-bearing property, ADR-0051 §3 item 6).
    missing_closed = _valid_fields()
    missing_closed["time"] = {"start": "2026-07-11T10:00:00+00:00"}
    with pytest.raises(EpisodeSchemaValidationError):
        validate_episode_note_fields(missing_closed)

    # An unknown segmentation value fails (only proposed/accepted/re-cut are valid).
    with pytest.raises(EpisodeSchemaValidationError):
        validate_episode_note_fields(_valid_fields(segmentation="approved"))

    # A malformed episode_id (not the fused ep-<uuid> shape) fails.
    with pytest.raises(EpisodeSchemaValidationError):
        validate_episode_note_fields(_valid_fields(episode_id="not-a-fused-id"))

    # Missing required top-level fields fails (episode_id, scope, title, time, segmentation).
    for required in ("episode_id", "scope", "title", "time", "segmentation"):
        broken = copy.deepcopy(_valid_fields())
        del broken[required]
        with pytest.raises(EpisodeSchemaValidationError):
            validate_episode_note_fields(broken)

    # additionalProperties: false -- an unknown top-level field fails.
    with pytest.raises(EpisodeSchemaValidationError):
        validate_episode_note_fields(_valid_fields(unexpected_field="nope"))
