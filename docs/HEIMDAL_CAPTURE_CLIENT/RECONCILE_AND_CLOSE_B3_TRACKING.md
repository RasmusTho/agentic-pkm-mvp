---
name: Reconcile And Close B3 Tracking
description: Assemble the B3 verification ledger on #3026, close it truthfully, update Epic B #3020 and this spec's state lines.
task_id: HCAP-10
source_anchor: docs/HEIMDAL_CAPTURE_CLIENT/README.md :: Capability acceptance criteria
parent_capability: Heimdal Capture Client
prerequisites: [HCAP-08, HCAP-09]
depends_on: [PROVE_CAPTURE_ROUND_TRIP_ON_TEST_CHANNEL, PROVE_CAPTURE_UAT_JOURNEYS]
can_parallelize_with: []
---

# Reconcile And Close B3 Tracking

Target repo: **`RasmusTho/agentic-pkm-mvp`** (hub — governance/tracking work, no Swift).

## Purpose

Close the B3 loop truthfully once every receipt exists — the same terminal pattern as B1/B2
(MIPAD-06). With B3 closed, Epic B's three slices are individually accounted for and the epic's
own closure decision becomes possible.

## What This Task Does

- Assembles the verification ledger on #3026: per-slice receipts (bifrost PR + CI run for
  HCAP-01..07 bifrost halves; hub PR for the sidecar consumer), the round-trip + EXP-1 receipt
  (HCAP-08), the journey + device walkthrough receipts (HCAP-09), and the gate audit (bifrost#4/#5
  merged before HCAP-04/05).
- Verifies each capability AC in the spec README against a receipt; unreceipted ACs keep #3026
  open with the gap named.
- Closes #3026; posts the B3-delivered ledger entry on Epic B #3020 (and, if B1/B2 are closed by
  then, surfaces "Epic B closable?" as a note to the owner rather than closing the epic
  unilaterally); flips this spec README's `State:` line to delivered; records the EXP-1 Model-2
  recommendation as the standing transport disposition.

## Concretely

`gh issue view 3026`: CLOSED, last comment is the full ledger; #3020 shows B3 delivered with
links; `docs/HEIMDAL_CAPTURE_CLIENT/README.md :: State` reads delivered with the date.

## Why This Matters

Capture is the highest-trust surface in the ecosystem — closing it on receipts (not vibes) is what
lets the owner treat "my phone captures into my second brain" as supported truth.

## Acceptance Criteria

- [ ] #3026 closed with the assembled ledger; every capability AC maps to a linked receipt.
  `Verify:` closing comment on #3026.
- [ ] Epic B #3020 carries the B3-delivered entry (+ epic-closable note if applicable). `Verify:`
  comment on #3020.
- [ ] Spec README `State:` updated; EXP-1 disposition recorded. `Verify:` doc writeback at
  `docs/HEIMDAL_CAPTURE_CLIENT/README.md :: State`.

## How to Verify (Pre-Merge)

- Docs-lane CI for the README flip; issue mutations executed via `gh` and linked in the PR body.

## Out of Scope

- Closing Epic B (owner-visible decision). Any code change. The missing stage-orchestrator gap
  (pre-existing, tracked separately).

## Related Docs

- `docs/YGGDRASIL_APP_SHELL_COMPLETION/RECONCILE_AND_CLOSE_B1_TRACKING.md` (pattern)
- `docs/HEIMDAL_CAPTURE_CLIENT/README.md`

## Related GitHub Issues

One implementation issue in `RasmusTho/agentic-pkm-mvp` (`type:task`, `agent:blocked` on HCAP-08 +
HCAP-09 receipts), linking #3026 and this spec file. TCD hint: Sonnet / low effort — mechanical
ledger assembly with a truthfulness bar.
