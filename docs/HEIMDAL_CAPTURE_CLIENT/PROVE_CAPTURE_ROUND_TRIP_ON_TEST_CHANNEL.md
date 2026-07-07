---
name: Prove Capture Round Trip On Test Channel
description: Real-runtime receipt — an app-delivered recording lands in the test channel's raw store with receipts; drive the downstream stages explicitly; record the EXP-1 phoneless-latency observation.
task_id: HCAP-08
source_anchor: docs/HEIMDAL_CAPTURE_CLIENT/README.md :: Capability acceptance criteria
parent_capability: Heimdal Capture Client
prerequisites: [HCAP-03, HCAP-04]
depends_on: [DELIVER_RECORDINGS_TO_WATCHED_FOLDER, DEVICE_REGISTRATION_AND_CONSENT_SURFACE]
can_parallelize_with: [PROVE_CAPTURE_UAT_JOURNEYS]
---

# Prove Capture Round Trip On Test Channel

Target repo: **`RasmusTho/agentic-pkm-mvp`** (hub — runbook + receipt work on the test channel;
mirrors B1's `VERIFY_CONTROL_SURFACE_ROUND_TRIP_ON_TEST_CHANNEL`).

## Purpose

Simulator tests prove the client's half; only the real runtime proves the system: a recording made
in the app must become an admitted, encrypted raw record on the mac mini's test channel with its
receipts intact. This task also carries the feasibility doc's **EXP-1** (no-code experiment):
measure the phoneless Watch → iCloud → admission latency to decide whether Model 2 streaming is
ever worth building.

## What This Task Does

- Configure the test channel's `HEIMDAL_CAPTURE_WATCH_DIR` (and required env:
  `HEIMDAL_RAW_STORE_KEY`, retention setting) per `docs/ENVIRONMENTS.md`; bind the app (operator
  device, installed per `APP_DEPLOYMENT_POSTURE.md`) to that folder.
- Drive the real path: record on the phone → delivery → iCloud sync → `capture-watch` tick admits
  it. Verify: raw-store row exists (content hash matches the delivered file), `RawEvidenceReceipt`
  present, source file deleted from the watch dir, stability guard respected (no partial
  admission), duplicate re-delivery is idempotent.
- **Named honestly:** on `main` today only raw admission runs unattended; ASR → capture note →
  attribution → publish have no orchestrator. Drive those stages **explicitly** (CLI/REPL) for one
  memo and record what ran manually vs unattended — the receipt must not imply an end-to-end
  automatic pipeline that does not exist. (The missing orchestrator is a pre-existing hub gap
  tracked outside this spec — reference it in the receipt.)
- **EXP-1:** with the iPhone in airplane mode and the (cellular) Watch on stock Voice Memos —
  the shipped floor — record N memos across a day; measure time-to-materialize in the watch dir
  and admission failure rate. Record the observation and the Model-2 go/no-go recommendation.
- Post the assembled receipt as a comment on #3026.

## Concretely

`#3026` gains a comment: "Round-trip receipt (test channel, SHA …): memo `sha256:…` recorded
14:02, admitted 14:07 (tick interval 30s), RawEvidenceReceipt id …, source deleted, re-delivery
no-op. Stages driven manually: asr_stage → transcript segments OK, capture note written. EXP-1:
n=6 phoneless memos, median materialize 4m, p95 11m, 0 failures — Model 2 not warranted."

## Why This Matters

B1's round-trip task exists because control-surface writes needed runtime proof; capture is even
less forgiving — it ends in an *encrypted* store where "looks fine" is unverifiable without
receipts. And EXP-1 is the cheap experiment that prevents building a streaming transport nobody
needs.

## Acceptance Criteria

- [ ] A real app-recorded memo is admitted on the test channel: raw record + `RawEvidenceReceipt`
  + source-file deletion + idempotent re-delivery, all evidenced. `Verify:` receipt comment on
  #3026 with the raw-record/receipt identifiers (non-behavioral; runtime receipt).
- [ ] Downstream stages driven for one memo with an explicit manual-vs-unattended ledger.
  `Verify:` same receipt comment, stages section.
- [ ] EXP-1 observation recorded with a Model-2 recommendation. `Verify:` same receipt comment,
  EXP-1 section.

## How to Verify (Pre-Merge)

This task is runbook + receipt, not a code PR (any test-channel config changes ride the standard
promote-to-test flow). "Pre-merge" here means: the receipt exists on #3026 before HCAP-10 may
close anything.

## Out of Scope

- Building the missing stage orchestrator (pre-existing hub gap, its own backlog item).
- Sidecar verification (HCAP-07's hub tests own that; if HCAP-07 landed, the receipt notes sidecar
  consumption as a bonus line).
- Prod-channel anything.

## Related Docs

- `docs/YGGDRASIL_APP_SHELL_COMPLETION/VERIFY_CONTROL_SURFACE_ROUND_TRIP_ON_TEST_CHANNEL.md` (the pattern)
- `docs/ENVIRONMENTS.md`, `docs/RELEASE_CHANNELS/DEFINE_CHANNEL_IDENTITY.md`
- Hub: `app/heimdal/{capture_adapter,capture_runtime,raw_store}.py`, `app/cli/heimdal.py`

## Related GitHub Issues

One implementation issue in `RasmusTho/agentic-pkm-mvp` (`type:task`, `agent:blocked` on the
HCAP-03/HCAP-04 issues; requires operator cooperation for the device/EXP-1 windows — the runbook
is agent-authored, the phone/watch handling is the operator's). Links #3026 and this spec file.
TCD hint: Sonnet / medium effort — runbook precision and receipt honesty, not engineering.
