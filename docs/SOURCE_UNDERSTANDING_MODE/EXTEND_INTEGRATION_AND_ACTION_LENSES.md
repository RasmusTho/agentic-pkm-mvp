---
name: Extend Integration And Action Lenses
description: Add Integration and Action lenses as source-bounded proposal outputs after P0 and P1 validation.
task_id: SUMODE-P2
state: blocked-post-p1
issue: 1686
source_anchor: docs/SOURCE_UNDERSTANDING_MODE/PARENT_FEATURE_ISSUE.md :: Implementation Tasks
parent_capability: SOURCE_UNDERSTANDING_MODE
prerequisites: [SUMODE-P0, SUMODE-P1, SUMODE-HANDOFF]
depends_on: [DELIVER_P0_SOURCE_UNDERSTANDING_PACKET.md, CONNECT_STABILIZED_NOTE_PROPOSAL_HANDOFF.md, EXTEND_CONCEPT_AND_CRITIQUE_LENSES.md]
can_parallelize_with: []
---

# Extend Integration And Action Lenses

## Purpose

Integration and Action connect source interpretation to the broader vault and possible next steps. They are higher risk because they can easily become hidden prioritization, task creation, or mutation authority.

## What This Task Does

Extend Source Understanding Mode with:

- Integration view: possible connections to existing notes, projects, concepts, or work, with source and vault references.
- Action view: possible next steps for the human, explicitly proposal-class and review-needed.

The output must remain bounded by the source packet, the retrieved/available vault context, and the existing governance boundary.

## Concretely

- Integration candidates carry both source anchors and vault/artifact references where available.
- Integration candidates distinguish retrieved evidence from agent speculation.
- Action candidates are labeled as proposals or possible next steps, not tasks, commitments, approvals, or urgency.
- If broader context is unavailable, the lenses degrade rather than inventing connections.
- No task, note, relation, metadata, or memory mutation occurs from generating the lenses.

## Why This Matters

These lenses are useful only if the human can inspect why a connection or action is suggested. Without explicit proposal posture, they would turn source understanding into ungoverned work steering.

## Acceptance Criteria

- [ ] Integration lens returns candidate connections with source anchors and vault/artifact references where available. Verify: `tests/source_understanding/test_integration_action_lenses.py::test_integration_lens_carries_source_and_vault_references`.
- [ ] Integration lens distinguishes retrieved context from agent speculation. Verify: `tests/source_understanding/test_integration_action_lenses.py::test_integration_lens_marks_retrieved_context_vs_agent_speculation`.
- [ ] Integration lens degrades when vault context is unavailable instead of fabricating links. Verify: `tests/source_understanding/test_integration_action_lenses.py::test_integration_lens_degrades_without_context`.
- [ ] Action lens returns possible next steps as proposal-class review objects, not durable tasks or approvals. Verify: `tests/source_understanding/test_integration_action_lenses.py::test_action_lens_returns_reviewable_proposals_not_tasks`.
- [ ] Action lens does not create commitments, notes, relations, metadata, memory, or receipts by generation alone. Verify: `tests/source_understanding/test_integration_action_lenses.py::test_action_lens_generation_has_no_durable_side_effects`.
- [ ] Any handoff to Act/Panel/governance preserves source freshness and proposal identity. Verify: `tests/source_understanding/test_integration_action_lenses.py::test_action_handoff_preserves_source_freshness_and_proposal_identity`.

## How to Verify (Pre-Merge)

Local:

- `pytest tests/source_understanding/test_integration_action_lenses.py`
- re-run P0 and Concept/Critique tests
- focused retrieval or Companion UI tests if context lookup or UI handoff is touched
- `git diff --check`
- `python3 scripts/docs_guard.py` if docs/contracts change

Post-merge:

- Post a child validation receipt to #1646 naming the source/vault reference posture, degraded-context behavior, and no-mutation proof.

## Out of Scope

- Creating durable tasks, commitments, relations, concept notes, or literature notes.
- Treating Action suggestions as urgency, priority, or approval.
- Broad autonomous research automation.
- Hidden memory promotion from source interpretation.
- Integration over private/work/creative domains without the existing context and trust boundaries.

## Related Docs

- Parent: [README.md](README.md), [PARENT_FEATURE_ISSUE.md](PARENT_FEATURE_ISSUE.md)
- Prerequisites: [CONNECT_STABILIZED_NOTE_PROPOSAL_HANDOFF.md](CONNECT_STABILIZED_NOTE_PROPOSAL_HANDOFF.md), [EXTEND_CONCEPT_AND_CRITIQUE_LENSES.md](EXTEND_CONCEPT_AND_CRITIQUE_LENSES.md)
- `docs/CAPABILITY_CONTRACT_MODEL.md :: Proposal-only capability semantics`
- `docs/CONCEPTS/WORKFLOW_MUTATION_AND_GOVERNANCE_SEMANTICS.md :: Proposal lifecycle`
- `docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md :: Authority rules`
- `companion-ui/docs/COMPANION_UI_STATE_MAP.md :: Authority posture per mode`

## Related GitHub Issues

GitHub Issue #1686. It must remain `agent:blocked` until P0, handoff, and P1 receipts are posted to the parent.
