from __future__ import annotations

import ast
import inspect

import app.source_understanding.handoff as handoff
from app.source_understanding import (
    GovernedApplyPath,
    SourceUnderstandingRequest,
    build_source_understanding_packet,
    resolve_stabilized_note_review_choice,
    stage_stabilized_note_proposal,
)


def _packet(**overrides):
    data = {
        "source_id": "source-1684",
        "source_ref": "docs/source.md#L12-L18",
        "title": "Packet authority posture",
        "scope": "selected_passage",
        "selection_start_line": 12,
        "selection_end_line": 18,
        "text": (
            "Source Understanding must preserve source identity.\n"
            "The packet should distinguish source claims from agent interpretation.\n"
            "A stabilized note proposal requires human review before promotion."
        ),
    }
    data.update(overrides)
    return build_source_understanding_packet(SourceUnderstandingRequest(**data))


def test_p0_packet_can_stage_reviewable_stabilized_note_proposal() -> None:
    packet = _packet()

    proposal = stage_stabilized_note_proposal(packet)

    assert proposal.proposal_kind == "stabilized_note_proposal"
    assert proposal.target_note_kind == "literature_note"
    assert proposal.status == "non-authoritative staged stabilized-note proposal"
    assert proposal.draft_title.startswith("Stabilized note proposal:")
    assert "Non-authoritative draft for human review" in proposal.draft_body
    assert proposal.durable_writes is False
    assert proposal.memory_writes is False
    assert proposal.canonical_artifact_created is False


def test_stabilized_note_proposal_preserves_source_and_packet_provenance() -> None:
    packet = _packet(selection_start_line=None, selection_end_line=None)

    proposal = stage_stabilized_note_proposal(packet)

    assert proposal.source.source_id == packet.source.source_id
    assert proposal.source.source_ref == packet.source.source_ref
    assert proposal.packet_scope == packet.scope
    assert proposal.source_anchors
    assert proposal.anchor_limitations == [
        "Selection text is available, but exact source line anchors were not supplied."
    ]
    assert "non-authoritative understanding projection" in proposal.packet_provenance
    assert any("Agent interpretation remains review-required" in item for item in proposal.packet_provenance)


def test_stabilized_note_proposal_identity_includes_source_anchors() -> None:
    first = stage_stabilized_note_proposal(_packet(selection_start_line=12, selection_end_line=18))
    second = stage_stabilized_note_proposal(_packet(selection_start_line=13, selection_end_line=19))

    assert first.proposal_id != second.proposal_id


def test_handoff_exposes_distinct_review_choices() -> None:
    proposal = stage_stabilized_note_proposal(_packet())

    choices = {choice.choice_id: choice for choice in proposal.review_choices}

    assert set(choices) == {"apply", "defer", "reject", "revise"}
    assert choices["apply"].effect == "governed_mutation"
    assert choices["apply"].requires_governed_mutation_path is True
    for choice_id in ("defer", "reject", "revise"):
        assert choices[choice_id].effect == "runtime_only"
        assert choices[choice_id].mutates_durable_surfaces is False


def test_non_apply_choices_do_not_mutate_durable_surfaces() -> None:
    proposal = stage_stabilized_note_proposal(_packet())

    for choice_id in ("defer", "reject", "revise"):
        result = resolve_stabilized_note_review_choice(proposal, choice_id)
        assert result.status == "runtime_only_recorded"
        assert result.durable_writes is False
        assert result.memory_writes is False
        assert result.canonical_artifact_created is False


def test_apply_uses_governed_mutation_path_when_available() -> None:
    proposal = stage_stabilized_note_proposal(
        _packet(),
        apply_path=GovernedApplyPath(
            available=True,
            route_name="existing_governed_stabilized_note_apply",
            write_guard_action="test.write_guard.action",
            receipt_posture="receipt linked to source packet and proposal",
        ),
    )

    apply = next(choice for choice in proposal.review_choices if choice.choice_id == "apply")
    result = resolve_stabilized_note_review_choice(proposal, "apply")

    assert apply.available is True
    assert apply.mutates_durable_surfaces is True
    assert apply.requires_governed_mutation_path is True
    assert "existing_governed_stabilized_note_apply" in (apply.governed_route or "")
    assert "WriteGuard action test.write_guard.action" in (apply.governed_route or "")
    assert "receipt linked to source packet and proposal" in (apply.governed_route or "")
    assert result.status == "requires_governed_apply"
    assert result.receipt_required is True
    assert result.durable_writes is False
    assert result.canonical_artifact_created is False


def test_unavailable_apply_path_degrades_without_promotion() -> None:
    proposal = stage_stabilized_note_proposal(_packet())

    apply = next(choice for choice in proposal.review_choices if choice.choice_id == "apply")
    result = resolve_stabilized_note_review_choice(proposal, "apply")

    assert apply.available is False
    assert apply.unavailable_reason
    assert result.status == "degraded_unavailable"
    assert result.durable_writes is False
    assert result.memory_writes is False
    assert result.canonical_artifact_created is False


def test_handoff_module_does_not_write_or_import_mutation_surfaces() -> None:
    src = inspect.getsource(handoff)
    tree = ast.parse(src)

    imported_modules: set[str] = set()
    used_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name.lower() for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = (node.module or "").lower()
            imported_modules.add(module)
            for alias in node.names:
                imported_modules.add(f"{module}.{alias.name}".lower())
                used_names.add(alias.asname or alias.name)
        elif isinstance(node, ast.Name):
            used_names.add(node.id)
        elif isinstance(node, ast.Attribute):
            used_names.add(node.attr)

    for forbidden in (
        "app.db",
        "app.events",
        "app.index",
        "app.objects",
        "app.outbox",
        "app.vault",
        "app.write_guard",
    ):
        assert not any(forbidden in module for module in imported_modules)
    for symbol in ("ObjectStore", "VaultPort", "WriteGuard", "emit", "open"):
        assert symbol not in used_names
