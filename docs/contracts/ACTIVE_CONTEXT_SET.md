State: V1 runtime seam shipped for request/session selection (MVR-03) with non-authoritative
dimension membership shipped by MVR-04 (#3858); production request-carrier propagation and
binding-keyed persistence remain target state.
Doc role: Contract
Authority: Owns the ActiveContextSet seam for WSP.
Owner subsystem: WSP - Workspace, Scope & Principal Context
Temporal class: strategic
Review cadence: event-driven
Source of truth: mixed
Last reviewed: 2026-08-01

# ActiveContextSet

## Purpose

Declare the active cognitive context as a versioned set of bindings rather than a scalar active vault.

## Shipped V1 seam (MVR-03, #3857)

`active_context_set.v1` is implemented in `app/vault/active_context_v1.py::ActiveContextSetV1`
as one immutable, generation-stamped snapshot. The v0 adapter in
`app/vault/active_context.py` remains the transitional projection for callers that still only
hold a scalar `VaultContext`; V1 is the same seam versioned forward, not a rival type.

Shipped fields: `context_id`, monotonic `generation`, explicit `WorkspaceState`
(bound workspace id **or** the typed `no_workspace` state), server-derived `scope` with the
canonical `"default"` fallback, `sphere_memberships`, `situated_identity`,
`principal_context`, separate `instance_identity`, zero/one/many immutable
`source_bindings` each carrying its own `binding_revision` and `authorization_epoch`,
`registry_revision`, snapshot `authorization_epoch`, `selection_provenance`,
non-reversible `selection_capability_digest`, `topology_posture`, `expires_at`, and a typed
`posture` (`healthy` | `degraded`) with a bounded `degraded_reason`.
`dimension_filter` is shipped by MVR-04 (#3858) as the typed `DimensionFilter` provenance
record — the resolved `dimension_id` plus its `dimension_revision`, and nothing else. It is
absent for an explicitly enumerated selection. The revision is recorded provenance, not a
shipped staleness check: nothing re-reads it against current registry truth. What protects a
selection whose dimension changed underneath it is the ordinary per-binding GOV
authorization that runs on every resolution. No client string can become one: the only
producer is the server-side resolver over an id already stored in the instance registry, and
it is never re-expanded, so it cannot widen a snapshot.

Shipped behaviour:

- **Selection store.** `app/instance/context_selection.py::ContextSelectionStore` is a
  TTL-bound, ephemeral, in-process map keyed by a high-entropy opaque server-minted
  `context_selection_id`. In the current single-user product that id is an expiring **bearer
  capability**, used *in addition to* the #2223 Companion authentication gate — not a claim
  of multi-user identity. Possession of a different id is required to reach a different
  session's selection.
- **Selection stores no authority.** The record has no action, write class, or permission
  field. Each request derives those independently from the server-owned endpoint/command
  contract and passes them to GOV as separate decision inputs, which is what lets one
  selection serve a separately authorized read and a separately authorized write without an
  over-broad stored scope or a scope mismatch.
- **Per-binding GOV.** `app/governance/binding_authority.py` authorizes every member binding
  independently. A deny raises rather than returning a partial set: no snapshot containing a
  denied binding is ever reissued.
- **Server-derived context only.** The production endpoints
  (`POST`/`PUT`/`GET`/`DELETE /api/companion/active-context/selection`) accept explicit
  binding-selection intent and nothing else. A client-authored workspace, scope, sphere
  membership, situated identity, principal, action, permission, or arbitrary dimension
  projection is rejected with `422`, never silently ignored. MVR-04 adds exactly one further
  admissible input: one `dimension_id` that already exists in the instance registry, which the
  server resolves through the locked dimension service into the same explicit binding set. An
  unknown, stale, or unauthorized member fails the whole request; explicit bindings combined
  with a `dimension_id` are refused rather than merged. Workspace, scope, spheres, and situated
  identity are derived by `app/instance/active_context_service.py` from the authenticated WSP
  context; principal comes from auth/GOV. Workspace is never inferred from vault, path,
  scope, or principal.
- **Generation transitions.** Switching a session's bindings advances only that session's
  generation; other sessions and the instance default are untouched. In-flight work holds an
  already-resolved immutable snapshot, so there is no in-flight rebinding. A changed binding
  revision, registry revision, or still-authorizing GOV verdict rotates to a new generation
  plus a cache-invalidation descriptor before the next snapshot is issued.
- **Truthful expiry and restart.** A request that omits a selection resolves the explicit
  instance default or no-vault. A request presenting an expired, unknown, or pre-restart id
  fails closed with a reselection-required error; it never falls through to a default, to
  last-active state, or to another session.
- **Full-context cache identity — shipped as an unwired seam.**
  `app/retrieval/context_cache.py` derives an identity from every context-affecting input
  plus the effective settings-bundle digest (`app/vault/settings_bundle.py`), never from
  binding plus generation alone, and raw bearer ids are never key material — only the digest
  is. **This is not yet the key the production retrieval path uses.**
  `app/retrieval/hybrid.py` still keys its in-memory document store by the durable index
  generation alone, and MVR-05B (#3860) owns migrating production retrieval onto this
  identity together with the request carrier that supplies the snapshot.
- **Principal.** Derived only from the auth/GOV-owned delegated-role or human record; see
  `docs/SECURITY.md :: Security` for the shipped credential/loopback/proxy subject mapping,
  the separate instance identity, and fail-closed principal resolution.

## Shipped dimension membership (MVR-04, #3858)

Durable, non-authoritative grouping over registered bindings, owned by
`docs/CONCEPTS/VAULT_TOPOLOGY_CONTRACT.md :: Dimensions` and implemented in
`app/instance/vault_dimensions.py`. Resolution is all-or-nothing and authorizes every member
independently through the same `app/governance/binding_authority.py` seam, with the calling
contract's own decision inputs; the dimension is never one of them. What a snapshot stores is the
resolved explicit binding set plus `dimension_filter` provenance — a dimension grants nothing.

Still target state after MVR-04: production request-header carrier propagation
(`X-Active-Context-Session` / `X-Active-Context-Override`) is owned by MVR-05B (#3860) and
binding-keyed persistence by MVR-05A.

## Inputs

- Workspace selection or no-workspace mode.
- Scope and sphere bindings.
- Situated identity and principal context.
- Topology posture: single-node, offline-only, cloud-assisted, central/satellite candidate.
- Zero, one, or many source/vault/folder/repository bindings.

## Outputs

- ActiveContextSet identifier and generation/version.
- Effective workspace, scope, sphere, situated identity, principal, and topology posture.
- Source-binding list treated as implementation detail.
- Typed healthy/degraded posture: ordinary no-vault is a healthy zero-binding state; unavailable,
  invalid, unauthorized, or stale requested binding is degraded with a bounded reason.

## Commands

- Select context.
- Add or remove binding.
- Transition generation atomically.
- Validate context membership and topology posture.

## Queries

- What context is active?
- Which principal/scope/sphere applies?
- Which bindings are available?
- Which topology restrictions apply?

## Events

- `active_context.changed`
- `active_context.binding_added`
- `active_context.binding_removed`
- `active_context.degraded`

## Invariants

- Vault/source binding is not architectural identity.
- Generation/version changes atomically with context transition.
- Zero-binding and many-binding modes are valid target states.
- WSP does not grant permission to act; GOV owns admissibility.

## Multi-Vault Runtime V1 Decision

This owner contract delegates the decided implementation-level V1 schema, transition, persistence,
and migration details to `docs/MULTI_VAULT_RUNTIME/README.md` and its bounded task specifications.
That capability specification is subordinate to this contract's WSP/GOV boundary and may not widen
authority. V1 requires an opaque context ID, monotonic generation, explicit workspace identity (or
a typed no-workspace state), zero/one/many immutable source bindings, server-derived principal,
cognitive operational scope, sphere memberships, situated identity, topology posture, selection provenance,
expiry where applicable, non-reversible selection-capability digest, and a typed degraded posture
(`healthy` or `degraded`) with a bounded machine-readable reason when degraded. A zero-binding
healthy no-vault context is distinct from an unavailable, invalid, unauthorized, or stale binding;
the latter cannot be represented as an ordinary empty set. Cache and receipt identity
includes workspace and every scope-affecting input; each binding is independently GOV-authorized. Current-state
owner docs remain shipped truth until the relevant implementation child writes them back.

Endpoint action, write class, and required permission are separate GOV decision inputs. They are
not WSP `scope`, do not mutate the selected cognitive context, and are recorded separately in
authority decisions/receipts.

## Allowed Producers

- HIX human selection surfaces.
- Configuration/import adapters through EBF.
- SFC topology state where relevant.

## Allowed Consumers

- HIX, HKA, SIP, GOV, RCA, MEM, CAO, EXE, SFC, OEF.
- EBF may consume only the bounded source-binding/topology projection needed to configure an
  adapter; PDM may consume only context identity/revision plus bounded source-binding identity and
  binding revision needed to namespace and persist mechanical state. It never receives a host path or
  treats binding identity as authority. Neither subsystem derives principal/permission or owns WSP
  semantics.

## Forbidden Use

- Do not infer authority from vault path.
- Do not pass `activeVault`/`vaultPath` as a public cognitive-context contract.
- Do not use source binding as durable artifact identity.

## Failure Modes

- Scope collapse into active vault.
- Cross-workspace memory or retrieval leakage.
- Principal context inferred from filesystem location.

## Transitional Implementation Notes

Current runtime may still carry active vault/path concepts. New work should wrap them as source bindings inside ActiveContextSet and avoid widening path-shaped public contracts.

## Open Questions

- Which context transitions need human review versus policy-only validation?

## Linked Source-Of-Truth Docs

- `docs/SYSTEM_BREAKDOWN_STRUCTURE.md`
- `docs/architecture/SBS_OPERATIONALIZATION_PLAN.md`
- `docs/architecture/SBS_TRANSITION_DEBT.md`
- `docs/CONCEPTS/VAULT_AND_SETTINGS_CONTEXT.md`
- `docs/CONCEPTS/STATE_AXES_CONTRACT.md`
