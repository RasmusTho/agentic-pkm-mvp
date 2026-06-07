from __future__ import annotations

from app.source_understanding import SourceUnderstandingRequest, build_source_understanding_packet


def _request(**overrides) -> SourceUnderstandingRequest:
    data = {
        "source_id": "source-1",
        "source_ref": "docs/source.md#selection",
        "title": "Authority-preserving projections",
        "scope": "selected_passage",
        "selection_start_line": 4,
        "selection_end_line": 9,
        "text": (
            "Source understanding must preserve source authority.\n"
            "The packet distinguishes source claims from agent interpretation.\n"
            "Evidence links claims to the supplied selection."
        ),
    }
    data.update(overrides)
    return SourceUnderstandingRequest(**data)


def test_packet_shape_includes_p0_lenses() -> None:
    packet = build_source_understanding_packet(_request())

    assert packet.packet_title == "Source Understanding Packet"
    assert packet.orientation
    assert packet.structure
    assert packet.claims
    assert packet.evidence


def test_packet_marks_non_authoritative_projection() -> None:
    packet = build_source_understanding_packet(_request())

    assert packet.status == "non-authoritative understanding projection"
    assert any("non-authoritative" in item for item in packet.review_posture)


def test_packet_preserves_source_anchors_or_limitations() -> None:
    packet = build_source_understanding_packet(_request(selection_start_line=None, selection_end_line=None))

    assert packet.source.source_id == "source-1"
    assert packet.source.source_ref == "docs/source.md#selection"
    assert packet.source.limitation
    assert all(evidence.source_anchor.limitation for evidence in packet.evidence)


def test_claims_distinguish_source_claim_from_agent_interpretation() -> None:
    packet = build_source_understanding_packet(_request())

    claim = packet.claims[0]
    assert "Source understanding must preserve source authority" in claim.claim
    assert "Agent interpretation:" in claim.agent_interpretation
    assert claim.review_needed is True


def test_evidence_links_to_claims_instead_of_generic_summary() -> None:
    packet = build_source_understanding_packet(_request())

    claim_texts = {claim.claim for claim in packet.claims}
    assert {item.claim for item in packet.evidence} <= claim_texts
    assert all(item.evidence_summary.startswith("Evidence is drawn") for item in packet.evidence)


def test_selected_passage_does_not_overclaim_whole_document_understanding() -> None:
    packet = build_source_understanding_packet(_request())

    assert packet.scope == "selected_passage"
    assert any("Selected-passage scope only" in item for item in packet.review_posture)


def test_packet_generation_has_no_durable_or_memory_writes() -> None:
    packet = build_source_understanding_packet(_request())

    assert packet.durable_writes is False
    assert packet.memory_writes is False
    assert packet.mutation_intents == []


def test_packet_identifies_stabilized_note_proposal_without_promotion() -> None:
    packet = build_source_understanding_packet(_request())

    assert any("stabilized literature-note proposal" in item for item in packet.possible_next_steps)
    assert packet.durable_writes is False
