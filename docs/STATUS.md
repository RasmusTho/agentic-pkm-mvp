State: SoT v4.10 Reality-MVP (baseline locked) with the v5.x forward line currently tracked through v5.5 (PanelAgent planner pipeline + CLI-first orchestration).
Status snapshot now includes SoT baseline + forward-line fields and intent/event counters (`promote.intent.created`, `panel.intent.executed`, watcher runs, ingest runs by plane) for UAT visibility.

Concept anchors: layering, portability, archive exposure, trust semantics, event compatibility, and config-as-product are now defined as concept contracts under `docs/CONCEPTS/` and are considered the canonical statements of intent. This status document describes operational snapshots and may lag those contracts.

## Health spine
- HealthContract + WriteGuard + incident logging now form the deterministic spine for startup readiness; this snapshot is the baseline for initial go-live visibility.

## Status fields (baseline vs forward line)
- `sot_baseline_version`: locked Reality-MVP baseline (v4.10).
- `sot_forward_line_version` / `feature_line_version`: active forward line (v5.x features on top of v4.10).
- `active_features`: human-readable list of forward-line capabilities (PanelAgent runtime, watcher track, config-driven wiring).
- Counters (totals + 24h window): `watcher_runs`, `panel_runs` (`panel.intent.executed`), `promote.intent.created`, `promotion_executed` (`promote.done`), and ingest run counts per plane. Use these in UAT to confirm watcher/panel flows; if promotion intents increment but notes do not change, the promotion consumer is not running.

## Status — Operational Snapshot

Reference: `docs/SYSTEM_DESIGN_v4.10.md` captures the external dependencies and deployment topology for this SoT.

| Version | Goal | Delivered | Open | Next | Notes |
| --- | --- | --- | --- | --- | --- |
| Reality-MVP (SoT v4.10) | Reliable vault ingestion + minimal external plane + ASK API + observability + interim GUI + orchestrator runtime V1 | PER-loop agents stable; ASK CLI/API baseline over vault objects; zones/planes defined; external object schema (`external_raw`) ready; status/backend/GUI shipped; orchestrator runtime runs internal tools | Operational acceptance: soak real-vault ingest; extend external samples; richer orchestrator scheduling deferred to v5.x | Stabilize FastAPI ASK endpoint with sources/latency; ship status CLI/dashboard; run ingest on real vault snapshots | Single-user focus; collaboration deferred; zones are derived overlays |
| v4.4 | Observability + Store abstraction | JSONL audit, Outbox, Core-6 identity | None | Keep doc set frozen | Stable legacy cut |
| v4.5A | Deterministic ingestion baseline | Full PER loop, promotion cooldowns, memory CI | Route ingestion polish to v4.5B | Monitor metrics + guard rails | Current green baseline |
| v4.5B | Fitness guards + ingestion polish | Delivered 2025-02-14 — rerank hooks, chunk/dedup, CI gates | — | Prep v4.6 rollout, keep fitness monitors green | Ready for tagging |
| v4.6 | Retrieval quality uplift (Objectives A–D) | Objectives A/B delivered; relation coverage at 100 % (v4.6-B); diarization-aware chunking delivered behind flag | Maintenance only: keep fitness baselines green; refresh rerank/diarization baselines as needed | Keep rerank/diarization optional and deterministic; no new scope until after Reality-MVP | Historical foundation for hybrid retrieval |
| v4.6-D | CI gates + summary contract | Delivered 2025-02-18 — baselines.yaml drives seven-line CI output with GATES ok=true | — | Refresh baselines when metrics improve; keep PRs pasting summary lines | ops/quality/baselines.yaml + GATE_STRICT=1 documented |
| v4.8 | A2A Protocol V1 + Orchestrator messaging | Canonical schema defined; mocks available | Wiring deferred until after Reality-MVP | Implement deterministic fixtures + status docs | Gated by `A2A_ENABLE`; post-MVP |
| v4.9 | MCP Integration + Planner Agent (LLM) | Delivered — Planner schema, MCP descriptor registry (`allowed_args` + `mock_result`), Mock/LLM planners, pipeline hook | Harden MCP transport + ToolProvider runtime | Align ToolProvider + Reasoning inputs | Flags: `MCP_ENABLE`, `PLANNER_ENABLE` |
| v4.10 | Orchestrator Runtime (LangGraph execution engine) | Runtime delivered — plan validation + audit + internal tool execution (external ingest) + MCP/A2A mocks; CLI dual-run available | Extend to LangGraph/parallel scheduling + richer MCP tool providers (post-MVP) | Validate planner playback + CLI parity; fold into Reality-MVP interim GUI/ASK path | Flag: `ORCHESTRATOR_ENABLE`; Reality-MVP consumes skeleton |
| v5.0 | PanelAgent Runtime V1 baseline on SoT v4.10 | Delivered — step 1 parse/map emits `panel.intent.created`; runtime interprets it, fans out promotion via `promote.intent.created`, emits `panel.intent.executed` + `panel.action.*` + `panel.log.created`, writes `panel_logs`; CLI default runs runtime, `--emit-only` keeps step 1 | Follow-on PanelAgent flows live under v5.x forward line | Extend runtime/action coverage in v5.x without altering v4.10 | Baseline locked for PanelAgent runtime V1 once merged to main |
| v5.1 | Watcher-ready ingest & panel flows | Planned v5.x — CLI ingest for single/changed notes + multi-note panel runtime CLI; watcher-compatible docs | None | Prepare CLI + docs for watcher readiness | Builds on v5.0 PanelAgent runtime baseline |
| v5.2 | Vault Watcher MVP (CLI, polling) | Delivered — snapshot-based CLI watcher (`vault-watcher-run`) polls vault, detects changes, ingests changed notes, optionally runs panel runtime; logs summary/metrics; no auto-panel policy yet | None | Wire into schedulers/ops; prep policy hooks for v5.3 | Manual/background, additive to existing CLI |
| v5.3 | Auto-panel as explicit policy | Delivered — frontmatter policy (`ai_panel_auto_run` or `ai_panel.auto_run`) gates watcher-triggered `panel run-many`/note-update after ingest; AI logs/events remain; manual CLI unaffected | None | Prepare further policy refinements for v5.4 | Must be opt-in and auditable |
| v5.4 | Watcher hardening & ergonomics | Delivered — dry-run mode, max-notes guard (with force override), structured watcher summaries; manual/cron ready | None | Prepare further ops polish if needed | Builds on v5.2–v5.3 |
| v5.5 | PanelAgent 2.0 (LangGraph inner) | In-progress (v5.5B) — `PanelActionIntent` + opt-in planner pipeline (`PANEL_AGENT_PIPELINE=planner`) create plans from panel actions; CLI-first execution via Orchestrator now available (promotion tool emits `promote.intent.created`) | Wire watcher auto-exec + extend action coverage; broaden action mapping | Design schema/graph; keep Runtime V1 baseline in place until 2.0 is proven | Bridges to the “LangGraph inner per agent” principle |
| v5.6 | LangGraph rollout to other agents | Planned — select 1–2 agents (Promotion, Reviewer, Hygiene), add AgentState + LangGraph graphs, move non-trivial decision logic out of pipelines | None | Pick pilot agents and design graphs | Extends LangGraph inner model beyond PanelAgent |
| v5.x | Symbolic reasoning + reflexive agents | Governance concepts, Agent Memory Graph sketches | RDF/OWL/SHACL enforcement, logic gates | Define policy bundles + knowledge graph API | Dependent on v4.6 telemetry |

Pattern Harvest (Outer/Inner agent architecture) — In progress (docs-first); see docs/research/pattern-harvest-agentic-architecture.md.

Watcher deployment note: `vault-watcher-daemon` offers a Docker-first polling service with snapshot storage outside the vault (e.g., `/state`); host services (launchd/systemd) remain the fallback when mounts are unreliable.

Eval baseline: DeepEval ASK + Ragas RAG suites are available under `@pytest.mark.eval` (seed cases; opt-in, diagnostics only).

## v5.0 Snapshot (PanelAgent Runtime V1 on the v4.10 baseline)
- SoT v4.10 Reality-MVP remains the locked baseline for ingestion, ASK, observability, and orchestrator runtime V1.
- SoT v5.0 formalizes PanelAgent runtime V1 delivered on top of v4.10: step 1 parse/map emits `panel.intent.created`, the runtime interprets it, fans promotion actions to `promote.intent.created`, emits `panel.intent.executed` + `panel.action.*` + `panel.log.created`, and writes AI-log entries (`panel_logs`) onto note payloads.
- CLI defaults run the full panel parse + runtime; `--emit-only` preserves a step-1-only path.
- v5.0 is baseline locked for PanelAgent runtime V1 once merged to main; later v5.x versions extend into Satellite Sync, Yggdrasil modules, and Orchestrator/Reasoning 2.0.

## Reality-MVP Snapshot (SoT v4.10 baseline)
- Implemented: PER-loop ingestion against vault objects with Core-6 projection + Stores/Outbox; ASK CLI/API baseline over the vault plane; zones/planes defined with `external_raw` schema for non-vault objects; Planner/Reasoning layers remain optional overlays.
- Malformed frontmatter is now handled gracefully in vault ingest (skip + warning + summary counters), preventing crashes on bad YAML; ingest errors are recorded with counts/paths and runs can resume to finish remaining notes.
- ASK API returns sources with plane/origin tags and latency alongside answers.
- Minimal external ingest path delivered: drop-folder → external_raw objects stored/indexed (txt/md), retrievable via ASK with origin/plane tags.
- Observability backend + CLI delivered: status service aggregates per-plane counts, ingest timestamps/errors, and ASK query counts/latency/error counts.
- Operational acceptance: soak ingest on real vault snapshots and extend external drop ingest to real newsletter/PDF samples; these are manual runs rather than code gaps.
- Delivered: Interim GUI dashboard (served at `/`) surfaces status snapshot (per-plane counts, ingest runs/errors, ASK latency/errors) and includes a basic ASK form; collaboration/multi-user explicitly deferred until after Reality-MVP foundations are stable.
- Reality-MVP smoke: canonical note → ingest → index → ASK path is captured in `docs/scenarios/REALITY_MVP.md` and enforced by `tests/e2e/test_reality_mvp_pipeline.py`.
- Orchestrator runtime V1: runs plans with internal tools (external ingest) and a CLI dual-run path; further LangGraph/parallel scheduling and richer MCP execution are deferred to v5.x.

## Note Ingestion Defaults
- Notes always get a UUID via `ensure_note_uuid` before watcher/update runs; the YAML round-trip helper is the only parser/writer for frontmatter.
- Missing UUIDs never suppress ingestion; CLI/status output notes when a UUID was added during processing.
- Default mode is ingestion-only: `note_moves_enable` defaults to false, Planner demotes move/rename steps, and Promotion logs `promote.skip.move` instead of moving files. Flip the flag in `vault/@Settings/global` to enable moves later.
