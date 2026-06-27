# Boundary: WSP — Workspace, Scope & Principal Context

State: Boundary charter — Draft (control-boundary contract; docs-only, not a runtime service declaration)

**Source docs:** [SBS](../SYSTEM_BREAKDOWN_STRUCTURE.md) ·
[context packet](../foundation/yggdrasil-architecture-context-packet.md) ·
[doctrine](../foundation/00-yggdrasil-doctrine.md) ·
[functional ontology](../architecture/functional-ontology.md) ·
[semantic dimensions](../architecture/semantic-dimensions.md) ·
[CrossScopeFlow](../architecture/cross-scope-flow.md) ·
[traceability matrix](../architecture/traceability-matrix.md)

**Canonical separation rule:** WSP owns **current situated context**. (SFC owns distributed state
over time.) Context is not identity, and context is not permission.

## Purpose

Own the active cognitive context as a governed **set of bindings** — workspace, scope, sphere,
principal, device/node posture — for the current session/operation.

## Owns

- Active workspace binding (`Workspace`), active scope binding, sphere binding (`Sphere`).
- Principal binding (`Principal`) and situated identity for the current session.
- Current device/node posture for the current operation (`ActiveContextSet`).

## Does not own

- Permission / authority → **GOV**.
- Artifact meaning → **SIP**/**HKA**; durable identity → **HKA** (anchors) / **SIP** (semantic identity).
- Sync mechanics → **SFC**; retrieval ranking → **RCA**.

> **Ownership-drift rule.** WSP states *what context is active*; it does not decide what that context
> is *allowed* to do. Permission is a GOV decision; WSP supplies context to GOV and never grants access itself.

## Inputs

- Workspace definitions, scope/sphere/principal bindings, topology posture (HIX selection, SFC status).

## Outputs

- `ActiveContextSet`, routing context, degraded-mode posture — consumed by GOV, RCA, MEM, CAO, EXE, SFC.

## Calls allowed

- **SIP** (scope/context semantics), **GOV** (supply principal/scope for decisions), **SFC** (read replica/topology status), **PDM** (configuration contracts).

## Calls forbidden

- **Granting access** — WSP cannot authorize; it cannot stand in for a GOV `PolicyDecision`.
- **Defining meaning/identity** — must not assign `source_role` or artifact identity.
- **Treating vault/folder/device as identity** — context bindings are not the artifact's identity.

## Required metadata

WSP **owns the binding facet of `scope_binding`** (which scopes/principal/device are active now) and
carries `sensitivity` context. It does **not** own `authority_state` (GOV) or `sync_state` (SFC); it
must keep `scope_binding` distinct from permission.

## Policy obligations

- Provide context to GOV; never decide permission. Cross-scope use is a GOV `CrossScopeFlow`, not a WSP binding.
- Support no-vault / no-workspace / multi-root modes without conferring authority.

## Provenance obligations

- Carry the active scope/principal context that SIP/GOV use as provenance context for actions.
- Context changes (e.g. switching workspace) do not alter any artifact's identity or provenance.

## Invariants owned

- Context is not identity (matrix #2).
- Scope is frame/audience/policy/provenance context, not merely vault/folder/device (matrix #2).
- WSP cannot grant access on its own (matrix #1, #2).
- Cross-scope use requires a typed `CrossScopeFlow` (matrix #1, #6).

## Failure modes

- **Context-as-identity:** closing a workspace changing artifact identity.
- **`activeVault` collapse:** scope reduced to a scalar vault/folder/device pointer.
- **Self-granting access:** WSP authorizing use without GOV.

## Required tests

Future test names for the invariant registry ([#2550](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2550)) / eval corpus ([#2551](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2551)); skeletons in [#2552](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2552). No tests created here.

- `context_not_identity`
- `scope_not_vault_only`
- `cross_scope_only_via_flow`

## Related ADRs

- ADR-0015 (authority-first target SBS).
- The doctrine/ontology/boundary decisions affecting this boundary (ADR-0026–ADR-0039, [#2549](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2549)) are mapped per boundary by the [traceability matrix](../architecture/traceability-matrix.md).

## Related schemas/contracts

- metadata bundle (`scope_binding`) — [#2544](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2544); `CrossScopeFlow` — [#2548](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2548); existing `ActiveContextSet` (SBS Part 5).

## Related issues

- Charter: [#2543](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2543) · Epic: [#2533](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2533) · Index: [README.md](README.md)
