State: SoT v5.5 Reality-MVP baseline locked (baseline definition anchored in `docs/STATUS.md#baseline-definition`).
Doc role: Core SoT
Authority: Canonical testing and validation strategy for the active baseline, including required layers and guardrails for code changes.
# TESTING

## Layers
- Unit / contract testing: pure functions, schemas, adapters, and bounded logic in isolation.
- Integration testing: component boundaries such as API ↔ stores ↔ services, routing compilation, and outbox/store interactions.
- System / bootstrap testing: end-to-end runtime flows such as note → ingest → index → ASK, watcher → panel → promotion chains, and clean-state local startup/bootstrap verification.
- Scripted UAT: seeded-vault checks that assert operator-visible outcomes on the canonical local test path.
- Real-vault acceptance: bounded verification against a real vault or real operator workflow when the capability claims operator-facing support.
- System integration testing (SIT): opt-in flows that exercise multiple runtime systems or external dependencies together, such as live LLM/provider wiring and full startup/runtime verification.
- LLM eval (DeepEval/Ragas): opt-in `@pytest.mark.eval` tests for ASK/retrieval quality (see `docs/eval.md`).
- Property-based ingest invariants: `tests/ingest/test_normalize_properties.py` ensures normalize outputs Core-6 fields robustly.

## Architecture And SBS Fitness Checks

Architecture tests under `tests/architecture/` include deterministic fitness checks for target-state boundaries that are stable enough to enforce mechanically.

The first SBS enforcement rail is `tests/architecture/test_sbs_fitness_rules.py::test_target_sbs_contracts_do_not_reintroduce_active_vault_identity`. It is a read-only pytest check that scans target public SBS contract stubs outside the WSP ActiveContextSet contract for `activeVault`, `vaultPath`, `active_vault`, `vault_path`, `vault_root`, `vault path`, or `vault root` contract terms. Violations fail with file and line context and should be corrected by using an ActiveContextSet reference plus source binding. The check reports only; it does not mutate policy, memory, retrieval, knowledge, execution, or contract docs.

## Companion UI Browser Runtime Tests

Decision (#1435): Companion UI client-JS runtime behaviour uses Playwright, not Selenium or
Preview-MCP-only UAT. Browser runtime tests are additive to the existing static
`tests/companion_ui/*_browser.py` assertions.

Use static Companion UI browser assertions when the contract is server-emitted HTML from
`render_index_html`: stable selectors, text, data attributes, fallback DOM, and API wiring visible
in the rendered string. These tests stay fast, run in normal pytest lanes, and do not require
browser binaries.

Use real browser runtime tests when the contract depends on actual client execution: dynamic
`import()` loading, DOM mutation after module scripts run, event/click behaviour, async fetch
handling, browser storage, or layout/runtime APIs. The current harness serves `render_index_html`
output on `127.0.0.1` and drives Chromium headlessly through Playwright.

Determinism rule: browser tests must not depend on live `esm.sh` or other network resources. The
browser harness fulfills the pinned Mermaid and CodeMirror module URLs from repo-local ESM stubs and
blocks unexpected external requests. These stubs prove Companion UI runtime wiring and graceful
degradation; they are not a new product bundle authority.

Execution:
- Normal companion UI test runs skip browser-runtime tests unless explicitly enabled.
- Local opt-in command:
  `COMPANION_UI_BROWSER_TESTS=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/companion_ui/test_runtime_unavailable_browser.py tests/companion_ui/test_mermaid_browser.py`
- CI runs these in `.github/workflows/browser-runtime.yml`: the deterministic, fully offline
  `test_runtime_unavailable_browser.py` runs as a **blocking** gate, while `test_mermaid_browser.py`
  stays advisory (step-level `continue-on-error`) so its heavier-ESM flakiness cannot block a PR.
  The existing smoke gates must not install browser binaries or depend on this job.
- Live UI smoke (`tests/companion_ui/test_companion_ui_live_smoke.py`) is a separate opt-in check
  against a *running* gateway; it skips unless `COMPANION_UI_SMOKE_URL` is set, so it never gates a PR.

## Panel Read-Mode Checkbox Projection Coverage

Companion UI read-mode Panel checkbox confirmation must keep focused coverage for:

- Parser/mapping tests proving only valid `AI-åtgärder` task checkboxes are eligible and code-block/ordinary-task checkboxes are excluded.
- Projection endpoint validation tests for `note_path`/`artifact_id`, `panel_id`, `option_id`, `content_hash`/`source_hash`, pending/selectable status, and stale-content rejection.
- Stale source tests covering changed content, moved options, missing options, removed proposal sections, and duplicate labels.
- WriteGuard and safe/degraded-mode tests proving projection does not bypass governed write policy.
- Idempotency/retry tests for duplicate browser clicks, request retries, already-checked options, watcher overlap, and projection-success/execution-failure separation.
- Watcher/runtime convergence tests proving Obsidian/plain-text checked checkboxes and Companion UI projection produce the same runtime semantics and receipts.
- Companion UI read-mode browser tests proving ordinary task checkboxes remain read-only/non-agent controls and only runtime-declared Panel options call the projection endpoint.
- Ordinary Markdown task-list regression tests proving generic rendered task-list DOM never becomes Panel authority.
- Obsidian/text-editor compatibility tests proving manually changing `- [ ]` to `- [x]` in a valid Panel remains a valid confirmation path.

The source-backed read-mode projection endpoint is `POST /api/panel/checkbox-projection`.
The existing `POST /api/panel/confirm` path remains the staged/transient confirm API and
must not be treated as Markdown checkbox projection coverage.

## Layer mapping
| Layer | Focus | Representative suites | Command |
| --- | --- | --- | --- |
| Unit | Correct logic in one function/class/module | `tests/components/llm/test_router.py`, `tests/settings/test_model_registry.py`, `tests/guards/test_no_hardcoded_inbox_scope.py` | `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/components/llm/test_router.py tests/settings/test_model_registry.py tests/guards/test_no_hardcoded_inbox_scope.py -m "not pg"` |
| Integration | Boundaries and data integration inside this repo | `tests/settings/test_runtime.py`, `tests/settings/test_auto_heal.py`, `tests/cli/test_health_llm_routing.py`, `tests/runtime/test_startup_env.py` | `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/settings/test_runtime.py tests/settings/test_auto_heal.py tests/cli/test_health_llm_routing.py tests/runtime/test_startup_env.py -m "not pg"` |
| System | Whole-system end-to-end flows in a production-like local test harness | `tests/e2e/test_reality_mvp_pipeline.py`, `tests/e2e/test_watcher_registry_e2e.py` | `STORE_BACKEND=memory PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/e2e/test_reality_mvp_pipeline.py tests/e2e/test_watcher_registry_e2e.py -m "not pg"` |
| SIT | Cross-system/runtime/provider integration, often opt-in or environment-dependent | `tests/e2e/test_panel_llm_e2e.py`, `tests/reasoning/test_reasoning_llm_live_alpha.py`, `tests/cli/test_llm_doctor_cli.py` | `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/cli/test_llm_doctor_cli.py -m "not pg"` |

## Execution Model

The active strategy is a lightweight verification and acceptance spine. It is V-model-inspired in the sense that each capability should define intent, implementation slices, verification, and acceptance, but it is intentionally kept practical and lightweight.

| Level | Purpose | Typical scope | Gate posture |
| --- | --- | --- | --- |
| Unit + contract | Catch logic/schema regressions early | pure functions, adapters, event shapes, settings validation | PR-blocking |
| Integration | Prove backend/runtime seams | pg-backed stores, queue wiring, API/store seams, CLI/service boundaries | PR-blocking for touched seams or nightly |
| System / bootstrap | Prove the canonical runtime and clean-state bootstrap chain works | watcher/runtime loop, ingest→index→ASK, docker/runtime smoke, `make test-bootstrap` slices | PR smoke plus broader nightly |
| Scripted UAT | Prove the seeded-vault operator path works | seeded vault, receipts/intents, rerun idempotence, status/health assertions | release/UAT gate |
| Real-vault acceptance | Prove the claimed operator-facing capability works in a realistic bounded environment | real vaults, bounded operator flows, acceptance walkthroughs | explicit acceptance gate for capabilities that claim it |

## Testing, Verification, Validation, And Acceptance

Use these terms distinctly in both docs and execution:

- Testing = the commands, suites, and checks that run.
- Slice verification = proof that one bounded slice / child issue implemented its intended contract correctly.
- Feature validation = proof that the wider feature / capability works for the intended operator or product outcome, sometimes after merge.
- Acceptance = the explicit decision that the repo can now claim and support that feature in owner docs.

Real-life evidence rule:
- PRs should carry slice verification evidence.
- Parent feature / capability issues should carry post-merge validation evidence and the acceptance checklist, typically through the issue body and validation comments.
- Owner docs should change when the accepted support claim changes, not for every rerun or post-merge observation.

This keeps docs stable while still allowing truthful post-merge validation.

## Dual Validation Model

The repo uses two complementary validation tracks and they must not be collapsed into one gate.

- Baseline verification protects the currently locked runtime baseline described in `docs/STATUS.md`.
- Human-need acceptance protects the intended product behavior described in `docs/HUMAN-FLOWS.md` and elaborated in `docs/plans/SCENARIO_ACCEPTANCE_MATRIX.md`.

Interpretation rule:
- baseline tests ask "does the current implementation still do what the active baseline claims?"
- human-need tests ask "does the system satisfy the human situation it is meant to support?"

Gate rule:
- baseline verification is blocking when it covers active baseline contracts
- human-need acceptance may begin as non-blocking system-level TDD when the current implementation does not yet fully satisfy the scenario
- a human-need scenario only becomes a blocking release or smoke gate when the baseline/status docs explicitly claim that capability as part of the active runtime

This distinction is intentional. It prevents the current architecture from becoming the accidental product definition while also preventing target-state scenarios from creating misleading smoke failures before the implementation is ready.

### Human-Need Acceptance Track

Human-need acceptance scenarios should be written from the user-facing contract first, not from the current runtime decomposition.

They should:
- derive from `docs/HUMAN-FLOWS.md` first and `docs/plans/SCENARIO_ACCEPTANCE_MATRIX.md` second
- express observable user outcomes rather than internal component choreography
- operate as system-level TDD for the future product shape
- be classified explicitly as `baseline`, `partial`, or `future` posture in planning/docs before they are promoted into blocking gates

Suggested posture markers:
- `@pytest.mark.human_uat` for human-need scenario tests
- `@pytest.mark.release_uat` for blocking release-grade UAT on capabilities already claimed by the active baseline

Expected CI posture:
- `pr-smoke` protects baseline verification only
- nightly/on-demand jobs may run broader `human_uat` scenarios even when some are expected to remain non-blocking
- release gates may include only the subset of human-need scenarios that the active baseline explicitly claims to support

### Change-to-test mapping

| Change type | Minimum required coverage |
| --- | --- |
| Pure business logic / parser / helper | unit + nearby contract tests |
| Event schema, outbox, promotion, watcher policy | unit + contract + targeted integration/e2e |
| Store/backend/runtime queue changes | unit + pg/integration + system/e2e |
| Operator flow, watcher automation, panel/promotion UX, local test bootstrap path | system/e2e + UAT harness |
| Retrieval/ASK behavior | unit + e2e + opt-in eval when relevance/quality changes materially |

## Bootstrap As A Verification Contract

The local test bootstrap path is a first-class testable contract. It should not be treated as informal setup glue.

For bootstrap-sensitive capabilities, define all four of the following:
- design / intent
- implementation slices
- verification path
- acceptance path

Bootstrap-specific rule:
- a local bootstrap capability is not done when the stack can sometimes be started manually
- it is done when the supported clean-state path is explicit, repeatable, verified, and acceptable as a repo-supported operator/developer workflow

Current canonical local bootstrap path:
1. reset runtime state
2. initialize a clean test vault
3. seed the UAT notes
4. start the local stack
5. verify health/status
6. run scripted UAT

The canonical command wrapper for that path is `make test-bootstrap`.

See `docs/LOCAL_TEST_BOOTSTRAP/` for the complete specification and verification contract for each step.

## Evaluation Stack (Registry Watcher / Panel / Promotion)
Delivery receipt: Quality Wave phases A-F landed across PRs #197, #198, #199, #200, #201, #202, and #210; this section is the lasting validation contract for the shipped stack.
- **A. Contract tests** — assert watcher→panel→promotion event envelopes and payload invariants; run via `pytest -q tests/e2e/test_watcher_registry_e2e.py -m "not pg"` (exact command may move to `tests/fitness`).
- **B. Golden vault** — seeded vault + snapshots under `docs/examples/vault_test_seed/`; deterministic diff harness to prove no unintended note mutations.
- **C. Metamorphic runs** — vary `WATCHER_AUTO_EXEC`, `WATCHER_SCOPE_GLOB`, `WATCHER_TICK_SLEEP_SECONDS`, and `--max-ticks`; expect identical receipts/intents where applicable.
- **D. Cold rebuild** — start from empty Store + existing mirrors; prove ingest + panel/promotion chain reconstructs counters/events without dupes.
- **E. Fitness gates** — status/outbox counters checked post-run (`panel_runs`, `promote.intent.created/done`) with idempotence (no duplicate intents on rerun) enforced in CI (`app/fitness/*`, `ops/quality/baselines.yaml`).
- **F. Scripted UAT** — CLI harness for registry watcher + promotion consumer + status assertions; runs on memory backend and real vaults with the golden seed pack.

### UAT contract

The scripted UAT harness should behave like a release candidate check, not just a demo command. At minimum it must assert:

- at least one `promote.intent.created` is emitted from the seeded vault pack
- at least one promotion is applied without watcher/promotion errors
- policy-gated notes remain skipped
- the seeded evergreen note reaches the expected frontmatter state
- a second run over the same snapshot produces no new watcher/panel/promotion side effects
- the harness emits a machine-readable report for CI/UAT automation

### Local test bootstrap contract

This bootstrap contract should be treated as a stabilization and release gate for the local `test` environment. If the repo claims a supported local verification path, the bootstrap path itself must remain observable, resettable, and reproducible.

The repo-supported local test bootstrap path is:

```bash
make test-bootstrap
```

Regression protection for that path must cover:
- clean-state vault layout bootstrap without undocumented folder hints
- seeded UAT notes being inside the startup ingest contract
- scripted UAT running against the real vault root with an explicit scoped folder, not by treating `<vault>/Test` as a standalone vault
- reset clearing watcher pause/state artifacts that would make the next startup appear healthy while the watcher is paused
- shell-local bootstrap resilience when `DEBUG` is exported with a non-boolean value

## CI And Fitness Gates

- GitHub Actions workflows are the enforced CI surface for lint, tests, and fitness gating.
- The fitness gate contract is:
  - `python -m app.fitness.report` emits `CI SUMMARY ...` lines
  - CI fails whenever `GATES.ok != true`

## CI Roles

The CI surface should stay small and explicit. The intended steady-state roles are:

| Workflow role | Purpose | Expected posture |
| --- | --- | --- |
| `pr-smoke` | Fast merge blocker: lint, settings validation, `not pg` smoke, architecture/contract checks, deterministic Quality Wave UAT harness, fitness summary parsing | required on PRs |
| `integration-nightly` | Full `pytest -m "not pg and not alpha_llm"` suite, explicit deterministic Quality Wave acceptance harness, first bounded PG contracts lane, runtime contract regressions, fitness gates | nightly / scheduled |
| `release-uat` | Quality Wave gate (UAT harness + golden vault + full QW suite), fitness gates | release/UAT gate (tags + manual) |

Human-need acceptance scenarios should map onto those roles explicitly instead of silently riding along with smoke:
- use `pr-smoke` only for active baseline behavior
- use `integration-nightly` or a dedicated non-blocking acceptance job for broader human-need scenarios that are still driving implementation
- move a scenario into `release-uat` only after the baseline/status docs say the capability is part of the supported runtime

Older overlapping workflows may still exist while the surface is being consolidated, but new coverage should map to these roles instead of adding more partial gates.

Current implementation:
- `.github/workflows/ci-smoke.yaml` — PR smoke with explicit system dependency parity (`ffmpeg`, `ripgrep`), required `ruff check app tests` and `settings-validate` checks, split baseline pytest and deterministic Quality Wave UAT harness steps, and path-based skipping of the heavy pytest slices for docs-only PRs that do not touch code, tests, scripts, workflow, Docker, dependency, or Makefile surfaces.
- `.github/workflows/integration-nightly.yaml` — full suite nightly at 02:00 UTC, explicit deterministic acceptance harness coverage via `tests/quality_wave/test_uat_harness.py`, first bounded PG contracts lane (`tests/int/test_pg_backend.py`, `tests/api/test_status_store_pg.py`, `tests/indexer/test_outbox_roundtrip_pg.py`), runtime contract regressions, and fitness gates.
- `.github/workflows/release-uat.yaml` — UAT harness + golden vault + full QW suite + fitness gates; triggered on version tags and manual dispatch.

### Nightly deterministic acceptance harness

The deterministic Quality Wave acceptance harness belongs in `integration-nightly`, not `release-uat`.

Reason:
- it is a trusted recurring verification signal for the active memory-backed runtime posture
- it proves the CLI-first UAT contract continues to pass outside tag/manual release events
- it should run alongside the broader nightly `not pg and not alpha_llm` surface rather than only as a release gate

Current nightly harness target:
- `tests/quality_wave/test_uat_harness.py`

### First bounded PG verification lane

The first recurring Postgres lane is intentionally small and contract-focused. It exists to establish a credible recurring PG signal without broadening nightly into all PG coverage at once.

Lane membership:
- `tests/int/test_pg_backend.py`
- `tests/api/test_status_store_pg.py`
- `tests/indexer/test_outbox_roundtrip_pg.py`

Required service/env contract:
- GitHub Actions service container: `postgres:16`
- `POSTGRES_USER=app`
- `POSTGRES_PASSWORD=app`
- `POSTGRES_DB=app`
- `DATABASE_URL` or `DB_DSN` points at the target Postgres endpoint; the repo DB abstraction normalizes psycopg/SQLAlchemy forms
- `STORE_BACKEND=pg`
- schema prepared with `alembic upgrade head`

First-green definition:
- all three PG lane tests pass against the provisioned Postgres service in `integration-nightly`
- the deterministic acceptance harness step is green in the same nightly workflow run
- the existing memory-backed nightly suite and runtime contract regressions remain green

## Required baseline checks

- `ruff check app tests`
- `mypy app`
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q -m "not pg"`
- `python -m app.cli settings-validate --json`

> **Plugin-load guard:** <!-- plugin-load-guard --> When `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` is set, flags provided by
> plugins are not available unless the plugin is also explicitly loaded with `-p <plugin_name>`.
> For example, to use `pytest-xdist` with autoload disabled:
> ```
> PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -p xdist.plugin -n auto ...
> ```
> Do not assume installing a plugin is sufficient — verify the flag resolves with an explicit
> `-p` load if autoload is disabled.

For fast local runs that bypass workspace/global pytest configuration, prefer:
- `STORE_BACKEND=memory PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q -m "not pg" -c /dev/null`
- `make smoke` (parallel by default via `pytest-xdist`; override workers with `SMOKE_WORKERS=<n|auto>`, and include e2e lane with `SMOKE_E2E_WORKERS=<n>`)

## Concurrency Tests (docs-only)
These regression suites live in `docs/CONCURRENCY.md` and the new watcher/promotion/test libraries.

- **Event deduplication:** `tests/ops/test_watcher_auto_exec_idempotent.py` validates watcher dedup + policy gating plus the `skipped_dedup` signal.
- **Optimistic locking:** the same suite exercises note writes when `DEFAULT_WRITE_GUARD` is engaged to ensure stale writes bail out cleanly.
- **Action idempotency:** `tests/promotion/test_consumer_idempotency.py` uses `EventDedupStore` to prove duplicate `promote.intent.created` events are recorded but do not reapply maturity changes.
- **Settings gating:** `tests/settings/test_panel_actions_settings.py` and `tests/settings/test_watcher_settings.py` cover panel action catalog validation, precedence, and provenance (path/mtime/sha).

Example commands:
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/ops/test_watcher_auto_exec_idempotent.py -m "not pg"`
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/promotion/test_consumer_idempotency.py -m "not pg"`
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/settings/test_panel_actions_settings.py tests/settings/test_watcher_settings.py -m "not pg"`

## Hermetic test environment
- The test suite clears VAULT_ROOT and PANEL_ACTION_WIRING_PATH by default to prevent accidentally reading a user’s real vault (often iCloud-backed) which can block and hang tests.
- Tests that require vault wiring overrides must set VAULT_ROOT explicitly (use monkeypatch + temp vault containing System/Config/panel-action-wiring.yaml) or set PANEL_ACTION_WIRING_PATH explicitly.

## Focused commands
- Single test:
  - `pytest -q tests/agents/test_normalizer.py`
- Eval (opt-in):
  - `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q -m "eval"`
- Human-need acceptance (opt-in):
  - `RUN_HUMAN_UAT=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/e2e/test_human_need_uat.py -m "human_uat"`
- PanelAgent LLM E2E (opt-in, real LLM):
  - `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/e2e/test_panel_llm_e2e.py -m "panel_llm_e2e"`
- Registry watcher deterministic E2E:
  - `STORE_BACKEND=memory PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/e2e/test_watcher_registry_e2e.py -m "not pg"`
- Architecture guardrails:
  - `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/architecture/test_outer_inner_boundaries.py tests/architecture/test_obsidian_port_boundaries.py -m "not pg"`
- Panel wiring precedence:
  - `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/agents/panel_agent/test_panel_wiring.py -m "not pg"`

## Debugging hanging tests
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONFAULTHANDLER=1 pytest -vv -m "not pg" --faulthandler-timeout 60`
- Note: the dump shows where the test is blocked (e.g. filesystem read / iCloud / background threads).

## Reality-MVP pipeline sanity
- Scenario: `tests/e2e/test_reality_mvp_pipeline.py` runs the canonical note → ingest/normalize/classify → store/outbox/index → hybrid search warm-load → `/api/ask` flow against `tests/fixtures/reality_mvp/demo_note.md` (see `docs/scenarios/REALITY_MVP.md`).
- Command: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/e2e/test_reality_mvp_pipeline.py --maxfail=1`
- Fit: keeps the top of the pyramid honest while unit/contract/property tests cover the lower layers (ingest invariants, agent contracts, retrieval).

## Determinism
- Hashing-based embeddings in tests for stable semantics
- Fixed chunk sizes and overlap

## Quality And Guardrails In Validation

- Guardrails are part of the validation surface, not just runtime behavior.
- Current quality checks worth preserving in test/eval design:
  - forbidden-content filtering
  - source requirements
  - token budget enforcement
  - circuit-breaker behavior when it becomes runtime-wired
- Performance budgets currently tracked operationally:
  - retrieval p95 target
  - QA answer latency target
  - ASR wall-time target
- Use `docs/guardrails.md` for the runtime safety policy itself; this document owns how those expectations are validated.

<!-- SECTION:TESTING-MATRIX:BEGIN -->
## Test matrix
| Type | Focus | Command |
| --- | --- | --- |
| Unit | Pure functions (retrieval, guardrails) | `PYTHONPATH="$(pwd)" pytest tests/retrieval -q` |
| Smoke (local/CI) | CLI + pipelines without Postgres | `LLM_PROVIDER=mock PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q -m "not pg"` |
| Transcribe smoke | yt-dlp + ffmpeg + faster-whisper stubs | `pytest -q tests/test_transcribe_smoke.py -m "not pg"` |
| Hybrid search | End-to-end recall | `pytest -q tests/test_hybrid_search.py` |
| Reality-MVP e2e | Note → ingest → index → ASK sanity (memory backend) | `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/e2e/test_reality_mvp_pipeline.py --maxfail=1` |

## Selective runs & mocking
- Set `LLM_PROVIDER=mock` and `LLM_MOCK_RESPONSE='{"type":"note","trust":"own","tags":["topic/test"],"confidence":0.95}'` for deterministic answers (mirrors `.github/workflows/smoke.yml`).
- Mock ASR by patching `app.media.transcribe.WhisperModel`; see `tests/test_transcribe_smoke.py`.
<!-- SECTION:TESTING-MATRIX:END -->
