State: Active — canonical benchmark protocol for PKM runtime drift measurement.
# PKM Runtime Benchmark Protocol

**Status**: Active
**Track**: v5.6 Track 6 — PKM runtime/storage + model benchmark track
**Authority**: Defines standardized metric names, tag dimensions, scenario format, output schema, and repeatable test protocol for runtime drift measurement. No latency thresholds are enforced; no CI gates are blocked.

---

## Purpose

Establish a standardized, repeatable measurement protocol for the canonical PKM runtime pipeline so that storage/model profile comparisons and drift observations are evidence-led rather than speculative. This protocol is **measurement-only** in its initial phase:

- No latency thresholds are enforced.
- No CI gates are added until sufficient baseline data exists.
- No storage migration decisions are made on the basis of these numbers until a baseline data criteria is met.

The protocol complements the existing fitness infrastructure (`app/fitness/`, `ops/quality/baselines.yaml`) by adding scenario-tagged runtime benchmarks that capture end-to-end pipeline timing across different deployment configurations.

---

## Canonical Pipeline and Metric Names

The canonical PKM runtime chain is:

```
vault note change
  → watcher tick
  → DB outbox write
  → worker pickup
  → index write
  → ASK query / panel intent / promote done
```

### Standardized metric names

| Metric Name | Unit | What It Measures | Capture Method |
|---|---|---|---|
| `watcher.event.latency_ms` | ms | Time for one watcher registry tick to detect a vault change and emit an event | Wall-clock around `registry.tick()` |
| `outbox.write.latency_ms` | ms | Time from ingest completion to outbox event persistence | Wall-clock around outbox writer call |
| `worker.process.latency_ms` | ms | Time from outbox event creation to worker dequeue and processing completion | Timestamp delta: event `created_at` vs worker completion |
| `index.write.latency_ms` | ms | Time for a single document to be embedded and written to the vector index | Wall-clock around embed + upsert |
| `ask.query.latency_ms` | ms | End-to-end hybrid search latency for a single query | Wall-clock around `hybrid_search()` |
| `panel.intent.latency_ms` | ms | Time for the panel agent to produce an intent from a note | Wall-clock around panel agent decision call |
| `promote.latency_ms` | ms | Time from `promote.intent.created` to `promote.done` | Timestamp delta between outbox events |
| `ingest_full_ms` | ms | End-to-end time: note file on disk to indexed in vector store | Wall-clock around full ingest pipeline |

**Naming convention**: dot-separated hierarchy (`stage.operation.latency_ms`). The `ingest_full_ms` name is a legacy alias for the end-to-end path and is kept for backward compatibility with the runner output.

### Phase 1 vs Phase 2 feasibility

- **Phase 1 (benchmark runner, current)**: `ingest_full_ms`, `index.write.latency_ms`, and `ask.query.latency_ms` are directly measurable with the in-process benchmark runner using seed data and the memory backend. The runner in `ops/benchmarks/run_benchmark.py` captures these today under the legacy names `ingest_full_ms`, `index_write_ms`, and `ask_query_ms`.
- **Phase 2 (runtime instrumentation, future)**: `watcher.event.latency_ms`, `outbox.write.latency_ms`, `worker.process.latency_ms`, `panel.intent.latency_ms`, and `promote.latency_ms` require runtime event timestamps or explicit instrumentation in the watcher/worker/promotion chain. These metric names are defined here for future capture.

---

## Tag Dimensions

Every benchmark sample must carry a scenario triple. This enables filtering and comparison across deployment profiles.

| Tag | Values | Description |
|---|---|---|
| `storage_profile` | `ssd`, `external`, `memory`, `pg` | Storage backend or device class |
| `runtime_placement` | `local`, `docker`, `colima` | Where the runtime processes execute |
| `model_profile` | `mock`, `local`, `cloud` | LLM/embedding provider class |

The `memory` and `pg` storage profile values are used in the benchmark runner (in-process). The `ssd` and `external` values are reserved for future runtime instrumentation where the physical storage device matters for latency analysis.

---

## Output Schema

The benchmark runner and `record_sample.py` emit JSON. Each run produces one top-level object per invocation:

```json
{
  "run_id": "<uuid-v4>",
  "timestamp": "<ISO-8601 UTC>",
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
        "seed_count": "5"
      },
      "timestamp": "<ISO-8601 UTC>"
    },
    {
      "name": "index_write_ms",
      "value_ms": 8.3,
      "tags": {
        "storage_profile": "memory",
        "runtime_placement": "local",
        "model_profile": "mock",
        "samples": "8"
      },
      "timestamp": "<ISO-8601 UTC>"
    }
  ],
  "warnings": ["panel.intent.latency_ms skipped: panel agent not available"]
}
```

### Field definitions

- `run_id`: UUID v4, unique per invocation.
- `timestamp`: ISO-8601 UTC time of run start.
- `scenario`: The tag triple for this run.
- `metrics`: Array of individual measurements. Each has a canonical `name`, `value_ms` in milliseconds, `tags` (scenario triple plus any per-measurement context), and `timestamp`.
- `warnings`: Human-readable strings for metrics that were skipped due to unavailable services or missing instrumentation.

### Baseline JSONL format

Accumulated runs are stored as newline-delimited JSON (JSONL) in `ops/benchmarks/baselines/`. Each line is one complete run object as above. This format allows incremental appending without rewriting existing data.

---

## Scenario Definitions

Scenarios are defined as YAML files in `ops/benchmarks/scenarios/`. Each scenario file specifies the parameters for a benchmark run and documents the intent of that scenario.

See `ops/benchmarks/scenarios/` for the concrete scenario files.

### Scenario YAML schema

```yaml
name: <scenario-name>
description: <human-readable description>
seed_dir: <path relative to repo root>
storage_profile: <memory|pg|ssd|external>
runtime_placement: <local|docker|colima>
model_profile: <mock|local|cloud>
notes: <optional free text>
```

---

## Repeatable Test Protocol

### Prerequisites

- Python environment with project dependencies installed (`pip install -r requirements.txt`).
- Seed vault files present at `docs/examples/vault_test_seed/`.
- For `memory` profile: no external services needed.
- For `pg` profile: PostgreSQL accessible via `DATABASE_URL`.
- For `local` model profile: Ollama running locally.
- For `cloud` model profile: `ANTHROPIC_API_KEY` configured.

### Running a benchmark scenario

```bash
# Memory backend, local runtime, mock model (no external deps)
python -m ops.benchmarks.run_benchmark \
  --storage-profile memory \
  --runtime-placement local \
  --model-profile mock \
  --seed-dir docs/examples/vault_test_seed \
  --output ops/benchmarks/baselines/run_$(date +%Y%m%dT%H%M%S).json

# Append to a JSONL accumulator
python ops/benchmarks/record_sample.py \
  --storage-profile memory \
  --runtime-placement local \
  --model-profile mock \
  --seed-dir docs/examples/vault_test_seed \
  --output ops/benchmarks/baselines/samples.jsonl
```

### Determinism requirements

- Use `STORE_BACKEND=memory` for the memory profile to avoid leftover state.
- Use `LLM_PROVIDER=mock` for the mock model profile.
- Seed data is fixed and version-controlled; do not modify seed files mid-collection.
- Each benchmark run creates a fresh store instance.
- Record the host machine and OS version in the scenario tags when collecting hardware-specific samples.

### Sample size guidance

| Phase | Minimum runs per scenario | Purpose |
|---|---|---|
| Exploration | 1–4 | Smoke-check instrumentation |
| Baseline establishment | 5+ | Enough to compute mean and CV |
| Comparison ready | 10+ | Stable enough for profile comparisons |

### Baseline data criteria

Baseline data is considered established for a scenario triple when:

1. At least 5 completed runs exist for that scenario triple.
2. Coefficient of variation (CV = stddev / mean) is below 50% for each metric.
3. All 5+ runs completed without structural failures (warnings for skipped metrics are acceptable).

Until these criteria are met, that scenario is `baseline_pending`. No comparisons are drawn and no CI annotations are added.

---

## Integration with Existing Fitness Infrastructure

This protocol does NOT replace or modify:

- `app/fitness/report.py` — continues to emit `CI SUMMARY` lines and enforce `GATES.ok`
- `ops/quality/baselines.yaml` — continues to hold latency/eval/relation CI thresholds
- `app/fitness/metrics.py` — QAS-003 and QAS-010 remain the CI-enforced latency probes
- `app/eval/benchmark.py` — `BenchmarkSuite` framework for decorator-based scenario registration

The benchmark runner is a separate, complementary tool:

| Tool | Purpose | Gate? |
|---|---|---|
| `app/fitness/report.py` | CI gate enforcement (fast, memory, in-process) | Yes — fails CI on regression |
| `ops/benchmarks/run_benchmark.py` | Drift measurement across profiles (scenario-tagged, JSON out) | No — measurement only |
| `ops/benchmarks/record_sample.py` | Append one run to a JSONL accumulator | No — data collection only |

When enough baseline data exists, benchmark metrics may inform future updates to `baselines.yaml` thresholds, but that decision is explicit and human-driven.

### Future fitness hook

The natural integration point for continuous benchmark collection is `app/fitness/__init__.py` or a new `app/fitness/benchmark_hook.py`. When the Phase 2 instrumentation is in place, runtime metric samples can be emitted from the watcher/worker/promotion chain using the same JSON schema defined here. The fitness module already has the infrastructure for emitting structured metrics; benchmark collection would add a JSONL sink alongside the existing CI summary sink.

---

## File locations

| Path | Purpose |
|---|---|
| `docs/benchmarks/BENCHMARK_PROTOCOL.md` | This document — canonical protocol reference |
| `docs/plans/BENCHMARK_PROTOCOL.md` | Historical plan document (superseded by this file) |
| `ops/benchmarks/run_benchmark.py` | CLI benchmark runner |
| `ops/benchmarks/record_sample.py` | Append-to-JSONL helper |
| `ops/benchmarks/scenarios/` | Scenario YAML definitions |
| `ops/benchmarks/baselines/` | Accumulated run data (not tracked in git) |
| `ops/benchmarks/README.md` | Operator instructions |

---

## Out of scope for initial phase

- Automated baseline comparison (current run vs stored baselines).
- CI integration as an informational annotation.
- Storage migration cost/benefit analysis.
- Grafana / JSON-lines trend visualization.
- Runtime instrumentation for watcher/worker/promotion timestamp capture (Phase 2).
