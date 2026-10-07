State: Target-state capability specification, created 2026-09-22 from accepted ADR-0066 and amended 2026-10-03 for the VLAN-only Ygg host profile, provider-neutral capability health, and distinct one-shot acceptance attempts. MARR-01–05, the MARR-08 completion API, generic MARR-09 path selection, MARR-10 provider-neutral capability health, and MARR-11 clone-local Product chat profiles are delivered. VLAN-only MARR-06 designated-host acceptance has a validator-accepted v3 receipt in Issue #5624; staged MARR-07 rollout remains pending. The owner-approved universal Product portal target is recorded in ADR-0067 and parent Issue #5819; its provider-egress and Product embedding/profile tasks remain undelivered. Parent validation Issue #5618 remains separate and open for its original Luna rollout gates.
Doc role: Capability specification
Authority: Defines the bounded delivery contract for the Model Access Router. ADR-0063, ADR-0064, ADR-0066, and ADR-0067 govern architecture decisions; current shipped behavior remains in the owner docs linked below.
Owner: Product LLM Routing / Architecture spine; Builder Model Inquiry for its isolated compatibility path
Temporal class: strategic
Review cadence: event-driven
Source of truth: ADR-0066/ADR-0067, implementation task Issues, implementation, and acceptance receipts
Last reviewed: 2026-10-07
Last verified against: Issue #5794 clone-local routing-profile tests, Issue #5772 dev/test Compose integration tests, the validator-accepted MARR-06 v3 receipt in Issue #5624, PR #5759, ADR-0066/ADR-0067, and the checked-in MARR task specifications.
Parent issue: #5618 (open, agent:blocked); validation hub, never a pickup task.

# Model Access Router

## Purpose

Deliver a thin Product API that hides the selected model harness behind one bounded completion call while Product remains the authority that selects the exact temporary route. Keep Product and Builder policy, registries, credentials, fallback decisions, and execution receipts separate. Builder Model Inquiry retains its current single-target, fallback-forbidden behavior.

## Current State and Boundary

- TSO-04 (#5768) adds repository support for the separate dev-only Builder `POST /v1/ckm-judgment`
  operation. Its authenticated ingress grant requires channel `builder` and action `ckm_judgment`;
  Product grants cannot use it. CKM owns its provider-free intent and caller credential references,
  while the server validates `config/model_access/builder_typesafe_profile.json` before resolving
  the MARR-owned dev provider key. Fixed candidate-only Choice requests are capped at 8 candidates,
  8 capabilities, 500 UTF-8 bytes per excerpt and 12 KiB total, including the actual SDK wire.
  Product retains its separate 4 KiB limit and profile/allowance. Builder defaults to disabled and
  requires its own parent #5764 dev acceptance; the repository proof uses fake HTTP only. See
  [TSO-04](../TYPESAFE_SYSTEM_ONE/MIGRATE_BUILDER_CKM_ASSOCIATION.md) for the actual-consumer plan.
- TSO-02 (#5766) adds repository support for the dev-only Product `POST /v1/judgment` operation and `CodexRemoteTransport.judge_product_intent`, with fixed canvas questions, a 2,000-byte intent-only state, and 4 KiB request ceiling. Product's server-owned validated profile pins the exact TypeSafe release independently of the SDK package; the response validates and preserves selected/returned provider/model identity. TSO-02 originally resolved the MARR-owned key through its Mac Keychain binding. TSO-07/#5808 supersede that provider-key source with the existing non-prod BWS project and reader identity; the MARR-only consumer binding and Keychain bootstrap token remain on the MARR server path. Product `judgment` authorization is required, SDK retries/body logging are disabled, and every post-dispatch outcome is terminal. The normal route stays unavailable pending separate Product dev acceptance on #5764; a separately authorized temporary `acceptance_once` process permits one actual-consumer synthetic call without activating that normal route. This adds no generic completion/default-model change, Builder authorization, live key read, installation or provider acceptance. See [TSO-02](../TYPESAFE_SYSTEM_ONE/ADD_TYPESAFE_TO_MAC_EXECUTOR.md) for profile/SDK update paths and the operator acceptance plan.
- Product routes chat/completion calls through app/components/llm/router.py, app/components/llm/fabric.py, and app/services/llm.py.
- Builder model access resolves independently through app/builderops/model_access_resolver.py and app/builderops/model_inquiry_adapters.py.
- llm_contract is the neutral, side-effect-free kernel. Builder may not import the Product router or fabric.
- MARR-01 adds neutral route/receipt provenance contracts and `app.model_access.router.ModelAccessRouter`, which composes a caller-supplied owner resolver/profile with a read-only adapter descriptor lookup. MARR-02 adds `app.model_access.adapter_factory.ModelAccessAdapterFactory`, driven by `docs/settings/models/adapters.yaml` and the provider census, plus the bounded `app.model_access.codex_cli.CodexCliExecutor`.
- MARR-08 (#5635) adds the bounded `POST /v1/complete` executor API and Product-side client. MARR-03 adds authenticated, no-inference `POST /v1/preflight` for safe remote fallback. MARR-04 adds authenticated, read-only `POST /v1/catalog`; it returns sanitized Codex account or local Ollama descriptors and a content hash, never a model response.
- MARR-05 moves Product chat, reasoning, reflection, constrained completion, evaluation, and health route inspection through the shared facade while retaining `LLMRoute` compatibility. The facade keeps settings as Product route authority, resolves latest-compatible Luna IDs only within an explicitly registered family, and binds the concrete model and snapshot hash. Builder and Model Inquiry continue to resolve independently.
- MARR-11 (#5794) lets shared routing settings declare registry-backed Product chat profiles and lets each clone select a profile through gitignored `settings/local.md`. It replaces only primary chat/reasoning/eval targets, preserves shared fallback policy, and does not change embeddings or Builder Model Inquiry.
- MARR-05 preserves caller output-token limits explicitly. The current Codex CLI executor rejects a per-call output-token-limit requirement during no-inference preflight; a policy-approved low-reasoning Ollama fallback may run only if its own preflight passes. Ollama receives the limit as `options.num_predict`. If fallback is not allowed or capable, the call fails before inference; after completion starts there is no retry or provider switch.
- Model Inquiry's `codex_subscription` remains a compatibility alias for the shared local Codex executor; its current single-target and no-fallback semantics do not change. Host activation still requires an exact-version no-tools profile outside Git.
- Embeddings remain in the embedding identity subsystem and are outside the chat/completion migration.
- Product runtime remains on Linux. The delivered Product client supports the executor API, and MARR-09 delivers generic configured path selection. The checked-in Ygg profile selects only `ygg_vlan_primary`; Tailscale is neither configured nor required for acceptance or rollout. The designated Mac profile, VLAN path, Luna route, and interactive Codex subscription session passed the MARR-06 dev-host acceptance in Issue #5624. This receipt does not activate a persistent Product route or release channel.
- The accepted target keeps the model route and network path independent. Deployment configuration supplies ordered logical path-profile references; the current Ygg profile resolves only the host-local VLAN endpoint. The generic path interface may support additional explicit profiles, but no Tailscale endpoint or Serve setup is a Ygg dependency.
- Each configured path must authenticate and authorize the same Product channel and operation-specific action. VLAN membership alone is not authorization. The executor backend remains loopback-bound behind configured ingress; public listeners are forbidden. Concrete endpoints and identity material remain outside Git.
- Product health reports required logical capability status through the provider-neutral MARR-10 contract and separately reports configured network-path reachability. The public `/api/health` projection omits model-access provider, model, transport, endpoint, and selected-path identity; local CLI diagnostics may retain selected-route detail. This code does not activate a host route or change the Product model default.
- The dev/test/prod Compose overlays support an optional host-local MARR path-reference env file and a read-only Codex client-identity mount for Product `api`, `worker`, and `watcher` only. The governed deploy wrapper validates the exact endpoint/file-path allowlist before lock/migration/state preparation, then exports those values explicitly; Compose never consumes the raw MARR file as a service `env_file`. Immediately before each Product-channel Compose invocation, the ordinary governed runtime env is copied into a private mode-0600 temporary snapshot and that stable snapshot is used as the service `env_file`, closing the path-swap window; cleanup occurs when Compose exits. Production pins the import-time `LLM_PROVIDER` default to `mock` and disables cross-task provider enforcement for those Product callers, so explicit task policy can select a different provider. The model-access file supplies network path references only; Product model selection remains in its owner-managed `llm_routing` settings. This binding support does not provision host identity or activate a persistent route. Base Compose and release-channel activation remain separate gates.
- The currently verified Product route is Luna through the Codex CLI for the designated dev-host chat/planning acceptance; embeddings still use the separate embedding identity subsystem. The owner-approved target is broader: the Mac mini mediates every registry-declared Product model capability, including embeddings, while Product settings select the model/profile per clone (ADR-0067). The current gateway does not yet serve every provider or embeddings; Issues #5819 and its MARR-12/MARR-13 tasks track that gap. This target does not prove that a production identity, task policy, embedding model, or release is active.
- MARR-06 separates offline validation of an already-sanitized receipt (#5694) from live host acceptance (#5624); only the latter can clear the host/network acceptance gate.
- No API credentials, host credentials, model downloads, or release-channel changes are part of the repository implementation slices. Live host/network activation requires its explicit operational gate.

## Accepted Universal Product Portal Target

ADR-0067 records the owner's 2026-10-07 decision: the Mac mini is the single model-access portal for
Product chat/completion and embeddings; shared settings declare compatible models/profiles, and
each Product clone or satellite selects its own profile locally. The Product router retains route
selection authority; the Mac API hides provider harnesses and resolves host-local provider
credentials. Product and Builder policies remain separate. The VLAN path is the active Ygg path;
Tailscale is not required, and Ollama is optional rather than a universal health prerequisite.

This is accepted target state, not shipped truth. MARR-12 adds provider adapters/catalog egress at
the Mac API. MARR-13 routes Product model kinds, including embeddings, through that API and extends
clone-local selection. The planned delivery order is server/API first, then Product integration, to
keep one stable request contract. Neither task alone can claim the portal complete: Product clients
send one exact selected route, the gateway performs one dispatch, and embedding identity/dimension
changes fail explicitly before index writes. Parent #5819 owns integrated acceptance and current-state
doc promotion; original Luna rollout gates remain under #5618.

Implementation task specifications:

- [MARR-12: Centralize Product provider egress on the Mac mini](CENTRALIZE_PROVIDER_EGRESS_ON_MAC_MINI.md)
- [MARR-13: Route Product chat and embeddings through the Mac portal](ROUTE_PRODUCT_CHAT_AND_EMBEDDINGS_THROUGH_MAC_PORTAL.md)

## Existing Backlog Reconciliation

- Issue #5177 remains the Builder System authority for execution-routing work: TCD capability tiers, Luna/Terra/Sol/Spark policy, scheduling, escalation, canary evidence, and its parent acceptance are not re-opened or replaced here.
- Its delivered Builder slices #5203 (Model Inquiry capability-resolution transport) and #5205 (Codex-only active worker carrier) remain delivered. MARR reuses the existing Model Inquiry bridge and compatibility alias; it does not create a parallel Builder route or duplicate those Issues.
- MARR adds the neutral facade/profile seam and later Product runtime integration that #5177 explicitly excludes. Any Builder adoption is limited to an explicit Builder profile/conformance path; the existing Builder execution policy and scheduler continue to own their decisions.
- The independent Builder owner-platform parent #5399 remains outside this capability.

## Capability Contract

The accepted target request flow is:

Product reads or refreshes a bounded catalog snapshot → Product policy selects the exact logical model route and required capabilities → Product client resolves the current Ygg VLAN-only profile (`ygg_vlan_primary`) → the VLAN ingress authenticates the caller and authorizes the Product channel/action → a no-inference `POST /v1/preflight` verifies that same route → each distinct completion request is preceded by a fresh preflight and sends exactly one `POST /v1/complete` → one selected model adapter executes the completion → the result and internal receipt retain route and path provenance.

Builder continues through its own resolver/profile and adapters. The shared facade does not make
Product and Builder share policy or credentials.

The shared facade remains policy-agnostic: Product resolves the route, and the executor API neither picks a model nor joins Product and Builder authority. Completion requests and responses carry exact provider, model, and transport identity. Preflight carries only that route and capability intent; it returns readiness or a sanitized typed failure and performs no inference. Catalog discovery likewise performs no inference; latest-compatible selection is a pure Product-side operation over a snapshot and caller-supplied policy allowlist.

The completion/catalog service exposes `POST /v1/complete`, `POST /v1/preflight`, and
`POST /v1/catalog`. Its additional bounded System One operations are Product `POST /v1/judgment`
and Builder `POST /v1/ckm-judgment`, each with a separate fixed payload, caller authorization and
server-owned profile. They add no completion fallback or model-selection authority to callers.
Completion supplies one declared provider/model/transport, optional reasoning
effort, output schema, and output-token limit, a capability intent, trusted instructions, and user
content as distinct fields. Preflight supplies only one declared provider/model/transport and
capability intent. Catalog
supplies only a declared `codex_cli` or `ollama_http` transport and returns a sanitized snapshot.
None accepts commands, argv, paths, arbitrary environment, tools, MCP servers, provider endpoints,
or credentials. Completion returns the exact route and result; preflight returns the exact route and
sanitized readiness; catalog returns the snapshot's provider, descriptors, source/fetch metadata,
freshness, and content hash.

The current executor API is exposed behind its configured authenticated ingress and remains
loopback-bound. The current Ygg profile contains only the authenticated VLAN path. The generic path
adapter can support explicitly configured additional transports, including Tailscale, but no such
profile or Serve setup is required for Ygg acceptance or rollout. Each configured path enforces the
same caller-owned channel and operation-specific authorization contract. Endpoint and identity material
remain host-local configuration.
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
3. Cross-host identity: every configured path authenticates a caller and authorizes the same Product channel/action contract. The current Ygg profile contains only VLAN. VLAN membership, source IP, user identity headers, or request-body claims alone are not authorization. An optional Tailscale adapter, if explicitly configured later, must forward only its scoped app-capability grant. The executor backend remains loopback-only; no public listener or unscoped shared bearer token is allowed.
4. Codex host isolation: Product Codex execution uses a dedicated empty cwd, read-only sandbox, ignored ambient user/project config, and an exact version-reviewed no-tools profile. It disables shell/execution and every other model-callable file, browser/computer, app, MCP, plugin, and agent capability. A new or unknown CLI tool/profile fails closed. Host authentication uses the existing interactive login session, never fresh non-interactive SSH.
5. Prompt-channel preservation: trusted Product system-instruction content and untrusted user content remain separate end-to-end; the CLI maps them only to its distinct developer-instructions and user-prompt channels. No flattening or concatenation. The route does not assert literal system-role equivalence.
6. Retry boundary: each completion sends one HTTP request. Any ambiguous completion result is terminal and does not retry the path or trigger a second provider call. Preflight is a distinct no-inference operation and may precede the single completion. Path failover preserves the exact logical executor, model, and capability intent.
7. Capability preservation and health: the selected adapter must satisfy the request. Product health reports the configured workload's required capability IDs and statuses through a provider-neutral contract; it does not require a particular provider to be configured. Unsupported capabilities fail before completion.
8. Catalog boundary: catalog responses are read-only, sanitized, and content-hash-bound. Only caller policy may accept a new descriptor; unordered, stale, deprecated, or capability-incomplete candidates cannot replace the pinned target. Model Inquiry never consumes the Product catalog.
9. Provider compatibility: existing declared DeepSeek Product routing remains supported through an explicit `deepseek_api` adapter and pinned registry descriptor unless a separate reviewed change retires it. This migration cannot silently remove an existing provider.
10. Partial Product migration: unmigrated Product callers continue through the legacy facade. Migrated callers go through one shared route and one adapter; no dual execution/shadow inference is permitted.
11. Host and rollout gates: missing VLAN profile, missing required authorization, executor/login, or failed acceptance leaves the parent blocked. There is no configured fallback prerequisite for the current Ygg profile. Ollama or Tailscale health, installation, model, Serve, and fallback are not prerequisites for Luna acceptance. No model download, API key creation, host credential change, or production deployment is used to make the receipt pass. Production remains behind the release-channel operator-acknowledgment gate.

## Implementation Tasks

1. [Establish shared route and provenance contracts](ESTABLISH_SHARED_ROUTE_AND_PROVENANCE_CONTRACTS.md) — MARR-01
2. [Build the adapter registry and local Codex CLI executor](BUILD_ADAPTER_REGISTRY_AND_CODEX_CLI_TRANSPORT.md) — MARR-02; depends on MARR-01
3. [Add the authenticated cross-host Codex executor API](ADD_TAILSCALE_CODEX_EXECUTOR_TRANSPORT.md) — MARR-08 / #5635; provides the bounded completion endpoint and client over a trusted private ingress. Tailscale Serve is optional; the current Ygg profile uses VLAN mTLS.
4. [Formalize Ollama and preflight-only fallback](FORMALIZE_OLLAMA_AND_PREFLIGHT_FALLBACK.md) — MARR-03; extends the base API with no-inference preflight and capability-preserving fallback policy
5. [Discover and select from fresh model catalogs](DISCOVER_FRESH_MODEL_CATALOGS.md) — MARR-04; adds bounded discovery/freshness and explicit policy-gated selection
6. [Migrate Product LLM callers to the shared facade](MIGRATE_PRODUCT_LLM_CALLERS.md) — MARR-05; depends on MARR-01–04 and MARR-08
7. [Configure executor network paths](CONFIGURE_EXECUTOR_NETWORK_PATHS.md) — MARR-09; provides generic path configuration and no-inference failover independently of model/provider selection; the active Ygg profile is VLAN-only
8. [Report provider-neutral capability health](REPORT_CAPABILITY_HEALTH.md) — MARR-10; specifies health through logical capability contracts, independent of provider identity
9. [Prove VLAN-only macOS executor and Luna acceptance](PROVE_MAC_MINI_ACCEPTANCE.md) — MARR-06 / #5624; depends on MARR-01–05, MARR-08, MARR-09, and MARR-10. The live Issue now matches the VLAN-only v3 acceptance contract; every distinct acceptance request requires a fresh no-inference catalog/preflight and is sent once without replay, automatic retry, or provider/path fallback.
10. [Roll out through release channels with config rollback](ROLLOUT_WITH_CONFIG_ROLLBACK.md) — MARR-07; depends on MARR-06 and explicit release-channel operator acknowledgment
11. [Select Product model profiles per satellite](../LLM_ROUTING.md) — MARR-11 / #5794; shared profile definitions use registry IDs, while each clone selects its profile locally

## Capability Acceptance

This parent-level acceptance remains separate from merging individual MARR slices, including the MARR-08 thin API slice.

- [ ] MARR-08 is verified by its slice tests and merged; this proves code exists, not live host activation.
- [ ] Product caller migration is delivered by MARR-05 through the shared facade; this does not activate the designated host or change the checked-in default route.
- [x] MARR-11 verifies clone-local Product profile selection and preserves shared fallback, embedding identity, and the isolated Builder Model Inquiry target.
- [ ] MARR-04 delivers read-only catalog discovery and latest-compatible selection primitives; MARR-05 separately adopts them in Product callers. Catalog refresh never changes MARR-08's one-shot completion behavior.
- [x] The authorized VLAN-only Mac executor acceptance is verified by the validator-accepted v3 receipt in Issue #5624; this proves the designated dev-host path, not persistent Product activation.
- [ ] MARR-09 retains generic multi-path selection tests, while the checked-in Ygg profile configures only VLAN and has no Tailscale dependency.
- [x] MARR-10 verifies health reports configured logical capability status separately from neutral network-path reachability and does not require an unselected provider.
- [x] The designated-host receipt in Issue #5624 proves Luna through Codex CLI over VLAN, provider-neutral capability health, refusal of unsupported capability intent before inference, and no retry after an ambiguous completion. Its configured path is exactly `[ygg_vlan_primary]`; no Tailscale or Ollama proof is required.
- [ ] The parent validation issue remains open until all child receipts, integrated host acceptance, authorized rollout evidence, and owner-doc reconciliation are complete.

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
