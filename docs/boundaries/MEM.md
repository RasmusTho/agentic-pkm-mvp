# Boundary: MEM — Machine Memory & Learning

State: Boundary charter — Draft (control-boundary contract; docs-only, not a runtime service declaration)

**Source docs:** [SBS](../SYSTEM_BREAKDOWN_STRUCTURE.md) ·
[context packet](../foundation/yggdrasil-architecture-context-packet.md) ·
[doctrine](../foundation/00-yggdrasil-doctrine.md) ·
[functional ontology](../architecture/functional-ontology.md) ·
[semantic dimensions](../architecture/semantic-dimensions.md) ·
[CrossScopeFlow](../architecture/cross-scope-flow.md) ·
[traceability matrix](../architecture/traceability-matrix.md)

**Canonical separation rule:** MEM **remembers and advises**. Memory is advisory and noncanonical
until governed promotion into HKA.

## Purpose

Own inspectable, revisable machine memory and learning feedback — recall that *advises* cognition
without ever becoming hidden authority.

## Owns

- Machine-memory candidates (`MemoryItem`) and advisory recall.
- Correction signals, contradiction handling, feedback loops.
- Forgetting / suppression / invalidation / decay **inside machine memory**.
- Promotion **requests** (memory → durable knowledge), routed through GOV.

## Does not own

- Durable human knowledge → **HKA**.
- Authority transitions and the promotion *decision* → **GOV**.
- Direct canonical writes → **HKA**/**GOV**; external execution → **EXE**.
- Retrieval ranking → **RCA** (MEM supplies recall, RCA ranks).

> **Ownership-drift rule.** MEM may *request* promotion; it must never *grant* it. Hidden authority
> through accumulation, similarity, or repetition is forbidden — promotion is a GOV + HKA transition.

## Inputs

- Observations, feedback, outcomes, receipts, source provenance, review decisions (HIX, CAO, GOV, SIP).

## Outputs

- `MemoryItem` records, recall results, contradiction reports, decay/forget decisions, promotion requests.

## Calls allowed

- **SIP/HKA** (provenance, source refs), **GOV** (memory policy, promotion), **RCA** (supply recall support), **PDM** (memory store), **DRI** (memory representations).

## Calls forbidden

- **Writing HKA directly** — memory becoming shadow knowledge is forbidden.
- **Self-promotion** — must not set canonical `authority_state` via `memory_state` alone.
- **Leaking suppressed memory** — forgotten/suppressed items must not enter context.

## Required metadata

MEM **owns `memory_state`** (`unreviewed`→`reviewed`→`promoted`/`corrected`/`decayed`/`forgotten`)
and carries `source_role: agent_memory`, `authority_state: noncanonical` (default),
`evidence_role: background`/`non_evidence`, `scope_binding`, `suppression_state`, `provenance_ref`.
`promoted` reflects a GOV transition — it does not itself confer canonical authority.

## Policy obligations

- Memory is advisory until promoted; honor GOV memory policy and `CrossScopeFlow` for cross-scope recall.
- Suppression/forgetting removes material from recall and context surfacing.

## Provenance obligations

- Every `MemoryItem` carries provenance and review state; promotion materializes into HKA with a receipt.
- Forgetting hides; it must not erase lineage/authority history (it tombstones).

## Invariants owned

- Agent memory is noncanonical by default (matrix #4).
- Machine memory is advisory until promoted (matrix #4, #9).
- Memory promotion requires GOV + HKA (matrix #4, #9).
- Forgotten/suppressed memory must not be retrieved into context (semantic dimensions: `suppression_state`).

## Failure modes

- **Shadow knowledge:** memory influencing decisions as if canonical.
- **Silent promotion:** `memory_state: promoted` without a GOV transition/receipt.
- **Forgetting leak:** suppressed/forgotten memory resurfacing in retrieval/context.

## Required tests

Future test names for the invariant registry ([#2550](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2550)) / eval corpus ([#2551](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2551)); skeletons in [#2552](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2552). No tests created here.

- `remember_not_canonical`
- `promote_requires_governance`
- `forgotten_memory_not_retrieved`

## Related ADRs

- ADR-0025 (agent memory noncanonical).

## Related schemas/contracts

- `MemoryItem` contract & promotion boundary — [#2546](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2546); `AuthorityTransition` — [#2547](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2547).

## Related issues

- Charter: [#2542](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2542) · Epic: [#2533](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2533) · Index: [README.md](README.md)
