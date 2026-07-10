"""Executable design check for the Mimer side of the Karakeep handoff (#3372)."""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from app.heimdal import candidate_projection

pytestmark = pytest.mark.not_pg

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = (
    REPO_ROOT
    / "docs"
    / "KARAKEEP_MIMER_ACQUISITION"
    / "DEFINE_READING_SOURCE_AND_CANDIDATE_CONTRACT.md"
)


def test_contract_extends_existing_mimer_projector_without_parallel_consumer() -> None:
    contract = CONTRACT_PATH.read_text(encoding="utf-8")
    projector_source = inspect.getsource(candidate_projection.project_pending_candidates)

    assert "## Additive Mimer candidate mapping" in contract
    assert "`reading_source_note`" in contract
    assert "`requires_review: true`" in contract
    assert "`review_state: draft`" in contract
    assert "`Sources/Reading/Karakeep/<item-id>-<revision-prefix>.md`" in contract
    assert "first-write-wins" in contract
    assert "never deletes or overwrites" in contract
    assert "tombstone candidate" in contract

    # The chosen extension point is a shipped production path with the one
    # existing consumer identity and the real guarded materialization call.
    assert candidate_projection.CANDIDATE_CONSUMER_ID == "mimer.candidate_projector"
    assert "read_observations_for_consumer(consumer_id" in projector_source
    assert "write_candidate_note(" in projector_source
    assert "advance_cursor_for_consumer(consumer_id, rows)" in projector_source

    for forbidden in (
        "/api/capture",
        "companion capture",
        "Karakeep MCP",
    ):
        assert f"forbids `{forbidden}`" in contract
