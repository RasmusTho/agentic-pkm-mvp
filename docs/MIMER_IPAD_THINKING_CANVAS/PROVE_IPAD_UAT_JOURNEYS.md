---
name: Prove iPad UAT Journeys
description: The B2 acceptance journeys run as XCUITests on the iPad simulator in CI, plus the operator's scripted eyes-on iPad walkthrough receipt on #3024.
task_id: MIPAD-05
source_anchor: docs/MIMER_IPAD_THINKING_CANVAS/README.md :: Capability acceptance criteria
parent_capability: Mimer iPad Thinking Canvas
prerequisites: [MIPAD-01, MIPAD-02, MIPAD-03, MIPAD-04]
depends_on: [ADAPTIVE_THREE_COLUMN_SHELL_ON_IPAD, VAULT_BROWSE_COLUMNS_WITH_NOTE_INSPECTOR, SIDE_BY_SIDE_ENTITY_CONFIRMATION_ON_IPAD, ANNOTATE_AND_PROMOTE_INTO_NOTES]
can_parallelize_with: []
---

# Prove iPad UAT Journeys

Target repo: **`RasmusTho/bifrost`** (Swift; hub repo holds only this spec).

## Purpose

MIPAD-01..04 each land journey-level tests for their own slice; this task proves the *capability*:
the composed journeys a human actually runs on the canvas, exercised end-to-end in CI, plus the
one deliberate human step — the operator's eyes-on walkthrough on a physical iPad under the
free-provisioning deploy posture. Mirrors B1's `PROVE_UAT_JOURNEYS_IN_SIMULATOR_AND_ON_DEVICE`.

## What This Task Does

- Consolidates/extends the slice tests into three composed iPad XCUITest journeys, one test each:
  1. **Browse-and-read:** pick vault → three columns → folder → note → inspector.
  2. **Entity decision:** entities source → compare → merge with explicit candidate → undo.
  3. **Curate:** annotate a note; drag an item onto a note; verify both blocks render.
- Ensures the fixture vault used by UI tests covers the states the journeys need (pending
  entities with 0/1/2 candidates, notes with and without uuid/provenance) — extending the fixture
  is in scope.
- Authors a scripted device walkthrough (checklist in the PR, mirroring the three journeys plus
  Pencil/Scribble which the simulator cannot prove) for the operator to run once on a physical
  iPad, installed per `docs/BIFROST/APP_DEPLOYMENT_POSTURE.md`; the operator posts the receipt as
  a comment on hub #3024.

## Concretely

`xcodebuild test -destination 'platform=iOS Simulator,name=iPad Pro 13-inch (M4)'` runs
`MimerCanvasJourneyTests` green in CI; hub #3024 carries a comment: "iPad walkthrough 2026-07-XX —
journeys 1–3 pass on device, Scribble annotation verified — <checklist copy>".

## Why This Matters

INV-B2-1 and the capability ACs are claims about composed behavior; slice tests alone let seams
rot invisibly (B1's own delivery deferred UAT and paid for it with a follow-up spec). The device
walkthrough is deliberately the ONLY human step in B2 — one interruption, scripted, receipted.

## Acceptance Criteria

- [ ] The three composed journeys run as XCUITests on the iPad destination in bifrost CI.
  `Verify:` bifrost
  `Yggdrasil/YggdrasilUITests/MimerCanvasJourneyTests.swift::{testBrowseAndReadJourney,testEntityDecisionJourney,testCurateJourney}`
  (new; green on the PR head).
- [ ] iPhone journeys (B1's XCUITest set) remain green on the same head — the canvas never
  regressed the phone. `Verify:` bifrost CI iPhone destination on the PR head.
- [ ] The scripted device walkthrough exists and the operator's receipt is posted on hub #3024.
  `Verify:` receipt comment on #3024 referencing this task and the walked build's SHA
  (non-behavioral; the ONE human step).

## How to Verify (Pre-Merge)

- bifrost CI green on both destinations. The device-walkthrough AC is post-merge by nature: the PR
  merges on the two behavioral ACs; the receipt AC holds the *task* (and MIPAD-06) open, not the PR.

## Out of Scope

- New canvas functionality — journeys exercise what MIPAD-01..04 shipped.
- Closing #3024 (MIPAD-06 owns closure once this task's receipt exists).
- TestFlight/any distribution change (posture is decided in `APP_DEPLOYMENT_POSTURE.md`).

## Related Docs

- `docs/BIFROST/APP_DEPLOYMENT_POSTURE.md` (how the walkthrough build reaches the iPad)
- `docs/YGGDRASIL_APP_SHELL_COMPLETION/PROVE_UAT_JOURNEYS_IN_SIMULATOR_AND_ON_DEVICE.md` (the B1 pattern this mirrors)
- `docs/MIMER_IPAD_THINKING_CANVAS/README.md`

## Related GitHub Issues

One implementation issue in `RasmusTho/bifrost` (`type:task`, `agent:blocked` on the MIPAD-01..04
issues), linking hub #3024 and this spec file. TCD hint: Sonnet / medium effort — XCUITest
composition over existing fixtures; the walkthrough checklist is writing, not engineering.
