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

- [x] The task file states the invariant in one quotable sentence.
- [x] The task file explicitly says LLM reasoning alone never triggers execution.
- [x] The task file defines "durable state" and explicitly notes that transient canvas state becomes durable only at the commit-through-governance step.
- [x] The task file shows the invariant holds under both candidate resolutions of `RECONCILE_CHAT_MUTATION_AUTHORITY.md`.
- [x] The task file shows the invariant covers Automation as well as Panel and Chat.
- [x] The task file does not claim current runtime code is fully aligned; it states the invariant as the contract.
- [x] The task file cites `docs/DESIGN_PRINCIPLES.md` §Explicit Mutation Authority and `docs/plans/V60_CAPABILITY_AND_AGENT_EVOLUTION.md` Fixed Decisions as source anchors.
- [x] The vocabulary matches `NAME_THE_THREE_INTERACTION_SURFACES.md`.

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

## The Invariant

> **"No interaction surface — including Panel, Chat (under any resolution of the Chat mutation question), Automation, and any future surface — mutates durable state except through the existing governed path: policy, validation, event pipeline, and the deterministic note writer or equivalent state-writer."**

This invariant is the floor. Every surface described in this capability sits above it; none sits below it.

### Corollary: LLM reasoning alone never triggers execution

Cognition and execution are separated. A model's decision to act is never the sole cause of an action. A model may propose an action, surface an intent, or draft a mutation. Something else — a human action, a policy-approved watcher event, a validated intent contract — must be the thing that actually moves state.

This corollary holds for Panel, Chat, and Automation alike. There is no exception for "obvious" or "low-risk" reasoning; the boundary between proposal and execution is not relaxed based on perceived safety.

### What "durable state" means here

- Vault notes and their frontmatter.
- Graph or store projections that the user relies on as truth.
- Receipts, event history, and governance-visible records.
- Scheduled or watcher-declared future behavior.

Transient canvas state — for example, what Chat-as-canvas manipulates in-place before any commit — is **not** durable state by this definition. Canvas state becomes durable state at the moment a commit-through-governance step runs. That step is subject to the invariant; the transient manipulation preceding it is not.

### Why the invariant is stated at the capability level, not per surface

Each surface describes its own authority upward from this floor. If the invariant lived only inside the Panel task, the Chat task would be free to ignore it. Stating it at the capability level makes the floor identical across surfaces and prevents per-surface carve-outs that would hollow it out.

### How the invariant interacts with the Chat mutation decision

The invariant holds under both candidate resolutions of `RECONCILE_CHAT_MUTATION_AUTHORITY.md`.

- **Candidate A (DESIGN_PRINCIPLES wins, currently selected):** Chat may carry governed mutation rights. Those mutations flow through the same gated path — policy, validation, event pipeline — that Panel mutations flow through. The invariant holds because the path requirement is the same.
- **Candidate B (V60 plan wins):** Chat stays structurally read-only. The invariant holds trivially because Chat never mutates.

The invariant is not a vote for either resolution. It is the shared contract both resolutions must honour.

### How the invariant interacts with Automation

Watcher reactions and scheduled jobs are not exceptions to the invariant. They are governed upstream by the policy that approves them and downstream by the same pipeline Panel uses. A watcher that used an LLM to decide what to do would still be subject to the invariant: the LLM may propose; the pipeline acts.

### What the invariant does not claim

- It does not claim that the governance pipeline is finished or that every policy surface has landed. It claims the shape: no surface bypasses it.
- It does not claim that existing event names or writer paths are final.
- It does not claim that all current runtime code already matches the invariant. It states the invariant as the contract; delta-from-contract work is tracked separately in implementation-track docs, not here.

### Source anchors

- `docs/DESIGN_PRINCIPLES.md` §Explicit Mutation Authority: "Any path that can mutate durable state must be policy-bounded, auditable, and reviewable."
- `docs/plans/V60_CAPABILITY_AND_AGENT_EVOLUTION.md` §Fixed Decisions :: Execution remains gated: "The target execution boundary is `observation -> normalization/contract -> admission -> execution`; cognition may assist proposal and normalization, but must not collapse admission into execution."

---

**Status:** Specification complete. `## The Invariant` section delivered. All acceptance criteria satisfied.
