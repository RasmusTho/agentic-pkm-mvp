---
name: Name the Three Capabilities
description: Establish retrieval, orientation, and resurfacing as three separately named cognitive-prosthetic capabilities with precise, mutually exclusive boundaries.
task_id: FINDING_AND_REORIENTING-01
source_anchor: docs/plans/V60_ARCHITECTURE_TARGET.md :: Pillar 7
parent_capability: FINDING_AND_REORIENTING
prerequisites: []
depends_on: []
can_parallelize_with: [DOCUMENT_SALIENCE_AS_DERIVED, DEPRECATE_ASK_AS_ARCHITECTURAL_CENTER]
---

# Name the Three Capabilities

## Purpose

Let the user come back to work and rediscover what mattered without doing the remembering themselves. To do that, the docs must first name three cognitive prosthetics that are currently conflated: retrieval (find the right thing), orientation (regain situational understanding after interruption), and resurfacing (notice what has quietly become relevant again). This task is the naming spec. It is the boundary on which every other task in this directory rests. If this task is wrong, the other five are wrong.

## What This Task Does

This task produces the canonical naming document for the three sub-capabilities inside `docs/FINDING_AND_REORIENTING/` (this task file itself, promoted in review). It:

- States the three capability names: retrieval, orientation, resurfacing.
- Defines each one in a single sentence written in the user's voice ("I need to…").
- States, for each capability, the one thing that capability uniquely does for the user that the other two cannot.
- Draws the boundary between them: retrieval is find-and-return, orientation is lead-home-after-interruption, resurfacing is bring-back-without-a-query.
- Explicitly forbids reducing any of the three to the other two.
- Establishes the convention used by the rest of the directory: retrieval, orientation, and resurfacing are capabilities, not agents, not endpoints, and not UI affordances.

## Concretely

The canonical three-way naming the rest of this directory cites:

- **Retrieval** answers the user verb "retrieve the right thing." The user has a concrete question, lookup, or operation in mind. A query or retrieval request exists. The system's job is to return the correct material with legible provenance.
- **Orientation** answers the user verb "re-orient after interruption." Orientation is situational reorientation after interruption: the user cannot yet formulate a query and needs the system to reconstruct where they were, what mattered, what remains open, and what changed.
- **Resurfacing** answers the user verb "notice what is becoming relevant again." The user has no active query and is not asking to be led home. The system's job is to bring something back into view because open-loop pressure, temporal drift, relational change, or renewed context has made it quietly matter again.

What each uniquely does that the other two cannot:

- Only retrieval can fulfill an existing query with a bounded, explainable result set.
- Only orientation can reconstruct a situational frame when the user cannot yet articulate what they need.
- Only resurfacing can decide to bring something forward with no user input at all.

The forbidden collapses, stated as rules the other tasks may cite:

- Retrieval must not be used as the whole answer to orientation. A returned document is not a regained situational frame.
- Resurfacing must not be reduced to ranking inside retrieval. A high-ranked retrieval hit is not the same as an unprompted surfacing decision.
- Orientation must not be reduced to Q&A. A question-answer loop assumes a question already exists; orientation is precisely the state where one does not.

## Why This Matters

If the three are not named separately, ASK-style question answering quietly re-becomes the architectural center for all three needs, and the system loses the ability to help a returning human who does not yet have a question. Pillar 7 of `docs/plans/V60_ARCHITECTURE_TARGET.md` calls this out directly: "findability does not masquerade as orientation, resurfacing does not masquerade as retrieval." This task is how that non-masquerade is enforced at the docs level.

Without this naming:

- Retrieval keeps absorbing orientation work and gets blamed for not being smart enough.
- Resurfacing keeps getting built as "better ranking" and never fires without a query.
- Orientation never becomes anything at all, because it has no name.

## Acceptance Criteria

- [ ] The document names exactly three capabilities: retrieval, orientation, resurfacing.
- [ ] Each capability is defined in a single user-voice sentence ("I need to…").
- [ ] For each capability, one sentence states the unique function the other two cannot serve.
- [ ] The document explicitly rejects three collapses: retrieval-as-orientation, resurfacing-as-ranking, orientation-as-Q&A.
- [ ] The document states the convention: these are capabilities, not agents, not endpoints, not UI affordances.
- [ ] A reviewer can read this document and, given a scenario ("I came back after a week away, I do not yet have a question"), correctly pick out the primary capability (orientation) and the likely secondary capability (resurfacing).
- [ ] The document cites Pillar 7 and Pillar 7A of `docs/plans/V60_ARCHITECTURE_TARGET.md` and the "Retrieval becomes a capability, not an agent" fixed decision in `docs/plans/V60_CAPABILITY_AND_AGENT_EVOLUTION.md`.
- [ ] The document does not propose any code change, schema change, or runtime behavior.

## How to Verify (Pre-Merge)

Verification is entirely docs-review. Pre-merge steps:

- Read the three definitions aloud. Each must be parseable as a user verb, not as a mechanism.
- Attempt the collapse test: try to rewrite any one capability as a special case of another. If any rewrite succeeds without losing user-level meaning, the definitions are not yet tight enough and the PR is not ready.
- Attempt the scenario test with at least two concrete reorientation scenarios (e.g., "returning after a week" and "returning mid-afternoon after a meeting") and confirm the reader can name which capability applies.
- Grep the document for "query" and "search" and confirm those words do not appear in the orientation or resurfacing definitions.

Pre-merge verification is complete when a reviewer other than the author signs off on all four checks.

## Out of Scope

- Defining the internal contracts of retrieval, orientation, or resurfacing. Those belong to `DEFINE_RETRIEVAL_CAPABILITY_CONTRACT.md`, `DEFINE_ORIENTATION_CAPABILITY_CONTRACT.md`, and `DEFINE_RESURFACING_CAPABILITY_CONTRACT.md`.
- Deciding where these capabilities are consumed from (Panel, Chat, API). That is `INTERACTION_SURFACES_AND_AUTHORITY`.
- Deciding what signals any of the three may use. Salience signals are spec'd in `DOCUMENT_SALIENCE_AS_DERIVED.md`.
- Modifying any code, test, schema, or ingest rule.
- Creating GitHub issues.

## Related Docs

- `docs/plans/V60_ARCHITECTURE_TARGET.md` :: Pillar 7, Pillar 7A, Delta 7
- `docs/plans/V60_CAPABILITY_AND_AGENT_EVOLUTION.md` :: Fixed Decisions
- `docs/CONCEPTS/USER_NEEDS_MODEL.md` :: §Recovering orientation
- `docs/HUMAN-FLOWS.md` :: Retrieve and re-orient
- `docs/CONCEPTS/SALIENCE_AND_ATTENTIONAL_RELEVANCE_CONTRACT.md`
- Sibling task files in this directory.

## Related GitHub Issues

When this spec is promoted into an implementation issue, reference: "Implements FINDING_AND_REORIENTING/NAME_THE_THREE_CAPABILITIES." Use the acceptance criteria above as the issue contract. Note in the issue body that this is a docs-only task and the PR should not touch any file outside `docs/FINDING_AND_REORIENTING/`.
