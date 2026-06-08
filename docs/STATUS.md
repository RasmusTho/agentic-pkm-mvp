State: SoT v5.5 Reality-MVP baseline locked (watcher auto-run gate, panel action provenance, and concurrency guard); v5.6 delivery line closed; v6.0 seams baseline shipped at capability-seam level (closed capability spec directories plus minimal orientation/resurfacing/commitment-domain/context-dimensions runtimes and read-only Chat cognition scaffold); broader v6.0 runtime consumption is deferred as v6.1+. Post-v5.6 follow-ups are tracked separately for LangGraph/Reasoning expansion, Orchestrator V2 hardening, A2A/MCP lifecycle cleanup, and local verification hardening. Contextualization Layer docs/spec package (#1093–#1097) delivered 2026-05-19 (life-wide taxonomy, context activation semantics, metadata contract update, media artifact contract, ingestion/triage policy, vault templates, vault audit runbook — docs-only, no runtime behavior changed). Agent Memory runtime slices for candidate/review/promotion/recall explanation/authority guard plus companion-note-aware handling are now shipped (#1079/#1080/#1081/#1082/#1083/#1085). Companion UI: substantial dev/staging-shell capability now shipped to main. The vault Markdown renderer covers §6 typography, callouts, tables, images (real-image fixture verified), and resolved/diagnostic wikilinks, with client-rendered Mermaid that fails gracefully (#1335 umbrella: #1334/#1338/#1340/#1341; #1332 Markdown/editor UAT: Mermaid #1344/PR #1433, wikilink resolver #1345/PR #1432, image fixture #1347/PR #1430, task/code retest #1348). The shell is an adaptive single-shell workspace with one left context panel, a canonical Vault Browser, single-shell scroll ownership, and rail/folder-density compaction (#1395 corrective: #1397/#1398/#1399/#1400/#1401 plus hardening #1417/#1418/#1419/#1425/#1427). Body-edit is wired through `active_note_body_update` with writeguard and an unsaved-edit signal, behind a fixed-height edit composer (#1346/PR #1434, #1416/PR #1429). The governance endpoint stub was replaced with a real CanvasPanelPipeline; the Panel correction path and source-backed read-mode checkbox projection are implemented. Note-independent workspace orientation is now shipped through a contract, API, re-entry UI, leave-point cursor, and MemoryCandidate intent ADR/runtime seam (#1457/#1460/#1461/#1463/#1464/#1466). This remains dev/staging-shell and v6.1 orientation work; broader production Companion UI hardening and packaging remain issue-first.
Doc role: Core SoT
Authority: Current operational snapshot for the active baseline; subordinate to concept contracts for normative semantics, but authoritative for current runtime status and rollout posture.
Owner: Runtime / current-state SoT
Temporal class: operational
Review cadence: weekly
Source of truth: mixed
Last reviewed: 2026-06-05
Last verified against: docs/ARCHITECTURE.md, docs/ROADMAP.md, docs/DOCS_INDEX.md, docs/OPERATIONS.md, docs/HUMAN-FLOWS.md, docs/SECURITY_ARCHITECTURE.md, docs/SECURITY_TRUST_BOUNDARIES.md, docs/SECURITY_DATA_FLOWS.md, docs/security/API_SECURITY_MATRIX.md, docs/security/STRIDE_LITE_REVIEW_2026_06_04.md, docs/PANEL_AGENT.md, docs/COMPANION_UI_PRODUCT_SPEC.md, docs/CANVAS_CHAT_SURFACE/README.md, docs/ENVIRONMENTS.md, docs/EVENTS.md, docs/OBSERVABILITY.md, docs/RELEASE_CHANNELS/README.md, docs/RELEASE_CHANNELS/TERMINOLOGY.md, docs/plans/MAJOR_ROADMAP_RESET_2026_06_04.md, docs/runbooks/UAT_PANEL_WATCHER.md, docs/VAULT_BROWSER_CAPABILITY_CONTRACT.md, docs/CONCEPTS/VAULT_TOPOLOGY_CONTRACT.md, companion-ui/docs/PANEL_COMPANION_UI_CONTRACT.md, companion-ui/docs/PANEL_CONFIRMATION_API_CONTRACT.md, companion-ui/docs/PANEL_DURABLE_PROJECTION_MAPPING.md, companion-ui/docs/WORKSPACE_ORIENTATION_CONTRACT.md, companion-ui/docs/COMPANION_UI_STATE_MAP.md, app/cli/health.py, app/api/routes/health.py, app/knowledge/write_ops.py, app/knowledge/locators.py, app/db/dsn.py, app/ingest/vault_alpha.py, app/watcher/registry.py, tests/api/test_health_api.py, tests/knowledge/test_write_ops.py, tests/watcher/test_panel_watcher_outbox_db.py, merged PRs #1085/#1460/#1461/#1463/#1464/#1466/#1475/#1486/#1490/#1525/#1526/#1488/#1487/#1459/#1534/#1535/#1536/#1537/#1538/#1551/#1552/#1569/#1570/#1571/#1572/#1574/#1577/#1581/#1582/#1583/#1584/#1585/#1586/#1591, GitHub issue #1085 closed 2026-05-22, GitHub issue #1457 implementation evidence, closed issues #1559/#1565/#1566 (delivered via PRs #1574/#1577), closed bug #1576 (completed 2026-06-05), Companion UI test-suite repair #1443 / PR #1475 (`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/companion_ui` -> 1260 passed, 1 skipped), and current repo state at 9b0564b2 on 2026-06-05

Status snapshot now includes SoT baseline + release-line fields and intent/event counters (`promote.intent.created`, `panel.intent.executed`, `watcher.run`, ingest runs by plane). Code still exposes `sot_forward_line_version` / `feature_line_version` as the v5.6 release-line marker, but GitHub issue truth treats v5.6 as delivered rather than active. `watcher_runs` now counts watcher audit events from the registry watcher as well as the legacy snapshot watcher, while runtime health still relies on heartbeat + tick logs.

Concept anchors: layering, portability, archive exposure, trust semantics, event compatibility, and config-as-product are now defined as concept contracts under `docs/CONCEPTS/` and are considered the canonical statements of intent. This status document describes operational snapshots and may lag those contracts.

Roadmap reset note: `docs/plans/MAJOR_ROADMAP_RESET_2026_06_04.md` is the accepted strategic reset
input for sequencing, not a runtime-promotion document. This status file remains the current-state
owner doc. Capabilities should be read as shipped only when code plus tests or operator evidence are
present and any owner-doc promotion gate has been satisfied.

Security review note: the security architecture spine (`docs/SECURITY_ARCHITECTURE.md` plus its
trust-boundary, data-flow, API-matrix, and STRIDE-lite companions) is now the review-routing owner
for security framing. The recent security hardening PRs (#1581-#1586/#1591) add review inputs and
targeted path/error-detail fixes; they do not change the local-first runtime exposure model or
promote public internet readiness.

## Health spine
- HealthContract + WriteGuard + incident logging now form the deterministic spine for startup readiness; this snapshot is the baseline for initial go-live visibility.

## Runtime verification
- `/api/health` reports watcher and worker heartbeat freshness plus the runtime DB/LLM probes so operators see deterministic health signals.
- `scripts/start_full_system.sh` and `scripts/gap_test_alpha.sh` drive the registry watcher → DB outbox → worker → index → `/api/ask` chain, emit `watcher.run` audit rows plus `index.embedding.created` / `index.embedding.failed` (legacy alias: `index.object.embedded`), and log diagnostics when sources are missing.
- `/api/orientation` now provides a minimal read-only orientation runtime seam that returns a situational frame without a query term; explanation remains bounded to `leave_point`, `open_items`, and `notable_change` derived from runtime signals.
- Leave-point cursor lookup now applies scope filtering at the DB boundary and uses a wider corrupt-row recovery candidate window; this is hardening of the existing read-only orientation seam, not a new mutation surface or semantic authority.
- Workspace orientation and Companion UI repair hardening keeps placeholder "no unresolved" text out of returned open loops, requires independent signal categories before emitting MemoryCandidate handoff intents, preserves non-UTC authored timestamp offsets in Vault Browser metadata, exposes previous-page cursor metadata for Vault Browser navigation, renders structured leave-point fields (`logical_ref`/`artifact_uuid`/`captured_at`), and keeps direct note-save paths and proxied runtime error details bounded to the active vault/runtime response.
- `app/resurfacing/runtime.py` now provides a minimal non-mutating resurfacing evaluator seam that
  does not require a query, derives relevance-change candidates from runtime status signals, emits
  explicit "why now" explanations with signal provenance, and exposes operator-visible receipt/status
  summaries without automatic writes.
- The interim GUI and Status service consume these heartbeats/events so the dashboard shows ingest health, counts, and incidents in one place.
- The local `test` bootstrap path is now treated as a first-class verification concern: parts of the path work today, but the repo-supported clean-state path is not yet fully self-contained end to end.
- `python -m app.cli sync-latency-harness` now defaults to provider-free `PANEL_AGENT_DECIDER=rule` for deterministic operator validation, emits progress before long-running watcher work, and fails within a bounded timeout instead of hanging indefinitely when a live LLM provider is unavailable.
- **Sync-latency harness — partial acceptance (2026-04-12, updated 2026-04-23):** iCloud transport chain validated end-to-end (MacBook → Mac mini via CloudDocs); server-side watcher detection confirmed; clean numeric latency measurement not yet captured. The allowlist blocker is now resolved for harness/operator runs via measurement mode (`WATCHER_MEASUREMENT_MODE=1`), which temporarily admits `ingest.summary.create` while preserving the default production-safe allowlist posture. Remaining blocker: Mac mini headless infrastructure gaps (Screen Sharing, auto-login recovery) tracked in #432. Follow-up timing receipt tracked in #433. Root cause of iCloud upload-queue blockage (`.git` dir inside vault) fixed by `.git.nosync` + symlink (Issue #421 closed).

## CI & Test Markers
- CI legs assert `docs/ARCHITECTURE.md` contains fitness guard statements, confirm CLI health smoke commands pass, and verify the worker logs show `worker starting`.
- The runbook ensures `pytest -q -m "not pg and not alpha_llm"` plus curated fitness gates keep the SoT baseline stable before merges.

Validation posture note:
- blocking smoke/release gates are anchored to the active baseline in this document
- broader human-need acceptance scenarios may exist in the repo as non-blocking system-level TDD derived from `docs/HUMAN-FLOWS.md`
- failures in those broader scenarios indicate target-state gaps unless and until this status document promotes the capability into the claimed baseline

## Version framing consistency note

| Version framing | Role | Authoritative doc |
| --- | --- | --- |
| v5.5 (SoT baseline locked) | Current operational runtime; no new feature scope | `docs/ARCHITECTURE.md`, `docs/STATUS.md` |
| v5.6 (delivered/closed) | Historical delivery line; read as shipped invariants | `docs/ROADMAP.md#closed-v56-delivery-line`, `docs/STATUS.md#v56-closure` |
| v6.0 seams (baseline shipped) | Capability-seam baseline on top of v5.5/v5.6: closed capability spec dirs plus minimal orientation/resurfacing/commitment-domain/context-dimensions runtimes and read-only Chat cognition scaffold. Safe for production. | `docs/ROADMAP.md`, `docs/ARCHITECTURE.md`, capability spec dirs under `docs/FINDING_AND_REORIENTING/`, `docs/INTERACTION_SURFACES_AND_AUTHORITY/`, `docs/SEPARATING_PERSISTENCE_SURFACES/`, `docs/COMMITMENT_AS_FIRST_CLASS/`, `docs/SCOPE_SPHERE_SITUATED_IDENTITY/` |
| v6.1+ (planned, post-seams) | Broader target-state runtime work the seams enable; not yet baseline | `docs/plans/V60_ARCHITECTURE_TARGET.md`, `docs/plans/V60_CAPABILITY_AND_AGENT_EVOLUTION.md`, `docs/plans/V60_COGNITIVE_SUPPORT_PRIORITIES.md` |

Use `docs/ARCHITECTURE.md` for current-state runtime questions. Use `docs/ROADMAP.md` and the v6 plans for target-state design direction questions. Do not read v5.5 as an active work queue; new implementation work is sliced against v6 target-state docs.

Interaction-surface status: Panel is the shipped command-oriented mutation surface. A read-only Chat
cognition scaffold exists for planning/decomposition through the shared `ReasoningFacade`; it does
not execute tools, write notes, emit outbox mutations, or emit promotion/action intents. In
addition, a flag-gated canvas session slice exists for direct in-place note-body editing plus
governance routing (`CANVAS_ENABLED=1`; CLI/API session flow; body-only edits, frontmatter and
cross-note mutations rejected or routed through governance). This canvas slice is not part of the
SoT v5.5 baseline/default runtime posture, and broader canvas-Chat co-editing plus hybrid
Panel/Chat integration remain v6/non-baseline surfaces. The interaction authority split is still
governed by
`docs/INTERACTION_SURFACES_AND_AUTHORITY/DEFINE_CANVAS_COEDITING_MODEL.md`,
`docs/INTERACTION_SURFACES_AND_AUTHORITY/DEFINE_PANEL_AS_THE_PRIMARY_COMMAND_SURFACE.md`, and
`docs/INTERACTION_SURFACES_AND_AUTHORITY/HYBRID_CHAT_INTEGRATION_SCHEMA.md`.

## Baseline Definition (SoT v5.5)
- Environment posture: `dev`, `test`, and `prod` are now the explicit minimal environment model in the SoT. The governing contract lives in `docs/ENVIRONMENTS.md`. `dev` and `prod` are runtime-selected environments today; `test` is the current workflow-driven bootstrap and verification environment.
- Runtime environment selection: explicit environment model for `dev` and `prod` is now canonical in the config layer (`app.config.environment`, Issue #263). The default environment is `prod` (production-safe). Operators can select `PKM_ENVIRONMENT=dev` for development/diagnostic mode, or it defaults from `PKM_SETTINGS_PROFILE`: `lab` → `dev`, `operator` → `prod`. Environment is resolved at startup and stored in `InstanceSettings.environment` within the `SettingsBundle`. This provides one documented control surface for environment-specific behavior across the runtime. See `docs/ENVIRONMENTS.md` for full specification.
- Runtime watcher: registry watcher (`configs/watchers.yaml` + `python -m app.cli watcher run`) is the default; legacy snapshot watchers are dev-only and require `PKM_SETTINGS_PROFILE=lab`.
- Runtime default: `scripts/start_full_system.sh` and `config/runtime.defaults.env` set `WATCHER_AUTO_EXEC=1` unless the operator already set a value; set `WATCHER_AUTO_EXEC=0` to run watchers in emit-only mode. Default-on does not bypass rollout discipline: once armed, any note with an AI panel fence is only a candidate, actions are still filtered through the allowlisted `watcher_settings.allowed_actions`, the only per-note opt-out is `ai_panel_auto_run: never` (nested form accepted), and manual CLI panel runs remain available. This default-on posture is intended to support autonomous proposals and low-risk action surfacing, not to force human-in-the-loop review for every trivial operation.
- Settings tiering (watcher controls): runtime defaults to `PKM_SETTINGS_PROFILE=operator` (which maps to `prod` environment); dev/lab-only watcher tuning env vars are applied only when `PKM_SETTINGS_PROFILE=lab` (which maps to `dev` environment).
- Storage baseline: `store_objects` is the canonical object table; legacy `objects` rows are best-effort migrated when needed so runtime avoids dual-table selection. Legacy `app/store/object_store.py` now delegates to canonical `app/stores` providers (compat mirror retained for tests), and `index rebuild` reads via `ObjectStore` rather than separate memory/DB query branches.
- ASK warm-load boundary: `/api/ask` hydrates HybridStore through the canonical store interface (`list_objects`) instead of backend-specific `_objects`/raw SQL introspection.
- Orientation posture: `/api/orientation` is additive to ASK and not a full cognitive rollout; it is a bounded read-only runtime surface with no mutation intents.
- Resurfacing posture: `app/resurfacing/runtime.py` is additive and read-only; resurfacing outputs are
  candidate summaries plus provenance-bearing explanations/receipts, not mutation intents or artifact
  writes.
- DB outbox is canonical in runtime; JSONL (`INDEX_OUTBOX_PATH`) is audit only and should not be used as the worker queue.
- Required contracts: event compatibility/outbox envelope (`docs/EVENTS.md`), trust semantics, config-as-product, and PanelAgent wiring (`docs/PANEL_AGENT.md` + `docs/settings/panel-actions.md`).
- State-axis normalization posture: `maturity` is the canonical standing sink, `review_state` is the canonical review/mutation posture field, and legacy values such as `evergreen`, `processed`, `promoted`, `inbox`, and `logged` are compatibility-only inputs rather than preferred runtime outputs.
- Context enablement posture: the relation store now supports optional `sphere_membership`
  memberships as broader belonging metadata. This seam is additive only; operational scope still
  governs conservative runtime behavior and retrieval is not relation-driven by default.
- Retrieval capability seam: salience/staleness signal payload exists as an optional diagnostics
  seam and is emitted only on explicit opt-in. Runtime does not source staleness from persisted
  state-axis labels in artifact payload (`review_state`, `maturity`).
<!-- commitment-runtime-baseline -->
- Commitment-runtime baseline: bounded `next`/`waiting` commitment query surfacing is present in
  the domain layer; commitment state values remain distinct from note state axes; commitment-state
  transitions carry receipt-linkage metadata and are gated through the receipt-governed APPLY path
  — state mutations not on the APPLY path are rejected (PR #703, issue #694); and the commitment
  query surface consumes optional salience/staleness signals for priority surfacing (PR #705,
  issue #695). Verification: `tests/commitments/test_commitment_receipt_gate.py`,
  `tests/commitments/test_commitment_salience_queries.py`.
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
- This PR adds two target-state contract docs: `docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md` and `docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md`. It does not change runtime behavior.
- Orchestrator V2 remains flagged; checkpoint/resume has been hardened (Issue #444): `_save_checkpoint()` is now called at the configured interval (default every 3 steps), checkpoints are persisted in CheckpointStore, and resume-on-load is implemented to skip already-completed steps and restore execution state.
- Retry/backoff observability has shipped for the flagged V2 path (Issue #445 / PR #452), including retry events, backoff diagnostics, and terminal retry-exhausted tracking. The follow-up timeout discriminator mismatch where documented executor `tool_timeout` errors could retry in V2 was fixed by Issue #456 / PR #458.
- A2A in-process handler routing exists, the current traceability test passes, and parent lifecycle issue #359 is now closed.
- Local runtime health verification shipped via #334/#365; repo contract drift in `tests/ops/test_runtime_verify_contract.py` and docs-index validation drift were fixed by #441 / PR #439 as local verification hardening, not as active v5.6 feature work.
- v6 target-state audits opened current-state bugs for domain/zone handling (#435, #436, #437). The retrieval domain fallback fix shipped via #435 / PR #453, the ASK zone computation fix shipped via #436 / PR #454, domain validation and recording shipped via #437 / PR #460, and whitespace-only domain normalization shipped via PR #470.

## Agent Evolution Track

- ASK -> deprecated as the architectural center for the v6 direction; current v5.x runtime/API compatibility remains in place.
- Retrieval -> being refactored into a reusable capability layer rather than retained as a dedicated agent.
- PanelAgent -> primary interaction surface for mutation-capable flows.
- Chat -> canvas-shaped interaction now has a materially shipped bounded co-authoring surface behind `CANVAS_ENABLED` (session logs, body-scoped editing, governance routing), while the broader cognition path remains read-only and hybrid Panel/Chat mutation remains follow-up work under governed execution.
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
- Context Bundles production runtime integration is shipped and closed: parent #1559 closed
  2026-06-04 after the read-only construction route (#1560), real retrieval emission (#1562),
  orientation/resurfacing consumption (#1563), governed write-proposal linkage (#1564), and the
  read-only receipt projection (#1565) merged, with owner docs promoted in #1566. The stable
  bundle addressing follow-up on the retrieval-backed route (#1576) closed 2026-06-05; no bounded
  Context Bundles items remain.
- The emitted ContextBundle consumption repair is shipped: retrieval-backed bundle queries record
  emitted bundles in a bounded process-local addressability registry, and the production
  orientation/resurfacing bundle routes resolve through that registry instead of reconstructing the
  synthetic construction envelope. This remains read-only, non-durable, and non-authoritative:
  `may_write` stays false and missing or evicted bundle ids fail honestly.
- Direct runtime repairs from PR #1573 keep retrieval-backed ContextBundle routes stable by
  preserving the requested bundle id in emitted bundles/receipts, and keep knowledge-compilation
  proposal builders aligned with canonical review posture by accepting `review_state: protected`
  sources alongside `reviewed` and `accepted` while still rejecting non-approved states.
<!-- memory-context-admissibility-default -->
- Memory/context admissibility default documented (#1598): the conservative admissibility posture
  is now recorded in `docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md` and
  `docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md`. The shipped bounded seams (Agent Memory runtime
  slices #1079–#1085; Context Bundles production integration #1559) remain in place; this note
  distinguishes their bounded read-side/proposal posture from a broader memory/context influence
  policy that has not shipped. Memory/context may support read-side awareness, orientation, and
  resurfacing when provenance is visible. It may influence proposals only as cited support with
  review/provenance posture surfaced. It must not authorize mutation or override human-authored
  truth. Context Bundles keep `may_write=false` unless a later governed contract explicitly
  changes that posture. No new runtime enforcement was added by #1598; the constraint is normative
  and drives future follow-up implementation issues if concrete enforcement gaps are identified.
- Runtime AgentState contract unification is shipped for the current ASK, generic graph, reasoning
  graph-builder, and PanelAgent state surfaces: `app/agents/runtime_state.py` defines the shared
  trace/authority/proposal/receipt linkage fields and the existing state classes now expose or adapt
  to that contract. This is runtime linkage only; it does not grant durable memory semantics or
  bypass WriteGuard/governance authority.
- BuilderOps Vault is shipped as a build-plane runtime: `app/builderops/` provides the store,
  schema, projections, promotion gateway, and boundary layer with CLI and API surfaces, covered by
  `tests/builderops/`, `tests/cli/test_builderops_cli.py`, and `tests/api/test_builderops_api.py`.
  Per `docs/adr/ADR-0010-builderops-vault-authority-boundary.md` it governs builder-operations
  material only; its records and generated projections are explicitly non-authoritative for
  product/runtime truth and never bypass repo authority gates. (ADR-0010's "not implemented" header
  predates this store/CLI/API delivery under the #1500-series follow-ups and is the stale surface to
  reconcile next.)
- Canvas co-authoring is materially implemented behind `CANVAS_ENABLED`: `canvas open` / `edit` /
  `close`, `/api/canvas/sessions*`, session-log persistence, and governance-bearing mutation routing
  are shipped; broader Chat cognition and hybrid Panel/Chat mutation remain separate follow-up work.
- Panel confirmation is now a bounded shipped runtime path: `POST /api/panel/confirm` confirms
  explicit panel actions through the governed confirmation path, preserves blocked/rejected receipts,
  and the runtime/client surface now includes `GET /api/artifacts/note` plus the companion-app
  real-note workspace shell and confirm-refresh flow for read-only artifact hydration after
  confirmation.
- Vault Browser `queue_review` now stages a pending Panel governance proposal through
  `POST /api/companion/vault-browser/actions/queue-review` when server-resolved artifact scope is
  available. This is only queue staging: durable execution and receipt-supporting records remain
  behind `POST /api/panel/confirm`.
- Companion UI operational loop (inspect → queue → confirm → receipt) is now a coherent, inspectable
  control surface over the existing shipped surfaces (#1603). The queue-review response names its
  loop position (`loop_stage: "queued_pending_confirmation"`), the Panel confirmation response exposes
  an explicit receipt-visibility posture (`receipt_visibility`: `durable_vault_visible` /
  `blocked_no_durable_receipt` / `none_rejected`), and the companion-app dev shell renders a
  derived, read-only operational-loop region showing receipt posture. This wires the existing surfaces
  into one loop; it does not bypass Panel confirmation, WriteGuard, or trust semantics, does not make
  the UI durable authority, and is bounded to the proven loop — broader Companion UI production
  packaging and full Chat mutation remain separate target-state work. The loop was verified on the
  live Niflheim dev runtime by a real-note UAT (#1604, 2026-06-06): the governed `queue_review`
  confirm/reject path executed end-to-end with durable receipts visible in the governance/receipt
  layer (orientation governance summary, `panel.receipts`). The UAT is bounded to that
  governance-handoff path; the in-note checkbox-projection path is separately verified for durable
  source-backed `- [x]` projection (#1621, 2026-06-06): see `docs/PANEL_AGENT.md` (In-note
  checkbox-projection receipt loop — #1621) for the narrowed fixture evidence. AI-status callout
  receipt visibility on that path is runtime-result specific, not a universal claim for every
  mapped/logged action. The two receipt paths are distinct: the `queue_review` +
  `POST /api/panel/confirm` path writes a durable receipt into the governance/receipt layer
  (`panel.receipts`, `receipt_visibility`); the `POST /api/panel/checkbox-projection` path writes a
  durable checked checkbox directly into the vault note Markdown and may also surface an AI-status
  callout when the invoked Panel runtime path emits one.
- Cognitive-load Phase 0 verification snapshot (#1638/#1657, 2026-06-07; fixed by #1698,
  2026-06-08): code inspection of
  `app/panel/checkbox_projection.py` confirms the source-backed checkbox-projection path validates
  `expected_content_hash`, resolves artifact identity, validates `expected_source_hash`, verifies
  option selectability, and calls `WriteGuard.assert_writes_allowed("panel.checkbox_projection")`
  before `write_note_from_absolute(...)`. The endpoint now narrows its response contract: a
  successful source-backed checkbox projection plus runtime invocation returns `status="projected"`
  when no response-level receipt/callout evidence is present, with `receipt=None`. It must not
  report `status="executed"` merely because the invoked runtime returned internal results; any future
  `executed` response must carry response-level receipt/callout evidence.
  Display/listening preference verification found no implemented preference write path; current TTS
  endpoints (`POST /api/companion/tts/plan`, `POST /api/companion/tts/synthesize`) are local-first
  speech planning/synthesis and not preference persistence. `WORKSPACE_STATE_CONTRACT.md` remains
  the storage-home owner for future local UI preference state. Orientation and resurfacing read
  paths remain read-side projections; context-bundle consumption explicitly keeps `may_write=false`.
  Runtime/UI fixing for #1690 remains gated by the issue pickup rule because the issue is labelled
  `agent:ready` but Project status is currently `Backlog`, not `Ready`.
<!-- authority-spine-diagnostic -->
- Authority spine diagnostic surfaced in health API (#1601): `/api/health` now includes an
  `authority_spine` key with bounded operator-visible posture strings (`write_guard`,
  `authority_non_upgrade`, `provenance_required_for_mutations`, `read_projection_isolation`).
  This is a diagnostic surface only — it does not grant or deny authority and must not be
  treated as a semantic authority source. See `docs/HEALTH.md#authority-spine-diagnostic`.
<!-- receipt-event-boundary -->
- Receipt/event boundary documented (#1600): `OutboxEvent` (operational trace) and `Receipt`
  (accountability record) are structurally distinct. For governed mutation paths (`POST
  /api/panel/confirm`), `ConfirmResponse` carries both a `Receipt` (with `action_taken`,
  `inverse_action`) and `events_emitted` (list of trace names); these surfaces must not be
  conflated. For read-only projection paths (orientation, resurfacing, vault browser reads),
  only operational traces are emitted and no receipt is returned. The boundary is asserted by
  `tests/runtime/test_receipt_event_boundary.py` and documented in `docs/EVENTS.md` and
  `docs/CONCEPTS/RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md`.
- Runtime event envelopes emitted through the shared outbox helper now include `meta.instance_provenance` (`instance_id`, `instance_role`, `environment`) as backward-compatible operational metadata.
<!-- agent-state-spine-contract -->
- Agent-state spine contract verified (#1625): the shared runtime-state linkage spine (`trace_id`,
  `authority`, `authority_basis`, `proposal_id`, `receipt_event_id`) defined in
  `app/agents/runtime_state.py` is now formally documented and compliance-tested. All five active
  agent state surfaces (`AskAgentState`, `GraphAgentState`, `AgentStateBase`, `PanelAgentState`, `PilotAgentState`)
  satisfy the contract. A lightweight architecture compliance gate
  (`tests/architecture/test_agent_state_spine.py`) ensures future state classes surface any spine
  gap before reaching production. The spine is intentionally narrow: it standardises trace
  identity, authority posture, proposal linkage, and receipt linkage without granting durable
  memory or bypassing WriteGuard. See `docs/ARCHITECTURE.md#agent-state-spine-contract`.
- Panel mutation gating now enforces explicit trust-verb classification on mutation-capable panel actions: only admitted `APPLY` actions can emit promotion mutation intents; `SUGGEST` remains non-mutating unless promoted through the governed execution path.
- APPLY transition receipts (`promotion.transition.applied`) now include accountability fields (`verb`, `authority`, `basis`, `outcome`, `artifact_linkage`, `instance_provenance`) as backward-compatible payload extensions.
- Status summaries now expose instance provenance (`instance_id`, `instance_role`, `environment`) for runtime attribution; this does not change artifact identity or companion note identity semantics.
- Production-facing path is the active current-state default; lab/dev-only flows remain explicitly non-production.
- The local test stack can be started successfully against a separate test vault, and `uat-seed-vault-test` works.
- The repo-supported local bootstrap/UAT path is still not fully self-contained end to end; several concrete blocker issues already exist for that work.
- Issue #240 has a real-vault Alpha acceptance receipt recorded in `docs/PANEL_AGENT.md` after the 2026-04-08 server-side soak; that specific PanelAgent 2.0 acceptance gate is no longer pending.
- iCloud sync transport chain is validated end-to-end (MacBook → Mac mini via CloudDocs); the `.git.nosync` + symlink fix (Issue #421) removed the root-cause CloudDocs upload-queue blocker. Parent feature #355 is closed COMPLETED with its final acceptance receipt posted on 2026-04-13; clean statistical timing measurement and Mac mini headless infrastructure hardening remain follow-up work in #432 and #433, not blockers for #355 closure.
- The current docs-first stabilization wave is making the intended supported path explicit before further implementation continues.
- Objective: a clean-state, repo-supported local test bootstrap path that is resettable, reproducible, verified, and acceptable as the canonical local verification flow.
- PanelAgent runtime V1 is part of the active baseline; planner pipeline and LangGraph expansion remain opt-in.
- Canvas co-authoring exists in the repo behind `CANVAS_ENABLED` with session logs, body-scoped co-authoring, and governance-intent routing. It is materially supported as a bounded human-facing surface, but it is still gated and is not part of the default production operator surface.
- Legacy snapshot watchers remain available only for lab/dev workflows and are not part of the runtime default.
- Eval suites remain opt-in diagnostics; they do not define baseline health by themselves.
- Full replica-aware behavior (conflict handling, distributed authority, sync transport semantics) remains post-baseline work.

## Forward-Line Tracking

| Area | Current baseline posture | Follow-up direction |
| --- | --- | --- |
| Watcher auto-exec | Guarded by dedup + optimistic writes + idempotency | Safe enablement only after gates and receipts prove stable behavior |
| LangGraph rollout | Active for ASK and PanelAgent-related flows; the shared `ReasoningFacade` seam is adopted for the PanelAgent pilot (Issue #231 delivered) | Expand in phases as additional agent pools (Promotion/Reviewer/Hygiene) migrate onto the shared `ReasoningFacade`; treat this as post-v5.6 adoption work rather than an open v5.6 blocker. |
| Orchestrator V2 pilot | Shipped/flagged: parallel execution + dependency-aware scheduling with `ORCHESTRATOR_VERSION=v2`; V1 is default. Coverage: flag contract, plan-graph scheduling, event/trace compat, compensation/rollback, retry metadata handling with structured observability (retry events, backoff diagnostics, terminal failure tracking), checkpoint/resume with configurable interval persistence (Issue #444), bounded per-tool timeout/SLA contract coverage from Issue #446 / PR #448, and optional plan-level timeout budgets via `plan_timeout_seconds` from Issue #540 / PR #555. Per-tool timeout via `tool_timeout_seconds` and optional plan-level timeout via `plan_timeout_seconds` are supported on both V1 and V2 (see `docs/contracts/TIMEOUT_AND_SLA_CONTRACT.md` for the complete contract). Delivery receipts include Issue #250 (pilot), Issue #251 (compensation), Issue #252 (checkpoint/retry handling), Issue #444 (checkpoint/resume hardening), Issue #445 (retry/backoff observability), Issue #446 (timeout/SLA contract), and Issue #540 (plan timeout budget). | Future slices: repo-wide A2A/runtime delivery SLA, and V2 adoption after stability signals. |

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
- delivery feedback loop governance for learning capture, retrospective review, and post-merge owner-doc receipt enforcement

Platform-side governance applied:
- the exact delivery-control-plane labels now exist in the repository
- GitHub Project v2 `Agent Delivery Control Plane` now exists and is linked to `RasmusTho/agentic-pkm-mvp`
- Project field `Status` now uses `Backlog`, `Ready`, `In Progress`, `Review`, `Done`
- Project field `Agent State` now exists with `Idle`, `Running`, `Waiting`
- required views `Kanban` and `Agent Queue` are now present in the Project
- built-in Project lifecycle automation is now configured for issue/PR status transitions
- the active governance issues/PR were seeded into the project with initial state values
- local Agent Issue Dispatcher hot-path coordination is now active: agents use dispatcher
  `status` / `next` / `claim` / `heartbeat` / `complete` for operational pickup while GitHub
  Issues, labels, and PR state remain the durable lifecycle truth

Observed before this change:
- existing Issues were present but not normalized to a strict machine-readable task contract
- recent PR practice showed inconsistent Issue-linking and branch naming conventions
- no dedicated repo workflow enforced the Issue/PR contract

Known remaining gaps: none — branch protection with required status checks (`smoke`, `smoke-docker`, `pr-contract`) was added to `stable` on 2026-05-10 (issue #844, PR #853).

Target delivery model:
- Issues = canonical task contract
- Project = state machine
- agents = execution layer
- PR = implementation artifact
- CI = validation gate

## Documentation follow-up (2026-05-12)

The cognitive prosthesis documentation spine added on 2026-05-12 introduces:

- `docs/COGNITIVE_PROSTHESIS_CHARTER.md` — product thesis.
- `docs/HUMAN_FLOW_TO_RUNTIME_MAP.md` — human-flow to runtime bridge.
- `docs/READING_PATHS.md` — practical reading paths.

These docs frame intent; they do not change runtime behavior and do not assert that all
target-state capabilities are implemented. The following companion docs are *recommended
follow-up PRs* — they are **not** delivered by the spine PR and should be authored later when
their owning surface needs the contract:

- `docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md` — bounded, inspectable agent memory
  and its relationship to human-authored knowledge.
- `docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md` — what a context bundle is, how it is assembled,
  and what it must carry as provenance.
- `docs/CONCEPTS/VAULT_TOPOLOGY_CONTRACT.md` — consolidating contract over vault layout,
  catalog projection, context/artifact dimensions, and persistence-surface separation; should
  reference rather than duplicate `docs/CONCEPTS/CATALOG_PROJECTION_PRINCIPLES.md`,
  `docs/CONCEPTS/CONTEXT_AND_ARTIFACT_DIMENSIONS.md`, and the
  `docs/SEPARATING_PERSISTENCE_SURFACES/` spec.
- `docs/COMPANION_UI_PRODUCT_SPEC.md` — companion UI product spec defining the Find/Reorient/
  Resurface/Act product model while preserving Panel/Chat/Automation as the canonical authority
  surfaces.

These follow-ups are not implemented by the spine PR and should be picked up via the normal
docs-authoring or docs-to-issue path when scheduled.

Update (2026-05-12): `docs/COMPANION_UI_PRODUCT_SPEC.md` is now added in this docs-only PR.
It is a target-state product specification and does not change runtime behavior.

Update (2026-05-13): context bundle and agent memory work has now moved from contract-definition
only into docs-first feature-breakdown preparation via `docs/CONTEXT_BUNDLES/` and
`docs/AGENT_MEMORY/`. These directories define bounded implementation-ready specs and local draft
parent feature issues. No runtime behavior changed; implementation remains future work.

Update (2026-05-13): Context Bundles now have filed GitHub backlog surfaces: parent feature issue
#894 plus the first two child implementation issues #895 (`CONTEXT-BUNDLES-01`) and #896
(`CONTEXT-BUNDLES-02`). No runtime behavior changed; implementation remains future work until
those issues are delivered and validated. Agent Memory remains local spec-only unless later issue
searches find or create active implementation issues. The bridge-map reference to the agent-memory
contract was corrected from a local stale "future" reference to the active
`docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md` contract.

Update (2026-05-14): Issue #850 delivered v6.0 seam observability: `config/runtime.defaults.env`
now explicitly declares `CANVAS_ENABLED=0` (canvas seam deliberately gated until stable);
startup logs report v6.0 seam readiness at INFO level; `/api/health` and `/api/status` include
an informational `v6_0_seams` field surfacing `orientation`, `resurfacing`, `commitments`, and
`canvas` status. This field is informational only and does not affect health pass/fail.

Update (2026-05-14): `CONTEXT-BUNDLES-01` (#895) delivered by PR #931. Adds the minimal
`ContextBundle` pydantic schema (`app/context_bundles/schema.py`) covering identity, trigger,
intended use, scope, included/excluded items with per-item provenance and trust posture, distinct
authority flags, stale/expiry posture, and receipt linkage. No runtime behavior changed; the schema
is a typed contract surface only.

Update (2026-05-15): All remaining Context Bundles child slices delivered. `CONTEXT-BUNDLES-02`
(#896) delivered retrieval emission; `CONTEXT-BUNDLES-03` (#946, PR #950) orientation consumer;
`CONTEXT-BUNDLES-04` (#947, PR #951) resurfacing consumer with auditable `WhyNowSignal`;
`CONTEXT-BUNDLES-05` (#948, PR #952) write-proposal linkage enforcing `may_propose ≠ may_write`;
`CONTEXT-BUNDLES-06` (#949, PR #954) receipt recording. Parent feature #894 closed. All six slices
are typed-contract implementations (`app/context_bundles/`, `app/orientation/bundle_consumer.py`,
`app/resurfacing/bundle_consumer.py`, `app/writeback/bundle_proposal.py`,
`app/receipts/bundle_receipts.py`) with full test coverage. At that delivery point, no production
route wiring had shipped; runtime bundle emission in API routes was left to a separate future slice.

Update (2026-06-04): **Context Bundles production runtime integration shipped.** The typed-contract
building blocks are now wired into production runtime, delivered by the #1559 wave:

- a read-only construction route `GET /api/context-bundles/{bundle_id}` returning an inspectable
  bundle envelope — #1560 (PR #1569);
- real retrieval emission through the capability/ports layer (not the raw-cosine `/search` route),
  recording a creation receipt — #1562 (PR #1570);
- production orientation (`GET /api/orientation/bundle/{id}`) and resurfacing
  (`GET /api/resurfacing/bundle/{id}`) consumers that preserve provenance/exclusions and reject
  mis-scoped bundles — #1563 (PR #1571);
- bundle linkage through the governed write-proposal path with WriteGuard kept independent and
  authoritative — #1564 (PR #1572);
- a read-only bundle receipt projection over creation/consumption/stale traces — #1565 (PR #1574).

Across every surface, Context Bundles remain inspectable bridge objects, not canonical truth:
`may_write` stays false, no surface upgrades authority, no bundle content is promoted into
memory/knowledge, and WriteGuard/trust/policy gates are never bypassed. Parent feature #1559 closed
on delivery of #1566. See `docs/CONTEXT_BUNDLES_RUNTIME/` for the per-slice specs and receipts.

### Cognitive mediation alignment (2026-05-16)

`docs/CAPABILITY_CONTRACT_MODEL.md` now carries the 6.x cognitive mediation alignment vocabulary:
capability classes (orientation, proposal, retrieval, clarification, synthesis/review,
governance-bearing execution, repair/maintenance), the intent-space vs capability-space
distinction, proposal-only capability semantics, and a metadata vocabulary for catalog entries
(`authority_class`, `capability_class`, `risk_tier`, `reversibility`, `approval_envelope`,
`side_effect_class`, `provenance_required`). `docs/PANEL_AGENT.md` cross-references this taxonomy
under "Capability taxonomy alignment" without claiming new shipped runtime behavior.

Scope: architecture alignment only. No runtime change, no event-payload change, no catalog change.
The vocabulary is the language new cognitive-mediation catalog entries (tracked separately) are
expected to populate; existing entries remain valid without retroactive backfill. Delivers #981
under the PanelAgent / Cognitive Mediation program coordinated by #978.
