State: Locked baseline SoT v4.10 (Reality-MVP) with active forward line tracked through v5.5 (PanelAgent planner pipeline + CLI-first orchestration).
# Roadmap — Strategic Control

This roadmap is forward-looking and skimmable. History lives in `docs/history/SOT_4X_HISTORY.md`; deep track details live under `docs/tracks/`. Current truth stays in `docs/ARCHITECTURE.md` and `docs/STATUS.md`.

## Status vocabulary
- **Shipped** — merged to main; code/doc exists.
- **Operationally accepted** — proven on real vault/external samples with runbook/soak.
- **Baseline locked** — scope frozen; only bugfixes allowed.
- **Planned / In progress** — tracked work not yet shipped.

## Baselines
- **SoT v4.10 (baseline locked)** — Reality-MVP: stable vault ingest, minimal external ingest, ASK API, observability + interim GUI, orchestrator runtime V1.
- **SoT v5.0+ (forward line)** — PanelAgent runtime + watcher track on top of v4.10; forward line tracked through **v5.5B** (planner pipeline + CLI-first orchestration with promotion consumer).

## Now / Next / Later
- **Now**
  - PanelAgent LangGraph decider opt-in, watcher policy auto-exec plumbing (v5.5C planned).
  - Watcher → panel → planner/orchestrator automation with safety limits; promotion consumer observable (v5.5D planned).
  - Vault-first config validation (panel wiring, watcher) with schema enforcement.
- **Next**
  - **Quality Wave: Runtime Loop Evaluation Stack** — A: contract tests for watcher→panel→promotion event chain; B: golden vault + seeded snapshots; C: metamorphic runs (interval/dry-run/max-notes); D: cold rebuild coverage (empty store + existing mirrors/snapshots); E: fitness gates (status/outbox counters, idempotence, no dup intents on rerun); F: scripted UAT harness (CLI-first). **Done means** idempotence proven (first run vs rerun stable), event chain proven (watcher.run→panel.intent.*→promote.*), deterministic diffs on golden vault, and gates enforced in CI/UAT. **Modules & Files to be touched during implementation**: `app/runtime/runtime_loop.py`, `app/watcher/vault_watcher.py`, `app/agents/panel_agent/*`, `app/components/settings/panel_actions_loader.py`, `app/promotion/consumer.py`, outbox writer/reader + status command modules, CLI runtime-loop/uat/status modules, `app/fitness/*` and `ops/quality/baselines.yaml`, `docs/examples/vault_test_seed/*`.
  - Vault-as-GUI settings compiler (`@Settings` / System/Config) with typed artifacts and CI schema checks (v5.6 track).
  - LangGraph rollout to additional agents (Promotion/Reviewer/Hygiene) with AgentState + graphs; event/A2A outer contracts preserved.
  - A2A/MCP orchestration routing with deterministic adapters and audit.
- **Later**
  - Watcher auto-exec of panel plans with guardrails and rollback; richer panel actions (summary/reply) via tool/MCP boundary.
  - Reasoning/reflective layers with eval gates; expanded observability counters for orchestration/A2A.
  - Collaboration/multi-user after single-user flows are stable.

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
| v5.6 | LangGraph rollout + Vault-as-GUI settings compiler | Planned |

## Tracks (details moved)
- Watcher track details: `docs/tracks/TRACK_WATCHER.md`
- PanelAgent LangGraph track: `docs/tracks/TRACK_PANELAGENT_LANGGRAPH.md`
- AgentOps/A2A/MCP hardening: `docs/tracks/TRACK_AGENTOPS_A2A_MCP.md`
- Fitness/CI contract: `docs/tracks/TRACK_FITNESS_CI_CONTRACT.md`
- Historical ladder: `docs/history/SOT_4X_HISTORY.md`
