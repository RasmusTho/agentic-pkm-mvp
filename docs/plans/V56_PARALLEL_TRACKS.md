State: Proposed — 6 parallel implementation tracks for the v5.6 forward line.
# v5.6 Parallel Implementation Tracks

**Status**: Proposed
**Source**: Roadmap + forward-line dependency chain analysis (2026-03-27)
**Prerequisite**: Quality Wave A–F done; ReasoningFacade UNBLOCKED; Companion Note Parts 1–3 done.

---

## Purpose

Define six concrete, subagent-assignable tracks that advance the v5.6 forward line
while preserving the locked SoT v5.5 baseline contracts. Each track is scoped so that
a single agent can implement it end-to-end (code + tests + doc updates) with minimal
cross-track coordination.

**System purpose alignment**: every track serves the vault-first, event-driven,
single-user PKM runtime. Human-written Markdown notes remain the canonical artifact;
derived stores stay rebuildable; all mutation is governed, mediated, and auditable.

---

## Track 1 — Companion Note Ingest Migration

**Plan ref**: `docs/plans/COMPANION_NOTE_AND_NOTE_CONTEXT.md` Part 4
**Blocks**: Track 2 (legacy cleanup), Track 5 (Panel Agent wiring)

Wire `app/ingest/vault_alpha.py` to write companion notes instead of VaultMirror files.
The companion service (`app/services/companion_note.py`) and healing scenarios (Parts 2–3)
are already shipped.

### Scope
- Replace `_write_mirror()` → `upsert_companion()` (calls `write_companion`)
- Replace `_load_mirror_frontmatter()` → `read_companion()` (flat UUID lookup)
- Replace `_find_mirror_uuid_by_fingerprint()` → `find_companion_by_content_hash()`
- Cold rebuild: check `_system/companions/` not `System/Metadata/VaultMirror`
- Fingerprint skip: compare `content_hash` (scalar) not `ingest_fingerprint` (dict)
- Add `_system/companions/**` to default `ignore_glob` in `app/ingest/config.py`
- Update `app/cli/alpha_human_flows.py`: `note_log_path()` → `companion_path()`

### Tests
- All existing ingest tests pass with companion paths
- Cold rebuild: empty DB + companions present → full rebuild
- Cold rebuild: empty DB + no companions → clean start
- Fingerprint skip: identical content → skip; changed content → re-ingest
- Idempotency: double ingest → same result
- Watcher: companion writes do NOT trigger new watcher events (validate ignore_glob)

### Exit criteria
Zero imports of `note_log` in `vault_alpha.py`. All ingest tests green. Event contracts unchanged.

### Doc updates
- `docs/ARCHITECTURE.md` — note companion path as active (remove "transitional" caveats)

---

## Track 2 — Legacy VaultMirror Cleanup

**Plan ref**: `docs/plans/COMPANION_NOTE_AND_NOTE_CONTEXT.md` Part 5
**Depends on**: Track 1 (ingest migration green)

Remove the now-unused VaultMirror and note_log code paths.

### Scope
- Delete `app/services/note_log.py`
- Delete `tests/services/test_note_log.py`
- Delete `app/services/note_mirror.py` (if no remaining callers)
- Remove any remaining `VaultMirror` or `note_log` imports from active code

### Verification
- `grep -r "note_log" app/` → zero results
- `grep -r "VaultMirror" app/` → zero results (only archive docs)
- `grep -r "note_mirror" app/` → zero results in active code
- Full test suite green

### Exit criteria
No active code references VaultMirror, note_log, or note_mirror.

---

## Track 3 — NoteContext Service

**Plan ref**: `docs/plans/COMPANION_NOTE_AND_NOTE_CONTEXT.md` Part 6
**Parallel with**: Tracks 1–2 (can start after companion service exists, which it does)
**Blocks**: Track 5 (Panel Agent wiring)

Create the runtime context assembler that gives agents structured, multi-surface context
instead of raw 800-char snippets. This is the prerequisite for meaningful agent quality
improvements.

### Scope
Create `app/services/note_context.py` with:

```python
@dataclass
class ContextBudget:
    max_body_chars: int = 2000
    include_relations: bool = True
    include_attachments: bool = True
    include_history: bool = False

@dataclass
class NoteContext:
    uuid: str
    source_ref: str
    content_hash: str
    ingest_state: str
    attachments: list[AttachmentRef]
    frontmatter: dict
    body: str
    outgoing_links: list[str]
    backlinks: list[str]
    classification: dict | None
    executed_actions: list[str]
    kind_policy: dict
    trust_level: str

def build_note_context(
    uuid: str, vault_root: Path, stores, *, budget: ContextBudget | None = None
) -> NoteContext: ...
```

### Tests
- Full assembly from all three surfaces (companion + vault note + runtime stores)
- Budget truncation: body capped at `max_body_chars`
- Missing companion → returns degraded context (classification=None, attachments=[])
- Missing DB record → graceful degradation (classification=None, history=[])

### Exit criteria
Service exists and is tested. No agent uses it yet (wiring is Track 5).

---

## Track 4 — ReasoningFacade + Basic Graph Builder

**Roadmap ref**: Forward-line dependency chain — UNBLOCKED after Quality Wave F
**Blocks**: LangGraph rollout Phases 1–3, Orchestrator V2

This is the critical-path blocker for the broader LangGraph rollout. All LangGraph agents
must route reasoning and tool calls through a shared facade to prevent pattern fragmentation.

### Scope
Create `app/components/reasoning/facade.py`:

- `ReasoningFacade` — unified interface for LLM reasoning calls (chat completions,
  structured output, tool-use) that routes through the existing `app/components/llm/router.py`
- Adds telemetry hooks (trace_id, latency, token counts) for fitness gate integration
- Wraps LangGraph-specific patterns (state reads, conditional edges) into reusable helpers
- Does NOT change existing ASK or PanelAgent wiring — those adopt the facade in later phases

Create `app/components/reasoning/graph_builder.py`:

- `build_agent_graph(agent_name, nodes, edges, state_cls)` — thin builder that standardizes
  how agents construct their LangGraph graphs
- Enforces: every graph has an entry node, a terminal node, telemetry on every edge
- Provides `AgentState` base class with standard fields (trace_id, budget, step_count)

### Tests
- Facade routes calls through LLM router (mock-based)
- Facade emits telemetry events with correct envelope
- Graph builder produces valid LangGraph graphs
- Graph builder rejects invalid topologies (no entry, no terminal)
- AgentState base class serializes/deserializes correctly

### Exit criteria
Facade + graph builder exist and are tested. Existing agents unchanged.
Architecture doc updated to mention ReasoningFacade as the canonical reasoning entry point.

---

## Track 5 — Panel Agent NoteContext Wiring

**Plan ref**: `docs/plans/COMPANION_NOTE_AND_NOTE_CONTEXT.md` Part 7
**Depends on**: Track 1 (ingest migration) + Track 3 (NoteContext service)

Replace the 800-char snippet in Panel Agent with rich NoteContext.

### Scope
Change `app/agents/panel_agent/graph.py` (the `[:800]` truncation):

```python
# Before
f"Note (snippet): {(state.note_content or '')[:800]}"

# After
ctx = build_note_context(state.note_uuid, vault_root, stores, budget=PANEL_BUDGET)
# Build prompt from ctx.frontmatter, ctx.body, ctx.backlinks, ctx.attachments
```

Default Panel budget:
- `max_body_chars=2000`
- `include_relations=True`
- `include_attachments=True`
- `include_history=False`

### Tests
- Panel Agent integration test: agent receives full frontmatter + relation count
- Fallback: if NoteContext build fails, agent degrades gracefully (does not crash)
- Budget enforcement: body content respects `max_body_chars`

### Exit criteria
Panel Agent uses NoteContext. The string `[:800]` is gone from `graph.py`.

---

## Track 6 — PKM Runtime Benchmark Protocol

**Roadmap ref**: Next → "PKM runtime/storage + model benchmark track (docs-first backlog)"
**Parallel with**: All other tracks (pure docs + measurement scaffolding)

Define the measurement protocol for runtime drift metrics before any storage migration
or model-switching decisions. This is a docs-first track that produces the protocol
definition and minimal tooling to start collecting baseline data.

### Scope

Create `docs/plans/BENCHMARK_PROTOCOL.md`:
- Define metric names for: watcher → DB outbox → worker → index → ASK/panel/promote latency chain
- Define scenario-based benchmark format (tagged by storage profile, runtime placement, model profile)
- Specify the repeatable test protocol (CLI-driven, deterministic seed data, output format)
- Define what "baseline data exists" means (minimum N runs, variance thresholds)

Create `ops/benchmarks/run_benchmark.py` (minimal scaffolding):
- CLI entry point that runs the canonical ingest→ASK chain on seed data
- Captures timing for each pipeline stage
- Outputs structured JSON (metric name, value, tags, timestamp)
- Integrates with existing fitness report format (`CI SUMMARY GATES`)

### Tests
- Benchmark runner produces valid JSON output
- Metric names match the protocol spec
- Runner gracefully handles missing services (skip with warning, don't crash)

### Exit criteria
Protocol doc exists. Benchmark runner produces baseline measurements on seed data.
No latency thresholds enforced yet (measurement only). No storage migration decisions.

---

## Sequencing & Parallelism

```
Track 1 (Ingest Migration) ──────────────┐
                                          ├──→ Track 2 (Legacy Cleanup)
Track 3 (NoteContext Service) ────────────┤
                                          └──→ Track 5 (Panel Agent Wiring)

Track 4 (ReasoningFacade) ───────────────────  (independent, critical path)

Track 6 (Benchmark Protocol) ────────────────  (independent, docs-first)
```

**Immediate parallelism** (can start simultaneously):
- Track 1, Track 3, Track 4, Track 6

**Sequential dependencies**:
- Track 2 starts after Track 1 is green
- Track 5 starts after Track 1 + Track 3 are green

**Maximum concurrency**: 4 subagents at launch, then 2 follow-up subagents.

---

## Invariants (all tracks)

Every track must:
1. Preserve Core-6 field semantics (uuid, title, origin, source_ref, trust, review_state)
2. Route all side effects through the Outbox with canonical envelope
3. Route all LLM/embedding calls through `app/components/*`
4. Keep agents independent of FastAPI/HTTP frameworks
5. Follow TDD: tests before or alongside code
6. Update docs in the same change
7. Pass all CI gates: `ruff check`, `mypy`, `pytest -q -m "not pg"`, `settings-validate`
8. Keep panel/UI sections as control surface only (not indexed as knowledge)
9. Keep watcher auto-run off (controlled by `WATCHER_AUTO_EXEC`)
10. Emit no new event types without updating `docs/EVENTS.md`
