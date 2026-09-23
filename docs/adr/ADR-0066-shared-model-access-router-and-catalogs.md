State: Accepted target-state decision (owner request, 2026-09-22; D2 amended by owner-selected option 1 on 2026-09-23). Architecture and delivery authority only; the described router, transports, discovery, Product migration, host profile, and rollout are not shipped by this ADR.
Doc role: Decision record (ADR)
Authority: Extends ADR-0063 and ADR-0064 for shared routing contracts, Codex CLI subscription access from Product, and preflight-only provider fallback. Does not merge Product and Builder policy, credential, registry, receipt, or execution authority.
Owner: Architecture spine / LLM boundary
Temporal class: Durable architecture decision; supersede through a later ADR.
Source of truth: This ADR plus the [capability specification](../MODEL_ACCESS_ROUTER/README.md). Current shipped behavior remains owned by docs/LLM_ROUTING.md, docs/LLM.md, and the Model Inquiry owner docs until acceptance.

# ADR-0066: Shared model-access facade with separate policy authorities and governed catalog discovery

**Date:** 2026-09-22
**Status:** Accepted (owner-directed target state, 2026-09-22)

## Context

ADR-0063 established a neutral LLM contract kernel while retaining separate Product and Builder execution and policy authorities. ADR-0064 added model access resolution, provider credentials, and the narrowly sanctioned subscription-backed Model Inquiry path; it intentionally left Product on its existing router and did not authorize Model Inquiry credentials or fallback to leak into Product.

The repository now has a Product LLM router/fabric, a Builder model-access resolver and adapter path, and a Codex CLI bridge used by Model Inquiry. The accepted delivery target needs a common route contract and adapter registry without turning Product policy into Builder policy or making a shared catalog an authority over credentials.

## Decision

### D1 — One neutral public facade, separate policy resolvers

Introduce a public ModelAccessRouter over the neutral llm_contract. It returns one exact resolved route, adapter/transport identity, declared capabilities, catalog snapshot reference, preflight status, logical execution-host and caller profiles, execution-boundary/authentication scheme, trusted-instruction mapping, and fallback provenance. It records logical profile references rather than concrete hostnames, endpoint URLs, or raw Tailscale identity/capability claims.

The facade is policy-agnostic. Product calls supply Product policy; Builder calls supply Builder policy. It may adapt Product LLMTaskIntent and retain LLMRoute as a compatibility projection during migration, but the neutral kernel does not import Product routers, settings, BuilderOps, credentials, provider sessions, or runtime stores. Builder does not import the Product LLM router or fabric.

### D2 — Product reaches Codex CLI through a Tailscale-only macOS executor

The Product runtime remains on its designated Linux/Tailscale hosts. It does not start a Codex
process on those hosts and does not depend on SSH into the macOS host. Product Codex requests cross
the tailnet to a separate, single-purpose executor on the designated macOS host; that executor
invokes the host's already-authenticated Codex CLI subscription session. This is a deliberate
exception to the current Ollama-only host profile, and remains target state until the host and
tailnet acceptance gate is complete. It is not a Product API, Product gateway, or general-purpose
BuilderOps service.

The Product workload reaches the executor only over private Tailscale Serve HTTPS. Serve proxies to
a backend bound exclusively to loopback; Funnel, public listeners, and direct LAN listeners are
forbidden. Tailnet grants limit the destination and port to the executor and the source to the
authorized Product workload identities. Because Product callers may be tagged devices, authorization
uses a narrowly scoped Tailscale application-capability grant forwarded by Serve, not user identity
headers. The supported Serve version must include app-capability forwarding (currently documented
for Tailscale v1.92+); Serve strips caller-supplied capability headers and injects only the granted
capability selected for forwarding. The backend rejects a missing, malformed, or wrong-channel
capability. The backend must bind only to loopback behind Serve; host-local processes remain inside
the executor host's trust boundary and are not authenticated by this forwarded header. The tailnet
policy, tag identities, Serve activation, service process, and endpoint binding are operator-owned
host configuration and are not checked into Git. If this app-capability path is unavailable, the
route fails closed; no shared bearer token or public endpoint is substituted.

The executor exposes only bounded, versioned catalog, preflight, and model-execution operations. It
does not accept arbitrary argv, shell commands, workspace paths, files, MCP servers, or caller-chosen
environment. It binds one exact model and reasoning effort before execution, runs
`codex exec --ephemeral` from an isolated empty working directory, and validates bounded output. The
host service runs in the authenticated macOS user's active login session required by the existing
Codex Keychain session; a fresh non-interactive SSH process is not an accepted auth path. The exact
machine identity, endpoint, CLI session, CODEX_HOME, executable path, credentials, and environment
remain host-local and outside Git and route receipts.

The Codex CLI safe profile must disable every model-callable tool, including shell/execution,
browser/computer, MCP/apps/plugins, file or patch operations, and agent-spawn capabilities. A
read-only sandbox and empty working directory are additional controls, not substitutes for proving
that no tool can execute. The adapter uses only a version-reviewed configuration/profile; if the
installed CLI cannot prove that profile, Product routing fails closed before inference. Product's
trusted system-instruction content is transported separately from caller/user content: the adapter
maps the former only to Codex's separate `developer_instructions` message and the latter only to the
user prompt. It never concatenates them. This mapping preserves the trusted-versus-user channel
boundary, not a claim that the Codex developer role is literally a system role. A policy requiring a
literal system role must reject this Codex route. The route records a non-secret mapping/profile id
and declares `system_prompt_channel` only when this behavior is tested for the pinned CLI version.

The Codex app-server model/list catalog may be used for read-only, account-scoped availability and
capability discovery. The executor returns only a validated, secret-free snapshot over its
Tailscale-authorized catalog operation. Catalog discovery is not inference. Model list order alone
is not release chronology and may not auto-promote a target. A provider-supplied release timestamp
or explicit provider replacement/upgrade relation is required for automatic latest-compatible
selection; otherwise the Product policy's pinned model remains authoritative.

The existing codex_subscription adapter name remains a compatibility alias for Model Inquiry. Model Inquiry keeps its current fallback_forbidden, single_target, and no-Ollama-fallback invariants; it does not inherit Product policy or Product fallback. Product's host-execution restrictions do not broaden or alter the existing Model Inquiry policy contract.

### D3 — Ollama fallback is preflight-only and intent-preserving

Product may preflight the remote Codex executor/Luna route first and use configured Ollama only if
the executor is unreachable or its Tailscale authorization, CLI executable, authentication, or
selected-model preflight fails before any inference request is sent. The Ollama route must satisfy
the entire declared capability intent, including the trusted-instruction/user-message separation.
Once the execute request may have reached the executor, any timeout or lost response is an
indeterminate/started execution and terminal: no Ollama call, retry, or provider switch is permitted.

Ollama may assert only capabilities exposed by its live model metadata and the adapter's tested behavior. In particular, it may not claim native tool calling unless the selected model and transport actually provide it. A route that requires a missing capability fails closed instead of falling back.

This exception changes Product route policy only. Builder routes keep their own fallback decisions, and Model Inquiry remains no-fallback.

### D4 — Dynamic catalogs are snapshots, not policy or credentials

Product and Builder retain separate registry scopes. Provider/capability allowlists, Product model descriptors, and host-local provider-discovery snapshots remain distinct data authorities while sharing a versioned neutral descriptor schema.

A catalog snapshot records exact model/provider/transport identity, provider-declared capabilities and reasoning levels, release or explicit replacement metadata when available, deprecation/sunset data, applicable limits/pricing, source, fetched time, freshness, and deterministic content hash. Default cache TTL is five minutes; maximum stale age is 24 hours. Snapshot refresh performs no model call.

Per request the owning policy filters the current snapshot by channel, permitted transport, capability tier, and required capabilities. It may select the newest compatible target only when the source provides verifier-friendly recency ordering. A stale, unavailable, or unordered catalog does not promote a model; policy keeps an explicitly pinned target or fails closed. Snapshot hash and exact model ID are bound to route and receipt.

Catalog discovery for OpenAI and Anthropic API endpoints may use only already-authorized,
already-configured provider credentials. This ADR does not provision credentials, create a new API
key, enable metered inference, or permit a catalog credential value to enter an intent, snapshot,
log, or receipt. When no authorized credential exists, that API catalog source remains unavailable
and the route stays pinned or unavailable. Codex app-server discovery uses the existing host-local
Codex login and returns only a sanitized snapshot over the authenticated executor boundary; Ollama
discovery uses its configured endpoint. The existing Product DeepSeek provider remains supported
through its declared API transport and pinned model descriptor unless a separate reviewed change
retires it; this ADR does not implicitly remove existing provider routes.

### D5 — Adapter registry and provenance

The shared adapter registry supports `codex_cli_tailscale` (Product remote transport), the local
`codex_cli` executor, `ollama_http`, `openai_api`, `anthropic_api`, `deepseek_api`, and `mock`.
`codex_subscription` remains the Model Inquiry compatibility alias for its existing local bridge.
Provider-neutral resolution chooses a transport only from owner policy and provider declarations.
Every route/receipt names exact provider, model, transport, snapshot hash/reference, requested and
resolved capabilities, preflight result, logical execution-host profile, authorized caller profile,
and any preflight fallback reason. It may record the auth scheme (`tailscale_app_capability`) and
safe-profile/mapping reference, but never raw Tailscale identity/capability claims, hostname,
endpoint URL, credential values, endpoint secrets, CODEX_HOME, prompts, or CLI environment.

Capability failure, missing CLI, version mismatch, expired session, timeout, output/schema violation, and provider refusal remain distinguishable. Once inference starts, every such failure is terminal for that route.

### D6 — Product integration and embedding boundary

Product chat, reasoning, constrained completion, evaluation, and health route through the shared facade and adapter registry, while LLMRoute remains a compatibility view until all in-scope call sites are migrated. Product model IDs and transport membership come from declared registry/provider configuration plus validated snapshots, not new hard-coded model branches.

Embedding identity remains in its existing subsystem and is not routed through this chat/completion migration.

## Consequences

- Product can use the subscription-backed Luna route without provisioning a metered API key; this is a deliberate extension of ADR-0064's Model-Inquiry-only sanction.
- The common facade shares mechanics and provenance, not Product/Builder authority.
- Runtime discovery is available-account-aware only when its source is authorized. Dynamic discovery cannot imply API inference access.
- No latest-model selection is inferred from array position, model-name spelling, local pull time, or a stale snapshot.
- Preflight fallback is visible and bounded; post-start failures never fan out into a second provider call.
- Owner docs may claim the new Product route as supported only after the capability acceptance receipt and the owner-doc promotion gate are satisfied.

## Delivery gates

1. Amend this ADR only through the normal docs-authoring/PR path and publish the linked capability specifications.
2. Implement contract, facade, local Codex executor, authenticated Tailscale transport, catalog, and Product migration slices in dependency order with fake-provider tests.
3. Keep host paths and sessions out of Git; do not download Ollama models or provision API credentials as part of these slices.
4. Under a separately authorized host/tailnet operation, produce a designated-host acceptance receipt covering the Serve/app-capability grant, Product-to-executor reachability, loopback-only backend, Codex version/auth in the interactive login session, Luna route, Ollama probe, compatible preflight fallback, trusted-instruction channel mapping, and rejected tool-capability fallback.
5. Plan and execute dev → test → prod only through the release-channel skills and their operator-acknowledged gates. A config rollback restores the last pinned route; this ADR authorizes no deployment by itself.

## Related decisions and owner docs

- docs/adr/ADR-0063-shared-llm-contract-kernel.md
- docs/adr/ADR-0064-model-access-substrate.md
- docs/adr/ADR-0062-builderops-ecosystem-wide-enabling-system.md
- docs/LLM_ROUTING.md
- docs/MODEL_ACCESS_SUBSTRATE/README.md
- docs/BUILDEROPS_MODEL_INQUIRY/README.md
- docs/MODEL_ACCESS_ROUTER/README.md
- Tailscale Serve identity and app-capability forwarding: https://tailscale.com/docs/features/tailscale-serve
- Tailscale application capabilities: https://tailscale.com/docs/features/access-control/grants/grants-app-capabilities
- Codex CLI `developer_instructions` configuration source: https://github.com/openai/codex/blob/main/codex-rs/core/src/config/mod.rs
- Codex CLI `exec` flags and config overrides: https://github.com/openai/codex/blob/main/codex-rs/exec/src/cli.rs
