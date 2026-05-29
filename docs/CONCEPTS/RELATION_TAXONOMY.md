State: Concept contract (relation taxonomy and semantic link model; target-state semantics, not a runtime claim).
Doc role: Core SoT
Authority: Owns the relation taxonomy and semantic link model under Layer 1 (Ontology) of `docs/SEMANTIC_SYSTEM_ARCHITECTURE.md`: the canonical relation types, and for each one its semantic meaning, authorship/authority, governance posture, lifecycle, persistence, retrieval, and projection semantics. Consolidates relation concepts already present in the repo (companion linkage, provenance references, support/evidence, sphere membership, lifecycle relations); it does not redefine the owner contracts those relations belong to.
Owner: Relation taxonomy
Temporal class: strategic
Review cadence: event-driven
Source of truth: mixed
Last reviewed: 2026-05-29
Last verified against: docs/SEMANTIC_SYSTEM_ARCHITECTURE.md, docs/CONCEPTS/ONTOLOGY_VOCABULARY.md, docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md, docs/CONCEPTS/ARTIFACT_PROJECTION_AND_SOURCE_CONTRACT.md, docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md, docs/CONCEPTS/COMMITMENT_LAYER_CONTRACT.md, docs/CONCEPTS/LAYERING_MODEL.md, docs/GLOSSARY.md, docs/COMPONENTS.md, docs/plans/SPHERE_CONTEXT_ENABLEMENT_PREP.md, epic #1363, issue #1367.

# Relation Taxonomy and Semantic Link Model

A wiki-link (`[[Some Note]]`) is a single, untyped affordance that the system has historically had to overload to mean many different things — "see also", "this came from", "this supports that", "this replaces that". That overloading hides semantics inside a generic link and makes provenance, authority, and lifecycle invisible.

This document formalizes the **typed relation model**: the canonical relation types and, for each, what it means and what authority/governance/lifecycle/persistence/retrieval/projection semantics it carries. It is the relation detail for **Layer 1 (Ontology)** of `docs/SEMANTIC_SYSTEM_ARCHITECTURE.md`.

It is target-state semantics. Some relations already exist in the repo (`source_ref`, `supports`, `sphere_membership`, `derived_from`, `companion_for`, `supersedes`, `links_to`); others are named here so that future link semantics have a contract to attach to rather than being smuggled into generic links.

## Load-bearing principles

1. **A generic link carries no hidden semantics.** `links_to` means only "the human associated these"; it never silently implies provenance, support, or authority. Anything stronger must use a typed relation.
2. **A relation is not authority.** Relations describe how artifacts connect (Layer 1). Whether a connection grants a use right (e.g. an evidence relation making something action-authorizing) is decided by the authority matrix (`docs/SEMANTIC_AUTHORITY_MATRIX.md`), not by the relation's existence.
3. **Inferred ≠ authoritative.** A machine-derived or inferred relation is a Machine Mirror projection (Layer 6): rebuildable, non-authoritative, and never silently upgraded to a human-authored relation.
4. **Provenance relations are not editorial links.** `derived_from` / `source_ref` / `supports` carry epistemic weight and must be visible as provenance, not flattened into "see also".
5. **The stricter boundary wins.** An ambiguous or unclassified relation is treated as the weaker form (generic association, non-authoritative) until explicitly typed (consistent with `LAYERING_MODEL.md` rule 7).

## Relation attribute legend

For every relation the taxonomy records:

- **Authorship** — `human` (human-authored), `machine` (deterministically derived), `inferred` (heuristically suggested, needs confirmation), or `mixed`.
- **Authority** — `authoritative` (durable semantic edge), `supporting`, or `derived` (rebuildable; borrows authority from endpoints).
- **Governance-bearing** — does creating/changing this relation route through governance/receipts? (`yes`/`no`/`cond`).
- **Rebuildable** — can the relation be reconstructed from the artifacts if lost? (`yes` for machine/inferred, `no` for human-authored semantic edges).
- **Persistence** — where the relation durably lives: `frontmatter`/`body-link` (durable, human surface), `companion` (system-owned durable), `relation-store` (machine mirror, rebuildable), `runtime` (ephemeral).
- **Retrieval** — does the relation participate in retrieval/traversal? (`traversed`/`ranking-signal`/`audit-only`/`none`).
- **Projection** — how the UI should surface it (`link`/`provenance`/`lifecycle-badge`/`overlay`/`hidden`).

## Canonical relation table

| Relation | Meaning | Authorship | Authority | Gov-bearing | Rebuildable | Persistence | Retrieval | Projection |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `links_to` | Generic human association ("see also"); carries no further semantics | human | authoritative (as an association only) | no | no | body-link / frontmatter | traversed | link |
| `companion_for` | A companion note is *about* this primary artifact (companion → primary) | machine/mixed | supporting | cond | partial | companion + relation-store | audit-only | hidden / provenance |
| `has_companion` | Inverse of `companion_for` (primary → companion) | machine/mixed | supporting | cond | partial | relation-store | audit-only | hidden |
| `derived_from` | This artifact was produced from that source (transformation/summary) | machine/mixed | derived (provenance) | cond | yes | frontmatter / companion | audit-only / ranking-signal | provenance |
| `source_ref` | Mutable locator to the origin artifact (path-or-equivalent); identity/continuity aid, not stable primary identity | machine/mixed | derived (provenance/locator) | no | yes | frontmatter | audit-only | provenance |
| `supports` | That artifact is evidence/grounding for a claim in this artifact | human/inferred | supporting (epistemic) | cond | partial | frontmatter / companion | ranking-signal | provenance |
| `conflicts_with` | This artifact contradicts or tensions with that one | human/inferred | supporting (epistemic) | cond | partial | frontmatter / companion | ranking-signal | provenance / overlay |
| `supersedes` | This artifact replaces that one (lifecycle transition) | human | authoritative (lifecycle) | yes | no | frontmatter | traversed | lifecycle-badge |
| `part_of` | This artifact is a component of that larger structure (project/MOC/collection) | human | authoritative | no | no | frontmatter / body-link | traversed | link |
| `task_for` | This task/next-action advances that commitment/project | human | authoritative (commitment) | cond | no | frontmatter | traversed | link |
| `proposal_for` | This proposal targets that artifact (staged change → target) | machine/mixed | proposal-bearing | yes | partial | runtime → relation-store | audit-only | overlay |
| `decision_about` | This decision record settles a question about that artifact/topic | human | authoritative (governance-recorded) | yes | no | frontmatter / companion | traversed | provenance |
| `contextualizes` | That artifact provides situating context for this one (sphere/role/purpose framing) | mixed/inferred | supporting | cond | partial | companion / relation-store | ranking-signal | overlay |
| `sphere_membership` | This artifact participates in that sphere (shared participation across life areas) | human/inferred | supporting (context) | cond | partial | frontmatter / relation-store | ranking-signal / scope-filter | overlay |

## Relation authority semantics

- **Authoritative relations** (`links_to` as association, `supersedes`, `part_of`, `task_for`, `decision_about`) are durable semantic edges authored or confirmed by the human. They are not rebuildable from nothing and belong to the durable set.
- **Supporting relations** (`companion_for`/`has_companion`, `supports`, `conflicts_with`, `contextualizes`, `sphere_membership`) carry epistemic or contextual weight but do not by themselves grant use rights. Whether `supports` makes a source `action-authorizing` is decided by the authority matrix, not by the edge.
- **Derived/provenance relations** (`derived_from`, `source_ref`) borrow authority from their endpoints. They must be **visible as provenance**, never flattened into editorial association, and they never gain independent authority.
- **Proposal relations** (`proposal_for`) are non-durable until the proposal is applied; at application the durable record is the resulting receipt and any authoritative relation it writes (e.g. `supersedes`).

## Inferred vs authoritative relations

- A machine-inferred relation (e.g. an embedding-similarity `supports` suggestion, an inferred `sphere_membership`) is a **suggestion**, not a fact. It lives in the relation store as a Machine Mirror projection and must be surfaced as inferred, with a confirmation path to become human-authored.
- Confirming an inferred relation is a governed transition: the human (or an authorized rule) accepts it, optionally writing it to the durable surface (frontmatter/body) where it becomes authoritative.
- An inferred relation must never be rendered as if human-authored, and must never silently authorize action.

## Relation lifecycle semantics

- Relations have lifecycle states parallel to artifacts: `inferred → confirmed` (suggestion accepted), `active`, `superseded` (replaced by `supersedes`), `revoked` (relation removed without changing endpoints).
- `supersedes` is itself the canonical lifecycle relation: creating it transitions the superseded artifact's standing and should produce a receipt (governance-bearing).
- Revoking a relation does not delete the endpoint artifacts; it removes the edge and is auditable (consistent with the cross-scope-allowance revocation semantics in `LAYERING_MODEL.md`).

## Relation rebuildability semantics

- **Not rebuildable (durable edges):** human-authored `links_to`, `supersedes`, `part_of`, `task_for`, `decision_about`. These live on the human surface (frontmatter/body) and are part of the continuity set.
- **Rebuildable (mirror projections):** the relation-store representation of any edge, inferred `supports`/`contextualizes`/`sphere_membership`, and `proposal_for` edges. The RelationIndex/relation store is a Machine Mirror (Layer 6): it must be reconstructable from the durable surface + provenance and carries no independent authority (owner: `docs/COMPONENTS.md`, semantic map Layer 6).
- If losing a relation would lose human-authored meaning, it was a durable edge and must be persisted on the human surface, not only in the relation store.

## Relation persistence semantics

- **Durable human-surface relations** (`links_to`, `part_of`, `supersedes`, `task_for`, `decision_about`, confirmed `supports`/`sphere_membership`) persist in frontmatter or body links and follow the frontmatter write contract (`docs/FRONTMATTER.md`) and write-guard rules.
- **System-owned relations** (`companion_for`/`has_companion`) persist via the companion note pattern and the relation store.
- **Provenance relations** (`derived_from`, `source_ref`) persist in frontmatter/companion as provenance fields; `source_ref` is explicitly a mutable secondary locator, not stable primary identity (owner: `docs/GLOSSARY.md`).
- **Inferred/runtime relations** persist only in the relation store (rebuildable) until confirmed; `proposal_for` is runtime/staged until application.

## Relation retrieval semantics

- **Traversed** relations (`links_to`, `part_of`, `task_for`, `supersedes`, `decision_about`) drive graph traversal and backlinking.
- **Ranking-signal** relations (`supports`, `conflicts_with`, `contextualizes`, `sphere_membership`, `derived_from`) inform retrieval ranking/scope but do not by themselves admit an artifact into working context — activation rules still apply (owner: `CONTEXT_ACTIVATION_SEMANTICS.md`).
- **Scope-filter:** `sphere_membership` may scope default retrieval to the active operational scope; cross-scope traversal requires explicit allowance (owner: `LAYERING_MODEL.md`).
- **Audit-only** relations (`companion_for`, `derived_from`, `source_ref`, `proposal_for`) are primarily for provenance/audit surfaces, not for content retrieval.

## UI projection guidance

- Render **provenance relations** (`derived_from`, `source_ref`, `supports`, `conflicts_with`) as visible provenance, never as plain "see also" links — preserving the fact/inference/stale distinction (owner: semantic map Layer 7, #1368).
- Render **lifecycle relations** (`supersedes`) as a lifecycle badge, not a navigational link.
- Render **inferred relations** with an explicit inferred marker and a confirm/dismiss affordance; never as confirmed edges.
- Keep **system relations** (`companion_for`/`has_companion`, `proposal_for`) out of the human's primary reading surface by default; surface them in audit/provenance/overlay views.

## Cross-references

- Parent semantic map (Layer 1 ontology, Layer 7 projection): `docs/SEMANTIC_SYSTEM_ARCHITECTURE.md`.
- Term canonicalization (`source`, `projection`, `relation`): `docs/CONCEPTS/ONTOLOGY_VOCABULARY.md`, `docs/CONCEPTS/ARTIFACT_TERMINOLOGY_NORMALIZATION.md`.
- Authority flags for relation endpoints: `docs/SEMANTIC_AUTHORITY_MATRIX.md`.
- Companion linkage: `docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md`.
- Provenance/source role: `docs/CONCEPTS/ARTIFACT_PROJECTION_AND_SOURCE_CONTRACT.md`.
- Commitment relations (`task_for`, `part_of` for projects): `docs/CONCEPTS/COMMITMENT_LAYER_CONTRACT.md`.
- Sphere membership / cross-scope: `docs/CONCEPTS/LAYERING_MODEL.md`, `docs/plans/SPHERE_CONTEXT_ENABLEMENT_PREP.md`.
- Relation store as machine mirror: `docs/COMPONENTS.md`, #1370 follow-up.

## Verification path

This document is verified by the existence of:
- a **canonical relation table** covering at least `links_to`, `companion_for`, `has_companion`, `derived_from`, `source_ref`, `supports`, `conflicts_with`, `supersedes`, `part_of`, `task_for`, `proposal_for`, `decision_about`, `contextualizes` (plus `sphere_membership`), each with authorship, authority, governance, rebuildability, persistence, retrieval, and projection semantics;
- explicit **inferred-vs-authoritative** and **provenance-relation** rules ensuring no hidden semantics inside generic links; and
- alignment of provenance-sensitive relations with the provenance/source contract and the authority matrix.
