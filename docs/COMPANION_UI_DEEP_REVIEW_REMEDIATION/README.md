---
name: Companion UI Deep-Review Remediation
description: Specification directory remediating the 2026-06-22 Claude Design "Deep Design Review" of the Companion UI, across three leverage-ordered waves.
parent_capability: Companion UI Deep-Review Remediation
state: Filed — parent feature issue #2443; nine child issues #2444–#2448, #2450–#2453
---

# Companion UI Deep-Review Remediation

## Overview

Claude Design (Crossing-A design input) produced a two-axis deep review of the Companion UI
shell — *does each journey stay intuitive (Axis A)* and *is each function built well (Axis B)* —
across journeys J1–J7 plus cross-cutting findings. The review is the design source-of-truth for
this capability and lives at:

- `companion-ui/design_handoff/2026-06-22-companion-ui-deep-review/REVIEW_RESPONSE.html` (rendered)
- `companion-ui/design_handoff/2026-06-22-companion-ui-deep-review/REVIEW_RESPONSE.txt` (text/diff)

The review's verdict: the core loop — *open → orient → read → act with clarity → leave a clean
thread* — is sound in concept and several surfaces are genuinely well-built (re-entry card,
capture, settings, the System Map). It breaks in three high-leverage interaction places and two
systemic layout/grammar places. This capability remediates the full prioritised set
(recommendations **A1–A3, B1–B4, C1–C4, D1–D4, E1–E2**) as nine bounded task specifications, each
carrying the review's own acceptance criterion.

## The single hard constraint (capability-wide)

Every task here changes **how runtime-declared data is presented**. None asks the client to
invent, reclassify, or recompute entry-state, authority, posture, staleness, or receipts. That
server-authoritative classification boundary is test-enforced and is the point of the system; the
review repeats it three times and lists it under "do not change." Each task spec restates this as a
Constraint, and every behavioral AC that touches a classified value must assert the value is
**rendered from** the runtime payload, not derived in the UI.

## Implementation tasks (leverage-ordered)

### Wave 1 — shared primitives + front door (presentation-only, low risk; unblock the rest)

| Task file | Folds in | Intent |
|-----------|----------|--------|
| [CALM_DEGRADED_GRAMMAR_AND_ENUM_MAP.md](CALM_DEGRADED_GRAMMAR_AND_ENUM_MAP.md) | D3, C3, A3-copy | One degraded-copy grammar + a runtime-enum/identifier → human-copy map applied before any token reaches a user surface. |
| [OVERLAY_MODAL_FRAME_SPEC.md](OVERLAY_MODAL_FRAME_SPEC.md) | B4, D4-furniture | One modal-frame spec: fixed positions, header-furniture order, one scrim, one dismiss/Esc/focus-trap grammar across every overlay. |
| [RAIL_AMBIENT_UNTIL_ACTIVE.md](RAIL_AMBIENT_UNTIL_ACTIVE.md) | B1, J2 | Demote the right rail to a thin ambient strip when idle; expand only when it carries a suggestion, proposal, or receipt. The note becomes the primary surface. |
| [EDGE_JOB_AND_REACHABILITY.md](EDGE_JOB_AND_REACHABILITY.md) | B2, B3, C1 | Decide what the top/bottom edges are for; route launchers into one never-clipping surface; move operator telemetry off the front edge. |
| [FRONT_DOOR_AND_COPY_HYGIENE.md](FRONT_DOOR_AND_COPY_HYGIENE.md) | D1, D2, C4 | Style the vault picker to the design system, make entry-screen actions ranked affordances, strip internal issue numbers from the System Map. |

### Wave 2 — signature interaction re-authoring (highest leverage; depends on Wave 1)

| Task file | Folds in | Intent |
|-----------|----------|--------|
| [MIST_LADDER_SUBTRACTIVE.md](MIST_LADDER_SUBTRACTIVE.md) | A1, D4-collision | Make the re-entry mist ladder subtractive: short gaps render little to nothing; orientation panels appear only from `full_mist` up, de-duplicated against the card. |
| [GOVERNED_RECEIPT_FIRST_CLASS.md](GOVERNED_RECEIPT_FIRST_CLASS.md) | A2 | Promote the governed receipt to a first-class, in-place confirmation: the applied card becomes "Applied · receipt recorded" linking to its history entry. |
| [BLOCKED_RECOURSE_AND_LANE_LABELING.md](BLOCKED_RECOURSE_AND_LANE_LABELING.md) | A3, C2 | Give Blocked a plain-language reason + recourse; label the two agent lanes (recorded vs not-recorded) in words, not colour. |

### Wave 3 — strategic (carries open product decisions)

| Task file | Folds in | Intent |
|-----------|----------|--------|
| [STRATEGIC_COLDSTART_AND_RAIL_PALETTE.md](STRATEGIC_COLDSTART_AND_RAIL_PALETTE.md) | E1, E2 | Reconsider the cold_start cutoff for long absences; decide the rail-vs-palette relationship deliberately. Both embed a named owner decision. |

## Execution order (one flat ordered list)

1. `CALM_DEGRADED_GRAMMAR_AND_ENUM_MAP` — primitive; consumed by mist ladder, blocked, front-door error.
2. `OVERLAY_MODAL_FRAME_SPEC` — primitive; consumed by receipt promotion and every overlay.
3. `RAIL_AMBIENT_UNTIL_ACTIVE` — primitive; the rail is the host for the receipt + active proposals.
4. `EDGE_JOB_AND_REACHABILITY` — primitive; moves telemetry off the orientation surface the mist ladder reclaims.
5. `FRONT_DOOR_AND_COPY_HYGIENE` — independent quick wins; parallelizable with 1–4.
6. `MIST_LADDER_SUBTRACTIVE` — needs 1 (enum map), 3 (rail), 4 (telemetry off orientation surface).
7. `GOVERNED_RECEIPT_FIRST_CLASS` — needs 2 (frame), 3 (rail active state).
8. `BLOCKED_RECOURSE_AND_LANE_LABELING` — needs 1 (grammar).
9. `STRATEGIC_COLDSTART_AND_RAIL_PALETTE` — needs 3 (rail calmed) to settle E2; carries the owner decision.

Tasks 1–5 parallelize freely (isolated worktrees). Tasks 6–8 unblock as their Wave-1 prerequisites
merge. Task 9 is owner-gated.

## Cross-Task Invariants / Interaction Safety

Several tasks read or write the same surface; these invariants hold *across* tasks:

- **Classification stays server-side (all tasks).** No task may move an entry-state, authority,
  posture, staleness, or receipt decision into the client. A task that needs a humanised string for
  a runtime enum (task 1) maps the *display*; the underlying classified value still arrives from the
  runtime payload. Partial-failure path: if the enum map (task 1) lands incomplete, tasks 6 and 8
  must **fail closed to the raw-token-suppressed calm fallback** ("… unavailable — details
  withheld"), never leak the raw token as a stopgap.
- **The rail is the single host for active proposals and the receipt (tasks 3, 7, 8).** The receipt
  promotion (7) and the lane-labelled proposal cards (8) both render into the rail's *active* state
  defined by task 3. Invariant: the rail is ambient **only** when it carries nothing; the moment a
  proposal, suggestion, or receipt exists it is in the active state — there is no state where a
  receipt exists but the rail still renders ambient. Seam: if task 7 lands before task 3, the
  receipt has no defined active host; task 7 must not ship until the rail active-state contract (3)
  exists.
- **The orientation surface carries no telemetry (tasks 4, 6).** Task 4 moves operator telemetry
  (RECOVERY / Online / as-of / Operator) off the front edge; task 6 reclaims the orientation surface
  for the re-entry card. Invariant: after both land, no governance/telemetry tile appears on the
  orientation surface at any mist rung — it is reachable only via the System Map / operator layer.
  Seam: if task 6 lands first, the governance tiles it de-duplicates must be **removed from the
  orientation render**, not merely relocated within it, so task 4 does not later re-introduce them.
- **One overlay frame, one dismiss grammar (tasks 2, 7).** The receipt's in-place confirmation and
  its link-to-history overlay both use the frame defined by task 2. No new bespoke overlay frame is
  introduced by a downstream task.

If any of these invariants cannot be stated for a re-cut of the tasks, the slice boundary is wrong —
re-cut before creating issues.

## Verification path (task level)

Each task spec names its `Verify:` target per AC: a behavioral AC names the test (path + name); a
non-behavioral AC names a render-capture diff or doc target. `static` ACs are verified by rendering
the relevant fixture (server-rendered capture) and diffing/inspecting it; `live` ACs (motion, focus,
round-trip, caret restore) are flagged for live UAT against the running shell. The split mirrors the
review's own Verify column.

## Validation / acceptance path (capability level)

The parent feature issue is the live validation hub. Acceptance criteria for claiming the capability
supported:

- [ ] Every Wave-1 and Wave-2 task is merged with its `static` ACs verified on a rendered capture.
  - Verify: PR receipts linked on the parent issue; capture diffs attached per task.
- [ ] The `live` ACs (A1 caret-restore, A2 post-apply state, B4 focus/Esc, populated flows) are
  exercised in one live UAT pass against the running Companion UI and recorded on the parent issue.
  - Verify: live UAT receipt comment on the parent feature issue.
- [ ] No user-facing surface shows a raw transport error, runtime enum, or internal identifier
  (capability-wide regression scan).
  - Verify: render scan across shell + entry + degraded fixtures.
- [ ] The owner decision in task 9 (E1/E2) is recorded before that task is built.
  - Verify: decision note on the parent issue or task-9 issue.

Owner docs (the Companion UI surface specs) are promoted only once acceptance is met — one owner-doc
PR at the end, not per task.

## Relationship to GitHub issues

This directory is the source of truth for *what to build*. The GitHub issues are execution
contracts that reference it. Filed state:

- Parent feature issue (validation hub): **#2443** — `companion-ui`, `agent:blocked`.
- Wave-1 children **#2444–#2448** — `agent:ready` (parallelizable).
- Wave-2 children **#2450** (CUIDR-06), **#2451** (CUIDR-07), **#2452** (CUIDR-08) — `agent:blocked`
  until their Wave-1 prerequisites merge.
- Wave-3 child **#2453** (CUIDR-09) — `agent:needs-human` (open E1/E2 owner decision).

[PARENT_FEATURE_ISSUE.md](PARENT_FEATURE_ISSUE.md) records the live issue numbers and lifecycle
state.
