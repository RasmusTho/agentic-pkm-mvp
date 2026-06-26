# Boundary: <ID> — <Name>

State: Template / Draft

> Copy this file to `docs/boundaries/<ID>.md` and fill every section. A charter is a
> **control-boundary contract**, not a runtime service declaration. It states what a boundary owns
> and — just as load-bearing — what it must never own. A section left as a placeholder is a
> readiness failure: state "none" or "n/a" explicitly rather than leaving it blank.

**Source docs** (read before editing): [System Breakdown Structure](../SYSTEM_BREAKDOWN_STRUCTURE.md) ·
[Architecture context packet](../foundation/yggdrasil-architecture-context-packet.md) ·
[Doctrine](../foundation/00-yggdrasil-doctrine.md) ·
[Functional ontology](../architecture/functional-ontology.md) ·
[Semantic dimensions](../architecture/semantic-dimensions.md) ·
[CrossScopeFlow](../architecture/cross-scope-flow.md) ·
[Traceability matrix](../architecture/traceability-matrix.md)

**Canonical separation rule:** <one line stating this boundary's place in the canonical rule, e.g.
`HKA says what is durable human knowledge.`>

## Purpose

<One or two sentences. What single responsibility does this boundary exist to protect?>

## Owns

- <durable responsibility / state this boundary is the authority for>

## Does not own

- <responsibility that belongs to another boundary — name the owner>

> **Ownership-drift rule.** If this boundary needs to make a decision outside its ownership, it must
> call or defer to the owning boundary rather than reimplementing the decision locally. Re-deriving
> another boundary's decision here is an architecture violation.

## Inputs

- <what it receives, and from which boundary>

## Outputs

- <what it emits, and to which boundary>

## Calls allowed

- <boundary → reason the call is permitted>

## Calls forbidden

- <call that would collapse a boundary, and why it is forbidden>

## Required metadata

<The [semantic dimensions](../architecture/semantic-dimensions.md) this boundary must preserve or
honor (`source_role`, `authority_state`, `evidence_role`, `sensitivity`, `scope_binding`,
`suppression_state`, `memory_state`, `sync_state`, `execution_state`). Name which it *owns* vs which
it must *carry forward* unchanged.>

## Policy obligations

- <which GOV policies / admissibility checks this boundary must obey or defer to>

## Provenance obligations

- <what provenance/lineage this boundary must preserve, attach, or never strip>

## Invariants owned

- <invariant this charter protects; cross-reference the traceability-matrix principle number>

## Failure modes

- <named collapse this boundary must not drift into, and how to detect it>

## Required tests

These are **TBD test names** for the future invariant registry
([#2550](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2550)) and anti-contamination eval
corpus ([#2551](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2551)); test skeletons land in
[#2552](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2552). No tests are created in the
charter batch.

- `<invariant_test_name>`

## Related ADRs

- ADR set — [#2549](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2549) (pending; link specific
  ADR ids once delivered)

## Related schemas/contracts

- <contract this boundary produces/consumes> — [#2544](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2544)–[#2548](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2548) (pending)

## Related issues

- Charter: <#issue> · Epic: [#2533](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2533) ·
  Index: [README.md](README.md)
