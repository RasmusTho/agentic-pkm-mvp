State: SoT v4.10 Reality-MVP (current).
# LLM Integration

This doc aligns with `docs/SYSTEM_DESIGN_v4.10.md` for model choices and deployment topology.

## Provider abstraction
All calls go through `app.llm.adapter.generate(messages, reasoning=False)`. Configure via environment variables:

| Var | Meaning | Example |
|---|---|---|
| LLM_PROVIDER | mock, ollama, openai, deepseek | mock (CI/smoke) |
| LLM_MODEL | default chat/model for non-reasoning prompts | llama3.1:8b |
| LLM_REASONING_MODEL | reasoning/analysis model (when reasoning=True) | deepseek-r1:8b |
| LLM_TIMEOUT | chat timeout (seconds) | 120 |
| OLLAMA_HOST | base URL to local server | http://127.0.0.1:11434 |

`reasoning=True` selects `LLM_REASONING_MODEL`; otherwise `LLM_MODEL` is used.

## Model matrix (Reality-MVP)

| Use case | Component | Default (local Ollama) | Notes |
| --- | --- | --- | --- |
| ASK answering/drafting | ASK Agent | `LLM_MODEL=llama3.1:8b` | Switch via `LLM_PROVIDER`/`LLM_MODEL`; remote providers optional |
| Embeddings | Indexer | `EMBED_MODEL=nomic-embed-text` | Feeds VectorIndex |
| Rerank/self-check | ASK Agent | `RERANK_MODEL=llama3.1:8b` | Can reuse chat model |
| Panel suggestions | PanelAgent | `LLM_MODEL` | Lightweight prompts, panel text never indexed |
| Eval/QA mocks | Eval stack | `LLM_PROVIDER=mock` | Keeps CI deterministic; no external calls |

## Ollama (local)
Base URL `http://127.0.0.1:11434`. Load models with `ollama pull`. Run one model at a time to conserve RAM.

## Remote providers
Set `LLM_PROVIDER=openai` (or `deepseek`) and provide API keys (`OPENAI_API_KEY`, `DEEPSEEK_API_KEY`). Timeout defaults to 120 s for chat calls.

## Configuration and environment
- Control models via `LLM_PROVIDER`, `LLM_MODEL`, `LLM_REASONING_MODEL`, `EMBED_MODEL`, `RERANK_MODEL`.
- `OPENAI_BASE_URL`/`OPENAI_API_KEY` are only required for remote providers; Reality-MVP runs locally via Ollama by default.
- CI/mock: `LLM_PROVIDER=mock` + fixtures for deterministic runs.

## Prompting
Agents use short, task-bound prompts. Reasoning is logged only as output.
