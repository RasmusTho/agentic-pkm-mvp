---
name: Define Orientation Capability Contract
description: Specify orientation in v6 as the reusable capability that helps a human regain situational understanding after interruption, distinct from retrieval and resurfacing.
task_id: FINDING_AND_REORIENTING-03
source_anchor: docs/plans/V60_ARCHITECTURE_TARGET.md :: Pillar 7
parent_capability: FINDING_AND_REORIENTING
prerequisites: [FINDING_AND_REORIENTING-01]
depends_on: [NAME_THE_THREE_CAPABILITIES.md]
can_parallelize_with: [DEFINE_RETRIEVAL_CAPABILITY_CONTRACT, DEFINE_RESURFACING_CAPABILITY_CONTRACT]
---

# Define Orientation Capability Contract

## Purpose

Let the user come back to work and rediscover what mattered without doing the remembering themselves. When the user is lost — after interruption, a context switch, or time passing — there is not yet a question in their head. There is a missing situational frame. Orientation is the cognitive prosthetic that rebuilds that frame and leads the human back to where they were and what mattered when they left. This task writes the orientation contract.

Orientation is repo working language closest to task resumption, context reconstruction, and situation-awareness recovery; it is not generic Q&A and not merely retrieving artifacts.

## What This Task Does

This task produces the orientation capability contract as a docs artifact inside `docs/FINDING_AND_REORIENTING/`. It:

- Defines orientation as a reusable capability, not an agent and not a UI affordance.
- Names its trigger: the user has returned to work and cannot yet formulate a query.
- Specifies what orientation draws on (recent activity, open commitments, last situational state, recent focus, unresolved loops) and treats each as a signal, not as a stored truth.
- Specifies what orientation produces: a situational frame that answers "where was I, what mattered, what is still open, what changed while I was away," not a document list.
- Specifies the orientation-specific explanation shape that distinguishes it from retrieval's request-anchored explanation and resurfacing's relevance-change-anchored explanation.
- States the hard boundaries: orientation does not wait for a query, does not return a ranked list of artifacts as its primary output, and does not compute or store salience.

## Concretely

The contract the document establishes:

- **Trigger:** the user is resuming work and has not yet posed a question. A query is absent by definition. The user's felt need is "lead me home," not "find me X."
- **Consumes (conceptually):** signals that describe the situational state the user left behind — what they were working on most recently, which commitments are still open, what context was active, what has changed in the meantime. These are signals, computed at request time. None of them is stored as a durable "last situation" field on any artifact.
- **Produces:** a situational frame. At the contract level, a frame is a short set of statements the user can read to rebuild where they were and what mattered. It may reference artifacts, but the primary output is the frame, not the artifact list. The frame should describe:
  - where the user was (the context and focus at the last leave-point),
  - what mattered (the open commitments or active threads at that point),
  - what is still open (unresolved loops that had not closed before the leave),
  - and what has changed (anything relevant that moved while the user was away).
- **Explanation shape:** orientation explains itself as "when you left, you were here; these threads were active; these remain open; this changed while you were away." Situation-anchored, not request-anchored and not surfacing-decision-anchored.
- **Does not do:** orientation does not require or wait for a query, does not reduce its output to a ranked artifact list, does not silently promote items into attention for the user (that is resurfacing), and does not write any durable situational field anywhere.

Boundary with retrieval:

- Retrieval answers "find me X." Orientation answers "where am I." A returned document is not a regained situational frame.
- Orientation may call retrieval as a subordinate mechanism to pull artifacts it wants to reference inside the frame. That does not make orientation a kind of retrieval; it makes retrieval a downstream capability orientation composes with.

Boundary with resurfacing:

- Resurfacing brings something back into view without a user-initiated moment. Orientation is triggered by a user-initiated return to work. The user is present; they just do not have a query yet.
- Orientation is about the user's state, not about the changing relevance of individual artifacts. A situational frame is not a salience event.

## Why This Matters

Pillar 7 of `docs/plans/V60_ARCHITECTURE_TARGET.md` is explicit: "findability does not masquerade as orientation." Delta 7 restates this as a transition from retrieval-as-orientation to explicit retrieval/orientation/resurfacing separation. Without this contract, orientation keeps getting built as "a better ASK response" and keeps failing, because ASK assumes a question already exists — the one thing the orientation user precisely does not have. This task is how orientation becomes its own capability instead of an unnamed expectation that ASK will "also do orientation somehow."

If orientation is not specified:

- The user who comes back after a week away gets a search box and has to build their own situational frame.
- The returning-to-work failure mode — "I don't even know where to start" — becomes a product gap with no owner.
- Retrieval keeps being extended with heuristics trying to solve an orientation problem it cannot solve.

## Acceptance Criteria

- [ ] The contract defines orientation as a reusable capability, not an agent.
- [ ] The contract states the trigger: the user is resuming work and does not yet have a query.
- [ ] The contract lists the signals orientation draws on as situational and derived, not as stored fields.
- [ ] The contract states that the primary output is a situational frame, not a ranked artifact list.
- [ ] The situational frame is specified as answering at minimum four things: where the user was, what mattered, what is still open, what has changed.
- [ ] The contract specifies the orientation explanation shape ("when you left, you were here; these threads were active; these remain open; this changed while you were away") and confirms it differs structurally from the retrieval and resurfacing explanation shapes.
- [ ] The contract states that orientation may compose retrieval as a subordinate mechanism without inheriting retrieval's contract.
- [ ] The contract explicitly states that orientation does not write any durable situational field.
- [ ] The contract cites Pillar 7, Pillar 7A, and Delta 7 of `docs/plans/V60_ARCHITECTURE_TARGET.md`.
- [ ] The contract does not propose any code change.

## How to Verify (Pre-Merge)

- Read the three contract files side by side. The orientation explanation shape must be situation-anchored and must not reduce to request-anchored.
- Grep the orientation contract for "query" and "search" — these words must not appear in the definition of what orientation consumes.
- Write a one-paragraph scenario ("the user comes back after a week away, opens the system, has not yet thought of a question") and confirm that the contract describes an output the user could actually use to orient themselves in that scenario.
- Confirm that the contract does not claim authority over any interaction surface; the question of where orientation lives (Panel, Chat, elsewhere) is deferred to `INTERACTION_SURFACES_AND_AUTHORITY`.
- A reviewer other than the author signs off on all four checks.

## Out of Scope

- Choosing which interaction surface renders orientation output. That is `INTERACTION_SURFACES_AND_AUTHORITY`.
- Specifying exact signals, weights, or thresholds for building the situational frame. Signal lists may reference `DOCUMENT_SALIENCE_AS_DERIVED.md` at a conceptual level only.
- Any modification to `app/retrieval/*`, `app/agents/ask/*`, or any other code.
- Defining retrieval or resurfacing behavior.
- Fixing Finding 2.
- Designing a UI for situational frames.

## Related Docs

- `docs/plans/V60_ARCHITECTURE_TARGET.md` :: Pillar 7, Pillar 7A, Delta 7
- `docs/plans/V60_CAPABILITY_AND_AGENT_EVOLUTION.md` :: Fixed Decisions
- `docs/CONCEPTS/USER_NEEDS_MODEL.md` :: §Recovering orientation
- `docs/HUMAN-FLOWS.md` :: Retrieve and re-orient
- `docs/CONCEPTS/SALIENCE_AND_ATTENTIONAL_RELEVANCE_CONTRACT.md`
- Sibling task files in this directory.

## Related GitHub Issues

When this spec is promoted into an implementation issue, reference: "Implements FINDING_AND_REORIENTING/DEFINE_ORIENTATION_CAPABILITY_CONTRACT." Mark the issue docs-only. Any later code-side implementation of orientation is a separate issue with its own contract.
