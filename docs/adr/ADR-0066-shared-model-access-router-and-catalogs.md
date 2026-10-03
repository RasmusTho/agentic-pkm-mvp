State: Accepted target-state decision (owner request, 2026-09-22; D2 and D3 amended by owner direction on 2026-10-02). Architecture and delivery authority only; the described router, transports, discovery, Product migration, host profile, and rollout are not shipped by this ADR.
Doc role: Decision record (ADR)
Authority: Extends ADR-0063 and ADR-0064 for shared routing contracts, Codex CLI subscription access from Product, configurable network-path selection, and provider-neutral capability health. Does not merge Product and Builder policy, credential, registry, receipt, or execution authority.
Owner: Architecture spine / LLM boundary
Temporal class: Durable architecture decision; supersede through a later ADR.
Source of truth: This ADR plus the [capability specification](../MODEL_ACCESS_ROUTER/README.md). Current shipped behavior remains owned by docs/LLM_ROUTING.md, docs/LLM.md, and the Model Inquiry owner docs until acceptance.

# ADR-0066: Shared model-access facade with separate policy authorities and governed catalog discovery

**Date:** 2026-09-22
**Status:** Accepted target state (owner-directed 2026-09-22; amended 2026-09-27 and 2026-10-02)

## Context

ADR-0063 established a neutral LLM contract kernel while retaining separate Product and Builder execution and policy authorities. ADR-0064 added model access resolution, provider credentials, and the narrowly sanctioned subscription-backed Model Inquiry path; it intentionally left Product on its existing router and did not authorize Model Inquiry credentials or fallback to leak into Product.

The repository now has a Product LLM router/fabric, a Builder model-access resolver and adapter path, and a Codex CLI bridge used by Model Inquiry. The accepted delivery target needs a common route contract and adapter registry without turning Product policy into Builder policy or making a shared catalog an authority over credentials.

## Decision

### D1 — One neutral public facade, separate policy resolvers

Introduce a public ModelAccessRouter over the neutral llm_contract. It returns one exact resolved route, adapter/transport identity, declared capabilities, catalog snapshot reference, preflight status, logical execution-host and caller profiles, execution-boundary/authentication scheme, trusted-instruction mapping, and fallback provenance. It records logical profile references rather than concrete hostnames, endpoint URLs, or raw Tailscale identity/capability claims.

The facade is policy-agnostic. Product calls supply Product policy; Builder calls supply Builder policy. It may adapt Product LLMTaskIntent and retain LLMRoute as a compatibility projection during migration, but the neutral kernel does not import Product routers, settings, BuilderOps, credentials, provider sessions, or runtime stores. Builder does not import the Product LLM router or fabric.

The neutral request distinguishes a trusted instruction channel from a literal system-role requirement. A transport mapping trusted instructions to `developer_instructions` may satisfy only the former; a policy requiring the literal system role rejects that route.

Fallback provenance is returned with the owner-resolved target, not supplied as caller profile metadata. It retains the source and selected effective identity, source and selected transport, preflight cause, and the owner profile that authorized selection; the selected identity, transport, and policy authority must match the route, and a selected fallback is visibly degraded with a closed reason code. The facade records this evidence but does not choose a fallback. Adapter descriptors declare their supported capability envelope; the facade rejects resolved capability claims outside it, and `adapter_attestation` provenance references the selected adapter ID.

Source and selected transport IDs are allowed to be equal when an owner resolver selects another model over the same transport. The neutral contract records both values but imposes no transport-switch rule.

The neutral contract preserves the five `FallbackRequirement` meanings from ADR-0063: a used fallback is invalid for `fallback_forbidden` and `human_decision_required`; `fallback_same_identity` requires equal source and selected effective identities; compatible-identity and policy-selected alternatives remain decisions of the owner resolver. The facade does not implement a compatibility predicate or make that selection. `preflight_status` describes preflight for the selected route; a failed source preflight that led to resolver-selected fallback remains separately represented by the fallback provenance until the selected target is checked.

This remains a target-state decision for provider execution and caller adoption. MARR-01 delivers only the neutral route/provenance contracts and policy-agnostic composition seam; Product and Builder keep their current runtime paths until their separately gated adapter and migration slices land.

### D2 — Product reaches the macOS Codex executor through configured network paths

The Product runtime remains on its designated Linux hosts. It does not start a Codex process on
those hosts and does not depend on SSH into the macOS host. Product Codex requests reach a
single-purpose executor on the designated macOS host; that executor invokes the host's
already-authenticated Codex CLI subscription session. Ygg Product VMs and the designated macOS executor share a
VLAN, so the current Ygg profile uses VLAN as its sole network path. Tailscale, Serve, and a second
path are not prerequisites for host acceptance or rollout. The designated Ygg development-host
acceptance is verified by the sanitized MARR-06 receipt in Issue #5624; persistent Product route
activation and release-channel rollout remain separate gates. The executor is not a Product API,
Product gateway, or general-purpose BuilderOps service.

The model route and network path are separate configuration dimensions. Product policy selects the
logical executor and exact model/capability intent; deployment configuration supplies an ordered
set of named path profiles. The current Ygg configuration contains only `ygg_vlan_primary`. The
generic path adapter may support additional profiles, including Tailscale, when a deployment
explicitly configures them; no such profile is active or required for Ygg. Each profile resolves its
endpoint and transport outside model policy and application code. Concrete addresses, machine
identities, and credentials remain host-local and are not committed. Path selection must not
silently change the model, provider, reasoning effort, or requested capability.

Each configured path must authenticate the caller and authorize the same Product channel and
operation-specific actions (`complete`, `preflight`, or `catalog`). The VLAN's presence on a private
segment is not caller authorization. The VLAN ingress uses its configured authenticated identity
mechanism and maps it to the common channel/action capability contract. If a deployment later
explicitly configures the optional Tailscale adapter, it uses a narrowly scoped Serve-forwarded
application-capability grant. Each configured ingress rejects missing, malformed, or wrong-channel/
action authorization. Ingress proxies may expose their configured private listeners, but the
executor backend remains bound exclusively to loopback. Public listeners are forbidden. Host-local
processes remain inside the executor host's trust boundary. The active VLAN profile, identity
mapping, service activation, and endpoint bindings are operator-owned host configuration and are
not checked into Git. If the configured path cannot establish authorization, the route fails closed;
no source-IP-only trust or unscoped shared bearer token is substituted.

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
path-authorized catalog operation. Catalog discovery is not inference. Model list order alone
is not release chronology and may not auto-promote a target. A provider-supplied release timestamp
or explicit provider replacement/upgrade relation is required for automatic latest-compatible
selection; otherwise the Product policy's pinned model remains authoritative.

The existing codex_subscription adapter name remains a compatibility alias for Model Inquiry. Model Inquiry keeps its current fallback_forbidden, single_target, and no-Ollama-fallback invariants; it does not inherit Product policy or Product fallback. Product's host-execution restrictions do not broaden or alter the existing Model Inquiry policy contract.

### D3 — Network-path failover is preflight-only and preserves the selected route

Before completion, the client may test explicitly configured network paths in order using
no-inference connectivity and route preflight. It may select another path only when one is
configured and the failure is typed and path-local, preserving the same executor, model, and
capability intent. The current Ygg profile contains one VLAN path, so it has no network-path
fallback. Path selection is transport provenance, not provider/model fallback. The Product
acceptance profile uses Luna through the Codex CLI; Tailscale and Ollama health, installation, model
download, or fallback are not prerequisites for this route. Provider or model fallback is a
separate owner policy and remains disabled unless explicitly configured and authorized.

Path unavailability, connect/preflight timeout, and failure of the path-specific authentication
mechanism may advance to the next configured profile before completion. A caller denied by the
common channel/action policy, a malformed request, or a missing route capability is not a path
outage and must fail closed without trying another path.

Once a completion request may have reached the executor, any timeout or lost response is an
indeterminate/started execution and terminal: no path retry, provider switch, or duplicate
completion is permitted. A path outage after that point is reported against the request; it cannot
authorize a second inference.

This path policy changes Product connectivity only. Builder routes keep their own path and fallback
decisions, and Model Inquiry remains single-target and fallback-forbidden.

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

### D5 — Adapter registry, capability health, and provenance

Model adapters describe how an executor supplies a model; network-path adapters describe how an
authorized Product client reaches that executor. The shared adapter registry keeps these axes
separate. Its existing model adapters include `codex_cli`, `ollama_http`, `openai_api`,
`anthropic_api`, `deepseek_api`, and `mock`; the legacy `codex_cli_tailscale` identifier remains a
compatibility alias while the path abstraction is introduced. Network profiles are named in
deployment configuration and resolve endpoint and authentication settings outside caller policy.
`codex_subscription` remains the Model Inquiry compatibility alias for its existing local bridge.

Health evaluates the configured workload's required logical capabilities through a provider-neutral
capability/preflight contract. Its stable health result reports capability identity and status,
without requiring or exposing a particular provider name. Adapter diagnostics may explain a failed
capability internally, but provider identity is not the health contract. Requested/resolved
capabilities are attested by the selected model adapter; path provenance is attested separately by
the selected network-path adapter.

Execution routes and receipts retain exact provider, model, adapter, selected path profile,
snapshot hash/reference, requested and resolved capabilities, preflight result, logical
execution-host profile, authorized caller profile, and any path-selection reason. They may record
configured auth-scheme and safe-profile/mapping references, but never raw identity/capability
claims, hostname, endpoint URL, credential values, endpoint secrets, CODEX_HOME, prompts, or CLI
environment. The public health projection omits provider and concrete path identity.

Capability failure, missing CLI, version mismatch, expired session, timeout, output/schema violation, and provider refusal remain distinguishable. Once inference starts, every such failure is terminal for that route.

### D6 — Product integration and embedding boundary

Product chat, reasoning, constrained completion, evaluation, and health route through the shared facade and adapter registry, while LLMRoute remains a compatibility view until all in-scope call sites are migrated. Product model IDs and transport membership come from declared registry/provider configuration plus validated snapshots, not new hard-coded model branches. Health reports which required capabilities are available through the configured workload, independently of provider selection; embedding identity and index compatibility remain separately reported by the embedding subsystem.

Embedding identity remains in its existing subsystem and is not routed through this chat/completion migration.

## Consequences

- Product can use the subscription-backed Luna route without provisioning a metered API key; this is a deliberate extension of ADR-0064's Model-Inquiry-only sanction.
- The common facade shares mechanics and provenance, not Product/Builder authority.
- Runtime discovery is available-account-aware only when its source is authorized. Dynamic discovery cannot imply API inference access.
- No latest-model selection is inferred from array position, model-name spelling, local pull time, or a stale snapshot.
- Configured network-path selection is visible and bounded; pre-completion path failover preserves the selected model route, and post-start failures never fan out into a second completion.
- Product health is capability-oriented and provider-neutral; model adapters may vary without changing the health contract.
- Owner docs may claim the new Product route as supported only after the capability acceptance receipt and the owner-doc promotion gate are satisfied.

## Delivery gates

1. Amend this ADR only through the normal docs-authoring/PR path and publish the linked capability specifications.
2. Implement contract, facade, local Codex executor, configured network-path adapters, catalog, capability-oriented health, and Product migration slices in dependency order with fake-provider tests.
3. Keep host paths and sessions out of Git; do not download Ollama models or provision API credentials as part of these slices.
4. Under the current owner authorization recorded on Issue #5624, produce a designated-host receipt for the current VLAN-only profile. It covers VLAN mTLS authorization, loopback-only executor backend, Codex version/auth in the interactive login session, Luna route, capability-oriented health, trusted-instruction channel mapping, and rejected tool-capability requests. The exact configured/selected path is `[ygg_vlan_primary]`; no Tailscale, Serve, or fallback evidence is required. Each distinct acceptance request requires a fresh no-inference catalog and exact-route preflight, is sent once, and is never replayed or automatically retried; no provider/path fallback occurs after dispatch.
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
