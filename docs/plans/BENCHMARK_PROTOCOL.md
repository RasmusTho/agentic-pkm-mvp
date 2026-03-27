State: Proposed — measurement-only benchmark protocol for the PKM runtime.
# PKM Runtime Benchmark Protocol

**Status**: Proposed
**Track**: v5.6 Track 6 (docs-first backlog)
**Authority**: Defines metric names, capture methods, scenario format, and repeatable test protocol for runtime drift measurement. No thresholds enforced.

---

## Purpose

Establish a standardized, repeatable measurement protocol for the canonical PKM runtime chain so that drift, regression, and storage/model profile comparisons are evidence-led rather than speculative. This protocol is measurement-only: no latency thresholds are enforced, no CI gates are blocked, and no storage migration decisions are made based on these numbers.

The protocol complements the existing fitness infrastructure (`app/fitness/`, `ops/quality/baselines.yaml`) by adding scenario-tagged runtime benchmarks that capture end-to-end pipeline timing across different deployment profiles.

---

## Canonical Chain Metrics

The canonical runtime chain is: vault note change -> watcher tick -> DB outbox write -> worker pickup -> index write -> ASK query -> panel intent -> promote done. Each segment is measured independently where instrumentation is feasible.

| Metric Name | Unit | What It Measures | Capture Method |
|---|---|---|---|
| `watcher_tick_ms` | ms | Time for one watcher registry tick to detect changes and emit events | Wall-clock around `registry.tick()` |
| `outbox_write_ms` | ms | Time from ingest completion to outbox event persistence | Wall-clock around outbox writer call |
| `worker_pickup_ms` | ms | Time from outbox event creation to worker dequeue | Timestamp delta: event `created_at` vs worker `dequeued_at` |
| `index_write_ms` | ms | Time for a single document to be embedded and written to vector index | Wall-clock around embed + upsert |
| `ask_query_ms` | ms | End-to-end ASK/hybrid search latency for a single query | Wall-clock around `hybrid_search()` call |
| `panel_intent_ms` | ms | Time for panel agent to produce an intent from a note | Wall-clock around panel agent decision |
| `promote_done_ms` | ms | Time from `promote.intent.created` to `promote.done` | Timestamp delta between events |
| `ingest_full_ms` | ms | End-to-end time: note file on disk to indexed in vector store | Wall-clock around full ingest pipeline |

### Notes on capture feasibility

- **Phase 1 (benchmark runner)**: `ingest_full_ms`, `index_write_ms`, and `ask_query_ms` are directly measurable with the in-process benchmark runner using seed data and the memory backend.
- **Phase 2 (runtime instrumentation)**: `watcher_tick_ms`, `outbox_write_ms`, `worker_pickup_ms`, `panel_intent_ms`, and `promote_done_ms` require runtime event timestamps or explicit instrumentation in the watcher/worker/promotion chain. These are defined here for future capture but are not required for the initial benchmark runner.

---

## Scenario Format

Each benchmark run is tagged with a scenario triple that enables comparison across deployment profiles.

### Tags

| Tag | Values | Description |
|---|---|---|
| `storage_profile` | `memory`, `pg` | Which store backend is active |
| `runtime_placement` | `local`, `docker`, `colima` | Where the runtime processes execute |
| `model_profile` | `mock`, `local`, `cloud` | LLM/embedding provider class |

### Seed Data

Benchmark runs use the golden vault test seed at `docs/examples/vault_test_seed/`. This provides deterministic, version-controlled input that produces repeatable results across runs.

Files in the seed pack:
- `evergreen-strategy.md` — standard evergreen note with AI panel section
- `mixed-actions.md` — note with multiple action types
- `reflection-journal.md` — journal-style note
- `summary-request.md` — note requesting summarization
- `unknown-action.md` — note with unrecognized action type
- `manual-policy.md` — note with manual policy gate

---

## Output Format

The benchmark runner emits structured JSON to stdout.

```json
{
  "run_id": "uuid",
  "timestamp": "ISO-8601",
  "scenario": {
    "storage_profile": "memory",
    "runtime_placement": "local",
    "model_profile": "mock"
  },
  "metrics": [
    {
      "name": "ingest_full_ms",
      "value_ms": 42.7,
      "tags": {
        "storage_profile": "memory",
        "runtime_placement": "local",
        "model_profile": "mock",
        "seed_file": "evergreen-strategy.md"
      },
      "timestamp": "ISO-8601"
    }
  ],
  "warnings": ["panel_intent_ms skipped: panel agent not available"]
}
```

### Field definitions

- `run_id`: UUID v4, unique per invocation.
- `timestamp`: ISO-8601 UTC time of run start.
- `scenario`: The tag triple for this run.
- `metrics`: Array of individual measurements. Each has a canonical `name` from the table above, `value_ms` in milliseconds, `tags` (scenario triple plus any per-measurement context), and `timestamp`.
- `warnings`: Array of human-readable strings for metrics that were skipped due to unavailable services.

---

## Repeatable Test Protocol

### Prerequisites

- Python environment with project dependencies installed.
- Seed vault files present at `docs/examples/vault_test_seed/`.
- For `memory` profile: no external services needed.
- For `pg` profile: PostgreSQL accessible via `DATABASE_URL`.
- For `local` model profile: Ollama or equivalent running.
- For `cloud` model profile: API keys configured.

### CLI invocation

```bash
python -m ops.benchmarks.run_benchmark \
  --storage-profile memory \
  --runtime-placement local \
  --model-profile mock \
  --seed-dir docs/examples/vault_test_seed \
  --output results.json
```

All flags have sensible defaults (`memory`, `local`, `mock`). Output goes to stdout unless `--output` is specified.

### Determinism requirements

- Use `STORE_BACKEND=memory` for the memory profile.
- Use `LLM_PROVIDER=mock` for the mock model profile.
- Seed data is fixed and version-controlled.
- Each run gets a fresh store instance (no leftover state).

---

## Baseline Data Criteria

Baseline data is considered established when:

1. **Minimum runs**: At least 5 completed runs exist for the same scenario triple.
2. **Variance threshold**: Coefficient of variation (CV = stddev / mean) is below 50% for each metric within that scenario.
3. **No structural failures**: All 5+ runs completed without errors (warnings for skipped metrics are acceptable).

Until baseline data criteria are met for a scenario, that scenario is flagged as `baseline_pending` and no comparisons are drawn. This is informational only; no CI gates are affected.

---

## Integration with Existing Fitness Infrastructure

This protocol does NOT replace or modify:
- `app/fitness/report.py` — continues to emit `CI SUMMARY` lines and enforce `GATES.ok`
- `ops/quality/baselines.yaml` — continues to hold latency/eval/relation thresholds
- `app/fitness/metrics.py` — QAS-003 and QAS-010 remain the CI-enforced latency probes

The benchmark runner is a separate, complementary tool:
- Fitness report = CI gate enforcement (fast, in-process, memory backend)
- Benchmark runner = drift measurement across profiles (slower, scenario-tagged, JSON output)

When enough baseline data exists, benchmark metrics may inform future updates to `baselines.yaml` thresholds, but that decision is explicit and human-driven.

---

## Runner location

`ops/benchmarks/run_benchmark.py` — minimal CLI entry point with argparse.

---

## Future extensions (out of scope for Track 6)

- Runtime instrumentation for watcher/worker/promotion timestamp capture.
- Automated baseline comparison (current run vs stored baselines).
- CI integration as an informational annotation (not a gate).
- Storage migration cost/benefit analysis using benchmark data.
- Grafana/JSON-lines export for trend visualization.
