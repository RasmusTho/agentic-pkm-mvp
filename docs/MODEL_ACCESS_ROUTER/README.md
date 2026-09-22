State: Target-state capability specification, created 2026-09-22 from accepted ADR-0066. Parent validation Issue #5618 is open and blocked. No router, Product migration, new provider auth, Mac mini profile, or rollout is claimed as shipped.
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
- Product acceptance is gated on a Mac mini host-local profile and a sanitized runtime receipt. This specification does not add secrets to Git, provision API keys, download models, or deploy to a release channel.

## Existing Backlog Reconciliation

- Issue #5177 remains the Builder System authority for execution-routing work: TCD capability tiers, Luna/Terra/Sol/Spark policy, scheduling, escalation, canary evidence, and its parent acceptance are not re-opened or replaced here.
- Its delivered Builder slices #5203 (Model Inquiry capability-resolution transport) and #5205 (Codex-only active worker carrier) remain delivered. MARR reuses the existing Model Inquiry bridge and compatibility alias; it does not create a parallel Builder route or duplicate those Issues.
- MARR adds the neutral facade/profile seam and Product runtime integration that #5177 explicitly excludes. Any Builder adoption is limited to an explicit Builder profile/conformance path; the existing Builder execution policy and scheduler continue to own their decisions.
- The independent Builder owner-platform parent #5399 remains outside this capability.

## Capability Contract

The request flow is:

Product or Builder intent → owner policy resolver → fresh permitted catalog → exact resolved route → preflight → one adapter → result/receipt

The shared facade accepts an owner profile and cannot select or merge that profile's policy. A route binds exact provider, model, transport, requested/resolved capabilities, catalog snapshot hash/reference, preflight status, execution host, and any pre-inference fallback cause.

Codex CLI/Luna is Product's primary target for configured general agent/text routes. Ollama can be selected only if Codex CLI executable, authentication, or model preflight fails before inference starts, and only if it satisfies the complete intent. No provider switch is allowed after the first model invocation. Missing native-tool support, reasoning level, structured-output support, stale/unordered catalog data, and missing credentials fail closed or retain an explicit pinned target as described by policy; they never silently weaken the intent.

## Catalog and Freshness Policy

The neutral catalog descriptor is shared; Product model IDs/pricing/user-facing metadata and Builder provider census/policy remain separate scopes. Runtime CatalogSnapshot data is host-local derived state, not policy or credential authority.

- Refresh TTL: five minutes. Maximum stale age: 24 hours.
- Discovery performs no inference. A snapshot binds the exact source, fetch time, descriptor set, and deterministic hash.
- Per-request latest-compatible selection requires provider-supplied release/created metadata or an explicit provider replacement/upgrade relation. Array position, model-name spelling, and Ollama local pull time are not release evidence.
- Codex app-server model/list is account-scoped availability/capability discovery using the existing host-local subscription session. If it has no release timestamp or explicit upgrade edge for a profile, retain its pinned model; never infer chronology from list order.
- OpenAI and Anthropic API catalog adapters may use only an already authorized and already configured credential reference. This delivery does not provision credentials or enable metered API inference. Missing credentials make that source unavailable; tests use fake HTTP only.
- Ollama discovery inspects configured local models and declared metadata. It never claims native_tools unless both model metadata and the tested adapter establish that capability.

## Cross-Task Invariants / Interaction Safety

1. Policy ownership: the facade accepts Product or Builder policy explicitly. If the neutral contract lands before either profile mapper, existing route behavior stays unchanged; no default policy is guessed.
2. Model Inquiry isolation: the Codex alias continues to resolve exactly one target with fallback_forbidden. Product's Ollama fallback cannot enter Model Inquiry, including when shared adapter code is reused.
3. Codex host isolation: Product Codex execution uses a dedicated empty cwd, read-only sandbox, disabled shell/unified-exec tools, ignored ambient tool configuration, and an explicit auth-only environment allowlist. If the installed CLI cannot enforce the profile, Product does not route through it.
4. Preflight boundary: fallback is permitted only before an inference invocation. If an adapter returns timeout, session-expired, parse/schema failure, or provider error after start, the route is terminal and no second provider receives the prompt.
5. Capability preservation: fallback is eligible only when the candidate satisfies every requested capability. Ollama lacking a capability such as native tools is a terminal preflight refusal, not a degraded route.
6. Catalog failure: failed refresh may use a snapshot only while it is within maximum stale age and the owning policy allows it. A stale, unordered, or unverifiable snapshot cannot auto-promote; with no pinned policy target, routing fails closed.
7. Partial Product migration: unmigrated Product callers continue through the legacy facade. Migrated callers go through one shared route and one adapter; no dual execution/shadow inference is permitted.
8. Host and rollout gates: missing Mac mini auth, missing Ollama model, or failed acceptance leaves the parent blocked. No model download, API key creation, or production deployment is used to make the receipt pass. Production remains behind the release-channel operator-acknowledgment gate.

## Implementation Tasks

1. [Establish shared route and provenance contracts](ESTABLISH_SHARED_ROUTE_AND_PROVENANCE_CONTRACTS.md) — MARR-01
2. [Build the adapter registry and Codex CLI transport](BUILD_ADAPTER_REGISTRY_AND_CODEX_CLI_TRANSPORT.md) — MARR-02; depends on MARR-01
3. [Formalize Ollama and preflight-only fallback](FORMALIZE_OLLAMA_AND_PREFLIGHT_FALLBACK.md) — MARR-03; depends on MARR-01 and MARR-02
4. [Discover and select from fresh model catalogs](DISCOVER_FRESH_MODEL_CATALOGS.md) — MARR-04; depends on MARR-01–03
5. [Migrate Product LLM callers to the shared facade](MIGRATE_PRODUCT_LLM_CALLERS.md) — MARR-05; depends on MARR-01–04
6. [Prove the Mac mini host profile and acceptance](PROVE_MAC_MINI_ACCEPTANCE.md) — MARR-06; depends on MARR-01–05
7. [Roll out through release channels with config rollback](ROLLOUT_WITH_CONFIG_ROLLBACK.md) — MARR-07; depends on MARR-06 and explicit release-channel operator acknowledgment

## Capability Acceptance

- [ ] All seven task receipts are linked here and to the parent validation issue.
- [ ] Contract/adapter/catalog/Product behavior passes the task-level fake-provider and integration tests.
- [ ] The Mac mini receipt proves CLI version/auth status, exact Luna route, Ollama probe, compatible preflight fallback, and correct refusal for a tool route that Ollama cannot satisfy; it contains no credential or endpoint secret.
- [ ] Owner docs describe only behavior proven by merged implementation and the Mac mini acceptance receipt.
- [ ] Dev → test → prod follows the release-channel skills; production is not claimed until the operator-acknowledged release and verification receipts exist.
- [ ] The parent validation issue receives the final acceptance and owner-doc handoff before closure.

## Relationship to GitHub Issues

The parent feature issue is [#5618](https://github.com/RasmusTho/agentic-pkm-mvp/issues/5618), a blocked validation hub, not an implementation issue. Each task above maps to one dependency-ordered child Issue; child Issue numbers are written into task frontmatter as soon as filed. No child is pickup-ready until its dependencies and the specification PR are merged, its Verify targets resolve, and strict readiness validation passes.

## Out of Scope

- Sharing or collapsing Product and Builder policy, registry, credential, fallback, health, or receipt authority.
- Provisioning API keys, changing subscription/account settings, or enabling metered inference.
- Downloading or modifying Ollama models or editing the Mac mini's host-local credentials.
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
