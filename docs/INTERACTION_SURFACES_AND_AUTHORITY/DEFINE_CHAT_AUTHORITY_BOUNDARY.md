---
name: Define Chat Authority Boundary
description: Frame Chat as a canvas-like thinking surface with governed mutation rights decided by the reconcile task, and keep it distinct from ASK-style question-answering
task_id: INTERACTION-03
source_anchor: docs/plans/V60_CAPABILITY_AND_AGENT_EVOLUTION.md :: Interaction Model :: Chat
parent_capability: Interaction surfaces and authority boundaries
prerequisites: [INTERACTION-01]
depends_on: [NAME_THE_THREE_INTERACTION_SURFACES.md]
can_parallelize_with: [DEFINE_PANEL_AUTHORITY_BOUNDARY, DEFINE_AUTOMATION_SURFACE_AUTHORITY, STATE_EXECUTION_AUTHORITY_REMAINS_GATED]
---

State: Specification draft. Docs-only. The authority boundary for Chat is canvas-shaped; the final mutation question is resolved by `RECONCILE_CHAT_MUTATION_AUTHORITY.md` as Candidate A, so future Chat-originated mutations must use governed execution.

# Define Chat Authority Boundary

## Purpose

Describe Chat as a canvas-like thinking surface whose cognitive posture is externalize-and-manipulate, not receive-query / return-answer. State the parts of Chat's authority boundary that are stable and point to the reconcile task for the recorded mutation decision.

This task originally shaped the question so the reconcile task could close it. The reconcile task has now closed it as Candidate A: Chat may carry governed mutation rights, while the Deep Agent introduction phase remains read-only.

## What This Task Does

Produces a docs section that states:

1. **What Chat is, in one sentence (canvas framing).**
   Proposed authority statement (to be finalized during review): "Chat is the exploration-oriented interaction surface where the user externalizes and manipulates thought across the context the system can already see, and where richer cognition may be introduced safely because the surface is structured as a canvas rather than as a command line."

2. **What Chat is not.**
   - Chat is not the ASK loop. ASK was receive-query / return-answer; canvas is externalize-thought / manipulate-in-place / optionally-commit. The difference is structural, not stylistic. A canvas is a place the user thinks on; an ASK exchange is a turn-based Q&A. This distinction must be preserved even if Chat later gains governed mutation rights.
   - Chat is not a second Panel. Panel is command-oriented with in-note receipts. Chat, if it eventually mutates, will not inherit Panel's in-note receipt locality automatically; the reconcile task names where Chat receipts would live.
   - Chat is not a generic conversation surface. The "multiple governed mutation paths" clause in `docs/DESIGN_PRINCIPLES.md` permits Chat to carry authority, but only if its authority is as explicit and as governed as Panel's.

3. **What Chat's cognitive posture is today, regardless of the mutation decision.**
   - Exploration-oriented: reason across vault context, orient the user in their own thinking, decompose a fuzzy problem.
   - Canvas-shaped: content can be drafted, rearranged, annotated, and revised in place without each change being a mutation of durable vault state.
   - A safe introduction surface for richer cognition (Deep Agents, multi-step reasoning) because the surface is introspective by default.

4. **The read-only-vs-canvas tension, resolved explicitly.**
   - `docs/plans/V60_CAPABILITY_AND_AGENT_EVOLUTION.md` §Fixed Decisions now narrows the read-only rule to the Deep Agent entry slice.
   - `docs/DESIGN_PRINCIPLES.md` §Explicit Mutation Authority already permits multiple governed mutation paths.
   - The user-intent framing treats Chat as canvas, which is compatible with governed mutation but incompatible with permanent read-only identity.
   - `RECONCILE_CHAT_MUTATION_AUTHORITY.md` resolves this as Candidate A: the read-only rule applies to the Deep Agent introduction phase, not to Chat's identity.

5. **What is already decided about Chat after the reconcile outcome.**
   - Chat never bypasses the gated-execution invariant (see `STATE_EXECUTION_AUTHORITY_REMAINS_GATED.md`). LLM reasoning alone never triggers mutation, under either resolution of the reconcile task.
   - Chat's introduction phase for Deep Agents is read-only, even if Chat's long-term identity is not. "Start read-only" applies to the Deep Agent introduction phase, not to Chat's identity.
   - Chat must not reintroduce ASK semantics. A reconciliation that restored the ASK loop would violate the product intent this capability is protecting.
   - Chat-originated mutation receipts live in the existing gated-execution pipeline locality. The concrete receipt shape remains deferred to a later canvas-commit capability lane.

6. **What this task does not say.**
   - The concrete runtime shape for canvas-Chat commits to the vault.
   - Which runtime hosts Chat.
   - Whether Chat lives inside Obsidian or outside it.
   - Which Deep Agent implementation is introduced in Chat first.
   - The concrete receipt field shape Chat uses if it mutates.

## Concretely

The deliverable is a section in this file titled `## Chat Authority Boundary` that captures the six points above and points to `RECONCILE_CHAT_MUTATION_AUTHORITY.md` for the recorded Candidate A decision.

A reviewer who reads this section should come away with: (a) Chat is canvas, not Q&A; (b) Chat's mutation boundary is a recorded governed-execution decision; (c) the gated-execution invariant holds for Chat-originated mutations.

## Why This Matters

Chat is the most under-described interaction surface in v6.0. The former ambiguity between "Chat is read-only" (older working-plan language) and "Chat is canvas" (product-intent language) has already been resolved by `RECONCILE_CHAT_MUTATION_AUTHORITY.md`; this task keeps the Chat boundary aligned to that recorded decision.

## Acceptance Criteria

- [ ] The task file states a one-sentence Chat authority statement framed as canvas, not ASK.
- [ ] The task file explicitly rejects ASK-style receive-query / return-answer semantics as a definition of Chat.
- [ ] The task file explicitly acknowledges the read-only-vs-canvas tension and points to the recorded Candidate A resolution.
- [ ] The task file defers runtime implementation shape to later capability work while treating the mutation-boundary decision as resolved by `RECONCILE_CHAT_MUTATION_AUTHORITY.md`.
- [ ] The task file restates the gated-execution invariant and names `STATE_EXECUTION_AUTHORITY_REMAINS_GATED.md` as its source.
- [ ] The task file names at least four things that are already decided about Chat even without the reconcile outcome.
- [ ] The task file does not describe a Chat implementation or pick a Chat runtime.
- [ ] The vocabulary matches `NAME_THE_THREE_INTERACTION_SURFACES.md`.

## How to Verify (Pre-Merge)

Docs review:

- A reviewer can quote from the file a sentence that says "Chat is canvas, not ASK."
- A reviewer can quote from the file a sentence that says the mutation-boundary decision is recorded in the reconcile task.
- A grep against this file for "Q&A" or "question and answer" returns only rejection language, not definitional language.
- The file contains no implementation details, no runtime choices, no architecture names (beyond citing Deep Agents as the planned cognition passenger).

## Out of Scope

- Implementing Chat mutation.
- Choosing a Chat runtime or front-end.
- Naming Chat's receipt surface.
- Introducing a Deep Agent.
- Designing the canvas interaction model.
- Describing how canvas-Chat integrates with existing Panel flows.

## Related Docs

- `docs/plans/V60_CAPABILITY_AND_AGENT_EVOLUTION.md` §Interaction Model §Chat
- `docs/plans/V60_CAPABILITY_AND_AGENT_EVOLUTION.md` §Fixed Decisions
- `docs/DESIGN_PRINCIPLES.md` §Explicit Mutation Authority
- `docs/DESIGN_PRINCIPLES.md` §Governance Before Autonomy
- `docs/CONCEPTS/USER_NEEDS_MODEL.md` :: externalize thought
- Sibling: `NAME_THE_THREE_INTERACTION_SURFACES.md`
- Sibling: `RECONCILE_CHAT_MUTATION_AUTHORITY.md`
- Sibling: `STATE_EXECUTION_AUTHORITY_REMAINS_GATED.md`

## Related GitHub Issues

If later filed, the issue should reference "Implements INTERACTION_SURFACES_AND_AUTHORITY/DEFINE_CHAT_AUTHORITY_BOUNDARY" and must preserve the recorded reconcile decision.

---

**Status:** Specification draft. The Chat mutation decision is resolved by `RECONCILE_CHAT_MUTATION_AUTHORITY.md`; runtime implementation remains out of scope here.
