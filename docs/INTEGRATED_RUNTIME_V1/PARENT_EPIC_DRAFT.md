# Parent Epic Draft - Yggdrasil Integrated Runtime v1

Status: pre-Fable draft. Do not file this as-is without human scope approval or Fable/Codex validation. This draft exists to reduce Fable token cost and give the future synthesis pass a concrete structure to critique.

## Proposed GitHub title

`epic(integration): ship Yggdrasil Integrated Runtime v1`

## Proposed parent issue body

### Context

The repository now contains many real Yggdrasil / Agentic PKM capabilities: System Entry Point, Companion UI shell surfaces, orientation, resurfacing, Vault Browser, governed Panel confirm, capture, memory review, receipts history, local-first TTS/read-back, Source Understanding, Canvas/Chat co-authoring, Chat-to-Panel handoff, BuilderOps, and health/status surfaces.

The problem is no longer absence of capability. The problem is integration and productization. Several capabilities still depend on dev/staging routes, feature flags, process-memory stores, optional providers, narrow proxy allowlists, fragmented health/status, or isolated capability tests rather than one no-mock production/operator path.

Integrated Runtime v1 is the release line that turns already-built capabilities into one coherent local-first operator workflow:

```text
Start -> Orient -> Work -> Review -> Commit/Confirm -> Receipt -> Resume
```

This parent issue is a validation hub, not a direct pickup issue. Child issues are the executable contracts.

### Scope

Deliver a normal Companion UI/operator runtime where v1-core capabilities are reachable, honest about readiness, routed through live same-origin/API paths, guarded by existing authority boundaries, and proven by golden-path UAT.

Core candidate outcomes:

- One documented operator start path and one Companion URL.
- System Entry Point closed or explicitly recorded with release-blocking residuals.
- Companion visible controls are either live-routed, disabled, or hidden with factual reasons.
- Orientation and Vault Browser form the read-only inspect/re-entry baseline.
- Vault Browser queue-review to Panel confirm to receipt visibility is proven end to end.
- Capture is classified and either included as quick intake or explicitly optional/out of scope.
- Receipts history is visible as read-only projection, without creating a new receipt authority store.
- Health/status exposes v1 capability readiness, degraded state, provider state, feature flag state, and persistence state.
- At least one no-mock real/test-vault golden path passes, plus negative safety UAT.

### Non-goals

- No new broad agent architecture.
- No new autonomous execution semantics.
- No broad Deep Agents runtime.
- No multi-user or collaboration release.
- No public internet exposure or auth/TLS/reverse-proxy hardening unless explicitly selected as a v1 gate.
- No weakening of WriteGuard, provenance, event/receipt separation, source/projection separation, or human/vault authority.
- No opportunistic solution to proportional governance. That remains a future design issue.

### Source Anchors

- `docs/plans/INTEGRATED_RUNTIME_V1_EVIDENCE_PACK.md`
- `docs/plans/INTEGRATED_RUNTIME_V1_EVIDENCE_PACK_ERRATA.md`
- `docs/STATUS.md`
- `docs/ARCHITECTURE.md`
- `docs/ROADMAP.md`
- `companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md`
- `docs/SYSTEM_ENTRY_POINT/README.md`
- `companion-ui/companion-app/companion_ui/workspace/serve_dev_page.py`
- `companion-ui/companion-app/companion_ui/workspace/overlay_host.py`
- `app/api/app.py`
- `app/api/routes/companion.py`
- `app/api/routes/capture.py`
- `app/api/routes/panel.py`
- `app/api/routes/status.py`
- `app/api/routes/health.py`
- `app/receipts/`
- `app/tts/`
- Issues #1782, #1795, #1851, #1699, #1702

### Constraints

- Vault remains the human/canonical surface.
- Runtime projections are not truth.
- No hidden writes.
- Governed mutations remain governed.
- Body edits remain human save or authorized body-edit paths.
- Receipts and events remain distinct.
- Receipt history is a read-only projection, not a new authority store.
- Source Understanding outputs remain non-authoritative unless promoted through an approved governed path.
- Memory/context may support awareness and proposals but must not authorize mutation.
- Capture is vault inbox intake, not tasks/reminders/commitment automation.
- BuilderOps remains build-plane/operator support, not product/runtime truth.
- V1 release gates must not hide missing provider readiness, process-memory persistence, or route parity gaps.

### Acceptance Criteria

- [ ] V1 scope is classified: each candidate capability is `core`, `optional`, `experimental`, or `out of scope`.
  Verify: scope table in `docs/INTEGRATED_RUNTIME_V1/README.md` or successor owner spec.
- [ ] System Entry Point release substrate is closed or explicitly blocked by named residual issues.
  Verify: #1782/#1795/#1851 state plus owner-doc/status writeback.
- [ ] Companion UI route parity is enforced for every active v1-visible control.
  Verify: focused Companion UI tests mapping active controls to same-origin routes or disabled/hidden factual states.
- [ ] Operator readiness surface names v1 core capabilities as ready/degraded/unavailable/experimental.
  Verify: API/status or Companion surface test plus startup/runbook check.
- [ ] Vault Browser queue-review -> Panel confirm -> receipt visibility works from normal Companion session.
  Verify: no-mock golden-path UAT and focused API/UI tests.
- [ ] Capture is either integrated as v1 quick intake or explicitly marked optional/out-of-scope with rationale.
  Verify: classification decision plus route/UI/UAT if included.
- [ ] Receipt visibility distinguishes source unavailable, no receipt, pending intent, blocked/rejected, and durable receipt without conflating events.
  Verify: receipt-history UI/API tests plus negative unavailable-source fixture.
- [ ] Any included process-memory-backed v1-critical state has a persistence decision.
  Verify: issue receipt for Panel proposals/idempotency, memory review, Canvas sessions if included, bundle receipts if included.
- [ ] Provider readiness is visible and mock/degraded providers cannot create canonical text or hidden writes.
  Verify: provider-unavailable negative UAT and health/status assertions.
- [ ] Golden-path UAT passes on a real or representative test vault.
  Verify: UAT receipt posted to parent and runbook updated.
- [ ] Proportional governance is captured as a deferred design issue, not solved inside this integration parent.
  Verify: follow-up issue linked from this parent before closure.

### Suggested Validation

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/companion_ui/`
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/api/test_companion_vault_browser*.py tests/api/test_capture_inbox_api.py tests/api/test_memory_review_queue_api.py tests/api/test_companion_tts_api.py`
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/runtime/test_receipt_event_boundary.py`
- `ruff check app tests`
- Startup/runbook UAT against a real or representative test vault.
- Browser runtime UAT covering normal Companion entry, route parity, governed confirm, receipt visibility, no-vault/degraded, WriteGuard blocked, and provider unavailable.

### Delivery Waves

1. Scope and release boundary.
2. System Entry Point closure/residual alignment.
3. Route parity and operator readiness matrix.
4. Core golden path: start -> orient -> Vault Browser -> queue-review -> Panel confirm -> receipt.
5. Capture/Memory/TTS optional-core decisions and hardening if included.
6. Golden-path and negative safety UAT.
7. Owner-doc/status/roadmap promotion and parent closure.

### Parent Closure Criteria

This parent closes only after all core v1 child issues have posted validation receipts, optional/experimental capabilities are explicitly classified, golden-path UAT has a receipt, status/architecture/roadmap owner docs are updated, and proportional governance is captured as a linked future design issue.

## Draft child issue table

| Order | Proposed title | Scope | Why it exists | Depends on | Verify targets | Draft v1 class |
| --- | --- | --- | --- | --- | --- | --- |
| 01 | `task(integration): classify Integrated Runtime v1 scope and capability tiers` | Core/optional/experimental/out-of-scope table | Prevent scope explosion and force explicit productization decisions | Evidence pack + errata | docs scope table, no code | Foundation |
| 02 | `task(system-entry-point): close v1 release substrate residuals` | Align #1782/#1795/#1851 with v1 entry substrate | Front door must be truthful before integration release | #1782/#1795/#1851 state | SEP tests, state-gallery tests | Core |
| 03 | `fix(companion-ui): enforce active-control route parity for v1 surfaces` | Active UI controls route, hide, or disable factually | Remove island/dead-affordance failure mode | 01, 02 | Companion UI route tests | Core |
| 04 | `feature(status): expose Integrated Runtime v1 readiness matrix` | Operator-facing ready/degraded/unavailable/experimental matrix | One status surface must explain whether v1 is usable | 01 | status/API/UI tests | Core |
| 05 | `test(uat): add no-mock v1 golden path scaffold` | Start -> Companion -> orient -> browse -> queue -> confirm -> receipt | Release must prove an integrated workflow | 03, 04 | UAT runbook + receipt | Core |
| 06 | `feature(companion-ui): prove Vault Browser queue-review to Panel confirm handoff` | Queue-review visible handoff, confirm, refresh, receipt | It is the narrowest governed mutation loop | 03 | API/UI/e2e tests | Core |
| 07 | `feature(receipts): harden v1 receipt-history projection states` | Pending/durable/blocked/source-unavailable states | User must understand accountability without receipt/event conflation | 06 | receipt UI tests | Core |
| 08 | `task(capture): decide and harden quick capture as v1 intake` | Include or mark optional; if included, UAT capture path | Errata says shipped; v1 must decide whether core | 01, 03 | capture API/UI/UAT | Core-candidate |
| 09 | `task(memory): decide Memory Review v1 persistence and recall boundary` | Persist/restart/activation decision or optional status | Errata says API+drawer shipped, but core memory needs persistence clarity | 01 | memory API/UI plus restart decision | Core-candidate |
| 10 | `task(tts): integrate local-first TTS readiness into v1 status` | Pull #1699/#1702 into optional readiness gate | Read-back should be usable or honestly optional | 04 | TTS status/API/UI tests | Optional |
| 11 | `task(source-understanding): decide P0 v1 route/apply posture` | Keep optional/API-only or add Companion route/handoff | Prevent source-peek/provenance from being conflated with SU P0 | 01 | source/API/UI decision receipt | Optional |
| 12 | `task(canvas): decide Canvas/Chat v1 inclusion boundary` | Keep experimental or promote with gates | Avoid dragging flag/process-memory/provider risk into core accidentally | 01, 04 | Canvas route/persistence/provider decision | Experimental |
| 13 | `task(builderops): define optional operator evidence projection posture` | Build-plane support, not product truth | Useful for delivery control but not runtime authority | 01 | docs/builderops checks | Optional |
| 14 | `epic(governance): design proportional governance tiers` | Future issue only | Reduce friction later without weakening authority | parent scope decision | linked future issue | Deferred |
| 15 | `task(docs): promote Integrated Runtime v1 owner docs and close parent` | Status/architecture/roadmap writeback | Close only after evidence exists | all core children | owner-doc diff + final receipt | Closure |

## First five child bodies for Fable/Codex validation

### 01 - task(integration): classify Integrated Runtime v1 scope and capability tiers

#### Context
Integrated Runtime v1 must not become a catch-all v6.1 backlog. Before implementation starts, classify every candidate capability as core, optional, experimental, or out of scope.

#### Scope
Create the v1 scope matrix, using the evidence pack and errata. Include System Entry Point, Companion UI routes, orientation, resurfacing, capture, Vault Browser, Panel Confirm, receipts history, Memory Review, Source Understanding, Canvas/Chat, Chat-to-Panel handoff, TTS, BuilderOps, health/status/config, and UAT.

#### Acceptance Criteria
- [ ] Every candidate capability has one v1 class and rationale.
  Verify: scope table in owner draft.
- [ ] No future v6.1 capability is smuggled into core v1 without a release gate.
  Verify: explicit out-of-scope/non-goals section.
- [ ] Proportional governance is linked as deferred.
  Verify: follow-up issue draft or linked placeholder.

#### Suggested Validation
- docs-only review.
- `git diff --check`.

### 02 - task(system-entry-point): close v1 release substrate residuals

#### Context
System Entry Point is the v1 front door. It has many shipped child surfaces, but release substrate status must reconcile #1782/#1795/#1851 and owner-doc writeback.

#### Scope
Verify state gallery, review residuals, shipped child-surface table, and owner docs. Either close the parent substrate or record explicit blockers.

#### Acceptance Criteria
- [ ] #1851 residuals are closed or linked as release blockers.
- [ ] #1795 state-gallery proof has a closure path.
- [ ] `SYSTEM_ENTRY_POINT_SPEC.md`, `docs/STATUS.md`, and `docs/SYSTEM_ENTRY_POINT/` do not overclaim.

#### Suggested Validation
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/companion_ui/`
- focused state-gallery and route residual tests.

### 03 - fix(companion-ui): enforce active-control route parity for v1 surfaces

#### Context
The evidence pack and errata identify route parity as the central island failure mode. Some SEP surfaces are fixed; remaining Panel/Vault/Canvas/TTS paths need targeted verification.

#### Scope
For every active v1-visible control, prove the route is same-origin reachable, or render a disabled/hidden state with factual reason.

#### Acceptance Criteria
- [ ] Panel confirm controls can reach `/api/panel/confirm` or are not active.
- [ ] Vault queue-review and vault-related controls are live-routed or factually disabled.
- [ ] Canvas controls are hidden/disabled unless v1 includes Canvas and routes are live.
- [ ] TTS status controls are live-routed if TTS is v1-visible.

#### Suggested Validation
- focused `tests/companion_ui/` route parity suite.
- browser runtime check.

### 04 - feature(status): expose Integrated Runtime v1 readiness matrix

#### Context
Health/status exists but is distributed. V1 needs one operator-facing readiness matrix for core/optional/experimental capabilities.

#### Scope
Expose capability readiness: ready, degraded, unavailable, experimental, or out of scope. Include vault, API, DB/outbox, worker/watcher, WriteGuard, Panel confirm, receipt sources, Companion route parity, provider state, feature flags, and optional TTS/Canvas/Memory state.

#### Acceptance Criteria
- [ ] Status names v1 capabilities and readiness state.
- [ ] Provider unavailable and feature disabled states are explicit.
- [ ] Process-memory-backed capabilities are marked experimental/degraded unless a persistence decision exists.

#### Suggested Validation
- API/status tests.
- Companion UI readiness render test if surfaced.

### 05 - test(uat): add no-mock v1 golden path scaffold

#### Context
Current tests are broad but fragmented. V1 needs a single integrated no-mock operator path.

#### Scope
Create a runbook/test scaffold that starts runtime, opens Companion UI, loads orientation/Vault Browser, stages a governed action, confirms it, shows receipt history, and validates health/status. Add negative cases for WriteGuard blocked, provider unavailable, no-vault/degraded, missing receipt source, and content-hash mismatch where applicable.

#### Acceptance Criteria
- [ ] UAT has exact commands, expected UI/API states, and failure criteria.
- [ ] Golden path proves at least one read-only step, one proposal step, one governed confirm, and one receipt visibility step.
- [ ] Negative safety cases do not create hidden writes or invented receipts.

#### Suggested Validation
- runbook dry-run against test vault where available.
- focused UAT receipt on parent.
