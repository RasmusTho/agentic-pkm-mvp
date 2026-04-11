---
name: Define Retrieval Capability Contract
description: Specify retrieval in v6 as a reusable find-and-return capability with precise input, output, and explicit non-responsibilities.
task_id: FINDING_AND_REORIENTING-02
source_anchor: docs/plans/V60_ARCHITECTURE_TARGET.md :: Pillar 6
parent_capability: FINDING_AND_REORIENTING
prerequisites: [FINDING_AND_REORIENTING-01]
depends_on: [NAME_THE_THREE_CAPABILITIES.md]
can_parallelize_with: [DEFINE_ORIENTATION_CAPABILITY_CONTRACT, DEFINE_RESURFACING_CAPABILITY_CONTRACT]
---

# Define Retrieval Capability Contract

## Purpose

Let the user come back to work and rediscover what mattered without doing the remembering themselves. When the user already has a question in their head, retrieval is the prosthetic that returns the right material with legible provenance. This task writes the retrieval contract as a reusable capability — find-and-return only — and draws the hard line where retrieval stops and orientation or resurfacing begins.

## What This Task Does

This task produces the retrieval capability contract as a docs artifact inside `docs/FINDING_AND_REORIENTING/`. It:

- Defines retrieval as a reusable capability, not an agent, consistent with Pillar 7A and the Fixed Decision "Retrieval becomes a capability, not an agent."
- States what retrieval consumes (the shape of a retrieval request at the contract level, not the API level).
- States what retrieval produces (a bounded, explainable result set with provenance).
- States what retrieval never does: re-orient the human, decide to surface without a query, compute durable salience, or act as the cognitive center.
- Specifies the explanation shape for "why was this returned" that is distinct from orientation's and resurfacing's explanation shapes.
- Aligns with Pillar 6: retrieval may combine scope, relations, and provenance rather than leaning on one flat boundary.

## Concretely

The contract the document establishes, at the level of user-visible behavior:

- **Trigger:** a retrieval request exists. There is an intent to find something. A query, a structured filter, or an operation boundary is present. Retrieval does not fire without one.
- **Consumes (conceptually):** a request carrying some combination of scope, relations, provenance constraints, and a user-facing question or operation. This aligns with Pillar 6, which asks retrieval to combine scope/relations/provenance instead of overloading one boundary.
- **Produces:** a bounded result set of artifacts (or references to artifacts), each carrying enough provenance that the user can answer "where did this come from and why did it match." No hidden re-ranking that cannot be explained. No implicit promotion of any result into "this is what you should be paying attention to."
- **Explanation shape:** retrieval explains itself as "this matched your request because…" with a pointer to the scope, relation, or provenance signal that caused the match. The sentence is always request-anchored.
- **Does not do:** retrieval does not take responsibility for rebuilding situational context, does not decide what the user should care about next, does not fire without a query, and does not write a durable salience field. A high-scoring retrieval result is not the same thing as a surfacing decision.

Relationship to the v5.x runtime:

- The v5.x retrieval runtime in `app/retrieval/*` is the current implementation of this capability. This task does not modify it, redesign its APIs, or refactor it.
- Finding 2 in `docs/plans/V60_ARCHITECTURE_TARGET.md` (zone read from artifact payload as if stored) is cited in this contract as the clearest example of why retrieval must not double as resurfacing: the runtime tried to surface things by reading an overlay it never wrote, because retrieval was carrying surfacing responsibility it should not have had.

## Why This Matters

Without a clean retrieval contract, retrieval keeps drifting into orientation and resurfacing work. It gets blamed for not being "smart enough" to lead a lost human home, and it gets extended with ranking tricks in a failing attempt to bring things back into view without a query. Both are category errors. Pillar 6 and Delta 7 of `docs/plans/V60_ARCHITECTURE_TARGET.md` call this out: retrieval remains the find/return capability, and orientation and resurfacing become distinct capabilities with their own contracts. This task is how retrieval learns to say no to work that does not belong to it.

If retrieval stays overloaded:

- New retrieval features keep trying to solve orientation indirectly and keep failing.
- Salience creeps back toward becoming a stored field because retrieval needs it at query time.
- The architectural center of the system silently remains ASK-shaped, undermining the v6 decision to decenter ASK.

## Acceptance Criteria

- [ ] The contract defines retrieval as a reusable capability with no agent identity.
- [ ] The contract states the trigger condition: a retrieval request exists.
- [ ] The contract states what retrieval consumes in user-visible terms, drawing from scope, relations, and provenance per Pillar 6.
- [ ] The contract states what retrieval produces: a bounded, explainable result set with provenance.
- [ ] The contract specifies the retrieval-specific explanation shape: request-anchored ("this matched your request because…").
- [ ] The contract lists what retrieval does not do: rebuild situational context, fire without a query, decide surfacing, write durable salience.
- [ ] The contract explicitly cites Finding 2 as the cautionary tale for overloading retrieval with surfacing responsibility, without attempting to fix Finding 2.
- [ ] The contract does not propose any modification to `app/retrieval/*` or any other code file.
- [ ] A reviewer can confirm the retrieval explanation shape differs structurally from the orientation and resurfacing explanation shapes in the sibling contracts.

## How to Verify (Pre-Merge)

Verification is docs-only.

- Read the contract alongside `DEFINE_ORIENTATION_CAPABILITY_CONTRACT.md` and `DEFINE_RESURFACING_CAPABILITY_CONTRACT.md` and confirm the three explanation shapes are structurally different (request-anchored vs. situation-anchored vs. relevance-change-anchored).
- Grep the contract for any language that implies retrieval fires without a query ("we decided to surface," "salience-driven," "proactive"); any such language must be removed.
- Confirm the contract cites Pillar 6, Pillar 7A, Delta 6, Delta 7, and the Fixed Decision in `docs/plans/V60_CAPABILITY_AND_AGENT_EVOLUTION.md`.
- Confirm the contract does not propose touching any code path.
- A reviewer other than the author signs off on all four checks.

## Out of Scope

- Modifying `app/retrieval/*` or any runtime code.
- Redesigning the retrieval API or request shape at the HTTP or function-signature level.
- Deciding which interaction surface calls retrieval. That is `INTERACTION_SURFACES_AND_AUTHORITY`.
- Specifying signal lists for salience. That is `DOCUMENT_SALIENCE_AS_DERIVED.md`.
- Fixing Finding 2. Cite only.
- Defining orientation or resurfacing behavior.

## Related Docs

- `docs/plans/V60_ARCHITECTURE_TARGET.md` :: Pillar 6, Pillar 7, Pillar 7A, Delta 6, Delta 7
- `docs/plans/V60_CAPABILITY_AND_AGENT_EVOLUTION.md` :: Fixed Decisions "Retrieval becomes a capability, not an agent"
- `docs/RETRIEVAL.md`
- `docs/ARCHITECTURE.md` :: retrieval-related sections
- Sibling task file `NAME_THE_THREE_CAPABILITIES.md`

## Related GitHub Issues

When this spec is promoted into an implementation issue, reference: "Implements FINDING_AND_REORIENTING/DEFINE_RETRIEVAL_CAPABILITY_CONTRACT." Use the acceptance criteria above as the issue contract and explicitly label the issue as docs-only. Any subsequent code-side work that consumes this contract must be a separate issue with its own acceptance.
