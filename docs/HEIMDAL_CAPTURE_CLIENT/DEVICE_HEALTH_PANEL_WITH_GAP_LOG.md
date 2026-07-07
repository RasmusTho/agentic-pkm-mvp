---
name: Device Health Panel With Gap Log
description: JD — live device telemetry panel (the ADR-0049 declared UI-only bend) plus the durable half — capture-gap log entries and last-known snapshot written to the device note.
task_id: HCAP-05
source_anchor: docs/adr/ADR-0049-heimdall-ingestion-organ-and-v1-uiux-enactment.md :: §2 (declared bends)
parent_capability: Heimdal Capture Client
prerequisites: [HCAP-02, HCAP-04]
depends_on: [DISCRETE_RECORD_WITH_BACKGROUND_AUDIO, DEVICE_REGISTRATION_AND_CONSENT_SURFACE]
can_parallelize_with: [WATCH_ONE_TAP_RECORD_WITH_HAPTIC_STATUS]
---

# Device Health Panel With Gap Log

Target repo: **`RasmusTho/bifrost`** (Swift; hub repo holds only this spec).
**Vault-write gate applies** (gap-log/snapshot writes): hub #3129/#3131/#3132 and bifrost#4/#5 all
merged (README :: Gates — same gate as B2's write-bearing slices).

## Purpose

JD answers "is my capture device healthy, and did I miss anything?" ADR-0049 §2 sanctions exactly
one UI-only bend for this: **live telemetry (battery/signal/buffer) is runtime data, not an
artifact of record** — while the durable part (capture-gap log, last-known snapshot) belongs in
the device note. This task ships both halves and keeps the line between them crisp.

## What This Task Does

- **Live panel (UI-only bend, nothing persisted):** recording/session state (from the HCAP-01
  state machine), delivery-queue depth and oldest-pending age (HCAP-03), battery level/state,
  storage headroom for staging, mic-permission state. No new persistence, no new note fields —
  ADR-0049 declares any *other* UI-only capability a `break` needing an owner decision, so the
  panel renders only from existing runtime state.
- **Capture-gap log (durable):** appends an entry to the device note's agent-authored
  `capture_gap_log` when the client can name a gap: a session that ended by interruption and was
  not resumed, a recording finalized by abandonment, a delivery that failed and aged past a
  threshold. Entries `{at, kind, detail}`, append-only via the coordinated seam,
  provenance-tagged (INV-B3-4's one allowed vault artifact).
- **Last-known snapshot (durable):** on entering background (and at most every N minutes while
  active), update `last_known_snapshot` `{at, battery, queue_depth, recording}` in the device
  note — coarse, low-churn (skip if unchanged), never on a tight timer.

## Concretely

Simulator: start recording → JD shows session live + queue 0; simulate an interruption abandoned →
device note gains one `capture_gap_log` entry `{kind: interrupted_not_resumed}`; background the
app → `last_known_snapshot` updates once. The panel itself persists nothing.

## Why This Matters

The wearable study's trust killer was silent capture gaps. The JD panel makes the live state
glanceable, and the gap log makes misses durable, in the vault, where Mimer-side surfaces (and the
human in Obsidian) can see them — not in an app-only store that dies with the app.

## Acceptance Criteria

- [ ] The live panel renders exclusively from existing runtime state — the slice adds no
  persistence for telemetry (enforcement of the declared bend's boundary). `Verify:` bifrost
  `Yggdrasil/YggdrasilTests/DeviceHealthModelTests.swift::testLivePanelHasNoPersistenceSideEffects`
  (new; model-level, asserts no store/file writes on telemetry updates).
- [ ] Nameable gaps append exactly one `capture_gap_log` entry each, append-only, provenance
  intact. `Verify:` bifrost
  `DeviceHealthModelTests.swift::testGapEventsAppendToDeviceNoteOnce` (new; temp vault).
- [ ] `last_known_snapshot` updates on backgrounding, is skipped when unchanged, and never
  rewrites other note fields. `Verify:` bifrost
  `DeviceHealthModelTests.swift::testSnapshotUpdateIsFieldScopedAndChangeGated` (new).

## How to Verify (Pre-Merge)

- bifrost CI green; `swiftlint --strict` clean. Gate check in the PR body: bifrost#4/#5 merged.

## Out of Scope

- Any new telemetry event schema or hub consumption of live values (none exists by design —
  NONE FOUND is the correct state, per ADR-0049's bend).
- Watch-side health display (the Watch shows capture status only, HCAP-06).
- Alerting/notifications (a future capability; would need its own decision).

## Restart / Durability Posture

The live panel is ephemeral by declaration (the sanctioned bend): kill the app, the panel state is
gone and that is correct. The durable truths (gaps, last snapshot) are in the device note and
survive anything the app does. The user consequence of a crash is at most one missing snapshot
update, never a lost gap entry for an already-detected gap (entries are written at detection
time, not batched in memory).

## Related Docs

- `docs/HEIMDAL_CAPTURE_CLIENT/README.md` (INV-B3-4; Gates)
- `docs/adr/ADR-0049-heimdall-ingestion-organ-and-v1-uiux-enactment.md` §2
- Hub: `app/heimdal/settings_notes.py` (device-note agent-authored fields)

## Related GitHub Issues

One implementation issue in `RasmusTho/bifrost` (`type:task`, `agent:blocked` — gate list: HCAP-02
+ HCAP-04 issues + hub #3129/#3131/#3132 + bifrost#4/#5), linking hub #3026 and this spec file. TCD hint: Sonnet / medium
effort — the discipline (what persists vs what doesn't) is fully specified; implementation is
routine.
