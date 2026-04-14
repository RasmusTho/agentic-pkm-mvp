State: SoT v5.5 Reality-MVP baseline locked (watcher auto-run gate, panel action provenance, and concurrency guard) with the v5.6 delivery line closed and post-v5.6 follow-ups tracked separately for LangGraph/Reasoning expansion, Orchestrator V2 hardening, A2A/MCP lifecycle cleanup, and local verification hardening.
Doc role: Core SoT
Authority: Current operational snapshot for the active baseline; subordinate to concept contracts for normative semantics, but authoritative for current runtime status and rollout posture.
Owner: Runtime / current-state SoT
Temporal class: operational
Review cadence: weekly
Source of truth: mixed
Last reviewed: 2026-04-14
Last verified against: docs/ARCHITECTURE.md, docs/ROADMAP.md, docs/DOCS_INDEX.md, docs/ENVIRONMENTS.md, docs/EVENTS.md, docs/OBSERVABILITY.md, docs/runbooks/UAT_PANEL_WATCHER.md, docs/plans/AUTONOMY_AND_SYNC_VALIDATION.md, docs/INTERACTION_SURFACES_AND_AUTHORITY/README.md, docs/INTERACTION_SURFACES_AND_AUTHORITY/RECONCILE_CHAT_MUTATION_AUTHORITY.md, docs/FINDING_AND_REORIENTING/DOCUMENT_SALIENCE_AS_DERIVED.md, docs/COMMITMENT_AS_FIRST_CLASS/README.md, docs/contracts/A2A_CONTRACT_AND_TRACE.md, docs/contracts/TOOL_POLICY_AND_MCP_ADAPTER_CONTRACT.md, app/cli/__init__.py, app/cli/latency_harness.py, app/observability/status_service.py, app/orchestrator/runtime.py, app/orchestrator/v2_runtime.py, app/orchestrator/executor.py, app/watcher/registry.py, app/workers/outbox_worker.py, Makefile, merged PRs #365/#376/#382/#383/#386/#389/#391/#423/#424/#425/#426/#427/#431/#434/#439, current repo state at f20c0fb on 2026-04-14, backlog issues #435/#436/#437/#444/#445/#446
Status snapshot now includes SoT baseline + release-line fields and intent/event counters (`promote.intent.created`, `panel.intent.executed`, `watcher.run`, ingest runs by plane). Code still exposes `sot_forward_line_version` / `feature_line_version` as the v5.6 release-line marker, but GitHub issue truth treats v5.6 as delivered rather than active. `watcher_runs` now counts watcher audit events from the registry watcher as well as the legacy snapshot watcher, while runtime health still relies on heartbeat + tick logs.

Concept anchors: layering, portability, archive exposure, trust semantics, event compatibility, and config-as-product are now defined as concept contracts under `docs/CONCEPTS/` and are considered the canonical statements of intent. This status document describes operational snapshots and may lag those contracts.

## Health spine
- HealthContract + WriteGuard + incident logging now form the deterministic spine for startup readiness; this snapshot is the baseline for initial go-live visibility.

## Runtime verification
- `/api/health` reports watcher and worker heartbeat freshness plus the runtime DB/LLM probes so operators see deterministic health signals.
- `scripts/start_full_system.sh` and `scripts/gap_test_alpha.sh` drive the registry watcher → DB outbox → worker → index → `/api/ask` chain, emit `watcher.run` audit rows plus `index.embedding.created` / `index.embedding.failed` (legacy alias: `index.object.embedded`), and log diagnostics when sources are missing.
- The interim GUI and Status service consume these heartbeats/events so the dashboard shows ingest health, counts, and incidents in one place.
- The local `test` bootstrap path is now treated as a first-class verification concern: parts of the path work today, but the repo-supported clean-state path is not yet fully self-contained end to end.
- `python -m app.cli sync-latency-harness` now defaults to provider-free `PANEL_AGENT_DECIDER=rule` for deterministic operator validation, emits progress before long-running watcher work, and fails within a bounded timeout instead of hanging indefinitely when a live LLM provider is unavailable.
- **Sync-latency harness — partial acceptance (2026-04-12):** iCloud transport chain validated end-to-end (MacBook → Mac mini via CloudDocs); server-side watcher detection confirmed; clean numeric latency measurement not yet captured. Blocking gaps: (1) allowlist gate in `vault/@Settings/watchers.md` only permits `promote.evergreen` — `ingest.summary.create` is known but not allowlisted, so the harness exits with 0 measurements on summary-type test notes; (2) Mac mini headless infrastructure gaps (Screen Sharing, auto-login recovery) tracked in #432. Follow-up timing receipt tracked in #433. Root cause of iCloud upload-queue blockage (`.git` dir inside vault) fixed by `.git.nosync` + symlink (Issue #421 closed).

## CI & Test Markers
- CI legs assert `docs/ARCHITECTURE.md` contains fitness guard statements, confirm CLI health smoke commands pass, and verify the worker logs show `worker starting`.
- The runbook ensures `pytest -q -m "not pg and not alpha_llm"` plus curated fitness gates keep the SoT baseline stable before merges.

Validation posture note:
- blocking smoke/release gates are anchored to the active baseline in this document
- broader human-need acceptance scenarios may exist in the repo as non-blocking system-level TDD derived from `docs/HUMAN-FLOWS.md`
- failures in those broader scenarios indicate target-state gaps unless and until this status document promotes the capability into the claimed baseline

## Baseline Definition (SoT v5.5)
- Environment posture: `dev`, `test`, and `prod` are now the explicit minimal environment model in the SoT. The governing contract lives in `docs/ENVIRONMENTS.md`. `dev` and `prod` are runtime-selected environments today; `test` is the current workflow-driven bootstrap and verification environment.
- Runtime environment selection: explicit environment model for `dev` and `prod` is now canonical in the config layer (`app.config.environment`, Issue #263). The default environment is `prod` (production-safe). Operators can select `PKM_ENVIRONMENT=dev` for development/diagnostic mode, or it defaults from `PKM_SETTINGS_PROFILE`: `lab` → `dev`, `operator` → `prod`. Environment is resolved at startup and stored in `InstanceSettings.environment` within the `SettingsBundle`. This provides one documented control surface for environment-specific behavior across the runtime. See `docs/ENVIRONMENTS.md` for full specification.
- Runtime watcher: registry watcher (`configs/watchers.yaml` + `python -m app.cli watcher run`) is the default; legacy snapshot watchers are dev-only and require `PKM_SETTINGS_PROFILE=lab`.
- Runtime default: `scripts/start_full_system.sh` and `config/runtime.defaults.env` set `WATCHER_AUTO_EXEC=1` unless the operator already set a value; set `WATCHER_AUTO_EXEC=0` to run watchers in emit-only mode. Default-on does not bypass rollout discipline: once armed, any note with an AI panel fence is only a candidate, actions are still filtered through the allowlisted `watcher_settings.allowed_actions`, the only per-note opt-out is `ai_panel_auto_run: never` (nested form accepted), and manual CLI panel runs remain available. This default-on posture is intended to support autonomous proposals and low-risk action surfacing, not to force human-in-the-loop review for every trivial operation.
- Settings tiering (watcher controls): runtime defaults to `PKM_SETTINGS_PROFILE=operator` (which maps to `prod` environment); dev/lab-only watcher tuning env vars are applied only when `PKM_SETTINGS_PROFILE=lab` (which maps to `dev` environment).
- Storage baseline: `store_objects` is the canonical object table; legacy `objects` rows are best-effort migrated when needed so runtime avoids dual-table selection. Legacy `app/store/object_store.py` now delegates to canonical `app/stores` providers (compat mirror retained for tests), and `index rebuild` reads via `ObjectStore` rather than separate memory/DB query branches.
- ASK warm-load boundary: `/api/ask` hydrates HybridStore through the canonical store interface (`list_objects`) instead of backend-specific `_objects`/raw SQL introspection.
- DB outbox is canonical in runtime; JSONL (`INDEX_OUTBOX_PATH`) is audit only and should not be used as the worker queue.
- Required contracts: event compatibility/outbox envelope (`docs/EVENTS.md`), trust semantics, config-as-product, and PanelAgent wiring (`docs/PANEL_AGENT.md` + `docs/settings/panel-actions.md`).
- State-axis normalization posture: `maturity` is the canonical standing sink, `review_state` is the canonical review/mutation posture field, and legacy values such as `evergreen`, `processed`, `promoted`, `inbox`, and `logged` are compatibility-only inputs rather than preferred runtime outputs.
- Context enablement posture: the relation store now supports optional `sphere_membership`
  memberships as broader belonging metadata. This seam is additive only; operational scope still
  governs conservative runtime behavior and retrieval is not relation-driven by default.
- Minimal concurrency guarantees: DedupTaskQueue + event_id dedup guard watcher runs, optimistic writes protect note updates, and the promotion consumer uses an EventDedupStore to skip duplicate intents (`docs/CONCURRENCY.md`, `app/promotion/consumer.py`).
- Settings compiler scope: panel action catalog, watcher settings, and outbox paths now compile with provenance (path/mtime/sha) via `vault/@Settings/watchers.md`, `docs/settings/panel-actions.md`, `python -m app.cli settings-validate`, and `python -m app.cli settings-explain`.
- Operator enablement signals: `python -m app.cli settings-explain` surfaces watcher auto-exec state, allowlist validity, provenance, and write-guard context; `python -m app.cli status` exposes the same gate, watcher automation counters, last tick skips, last-run skip reasons, and panel-action/compiler provenance (source paths, mtimes, combined digest). Treat `allowlist`, `dedup/skipped_*`, `panel_skipped_policy`, and `writes_allowed` as the safe-to-enable checklist, not just the raw `WATCHER_AUTO_EXEC` value.
- Required tests: `ruff check app tests`, `mypy app`, `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q -m "not pg"`, plus `python -m app.cli settings-validate --json` and the new concurrency/promote/settings regression suites.
- CI gate workflows: `.github/workflows/ci-smoke.yaml` and `.github/workflows/ci-lite.yml` parse the fitness report summary lines (including `CI SUMMARY GATES ok=<bool>`) and exit non-zero when `GATES.ok != true`, making them the enforced gate jobs that must pass before merges to main.

## v5.6 Closure and Post-v5.6 Follow-ups

GitHub issue/PR truth treats the v5.6 delivery line as closed, not as the active work queue. Direct v5.6 issues found in the current audit are closed, including PanelAgent/ReasoningFacade/runtime surface sync, Orchestrator V2 pilot slices, runbook alignment, Quality Wave / bounded PG verification, PanelAgent 2.0 Alpha acceptance, and low-risk sync validation parent #355.

Delivered v5.6 receipts include:
- PanelAgent decider hardening through the shared `ReasoningFacade` seam: Issue #230 / PR #236.
- ReasoningFacade + LangGraph rollout for the PanelAgent pilot agent pool: Issue #231 closed COMPLETED.
- Companion note + Note Context doc-sync correction: Issue #229 / PR #237.
- Vault-as-GUI settings provenance: Issue #238 / PR #254.
- CLI/docs runbook alignment: Issue #232 closed COMPLETED.
- Nightly deterministic Quality Wave acceptance harness and first bounded PG contracts lane: Issue #274 and Issue #285 closed.
- PanelAgent 2.0 Alpha real-vault acceptance: Issue #240 / PR #381.
- Low-risk autonomy + automated sync validation: parent Issue #355 closed COMPLETED with a final acceptance receipt on 2026-04-13; #432 and #433 remain follow-up/infra/statistical timing work, not blockers for #355 closure.

Post-v5.6 follow-up truth:
- Orchestrator V2 remains flagged; `CheckpointStore` plumbing exists, but a code audit shows the V2 runtime does not call `_save_checkpoint()` during execution, so checkpoint/resume must not be claimed as supported baseline behavior.
- A2A in-process handler routing exists and the current traceability test passes, while parent lifecycle issue #359 remains open and should be treated as stale lifecycle/project drift until closed or re-scoped.
- Local runtime health verification shipped via #334/#365; repo contract drift in `tests/ops/test_runtime_verify_contract.py` and docs-index validation drift were fixed by #441 / PR #439 as local verification hardening, not as active v5.6 feature work.
- v6 target-state audits opened current-state bugs for domain/zone handling (#435, #436, #437); these are post-v5.6 bug/follow-up slices.

## Agent Evolution Track

- ASK -> deprecated as the architectural center for the v6 direction; current v5.x runtime/API compatibility remains in place.
- Retrieval -> being refactored into a reusable capability layer rather than retained as a dedicated agent.
- PanelAgent -> primary interaction surface for mutation-capable flows.
- Chat -> planned as a canvas-shaped interaction surface whose early Deep Agent introduction slice stays read-only; any future Chat-originated mutation must still pass through governed execution.
- Deep Agents -> planned only after v6.0 structural separation; not active in production mutation flows.
- Execution layer expansion -> research only.
- Governance -> active concern across policy, provenance, admissibility, approval, and auditability.

The system is not yet an autonomous agent system. All execution remains controlled and mediated.
High-level design rules for this direction now live in `docs/DESIGN_PRINCIPLES.md`; roadmap and architecture should stay aligned to that split.

## Status fields (baseline vs release line)
- `sot_baseline_version`: locked SoT v5.5 Reality-MVP baseline.
- `sot_forward_line_version` / `feature_line_version`: code-level release-line marker that still reports v5.6 on top of the v5.5 baseline; this is not proof that v5.6 remains the active issue queue.
- `active_features`: human-readable list of forward-line capabilities (PanelAgent runtime, watcher track, config-driven wiring).
- Counters (totals + 24h window): `panel_runs` (`panel.intent.executed`), `promote.intent.created`, `promotion_executed` (`promote.done`), `watcher_runs` (`watcher.run` from registry and legacy watcher ticks), and ingest run counts per plane. Registry watcher health is also tracked via heartbeat + tick logs.

## Concurrency & Safety (v5.5 gate)
- DedupTaskQueue now guards watcher auto-runs and powers the `skipped_dedup` signal before releasing keys.
- Optimistic locking keeps note writes safe; stale writes surface recoverable warnings instead of corrupting vault files.
- Event idempotency (watcher events + promotion intents) leverages deterministic `event_id`s and an EventDedupStore so repeated `promote.intent.created` lines are no-ops (`docs/EVENTS.md`, `docs/CONCURRENCY.md`, `app/promotion/consumer.py`).

## Current Snapshot

- Runtime uses the registry watcher, DB outbox, worker, ASK API, and status/health surfaces as the canonical operational path.
- Production-facing path is the active current-state default; lab/dev-only flows remain explicitly non-production.
- The local test stack can be started successfully against a separate test vault, and `uat-seed-vault-test` works.
- The repo-supported local bootstrap/UAT path is still not fully self-contained end to end; several concrete blocker issues already exist for that work.
- Issue #240 has a real-vault Alpha acceptance receipt recorded in `docs/PANEL_AGENT.md` after the 2026-04-08 server-side soak; that specific PanelAgent 2.0 acceptance gate is no longer pending.
- iCloud sync transport chain is validated end-to-end (MacBook → Mac mini via CloudDocs); the `.git.nosync` + symlink fix (Issue #421) removed the root-cause CloudDocs upload-queue blocker. Parent feature #355 is closed COMPLETED with its final acceptance receipt posted on 2026-04-13; clean statistical timing measurement and Mac mini headless infrastructure hardening remain follow-up work in #432 and #433, not blockers for #355 closure.
- The current docs-first stabilization wave is making the intended supported path explicit before further implementation continues.
- Objective: a clean-state, repo-supported local test bootstrap path that is resettable, reproducible, verified, and acceptable as the canonical local verification flow.
- PanelAgent runtime V1 is part of the active baseline; planner pipeline and LangGraph expansion remain opt-in.
- Legacy snapshot watchers remain available only for lab/dev workflows and are not part of the runtime default.
- Eval suites remain opt-in diagnostics; they do not define baseline health by themselves.

## Forward-Line Tracking

| Area | Current baseline posture | Follow-up direction |
| --- | --- | --- |
| Watcher auto-exec | Guarded by dedup + optimistic writes + idempotency | Safe enablement only after gates and receipts prove stable behavior |
| LangGraph rollout | Active for ASK and PanelAgent-related flows; the shared `ReasoningFacade` seam is adopted for the PanelAgent pilot (Issue #231 delivered) | Expand in phases as additional agent pools (Promotion/Reviewer/Hygiene) migrate onto the shared `ReasoningFacade`; treat this as post-v5.6 adoption work rather than an open v5.6 blocker. |
| Orchestrator V2 pilot | Shipped/flagged: parallel execution + dependency-aware scheduling with `ORCHESTRATOR_VERSION=v2`; V1 is default. Coverage: flag contract, plan-graph scheduling, event/trace compat, compensation/rollback, and retry metadata handling. `CheckpointStore` plumbing exists, but checkpoint/resume is not the supported baseline execution path. Delivery receipts include Issue #250 (pilot), Issue #251 (compensation), and Issue #252 (checkpoint/retry handling). | Future slices: checkpoint/resume hardening (#444), retry/backoff observability (#445), broader timeout/SLA policy beyond executor-level tool timeouts (#446), and adoption after stability signals. |

For detailed sequencing, version history, and roadmap ladder, use:
- `docs/ROADMAP.md`
- `docs/plans/V56_FORWARD_LINE.md`
- `docs/history/SOT_4X_HISTORY.md`

## GitHub delivery governance snapshot

Repo-side governance added:
- task Issue form
- blank Issue disablement
- PR template requiring Issue linkage
- governance workflow checking Issue shape and PR Issue linkage
- machine-readable GitHub governance contract in `.github/github-governance.yml`

Platform-side governance applied:
- the exact delivery-control-plane labels now exist in the repository
- GitHub Project v2 `Agent Delivery Control Plane` now exists and is linked to `RasmusTho/agentic-pkm-mvp`
- Project field `Status` now uses `Backlog`, `Ready`, `In Progress`, `Review`, `Done`
- Project field `Agent State` now exists with `Idle`, `Running`, `Waiting`
- required views `Kanban` and `Agent Queue` are now present in the Project
- built-in Project lifecycle automation is now configured for issue/PR status transitions
- the active governance issues/PR were seeded into the project with initial state values

Observed before this change:
- existing Issues were present but not normalized to a strict machine-readable task contract
- recent PR practice showed inconsistent Issue-linking and branch naming conventions
- no dedicated repo workflow enforced the Issue/PR contract

Known remaining gap:
- branch protection/rules were not adopted in this change

Target delivery model:
- Issues = canonical task contract
- Project = state machine
- agents = execution layer
- PR = implementation artifact
- CI = validation gate
