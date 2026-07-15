---
name: Version Active Context Selection
description: Make ActiveContextSet a versioned immutable request/session runtime seam
task_id: MVR-03
source_anchor: "docs/contracts/ACTIVE_CONTEXT_SET.md :: target contract"
parent_capability: Multi-vault runtime selection
prerequisites: [MVR-01, MVR-02]
depends_on: [ESTABLISH_INSTANCE_VAULT_REGISTRY.md, RESOLVE_INSTANCE_DEFAULT_VAULT.md]
can_parallelize_with: []
---

# Version Active Context Selection

## Purpose

The v0 `ActiveContextSet` adapter wraps at most one `VaultContext` and leaves context identity and
generation unknown. A process-global mutable manager cannot safely represent concurrent sessions.

## What This Task Does

- Define the minimal runtime-capable `ActiveContextSet` schema: `context_id`, monotonic
  `generation`, immutable zero/one/many source bindings, selection provenance, optional dimension
  filter, and principal/scope/topology fields already reserved by the contract.
- Add a typed `ContextSelectionStore` keyed by a high-entropy opaque server-minted
  `context_selection_id`. In the current single-user product that ID is an expiring bearer
  capability, not a claim of multi-user identity: every operation also passes the existing #2223
  Companion authentication gate, and the server derives one operator principal from the durable
  `appInstallId` plus a server-owned operational scope for the endpoint/command. API keys, paths,
  correlation IDs, and client-supplied principal/scope strings never become identity or authority.
  The record is bound to that instance principal and allowed server-derived scope; possession of a
  different selection ID is required to access a different session selection. The production
  resolver snapshots one context per request without mutating process-global state and GOV
  re-authorizes every binding on every resolution.
- Add production Companion endpoints to create, replace, inspect, and clear a TTL-bound selection.
  Creation returns the server-minted ID; later mutation/read requires that bearer ID plus the
  #2223 gate and the same server-derived instance principal/allowed scope. The existing
  `/api/companion/vault/select` remains only a
  named legacy-global adapter until task 05 migrates its production client; it cannot be the new
  session-selection command or mutate a scoped selection implicitly.
- Keep session selection TTL-bound and ephemeral in V1. A request that supplies no selection ID
  may resolve the instance default or no-vault. A request that explicitly supplies an expired,
  unknown, or pre-restart `context_selection_id` fails closed with a reselection-required error; it
  never falls through to a default, last-active state, or another session. No unrelated
  chat/canvas session map or durable human-artifact store is reused.
- Rotate generation atomically on session change; let in-flight work finish on its snapshot.
- Key/invalidate caches and downstream context artifacts by `context_id`, generation, principal,
  scope, a non-reversible selection-capability digest, dimension/filter, and binding set; never by
  binding plus generation alone. Raw bearer IDs are never logged, receipted, or embedded in cache
  keys.
- Enforce GOV authorization independently for every resolved binding.

## Concretely

Sessions S1 and S2 concurrently select vaults A and B. Each request receives one immutable context
generation. Switching S1 to B increments only S1's generation; S1's in-flight A request finishes
on A while its next request uses B, and S2 remains unchanged. These transitions are exercised
through the production create/replace/inspect/clear endpoints, not by seeding the store in tests.

## Why This Matters

A mutable scalar selection cannot give concurrent work a coherent boundary and invites cache,
retrieval, settings, or write provenance to leak between humans or vaults.

## Source Anchors

- `docs/contracts/ACTIVE_CONTEXT_SET.md :: target contract`
- `app/vault/active_context.py :: ActiveContextSet v0 transitional adapter`
- `docs/SYSTEM_BREAKDOWN_STRUCTURE.md :: WSP active cognitive context`
- `docs/MULTI_VAULT_RUNTIME/README.md :: Active context and isolation`

## SBS Impact

- Primary subsystem: WSP
- Secondary subsystem(s): GOV, EBF, RCA, SFC
- Write class: mechanical session state; governed content writes remain unchanged
- Authority impact: selection cannot upgrade authority; per-binding GOV check becomes enforced
- Persistence impact: request snapshots and TTL-bound V1 session selection are ephemeral; only the instance default is durable
- Derived/rebuildable impact: context snapshots/caches are rebuildable and full-context-keyed
- Human knowledge impact: no cross-vault carry or silent merge
- Memory impact: memory/retrieval consumers receive explicit binding provenance
- Retrieval/context impact: replaces scalar global context with immutable zero/one/many snapshot
- Sync/deployment impact: concurrent requests no longer require process-level rebinding
- External boundary impact: adapters translate legacy vault inputs only at ingress
- New or changed contract: `ACTIVE_CONTEXT_SET.md` moves from v0 target stub to versioned runtime seam
- Owner-doc impact: will-update-in-PR at `docs/contracts/ACTIVE_CONTEXT_SET.md`
- Transition debt impact: reduces WSP global-context deviation; legacy adapters remain bounded for task 07
- Fitness rule impact: adds request snapshot/generation/no-cross-talk fitness tests

## Constraints

- Do not expose `activeVault`/`vaultPath` as a rival public context contract.
- A session switch affects later requests only; no in-flight rebinding.
- Cross-vault synthesis requires an explicit many-binding set and preserves provenance.

## Acceptance Criteria

- [ ] The production request dependency resolves one immutable, versioned ActiveContextSet and
  propagates it through downstream context without consulting mutable global selection again.
  - Verify: `tests/api/test_active_context_resolution.py::test_request_uses_one_context_generation_end_to_end`
- [ ] Two concurrent sessions select different vaults without mutating each other or the instance
  default.
  - Verify: `tests/api/test_active_context_resolution.py::test_concurrent_sessions_are_isolated`
- [ ] Switching a session atomically advances generation; in-flight work completes on the prior
  snapshot and subsequent work uses the new snapshot.
  - Verify: `tests/api/test_active_context_resolution.py::test_session_switch_is_generation_atomic`
- [ ] After session expiry or process restart, a request with no selection ID resolves the explicit
  instance default or no-vault, while a request presenting the expired/unknown prior ID fails
  closed and requires reselection; neither path resurrects last-active state or another session.
  - Verify: `tests/api/test_active_context_resolution.py::test_session_expiry_and_restart_are_truthful`
- [ ] Zero/one/many bindings are valid and each member is independently GOV-authorized.
  - Verify: `tests/api/test_active_context_resolution.py::test_each_binding_is_authorized_independently`
- [ ] Session selection uses an expiring high-entropy server-minted bearer ID in addition to #2223
  authentication, binds to the server-derived single-operator instance principal and operational
  scope, and rejects arbitrary client correlation/principal/scope inputs or a different ID.
  - Verify: `tests/api/test_active_context_resolution.py::test_selection_id_is_single_user_bearer_with_server_derived_context`
- [ ] Production create/replace/inspect/clear commands drive the selection store, enforce #2223
  authentication and expiry, and never mutate process-global `VaultManager` state.
  - Verify: `tests/api/test_active_context_selection_api.py::test_production_selection_lifecycle_is_scoped_and_global_free`
- [ ] Cache/retrieval context cannot collide across two bearer selections with the same binding and
  generation but different server-derived scope, selection-capability digest, or dimension/filter;
  raw bearer IDs remain secret and the typed principal field stays in the key for future
  authenticated-principal expansion.
  - Verify: `tests/retrieval/test_active_context_cache_isolation.py::test_cache_keys_include_full_context_identity`

## Out of Scope

- Migrating every HTTP/background caller, UI selection controls, or dimension persistence.

## How to Verify (Pre-Merge)

- `pytest -q tests/api/test_active_context_resolution.py tests/api/test_active_context_selection_api.py tests/retrieval/test_active_context_cache_isolation.py`
- `ruff check app tests`

## Restart / Durability Posture

Request snapshots and V1 session selections are ephemeral. The bounded TTL
`ContextSelectionStore` is not an unrelated canvas/chat session map. After expiry, process restart,
or session loss an omitted selection resolves the instance default or no-vault, but a presented
stale ID returns an explicit reselection-required error. Context generations are never reused in a
way that makes stale cached work appear current.

## Related Docs

- `docs/contracts/ACTIVE_CONTEXT_SET.md`
- `docs/MULTI_VAULT_RUNTIME/README.md`
- `docs/SYSTEM_BREAKDOWN_STRUCTURE.md`

## Related GitHub Issues

Create one child under #2143 after MVR-01/02. Use Sol/xhigh: request concurrency, bearer-capability
handling, cache isolation, and authority enforcement have high blast radius. Reuse #2356's type;
do not create a rival seam or claim multi-user identity that #2223 does not provide.
