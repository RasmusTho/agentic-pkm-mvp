State: Target-state capability specification, created 2026-09-22 from accepted ADR-0066 and amended 2026-09-23 for the selected Tailscale-only macOS executor. Parent validation Issue #5618 is open and blocked. No router, Product migration, remote executor, new provider auth, designated-host profile, or rollout is claimed as shipped.
Doc role: Capability specification
Authority: Defines the bounded delivery contract for the Model Access Router. ADR-0063, ADR-0064, and ADR-0066 govern architecture decisions; current shipped behavior remains in the owner docs linked below.
Owner: Product LLM Routing / Architecture spine; Builder Model Inquiry for its isolated compatibility path
Parent issue: #5618 (open, agent:blocked); validation hub, never a pickup task.

# Model Access Router

## Purpose

Deliver one provider-neutral model-access facade that can be used by Product and Builder while keeping their policy resolvers, registries, credential authorities, fallback decisions, execution receipts, and health views separate. Product gains a Codex CLI subscription route with a strictly preflight-only Ollama fallback; Builder Model Inquiry retains its current single-target, fallback-forbidden behavior.

## Current State and Boundary

- Product routes chat/completion calls through app/components/llm/router.py, app/components/llm/fabric.py, and app/services/llm.py.
- Builder model access resolves independently through app/builderops/model_access_resolver.py and app/builderops/model_inquiry_adapters.py.
- llm_contract is the neutral, side-effect-free kernel. Builder may not import the Product router or fabric.
- Model Inquiry's codex_subscription is a compatibility alias only; its current single_target and no-fallback semantics do not change.
- Embeddings remain in the embedding identity subsystem and are outside the chat/completion migration.
- Product currently runs on Linux/Tailscale hosts. The current-state environment and host owner docs still describe the macOS host as Ollama/model-serving only; the selected remote Codex executor is a future, unshipped exception that requires separate host and tailnet acceptance.
- Product acceptance requires a single-purpose Codex executor reachable only over Tailscale Serve HTTPS, an app-capability grant for authorized Product workloads, a loopback-only backend, a verified Codex safe profile in the authenticated interactive macOS login session, and a sanitized cross-host runtime receipt. The concrete machine identity and endpoint remain host-local and are not committed.
- No API credentials, Tailscale policy values, bearer secrets, host credentials, Ollama model downloads, or release-channel changes are part of the repository implementation slices. Live host/tailnet activation requires its explicit operational gate.

## Existing Backlog Reconciliation

- Issue #5177 remains the Builder System authority for execution-routing work: TCD capability tiers, Luna/Terra/Sol/Spark policy, scheduling, escalation, canary evidence, and its parent acceptance are not re-opened or replaced here.
- Its delivered Builder slices #5203 (Model Inquiry capability-resolution transport) and #5205 (Codex-only active worker carrier) remain delivered. MARR reuses the existing Model Inquiry bridge and compatibility alias; it does not create a parallel Builder route or duplicate those Issues.
- MARR adds the neutral facade/profile seam and Product runtime integration that #5177 explicitly excludes. Any Builder adoption is limited to an explicit Builder profile/conformance path; the existing Builder execution policy and scheduler continue to own their decisions.
- The independent Builder owner-platform parent #5399 remains outside this capability.

## Capability Contract

The target request flow is:

Product on Linux → Product policy → authorized catalog snapshot → exact route → Tailscale-only preflight → one remote Codex executor or Ollama adapter → result/receipt

Builder continues through its own resolver/profile and adapters. The shared facade does not make
Product and Builder share policy or credentials.

The shared facade accepts an owner profile and cannot select or merge that profile's policy. A route binds exact provider, model, transport, requested/resolved capabilities, catalog snapshot hash/reference, preflight status, execution host, and any pre-inference fallback cause.

Codex CLI/Luna is Product's primary target for configured general agent/text routes, executed by a
single-purpose service on the designated macOS host. The service is not a Product API/gateway and
does not execute on the Product host. Product may reach it only through Tailscale Serve HTTPS with
a narrowly granted application capability; the backend binds to loopback and has no public, LAN, or
Funnel listener. Request bodies cannot choose shell commands, CLI arguments, workspace paths,
environment, MCP servers, or unrestricted tools.

Ollama can be selected only if executor/Tailscale/CLI authentication/model preflight fails before an
inference request is sent, and only if it satisfies the complete intent. If an execute request may
have reached the Codex host, a timeout or lost response is terminal and cannot trigger a second
provider call. Missing native-tool support, trusted-instruction separation, reasoning level,
structured-output support, stale/unordered catalog data, and missing credentials fail closed or
retain an explicit pinned target as described by policy; they never silently weaken the intent.

The Codex adapter carries Product trusted system-instruction content separately from caller/user
content. It maps trusted content only to the CLI's separate `developer_instructions` message and
user content only to the prompt; the fields may never be concatenated. This preserves the
trusted-versus-user boundary but does not claim literal system-role equivalence. A request whose
policy requires a literal system role is not eligible for the Codex route. The exact mapping is
versioned, recorded without prompt contents, and tested; Ollama fallback must satisfy the same
channel requirement.

## Catalog and Freshness Policy

The neutral catalog descriptor is shared; Product model IDs/pricing/user-facing metadata and Builder provider census/policy remain separate scopes. Runtime CatalogSnapshot data is host-local derived state, not policy or credential authority.

- Refresh TTL: five minutes. Maximum stale age: 24 hours.
- Discovery performs no inference. A snapshot binds the exact source, fetch time, descriptor set, and deterministic hash.
- Per-request latest-compatible selection requires provider-supplied release/created metadata or an explicit provider replacement/upgrade relation. Array position, model-name spelling, and Ollama local pull time are not release evidence.
- Codex app-server model/list is account-scoped availability/capability discovery using the existing host-local subscription session. The executor returns only a validated, secret-free snapshot through its app-capability-gated catalog operation. If the source has no release timestamp or explicit upgrade edge for a profile, retain its pinned model; never infer chronology from list order.
- OpenAI and Anthropic API catalog adapters may use only an already authorized and already configured credential reference. This delivery does not provision credentials or enable metered API inference. Missing credentials make that source unavailable; tests use fake HTTP only.
- Ollama discovery inspects configured local models and declared metadata. It never claims native_tools unless both model metadata and the tested adapter establish that capability.

## Cross-Task Invariants / Interaction Safety

1. Policy ownership: the facade accepts Product or Builder policy explicitly. If the neutral contract lands before either profile mapper, existing route behavior stays unchanged; no default policy is guessed.
2. Model Inquiry isolation: the Codex alias continues to resolve exactly one target with fallback_forbidden. Product's Ollama fallback cannot enter Model Inquiry, including when shared adapter code is reused.
3. Cross-host identity: Tailscale Serve is private-only, its backend is loopback-only, and the backend authorizes the forwarded app-capability grant for the caller's Product channel. User identity headers or request-body claims are not substitutes. No public listener, Funnel, shared bearer token, or generic execution endpoint is allowed. The forwarded header authenticates tailnet permission only at the loopback backend; host-local processes remain within the executor host's trust boundary.
4. Codex host isolation: Product Codex execution uses a dedicated empty cwd, read-only sandbox, ignored ambient user/project config, and an exact version-reviewed no-tools profile. It disables shell/execution and every other model-callable file, browser/computer, app, MCP, plugin, and agent capability. A new or unknown CLI tool/profile fails closed. Host authentication uses the existing interactive login session, never fresh non-interactive SSH.
5. Prompt-channel preservation: trusted Product system-instruction content and untrusted user content remain separate end-to-end; the CLI maps them only to its distinct developer-instructions and user-prompt channels. No flattening or concatenation. The route does not assert literal system-role equivalence.
6. Preflight boundary: fallback is permitted only before an inference request can reach the executor. If execution may have started, including an ambiguous remote timeout, the route is terminal and no second provider receives the prompt.
7. Capability preservation: fallback is eligible only when the candidate satisfies every requested capability and instruction-channel requirement. Ollama lacking a capability such as native tools is a terminal preflight refusal, not a degraded route.
8. Catalog failure: failed refresh may use a snapshot only while it is within maximum stale age and the owning policy allows it. A stale, unordered, or unverifiable snapshot cannot auto-promote; with no pinned policy target, routing fails closed.
9. Provider compatibility: existing declared DeepSeek Product routing remains supported through an explicit `deepseek_api` adapter and pinned registry descriptor unless a separate reviewed change retires it. This migration cannot silently remove an existing provider.
10. Partial Product migration: unmigrated Product callers continue through the legacy facade. Migrated callers go through one shared route and one adapter; no dual execution/shadow inference is permitted.
11. Host and rollout gates: missing app-capability grant, executor/login, Ollama model, or failed acceptance leaves the parent blocked. No model download, API key creation, host credential change, or production deployment is used to make the receipt pass. Production remains behind the release-channel operator-acknowledgment gate.

## Implementation Tasks

1. [Establish shared route and provenance contracts](ESTABLISH_SHARED_ROUTE_AND_PROVENANCE_CONTRACTS.md) — MARR-01
2. [Build the adapter registry and local Codex CLI executor](BUILD_ADAPTER_REGISTRY_AND_CODEX_CLI_TRANSPORT.md) — MARR-02; depends on MARR-01
3. [Formalize Ollama and preflight-only fallback](FORMALIZE_OLLAMA_AND_PREFLIGHT_FALLBACK.md) — MARR-03; depends on MARR-01 and MARR-02
4. [Add the authenticated Tailscale executor transport](ADD_TAILSCALE_CODEX_EXECUTOR_TRANSPORT.md) — MARR-08; depends on MARR-01 and MARR-02
5. [Discover and select from fresh model catalogs](DISCOVER_FRESH_MODEL_CATALOGS.md) — MARR-04; depends on MARR-01–03 and MARR-08
6. [Migrate Product LLM callers to the shared facade](MIGRATE_PRODUCT_LLM_CALLERS.md) — MARR-05; depends on MARR-01–04 and MARR-08
7. [Prove the designated macOS executor profile and acceptance](PROVE_MAC_MINI_ACCEPTANCE.md) — MARR-06; depends on MARR-01–05 and MARR-08
8. [Roll out through release channels with config rollback](ROLLOUT_WITH_CONFIG_ROLLBACK.md) — MARR-07; depends on MARR-06 and explicit release-channel operator acknowledgment

## Capability Acceptance

- [ ] All eight task receipts are linked here and to the parent validation issue.
- [ ] Contract/adapter/catalog/Product behavior passes the task-level fake-provider and integration tests.
- [ ] The designated-host receipt proves the reviewed Tailscale app-capability grant and Serve boundary, Product-to-executor route, loopback-only service, Codex CLI version/auth in the interactive login session, exact Luna route, Ollama probe, compatible preflight fallback, trusted-instruction mapping, and correct refusal for a tool route that Ollama cannot satisfy; it contains no concrete host identity, endpoint, prompt, or secret.
- [ ] After host acceptance, environment and host owner docs describe only behavior proven by merged implementation and the designated-host receipt; until then, current-state docs retain the existing Ollama-only host truth.
- [ ] Dev → test → prod follows the release-channel skills; production is not claimed until the operator-acknowledged release and verification receipts exist.
- [ ] The parent validation issue receives the final acceptance and owner-doc handoff before closure.

## Relationship to GitHub Issues

The parent feature issue is [#5618](https://github.com/RasmusTho/agentic-pkm-mvp/issues/5618), a blocked validation hub, not an implementation issue. Each task above maps to one dependency-ordered child Issue; child Issue numbers are written into task frontmatter as soon as filed. No child is pickup-ready until its dependencies and the specification PR are merged, its Verify targets resolve, and strict readiness validation passes.

## Out of Scope

- Sharing or collapsing Product and Builder policy, registry, credential, fallback, health, or receipt authority.
- Provisioning API keys, changing subscription/account settings, or enabling metered inference.
- Downloading or modifying Ollama models; provisioning credentials; or making live Tailscale policy, Serve, LaunchAgent, or host-service changes from this specification PR.
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
