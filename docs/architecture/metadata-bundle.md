State: Canonical Yggdrasil metadata bundle contract. Docs-only architecture/schema contract for the foundation backlog (#2533–#2552); defines the required semantic/provenance envelope every usable object carries. Pairs with `schemas/metadata-bundle.schema.json`. Does not claim shipped runtime behavior.
Doc role: Architecture / contract
Authority: Owns the field families, required fields, value families, and conditional rules of the metadata bundle — the physical envelope that carries the [semantic dimensions](semantic-dimensions.md) for every [functional-ontology](functional-ontology.md) object. The machine-readable contract is `schemas/metadata-bundle.schema.json`; this doc is its prose mirror. Subordinate to `docs/foundation/00-yggdrasil-doctrine.md`, `docs/architecture/functional-ontology.md`, and `docs/architecture/semantic-dimensions.md`.
Owner: Architecture spine
Temporal class: strategic
Review cadence: event-driven
Source of truth: canonical (metadata bundle contract); subordinate to doctrine, ontology, semantic dimensions
Last reviewed: 2026-07-01
Last verified against: docs/architecture/functional-ontology.md, docs/architecture/semantic-dimensions.md, docs/architecture/cross-scope-flow.md, docs/foundation/00-yggdrasil-doctrine.md, schemas/metadata-bundle.schema.json

# Yggdrasil Metadata Bundle

Parent epic: [#2533](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2533) ·
Contract issue: [#2544](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2544) ·
Schema: [`schemas/metadata-bundle.schema.json`](../../schemas/metadata-bundle.schema.json)

The metadata bundle is the **required semantic/provenance envelope for every usable Yggdrasil
object**. The system cannot enforce ontology, provenance, scope, authority, memory, retrieval, or
projection boundaries unless every usable object carries this metadata. This document defines the
field families and rules; the machine-checkable form is
[`schemas/metadata-bundle.schema.json`](../../schemas/metadata-bundle.schema.json).

Read first: the [doctrine](../foundation/00-yggdrasil-doctrine.md), the
[functional ontology](functional-ontology.md), and the [semantic dimensions](semantic-dimensions.md).
The bundle physically carries the orthogonal dimensions defined there; cross-scope use of objects
carrying a bundle is governed by [cross-scope-flow](cross-scope-flow.md). The other four contracts in
this batch — [context-envelope](context-envelope.md), [memory-model](memory-model.md),
[authority-transition-flow](authority-transition-flow.md), and
[retrieval-contract](retrieval-contract.md) — all reference this bundle.

## 1. What it carries (field families)

| Family | Fields | Notes |
| --- | --- | --- |
| **identity** | `object_id`, `object_type` | What this object is. `object_type` ∈ artifact, segment, claim, concept, relation, source, memory_item, proposal, projection, retrieval_result, context_item, authority_transition, execution_effect. |
| **location / context** | `vault_id`, `workspace_id`, `scope_id`, `sphere`, `principal_id`, `scope_binding` | Where and in what frame it lives. `vault_id` is storage topology; **it is not equivalent to `scope_id`** (a scope is a cognitive/audience/policy/provenance frame). |
| **semantics** | `source_role`, `authority_state`, `evidence_role`, `sensitivity`, `suppression_state` | The orthogonal [semantic dimensions](semantic-dimensions.md). The three role dimensions answer different questions and are never collapsed. |
| **provenance** | `created_by`, `created_at`, `derived_from`, `content_hash`, `provenance_event_ids` | Where it came from and **why it has the standing it has**. Provenance survives derivation. |
| **lifecycle** | `valid_at`, `invalid_at`, `indexed_at`, `suppression_state`, `sync_state`, `memory_state`, `execution_state`, `authority_receipt_ref` | Validity, indexing, suppression, replication, and (per type) memory/execution state. |

## 2. Supported object types

The same bundle describes every usable object: `artifact`, `segment`, `claim`, `concept`,
`relation`, `source`, `memory_item`, `proposal`, `projection`, `retrieval_result`, `context_item`,
`authority_transition`, and `execution_effect`. Not every type can carry every field, so the schema
uses **conditional requirements** (§4) rather than forcing one rigid shape.

This set is reconciled against the first-class metadata-bearing objects named in
[functional-ontology §3](functional-ontology.md#3-knowledge-and-meaning-terms): `Concept`,
`Relation`, and `Source` are usable, metadata-bearing ontology objects and are therefore
first-class `object_type` values here, alongside `Artifact`, `Segment`, and `Claim`.
`HumanArtifact` and `AcceptedArtifact` are states/subtypes of `Artifact` (distinguished by
`source_role`/`authority_state`, not by a separate `object_type`), so they carry `object_type:
artifact` rather than their own enum value. No first-class metadata-bearing ontology object is
usable per the functional ontology while being absent from this enum.

## 3. Required rules

These are encoded in the schema where possible and are load-bearing everywhere:

1. **No usable object without the core set.** Every object requires `object_id`, `object_type`,
   `scope_id`, `source_role`, `authority_state`, `evidence_role`, and provenance
   (`provenance_event_ids`, with `created_by`/`created_at`). `sensitivity` and `suppression_state`
   are also required.
2. **`vault_id` is not `scope_id`.** They are separate fields. Two objects in one vault may be in
   different scopes; one scope may span vaults.
3. **Derived/rebuildable objects must carry `derived_from`.** Segments, projections, retrieval
   results, and context items are regenerable; they must preserve provenance lineage.
4. **Projection is not evidence by default.** A `projection` defaults to a non-evidence role and may
   hold `evidence_role: evidence` only with a provenance-backed promotion (`authority_receipt_ref`).
5. **Memory is not canonical by default.** A `memory_item` carries `memory_state`; its standing is
   noncanonical unless promoted (see [memory-model](memory-model.md)).
6. **Source role does not imply authority.** Being human-authored or `agent_memory` sets origin, not
   standing. Authority changes only through a governed [authority transition](authority-transition-flow.md).
7. **Authority state does not imply evidence role.** Accepted material is not automatically
   admissible as evidence for every task; admissibility is its own field.

## 4. Schema requirements

[`schemas/metadata-bundle.schema.json`](../../schemas/metadata-bundle.schema.json):

- requires the core identity, semantic, and provenance fields above;
- defines `source_role`, `authority_state`, and `evidence_role` as **three separate required
  fields**, each with its own value family from [`schemas/_defs.schema.json`](../../schemas/_defs.schema.json)
  — they structurally cannot be collapsed into one;
- enumerates value families for `object_type`, `source_role`, `authority_state`, `evidence_role`,
  `sensitivity`, and `suppression_state`;
- applies conditional requirements: `derived_from` for derived types; `authority_receipt_ref` for
  canonical authority; `memory_state` plus a non-authoritative `evidence_role` (never real-world
  `evidence`), `source_role` fixed to `agent_memory`, and `authority_state` fixed to `noncanonical`
  for memory items — so a memory item carried only as a bundle cannot claim evidence, pass as
  human/shared source material, or hold any draft/proposed/canonical standing;
  `execution_state` + `authority_receipt_ref` for execution effects; `authority_receipt_ref` for a
  projection claiming evidence role;
- closes the object (`additionalProperties: false`) but provides an explicit `extensions` object for
  runtime evolution.

**Validation expectation.** A vector/chunk represented without scope, authority, source role,
evidence role, and provenance **fails** schema validation. There is no shape for a "naked vector".

## 5. Relationship to boundaries

The bundle is the shared currency of the control boundaries that must preserve meaning:

- [SIP](../boundaries/SIP.md) owns `source_role`, provenance/lineage, and the non-collapse rule
  (`metadata_bundle_required`, `provenance_survives_derivation`, `store_no_naked_vectors`).
- [HKA](../boundaries/HKA.md) durably carries the bundle on artifacts.
- [PDM](../boundaries/PDM.md) stores it without redefining meaning (`store_no_naked_vectors`).
- [DRI](../SYSTEM_BREAKDOWN_STRUCTURE.md) and [RCA](../boundaries/RCA.md) must preserve and carry the
  bundle forward into every derived representation and retrieval result.

## Related documents

- [Architecture context packet](../foundation/yggdrasil-architecture-context-packet.md) — full synthesis
- [System Breakdown Structure](../SYSTEM_BREAKDOWN_STRUCTURE.md) — owning control boundaries
- [Doctrine](../foundation/00-yggdrasil-doctrine.md) — the commitments this bundle enforces
- [Functional ontology](functional-ontology.md) — the objects the bundle describes
- [Semantic dimensions](semantic-dimensions.md) — the orthogonal metadata it carries
- [CrossScopeFlow](cross-scope-flow.md) — governed cross-scope use of bundled objects
- [Traceability matrix](traceability-matrix.md) — principle → contract → test → issue
- [Boundary charters](../boundaries/README.md) — [SIP](../boundaries/SIP.md), [HKA](../boundaries/HKA.md), [PDM](../boundaries/PDM.md), [RCA](../boundaries/RCA.md)
- Schema: [`schemas/metadata-bundle.schema.json`](../../schemas/metadata-bundle.schema.json) · shared defs [`schemas/_defs.schema.json`](../../schemas/_defs.schema.json)
