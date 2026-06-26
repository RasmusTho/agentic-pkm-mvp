State: Canonical Yggdrasil CrossScopeFlow model. Docs-only architecture/policy contract for the foundation backlog (#2533–#2552); defines governed cross-scope knowledge movement/use and retires global `general_knowledge` bypass semantics. Does not claim shipped runtime behavior.
Doc role: Architecture / policy contract
Authority: Owns the model for moving or using knowledge across scope boundaries. Establishes that cross-scope use is a typed, directional, operation-specific governed grant — never a boolean and never a consequence of similarity. Subordinate to `docs/foundation/00-yggdrasil-doctrine.md`, `docs/architecture/functional-ontology.md`, and `docs/architecture/semantic-dimensions.md`; later schema/policy work is owned by the contract issues (#2544–#2548).
Owner: Architecture spine
Temporal class: strategic
Review cadence: event-driven
Source of truth: canonical (CrossScopeFlow model); subordinate to doctrine, ontology, semantic dimensions
Last reviewed: 2026-06-26
Last verified against: docs/foundation/00-yggdrasil-doctrine.md, docs/architecture/functional-ontology.md, docs/architecture/semantic-dimensions.md, docs/foundation/yggdrasil-architecture-context-packet.md

# Yggdrasil CrossScopeFlow

Parent epic: [#2533](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2533)

A [`Scope`](functional-ontology.md) is a cognitive frame, an audience boundary, a policy boundary,
and a provenance context. Material does not move or get used across a scope boundary because it is
*similar* to something in the target scope. It moves only through a **typed `CrossScopeFlow`**: a
directional, operation-specific, provenance-preserving, governed grant.

> **Similarity is not permission.** Embedding or keyword similarity may surface a candidate, but it
> never grants the right to retrieve across a boundary, cite, import, remember, mutate, or execute.
> Ranking does not create a flow.

Read first: the [doctrine](../foundation/00-yggdrasil-doctrine.md), the
[functional ontology](functional-ontology.md), and the
[semantic dimensions](semantic-dimensions.md). The cross-scope decision reads the orthogonal
dimensions (`source_role`, `authority_state`, `evidence_role`, `sensitivity`, `scope_binding`)
defined there. Later schema/policy is owned by the metadata bundle
([#2544](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2544)) and `RetrievalResult`
([#2548](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2548)) contracts; eval fixtures by the
anti-contamination corpus ([#2551](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2551)).

## 1. CrossScopeFlow fields

A `CrossScopeFlow` is a typed grant. It is **not bidirectional by default** — a flow authorizes
exactly one direction, `source_scope → target_scope`.

| Field | Meaning |
| --- | --- |
| `flow_id` | Stable identifier for this flow grant. |
| `source_scope` | The scope material moves/used **from**. |
| `target_scope` | The scope material moves/used **into**. One direction only. |
| `allowed_operations` | The explicit operations this flow permits (subset of §2). Anything not listed is denied. |
| `denied_operations` | Operations explicitly denied, for clarity/auditing even where the default already denies them. |
| `source_roles_allowed` | Which `source_role` families may cross (e.g. `general_knowledge`, `work_project`). |
| `authority_states_allowed` | Which `authority_state` values may cross (e.g. `accepted`, never `proposed`). |
| `evidence_roles_allowed` | The evidence role the material may hold **in the target** (e.g. `background`, `analogy`) — may be downgraded from the source. |
| `redaction_required` | Whether material must be redacted before crossing, and which redaction profile. |
| `confirmation_required` | Whether a human confirmation is required before the operation completes. |
| `expiry` | When the grant lapses; flows are bounded, not perpetual. |
| `audit_required` | Whether each use under this flow must emit an audit/provenance record. |
| `provenance_requirements` | What provenance must be preserved/attached when material crosses (origin, justification, original scope, `source_role`). |

A flow is the unit GOV evaluates. Its existence in the ontology is
[`CrossScopeFlow`](functional-ontology.md); GOV owns it, and an `AuthorityReceipt` records uses that
constitute governed transitions.

## 2. Operations are distinct

Cross-scope use is **not** one permission. Each operation is separately granted. In particular:

> `retrieve` ≠ `surface` ≠ `cite` ≠ `import` ≠ `remember` ≠ `mutate` ≠ `execute` ≠ `export`

| Operation | Meaning | Granting one does NOT grant |
| --- | --- | --- |
| `retrieve` | Find/rank a candidate from the source scope for a target-scope task. | `surface` or `cite` — retrieval is candidate generation, not disclosure or use. |
| `surface` | Show the candidate to the human in the target context. | `cite` — being shown is not being used as basis. |
| `cite` | Use the material as a stated basis in target-scope reasoning/output. | `import` — citing references; it does not copy in. |
| `import` | Copy material into the target scope as a new bound artifact. | `mutate` — importing creates; it does not change durable target knowledge. |
| `remember` | Let machine memory retain cross-scope material for recall. | canonical authority — memory is noncanonical until promoted. |
| `mutate` | Change accepted durable knowledge in the target scope. | self-authorization — requires a governed Authority Transition. |
| `execute` | Perform an authorized side effect informed by cross-scope material. | authorization — execution cannot authorize itself. |
| `export` | Send material outside the system/scope boundary entirely. | any of the above; export is its own high-sensitivity grant. |

Because the operations are independent, a flow that allows `retrieve` + `surface` as `background`
does **not** permit `cite`, `import`, `remember`, `mutate`, `execute`, or `export`.

## 3. The general_knowledge anti-bypass rule

> **`general_knowledge` may be a `source_role` or an eligibility signal, but it is not a universal
> bypass.** There is no `general_knowledge: true` flag that waves material across every scope.

General reusable knowledge can exist and can be widely useful, but each cross-scope use is still a
typed flow with explicit operations, evidence role, expiry, and audit. Marking material
`source_role: general_knowledge` makes it *eligible* to be named in a flow's `source_roles_allowed`;
it does not itself authorize any crossing. Re-introducing a global boolean bypass is an architecture
violation (see [doctrine](../foundation/00-yggdrasil-doctrine.md)).

## 4. Worked examples

Each example names source, target, operation(s), the evidence role in the target, and
confirmation/audit semantics.

### General programming knowledge → work project

- `source_scope`: general / `source_role: general_knowledge`; `target_scope`: a work project.
- `allowed_operations`: `retrieve`, `surface`, `cite` as **background/reference**.
- `evidence_roles_allowed`: `background`. `confirmation_required`: no; `audit_required`: yes.
- Reading: allowed as background/reference **only through an explicit flow** — never as real-world
  decision evidence, and not `import`/`mutate`.

### Private programming notes → work project

- `source_scope`: a private scope; `target_scope`: a work project.
- Default: **denied**. May cross only with `redaction_required` and `confirmation_required`, and only
  for promoted/accepted material.
- `allowed_operations`: at most `cite`/`import` after redaction + human confirmation;
  `audit_required`: yes.
- Reading: private → work is denied by default; crossing requires promotion, redaction, and explicit
  confirmation.

### RPG / worldbuilding → work project

- `source_scope`: RPG/worldbuilding (`source_role: fictional_simulation`); `target_scope`: work.
- `allowed_operations`: `retrieve`, `surface` as **analogy/inspiration** only, if explicitly
  permitted.
- `evidence_roles_allowed`: `analogy` / `inspiration`. **Never** `evidence`.
- Reading: usable as analogy/inspiration only when a flow explicitly allows it; fiction is never
  real-world evidence.

### Parent/master aggregate → configured descendant

- `source_scope`: a parent/master scope; `target_scope`: a configured descendant.
- `allowed_operations`: `retrieve`/`surface` of the **declared aggregation** only.
- Reading: configured parent aggregation is allowed **only as declared**. It does **not** imply
  sibling sharing — descendant and sibling scopes remain isolated unless their own explicit flow
  exists.

### Work Project Alpha ↔ Work Project Beta

- Two sibling work-project scopes.
- Default: **denied** in both directions. No flow exists implicitly because both are "work".
- Reading: sibling work projects are isolated; crossing requires an explicit, directional flow per
  direction. `↔` is shorthand for "needs two flows", not one bidirectional grant.

## Related documents

- [Doctrine](../foundation/00-yggdrasil-doctrine.md) — "similarity is not permission"
- [Functional ontology](functional-ontology.md) — `Scope`, `CrossScopeFlow`, `AuthorityReceipt`
- [Semantic dimensions](semantic-dimensions.md) — the dimensions a flow reads and may downgrade
- [Traceability matrix](traceability-matrix.md) — principle → flow → boundary → contract → test → issue
- [System Breakdown Structure](../SYSTEM_BREAKDOWN_STRUCTURE.md) — GOV/RCA/WSP boundaries
- Pending schema: metadata bundle ([#2544](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2544)); `RetrievalResult` candidate-evidence semantics ([#2548](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2548))
