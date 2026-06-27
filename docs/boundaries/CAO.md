# Boundary: CAO — Cognitive Capability & Agent Orchestration

State: Boundary charter — Draft (control-boundary contract; docs-only, not a runtime service declaration)

**Source docs:** [SBS](../SYSTEM_BREAKDOWN_STRUCTURE.md) ·
[context packet](../foundation/yggdrasil-architecture-context-packet.md) ·
[doctrine](../foundation/00-yggdrasil-doctrine.md) ·
[functional ontology](../architecture/functional-ontology.md) ·
[semantic dimensions](../architecture/semantic-dimensions.md) ·
[CrossScopeFlow](../architecture/cross-scope-flow.md) ·
[traceability matrix](../architecture/traceability-matrix.md)

**Canonical separation rule:** CAO **reasons and proposes**. Agents plan and propose; they do not
mutate durable state or execute side effects directly.

## Purpose

Own reusable cognition and agent-workflow orchestration that reads, reasons, plans, and proposes —
without side effects.

## Owns

- Agent roles, non-side-effecting cognition, planning loops, workflows, task/workflow state.
- Proposal generation (`Proposal`), capability contracts (`CapabilityContract`), human-decision requests.
- Use of assigned capabilities as **planning affordances** (it requests EXE/GOV, it does not act).

## Does not own

- Direct mutation → **HKA**/**GOV**; direct tool execution → **EXE**.
- Policy → **GOV**; raw vault/index access → bounded context from **RCA**/**MEM** only.
- Durable memory promotion → **MEM**/**GOV**; authority receipts → **GOV**.

> **Ownership-drift rule.** An agent is **not a superuser**. When an action needs authority, CAO emits
> a proposal/request to GOV (for authorization) and EXE (for the effect) — it never self-authorizes or
> reaches around its boundary into storage, indexes, or durable knowledge.

## Inputs

- Intent (HIX), `ContextBundle`/`ContextEnvelope` (RCA), memory recall (MEM), policies/filters (GOV), model outputs (EBF).

## Outputs

- Capability results, plans, `Proposal`s, workflow state, execution **requests** (`ExecutionRequest` to EXE via GOV).

## Calls allowed

- **RCA** (request context), **MEM** (request recall), **GOV** (request authorization), **EXE** (request execution), **EBF** (model providers).

## Calls forbidden

- **Direct mutation / tool calls** — must not write HKA or call tools without EXE + GOV.
- **Raw vault/index access** — must consume bounded context, never the raw store.
- **Self-authorization** — must not mint authority or treat its own proposal as accepted.

## Required metadata

CAO **reads** bounded context carrying the full metadata bundle and **produces** proposals tagged
`authority_state: proposed`, `evidence_role` per source. It must preserve `scope_binding` and
provenance from the context it consumes; it sets no canonical `authority_state` itself.

## Policy obligations

- Operate within its `CapabilityGrant`; respect scope eligibility and `CrossScopeFlow` on consumed context.
- Under uncertainty, propose / confirm / escalate rather than silently act (doctrine §4).

## Provenance obligations

- Proposals cite the evidence/context they rest on, carrying provenance forward.
- Plans/proposals are projections, not primary sources, until governed acceptance.

## Invariants owned

- Agents reason and propose; they do not mutate or execute directly (matrix #10, with GOV/EXE).
- Agents consume bounded context, not raw vault access (matrix #8, #17).
- Durable mutation requires a governed authority transition (matrix #9).
- Under uncertainty, propose/confirm/escalate (matrix #17).

## Failure modes

- **Agent-as-superuser:** CAO writing durable state or calling tools directly.
- **Raw-store reach-around:** bypassing RCA/MEM to read the vault/index.
- **Silent action:** acting under uncertainty instead of proposing/escalating.

## Required tests

Future test names for the invariant registry ([#2550](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2550)) / eval corpus ([#2551](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2551)); skeletons in [#2552](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2552). No tests created here.

- `agent_no_raw_vault_access`
- `agent_receives_bounded_context`
- `authority_transition_required_for_durable_mutation`

## Related ADRs

- ADR-0019 (governed writes), ADR-0024 (retrieval candidate evidence).
- The doctrine/ontology/boundary decisions affecting this boundary (ADR-0026–ADR-0039, [#2549](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2549)) are mapped per boundary by the [traceability matrix](../architecture/traceability-matrix.md).

## Related schemas/contracts

- `ContextEnvelope` (bounded operating context) — [#2545](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2545); existing `CapabilityContract`/`WorkflowContract` (SBS Part 5).

## Related issues

- Charter: [#2542](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2542) · Epic: [#2533](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2533) · Index: [README.md](README.md)
