State: Target-state contract stub; not fully implemented.
Doc role: Contract stub
Authority: Owns the target ActiveContextSet seam for WSP.
Owner subsystem: WSP - Workspace, Scope & Principal Context
Temporal class: strategic
Review cadence: event-driven
Source of truth: mixed
Last reviewed: 2026-06-21

# ActiveContextSet

## Purpose

Declare the active cognitive context as a versioned set of bindings rather than a scalar active vault.

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
