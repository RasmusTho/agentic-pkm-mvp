# Workspace – Agentisk AI (MVP)

## Snabbstart (lokal)
```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
export STORE_BACKEND=memory
export PYTHONPATH="$(pwd)"
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
export LLM_PROVIDER=ollama
export OLLAMA_MODEL=llama3.1:8b-instruct
```
Ingest (fil/URL/ljud)

python -m app.cli normalize <PATH|URL>
python -m app.cli transcribe <YOUTUBE|AUDIOFILE>
python -m app.cli pipe <PATH|URL|AUDIO>

Index-outbox

Skrivs till tmp/index-outbox.jsonl med poster av typen:
- kind: doc | transcript | note
- payload: { title, content, language, source_ref, segments? }

Status
- 4.5 Ingest (klar)
- 5.0 Transkribering (klar)
- 5.5 Retrieval (BM25+Emb) (klar)
- 6.0 Agentloop (deterministisk) (klar)
- 6.5 Gardrails (asserts/timeout/cache) (klar)
- 7.0 Observability (loggar + enkel vy) (klar)
- 7.5 Eval-harness (klar)
- 8.0 Fallback/Policy (pågående)

<!-- DOCS-LINKS:BEGIN -->
- [ARCHITECTURE](docs/ARCHITECTURE.md)
- [DIAGRAMS](docs/DIAGRAMS.md)
- [OBSERVABILITY](docs/OBSERVABILITY.md)
- [HEALTH](docs/HEALTH.md)
- [LLM_BACKENDS](docs/LLM_BACKENDS.md)
- [DEPENDENCIES](docs/DEPENDENCIES.md)
- [QUALITY](docs/QUALITY.md)
- [TESTING](docs/TESTING.md)
- [OPERATIONS](docs/OPERATIONS.md)
- [SECURITY](docs/SECURITY.md)
- [PRIVACY](docs/PRIVACY.md)
- [INVENTORY](docs/INVENTORY.md)
- [ROADMAP](docs/ROADMAP.md)
- [CHANGELOG](docs/CHANGELOG.md)
- [GLOSSARY](docs/GLOSSARY.md)
- [CLI](docs/CLI.md)
<!-- DOCS-LINKS:END -->

Se detaljer i docs/.
