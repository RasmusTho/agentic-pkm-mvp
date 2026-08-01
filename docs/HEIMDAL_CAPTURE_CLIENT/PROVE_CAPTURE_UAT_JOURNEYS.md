---
name: Prove Capture UAT Journeys
description: The B3 capture journeys run as XCUITests in bifrost CI, plus the operator's scripted device walkthrough — background capture, interruptions, Watch haptics — receipted on #3026.
task_id: HCAP-09
github_issue: "https://github.com/RasmusTho/bifrost/issues/21"
source_anchor: docs/HEIMDAL_CAPTURE_CLIENT/README.md :: Capability acceptance criteria
parent_capability: Heimdal Capture Client
prerequisites: [HCAP-02, HCAP-03, HCAP-04, HCAP-05, HCAP-06]
depends_on: [DISCRETE_RECORD_WITH_BACKGROUND_AUDIO, DELIVER_RECORDINGS_TO_WATCHED_FOLDER, DEVICE_REGISTRATION_AND_CONSENT_SURFACE, DEVICE_HEALTH_PANEL_WITH_GAP_LOG, WATCH_ONE_TAP_RECORD_WITH_HAPTIC_STATUS]
can_parallelize_with: [PROVE_CAPTURE_ROUND_TRIP_ON_TEST_CHANNEL]
---

# Prove Capture UAT Journeys

State: Agent-verifiable scope delivered by Bifrost PR #56 on 2026-07-30 (merge commit
`364a283d84dd2c3d2e274b4aaedcff18a96f82af`). Bifrost #21 remains open with
`agent:needs-human` only for the physical-device walkthrough receipt on hub #3026.

Target repo: **`RasmusTho/bifrost`** (Swift; hub repo holds only this spec).

## Purpose

Slice tests prove parts; this proves the composed journeys a human runs — and scripts the one set
of truths only a physical device can prove (real background audio under lock, real interruptions
by real calls, real wrist haptics). Mirrors B1's UAT task; the device walkthrough is B3's
deliberate human step.

## What This Task Does

- Three composed XCUITest journeys (iPhone destination; fixture capture folder + vault):
  1. **Capture:** bind folder → record → background/foreground → stop → staged → delivered.
  2. **Identity & health:** register device → JC shows grant + registered → force a nameable gap
     → JD panel + gap-log entry.
  3. **Recovery:** fail delivery (unbound folder) → visible failed state → rebind → retry
     succeeds; relaunch mid-queue → queue rebuilt from disk.
- Watch journey automated as far as paired simulators allow (record → relay reaches phone
  staging); what cannot be automated is explicitly in the walkthrough instead.
- Scripted device walkthrough (checklist in the PR): pocket-recording with screen locked ≥10
  minutes; a real incoming call mid-recording (pause haptic on Watch, resume behavior);
  Watch one-tap capture end-to-end; JD panel sanity. Operator posts the receipt on #3026, build
  SHA included, installed per `APP_DEPLOYMENT_POSTURE.md`.

## Concretely

CI on the PR head runs `HeimdalCaptureJourneyTests` green on iPhone destination + watch build;
#3026 later carries: "Device walkthrough 2026-07-XX — journeys pass, 10-min locked capture OK,
call-interruption haptic felt, Watch relay OK — <checklist>".

## Why This Matters

Every capture guarantee in this spec is a trust promise about *hostile conditions* (lock screens,
calls, dead phones). Only the composed journeys + one honest device pass make those promises
receipts instead of claims.

## Acceptance Criteria

- [x] The three recomposed journeys run green as XCUITests in bifrost CI.
  - Verify: `Yggdrasil/YggdrasilUITests/HeimdalCaptureJourneyTests.swift::{testCaptureAndDurableCustodyJourney,testIdentityHealthAndQueueJourney,testRecoveryAndDiskRebuiltTruthJourney}`
- [x] Existing B1/B2 journeys stay green on the same reviewed head across both configured
  destinations.
  - Verify: runtime receipt: bifrost.capture_uat.pr56_full_suite.v1
- [ ] The scripted device walkthrough exists and the operator's receipt is posted on #3026.
  - Verify: runtime receipt: heimdal.capture_uat.physical_device_walkthrough.v1

## How to Verify (Pre-Merge)

- bifrost CI green. The walkthrough receipt is post-merge by nature — it holds the task and
  HCAP-10 open, not this PR.

## Out of Scope

- New capture functionality. Test-channel verification (HCAP-08). Closure (HCAP-10).

## Related Docs

- `docs/BIFROST/APP_DEPLOYMENT_POSTURE.md`
- `docs/YGGDRASIL_APP_SHELL_COMPLETION/PROVE_UAT_JOURNEYS_IN_SIMULATOR_AND_ON_DEVICE.md` (pattern)
- `docs/HEIMDAL_CAPTURE_CLIENT/README.md`

## Related GitHub Issues

Bifrost #21 is not an implementation pickup: PR #56 delivered the agent-verifiable journey work,
and `agent:needs-human` now truthfully marks the one remaining operator walkthrough receipt on hub
#3026.
