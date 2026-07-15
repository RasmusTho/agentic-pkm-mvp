---
name: Version Active Context Selection
description: Make ActiveContextSet a versioned immutable request/session runtime seam
task_id: MVR-03
source_anchor: "docs/contracts/ACTIVE_CONTEXT_SET.md :: Multi-Vault Runtime V1 Decision"
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
  filter, and principal/scope/topology fields already reserved by the contract. Every source
  binding also carries its monotonic `binding_revision` (path/device/authority-provenance revision),
  and the snapshot carries the registry revision plus a non-secret authorization-decision epoch or
  fingerprint.
- Add a typed `ContextSelectionStore` keyed by a high-entropy opaque server-minted
  `context_selection_id`. In the current single-user product that ID is an expiring bearer
  capability, not a claim of multi-user identity: every operation also passes the existing #2223
  Companion authentication gate. The server resolves `principal_context` from an authenticated
  human principal or a server-owned delegated operator-role principal supplied by the auth/GOV
  boundary. Each later request derives its operational scope independently from the server-owned
  endpoint/command contract; a selection never grants or stores operation authority. The current local-only
  bootstrap may use a private `local_operator_role_id` owned by that boundary; it denotes an
  instance-scoped delegated role, not the human's global identity. `appInstallId` is carried
  separately as instance identity and can never derive, equal, or substitute for a principal. API
  keys are credentials rather than principals; paths, correlation IDs, and client-supplied
  principal/scope strings never become identity or authority. A governed operation with no resolved
  principal/delegated role fails closed. The selection record is bound to that principal, instance,
  and selected binding set, not to an endpoint scope. Possession of a different selection ID is
  required to access a different session selection. At later request resolution the server derives
  the operation scope for that call, GOV authorizes the principal/bindings/operation independently,
  and the resulting immutable context snapshot carries that per-call scope. The same selection may
  therefore support an authorized read and governed write without either an over-broad stored scope
  or a scope mismatch; an unauthorized operation still fails closed.
- Own the missing current-runtime producer for that delegated role. On an existing single-user
  installation, a one-shot auth/GOV bootstrap maps the one configured #2223 credential fingerprint
  (never the raw key) to a freshly generated opaque `local_operator_role_id` in private mode-`0600`
  auth state under the MVR-01 instance-state boundary (native installs use private app-data). The
  record has its own schema, revision, migration provenance, lock/fsync/atomic-write path, and is
  never derived from `appInstallId` or the credential value. Production API and CLI authentication
  resolve the same record. Bootstrap binds the same local role to `trusted_loopback` after proving
  the effective listener and request path are loopback-local, and to `trusted_companion_proxy` only
  when server configuration identifies the Companion peer and existing middleware validates it,
  regardless of whether an API key is also configured. Both subjects are server-derived; proxy,
  forwarding, or client headers cannot claim them. Provisioning or rotating API-key auth binds the
  credential fingerprint to the same role without disabling the already-supported loopback/proxy
  subjects; only an explicit governed posture change may revoke one atomically.
  Multiple ambiguous credentials, any other zero-credential non-loopback posture, unsafe
  ownership, missing durable storage, or a partial record fails preflight with an explicit
  provisioning action. A governed credential rotation preserves the role ID, while an explicitly
  added human/agent role receives a distinct principal. Update bootstrap, existing-install migration,
  channel init, and test fixtures in this slice before fail-closed enforcement is enabled.
- Treat this new private delegated-principal record as a versioned runtime boundary. Before its first
  durable write MVR-03 records a `minimum_runtime_principal` floor; the MVR-01 rollback launcher
  and native preflight refuse an earlier credential-only image while that floor exists. Compatible
  roll-forward exports the prior image's final credential/auth revision under lock, verifies its
  recorded fork, and reconciles a credential rotation into the same role ID; missing, divergent, or
  ambiguous auth state fails closed without overwriting either lineage. The floor may be lowered
  only by a later explicitly verified reversible migration, never by scalar rollback.
- Add production Companion endpoints to create, replace, inspect, and clear a TTL-bound selection.
  Creation returns the server-minted ID; later selection-record mutation/read requires that bearer
  ID plus the #2223 gate, the same server-resolved principal/instance, and the selection-management
  command's independently derived scope. The existing
  `/api/companion/vault/select` remains only a
  named legacy-global adapter until task 05 migrates its production client; it cannot be the new
  session-selection command or mutate a scoped selection implicitly.
- The selection resource is reusable by the later MVR-05 ingress contract without inventing a
  second store: a retained client session sends its bearer as `X-Active-Context-Session`; a caller
  that needs a one-request override mints/uses a separately authorized selection and sends it as
  `X-Active-Context-Override`. The request dependency gives the override precedence for that call
  only and never replaces the retained session record. This slice owns store/auth semantics;
  MVR-05B owns the production header dependency and call-site test.
- Keep session selection TTL-bound and ephemeral in V1. A request that supplies no selection ID
  may resolve the instance default or no-vault. A request that explicitly supplies an expired,
  unknown, or pre-restart `context_selection_id` fails closed with a reselection-required error; it
  never falls through to a default, last-active state, or another session. No unrelated
  chat/canvas session map or durable human-artifact store is reused.
- Rotate generation atomically on session change; let in-flight work finish on its snapshot. On
  each production resolution, compare current binding/registry revisions and authorization epoch
  with the prior snapshot. Relocation, removal, authority-provenance, or verdict change invalidates
  affected cache entries and rotates generation before downstream work starts.
- Key/invalidate caches and downstream context artifacts by `context_id`, generation,
  registry/binding revisions, authorization epoch/fingerprint, principal, scope, a non-reversible
  selection-capability digest, dimension/filter, and binding set; never by binding plus generation
  alone. Raw bearer IDs are never logged, receipted, or embedded in cache keys.
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
- Persistence impact: request snapshots and TTL-bound V1 session selection are ephemeral; the
  auth/GOV-owned delegated operator-role record and instance default are separate durable inputs
- Derived/rebuildable impact: context snapshots/caches are rebuildable and full-context-keyed
- Human knowledge impact: no cross-vault carry or silent merge
- Memory impact: memory/retrieval consumers receive explicit binding provenance
- Retrieval/context impact: replaces scalar global context with immutable zero/one/many snapshot
- Sync/deployment impact: concurrent requests no longer require process-level rebinding
- External boundary impact: adapters translate legacy vault inputs only at ingress
- New or changed contract: `ACTIVE_CONTEXT_SET.md` moves from v0 target stub to versioned runtime seam
- Owner-doc impact: will-update-in-PR at `docs/contracts/ACTIVE_CONTEXT_SET.md`, `docs/SECURITY.md`,
  `docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md`, and `docs/RELEASE_CHANNELS/README.md`
- Transition debt impact: reduces WSP global-context deviation; legacy adapters remain bounded for task 07
- Fitness rule impact: adds request snapshot/generation/no-cross-talk fitness tests

## Constraints

- Do not expose `activeVault`/`vaultPath` as a rival public context contract.
- A session switch affects later requests only; no in-flight rebinding.
- Cross-vault synthesis requires an explicit many-binding set and preserves provenance.

## Acceptance Criteria

- [ ] The selection store/resolver returns one immutable, versioned ActiveContextSet snapshot from
  explicit selection inputs without consulting mutable global selection; production HTTP carrier
  propagation remains sealed until MVR-05B.
  - Verify: `tests/instance/test_context_selection_store.py::test_selection_resolution_is_immutable_and_global_free`
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
  authentication, binds to the server-resolved human/delegated-role principal, separate instance
  identity, and selected bindings—but stores no operational authority. The resolver derives scope
  per call, permits the same selection for separately authorized read/write operations, and rejects
  arbitrary client correlation/principal/scope inputs, unauthorized operations, or a different ID.
  `appInstallId` is never principal identity.
  - Verify: `tests/api/test_active_context_resolution.py::test_selection_id_is_single_user_bearer_with_server_derived_context`
- [ ] Principal derivation uses only the auth/GOV-owned human or delegated-role record; two
  installations cannot be conflated with two humans, and multiple human/agent roles on one instance
  remain distinct in GOV decisions, cache keys, and receipts.
  - Verify: `tests/api/test_active_context_resolution.py::test_instance_identity_never_substitutes_for_principal_context`
- [ ] Existing one-credential single-user installs, new channel bootstrap, native init, and fixtures
  all produce the private versioned delegated-role binding before request selection is enabled;
  production API/CLI resolve it, rotation preserves it, and ambiguous/missing/unsafe state fails loud.
  - Verify: `tests/integration/test_local_operator_principal_bootstrap.py::test_existing_single_user_auth_migrates_to_distinct_delegated_role`
- [ ] **MVR-03:** The delegated-principal migration records its minimum-runtime floor before its first
  durable role write; credential-only rollback is blocked, while compatible roll-forward preserves
  role identity and reconciles only an unambiguous credential rotation from its final old-image export.
  - Verify: `tests/migrations/test_local_operator_principal_upgrade.py::test_principal_floor_blocks_credential_only_rollback_and_reconciles_safe_rollforward`
- [ ] **MVR-03:** Deployment and release-channel owner docs record the shipped
  `minimum_runtime_principal` floor, compatible rollback/roll-forward images, and operator preflight
  in the same PR that advances the floor.
  - Verify: doc writeback at `docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md :: Deployment and Environments` +
    doc writeback at `docs/RELEASE_CHANNELS/README.md :: Release Channels Specification`
- [ ] Existing auth-disabled/no-key loopback and server-configured trusted Companion proxy installs
  bootstrap the same private delegated role and keep production selection/governed writes working;
  forwarded-header spoofing and every other non-loopback peer fail until governed credential
  provisioning completes.
  - Verify: `tests/integration/test_local_operator_principal_bootstrap.py::test_zero_key_loopback_and_trusted_companion_proxy_map_to_local_role`
  - Verify: `tests/integration/test_local_operator_principal_bootstrap.py::test_zero_key_nontrusted_nonloopback_fails_principal_preflight`
- [ ] A configured-key installation still maps middleware-admitted keyless loopback and trusted
  Companion-proxy requests to the same local delegated role, while nontrusted peers require the key.
  - Verify: `tests/integration/test_local_operator_principal_bootstrap.py::test_configured_key_preserves_local_and_trusted_proxy_subjects`
- [ ] Security and ActiveContextSet owner contracts describe the shipped credential/loopback/proxy subject
  to delegated-role mapping, separate instance identity, and fail-closed principal resolution.
  - Verify: doc writeback at `docs/SECURITY.md :: Security` + doc writeback at
    `docs/contracts/ACTIVE_CONTEXT_SET.md :: ActiveContextSet`
- [ ] Production create/replace/inspect/clear commands drive the selection store, enforce #2223
  authentication and expiry, and never mutate process-global `VaultManager` state.
  - Verify: `tests/api/test_active_context_selection_api.py::test_production_selection_lifecycle_is_scoped_and_global_free`
- [ ] Cache/retrieval context cannot collide across two bearer selections with the same binding and
  generation but different server-derived scope, selection-capability digest, or dimension/filter;
  raw bearer IDs remain secret and the typed principal field stays in the key for future
  authenticated-principal expansion.
  - Verify: `tests/retrieval/test_active_context_cache_isolation.py::test_cache_keys_include_full_context_identity`
- [ ] Relocating a binding or changing its authority provenance/verdict rotates the production
  request context and invalidates affected cache entries before the next request can reuse data.
  - Verify: `tests/integration/test_multi_vault_request_isolation.py::test_binding_revision_rotates_context_and_cache_before_next_request`

## Out of Scope

- Migrating every HTTP/background caller, UI selection controls, or dimension persistence.

## How to Verify (Pre-Merge)

- `RUN_INTEGRATED_RUNTIME_UAT=1 pytest -q tests/instance/test_context_selection_store.py tests/api/test_active_context_resolution.py tests/api/test_active_context_selection_api.py tests/retrieval/test_active_context_cache_isolation.py tests/integration/test_multi_vault_request_isolation.py tests/integration/test_local_operator_principal_bootstrap.py tests/migrations/test_local_operator_principal_upgrade.py`
- `mypy app`
- `pytest -q -m "not pg"`
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
