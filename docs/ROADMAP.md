State: Locked baseline SoT v5.5 (Reality-MVP + watchers/panel policy) with forward line now moving into v5.6 LangGraph/Reasoning rollouts.
# Roadmap — Strategic Control

This roadmap is forward-looking and skimmable. History lives in `docs/history/SOT_4X_HISTORY.md`; deep track details live under `docs/tracks/`. Current truth stays in `docs/ARCHITECTURE.md` and `docs/STATUS.md`.

## Status vocabulary
- **Shipped** — merged to main; code/doc exists.
- **Operationally accepted** — proven on real vault/external samples with runbook/soak.
- **Baseline locked** — scope frozen; only bugfixes allowed.
- **Planned / In progress** — tracked work not yet shipped.

## Baselines
- **SoT v4.10 (foundation)** — Reality-MVP ingest/ASK/observability runtime; now subsumed by the v5.5 baseline.
- **SoT v5.5 (baseline locked)** — watcher auto-run gate + panel action provenance + concurrency/idempotency guards (dedup queue, promotion consumer dedup, optimistic writes); baseline ships with the new settings compiler and CLI controls.

## Now / Next / Later
- **Now**
  - **v5.5 baseline lock + safety guard** — watcher auto-run stays off by default while the DedupTaskQueue, EventDedupStore, and optimistic writes keep the vault deterministic; panel action provenance and watcher/panel settings are compiled with provenance metadata before letting the LangGraph forward line take over.
  - PanelAgent LangGraph decider opt-in, watcher policy auto-exec plumbing (v5.5C in progress).
  - Watcher → panel → planner/orchestrator automation with safety limits now includes dedup reports, promotion consumer visibility, and explicit skipped receipts.
  - Vault-first config validation (panel wiring, watcher, outbox) with schema enforcement and `python -m app.cli.settings_explain`.
- **Next**
  - **Quality Wave: Registry Watcher Evaluation Stack** — A: contract tests for watcher→panel→promotion event chain; B: golden vault + seeded snapshots; C: metamorphic runs (interval/max-ticks/scope overrides); D: cold rebuild coverage (empty store + existing mirrors); E: fitness gates (status/outbox counters, idempotence, no dup intents on rerun); F: scripted UAT harness (CLI-first). **Done means** idempotence proven (first run vs rerun stable), event chain proven (registry watcher → `ingest.vault.changed` → worker → `panel.intent.*` → `promote.*`), deterministic diffs on golden vault, and gates enforced in CI/UAT. **Modules & Files to be touched during implementation**: `app/watcher/registry.py`, `configs/watchers.yaml`, `app/agents/panel_agent/*`, `app/components/settings/panel_actions_loader.py`, `app/promotion/consumer.py`, outbox writer/reader + status command modules, CLI `watcher run`/status modules, `app/fitness/*` and `ops/quality/baselines.yaml`, `docs/examples/vault_test_seed/*`.
  - **ReasoningFacade + basic graph builder** (BLOCKER for LangGraph rollout).
    - Rationale: prevents pattern fragmentation; all LangGraph agents route reasoning/tool calls through the facade.
  - Orchestrator V2 (LangGraph): parallel execution, compensation/rollback, checkpointing, retries.
    - Back-compat: `ORCHESTRATOR_VERSION=v1|v2`.
  - PanelAgent 2.0 timeline:
    - v5.5C: decider (in progress).
    - v5.6: PanelAgent 2.0 full migration (freeform interpretation, multi-step workflows, uncertainty→suggested checkboxes, catalog-driven discovery).
    - v5.7: advanced (panel versioning, cross-note coordination).
  - Vault-as-GUI settings compiler (`@Settings` / System/Config) now covers panel-action catalogs, watcher settings, and outbox paths with CI schema checks (v5.6 track).
  - LangGraph rollout to additional agents (Promotion/Reviewer/Hygiene) in phases:
    - Phase 1: single pilot agent behind a flag; AgentState + graph parity tests green.
    - Phase 2: two agents; planner/orchestrator integration stable; event/A2A contracts unchanged.
    - Phase 3: broader adoption; runtime metrics + rollback plan validated.
  - A2A/MCP orchestration routing with deterministic adapters and audit.
- **Later**
  - Watcher auto-exec of panel plans with guardrails and rollback; richer panel actions (summary/reply) via tool/MCP boundary.
  - Reasoning/reflective layers with eval gates; expanded observability counters for orchestration/A2A.
  - Collaboration/multi-user after single-user flows are stable.

## Fitness Functions Enforced in CI
- `pytest -q -c /dev/null -m "not pg and not alpha_llm"` is the primary smoke gate in CI.
- `ops/quality/baselines.yaml` writes the `GATES` block and must report `ok=true` for merges; CI pipelines rely on that signal.
- Docker smoke checks ensure the worker emits the `worker starting` log and that the stack responds to health probes.
- Latency thresholds are provisional while the stack is still stabilizing; they can be re-tuned as the system matures to avoid blocking CI before the runtime is fully healthy.

## Reality-MVP acceptance (operator outcomes)
- Vault ingest and external ingest run successfully on real samples with provenance preserved; no data loss.
- ASK API returns answers with sources/latency; interim GUI surfaces status + ASK.
- Observability shows per-plane object counts, ingest runs/errors, and ASK usage.
- Orchestrator runtime V1 executes internal tools (external ingest) via plan or direct CLI; green CI (`pytest -q -m "not pg"`, memory backend) and docs aligned.

## Reality-MVP scope (operator view)
1) Vault ingestion of selected folders into ObjectStore with Core-6 projection and provenance; Outbox events emitted; indexed into VectorIndex.
2) Minimal external ingest of real samples into `external_raw`; stored and indexed without creating Obsidian notes.
3) ASK API returning `{uuid, title, origin, zone?, path/source_ref}` with latency; hybrid retrieval across planes.
4) Observability backend + interim GUI surfacing object counts, ingest runs/errors, ASK usage.
5) Orchestrator runtime V1 available via CLI/plan path for external ingest; future LangGraph/MCP remains additive.

## Version ladder (summary)
| Version | Intent | State |
| --- | --- | --- |
| v4.10 | Reality-MVP baseline | Baseline locked |
| v5.0 | PanelAgent Runtime V1 | Shipped |
| v5.1–v5.4 | Watcher track (ingest/panel CLI, policy, ergonomics) | Operationally accepted |
| v5.5A/B | Panel planner pipeline + CLI-first orchestration/promotion consumer | Shipped |
| v5.5C/D | Panel LangGraph decider + watcher auto-exec; watcher→planner/orchestrator automation | Planned/In progress |
| v5.6 | ReasoningFacade + LangGraph rollout + Orchestrator V2 (flagged) + Vault-as-GUI settings compiler; docs-first kickoff plan in `docs/V56_FORWARD_LINE.md` | Docs-first kickoff (status/roadmap updates) |

## Tracks (details moved)
- Watcher track details: `docs/tracks/TRACK_WATCHER.md`
- PanelAgent LangGraph track: `docs/tracks/TRACK_PANELAGENT_LANGGRAPH.md`
- AgentOps/A2A/MCP hardening: `docs/tracks/TRACK_AGENTOPS_A2A_MCP.md`
- Fitness/CI contract: `docs/tracks/TRACK_FITNESS_CI_CONTRACT.md`
- Historical ladder: `docs/history/SOT_4X_HISTORY.md`
