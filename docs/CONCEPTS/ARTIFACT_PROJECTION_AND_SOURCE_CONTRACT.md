State: Concept contract companion (artifact/projection/source clarification; ontology-first, representation-cautious).

# Artifact, Projection, and Source Contract

## Purpose

This document sharpens three closely related concepts that are currently easy to flatten in runtime
and documentation language:
- `artifact`
- `projection`
- `source`

It exists so the repo can:
- keep the human-first ontology clear when runtime/store/search layers need representations,
- name projections without treating them as the primary thing,
- and clarify that `source` is primarily an epistemic role in context rather than a universal base
  artifact type.

This document is subordinate to:
- `docs/CONCEPTS/COGNITIVE_ONTOLOGY.md`
- `docs/CONCEPTS/ONTOLOGY_VOCABULARY.md`
- `docs/CONCEPTS/CONTEXT_REPRESENTATION_POSTURE.md`

It is upstream of:
- `docs/ARCHITECTURE.md`
- `docs/RETRIEVAL.md`
- `docs/COMPONENTS.md`

## Core rule

Artifacts are meaning-bearing things in the human domain.
Projections are bounded representations of artifacts for some surface, operation, or runtime need.
`Source` usually names a role an artifact plays in a context of inquiry, citation, grounding, or
reuse.

These three must not be silently collapsed.

## 1. Artifact

An artifact is the thing in the domain that bears meaning, use, commitment relevance, creative
potential, provenance, or long-horizon value.

Examples:
- a vault note,
- a retained PDF,
- a project brief,
- a reflective note,
- a creative fragment.

Artifacts may be:
- primary human artifacts,
- retained artifacts,
- creative artifacts,
- project artifacts,
- reflective artifacts,
- or system artifacts.

The artifact is the ontological referent.
It is not identical to every row, payload, index document, or mirror file that may later represent
it.

## 2. Projection

A projection is a bounded representation of an artifact created for a specific surface, operation,
or system need.

Problem solved:
- the runtime needs searchable records, store payloads, mirrors, frontmatter projections, retrieval
  documents, and response objects,
- but those representations are not ontologically the same thing as the underlying artifact.

Examples:
- a Core-6 frontmatter projection,
- a store object payload representing an ingested note,
- a mirror artifact that preserves selected metadata/history,
- a retrieval document used for scoring,
- an API response object pointing back to a cited artifact.

A projection:
- preserves only some aspects of the artifact,
- may be derived, partial, or operational,
- may be rebuildable,
- and may differ across devices, indexes, or runtime layers.

A projection should therefore be judged by:
- what it preserves,
- what it omits,
- what authority it has,
- and whether it remains linked to provenance and the underlying artifact.

### Projection is not automatically a system artifact

Some projections are system artifacts.
Some are only partial representations inside a runtime or store.

The important distinction is:
- `artifact` answers what the thing is in the domain,
- `projection` answers how that thing is represented for a bounded purpose.

Not every projection deserves its own durable artifact class.

## 3. Source as role

`Source` is canonically an epistemic role.

Problem solved:
- the same artifact may be cited, inspected, or relied on in one context,
- while functioning as draft, memory support, retained material, or project artifact in another.

Examples:
- a retained PDF plays a source role during retrieval or citation,
- a vault note plays a source role when later used as evidence,
- a meeting note may be a project artifact and also a source in a later synthesis.

So:
- `source` should usually be read as a role in context,
- not as the deepest intrinsic type of the artifact.

### Historical compatibility: `Source Artifact`

The repo may still use `Source Artifact` in some docs and runtime descriptions.

Read it as:
- an artifact functioning in a source role,
- or a shorthand for an artifact intentionally curated and commonly used as source material.

It should not be read as proof that `source` is always a separate ontological base class parallel to
every other artifact class.

## 4. Recommended interpretation by layer

### In ontology docs

Prefer:
- `artifact`
- `projection`
- `source role`

Avoid:
- using `object` as if it were the domain term,
- using `source` as if it were always an intrinsic type,
- or letting retrieval/store representations define the meaning of the artifact.

### In architecture docs

Use:
- `projection` for store/runtime/boundary representations,
- `artifact` for the domain referent,
- `source_ref` for the runtime pointer,
- and `source role` when the epistemic function matters.

### In retrieval docs

Treat:
- retrieval documents and hits as projections,
- cited evidence as artifacts currently playing a source role,
- and `source_ref` as runtime linkage rather than the whole semantics of sourcehood.

## 5. Stable consequences

1. A vault note is an artifact; its store row, frontmatter summary, retrieval document, and mirror
   are projections of it, not replacements for it.
2. A retained artifact often plays a source role, but retainedness and sourcehood are different
   ideas.
3. A retrieval hit is not the artifact itself; it is a projection pointing back to one.
4. Different projections of the same artifact may coexist without creating multiple ontological
   artifacts.
5. When projections disagree, provenance and artifact-level authority should determine what counts
   as the better representation.

## 6. Non-goals

This document does not yet define:
- a complete schema for projection records,
- how many durable projection types the runtime should have,
- or the full future relation between projections and multi-device instance provenance.

Those stay downstream of ontology clarification.

## Related documents

- `docs/CONCEPTS/COGNITIVE_ONTOLOGY.md`
- `docs/CONCEPTS/ONTOLOGY_VOCABULARY.md`
- `docs/CONCEPTS/CONTEXT_REPRESENTATION_POSTURE.md`
- `docs/CONCEPTS/MIRROR_RECEIPT_DECISION.md`
- `docs/ARCHITECTURE.md`
- `docs/RETRIEVAL.md`
