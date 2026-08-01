---
name: Project Live Transcript And Default Analysis
description: Hub-side per-segment ASR into a revisable transcript projection plus a generic-default-template analysis projection with revision and derivation provenance.
task_id: CDLM-06
source_anchor: docs/CROSS_DEVICE_CAPTURE_AND_LIVE_MEETING/README.md :: Fixed scope
parent_capability: Cross-Device Capture & Live Meeting
prerequisites: [CDLM-02]
depends_on: [TRACK_MEETING_SESSIONS_AND_SEGMENT_GAPS.md]
can_parallelize_with: [CAPTURE_PHOTOS_DOCUMENTS_AND_VIDEO.md, SHOW_DURABLE_TRANSFER_QUEUE_ON_IPAD.md]
---

# Project Live Transcript And Default Analysis

State: Delivered by hub issue #4386 (2026-07-30). `GET /api/heimdal/meeting/{session_id}/projection`
is implemented in `app/api/routes/heimdal_meeting.py` over `app/heimdal/meeting_projection.py`, with
per-segment ASR triggered from the production admission path (`app/heimdal/media_ingress.py`)
through the shared engine seam `app.media.transcribe.run_asr`, and the six acceptance criteria below
proven by `tests/heimdal/test_meeting_projection.py`. Projection tables ship in migration
`b8d3f0a5c2e4` (Postgres/PDM) with a file-backed SQLite dev/test lane. The analysis engine in this
slice is deterministic (`heimdal-meeting-analysis v1`, no LLM), so convergence is structural;
`generic-default@1` is the only shipped template. The `HEIMDAL_RAW_STORE_KEY` provisioning gap is
closed in code (#4422); the residual operator Keychain step bounds live end-to-end derivation the
same way it bounds admission — see `docs/STATUS.md :: Runtime verification`.

## Purpose

Turn durably admitted meeting segments into what the iPad shows live: a running transcript and a
provisional analysis — both explicitly revisable projections, never canonical truth
(INV-CDLM-5).

## What This Task Does

- **Per-segment derivation.** Admission of a session segment (CDLM-02 ledger row) triggers ASR
  through the existing shared engine seam (`app.media.transcribe.run_asr` — the one-Whisper rule,
  ADR-0049 §3; no second ASR identity). Each segment derives exactly once per content hash;
  idempotent replays and hub restarts do not re-derive (INV-CDLM-3).
- **Transcript projection.** Ordered by `session_seq`, stored as durable, rebuildable projection
  state (PDM) with per-segment text, timing, and confidence. Gaps in the ledger render as explicit
  gap markers, never elided (INV-CDLM-9). Third-party speech handling follows ADR-0060's default
  withheld posture; **no speaker naming of any kind** in this slice (INV-CDLM-8) — segments carry
  device/source provenance, not person attribution.
- **Analysis projection under the generic default template.** After each newly derived segment (or
  batch), the analysis engine re-derives: summary, themes, provisional decisions, open questions,
  action candidates — each emitted as `derived_projection` blocks (CDLM-07's model) with
  `{revision, derived_from: [segment seqs/hashes], template_id: "generic-default@1", engine
  provenance}`. Re-derivation over the same admitted segment set is convergent: same inputs, same
  blocks.
- **Template selection seam.** The session's template resolves with fixed precedence: explicit
  user selection → explicitly permitted metadata mapping (only when such a permission flag exists
  on the session; none ships in this slice) → generic default. The seam exists and is tested; the
  only shipped template is `generic-default@1`. Rich templates and any participant/owner
  inference are later work and structurally out of scope here.
- **Projection read API.** `GET /api/heimdal/meeting/{session_id}/projection` returns transcript
  and analysis blocks with revisions, derivation provenance, gap markers, and the session's
  completeness state — the iPad's poll target (CDLM-09). Reads are cheap and side-effect-free.
- **Late-segment reconciliation.** The CDLM-02 late-admitted event re-derives affected
  projections as a new revision; prior revisions remain addressable in the projection state until
  finalization (bounded retention, config-capped).

## Concretely

Admit segments 0–3 of `mtg-42` on the test channel → `GET …/projection` shows four transcript
entries and analysis revision N derived_from [0..3]; withhold segment 2 → transcript shows a gap
marker at 2 and analysis provenance excludes it; late-admit 2 → revision N+1 includes it;
re-admit segment 1 (idempotent replay) → no new revision, no re-derivation.

## Why This Matters

This is the "live" in live meeting capture — and the honesty seam of the whole meeting surface. If
derivation is not idempotent, reconnect double-counts content; if provenance is missing, the iPad
cannot label provisionality truthfully; if gaps elide, the user reads a confident summary over
missing audio and INV-CDLM-9 dies at the source.

## Acceptance Criteria

- [ ] Each admitted segment derives exactly once per content hash across idempotent replays and a
  simulated hub restart, asserted through the production trigger path.
  - Verify: `tests/heimdal/test_meeting_projection.py::test_segment_derives_exactly_once`
- [ ] The transcript projection orders by sequence, marks ledger gaps explicitly, and carries no
  person attribution fields anywhere in its schema.
  - Verify: `tests/heimdal/test_meeting_projection.py::test_transcript_orders_and_marks_gaps`
- [ ] Analysis blocks carry revision, derived_from, template, and engine provenance; re-derivation
  over an identical admitted set is convergent (block-level equality).
  - Verify: `tests/heimdal/test_meeting_projection.py::test_analysis_provenance_and_convergence`
- [ ] Template precedence resolves user-selection over permitted-metadata over default, via the
  production resolution seam, with `generic-default@1` as the only shipped template.
  - Verify: `tests/heimdal/test_meeting_projection.py::test_template_precedence_resolution`
- [ ] Late admission produces a new revision that includes the late segment; the projection read
  reports both the new revision and the completeness state consistently.
  - Verify: `tests/heimdal/test_meeting_projection.py::test_late_segment_creates_new_revision`
- [ ] ASR failure for a segment surfaces as a per-segment needs-attention state in the projection
  (fail-loud), leaving other segments' derivations intact.
  - Verify: `tests/heimdal/test_meeting_projection.py::test_asr_failure_is_legible_and_isolated`

## How to Verify (Pre-Merge)

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -p pytest_asyncio.plugin -q tests/heimdal/test_meeting_projection.py`
  (ASR stubbed at the shared-engine seam; no model download in CI).
- `ruff check app tests`; migration + producers + preflight in the same PR for projection tables.
- CI: `Unit tests (not pg)` green on the head SHA.

## Out of Scope

- Block-ownership enforcement (CDLM-07 — this task emits `derived_projection` blocks only and
  never touches user content).
- Finalization artifacts (CDLM-08). Any UI (CDLM-09).
- Diarization-driven attribution, voiceprints, participant inference, rich templates (later work;
  ADR-0060 gates).
- Push/streaming transport to clients (polling read is the v1 posture; a push channel is a future
  bounded slice).
- Analysis of non-audio kinds (photos/documents in meetings attach as items, not analysis inputs,
  in this slice).

## Related Docs

- `docs/CROSS_DEVICE_CAPTURE_AND_LIVE_MEETING/README.md` (INV-CDLM-5/8/9)
- `docs/MIMER_VOICE_LOOP/SHARE_TRANSCRIPTION_CAPABILITY.md` (the shared ASR seam)
- `docs/adr/ADR-0060-capture-posture-b-full-voice-identity.md` (withheld default; gates for later attribution)
- `docs/research/VOICEPRINT_ATTRIBUTION_DESIGN.md` (advisory only; nothing enacted here)

## Related GitHub Issues

One hub issue implements this task ("Implements CROSS_DEVICE_CAPTURE_AND_LIVE_MEETING/PROJECT_LIVE_TRANSCRIPT_AND_DEFAULT_ANALYSIS").
TCD hint: Opus / high — derivation idempotency, convergence, and gap honesty across restart and
late-segment paths; LLM-adjacent analysis must stay deterministic-in-inputs at the block level.
