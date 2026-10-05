State: SoT v5.5 Reality-MVP baseline locked.
Doc role: Reference
Authority: Canonical routing and fabric contract for LLM chat and embedding access in the current runtime; operational provider configuration lives here, while broader provider usage lives in `docs/LLM.md`.
Temporal class: operational
Review cadence: event-driven
Source of truth: routing code, compiled Product settings, channel Compose, and acceptance receipts
Last reviewed: 2026-10-04
Last verified against: Issue #5772 Compose integration tests and the MARR-06 acceptance receipt in Issue #5624.

# LLM Routing Contract (Router + Fabric)

This document defines the canonical LLM access layer for chat/completions and embeddings.
The router chooses a route (provider/model/mode), and the fabric is the only allowed entrypoint
for high-level modules to talk to LLMs.

Related docs:
- `docs/LLM.md` for provider setup, environment configuration, and operational scenarios
- `docs/SETTINGS.md` for the broader settings/registry model
- `docs/HEALTH.md` for current route health and the provider-neutral capability-health target

## Concepts

- **Router**: Deterministic route selector. Produces
  `LLMRoute {provider, model, mode, reason, degraded, embedding_identity}`
  from `LLMTaskIntent`. It is deterministic and settings-aware.
- **Fabric**: Runtime entrypoint that binds a route to an actual client. It exposes:
  - `get_chat_client(LLMTaskIntent)` → `ChatClient` with `.chat(...)`
  - `get_embeddings_client(LLMTaskIntent)` → embedding client with `.embed_text(...)`
- **Explicit evaluation**: `get_chat_client(..., model_id=..., transport_id=...)`
  admits an explicit transport only for an exact registered evaluation target and
  disables catalog promotion and fallback. A model descriptor's
  `explicit_eval_transports` adds admission only for that explicit eval request;
  ordinary `allowed_transports` and their existing refusal/selection stay unchanged.
  Measured classification invocation and usage/cost evidence are defined in `docs/eval.md`.
- **Routes/Providers**: A route selects a provider + model. Providers are identified by string values
  (`mock`, `ollama`, `openai`, `deepseek`, etc.).
- **Deterministic routing**: If `determinism_required=True`, the router prefers `mock` over non-deterministic providers.
- **Task policy routing**: User-facing task policies live in `vault/@Settings/llm_routing.md` and compile to
  `runtime/settings/llm_routing.yaml`.
- **Model-first settings**: The settings note selects `model_id` values from the model registry. The compiler derives
  `provider` and `model` from that registry so users do not need to keep both in sync by hand.
- **Embedding identity protection**: embed tasks may auto-repair transport/endpoints, but must not silently switch
  to an incompatible embedding identity when `require_compatible_identity=true`.
- **Default route reporting**: The fabric exposes `describe_default_routes()` and
  `describe_default_route_policies()` for current operator diagnostics. The accepted health target
  reports logical capability status; route/provider diagnostics remain behind the routing and
  adapter diagnostic surfaces.

## Configuration precedence

Routing is intentionally deterministic and single-source:

1. **Force overrides** — `LLM_FORCE_PROVIDER` / `LLM_FORCE_MODEL` win for debugging and explicit operator overrides.
2. **Compiled task policy settings** — `runtime/settings/llm_routing.yaml`, generated from `vault/@Settings/llm_routing.md`.
3. **Environment defaults** — env vars fill in provider/model defaults when the task policy leaves them blank.
4. **Built-in defaults** — used when no settings or env override is present.

For the dev, test, and prod channels, Compose forwards the governed `LLM_PROVIDER` value to only the
Product `api`, `worker`, and `watcher` callers, defaulting to `mock` when the channel has no
provider selection. Production pins that import-time default to `mock` and sets
`LLM_PROVIDER_ENFORCE=0` for those callers, allowing explicit `llm_routing` task policies to use
their configured provider. The value `mock` remains the fallback when a task has no explicit policy.
These overlays also accept the optional host-local
`/etc/yggdrasil/model-access/runtime.env` path-reference file and mount
`/etc/yggdrasil/model-access/codex-client` read-only for those callers only. The host-managed file
may contain only `MODEL_ACCESS_CODEX_VLAN_ENDPOINT` and the three CA/certificate/key path
references. The deploy wrapper fails closed on duplicate, malformed, or additional keys; it accepts
only an HTTPS endpoint without URL credentials and absolute file paths, then exports just those
four values. Compose does not read the raw file as a service `env_file`, so unrelated settings or
credentials cannot leak into Product containers. The file selects no model and activates no route.
The deploy entrypoint validates this separation before acquiring the channel lock or preparing
migrations/state. Immediately before a Product-channel Compose invocation, it snapshots the governed
runtime env into a private mode-0600 temporary file and passes that stable snapshot as the normal
service `env_file`; the snapshot is removed when Compose exits. This prevents a later path swap
from making Compose read the MARR file through the generic runtime-env layer.
If the client directory is absent, Compose may create an empty host directory so the mock-default
channel can still start; this does not provision an identity. Any selected Codex route still
requires successful no-inference preflight. Product model selection remains in the owner-managed
`vault/settings/llm_routing.md` and its compiled settings. Production code support does not prove
its host identity, live route policy, provider availability, or release is active.

The owner-approved Product target is Luna through the Codex CLI for chat/planning and Ollama for
embeddings. These capabilities have separate route policies and health requirements.

For embeddings, a blank compiled task target also permits the operator activation seam
`EMBED_PROFILE` to select one complete named identity (provider, model, dimension, and
normalization) before the generic `EMBED_MODEL` / `OLLAMA_EMBED_MODEL` environment fallback is
applied. The checked-in `profile: default` plus `ollama.embed.nomic_embed_text` compiled target is
the shipped no-activation placeholder, so it defers as one unit to embedding-profile resolution:
an explicit `EMBED_PROFILE` or an operator-selected `embedding_profiles.default_profile` replaces
the whole target, while the unchanged default profile still resolves to nomic. Any other explicit
compiled `primary.{model_id,provider,model,profile}` target remains
higher-precedence settings authority. This prevents a profile activation such as `bge-m3` from
being blocked by the placeholder or combined with the shipped `nomic-embed-text` model fallback
into a non-existent hybrid identity.

For a forced embedding route, the router resolves and attaches one exact
`embedding_identity` before returning. Implicit named, global, and default embedding profiles do
not alter that forced identity. Provider and model are canonicalized together: an untagged Ollama
model gains `:latest`, while an invalid forced provider degrades coherently to
`mock/mock-embedding`. The fabric consumes the attached identity without resolving it again.

Current state:
- The neutral route/provenance contract and policy-agnostic `ModelAccessRouter` seam are available. Product chat/completion callers continue to enter through the Product router and fabric, with the selected target resolved through the shared facade before adapter execution. The facade carries owner-resolver fallback lineage, preserves the `fallback_forbidden`, `human_decision_required`, and `fallback_same_identity` requirements, distinguishes source fallback cause from selected-target preflight status, and rejects resolved capability claims outside the selected adapter descriptor's declared support. Product route policy remains settings-owned; the facade does not create a separate model-selection authority.
- `app.model_access.adapter_factory.ModelAccessAdapterFactory` loads the strict transport declarations in `docs/settings/models/adapters.yaml` and binds an already-resolved provider/model to the provider census. It describes `codex_cli`, `ollama_http`, `openai_api`, `anthropic_api`, `deepseek_api`, and `mock`; this descriptor registration does not claim that Product's API/Ollama transports have migrated or that these adapters now select routes.
- The bounded local Codex CLI executor is available for the Model Inquiry compatibility bridge. It uses an isolated empty working directory, read-only sandbox, ephemeral execution, separate developer/user channels, output bounds, and a version-pinned no-tools profile. No designated-host profile or Product caller is activated by this change; missing or unrecognized host profile fails before inference. Model Inquiry still owns its separate single-target, fallback-forbidden policy.
- Chat, reasoning, eval, and embedding routes can each carry separate preferred model choices.
- Embedding fallback is blocked unless the fallback is **dimension-matched** and its mixed-identity write is bound to reconcile discipline. The sanctioned fallback is Ollama-primary with a Gemini `gemini-embedding-001` @ `output_dimensionality=768` (L2-renormalized) auto-fallback on primary failure; the write is **MIXED-IDENTITY / reconcilable** (carries the Gemini identity, reconciled via `index reconcile` once Ollama recovers), and the query path always uses the primary identity — per `docs/adr/ADR-0023-embedding-egress-gemini-fallback.md`, `docs/EMBEDDINGS.md :: Fallback rule`, and `docs/EMBEDDING_RELIABILITY/README.md` CTI-1/2/3. Generic fallback that changes dimension/normalization, or switches identity without that discipline, remains blocked.
- Endpoint repair is operational and separate from provider substitution.
- The router never emits a route whose `model` belongs to a different provider than the one that will execute the call. `LLM_PROVIDER` binds the executing provider on the enforced path **and** on the no-explicit-policy default path: the env provider is bound only when `LLM_PROVIDER_ENFORCE=1` (enforce) or when the task has no explicit policy (`router.py`: `if enforce or not has_explicit_task_policy`). For a task that *does* carry an explicit policy (e.g. `tasks.qa` with a cloud primary) and `LLM_PROVIDER` set **without** enforce, the router falls through to the policy primary — so `LLM_PROVIDER` does not necessarily run that call. To force an explicit-policy task onto the env provider, set `LLM_PROVIDER_ENFORCE=1`; then the resolved route uses a candidate (primary or fallback) that provider actually serves — e.g. an `ollama`-enforced chat task with a cloud-primary policy resolves to the local `ollama` fallback model, not the cloud model. When `LLM_PROVIDER_ENFORCE=1` and no candidate is served by the enforced provider, the router fails loud (`LLMRouteError`) rather than guessing a cross-provider route. The model swap is surfaced via `LLMRoute.reason` (`enforced-provider:<provider>`).

Tests: `tests/components/llm/test_router.py::test_router_respects_env_defaults`, `tests/components/llm/test_router_enforced_provider.py`

### Provider-neutral capability health and network paths (accepted target)

Model choice and cross-host network path are separate configuration layers. The Product client now
resolves `profile.codex_remote_host` through the configured profiles in
`config/model_access/executor_network_paths.yaml`. The active Ygg profile contains only
`ygg_vlan_primary`; no Tailscale endpoint, Serve setup, or fallback is required for acceptance or
rollout. Host-local environment-variable references are checked in; endpoint values, host
identities, CA bundles, and client certificates remain on the host. Provider/model policy does not
choose an endpoint or network adapter.

Before completion, the path router runs no-inference catalog and route-preflight requests. It may
advance to the next configured path only for `PATH_UNAVAILABLE`, `CONNECT_TIMEOUT`,
`PREFLIGHT_TIMEOUT`, or `PATH_AUTHENTICATION_FAILED`. Common Product authorization denial, malformed
requests, route/capability mismatch, and missing path configuration fail closed. Once a non-200 HTTP
status is received, a stalled, disconnected, or oversized error body preserves that status; only a
fully decoded explicit path-local error code can authorize another configured path. The active Ygg
profile has no second path, so VLAN failure is terminal. The VLAN ingress uses mutually
authenticated HTTPS to a host-local RFC1918 IPv4 or IPv6 unique-local address literal; DNS names
are rejected so a public endpoint cannot receive completion content. Its gateway maps the
authenticated caller to the Product channel/action capability contract, strips caller-supplied
capability headers, and injects the trusted claim. The executor backend remains loopback-bound.
After preflight, exactly one completion uses the selected path. An ambiguous completion cannot retry
over another path or switch providers. Provider/model fallback remains a separate explicit policy
decision.

This is code and configuration support, not persistent Product-route or release-channel activation.
The designated Ygg development-host VLAN settings, gateway authorization, Luna/Codex CLI route, and
sanitized acceptance receipt are verified by Issue #5624. That receipt proves the bounded dev-host
path only; release-channel rollout remains a separate operational gate. Optional generic multi-path
adapters do not make Tailscale a current Ygg dependency. Product policy can select Luna through the
Codex CLI, but a PR merge or host acceptance alone does not change the deployed Product default.

System health reports whether the configured workload's logical capabilities are available, not
whether an unselected provider is installed or reachable. Adapter readiness and declared
capabilities map into `checks.llm_access.capabilities`; only fresh `available` observations satisfy
a required capability. `checks.llm_access.transport_observation` separately reports configured
executor-path reachability; a successful pre-completion path fallback is `degraded` transport while
the same logical capability can remain available. The public `/api/health` response omits
model-access provider, model, transport, endpoint, and selected-path identity. Local CLI output
retains selected-route diagnostics in `checks.llm_router` and `checks.llm_providers` for operator
troubleshooting. Health remains a
no-inference observer: it checks the configured route and does not select a model or authorize
provider/model fallback. `docs/HEALTH.md` and
`docs/MODEL_ACCESS_ROUTER/REPORT_CAPABILITY_HEALTH.md` define the shipped contract. This code change
does not activate a host route or change the Product model default.

## Supported environment variables

Core routing:
- `LLM_PROVIDER` — default provider (`mock`, `ollama`, `openai`, `deepseek`).
- `LLM_MODEL` — default chat/completions model.
- `EMBED_PROFILE` — selects a registered complete embedding identity when the compiled embedding
  task target is blank or is the checked-in `profile: default`/nomic placeholder (for example
  `bge-m3` during the governed cutover).
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
  - `checks.llm_access.routes` shows no-inference preflight status for effective text-generation routes; embeddings remain separate.
  - `checks.llm_task_routes.routes` is a compatibility projection of `llm_access` during migration.
  - `checks.embedding_index` shows whether the active embedding identity is compatible with the stored index or requires rebuild.
  - `checks.llm_providers.providers` lists declared providers only; selected-route readiness is reported by `llm_access`.
- **Alpha status output** (`scripts/alpha_status.py`)
  - Prints `llm routes` and `llm providers` summaries for human operators.

Tests: `tests/e2e/test_llm_routing_e2e.py::test_force_override_affects_ask_api`

## Current policy and future work

- Task-aware routing is implemented for the current task classes through the compiled settings file.
- Generic chat/reasoning fallback can remain local or mock when the task policy allows it.
- Embeddings are stricter: if the configured provider/model implies a different identity, startup must fail or require rebuild instead of silently degrading. The one sanctioned exception is the **dimension-matched (768/L2)** Gemini fallback per `docs/adr/ADR-0023-embedding-egress-gemini-fallback.md`; its write is mixed-identity (carries the Gemini identity) and reconcilable, the query path uses the primary identity, and a mixed-identity index triggers `index reconcile`, not silent degradation (`docs/EMBEDDING_RELIABILITY/README.md` CTI-1/2/3).
- Multi-provider load balancing and rate limit handling are out of scope for the current fabric. The Gemini embedding fallback above is a single dimension-matched reliability fallback, not load balancing.
