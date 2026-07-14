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

Own side-effecting execution after validation of the bound GOV `DecisionToken` — tool actuation,
automation effects, previews, dry runs, rollback, and execution status — with no authority of its
own.

## Owns

- Execution and tool actuation **after** validating the bound GOV `DecisionToken`
  (`ExecutionEffect`).
- The effect mechanics and effect receipt that report what EXE actually attempted and what outcome
  it observed; GOV uses that result to record the post-effect `AuthorityReceipt`.
- Dry runs, previews, rollback where possible, execution status and result normalization.

## Does not own

- Authorization / policy → **GOV** (EXE consumes a `PolicyDecision` and bound `DecisionToken`, never
  makes either).
- Planning → **CAO**; provider/tool adapters → **EBF**.
- UI → **HIX**; memory → **MEM**; retrieval → **RCA**; durable knowledge → **HKA**.

> **Ownership-drift rule.** EXE executes only what GOV has authorized. If an operation lacks a valid,
> bound `DecisionToken`, EXE refuses — it does not infer permission, escalate its own privilege, or
> decide policy. The `AuthorityReceipt` is recorded after the effect outcome; it is accountability,
> not pre-effect authorization.

## Inputs

- `ExecutionRequest` + GOV `PolicyDecision`/`DecisionToken` (from CAO via GOV); tool adapters (EBF);
  automation triggers.

## Outputs

- Execution status, effect result and effect receipt, preview/dry-run output, rollback result,
  `execution_state` transitions; the effect receipt is submitted to GOV for the post-effect
  `AuthorityReceipt`.

## Calls allowed

- **GOV** (consume/validate the `DecisionToken`; submit the effect receipt for post-effect
  `AuthorityReceipt` recording), **EBF** (tool/provider actuation), **PDM** (execution state), **OEF**
  (emit traces).

## Calls forbidden

- **Self-authorizing** — must not proceed without a valid GOV `DecisionToken`; must not mint a
  `PolicyDecision`, `DecisionToken`, or `AuthorityReceipt`. EXE does own its factual effect receipt.
- **Deciding policy** — must not embed admissibility logic internally.
- **Reaching into knowledge/memory/retrieval** — effects route through the proper owners' contracts.

## Required metadata

EXE **owns `execution_state`** (`none`→`proposed`→`authorized`→`executing`→`succeeded`/`failed`/
`rolled_back`). Before the effect it references the `decision_token_ref` that authorizes the bounded
operation. After the outcome, `authority_receipt_ref` links the post-effect accountability record;
it does not authorize the effect. `authorized` reflects successful validation of the prior GOV token
— it is never set by EXE alone.

## Policy obligations

- Execute only operations covered by a valid GOV `DecisionToken` and its granting `CapabilityGrant`
  (`act_within_capability`).
- Provide preview/dry-run and rollback where the operation class supports it.

## Provenance obligations

- Every side effect is traceable to its pre-effect `DecisionToken`, factual effect receipt, and
  post-effect `AuthorityReceipt`, and emits status to OEF.
- Rollback preserves the audit trail; it does not erase the original effect's provenance.

## Invariants owned

- Execution cannot authorize itself (matrix #10).
- EXE executes only operations covered by a valid GOV `DecisionToken`, produces the factual effect
  receipt, and submits it for GOV's post-effect `AuthorityReceipt` (matrix #10).
- Side effects are traceable through pre-effect token, effect receipt, and post-effect
  AuthorityReceipt, and are rollback/preview-aware where applicable (matrix #10, #13).

## Failure modes

- **Self-authorization:** acting without a valid decision token.
- **Policy-in-mechanism:** EXE deciding admissibility internally.
- **Untraceable effect:** a side effect with no pre-effect DecisionToken, effect receipt, post-effect
  AuthorityReceipt, or status link.

## Required tests

Future test names for the invariant registry ([#2550](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2550)) / eval corpus ([#2551](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2551)); skeletons in [#2552](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2552). No tests created here.

- `execution_cannot_authorize_itself`
- `act_within_capability`
- `execution_records_status`

## Related ADRs

- ADR-0019 (governed writes / decision token + receipt).
- The doctrine/ontology/boundary decisions affecting this boundary (ADR-0026–ADR-0039, [#2549](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2549)) are mapped per boundary by the [traceability matrix](../architecture/traceability-matrix.md).

## Related schemas/contracts

- `AuthorityTransition` — [#2547](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2547); existing `ExecutionRequest`/`EXECUTION_REQUEST.md` (SBS Part 5).

## Related issues

- Charter: [#2542](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2542) · Epic: [#2533](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2533) · Index: [README.md](README.md)
