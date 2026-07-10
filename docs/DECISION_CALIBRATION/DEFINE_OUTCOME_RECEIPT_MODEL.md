---
name: Define Outcome Receipt Model
description: A separate, append-only outcome receipt referencing an original decision by stable id, mirroring the decision-receipt log's vault-canonical + Postgres-projection architecture
task_id: CAL-01
source_anchor: docs/DECISION_RECEIPT_LOG/README.md :: Design
parent_capability: Decision Calibration
prerequisites: []
depends_on: []
can_parallelize_with: []
---

State: Foundational task; no prerequisites. Slice 1 of the Decision Calibration capability.

# Define Outcome Receipt Model

## Purpose

Give a decision an outcome without ever touching the decision itself. The owner's own decisions
(`decision_record` Human Knowledge Artifacts) are append-only and human-authored; the receipt log this
mirrors (`docs/DECISION_RECEIPT_LOG/`) is append-only for the same reason. This task defines and ships
the outcome vocabulary and its storage: a separate record, linked to the original decision's stable
identity, immutable-original-preserving, durable, and rebuildable — the foundation every other
Decision Calibration task builds on.

## What This Task Does

1. Defines the **outcome vocabulary**: exactly `held` / `partly_held` / `did_not_hold` / `unknown_yet`,
   plus an optional free-text note. No other vocabulary values.
2. Defines **decision identity**: a `decision_record` note, once ingested, is an ordinary vault object
   with `objects.id` (runtime) and `objects.uuid` (frontmatter). An outcome receipt carries both
   (`decision_object_id`, `decision_uuid`) — the same dual-identity shape
   `app/receipts/decision_receipt_log.py::resolve_vault_uuid` already resolves for the GOV judgment
   log, reused here so a Postgres rebuild can re-link a decision whose runtime id was re-minted.
3. Ships the **outcome-receipt log**, structurally mirroring
   `app/receipts/decision_receipt_log.py` line for line: `app/receipts/outcome_receipt_log.py` with
   `append_outcome_receipt()`, `iter_outcome_receipts()`, `build_receipt()`,
   `outcome_receipts_dir()`. Storage: `vault/<system_dir>/receipts/decision_outcomes/` — dated JSONL
   shards (`decision_outcomes-YYYYMM.jsonl`), one schema-versioned JSON object per outcome, append-only.
   **JSONL, not markdown** — decision outcomes are structured verdicts (a vocabulary value + optional
   note + a rung index), the exact same shape rationale `docs/DECISION_RECEIPT_LOG/README.md ::
   Rejected alternatives` gives for choosing JSONL over markdown for the original log applies
   unchanged here; the markdown surface this capability produces is CAL-04's aggregated calibration
   profile, a distinct human-readable derived view, not the receipt itself.
4. **WriteGuard-gated at the seam**: the append asserts `assert_writes_allowed("decision.outcome_receipt")`
   before any I/O, mirroring `RECEIPT_WRITE_ACTION` — a new, named action, not in
   `DEFAULT_BOOTSTRAP_ACTIONS`, so a write-blocked runtime denies it loudly rather than silently
   dropping the owner's answer.
5. **Receipt-before-ack**: the JSONL append is the commit point. A minimal Postgres projection table
   (`decision_outcomes`, one Alembic migration) is written *after*, mirroring
   `app/services/decisions.py::insert_decision`'s ordering — a projection failure must propagate
   (fail-loud), never silently fall back to memory-only.
6. **Idempotency per (decision, rung)**: the receipt carries a `rung_index` (which ladder step this
   outcome answers, defined by CAL-02) and the insert path is a no-op (not a duplicate row) on a
   retried write for the same `(decision_uuid, rung_index)` pair.
7. Original artifacts stay untouched: no code path this task introduces reads-then-writes a
   `decision_record` note's body or frontmatter, or an existing outcome receipt's JSONL line.

## Concretely

```
$ python -m app.cli calibration outcomes append \
    --decision-uuid 8f2e... --rung 0 --outcome held --note "still true, moved on schedule"
{"schema_version": 1, "decision_object_id": "...", "decision_uuid": "8f2e...", "rung_index": 0,
 "outcome": "held", "note": "still true, moved on schedule", "created_at": "2026-07-07T12:00:00+00:00"}
$ python -m app.cli calibration outcomes append --decision-uuid 8f2e... --rung 0 --outcome held
# same (decision_uuid, rung_index) retried → no duplicate row, same receipt returned
```

## Why This Matters

If an outcome could edit the original decision or a prior outcome, the calibration profile would be
lying about its own history — exactly the failure `decision_record`'s "append-only, AI MUST NOT
silently mutate a logged decision" rule exists to prevent. If the outcome log were markdown instead of
JSONL, appends would be lossy/awkward to parse back for aggregation (CAL-04) — the same tradeoff
`docs/DECISION_RECEIPT_LOG/README.md` already worked through and rejected for the original log. If the
WriteGuard seam were skipped, a degraded runtime could silently drop the owner's stamped judgment
DB-only, the exact anti-pattern C-8 exists to close.

## Acceptance Criteria

- [ ] AC1: An outcome-receipt schema validates the four-value vocabulary, optional note, and both
      identity fields (`decision_object_id`, `decision_uuid`); an invalid vocabulary value is rejected.
      Verify: `tests/services/test_outcome_receipt_log.py::test_outcome_schema_validates_vocabulary`
- [ ] AC2: The JSONL append is WriteGuard-gated; a blocked guard raises before any I/O and no partial
      file is written.
      Verify: `tests/services/test_outcome_receipt_log.py::test_append_blocked_by_write_guard_raises_before_io`
- [ ] AC3: The JSONL append is the commit point (receipt-before-ack): a Postgres projection failure
      after a successful append still leaves the outcome durable and readable from the log.
      Verify: `tests/services/test_outcome_receipt_log.py::test_append_durable_even_if_projection_write_fails`
- [ ] AC4: Re-appending the same `(decision_uuid, rung_index)` pair is idempotent — no duplicate row in
      the log or the projection.
      Verify: `tests/services/test_outcome_receipt_log.py::test_append_idempotent_per_decision_and_rung`
- [ ] AC5: No code path in this task reads-then-rewrites a `decision_record` note or an existing
      outcome-receipt JSONL line; append-only is enforced (existing shard files are opened in append
      mode only, never truncate/rewrite).
      Verify: `tests/services/test_outcome_receipt_log.py::test_existing_receipts_never_rewritten`
- [ ] AC6 (enforcement): the only production call site that writes an outcome asserts the WriteGuard
      action — verified at the call site, not just on the guard function in isolation.
      Verify: `tests/services/test_outcome_receipt_log.py::test_append_call_site_asserts_write_guard_action`

## How to Verify (Pre-Merge)

```
ruff check app tests && mypy app
pytest -q tests/services/test_outcome_receipt_log.py
pytest -q -m "not pg"
```

The Postgres projection table and its migration land in this task but the projection-rebuild/doctor
tooling (which reads the whole log back and asserts DB-vs-log equivalence) is CAL-04's deliverable —
this task's own tests exercise the live insert path only, not the rebuild path.

## Out of Scope

The revisit scheduler and ladder (CAL-02); the companion UI card and its endpoints (CAL-03); the
calibration-profile aggregation, rebuild, doctor check, and markdown writeback (CAL-04); any change to
the GOV judgment log (`app/services/decisions.py`, `app/receipts/decision_receipt_log.py`) — those stay
byte-for-byte as delivered; adding a `confidence` field to `decision_record`.

## Related Docs

- `docs/DECISION_RECEIPT_LOG/README.md` — the architecture pattern mirrored here
- `app/receipts/decision_receipt_log.py`, `app/services/decisions.py` — the code precedent
- `docs/CONTEXTUALIZATION_LAYER/LIFE_WIDE_ARTIFACT_TAXONOMY.md :: decision_record`
- `docs/adr/ADR-0019-governed-writes-decision-token-authority-receipt.md`
- `app/write_guard.py` — `WriteGuard`, `DEFAULT_BOOTSTRAP_ACTIONS`

## Related GitHub Issues

One issue: `[Decision Calibration] define-outcome-receipt-model: append-only outcome receipts linked to
the original decision`. Ready immediately (no prerequisites) — the foundation every other task in this
capability builds on.
