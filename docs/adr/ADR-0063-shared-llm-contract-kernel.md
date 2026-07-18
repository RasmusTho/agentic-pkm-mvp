State: Accepted (owner decision, 2026-07-17). Selects a neutral shared LLM Contract Kernel with separate Product and Builder execution/policy runtimes; changes no shipped runtime, registry authority, credentials, fallback policy, or provider execution path by itself.
Doc role: Decision record (ADR)
Authority: Authoritative for the dependency direction and compatibility contract between Product and Builder LLM runtimes. `docs/LLM_ROUTING.md` remains authoritative for the current Product LLM Fabric; ADR-0010 and ADR-0062 remain authoritative for BuilderOps and Product/Builder separation.
Owner: Architecture
Temporal class: Durable architecture decision; supersede through a later ADR.
Source of truth: Current-state behavior remains in `docs/LLM_ROUTING.md`, `docs/LLM.md`, and code. Builder authority remains in ADR-0010, ADR-0062, `docs/BUILDEROPS_MODEL_INQUIRY/`, and `docs/BUILDEROPS_CONTROL_PLANE/`. Evidence and migration analysis are in `docs/audits/LLM_RUNTIME_COORDINATION_2026-07-17.md`.

# ADR-0063: Share a neutral LLM contract kernel; keep Product and Builder execution fabrics separate

**Date:** 2026-07-17
**Status:** Accepted (owner decision, 2026-07-17)

## Context

Mimer already has a canonical Product LLM access layer. `LLMTaskIntent` is resolved by the
settings-aware `LLMRouter` into `LLMRoute`; `get_chat_client` and `get_embeddings_client` bind that
route to Product provider clients; constrained completion validates schema-bound output; and
`ReasoningFacade` owns Product reasoning and telemetry (`app/components/llm/router.py:14-33`,
`app/components/llm/fabric.py:11-50`, `app/components/llm/constrained.py:40-177`,
`app/components/reasoning/facade.py:231-385`). Product routing authority includes vault-compiled
settings, environment defaults and overrides, Product model descriptors, Product fallback policy,
embedding identity, and Product health reporting (`docs/LLM_ROUTING.md:16-67,84-150`).

The Builder System already has different execution semantics. BuilderOps Model Inquiry requires two
explicit, independently attested role adapters, host-local subscription sessions, provider request
lineage, strict structured responses, durable turn receipts, and no provider fallback
(`docs/BUILDEROPS_MODEL_INQUIRY/MODEL_TURN_ADAPTERS.md:20-32,58-62,95-119`). Its implementation
therefore uses a BuilderOps-only adapter boundary (`app/builderops/model_inquiry_adapters.py:20-79,
278-397`) and records provider/model/request identity per accepted turn
(`app/builderops/model_inquiry_runner.py:284-388`). ADR-0062 additionally requires Product Runtime to
own no BuilderOps process, data, credential, route, or health dependency and reserves host-local
model/subscription sessions for the privileged Builder executor
(`docs/adr/ADR-0062-builderops-ecosystem-wide-enabling-system.md:148-168,247-257`).

One current Builder component points in the opposite direction: CKM semantic association imports the
Product schema registry, Product `LLMTaskIntent`, and Product `get_chat_client`, thereby resolving a
Builder inference task through Product settings and routing policy
(`app/builderops/ckm/semantic.py:27-34,116-192`). The code rejects a selected mock route, but the
Product router may still construct policy-defined fallback candidates before that check
(`app/components/llm/router.py:307-378`). This is contained transition debt, not a reason to make the
Product Fabric authoritative for all Builder model work.

The decision must prevent two failure modes at once:

1. a second, semantically incompatible LLM abstraction that duplicates identity, schema, failure,
   health, and trace concepts; and
2. an over-shared runtime that transfers Product settings, fallback rules, credentials, health, or
   authority into Builder execution.

## Decision

The system will **share a neutral LLM Contract Kernel while keeping Mimer Product LLM
Fabric and Builder LLM Capability Runtime as separate execution and policy authorities**.

Builder Capability Runtime will **not** reuse Mimer Product LLM Fabric as its execution fabric.
External adapter-only integration remains permitted at explicit system boundaries, but is not the
primary semantic-sharing mechanism because identity, failure, schema, fallback, health, and trace
semantics would otherwise drift in parallel.

The dependency direction is:

```text
Shared LLM Contract Kernel
          ^                         ^
          |                         |
Mimer Product LLM Fabric    Builder LLM Capability Runtime
          ^                         ^
 Product facades/settings     BuilderOps policy/executors
```

Neither execution runtime may import the other's policy, registry, credentials, provider sessions,
health receipts, or runtime stores. Cross-runtime use is an explicit mapper or external adapter,
never a direct authority dependency.

### Shared LLM Contract Kernel

The kernel may own only neutral, side-effect-free contracts and validation:

- task intent fields whose semantics are independent of Product and Builder taxonomies;
- capability, route, provider, model, and registry provenance identities;
- input/output schema references and schema validation;
- common failure classes and health-state vocabulary;
- deadline, determinism, and explicit fallback requirement values;
- trace, request, artifact, and receipt references; and
- compatibility-mapper input/output contracts.

The kernel must not own Product policy, BuilderOps policy, vault settings, credentials, provider or
subscription sessions, host processes, implicit fallback, side effects, health receipts, telemetry
stores, or any runtime store. It is a contract dependency, not a third router or provider fabric.

### Separate runtime authority

Mimer Product LLM Fabric continues to own Product task routing, Product task-kind policy, vault-
compiled settings, Product provider configuration, chat and embeddings, embedding identity and
reconciliation, Product fallback policy, Product health, and `ReasoningFacade`.

Builder LLM Capability Runtime owns Builder development/review capabilities, role separation,
subscription-authenticated CLI/MCP/HTTP/GUI-session adapters, host bootstrap/supervision, Builder
registry and policy, provider request receipts, BuilderOps trace lineage, approvals, preflight, and
restart recovery. It must not read Product vault settings as implicit Builder configuration.

### Fallback is contract data, not discovery behavior

Every request carries exactly one declared fallback requirement:

- `fallback_forbidden`;
- `fallback_same_identity`;
- `fallback_compatible_identity`;
- `fallback_policy_selected`; or
- `human_decision_required`.

Every attempted or selected fallback is present in provenance with original and effective identity,
policy authority, reason, and degraded state. Capability discovery reports what is available; it does
not authorize a provider or identity switch. A Builder independent-review receipt is invalid if both
roles resolve to the same effective runtime target when the governing capability requires independent
roles.

### Registry authority

The runtimes share one descriptor schema, not one mutable registry:

- Product Model Registry remains authoritative only for Product Runtime;
- Builder Capability Registry is authoritative only for Builder Runtime;
- imports/projections are explicit, directional, versioned, and provenance-bearing; and
- no automatic bidirectional synchronization exists.

The same provider/model identity appearing in both registries denotes two separately governed runtime
configurations. Shared identity shape does not imply equal credentials, capability, policy, health, or
availability.

### Compatibility mappers

The initial mapper set is:

- Product `LLMTaskIntent` -> neutral task-intent projection -> Builder `CapabilityRequest` only when
  a caller explicitly crosses from Product-shaped input into a Builder capability;
- Builder `CapabilityResolution` -> Product `LLMRoute` only for an explicitly authorized Product
  adapter, never to make Builder routing Product-authoritative;
- Builder `ModelCapabilityResult` -> schema-constrained result after kernel validation;
- Product health and Builder health -> common health vocabulary while retaining separate authority,
  component, trace, and receipt references; and
- Product/Builder model descriptors -> common identity shape with source registry, registry version,
  and policy authority preserved.

A mapper must be total for its declared version and must preserve provider, model, registry
provenance, trace, failure classification, fallback requirement/decision, degraded state, and
side-effect classification. It must fail loud rather than invent an unmappable value. No mapper may
change authority or authorize fallback.

## Options considered

### A. Reuse Mimer Product LLM Fabric for Builder execution — rejected

This minimizes code count but makes Product vault settings, Product routing precedence, Product
fallback candidates, Product registry authority, Product provider clients, and Product health
semantics part of Builder execution. It conflicts with ADR-0062 credential/process/route separation
and cannot represent Model Inquiry's independent-role and provider-receipt guarantees without turning
the Product Fabric into a Builder policy engine.

### B. Share a neutral contract kernel; keep execution fabrics separate — recommended

This removes duplicate semantic primitives while preserving authority, credentials, fallback,
failure, health, and lifecycle isolation. It adds explicit mapper and versioning cost, but that cost is
bounded and testable. It is the only option that addresses both abstraction drift and authority
leakage structurally.

### C. Keep both systems fully separate and integrate only through an external adapter — viable interim, rejected as the target

This gives excellent runtime and credential isolation, and is appropriate for remote process
boundaries. Used as the only integration model, however, it leaves identity, fallback, failure,
schema, health, and trace vocabularies duplicated. Compatibility then depends on convention at each
adapter and the risk of semantically parallel abstractions remains.

## Consequences

- Acceptance authorizes specification and backlog decomposition, not direct implementation. Runtime
  changes must first pass through `feature-breakdown` and the Issue-first implementation lane.
- Current Product behavior and Builder Model Inquiry behavior remain unchanged.
- CKM's direct Product Fabric dependency is recorded as transition debt to migrate only after the
  Builder runtime and compatibility contract exist; it is not removed in a broad rewrite.
- The Product `LLMTaskIntent`, `LLMRoute`, `ChatClient`, model registry, and `ReasoningFacade` remain
  Product-facing compatibility surfaces during migration.
- Builder's current Model Inquiry adapters remain the executable baseline and are adapted behind the
  future Builder capability boundary rather than replaced wholesale.
- Neutral extraction is contract-first and module-lazy per ADR-0016. This ADR does not choose a
  package path, deployment unit, transport library, provider SDK, or store.
- Architecture tests must eventually enforce facade use, authority direction, registry write
  isolation, credential isolation, fallback preservation, schema validation, role independence,
  health separation, and mock-route honesty.

## SBS reconciliation

- **Conforms:** Product and Builder remain distinct systems under
  `docs/architecture/SBS_OPERATING_MODEL.md §3`; Builder credentials and policy do not enter the
  Product SBS.
- **Extends:** CES gains a versioned cross-system LLM compatibility contract and mapper stewardship
  responsibility.
- **Does not reshape Product SBS:** Product CAO/EBF ownership is unchanged; the neutral kernel is a
  shared contract surface, not a new Product subsystem or runtime service.
- **Future physical extraction:** any later shared package/repository or service boundary is a new
  decision if it changes deployment, ownership, or source-repository authority.

## Owner decision receipt

The owner ratified **Option B — shared neutral contract kernel, separate execution fabrics** on
2026-07-17. The authenticated
[public owner decision receipt](https://github.com/RasmusTho/agentic-pkm-mvp/pull/3970#issuecomment-5012163248)
records that ratification; private deliberation is intentionally not republished. The selected
architectural answer is:

> Builder Capability Runtime shares a neutral LLM Contract Kernel with Mimer Product LLM Fabric,
> while each runtime retains separate policy, registry, credentials, provider sessions, fallback,
> health receipts, stores, and execution facades; explicit mappers or external adapters are the only
> cross-runtime integration paths.

This receipt ratifies the decision. The audit backlog remains advisory until `feature-breakdown`
creates executable specifications and strictly valid Issues; no implementation Issue becomes
`agent:ready` merely because the ADR is Accepted.
