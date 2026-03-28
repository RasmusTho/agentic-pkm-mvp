State: Reference guide for the v5.6 forward-line Quality Wave acceptance stack.
# Quality Wave: v5.6 Acceptance Evaluation Stack

Quality Wave is a comprehensive evaluation framework proving that the v5.6 forward line is ready for broader LangGraph and orchestrator rollout.

**Status**: All phases must PASS sequentially (A→B→C→D→E) before Phase F gates.

## Overview

Quality Wave is organized into 6 sequential phases:

| Phase | File | Purpose | Gate |
|-------|------|---------|------|
| **A** | `tests/quality_wave/test_event_chain.py` | Event chain contracts (trace_id propagation, idempotency) | Canonical envelope; trace_ids propagate through ingest→index→panel→promote chain |
| **B** | `tests/quality_wave/test_golden_vault.py` | Golden vault + seeded snapshots (reproducibility) | Golden vault loads deterministically; expected_outcomes.json matches |
| **C** | `tests/quality_wave/test_metamorphic_runs.py` | Stability across parameter changes (ingest interval, watcher ticks, store backend) | Same input + different params → same output |
| **D** | `tests/quality_wave/test_cold_rebuild.py` | Cold rebuild from empty DB (lossless, idempotent) | Rebuild matches original; no data loss |
| **E** | `tests/quality_wave/test_fitness_gates.py` | Fitness gates (counters, idempotence, no duplicates) | Counter consistency; event_id dedup; watcher idempotency |
| **F** | `ops/quality/acceptance_test.py` | Scripted UAT harness (end-to-end) | Full system passes 8-step acceptance criteria; CI SUMMARY GATES ok=True |

## Running Quality Wave Tests

### Quick Start

```bash
# Run all phases in order
pytest tests/quality_wave/ -v

# Run specific phase
pytest tests/quality_wave/test_event_chain.py -v          # Phase A
pytest tests/quality_wave/test_golden_vault.py -v         # Phase B
pytest tests/quality_wave/test_metamorphic_runs.py -v     # Phase C
pytest tests/quality_wave/test_cold_rebuild.py -v         # Phase D
pytest tests/quality_wave/test_fitness_gates.py -v        # Phase E

# Run Phase F UAT harness
python3 ops/quality/acceptance_test.py --vault docs/examples/vault_test_seed/ --verbose

# Full pipeline (all phases)
pytest tests/quality_wave/ -v && python3 ops/quality/acceptance_test.py --vault docs/examples/vault_test_seed/
```

### Disable Postgres Tests

Quality Wave tests default to memory-only stores (marked with `@pytest.mark.not_pg`):

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest tests/quality_wave/ -v -m "not pg"
```

## Phases in Detail

### Phase A: Event Chain Contracts

**Location**: `tests/quality_wave/test_event_chain.py`

**Purpose**: Validate the canonical event envelope and trace_id propagation.

**Key Tests**:
- Event envelope has all required fields: `event`, `event_id`, `trace_id`, `source`, `timestamp`, `payload`, `meta`
- `trace_id` is unique per operation (UUID v4)
- `event_id` is unique per event (UUID v4, or provided)
- Single `trace_id` propagates through entire chain:
  - `ingest.vault.changed` → `ingest.object.created` → `index.embedding.requested` → `index.embedding.created`
  - `panel.intent.created` → `panel.intent.executing` → `promote.intent.created` → `promote.done` → `panel.intent.executed`
- Event ordering is preserved by timestamp
- Duplicate event_ids can be detected (for Phase E dedup)

**Gate**: All events conform to canonical envelope; trace_ids propagate consistently.

**Exit Criteria**:
```
test_event_has_required_fields PASSED
test_trace_id_can_be_provided PASSED
test_single_trace_id_through_ingest_chain PASSED
test_vault_changed_to_embedding_created_chain PASSED
test_panel_to_promotion_chain PASSED
```

---

### Phase B: Golden Vault + Seeded Snapshots

**Location**: `tests/quality_wave/test_golden_vault.py`

**Golden Vault**: `docs/examples/vault_test_seed/`
- `Note_1.md` — Simple note (no links)
- `Note_2.md` — Note with links to other notes
- `2_Cards/Concept.md` — Promoted concept card
- `Workbench/Draft.md` — Draft for promotion tests
- `expected_outcomes.json` — Snapshot of expected metrics

**Purpose**: Provide deterministic test data for reproducible ingest tests.

**Key Tests**:
- Golden vault files exist and are loadable
- All notes have UUIDs and frontmatter
- `expected_outcomes.json` is valid and complete
- Golden vault content is deterministic (same input → same output, always)
- Expected counts match: 5 notes, 5 objects, 5 embeddings, 2 relations

**Gate**: Golden vault is deterministic and reproducible.

**Expected Outcomes**:
```json
{
  "ingest_metrics": {
    "total_notes": 5,
    "objects_created": 5,
    "embeddings_created": 5
  },
  "object_counts": {
    "total": 5,
    "by_review_state": {"inbox": 2, "reviewed": 1, "promoted": 1, "unknown": 1},
    "by_kind": {"note": 4, "card": 1}
  }
}
```

---

### Phase C: Metamorphic Runs

**Location**: `tests/quality_wave/test_metamorphic_runs.py`

**Purpose**: Prove output is stable regardless of parameter variations.

**Metamorphic Relation**: Same input + different parameters → same processed state.

**Parameter Variations Tested**:
1. **INGEST_INTERVAL**: 1 sec (aggressive polling) vs 10 sec (lazy polling)
   - Same vault → same object count, embedding count
2. **MAX_WATCHER_TICKS**: 5 (tight limit) vs 20 (generous limit)
   - Same vault → same processed count
3. **STORE_BACKEND**: memory vs postgres
   - Same operations → same counts (idempotent writes protect against duplication)
4. **EMBEDDING_MODEL**: text-embedding-3-small vs text-embedding-3-large
   - Same vault → same embedding COUNT (values differ, but count is stable)

**Key Tests**:
- Ingest with INTERVAL=1 yields same counts as INTERVAL=10
- Watcher with TICKS=5 yields same processed count as TICKS=20
- Memory and Postgres store backends yield same counts
- Idempotency is preserved across parameter variations
- Vector indices are stable across embedding model changes

**Gate**: Metamorphic relations hold; output stable across parameters.

**Exit Criteria**:
```
test_metamorphic_relation_ingest_interval PASSED
test_metamorphic_relation_watcher_ticks PASSED
test_metamorphic_relation_store_backend PASSED
test_metamorphic_preserves_idempotency PASSED
```

---

### Phase D: Cold Rebuild Coverage

**Location**: `tests/quality_wave/test_cold_rebuild.py`

**Purpose**: Prove lossless reconstruction from empty DB + existing companion notes.

**Scenario**:
- DB is empty or corrupted
- Companion notes exist in `vault/_system/companions/<uuid>.md` (source of truth)
- Cold rebuild re-populates DB from companions

**Key Tests**:
- Start with empty DB, ingest golden vault
- Rebuilt DB matches original (all counts match)
- Object kind distribution preserved
- Rebuilding twice is idempotent (first rebuild = second rebuild)
- Relations are indexed correctly
- No data loss (lossless)

**Gate**: Cold rebuild is lossless and idempotent.

**Concrete Workflow**:
1. Verify empty DB
2. Load companions from vault
3. Create objects from companions
4. Generate embeddings
5. Index relations
6. Verify metrics match expected_outcomes.json

**Exit Criteria**:
```
test_cold_rebuild_workflow_empty_to_full PASSED
test_rebuild_matches_original_count PASSED
test_rebuild_once_vs_twice PASSED (idempotent)
test_rebuild_relations_idempotent PASSED
```

---

### Phase E: Fitness Gates

**Location**: `tests/quality_wave/test_fitness_gates.py`

**Purpose**: Validate that the system reports accurate telemetry and maintains invariants.

**Gates**:
1. **Counter Consistency**
   - `ingest_runs` increments correctly
   - `panel_runs` increments correctly
   - `promote.intent.created` matches actual intents
   - `object_count` == `embedding_count` (1:1 correspondence)

2. **Event Dedup**
   - All event_ids are unique
   - Duplicate event_ids are rejected
   - `trace_id` is NOT used for dedup (only `event_id`)

3. **Watcher Idempotency**
   - Running watcher twice on same vault → identical state
   - No duplicate events on double run

4. **Heartbeat Signals**
   - Watcher heartbeat within bounds (recent)
   - Worker heartbeat within bounds

5. **Concurrency Guards**
   - Event dedup guard prevents duplicate processing
   - Optimistic locks prevent concurrent writes
   - Dedup queue prevents duplicate watcher runs

6. **Status Endpoint**
   - Reports all required counters
   - JSON-serializable output

**Gate**: All fitness gates green; CI SUMMARY GATES ok=True.

**Exit Criteria**:
```
test_ingest_runs_counter_increments PASSED
test_promote_intents_counter_accuracy PASSED
test_event_id_uniqueness_in_outbox PASSED
test_watcher_run_idempotent PASSED
test_gates_all_present PASSED
test_ci_summary_report PASSED
```

---

### Phase F: Scripted UAT Harness

**Location**: `ops/quality/acceptance_test.py`

**Entry**:
```bash
python3 ops/quality/acceptance_test.py --vault docs/examples/vault_test_seed/ --verbose
```

**Exit**: 0 (pass) or 1 (fail with report)

**8-Step Acceptance Criteria**:
1. **Verify Golden Vault** — Check vault exists, has expected files, notes are valid
2. **Initialize System** — Start watcher, worker, ASK API
3. **Ingest Golden Vault** — Process all notes, create objects and embeddings
4. **Health Checks** — Verify watcher/worker/ASK API are healthy
5. **ASK API Test** — Run sample queries, verify sources returned
6. **Panel Agent Test** — Execute panel actions (e.g., promotion)
7. **Idempotency** — Run ingest again, verify state unchanged
8. **Report Results** — Output metrics and CI SUMMARY GATES

**Metrics Captured**:
- `vault_loaded`: Golden vault verified
- `objects_ingested`: Count of objects created
- `embeddings_created`: Count of embeddings created
- `ask_queries_successful`: Number of ASK queries returning sources
- `panel_actions_executed`: Number of panel actions completed
- `watcher_healthy`, `worker_healthy`, `ask_api_healthy`: Health checks
- `idempotent_run`: State unchanged on second run
- `all_passed`: All 8 steps passed

**CI Summary Line**:
```
CI SUMMARY GATES ok=True
```

**Exit Criteria**:
```
Step 1: Verify Golden Vault ✓
Step 2: Initialize System ✓
Step 3: Ingest Golden Vault ✓ (5 objects, 5 embeddings)
Step 4: Health Checks ✓ (watcher, worker, ask)
Step 5: ASK API Test ✓ (1+ queries successful)
Step 6: Panel Agent Test ✓ (1+ actions executed)
Step 7: Idempotency Verification ✓ (metrics match)
Step 8: Final Report ✓ (all gates pass)
```

---

## Metrics and Baselines

### Golden Vault Baselines

See `ops/quality/baselines.yaml` for authoritative baselines:

```yaml
golden_vault:
  total_notes: 5
  total_objects: 5
  total_embeddings: 5
  total_relations: 2
```

### Metamorphic Baselines

Same metrics expected across all parameter variations:
- INGEST_INTERVAL variations: 5 objects, 5 embeddings
- WATCHER_TICKS variations: 5 objects, 5 embeddings
- STORE_BACKEND variations: 5 objects, 5 embeddings

### Cold Rebuild Baselines

```yaml
cold_rebuild:
  expected_object_count: 5
  expected_embedding_count: 5
  lossless: true
  idempotent: true
```

### Fitness Gates Baselines

```yaml
fitness_gates:
  minimum_ingest_runs: 1
  minimum_objects: 5
  minimum_embeddings: 5
  event_dedup_strict: true
  idempotent_operations: true
```

---

## Test Fixtures (conftest.py)

**Location**: `tests/quality_wave/conftest.py`

### MetricsCollector

Tracks:
- `ingest_runs`, `panel_runs`, `promote_intents_created`, `promote_done`
- `object_count`, `embedding_count`
- `trace_ids_seen` (set of unique trace_ids)

Methods:
- `record_event(event)` — Record event and track trace_id
- `snapshot()` — Return JSON-serializable metrics dict
- `assert_idempotent(other)` — Assert two runs are identical
- `assert_trace_ids_unique()` — Assert no duplicate trace_ids

### EventChain

Tracks:
- `events` — List of OutboxEvent objects
- `trace_id_map` — Dict mapping trace_id → list of event types

Methods:
- `append(event)` — Record event in chain
- `assert_trace_id_consistent(trace_id)` — Assert trace_id exists
- `assert_ordering()` — Assert events ordered by timestamp

### Fixtures

- `metrics` — Provides MetricsCollector instance
- `event_chain` — Provides EventChain instance
- `golden_vault_path` — Path to golden vault directory
- `golden_vault_content` — Dict of {path: content} for all notes
- `expected_outcomes` — Dict of expected metrics from expected_outcomes.json
- `memory_stores` — Dict of {objects, vectors, relations, decisions} in-memory stores
- `deterministic_uuid` — UUID "00000000-0000-0000-0000-000000000001"
- `now_iso` — Fixed ISO timestamp "2025-03-28T12:00:00Z"

---

## CI Integration

### CI Gates

The `.github/workflows/ci-smoke.yaml` and `.github/workflows/ci-lite.yml` jobs parse:

```
CI SUMMARY GATES ok=<bool>
```

Exit non-zero if `ok != true`.

### Required Commands

```bash
# Phase A-E (pytest)
pytest tests/quality_wave/ -v

# Phase F (UAT harness)
python3 ops/quality/acceptance_test.py --vault docs/examples/vault_test_seed/
```

### CI Job Integration

```yaml
- name: Run Quality Wave (Phases A-E)
  run: pytest tests/quality_wave/ -v

- name: Run Quality Wave UAT (Phase F)
  run: python3 ops/quality/acceptance_test.py --vault docs/examples/vault_test_seed/

- name: Check CI Gates
  run: grep "CI SUMMARY GATES ok=True" test-output.log || exit 1
```

---

## Troubleshooting

### Phase A Failures

- **Duplicate event_ids**: Each event should have unique event_id (UUID v4)
- **trace_id not propagating**: Ensure trace_id is passed through entire chain
- **Event ordering wrong**: Events must be ordered by timestamp, not by record order

### Phase B Failures

- **Golden vault not found**: Ensure `docs/examples/vault_test_seed/` exists
- **expected_outcomes.json invalid**: Check JSON syntax and required keys
- **Notes missing UUIDs**: All notes must have `uuid:` in frontmatter

### Phase C Failures

- **Metrics differ across parameters**: Check that idempotent writes prevent duplication
- **Store backend counts differ**: Verify memory and postgres implementations are equivalent
- **Embedding count changes**: Count should be stable even if dimension changes

### Phase D Failures

- **Cold rebuild doesn't match original**: Check companion note loading and object creation
- **Rebuild not idempotent**: Verify upsert operations are idempotent (no duplicates on second run)
- **Relations not indexed**: Check relation linking is correct

### Phase E Failures

- **Duplicate event_ids in outbox**: Implement event dedup guard (track seen event_ids)
- **Counters don't match**: Verify counters are incremented atomically
- **Watcher not idempotent**: Ensure dedup queue prevents duplicate runs

### Phase F Failures

- **System doesn't initialize**: Check watcher, worker, ASK API startup
- **ASK queries return no sources**: Verify embeddings were created and indexed
- **Idempotency fails**: Run ingest again and compare metrics; identify what changed

---

## Forward Line Integration

Quality Wave is a prerequisite gate for:
- **ReasoningFacade rollout** — Proof that telemetry/provenance is deterministic
- **LangGraph expansion** — Gate for adopting LangGraph in additional agents
- **Orchestrator V2** — Prerequisite for experiment flag enablement
- **Watcher auto-run** — Gate for enabling WATCHER_AUTO_EXEC=1

---

## Documentation

- `docs/STATUS.md` — Current operational snapshot (includes Quality Wave status)
- `docs/plans/V56_FORWARD_LINE.md` — v5.6 kickoff (Quality Wave is acceptance gate)
- `docs/ARCHITECTURE.md` — Runtime architecture (event chain, store interfaces)
- `docs/EVENTS.md` — Event envelope contract
- `docs/CONCURRENCY.md` — Concurrency guards (dedup, optimistic lock)

---

## FAQ

**Q: Do I need to run Postgres for Quality Wave?**
A: No. All tests are marked `@pytest.mark.not_pg` and use memory-only stores. Postgres backend is tested as a metamorphic variation, but not required to pass the gate.

**Q: What if Phase C metamorphic tests fail?**
A: This indicates the system is parameter-sensitive. Check for:
- Timing-dependent logic (use deterministic intervals in tests)
- Backend-specific behavior (memory vs postgres should be identical)
- Non-idempotent writes (upsert should be safe to repeat)

**Q: Can I skip Phase F (UAT harness)?**
A: No. Phase F is the final gate proving end-to-end acceptance. All 8 steps must pass.

**Q: How do I add new metrics to track?**
A: 1. Add field to `MetricsCollector` in `conftest.py`, 2. Update `snapshot()` method, 3. Update Phase E fitness gate tests, 4. Update baselines.yaml, 5. Add to Phase F UAT harness.

---

## Success Criteria Summary

✓ Phase A: Event chain idempotent; trace_ids propagate
✓ Phase B: Golden vault reproducible; expected_outcomes match
✓ Phase C: Metamorphic relations hold; output stable across parameters
✓ Phase D: Cold rebuild lossless; no data loss
✓ Phase E: Fitness gates all green; counters consistent
✓ Phase F: UAT harness passes; CI SUMMARY GATES ok=True

**Overall**: Quality Wave PASSED → v5.6 ready for LangGraph/orchestrator rollout.
