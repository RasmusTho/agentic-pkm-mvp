State: Canonical Yggdrasil semantic dimensions. Docs-only architecture contract for the foundation backlog (#2533–#2552); defines the orthogonal metadata that preserves meaning across storage, indexing, retrieval, memory, projection, and agent use. Does not claim shipped runtime behavior.
Doc role: Architecture / semantic model
Authority: Owns the orthogonal semantic dimensions (metadata fields) that every Yggdrasil object carries and that must not be collapsed. Its central commitment: `source_role`, `authority_state`, and `evidence_role` are independent and answer different questions. Subordinate to `docs/foundation/00-yggdrasil-doctrine.md` and `docs/architecture/functional-ontology.md`; the physical field bundle is owned by the metadata bundle schema (#2544).
Owner: Architecture spine
Temporal class: strategic
Review cadence: event-driven
Source of truth: canonical (dimension definitions); subordinate to doctrine and ontology
Last reviewed: 2026-06-26
Last verified against: docs/foundation/00-yggdrasil-doctrine.md, docs/architecture/functional-ontology.md, docs/foundation/yggdrasil-architecture-context-packet.md

# Yggdrasil Semantic Dimensions

Parent epic: [#2533](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2533)

This document defines the metadata fields that preserve meaning as objects move across storage,
indexing, retrieval, memory, projection, and agent use. Each dimension is a **separate question**.
The architecture's core failure mode is collapsing different questions into one field; this document
exists to make that collapse visibly violate the contract.

Read first: the [doctrine](../foundation/00-yggdrasil-doctrine.md) and the
[functional ontology](functional-ontology.md). The physical field bundle that carries these
dimensions is the metadata bundle schema
([#2544](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2544)); the cross-scope use of objects
carrying these dimensions is governed by [cross-scope-flow](cross-scope-flow.md). Tests/invariants
are pinned by the invariant registry
([#2550](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2550)) and the anti-contamination eval
corpus ([#2551](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2551)).

## 1. The non-collapse rule (read first)

> **`source_role`, `authority_state`, and `evidence_role` are orthogonal.** They are three
> independent fields and must never be merged, inferred from one another, or stored as one value.

They answer different questions:

- **`source_role`** answers: *where did this come from and what kind of source is it?*
- **`authority_state`** answers: *what standing does it currently have?*
- **`evidence_role`** answers: *what may it do in reasoning?*

The forbidden inferences:

- `source_role` **does not** imply `authority_state`. Being human-authored does not make material
  accepted; being `agent_memory` does not make it noncanonical *by policy* — the state field says so
  explicitly.
- `authority_state` **does not** imply `evidence_role` (admissibility). Accepted material is not
  automatically admissible as evidence for every reasoning task; admissibility is its own field.
- `evidence_role` **does not** imply permission to retrieve or cite across a boundary. Even
  `evidence`-roled material may be retrieved/cited across scopes only through a typed
  [`CrossScopeFlow`](cross-scope-flow.md). Similarity is not permission.

A single object legitimately holds different values on all three at once. See the worked
[examples](#4-worked-examples).

## 2. Dimension definitions

For each dimension: the question it answers, allowed value families (initial, extensible), owning
control boundary, the required metadata field, and what must **not** be inferred from it. Owning
boundaries are defined in the [System Breakdown Structure](../SYSTEM_BREAKDOWN_STRUCTURE.md).

### `source_role`

- **Question:** Where did this come from, and what kind of source is it?
- **Value families:** `human_note`, `human_capture`, `decision_record`, `work_project`,
  `private_note`, `general_knowledge`, `agent_memory`, `agent_proposal`, `fictional_simulation` /
  `rpg_rule`, `external_source`, `projection` / `machine_mirror`. (Extensible; `general_knowledge`
  is a **source role**, not a cross-scope bypass — see [cross-scope-flow](cross-scope-flow.md).)
- **Owning boundary:** SIP (provenance/origin).
- **Required field:** `source_role`.
- **Must NOT be inferred:** authority/standing, evidence admissibility, or permission to cross a
  scope. Origin alone decides none of these.
- **Invariant:** TBD ([#2551](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2551)) — origin
  classification preserved through derivation.

### `authority_state`

- **Question:** What standing does this currently have?
- **Value families:** `captured`, `draft`, `proposed`, `working_fiction` / `fictional_canon`,
  `accepted` / `canonical`, `noncanonical`, `derived` / `projection`, `deprecated` / `retracted`.
- **Owning boundary:** GOV (standing is a governed state).
- **Required field:** `authority_state`.
- **Must NOT be inferred:** origin (who wrote it) or evidence admissibility. Authority is changed
  only by a governed transition with an `AuthorityReceipt`.
- **Invariant:** TBD ([#2550](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2550)) — no field
  promotes `authority_state` without a receipt.

### `evidence_role`

- **Question:** What may this do in reasoning?
- **Value families:** `evidence`, `background` / `reference`, `analogy` / `inspiration`,
  `non_evidence`.
- **Owning boundary:** GOV (admissibility); consumed by RCA and CAO.
- **Required field:** `evidence_role`.
- **Must NOT be inferred:** from `source_role` or `authority_state`, and it does **not** grant
  retrieval or citation rights across scopes (that is a `CrossScopeFlow`).
- **Invariant:** TBD ([#2551](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2551)) — fiction /
  agent memory never silently roled as real-world `evidence`.

### `sensitivity`

- **Question:** How confidential is this; who may see it?
- **Value families:** `public`, `internal`, `private`, `secret`.
- **Owning boundary:** GOV (policy); honored by HIX at surfaces and RCA before context assembly.
- **Required field:** `sensitivity`.
- **Must NOT be inferred:** evidence role or authority. A `secret` decision can still be `evidence`
  for the human; sensitivity governs disclosure, not reasoning standing.
- **Invariant:** TBD ([#2551](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2551)).

### `scope_binding`

- **Question:** Which scope(s) does this belong to?
- **Value families:** one or more `scope_id`s (plus optional `sphere`); `bound` vs `unbound`.
- **Owning boundary:** WSP (scope); GOV for the policy facet.
- **Required field:** `scope_binding`.
- **Must NOT be inferred:** permission to use the object in another scope. Binding states membership,
  not cross-scope rights; crossing requires a `CrossScopeFlow`.
- **Invariant:** TBD ([#2550](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2550)) —
  scope_binding propagated through segment/projection/retrieval.

### `suppression_state`

- **Question:** Is this currently withheld, redacted, or tombstoned from surfacing/use?
- **Value families:** `visible`, `redacted`, `suppressed` / `withheld`, `tombstoned`.
- **Owning boundary:** GOV (decision); honored by HIX, RCA, DRI.
- **Required field:** `suppression_state`.
- **Must NOT be inferred:** deletion of meaning or loss of provenance. Suppression hides; it does
  not erase lineage or authority history.
- **Invariant:** TBD ([#2551](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2551)) — suppressed
  material excluded from retrieval/context.

### `memory_state`

- **Question:** Where is this in the machine-memory lifecycle?
- **Value families:** `unreviewed`, `reviewed`, `promoted`, `corrected`, `decayed`, `forgotten`.
- **Owning boundary:** MEM (lifecycle); GOV for the promotion transition.
- **Required field:** `memory_state`.
- **Must NOT be inferred:** canonical authority or evidence standing. `promoted` means a governed
  transition into HKA occurred — the resulting `authority_state` is set by that transition, not by
  `memory_state` alone.
- **Invariant:** TBD ([#2546](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2546),
  [#2550](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2550)).

### `sync_state`

- **Question:** What is the replication/convergence status across nodes?
- **Value families:** `local_only`, `pending`, `synced`, `conflicted`, `diverged`.
- **Owning boundary:** SFC.
- **Required field:** `sync_state`.
- **Must NOT be inferred:** authority, scope membership, or evidence role. Sync preserves boundaries;
  it never promotes or rescopes. A conflict is resolved through governance, not by last-writer-wins
  over meaning.
- **Invariant:** TBD ([#2550](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2550)).

### `execution_state`

- **Question:** What is the status of an authorized side effect associated with this?
- **Value families:** `none`, `proposed`, `authorized`, `executing`, `succeeded`, `failed`,
  `rolled_back`.
- **Owning boundary:** EXE (status); GOV for the authorization.
- **Required field:** `execution_state`.
- **Must NOT be inferred:** authorization itself. `authorized` reflects a prior GOV grant/receipt;
  execution cannot authorize itself.
- **Invariant:** TBD ([#2550](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2550)).

## 3. Dimension summary

| Dimension | Question | Owning boundary | Required field | Must not be inferred |
| --- | --- | --- | --- | --- |
| `source_role` | Where from / what kind of source? | SIP | `source_role` | authority, evidence, cross-scope permission |
| `authority_state` | What standing now? | GOV | `authority_state` | origin, evidence admissibility |
| `evidence_role` | What may it do in reasoning? | GOV (admissibility) | `evidence_role` | from source/authority; retrieve/cite rights |
| `sensitivity` | How confidential? | GOV | `sensitivity` | evidence role, authority |
| `scope_binding` | Which scope(s)? | WSP / GOV | `scope_binding` | cross-scope permission |
| `suppression_state` | Withheld/redacted/tombstoned? | GOV | `suppression_state` | erasure of meaning/provenance |
| `memory_state` | Memory-lifecycle position? | MEM / GOV | `memory_state` | canonical authority / evidence |
| `sync_state` | Replication/convergence status? | SFC | `sync_state` | authority, scope, evidence |
| `execution_state` | Side-effect status? | EXE / GOV | `execution_state` | authorization itself |

## 4. Worked examples

Each row shows the three orthogonal role dimensions holding **different, non-contradictory** values
on one object.

### RPG / worldbuilding material

- `source_role: fictional_simulation` (or `rpg_rule`)
- `authority_state: fictional_canon` (or `working_fiction`)
- `evidence_role: analogy` / `inspiration` — **not** real-world evidence
- `scope_binding`: an RPG/worldbuilding scope; `sensitivity: private` typical
- Reading: canonical *within the fiction*, usable as analogy/inspiration, never admissible as
  real-world evidence, and not usable in a `work` scope except through an explicit
  [`CrossScopeFlow`](cross-scope-flow.md).

### Agent memory

- `source_role: agent_memory`
- `authority_state: noncanonical`
- `evidence_role: background` / `non_evidence`
- `memory_state: unreviewed` → `reviewed` → `promoted`
- Reading: advisory recall. It influences reasoning as background only and becomes durable knowledge
  solely through a governed promotion that sets a new `authority_state` — never by `memory_state`
  alone.

### Work decision

- `source_role: work_project` (or `decision_record`)
- `authority_state: accepted` / `canonical`
- `evidence_role: evidence`
- `scope_binding`: a specific work-project scope; `sensitivity: internal`/`private`
- Reading: accepted, citable evidence **within its scope**; using it in another work project still
  requires an explicit `CrossScopeFlow` (Project Alpha → Project Beta is denied by default).

### Projection / dashboard / summary

- `source_role: projection` (or `object_type: projection`)
- `authority_state: projection` / `derived`
- `evidence_role: non_evidence` — unless promoted/cited through provenance
- `scope_binding`: inherited from its sources; `rebuildable: true`
- Reading: a derived view. It is never evidence by default and gains evidence standing only by an
  explicit, provenance-backed promotion of the underlying material — not by appearing in a summary.

## Related documents

- [Doctrine](../foundation/00-yggdrasil-doctrine.md) — the commitments these dimensions enforce
- [Functional ontology](functional-ontology.md) — the objects that carry these dimensions
- [CrossScopeFlow](cross-scope-flow.md) — why `evidence_role` is not retrieval/citation permission
- [Traceability matrix](traceability-matrix.md) — principle → dimension → boundary → contract → test → issue
- [System Breakdown Structure](../SYSTEM_BREAKDOWN_STRUCTURE.md) — the owning control boundaries
- Pending schema: metadata bundle ([#2544](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2544)) — the field bundle that physically carries these dimensions
