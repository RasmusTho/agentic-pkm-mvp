"""Executable contract checks for the Karakeep -> Heimdal handoff (#3372).

This slice deliberately lands no adapter.  The tests make the checked-in
field map executable against the shipped published-v1 schema and pin the
already-sanctioned log/cursor seam for the later runtime slices.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.events.topic_schema_registry import validate_topic_payload
from app.events.types import HEIMDAL_OBSERVATION_PUBLISHED
from app.heimdal import candidate_projection, publish

pytestmark = pytest.mark.not_pg

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = (
    REPO_ROOT
    / "docs"
    / "KARAKEEP_MIMER_ACQUISITION"
    / "DEFINE_READING_SOURCE_AND_CANDIDATE_CONTRACT.md"
)
SCHEMA_PATH = REPO_ROOT / "schemas" / "events" / "heimdal.observation.published.v1.schema.json"


def _contract() -> str:
    return CONTRACT_PATH.read_text(encoding="utf-8")


def _marked_json(text: str, marker: str) -> dict:
    start = f"<!-- {marker}:start -->"
    end = f"<!-- {marker}:end -->"
    assert text.count(start) == 1
    assert text.count(end) == 1
    fenced = text.split(start, 1)[1].split(end, 1)[0].strip()
    assert fenced.startswith("```json\n") and fenced.endswith("\n```")
    return json.loads(fenced.removeprefix("```json\n").removesuffix("\n```"))


def test_karakeep_mapping_conforms_to_canonical_published_v1_schema() -> None:
    contract = _contract()
    payload = _marked_json(contract, "karakeep-published-v1-example")
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    validate_topic_payload(HEIMDAL_OBSERVATION_PUBLISHED, payload)

    required = set(schema["required"])
    assert required == {
        "observation_id",
        "episode_id",
        "observed_at_start",
        "attributions",
        "confidence",
        "provenance",
        "sensitivity",
        "consent",
    }
    assert required <= payload.keys()

    # Nullable/optional families stay semantically optional in the Karakeep
    # mapping. The sanctioned assembler represents a no-mention input as an
    # empty list, so the fixture must not require a source-derived mention.
    assert payload["entity_mentions"] == []
    assert payload["modality"] is None
    assert "Optional/nullable published-v1 families" in contract
    assert "assembler represents the no-mention case as\n`entity_mentions: []`" in contract
    assert "Karakeep REST" in contract
    assert "Mimer does not contact Karakeep" in contract


def test_contract_reuses_canonical_log_and_cursor_seam() -> None:
    contract = _contract()

    assert "## Canonical publication and cursor seam" in contract
    for name in (
        "publish_full_observation",
        "read_observations_for_consumer",
        "advance_cursor_for_consumer",
        "mimer.candidate_projector",
    ):
        assert f"`{name}`" in contract

    assert callable(publish.publish_full_observation)
    assert callable(publish.read_observations_for_consumer)
    assert callable(publish.advance_cursor_for_consumer)
    assert candidate_projection.CANDIDATE_CONSUMER_ID == "mimer.candidate_projector"

    for forbidden in (
        "karakeep.observation.published",
        "karakeep_observation_log",
        "mimer.karakeep_projector",
        "karakeep_candidate_cursor",
    ):
        assert forbidden not in contract

    assert "source checkpoint advances only after published evidence is durable" in contract
    assert "KMA-04 must change that\nbehavior before enabling Karakeep projection" in contract
    assert "affected row replayable, with a regression test at the production projector call site" in contract
