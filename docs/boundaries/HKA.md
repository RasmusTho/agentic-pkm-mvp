# Boundary: HKA — Human Knowledge & Artifact Substrate

State: Boundary charter — Draft (control-boundary contract; docs-only, not a runtime service declaration)

**Source docs:** [SBS](../SYSTEM_BREAKDOWN_STRUCTURE.md) ·
[context packet](../foundation/yggdrasil-architecture-context-packet.md) ·
[doctrine](../foundation/00-yggdrasil-doctrine.md) ·
[functional ontology](../architecture/functional-ontology.md) ·
[semantic dimensions](../architecture/semantic-dimensions.md) ·
[CrossScopeFlow](../architecture/cross-scope-flow.md) ·
[traceability matrix](../architecture/traceability-matrix.md)

**Canonical separation rule:** HKA says **what is durable human knowledge**. (SIP says how it means;
PDM says how it is stored.)

## Purpose

Preserve durable human-authored and human-accepted knowledge artifacts — and the minimal identity
and origin-provenance anchors that let them survive the loss of every derived machine artifact.

## Owns

- Durable human artifacts (`Artifact`, `HumanArtifact`).
- Human-accepted machine contributions promoted into knowledge.
- Canonical artifact state and accepted durable-knowledge state (`AcceptedArtifact`, `Commitment`).
- The artifact's `authority_state` *as carried on the artifact* after a governed transition.
- Minimal durable identity anchors and origin-provenance stamps carried **inside** the artifact.
- Artifact lifecycle and exportable/portable human-readable representations.

## Does not own

- Storage backend details → **PDM**.
- Embeddings, indexes, derived projections → **DRI**.
- Semantic graph, ontology, lineage views → **SIP**.
- Agent plans → **CAO**; machine memory → **MEM**.
- Policy / admissibility decisions and the authority transition itself → **GOV**.
- Execution mechanics → **EXE**.

> **Ownership-drift rule.** HKA never sets canonical authority on its own. When standing must change,
> it requests a GOV transition and applies the result; it does not re-derive admissibility locally.

## Inputs

- Human artifacts and retained source material (from HIX / EBF).
- Governed mutations carrying a GOV decision token / `AuthorityReceipt`.
- Promotion targets routed from MEM **through GOV** (memory → durable knowledge).
- Representation-migration requests.

## Outputs

- `Artifact` / `ArtifactContract` instances, artifact views, exports, lifecycle state.
- `AcceptedArtifact` / `Commitment` once a governed transition completes.
- Identity/origin-provenance anchors consumed by SIP to build the semantic graph.

## Calls allowed

- **GOV** — request admissibility, supply mutations, receive `AuthorityReceipt`.
- **SIP** — read/contribute semantic identity & provenance contracts.
- **PDM** — persist and resolve artifacts through `StorePort`s.

## Calls forbidden

- **DRI / PDM internals** — HKA must not write embeddings/indexes or touch storage tables directly outside PDM ports.
- **RCA / MEM as truth** — must not treat a retrieval result or an unpromoted memory as canonical.
- **Self-promotion** — must not move an artifact to `accepted`/`canonical` without a GOV transition + receipt.

## Required metadata

Every artifact must carry the [semantic dimensions](../architecture/semantic-dimensions.md):
`source_role`, `authority_state`, `scope_binding`, `sensitivity` (and `suppression_state` when set).
HKA **owns the durable carrying** of these on the artifact and of the minimal identity/origin anchors;
it does **not** own the `authority_state` transition (GOV) or the `source_role` semantics (SIP).

## Policy obligations

- Durable mutation requires a valid GOV decision token; reject writes lacking one (governed write protocol).
- Honor `sensitivity` and `suppression_state` set by GOV.
- Cross-scope import/mutation occurs only under a typed [`CrossScopeFlow`](../architecture/cross-scope-flow.md).

## Provenance obligations

- Carry origin-provenance stamps and identity anchors inside the artifact so knowledge survives machine loss.
- Never strip provenance on representation migration or export.
- Record the `authority_receipt_ref` on accepted artifacts.

## Invariants owned

- Durable human knowledge changes only through governed authority transition (matrix #9, #15).
- Human-authored material is not automatically canonical (matrix #15).
- Projection is not evidence (matrix #8) — a projection never enters HKA as knowledge by default.
- Memory is not durable knowledge until promoted (matrix #4, #9).

## Failure modes

- **Storage-as-knowledge:** treating "stored" as "accepted" — detect writes that set canonical state without a receipt.
- **Silent promotion:** memory/retrieval/agent output entering HKA without a GOV transition.
- **Provenance stripping:** migration/export dropping origin anchors.

## Required tests

Future test names for the invariant registry ([#2550](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2550)) / eval corpus ([#2551](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2551)); skeletons in [#2552](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2552). No tests created here.

- `authority_transition_required_for_durable_mutation`
- `promote_requires_governance`
- `projection_not_evidence`

## Related ADRs

- ADR-0017 (human-knowledge & governance survivability), ADR-0019 (governed writes).

## Related schemas/contracts

- `AuthorityTransition` — [#2547](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2547); metadata bundle — [#2544](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2544); `MemoryItem` promotion boundary — [#2546](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2546).

## Related issues

- Charter: [#2541](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2541) · Epic: [#2533](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2533) · Index: [README.md](README.md)
