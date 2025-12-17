State: SoT v4.10 (current; details may lag ARCHITECTURE).

# LLM Integration

This doc aligns with `docs/SYSTEM_DESIGN_v4.10.md` for model choices and deployment topology.

## Provider abstraction

All calls go through `app.llm.adapter.generate(messages, reasoning=False)`. Configure via environment variables:

| Var | Meaning | Example |
|---|---|---|
| LLM_PROVIDER | ollama, openai, azureopenai, anthropic, mock | ollama |
| LLM_MODEL | default chat model | llama3.1:8b |
| LLM_REASONING_MODEL | reasoning/analysis model | deepseek-r1:8b |

`reasoning=True` selects `LLM_REASONING_MODEL`.

## Model matrix (Reality-MVP)

| Use case | Component | Default (local Ollama) | Notes |
| --- | --- | --- | --- |
| ASK answering/drafting | ASK Agent | `LLM_MODEL=llama3.1:8b` | Switch via `LLM_PROVIDER`/`LLM_MODEL`; remote providers optional |
| Embeddings | Indexer | `EMBED_MODEL=nomic-embed-text` + `EMBED_DIM=1536` | Embedding vectors are computed in the indexer stage and are not carried in Outbox events |
| Rerank/self-check | ASK Agent | `RERANK_MODEL=llama3.1:8b` | Can reuse chat model |
| Panel suggestions | PanelAgent | `LLM_MODEL` | Lightweight prompts; panel text is not indexed |
| Eval/QA mocks | Eval stack | `LLM_PROVIDER=mock` | Keeps CI deterministic; no external calls |

## Ollama (local)

Base URL `http://127.0.0.1:11434`. Load models with `ollama pull`. Run one model at a time to conserve RAM.

## Remote providers

Set `LLM_PROVIDER=openai` and `OPENAI_API_KEY`. Timeout 120 s.

## Configuration and environment

- Control models via `LLM_PROVIDER`, `LLM_MODEL`, `LLM_REASONING_MODEL`, `EMBED_MODEL`, `RERANK_MODEL`.
- Embedding dimension is controlled via `EMBED_DIM` (default: 1536). The configured dimension must match the embedding provider output.
- `OPENAI_BASE_URL`/`OPENAI_API_KEY` are only required for remote providers; Reality-MVP runs locally via Ollama by default.
- CI/mock: `LLM_PROVIDER=mock` + fixtures for deterministic runs.

## Prompting

Agents use short, task-bound prompts. Reasoning is logged only as output.

## Logging

When `LOG_LEVEL=DEBUG`, `{provider, model, tokens_in, tokens_out, duration}` is logged to audit.
