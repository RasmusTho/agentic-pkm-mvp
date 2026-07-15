---
name: Deliver Single-Transaction Query Service
description: Ship the minimal production read-only CKM snapshot/query service and CLI JSON adapter that complete the Q1 acceptance gate.
task_id: CKM-MA-Q1B
source_anchor: docs/CKM_MEASUREMENT_AND_ACCESS/README.md :: Accepted architecture decisions
parent_capability: CKM Measurement & Access
prerequisites: [CKM-MA-Q1A]
depends_on: [ESTABLISH_PUBLIC_SNAPSHOT_CONTRACT.md]
can_parallelize_with: []
---

# Deliver Single-Transaction Query Service

## Purpose

Prove the public contract on the real read path. Q1 becomes delivered only when this task produces bounded structured results from one explicit read-only SQLite transaction and exposes them through CLI JSON.

## What This Task Does

- Open existing CKM SQLite state in read-only mode without directory/schema/migration/receipt side effects.
- Produce a snapshot manifest and result inside one explicit read transaction.
- Support exact public-ID lookup and one stable keyset-paginated resource scan with hard limits.
- Bind and validate continuation cursors; reject tampering, query mismatch, version mismatch, missing state, and snapshot change.
- Add a thin CLI JSON adapter over transport-neutral DTO/query service modules.

## Concretely

An initial command such as `builderops ckm query capabilities --limit 50 --json` returns a versioned projection envelope. Continuation under unchanged state is gap/overlap free; continuation after any CKM mutation returns typed `snapshot_changed` rather than mixed data.

## Why This Matters

Without one transaction and a read-only connection, the envelope's digest and projection-only promise are false. Without an exemplar keyset listing, the cursor contract remains untested until after consumers depend on it.

## Acceptance Criteria

- [ ] Capability list results and snapshot manifest are produced within one explicit SQLite read transaction.
  Verify: `tests/builderops/ckm/test_query_service.py::test_list_capabilities_uses_one_read_transaction`
- [ ] Exact public-ID lookup and stable total-order keyset continuation return each resource once with no gap/overlap.
  Verify: `tests/builderops/ckm/test_query_service.py::test_exact_id_lookup_and_stable_keyset_continuation`
- [ ] Query execution against missing, unsupported, or valid stores creates no directory/database/schema/migration/receipt and performs no write.
  Verify: `tests/builderops/ckm/test_query_service.py::test_query_path_is_read_only_and_side_effect_free`
- [ ] Cursor tampering, query/version mismatch, and CKM mutation between pages fail with typed refusal and no partial data.
  Verify: `tests/builderops/ckm/test_query_service.py::test_cursor_tampering_and_snapshot_change_refuse`
- [ ] Candidate/confirmed separation, tagged missing values, hard limits, and truncation reason are present on the production result path.
  Verify: `tests/builderops/ckm/test_query_service.py::test_missing_candidate_and_truncation_semantics`
- [ ] CLI JSON serializes the transport-neutral query service without importing Click/CLI concepts into DTOs or service logic.
  Verify: `tests/builderops/ckm/test_query_service.py::test_cli_json_uses_transport_neutral_service`
- [ ] Deterministic semantic output is byte-identical for identical snapshot/query/version inputs modulo declared volatile fields.
  Verify: `tests/builderops/ckm/test_query_service.py::test_same_snapshot_query_and_versions_are_deterministic`
- [ ] Q1 acceptance is marked complete only after Q1a and Q1b receipts exist.
  Verify: parent validation receipt plus doc writeback at `docs/CKM_MEASUREMENT_AND_ACCESS/README.md :: Capability acceptance criteria`

## How to Verify (Pre-Merge)

- `python3 -m pytest -q tests/builderops/ckm/test_query_service.py`
- `python3 -m pytest -q tests/builderops/ckm`
- `ruff check app tests`
- `mypy app`
- CLI smoke over a populated temporary store, including continuation, tampered cursor, changed snapshot, missing DB, and unsupported schema.

## Out of Scope

- Rich filter algebra, subtree queries, batch planning, indexes, or N+1 removal beyond the minimal bound.
- HTTP/UI adapters.
- Metrics, usage observation, general history, ranking, drift, automation, or federation.

## Related Docs

- `docs/CKM_MEASUREMENT_AND_ACCESS/README.md`
- `docs/CKM_MEASUREMENT_AND_ACCESS/ESTABLISH_PUBLIC_SNAPSHOT_CONTRACT.md`

## Related GitHub Issues

Implementation issue #3777 under validation parent #3775, dependency-blocked on #3776. TCD hint: Sol/high or Terra/high; escalate to Sol/xhigh for unresolved transaction, read-only SQLite, cursor, or compatibility risk.
