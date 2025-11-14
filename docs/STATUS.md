# Status — Operational Snapshot

| Version | Goal | Delivered | Open | Next | Notes |
| --- | --- | --- | --- | --- | --- |
| v4.4 | Observability + Store abstraction | JSONL audit, Outbox, Core-6 identity | None | Keep doc set frozen | Stable legacy cut |
| v4.5A | Deterministic ingestion baseline | Full PER loop, promotion cooldowns, memory CI | Route ingestion polish to v4.5B | Monitor metrics + guard rails | Current green baseline |
| v4.5B | Fitness guards + ingestion polish | Delivered 2025-02-14 — rerank hooks, chunk/dedup, CI gates | — | Prep v4.6 rollout, keep fitness monitors green | Ready for tagging |
| v4.6 | Retrieval quality uplift (Objectives A–D active) | Objectives A (ce_local heuristic + golden eval) and B delivered; **v4.6-B Delivered 2025-02-16** with 100 % coverage/validity; v4.6-C diarization-aware chunking in progress | Objective C/D hardening, relation coverage ≥95%; issues #55–#58 track work | Prototype cross-encoder + diarization PER loops | Guard rails enforce ΔnDCG@10 ≥ +0.01 or ΔP@10 ≥ +0.005 |
| v4.6-D | CI gates + summary contract | Delivered 2025-02-18 — baselines.yaml drives seven-line CI output with GATES ok=true | — | Refresh baselines when metrics improve; keep PRs pasting summary lines | ops/quality/baselines.yaml + GATE_STRICT=1 documented |
| v4.8 | A2A Protocol V1 + Orchestrator messaging | — | Define envelopes, hooks, sample chain | Implement deterministic fixtures + status docs | Gated by `A2A_ENABLE` |
| v4.9 | MCP Integration + Planner Agent (LLM) | — | Build MCP server/client and Planner V1 schema | Align ToolProvider + Reasoning inputs | Flags: `MCP_ENABLE`, `PLANNER_ENABLE` |
| v4.10 | Orchestrator Runtime (LangGraph execution engine) | — | Prototype deterministic executor | Validate planner playback + CLI parity | Planned flag: `ORCHESTRATOR_ENABLE` |
| v5.x | Symbolic reasoning + reflexive agents | Governance concepts, Agent Memory Graph sketches | RDF/OWL/SHACL enforcement, logic gates | Define policy bundles + knowledge graph API | Dependent on v4.6 telemetry |

## v4.8 — Agent Coordination (A2A)
- Status: Planned.
- Summary: Defines the canonical A2A schema (`agent.request.created`, `agent.response.created`, `agent.error`) and wires it through the Orchestrator so multi-agent coordination stays deterministic and audited.
- Flags: `A2A_ENABLE` (default off) keeps choreography inert until explicitly toggled by operators or the Planner Agent.
- CI: Deterministic mocks replay A2A envelopes and keep memory-mode smoke at eight lines; Planner Agent + Orchestrator remain disabled in CI by default.
- Protocol hooks implemented (schema + logging); orchestration/routing logic queued for later v4.8+/v4.10 milestones.

## v4.9 — MCP + LLM Planning
- Status: Planned.
- Summary: Introduces MCP server/client plus the LLM-driven Planner Agent that emits schema-validated plans referencing agents, A2A envelopes, and MCP tools for the Orchestrator to execute.
- Flags: `MCP_ENABLE`, `PLANNER_ENABLE` (both default off) scope MCP exposure and planner invocation.
- CI: Mock Planner Agent + fake MCP provider keep tests deterministic; `python -m app.fitness.report` remains independent of network access and MCP stays fully stubbed.

## v4.10 — Orchestrator Runtime
- Status: Planned.
- Summary: Brings in the deterministic Orchestrator runtime (LangGraph or equivalent) that consumes Planner Agent output, schedules agents, delivers A2A envelopes, and invokes MCP tools while keeping CLI workflows available.
- Flags: `ORCHESTRATOR_ENABLE` (planned) will gate the runtime so teams can dual-run CLI and Orchestrator paths.
- CI: LangGraph-backed executor will ship with replay fixtures proving deterministic execution of at least one multi-agent chain; CI independence from MCP remains intact via mocks.

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
- Cross-encoder provider contract for v4.6 reranker (decision pending between OpenAI and local model).
- Production diarization sample set requires legal approval for sharing audio traces.
- RelationIndex fitness benchmark tooling lacks test data beyond 10k objects.

## Ready for Tagging
- [x] v4.5A baseline
- [ ] v4.5B polish release (P1 rerank + P2 chunk/dedup complete)
- [ ] v4.6 feature release
