State: SoT v5.5 Reality-MVP baseline locked (watcher auto-run gate, panel action provenance, and concurrency guard) with the forward line exploring v5.6 LangGraph/Reasoning improvements.
Doc role: Core SoT
Authority: Current operational snapshot for the active baseline; subordinate to concept contracts for normative semantics, but authoritative for current runtime status and rollout posture.
Status snapshot now includes SoT baseline + forward-line fields and intent/event counters (`promote.intent.created`, `panel.intent.executed`, ingest runs by plane). `watcher_runs` refers to legacy snapshot watchers only; registry watcher health is via heartbeat + tick logs.

Concept anchors: layering, portability, archive exposure, trust semantics, event compatibility, and config-as-product are now defined as concept contracts under `docs/CONCEPTS/` and are considered the canonical statements of intent. This status document describes operational snapshots and may lag those contracts.

## Health spine
- HealthContract + WriteGuard + incident logging now form the deterministic spine for startup readiness; this snapshot is the baseline for initial go-live visibility.

## Runtime verification
- `/api/health` reports watcher and worker heartbeat freshness plus the runtime DB/LLM probes so operators see deterministic health signals.
- `scripts/start_full_system.sh` and `scripts/gap_test_alpha.sh` drive the registry watcher → DB outbox → worker → index → `/api/ask` chain, emit `index.embedding.created` / `index.embedding.failed` (legacy alias: `index.object.embedded`), and log diagnostics when sources are missing.
- The interim GUI and Status service consume these heartbeats/events so the dashboard shows ingest health, counts, and incidents in one place.

## CI & Test Markers
- CI legs assert `docs/ARCHITECTURE.md` contains fitness guard statements, confirm CLI health smoke commands pass, and verify the worker logs show `worker starting`.
- The runbook ensures `pytest -q -m "not pg and not alpha_llm"` plus curated fitness gates keep the SoT baseline stable before merges.

## Baseline Definition (SoT v5.5)
- Runtime watcher: registry watcher (`configs/watchers.yaml` + `python -m app.cli watcher run`) is the default; legacy snapshot watchers are dev-only and require `PKM_SETTINGS_PROFILE=lab`.
- Runtime default: `scripts/start_full_system.sh` sets `WATCHER_AUTO_EXEC=1` unless explicitly set by the operator; set `WATCHER_AUTO_EXEC=0` to run watchers in emit-only mode. Once armed, any note with an AI panel fence is treated as a candidate and actions are filtered through the allowlisted `watcher_settings.allowed_actions`, while the only per-note opt-out is `ai_panel_auto_run: never` (nested form accepted) and manual CLI panel runs remain available.
- Settings tiering (watcher controls): runtime defaults to `PKM_SETTINGS_PROFILE=operator`; dev/lab-only watcher tuning env vars are applied only when `PKM_SETTINGS_PROFILE=lab`.
- Storage baseline: `store_objects` is the canonical object table; legacy `objects` rows are best-effort migrated when needed so runtime avoids dual-table selection. Legacy `app/store/object_store.py` now delegates to canonical `app/stores` providers (compat mirror retained for tests), and `index rebuild` reads via `ObjectStore` rather than separate memory/DB query branches.
- ASK warm-load boundary: `/api/ask` hydrates HybridStore through the canonical store interface (`list_objects`) instead of backend-specific `_objects`/raw SQL introspection.
- DB outbox is canonical in runtime; JSONL (`INDEX_OUTBOX_PATH`) is audit only and should not be used as the worker queue.
- Required contracts: event compatibility/outbox envelope (`docs/EVENTS.md`), trust semantics, config-as-product, and PanelAgent wiring (`docs/PANEL_AGENT.md` + `docs/settings/panel-actions.md`).
- Minimal concurrency guarantees: DedupTaskQueue + event_id dedup guard watcher runs, optimistic writes protect note updates, and the promotion consumer uses an EventDedupStore to skip duplicate intents (`docs/CONCURRENCY.md`, `app/promotion/consumer.py`).
- Settings compiler scope: panel action catalog, watcher settings, and outbox paths now compile with provenance (path/mtime/sha) via `vault/@Settings/watchers.md`, `docs/settings/panel-actions.md`, `python -m app.cli settings-validate`, and `python -m app.cli settings-explain`.
- Required tests: `ruff check app tests`, `mypy app`, `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q -m "not pg"`, plus `python -m app.cli settings-validate --json` and the new concurrency/promote/settings regression suites.
- CI gate workflows: `.github/workflows/ci-smoke.yaml` and `.github/workflows/ci-lite.yml` parse the fitness report summary lines (including `CI SUMMARY GATES ok=<bool>`) and exit non-zero when `GATES.ok != true`, making them the enforced gate jobs that must pass before merges to main.

## Forward line: SoT v5.6 (Now / Next / Later)
### Now
- Ground the v5.6 objectives in a docs-first kickoff: the detailed plan in `docs/plans/V56_FORWARD_LINE.md` captures the pillars, acceptance criteria, and immediate signal checks the forward line needs to ship.
- Keep the watcher auto-run/evidence pipeline ready for safe enablement: confirm allowlist enforcement, dedup counts, and skipped receipts are surfaced in status, events, and the new CLI `settings-explain` output before any runtime gate opens.
- Harden the PanelAgent LangGraph pilot (panel action catalog + planner pipeline + promotion consumer) so its telemetry, provenance, and gating sensors stay deterministic while remaining opt-in.
### Next
- **Companion Note + Note Context** — replace VaultMirror with flat companion files at `vault/_system/companions/<uuid>.md`; introduce `NoteContext` assembler for agent-facing rich context. 8-part plan: `docs/plans/COMPANION_NOTE_AND_NOTE_CONTEXT.md`. Parts 1–5 deliver portable identity; Parts 6–7 wire Note Context into Panel Agent (eliminating the 800-char snippet). Event contracts unchanged. Blocks agent quality improvements in v5.6+.
- Sequence the ReasoningFacade + LangGraph rollout for one additional agent pool, ensuring instrumentation feeds into the fitness gates and the orchestrator V2 experiment flag remains gated until stability signals arrive.
- Expand the vault-as-GUI settings compiler (panel actions, watcher settings, outbox paths, plus any new connectors) so the forward line can describe runtime topology with complete provenance and precedence.
- Align CLI/docs runbooks with the v5.6 narrative: update `docs/ROADMAP.md`, status snapshots, and the new forward-line doc so operators know what signals (watcher summaries, `CI SUMMARY GATES`, panel/promote counters) prove the rollout is safe.
### Later
- Extend LangGraph adoption across more agents (Promotion, Reviewer, Hygiene) and the orchestrator V2 control plane once the v5.6A pilot stabilizes.
- Surface LangGraph/Reasoning rollouts in the evaluation stack (golden vault, metamorphic runs, cold rebuild, fitness gates) so the forward line has measurable acceptance per contract.
- Begin planning multi-user and external sync guardrails that rely on the v5.6 safe mode (watcher gating + plan audits) before the next forward milestone.
**Out of scope for the v5.6 kickoff PR**: orchestrator/langgraph plumbing stays opt-in until the defined gates pass; watcher auto-run is controlled by `WATCHER_AUTO_EXEC` (set `WATCHER_AUTO_EXEC=0` for emit-only/safe mode).


## Status fields (baseline vs forward line)
- `sot_baseline_version`: locked SoT v5.5 Reality-MVP baseline.
- `sot_forward_line_version` / `feature_line_version`: active forward line (v5.6 features on top of the v5.5 baseline).
- `active_features`: human-readable list of forward-line capabilities (PanelAgent runtime, watcher track, config-driven wiring).
- Counters (totals + 24h window): `panel_runs` (`panel.intent.executed`), `promote.intent.created`, `promotion_executed` (`promote.done`), and ingest run counts per plane. `watcher_runs` only increments for legacy snapshot watchers; registry watcher health is via heartbeat + tick logs.

## Concurrency & Safety (v5.5 gate)
- DedupTaskQueue now guards watcher auto-runs and powers the `skipped_dedup` signal before releasing keys.
- Optimistic locking keeps note writes safe; stale writes surface recoverable warnings instead of corrupting vault files.
- Event idempotency (watcher events + promotion intents) leverages deterministic `event_id`s and an EventDedupStore so repeated `promote.intent.created` lines are no-ops (`docs/EVENTS.md`, `docs/CONCURRENCY.md`, `app/promotion/consumer.py`).

## Current Snapshot

- Runtime uses the registry watcher, DB outbox, worker, ASK API, and status/health surfaces as the canonical operational path.
- PanelAgent runtime V1 is part of the active baseline; planner pipeline and LangGraph expansion remain opt-in.
- Legacy snapshot watchers remain available only for lab/dev workflows and are not part of the runtime default.
- Eval suites remain opt-in diagnostics; they do not define baseline health by themselves.

## Forward-Line Tracking

| Area | Current baseline posture | Forward-line direction |
| --- | --- | --- |
| Watcher auto-exec | Guarded by dedup + optimistic writes + idempotency | Safe enablement only after gates and receipts prove stable behavior |
| LangGraph rollout | Active for ASK and PanelAgent-related flows only | Expand in phases after ReasoningFacade/basic graph builder land |
| Orchestrator V2 | Not baseline | Flagged preview only |
| Companion Note + Note Context | VaultMirror (`System/Metadata/VaultMirror`) is active but planned for replacement | Flat `_system/companions/<uuid>.md` + NoteContext assembler; 8-part plan in `docs/plans/COMPANION_NOTE_AND_NOTE_CONTEXT.md` |

For detailed sequencing, version history, and roadmap ladder, use:
- `docs/ROADMAP.md`
- `docs/plans/V56_FORWARD_LINE.md`
- `docs/history/SOT_4X_HISTORY.md`
