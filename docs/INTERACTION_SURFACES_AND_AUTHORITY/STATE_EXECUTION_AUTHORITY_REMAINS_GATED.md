---
name: State Execution Authority Remains Gated
description: Explicit invariant that no interaction surface mutates durable state without passing through policy, validation, and the event pipeline, and that LLM reasoning alone never triggers execution
task_id: INTERACTION-06
source_anchor: docs/DESIGN_PRINCIPLES.md :: Explicit Mutation Authority
parent_capability: Interaction surfaces and authority boundaries
prerequisites: [INTERACTION-01]
depends_on: [NAME_THE_THREE_INTERACTION_SURFACES.md]
can_parallelize_with: [DEFINE_PANEL_AUTHORITY_BOUNDARY, DEFINE_CHAT_AUTHORITY_BOUNDARY, DEFINE_AUTOMATION_SURFACE_AUTHORITY]
---

State: Specification draft. Docs-only. States an invariant that must hold across every interaction surface regardless of how the Chat mutation decision is resolved.

# State Execution Authority Remains Gated

## Purpose

Put the gated-execution invariant into one file that every other task can point to. The invariant is not new — it is already implicit in `docs/DESIGN_PRINCIPLES.md` §Explicit Mutation Authority and in the V60 working plan's "execution remains gated" fixed decision. This task makes it explicit, names it, and makes it quotable.

The invariant is the floor for every surface. Panel is above the floor. Chat is above the floor under any resolution of the reconcile task. Automation is above the floor. Any future interaction surface must also sit above the floor.

## What This Task Does

Produces a docs section that states the invariant and its consequences:

1. **The invariant, one sentence.**
   "No interaction surface — including Panel, Chat (under any resolution of the Chat mutation question), Automation, and any future surface — mutates durable state except through the existing governed path: policy, validation, event pipeline, and the deterministic note writer or equivalent state-writer."

2. **Corollary: LLM reasoning alone never triggers execution.**
   Cognition and execution are separated. A model's decision to act is never the sole cause of an action. A model can propose an action, surface an intent, or draft a mutation; something else — a human action, a policy-approved watcher event, a validated intent contract — must be the thing that actually moves state.

3. **What "durable state" means here.**
   - Vault notes and their frontmatter.
   - Graph or store projections that the user relies on as truth.
   - Receipts, event history, and governance-visible records.
   - Scheduled or watcher-declared future behavior.
   Transient canvas state (for example, whatever Chat-as-canvas manipulates in-place before any commit) is not durable state by this definition. Canvas state becomes durable state at the moment a commit-through-governance step runs, and that step is subject to the invariant.

4. **Why the invariant is stated at the capability level, not per surface.**
   Each surface describes its own authority upwards from this floor. If the invariant lived only inside the Panel task, the Chat task would feel free to ignore it. Stating it at the capability level makes the floor identical across surfaces.

5. **How the invariant interacts with the Chat mutation decision.**
   The invariant holds under both candidate resolutions of `RECONCILE_CHAT_MUTATION_AUTHORITY.md`. If Chat ends up mutation-capable, its mutations flow through the same gated path Panel mutations flow through (or a new parallel gated path that satisfies the same policy + validation + audit properties). If Chat stays read-only, the invariant still holds trivially because Chat never mutates.

6. **How the invariant interacts with Automation.**
   Watcher reactions and scheduled jobs are not exceptions. They are governed upstream by the policy approving them and downstream by the same pipeline Panel uses. A watcher that called an LLM to decide what to do would be subject to the invariant: the LLM can propose, the pipeline acts.

7. **What the invariant does not claim.**
   - It does not claim that the governance pipeline is finished or that every policy surface has landed. It claims the shape: no surface bypasses it.
   - It does not claim that the existing event names or writer paths are final.
   - It does not claim that all current runtime code already matches the invariant. It states the invariant as the contract; delta-from-contract work is tracked separately in implementation-track docs, not here.

## Concretely

The deliverable is a section in this file titled `## The Invariant` that captures the seven points above, ending with a quotable single-sentence form of the invariant that the other task files can cite by copy-paste.

## Why This Matters

Every high-risk question in the v6.0 interaction model reduces, under pressure, to "does the LLM decide?" The gated-execution invariant says no, and says it in one place, so the reconcile task, the Chat authority task, and the Automation task can all point to it without re-arguing it.

Without this invariant stated at the capability level, the reconcile task would be forced to carry the "no autonomous mutation" argument inside its candidate-resolution body, and that would make the reconcile task look like it is pre-empting the decision. Splitting the invariant out here keeps the reconcile task neutral.

## Acceptance Criteria

- [ ] The task file states the invariant in one quotable sentence.
- [ ] The task file explicitly says LLM reasoning alone never triggers execution.
- [ ] The task file defines "durable state" and explicitly notes that transient canvas state becomes durable only at the commit-through-governance step.
- [ ] The task file shows the invariant holds under both candidate resolutions of `RECONCILE_CHAT_MUTATION_AUTHORITY.md`.
- [ ] The task file shows the invariant covers Automation as well as Panel and Chat.
- [ ] The task file does not claim current runtime code is fully aligned; it states the invariant as the contract.
- [ ] The task file cites `docs/DESIGN_PRINCIPLES.md` §Explicit Mutation Authority and `docs/plans/V60_CAPABILITY_AND_AGENT_EVOLUTION.md` Fixed Decisions as source anchors.
- [ ] The vocabulary matches `NAME_THE_THREE_INTERACTION_SURFACES.md`.

## How to Verify (Pre-Merge)

Docs review:

- A reviewer can copy-paste the one-sentence invariant from this file and drop it into another task file unchanged.
- A reviewer can read the "durable state" definition and place "canvas-in-progress" on the correct side of it without ambiguity.
- A reviewer can state, from this file alone, why the invariant does not pre-empt the reconcile decision.
- The file contains no implementation or schema changes.

## Out of Scope

- Auditing current runtime code against the invariant.
- Proposing new policy engines, validation layers, or event pipelines.
- Redesigning the note writer.
- Picking a resolution to the Chat mutation question.
- Renaming any event family.
- Listing every specific mutation path in the current runtime.

## Related Docs

- `docs/DESIGN_PRINCIPLES.md` §Explicit Mutation Authority
- `docs/DESIGN_PRINCIPLES.md` §Governance Before Autonomy
- `docs/plans/V60_CAPABILITY_AND_AGENT_EVOLUTION.md` §Fixed Decisions :: Execution remains gated
- `docs/plans/V60_ARCHITECTURE_TARGET.md` §Pillar 10, §Pillar 10A
- Sibling: `NAME_THE_THREE_INTERACTION_SURFACES.md`
- Sibling: `DEFINE_PANEL_AUTHORITY_BOUNDARY.md`
- Sibling: `DEFINE_CHAT_AUTHORITY_BOUNDARY.md`
- Sibling: `DEFINE_AUTOMATION_SURFACE_AUTHORITY.md`
- Sibling: `RECONCILE_CHAT_MUTATION_AUTHORITY.md`

## Related GitHub Issues

None in this capability. If later filed, the issue should reference "Implements INTERACTION_SURFACES_AND_AUTHORITY/STATE_EXECUTION_AUTHORITY_REMAINS_GATED" and use the acceptance criteria above.

---

## The Invariant

> **No interaction surface — including Panel, Chat (under any resolution of the Chat mutation question), Automation, and any future surface — mutates durable state except through the existing governed path: policy, validation, event pipeline, and the deterministic note writer or equivalent state-writer.**

This is a floor-level invariant. Every surface described in this capability sits above it. No surface may define its authority boundary in a way that breaches this invariant.

### Corollary: LLM Reasoning Alone Never Triggers Execution

Cognition and execution are separated. A model's decision to act is never the sole cause of an action in this system. A model can:
- propose an action,
- surface an intent,
- draft a mutation.

But something else — a human action, a policy-approved watcher event, a validated intent contract — must be the thing that actually moves state. This corollary holds regardless of how capable the model is and regardless of how confident its reasoning appears.

### What "Durable State" Means Here

For the purposes of this invariant, durable state includes:

- **Vault notes and their frontmatter.** Any file the system writes, creates, modifies, or deletes inside the vault.
- **Graph or store projections.** Derived views and index structures the user relies on as truth (for example, relation graphs, knowledge-graph projections).
- **Receipts, event history, and governance-visible records.** The audit trail of what the system did on the user's behalf.
- **Scheduled or watcher-declared future behavior.** Registering a scheduled job, a watcher rule, or a policy trigger is itself a durable state change because it commits the system to future action.

**Transient canvas state is not durable state.** Whatever Chat-as-canvas manipulates in-place — drafts, reasoning traces, in-flight thought manipulations — remains non-durable until a commit-through-governance step runs. At the moment a commit step runs, the output becomes durable state and that step is subject to this invariant.

### Why the Invariant Is Stated at the Capability Level, Not Per Surface

Each surface in this capability defines its authority boundary upward from this floor. If the invariant lived only inside the Panel task, the Chat and Automation tasks would feel structurally free to ignore it. Stating it once here makes the floor identical across all surfaces: the same sentence applies to Panel, Chat, Automation, and any future surface the architecture adds.

### How the Invariant Interacts With the Chat Mutation Decision

The invariant holds under both candidate resolutions in `RECONCILE_CHAT_MUTATION_AUTHORITY.md`:

- **Candidate A (DESIGN_PRINCIPLES wins):** Chat is a canvas-shaped surface that may carry governed mutation rights. Chat mutations, when they exist, flow through the same policy + validation + event pipeline Panel mutations use. The invariant is satisfied because the governed path is identical.
- **Candidate B (V60 plan wins):** Chat is structurally read-only and never mutates durable state. The invariant holds trivially.

Neither resolution produces a Chat surface that mutates durable state outside the governed path. The invariant is not a tiebreaker between the candidates; it is a shared constraint both candidates satisfy.

### How the Invariant Interacts With Automation

Watcher reactions and scheduled jobs are not exceptions to this invariant. They are governed *upstream* by the policy that authorized them and *downstream* by the same pipeline Panel uses. A watcher that called an LLM to decide autonomously what to do would still be subject to the invariant: the LLM can propose; the governed pipeline acts. An Automation action that writes directly to vault state without passing through policy, validation, and the event pipeline breaches the invariant regardless of how routine the action appears.

See `DEFINE_AUTOMATION_SURFACE_AUTHORITY.md` for Automation's full authority boundary statement.

### What the Invariant Does Not Claim

- **It does not claim current runtime code is fully aligned.** The invariant is the contract. Delta-from-contract work — where current code does not yet satisfy the invariant — is tracked in implementation-track docs, not here. Shipping this invariant doc does not imply the runtime already satisfies it on every code path.
- **It does not claim the governance pipeline is finished.** The pipeline may evolve. The invariant names the *shape* — policy, validation, event pipeline, state-writer — not the specific implementation artifacts.
- **It does not claim existing event names or writer paths are final.** Renaming events, refactoring the note writer, or extending the pipeline are all permitted as long as the shape is preserved.
- **It does not pick a resolution to the Chat mutation question.** See `RECONCILE_CHAT_MUTATION_AUTHORITY.md`.

### Source Anchors

This invariant is derived from:
- `docs/DESIGN_PRINCIPLES.md` §Explicit Mutation Authority: "No system component may mutate durable state without a validated, policy-gated, event-producing execution step."
- `docs/plans/V60_CAPABILITY_AND_AGENT_EVOLUTION.md` §Fixed Decisions: "Execution remains gated. The LLM reasoning layer does not directly trigger mutations."

---

**Status:** Specification draft. `## The Invariant` section complete. Ready for review.
