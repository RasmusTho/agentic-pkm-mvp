---
uuid: 00000000-0000-0000-0000-000000000006
title: LLM Routing
origin: user
review_state: evergreen
trust: internal
---
## Task routing defaults
Choose a model per task. The compiler resolves the provider from the model registry, so users do not need to pick both.

## Chat
Used for normal ask, drafting, and short synthesis.

Selected model:
- `openai.chat.gpt_4_1_mini` for the primary route

Available options:
- `openai.chat.gpt_4_1_mini`: balanced cloud chat model for day-to-day work
- `openai.chat.gpt_4_1`: stronger cloud reasoning model when cost/latency are acceptable
- `ollama.chat.llama3_1_8b`: local fallback model for offline or low-cost work
- `mock.chat`: deterministic test-only route

## Reasoning
Used for planning and heavier multi-step synthesis.

Selected model:
- `openai.chat.gpt_4_1` for the primary route

Available options:
- `openai.chat.gpt_4_1`: strongest current default for reasoning-heavy tasks
- `openai.chat.gpt_4_1_mini`: cheaper cloud fallback if reasoning can be lighter
- `ollama.chat.llama3_1_8b`: local fallback model
- `mock.chat`: deterministic test-only route

## Embeddings
Used for indexing and retrieval. Switching this model may require an index rebuild, so the selected model is stricter than chat.

Selected model:
- `ollama.embed.nomic_embed_text` for the primary route

Available options:
- `ollama.embed.nomic_embed_text`: local embedding default, compatible with the current local RAG path
- `mock.embed`: deterministic CI-only embedding route; not a production replacement

## Eval
Follows the same model-first contract but still defaults to skip mode unless explicitly enabled elsewhere.

```yaml settings
default_chat:
  primary:
    model_id: openai.chat.gpt_4_1_mini
  fallback:
    mode: local
    model_id: ollama.chat.llama3_1_8b

default_reasoning:
  primary:
    model_id: openai.chat.gpt_4_1
  fallback:
    mode: local
    model_id: ollama.chat.llama3_1_8b

default_embedding:
  primary:
    model_id: ollama.embed.nomic_embed_text
    profile: default
  fallback:
    mode: never
  require_compatible_identity: true

tasks:
  qa:
    primary:
      model_id: openai.chat.gpt_4_1_mini
    fallback:
      mode: local
      model_id: ollama.chat.llama3_1_8b
  classify:
    primary:
      model_id: openai.chat.gpt_4_1_mini
    fallback:
      mode: local
      model_id: ollama.chat.llama3_1_8b
  plan:
    primary:
      model_id: openai.chat.gpt_4_1
    fallback:
      mode: local
      model_id: ollama.chat.llama3_1_8b
  embed:
    primary:
      model_id: ollama.embed.nomic_embed_text
      profile: default
    fallback:
      mode: never
    require_compatible_identity: true
```

## Notes
- Chat/reasoning tasks may choose a local fallback.
- Embeddings must keep a compatible identity. Endpoint repair is allowed; incompatible model fallback is not.

<!-- BEGIN:settings:reference -->
### Reference — LLM routing

| key | type | default | allowed | description |
|-----|------|---------|---------|-------------|
| `default_provider` | `str | None` | `` | `` | Default LLM provider override for router (vault-configurable). |
| `default_chat_model` | `str | None` | `` | `` | Default chat model override for routed LLM tasks. |
| `default_embed_model` | `str | None` | `` | `` | Default embedding model override for routed tasks. |
| `task_overrides` | `Dict` | `PydanticUndefined` | `` | Per task_kind provider/model overrides (future use). |
| `default_chat` | `TaskPolicy` | `PydanticUndefined` | `` | Default task policy for chat/completion work. |
| `default_reasoning` | `TaskPolicy` | `PydanticUndefined` | `` | Default task policy for reasoning-heavy work. |
| `default_embedding` | `TaskPolicy` | `PydanticUndefined` | `` | Default task policy for embeddings and retrieval/index identity. |
| `default_eval` | `TaskPolicy` | `PydanticUndefined` | `` | Default task policy for eval tooling. |
| `tasks` | `Dict` | `PydanticUndefined` | `` | Per task_kind routing policies. |
<!-- END:settings:reference -->
