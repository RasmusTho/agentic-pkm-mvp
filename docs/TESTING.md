State: SoT v5.5 Reality-MVP baseline locked (baseline definition anchored in `docs/STATUS.md#baseline-definition`).
# TESTING

## Layers
- Unit: pure functions and single-agent logic
- Contract: `.done` event payload shape and DB side-effects per agent
- E2E: normalizer → classifier → chunker → deduper → citation → indexer → reviewer → projector
- LLM eval (DeepEval/Ragas): opt-in `@pytest.mark.eval` tests for ASK/retrieval quality (see `docs/eval.md`)
- Property-based ingest invariants: `tests/ingest/test_normalize_properties.py` ensures normalize outputs Core-6 fields robustly.

## Test Coverage

Current coverage (updated 2025-01-XX):
- Router: 95% line coverage, 100% branch coverage
- Fabric: 60% line coverage (gaps: failure modes)
- Health: 85% line coverage (gaps: malformed input handling)

Critical uncovered paths (issue links):
- Router: Malformed LLMTaskIntent handling (Issue: `docs/ISSUES_TESTING.md#router-malformed-intent`)
- Fabric: Provider unavailable scenarios (Issue: `docs/ISSUES_TESTING.md#fabric-provider-unavailable`)
- Health: Future timestamp rejection (Issue: `docs/ISSUES_TESTING.md#health-future-timestamp`)

See: `pytest --cov=app --cov-report=html`

## Evaluation Stack (Runtime Loop / Panel / Promotion)
- **A. Contract tests** — assert watcher→panel→promotion event envelopes and payload invariants; run via `pytest -q tests/e2e/test_runtime_loop_vault_test.py -m "not pg"` (exact command may move to `tests/fitness`).
- **B. Golden vault** — seeded vault + snapshots under `docs/examples/vault_test_seed/`; deterministic diff harness to prove no unintended note mutations.
- **C. Metamorphic runs** — vary `--interval`, `--dry-run`, `--max-notes`, and wiring/policy flags; expect identical receipts/intents where applicable.
- **D. Cold rebuild** — start from empty Store + existing mirrors/snapshots; prove ingest + panel/promotion chain reconstructs counters/events without dupes.
- **E. Fitness gates** — status/outbox counters checked post-run (watcher_runs, panel_runs, promote.intent.created/done) with idempotence (no duplicate intents on rerun) enforced in CI (`app/fitness/*`, `ops/quality/baselines.yaml`).
- **F. Scripted UAT** — CLI harness for runtime-loop + promotion consumer + status assertions; runs on memory backend and real vaults with the golden seed pack.

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

## Commands
- Repo-root deterministic run (memory backend; plugin autoload disabled):
  - STORE_BACKEND=memory PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q -m "not pg"
- Workspace-root deterministic run (bypass global a workspace-level pytest.ini):
  - STORE_BACKEND=memory PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q -m "not pg" -c /dev/null
- Note: global a workspace-level pytest.ini can inject timeout args when plugins are disabled; prefer the commands above when running locally.
- Single test
  - pytest -q tests/agents/test_normalizer.py
- E2E graph
  - PYTHONPATH="$(pwd)" env DATABASE_URL="postgresql+psycopg://app:app@127.0.0.1:15432/app" pytest -q tests/e2e/test_pipe_graph.py
- Eval (opt-in)
  - PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q -m "eval"  # DeepEval/Ragas; not part of fast CI
- PanelAgent LLM E2E (opt-in, real LLM)
  - export PANEL_AGENT_LLM_E2E=1 PANEL_AGENT_DECIDER=llm
  - export LLM_PROVIDER=<provider> plus any provider-specific env (e.g., OPENAI_BASE_URL/OPENAI_API_KEY)
  - PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/e2e/test_panel_llm_e2e.py -m "panel_llm_e2e"
  - CI: optional job `panel-llm-e2e` in `ci-smoke.yaml` runs these tests when `PANEL_AGENT_LLM_E2E_CI=true` and LLM secrets are present; otherwise it skips without failing the pipeline.
- Panel planner/orchestrator (deterministic)
  - export STORE_BACKEND=memory PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
  - pytest -q tests/cli/test_panel_orchestrator_cli.py -m "not pg"
  - Planner pipeline remains opt-in (`PANEL_AGENT_PIPELINE=planner`); CLI execution is available via `panel-orchestrate-plan`.
- Runtime Loop V1 (deterministic E2E, memory backend):
  - export STORE_BACKEND=memory PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 INDEX_OUTBOX_PATH=$(mktemp)
  - pytest -q tests/e2e/test_runtime_loop_vault_test.py -m "not pg"
  - Contract: second tick with unchanged snapshot should report promotion applied=0 and errors=0 (outbox cursor prevents replays).
- Optional manual run: `python -m app.cli runtime-loop --vault-root "<vault>" --interval 0` with the UAT seed pack.
- Watcher/Panel UAT CLI pack (deterministic, memory backend)
  - export STORE_BACKEND=memory PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 INDEX_OUTBOX_PATH=$(mktemp)
  - pytest -q tests/cli/test_uat_seed_cli.py tests/cli/test_uat_run_cli.py -m "not pg"
  - Real vault: `python -m app.cli uat-seed-vault-test --vault-root "<vault>"` then `python -m app.cli uat-run-vault-test --vault-root "<vault>" --assert`.
- Architecture guardrails
  - export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
  - pytest -q tests/architecture/test_outer_inner_boundaries.py -m "not pg"
- Panel action wiring (config-driven)
  - export STORE_BACKEND=memory PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
  - pytest -q tests/agents/panel_agent/test_panel_wiring.py -m "not pg"

- Settings/Config
  - `python -m app.cli.settings validate --json`
  - `python -m app.cli.settings_explain`

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

## DB
- Local Postgres with pgvector
- Alembic upgrade before tests

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
- To skip slower classifier tests, set `SKIP_CLASSIFIER_TESTS=0` locally (default `1` in `tests/agents/test_classifier.py:3`).
- Mock ASR by patching `app.media.transcribe.WhisperModel`; see `tests/test_transcribe_smoke.py`.

## Artifacts
- `tmp/index-outbox.jsonl` – written by CLI/ASR tests; clean between runs if determinism is required.
- `logs/*.jsonl` – JSON spans used by `jq` recipes in `docs/OBSERVABILITY.md`.
- `tmp/audio/` – yt-dlp cache (unique filenames per test). Clean via `rm -rf tmp/audio/*`.
<!-- SECTION:TESTING-MATRIX:END -->

- Panel wiring precedence (deterministic):
  - export PANEL_ACTIONS_PATH=<tmp/actions.md>
  - optional vault override: set VAULT_ROOT to a temp vault containing System/Config/panel-action-wiring.yaml
  - env override: PANEL_ACTION_WIRING_PATH points to a temp wiring file
  - run: pytest -q tests/agents/panel_agent/test_panel_wiring.py -m "not pg"
