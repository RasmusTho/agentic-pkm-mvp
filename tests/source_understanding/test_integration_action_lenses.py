from __future__ import annotations

import ast
import inspect

import app.source_understanding.integration_action as integration_action
from app.source_understanding import (
    SourceUnderstandingRequest,
    VaultContextReference,
    build_action_handoff,
    build_integration_action_lenses,
    build_source_understanding_packet,
)


def _packet(**overrides):
    data = {
        "source_id": "source-1686",
        "source_ref": "docs/source.md#L40-L55",
        "title": "Integration and action posture",
        "scope": "selected_passage",
        "selection_start_line": 40,
        "selection_end_line": 55,
        "text": (
            "Integration view requires source review before broader placement.\n"
            "Action view should remain a proposal until governed confirmation.\n"
            "The source distinguishes possible next steps from tasks."
        ),
    }
    data.update(overrides)
    return build_source_understanding_packet(SourceUnderstandingRequest(**data))


def _vault_context() -> list[VaultContextReference]:
    return [
        VaultContextReference(
            artifact_id="note:concept-1",
            source_ref="vault://Concepts/Source Placement.md",
            title="Source Placement",
            freshness="fresh",
        )
    ]


def test_integration_lens_carries_source_and_vault_references() -> None:
    lens = build_integration_action_lenses(_packet(), vault_context=_vault_context())

    retrieved = next(item for item in lens.integration if item.posture == "retrieved_context")

    assert retrieved.source_anchor.source_ref == "docs/source.md#L40-L55"
    assert retrieved.vault_reference is not None
    assert retrieved.vault_reference.artifact_id == "note:concept-1"
    assert retrieved.vault_reference.source_ref == "vault://Concepts/Source Placement.md"


def test_integration_lens_marks_retrieved_context_vs_agent_speculation() -> None:
    lens = build_integration_action_lenses(_packet(), vault_context=_vault_context())

    retrieved = [item for item in lens.integration if item.posture == "retrieved_context"]
    speculation = [item for item in lens.integration if item.posture == "agent_speculation"]

    assert retrieved
    assert all(item.vault_reference is not None for item in retrieved)
    assert speculation
    assert all(item.vault_reference is None for item in speculation)
    assert all("Agent speculation" in item.rationale for item in speculation)


def test_integration_lens_degrades_without_context() -> None:
    lens = build_integration_action_lenses(_packet(), vault_context=None)

    assert len(lens.integration) == 1
    candidate = lens.integration[0]
    assert candidate.posture == "context_unavailable"
    assert candidate.vault_reference is None
    assert candidate.degraded_reason == "vault context unavailable"
    assert "unavailable rather than fabricated" in candidate.rationale


def test_action_lens_returns_reviewable_proposals_not_tasks() -> None:
    lens = build_integration_action_lenses(_packet(), vault_context=_vault_context())

    assert lens.actions
    for proposal in lens.actions:
        assert proposal.proposal_class == "proposal"
        assert proposal.status == "non-authoritative review-needed action proposal"
        assert proposal.review_needed is True
        assert proposal.task_created is False
        assert proposal.commitment_created is False
        assert proposal.approval_granted is False
        assert proposal.urgency is None


def test_action_lens_generation_has_no_durable_side_effects() -> None:
    lens = build_integration_action_lenses(_packet(), vault_context=_vault_context())

    assert lens.durable_writes is False
    assert lens.memory_writes is False
    assert lens.canonical_artifact_created is False
    assert lens.task_created is False
    assert lens.commitment_created is False
    assert lens.receipt_created is False
    assert lens.mutation_intents == []
    assert all(action.durable_writes is False for action in lens.actions)
    assert all(action.memory_writes is False for action in lens.actions)

    src = inspect.getsource(integration_action)
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


def test_action_handoff_preserves_source_freshness_and_proposal_identity() -> None:
    lens = build_integration_action_lenses(
        _packet(),
        vault_context=_vault_context(),
        source_freshness="fresh:source-hash-abc",
    )
    proposal = lens.actions[0]

    handoff = build_action_handoff(proposal)

    assert handoff.proposal_id == proposal.proposal_id
    assert handoff.proposal_identity == proposal.proposal_identity
    assert handoff.source_anchor == proposal.source_anchor
    assert handoff.source_freshness == "fresh:source-hash-abc"
    assert handoff.status.startswith("handoff metadata only")
    assert handoff.durable_writes is False
    assert handoff.receipt_created is False
