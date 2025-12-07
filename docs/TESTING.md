State: SoT v4.10 Reality-MVP (current core).
# TESTING

## Layers
- Unit: pure functions and single-agent logic
- Contract: `.done` event payload shape and DB side-effects per agent
- E2E: normalizer → classifier → chunker → deduper → citation → indexer → reviewer → projector
- LLM eval (DeepEval/Ragas): opt-in `@pytest.mark.eval` tests for ASK/retrieval quality (see `docs/eval.md`)
- Property-based ingest invariants: `tests/ingest/test_normalize_properties.py` ensures normalize outputs Core-6 fields robustly.

## Commands (aligned with CI)
- Fast smoke (matches `ci-smoke` defaults; memory store, mock LLM, rerank off):  
  `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q -c /dev/null -m "not pg and not alpha_llm"`
- Developer fast pass (no Postgres, excludes alpha_llm):  
  `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q -m "not pg"`
- E2E graph (full PER chain, local Postgres recommended):  
  `PYTHONPATH="$(pwd)" DATABASE_URL="postgresql+psycopg://app:app@127.0.0.1:15432/app" pytest -q tests/e2e/test_pipe_graph.py`
- Eval (opt-in diagnostics; not part of smoke):  
  `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q -m "eval"`  # DeepEval/Ragas; skipped when deps/config missing
- Single test:  
  `pytest -q tests/agents/test_normalizer.py`

## Markers
- `not_pg`: safe to run without Postgres.
- `alpha_llm`: uses heavier LLM-driven reasoning/planner flows; excluded from smoke.
- `alpha_llm_live`: live LLM calls; manual only.
- `eval`: DeepEval/Ragas diagnostics; opt-in.

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
| Smoke (local/CI) | CLI + pipelines without Postgres | `LLM_PROVIDER=mock PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q -c /dev/null -m "not pg and not alpha_llm"` |
| Transcribe smoke | yt-dlp + ffmpeg + faster-whisper stubs | `pytest -q tests/test_transcribe_smoke.py -m "not pg"` |
| Hybrid search | End-to-end recall | `pytest -q tests/test_hybrid_search.py` |
| Reality-MVP e2e | Note → ingest → index → ASK sanity (memory backend) | `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/e2e/test_reality_mvp_pipeline.py --maxfail=1` |

## Selective runs & mocking
- Set `LLM_PROVIDER=mock` and `LLM_MOCK_RESPONSE='{"type":"note","trust":"own","tags":["topic/test"],"confidence":0.95}'` for deterministic answers (mirrors `ci-smoke` workflow).
- To skip slower classifier tests, set `SKIP_CLASSIFIER_TESTS=0` locally (default `1` in `tests/agents/test_classifier.py:3`).
- Mock ASR by patching `app.media.transcribe.WhisperModel`; see `tests/test_transcribe_smoke.py`.

## Artifacts
- `tmp/index-outbox.jsonl` – written by CLI/ASR tests; clean between runs if determinism is required.
- `logs/*.jsonl` – JSON spans used by `jq` recipes in `docs/OBSERVABILITY.md`.
- `tmp/audio/` – yt-dlp cache (unique filenames per test). Clean via `rm -rf tmp/audio/*`.
<!-- SECTION:TESTING-MATRIX:END -->
