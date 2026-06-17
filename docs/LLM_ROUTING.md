State: SoT v5.5 Reality-MVP baseline locked.
Doc role: Reference
Authority: Canonical routing and fabric contract for LLM chat and embedding access in the current runtime; operational provider configuration lives here, while broader provider usage lives in `docs/LLM.md`.

# LLM Routing Contract (Router + Fabric)

This document defines the canonical LLM access layer for chat/completions and embeddings.
The router chooses a route (provider/model/mode), and the fabric is the only allowed entrypoint
for high-level modules to talk to LLMs.

Related docs:
- `docs/LLM.md` for provider setup, environment configuration, and operational scenarios
- `docs/SETTINGS.md` for the broader settings/registry model
- `docs/HEALTH.md` for route/provider visibility in health output

## Concepts

- **Router**: Deterministic route selector. Produces `LLMRoute {provider, model, mode, reason, degraded}`
  from `LLMTaskIntent`. It is deterministic and settings-aware.
- **Fabric**: Runtime entrypoint that binds a route to an actual client. It exposes:
  - `get_chat_client(LLMTaskIntent)` → `ChatClient` with `.chat(...)`
  - `get_embeddings_client(LLMTaskIntent)` → embedding client with `.embed_text(...)`
- **Routes/Providers**: A route selects a provider + model. Providers are identified by string values
  (`mock`, `ollama`, `openai`, `deepseek`, etc.).
- **Deterministic routing**: If `determinism_required=True`, the router prefers `mock` over non-deterministic providers.
- **Task policy routing**: User-facing task policies live in `vault/@Settings/llm_routing.md` and compile to
  `runtime/settings/llm_routing.yaml`.
- **Model-first settings**: The settings note selects `model_id` values from the model registry. The compiler derives
  `provider` and `model` from that registry so users do not need to keep both in sync by hand.
- **Embedding identity protection**: embed tasks may auto-repair transport/endpoints, but must not silently switch
  to an incompatible embedding identity when `require_compatible_identity=true`.
- **Default route reporting**: The fabric exposes `describe_default_routes()` so health checks can report
  the active defaults and `describe_default_route_policies()` so health checks can report preferred versus effective routes.

## Configuration precedence

Routing is intentionally deterministic and single-source:

1. **Force overrides** — `LLM_FORCE_PROVIDER` / `LLM_FORCE_MODEL` win for debugging and explicit operator overrides.
2. **Compiled task policy settings** — `runtime/settings/llm_routing.yaml`, generated from `vault/@Settings/llm_routing.md`.
3. **Environment defaults** — env vars fill in provider/model defaults when the task policy leaves them blank.
4. **Built-in defaults** — used when no settings or env override is present.

Current state:
- Chat, reasoning, eval, and embedding routes can each carry separate preferred model choices.
- Embedding fallback is blocked unless the fallback preserves the resolved embedding identity.
- Endpoint repair is operational and separate from provider substitution.
- The router never emits a route whose `model` belongs to a different provider than the one that will execute the call. When `LLM_PROVIDER` is set it must run the call, so the resolved route uses a candidate (primary or fallback) that provider actually serves — e.g. an `ollama`-enforced chat task with a cloud-primary policy resolves to the local `ollama` fallback model, not the cloud model. When `LLM_PROVIDER_ENFORCE=1` and no candidate is served by the enforced provider, the router fails loud (`LLMRouteError`) rather than guessing a cross-provider route. The model swap is surfaced via `LLMRoute.reason` (`enforced-provider:<provider>`).

Tests: `tests/components/llm/test_router.py::test_router_respects_env_defaults`, `tests/components/llm/test_router_enforced_provider.py`

## Supported environment variables

Core routing:
- `LLM_PROVIDER` — default provider (`mock`, `ollama`, `openai`, `deepseek`).
- `LLM_MODEL` — default chat/completions model.
- `EMBED_MODEL` / `OLLAMA_EMBED_MODEL` — embedding model name for embed routes.
- `LLM_FORCE_PROVIDER` — hard override for router provider (all tasks).
- `LLM_FORCE_MODEL` — hard override for router model (all tasks).
- `LLM_PROVIDER_ENFORCE` — when truthy (`1`/`true`/`yes`/`on`), require `LLM_PROVIDER` to be set and bind every chat task to that provider; the router resolves to a model the provider serves or fails loud rather than emitting a cross-provider route.

Compiled routing settings:
- `vault/@Settings/llm_routing.md`
  - `default_chat`
  - `default_reasoning`
  - `default_embedding`
  - `default_eval`
  - `tasks.<task_kind>`
- Each task policy supports:
  - `primary.{model_id,provider,model,profile}`
  - `fallback.{mode,model_id,provider,model,profile}`
  - `require_compatible_identity`

Model registry:
- `docs/settings/models/registry.yaml`
- each `model_id` points to a descriptor with `kind`, `provider`, `model`, and notes
- routing compile requires chat tasks to resolve to `kind: chat` and embed tasks to resolve to `kind: embedding`

Provider-specific:
- `OLLAMA_HOST` / `OLLAMA_URL` — base URL for Ollama native APIs.
- `OPENAI_API_KEY`, `OPENAI_BASE` — OpenAI API auth + base URL.
- `DEEPSEEK_API_KEY`, `DEEPSEEK_BASE` — DeepSeek API auth + base URL.

Optional tuning:
- `LLM_TIMEOUT` — HTTP timeout (seconds).
- `LLM_TEMPERATURE` — chat temperature for Ollama/native calls.
- `LLM_MAX_TOKENS` — token budget used by the fabric caller.
- `LLM_MOCK_RESPONSE` — deterministic mock response payload for `mock` provider.

Tests: `tests/components/llm/test_router.py::test_router_respects_model_env_defaults`

### Examples

```bash
# Deterministic local run
export LLM_PROVIDER=mock
export LLM_MOCK_RESPONSE='{"type":"note","trust":"own","tags":["topic/test"],"confidence":0.95}'

# Ollama chat + embeddings
export LLM_PROVIDER=ollama
export LLM_MODEL=llama3.1:8b
export OLLAMA_HOST=http://127.0.0.1:11434
export OLLAMA_EMBED_MODEL=nomic-embed-text:latest

# Force a specific model for all LLM calls
export LLM_FORCE_PROVIDER=ollama
export LLM_FORCE_MODEL=llama3.1:8b-instruct
```

## How to debug routing

- **Health snapshot** (`/api/health`)
  - `checks.llm_router.selected_defaults` shows the router’s default routes.
  - `checks.llm_router.route_policies` shows preferred and effective routes per task class.
  - `checks.llm_task_routes.routes` shows whether each effective task route is actually configured and startup-safe.
  - `checks.embedding_index` shows whether the active embedding identity is compatible with the stored index or requires rebuild.
  - `checks.llm_providers.providers` lists provider health checks.
- **Alpha status output** (`scripts/alpha_status.py`)
  - Prints `llm routes` and `llm providers` summaries for human operators.

Tests: `tests/e2e/test_llm_routing_e2e.py::test_force_override_affects_ask_api`

## Current policy and future work

- Task-aware routing is implemented for the current task classes through the compiled settings file.
- Generic chat/reasoning fallback can remain local or mock when the task policy allows it.
- Embeddings are stricter: if the configured provider/model implies a different identity, startup must fail or require rebuild instead of silently degrading.
- Multi-provider load balancing and rate limit handling are out of scope for the current fabric.
