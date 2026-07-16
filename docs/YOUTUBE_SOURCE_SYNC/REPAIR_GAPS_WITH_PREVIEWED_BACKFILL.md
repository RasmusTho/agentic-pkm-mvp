---
name: Repair Gaps with Previewed Backfill
description: Weekly reconciliation and operator-confirmed historical backfill — full enumeration (API pagination or logged-out yt-dlp flat-playlist), diff against dispositions, preview receipt, explicit arm gate.
task_id: YSS-08
source_anchor: "docs/YOUTUBE_SOURCE_SYNC/SOURCE_SYNC_CONTRACT.md :: Cursor discipline"
parent_capability: YouTube Source Sync
prerequisites: [YSS-05, YSS-07]
depends_on: [DISCOVER_PLAYLIST_ITEMS_CONTINUOUSLY.md, SYNC_SUBSCRIPTIONS_FROM_TAKEOUT_AND_RSS.md]
can_parallelize_with: [SURFACE_SYNC_HEALTH_STATUS_AND_RECEIPTS.md, OPERATE_SYNC_FROM_CLI.md]
---

# Repair Gaps with Previewed Backfill

## Purpose

Incremental discovery has honest blind spots: the ~15-entry RSS window, capped pagination
overflows, and time offline. Backfill is the rare, expensive full enumeration that repairs them —
and the one operation big enough that it never starts without a preview and an explicit
confirmation.

## What This Task Does

1. New module `app/knowledge_acquisition/sync_backfill.py`:
   - `enumerate_collection(binding)` — full item enumeration: API pagination for authenticated
     playlist bindings (YSS-03 client), logged-out `yt-dlp --flat-playlist` (existing dependency,
     metadata-only, politeness sleeps) for channels/public playlists;
   - `plan_backfill(binding | all)` → **preview receipt**: sources covered, items enumerated,
     items already disposed, gap count, estimated work (requests to create, per current policy),
     and the chosen mode `new_items_only` (from each incremental frontier) vs `full_history`;
   - `execute_backfill(plan_id)` — enqueues exactly the plan's gap set through YSS-04 (`trigger:
     backfill`), idempotent per INV-YSS-2; never rewinds incremental cursors; clears
      `backfill_needed` markers set by YSS-05/07.
2. **Arm gate:** `execute_backfill` refuses unless the specific plan was explicitly confirmed
   (plan id echo — CLI flag `--confirm-plan <id>` / UI confirm step). `full_history` additionally
   requires `youtubeSync.historicalBackfillArmed=true` at execution time; the flag auto-resets
   after one armed execution (per-run confirmation, not a standing switch).
3. **Weekly reconciliation:** a `reconcile` due-time (default `reconcileIntervalDays=7`) in the
   YSS-06 scheduler runs `plan_backfill(new_items_only)` per enabled source and auto-executes
   only when the gap count is small (bounded auto-repair threshold, default ≤ 25 items); larger
   gaps surface as a pending preview requiring confirmation (never silent bulk acquisition).
4. Emits `youtube.sync.completed`/`degraded` with `run_id=backfill:<plan_id>` and per-item
   `youtube.source.discovered` (`trigger: backfill`).

## Concretely

```
$ python -m app.cli youtube-sync backfill --plan --json
{"plan_id": "bf-…", "sources": 3, "enumerated": 812, "already_disposed": 790, "gap": 22, "mode": "new_items_only"}
$ python -m app.cli youtube-sync backfill --execute --confirm-plan bf-… --json
{"plan_id": "bf-…", "enqueued": 22, "deduplicated": 0}
```

## Why This Matters

Backfill is where a misstep becomes 4,000 surprise acquisitions burning quota and flooding triage
— or, inverted, where silently *not* repairing gaps loses saved videos forever. The preview/arm
gate makes the first impossible; the weekly reconcile makes the second impossible.

## Acceptance Criteria

- [ ] Gap repair: items missing from incremental discovery (beyond-RSS-window fixture) are found
      and enqueued exactly once; already-disposed items are not re-enqueued.
      Verify: `tests/knowledge_acquisition/test_sync_backfill.py::test_backfill_repairs_gap_without_duplicates`
- [ ] `execute_backfill` without a confirmed matching plan id is refused — asserted at the
      production execute call site.
      Verify: `tests/knowledge_acquisition/test_sync_backfill.py::test_execute_requires_confirmed_plan_at_call_site`
- [ ] `full_history` requires the armed flag and the flag auto-resets after one execution.
      Verify: `tests/knowledge_acquisition/test_sync_backfill.py::test_full_history_requires_arm_and_flag_resets`
- [ ] The preview receipt reports sources/enumerated/disposed/gap/estimated-work truthfully for a
      mixed fixture and is secret-free.
      Verify: `tests/knowledge_acquisition/test_sync_backfill.py::test_preview_receipt_counts_truthful_and_secret_free`
- [ ] Weekly reconcile auto-repairs only under the bounded threshold; above it, a pending preview
      is surfaced instead.
      Verify: `tests/knowledge_acquisition/test_sync_backfill.py::test_weekly_reconcile_bounded_auto_repair`
- [ ] Backfill never mutates incremental cursors; a failed enumeration degrades reason-coded
      without partial enqueue of an unplanned set.
      Verify: `tests/knowledge_acquisition/test_sync_backfill.py::test_backfill_never_touches_cursors_and_fails_atomic`

## How to Verify (Pre-Merge)

- `pytest -q tests/knowledge_acquisition/test_sync_backfill.py`
- `pytest -q -m "not pg"`
- `ruff check app tests && mypy app`

## Out of Scope

Media/file archival (policy stays off — contract §Media retention policy), UI confirm surface
markup (YSS-11 consumes the plan/execute API), Takeout re-import (YSS-07 owns it; reconcile may
*recommend* a fresh Takeout when subscription drift is detected, it never fetches one).

## Restart / Durability Posture

Plans are durable rows (plan id, counts, confirmed_at, executed_at) in the sync-state substrate; a
restart between plan and execute preserves the pending confirmation. A crash mid-execute
re-converges through request idempotency — re-executing the same confirmed plan enqueues only what
is still missing.

## Related Docs

- `docs/YOUTUBE_SOURCE_SYNC/SOURCE_SYNC_CONTRACT.md :: Cursor discipline / Acquisition policy`
- `docs/CONTEXTUALIZATION_LAYER/INGESTION_AND_TRIAGE_POLICY.md :: §8 Open questions` (bulk-import receipts — this preview receipt is acquisition-scoped, not a triage-policy change)

## Related GitHub Issues

One issue. TCD hint: Sonnet / high — enumeration/diff/gating logic over fixed contracts; the arm
gate and atomicity are the review focus.
