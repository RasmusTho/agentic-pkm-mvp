---
name: Track Meeting Sessions And Segment Gaps
description: Hub-side meeting session ledger over admitted segments with open/close, monotonic sequence tracking, gap detection, and late-segment reconciliation.
task_id: CDLM-02
source_anchor: docs/CROSS_DEVICE_CAPTURE_AND_LIVE_MEETING/README.md :: Fixed scope
parent_capability: Cross-Device Capture & Live Meeting
prerequisites: [CDLM-01]
depends_on: [ADMIT_MEDIA_WITH_DURABLE_RECEIPTS.md]
can_parallelize_with: [RETAIN_ORIGINALS_UNTIL_BACKEND_RECEIPT.md]
---

# Track Meeting Sessions And Segment Gaps

## Purpose

Make "which parts of this meeting does the hub durably hold?" a database answer instead of a
guess. Live projections (CDLM-06), reconnect resend (CDLM-03/09), and honest finalization
(CDLM-08) all consume this ledger.

## What This Task Does

- **Session lifecycle:** `POST /api/heimdal/meeting/session` opens a session
  (`session_id` client-minted UUID, `device_id`, `template_selection` opaque at this layer);
  `POST /api/heimdal/meeting/{session_id}/close` records the client's declared final segment
  count. Both idempotent by their client-minted identity: re-posting open/close replays the
  recorded outcome, never forks a session.
- **Segment ledger:** every CDLM-01 admission carrying `(session_id, session_seq)` upserts exactly
  one ledger row keyed `(session_id, session_seq)` referencing the admission receipt. Idempotent
  replays do not duplicate rows; a *different* content hash arriving for an already-ledgered
  `(session_id, session_seq)` is a named conflict — recorded, surfaced as `needs attention`, and
  the original row preserved (fail closed, never silently replaced).
- **Gap report:** `GET /api/heimdal/meeting/{session_id}/segments` returns the received sequence
  set, missing sequence numbers (holes below the declared or observed maximum), the close state,
  and per-segment receipt refs — the reconnect answer CDLM-03/09 resend from.
- **Late reconciliation:** an admission for a closed session's missing sequence number updates the
  ledger and emits `heimdal.meeting.segment.late_admitted`, the trigger CDLM-06/08 re-derive on.
  Sessions never re-open; completeness state is recomputed from the ledger.
- **Restart truth:** ledger and close state live in durable hub storage (PDM); a hub restart
  rebuilds nothing from memory — the ledger *is* the state.

## Concretely

```bash
curl -s -X POST http://hub.local/api/heimdal/meeting/session \
  -d '{"session_id":"mtg-42","device_id":"ipad-1","template_selection":{"mode":"default"}}'
# admit segments seq 0,1,3 via CDLM-01 (seq 2 lost with the network)
curl -s http://hub.local/api/heimdal/meeting/mtg-42/segments
# → {"received":[0,1,3],"missing":[2],"closed":false,"segments":[{"seq":0,"receipt_id":"rcp_…"},…]}
curl -s -X POST http://hub.local/api/heimdal/meeting/mtg-42/close -d '{"final_seq_count":4}'
curl -s http://hub.local/api/heimdal/meeting/mtg-42/segments
# → {"received":[0,1,3],"missing":[2],"closed":true,"complete":false,…}
# late admission of seq 2 → missing:[] , complete:true, late_admitted event emitted
```

## Why This Matters

Without a sequence ledger, a disconnect mid-meeting is indistinguishable from a short meeting:
projections claim completeness over holes, finalization publishes a transcript with silent gaps,
and reconnect cannot name what to resend. INV-CDLM-9 (gaps are legible) is only enforceable if
this ledger exists and survives restart.

## Acceptance Criteria

- [ ] Opening, closing, and re-posting open/close with the same identities replays recorded
  outcomes without forking session state.
  - Verify: `tests/heimdal/test_meeting_session_ledger.py::test_session_lifecycle_is_idempotent`
- [ ] Admissions with session fields create exactly one ledger row per `(session_id, session_seq)`
  across idempotent replays, asserted through the production admission path.
  - Verify: `tests/heimdal/test_meeting_session_ledger.py::test_segment_rows_unique_across_replays`
- [ ] The gap report names exactly the missing sequence numbers before and after close, and
  `complete` flips only when the ledger actually covers the declared count.
  - Verify: `tests/heimdal/test_meeting_session_ledger.py::test_gap_report_names_missing_sequences`
- [ ] A conflicting content hash for an existing `(session_id, session_seq)` preserves the original
  row, records the conflict, and surfaces it in the report as needs-attention.
  - Verify: `tests/heimdal/test_meeting_session_ledger.py::test_seq_conflict_fails_closed`
- [ ] A late admission into a closed session updates the ledger, emits the late-admitted event,
  and recomputes completeness — without re-opening the session.
  - Verify: `tests/heimdal/test_meeting_session_ledger.py::test_late_segment_reconciliation`
- [ ] A simulated hub restart between admissions loses no ledger state (ledger read-back equals
  pre-restart state from durable storage alone).
  - Verify: `tests/heimdal/test_meeting_session_ledger.py::test_ledger_survives_restart`

## How to Verify (Pre-Merge)

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -p pytest_asyncio.plugin -q tests/heimdal/test_meeting_session_ledger.py`
- `ruff check app tests`; Alembic migration for ledger tables ships with its producers and a
  fail-loud preflight in the same PR (Invariant → producers rule, `AGENTS.md :: Required rules`).
- CI: `Unit tests (not pg)` green on the head SHA.

## Out of Scope

- ASR/analysis derivation (CDLM-06) — this task emits triggers, derives nothing.
- Client resend behavior (CDLM-03/09) — this task answers, never commands.
- Finalization artifacts (CDLM-08).
- Any UI. Any person attribution (INV-CDLM-8).

## Related Docs

- `docs/CROSS_DEVICE_CAPTURE_AND_LIVE_MEETING/README.md` (INV-CDLM-3/9; partial-failure matrix)
- `docs/CROSS_DEVICE_CAPTURE_AND_LIVE_MEETING/ADMIT_MEDIA_WITH_DURABLE_RECEIPTS.md` (admission seam)
- `docs/EVENTS.md` (event authority for the new event names)

## Related GitHub Issues

One hub issue implements this task ("Implements CROSS_DEVICE_CAPTURE_AND_LIVE_MEETING/TRACK_MEETING_SESSIONS_AND_SEGMENT_GAPS").
TCD hint: Sonnet / high — schema plus invariants are fully specified; the conflict and restart
paths are where under-modeling would hide.
