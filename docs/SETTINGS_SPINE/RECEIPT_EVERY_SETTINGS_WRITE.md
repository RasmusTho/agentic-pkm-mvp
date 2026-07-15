---
name: Receipt Every Settings Write
description: Every writer that mutates a settings file — API, watcher delta, compiler auto-heal, agent — emits a durable actor-tagged SettingsWriteReceipt
task_id: SETTINGS-04
source_anchor: docs/audits/SETTINGS_ARCHITECTURE_2026-07-07.md :: F5
parent_capability: Settings Spine
prerequisites: [SETTINGS-01]
depends_on: [WIRE_SETTINGS_INGESTION.md]
can_parallelize_with: [Canonicalize Settings Location]
---

# Receipt Every Settings Write

## Purpose

Close audit finding F5 (SET-3): only `SettingsService.update_setting` emits a durable
`SettingsWriteReceipt` today (`app/vault/settings_service.py:66-119,372-379`). The compiler's
auto-heal **writes into vault markdown** with only an in-process bus event
(`app/settings/compiler.py:440-443`); app-local writes and Heimdal-pattern agent writes emit
nothing. The product's moat is write-gating + receipts; a machine mutating a human-editable file
without a durable receipt violates the posture.

## What This Task Does

- Generalizes the existing receipt emission (`_emit_settings_write_receipt`, dual JSONL+DB outbox,
  topic `settings.write.receipt`) into a seam every settings writer calls.
- Wires it into: compiler auto-heal writeback (`app/settings/writeback.py:44-57`), the watcher
  settings-delta apply path (`app/watcher/settings_delta.py:26-102`), and the app-local store's
  writes (`app/vault/app_local.py`) — each receipt actor-tagged (`surface`: api / file-watch /
  auto-heal / agent) and key-scoped.
- Extends `query_settings_receipts` (`app/receipts/settings_receipts.py`) so all writers' receipts
  are queryable through the one existing read surface.
- If SETTINGS-03 merged first with unreceipted migration writes, backfills a migration receipt
  from its PR record (see capability Cross-Task Invariants).

## Concretely

```
# auto-heal clamps an out-of-range timeout in llm_routing.md:
$ agentic-pkm settings compile
$ agentic-pkm settings receipts --last 1
  {"topic":"settings.write.receipt","surface":"auto-heal","key":"global.timeout_ms","from":999999,"to":120000,...}
```

## Why This Matters

Auto-heal silently editing a human's markdown is exactly the "machine overwrote my note and
nothing tells me" failure the write-gating + receipts moat exists to prevent.

## Acceptance Criteria

- [ ] Compiler auto-heal writeback emits a durable receipt naming file, key, old/new value, and
      surface `auto-heal`.
  - Verify: `tests/vault/test_settings_receipt_durable.py::test_autoheal_writeback_receipted`
    (enforcement AC — drives `compile_all()` with an invalid value and asserts the receipt lands
    via the production writeback call site)
- [ ] Watcher settings-delta applies emit a receipt with surface `file`.
  - Verify: `tests/watcher/test_settings_delta_receipts.py::test_delta_apply_receipted` (extend
    existing module)
- [ ] App-local store writes emit a receipt with surface `app-local` (pre-vault: receipt goes to
      the JSONL sink; DB sink is best-effort as today).
  - Verify: `tests/vault/test_settings_receipt_durable.py::test_app_local_write_receipted`
- [ ] All receipts are queryable via `query_settings_receipts` regardless of writer.
  - Verify: `tests/vault/test_settings_receipt_durable.py::test_all_writers_queryable`
- [ ] SET-3 registered in the invariant registry with enforcement `runtime_test`.
  - Verify: doc writeback at `docs/testing/invariant-tests.md :: every_settings_write_receipted`

## How to Verify (Pre-Merge)

- `pytest -q tests/vault/test_settings_receipt_durable.py tests/watcher/test_settings_delta_receipts.py`
- `pytest -q -m "not pg"` (shared write seam touched)

## Out of Scope

- Heimdal `_heimdal/**` note receipts — its write path is contract-owned (Mimer client contract
  F7 schema publication); raise a follow-up there rather than changing a contracted surface here.
- New write surfaces or approval loops (receipts observe; they do not gate — #2475 posture).

## Restart / Durability Posture

Receipts are durable (JSONL + DB outbox, both best-effort-dual as today). A receipt written only
to JSONL pre-vault survives restart with the file; the known dual-sink semantics are unchanged.

## Related Docs

- `docs/audits/SETTINGS_ARCHITECTURE_2026-07-07.md :: F5`
- `docs/EVENTS.md` (`settings.write.receipt` topic)

## Related GitHub Issues

One implementation issue. TCD hint: sonnet / medium — extends an existing, well-tested receipt
mechanism along known write paths.
