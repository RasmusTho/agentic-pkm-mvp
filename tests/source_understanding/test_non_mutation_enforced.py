"""Tests that non-mutation flags on source-understanding objects are enforced.

Source understanding stays read-only. These tests verify that if code ever
attempts a durable or memory write while the corresponding flag is False, the
guard raises rather than allowing the write silently.

Issue: #1946
"""
from __future__ import annotations

import pytest

from app.source_understanding.p0 import SourceUnderstandingPacket
from app.source_understanding.guard import (
    assert_durable_write_allowed,
    assert_memory_write_allowed,
    SourceUnderstandingMutationError,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _minimal_packet(**overrides) -> SourceUnderstandingPacket:
    from app.source_understanding.p0 import SourceAnchor
    defaults = dict(
        scope="selected_passage",
        source=SourceAnchor(
            source_id="test-src",
            source_ref="test-ref",
            label="test",
        ),
        orientation=[],
        structure=[],
        claims=[],
        evidence=[],
        review_posture=[],
        possible_next_steps=[],
    )
    defaults.update(overrides)
    return SourceUnderstandingPacket(**defaults)


# ---------------------------------------------------------------------------
# AC-1: durable write rejected when durable_writes=False
# ---------------------------------------------------------------------------

def test_durable_write_rejected_when_flag_false() -> None:
    """A durable-write attempt while durable_writes=False must raise."""
    packet = _minimal_packet(durable_writes=False)
    with pytest.raises(SourceUnderstandingMutationError):
        assert_durable_write_allowed(packet)


# ---------------------------------------------------------------------------
# AC-2: memory write rejected when memory_writes=False
# ---------------------------------------------------------------------------

def test_memory_write_rejected_when_flag_false() -> None:
    """A memory-write attempt while memory_writes=False must raise."""
    packet = _minimal_packet(memory_writes=False)
    with pytest.raises(SourceUnderstandingMutationError):
        assert_memory_write_allowed(packet)


# ---------------------------------------------------------------------------
# AC-3: read-only flow unaffected
# ---------------------------------------------------------------------------

def test_read_only_flow_unaffected() -> None:
    """Normal read-only source-understanding flows complete without raising.

    Neither build_source_understanding_packet nor stage_stabilized_note_proposal
    should trigger the guard — they are pure read/build operations.
    """
    from app.source_understanding.p0 import (
        SourceUnderstandingRequest,
        build_source_understanding_packet,
    )
    from app.source_understanding.handoff import stage_stabilized_note_proposal

    request = SourceUnderstandingRequest(
        source_id="doc-1",
        source_ref="docs/example.md",
        title="Example document",
        text="This is a source document. It must preserve meaning. It should be reviewed.",
        scope="whole_document",
    )
    packet = build_source_understanding_packet(request)

    # Flags are False by default — read-only flow must never invoke the guard
    assert packet.durable_writes is False
    assert packet.memory_writes is False

    # Handoff build also stays read-only
    proposal = stage_stabilized_note_proposal(packet)
    assert proposal.durable_writes is False
    assert proposal.memory_writes is False

    # No exception means the read-only flow is unaffected
