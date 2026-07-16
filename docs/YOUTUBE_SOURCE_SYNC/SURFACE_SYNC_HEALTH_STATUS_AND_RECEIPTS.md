---
name: Surface Sync Health, Status, and Receipts
description: Doctor/health checks, /api/status slice, degraded-reason surfacing, and a typed read-only receipt projection that answers the audit questions without secrets.
task_id: YSS-09
source_anchor: "docs/YOUTUBE_SOURCE_SYNC/SOURCE_SYNC_CONTRACT.md :: Event topics"
parent_capability: YouTube Source Sync
prerequisites: [YSS-02, YSS-04, YSS-06]
depends_on: [BIND_YOUTUBE_ACCOUNT_WITH_OAUTH.md, ESTABLISH_DURABLE_ACQUISITION_REQUESTS.md, SCHEDULE_AND_OPERATE_CONTINUOUS_SYNC.md]
can_parallelize_with: [REPAIR_GAPS_WITH_PREVIEWED_BACKFILL.md, OPERATE_SYNC_FROM_CLI.md]
---

# Surface Sync Health, Status, and Receipts

## Purpose

Sync must be legible: the operator sees auth state, per-source degradation, queue depth, quota,
next due times, and can answer "why does this candidate exist?" from durable receipts — all
through the existing health/status/receipt substrates, never a parallel channel.

## What This Task Does

1. **Doctor check:** `_check_youtube_sync()` in `app/cli/health.py` added to the `checks` dict
   (`required=False`): enabled flags, auth binding state (reason-coded), token-store key
   presence, sources total/enabled/degraded, queue depth + dead letters, quota status,
   `last_tick_at` staleness (`runner_offline` derived). Suggested actions carry the matching
   remediation command hints (`youtube-auth connect`, `youtube-sync run`, key provisioning per
   runbook) — hints, not auto-repair.
2. **Status slice:** `_get_youtube_sync_status()` + a `youtube_sync` field on `SystemStatus`
   (`app/observability/status_service.py` / `status_model.py`): the same signals shaped for
   `/api/status`, which the Companion UI already proxies — YSS-11 renders this projection.
3. **Receipt projection:** `app/receipts/youtube_sync_receipts.py` following the
   `settings_receipts`/`promotion_receipts` pattern (`read_receipt_source_records` over the
   `acquisition.*` / `youtube.sync.*` / `youtube.source.discovered` topics), joined with request
   rows to answer, per item: which source(s) discovered it and when; whether it was deduplicated
   (trigger count > 1); which step failed (reason code + stage); whether the cursor advanced
   (source `last_success_at` vs frontier); when the next retry is due; which account binding and
   channel database ran the job. All secret-free (INV-YSS-5).
4. **Health-contract feed:** dead-letter counts and queue-age signals ride the existing
   outbox/dead-letter fields the `HealthContract` already evaluates — no new health channel;
   `/healthz` semantics unchanged.

## Concretely

```
$ python -m app.cli health --json | jq .checks.youtube_sync
{"ok": true, "detail": "connected; 12 sources (1 degraded); queue 3; quota 214/10000; last tick 41s ago", "required": false, ...}
$ python -m app.cli youtube-sync why dQw4w9WgXcQ --json
{"item_ref": "dQw4w9WgXcQ", "request_id": "…", "triggers": [{"binding": "Mimer Inbox", "at": "…"}, {"binding": "Liked Videos", "at": "…"}],
 "deduplicated": true, "status": "completed", "artifact_path": "Sources/…md", "attempts": 1, "next_attempt_at": null}
```

## Why This Matters

The observability audit's standing lesson is that always-on signals false-green: a sync that
cannot say "degraded because auth_revoked since Tuesday" silently rots. And provenance questions
("why is this note here?") are the product's trust spine.

## Acceptance Criteria

- [ ] The doctor check reports each contract reason code distinctly (fixtures per degraded state:
      auth_revoked, quota_exhausted, runner_offline, paused, dead letters present) and stays
      secret-free.
      Verify: `tests/cli/test_health_youtube_sync.py::test_doctor_check_reason_codes_and_redaction`
- [ ] `runner_offline` is derived from `last_tick_at` staleness; a stale runner is never reported
      "up to date".
      Verify: `tests/cli/test_health_youtube_sync.py::test_stale_runner_never_reads_up_to_date`
- [ ] The `/api/status` slice carries sources/queue/quota/auth and renders through the existing
      status route (production wiring asserted, not the helper in isolation).
      Verify: `tests/observability/test_status_youtube_sync.py::test_status_slice_wired_into_system_status`
- [ ] The receipt projection answers all eight audit questions for a fixture item discovered by
      two sources with one failed attempt — without any secret material.
      Verify: `tests/receipts/test_youtube_sync_receipts.py::test_projection_answers_audit_questions_secret_free`
- [ ] Dead letters and queue depth surface through the existing health-contract signals (no
      parallel health channel introduced).
      Verify: `tests/cli/test_health_youtube_sync.py::test_signals_ride_existing_health_contract`

## How to Verify (Pre-Merge)

- `pytest -q tests/cli/test_health_youtube_sync.py tests/observability/test_status_youtube_sync.py tests/receipts/test_youtube_sync_receipts.py`
- `pytest -q -m "not pg"`
- `ruff check app tests && mypy app`

## Out of Scope

UI rendering of these projections (YSS-11), CLI command surfaces beyond `youtube-sync why`
(YSS-10 owns the family), alerting/notification delivery (observability roadmap owns it).

## Restart / Durability Posture

Everything surfaced is a projection over durable rows/events; the surfaces themselves hold no
state. Staleness derivation means a dead runner is visible as degraded within one staleness
window, not on self-report.

## Related Docs

- `docs/YOUTUBE_SOURCE_SYNC/SOURCE_SYNC_CONTRACT.md :: Event topics / Reason codes / Quota accounting`
- `docs/EVENTS.md :: Receipt vs Event boundary`

## Related GitHub Issues

One issue. TCD hint: Sonnet / high — projection and wiring work across three existing substrates;
truthfulness-under-degradation is the review focus.
