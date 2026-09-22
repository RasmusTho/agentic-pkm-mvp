State: Accepted target-state decision (owner request, 2026-09-22). Architecture and delivery authority only; the described router, transports, discovery, Product migration, host profile, and rollout are not shipped by this ADR.
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

Introduce a public ModelAccessRouter over the neutral llm_contract. It returns one exact resolved route, adapter/transport identity, declared capabilities, catalog snapshot reference, preflight status, execution host, and fallback provenance.

The facade is policy-agnostic. Product calls supply Product policy; Builder calls supply Builder policy. It may adapt Product LLMTaskIntent and retain LLMRoute as a compatibility projection during migration, but the neutral kernel does not import Product routers, settings, BuilderOps, credentials, provider sessions, or runtime stores. Builder does not import the Product LLM router or fabric.

### D2 — Codex CLI subscription transport is explicitly allowed for Product

Product may use the host-local authenticated Codex CLI on the designated Mac mini for declared agent/text routes. The CLI session and CODEX_HOME, executable path, and other host configuration remain host-local and outside Git. The adapter binds an exact model and reasoning effort before execution and invokes `codex exec --ephemeral` in a dedicated empty working directory, never in a Product workspace or repository. It must enforce `--sandbox read-only`, disable the CLI shell/execution features (`shell_tool` and `unified_exec`), ignore ambient user/project tool configuration, and pass only an explicit host-local environment allowlist needed for authentication. The adapter advertises no Product tool capability. If the installed CLI cannot prove and enforce this profile, Product routing fails closed before inference. Structured output is validated and CLI version/auth mode/host provenance is sanitized.

The Codex app-server model/list catalog may be used for read-only, account-scoped availability and capability discovery. Catalog discovery is not inference. Model list order alone is not release chronology and may not auto-promote a target. A provider-supplied release timestamp or explicit provider replacement/upgrade relation is required for automatic latest-compatible selection; otherwise the Product policy's pinned model remains authoritative.

The existing codex_subscription adapter name remains a compatibility alias for Model Inquiry. Model Inquiry keeps its current fallback_forbidden, single_target, and no-Ollama-fallback invariants; it does not inherit Product policy or Product fallback. Product's host-execution restrictions do not broaden or alter the existing Model Inquiry policy contract.

### D3 — Ollama fallback is preflight-only and intent-preserving

Product may preflight Codex CLI/Luna first and use configured Ollama only if the Codex CLI executable, authentication, or selected-model preflight fails before any model invocation. The Ollama route must satisfy the entire declared capability intent. No retry, provider switch, or second inference is permitted after execution begins.

Ollama may assert only capabilities exposed by its live model metadata and the adapter's tested behavior. In particular, it may not claim native tool calling unless the selected model and transport actually provide it. A route that requires a missing capability fails closed instead of falling back.

This exception changes Product route policy only. Builder routes keep their own fallback decisions, and Model Inquiry remains no-fallback.

### D4 — Dynamic catalogs are snapshots, not policy or credentials

Product and Builder retain separate registry scopes. Provider/capability allowlists, Product model descriptors, and host-local provider-discovery snapshots remain distinct data authorities while sharing a versioned neutral descriptor schema.

A catalog snapshot records exact model/provider/transport identity, provider-declared capabilities and reasoning levels, release or explicit replacement metadata when available, deprecation/sunset data, applicable limits/pricing, source, fetched time, freshness, and deterministic content hash. Default cache TTL is five minutes; maximum stale age is 24 hours. Snapshot refresh performs no model call.

Per request the owning policy filters the current snapshot by channel, permitted transport, capability tier, and required capabilities. It may select the newest compatible target only when the source provides verifier-friendly recency ordering. A stale, unavailable, or unordered catalog does not promote a model; policy keeps an explicitly pinned target or fails closed. Snapshot hash and exact model ID are bound to route and receipt.

Catalog discovery for OpenAI and Anthropic API endpoints may use only already-authorized, already-configured provider credentials. This ADR does not provision credentials, create a new API key, enable metered inference, or permit a catalog credential value to enter an intent, snapshot, log, or receipt. When no authorized credential exists, that API catalog source remains unavailable and the route stays pinned or unavailable. Codex app-server discovery uses the existing host-local Codex login; Ollama discovery uses its configured local endpoint.

### D5 — Adapter registry and provenance

The shared adapter registry supports codex_cli, ollama_http, openai_api, anthropic_api, and mock. Provider-neutral resolution chooses a transport only from owner policy and provider declarations. Every route/receipt names exact provider, model, transport, snapshot hash/reference, requested and resolved capabilities, preflight result, execution host, and any preflight fallback reason. It never includes credential values, endpoint secrets, CODEX_HOME, or CLI environment contents.

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
2. Implement contract, facade, adapter, catalog, and Product migration slices in dependency order with fake-provider tests.
3. Keep host paths and sessions out of Git; do not download Ollama models or provision API credentials as part of these slices.
4. Produce a Mac mini acceptance receipt covering Codex version/auth, Luna route, Ollama probe, compatible preflight fallback, and rejected tool-capability fallback.
5. Plan and execute dev → test → prod only through the release-channel skills and their operator-acknowledged gates. A config rollback restores the last pinned route; this ADR authorizes no deployment by itself.

## Related decisions and owner docs

- docs/adr/ADR-0063-shared-llm-contract-kernel.md
- docs/adr/ADR-0064-model-access-substrate.md
- docs/adr/ADR-0062-builderops-ecosystem-wide-enabling-system.md
- docs/LLM_ROUTING.md
- docs/MODEL_ACCESS_SUBSTRATE/README.md
- docs/BUILDEROPS_MODEL_INQUIRY/README.md
- docs/MODEL_ACCESS_ROUTER/README.md
