# Boundary: GOV — Governance, Policy, Authority & Receipts

State: Boundary charter — Draft (control-boundary contract; docs-only, not a runtime service declaration)

**Source docs:** [SBS](../SYSTEM_BREAKDOWN_STRUCTURE.md) ·
[context packet](../foundation/yggdrasil-architecture-context-packet.md) ·
[doctrine](../foundation/00-yggdrasil-doctrine.md) ·
[functional ontology](../architecture/functional-ontology.md) ·
[semantic dimensions](../architecture/semantic-dimensions.md) ·
[CrossScopeFlow](../architecture/cross-scope-flow.md) ·
[traceability matrix](../architecture/traceability-matrix.md)

**Canonical separation rule:** GOV **authorizes, delegates, approves, and receipts**. It gives
normative meaning; it is not storage, ranking, or execution.

## Purpose

Own admissibility, authority, delegation, approval, and accountability — the trust spine that decides
whether an action is allowed and records that decision durably.

## Owns

- Policy and admissibility (`PolicyDecision`); delegation and revocation (`CapabilityGrant`).
- Approval / rejection and authority transitions; authority receipts (`AuthorityReceipt`).
- Accountability decisions; the typed [`CrossScopeFlow`](../architecture/cross-scope-flow.md) grant.
- The `authority_state` and `evidence_role` (admissibility) transitions; `sensitivity` / `suppression_state` decisions.

## Does not own

- Retrieval ranking → **RCA**.
- Storage → **PDM**; derived-representation construction → **DRI**.
- Execution mechanics → **EXE**; agent planning → **CAO**.
- Memory storage/lifecycle → **MEM** (GOV owns only the *promotion* transition).

> **Ownership-drift rule.** GOV centralizes **accountability, not mechanism**. It must not become a
> god-object that performs storage, formatting, routing, ranking, or execution. State owners perform
> their own writes under a governed write protocol; GOV issues the decision and the receipt.

## Inputs

- Intent and proposals (HIX, CAO); policy profiles, authority grants, conflict classes.
- Provenance/identity views (SIP); scope/principal context (WSP); conflict classes (SFC); evidence (OEF).

## Outputs

- `PolicyDecision`, `AuthorityReceipt`, approvals, denials, revocations, `CrossScopeFlow` grants.

## Calls allowed

- **SIP** (identity/provenance views), **WSP** (principal/scope context), **HKA** (artifact refs), **SFC** (conflict classes), **OEF** (evidence) — all as inputs to decisions.

## Calls forbidden

- **Performing the mutation** — GOV decides; the state owner (HKA/MEM/EXE) writes under the decision token.
- **Ranking / retrieving** — must not assume RCA's role.
- **Self-justifying execution** — must not let EXE or CAO authorize themselves through GOV-shaped fields.

## Required metadata

GOV **owns** `authority_state`, `evidence_role` (admissibility), `sensitivity`, `suppression_state`,
the policy facet of `scope_binding`, and the promotion of `memory_state`/`execution_state`
transitions. Every governed transition emits an `AuthorityReceipt` with justification.

## Policy obligations

- No durable authority change without a `PolicyDecision` + `AuthorityReceipt` (no advisory-only governance).
- Cross-scope use is granted only via a typed `CrossScopeFlow`; no global `general_knowledge: true` bypass.
- Memory promotion and execution authorization are governed transitions, not defaults.

## Provenance obligations

- Receipts are the accountable record of who/what/why/when under which grant — distinct from OEF traces.
- Decisions reference the provenance/identity SIP supplies; they do not invent origin.

## Invariants owned

- Authority transitions require governance and receipts (matrix #9).
- Execution cannot authorize itself (matrix #10).
- Cross-scope use requires typed `CrossScopeFlow` (matrix #1, #6, #11).
- Memory promotion requires governance (matrix #4).

## Failure modes

- **Governance god-core:** GOV APIs carrying storage/render/execution fields.
- **Advisory governance:** durable writes proceeding without a receipt.
- **Bypass reintroduction:** a boolean cross-scope flag replacing typed flows.

## Required tests

Future test names for the invariant registry ([#2550](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2550)) / eval corpus ([#2551](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2551)); skeletons in [#2552](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2552). No tests created here.

- `promote_requires_governance`
- `authority_transition_required_for_durable_mutation`
- `execution_cannot_authorize_itself`
- `cross_scope_only_via_flow`

## Related ADRs

- ADR-0017, ADR-0019 (governed writes / receipts), ADR-0021 (CES not GOV) — via [#2549](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2549).

## Related schemas/contracts

- `AuthorityTransition` — [#2547](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2547); `CrossScopeFlow` schema — [#2544](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2544), [#2548](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2548).

## Related issues

- Charter: [#2542](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2542) · Epic: [#2533](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2533) · Index: [README.md](README.md)
