State: Canonical Yggdrasil MemoryItem contract and promotion boundary. Docs-only architecture/schema contract for the foundation backlog (#2533–#2552). Pairs with `schemas/memory-item.schema.json`. Does not claim shipped runtime behavior.
Doc role: Architecture / contract
Authority: Owns the `MemoryItem` contract — machine-memory types, lifecycle states, required fields, defaults, and the promotion boundary (MEM → GOV → HKA). The machine-readable form is `schemas/memory-item.schema.json`; this doc is its prose mirror. Subordinate to `docs/foundation/00-yggdrasil-doctrine.md`, `docs/architecture/functional-ontology.md`, and `docs/architecture/semantic-dimensions.md`; the durable-mutation path it requires is owned by `docs/architecture/authority-transition-flow.md`.
Owner: Architecture spine
Temporal class: strategic
Review cadence: event-driven
Source of truth: canonical (MemoryItem contract); subordinate to doctrine, ontology, semantic dimensions
Last reviewed: 2026-06-27
Last verified against: docs/architecture/semantic-dimensions.md, docs/architecture/metadata-bundle.md, docs/architecture/authority-transition-flow.md, docs/boundaries/MEM.md, docs/boundaries/GOV.md, docs/boundaries/HKA.md, schemas/memory-item.schema.json

# Yggdrasil Memory Model (MemoryItem)

Parent epic: [#2533](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2533) ·
Contract issue: [#2546](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2546) ·
Schema: [`schemas/memory-item.schema.json`](../../schemas/memory-item.schema.json)

Machine memory helps agents recall and reason **without becoming hidden authority**. A `MemoryItem`
is advisory and noncanonical until promoted into durable human knowledge through governance. This
document defines the memory types, lifecycle, fields, and promotion boundary; the machine-checkable
form is [`schemas/memory-item.schema.json`](../../schemas/memory-item.schema.json).

Read first: the [doctrine](../foundation/00-yggdrasil-doctrine.md) §2.4, the
[semantic dimensions](semantic-dimensions.md) (`memory_state`), the [MEM charter](../boundaries/MEM.md),
and the [metadata bundle](metadata-bundle.md).

## 1. Memory types

`memory_type` ∈ `episodic`, `semantic_machine_memory`, `procedural`, `reflection`,
`correction_signal`, `promotion_candidate`.

## 2. Lifecycle states

Memory lifecycle is tracked across three **disjoint** fields, so each lifecycle value lives in exactly
one place and the states cannot contradict each other (suppression, invalidation, tombstone, and purge
stub are **not** the same operation):

| Concern | Field | Values |
| --- | --- | --- |
| Recall / existence | `memory_state` | `unreviewed`, `reviewed`, `active`, `corrected`, `decayed`, `invalidated`, `forgotten`, `purged_stub` |
| Visibility | `suppression_state` | `visible`, `redacted`, `suppressed`, `withheld`, `tombstoned` |
| Governed promotion | `promotion_state` | `not_requested`, `promotion_requested`, `promoted`, `rejected` |

`memory_state` is a **superset of the canonical [semantic-dimensions](semantic-dimensions.md) review
family** (`unreviewed`, `reviewed`, `corrected`, `decayed`, `forgotten`) plus the existence states
(`active`, `invalidated`, `purged_stub`). Promotion and visibility are deliberately held in the other
two fields, so no value is duplicated and the states cannot contradict (`memory_state` contains only
recall/existence values and has no suppression or promotion values).

The lifecycle states this contract must support map to **exactly one** field each — no value is
duplicated across fields, so a memory can never look (e.g.) promoted in one field while another says
otherwise:

| Lifecycle state | Field = value |
| --- | --- |
| active | `memory_state = active` |
| suppressed | `suppression_state = suppressed` |
| invalidated | `memory_state = invalidated` |
| tombstoned | `suppression_state = tombstoned` |
| purged_stub | `memory_state = purged_stub` |
| promotion_requested | `promotion_state = promotion_requested` |
| promoted | `promotion_state = promoted` |
| rejected | `promotion_state = rejected` |

`suppression_state` is the cross-object visibility dimension shared with the
[metadata bundle](metadata-bundle.md); `promotion_state` is the governed-promotion sub-lifecycle.
Forgetting/suppression hides material from recall and context; it never erases lineage or provenance
(`purged_stub` retains lineage after the payload is purged). Promotion is governed: `promotion_state`
reaches `promoted` only through an [authority transition](authority-transition-flow.md) with a receipt
— `memory_state` carries no promotion value, so a memory can never *look* promoted without the governed
evidence.

## 3. Required fields

`memory_id`, `scope_id`, `workspace_id` (optional), `principal_id`, `memory_type`, `source_role`,
`authority_state`, `evidence_role`, `sensitivity`, `content`, `summary` (optional), `derived_from` (optional),
`created_by`, `created_at`, `valid_at`/`invalid_at` (optional), `memory_state`, `suppression_state`,
`promotion_state`, `promotion_request_id` (conditional), `authority_receipt_ref` (conditional),
`provenance_event_ids`.

### Required defaults

- `source_role` is **fixed** to `agent_memory` (the canonical machine-memory origin) — enforced as a
  schema `const`, not just a default, so a memory can never validate as human/shared source material
  and pass a [`CrossScopeFlow`](cross-scope-flow.md) `source_roles_allowed` filter as if human-authored.
- `authority_state` is **fixed to `noncanonical`** (a schema `const`, not merely a default). A memory
  record never holds `draft`/`proposed`/`accepted`/`canonical`/`deprecated`/etc. standing — so it can
  never pass an authority-state filter intended for drafts, proposals, or canonical material. Promotion
  does not make the memory canonical; it materializes a **separate** canonical artifact in HKA while the
  memory record itself stays noncanonical (MEM charter: "promoted reflects a GOV transition; it does
  not itself confer canonical authority").
- `evidence_role` = `background` (or `non_evidence`).

In the schema, a memory item's `evidence_role` is restricted to the non-authoritative roles
(`background`, `reference`, `analogy`, `inspiration`, `non_evidence`): a memory **cannot** carry
real-world `evidence` standing. To become factual evidence it must first be promoted into an HKA
artifact, after which it is no longer a memory. When `memory_state` is `purged_stub`, `content` must
be empty — the payload is purged while lineage/provenance is retained.

## 4. Required rules

1. **Machine memory is advisory until promoted.**
2. **Agent memory is noncanonical by default.**
3. **Memory may support recall/context but must not be cited as factual evidence** unless the claim is
   explicitly about the memory itself (e.g. "the agent previously recorded X"). The schema enforces
   this by excluding the `evidence` role from memory items.
4. **Promotion requires GOV authorization and HKA materialization.** MEM may *request* promotion; it
   cannot perform it. Promotion is a governed [authority transition](authority-transition-flow.md):
   MEM → GOV → HKA.
5. **Suppression, invalidation, tombstone, and purge stub are distinct** (§2).
6. **Memory must be scoped** (`scope_id` required); cross-scope recall requires a
   [`CrossScopeFlow`](cross-scope-flow.md) that allows `remember`.
7. **Memory must carry provenance** (`provenance_event_ids`).

## 5. Promotion boundary: MEM → GOV → HKA

```
MemoryItem (noncanonical — always)
  └─ promotion_state: promotion_requested  (MEM requests; promotion_request_id set)
       └─ AuthorityTransition (initiating_source: memory_promotion_request)   [GOV decides]
            ├─ approved  → HKA materializes a SEPARATE canonical AcceptedArtifact; AuthorityReceipt issued
            │             memory record: promotion_state=promoted, authority_receipt_ref set,
            │             authority_state STAYS noncanonical (the artifact is the canonical thing)
            └─ rejected  → memory: promotion_state=rejected (stays noncanonical)
```

It is **impossible for a memory item to be canonical**: the schema forbids `accepted`/`canonical`
`authority_state` on a memory entirely. The canonical result of a promotion is a separate HKA
artifact, not the memory; the memory record tracks the promotion through `promotion_state: promoted`
(with a `promotion_request_id` and `authority_receipt_ref`) while remaining noncanonical. This same
restriction is mirrored on a `memory_item` [metadata bundle](metadata-bundle.md), so a memory carried
as a bundle in a retrieval candidate or context item cannot be laundered into canonical authority
either.

## Related documents

- [Architecture context packet](../foundation/yggdrasil-architecture-context-packet.md)
- [System Breakdown Structure](../SYSTEM_BREAKDOWN_STRUCTURE.md)
- [Doctrine](../foundation/00-yggdrasil-doctrine.md) — memory is reconstructive and noncanonical until promoted
- [Functional ontology](functional-ontology.md) (`MemoryItem`) · [Semantic dimensions](semantic-dimensions.md) (`memory_state`) · [CrossScopeFlow](cross-scope-flow.md)
- [Metadata bundle](metadata-bundle.md) — a memory item is an `object_type: memory_item`
- [Authority transition flow](authority-transition-flow.md) — the governed promotion path
- [Existing MEM contract stub `MEMORY_RECORD.md`](../contracts/MEMORY_RECORD.md)
- [Traceability matrix](traceability-matrix.md)
- [Boundary charters](../boundaries/README.md) — [MEM](../boundaries/MEM.md), [GOV](../boundaries/GOV.md), [HKA](../boundaries/HKA.md), [SIP](../boundaries/SIP.md)
- Schema: [`schemas/memory-item.schema.json`](../../schemas/memory-item.schema.json) · shared defs [`schemas/_defs.schema.json`](../../schemas/_defs.schema.json)
