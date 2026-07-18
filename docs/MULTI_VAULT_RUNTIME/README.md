# Multi-vault runtime selection

State: Active future-state capability specification. Parent validation hub **#2143** remains
blocked and must never be claimed as an implementation issue. The 17 executable children are filed
as **#3853–#3869**; only #3853 is initially pickup-ready. No text in this directory claims that
multi-vault runtime behavior is shipped.
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
enabled consumer. Startup and every registration/relocation transaction also resolve the override
and all known/candidate content roots and fail closed when the registry file or any ancestor/
descendant alias lies inside a content vault. This disjointness check runs again when a new root is
introduced, so an override chosen before the first registration cannot become content-owned later.

Per-channel registry isolation is not sufficient because current containers can see shared host
roots. A separate host-local **channel ownership ledger** is mounted consistently into every channel
and native runtime. Under one global mode-`0600` lock it records `channel_id`, stable binding, and
HMAC fingerprints of canonical filesystem identity plus its canonical ancestor-identity chain
(never a raw host path). Duplicate physical identity under different bindings is always a conflict;
ancestor/descendant overlap conflicts across different channel/native ownership domains, including
after symlink or bind-mount alias resolution. One channel/instance may register initialized parent
and child vaults only under the existing nested-vault boundary contract: parent traversal prunes the
child and effects target one explicit binding. One CSPRNG-generated,
host-global ledger key lives mode `0600` in private host app-data outside every channel volume and
is mounted read-only into all channel/native consumers; generation, permissions, durable backup,
and key ID are host-bootstrap truth. Missing, ephemeral, channel-specific, mismatched, or permissive
key state blocks claims and lifecycle start. Key rotation holds the global fence, drains all owners,
re-fingerprints every canonical root, and atomically advances ledger plus key generation before any
owner resumes; interrupted rotation recovers one complete generation and never compares mixed keys.
Registration uses a recoverable pending→registry-commit→active reservation protocol; lifecycle start proves the
active reservation still matches its channel and root. The same physical content root cannot be
active in two dev/test/prod/native ownership domains simultaneously, and nested roots cannot straddle
those domains. Relocation is implemented but capability-gated until MVR-06C proves every foreground
and background consumer uses the matching shared/exclusive effect-lease order. Explicit transfer
remains capability-gated until MVR-05C activates foreground read/write ownership fencing. It then
uses a production-derived source-channel inventory to close foreground ingress, drain and stop every
vault-bound watcher, scalar worker, settings reload, outbox/ingest, Heimdal projection, API/CLI, and
other lifecycle/effect producer, and installs a restart fence that rejects the old channel lease
before committing release and claiming the destination. Vault-independent global work is classified
and unaffected. Crashes leave a
blocking recoverable reservation, never two owners or an unowned running lifecycle.

The first MVR-01 rollout is a host-wide ownership migration, not a per-channel best effort. Before
any new reservation is accepted, deployment acquires a global bootstrap fence, blocks legacy
selection/registry ingress, inventories every dev/test/prod Compose deployment and native runtime
that can reach the host roots, and drains or stops all of their registry and lifecycle writers. It
then rejects any pre-existing root collision and seeds one ledger generation with every legacy
channel/native owner before opening claims. A seeded old channel may resume before its own upgrade
only on that fixed root behind mutation-denying ingress; a native or channel runtime that cannot be
fenced remains stopped. Missing inventory, a racing writer, ambiguous ownership, or duplicate roots
blocks every MVR-01 claim rather than letting an upgraded channel race an old image.

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
- an initialized registry entry preserves `vault_binding_id`, `vault_id`, display name, content-root
  path, local-instance/device provenance, and last-opened metadata; path relocation updates a binding
  without changing logical-vault or local-instance identity;
- a selected existing uninitialized root may be represented without writing into it by a provisional
  read-only registration whose stable binding/local-instance identity and root fingerprint are
  registry-owned while `vault_id` remains null; only an explicit initialize gesture may complete
  that same binding's vault identity, and writes/initialized-only lifecycles fail closed beforehand;
- `default_vault_binding_id` is explicit and is not inferred from `last_active_vault_ref`;
  compatibility input named `DEFAULT_VAULT_ID` may resolve only when that logical ID maps to one
  unambiguous local binding, otherwise it fails closed;
- `last_active_vault_ref` remains compatibility/history state, not the instance default;
- the one-time registry-schema migration preserves existing picker-only installs by materializing
  a valid legacy `last_active_vault_ref` as `default_vault_binding_id` with explicit
  `legacy_last_active_migration` provenance when no default exists. Later last-active changes never
  mutate the default;
- on a fresh empty registry, the first initialize or first open-existing transaction records its
  stable initialized/provisional binding as the default exactly once, preserving restart without
  turning later picker or last-active changes into default mutations. In 05B, first initialize uses
  a single-use authenticated bootstrap precondition bound to the canonical target, empty registry
  revision, and no-compatibility posture; it revalidates under the ownership/registry lock and is
  failure-atomic rather than depending on a compatibility binding that does not yet exist;
- a one-request `X-Active-Context-Override` selection outranks the retained
  `X-Active-Context-Session` selection; session selection outranks the instance default; default
  outranks an explicit legacy bootstrap adapter; absence resolves to no-vault. The override is
  never persisted into the session. The
  one-time legacy restoration is a migration only, not a later runtime-precedence source;
- unknown, unauthorized, or stale selections fail closed and never fall back silently to another
  vault, CWD, or `./vault`.

### Active context and isolation

`ActiveContextSet` is the public WSP seam. Its first runtime-capable version carries a stable
`context_id`, monotonic `generation`, explicit workspace identity or typed no-workspace state,
zero/one/many immutable source bindings, selection provenance, and optional dimension filter.
Workspace is never inferred from vault, path, scope, or principal. Every binding keeps its vault
identity and instance provenance. A request resolves one snapshot and all downstream work for that
request uses it.

Changing a session selection creates a new generation. In-flight work completes against its old
snapshot; later work sees the new generation. Caches, retrieval results, and settings bundles are
keyed by `context_id` plus generation and every context-affecting input (workspace/no-workspace,
server-derived principal,
cognitive operational scope, sphere memberships, situated identity, non-reversible selection-
capability digest, dimension/filter, binding set, and the effective per-binding/request-wide settings
bundle revision or digest). A Settings
Spine hot reload atomically invalidates affected entries or rotates the context generation before a
later lookup; model, reranking, threshold, or other behavior-sensitive results can never reuse a
pre-reload cache identity. Receipts and writes record that identity and their target binding. In the
current single-user runtime the opaque
  selection ID is an expiring bearer capability used in addition to #2223 authentication, while the
  server resolves a human or delegated operator-role principal from the auth/GOV boundary and owns
  action, write class, and required permission per request. The selection record binds principal/
  instance/bindings plus its cognitive dimensions but stores no operation authority; the same
  selection can support separately authorized read and write calls without mutating WSP scope or
  widening either. `appInstallId` remains separate instance identity, API keys remain credentials,
and client identity/scope strings are never trusted. The local-only bootstrap role is explicitly an
instance-scoped delegated role, not a claim of the human's global identity. MVR-03 owns its missing
producer: existing one-credential installs atomically migrate a credential fingerprint to a private,
opaque `local_operator_role_id`; channel/native bootstrap and fixtures produce the same auth/GOV
record before fail-closed principal enforcement. Auth-disabled/no-key installs bind that role to
either a server-proven trusted-loopback subject or the existing server-configured, middleware-
validated Companion proxy subject and keep working; client forwarding headers can establish
neither. Any other non-loopback posture requires governed credential provisioning. Binding plus
generation alone is insufficient because two
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
- **MVR-01B #3854 and MVR-01C #3855** first own the protected instance-state substrate, final
  legacy-writer fence/export, guarded authority cutover, rollback isolation, and applicable runtime
  floor. **#3156 / #3163** then own the Settings Spine compatibility rebind as three serial children:
  dormant durable record, dormant watcher reconciler, and picker/API activation plus aggregate proof.
  SETTINGS-05 consumes MVR-owned protected authority and never creates a parallel volume, migration,
  export, backup, or rollback floor. MVR-05 temporarily preserves the activated production behavior
  only for the legacy picker action;
  generic scoped selections do not drive it. MVR-06 reuses #3163's reload machinery, atomically
  imports the live watcher binding into durable compatibility intent, then retires the bridge while
  the legacy choose/open producer and replacement supervisor preserve the mutation-gate/final-scan/
  quiesce → commit → resume protocol. Wake-up hints remain non-authoritative. Governed
  background administration explicitly transitions to multi-binding `explicit` mode; only then do
  picker/default events stop changing lifecycle intent. #3163 remains a blocked validation hub, is
  not a multi-active implementation, and no duplicate watcher-rebind issue is created here.
- **#2003 / #2311** delivered no-vault startup, runtime switching foundations, and removal of
  silent `./vault` fallback. This capability preserves those contracts.
- **#2356** delivered the v0 `ActiveContextSet` containment adapter. Task 03 evolves that seam;
  it does not create a rival context type.
- **ADR-0055 / #3132** govern concurrent writers to a content vault. Multi-vault selection does
  not reopen or duplicate the multi-writer consistency model.
- host/container mount terminology from #2141 and instance/device/replica identity remain
  unchanged; paths and mounts never become vault identities.

## Implementation tasks

| Order | Task | Issue | Adds | Dependency | Initial capability |
| --- | --- | --- | --- | --- | --- |
| 01A | [ESTABLISH_INSTANCE_VAULT_REGISTRY](ESTABLISH_INSTANCE_VAULT_REGISTRY.md#bounded-implementation-issue-decomposition) | [#3853](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3853) | registry identity/store, package relocation, recovery, and concurrency | none | Sol/high |
| 01B | [ESTABLISH_INSTANCE_VAULT_REGISTRY](ESTABLISH_INSTANCE_VAULT_REGISTRY.md#bounded-implementation-issue-decomposition) | [#3854](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3854) | durable volume migration, ownership/key fencing, and scalar-compatible rollback export | 01A | Sol/xhigh |
| 01C | [ESTABLISH_INSTANCE_VAULT_REGISTRY](ESTABLISH_INSTANCE_VAULT_REGISTRY.md#bounded-implementation-issue-decomposition) | [#3855](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3855) | scalar rollback gateway, exports, and roll-forward lineage | 01B | Sol/xhigh |
| 02 | [RESOLVE_INSTANCE_DEFAULT_VAULT](RESOLVE_INSTANCE_DEFAULT_VAULT.md) | [#3856](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3856) | explicit default and fail-closed precedence | 01A–01C | Sol/high |
| 03 | [VERSION_ACTIVE_CONTEXT_SELECTION](VERSION_ACTIVE_CONTEXT_SELECTION.md) | [#3857](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3857) | versioned request/session `ActiveContextSet` | 01A–01C, 02 | Sol/xhigh |
| 04 | [GROUP_VAULT_BINDINGS_BY_DIMENSION](GROUP_VAULT_BINDINGS_BY_DIMENSION.md) | [#3858](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3858) | non-authoritative dimension membership and context resolution | 01A–01C, 03 | Sol/high design; Terra/high execution after contract freeze |
| 05A | [ROUTE_REQUESTS_THROUGH_ACTIVE_CONTEXT](ROUTE_REQUESTS_THROUGH_ACTIVE_CONTEXT.md#bounded-implementation-issue-decomposition) | [#3859](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3859) | binding-keyed persistence cutover | 03, 04 | Sol/xhigh |
| 05B | [ROUTE_REQUESTS_THROUGH_ACTIVE_CONTEXT](ROUTE_REQUESTS_THROUGH_ACTIVE_CONTEXT.md#bounded-implementation-issue-decomposition) | [#3860](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3860) | request ingress, picker, reads, retrieval, and read-race fence | 05A, #3163 | Sol/high; Terra/high mechanical consumers |
| 05C | [ROUTE_REQUESTS_THROUGH_ACTIVE_CONTEXT](ROUTE_REQUESTS_THROUGH_ACTIVE_CONTEXT.md#bounded-implementation-issue-decomposition) | [#3861](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3861) | governed write target/token/receipt migration | 05B | Sol/xhigh |
| 05D | [ROUTE_REQUESTS_THROUGH_ACTIVE_CONTEXT](ROUTE_REQUESTS_THROUGH_ACTIVE_CONTEXT.md#bounded-implementation-issue-decomposition) | [#3862](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3862) | outbox producers, interim worker delivery, aggregate proof, owner docs | 05C | Sol/high; Terra/high mechanical consumers |
| 06A | [BIND_BACKGROUND_LIFECYCLES](BIND_BACKGROUND_LIFECYCLES.md#bounded-implementation-issue-decomposition) | [#3863](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3863) | durable intent, service role, admin, and runtime floor | 05D, #3163 | Sol/xhigh |
| 06B | [BIND_BACKGROUND_LIFECYCLES](BIND_BACKGROUND_LIFECYCLES.md#bounded-implementation-issue-decomposition) | [#3864](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3864) | #3163 compatibility bridge handoff and settings rebind | 06A, #3163 | Sol/xhigh |
| 06C | [BIND_BACKGROUND_LIFECYCLES](BIND_BACKGROUND_LIFECYCLES.md#bounded-implementation-issue-decomposition) | [#3865](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3865) | isolated zero/one/many lifecycle supervision | 06B | Sol/xhigh |
| 06D | [BIND_BACKGROUND_LIFECYCLES](BIND_BACKGROUND_LIFECYCLES.md#bounded-implementation-issue-decomposition) | [#3866](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3866) | queued-work convergence and aggregate proof | 06C | Sol/xhigh |
| 07A | [PRESERVE_SINGLE_VAULT_MIGRATION](PRESERVE_SINGLE_VAULT_MIGRATION.md#bounded-implementation-issue-decomposition) | [#3867](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3867) | compatibility inventory, isolated smoke, and no/one-vault fitness | 04, 05A–05D, 06A–06D | Terra/high |
| 07B | [PRESERVE_SINGLE_VAULT_MIGRATION](PRESERVE_SINGLE_VAULT_MIGRATION.md#bounded-implementation-issue-decomposition) | [#3868](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3868) | runtime floor, reservation, governed topology reduction, and rollback | 07A | Sol/xhigh |
| 08 | [PROMOTE_MULTI_VAULT_RUNTIME_TRUTH](PROMOTE_MULTI_VAULT_RUNTIME_TRUTH.md) | [#3869](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3869) | integrated proof, owner-doc/debt promotion, parent closure ledger | 01A–01C, 02–04, 05A–05D, 06A–06D, 07A–07B | Terra/high review; Sol/high if residual architecture risk |

Execution is serial through issue 06D: task 04 and the 05/06 families evolve shared registry,
projection, auth, queue, and lifecycle contracts, and their producer/preflight sets are not disjoint.
No parallel dispatch is allowed through 06D. Every merge posts a child receipt
to #2143 and re-evaluates live GitHub and `origin/main` before the next pickup.

## Cross-Task Invariants / Interaction Safety

- A selected vault is a content root with stable identity; mount paths, instances, devices,
  dimensions, defaults, and sessions are not vaults.
- Selection cannot upgrade authority. Every binding is independently authorized by GOV.
- Foreground request resolution, reads, and writes also require the MVR-01 host-global ownership
  ledger to hold the active lease for the exact channel, binding, and canonical-root fingerprint;
  a stale source registry/selection cannot access a root after cross-channel transfer and restart.
- No request, session, worker, restart, or migration silently falls back to another vault,
  `last_active`, CWD, or `./vault` after an explicit selection fails.
- One request uses one immutable context generation. A session-only selection change lets in-flight
  reads keep their snapshot. Binding relocation/removal or authority revision invalidates caches and
  later generations. Every foreground read/write and background content/dispatch/ack effect acquires
  the host-global ownership fence and then a cross-process shared per-binding effect lease, releases
  the global fence after final target/auth revalidation, and holds the shared lease through I/O,
  cache/response/ack, and receipt. Relocation, removal, transfer, and revocation use the same order
  with the matching exclusive lease; stale effects fail before access or a change waits for an
  already-authorized effect to complete under the prior revision.
- An expired/stale explicit session bearer always requires visible reselection; an ephemeral server
  store cannot infer its former target from a sole remaining/default binding. Normal default
  resolution for a new client with no stale explicit intent is a separate path.
- Every read, retrieval result, write, receipt, cache entry, and background binding preserves
  vault identity and context-generation provenance.
- Many-binding requests resolve settings before effects: binding-local values remain inside each
  binding's isolated sub-operation, and every registry-classified request-wide behavior setting
  must have one identical typed effective value across all participating bindings. A conflict fails
  the whole request before reads, cache/model/retrieval work, or partial results; binding iteration
  order is never settings precedence.
- Container registry/default/background intent survives force-recreate on a shared instance-state
  volume and resolves to the identical store from every enabled process.
- Request/session selection never auto-enrols a vault into background work. Background lifecycle
  intent is a distinct durable instance-local binding set; each member is re-authorized at start by
  an auth/GOV-produced, least-privilege instance background-runtime role delegated from the local
  operator role. Missing, stale, or ambiguous delegation blocks lifecycle startup.
- Background supervisors reconcile durable registry revisions and auth/GOV decision epochs, not
  event delivery: every affected lifecycle drains and re-resolves after relocation, removal,
  revocation, authority-provenance, default, or intent changes. Compatibility picker/default changes
  keep mutation ingress gated and the prior lifecycle final-scanned/quiescent until durable commit,
  then resume; wake-up hints are never the transition authority. Per-operation authorization closes
  races between reconciliation passes.
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

- after issue 01B but before 01C atomically installs the complete multi-registration rollback floor,
  the prepared registry remains non-authoritative and the legacy scalar store stays authoritative:
  every new-schema and registration-#2 picker/API/CLI/import/bootstrap/direct-service producer fails
  before reservation or mutation; 01C performs guarded authority cutover only with the rollback
  gateway/guards, current export, and roll-forward lineage;
- after issue 01C but before task 02, registrations exist but `last_active_vault_ref` remains the
  compatibility behavior; no registration is silently promoted to default;
- after issue 01B and until issue 05C advances the foreground-ownership floor, cross-channel transfer
  is implemented but production transfer requests fail capability-not-ready; the source lease cannot be
  released while legacy foreground read/write paths remain unfenced. Once activated, a journaled
  transfer-only reservation excludes the root while source registration is retired to a tombstone and
  destination registration/lineage becomes durable, so ordinary duplicate-root admission is never
  bypassed and two live registrations/owners never coexist. MVR-06B upgrades the transfer journal
  before retiring the #3163 bridge so later transfers repair the then-authoritative background intent
  before source retirement and restart cannot resurrect a transferred binding;
- after issue 01B and until issue 06B proves both foreground and background consumer floors, active
  registration removal is implemented but production removal fails capability-not-ready without
  changing registry/revision/ownership; only 06B may activate its drain/tombstone/release sequence.
  Removal retains immutable binding/root/logical lineage, and later reactivation/rehome cannot mint
  around historical receipt/outbox provenance;
- after task 02 but before task 03, default resolution is available only through explicit
  background/compatibility adapters; requests do not pretend to be session-scoped;
- after task 03 but before issues 05A–06D, migrated callers may use ActiveContextSet while unmigrated
  callers stay on named single-vault adapters; the architecture guard records the mixed state and
  no global "multi-vault delivered" claim is allowed;
- after issue 05B but before issue 06B, the existing picker and every MVR-02 default set/clear
  producer prepare the SETTINGS-05C-activated monotonic cross-process compatibility revision.
  Compatibility-
  mutation ingress is gated/drained first; an
  enabled watcher scans the old root and acknowledges quiescence on the prepared revision while
  retaining durable old-root event observation through commit, then performs the bracketing
  post-commit scan/buffer drain and receipt before it applies/reloads and resumes B. An
  intentionally disabled/absent watcher is represented by durable `no_lifecycle` posture
  and requires no process acknowledgement. An in-process event is only a hint and scoped request/
  session selection does not mutate the record. A default mutation cannot commit first and notify
  later: it uses the same bracketing transaction or fails `capability_not_ready` without changing the
  default. Issue 06B atomically hands
  that live binding plus the MVR-05 scalar worker to versioned durable singleton/empty state before
  disabling the bridge or enabling intent mutation;
- after issue 05B but before issue 05C, scoped session/override writes and any write whose resolved
  target differs from the sole freshly validated compatibility binding fail capability-not-ready
  before the compatibility translator or any effect. A migrated picker client sends an opaque
  expected-binding/revision precondition on mutations; it grants no authority and fails before
  effect if another client moved the compatibility binding. Only truly legacy carrier/precondition-
  free single-binding writes to that exact binding retain the prior journey; 05C replaces this seal
  with governed explicit-target writes;
- before issue 05A enables the first binding-keyed compatibility producer, every pending legacy
  outbox key is classified and
  scoped/coalesced under the DB fence; identical retries preserve one canonical lineage and
  ambiguous/conflicting rows quarantine. Issue 05D retires the compatibility translator only after
  native producer migration, and issue 06D cannot backfill a duplicate;
- before issue 05A enables scalar vault-bound dispatch, every enabled GOV-revocation producer uses
  the host-global ownership fence and matching exclusive binding lease. The 05A worker holds the
  shared lease through dispatch/ack/receipt, so revocation cannot cross that effect window; 05B
  extends the already-live fence to foreground read producers;
- after issue 06B, legacy choose/open and default set/clear continue to rebind only `compatibility`
  lifecycle intent with the same mutation-gate/pre-commit scan+buffer/quiesce → commit →
  post-commit old-root scan+buffer drain → resume transaction. Default clear re-runs the canonical
  default → registered legacy bootstrap → no-vault precedence; the first governed background
  add/remove enters `explicit` mode, after which picker and default changes cannot mutate the explicit
  background set;
- from issue 05A through issue 06B, the interim scalar worker dispatches a versioned vault-bound row
  only when the row uniquely matches the worker's explicit current single-binding compatibility
  context, current authorization, binding revision, and resolved root, and it holds the binding's
  shared effect lease from final validation through dispatch, acknowledgement, and receipt. Extra
  remembered registry entries do not block that match. Ambiguous/mismatched rows remain pending and
  unacknowledged, safe global work continues, and only issue 06D enables multi-binding dispatch and
  governed quarantine recovery;
- a dimension containing an unknown, stale, or unauthorized member fails the whole production
  context resolution; it never returns a partial set, excludes the member, or substitutes another;
- if one background binding fails, its lifecycle and health remain failed while other bindings
  continue truthfully; no failed work is redirected;
- compatibility adapters are removed only after all producers, consumers, fixtures, preflights,
  and rollback readers have migrated. Task 08 cannot close the parent over residual unnamed debt.

## Capability acceptance

- [ ] Two sessions can concurrently select different registered vaults and use production read
  and governed-write paths without global mutation or cross-talk; a one-request override outranks
  its retained session without mutating it.
  Verify: `tests/integration/test_multi_vault_request_isolation.py::test_two_sessions_use_distinct_vaults_without_cross_talk` +
  `tests/api/test_active_context_resolution.py::test_request_override_header_outranks_session_without_mutating_it` +
  `tests/integration/test_multi_vault_request_isolation.py::test_parent_request_context_acceptance`
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
