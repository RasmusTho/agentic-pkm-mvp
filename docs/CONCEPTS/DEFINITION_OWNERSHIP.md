State: Reference convention (semantic clarity; minimal working rule for concept ownership and change visibility).
Doc role: Reference
Authority: Defines the repo's minimal reference convention for where established concept definitions live, how downstream docs should relate to them, and how semantic changes should be made visible without adding governance overhead. It does not create or override concept meaning.
Owner: `docs/CONCEPTS/COGNITIVE_ONTOLOGY.md` and the specialist Core SoT concept docs that explicitly own narrower concept areas
Last reviewed: 2026-03-22

# Definition Ownership

## Purpose

This document defines a minimal working convention for semantic clarity across the repo.

It exists to answer four practical questions:

- where an established concept definition lives,
- how downstream docs should relate to that definition,
- how overlap between Core SoT concept docs is resolved,
- and how semantic changes are made visible without adding process overhead.

This document is intentionally small.
It does not introduce a new governance layer.

## Scope

This is a reference convention, not a new Core SoT semantic contract.

It applies when:
- a concept is already defined in a Core SoT concept doc,
- another doc uses that concept,
- or two Core SoT docs touch overlapping aspects of the same concept.

## Related Docs

- `docs/CONCEPTS/COGNITIVE_ONTOLOGY.md`
- `docs/CONCEPTS/ONTOLOGY_VOCABULARY.md`
- `docs/DOCS_INDEX.md`
- `docs/templates/DOC_TEMPLATE.md`

## Rule 1 - Owning definition

An established concept definition is owned by its Core SoT concept doc.

In practice:
- general ontology definitions are owned by `docs/CONCEPTS/COGNITIVE_ONTOLOGY.md`,
- specialist concept contracts own the narrower concept areas they explicitly declare,
- downstream docs should treat those owning concept docs as authoritative for meaning.

This document does not create new meanings.
It only makes ownership legible.

## Rule 2 - Precedence

When two Core SoT docs define overlapping aspects of the same concept:

- the more specific specialist concept doc governs within its explicitly declared scope,
- the general ontology governs outside that scope,
- and if there is still tension, the more recently reviewed doc is the temporary reading default until one of the docs records the conflict explicitly.

Conflicts should be resolved by clarifying one of the owning docs, not by allowing silent divergence to persist.

## Rule 3 - Downstream reference convention

Downstream docs must not silently introduce local redefinitions of terms already defined in Core SoT concept docs.

When precision matters, a downstream doc should say:
- `as defined in docs/CONCEPTS/...`

When precision does not require an explicit citation, the reader should assume that the Core SoT concept definition applies.

This is a reading and writing discipline, not a runtime mechanism.

## Rule 4 - Change visibility

When a semantic change is made to an established concept definition in an owning Core SoT doc, the maintainer should add a short `Changed:` note at the bottom of that owning doc.

A semantic change means the meaning of the concept changed, not merely wording, formatting, or copy editing.

The note should be one line and should name:
- the concept,
- the nature of the change,
- and the date.

Example:

- `Changed: Receipt - clarified that a receipt is a human-legible accountability record, not a generic runtime trace. 2026-03-22.`

No concept-level version numbers are required at this stage.

## Exclusions

This document does not own:
- ontology itself,
- trust gating or admissibility rules,
- event compatibility or schema versioning,
- runtime config precedence,
- prompt text ownership in general,
- approval workflows,
- runtime metadata fields such as semantic bundle references.

Those concerns remain with their existing owning docs and contracts.

## Practical posture

Use the smallest mechanism that prevents silent semantic drift.

Prefer:
- clear ownership,
- light reference discipline,
- and visible semantic change notes

over:
- new process,
- new runtime fields,
- or abstract governance machinery.
