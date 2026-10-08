State: SoT v5.5 Reality-MVP baseline locked.
Doc role: Reference
Authority: Canonical routing and fabric contract for LLM chat and embedding access in the current runtime; operational provider configuration lives here, while broader provider usage lives in `docs/LLM.md`.
Temporal class: operational
Review cadence: event-driven
Source of truth: routing code, compiled Product settings, channel Compose, and acceptance receipts
Last reviewed: 2026-10-08
Last verified against: Issue #5820 Product gateway/profile tests (local ASGI and mocked provider); Issue #5624's bounded Luna/Codex CLI dev-chat acceptance. No live embedding-route or satellite-profile acceptance is claimed.

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
  The Mac portal's no-inference preflight must bind that exact transport; a different
  host transport is rejected before completion rather than silently substituted.
  Measured classification invocation and usage/cost evidence are defined in `docs/eval.md`.
- **Routes/Providers**: A route selects a provider + model. Providers are identified by string values
  (`mock`, `ollama`, `openai`, `deepseek`, etc.).
- **Deterministic routing**: If `determinism_required=True`, the router prefers `mock` over non-deterministic providers.
- **Task policy routing**: User-facing task policies live in `vault/@Settings/llm_routing.md` and compile to
  `runtime/settings/llm_routing.yaml`.
- **Model-first settings**: The settings note selects `model_id` values from the model registry. The compiler derives
  `provider` and `model` from that registry so users do not need to keep both in sync by hand.
- **Clone-local model profiles**: `llm_routing.md` may declare named profiles with registry-backed
  chat targets and embedding targets (`default_embedding` or `tasks.embed`). The compiler enforces
  the model kind. Each clone selects one profile with `llmRoutingProfile` in its gitignored
  `settings/local.md`; omit it or use `default` to retain the shared task policy. A work satellite
  can select `work` while another clone uses a different profile. Profile targets replace the
  primary chat/reasoning/eval or embedding model; shared fallback policy and capability/identity
  checks remain in force. Selecting another embedding model changes the requested embedding
  identity, so the existing index compatibility and governed rebuild/reconcile rules still apply.
  Builder Model Inquiry is not affected. Unknown profile names, unregistered model IDs, and
  chat/embedding kind mismatches fail closed. For example, declare
  `profiles.work.default_embedding.model_id` using an embedding ID from
  `docs/settings/models/registry.yaml`, then put `llmRoutingProfile: work` in that clone's local.md.
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

For Product chat, reasoning, eval, and embedding tasks, a non-default clone-local
`llmRoutingProfile` overrides the corresponding primary target after the shared task policy is
loaded. Profile definitions remain shared configuration; the selected profile name remains local to
each clone and is not committed.

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

The current shared Product defaults select Luna through Codex CLI for text tasks and
`nomic-embed-text` through Ollama for embeddings. Those are model/provider choices, not local
Product-side execution paths: every non-mock Product inference is sent through the Mac Product API
over the configured VLAN path, and the Mac host resolves the actual transport/harness. A clone may
select a different compatible registry-backed model through its local profile. Ollama is not a
required local service or health dependency when it is unselected; provider-neutral health reports
the selected logical `llm_access` capabilities.

Vault initialization seeds these shared Luna and Nomic defaults in `settings/llm_routing.md` only
when that file is absent. Reinitializing an existing vault preserves its owner-authored routing
policy. No Ollama chat fallback is configured for Luna chat and planning; existing failure handling
applies when the Mac route is unavailable.

Product evaluation uses the same Mac portal and host-owned provider credentials/endpoints; local
`EVAL_LLM_API_KEY`, `EVAL_LLM_BASE_URL`, `OPENAI_API_KEY`, and `OPENAI_BASE_URL` do not override
that authority. Measured classification evaluation additionally pins one registry model and the
`openai_api` transport, with no catalog promotion or transport fallback.

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
- Every non-mock Product chat/completion and embedding inference uses the logical Mac Product API over the configured executor/VLAN path. Product requests bind the selected provider/model and capability intent but do not choose the host transport, endpoint, or credentials. The host response binds the actual transport and catalog snapshot to the route. `mock` remains local for deterministic use.
- `app.model_access.adapter_factory.ModelAccessAdapterFactory` validates declared model/provider/adapter compatibility; its descriptors do not make Product callers select or invoke provider SDKs directly. The Mac host owns the provider transport and subscription/credential boundary.
- Clone-local Product profiles can select separate registry-backed chat and embedding models. Embedding inference uses `POST /v1/product/embed`; the Product client preserves its selected `EmbeddingIdentity`, checks the returned model/transport/dimension and catalog provenance, and does not retry after sending an embedding request. Switching embedding identity remains subject to the index compatibility/rebuild/reconcile gates.
- The bounded local Codex CLI executor remains the Model Inquiry compatibility bridge. Product code rejects local `codex_cli` execution; the Mac portal returns the actual host transport. Model Inquiry retains its separate single-target, fallback-forbidden policy.
- Chat, reasoning, eval, and embedding routes can each carry separate preferred model choices. A preflight-approved text fallback, if policy allows one, occurs before inference; a failure after inference starts is terminal and cannot cause another provider call.
- Product embeddings preserve the dimension and identity/reconcile rules in `docs/EMBEDDINGS.md`, but the Mac portal owns provider egress and credentials. The Product caller does not inspect a local Gemini key or invoke a provider SDK. Once `/v1/product/embed` has entered the HTTP transport, the outcome is terminal: no queue retry and no client-side provider fallback. Any future Product fallback must be selected and capability-preflighted by the Mac before its single inference dispatch; its returned provider/model/transport/snapshot provenance remains authoritative. A mixed-identity write, if the host later supports that posture, still requires the existing `index doctor` / `index reconcile` discipline.
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
`PREFLIGHT_TIMEOUT`, or `PATH_AUTHENTICATION_FAILED`. Malformed requests, route/capability mismatch,
and missing path configuration fail closed. Once a non-200 HTTP
status is received, a stalled, disconnected, or oversized error body preserves that status; only a
fully decoded explicit path-local error code can authorize another configured path. The active Ygg
profile has no second path, so VLAN failure is terminal. The VLAN ingress uses mutually
authenticated HTTPS to a host-local RFC1918 IPv4 or IPv6 unique-local address literal; DNS names
are rejected so a public endpoint cannot receive completion content. The executor backend remains
loopback-bound and does not rely on Tailscale-Serve headers or per-action capability claims.
After preflight, exactly one completion uses the selected path. An ambiguous completion cannot retry
over another path or switch providers. Provider/model fallback remains a separate explicit policy
decision.

This is repository code/configuration support, not persistent Product-route or release-channel
activation. Issue #5624's acceptance receipt verifies the bounded Ygg dev-host VLAN and Luna/Codex
CLI chat path only; it does not verify this change's embedding request path or a clone-selected
satellite model. Those live selections require their own host-level acceptance evidence. A PR merge
does not change a deployed Product default. Optional generic multi-path adapters do not make
Tailscale a current Ygg dependency.

System health reports whether the configured workload's logical capabilities are available, not
whether an unselected provider is installed or reachable. Adapter readiness and declared
capabilities map into `checks.llm_access.capabilities`; only fresh `available` observations satisfy
a required capability. `checks.llm_access.transport_observation` separately reports configured
executor-path reachability; a successful pre-completion path fallback is `degraded` transport while
the same logical capability can remain available. The public `/api/health` response omits
model-access provider, model, transport, endpoint, and selected-path identity. Local CLI output
retains selected-route diagnostics in `checks.llm_router` and `checks.llm_providers` for operator
troubleshooting. Each selected non-mock Product text route is checked through the Product
model-access facade using no-inference preflight; health does not inspect local OpenAI credentials
or a local Ollama endpoint. Ollama remains optional, and embedding-index identity health is reported
separately. Health remains a no-inference observer: it checks the configured route and does not
select a model or authorize provider/model fallback. `docs/HEALTH.md` and
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

- Canvas intent classification has repository support for the bounded Product MARR judgment
  operation (`IntentClassifierCognition.classify` -> `CodexRemoteTransport.judge_product_intent`).
  Only `intent_text` crosses this boundary: at most 2,000 UTF-8 bytes and 4 KiB serialized request.
  No current body, title, vault path or prior turn is sent; undeclared fields are rejected.
  Product's server-owned TypeSafe profile is independent of clone-local `llmRoutingProfile` and
  generic chat/reasoning/eval defaults. The SDK pin remains separate from the model release.
- Typed intent selection requires confidence and selected-choice probability of at least 0.8;
  governance also requires a non-unknown action meeting both floors. Contradictory actions,
  invalid responses and unavailable/uncertain judgments remain `UNKNOWN` with read-only re-ask.
  This floor has deterministic boundary proof, not a live semantic-calibration claim. Existing
  confirmation, APPLY and WriteGuard remain required; judgments grant no execution authority.
- This is dormant repository support: the normal MARR operation stays unavailable pending the
  separate Product dev acceptance on #5764. No live call, installation or test/prod activation
  is attested by fake-backed tests. The [actual-consumer one-call plan](TYPESAFE_SYSTEM_ONE/MIGRATE_PRODUCT_INTENT_CLASSIFIER.md#development-acceptance-gate)
  owns its invocation and redacted receipt. There is no retry or completion fallback after send.
- The existing opt-in OpenAI classification evaluator remains an explicitly identified legacy
  completion comparator with its original exact model and billing gates. Offline authored
  fixtures exercise the typed Product mapper; neither path attests a live TypeSafe judgment.

- Task-aware routing is implemented for the current task classes through the compiled settings file.
- Generic chat/reasoning fallback can remain local or mock when the task policy allows it.
- Embeddings are stricter: if the configured provider/model implies a different identity, startup must fail or require rebuild instead of silently degrading. The one sanctioned exception is the **dimension-matched (768/L2)** Gemini fallback per `docs/adr/ADR-0023-embedding-egress-gemini-fallback.md`; its write is mixed-identity (carries the Gemini identity) and reconcilable, the query path uses the primary identity, and a mixed-identity index triggers `index reconcile`, not silent degradation (`docs/EMBEDDING_RELIABILITY/README.md` CTI-1/2/3).
- Multi-provider load balancing and rate limit handling are out of scope for the current fabric. The Gemini embedding fallback above is a single dimension-matched reliability fallback, not load balancing.
- **ADR-0067 Product portal implementation:** Issue #5821 supplies the real Product embedding API and Issue #5820 routes non-mock Product chat and embedding calls through the Mac portal, with clone-local registry-backed profile selection across both model kinds. These repository tests use a real in-process ASGI boundary with mocked provider I/O; they do not attest live host configuration, provider access, deployment, or a changed channel default. Keep the existing bounded live chat receipt and any future embedding/satellite acceptance evidence distinct.
