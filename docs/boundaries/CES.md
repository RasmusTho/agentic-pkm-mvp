# Boundary: CES — Contract & Evolution Stewardship

State: Boundary charter — Draft (cross-cutting stewardship practice; docs-only, **not** a runtime subsystem or control boundary)

**Kind:** Cross-cutting **stewardship practice** — *not* an ordinary Level 2 control boundary and
*not* a runtime subsystem. Listed separately from the fourteen control boundaries in
[README.md](README.md) and in [SBS](../SYSTEM_BREAKDOWN_STRUCTURE.md) Part 3.

**Source docs:** [SBS](../SYSTEM_BREAKDOWN_STRUCTURE.md) ·
[context packet](../foundation/yggdrasil-architecture-context-packet.md) ·
[doctrine](../foundation/00-yggdrasil-doctrine.md) ·
[functional ontology](../architecture/functional-ontology.md) ·
[semantic dimensions](../architecture/semantic-dimensions.md) ·
[CrossScopeFlow](../architecture/cross-scope-flow.md) ·
[traceability matrix](../architecture/traceability-matrix.md)

**Canonical separation rule:** **CES is stewardship, not runtime.**

## Purpose

Provide lean stewardship for long-term architectural contracts: subsystem charters, dependency rules,
ADRs, versioning, deprecation, and the architecture-evolution process — so the SBS does not decay back
into implementation structure.

> **What CES is not** (preserving the #2534 stabilization):
>
> - CES is **not runtime**.
> - CES is **not a policy engine** (runtime policy/authority is **GOV**).
> - CES is **not user governance** (it does not approve user-level mutations or runtime business behavior).
> - CES **is not the Builder System** — repo-local skills, issue pickup, release workflows, BuilderOps
>   records, delivery receipts, and TCD routing are Builder System concerns
>   ([`docs/architecture/SBS_OPERATING_MODEL.md`](../architecture/SBS_OPERATING_MODEL.md)), not CES-owned runtime.
>
> CES stewards contracts, ADRs, dependency rules, versioning, deprecation, and architecture evolution.

## Owns

- Subsystem charters (this `docs/boundaries/` set), dependency/boundary rules, the boundary vocabulary.
- ADRs, interface versioning, compatibility matrices, deprecation policy, change-impact playbooks.
- The architecture-evolution process and contract stewardship (`SubsystemContract`).

## Does not own

- Runtime behavior → the runtime control boundaries (HKA…OEF).
- User governance / policy decisions → **GOV**.
- Execution → **EXE**; ranking → **RCA**; memory → **MEM**; storage → **PDM**.

> **Ownership-drift rule.** CES describes and stewards contracts; it never executes them. If a
> stewardship concern implies a runtime decision, it routes to the owning runtime boundary (usually GOV) —
> CES must not become a development or runtime control plane.

## Inputs

- Subsystem contracts, ADRs, compatibility needs, deprecation requests, new-term/boundary proposals.

## Outputs

- `SubsystemContract`s, compatibility matrices, dependency rules, ADRs, change-impact playbooks.

## Calls allowed

- Reads **contracts from all subsystems** (as documentation/CI discipline); produces docs/ADRs/rules.

## Calls forbidden

- **Runtime control** — must not gate, authorize, rank, store, remember, or execute at runtime.
- **Becoming GOV** — must not make user-level or runtime policy/authority decisions.
- **Absorbing the Builder System** — must not concentrate skills/BuilderOps/TCD authority into CES.

## Required metadata

CES governs **documentation/contract artifacts**, not runtime objects, so it owns no runtime metadata
dimension. It ensures that every contract/charter carries its traceability (principle → boundary →
contract → test → issue) and that new terms enter the [metadata bundle](../architecture/semantic-dimensions.md)
deliberately rather than ad hoc.

## Policy obligations

- New architecture terms/boundaries require a traceability-matrix entry and, where load-bearing, an ADR.
- Deprecations and contract version changes follow explicit stewardship process, not silent edits.

## Provenance obligations

- ADRs record the decision lineage for architecture changes; charters cite their governing SBS/doctrine.
- `DOCS_INDEX.md` and the traceability matrix stay current as contracts evolve.

## Invariants owned

- Architecture evolves explicitly (matrix #13 governance discipline; context packet §10).
- New terms/boundaries require traceability and possibly an ADR.
- CES cannot become runtime control (SBS Part 3; ADR-0021).

## Failure modes

- **CES-as-runtime:** a charter/ADR process gating live behavior.
- **CES-as-GOV:** stewardship making user/runtime policy decisions.
- **CES overload:** the whole Builder System collapsing into CES (transition debt D11).

## Required tests

Future test names for the invariant registry ([#2550](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2550)) / eval corpus ([#2551](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2551)); skeletons in [#2552](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2552). No tests created here. `docs_index_stays_current` maps to the existing `tests/architecture/test_docs_index.py`.

- `architecture_changes_have_traceability`
- `new_boundary_requires_adr`
- `docs_index_stays_current`

## Related ADRs

- ADR-0021 (CES as architecture stewardship practice, not runtime peer).
- The doctrine/ontology/boundary decisions affecting this boundary (ADR-0026–ADR-0039, [#2549](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2549)) are mapped per boundary by the [traceability matrix](../architecture/traceability-matrix.md).

## Related schemas/contracts

- `SubsystemContract` (SBS Part 5); the boundary-charter set in this directory; ADR set — [#2549](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2549).

## Related issues

- Charter: [#2543](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2543) · Epic: [#2533](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2533) · Index: [README.md](README.md)
