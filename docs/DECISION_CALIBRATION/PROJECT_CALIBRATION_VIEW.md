---
name: Project Calibration View
description: Rebuildable aggregation over outcome receipts by decision kind/tag and stated confidence, hazard-safe against the known Postgres-only-row-loss failure mode, projected as a readable markdown vault surface
task_id: CAL-04
source_anchor: docs/DECISION_CALIBRATION/README.md :: Cross-Task Invariants / Interaction Safety :: INV-CAL-F
parent_capability: Decision Calibration
prerequisites: [CAL-01]
depends_on: [DEFINE_OUTCOME_RECEIPT_MODEL.md]
can_parallelize_with: [Schedule Decision Revisits]
---

State: Depends on CAL-01 (reads outcome receipts). Can build in parallel with CAL-02 — this task never
touches the scheduler or the dismissal ledger. Slice 4 of the Decision Calibration capability; the
compounding-value payoff the other three tasks exist to feed.

# Project Calibration View

## Purpose

An outcome receipt per decision is only individually useful; the compounding value the owner asked for
— "over time, learn which decision types I over- or under-estimate" — requires aggregating outcomes
across the whole journal. This task builds that aggregation as a rebuildable projection (never a second
source of truth) and writes a human-readable summary back into the vault, exactly the way every other
derived view in this repo is required to be rebuildable from durable sources alone.

## What This Task Does

1. Defines the **rollup shape**: counts and rates of `held` / `partly_held` / `did_not_hold` /
   `unknown_yet` grouped by decision kind/tag — read from whatever the `decision_record` note already
   carries (`area`, `project` frontmatter fields today; a generic `tags` array if present) — and,
   *where present*, grouped further by a stated confidence value. No new required frontmatter field is
   introduced on `decision_record`; grouping degrades gracefully to "ungrouped" when neither `area` nor
   `project` nor `tags` is set, and confidence-grouping is simply omitted when no outcome/decision in
   the set carries one.
2. Ships `rebuild_calibration_projection()` in `app/jobs/calibration_projection.py`, mirroring
   `app/jobs/decisions_projection.py::rebuild_decisions_projection` in shape (read every JSONL outcome
   receipt via CAL-01's `iter_outcome_receipts()`, truncate-and-replay the `decision_outcomes`
   Postgres rows, compute the rollup) — **with one addition the original function is missing**: a
   pre-rebuild doctor-equivalence check.
3. Ships `doctor_calibration_projection()`, mirroring `doctor_decisions_projection`: compares every
   Postgres `decision_outcomes` row against what the vault JSONL log implies. **`rebuild_calibration_projection()`
   calls this first and refuses to truncate — raises loudly, does not proceed — if Postgres carries any
   row the vault log cannot account for.** This is the safety net
   `app/jobs/decisions_projection.py::rebuild_decisions_projection` does not have today: that function
   already caused a real prod incident (2 rows that existed only in Postgres, pre-dating the JSONL log,
   were silently dropped on a rebuild). This task's rebuild must not repeat that failure mode for the
   new outcome-receipt table.
4. Writes the rollup back as a **generated, human-readable markdown note**:
   `vault/<system_dir>/calibration/calibration-profile.md` — regenerated on every rebuild, WriteGuard
   -gated the same way other system-generated vault artifacts are (companion-note precedent), never
   hand-edited by the owner (it is a derived view, not a `decision_record`).
5. Exposes a CLI entrypoint (`python -m app.cli calibration profile rebuild`) and a scheduled/triggered
   hook point (invoked after CAL-01 outcome appends, or on demand) — this task defines the rebuild
   function and its call site; wiring it to a periodic tick is a lightweight follow-up, not blocking
   acceptance, since the rebuild is idempotent and safe to run on demand.

## Concretely

```
$ python -m app.cli calibration profile rebuild
{"total_receipts": 14, "inserted": 14, "orphans": 0, "markdown_written": true}
$ python -m app.cli calibration profile rebuild   # with a stray DB-only row present
Error: calibration projection rebuild refused — Postgres has 1 outcome row with no matching
vault-canonical receipt (decision_uuid=..., rung_index=...). Reconcile before rebuilding; a
rebuild that proceeded here would silently drop that row (the historical `decisions` incident).
```

`vault/<system_dir>/calibration/calibration-profile.md` (excerpt):

```markdown
# Decision Calibration Profile
_generated 2026-07-07 — do not edit by hand_

## By area
- architecture (6 decisions, 9 stamped outcomes): held 6, partly-held 2, did-not-hold 1
- product (3 decisions, 3 stamped outcomes): held 2, unknown-yet 1
```

## Why This Matters

This is the entire compounding payoff the ideation capture names: without it, Decision Calibration is
just a slower version of "write it down and forget it" — outcomes get stamped but nothing ever tells
the owner *which kinds* of decisions he tends to get right or wrong. And if the rebuild is not
hazard-safe, the very first time someone runs it against a live, slightly-inconsistent Postgres, it
repeats the exact prod incident this repo already lived through with `decisions` — silently discarding
history that exists nowhere else. Naming the hazard and gating the rebuild on it is not defensive
over-engineering; it is closing a known, already-occurred failure mode before it can recur on a second
table.

## Acceptance Criteria

- [ ] AC1: The rollup groups outcome receipts by whatever kind/tag signal the referenced
      `decision_record` carries (`area`/`project`/`tags`), degrading to "ungrouped" when none is
      present, and further groups by stated confidence only when at least one entry carries it.
      Verify: `tests/jobs/test_calibration_projection_rebuild.py::test_rollup_groups_by_available_kind_and_confidence`
- [ ] AC2: `rebuild_calibration_projection()` truncates and replays the projection correctly from a
      fixture JSONL log with no Postgres-only residue.
      Verify: `tests/jobs/test_calibration_projection_rebuild.py::test_rebuild_replays_log_into_projection`
- [ ] AC3 (enforcement): `rebuild_calibration_projection()` calls the doctor-equivalence check *before*
      truncating, and refuses (raises, no truncate executed) when Postgres carries a
      `decision_outcomes` row the vault log cannot account for — asserted at the rebuild function's own
      call site, not only on the doctor check in isolation.
      Verify: `tests/jobs/test_calibration_projection_rebuild.py::test_rebuild_refuses_when_db_has_unaccountable_rows`
- [ ] AC4: The calibration profile is fully rebuildable from the vault JSONL log alone — a rebuild
      starting from an empty Postgres reproduces the same rollup as one starting from a populated,
      log-consistent Postgres.
      Verify: `tests/integration/test_calibration_rebuild_from_log_only.py::test_rebuild_from_log_only_matches_populated_rebuild`
- [ ] AC5: A revisit answered while the projection/rebuild job is down is not lost: the durable receipt
      (CAL-01) exists and a later rebuild picks it up; no answer is silently dropped by a projection
      outage.
      Verify: `tests/integration/test_calibration_rebuild_from_log_only.py::test_answer_survives_projection_outage`
- [ ] AC6: The rollup is written back as a generated markdown note at the canonical vault path,
      regenerated (not appended to) on every successful rebuild.
      Verify: doc writeback at `vault/<system_dir>/calibration/calibration-profile.md`; test:
      `tests/jobs/test_calibration_projection_rebuild.py::test_markdown_profile_written_on_rebuild`

## How to Verify (Pre-Merge)

```
ruff check app tests && mypy app
pytest -q tests/jobs/test_calibration_projection_rebuild.py
pytest -q -m pg tests/jobs/test_calibration_projection_rebuild.py tests/integration/test_calibration_rebuild_from_log_only.py
pytest -q -m "not pg"
```

The hazard-refusal test (AC3) and the log-only rebuild-equivalence test (AC4) require a real Postgres
instance (`pg`-marked); they exercise the exact condition (Postgres has a row the log does not) that
caused the historical `decisions` incident.

## Out of Scope

The outcome-receipt write path and its idempotency (CAL-01); the scheduler, ladder, and dismissal
ledger (CAL-02); the companion UI card (CAL-03); adding a `confidence` field to `decision_record` (this
task only *tolerates* it if present); periodic/automatic rebuild scheduling (a follow-up wiring task,
not blocking — the rebuild function itself is this task's deliverable and is safe to invoke manually or
on demand); reconciling an existing Postgres-only row once the doctor check flags one (an operator
decision when it happens, not something this task automates away).

## Related Docs

- `docs/DECISION_CALIBRATION/README.md` — capability grounding, INV-CAL-F, and the historical hazard
- `docs/DECISION_CALIBRATION/DEFINE_OUTCOME_RECEIPT_MODEL.md` — the outcome receipts this task reads
- `app/jobs/decisions_projection.py` — `rebuild_decisions_projection` / `doctor_decisions_projection`,
  the code precedent this task mirrors and hardens
- `reference_prod_db_backup` / the operator's standing "don't run `rebuild_decisions_projection` on
  prod" caution — the lived incident this task's doctor-first gate exists to prevent from recurring

## Related GitHub Issues

One issue: `[Decision Calibration] project-calibration-view: rebuildable calibration profile, hazard
-safe rebuild, markdown writeback`. Blocked on CAL-01 merging; can be picked up in parallel with CAL-02.
