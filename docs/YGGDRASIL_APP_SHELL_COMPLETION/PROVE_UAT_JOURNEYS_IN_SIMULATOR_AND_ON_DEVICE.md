---
name: Prove UAT Journeys In Simulator And On Device
description: Mechanize B1's deferred UAT — the acceptance journeys become XCUITests running in bifrost CI's simulator, plus a scripted eyes-on device walkthrough whose receipt lands on hub #3023.
task_id: YGGSHELL-04
source_anchor: docs/BIFROST/APP_TOPOLOGY_AND_PLATFORMS.md :: §1
parent_capability: Yggdrasil App Shell Completion
prerequisites: [YGGSHELL-01, YGGSHELL-02, YGGSHELL-03]
depends_on: [ALIGN_VAULT_WRITES_TO_COORDINATED_FILE_ACCESS.md, TAG_WRITER_PROVENANCE_AND_CITE_DECIDED_CONSISTENCY_MODEL.md, FIX_FIRST_DELIVERY_REVIEW_FOLLOWUPS.md]
can_parallelize_with: [VERIFY_CONTROL_SURFACE_ROUND_TRIP_ON_TEST_CHANNEL]
---

# Prove UAT Journeys In Simulator And On Device

Target repo: **`RasmusTho/bifrost`** (Swift; hub repo holds only this spec; the receipt lands on hub
#3023).

## Purpose

B1's delivery explicitly deferred the manual on-device/simulator UAT ("still owed as a follow-up" —
the authoring environment had no `Xcode.app`). #3023's third acceptance criterion is exactly this
walkthrough. Bifrost CI runs on `macos-14` with a real Xcode and simulator, so most of the UAT can
be mechanized as XCUITest journeys that then guard every future PR — leaving only a short eyes-on
device pass as the genuinely human step.

## What This Task Does

- **Extends `Yggdrasil/YggdrasilUITests`** (currently 1 UI test) with journey tests mirroring the B1
  acceptance surface, against a fixture vault injected via launch arguments (bypassing the system
  document picker and biometric prompt in test mode — test-only seams, clearly marked, never
  compiled into release behavior):
  1. Launch → auth gate appears before any vault content.
  2. Vault selection is a visual pick: the vault-selection flow contains **no text-input field**
     (dyslexia-safe rule: never require typing or pasting a path).
  3. With the fixture vault open: browse to a `_heimdal/**` note, render it, edit it, save; the
     file content changes on disk.
  4. Each of the five lenses (Attention, Interests, Entity confirmation, Consent, Settings) loads
     its fixture note without error; Consent is read-only.
- **Authors a scripted walkthrough** (`docs/UAT_B1_WALKTHROUGH.md` in the bifrost repo): numbered
  steps + expected observations for the same journeys on a physical iPhone with a real iCloud vault,
  written so the operator can run it in ~10 minutes without typing any path (selection is always a
  visual pick).
- **Collects the receipt:** the operator's walkthrough outcome (pass/fail per step, device, app
  build SHA) is posted as a comment on hub #3023. The implementing agent prepares everything,
  requests the walkthrough once, and records the result — one human interruption total.

## Concretely

```bash
# In RasmusTho/bifrost — CI already does this; the journey tests join the run:
xcodebuild test -scheme Yggdrasil -destination 'platform=iOS Simulator,name=iPhone 15'
```

Receipt shape on #3023: "UAT walkthrough receipt — device: iPhone <model>, build: <sha>, steps
1–N: pass/fail, notes: …".

## Why This Matters

CI's `xcodebuild test` proved the code compiles and units pass; nobody has yet watched the shell do
its job. A UAT gap on the *daily-driver surface* is precisely where "closed-on-green rots the test
layer": the missing `NavigationStack` that made vault navigation a no-op was caught only by review —
journey tests make that class of defect mechanically visible from now on.

## Acceptance Criteria

- [ ] XCUITest journeys cover: auth gate first, visual-pick-only vault selection (no text input in
  the flow), `_heimdal/**` note render + edit round-trip, and all five lenses loading (Consent
  read-only). `Verify:` bifrost
  `Yggdrasil/YggdrasilUITests/YggdrasilUITests.swift::testAuthGatePrecedesVaultContent`,
  `::testVaultSelectionHasNoTextInput`, `::testHeimdalNoteRenderEditRoundTrip`,
  `::testAllFiveLensesLoadFixtureNotes` (new; green in bifrost CI).
- [ ] Test-only seams (fixture vault via launch args, auth bypass) are inert outside UI-test runs.
  `Verify:` bifrost unit/UI test asserting the seam is gated on the launch argument, e.g.
  `Yggdrasil/YggdrasilTests/TestSeamGatingTests.swift::testFixtureVaultSeamRequiresLaunchArgument` (new).
- [ ] The scripted device walkthrough exists in the bifrost repo and requires no path typing at any
  step. `Verify:` doc writeback at bifrost `docs/UAT_B1_WALKTHROUGH.md` (steps + expected
  observations; grep finds no "type the path"-class instruction).
- [ ] The operator's eyes-on walkthrough receipt is posted on hub #3023 (device, build SHA, per-step
  outcome). `Verify:` runtime receipt — comment on `RasmusTho/agentic-pkm-mvp#3023`.

## How to Verify (Pre-Merge)

- bifrost CI green with the new journey tests in the simulator run.
- Walkthrough doc present in the PR; the operator receipt AC completes post-merge on #3023 (it is
  the one deliberately human step; the issue is done when the receipt exists, and the closure task
  RECONCILE_AND_CLOSE_B1_TRACKING gates on it — see spec INV-B1C-4 for the stall path).

## Out of Scope

- iPad layouts and side-by-side entity confirmation (B2 #3024).
- Capture/Watch journeys (B3 #3026).
- Performance/battery profiling — not a B1 acceptance surface.

## Related Docs

- `docs/BIFROST/APP_TOPOLOGY_AND_PLATFORMS.md` §1 (topology C — the surface verified), §3 (shell
  shares auth/vault-pick/renderer/design system)
- Hub #3023 Acceptance Criteria (visual vault pick; `_heimdal/**` read/write; A14–A19 lenses)
- bifrost: `Yggdrasil/YggdrasilUITests/`, `.github/workflows/ci.yml`

## Related GitHub Issues

One implementation issue in `RasmusTho/bifrost` (`type:task`, `agent:blocked` until YGGSHELL-01..03
merge, then `agent:ready`), linking hub #3023. TCD hint: Sonnet / high effort — UI-test injection
seams and simulator flakiness need real design care; the walkthrough doc itself is cheap.
