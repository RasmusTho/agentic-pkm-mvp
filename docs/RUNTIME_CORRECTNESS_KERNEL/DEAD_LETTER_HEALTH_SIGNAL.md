---
name: Dead Letter Health Signal
description: Surface dead_lettered_count and oldest_undelivered_age_seconds in the health contract with configurable thresholds, read-only, no auto-repair
task_id: KERNEL-12
source_anchor: "docs/audits/SYSTEM_REDESIGN_CORRECTNESS_KERNEL_2026-07-02.md :: I-E4, CW-5"
parent_capability: RUNTIME_CORRECTNESS_KERNEL
prerequisites: []
depends_on: []
can_parallelize_with: [TRANSACTIONAL_VAULT_SYNC, SINGLE_STORE_GENERATION, STORE_SCHEMA_IN_MIGRATIONS, STRUCTURED_INTENT_OUTPUT_WITH_UNKNOWN]
---

# Dead Letter Health Signal

## Purpose

Dead-letters (`outbox.event.dead_lettered`, emitted after `_resolve_max_dispatch_attempts()`
— default `_MAX_DISPATCH_ATTEMPTS = 5`, `app/workers/outbox_worker.py`:
`_dead_letter_outbox_message` approx. lines 608–654, dispatch-exhaustion call site approx. lines
1149–1173) land in the JSONL audit sink and optionally the DB outbox, but **nothing signals them**.
Queue depth is unbounded and unsignaled. The 2026-06 observability audit scored ~1.4/5 with the
canonical failure "processed_total=0 for weeks, invisible" (#2242). Audit invariant **I-E4**: dead-
letter count and oldest-undelivered age MUST surface in the health contract.

## What This Task Does

- Compute `dead_lettered_count` and `oldest_undelivered_age_seconds` from the outbox table and feed
  them into the health contract (`app/health_contract.py`, `HealthContract.evaluate()` approx. line
  208; `DEFAULT_CONTRACT` line 596). The snapshot dict `evaluate()` already returns is the seam —
  add the two fields alongside the existing `errors_last_10m` / events status.
- Add configurable thresholds to `HealthThresholds` (dataclass approx. line 114; add to
  `to_payload()` and to `config`/settings loading): e.g. `dead_lettered_warn` and
  `oldest_undelivered_age_warn_s`. Follow the existing `outbox_degrade_oldest_age_s` pattern.
- Threshold breach surfaces on the health surface. The CLI health surface is `app/cli/health.py`
  (per-check `_result(...)` dicts, e.g. `_check_outbox_path` line 109) and the contract snapshot is
  the HTTP `/healthz`/`/readyz` source; add a dead-letter check that reflects the contract fields.
  Read `docs/HEALTH.md` and reflect the new fields there.
- **Read-only signal, no auto-repair** (cross-task invariant #5): the signal detects; repair stays
  an explicit operator/agent action. Do not add any mutation.

## Design decision (state explicitly in the implementation)

A full dead-letter queue MUST **not** block vault writes: do **not** add dead-letter breach to
`WRITE_BLOCKED_STATES` (`app/health_contract.py` line 102 — currently `{"safe_mode", "unhealthy"}`).
Justification: dead-letters are downstream-processing failures; blocking the human's ability to
capture notes because a background handler is failing inverts the priority (capture is the product;
processing is derived and replayable once the handler is fixed). This is an **alerting** signal, not
a write gate. It may raise `degraded` visibility but must leave `writes_allowed` true.

## Concretely

```bash
pytest -q tests/health/test_dead_letter_signal.py
```

## Why This Matters

The pipeline's worst failure is "quietly does nothing" — for a memory system, absence of recall is
indistinguishable from absence of content (CW-5). Making dead-letters loud is the minimum
observability that turns a weeks-long silent stall into a same-tick visible signal.

## Acceptance Criteria

- [ ] `evaluate()` snapshot includes `dead_lettered_count` and `oldest_undelivered_age_seconds`
      computed from the outbox source.
      Verify: `tests/health/test_dead_letter_signal.py::test_snapshot_includes_dead_letter_fields`
- [ ] Thresholds are configurable via `HealthThresholds` and reflected in `to_payload()`.
      Verify: `tests/health/test_dead_letter_signal.py::test_thresholds_configurable`
- [ ] An injected dead-letter flips the health snapshot within one worker tick, through the
      production `evaluate()` path — not a helper computed in isolation.
      Verify: `tests/health/test_dead_letter_signal.py::test_injected_dead_letter_flips_snapshot` — asserts the field/breach appears via `app.health_contract.DEFAULT_CONTRACT.evaluate()`.
- [ ] Dead-letter breach does NOT set `writes_allowed=False` (not added to `WRITE_BLOCKED_STATES`).
      Verify: `tests/health/test_dead_letter_signal.py::test_dead_letter_does_not_block_writes`
- [ ] `docs/HEALTH.md` documents the two fields and their thresholds.
      Verify: doc writeback at `docs/HEALTH.md :: Dead-letter signal`

## How to Verify (Pre-Merge)

1. `pytest -q tests/health/test_dead_letter_signal.py` (new; sits alongside existing
   `tests/health/test_container_health_signals.py`).
2. Full `pytest -q -m "not pg"`.
3. `ruff check app tests`.

## Out of Scope

- Auto-repair / re-drive of dead-lettered rows (explicit operator action).
- Changing `_MAX_DISPATCH_ATTEMPTS` or dead-letter emission logic (KERNEL-02/08 own producers).
- Alert routing/paging integration (this task lands the signal; delivery is a later concern).

## Related Docs

- `docs/audits/SYSTEM_REDESIGN_CORRECTNESS_KERNEL_2026-07-02.md :: I-E4, CW-5`
- `docs/HEALTH.md`, `app/health_contract.py`, `app/cli/health.py`
- `docs/testing/invariant-tests.md` (I-E4)

## Related GitHub Issues

One bounded issue; may pair with the 2026-06 observability audit follow-ups (#2621 LLM-readiness is
separate). TCD hint: Sonnet / medium effort (read-only signal + threshold config + one enforcement
test through the production evaluate path). Escalate only if the outbox-source query needs a DB
migration to be efficient.
