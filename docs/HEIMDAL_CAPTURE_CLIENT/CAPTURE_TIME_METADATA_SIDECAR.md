---
name: Capture-Time Metadata Sidecar
description: A versioned sidecar file with capture-time context delivered alongside each recording (bifrost half), consumed by the hub capture adapter into raw-record/capture-note metadata (hub half).
task_id: HCAP-07
source_anchor: docs/HEIMDAL/CAPTURE_TRANSPORT_FEASIBILITY.md :: Metadata → Episode argument
parent_capability: Heimdal Capture Client
prerequisites: [HCAP-03]
depends_on: [DELIVER_RECORDINGS_TO_WATCHED_FOLDER]
can_parallelize_with: [DEVICE_HEALTH_PANEL_WITH_GAP_LOG, WATCH_ONE_TAP_RECORD_WITH_HAPTIC_STATUS]
---

# Capture-Time Metadata Sidecar

Target repos: **`RasmusTho/bifrost`** (producer) and **`RasmusTho/agentic-pkm-mvp`** (consumer) —
two issues, one contract, defined here once.

## Purpose

A raw voice memo carries almost no context (`clock_basis: device_metadata` — timestamp and
duration). The feasibility doc's episode argument: capture-time signals (device of origin, precise
session timing, timezone, optionally location/Focus state) map onto ADR-0051's Episode dimensions
and **can only be captured at capture time by a native app** — this is B3's value beyond friction.
Today no sidecar convention exists (NONE FOUND in the adapter); this task creates it, versioned
and optional-by-construction so the pipeline never depends on it.

## What This Task Does

**Contract (normative here until hub #3131's published-schema surface absorbs it):** for a
delivered `foo.m4a`, an optional sibling `foo.m4a.capture.json`:

```json
{
  "sidecar_version": 1,
  "device_id": "<HCAP-04 device_id>",
  "recorded_start_at": "2026-07-07T14:02:11+02:00",
  "recorded_end_at": "2026-07-07T14:09:40+02:00",
  "timezone": "Europe/Stockholm",
  "interruptions": 1,
  "source_surface": "iphone-app | watch-relay",
  "location": {"lat": 0.0, "lon": 0.0, "precision_m": 100}
}
```

`location` present only when the operator has enabled it in the Heimdal client (off by default;
mic-only permission posture stays the default). Unknown fields are ignored by the consumer;
missing sidecar means v1 behavior exactly as today.

- **Bifrost half:** assemble the sidecar from the session state machine (start/end/interruptions,
  source surface incl. watch relay), write it into the watched folder AFTER the audio's final
  rename, with the same temp-then-rename discipline (final name matches the audio + `.capture.json`).
- **Hub half:** `capture_adapter` looks for the sidecar when admitting audio; validates
  `sidecar_version`; threads the fields into the raw record's metadata and (when the note stage
  runs) into the capture note's frontmatter; deletes the sidecar with the same
  delete-after-confirmed-write custody as the audio. Malformed sidecar → log + proceed without it
  (never blocks audio admission).

## Concretely

Deliver `heimdal-abc-...m4a` + its `.capture.json` into the test-channel watch dir → raw store
row's metadata carries `device_id`/`recorded_start_at`/…; adapter log shows `sidecar: consumed`.
Deliver audio alone → admission identical to today, log `sidecar: absent`.

## Why This Matters

This is the seam that lets Episode resolution (ADR-0051, ERE lane #3175–#3184) anchor capture
artifacts to lived situations — boundary proposals need real session timing, and "which device
captured this" is provenance the raw record cannot reconstruct later. Doing it as an optional
sidecar keeps the pipeline honest: no coupling, no flag-day.

## Acceptance Criteria

- [ ] (bifrost) Sidecar is written after the audio's final rename, same completeness discipline,
  fields sourced from the real session. `Verify:` bifrost
  `Yggdrasil/YggdrasilTests/CaptureSidecarTests.swift::testSidecarWrittenAfterAudioWithSessionFields`
  (new).
- [ ] (bifrost) Location absent unless explicitly enabled. `Verify:` bifrost
  `CaptureSidecarTests.swift::testLocationOmittedByDefault` (new).
- [ ] (hub) Adapter consumes a valid sidecar into raw-record metadata and deletes it with
  audio-custody discipline. `Verify:` hub
  `tests/heimdal/test_capture_adapter.py::test_sidecar_consumed_into_raw_metadata` (new).
- [ ] (hub) Missing or malformed sidecar never affects audio admission (enforcement AC on the
  admission path). `Verify:` hub
  `tests/heimdal/test_capture_adapter.py::test_admission_unaffected_by_missing_or_malformed_sidecar`
  (new).
- [ ] (hub) Sidecar files themselves are never admitted as capture audio. `Verify:` hub
  `tests/heimdal/test_capture_adapter.py::test_sidecar_extension_not_admissible` (new — `.json`
  is already outside the allowlist; the test pins it).

## How to Verify (Pre-Merge)

- bifrost CI green; hub `pytest -m "not pg"` green including the three named tests (hub half also
  runs the full not-pg suite — capture adapter is hot-path).

## Out of Scope

- Episode-boundary computation or `episode_ref` assignment (ERE lane owns resolution; this task
  only delivers the raw signals).
- Focus-state/motion signals (future sidecar_version bump).
- Any change to admission rules for audio itself.

## Related Docs

- `docs/HEIMDAL_CAPTURE_CLIENT/README.md`
- `docs/adr/ADR-0051-*` (Episode primitive), `docs/EPISODE_RESOLUTION_ENGINE/` (consumer lane)
- Hub: `app/heimdal/capture_adapter.py`, `app/heimdal/raw_store.py`

## Related GitHub Issues

Two implementation issues: `RasmusTho/bifrost` (`type:task`, `agent:blocked` on HCAP-03) and
`RasmusTho/agentic-pkm-mvp` (`type:task`, `agent:ready` — the hub half has no client dependency:
it can land first and wait for real sidecars). Both link hub #3026 and this spec file. TCD hint:
Sonnet / medium effort each — a small, crisply-contracted seam on both sides.
