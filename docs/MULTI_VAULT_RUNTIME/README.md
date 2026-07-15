# Multi-vault runtime selection

State: Active future-state capability specification. Parent validation hub **#2143** remains
blocked and must never be claimed as an implementation issue. No text in this directory claims
that multi-vault runtime behavior is shipped.
Doc role: Authoritative capability specification and feature-breakdown source of truth.
Primary subsystem: WSP. Secondary boundaries: GOV, SFC, PDM, EBF, HKA, RCA, HIX, OEF.

## Capability boundary

One product instance may register several content vaults, nominate one instance default, group
registrations into non-authoritative dimensions, and resolve a zero/one/many vault
`ActiveContextSet` for a request or session. The runtime must stop treating a process-global
`VAULT_ROOT` or mutable `VaultManager.active_context` as the public context seam.

This capability generalizes selection, not authority:

- the registry says which content roots this instance knows and their provenance;
- the default says which registered vault a background or compatibility caller may bind when no
  narrower context exists;
- request/session selection produces an immutable, generation-stamped `ActiveContextSet`;
- a dimension is an opaque grouping/filter over registered bindings, never a permission,
  confidentiality label, or semantic authority claim;
- GOV still decides whether a principal may read or mutate a selected binding.

The current one-vault and no-vault states remain valid. Existing single-vault callers migrate
through explicit adapters and keep their behavior until their production call sites adopt the
new context seam.

## Decided contracts

### Persistence and package placement

The authoritative registry is **mechanical durable instance-local state**. It does not belong in
a content vault (which would require selecting a vault before the registry can be read), and it
is not an authority-bearing database record. The Markdown store remains the durable substrate; a
database view, if later added, is rebuildable only.

Container deployments must mount one channel/instance-scoped named volume at
`/app/instance-state` into every registry consumer (initially API, worker, watcher, and Heimdal
capture watcher). The production default is
`/app/instance-state/agentic-pkm/vault-registry.md`; test/dev/prod compose project names keep
those stores isolated. `/app/tmp`, `/app/runtime`, the image layer, `$HOME`, and a selected content
vault are not valid authoritative container locations. Native-host installs retain their normal
XDG/macOS app-data location. `DESIGN_HANDOFF_APP_LOCAL_SETTINGS` remains an explicit deployment
override only when the preflight proves that the resolved parent is durable and shared by every
enabled consumer.

Per-channel registry isolation is not sufficient because current containers can see shared host
roots. A separate host-local **channel ownership ledger** is mounted consistently into every channel
and native runtime. Under one global mode-`0600` lock it records `channel_id`, stable binding, and an
HMAC fingerprint of canonical filesystem identity (never a raw host path). Registration/relocation
uses a recoverable pending→registry-commit→active reservation protocol; lifecycle start proves the
active reservation still matches its channel and root. The same physical content root cannot be
active in dev/test/prod/native simultaneously. Explicit transfer drains/stops the source channel,
commits release, then claims the destination; crashes leave a blocking recoverable reservation,
never two owners or an unowned running lifecycle.

Before the first recreate that introduces this volume, the deploy/startup migration gate resolves
the legacy path and records a preliminary fingerprint inside the still-running old API container.
It then acquires the channel deployment fence, rejects and drains every registry mutation producer,
stops the old API, exports the **final post-stop** file with mode `0600` to channel-scoped host
staging, and validates its fingerprint/schema again. The fence prevents any old writer from
restarting through import; a changed final fingerprint or unfenced writer aborts rather than using
a pre-quiescence snapshot. If no old container exists, the gate may proceed only when it proves the
legacy source itself is durable and unchanged under the fence or no legacy registry ever existed.
The new-image one-shot migrator mounts `instance-state`, atomically imports the staged payload and
records source fingerprint/provenance. It never deletes an independently durable legacy source; the
staged copy remains through cross-process verification and is removed only after that verification
succeeds. A missing export, conflicting populated destination, or unreadable/ambiguous source
blocks recreate/import rather than booting an empty registry.

All registry-backed mutation uses one store transaction contract: an exclusive OS file lock on a
sidecar in the shared volume, reload plus monotonic schema revision/CAS validation, write to a
same-directory temporary file, `fsync`, atomic replace, and parent-directory `fsync`. Readers see
only complete revisions. API, picker, default, dimension, migration, and headless-CLI producers use
this contract; worker/watcher/Heimdal readers do not invent independent writers.

Promotion/startup preflight must prove the volume, ownership, identical resolved path, and lock
semantics across processes before recreate. Post-recreate verification must prove the same
registry revision from API, worker, watcher, and Heimdal capture watcher.

`app/vault/app_local.py` moves to `app/instance/vault_registry.py` when the registry becomes
first-class. The old import path remains a bounded compatibility re-export until the final
migration slice proves no production caller depends on it. This records the relocation decision
required by #2143 without pretending that the move has shipped.

### Identity and selection

- `vault_id` identifies the logical content vault, while `local_instance_id` identifies one local
  clone and a stable `vault_binding_id` identifies its registry entry; two paths/clones may share
  one `vault_id` and must never collapse into one registration;
- a registry entry preserves `vault_binding_id`, `vault_id`, display name, content-root path,
  local-instance/device provenance, and last-opened metadata; path relocation updates a binding
  without changing logical-vault or local-instance identity;
- `default_vault_binding_id` is explicit and is not inferred from `last_active_vault_ref`;
  compatibility input named `DEFAULT_VAULT_ID` may resolve only when that logical ID maps to one
  unambiguous local binding, otherwise it fails closed;
- `last_active_vault_ref` remains compatibility/history state, not the instance default;
- the one-time registry-schema migration preserves existing picker-only installs by materializing
  a valid legacy `last_active_vault_ref` as `default_vault_binding_id` with explicit
  `legacy_last_active_migration` provenance when no default exists. Later last-active changes never
  mutate the default;
- request selection outranks session selection; session selection outranks the instance default;
  default outranks the one-time legacy restoration result and an explicit legacy bootstrap adapter;
  absence resolves to no-vault;
- unknown, unauthorized, or stale selections fail closed and never fall back silently to another
  vault, CWD, or `./vault`.

### Active context and isolation

`ActiveContextSet` is the public WSP seam. Its first runtime-capable version carries a stable
`context_id`, monotonic `generation`, zero/one/many immutable source bindings, selection
provenance, and optional dimension filter. Every binding keeps its vault identity and instance
provenance. A request resolves one snapshot and all downstream work for that request uses it.

Changing a session selection creates a new generation. In-flight work completes against its old
snapshot; later work sees the new generation. Caches, retrieval results, and settings bundles are
keyed by `context_id` plus generation and every scope-affecting input (server-derived principal,
operational scope, non-reversible selection-capability digest, dimension/filter, and binding set); receipts and writes
record that identity and their target binding. In the current single-user runtime the opaque
selection ID is an expiring bearer capability used in addition to #2223 authentication, while the
server resolves a human or delegated operator-role principal from the auth/GOV boundary and owns
operational scope; `appInstallId` remains separate instance identity, API keys remain credentials,
and client identity/scope strings are never trusted. The local-only bootstrap role is explicitly an
instance-scoped delegated role, not a claim of the human's global identity. MVR-03 owns its missing
producer: existing one-credential installs atomically migrate a credential fingerprint to a private,
opaque `local_operator_role_id`; channel/native bootstrap and fixtures produce the same auth/GOV
record before fail-closed principal enforcement. Auth-disabled loopback/no-key installs bind that
role to a server-proven trusted-loopback subject and keep working; any non-loopback posture requires
governed credential provisioning. Binding plus generation alone is insufficient because two
bearer selections may share both while carrying different scopes or filters. Context is never
carried from one vault to another merely because a selection changed. Cross-vault synthesis
requires an explicit multi-binding context and preserves per-source provenance.
Raw bearer IDs are never logged, receipted, or used directly as cache-key material.

### Dimensions

`dimension_id` is an instance-local opaque identifier with display metadata and ordered
`vault_binding_id` membership. It is useful for filtering or selecting several bindings. It does not grant access,
merge identities, choose a default, or imply a master/satellite topology. GOV evaluates every
member binding independently. Removing a dimension does not remove its vault registrations.

## Reconciliation — do not duplicate

- **#2566** owns the downstream overlay/UI active-vault switcher. It consumes this runtime seam;
  this directory creates no second switcher issue. It stays blocked until the request/session
  runtime contract it needs is delivered.
- **#3156 / #3163** own the Settings Spine and the single-watcher-follows-single-selection
  rebind. MVR-05 temporarily preserves that production behavior only for the legacy picker action;
  generic scoped selections do not drive it. MVR-06 reuses #3163's reload machinery, atomically
  imports the live watcher binding into durable compatibility intent, then retires the bridge while
  the legacy choose/open producer commits compatibility intent before its wake-up hint and the
  supervisor reconciles that durable revision. Governed
  background administration explicitly transitions to multi-binding `explicit` mode; only then do
  picker/default events stop changing lifecycle intent. #3163 is not a multi-active implementation,
  and no duplicate watcher-rebind issue is created here.
- **#2003 / #2311** delivered no-vault startup, runtime switching foundations, and removal of
  silent `./vault` fallback. This capability preserves those contracts.
- **#2356** delivered the v0 `ActiveContextSet` containment adapter. Task 03 evolves that seam;
  it does not create a rival context type.
- **ADR-0055 / #3132** govern concurrent writers to a content vault. Multi-vault selection does
  not reopen or duplicate the multi-writer consistency model.
- host/container mount terminology from #2141 and instance/device/replica identity remain
  unchanged; paths and mounts never become vault identities.

## Implementation tasks

| Order | Task | Adds | Dependency | Initial capability |
| --- | --- | --- | --- | --- |
| 01 | [ESTABLISH_INSTANCE_VAULT_REGISTRY](ESTABLISH_INSTANCE_VAULT_REGISTRY.md) | first-class durable registry and package relocation | none | Sol/high |
| 02 | [RESOLVE_INSTANCE_DEFAULT_VAULT](RESOLVE_INSTANCE_DEFAULT_VAULT.md) | explicit default and fail-closed precedence | 01 | Sol/high |
| 03 | [VERSION_ACTIVE_CONTEXT_SELECTION](VERSION_ACTIVE_CONTEXT_SELECTION.md) | versioned request/session `ActiveContextSet` | 01, 02 | Sol/xhigh |
| 04 | [GROUP_VAULT_BINDINGS_BY_DIMENSION](GROUP_VAULT_BINDINGS_BY_DIMENSION.md) | non-authoritative dimension membership and context resolution | 01, 03 | Sol/high design; Terra/high execution after contract freeze |
| 05 | [ROUTE_REQUESTS_THROUGH_ACTIVE_CONTEXT](ROUTE_REQUESTS_THROUGH_ACTIVE_CONTEXT.md) | production picker/HTTP/retrieval/write migration plus binding-scoped projections | 03, 04, #3163 | Sol/high schema/authority; Terra/high mechanical consumers |
| 06 | [BIND_BACKGROUND_LIFECYCLES](BIND_BACKGROUND_LIFECYCLES.md) | watcher/worker/settings lifecycle bindings and queued-work migration | 02–05, #3163 | Sol/xhigh |
| 07 | [PRESERVE_SINGLE_VAULT_MIGRATION](PRESERVE_SINGLE_VAULT_MIGRATION.md) | compatibility adapters and migration fitness | 04, 05, 06 | Terra/high |
| 08 | [PROMOTE_MULTI_VAULT_RUNTIME_TRUTH](PROMOTE_MULTI_VAULT_RUNTIME_TRUTH.md) | integrated proof, owner-doc/debt promotion, parent closure ledger | 01–07 | Terra/high review; Sol/high if residual architecture risk |

Execution is serial through task 06: tasks 04 and 06 both evolve the instance-registry schema, task
05 introduces binding-keyed projection migrations consumed by task 06, and their producer/preflight
sets are not disjoint. No parallel dispatch is allowed for 04–06. Every merge posts a child receipt
to #2143 and re-evaluates live GitHub and `origin/main` before the next pickup.

## Cross-Task Invariants / Interaction Safety

- A selected vault is a content root with stable identity; mount paths, instances, devices,
  dimensions, defaults, and sessions are not vaults.
- Selection cannot upgrade authority. Every binding is independently authorized by GOV.
- No request, session, worker, restart, or migration silently falls back to another vault,
  `last_active`, CWD, or `./vault` after an explicit selection fails.
- One request uses one immutable context generation. A session-only selection change lets in-flight
  reads keep their snapshot. Binding relocation/removal or authority revision invalidates caches and
  later generations, and every governed mutation must immediately before write re-resolve the target
  binding revision/root and validate a current GOV `DecisionToken`; stale in-flight mutations fail
  without writing or drain under an owner-defined transaction protocol.
- Every read, retrieval result, write, receipt, cache entry, and background binding preserves
  vault identity and context-generation provenance.
- Container registry/default/background intent survives force-recreate on a shared instance-state
  volume and resolves to the identical store from every enabled process.
- Request/session selection never auto-enrols a vault into background work. Background lifecycle
  intent is a distinct durable instance-local binding set; each member is re-authorized at start.
- Background supervisors reconcile durable registry revisions and auth/GOV decision epochs, not
  event delivery: every affected lifecycle drains and re-resolves after relocation, removal,
  revocation, authority-provenance, default, or intent changes. Picker/default/background producers
  commit intent before publishing wake-up hints, and per-operation authorization closes races between
  reconciliation passes.
- Zero, one, and many bindings are all valid. One configured vault behaves as before; no-vault
  behavior remains truthful and idle.
- The durable registry/default/dimension store is instance-local mechanical state; content and
  human knowledge remain in their content vaults.
- Multi-vault topology remains reducible to one vault without loss of meaning, attribution, or
  receipts.
- MVR-01 owns scalar rollback only for its registry/multi-registration schema: it requires one
  validated explicit target and keeps unknown fields plus complete lineage intact. Each later task
  extends rollback preservation or advances the minimum-runtime floor for the state it introduces;
  no earlier child must interpret future default, dimension, or background-intent schemas.
- Once MVR-05 enables binding-keyed database state, a durable minimum-runtime floor blocks every
  scalar pre-MVR rollback, including one-binding instances; rollback must use a compatible image
  and never project shared projection/outbox tables into unsafe scalar semantics.
- Before MVR-05 records that floor or runs its shared-database migration, the channel deployment
  fence inventories, drains, and stops every old shared-DB/outbox client—including API, worker,
  watcher, Heimdal/capture, and enabled auxiliary producers—proves their DB sessions gone, and
  prevents restart. New-image migration cannot run ahead while any incompatible process remains live.

Partial delivery remains fail-closed:

- after task 01 but before task 02, registrations exist but `last_active_vault_ref` remains the
  compatibility behavior; no registration is silently promoted to default;
- after task 02 but before task 03, default resolution is available only through explicit
  background/compatibility adapters; requests do not pretend to be session-scoped;
- after task 03 but before tasks 05/06, migrated callers may use ActiveContextSet while unmigrated
  callers stay on named single-vault adapters; the architecture guard records the mixed state and
  no global "multi-vault delivered" claim is allowed;
- after task 05 but before task 06, the existing picker alone continues to drive #3163's named
  single-watcher bridge while scoped request/session selection does not; task 06 atomically hands
  that live binding to the durable supervisor before disabling the bridge;
- before task 05 enables binding-keyed producers, every pending legacy outbox key is classified and
  scoped/coalesced under the DB fence; identical retries preserve one canonical lineage and
  ambiguous/conflicting rows quarantine, so task 06 cannot backfill a duplicate;
- after task 06, legacy choose/open continues to rebind only `compatibility` lifecycle intent by
  committing it before the supervisor wake-up hint; the first governed background add/remove enters
  `explicit` mode, after which picker and default changes cannot mutate the explicit background set;
- after task 05 but before task 06, the interim scalar worker dispatches a versioned vault-bound row
  only when the row uniquely matches the worker's explicit current single-binding compatibility
  context, current authorization, binding revision, and resolved root; extra remembered registry
  entries do not block that match. Ambiguous/mismatched rows remain pending and unacknowledged, safe global work
  continues, and only task 06 enables multi-binding dispatch and governed quarantine recovery;
- a dimension containing an unknown, stale, or unauthorized member fails the whole production
  context resolution; it never returns a partial set, excludes the member, or substitutes another;
- if one background binding fails, its lifecycle and health remain failed while other bindings
  continue truthfully; no failed work is redirected;
- compatibility adapters are removed only after all producers, consumers, fixtures, preflights,
  and rollback readers have migrated. Task 08 cannot close the parent over residual unnamed debt.

## Capability acceptance

- [ ] Two sessions can concurrently select different registered vaults and use production read
  and governed-write paths without global mutation or cross-talk.
  Verify: `tests/integration/test_multi_vault_request_isolation.py::test_two_sessions_use_distinct_vaults_without_cross_talk`
- [ ] A fresh process resolves an explicit default, while request/session selection overrides it
  without mutating it; invalid explicit selection fails closed.
  Verify: `tests/integration/test_multi_vault_resolution.py::test_resolution_precedence_and_fail_closed_behavior`
- [ ] A dimension selects multiple independently authorized bindings without becoming an
  authority or merging provenance.
  Verify: `tests/integration/test_multi_vault_dimensions.py::test_dimension_preserves_per_binding_authority_and_provenance`
- [ ] Watcher, worker, settings, HTTP, retrieval, and governed-write production entrypoints use
  explicit binding/context resolution; no unapproved process-global vault resolution remains.
  Verify: `tests/architecture/test_multi_vault_context_boundaries.py::test_production_consumers_use_context_seam`
- [ ] No-vault and one-vault installations retain their prior startup, picker, watcher-idle,
  restart, and request behavior.
  Verify: `tests/integration/test_single_vault_compatibility.py::test_existing_single_vault_journey_is_preserved`
- [ ] Owner docs and transition-debt ledger describe shipped reality, and #2143 contains a receipt
  for every child and every acceptance target.
  Verify: doc writeback at `docs/ARCHITECTURE.md :: Active context and vault bindings` + doc
  writeback at `docs/architecture/SBS_TRANSITION_DEBT.md :: multi-vault runtime selection` +
  runtime receipt on GitHub issue `#2143`

## Stop conditions

Stop and repair the governing contract before implementation if a slice would make dimensions an
authority mechanism, store the only registry inside a selected content vault, erase vault or
generation provenance, require a silent fallback, or introduce a second context/selection hub.
An external operator gate is allowed only for the final integrated channel proof; it is not a
reason to leave locally verifiable implementation unfinished.

## Related authority

- `docs/contracts/ACTIVE_CONTEXT_SET.md`
- `docs/CONCEPTS/VAULT_TOPOLOGY_CONTRACT.md`
- `docs/CONCEPTS/VAULT_AND_SETTINGS_CONTEXT.md`
- `docs/CONCEPTS/INSTANCE_DEVICE_AND_REPLICA_CONTRACT.md`
- `docs/SYSTEM_BREAKDOWN_STRUCTURE.md`
- `docs/architecture/SBS_TRANSITION_DEBT.md`
- `docs/SETTINGS_SPINE/REBIND_ON_VAULT_SELECTION.md`
- `docs/VAULT_OPTIONAL_RUNTIME/README.md`
