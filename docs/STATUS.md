State: SoT v5.5 Reality-MVP baseline locked (watcher auto-run gate, panel action provenance, and concurrency guard) with the forward line exploring v5.6 LangGraph/Reasoning improvements.
Status snapshot now includes SoT baseline + forward-line fields and intent/event counters (`promote.intent.created`, `panel.intent.executed`, watcher runs, ingest runs by plane) for UAT visibility.

Concept anchors: layering, portability, archive exposure, trust semantics, event compatibility, and config-as-product are now defined as concept contracts under `docs/CONCEPTS/` and are considered the canonical statements of intent. This status document describes operational snapshots and may lag those contracts.

## Health spine
- HealthContract + WriteGuard + incident logging now form the deterministic spine for startup readiness; this snapshot is the baseline for initial go-live visibility.

## Runtime verification
- `/api/health` now reports watcher and worker heartbeat freshness plus the runtime DB/LLM probes so operators see deterministic health signals.
- `scripts/start_full_system.sh` and `scripts/gap_test_alpha.sh` drive the watcher→worker→index→/api/ask chain, emit `index.object.embedded` / `index.embedding.failed`, and log diagnostics when sources are missing.
- The interim GUI and Status service consume these heartbeats/events so the dashboard shows ingest health, counts, and incidents in one place.

## CI & Test Markers
- CI legs assert `docs/ARCHITECTURE.md` contains fitness guard statements, confirm CLI health smoke commands pass, and verify the worker logs show `worker starting`.
- The runbook ensures `pytest -q -m "not pg and not alpha_llm"` plus curated fitness gates keep the SoT baseline stable before merges.

## Baseline Definition (SoT v5.5)
- Default safety mode: watcher auto-run stays off unless `WATCHER_AUTO_EXEC=1` and the note frontmatter explicitly allows it (`ai_panel_auto_run: watcher`); when enabled, candidate actions are filtered through the allowlisted `watcher_settings.allowed_actions`, and disallowed intents result in skipped receipts that are persisted for audit, while manual CLI panel runs remain available.
- Required contracts: event compatibility/outbox envelope (`docs/EVENTS.md`), trust semantics, config-as-product, and PanelAgent wiring (`docs/PANEL_AGENT.md` + `docs/settings/panel-actions.md`).
- Minimal concurrency guarantees: DedupTaskQueue + event_id dedup guard watcher runs, optimistic writes protect note updates, and the promotion consumer uses an EventDedupStore to skip duplicate intents (`docs/CONCURRENCY.md`, `app/promotion/consumer.py`).
- Settings compiler scope: panel action catalog, watcher settings, and outbox paths now compile with provenance (path/mtime/sha) via `vault/@Settings/watchers.md`, `docs/settings/panel-actions.md`, `python -m app.cli.settings validate`, and `python -m app.cli.settings_explain`.
- Required tests: `ruff check app tests`, `mypy app`, `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q -m "not pg"`, plus `python -m app.cli.settings validate --json` and the new concurrency/promote/settings regression suites.
- CI gate workflows: `.github/workflows/ci-smoke.yaml` and `.github/workflows/ci-lite.yml` parse the fitness report summary lines (including `CI SUMMARY GATES ok=<bool>`) and exit non-zero when `GATES.ok != true`, making them the enforced gate jobs that must pass before merges to main.

## Forward line: SoT v5.6 (Now / Next / Later)
### Now
- Ground the v5.6 objectives in a docs-first kickoff: the detailed plan in `docs/V56_FORWARD_LINE.md` captures the pillars, acceptance criteria, and immediate signal checks the forward line needs to ship.
- Keep the watcher auto-run/evidence pipeline ready for safe enablement: confirm allowlist enforcement, dedup counts, and skipped receipts are surfaced in status, events, and the new CLI `settings explain` output before any runtime gate opens.
- Harden the PanelAgent LangGraph pilot (panel action catalog + planner pipeline + promotion consumer) so its telemetry, provenance, and gating sensors stay deterministic while remaining opt-in.
### Next
- Sequence the ReasoningFacade + LangGraph rollout for one additional agent pool, ensuring instrumentation feeds into the fitness gates and the orchestrator V2 experiment flag remains gated until stability signals arrive.
- Expand the vault-as-GUI settings compiler (panel actions, watcher settings, outbox paths, plus any new connectors) so the forward line can describe runtime topology with complete provenance and precedence.
- Align CLI/docs runbooks with the v5.6 narrative: update `docs/ROADMAP.md`, status snapshots, and the new forward-line doc so operators know what signals (watcher summaries, `CI SUMMARY GATES`, panel/promote counters) prove the rollout is safe.
### Later
- Extend LangGraph adoption across more agents (Promotion, Reviewer, Hygiene) and the orchestrator V2 control plane once the v5.6A pilot stabilizes.
- Surface LangGraph/Reasoning rollouts in the evaluation stack (golden vault, metamorphic runs, cold rebuild, fitness gates) so the forward line has measurable acceptance per contract.
- Begin planning multi-user and external sync guardrails that rely on the v5.6 safe mode (watcher gating + plan audits) before the next forward milestone.
**Out of scope for the v5.6 kickoff PR**: no runtime behavior changes are merged yet—watcher auto-run remains disabled by default, and the orchestrator/langgraph plumbing stays opt-in until the defined gates pass.


## Status fields (baseline vs forward line)
- `sot_baseline_version`: locked SoT v5.5 Reality-MVP baseline.
- `sot_forward_line_version` / `feature_line_version`: active forward line (v5.6 features on top of the v5.5 baseline).
- `active_features`: human-readable list of forward-line capabilities (PanelAgent runtime, watcher track, config-driven wiring).
- Counters (totals + 24h window): `watcher_runs`, `panel_runs` (`panel.intent.executed`), `promote.intent.created`, `promotion_executed` (`promote.done`), and ingest run counts per plane. Use these in UAT to confirm watcher/panel flows; if promotion intents increment but notes do not change, the promotion consumer is not running.

## Current / Next up
- v5.5 baseline is now locked with concurrency/idempotency guards (watcher dedup, promote dedup, optimistic writes) keeping auto-exec safe while the forward line stabilizes.
- v5.6 sequencing: ReasoningFacade + basic graph builder first, then LangGraph Phase 1, then Orchestrator V2 (flagged via `ORCHESTRATOR_VERSION=v1|v2`).

## Concurrency & Safety (v5.5 gate)
- DedupTaskQueue now guards watcher auto-runs and powers the `skipped_dedup` signal before releasing keys.
- Optimistic locking keeps note writes safe; stale writes surface recoverable warnings instead of corrupting vault files.
- Event idempotency (watcher events + promotion intents) leverages deterministic `event_id`s and an EventDedupStore so repeated `promote.intent.created` lines are no-ops (`docs/EVENTS.md`, `docs/CONCURRENCY.md`, `app/promotion/consumer.py`).

## Migration tracking (forward line)

| Area | v5.5 baseline | v5.6 | Notes |
| --- | --- | --- | --- |
| Watcher auto-exec | Blocked on concurrency guards | — | Gate: dedup + optimistic locking + idempotency |
| LangGraph rollout | ASK + PanelAgent only | Phase 1 pilots after ReasoningFacade | Phased adoption per ROADMAP |
| Orchestrator V2 | Not started | Flagged rollout (`ORCHESTRATOR_VERSION=v1|v2`) | Preview scope only |

## Status — Operational Snapshot

Reference: `docs/SYSTEM_DESIGN_v4.10.md` captures the foundation deployment topology still used by the v5.5 baseline.

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
| v5.5 | Baseline lock (watcher/panel safety + concurrency guards) | Delivered — watcher auto-run gate, panel action provenance, IdempotencyGuard + EventDedupStore, optimistic writes; PanelAgent runtime + opt-in planner pipeline (`PANEL_AGENT_PIPELINE=planner`) available | Watcher auto-exec remains gated; expand action coverage | Keep baseline stable; drive v5.6 rollouts via forward line | Baseline locked; bugfixes only |
| v5.6 | ReasoningFacade + LangGraph rollout | Planned — ReasoningFacade + basic graph builder; LangGraph rollout Phase 1 for 1–2 agents (Promotion, Reviewer, Hygiene); Orchestrator V2 flagged (`ORCHESTRATOR_VERSION=v1|v2`) | None | Sequence ReasoningFacade → Phase 1 → Orchestrator V2 | Extends LangGraph inner model beyond PanelAgent |
| v5.x | Symbolic reasoning + reflexive agents | Governance concepts, Agent Memory Graph sketches | RDF/OWL/SHACL enforcement, logic gates | Define policy bundles + knowledge graph API | Dependent on v4.6 telemetry |

Pattern Harvest (Outer/Inner agent architecture) — In progress (docs-first); see docs/research/pattern-harvest-agentic-architecture.md.

Watcher deployment note: `vault-watcher-daemon` offers a Docker-first polling service with snapshot storage outside the vault (e.g., `/state`); host services (launchd/systemd) remain the fallback when mounts are unreliable.

Eval baseline: DeepEval ASK + Ragas RAG suites are available under `@pytest.mark.eval` (seed cases; opt-in, diagnostics only).

## v5.0 Snapshot (PanelAgent Runtime V1 on the v5.5 baseline)
- SoT v5.5 Reality-MVP is the locked baseline for ingestion, ASK, observability, watcher policy, and orchestrator runtime V1.
- SoT v5.0 formalizes PanelAgent runtime V1 delivered on top of v4.10: step 1 parse/map emits `panel.intent.created`, the runtime interprets it, fans promotion actions to `promote.intent.created`, emits `panel.intent.executed` + `panel.action.*` + `panel.log.created`, and writes AI-log entries (`panel_logs`) onto note payloads.
- CLI defaults run the full panel parse + runtime; `--emit-only` preserves a step-1-only path.
- v5.0 is baseline locked for PanelAgent runtime V1 once merged to main; later v5.x versions extend into Satellite Sync, Yggdrasil modules, and Orchestrator/Reasoning 2.0.

## Reality-MVP Foundation Snapshot (SoT v4.10 — historical)
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
