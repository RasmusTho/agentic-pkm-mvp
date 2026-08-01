---
name: Prove Cross-Device Round Trip With Reconnect
description: Test-channel proof of the composed vertical — multi-modality round trip with kill/restart and disconnect/reconnect chaos steps, duplicate-free idempotency evidence, and receipts on the parent issue.
task_id: CDLM-10
github_issue: "https://github.com/RasmusTho/agentic-pkm-mvp/issues/4389"
source_anchor: docs/CROSS_DEVICE_CAPTURE_AND_LIVE_MEETING/README.md :: Capability acceptance criteria
parent_capability: Cross-Device Capture & Live Meeting
prerequisites: [CDLM-04, CDLM-05, CDLM-08, CDLM-09]
depends_on: [CAPTURE_PHOTOS_DOCUMENTS_AND_VIDEO.md, SHOW_DURABLE_TRANSFER_QUEUE_ON_IPAD.md, CONSOLIDATE_MEETING_ON_END.md, RUN_LIVE_MEETING_ON_IPAD.md]
can_parallelize_with: []
---

# Prove Cross-Device Round Trip With Reconnect

State: Delivered by hub issue #4389 / PR #4433 on 2026-07-30 (merge commit
`c1164516785c3e3263bbadae6cdfc57786f2ec3b`). Test-channel run `cdlm10-868e042e59` is the
terminal composed receipt on parent #4383; physical-device-only truth remains Bifrost #21.

## Purpose

Replace "each slice's tests passed" with one composed, real-runtime receipt: the vertical's
promises hold on the test channel, under the failure conditions they were designed for, with
evidence a cold reader can audit on the parent issue.

## What This Task Does

Scripts and executes a receipted proof run against the test channel (per
`docs/RELEASE_CHANNELS/DEFINE_CHANNEL_IDENTITY.md`), driven from the app in the simulator plus
hub-side verification commands. Stages, each producing named evidence:

1. **Multi-modality round trip.** One audio memo, one photo, one two-page receipt scan, one short
   video from iPhone and iPad simulators → all four reach `backend durably received` then
   `complete`; hub-side raw store and receipts enumerate exactly four objects with matching
   hashes.
2. **Kill/restart chaos.** Force-quit during transfer and relaunch (per CDLM-03's states);
   restart the hub's API between admissions; verify no lost original, no duplicate admission, no
   fabricated queue state. Evidence: receipt query outputs + raw-store object count before/after.
3. **Duplicate-injection.** Deliberately resend admitted items (script-driven double-POST):
   raw-store count, ledger rows, and derived segments remain singular; receipts return
   `idempotent_replay`.
4. **Live meeting with reconnect.** A scripted session (fixture audio segments): live projection
   grows; forced network drop over ≥2 segments; reconnect resends exactly the ledger-missing
   sequences; projections reconcile as a new revision; user notes written throughout survive
   verbatim (hash-compared against the block registry and the final artifact).
5. **Gapped close + late reconcile.** Close with a withheld segment → `needs_attention` receipt
   naming it; late-admit → re-finalization with lineage; final artifacts verified for the
   three-way separation (transcript / final analysis / verbatim user notes).
6. **Legacy-lane statement.** One watched-folder file admitted for contrast, its receipt queried,
   and the report stating plainly which guarantees apply to which lane.

The run report (commands, outputs, counts, hashes, channel identity, build SHAs for both repos)
posts as the CDLM-10 validation receipt on the parent feature issue. Stages that require the
operator's eyes (device-not-simulator behavior) are explicitly listed as not covered here — they
remain bifrost#21's walkthrough scope, unblocked after this task.

## Concretely

```bash
# hub-side verification snippets the script wraps:
curl -s 'http://test-hub/api/heimdal/capture/receipts?capture_id=…'   # per-item receipts
psql "$TEST_DSN" -c 'select session_id, count(*) from meeting_segment group by 1;'
python -m app.cli raw-store-verify --channel test --expect-count 4     # or the existing raw-store audit entrypoint
```

## Why This Matters

Every prior loss this vertical answers (#4369's vanished recordings, #4362's false-green watcher)
was invisible precisely because no composed proof existed — slice tests passed while the system
lost data. This receipt is the difference between "the contract is written" and "the contract is
demonstrated", and it is the parent issue's closure evidence.

## Acceptance Criteria

- [ ] The proof script exists in the hub repo, is re-runnable against the test channel, and covers
  stages 1–6 with named evidence outputs.
  - Verify: `tests/heimdal/test_cdlm_roundtrip_script.py::test_script_stages_and_evidence_contract`
    (script structure + stage contract; the live run itself is the receipt below).
- [ ] A complete run's report is posted on the parent feature issue, including channel identity,
  both build SHAs, per-stage evidence, and the duplicate-injection counts.
  - Verify: receipt comment on the parent feature issue referencing this task id (non-behavioral;
    the run receipt).
- [ ] The run demonstrates zero lost originals, zero duplicates, gap legibility, and user-note
  verbatim survival — each as an explicit checked line in the report with its evidence.
  - Verify: the same parent-issue receipt's per-stage checklist (non-behavioral; auditable
    outputs inline).
- [ ] Simulator-only limits are stated, and bifrost#21's walkthrough is explicitly named as the
  remaining human step (unblocking it).
  - Verify: doc writeback at `docs/CROSS_DEVICE_CAPTURE_AND_LIVE_MEETING/README.md :: Supersessions (explicit)`
    (bifrost#21 row updated) plus the parent-issue receipt.

## How to Verify (Pre-Merge)

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/heimdal/test_cdlm_roundtrip_script.py` for the
  script-contract AC; the live-run receipt is post-merge by nature and holds this task's issue
  open until posted (same pattern as HCAP-08).
- Test-channel runs take the host lease per `AGENTS.md :: Parallel-agent execution` when they touch
  host-global resources.

## Out of Scope

- Physical-device truths (bifrost#21's walkthrough: locked-screen capture, real calls, wrist
  haptics).
- Performance/latency benchmarking beyond recording observed segment→projection latency in the
  report (informative, not gating).
- Prod-channel anything (test channel only; promotion follows the release-channel workflows).

## Related Docs

- `docs/CROSS_DEVICE_CAPTURE_AND_LIVE_MEETING/README.md` (capability acceptance criteria this proves)
- `docs/RELEASE_CHANNELS/DEFINE_CHANNEL_IDENTITY.md` (channel identity for the run)
- `docs/HEIMDAL_CAPTURE_CLIENT/PROVE_CAPTURE_ROUND_TRIP_ON_TEST_CHANNEL.md` (HCAP-08 precedent this extends)

## Related GitHub Issues

One hub issue implements this task ("Implements CROSS_DEVICE_CAPTURE_AND_LIVE_MEETING/PROVE_CROSS_DEVICE_ROUND_TRIP_WITH_RECONNECT").
It carries the parent-closure handoff: when its receipt lands and all prior children are
delivered, the parent's acceptance checklist is resolvable. TCD hint: Sonnet / high — composition
and evidence discipline over already-delivered mechanisms.
