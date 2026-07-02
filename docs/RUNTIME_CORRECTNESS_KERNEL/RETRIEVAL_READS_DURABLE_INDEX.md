---
name: Retrieval Reads Durable Index
description: Retrieval serves from store_vector_index; the in-memory hybrid store becomes a cache-through rebuilt from the durable index; JSONL fan-in is demoted to pure audit
task_id: KERNEL-05
source_anchor: "docs/audits/SYSTEM_REDESIGN_CORRECTNESS_KERNEL_2026-07-02.md :: CW-1, I-D3"
parent_capability: RUNTIME_CORRECTNESS_KERNEL
prerequisites: [KERNEL-03, KERNEL-04]
depends_on: [KERNEL-03, KERNEL-04]
can_parallelize_with: []
---

# Retrieval Reads Durable Index

## Purpose

Retrieval currently serves from an in-memory hybrid store (`app/retrieval/hybrid.py`, module-level
`_STORE: MemoryHybridStore`) that is fed by a **best-effort, never-block** fan-in from the JSONL
append path (`app/index/outbox.py :: append_jsonl()`, approx. lines 45–67 at audit time — the
`try/except Exception: pass` that calls `get_store().add_document(...)`). Failures are silently
swallowed, so what is retrieved diverges from what is durable in `store_vector_index`. Audit
invariant **I-D3**: no serving substrate may hold state not reconstructible from durable stores —
the in-memory store must be a *cache* of the durable index, never an independent truth (CW-1).

## What This Task Does

- Make `store_vector_index` (via `app/stores/__init__.py :: get_vector_index()`, `PgVectorIndex` in
  `app/stores/pg.py`) the single truth for retrieval. `MemoryHybridStore` becomes a cache-through:
  populated only by a load/rebuild from the durable index (at startup and on explicit rebuild),
  never independently written from the ingest/JSONL path.
- Remove the fan-in `get_store().add_document(...)` block in `app/index/outbox.py`; the JSONL file
  stays as a pure audit log (its `append_jsonl` still writes the line, minus the retrieval side
  effect). Migrate/remove the other ad-hoc `add_document` write paths so the *only* population of
  the retrieval store is the durable-index load: `app/ingest/vault_alpha.py:568`,
  `app/api/routes/ask.py:43`, `app/cli/alpha_human_flows.py:126`, `app/cli/smoke.py` (`set_documents`).
- Add a rebuild entrypoint (e.g. `app/retrieval/hybrid.py :: rebuild_from_durable_index()`) that
  loads rows from `get_vector_index()` into `_STORE`; call it at process/store init so retrieval is
  correct after a cold start with an empty in-process cache.
- Per cross-task invariant #3 (removal-follows-rewiring), no read path may be orphaned: `hybrid_search`
  and its callers (`app/retrieval/capability.py`, `app/agents/qa/agent.py`) keep working.

## Concretely

```bash
pytest -q tests/retrieval/test_retrieval_durable_equivalence.py
pytest -q -m pg tests/retrieval/test_retrieval_durable_equivalence.py   # pg-marked equivalence
```

The equivalence test upserts vectors to `store_vector_index`, runs `hybrid_search`, discards the
in-process cache (simulating a restart), rebuilds from the durable index, and asserts identical
result ordering and ids — proving no volatile truth.

## Why This Matters

Split truth is the root of #2314's "live retrieval disconnected from durable PgVectorIndex" and of
#2242-class "consumes nothing" incidents being invisible. Once retrieval reads the durable index,
absence of recall becomes diagnosable (index doctor) instead of silent.

## Acceptance Criteria

- [ ] Kill-and-restart equivalence: retrieval results are identical before and after discarding the
      in-process cache and rebuilding from `store_vector_index` (no volatile truth).
      Verify: `tests/retrieval/test_retrieval_durable_equivalence.py::test_results_survive_restart`
- [ ] Fan-in removed: no code path adds documents to the retrieval store except the durable-index
      load/rebuild. An architecture test asserts the only caller of `add_document`/`set_documents`
      is the rebuild path.
      Verify: `tests/retrieval/test_retrieval_durable_equivalence.py::test_no_fanin_writers`
- [ ] Enforcement AC: the rebuild is driven from the production init call site — the test asserts
      `rebuild_from_durable_index` is invoked from store/process initialization, not called only in
      the test.
      Verify: `tests/retrieval/test_retrieval_durable_equivalence.py::test_rebuild_wired_at_init`
- [ ] Index doctor reports zero retrieval-vs-index divergence on a synced fixture.
      Verify: `tests/index/test_index_doctor_route.py::test_no_retrieval_index_divergence`

## How to Verify (Pre-Merge)

1. `pytest -q tests/retrieval/test_retrieval_durable_equivalence.py tests/index/test_index_doctor_route.py`
2. Full `pytest -q -m "not pg"` (hot-path change), plus `pytest -q -m pg tests/retrieval/`
   against local Postgres (`make db-up`), plus
   `RUN_INTEGRATED_RUNTIME_UAT=1 pytest -q -m uat_integrated_runtime` (retrieval is on the ASK hot path).
3. `ruff check app tests`.

## Out of Scope

- Lexical mirror + hybrid-fusion refinement — that half of #2314 W4-RET-01 stays with the epic.
- Provenance stamp fields on the vector rows (KERNEL-06).
- Store backend resolution / legacy writer removal (KERNEL-03) and DDL migration (KERNEL-04),
  which this task depends on.

## Related Docs

- `docs/audits/SYSTEM_REDESIGN_CORRECTNESS_KERNEL_2026-07-02.md :: CW-1, I-D3`
- `docs/EMBEDDINGS.md`, `docs/ARCHITECTURE.md` (update the retrieval-truth description at promotion)
- `docs/RAG` / epic #2314 spec surfaces

## Related GitHub Issues

**This task delivers the "reconcile the in-memory/durable split" half of #2314's deferred stub
W4-RET-01.** The lexical-mirror + hybrid-fusion half stays with epic #2314. The issue created from
this spec MUST comment on #2314 linking the delivery (epic stop-condition honored; no parallel hub).
TCD hint: Opus / high effort (retrieval hot path, architecture-bearing — single-truth cutover with
a restart-equivalence proof).
