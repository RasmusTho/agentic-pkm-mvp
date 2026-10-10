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
- `openai.chat.gpt_6_luna` for the primary route

Available options:
- `openai.chat.gpt_6_luna`: Luna through the Product Mac portal
- `mock.chat`: deterministic test-only route

Text routing does not fall back to another provider when the selected Luna route is unavailable.

## Reasoning
Used for planning and heavier multi-step synthesis.

Selected model:
- `openai.chat.gpt_6_luna` for the primary route

Available options:
- `openai.chat.gpt_6_luna`: Luna through the Product Mac portal
- `mock.chat`: deterministic test-only route

Planning does not fall back to another provider when the selected Luna route is unavailable.

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
    model_id: openai.chat.gpt_6_luna
  fallback:
    mode: never

default_reasoning:
  primary:
    model_id: openai.chat.gpt_6_luna
  fallback:
    mode: never

default_embedding:
  primary:
    model_id: ollama.embed.nomic_embed_text
    profile: default
  fallback:
    mode: never
  require_compatible_identity: true

```

## Notes
- Chat and planning use Luna through the Product Mac portal; no Ollama chat fallback is configured.
- Embeddings must keep a compatible identity. Endpoint repair is allowed; incompatible model fallback is not.
- Optional named Product chat profiles can be declared under profiles in the settings block. A clone selects one through llmRoutingProfile in its gitignored settings/local.md; profile targets use model-registry IDs and inherit the shared fallback policy.

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
| `profiles` | `Dict` | `PydanticUndefined` | `` | Named Product model-target profiles selected clone-locally by the vault-local llmRoutingProfile setting. Shared fallback policy is retained. |
<!-- END:settings:reference -->
