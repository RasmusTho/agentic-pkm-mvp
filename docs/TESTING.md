State: SoT v5.5 Reality-MVP baseline locked (baseline definition anchored in `docs/STATUS.md#baseline-definition`).
Doc role: Core SoT
Authority: Canonical testing and validation strategy for the active baseline, including required layers and guardrails for code changes.
# TESTING

## Layers
- Unit: pure functions and single-agent logic
- Contract: `.done` event payload shape and DB side-effects per agent
- E2E: normalizer → classifier → chunker → deduper → citation → indexer → reviewer → projector
- LLM eval (DeepEval/Ragas): opt-in `@pytest.mark.eval` tests for ASK/retrieval quality (see `docs/eval.md`)
- Property-based ingest invariants: `tests/ingest/test_normalize_properties.py` ensures normalize outputs Core-6 fields robustly.

## Execution Model

The active strategy is a four-level pyramid. Each level protects a different class of regression and should remain explicit in both docs and CI.

| Level | Purpose | Typical scope | Gate posture |
| --- | --- | --- | --- |
| Unit + contract | Catch logic/schema regressions early | pure functions, adapters, event shapes, settings validation | PR-blocking |
| Integration | Prove backend/runtime seams | pg-backed stores, queue wiring, API/store seams, CLI/service boundaries | PR-blocking for touched seams or nightly |
| System / E2E | Prove the canonical runtime chain works | watcher/runtime loop, ingest→index→ASK, docker/runtime smoke | PR smoke plus broader nightly |
| UAT / release | Prove operator-visible behavior on a golden vault pack | seeded vault, receipts/intents, rerun idempotence, status/health assertions | release/UAT gate |

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
| `pr-smoke` | Fast merge blocker: lint, settings validation, `not pg` smoke, architecture/contract checks, fitness summary parsing | required on PRs |
| `integration-nightly` | Slower pg-backed and metamorphic coverage for runtime seams and rebuild/idempotence checks | nightly / scheduled |
| `release-uat` | Golden-vault runtime verification with the UAT harness and operator-facing assertions | release/UAT gate |

Older overlapping workflows may still exist while the surface is being consolidated, but new coverage should map to these roles instead of adding more partial gates.

Current implementation checkpoint:
- `.github/workflows/integration-nightly.yaml` runs the runtime-contract regression slice (metamorphic watcher coverage, alpha/UAT contract helpers, and cold-rebuild regression tests).

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
