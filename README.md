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

<!-- DOCS-LINKS:BEGIN -->
- [ARCHITECTURE](docs/ARCHITECTURE.md)
- [ROADMAP](docs/ROADMAP.md)
- [STATUS](docs/STATUS.md)
- [CHANGELOG](CHANGELOG.md)
- [CI](docs/CI.md)
- [TESTING](docs/TESTING.md)
<!-- DOCS-LINKS:END -->

## Environment Flags
| Flag | Default | Description |
| --- | --- | --- |
| `STORE_BACKEND` | `memory` | Selects memory vs pg stores (CI uses memory). |
| `LLM_PROVIDER` | `mock` | Deterministic LLM adapter for tests; set to `ollama` locally. |
| `RERANK_ENABLE` | unset | Enables rerank hook when truthy. |
| `RERANK_PROVIDER` | `none` | `none|mock_ce|ce_local|ce_http` provider matrix. |
| `RERANK_TOP_K` | unset | Maximum candidates to rerank (optional). |
| `DIARIZE_ENABLE` | unset | Enables diarization-aware ingestion pipeline. |
| `DIARIZE_PROVIDER` | `mock` | `none|mock|external` diarization providers. |
| `RERANK_HTTP_ENDPOINT` | unset | Required for `ce_http`; not contacted in CI. |
| `DIARIZE_HTTP_ENDPOINT` | unset | Required for `DIARIZE_PROVIDER=external`; stubbed in CI. |
| `PROMOTION_REQUIRE_RELATIONS` | `0` | When `1`, promotion blocks unless RelationIndex records ≥1 relation or an audited override is supplied. |
| `PROMOTION_ALLOW_ORPHANS` | unset | When truthy, bypasses orphan gate (requires override reason). |
| `PROMOTION_ORPHAN_OVERRIDE_REASON` | unset | Free-text reason logged/audited when overriding promotion relation gate. |
