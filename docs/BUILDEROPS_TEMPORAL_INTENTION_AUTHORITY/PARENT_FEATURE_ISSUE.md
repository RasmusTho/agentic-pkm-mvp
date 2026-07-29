State: Active blocked validation hub #4375.
Doc role: Parent validation-hub contract
Authority: The capability README owns stable decomposition. The live GitHub parent owns backlog and validation state after filing.

# Parent feature issue — BuilderOps temporal intention authority

## Context

ADR-0065 accepts an opaque-first, PostgreSQL-only, receipt-backed authority boundary for BuilderOps
temporal-intention lifecycle evidence. This parent coordinates the dependency-ordered tasks in
`docs/BUILDEROPS_TEMPORAL_INTENTION_AUTHORITY/README.md` without claiming that any Product or
runtime behavior is delivered.

## Scope

- Deliver TIA-01 through TIA-06 only when each task's named dependency and decision gates are met.
- Keep this parent as the live validation, decision, and receipt hub.
- Reuse the transaction, receipt, and outbox kernel delivered under #3792.
- Keep implementation blocked until BCP-06 #3793 proves the canonical PostgreSQL writer.
- Promote current-state owner docs only after the relevant capability acceptance evidence exists.

## Source Anchors

- `docs/adr/ADR-0065-builderops-temporal-intention-authority.md :: D2 — One future canonical writer, gated on BCP-06 cutover`
- `docs/adr/ADR-0065-builderops-temporal-intention-authority.md :: D5 — The first slice is strictly content-free`
- `docs/adr/ADR-0065-builderops-temporal-intention-authority.md :: D8 — Delivery sequencing`

## SBS Impact

- Primary subsystem: Builder System / CES boundary
- Secondary subsystem(s): BuilderOps control plane; Product boundary only through separately gated future adapters
- Write class: target-state authority-bearing BuilderOps state plus governance/docs/process
- Persistence impact: future durable PostgreSQL records and append-only receipts; none from this planning Issue
- Derived/rebuildable impact: future read-only projections are rebuildable and non-authoritative
- New or changed contract: temporal-intention lifecycle evidence admission and deferred decision gates
- Owner-doc impact: follow-up only after accepted implementation evidence
- Transition debt impact: reduces competing-state risk; adds no interim writer
- Boundary risk: Builder evidence must never become Product intention truth or competing Markdown state

## Constraints

- Parent is a validation hub and never receives `agent:ready`.
- TIA-01 remains `agent:blocked` until #3793 is closed with the BCP-06 cutover receipt.
- TIA-02 requires an explicit owner decision before it can authorize any implementation.
- TIA-03 through TIA-06 remain blocked until every decision named in their contracts is accepted.
- No task may create a second registry, JSONL ledger, Markdown state, SQLite fallback, or direct
  database writer.
- No deferred scope may be folded into TIA-01.

## Acceptance Criteria

- [ ] Every child has terminal delivery evidence or an explicit superseding owner decision.
  - Verify: `doc writeback at docs/BUILDEROPS_TEMPORAL_INTENTION_AUTHORITY/PARENT_FEATURE_ISSUE.md :: Implementation Tasks`
- [ ] TIA-01 proves canonical, content-free admission only after BCP-06 cutover.
  - Verify: `tests/builderops/control_plane/test_temporal_intention_admission.py::test_production_admission_requires_proven_bcp06_cutover`
- [ ] The closed disposition vocabulary, replay semantics, receipt lineage, and projection
  non-authority invariants are evidenced.
  - Verify: `doc writeback at docs/BUILDEROPS_TEMPORAL_INTENTION_AUTHORITY/README.md :: Capability acceptance`
- [ ] Deferred privacy, retention, collection, migration, sync, UI, and erasure work is not treated
  as implicitly authorized.
  - Verify: `runtime receipt: temporal_intention_deferred_scope_gate.v1`
- [ ] Current-state owner docs are promoted only after corresponding delivery evidence is accepted.
  - Verify: `runtime receipt: temporal_intention_owner_doc_promotion.v1`

## Out of Scope

- Implementing Product or runtime behavior in this planning work.
- Treating the audit as normative authority.
- Allowing projections or local files to become canonical state.
- Starting any child before its dependency and decision gates are proven.

## Suggested Validation

- Resolve every child `Verify:` target on its governing PR.
- Maintain exact issue, decision, PR-head, CI, merge, and BuilderOps receipt links on the parent.
- Re-run strict issue validation before changing any child to `agent:ready`.
- Close the parent only through the governed parent-acceptance path.

## Source Docs

- `docs/BUILDEROPS_TEMPORAL_INTENTION_AUTHORITY/README.md`
- `docs/adr/ADR-0065-builderops-temporal-intention-authority.md`
- `docs/BUILDEROPS_CONTROL_PLANE/POSTGRES_TRANSACTION_KERNEL.md`
- `docs/builderops/BUILDEROPS_VAULT_OBJECT_MODEL.md`

## Applies learning (optional)


## Implementation Tasks

| Task | Issue | Initial lifecycle | Dependency |
| --- | --- | --- | --- |
| TIA-01 — opaque canonical admission | [#4376](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4376) | blocked | #3793 BCP-06 |
| TIA-02 — privacy/retention/erasure decision | [#4377](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4377) | needs human | explicit owner decision |
| TIA-03 — content-bearing evidence | [#4378](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4378) | blocked | #4376 and accepted #4377 |
| TIA-04 — collection/sync/migration | [#4379](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4379) | blocked | #4376, accepted #4377 where applicable, separate source/topology/migration decision |
| TIA-05 — human-facing projection | [#4380](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4380) | blocked | #4376 and separate Product/HIX decision |
| TIA-06 — retention/physical erasure | [#4381](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4381) | blocked | #4376 and accepted #4377 |

## Verification Path

Each child resolves its own inline `Verify:` targets and posts a compact receipt to the live parent.

## Validation / Acceptance Path

The parent remains blocked while any required dependency, decision, child validation, owner-doc
writeback, or terminal receipt is unresolved.
