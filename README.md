# Workspace – Agentic AI (MVP)

## Quick start (local)
```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
export STORE_BACKEND=memory
export PYTHONPATH="$(pwd)"
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
export LLM_PROVIDER=ollama
export OLLAMA_MODEL=llama3.1:8b-instruct
```
### Run the CLI (file / URL / audio)

python -m app.cli normalize <PATH|URL>
python -m app.cli transcribe <YOUTUBE|AUDIOFILE>
python -m app.cli pipe <PATH|URL|AUDIO>

### Index outbox
Writes to `tmp/index-outbox.jsonl` with entries such as:
- kind: doc | transcript | note
- payload: { title, content, language, source_ref, segments? }

### Status
- 4.5 Ingest (done)
- 5.0 Transcription (done)
- 5.5 Retrieval (BM25 + embeddings) (done)
- 6.0 Agent loop (deterministic) (done)
- 6.5 Guardrails (asserts/timeout/cache) (done)
- 7.0 Observability (logs + lightweight view) (done)
- 7.5 Evaluation harness (done)
- 8.0 Fallback / policy (in progress)

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

See the docs/ directory for full reference material.
