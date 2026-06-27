# Boundary: EXE — Capability Execution & Automation

State: Boundary charter — Draft (control-boundary contract; docs-only, not a runtime service declaration)

**Source docs:** [SBS](../SYSTEM_BREAKDOWN_STRUCTURE.md) ·
[context packet](../foundation/yggdrasil-architecture-context-packet.md) ·
[doctrine](../foundation/00-yggdrasil-doctrine.md) ·
[functional ontology](../architecture/functional-ontology.md) ·
[semantic dimensions](../architecture/semantic-dimensions.md) ·
[CrossScopeFlow](../architecture/cross-scope-flow.md) ·
[traceability matrix](../architecture/traceability-matrix.md)

**Canonical separation rule:** EXE **executes only authorized side effects**. It knows *how*;
Governance decides *whether*.

## Purpose

Own side-effecting execution after authorization — tool actuation, automation effects, previews,
dry runs, rollback, and execution status — with no authority of its own.

## Owns

- Authorized execution and tool actuation **after** a GOV authorization (`ExecutionEffect`).
- Dry runs, previews, rollback where possible, execution status and result normalization.

## Does not own

- Authorization / policy → **GOV** (EXE consumes a decision, never makes one).
- Planning → **CAO**; provider/tool adapters → **EBF**.
- UI → **HIX**; memory → **MEM**; retrieval → **RCA**; durable knowledge → **HKA**.

> **Ownership-drift rule.** EXE executes only what GOV has authorized. If an operation lacks a valid
> decision/receipt, EXE refuses — it does not infer permission, escalate its own privilege, or decide policy.

## Inputs

- `ExecutionRequest` + GOV `PolicyDecision`/`AuthorityReceipt` (from CAO via GOV); tool adapters (EBF); automation triggers.

## Outputs

- Execution status, effect result, preview/dry-run output, rollback result, `execution_state` transitions.

## Calls allowed

- **GOV** (consume authorization), **EBF** (tool/provider actuation), **PDM** (execution state), **OEF** (emit traces).

## Calls forbidden

- **Self-authorizing** — must not proceed without a GOV decision; must not mint receipts.
- **Deciding policy** — must not embed admissibility logic internally.
- **Reaching into knowledge/memory/retrieval** — effects route through the proper owners' contracts.

## Required metadata

EXE **owns `execution_state`** (`none`→`proposed`→`authorized`→`executing`→`succeeded`/`failed`/
`rolled_back`) and references the `authority_receipt_ref` that authorized the effect. `authorized`
reflects a prior GOV grant — it is never set by EXE alone.

## Policy obligations

- Execute only GOV-authorized operations, within the granting `CapabilityGrant` (`act_within_capability`).
- Provide preview/dry-run and rollback where the operation class supports it.

## Provenance obligations

- Every side effect is traceable to its `AuthorityReceipt` and emits status to OEF.
- Rollback preserves the audit trail; it does not erase the original effect's provenance.

## Invariants owned

- Execution cannot authorize itself (matrix #10).
- EXE executes only GOV-authorized operations (matrix #10).
- Side effects are traceable and rollback/preview-aware where applicable (matrix #10, #13).

## Failure modes

- **Self-authorization:** acting without a valid decision token.
- **Policy-in-mechanism:** EXE deciding admissibility internally.
- **Untraceable effect:** a side effect with no receipt/status link.

## Required tests

Future test names for the invariant registry ([#2550](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2550)) / eval corpus ([#2551](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2551)); skeletons in [#2552](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2552). No tests created here.

- `execution_cannot_authorize_itself`
- `act_within_capability`
- `execution_records_status`

## Related ADRs

- ADR-0019 (governed writes / decision token + receipt).

## Related schemas/contracts

- `AuthorityTransition` — [#2547](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2547); existing `ExecutionRequest`/`EXECUTION_REQUEST.md` (SBS Part 5).

## Related issues

- Charter: [#2542](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2542) · Epic: [#2533](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2533) · Index: [README.md](README.md)
