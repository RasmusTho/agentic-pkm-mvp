---
name: Define Automation Surface Authority
description: State that watcher-driven, scheduled, and proactive surfaces form a distinct authority lane that is governed but not interactive
task_id: INTERACTION-04
source_anchor: docs/plans/V60_CAPABILITY_AND_AGENT_EVOLUTION.md :: Fixed Decisions :: Execution remains gated
parent_capability: Interaction surfaces and authority boundaries
prerequisites: [INTERACTION-01]
depends_on: [NAME_THE_THREE_INTERACTION_SURFACES.md]
can_parallelize_with: [DEFINE_PANEL_AUTHORITY_BOUNDARY, DEFINE_CHAT_AUTHORITY_BOUNDARY, STATE_EXECUTION_AUTHORITY_REMAINS_GATED]
---

State: Specification draft. Docs-only. Describes an authority lane that is already live in the runtime but under-named.

# Define Automation Surface Authority

## Purpose

Name Automation as a distinct interaction-adjacent surface with its own authority envelope. Automation covers watcher-driven reactions, scheduled jobs, and future proactive agent behaviors. The user is not in a live turn when Automation acts, so the trust model, the receipt model, and the failure mode are all different from Panel and Chat.

Without this task, Automation silently collapses into "background behavior" and loses its status as a first-class surface in the interaction model.

## What This Task Does

Produces a docs section that states:

1. **What Automation is, in one sentence.**
   Proposed authority statement (to be finalized during review): "Automation is the interaction-adjacent surface where the system acts on the user's behalf without a live interactive turn — in response to watcher events, schedules, or policy triggers — within an envelope the user has approved in advance and can audit afterward."

2. **What belongs in the Automation lane today.**
   - Vault watcher reactions (file creation, modification, deletion that trigger the intent pipeline).
   - Scheduled or periodic jobs (registry watchers, temporal governance checks, maintenance sweeps).
   - Auto-exec paths that a human has previously opted into (for example, policy auto-exec plumbing under v5.5 baseline guardrails).
   - Future proactive agent behaviors: surface a suggestion, resurface a stale note, propose a cleanup — where the surfacing itself is the action.

3. **What the Automation lane is not.**
   - It is not a separate execution runtime that bypasses governance. It uses the same policy / validation / event pipeline as Panel does.
   - It is not a Chat replacement for users who dislike chatting.
   - It is not a Panel replacement for explicit intent. A scheduled action is not an intent; it is a policy outcome of a previously-declared intent shape.
   - It is not allowed to act on LLM reasoning alone. See `STATE_EXECUTION_AUTHORITY_REMAINS_GATED.md`.

4. **Automation's cognitive posture.**
   Proactive or reactive: the system initiates the turn, not the user. The user's cognitive posture is audit-afterwards, not drive-through-interaction.

5. **Automation's accountability surface.**
   Event stream and outbox history. Unlike Panel, there is no in-note receipt callout by default, because there is no note the user was currently in. Receipts must be findable in the event record and, where applicable, via the watcher-run events (for example, the `watcher.run` event emission referenced in recent infrastructure work). This task names the receipt expectation; it does not redesign the receipt surface.

6. **Automation's relationship to Chat and Panel.**
   Automation can surface a suggestion that becomes a Panel action or a canvas item in Chat. Crossing from Automation into Panel or Chat is a surface crossing and must be legible to the user — they should be able to see "this action started as an automated suggestion" in the receipt record. The reconcile task owns the Chat-side of that crossing; this task just asserts the requirement.

7. **Where Automation differs from Panel and Chat on the trust model.**
   Panel trust comes from explicit-intent-in-note. Chat trust (under any resolution of the reconcile task) comes from externalized-canvas-commit-path. Automation trust comes from pre-approved envelope plus after-the-fact auditability. These are three different trust models, which is the central argument for keeping the three surfaces distinct.

## Concretely

The deliverable is a section in this file titled `## Automation Authority Boundary` that captures the seven points above and ends with a short "what already exists in runtime" paragraph that cites watcher, scheduler, and policy auto-exec plumbing as the current Automation surface members.

## Why This Matters

Automation is already doing work on the user's behalf in v5.5 (watcher, scheduled jobs, policy auto-exec plumbing). If the interaction model does not name it as a distinct surface, it ends up classified as "the rest of Panel" or "background plumbing," neither of which carries a real authority statement. The user-needs model "trust what the system did" requires that the user can describe Automation's envelope in one sentence; this task makes that sentence exist.

This task also protects against a common failure mode where proactive or scheduled behavior is added opportunistically with no explicit authority envelope and then quietly widens what the system is allowed to do.

## Acceptance Criteria

- [ ] The task file states a one-sentence Automation authority statement.
- [ ] The task file names at least three concrete current members of the Automation lane (watcher reactions, scheduled jobs, policy auto-exec plumbing).
- [ ] The task file states that Automation uses the same governance pipeline as Panel and does not bypass it.
- [ ] The task file explicitly says LLM reasoning alone never triggers an Automation action, and cites `STATE_EXECUTION_AUTHORITY_REMAINS_GATED.md`.
- [ ] The task file describes Automation's trust model (pre-approved envelope + after-the-fact audit) as distinct from Panel's and Chat's.
- [ ] The task file names the receipt expectation (event stream / outbox / watcher-run events) without redesigning it.
- [ ] The vocabulary matches `NAME_THE_THREE_INTERACTION_SURFACES.md`.
- [ ] The task file does not propose new automation capabilities.

## How to Verify (Pre-Merge)

Docs review:

- A reviewer can point to the one-sentence Automation authority statement and read it aloud.
- A reviewer can list the three current members of the Automation lane without running any code.
- The file contains no implementation or schema changes.
- The file does not propose new watcher behaviors or new schedulers.

## Out of Scope

- Redesigning the watcher.
- Redesigning the scheduler.
- Adding new automation triggers.
- Naming a specific future proactive agent.
- Deciding how Automation integrates with canvas-Chat — only asserting that the crossing must be legible.
- Changing any event schema or payload.

## Related Docs

- `docs/plans/V60_CAPABILITY_AND_AGENT_EVOLUTION.md` §Fixed Decisions :: Execution remains gated
- `docs/plans/V60_ARCHITECTURE_TARGET.md` §Pillar 10A
- `docs/DESIGN_PRINCIPLES.md` §Governance Before Autonomy
- `docs/PANEL_AGENT.md` :: watcher auto-exec plumbing references
- Sibling: `NAME_THE_THREE_INTERACTION_SURFACES.md`
- Sibling: `STATE_EXECUTION_AUTHORITY_REMAINS_GATED.md`

## Related GitHub Issues

None in this capability. If later filed, the issue should reference "Implements INTERACTION_SURFACES_AND_AUTHORITY/DEFINE_AUTOMATION_SURFACE_AUTHORITY".

---

## Automation Authority Boundary

**Automation** is the interaction-adjacent surface where the system acts on the user's behalf without a live interactive turn — in response to watcher events, schedules, or policy triggers — within an envelope the user has approved in advance and can audit afterward.

### What Belongs in the Automation Lane Today

The following behaviors are current members of the Automation surface:

1. **Vault watcher reactions.** File creation, modification, and deletion events that trigger the intent pipeline. When the watcher fires, the system applies a governance-approved rule, not an ad-hoc LLM decision.
2. **Scheduled and periodic jobs.** Registry watchers, temporal governance checks, and maintenance sweeps that run on timer or policy trigger.
3. **Policy auto-exec paths.** Paths where a human has previously opted into automatic execution (for example, policy auto-exec plumbing under v5.5 baseline guardrails). The opt-in is the pre-approved envelope; the action itself still flows through the governed pipeline.
4. **Future proactive agent behaviors.** Surfacing a suggestion, resurfacing a stale note, or proposing a cleanup where the surfacing itself is the action. This is Automation, not Panel, because the user did not initiate the turn.

### What the Automation Lane Is Not

- **Not a bypass of the governance pipeline.** Automation uses the same policy, validation, and event pipeline as Panel. Nothing in the Automation lane may skip policy enforcement or write to durable state outside that pipeline.
- **Not a Chat replacement.** Automation is not a way to hold a live interactive conversation with the user. The user's cognitive posture during Automation is audit-afterwards, not drive-through-interaction.
- **Not a Panel replacement.** A scheduled or watcher-triggered action is not an explicit user intent. It is a policy outcome of a previously declared intent shape. Panel serves command-oriented explicit intent; Automation does not.
- **Not permitted to act on LLM reasoning alone.** See `STATE_EXECUTION_AUTHORITY_REMAINS_GATED.md`. The LLM may propose or draft a mutation; Automation may not execute it without a policy-approved, validated trigger from the governed pipeline.

### Automation's Cognitive Posture

**Proactive or reactive:** the system initiates the turn, not the user. The user's cognitive posture during Automation is *audit-afterwards*, not *drive-through interaction*. The user should be able to answer "what did the system do on my behalf, and why?" by reading the receipt and event record — without having been present when the action occurred.

### Automation's Trust Model

Automation trust is derived from two distinct sources, neither of which applies to Panel or Chat:

1. **Pre-approved envelope.** The user (or a policy the user has accepted) has declared in advance what class of action the system is permitted to take and under what conditions. The envelope is the authority grant; individual actions within it do not require interactive confirmation.
2. **After-the-fact auditability.** Because the user is not present during the turn, the system must produce a findable record for every action: what triggered it, what the action was, what changed, and where the receipt lives.

This is distinct from Panel's trust model (explicit-intent-in-note, receipt-in-note) and from Chat's trust model under the `RECONCILE_CHAT_MUTATION_AUTHORITY.md` resolution (externalized-canvas-commit-path through the gated-execution pipeline).

### Automation's Accountability Surface

Automation receipts live in the **event stream and outbox history**, not in individual notes. Unlike Panel, there is no in-note receipt callout by default, because there is no note the user was currently in. The receipt expectations for Automation are:

- Every watcher-triggered action emits a `watcher.run` event (or equivalent) that names the trigger, the rule applied, and the outcome.
- Every scheduled job emits an event that names the schedule, the job, and the outcome.
- Policy auto-exec paths emit events consistent with the existing governance pipeline.

This task names the receipt expectation. It does not redesign the receipt surface; that belongs to implementation-track work.

### Automation's Relationship to Panel and Chat

Automation can surface a suggestion that becomes a Panel action or a canvas item in Chat. Crossing from Automation into Panel or Chat is a **surface crossing** and must be legible to the user — they should be able to see "this action started as an automated suggestion" in the receipt record. The `RECONCILE_CHAT_MUTATION_AUTHORITY.md` reconcile task owns the Chat-side of that crossing; this task asserts the crossing-legibility requirement without designing its implementation.

### What Already Exists in the Runtime

The Automation surface is not hypothetical. The following runtime components are current Automation surface members as of the v5.5 baseline:

- **Vault watcher** (previously `VaultMirror`, **deprecated** — replaced by companion notes; see `docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md`): reacts to file-system events and triggers the intent classification and routing pipeline.
- **Scheduler / periodic jobs**: runs temporal governance checks (commitment expiry detection, stale-note detection) and maintenance sweeps on schedule.
- **Policy auto-exec plumbing**: the infrastructure that allows a previously-approved policy to trigger vault mutations without interactive confirmation per action.

These components are governed by the same pipeline as Panel mutations. They are named here as Automation lane members to close the gap between the system's operational reality and its interaction model vocabulary.

---

**Status:** Specification draft. `## Automation Authority Boundary` section complete. Ready for review.
