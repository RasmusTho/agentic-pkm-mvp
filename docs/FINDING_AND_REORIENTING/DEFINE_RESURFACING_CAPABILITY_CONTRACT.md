---
name: Define Resurfacing Capability Contract
description: Specify resurfacing in v6 as the reusable capability that brings something back into attention without a user-initiated query, distinct from ranking and retrieval.
task_id: FINDING_AND_REORIENTING-04
source_anchor: docs/plans/V60_ARCHITECTURE_TARGET.md :: Pillar 7
parent_capability: FINDING_AND_REORIENTING
prerequisites: [FINDING_AND_REORIENTING-01]
depends_on: [NAME_THE_THREE_CAPABILITIES.md]
can_parallelize_with: [DEFINE_RETRIEVAL_CAPABILITY_CONTRACT, DEFINE_ORIENTATION_CAPABILITY_CONTRACT]
---

# Define Resurfacing Capability Contract

## Purpose

Let the user come back to work and rediscover what mattered without doing the remembering themselves. The third prosthetic — the one the user is least likely to ask for, and the one the system must do without being asked — is resurfacing. Resurfacing brings something back into view because open-loop pressure, temporal drift, relational change, or renewed context has made it quietly matter again. This task writes the resurfacing contract and pins down the distinction that keeps being lost: resurfacing is not ranking, and resurfacing is not retrieval-with-a-timer.

## What This Task Does

This task produces the resurfacing capability contract as a docs artifact inside `docs/FINDING_AND_REORIENTING/`. It:

- Defines resurfacing as a reusable capability, not an agent, not a cron job, and not a ranking knob.
- States its trigger: a change in relevance that does not come from a user-initiated query or a user-initiated return to work.
- States its relationship to salience: resurfacing consumes derived salience signals (per the salience contract) but does not own them, does not store them, and does not treat its own decisions as durable facts.
- States what resurfacing produces: an explained surfacing decision with provenance for why now and why this.
- Specifies the resurfacing-specific explanation shape, distinct from retrieval's and orientation's.
- Draws the hard boundary that keeps resurfacing from collapsing back into retrieval: resurfacing can fire without a query, and retrieval cannot.
- Draws the hard boundary that keeps resurfacing from being "better ranking": ranking is a mechanism that orders a candidate list; resurfacing is the decision to produce a surfacing event at all.

## Concretely

The contract the document establishes:

- **Trigger:** a change in attentional relevance that the system notices on behalf of the user. The user has not asked, is not resuming work, and has not posed a query. The system notices that something once parked has become relevant again.
- **Consumes (conceptually):** derived salience signals as specified by `docs/CONCEPTS/SALIENCE_AND_ATTENTIONAL_RELEVANCE_CONTRACT.md` — open-loop pressure, temporal drift or staleness, relational change, renewed context, review cadence, and so on. All of these are situational and computed at decision time. None of them are stored on an artifact.
- **Produces:** a surfacing decision — one item (or a small set) accompanied by a "why now" explanation and enough provenance that the user can answer "is this really relevant right now or is the system wrong about me." The output is a surfacing event, not a ranked list of hits.
- **Explanation shape:** resurfacing explains itself as "this became relevant again because…" — relevance-change-anchored, pointing at the specific signal (a loop that reopened, a commitment whose deadline moved, a context that became active again, a related artifact that changed). The sentence is always anchored in a change, not in a query and not in a situational frame.
- **Does not do:** resurfacing does not fire in response to a user query (that is retrieval), does not fire because the user just came back to work (that is orientation), does not store its own decisions as durable fields, and does not collapse into "the top of a ranked list."

Relationship to ranking:

- Ranking is a mechanism. Given a candidate set and some signals, ranking orders them. Resurfacing is the decision that a surfacing event should happen at all. Ranking may be used as a subordinate mechanism inside a resurfacing pipeline, but a resurfacing decision is never reducible to "the top of a ranking."
- A higher-ranked retrieval hit is not a resurfacing event. If the user did not ask, ranking alone did nothing.

Relationship to salience:

- Salience is a first-class concept. It is always derived, never stored. Resurfacing is the capability most tempted to store salience, because it would be easier to pre-compute "surfaceable" than to recompute it at decision time. This contract forbids that shortcut. The temptation is the cautionary tale of Finding 2 in `docs/plans/V60_ARCHITECTURE_TARGET.md`, which is where a zone overlay was read as if it were a stored field and silently returned `None` because nothing ever wrote it.

Relationship to retrieval:

- Retrieval returns things for a query. Resurfacing decides to present something with no query. A resurfacing decision may use retrieval as a subordinate mechanism to fetch the chosen item's payload, but the decision to surface at all is not retrieval's responsibility.

## Why This Matters

Pillar 7 and Delta 7 of `docs/plans/V60_ARCHITECTURE_TARGET.md` say it directly: "resurfacing does not masquerade as retrieval" and "resurfacing is not reduced to ranking or query-answer relevance." Without this contract, resurfacing keeps being implemented as "retrieval but with better ranking over time" and never learns to fire without a query. The system then cannot serve the user's real need — "notice for me what is becoming relevant again, because I won't." This is precisely the use case the user cannot ask for in advance.

If resurfacing is not specified:

- It quietly collapses into retrieval-with-recency-weighting and stops being a distinct capability.
- Salience creeps back toward being stored, because an unspecified resurfacing pipeline cannot tell itself not to.
- The user never gets help with "what has quietly become relevant again," because nobody owns that responsibility.

## Acceptance Criteria

- [ ] The contract defines resurfacing as a reusable capability, not an agent and not a ranking knob.
- [ ] The contract states the trigger: a change in attentional relevance noticed without a user query or a user-initiated return to work.
- [ ] The contract cites `docs/CONCEPTS/SALIENCE_AND_ATTENTIONAL_RELEVANCE_CONTRACT.md` and affirms that resurfacing consumes derived salience signals, does not own them, and does not store them.
- [ ] The contract states that the output is a surfacing decision with a "why now" explanation, not a ranked list.
- [ ] The contract specifies the resurfacing explanation shape as relevance-change-anchored and confirms it differs structurally from the retrieval and orientation explanation shapes.
- [ ] The contract explicitly rejects two collapses: resurfacing-as-better-ranking and resurfacing-as-retrieval-with-a-timer.
- [ ] The contract cites Finding 2 in `docs/plans/V60_ARCHITECTURE_TARGET.md` as the cautionary tale for storing attentional overlays, without attempting to fix Finding 2.
- [ ] The contract does not propose any code change or any durable storage of salience or surfacing decisions.
- [ ] The contract cites Pillar 7, Pillar 7A, and Delta 7 of `docs/plans/V60_ARCHITECTURE_TARGET.md`.

## How to Verify (Pre-Merge)

- Read the three contract files side by side. The resurfacing explanation shape must be relevance-change-anchored and must not reduce to either request-anchored or situation-anchored.
- Write a scenario in which the user is neither querying nor returning from a break, and confirm the contract describes a sensible resurfacing decision for that scenario.
- Grep for "rank" and "top N" and confirm those words are not used as the primary definition of what resurfacing produces.
- Confirm that the contract does not propose any stored field or any code path.
- A reviewer other than the author signs off on all four checks.

## Out of Scope

- Modifying `app/retrieval/*`, `app/agents/ask/*`, or any other code file.
- Writing a ranking algorithm, a surfacing queue, or any signal-weighting rule.
- Deciding where resurfacing decisions are displayed. That is `INTERACTION_SURFACES_AND_AUTHORITY`.
- Defining retrieval or orientation behavior.
- Fixing Finding 2.
- Specifying exact salience signal weights or thresholds.

## Related Docs

- `docs/plans/V60_ARCHITECTURE_TARGET.md` :: Pillar 7, Pillar 7A, Delta 7, Finding 2 (cite only)
- `docs/CONCEPTS/SALIENCE_AND_ATTENTIONAL_RELEVANCE_CONTRACT.md`
- `docs/CONCEPTS/USER_NEEDS_MODEL.md`
- `docs/HUMAN-FLOWS.md`
- Sibling task files in this directory.

## Related GitHub Issues

When this spec is promoted into an implementation issue, reference: "Implements FINDING_AND_REORIENTING/DEFINE_RESURFACING_CAPABILITY_CONTRACT." Mark the issue docs-only. Any later code-side implementation of resurfacing is a separate issue.
