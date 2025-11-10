# TESTING

## Layers
- Unit: pure functions and single-agent logic
- Contract: `.done` event payload shape and DB side-effects per agent
- E2E: normalizer → classifier → chunker → deduper → citation → indexer → reviewer → projector

## Commands
- Single test
  - pytest -q tests/agents/test_normalizer.py
- E2E graph
  - PYTHONPATH="$(pwd)" env DATABASE_URL="postgresql+psycopg://app:app@127.0.0.1:15432/app" pytest -q tests/e2e/test_pipe_graph.py

## Determinism
- Hashing-based embeddings in tests for stable semantics
- Fixed chunk sizes and overlap

## DB
- Local Postgres with pgvector
- Alembic upgrade before tests

<!-- SECTION:TESTING-MATRIX:BEGIN -->
## Testmatris
| Typ | Fokus | Kommando |
| --- | --- | --- |
| Unit | Pure funktioner (retrieval, guardrails) | `PYTHONPATH="$(pwd)" pytest tests/retrieval -q` |
| Smoke (lokal/CI) | CLI + pipelines utan Postgres | `LLM_PROVIDER=mock PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q -m "not pg"` |
| Transcribe smoke | yt-dlp + ffmpeg + faster-whisper stubbar | `pytest -q tests/test_transcribe_smoke.py -m "not pg"` |
| Hybrid search | End-to-end recall | `pytest -q tests/test_hybrid_search.py` |

## Selektiv körning & mocking
- Sätt `LLM_PROVIDER=mock` samt `LLM_MOCK_RESPONSE='{"type":"note","trust":"own","tags":["topic/test"],"confidence":0.95}'` för deterministiska svar (se `.github/workflows/smoke.yml`).
- För att hoppa över långsamma classifier-tester, ändra `SKIP_CLASSIFIER_TESTS=0` lokalt via env (default `1` i `tests/agents/test_classifier.py:3`).
- ASR kan mockas genom att patcha `app.media.transcribe.WhisperModel` i tester; se `tests/test_transcribe_smoke.py`.

## Artefakter
- `tmp/index-outbox.jsonl` – skrivs av CLI/ASR-tester. Rensa mellan körningar om determinism krävs.
- `logs/*.jsonl` – JSON-spanloggar som används av `jq`-recept i `docs/OBSERVABILITY.md`.
- `tmp/audio/` – yt-dlp cache. Testerna använder unika filnamn så parallella körningar fungerar; rensa via `rm -rf tmp/audio/*`.
<!-- SECTION:TESTING-MATRIX:END -->
