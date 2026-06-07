---
name: Source Understanding Mode Parent Feature Issue
description: Local source for the live #1646 parent validation hub.
issue: 1646
state: open-validation-hub
authority: GitHub Issue #1646 is the live backlog and validation surface; this file records the repo-local source contract.
---

# Source Understanding Mode Parent Feature Issue

GitHub issue: #1646
Lifecycle state: open parent validation hub, blocked on child delivery.

## Context

Source Understanding Mode establishes a concrete Yggdrasil capability for complex source material such as research papers, reports, long articles, retained source artifacts, or selected passages.

The goal is not generic summarization. The goal is to help the human understand, review, critique, connect, and decide what to do with a source while preserving source authority, provenance, review posture, and human control.

## Scope

The parent scope is the capability outcome:

- a documented product and authority model for Source Understanding Mode;
- a working first vertical slice for a whole-source or selection-scoped input path;
- source-anchored understanding packets;
- a reviewable stabilized-note proposal handoff without auto-promotion;
- follow-up lenses for Concept, Critique, Integration, and Action delivered only after P0 validation; and
- owner-doc promotion only after delivered child receipts prove the supported truth.

## Source Anchors

- `docs/HUMAN-FLOWS.md :: Canonical human loops` - `Source -> interpret -> stabilize`.
- `docs/COGNITIVE_PROSTHESIS_CHARTER.md :: source authority, provenance, write guards, events, and receipts`.
- `docs/CAPABILITY_CONTRACT_MODEL.md :: Synthesis / Review` - read-only/proposal capability semantics.
- `docs/COGNITIVE_LOAD_PROJECTION_LAYER.md :: Core Rules` - cognitive-load projections are non-authoritative and source-preserving.
- `docs/research/COGNITIVE_LOAD_REDUCTION_RESEARCH.md :: WP-E: Source-Preserving Summary Pattern`.
- `docs/CONCEPTS/ARTIFACT_PROJECTION_AND_SOURCE_CONTRACT.md :: Core rule` - artifact/projection/source role must not collapse.
- `docs/CONCEPTS/WORKFLOW_MUTATION_AND_GOVERNANCE_SEMANTICS.md :: Proposal lifecycle`.
- `docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md :: Authority rules`.
- `companion-ui/docs/COMPANION_UI_STATE_MAP.md :: Authority posture per mode`.
- GitHub Issue #1646 - Source Understanding Mode parent.
- GitHub Issue #1647 - P0 vertical slice.

## Constraints

- #1646 is a validation hub, not a pickup issue.
- #1647 remains the only ready first child until its P0 receipt proves the source-to-understanding pattern.
- Later children remain blocked until #1647 delivers and #1646 records the validation decision to unblock them.
- Understanding packets are non-authoritative projections.
- Source claims, source facts, agent interpretation, critique, uncertainty, and recommended action must remain distinct.
- Generated packets must not create canonical notes, durable knowledge, or hidden memory by default.
- Any stabilized-note output is a reviewable proposal until a governed path applies it.
- Selection mode must not overclaim whole-document understanding.
- Integration and Action lenses must not mutate the vault, create tasks, or claim urgency without governed confirmation.

## Implementation Tasks

1. [DELIVER_P0_SOURCE_UNDERSTANDING_PACKET.md](DELIVER_P0_SOURCE_UNDERSTANDING_PACKET.md) -> existing #1647.
2. [CONNECT_STABILIZED_NOTE_PROPOSAL_HANDOFF.md](CONNECT_STABILIZED_NOTE_PROPOSAL_HANDOFF.md) -> #1684, blocked post-P0 child issue.
3. [EXTEND_CONCEPT_AND_CRITIQUE_LENSES.md](EXTEND_CONCEPT_AND_CRITIQUE_LENSES.md) -> #1685, blocked post-P0 child issue.
4. [EXTEND_INTEGRATION_AND_ACTION_LENSES.md](EXTEND_INTEGRATION_AND_ACTION_LENSES.md) -> #1686, blocked post-P1 child issue.
5. [PROMOTE_SOURCE_UNDERSTANDING_OWNER_DOCS.md](PROMOTE_SOURCE_UNDERSTANDING_OWNER_DOCS.md) -> #1687, final blocked closure issue.

## Acceptance Criteria

- [ ] #1647 delivers a P0 packet for one chosen whole-source or selected-passage path. Verify: #1647 PR tests and #1646 child receipt.
- [ ] P0 packet output includes Orientation, Structure, Claims, and Evidence with source anchors or explicit anchor limitations. Verify: #1647 packet-shape/source-anchor tests.
- [ ] P0 output is explicitly non-authoritative and does not write canonical artifacts or hidden memory. Verify: #1647 no-write/no-memory tests.
- [ ] Stabilized-note proposal handoff is reviewable and supports promote/defer/reject/revise posture without auto-promotion. Verify: handoff issue tests and #1646 receipt.
- [ ] Concept and Critique lenses preserve source references and distinguish source claims from agent critique. Verify: Concept/Critique issue tests and #1646 receipt.
- [ ] Integration and Action lenses remain proposal-class and do not mutate the vault or create task authority. Verify: Integration/Action issue tests and #1646 receipt.
- [ ] Owner docs record what is shipped, what remains target-state, and why #1638 is related but separate. Verify: owner-doc promotion issue diff and #1646 closure comment.

## Verification Path

Each child PR must run its focused tests plus:

- `git diff --check`
- `python3 scripts/docs_guard.py` when docs/contracts change
- issue-specific `rg` checks proving the expected source anchors, issue numbers, and no-write language are present

The parent acceptance checklist is updated only from merged PRs and explicit validation receipts, not from speculative implementation claims.

## Validation / Acceptance Path

1. Deliver #1647 and post a P0 receipt to #1646.
2. If the P0 packet shape is accepted, unblock the stabilized-note proposal handoff child.
3. After handoff delivery, unblock Concept/Critique.
4. After Concept/Critique delivery, unblock Integration/Action.
5. After all child receipts are complete, run the owner-doc promotion child and close #1646 with a final validation receipt.

If #1647 proves that the packet shape, source anchor model, or input seam differs materially from this breakdown, rewrite or supersede the blocked child issues before unblocking them.

## Out of Scope

- All eight lenses in one implementation pass.
- Full citation management.
- Generic PDF reader replacement.
- Broad literature-review automation.
- Auto-created canonical concept or literature notes.
- Durable memory promotion from UI-only projections.
- Integration/Action vault mutation outside governed proposal/confirmation paths.

## Suggested Validation

Run:

- `git status --short`
- `git diff --check`
- focused Source Understanding tests named by each child issue
- focused Companion UI/API tests when UI/API surfaces are touched
- `python3 scripts/docs_guard.py` when docs/contracts are updated

## Source Docs

- `docs/SOURCE_UNDERSTANDING_MODE/README.md`
- `docs/HUMAN-FLOWS.md`
- `docs/COGNITIVE_PROSTHESIS_CHARTER.md`
- `docs/CAPABILITY_CONTRACT_MODEL.md`
- `docs/COGNITIVE_LOAD_PROJECTION_LAYER.md`
- `docs/research/COGNITIVE_LOAD_REDUCTION_RESEARCH.md`
- `docs/CONCEPTS/ARTIFACT_PROJECTION_AND_SOURCE_CONTRACT.md`
- `docs/CONCEPTS/WORKFLOW_MUTATION_AND_GOVERNANCE_SEMANTICS.md`
- `docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md`
- `companion-ui/docs/COMPANION_UI_STATE_MAP.md`
