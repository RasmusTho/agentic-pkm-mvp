State: Accepted target-state decision, owner-directed 2026-10-07. The universal Product portal is not yet implemented or live; Issue #5819 tracks delivery and acceptance.
Doc role: Decision record (ADR)
Authority: Supersedes ADR-0064's direct provider-egress default for Product inference and ADR-0066 D6 only on where Product embeddings execute. It does not merge Product and Builder policy or credential authority.
Owner: Product LLM Routing / Architecture spine
Temporal class: Durable architecture decision; supersede through a later ADR.
Source of truth: This ADR and the Model Access Router capability specification. Shipped behavior remains owned by `docs/LLM_ROUTING.md` and runtime evidence.

# ADR-0067: Mac mini is the Product model-access portal

**Date:** 2026-10-07
**Status:** Accepted target state (owner-directed)

## Context

The Product already has a settings-backed LLM router, clone-local chat profiles, and a bounded Mac
mini API that can execute the accepted Luna/Codex CLI route. The current Mac API does not yet mediate
every declared provider or embeddings; Product embedding calls still use the separate embedding
client path. OpenAI and Anthropic catalogs also need to keep up with provider model releases without
putting model-specific routing into Product call sites.

The owner has decided that the Mac mini is the single model-access portal for Product, while each
Product clone or satellite retains control of its selected model/profile in settings. This is a
target-state decision, not a claim that all provider routes are currently served.

## Decision

### D1 — One Product model-access portal

All Product model inference, including chat/completion and embeddings, is mediated through the Mac
mini Model Access API over the configured VLAN path. Product call sites use the thin API rather than
provider SDKs, CLI commands, or provider-specific endpoints. `mock` remains available for
deterministic tests.

### D2 — Product settings select; the portal executes

Product shared settings declare registry-backed models/profiles, and each clone may select a
different profile in its local settings. The Product router resolves that choice and required
capabilities. The Product wire request names the logical provider/model and bounded task payload,
not a caller-selected transport or catalog snapshot. The Mac portal maps that exact provider/model
to an allowed host-local adapter and returns resolved transport/catalog provenance; it does not
silently substitute an unselected model. Exact-route compatibility operations remain distinct from
the logical Product API. A
profile may opt into a latest-compatible model family only when the catalog provides verifiable
release ordering and the descriptor satisfies the profile's capability allowlist.

### D3 — Provider credentials stay at the portal

Provider credentials and harness/session state are resolved on the Mac mini from its configured
host-local credential sources. Product requests carry neither credential values nor arbitrary
provider endpoints, commands, arguments, environment, tools, or MCP configuration. The trusted
Product caller identity may be shared across dev/test/prod for this single-operator deployment;
separate model credentials per release channel are not a requirement. Product and Builder retain
separate policy authorities, and this decision does not authorize Product credentials for Builder.

### D4 — One exact dispatch and capability-safe fallback

The route binds an exact provider/model and catalog snapshot. Any fallback is allowed only after a
no-inference preflight and before the inference request. Once dispatch may have started, errors are
terminal: no retry, model switch, or second provider call. A route that lacks a requested capability
fails before inference.

### D5 — Preserve embedding identity and make Ollama optional

Embeddings use the same portal but retain the existing embedding identity and dimension guards. A
model change that invalidates the stored vector identity must fail clearly and use the existing
governed rebuild/reconcile path; the portal must not silently mix identities. Ollama is an optional
configured provider, not a mandatory service or health-check dependency. Luna/Codex CLI readiness
must not depend on Ollama.

### D6 — Keep Builder policy independent

Builder Model Inquiry retains its own resolver, policy, receipt, single-target behavior, and
`fallback_forbidden` invariant. It may reuse a Mac-hosted transport through its existing compatibility
seam, but Product settings and Product route authority do not configure Builder.

### D7 — Use one operator-controlled ingress boundary

For the current single-operator Ygg deployment, VLAN mTLS at the ingress and the loopback-only
executor are the caller boundary. Do not add separate credentials or application-level
channel/action claims solely to distinguish Product, Builder, dev, test, and prod callers. This
means an mTLS-admitted caller may invoke the fixed executor operations exposed by the ingress; that
is an accepted operational risk for this one-operator system, not a reason to merge Product and
Builder policy resolvers, profiles, credentials, or receipts. Revisit this boundary before adding
multiple operators or untrusted tenants. This decision supersedes ADR-0066's per-channel/action
ingress-claim requirement for the current Ygg profile; VLAN mTLS and loopback remain required.

## Options considered

- **Product instances call providers directly:** rejected for the Product target; it duplicates
  egress and credential resolution across satellites and makes the Mac portal incomplete.
- **Mac mini mediates all registered Product model capabilities:** selected; one route surface hides
  provider harnesses while clone-local settings retain model choice.
- **A separate model gateway per release channel:** rejected for this single-operator deployment;
  it adds credentials and operational state without a current requirement.
- **Keep embeddings permanently outside the portal:** rejected as the target. The existing embedding
  identity contract remains; only execution location is unified.

## Consequences

- The current Luna/Codex CLI path remains the initial Product route and can be rolled out separately.
- The Mac API still needs provider adapters/catalog discovery for the declared provider census and a
  bounded embeddings operation; Product embedding clients and clone-local profiles need migration.
- Current implementation/acceptance gaps are tracked in [Issue #5819](https://github.com/RasmusTho/agentic-pkm-mvp/issues/5819).
- Current shipped claims must continue to distinguish the accepted Luna host receipt from the
  not-yet-delivered universal portal.

## Related decisions and owner docs

- [ADR-0063](./ADR-0063-shared-llm-contract-kernel.md) keeps Product and Builder execution fabrics
  separate behind a neutral contract.
- [ADR-0064](./ADR-0064-model-access-substrate.md) continues to govern provider credentials and
  model identity; this decision changes Product provider egress location.
- [ADR-0066](./ADR-0066-shared-model-access-router-and-catalogs.md) continues to govern the shared
  route contract, path and catalog constraints, except for the Product embedding execution target
  and single-operator ingress boundary clarified by D5 and D7 here.
- [Model Access Router](../MODEL_ACCESS_ROUTER/README.md) records implementation state and the
  bounded delivery tasks.
- [LLM Routing](../LLM_ROUTING.md) remains authoritative for current Product behavior.
