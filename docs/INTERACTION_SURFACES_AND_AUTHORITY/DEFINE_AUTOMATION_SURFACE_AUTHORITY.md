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

**Status:** Specification draft. No blockers.
