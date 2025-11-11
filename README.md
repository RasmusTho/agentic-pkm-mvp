# Agentic PKM — SoT v4.5A Baseline

This repository implements the SoT v4.5A baseline:
- Store abstraction (ObjectStore, VectorIndex, RelationIndex)
- Outbox + events
- Promotion Agent (idempotent state transitions; frontmatter Core-6)
- Deterministic CI in memory mode
- Optional rerank hook (inert by default)

## Quickstart (CI-like)

python -m pip install --upgrade pip
pip install -e .
pip install pytest
INDEX_PERSIST_PATH=tmp/index.jsonl STORE_BACKEND=memory LLM_PROVIDER=mock PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q -m "not pg"

## Environment Flags
| Variable               | Default  | Effect |
|------------------------|----------|--------|
| STORE_BACKEND          | memory   | Memory-first execution for CI and local runs. |
| LLM_PROVIDER           | mock     | Deterministic LLM for tests; use Ollama locally if desired. |
| PYTEST_DISABLE_PLUGIN_AUTOLOAD | 1 | Keeps pytest deterministic on CI. |
| INDEX_PERSIST_PATH     |          | When set, persists memory VectorIndex as JSONL. |
| INDEX_PERSIST_LOAD     | 0        | When 1, loads persisted JSONL at start. |
| AUDIT_LOG_PATH         |          | When set, writes JSONL audit lines to disk. |
| LLM_MAX_RETRIES        | 3        | Max retries for LLM calls. |
| LLM_BASE_DELAY         | 0.1      | Base delay for bounded backoff. |
| RERANK_ENABLE          |          | Enable optional rerank when set to 1/true/on. |
| RERANK_PROVIDER        | none     | Selects reranker: none|mock_ce. |
| RERANK_TOP_K           |          | Limit rerank to top K items. |

## Rerank (opt-in)

export RERANK_ENABLE=1
export RERANK_PROVIDER=mock_ce

The rerank hook is applied at the final candidate merge step, preserving default behavior when disabled.

## Status
- v4.4: Delivered
- v4.5A: Delivered (this baseline)
- v4.5B: Open — retrieval polish (rerank integration, diarization hooks, RelationIndex fitness)
- v4.6: Planned — retrieval quality and reasoning prep
