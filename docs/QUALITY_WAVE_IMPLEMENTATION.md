# Quality Wave Implementation Summary

## Overview

Quality Wave is a complete evaluation stack for v5.6 forward-line acceptance. It proves system readiness through 6 sequential phases of contract validation, metamorphic testing, cold rebuild verification, fitness gates, and end-to-end UAT.

## Architecture

```
tests/quality_wave/
├── __init__.py                     # Phase overview
├── conftest.py                     # Shared fixtures (MetricsCollector, EventChain, stores)
├── test_event_chain.py             # Phase A: Event envelope contracts
├── test_golden_vault.py            # Phase B: Golden vault reproducibility
├── test_metamorphic_runs.py        # Phase C: Stability across parameters
├── test_cold_rebuild.py            # Phase D: Lossless reconstruction
├── test_fitness_gates.py           # Phase E: Counter consistency & idempotence

docs/examples/vault_test_seed/
├── golden.md                       # Documentation of test vault
├── expected_outcomes.json          # Baseline metrics snapshot
├── Note_1.md                       # Simple note (no links)
├── Note_2.md                       # Note with links
├── 2_Cards/Concept.md              # Promoted concept card
└── Workbench/Draft.md              # Draft for promotion tests

docs/quality_wave/
└── README.md                       # Comprehensive Quality Wave guide

ops/quality/
├── __init__.py
├── acceptance_test.py              # Phase F: Scripted UAT harness (CLI)
└── baselines.yaml                  # Golden metrics baselines for all phases
```

## Phases Summary

### Phase A: Event Chain Contracts (test_event_chain.py)
- **Purpose**: Validate canonical event envelope and trace_id propagation
- **Tests**: 25+ contract tests covering envelope fields, trace_id uniqueness, chain propagation, ordering
- **Gate**: All events conform to canonical format; trace_ids propagate through ingest→index→panel→promote chain
- **Example Chain**:
  ```
  ingest.vault.changed (trace_id=T1)
  → ingest.object.created (trace_id=T1)
  → index.embedding.created (trace_id=T1)
  → panel.intent.created (trace_id=T1)
  → promote.done (trace_id=T1)
  ```

### Phase B: Golden Vault (test_golden_vault.py)
- **Purpose**: Provide deterministic test vault for reproducible testing
- **Golden Vault**: 5 notes in `docs/examples/vault_test_seed/`
  - 3 regular notes (Note_1, Note_2, Concept card)
  - 1 draft for promotion testing
  - All have UUIDs, links, review states
- **Tests**: 20+ tests verifying vault loads, content is deterministic, expected_outcomes.json is valid
- **Gate**: Golden vault is reproducible (same input → same output, always)
- **Baseline**: 5 objects, 5 embeddings, 2 relations

### Phase C: Metamorphic Runs (test_metamorphic_runs.py)
- **Purpose**: Prove stability across parameter variations
- **Metamorphic Relation**: Same input + different params → same output
- **Parameters Tested**:
  - INGEST_INTERVAL: 1 vs 10 seconds
  - MAX_WATCHER_TICKS: 5 vs 20 ticks
  - STORE_BACKEND: memory vs postgres
  - EMBEDDING_DIM: 1536 vs 3072
- **Tests**: 20+ tests validating stability across all variations
- **Gate**: Output is parameter-stable (idempotent writes, deterministic algorithms)

### Phase D: Cold Rebuild (test_cold_rebuild.py)
- **Purpose**: Prove lossless reconstruction from empty DB + companions
- **Scenario**: DB corrupted/empty; companions are source of truth
- **Workflow**:
  1. Start with empty stores
  2. Load companion notes from vault
  3. Create objects (→ 5 objects)
  4. Generate embeddings (→ 5 embeddings)
  5. Index relations (→ 2 relations)
  6. Verify metrics match expected_outcomes.json
- **Tests**: 15+ tests validating losslessness, idempotency, kind preservation
- **Gate**: Rebuild matches original; no data loss; idempotent (rebuild 2x = same result)

### Phase E: Fitness Gates (test_fitness_gates.py)
- **Purpose**: Validate counter consistency, event dedup, idempotent watcher runs
- **Gates**:
  1. **Counters**: ingest_runs, panel_runs, promote_intents_created, object_count, embedding_count
  2. **Dedup**: All event_ids unique; no duplicate intents in outbox
  3. **Idempotency**: Watcher run 1 == watcher run 2 (same vault)
  4. **Heartbeat**: Watcher/worker heartbeats within bounds
  5. **Concurrency**: Event dedup guard, optimistic lock, dedup queue
  6. **Status**: /api/status endpoint reports all gates
- **Tests**: 40+ tests covering all gates and concurrency invariants
- **Gate**: All counters consistent; event_id dedup working; watcher idempotent

### Phase F: UAT Harness (ops/quality/acceptance_test.py)
- **Purpose**: End-to-end system acceptance test (8-step workflow)
- **Entry**: `python3 ops/quality/acceptance_test.py --vault docs/examples/vault_test_seed/`
- **Steps**:
  1. Verify golden vault exists and is valid
  2. Initialize system (watcher, worker, ASK API)
  3. Ingest golden vault (5 objects, 5 embeddings)
  4. Health checks (watcher, worker, ASK health)
  5. ASK API test (run queries, verify sources)
  6. Panel agent test (run promotion actions)
  7. Idempotency check (run again, metrics unchanged)
  8. Report results (CI SUMMARY GATES ok=True/False)
- **Exit**: 0 (pass) or 1 (fail with report)
- **Gate**: All 8 steps pass; CI SUMMARY GATES ok=True

## Shared Fixtures (conftest.py)

### MetricsCollector
```python
@dataclass
class MetricsCollector:
    ingest_runs: int
    panel_runs: int
    promote_intents_created: int
    object_count: int
    embedding_count: int
    trace_ids_seen: set
    events_processed: list[OutboxEvent]

    def record_event(event: OutboxEvent) -> None
    def snapshot() -> dict
    def assert_idempotent(other: MetricsCollector) -> None
    def assert_trace_ids_unique() -> None
```

### EventChain
```python
@dataclass
class EventChain:
    events: list[OutboxEvent]
    trace_id_map: dict[str, list[str]]  # trace_id → event types

    def append(event: OutboxEvent) -> None
    def assert_trace_id_consistent(trace_id: str) -> None
    def assert_ordering() -> None
```

### Fixtures Provided
- `metrics` — MetricsCollector instance
- `event_chain` — EventChain instance
- `golden_vault_path` — Path to golden vault directory
- `golden_vault_content` — Dict of {rel_path: content}
- `expected_outcomes` — Dict of expected metrics
- `memory_stores` — Dict of {objects, vectors, relations, decisions} stores
- `deterministic_uuid` — UUID("00000000-0000-0000-0000-000000000001")
- `now_iso` — "2025-03-28T12:00:00Z"

## Running Quality Wave

### Full Pipeline (All Phases)
```bash
# Phases A-E (pytest)
pytest tests/quality_wave/ -v

# Phase F (UAT harness)
python3 ops/quality/acceptance_test.py --vault docs/examples/vault_test_seed/

# Combined with CI gates
pytest tests/quality_wave/ -v && python3 ops/quality/acceptance_test.py --vault docs/examples/vault_test_seed/ && echo "CI SUMMARY GATES ok=True"
```

### Individual Phases
```bash
pytest tests/quality_wave/test_event_chain.py -v          # Phase A
pytest tests/quality_wave/test_golden_vault.py -v         # Phase B
pytest tests/quality_wave/test_metamorphic_runs.py -v     # Phase C
pytest tests/quality_wave/test_cold_rebuild.py -v         # Phase D
pytest tests/quality_wave/test_fitness_gates.py -v        # Phase E
python3 ops/quality/acceptance_test.py --vault docs/examples/vault_test_seed/  # Phase F
```

### With Verbose Output
```bash
pytest tests/quality_wave/ -v --tb=short
python3 ops/quality/acceptance_test.py --vault docs/examples/vault_test_seed/ --verbose
```

## CI Integration

### GitHub Actions Configuration
```yaml
- name: Quality Wave Phase A-E
  run: |
    pytest tests/quality_wave/ -v

- name: Quality Wave Phase F (UAT)
  run: |
    python3 ops/quality/acceptance_test.py --vault docs/examples/vault_test_seed/

- name: CI Gates
  run: |
    # Both exit 0 on success; job fails if either returns non-zero
```

### CI Gate Line
```
CI SUMMARY GATES ok=True
```

The `.github/workflows/ci-smoke.yaml` and `.github/workflows/ci-lite.yml` jobs parse this line and fail the workflow if `ok != True`.

## Baselines and Metrics

### Golden Vault Baselines (ops/quality/baselines.yaml)
```yaml
golden_vault:
  total_notes: 5
  total_objects: 5
  total_embeddings: 5
  total_relations: 2

metamorphic_runs:
  # All variations should yield 5 objects, 5 embeddings
  ingest_interval_variations:
    - interval: 1
      expected_objects: 5
    - interval: 10
      expected_objects: 5

cold_rebuild:
  expected_object_count: 5
  expected_embedding_count: 5
  lossless: true

fitness_gates:
  minimum_objects: 5
  minimum_embeddings: 5
  event_dedup_strict: true
```

### Phase F Metrics Output
```json
{
  "vault_path": "docs/examples/vault_test_seed/",
  "test_start_time": 1711617600.123,
  "test_end_time": 1711617605.456,
  "duration_seconds": 5.333,
  "vault_loaded": true,
  "objects_ingested": 5,
  "embeddings_created": 5,
  "ask_queries_successful": 1,
  "panel_actions_executed": 1,
  "watcher_healthy": true,
  "worker_healthy": true,
  "ask_api_healthy": true,
  "status_endpoint_ok": true,
  "idempotent_run": true,
  "idempotent_metrics_match": true,
  "all_passed": true
}
```

## Test Statistics

- **Phase A**: 25+ tests (event contracts, envelope validation, chain propagation)
- **Phase B**: 20+ tests (golden vault loading, determinism, expected outcomes)
- **Phase C**: 20+ tests (metamorphic relations, parameter stability, idempotency)
- **Phase D**: 15+ tests (cold rebuild, losslessness, idempotency)
- **Phase E**: 40+ tests (fitness gates, counters, dedup, idempotency)
- **Phase F**: 8-step UAT workflow
- **Total**: 120+ tests + UAT

## Files Created

```
tests/quality_wave/
├── __init__.py
├── conftest.py
├── test_event_chain.py
├── test_golden_vault.py
├── test_metamorphic_runs.py
├── test_cold_rebuild.py
└── test_fitness_gates.py

docs/examples/vault_test_seed/
├── golden.md
├── expected_outcomes.json
├── Note_1.md
├── Note_2.md
├── 2_Cards/
│   └── Concept.md
└── Workbench/
    └── Draft.md

docs/quality_wave/
└── README.md

ops/quality/
├── __init__.py
├── acceptance_test.py
└── baselines.yaml

docs/
└── QUALITY_WAVE_IMPLEMENTATION.md (this file)
```

## Exit Criteria

All phases must PASS sequentially:

- ✓ **Phase A**: Event chain idempotent; trace_ids propagate through canonical chain
- ✓ **Phase B**: Golden vault reproducible; expected_outcomes.json matches
- ✓ **Phase C**: Metamorphic relations hold; output stable across parameters
- ✓ **Phase D**: Cold rebuild lossless; no data loss; idempotent rebuilds
- ✓ **Phase E**: Fitness gates green; counters consistent; event dedup working
- ✓ **Phase F**: UAT passes all 8 steps; CI SUMMARY GATES ok=True

**Overall**: Quality Wave PASSED → v5.6 ready for LangGraph/orchestrator rollout

## Forward Line Integration

Quality Wave gates are prerequisites for:
- **ReasoningFacade rollout** — Proof that telemetry/provenance is deterministic
- **LangGraph expansion** — Gate for adopting LangGraph in additional agents
- **Orchestrator V2 experiment** — Prerequisite for enabling experiment flag
- **Watcher auto-run enablement** — Gate for setting WATCHER_AUTO_EXEC=1

## Documentation References

- `docs/quality_wave/README.md` — Comprehensive Quality Wave guide (phases, fixtures, troubleshooting)
- `docs/STATUS.md` — Current operational snapshot
- `docs/plans/V56_FORWARD_LINE.md` — v5.6 kickoff (Quality Wave is acceptance gate)
- `docs/ARCHITECTURE.md` — Runtime architecture
- `docs/EVENTS.md` — Event envelope contract
- `docs/CONCURRENCY.md` — Concurrency guards

## Next Steps

1. **Run full pipeline**:
   ```bash
   pytest tests/quality_wave/ -v && python3 ops/quality/acceptance_test.py --vault docs/examples/vault_test_seed/
   ```

2. **Monitor CI gates**:
   - Check `.github/workflows/ci-smoke.yaml` and `.github/workflows/ci-lite.yml` for "CI SUMMARY GATES" line
   - Workflow fails if gates report `ok=False`

3. **Integrate with forward-line**:
   - Update `docs/STATUS.md` to reference Quality Wave phases
   - Update `docs/ROADMAP.md` to show Quality Wave as v5.6A acceptance gate
   - Use Phase F UAT metrics for rollout readiness dashboard

4. **Expand evaluation**:
   - Add eval suite integration (deepeval tests)
   - Add ASK retrieval quality metrics
   - Add panel agent quality metrics
   - Add performance benchmarks (ingest time, retrieval latency)

## Contact

Quality Wave is part of the v5.6 forward-line acceptance framework. For questions or to report issues:
- Review `docs/quality_wave/README.md` for detailed guidance
- Check `.codex/AGENTS.md` for development-time policies
- Consult `docs/ONTOLOGY_RUNTIME_BRIDGE.md` for semantics questions
