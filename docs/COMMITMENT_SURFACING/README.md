---
name: Commitment Surfacing Specification
description: System specification for surfacing durable human commitments (next-action / waiting / review-cycle) to the human through the companion route and Panel/Companion UI
type: specification
authority: System-level spec for the commitment-surfacing capability; downstream of COMMITMENT_AS_FIRST_CLASS and COMMITMENT_LAYER_CONTRACT, upstream of runtime realization
source_of_truth: docs/CONCEPTS/COMMITMENT_LAYER_CONTRACT.md :: Primary concepts
related_docs:
  - docs/COMMITMENT_AS_FIRST_CLASS/README.md
  - docs/COMMITMENT_AS_FIRST_CLASS/DEFINE_COMMITMENT_STATE_TRANSITIONS.md
  - docs/COMMITMENT_AS_FIRST_CLASS/DEFINE_COMMITMENT_RECEIPT_REQUIREMENT.md
  - docs/CONCEPTS/COMMITMENT_LAYER_CONTRACT.md
  - docs/CONCEPTS/STATE_AXES_CONTRACT.md
  - docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md
---

State: Delivered capability specification lane. Parent validation hub **#1960** closed as completed on 2026-06-18 after child slices #2073-#2075 delivered; this directory remains the system-level source record for what shipped, and GitHub remains the authoritative backlog and validation record. Shaped by the owner decision recorded on #1960 (2026-06-15): durable persistence is a prerequisite and the substrate is the vault, in the companion-note family — not a new DB, not transient `AgentState`.

# Commitment Surfacing

This directory is the system-level specification for one capability: **surfacing human commitments to the human**. The commitment domain model already ships (`app/domain/commitments.py`: `CommitmentKind`, `CommitmentRecord`, `CommitmentQueryResult`), and the planner attaches ephemeral `CommitmentHandle`s to the in-memory `AgentState` — but nothing persists, queries, exposes, or renders commitments. There is no companion API field and no UI render. This spec closes that gap.

The capability, in one sentence:

> Active commitments (next_action / waiting / review_return) are persisted as durable, agent-maintained vault artefacts in the companion-note family, exposed read-only through the companion workspace route, and rendered in the Panel/Companion UI with next-action visually distinguished from review-cycle.

This is a **specification**, not a plan. Each task file describes a discrete, independently mergeable implementation task with its own acceptance criteria and verification targets.

## Human need this serves

This is the classic cognitive-prosthetic capability for a second brain (`docs/COMMITMENT_AS_FIRST_CLASS/README.md` :: "Human needs this serves"). The user externalizes open loops, next actions, and waiting states and must be able to **trust and inspect** what the system holds. Two needs drive surfacing:

- **See what is carried without re-remembering it.** The user should glance at the workspace and see what is next, what is waiting, and what returns to review — without re-deriving it each session.
- **Trust the surface.** If the surface flickers (a commitment shown one request, gone the next), trust collapses. That is exactly why the owner decision makes durable persistence a prerequisite: surfacing from the ephemeral per-request `AgentState` `CommitmentHandle`s would flicker and break trust.

## The recorded owner decision (governs this breakdown)

Recorded on #1960 (2026-06-15, coordinator `deliver-issue-set/v6.1-wave2`):

- **Who needs commitments?** The human → a **human artefact**.
- **Expected lifetime?** Long-lived; open loops outlive a single request/session → **durable**.
- **Therefore:** durable persistence is required first. The substrate is the **vault, stored in the companion-note manner** — an agent-maintained durable vault artefact carrying the existing `CommitmentRecord` shape (kind / state / target_ref / summary / source_goal). It is **NOT** a separate DB (this honors the v6.0 spec's explicit DB-schema-deferral non-goal in `docs/COMMITMENT_AS_FIRST_CLASS/README.md` :: "What this capability is NOT") and **NOT** transient `AgentState`. Writes stay **read/proposal-only and WriteGuard-governed**.
- **Residual sub-question (does not block this breakdown):** whether a commitment is its own vault artefact or a section within the related note's companion note. This is pinned **inside slice 1** against `COMMITMENT_LAYER_CONTRACT` and `DEFINE_COMMITMENT_STATE_TRANSITIONS`.

## Implementation tasks

Read and execute in this order. Each task is one file in this directory and maps to one bounded GitHub child issue under parent #1960.

1. **[PERSIST_COMMITMENTS_AS_VAULT_ARTEFACTS.md](PERSIST_COMMITMENTS_AS_VAULT_ARTEFACTS.md)** — the durable foundation. Persist `CommitmentRecord`s as agent-maintained durable vault artefacts in the companion-note family; read/proposal-only, WriteGuard-governed; survives process restart. Pins the artefact shape against the contract.
2. **[EXPOSE_COMMITMENTS_IN_COMPANION_ROUTE.md](EXPOSE_COMMITMENTS_IN_COMPANION_ROUTE.md)** — expose active commitments in the companion workspace state via `app/api/routes/companion.py`, read-only, backed by the durable query path from task 1 (not by live `AgentState`). Depends on task 1.
3. **[RENDER_COMMITMENTS_IN_PANEL_UI.md](RENDER_COMMITMENTS_IN_PANEL_UI.md)** — render commitments in the Panel/Companion UI, visually distinguishing next-action from review-cycle. Depends on task 2.

## Execution order

```
PERSIST_COMMITMENTS_AS_VAULT_ARTEFACTS  →  EXPOSE_COMMITMENTS_IN_COMPANION_ROUTE  →  RENDER_COMMITMENTS_IN_PANEL_UI
        (slice 1, durable source)              (slice 2, read-only API surface)           (slice 3, read-only render)
```

Strict dependency chain. The API surface (task 2) must not be built over live `AgentState`; it reads from the durable source ratified in task 1. The UI (task 3) renders from the API model produced in task 2. No task may start before its predecessor merges.

## Cross-Task Invariants / Interaction Safety

Tasks 1, 2, and 3 share commitment state: task 1 writes/queries the durable source, task 2 reads it through the route, task 3 renders what the route returns. A breakdown whose tasks are each locally correct can still lose trust in the seams between them. The invariants that must hold *across* tasks:

- **CI-1 — Single source of truth.** The surfaced commitment set has exactly one authority: the durable vault artefact(s) from task 1. The route (task 2) and the UI (task 3) are read-only projections of that source. Neither the route nor the UI may invent, cache-as-authority, or mutate commitment state. (Verified at task 2 by an architecture assertion that the route reads the durable query path, not `AgentState`.)
- **CI-2 — No flicker / no fabricated absence.** Because the source is durable (survives restart, task 1), the surface must not flicker between requests for the same underlying state. A commitment shown to the user in one request must still be shown in the next request unless the durable source changed. The UI must not silently drop a commitment because a read degraded; a degraded read is shown as degraded, not as empty (the `unknown` legality from `DEFINE_COMMITMENT_STATE_TRANSITIONS` applies — absence of certainty is `unknown`, never a fabricated empty list presented as truth).
- **CI-3 — Read-only all the way down.** Surfacing is read/proposal-only at every layer. WriteGuard governs the only write path (task 1's persistence). The route (task 2) and UI (task 3) perform no writes and assert read-only posture. This matches the existing companion read surfaces (`WorkspaceStateResponse`, vault browser `read_only: True`).

### Partial-failure seams (walk every one before slicing is final)

- **Persisted but not exposed (seam 1↔2).** Task 1 persists a commitment to the vault, but task 2's route fails to expose it (read error, query degraded, route not yet wired, or deployed out of order). Invariant: the durable artefact is the truth; a route that cannot read it must surface a **degraded** read state (empty-but-degraded, with a reason), never a confident empty surface that tells the user "you have no commitments" when the durable source says otherwise. The commitment is not lost — it is on disk in the vault; the bug is a read/exposure bug, recoverable by re-reading. This is the direct analog of the v6.0 receipt rule "a missing receipt is a trust bug; a missing commitment is a different bug" (`DEFINE_COMMITMENT_RECEIPT_REQUIREMENT.md` :: Non-displacing).
- **Exposed but not rendered (seam 2↔3).** Task 2 returns commitments in the workspace state, but task 3's UI is not yet deployed or fails to render the new field. Invariant: the API field is additive and backward-compatible; an older UI that ignores the field degrades to "not shown", not to a crash. The commitment remains in the API payload and on disk. When task 3 ships, it renders without a data migration.
- **Write blocked mid-persist (seam inside 1, but visible to 2/3).** WriteGuard blocks the persistence write (degraded runtime state). Invariant: a blocked write must not leave a half-written artefact that the route then reads as a real commitment. Persistence is atomic-or-absent (write the complete artefact or none of it), matching the `materialize_promoted_memory` pattern where the guard is asserted *before* the write and the write is a single complete file. A blocked write means "this commitment was not persisted", which is honest, not "this commitment is in an indeterminate state".
- **Out-of-order deploy (any pair).** Because the dependency chain is strict and the API field is additive, deploying task 2 before task 1 means the route has no durable source and must report degraded/empty-with-reason (not crash); deploying task 3 before task 2 means the UI has no field to render and degrades to not-shown. No ordering produces data loss or a confident-but-wrong surface.

If any of these seams could not be given an invariant, the slice boundaries would be wrong. They can; the boundaries hold.

## Acceptance

Hub #1960 closed as delivered on 2026-06-18 after the repo-verifiable implementation acceptance below landed on `main`. The closure receipt left owner-doc promotion as a follow-up docs step rather than a blocker for closing the validation hub.

- [x] `CommitmentRecord`s persist as agent-maintained durable vault artefacts in the companion-note family and survive a process restart.
  - Verify: `tests/commitments/test_commitment_persistence.py` (new) — durability across a simulated restart + WriteGuard enforcement at the production call site.
- [x] Active commitments (next_action / waiting / review_return) are exposed in the companion workspace state, read-only, backed by the durable source (not `AgentState`).
  - Verify: `tests/api/test_companion_commitments.py::test_commitments_in_workspace_state` (new).
- [x] Next-action and review-cycle commitments are visually distinguished in the Panel/Companion UI.
  - Verify: `tests/companion_ui/test_commitment_surface.py` (new).
- [x] The architecture guard `tests/api/test_arch_commitment_and_canvas.py::test_commitments_surface_in_workspace_state` flips from xfail to pass on merged heads (the workspace surface exposes a commitment field).
  - Verify: `tests/api/test_arch_commitment_and_canvas.py::test_commitments_surface_in_workspace_state` passes (xfail removed).
- [ ] Owner-doc promotion decided once the shipped source and surface are accepted (see Validation / Acceptance Path).
  - Verify: doc writeback at `docs/COMMITMENT_AS_FIRST_CLASS/README.md` or `docs/STATUS.md` recording commitment surfacing as shipped (only when accepted).

## Verification path

Task-level proof surfaces (each task names its own tests; this is the rollup):

- Slice 1: `tests/commitments/test_commitment_persistence.py` — durability across restart, read/proposal-only, WriteGuard asserted at the production write call site.
- Slice 2: `tests/api/test_companion_commitments.py::test_commitments_in_workspace_state` + an architecture assertion that the route reads the durable query path (not `AgentState`).
- Slice 3: `tests/companion_ui/test_commitment_surface.py` — next-action vs review-cycle distinguished; read-only projection (no mutation affordances).
- Capability guard: `tests/api/test_arch_commitment_and_canvas.py::test_commitments_surface_in_workspace_state` — xfail removed; passes on merged heads after the workspace commitment surface landed.

## Validation / Acceptance path

- Each delivered child PR posted a validation receipt to parent #1960 naming the merged SHA, the tests that ran green, and whether the capability was closer to acceptance.
- After all three slices merged and the xfail guard flipped, the operator validation path remained: a real commitment persisted, read through the route, rendered in the UI, and still present after a runtime restart.
- The 2026-06-18 closure receipt closed #1960 as delivered while leaving owner-doc promotion (recording commitment surfacing as shipped reality) as a follow-up docs step after that operator validation, per the feature-breakdown evidence-surface rule.

## Relationship to GitHub issues

- **Parent / validation hub:** Issue **#1960** (`CLOSED` / `COMPLETED`, `Status=Done`). It is not a pickup issue; it is the delivered validation record for this capability.
- **Child slices** (each references "Implements COMMITMENT_SURFACING/{TASK}" and carries `Parent: #1960`):
  - Slice 1 → **#2073** `[Commitment Surfacing] persist-commitments-as-vault-artefacts` — closed/completed.
  - Slice 2 → **#2074** `[Commitment Surfacing] expose-commitments-in-companion-route` — closed/completed.
  - Slice 3 → **#2075** `[Commitment Surfacing] render-commitments-in-panel-ui` — closed/completed.

The specification in this directory is the source of truth for *what the system needed to do*; the GitHub issues now serve as the delivered validation history for that work.

## Navigation

- **Parent feature issue (local source):** [PARENT_FEATURE_ISSUE.md](PARENT_FEATURE_ISSUE.md)
- **Upstream semantic spec:** `docs/COMMITMENT_AS_FIRST_CLASS/README.md`
- **Commitment concept contract:** `docs/CONCEPTS/COMMITMENT_LAYER_CONTRACT.md`
- **State axes (stay distinct from):** `docs/CONCEPTS/STATE_AXES_CONTRACT.md`
- **Companion-note substrate contract:** `docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md`
- **Commitment domain model:** `app/domain/commitments.py`
- **Companion route:** `app/api/routes/companion.py`
