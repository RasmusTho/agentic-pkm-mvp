---
name: Schedule Decision Revisits
description: Time-based revisit trigger over a provisional interval ladder; at most one pending revisit per decision; a durable dismissal ledger so ignoring a card durably advances the ladder
task_id: CAL-02
source_anchor: docs/DECISION_CALIBRATION/README.md :: Cross-Task Invariants / Interaction Safety :: INV-CAL-C
parent_capability: Decision Calibration
prerequisites: [CAL-01]
depends_on: [DEFINE_OUTCOME_RECEIPT_MODEL.md]
can_parallelize_with: [Project Calibration View]
---

State: Depends on CAL-01 (reads outcome receipts to compute what is still due). Can build in parallel
with CAL-04. Slice 2 of the Decision Calibration capability.

# Schedule Decision Revisits

## Purpose

A decision journal only compounds in value if something eventually asks "did that hold?" — on a
schedule, not only when the owner happens to remember. This task computes, for every ingested
`decision_record` note, whether a revisit is due right now, using a provisional time-based ladder, and
guarantees the owner is never shown more than one pending revisit for the same decision at once.

## What This Task Does

1. Declares the **interval ladder** as a provisional, single-sourced, settings-governed constant — the
   same posture ERE's provisional thresholds and `docs/SETTINGS_SPINE/DEHARDCODE_WAVE_ONE.md` use for
   values that will migrate into the settings registry once `docs/SETTINGS_SPINE/` ships: a Python
   module constant today (`app/calibration/ladder.py::DEFAULT_REVISIT_LADDER = (14, 42, 180)` — days;
   2w/6w/6m), declared once, read from one place, shaped so `SINGLE_DEFAULT_REGISTRY.md`'s eventual
   registry key (`calibration.revisit_ladder_days`) can absorb it without a second migration. This task
   does **not** depend on Settings Spine merging; it only avoids scattering the literal.
2. Ships `next_pending_revisit(decision) -> RevisitDue | None`: given a decision's `decided_on` date,
   the ladder, and (a) every outcome receipt CAL-01 has recorded for it, and (b) every dismissal this
   task has recorded for it, returns the earliest un-actioned rung whose due date
   (`decided_on + ladder[i]`) has passed — or `None` if every rung is actioned or none is due yet.
3. Ships a **durable dismissal ledger**, `app/receipts/revisit_dismissal_log.py`, structurally mirroring
   CAL-01's outcome-receipt log (vault-canonical JSONL, WriteGuard-gated seam, action
   `decision.revisit_dismissal`, append-only): a dismissal is *not* an outcome (no vocabulary value),
   it is a record that a rung was shown and the owner chose "not now," so the ladder durably advances
   past it without asserting a judgment. Without this ledger, a dismissed card would resurface after
   every restart — the exact trust failure the Restart/Durability Posture rule exists to catch.
4. Guarantees **at most one pending revisit per decision**: if the owner never engages for months and
   several rungs fall due, `next_pending_revisit` still returns only the earliest un-actioned one; the
   next rung is only computed as pending once the current one is actioned (answered via CAL-01 or
   dismissed via this task's ledger).
5. Exposes a query over all decisions with a pending revisit (`app/calibration/scheduler.py::due_revisits()`)
   for CAL-03 to render and for a future daily-briefing consumer (named future seam, not built here).

## Concretely

```
$ python -m app.cli calibration revisits due --json
{"due": [{"decision_uuid": "8f2e...", "title": "Postgres as projection, not source of truth",
          "decided_on": "2026-06-23", "rung_index": 0, "rung_days": 14, "due_since": "2026-07-07"}]}
$ python -m app.cli calibration revisits dismiss --decision-uuid 8f2e... --rung 0
# rung 0 recorded dismissed; `due` now reports nothing for this decision until rung 1 (day 42) falls due
```

## Why This Matters

Without a ladder, "revisit decisions" is a vague aspiration with no trigger — the exact gap the
ideation capture names ("nothing revisits a decision"). Without the dismissal ledger, the owner would
be nagged by the same card every session even after explicitly saying "not now," training him to ignore
the surface entirely — the same trust erosion `docs/COMMITMENT_SURFACING/README.md`'s "no flicker"
invariant protects against, applied to dismissal instead of read consistency. Without the
at-most-one-pending guarantee, a long-neglected journal would dump a wall of overdue cards on the owner
the moment he returns, defeating the "low-cognitive-load touchpoint" the whole Reflect arc exists to
provide.

## Acceptance Criteria

- [ ] AC1: The revisit ladder is declared once as a single named constant; no second literal copy of
      the interval values exists elsewhere in the scheduler or its tests' production code path.
      Verify: `tests/services/test_revisit_scheduler.py::test_ladder_declared_once_and_imported`
- [ ] AC2: `next_pending_revisit` returns the earliest un-actioned rung whose due date has passed, and
      `None` when no rung is due or every rung is actioned.
      Verify: `tests/services/test_revisit_scheduler.py::test_next_pending_revisit_returns_earliest_due_rung`
- [ ] AC3: A decision with several overdue rungs (owner absent for months) reports exactly one pending
      revisit, not one per overdue rung.
      Verify: `tests/services/test_revisit_scheduler.py::test_at_most_one_pending_revisit_per_decision`
- [ ] AC4: Dismissing a rung is durable (survives a fresh process / re-import of the scheduler module)
      and does not write an outcome receipt.
      Verify: `tests/services/test_revisit_scheduler.py::test_dismissal_is_durable_and_writes_no_outcome`
- [ ] AC5: Dismissing a rung is WriteGuard-gated at the seam, mirroring CAL-01's guard posture.
      Verify: `tests/services/test_revisit_scheduler.py::test_dismiss_blocked_by_write_guard_raises_before_io`
- [ ] AC6: Answering a rung (an outcome receipt exists for it, per CAL-01) advances the schedule the
      same way a dismissal does — the next rung becomes eligible, the answered one never resurfaces.
      Verify: `tests/services/test_revisit_scheduler.py::test_answered_rung_advances_schedule_like_dismissal`

## How to Verify (Pre-Merge)

```
ruff check app tests && mypy app
pytest -q tests/services/test_revisit_scheduler.py
pytest -q -m "not pg"
```

## Out of Scope

The companion UI card and its endpoints (CAL-03, which calls `due_revisits()` and the dismiss path
built here); the outcome-receipt write path itself (CAL-01, consumed read-only here); the calibration
profile aggregation (CAL-04); episode-closure-triggered revisits (future, dependent on the Episode
Resolution Engine — this task ships only the time-based ladder); migrating the ladder constant into the
live Settings Spine registry (follow-up once that capability ships; this task only shapes the constant
so that migration is a single move, not a redesign).

## Related Docs

- `docs/DECISION_CALIBRATION/README.md` — capability grounding and cross-task invariants
- `docs/DECISION_CALIBRATION/DEFINE_OUTCOME_RECEIPT_MODEL.md` — the outcome receipts this task reads
- `docs/SETTINGS_SPINE/README.md`, `docs/SETTINGS_SPINE/DEHARDCODE_WAVE_ONE.md` — the tunables posture
  this task's ladder constant follows without depending on the capability shipping
- `app/receipts/decision_receipt_log.py` — the guarded-append pattern the dismissal ledger mirrors

## Related GitHub Issues

One issue: `[Decision Calibration] schedule-decision-revisits: time-based ladder, at most one pending
revisit per decision`. Blocked on CAL-01 merging (reads outcome receipts); can be picked up in parallel
with CAL-04.
