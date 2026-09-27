State: Target-state capability specification, created 2026-09-22 from accepted ADR-0066 and amended 2026-09-27 for VLAN-primary/Tailscale-fallback paths and provider-neutral capability health. MARR-01 through MARR-04, the base MARR-08 completion API, and the MARR-05 Product caller migration are delivered. Configured path selection, capability-oriented health, designated-host acceptance, and staged rollout remain unshipped. Parent validation Issue #5618 is open and blocked.
Doc role: Capability specification
Authority: Defines the bounded delivery contract for the Model Access Router. ADR-0063, ADR-0064, and ADR-0066 govern architecture decisions; current shipped behavior remains in the owner docs linked below.
Owner: Product LLM Routing / Architecture spine; Builder Model Inquiry for its isolated compatibility path
Temporal class: strategic
Review cadence: event-driven
Source of truth: ADR-0066, child Issues, implementation, and acceptance receipts
Last reviewed: 2026-09-27
Last verified against: ADR-0066 and the checked-in MARR task specifications; GitHub child-issue reconciliation remains pending.
Parent issue: #5618 (open, agent:blocked); validation hub, never a pickup task.

# Model Access Router

## Purpose

Deliver a thin Product API that hides the selected model harness behind one bounded completion call while Product remains the authority that selects the exact temporary route. Keep Product and Builder policy, registries, credentials, fallback decisions, and execution receipts separate. Builder Model Inquiry retains its current single-target, fallback-forbidden behavior.

## Current State and Boundary

- Product routes chat/completion calls through app/components/llm/router.py, app/components/llm/fabric.py, and app/services/llm.py.
- Builder model access resolves independently through app/builderops/model_access_resolver.py and app/builderops/model_inquiry_adapters.py.
- llm_contract is the neutral, side-effect-free kernel. Builder may not import the Product router or fabric.
- MARR-01 adds neutral route/receipt provenance contracts and `app.model_access.router.ModelAccessRouter`, which composes a caller-supplied owner resolver/profile with a read-only adapter descriptor lookup. MARR-02 adds `app.model_access.adapter_factory.ModelAccessAdapterFactory`, driven by `docs/settings/models/adapters.yaml` and the provider census, plus the bounded `app.model_access.codex_cli.CodexCliExecutor`.
- MARR-08 (#5635) adds the bounded `POST /v1/complete` executor API and Product-side client. MARR-03 adds authenticated, no-inference `POST /v1/preflight` for safe remote fallback. MARR-04 adds authenticated, read-only `POST /v1/catalog`; it returns sanitized Codex account or local Ollama descriptors and a content hash, never a model response.
- MARR-05 moves Product chat, reasoning, reflection, constrained completion, evaluation, and health route inspection through the shared facade while retaining `LLMRoute` compatibility. The facade keeps settings as Product route authority, resolves latest-compatible Luna IDs only within an explicitly registered family, and binds the concrete model and snapshot hash. Builder and Model Inquiry continue to resolve independently.
- MARR-05 preserves caller output-token limits explicitly. The current Codex CLI executor rejects a per-call output-token-limit requirement during no-inference preflight; a policy-approved low-reasoning Ollama fallback may run only if its own preflight passes. Ollama receives the limit as `options.num_predict`. If fallback is not allowed or capable, the call fails before inference; after completion starts there is no retry or provider switch.
- Model Inquiry's `codex_subscription` remains a compatibility alias for the shared local Codex executor; its current single-target and no-fallback semantics do not change. Host activation still requires an exact-version no-tools profile outside Git.
- Embeddings remain in the embedding identity subsystem and are outside the chat/completion migration.
- Product runtime remains on Linux. The delivered Product client supports the executor API, but the designated Mac profile, VLAN-first network-path selection, Tailscale fallback, and Codex subscription session have not been activated or accepted.
- The accepted target keeps the model route and network path independent. Deployment configuration supplies ordered logical path-profile references; host-local configuration resolves the VLAN endpoint and Tailscale Serve endpoint. Neither path may be hard-coded into Product model policy or source code.
- Both paths must authenticate and authorize the same Product channel and operation-specific action. VLAN membership alone is not authorization. The executor backend remains loopback-bound behind configured ingress; public listeners and Funnel are forbidden. Concrete endpoints and identity material remain outside Git.
- Health is intended to report required logical capability status without requiring or exposing a named LLM provider. The current implementation still reports selected-route/provider details and has not yet met that target.
- The Product target uses Luna through the Codex CLI. Ollama is not a prerequisite or default fallback for this route. Existing Ollama adapter/fallback support remains separate implementation capability and does not authorize its activation here.
- No API credentials, host credentials, model downloads, or release-channel changes are part of the repository implementation slices. Live host/network activation requires its explicit operational gate.

## Existing Backlog Reconciliation

- Issue #5177 remains the Builder System authority for execution-routing work: TCD capability tiers, Luna/Terra/Sol/Spark policy, scheduling, escalation, canary evidence, and its parent acceptance are not re-opened or replaced here.
- Its delivered Builder slices #5203 (Model Inquiry capability-resolution transport) and #5205 (Codex-only active worker carrier) remain delivered. MARR reuses the existing Model Inquiry bridge and compatibility alias; it does not create a parallel Builder route or duplicate those Issues.
- MARR adds the neutral facade/profile seam and later Product runtime integration that #5177 explicitly excludes. Any Builder adoption is limited to an explicit Builder profile/conformance path; the existing Builder execution policy and scheduler continue to own their decisions.
- The independent Builder owner-platform parent #5399 remains outside this capability.

## Capability Contract

The accepted target request flow is:

Product reads or refreshes a bounded catalog snapshot → Product policy selects the exact logical model route and required capabilities → Product client resolves configured network path profiles in order (`ygg_vlan_primary`, then `tailscale_fallback`) → the selected ingress authenticates the caller and authorizes the Product channel/action → a no-inference `POST /v1/preflight` verifies that same route → after successful preflight, Product sends exactly one `POST /v1/complete` → one selected model adapter executes the completion → the result and internal receipt retain route and path provenance.

Builder continues through its own resolver/profile and adapters. The shared facade does not make
Product and Builder share policy or credentials.

The shared facade remains policy-agnostic: Product resolves the route, and the executor API neither picks a model nor joins Product and Builder authority. Completion requests and responses carry exact provider, model, and transport identity. Preflight carries only that route and capability intent; it returns readiness or a sanitized typed failure and performs no inference. Catalog discovery likewise performs no inference; latest-compatible selection is a pure Product-side operation over a snapshot and caller-supplied policy allowlist.

The service exposes only three bounded operations: `POST /v1/complete`, `POST /v1/preflight`, and
`POST /v1/catalog`. Completion supplies one declared provider/model/transport, optional reasoning
effort, output schema, and output-token limit, a capability intent, trusted instructions, and user
content as distinct fields. Preflight supplies only one declared provider/model/transport and
capability intent. Catalog
supplies only a declared `codex_cli` or `ollama_http` transport and returns a sanitized snapshot.
None accepts commands, argv, paths, arbitrary environment, tools, MCP servers, provider endpoints,
or credentials. Completion returns the exact route and result; preflight returns the exact route and
sanitized readiness; catalog returns the snapshot's provider, descriptors, source/fetch metadata,
freshness, and content hash.

The current executor API is exposed behind its configured authenticated ingress and remains
loopback-bound. The target supports an ordered VLAN-primary profile and private Tailscale Serve
fallback profile. Both path adapters enforce the same Product channel and operation-specific
authorization contract; the Tailscale adapter uses the configured Serve-forwarded application
capability (Serve 1.92 or later). Endpoint and identity material remain host-local configuration.
The Codex CLI profile path, `CODEX_HOME`, and subscription session also remain host-local.

The completion endpoint dispatches exactly once to the named adapter and performs no fallback or
retry. Once a completion request is sent, an ambiguous timeout is terminal; the client must not
repeat it or switch provider. Product may perform separate no-inference preflight requests first,
then submit one completion to the explicitly selected target. Native-tool intent is rejected
because the current Codex and Ollama executor profiles declare no native tools.

Trusted instructions and user content remain separate end to end. Codex maps trusted instructions
to its existing `developer_instructions` channel, not a literal system role; Ollama uses its
explicit `system` message. A literal-system-role request fails on Codex.

## Catalog Discovery and Freshness Contract

MARR-04 supplies the catalog and selection primitives; MARR-05 adopts them in Product callers through the shared facade.
The executor does not choose a model, and Product cannot promote a descriptor merely because it
appears in a provider response. The caller's policy allowlist must accept the exact descriptor and
transport before the pure latest-compatible selector can use it.

- Catalog snapshots bind exact model IDs, transports, capabilities, reasoning efforts, lifecycle/limits where known, source, fetch time, freshness, and a deterministic content hash. Refresh at five minutes; fail closed past 24 hours.
- Codex `model/list` and Anthropic/OpenAI model-list discovery use source timestamps or explicit replacement metadata only. App-server/API list order is not chronology. Ollama `modified_at` is local pull metadata and never authorizes promotion. Missing or incomparable order retains the explicitly pinned target.
- Discovery is read-only and makes no model call or credential. Model Inquiry continues to use a pinned single target and never inherits Product catalog or fallback behavior.

## Cross-Task Invariants / Follow-up Boundaries

1. Policy ownership: the facade accepts Product or Builder policy explicitly. If the neutral contract lands before either profile mapper, existing route behavior stays unchanged; no default policy is guessed.
2. Model Inquiry isolation: the Codex alias continues to resolve exactly one target with fallback_forbidden. Product's Ollama fallback cannot enter Model Inquiry, including when shared adapter code is reused.
3. Cross-host identity: configured VLAN and Tailscale paths both authenticate a caller and authorize the same Product channel/action contract. VLAN membership, source IP, user identity headers, or request-body claims alone are not authorization. Tailscale Serve is private-only and forwards its scoped app-capability grant; the executor backend remains loopback-only. No public listener, Funnel, unscoped shared bearer token, or generic execution endpoint is allowed.
4. Codex host isolation: Product Codex execution uses a dedicated empty cwd, read-only sandbox, ignored ambient user/project config, and an exact version-reviewed no-tools profile. It disables shell/execution and every other model-callable file, browser/computer, app, MCP, plugin, and agent capability. A new or unknown CLI tool/profile fails closed. Host authentication uses the existing interactive login session, never fresh non-interactive SSH.
5. Prompt-channel preservation: trusted Product system-instruction content and untrusted user content remain separate end-to-end; the CLI maps them only to its distinct developer-instructions and user-prompt channels. No flattening or concatenation. The route does not assert literal system-role equivalence.
6. Retry boundary: each completion sends one HTTP request. Any ambiguous completion result is terminal and does not retry the path or trigger a second provider call. Preflight is a distinct no-inference operation and may precede the single completion. Path failover preserves the exact logical executor, model, and capability intent.
7. Capability preservation and health: the selected adapter must satisfy the request. Product health reports the configured workload's required capability IDs and statuses through a provider-neutral contract; it does not require a particular provider to be configured. Unsupported capabilities fail before completion.
8. Catalog boundary: catalog responses are read-only, sanitized, and content-hash-bound. Only caller policy may accept a new descriptor; unordered, stale, deprecated, or capability-incomplete candidates cannot replace the pinned target. Model Inquiry never consumes the Product catalog.
9. Provider compatibility: existing declared DeepSeek Product routing remains supported through an explicit `deepseek_api` adapter and pinned registry descriptor unless a separate reviewed change retires it. This migration cannot silently remove an existing provider.
10. Partial Product migration: unmigrated Product callers continue through the legacy facade. Migrated callers go through one shared route and one adapter; no dual execution/shadow inference is permitted.
11. Host and rollout gates: missing VLAN profile, unavailable configured fallback, missing required authorization, executor/login, or failed acceptance leaves the parent blocked. Ollama is not an acceptance prerequisite for Luna. No model download, API key creation, host credential change, or production deployment is used to make the receipt pass. Production remains behind the release-channel operator-acknowledgment gate.

## Implementation Tasks

1. [Establish shared route and provenance contracts](ESTABLISH_SHARED_ROUTE_AND_PROVENANCE_CONTRACTS.md) — MARR-01
2. [Build the adapter registry and local Codex CLI executor](BUILD_ADAPTER_REGISTRY_AND_CODEX_CLI_TRANSPORT.md) — MARR-02; depends on MARR-01
3. [Add the authenticated Tailscale executor transport](ADD_TAILSCALE_CODEX_EXECUTOR_TRANSPORT.md) — MARR-08 / #5635; base completion endpoint and client, with no fallback or catalog API in that slice
4. [Formalize Ollama and preflight-only fallback](FORMALIZE_OLLAMA_AND_PREFLIGHT_FALLBACK.md) — MARR-03; extends the base API with no-inference preflight and capability-preserving fallback policy
5. [Discover and select from fresh model catalogs](DISCOVER_FRESH_MODEL_CATALOGS.md) — MARR-04; adds bounded discovery/freshness and explicit policy-gated selection
6. [Migrate Product LLM callers to the shared facade](MIGRATE_PRODUCT_LLM_CALLERS.md) — MARR-05; depends on MARR-01–04 and MARR-08
7. [Configure VLAN-primary and Tailscale-fallback executor paths](CONFIGURE_EXECUTOR_NETWORK_PATHS.md) — MARR-09; specifies path configuration and no-inference failover independently of model/provider selection
8. [Report provider-neutral capability health](REPORT_CAPABILITY_HEALTH.md) — MARR-10; specifies health through logical capability contracts, independent of provider identity
9. [Prove configured Mac mini executor paths and Luna acceptance](PROVE_MAC_MINI_ACCEPTANCE.md) — MARR-06; depends on MARR-01–05, MARR-08, MARR-09, and MARR-10. Live Issue #5624 must be reconciled with the amended acceptance contract before pickup.
10. [Roll out through release channels with config rollback](ROLLOUT_WITH_CONFIG_ROLLBACK.md) — MARR-07; depends on MARR-06 and explicit release-channel operator acknowledgment

## Capability Acceptance

This parent-level acceptance remains separate from merging the MARR-08 thin API slice.

- [ ] MARR-08 is verified by its slice tests and merged; this proves code exists, not live host activation.
- [ ] Product caller migration is delivered by MARR-05 through the shared facade; this does not activate the designated host or change the checked-in default route.
- [ ] MARR-04 delivers read-only catalog discovery and latest-compatible selection primitives; MARR-05 separately adopts them in Product callers. Catalog refresh never changes MARR-08's one-shot completion behavior.
- [ ] A separate operator-owned host acceptance is required before claiming the Mac service or Tailscale Serve is live.
- [ ] MARR-09 verifies VLAN-first path selection and Tailscale fallback using the same route and channel/action authorization contract.
- [ ] MARR-10 verifies health reports only configured capability status and does not require provider-specific checks.
- [ ] The designated-host receipt proves Luna through Codex CLI over VLAN, Tailscale fallback only for typed recoverable path-local failures before completion, provider-neutral capability health, and no retry after an ambiguous completion. Common policy, request, route, configuration, and capability failures remain terminal. Ollama is not required.
- [ ] The parent validation issue remains open until its chosen broader acceptance scope is explicitly satisfied.

## Relationship to GitHub Issues

The parent feature issue is [#5618](https://github.com/RasmusTho/agentic-pkm-mvp/issues/5618), a blocked validation hub, not an implementation issue. Each task above maps to one dependency-ordered child Issue; child Issue numbers are written into task frontmatter as soon as filed. No child is pickup-ready until its dependencies and the specification PR are merged, its Verify targets resolve, and strict readiness validation passes.

## Out of Scope

- Sharing or collapsing Product and Builder policy, registry, credential, fallback, health, or receipt authority.
- Provisioning API keys, changing subscription/account settings, or enabling metered inference.
- Downloading or modifying models; provisioning credentials; or making live VLAN, Tailscale policy, Serve, LaunchAgent, or host-service changes from this specification PR.
- Model Inquiry fallback, cross-provider retry after inference starts, dual execution, or shadow inference.
- Embedding identity migration.
- Executing a production deployment directly from a code/specification PR.

## Related Docs

- docs/adr/ADR-0063-shared-llm-contract-kernel.md
- docs/adr/ADR-0064-model-access-substrate.md
- docs/adr/ADR-0066-shared-model-access-router-and-catalogs.md
- docs/LLM_ROUTING.md
- docs/MODEL_ACCESS_SUBSTRATE/README.md
- docs/BUILDEROPS_MODEL_INQUIRY/README.md
- docs/architecture/SBS_CURRENT_TO_TARGET_MAPPING.md
- docs/architecture/SBS_OPERATING_MODEL.md
