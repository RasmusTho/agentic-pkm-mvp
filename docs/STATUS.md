# Status — Operational Snapshot

| Version | Goal | Delivered | Open | Next | Notes |
| --- | --- | --- | --- | --- | --- |
| Reality-MVP (SoT v4.10) | Reliable vault ingestion + minimal external plane + ASK API + observability + interim GUI | PER-loop agents stable; ASK CLI/API baseline over vault objects; zones/planes defined; external object schema (`external_raw`) ready | Harden real-vault ingest runs, wire minimal external drop ingest, build observability backend + interim GUI | Stabilize FastAPI ASK endpoint with sources/latency; ship status CLI/dashboard; run ingest on real vault snapshots | Single-user focus; collaboration deferred; zones are derived overlays |
| v4.4 | Observability + Store abstraction | JSONL audit, Outbox, Core-6 identity | None | Keep doc set frozen | Stable legacy cut |
| v4.5A | Deterministic ingestion baseline | Full PER loop, promotion cooldowns, memory CI | Route ingestion polish to v4.5B | Monitor metrics + guard rails | Current green baseline |
| v4.5B | Fitness guards + ingestion polish | Delivered 2025-02-14 — rerank hooks, chunk/dedup, CI gates | — | Prep v4.6 rollout, keep fitness monitors green | Ready for tagging |
| v4.6 | Retrieval quality uplift (Objectives A–D) | Objectives A/B delivered; relation coverage at 100 % (v4.6-B); diarization-aware chunking delivered behind flag | Maintenance only: keep fitness baselines green; refresh rerank/diarization baselines as needed | Keep rerank/diarization optional and deterministic; no new scope until after Reality-MVP | Historical foundation for hybrid retrieval |
| v4.6-D | CI gates + summary contract | Delivered 2025-02-18 — baselines.yaml drives seven-line CI output with GATES ok=true | — | Refresh baselines when metrics improve; keep PRs pasting summary lines | ops/quality/baselines.yaml + GATE_STRICT=1 documented |
| v4.8 | A2A Protocol V1 + Orchestrator messaging | Canonical schema defined; mocks available | Wiring deferred until after Reality-MVP | Implement deterministic fixtures + status docs | Gated by `A2A_ENABLE`; post-MVP |
| v4.9 | MCP Integration + Planner Agent (LLM) | Delivered — Planner schema, MCP descriptor registry (`allowed_args` + `mock_result`), Mock/LLM planners, pipeline hook | Harden MCP transport + ToolProvider runtime | Align ToolProvider + Reasoning inputs | Flags: `MCP_ENABLE`, `PLANNER_ENABLE` |
| v4.10 | Orchestrator Runtime (LangGraph execution engine) | Skeleton delivered — plan validation + audit + mocked MCP/A2A execution | Integrate LangGraph + real MCP/agent loops (post-MVP) | Validate planner playback + CLI parity; fold into Reality-MVP interim GUI/ASK path | Flag: `ORCHESTRATOR_ENABLE`; Reality-MVP consumes skeleton |
| v5.x | Symbolic reasoning + reflexive agents | Governance concepts, Agent Memory Graph sketches | RDF/OWL/SHACL enforcement, logic gates | Define policy bundles + knowledge graph API | Dependent on v4.6 telemetry |

## Reality-MVP Snapshot
- Implemented: PER-loop ingestion against vault objects with Core-6 projection + Stores/Outbox; ASK CLI/API baseline over the vault plane; zones/planes defined with `external_raw` schema for non-vault objects; Planner/Reasoning layers remain optional overlays.
- In progress: Running ingest on real vault snapshots and hardening resume/error handling; minimal external drop ingest for newsletters/PDFs into `external_raw`; FastAPI ASK endpoint with answers + sources + latency; zone/plane tags exposed in ASK responses.
- Planned/queued: Observability backend + CLI (object counts per plane, ingest timestamps/errors, ASK counts/latency); interim GUI dashboard showing status + ASK; external ingest sample set; collaboration/multi-user explicitly deferred.

## Note Ingestion Defaults
- Notes always get a UUID via `ensure_note_uuid` before watcher/update runs; the YAML round-trip helper is the only parser/writer for frontmatter.
- Missing UUIDs never suppress ingestion; CLI/status output notes when a UUID was added during processing.
- Default mode is ingestion-only: `note_moves_enable` defaults to false, Planner demotes move/rename steps, and Promotion logs `promote.skip.move` instead of moving files. Flip the flag in `vault/@Settings/global` to enable moves later.

## v4.8 — Agent Coordination (A2A)
- Status: Planned (post-MVP).
- Summary: Defines the canonical A2A schema (`agent.request.created`, `agent.response.created`, `agent.error`) and wires it through the Orchestrator so multi-agent coordination stays deterministic and audited.
- Flags: `A2A_ENABLE` (default off) keeps choreography inert until explicitly toggled by operators or the Planner Agent.
- CI: Deterministic mocks replay A2A envelopes and keep memory-mode smoke at eight lines; Planner Agent + Orchestrator remain disabled in CI by default.
- Protocol hooks implemented (schema + logging); orchestration/routing logic queued for later v4.8+/v4.10 milestones.

## v4.9 — MCP + LLM Planning
- Status: Delivered (SoT v4.9).
- Summary: Plan/PlanStep schema finalized, MCP descriptor registry now encodes `allowed_args` + `mock_result`, deterministic `MockPlanner` + Ollama-backed `LLMPlanner` providers ship, and the ingest pipeline emits `planner.plan.created` (with fallback logging) whenever `PLANNER_ENABLE=1`. MCP transport/client wiring continues under v4.10 but all descriptors and mocks are stable.
- Flags: `MCP_ENABLE`, `PLANNER_ENABLE` (both default off) scope MCP exposure and planner invocation.
- CI: Mock Planner Agent keeps tests deterministic; `PLANNER_PROVIDER=mock` is enforced automatically when `LLM_PROVIDER=mock`, and descriptor validation is covered by new planner/orchestrator tests.

## v4.10 — Orchestrator Runtime
- Status: Skeleton delivered; maintained as part of Reality-MVP while LangGraph/real MCP execution is deferred.
- Summary: `app/orchestrator.runtime` validates plans, runs steps sequentially, emits `orchestrator.step.*`, and integrates with `send_agent_request` plus MCP mock descriptors so plan execution stays fully audited without touching the filesystem/network. `app.agents.pipeline.maybe_execute_plan()` (gated by `ORCHESTRATOR_ENABLE`) now replays plans immediately after planning.
- Flags: `ORCHESTRATOR_ENABLE` gates the runtime so teams can dual-run CLI and Orchestrator paths; planner flag must also be enabled.
- CI: New tests under `tests/orchestrator/` assert plan playback, MCP validation, A2A error emission, and pipeline wiring. Execution remains mock-only, preserving the eight-line CI contract while groundwork for LangGraph + real MCP integrations proceeds.

## v4.5B Delivery Summary (2025-02-14)
- Fitness gates enforced with deterministic QAS-003 hybrid-search and QAS-010 outbox→index probes.
- Cross-encoder providers (`ce_local`, `ce_http`) hardened with deterministic fallback paths and golden-set evaluation.
- RelationIndex `has_any()` plus Promotion orphan gate enforced by default; overrides require reason and are audited.
- Diarization hook integrated; speaker metadata flows into chunking when `DIARIZE_ENABLE=1`.
- Golden evaluation pipeline (P@k, nDCG@k) wired into CI summary.
- Doc-integrity gating and v4.6 PR/issue templates active for every submission.

## CI & Test Markers
- Last CI run: PASS — `pytest -q -m "not pg"` (STORE_BACKEND=memory, LLM_PROVIDER=mock, audit JSONL enabled).
- Mermaid export: PASS — `docker run --rm -v $(pwd)/tmp:/data minlag/mermaid-cli -i /data/diagram.mmd -o /data/diagram.svg`.
- Chunk/dedup coverage: PASS — `pytest -q -m "not pg" -k "chunk_dedup"`.
- Fitness: PASS — `python -m app.fitness.report` (latest sample: QAS-003 p95=0.000126 s, QAS-010 p95=0.000006 s).
- Golden evaluation: PASS — `pytest -q -m "not pg" -k "golden_metrics"` plus `python -m app.fitness.report` (ce_local vs baseline with ΔnDCG@10=+0.070, ΔP@10=+0.000).
- Relation coverage sample: 81.82% of promoted items (golden relations corpus).
- Alpha reasoning + reviewer (local LLM): export the vars below, then run the two single-note tests to inspect real reasoning output.

```bash
export STORE_BACKEND=memory
export OPENAI_BASE_URL=http://127.0.0.1:11434/v1
export OPENAI_API_KEY=sk-local
export LLM_PROVIDER=llm
export REASONING_ENABLE=1
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1

.venv/bin/pytest tests/reasoning/test_reasoning_single_note.py \
                 tests/agents/test_reviewer_single_note.py
```

LLM trace (local/alpha only)
- Toggle tracing locally to capture all LLM calls in JSONL:
  - `export LLM_TRACE_ENABLE=1`
  - `export LLM_TRACE_PATH=tmp/llm-trace.jsonl`
- Inspect with `jq . tmp/llm-trace.jsonl | head` after running reasoning flows.

Reasoning alpha (multi-note, ranking, planning)
- CI (mock) now covers multi-note reasoning on pkm-alpha notes, SetEvaluator ranking with reasons, and a planner/orchestrator reasoning flow.
- Re-run locally with `LLM_PROVIDER=llm` + `LLM_TRACE_ENABLE=1` to inspect real LLM calls in `tmp/llm-trace.jsonl`.

Human-facing validation (alpha)
- Alpha changes to classification, AI panels, ASK responses, or promotion flows should be validated against `docs/HUMAN-FLOWS.md`.
- Quick check: “Does this change match the human expectations in HUMAN-FLOWS §3.x?”

Reasoning Alpha (local LLM)
- Environment for running the full reasoning suite against Ollama + tracing:
  ```bash
  export STORE_BACKEND=memory
  export OPENAI_BASE_URL=http://127.0.0.1:11434/v1
  export OPENAI_API_KEY=sk-local
  export LLM_PROVIDER=llm
  export REASONING_PROVIDER=llm
  export PLANNER_PROVIDER=llm
  export REASONING_ENABLE=1
  export LLM_TRACE_ENABLE=1
  export LLM_TRACE_PATH=tmp/llm-trace.jsonl
  export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
  ```
- Run the full alpha suite:
  ```bash
  .venv/bin/pytest -q \
    tests/reasoning/test_reasoning_single_note.py \
    tests/agents/test_reviewer_single_note.py \
    tests/reasoning/test_reasoning_multi_note.py \
    tests/agents/test_set_evaluator_pkm_alpha.py \
    tests/agents/test_planner_reasoning_e2e.py
  ```
- The same env routes calls through the local LLM and writes JSONL traces for inspection.

## PKM-Alpha Alpha Reasoning Run (local LLM)
- End-to-end local run against the real PKM-Alpha vault (limited ingest, alpha LLM tests, trace export to Obsidian).

Environment (local LLM + memory/pg)
```bash
cd ~/workspace/agentic-pkm-mvp

# Stores: for alpha runs we can use memory or pg; document both options.
# Option A: memory store (fast experimentation)
export STORE_BACKEND=memory

# Option B: PG store (commented out; user can switch)
# export STORE_BACKEND=pg
# export DATABASE_URL="postgresql+psycopg://app:app@localhost:15432/app"

# Local LLM (Ollama)
export OPENAI_BASE_URL=http://127.0.0.1:11434/v1
export OPENAI_API_KEY=sk-local
export LLM_PROVIDER=llm
export REASONING_PROVIDER=llm

# Reasoning + tracing
export REASONING_ENABLE=1
export LLM_TRACE_ENABLE=1
export LLM_TRACE_PATH=tmp/llm-trace-alpha.jsonl

# Pytest isolation
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
```

Ingest a controlled subset from PKM-Alpha
```bash
# Ingest a limited number of notes from the PKM-Alpha vault
python -m app.cli pkm-alpha-ingest --limit 50
```
- Uses DEFAULT_VAULT_ROOT (`/Users/rasmus/Library/Mobile Documents/iCloud~md~obsidian/Documents/PKM - Alpha`) under the hood.
- Start with limit=50 for quick iterations; raise as needed after the first pass.

Run the alpha reasoning suite against real notes
```bash
.venv/bin/pytest -q \
  tests/reasoning/test_reasoning_single_note.py \
  tests/agents/test_reviewer_single_note.py \
  tests/reasoning/test_reasoning_multi_note.py \
  tests/agents/test_set_evaluator_pkm_alpha.py \
  tests/agents/test_planner_reasoning_e2e.py \
  -m alpha_llm
```
- Covers single-note and multi-note reasoning, reviewer, set_evaluator ranking, and planner/orchestrator reasoning paths.
- These tests call the real provider (llm → Ollama) and expect PKM-Alpha content already ingested; no monkeypatching of LLM or Stores.

Export latest trace as a Mermaid sequence into PKM-Alpha
```bash
python -m app.cli llm-trace-sequence \
  --latest \
  --format mermaid \
  --out-file "/Users/rasmus/Library/Mobile Documents/iCloud~md~obsidian/Documents/PKM - Alpha/System/Observability/LLM Traces/trace-latest.md"
```
- Writes a Markdown file with a `sequenceDiagram` into the vault; opening `System/Observability/LLM Traces/trace-latest.md` in Obsidian shows the full reasoning flow (agents, modes, prompts, responses).

Provider policy
- Local default (CI unset, providers empty): reasoning/planner prefer LLM backends.
- CI default: `LLM_PROVIDER=mock`, `REASONING_PROVIDER=mock`, `PLANNER_PROVIDER=mock`, `REASONING_ENABLE=1`; alpha LLM tests are skipped via `-m "not alpha_llm"`.
- Use `@pytest.mark.alpha_llm` tests for real LLM flows; they respect your env and never force mock providers.
- Reasoning now supports modes (claims, review, ranking) via `run_reasoning(...)`; traces use kinds `reasoning.claims`, `reasoning.review`, `reasoning.ranking`.

## Alpha Vault Observability (DEFAULT_VAULT_ROOT)
- DEFAULT_VAULT_ROOT: `/Users/rasmus/Library/Mobile Documents/iCloud~md~obsidian/Documents/PKM - Alpha`
- Observability path for trace Markdown: `<DEFAULT_VAULT_ROOT>/System/Observability/LLM Traces/`
- Mermaid sequence diagrams exported by `llm-trace-sequence` should be written into `System/Observability/LLM Traces/`.

### Live alpha LLM trace check (manual, not in CI)
Run this locally against your Ollama setup to ensure traces are populated (response_preview not `{}`):
```bash
cd ~/workspace/agentic-pkm-mvp
export STORE_BACKEND=memory
export OPENAI_BASE_URL=http://127.0.0.1:11434/v1
export OPENAI_API_KEY=sk-local
export LLM_TRACE_ENABLE=1
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1

.venv/bin/pytest -q tests/reasoning/test_reasoning_llm_live_alpha.py -m alpha_llm_live
```
Then inspect with:
```bash
python -m app.cli llm-trace-flows --agent reasoning --limit 3
python -m app.cli llm-trace-flows --agent set_evaluator --limit 3
python -m app.cli llm-trace-planner-flows --limit 3
```
Expect non-empty response previews (claims/evidence/ranking) rather than `{}`.

### Run alpha LLM suite with tracing and export latest trace
```bash
cd ~/workspace/agentic-pkm-mvp

export STORE_BACKEND=memory
export OPENAI_BASE_URL=http://127.0.0.1:11434/v1
export OPENAI_API_KEY=sk-local
export LLM_PROVIDER=llm
export REASONING_PROVIDER=llm
export PLANNER_PROVIDER=llm
export REASONING_ENABLE=1
export LLM_TRACE_ENABLE=1
export LLM_TRACE_PATH=tmp/llm-trace.jsonl
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1

# Run alpha LLM reasoning suite against local Ollama
.venv/bin/pytest -q -m alpha_llm

# Export the latest LLM flow as a Mermaid sequence diagram (Obsidian-ready)
python -m app.cli llm-trace-sequence \
  --latest \
  --format mermaid \
  --out-file "/Users/rasmus/Library/Mobile Documents/iCloud~md~obsidian/Documents/PKM - Alpha/System/Observability/LLM Traces/trace-latest.md"

# Inspect reasoning and set_evaluator flows (response_preview should show JSON/text, not {})
python -m app.cli llm-trace-flows --agent reasoning --limit 3
python -m app.cli llm-trace-flows --agent set_evaluator --limit 3
python -m app.cli llm-trace-planner-flows --limit 3
```
Note: reasoning calls are tagged by mode (`reasoning.claims`, `reasoning.review`, `reasoning.ranking`) and traces fall back to raw previews so responses are visible even without `LLM_TRACE_DETAIL=debug`.

Mock-mode contract run (CI-friendly):
```bash
STORE_BACKEND=memory LLM_PROVIDER=mock REASONING_PROVIDER=mock PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  pytest -q tests/reasoning/test_reasoning_modes_contract.py \
          tests/reasoning/test_reasoning_single_note.py \
          tests/reasoning/test_reasoning_multi_note.py \
          tests/agents/test_reviewer_single_note.py \
          tests/agents/test_set_evaluator_pkm_alpha.py
```
Reasoning invariants: claims succeeds only if claims+evidence is non-empty; ranking succeeds only if the ranking list is non-empty and has reasons.

## Metrics Snapshot
- QAS-003 p95: 0.000127 s
- QAS-010 p95: 0.000006 s
- Golden P@10 / nDCG@10: 0.188 / 0.924 (ce_local), baseline 0.188 / 0.855 (ΔnDCG@10 = +0.070, DP10 = +0.000)
- Relation coverage: 100% (golden sample), relation validity: 100% (all recorded links use supported types)
- Diarization chunk p95 (flag on/off): 78 / 117 chars, speaker_avg (flag on) = 2.33, CI gates report `ok=true` (v4.6-D baselines.yaml)

### Latest CI Snapshot (Delivered 2025-02-16 — SoT v4.6-B)
- A2A and MCP/Planner initiatives do not introduce new CI gates; existing smoke contract stays at eight deterministic summary lines.
- Eight-line CI contract remains unchanged until v4.8+/v4.9 flags are explicitly enabled locally.
CI SUMMARY LATENCY QAS003=0.000127s QAS010=0.000006s  
CI SUMMARY EVAL P10=0.188 NDCG10=0.924 BASE_P10=0.188 BASE_NDCG10=0.855  
CI SUMMARY EVAL DELTA DP10=+0.000 DnDCG10=+0.070 RELATION_TARGET=60%  
CI SUMMARY RELATION COVERAGE=100.00%  
CI SUMMARY RELATIONS coverage=100.00% validity=100.00% target=95%  
CI SUMMARY DIARIZATION chunk_p95=78.00 speaker_avg=2.33 flag=on  
CI SUMMARY REASONING claims_avg=1.33 inferences_avg=1.00 conflicts=1.00 flag=on  
CI SUMMARY GATES ok=true reasons=  
Relation coverage + validity now exceed the ≥95 % SoT v4.6-B guardrail while ce_local remains default-off unless flags are set; staging now runs with `PROMOTION_REQUIRE_RELATIONS=1` so promotion gating is enforced ahead of production.

## Outstanding Blockers
- Long-run ingest reliability on real vaults (resume logic, malformed frontmatter handling) needs soak testing before calling vault ingestion “stable”.
- Minimal external ingest sample (newsletters/PDFs) and drop-folder wiring need to be finalized so external plane coverage can be demonstrated.
- Observability aggregator + interim GUI endpoints are unimplemented; status CLI/dashboard requires object counts per plane and ASK latency/error metrics.

## Ready for Tagging
- [ ] Reality-MVP (vault ingestion + minimal external ingest + ASK API + observability backend + interim GUI)
- [x] v4.5A baseline
- [ ] v4.5B polish release (P1 rerank + P2 chunk/dedup complete) — archival
- [ ] v4.6 feature release — archival
