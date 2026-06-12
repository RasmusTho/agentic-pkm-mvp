# Integrated Runtime v1 Evidence Pack

Status: factual evidence pack for a future productization epic. This does not
propose a redesign, create issues, or implement code.

Primary question: what prevents the already-built system from functioning as
one integrated production/operator workflow?

Summary finding: the repository contains many real runtime capabilities, but
they are not yet one production/operator workflow because several capabilities
are dev-shell-only, API-only, flag-gated, process-memory-backed, mock/degraded
by default, missing Companion UI route parity, missing unified receipt history,
or covered by isolated tests rather than one no-mock end-to-end operator path.

Non-negotiable constraints observed in this pack:

- The vault remains the human/canonical surface.
- Runtime projections are not truth.
- No hidden writes.
- WriteGuard, receipts, source/projection separation, and event/receipt
  separation must not be weakened.
- Proportional governance remains an open design question.

## Capability Findings

### 1. System Entry Point

- Current implementation evidence: `scripts/start_full_system.sh` is the broad
  local startup spine. It loads `.env` and `config/runtime.defaults.env`, checks
  Docker, requires `VAULT_ROOT` unless legacy mode is explicitly allowed, starts
  Compose services, probes DB, API, vault read/write, `/readyz`, and
  `/api/health`, then prints runtime URLs. `app/api/app.py` is the API router
  composition point and conditionally mounts optional runtime routers.
- Main files: `scripts/start_full_system.sh`, `scripts/lib/start_full_system_env.sh`,
  `config/runtime.defaults.env`, `docker-compose.yaml`, `app/api/app.py`,
  `docs/runbooks/RUNBOOK_STARTUP_FULL_SYSTEM.md`.
- User entry point: `make start` / full-system script and printed local URLs.
- API/CLI entry point: FastAPI app plus health/status endpoints.
- Feature flags or dev-only gates: `CANVAS_ENABLED` defaults to `0`; watcher
  auto-exec defaults are set by startup env helpers; runtime profile is env
  controlled.
- Runtime/provider/config dependencies: Docker, Compose DB/API/worker/watcher,
  vault mount, `.env`, runtime defaults, `VAULT_ROOT`, `STORE_BACKEND`,
  provider env.
- Authority path: other. This is runtime orchestration; it does not itself
  create canonical content authority.
- Receipt/event behavior: startup validates health and outbox-related state but
  is not a receipt history surface.
- Health/status visibility: strong; probes `/healthz`, `/readyz`,
  `/api/health`, vault read/write, DB, worker/watcher.
- Tests that cover it: startup behavior is mostly runbook and script-level
  acceptance rather than a single integrated UI UAT.
- Missing integration work: one documented v1 operator entry needs to tie
  startup, Companion UI, route availability, feature flag state, receipt
  visibility, and golden-path UAT together.
- v1 eligibility: core.
- Evidence anchors: `app/api/app.py:16`, `app/api/app.py:184`,
  `app/api/app.py:228`, `scripts/start_full_system.sh:12`,
  `scripts/start_full_system.sh:767`, `scripts/start_full_system.sh:925`,
  `scripts/start_full_system.sh:1556`, `scripts/start_full_system.sh:1817`,
  `scripts/start_full_system.sh:2348`, `config/runtime.defaults.env:31`,
  `docker-compose.yaml:44`, `docs/runbooks/RUNBOOK_STARTUP_FULL_SYSTEM.md:220`.

### 2. Companion UI Routes and Surfaces

- Current implementation evidence: the main served Companion page is explicitly
  dev/staging-only and proxies a limited allowlist of runtime API routes.
  A separate production page exists, but it is still local-only and explicitly
  not an auth/TLS/reverse-proxy security boundary.
- Main files: `companion-ui/companion-app/companion_ui/workspace/serve_dev_page.py`,
  `companion-ui/companion-app/companion_ui/workspace/serve_production_page.py`,
  `companion-ui/companion-app/companion_ui/workspace/real_note_workspace_dev_page.py`,
  `companion-ui/companion-app/companion_ui/workspace/confirm_session.py`,
  `scripts/lib/companion_ui_startup.sh`.
- User entry point: local Companion URL from startup scripts; note workspace
  and orientation/vault-browser page.
- API/CLI entry point: runtime API is reached through the UI server proxy; the
  startup helper can start or validate the API and UI.
- Feature flags or dev-only gates: dev/staging warnings; production server is
  local-only; Companion startup requires channel-specific local env; route
  access depends on explicit proxy allowlists.
- Runtime/provider/config dependencies: API base URL, vault path binding,
  target note verification, channel env, runtime health.
- Authority path: read-only for orientation/vault browsing; human save for
  `/api/companion/note/save`; proposal or governed Panel confirm only where the
  UI can reach the runtime handoff.
- Receipt/event behavior: UI renders receipt posture and Panel receipt blocks,
  but several mutation controls do not have same-origin proxy coverage.
- Health/status visibility: Companion startup probes API `/healthz` and vault
  mount. The served page does not unify all health/status surfaces.
- Tests that cover it: Companion UI tests cover rendering, TTS, Canvas, vault
  browser, and dev-server wiring, but coverage is fragmented by feature.
- Missing integration work: route parity. Visible controls must either be
  proxied, disabled, or hidden. Current risk areas include Vault related,
  queue-review, Panel confirm, and several Canvas session/edit controls.
- v1 eligibility: core, as the operator surface, with route parity required.
- Evidence anchors: `companion-ui/companion-app/companion_ui/workspace/serve_dev_page.py:1`,
  `companion-ui/companion-app/companion_ui/workspace/serve_dev_page.py:8890`,
  `companion-ui/companion-app/companion_ui/workspace/serve_dev_page.py:9082`,
  `companion-ui/companion-app/companion_ui/workspace/serve_dev_page.py:9131`,
  `companion-ui/companion-app/companion_ui/workspace/serve_dev_page.py:9143`,
  `companion-ui/companion-app/companion_ui/workspace/serve_production_page.py:1`,
  `companion-ui/companion-app/companion_ui/workspace/serve_production_page.py:21`,
  `scripts/lib/companion_ui_startup.sh:13`,
  `scripts/lib/companion_ui_startup.sh:125`,
  `companion-ui/companion-app/companion_ui/workspace/real_note_workspace_dev_page.py:1`,
  `companion-ui/companion-app/companion_ui/workspace/confirm_session.py:1`.

### 3. Orientation

- Current implementation evidence: Orientation is implemented as a read-only
  runtime frame over derived signals and optional emitted context bundles.
  Bundle consumption rejects missing or invalid authority and does not upgrade
  write authority.
- Main files: `app/api/routes/orientation.py`,
  `app/orientation/runtime.py`, `app/orientation/bundle_consumer.py`,
  `app/api/routes/companion.py`.
- User entry point: Companion orientation surface.
- API/CLI entry point: `GET /api/orientation`, `GET /api/orientation/bundle/{id}`,
  and `GET /api/companion/orientation`.
- Feature flags or dev-only gates: no primary feature flag found; bundle use
  requires process-local emitted bundle availability.
- Runtime/provider/config dependencies: status/orientation signals, bundle
  registry when bundle-backed.
- Authority path: read-only. Mutation intents are references only.
- Receipt/event behavior: no receipt authority; bundle lifecycle receipts are
  separate in-memory projection records.
- Health/status visibility: orientation signals are included in status service
  inputs and Companion orientation degraded reasons.
- Tests that cover it: orientation and bundle-consumption tests exist.
- Missing integration work: turn orientation suggestions/mutation-intent
  references into explicit visible handoffs without creating hidden writes.
- v1 eligibility: core.
- Evidence anchors: `app/api/routes/orientation.py:17`,
  `app/orientation/runtime.py:16`, `app/orientation/runtime.py:39`,
  `app/orientation/bundle_consumer.py:1`,
  `app/orientation/bundle_consumer.py:75`,
  `app/orientation/bundle_consumer.py:128`,
  `app/api/routes/companion.py:2286`.

### 4. Resurfacing

- Current implementation evidence: Resurfacing is implemented as a suggestion
  and query-independent read-only evaluation. Bundle-backed resurfacing rejects
  write authority and requires explicit resurface intent.
- Main files: `app/api/routes/resurfacing.py`,
  `app/resurfacing/runtime.py`, `app/resurfacing/bundle_consumer.py`.
- User entry point: indirect, through Companion orientation/signals where
  surfaced.
- API/CLI entry point: `GET /api/resurfacing` and bundle-backed resurfacing
  route.
- Feature flags or dev-only gates: requires emitted bundle for bundle route;
  no default write path.
- Runtime/provider/config dependencies: derived orientation signals, pending
  promotions, work queue, recent activity, bundle registry.
- Authority path: read-only.
- Receipt/event behavior: receipts are trace text only in the evaluation, not
  durable authority receipts.
- Health/status visibility: no dedicated health surface found beyond general
  runtime degradation.
- Tests that cover it: resurfacing runtime/API/bundle tests exist.
- Missing integration work: no first-class UI handoff from resurfaced item to
  expected next action with receipt/governance posture.
- v1 eligibility: core if v1 includes proactive operator review; otherwise
  optional.
- Evidence anchors: `app/api/routes/resurfacing.py:1`,
  `app/api/routes/resurfacing.py:44`,
  `app/resurfacing/runtime.py:27`,
  `app/resurfacing/runtime.py:40`,
  `app/resurfacing/runtime.py:141`,
  `app/resurfacing/bundle_consumer.py:1`,
  `app/resurfacing/bundle_consumer.py:93`,
  `app/resurfacing/bundle_consumer.py:156`.

### 5. Capture

- Current implementation evidence: capture note generation and capture triage
  contracts exist as library code. The current triage LLM summarizer is not
  wired and deterministic fallback is used.
- Main files: `app/capture/writer.py`,
  `app/agents/capture_triage/agent.py`,
  `tests/capture/test_capture_writer_layout.py`,
  `tests/capture/test_capture_triage_contract.py`.
- User entry point: no UI route found in inspected app/Companion entry points.
- API/CLI entry point: no app route or CLI command found in inspected runtime
  entry points.
- Feature flags or dev-only gates: no specific flag found; functionality is
  effectively library/test-only.
- Runtime/provider/config dependencies: future LLM summarizer is noted but not
  wired.
- Authority path: proposal-like draft generation only; writer returns markdown
  and frontmatter, not a vault write.
- Receipt/event behavior: no runtime receipt behavior found.
- Health/status visibility: no dedicated health/status visibility found.
- Tests that cover it: layout and contract tests.
- Missing integration work: user/API/CLI entry, WriteGuard-backed save or
  governed handoff, receipt posture, and end-to-end capture-to-vault review.
- v1 eligibility: experimental.
- Evidence anchors: `app/capture/writer.py:18`,
  `app/capture/writer.py:93`,
  `app/capture/writer.py:102`,
  `app/agents/capture_triage/agent.py:8`,
  `app/agents/capture_triage/agent.py:65`,
  `tests/capture/test_capture_writer_layout.py:4`,
  `tests/capture/test_capture_triage_contract.py:5`.

### 6. Memory Review

- Current implementation evidence: an in-memory review queue, candidate model,
  promotion/reject/revise logic, and read-only posture projection exist. The
  queue explicitly has no storage backend, API, prompt wiring, or activation
  engine. A separate memory store exists with DB-or-in-memory fallback and
  `MEMORY_ENABLED`.
- Main files: `app/agent_memory/review_queue.py`,
  `app/agent_memory/candidate.py`, `app/agent_memory/promotion.py`,
  `app/agent_memory/posture_projection.py`, `app/memory/store.py`.
- User entry point: Vault Browser can show artifact memory posture; no full
  review UI found.
- API/CLI entry point: no first-class memory review API found in inspected
  runtime routes.
- Feature flags or dev-only gates: review queue is in-memory; separate memory
  store uses `MEMORY_ENABLED`.
- Runtime/provider/config dependencies: memory DB DSN only if explicitly
  configured; otherwise in-memory fallback.
- Authority path: memory promotion/review, but current review queue promotion
  is not a durable activation system.
- Receipt/event behavior: promotion receipt projection exists elsewhere, but
  queue decisions themselves are not a unified durable review surface.
- Health/status visibility: posture can appear per artifact; no dedicated
  operator health for review queue persistence.
- Tests that cover it: `tests/agent_memory/*`.
- Missing integration work: durable review storage, API/UI review workflow,
  activation/recall integration, receipts, and status visibility.
- v1 eligibility: experimental unless narrowed to read-only posture.
- Evidence anchors: `app/agent_memory/review_queue.py:1`,
  `app/agent_memory/review_queue.py:34`,
  `app/agent_memory/review_queue.py:114`,
  `app/agent_memory/review_queue.py:141`,
  `app/agent_memory/candidate.py:51`,
  `app/agent_memory/promotion.py:1`,
  `app/agent_memory/posture_projection.py:1`,
  `app/memory/store.py:16`, `app/memory/store.py:56`.

### 7. Source Understanding

- Current implementation evidence: Source Understanding P0 returns a
  non-authoritative understanding projection with no durable writes, memory
  writes, index updates, or promotions. Handoff helpers describe review choices
  and unavailable governed apply paths by default.
- Main files: `app/api/routes/source_understanding.py`,
  `app/source_understanding/p0.py`,
  `app/source_understanding/handoff.py`,
  `app/source_understanding/integration_action.py`.
- User entry point: no primary Companion route found in inspected surfaces.
- API/CLI entry point: `POST /api/source-understanding/p0`.
- Feature flags or dev-only gates: no specific flag found; apply path is
  unavailable unless a governed apply path is supplied.
- Runtime/provider/config dependencies: source payload and optional vault
  context.
- Authority path: read-only projection and proposal/handoff metadata; no
  canonical apply by default.
- Receipt/event behavior: integration-action handoff reports no receipt created;
  governed apply would require receipt before canonical change.
- Health/status visibility: no dedicated health/status visibility found.
- Tests that cover it: `tests/source_understanding/*` and API tests.
- Missing integration work: UI route, explicit governed apply path, receipt
  surface, and link to Panel or review workflow.
- v1 eligibility: optional.
- Evidence anchors: `app/api/routes/source_understanding.py:11`,
  `app/source_understanding/p0.py:45`,
  `app/source_understanding/p0.py:111`,
  `app/source_understanding/p0.py:149`,
  `app/source_understanding/handoff.py:16`,
  `app/source_understanding/handoff.py:175`,
  `app/source_understanding/handoff.py:210`,
  `app/source_understanding/integration_action.py:32`,
  `app/source_understanding/integration_action.py:49`.

### 8. Canvas / Chat Co-authoring

- Current implementation evidence: Canvas sessions, body-only edits, undo,
  coauthoring cognition, and governance handoff exist behind `CANVAS_ENABLED`.
  Session state and edit histories are process-local. CanvasWriter writes
  body-only content through write ops and rejects frontmatter/cross-note edits.
- Main files: `app/api/routes/canvas.py`, `app/chat/canvas_writer.py`,
  `app/chat/coauthoring_cognition.py`, `app/chat/governance_router.py`,
  `app/panel/canvas_pipeline.py`.
- User entry point: Companion dev/staging workspace has Canvas affordances.
- API/CLI entry point: `/api/canvas/sessions`, session edit/undo/coauthor,
  governance, and close routes; CLI tests also exist.
- Feature flags or dev-only gates: `CANVAS_ENABLED=0` by default; Agentic Lab
  runbook marks this dev/staging-only; positive coauthor path requires a real
  edit-capable provider.
- Runtime/provider/config dependencies: active note, WriteGuard, content hash,
  LLM provider for cognition, Panel proposal store for governance.
- Authority path: human/body edit through CanvasWriter for body-only edits;
  governed Panel confirm for escalated governance actions.
- Receipt/event behavior: session logs for Canvas edits; Panel handoff creates
  pending Panel proposal, with durable receipt only after confirm.
- Health/status visibility: v6 seam status reports Canvas as enabled only if
  importable and flag-enabled; Companion workspace reports canvas/panel state.
- Tests that cover it: canvas API/chat/UI/CLI tests exist.
- Missing integration work: default-off flag, process-memory sessions, route
  parity in served UI, provider readiness, and reliable natural-language
  governance intent handoff.
- v1 eligibility: experimental.
- Evidence anchors: `app/api/routes/canvas.py:1`,
  `app/api/routes/canvas.py:37`, `app/api/routes/canvas.py:55`,
  `app/api/routes/canvas.py:241`, `app/api/routes/canvas.py:349`,
  `app/api/routes/canvas.py:455`, `app/chat/canvas_writer.py:1`,
  `app/chat/canvas_writer.py:57`, `app/chat/coauthoring_cognition.py:1`,
  `app/chat/governance_router.py:1`, `app/panel/canvas_pipeline.py:1`,
  `config/runtime.defaults.env:31`.

### 9. Chat to Panel Governance Handoff

- Current implementation evidence: governance handoff exists as a Canvas-to-
  Panel bridge. It stages Panel proposals without mutating the note and returns
  pending action metadata.
- Main files: `app/chat/governance_router.py`,
  `app/panel/canvas_pipeline.py`, `app/api/routes/canvas.py`,
  `app/api/routes/panel.py`.
- User entry point: Companion Canvas governance affordances, where proxied.
- API/CLI entry point: Canvas governance route and Panel confirm route.
- Feature flags or dev-only gates: depends on Canvas flag and Panel in-memory
  proposal store; UAT notes use explicit governance endpoint because natural
  `/coauthor` governance is not reliable enough as the only path.
- Runtime/provider/config dependencies: WriteGuard, active Canvas session,
  Panel store, idempotency state.
- Authority path: proposal to governed Panel confirm.
- Receipt/event behavior: pending proposal first; receipt/event only after
  Panel confirm or block/reject handling.
- Health/status visibility: Companion panel state reads in-memory proposal and
  idempotency stores.
- Tests that cover it: Canvas governance handoff, chat-to-panel handoff, and
  receipt reflection tests exist.
- Missing integration work: durable proposal store, reliable UI route proxy,
  clear user-visible handoff state, and no-mock E2E path from chat intent to
  confirmed receipt.
- v1 eligibility: experimental.
- Evidence anchors: `app/chat/governance_router.py:101`,
  `app/panel/canvas_pipeline.py:24`,
  `app/panel/canvas_pipeline.py:45`,
  `app/api/routes/canvas.py:301`,
  `app/api/routes/canvas.py:455`,
  `app/api/routes/panel.py:1`,
  `app/api/routes/companion.py:806`,
  `docs/runbooks/UAT_CANVAS_COAUTHORING.md:98`.

### 10. Panel Confirm

- Current implementation evidence: Panel confirm is implemented as the runtime
  authority point for policy, WriteGuard, idempotency, execution, receipts, and
  events. Proposal and idempotency stores are process-local globals.
- Main files: `app/api/routes/panel.py`, `app/panel/confirmation.py`,
  `app/panel/canvas_pipeline.py`.
- User entry point: Companion Panel affordances where routed; dedicated
  confirm-session helper exists.
- API/CLI entry point: `POST /api/panel/confirm`, `POST /api/panel/checkbox-projection`.
- Feature flags or dev-only gates: no primary flag, but staged proposals depend
  on process memory unless backed by a staging path.
- Runtime/provider/config dependencies: WriteGuard, outbox/event store, proposal
  store, idempotency key.
- Authority path: governed Panel confirm.
- Receipt/event behavior: confirm emits panel action events and returns receipt
  visibility; blocked/rejected paths are represented.
- Health/status visibility: status includes panel diagnostics and WriteGuard.
- Tests that cover it: Panel confirm API/unit/integration tests and receipt/
  event boundary tests.
- Missing integration work: durable proposal/idempotency persistence,
  end-to-end UI proxy parity, and unified receipt history after confirm.
- v1 eligibility: core.
- Evidence anchors: `app/api/routes/panel.py:1`,
  `app/api/routes/panel.py:33`,
  `app/panel/confirmation.py:1`,
  `app/panel/confirmation.py:100`,
  `app/panel/confirmation.py:139`,
  `app/panel/confirmation.py:174`,
  `app/panel/confirmation.py:300`,
  `app/panel/confirmation.py:412`,
  `app/panel/confirmation.py:470`.

### 11. Receipts History

- Current implementation evidence: receipt projection exists for artifacts,
  promotion receipts, bundle lifecycle receipts, and Panel confirm responses.
  Event/receipt separation is explicitly tested. There is no single unified
  operator receipt-history route found.
- Main files: `app/receipts/artifact_receipts.py`,
  `app/receipts/promotion_receipts.py`,
  `app/receipts/outbox_sources.py`,
  `app/receipts/bundle_receipts.py`,
  `app/receipts/bundle_receipt_projection.py`,
  `app/api/routes/events_tail.py`,
  `tests/runtime/test_receipt_event_boundary.py`.
- User entry point: Companion renders per-artifact receipt posture and Panel
  confirm receipt blocks.
- API/CLI entry point: artifact receipts are consumed by Companion APIs; events
  tail route exists for JSONL outbox diagnostics.
- Feature flags or dev-only gates: source availability depends on DB outbox or
  JSONL path; bundle receipts are in-memory.
- Runtime/provider/config dependencies: DB outbox, JSONL outbox path,
  projection records, Panel confirm result.
- Authority path: read-only receipt projection; receipts are accountability
  records, not events.
- Receipt/event behavior: projection distinguishes source unavailable, no
  receipts, pending, blocked/logged, and durable-like states depending on source.
- Health/status visibility: events/outbox status exists; no single receipt
  health surface found.
- Tests that cover it: receipt/event boundary tests and per-capability receipt
  tests.
- Missing integration work: unified receipt history visible to operator,
  consistent pending/durable/unavailable states across UI, and durable source
  coverage for all governed flows.
- v1 eligibility: core.
- Evidence anchors: `app/receipts/artifact_receipts.py:1`,
  `app/receipts/artifact_receipts.py:32`,
  `app/receipts/artifact_receipts.py:105`,
  `app/receipts/promotion_receipts.py:1`,
  `app/receipts/promotion_receipts.py:85`,
  `app/receipts/outbox_sources.py:14`,
  `app/receipts/bundle_receipts.py:1`,
  `app/receipts/bundle_receipt_projection.py:1`,
  `app/api/routes/events_tail.py:42`,
  `tests/runtime/test_receipt_event_boundary.py:1`.

### 12. Vault Browser

- Current implementation evidence: Companion Vault Browser is implemented as a
  read-only vault projection with filters, pagination, receipt attachment,
  agent-memory posture, related artifacts, and queue-review action staging.
  Queue-review returns pending intent and explicitly says no durable receipt is
  created until confirmation.
- Main files: `app/api/routes/companion.py`,
  `companion-ui/companion-app/companion_ui/workspace/serve_dev_page.py`,
  `tests/api/test_companion_vault_browser*.py`,
  `tests/companion_ui/test_vault_browser*.py`.
- User entry point: Companion Vault Browser UI.
- API/CLI entry point: `GET /api/companion/vault-browser`,
  `GET /api/companion/vault-related`,
  `POST /api/companion/vault-browser/actions/queue-review`.
- Feature flags or dev-only gates: no primary flag; served dev page proxy
  allowlist currently omits related and queue-review routes.
- Runtime/provider/config dependencies: vault root, receipt sources, memory
  posture projection, WriteGuard for queue-review.
- Authority path: read-only browsing; proposal handoff for queue-review;
  governed Panel confirm expected for execution.
- Receipt/event behavior: attached per-artifact receipts where source
  available; queue-review pending intent is not a durable receipt.
- Health/status visibility: degraded fields in API responses; no dedicated
  operator status for route parity.
- Tests that cover it: Vault Browser API and UI tests.
- Missing integration work: same-origin proxy route parity, queue-review to
  Panel confirm visible handoff, and unified receipt history.
- v1 eligibility: core.
- Evidence anchors: `app/api/routes/companion.py:1271`,
  `app/api/routes/companion.py:1548`,
  `app/api/routes/companion.py:2065`,
  `app/api/routes/companion.py:2182`,
  `app/api/routes/companion.py:2240`,
  `app/api/routes/companion.py:542`,
  `companion-ui/companion-app/companion_ui/workspace/serve_dev_page.py:8662`,
  `companion-ui/companion-app/companion_ui/workspace/serve_dev_page.py:8687`,
  `companion-ui/companion-app/companion_ui/workspace/serve_dev_page.py:9082`,
  `companion-ui/companion-app/companion_ui/workspace/serve_dev_page.py:9131`.

### 13. TTS / Read-back

- Current implementation evidence: TTS has config, provider readiness, plan,
  synthesis, audio cache, status, and Companion API endpoints. It is disabled
  by default, local-only by default, and fails closed when provider requirements
  are missing.
- Main files: `app/tts/config.py`, `app/tts/service.py`,
  `app/tts/status.py`, `app/tts/providers.py`,
  `app/api/routes/companion.py`,
  `tests/api/test_companion_tts_api.py`,
  `tests/companion_ui/test_tts_readback.py`.
- User entry point: Companion read-back controls.
- API/CLI entry point: Companion TTS plan, synthesize, status, and audio routes.
- Feature flags or dev-only gates: `TTS_ENABLED` defaults false; `TTS_LOCAL_ONLY`
  defaults true; browser/cloud fallbacks default false.
- Runtime/provider/config dependencies: local provider command, model/config,
  voice, cache path, concurrency guard.
- Authority path: other. Read-back does not mutate vault truth.
- Receipt/event behavior: status includes an operator receipt object describing
  local runtime/cache behavior; no canonical vault receipt.
- Health/status visibility: TTS status endpoint and Companion API responses.
- Tests that cover it: API and UI read-back tests cover local-only behavior,
  cache, provider unavailable, no autoplay, and draft read-back.
- Missing integration work: operator install/readiness profile, production UI
  route coverage for status if exposed, and clear optional-vs-core decision.
- v1 eligibility: optional.
- Evidence anchors: `app/tts/config.py:24`, `app/tts/config.py:49`,
  `app/tts/service.py:27`, `app/tts/service.py:52`,
  `app/tts/status.py:48`, `app/tts/status.py:80`,
  `app/tts/providers.py:40`, `app/api/routes/companion.py:2400`,
  `tests/api/test_companion_tts_api.py:48`,
  `tests/companion_ui/test_tts_readback.py:87`.

### 14. BuilderOps Projections

- Current implementation evidence: BuilderOps has a durable SQLite-backed
  store, API routes, CLI, boundary policy, non-authoritative projection
  generator, and promotion gateway. The gateway explicitly does not create
  GitHub Issues, write repo docs, open PRs, or mutate product/runtime authority.
- Main files: `app/api/routes/builderops.py`, `app/builderops/store.py`,
  `app/builderops/boundary.py`, `app/builderops/config.py`,
  `app/builderops/projections.py`,
  `app/builderops/promotion_gateway.py`, `app/builderops/cli.py`,
  `app/cli/builderops.py`,
  `docs/security/AGENT_TOOL_EXECUTION_SECURITY_ADDENDUM.md`.
- User entry point: no main Companion surface found.
- API/CLI entry point: `/api/builderops/*` and the `app/builderops/cli.py`
  command group, re-exported through `app/cli/builderops.py`.
- Feature flags or dev-only gates: real MCP BuilderOps tool execution requires
  `mcp_builderops_enable`; projection and promotion paths remain
  non-authoritative.
- Runtime/provider/config dependencies: BuilderOps state dir/SQLite DB, leases,
  idempotency keys, receipt refs.
- Authority path: proposal/other. Projections are not truth; promotion gateway
  is dry-run/proposal-oriented.
- Receipt/event behavior: store appends receipts for transitions and dry-run
  promotion receipts; projections display receipt refs.
- Health/status visibility: boundary health lists safe/review operation sets;
  no integrated product runtime health gate found.
- Tests that cover it: BuilderOps API/CLI/store/promotion/boundary tests.
- Missing integration work: decide whether this is v1 operator-core or optional,
  expose only as non-authoritative operator support, and avoid treating
  projections as product truth.
- v1 eligibility: optional.
- Evidence anchors: `app/api/routes/builderops.py:11`,
  `app/api/routes/builderops.py:68`,
  `app/builderops/store.py:54`,
  `app/builderops/store.py:264`,
  `app/builderops/boundary.py:15`,
  `app/builderops/boundary.py:43`,
  `app/builderops/config.py:9`,
  `app/builderops/projections.py:1`,
  `app/builderops/projections.py:169`,
  `app/builderops/promotion_gateway.py:1`,
  `app/builderops/promotion_gateway.py:105`,
  `app/builderops/cli.py:106`,
  `app/cli/builderops.py:1`,
  `docs/security/AGENT_TOOL_EXECUTION_SECURITY_ADDENDUM.md:76`.

### 15. Health / Status

- Current implementation evidence: health/status endpoints, a structured status
  model, runtime status service, bounded health contract, CLI health checks, and
  v6 seam diagnostics exist.
- Main files: `app/api/routes/status.py`, `app/api/routes/health.py`,
  `app/api/routes/health_contract.py`,
  `app/observability/status_model.py`,
  `app/observability/status_service.py`,
  `app/health_contract.py`, `app/cli/health.py`.
- User entry point: startup summary and documented health/status checks.
- API/CLI entry point: `/api/status`, `/api/health`, `/healthz`, `/readyz`,
  `/status`, CLI health.
- Feature flags or dev-only gates: status reports feature and seam state,
  including Canvas gated by flag/importability.
- Runtime/provider/config dependencies: DB/outbox, event logs, worker/watcher,
  views, WriteGuard, settings, providers, vault.
- Authority path: read-only diagnostics.
- Receipt/event behavior: reports events/outbox and write-guard posture; does
  not itself act as receipt authority.
- Health/status visibility: strong but distributed across endpoints and CLI.
- Tests that cover it: API, observability, health contract, and CLI health
  tests.
- Missing integration work: one release health gate that names which v1
  capabilities are enabled, degraded, unavailable, or experimental from the
  operator's point of view.
- v1 eligibility: core.
- Evidence anchors: `app/api/routes/status.py:11`,
  `app/api/routes/health.py:36`,
  `app/api/routes/health_contract.py:12`,
  `app/api/routes/health_contract.py:20`,
  `app/observability/status_model.py:170`,
  `app/observability/status_service.py:624`,
  `app/observability/status_service.py:938`,
  `app/observability/status_service.py:946`,
  `app/health_contract.py:18`, `app/health_contract.py:195`,
  `app/cli/health.py:624`, `app/cli/health.py:646`.

### 16. Environment / Config / Profiles / Feature Flags

- Current implementation evidence: environment separation, runtime settings,
  default env, Compose env, startup env inference, and production acceptance
  docs exist. The prod acceptance runbook explicitly scopes current acceptance
  to the baseline registry watcher, DB outbox, worker, health/status path and
  excludes Canvas, Chat cognition, Deep Agents/v6.1, and new watcher authority.
- Main files: `docs/ENVIRONMENTS.md`, `docs/SETTINGS.md`,
  `config/runtime.defaults.env`, `docker-compose.yaml`,
  `scripts/lib/start_full_system_env.sh`,
  `docs/runbooks/PROD_GO_LIVE_ACCEPTANCE.md`.
- User entry point: `.env`, profile/channel env files, startup scripts.
- API/CLI entry point: status/settings surfaces and startup CLI.
- Feature flags or dev-only gates: `CANVAS_ENABLED`,
  `WORKSPACE_UPDATE_FLOW_ENABLED`, `COMPANION_WORKSPACE_UPDATE_ENABLED`,
  `TTS_ENABLED`, `TTS_LOCAL_ONLY`, `WATCHER_AUTO_EXEC`, `MEMORY_ENABLED`,
  `mcp_builderops_enable`, `PKM_ENVIRONMENT`, `PKM_SETTINGS_PROFILE`,
  `BUILDEROPS_DB_PATH`.
- Runtime/provider/config dependencies: vault scoping, DB/outbox backend,
  runtime state dirs, settings profiles, provider vars.
- Authority path: other. Config determines which authority paths are available.
- Receipt/event behavior: config determines durable source availability and
  whether runtime can write/probe safely.
- Health/status visibility: broad, but v1 capability matrix is not one
  operator-facing profile.
- Tests that cover it: settings/path/profile and production launch profile
  tests exist.
- Missing integration work: explicit v1 profile with default enabled/disabled
  capabilities, operator-visible reasons, and no reliance on hidden local
  assumptions.
- v1 eligibility: core.
- Evidence anchors: `docs/ENVIRONMENTS.md:17`,
  `docs/ENVIRONMENTS.md:73`, `docs/ENVIRONMENTS.md:101`,
  `docs/ENVIRONMENTS.md:148`, `docs/SETTINGS.md:5`,
  `docs/SETTINGS.md:39`, `config/runtime.defaults.env:5`,
  `config/runtime.defaults.env:31`, `docker-compose.yaml:26`,
  `docker-compose.yaml:44`, `scripts/lib/start_full_system_env.sh:42`,
  `scripts/lib/start_full_system_env.sh:213`,
  `docs/runbooks/PROD_GO_LIVE_ACCEPTANCE.md:18`.

### 17. Tests and UAT Coverage

- Current implementation evidence: many unit, API, CLI, UI, and runbook UAT
  tests exist by capability. The current production go-live acceptance path
  deliberately excludes Canvas/Chat/deep-agents work. Some UATs use in-memory
  store, patched Panel/DB dependencies, or defer full-stack browser validation.
- Main files: `tests/`, `docs/runbooks/UAT_REAL_NOTE_VERTICAL_SLICE.md`,
  `docs/runbooks/UAT_CANVAS_COAUTHORING.md`,
  `docs/runbooks/UAT_PANEL_WATCHER.md`,
  `docs/LOCAL_TEST_BOOTSTRAP/RUN_SCRIPTED_UAT.md`,
  `docs/runbooks/PROD_GO_LIVE_ACCEPTANCE.md`.
- User entry point: scripted UAT and runbook commands.
- API/CLI entry point: pytest, CLI scripts, startup/health commands.
- Feature flags or dev-only gates: Canvas UAT requires `CANVAS_ENABLED=1`;
  real positive coauthor path requires provider readiness; some runbooks allow
  memory mode or patched dependencies.
- Runtime/provider/config dependencies: test vault, DB/outbox for durable
  receipts, provider availability for chat/canvas, UI browser for full path.
- Authority path: varied by test target.
- Receipt/event behavior: receipt/event boundary is tested, but not all
  capability paths converge into one receipt-history UAT.
- Health/status visibility: health/status tests exist; integrated operator
  readiness needs one consolidated acceptance.
- Tests that cover it: broad but fragmented across capability suites.
- Missing integration work: one no-mock v1 golden-path UAT that starts runtime,
  opens Companion UI, performs read-only orientation/vault browse, stages and
  confirms a governed mutation, shows receipt history, and validates health.
- v1 eligibility: core release gate.
- Evidence anchors: `docs/runbooks/UAT_REAL_NOTE_VERTICAL_SLICE.md:4`,
  `docs/runbooks/UAT_REAL_NOTE_VERTICAL_SLICE.md:20`,
  `docs/runbooks/UAT_REAL_NOTE_VERTICAL_SLICE.md:201`,
  `docs/runbooks/UAT_CANVAS_COAUTHORING.md:1`,
  `docs/runbooks/UAT_CANVAS_COAUTHORING.md:23`,
  `docs/runbooks/UAT_CANVAS_COAUTHORING.md:98`,
  `docs/runbooks/UAT_PANEL_WATCHER.md:4`,
  `docs/runbooks/UAT_PANEL_WATCHER.md:55`,
  `docs/LOCAL_TEST_BOOTSTRAP/RUN_SCRIPTED_UAT.md:22`,
  `docs/LOCAL_TEST_BOOTSTRAP/RUN_SCRIPTED_UAT.md:148`,
  `docs/runbooks/PROD_GO_LIVE_ACCEPTANCE.md:18`,
  `docs/runbooks/PROD_GO_LIVE_ACCEPTANCE.md:721`.

## A. Dev-only / Staging-only / Flag-only Limitations

- Companion dev server is explicitly DEV/STAGING ONLY and lacks auth, TLS,
  reverse proxy, and public exposure hardening.
- Companion production page is a separate local-only profile and still warns it
  is not an auth/TLS/reverse-proxy boundary.
- Canvas is default-off with `CANVAS_ENABLED=0`, process-memory sessions, and
  dev/staging UAT language.
- Workspace body update route is gated by `WORKSPACE_UPDATE_FLOW_ENABLED`;
  workspace update capability can also be disabled by Canvas/WriteGuard state.
- TTS is disabled by default, local-only by default, and depends on installed
  local provider commands/models.
- BuilderOps real MCP execution requires explicit `mcp_builderops_enable`; it
  does not promote BuilderOps records into repo/product truth.
- Memory review queue is in-memory and has no storage backend, API, prompt
  wiring, or activation engine.
- Capture is library/test-only in inspected entry points; LLM summarize is not
  wired.
- Production go-live acceptance currently excludes Canvas, Chat cognition, Deep
  Agents/v6.1, and new watcher authority.
- Memory-mode UAT paths have cross-process limitations; durable receipt paths
  depend on DB/outbox availability.

## B. API-only Capabilities

- Source Understanding P0 and handoff metadata.
- Context-bundle-backed orientation/resurfacing consumption.
- BuilderOps APIs for worklogs, learning, promotions, and receipts.
- Vault Browser queue-review API, because the served dev page proxy allowlist
  does not include the queue-review POST route.
- Vault related artifacts API, because the served dev page GET proxy allowlist
  does not include the related route.
- TTS status API, if exposed in UI expectations; plan/synthesize/audio are
  proxied, but status was not in the inspected served-page GET proxy allowlist.
- Events tail diagnostic API.

## C. UI-only or Dead-affordance Risks

- Vault Browser related lookup JavaScript calls `/api/companion/vault-related`,
  while the served GET proxy allowlist does not include that route.
- Vault Browser queue-review JavaScript calls
  `/api/companion/vault-browser/actions/queue-review`, while the served POST
  proxy allowlist does not include that route.
- Panel confirm buttons declare `/api/panel/confirm`, while the served POST
  proxy allowlist does not include that route.
- Canvas controls declare session open, edit, undo, governance, and close
  endpoints, while the served POST proxy dynamically allows only coauthor among
  Canvas routes.
- Real note workspace model methods can call runtime endpoints through an
  injected client, but the browser-served same-origin route surface is narrower.

## D. Missing Handoff Map

| Source capability | Expected next capability | Missing link |
| --- | --- | --- |
| Orientation mutation-intent references | Memory review or Panel proposal | References are not durable candidates or visible governed handoffs. |
| Resurfacing suggestions | User action, Vault Browser, or Panel | No first-class UI handoff with authority/receipt posture. |
| Vault Browser queue review | Panel confirm | API stages proposal, but served UI proxy route is missing and receipt is pending until confirm. |
| Canvas visible controls | Canvas runtime API | Same-origin proxy route parity is incomplete. |
| Chat coauthor governance intent | Panel confirm | Explicit governance route exists, but natural coauthor governance path is not a complete no-mock golden path. |
| Source Understanding P0 | Governed apply / stabilized note proposal | Apply path is unavailable by default and no Companion route was found. |
| Source Understanding action handoff | Task/Panel governance | Handoff is metadata only and creates no task, commitment, write, or receipt. |
| Capture triage/writer | Vault save or governed review | No inspected user/API/CLI entry and no WriteGuard/receipt integration. |
| Memory review queue | Durable memory promotion/recall | In-memory queue lacks storage, API/UI review, and activation engine. |
| Panel confirm | Operator receipt history | Confirm returns receipt data, but no single unified receipt-history surface was found. |
| TTS read-back | Operator readiness/status | Runtime status exists, but optional provider readiness is not part of one v1 release gate. |
| BuilderOps promotion gateway | Repo/GitHub/product truth | Gateway deliberately remains proposal/dry-run and non-authoritative. |

## E. Current Golden Path Candidates

- Production/operator baseline: start full system, verify vault binding,
  registry watcher, DB outbox, worker, `/healthz`, `/readyz`, `/api/health`,
  and `/api/status`.
- Companion read-only workspace: start Companion, load orientation and Vault
  Browser or note workspace, inspect current vault state, and preserve vault as
  canonical truth.
- Governed Panel mutation: staged proposal, `/api/panel/confirm`, WriteGuard,
  event/receipt response, and workspace refresh. Current blocker: proposal/
  idempotency persistence and UI proxy parity.
- Vault Browser inspect to queue to confirm: read-only browse, queue-review
  pending intent, Panel confirm, receipt visibility. Current blocker: same-
  origin proxy and unified receipt history.
- Canvas Lab path: enable Canvas, open session, body-only coauthor/edit/undo,
  explicit governance handoff to Panel. Current blocker: default-off,
  dev/staging status, provider dependency, in-memory state, and UI route parity.
- Source Understanding optional path: P0 understanding projection and review
  handoff metadata. Current blocker: no governed apply route by default.
- BuilderOps operator support path: create records, append receipts, generate
  non-authoritative projections, dry-run promotions. Current blocker: not product
  truth and no Companion operator surface.

## F. Suggested Minimal Release Gates for Integrated Runtime v1

- One documented operator entry path: one start command, one Companion URL, one
  release health gate.
- Health gate covers `/healthz`, `/readyz`, `/api/health`, `/api/status`,
  Companion reachability, vault binding, WriteGuard, DB/outbox, worker/watcher,
  provider readiness, and feature flag state.
- UI/API route parity: every visible active UI control resolves through the
  same-origin server or is disabled/hidden with a factual reason.
- Authority contract: every mutation path is classified as human save,
  governed Panel confirm, memory review, proposal-only, or read-only.
- Receipt visibility: operator can distinguish source unavailable, no receipts,
  pending intent, blocked/rejected, and durable receipt without conflating
  events with receipts.
- Persistence decision: all v1-critical state survives restart or is explicitly
  marked experimental/degraded. This includes Panel proposals/idempotency,
  Canvas sessions if included, memory review if included, BuilderOps DB, and
  outbox sources.
- Config profile: v1 defaults state which capabilities are core, optional,
  experimental, or out of scope.
- Provider readiness: LLM, embedding, TTS, and other providers are visible as
  ready/degraded/unavailable; mock or degraded providers must not create
  diagnostic text in canonical vault notes.
- End-to-end UAT: at least one no-mock test-vault path starts runtime, opens
  Companion UI, performs read-only orientation/vault browse, stages and confirms
  one governed mutation, shows receipt history, and validates health/status.
- Negative safety UAT: WriteGuard blocked, content-hash mismatch, same-turn
  confirm rejection, provider unavailable, missing receipt source, and wrong
  vault/environment.

## G. Open Questions for Fable

- Proportional governance / risk-tiered authority: which actions are safe as
  human save, which require governed Panel confirm, and which require memory
  review or separate approval?
- Which flows should be fast-path versus governed: human note save, body-only
  coauthor edit, queue review, memory promotion, source-understanding apply,
  resurfacing follow-up, and capture?
- What is core versus optional in v1: Canvas coauthoring, Source Understanding,
  TTS/read-back, BuilderOps projections, Memory Review, and Capture?
- Which process-memory stores must become durable for v1: Panel proposals,
  idempotency, Canvas sessions, memory review queue, and bundle receipts?
- Should v1 expose one operator receipt-history service, or keep per-artifact
  projections plus event diagnostics?
- Is local-only UI acceptable for v1 production/operator use, or is auth/TLS/
  reverse-proxy hardening required before calling it production?
- How should runtime projections be labeled so users never treat BuilderOps,
  Source Understanding, or generated status views as canonical truth?
- For body-only coauthoring, is direct apply with undo/session log acceptable,
  or should v1 route it through preview/governance?
- What is the minimum capture entry point for v1: Companion quick capture, inbox
  note, API, CLI, or out of scope?
- Should Memory Review be a core v1 capability or an optional read-only posture
  surface until durable review and activation exist?
- Is TTS/read-back accessibility core, or a local optional capability with
  readiness/status only?
- Should Canvas remain default-off in v1, and should watcher auto-exec remain
  default-on only when allowlist, WriteGuard, and settings corroborate it?
