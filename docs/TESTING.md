State: SoT v5.5 Reality-MVP baseline locked (baseline definition anchored in `docs/STATUS.md#baseline-definition`).
Doc role: Core SoT
Authority: Canonical testing and validation strategy for the active baseline, including required layers and guardrails for code changes.
# TESTING

## Layers
- Unit testing: pure functions and single-agent logic in isolation.
- Integration testing: component boundaries such as API ↔ stores ↔ services, routing compilation, and outbox/store interactions.
- System testing: end-to-end runtime flows such as note → ingest → index → ASK or watcher → panel → promotion chains.
- System integration testing (SIT): opt-in flows that exercise multiple runtime systems or external dependencies together, such as live LLM/provider wiring and full startup/runtime verification.
- Contract: `.done` event payload shape and DB side-effects per agent.
- LLM eval (DeepEval/Ragas): opt-in `@pytest.mark.eval` tests for ASK/retrieval quality (see `docs/eval.md`).
- Property-based ingest invariants: `tests/ingest/test_normalize_properties.py` ensures normalize outputs Core-6 fields robustly.

## Layer mapping
| Layer | Focus | Representative suites | Command |
| --- | --- | --- | --- |
| Unit | Correct logic in one function/class/module | `tests/components/llm/test_router.py`, `tests/settings/test_model_registry.py`, `tests/guards/test_no_hardcoded_inbox_scope.py` | `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/components/llm/test_router.py tests/settings/test_model_registry.py tests/guards/test_no_hardcoded_inbox_scope.py -m "not pg"` |
| Integration | Boundaries and data integration inside this repo | `tests/settings/test_runtime.py`, `tests/settings/test_auto_heal.py`, `tests/cli/test_health_llm_routing.py`, `tests/runtime/test_startup_env.py` | `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/settings/test_runtime.py tests/settings/test_auto_heal.py tests/cli/test_health_llm_routing.py tests/runtime/test_startup_env.py -m "not pg"` |
| System | Whole-system end-to-end flows in a production-like local test harness | `tests/e2e/test_reality_mvp_pipeline.py`, `tests/e2e/test_watcher_registry_e2e.py` | `STORE_BACKEND=memory PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/e2e/test_reality_mvp_pipeline.py tests/e2e/test_watcher_registry_e2e.py -m "not pg"` |
| SIT | Cross-system/runtime/provider integration, often opt-in or environment-dependent | `tests/e2e/test_panel_llm_e2e.py`, `tests/reasoning/test_reasoning_llm_live_alpha.py`, `tests/cli/test_llm_doctor_cli.py` | `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/cli/test_llm_doctor_cli.py -m "not pg"` |

## Execution Model

The active strategy is a four-level pyramid. Each level protects a different class of regression and should remain explicit in both docs and CI.

| Level | Purpose | Typical scope | Gate posture |
| --- | --- | --- | --- |
| Unit + contract | Catch logic/schema regressions early | pure functions, adapters, event shapes, settings validation | PR-blocking |
| Integration | Prove backend/runtime seams | pg-backed stores, queue wiring, API/store seams, CLI/service boundaries | PR-blocking for touched seams or nightly |
| System / E2E | Prove the canonical runtime chain works | watcher/runtime loop, ingest→index→ASK, docker/runtime smoke | PR smoke plus broader nightly |
| UAT / release | Prove operator-visible behavior on a golden vault pack | seeded vault, receipts/intents, rerun idempotence, status/health assertions | release/UAT gate |

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
| Operator flow, watcher automation, panel/promotion UX | system/e2e + UAT harness |
| Retrieval/ASK behavior | unit + e2e + opt-in eval when relevance/quality changes materially |

## Evaluation Stack (Registry Watcher / Panel / Promotion)
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

## CI And Fitness Gates

- GitHub Actions workflows are the enforced CI surface for lint, tests, and fitness gating.
- The fitness gate contract is:
  - `python -m app.fitness.report` emits `CI SUMMARY ...` lines
  - CI fails whenever `GATES.ok != true`

## CI Roles

The CI surface should stay small and explicit. The intended steady-state roles are:

| Workflow role | Purpose | Expected posture |
| --- | --- | --- |
| `pr-smoke` | Fast merge blocker: lint, settings validation, `not pg` smoke, architecture/contract checks, Quality Wave suite, fitness summary parsing | required on PRs |
| `integration-nightly` | Full `pytest -m "not pg and not alpha_llm"` suite (736+ tests), runtime contract regressions, fitness gates | nightly / scheduled |
| `release-uat` | Quality Wave gate (UAT harness + golden vault + full QW suite), fitness gates | release/UAT gate (tags + manual) |

Human-need acceptance scenarios should map onto those roles explicitly instead of silently riding along with smoke:
- use `pr-smoke` only for active baseline behavior
- use `integration-nightly` or a dedicated non-blocking acceptance job for broader human-need scenarios that are still driving implementation
- move a scenario into `release-uat` only after the baseline/status docs say the capability is part of the supported runtime

Older overlapping workflows may still exist while the surface is being consolidated, but new coverage should map to these roles instead of adding more partial gates.

Current implementation:
- `.github/workflows/ci-smoke.yaml` — PR smoke including `tests/quality_wave/` (99 QW tests).
- `.github/workflows/integration-nightly.yaml` — full suite nightly at 02:00 UTC + runtime contract regressions + fitness gates.
- `.github/workflows/release-uat.yaml` — UAT harness + golden vault + full QW suite + fitness gates; triggered on version tags and manual dispatch.

## Required baseline checks

- `ruff check app tests`
- `mypy app`
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q -m "not pg"`
- `python -m app.cli settings-validate --json`

For fast local runs that bypass workspace/global pytest configuration, prefer:
- `STORE_BACKEND=memory PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q -m "not pg" -c /dev/null`

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
