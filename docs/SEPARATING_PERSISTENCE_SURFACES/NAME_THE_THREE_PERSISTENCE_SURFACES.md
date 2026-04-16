---
name: Name The Three Persistence Surfaces
description: Core naming specification establishing the writing, retention, and system persistence surfaces with stable identities and invariants
task_id: SEPSURF-01
source_anchor: docs/plans/V60_ARCHITECTURE_TARGET.md :: Pillar 4 (explicit persistence surfaces)
parent_capability: Separating Persistence Surfaces
prerequisites: none
depends_on: []
can_parallelize_with: []
---

State: Implementation complete. Foundational naming task delivered.

# The Three Persistence Surfaces

## Why three, not one

The runtime must not allow the three persistence surfaces to collapse into a single undifferentiated "storage" layer. If they do — if a mirror becomes the master, a receipt becomes just another log line, if the system surface silently becomes the only real source of meaning — the user loses the guarantee that their central artifacts remain intelligible without the runtime. 

This is the cognitive-prosthetic guarantee (source: `docs/plans/V60_ARCHITECTURE_TARGET.md` §Pillar 3, §Pillar 4): the user must be able to point at a file and say "**mine** / **copy** / **bookkeeping**" without needing hidden machinery to understand it. The three surfaces are how the runtime defends this guarantee.

These three surfaces exist to make surface authority explicit and to prevent silent collapse. They interact — a writing-surface artifact may cite retained material, retained material may have system-surface projections — but they must never be read as one storage concept.

## The Writing Surface

**Identity:** The persistence surface the human owns outright. Authorship, editability, and intelligibility-without-the-runtime are its defining properties.

**Holds:**
- Settled human notes
- In-progress notes
- Creative fragments
- Parallel alternatives
- Revision variants
- Partially stabilized creative threads
- Drafts the human chooses never to finish

**What the human expects:** This is my work. I author it. The runtime may assist (suggest, annotate, cite), but I own the final word. I can leave things unfinished, explore alternatives, and return to rework them. No runtime component rewrites what I have written.

**Must never silently become:**
- A source of meaning *for* the system (machine-owned state)
- A dumping ground for retained source material
- A log of system action
- A replica of runtime state
- A place where fragments are forced to resolve into finished notes before acceptance

**Contract:** See [DEFINE_WRITING_SURFACE_CONTRACT.md](DEFINE_WRITING_SURFACE_CONTRACT.md)

## The Retention Surface

**Identity:** The persistence surface that preserves source-rich material for citation, grounding, rediscovery, and later reuse. Retained artifacts are kept because they carry value for future reference, not because the human is actively editing them right now.

**Holds:**
- Quoted source material
- Research notes and references
- Cited documents and excerpts
- Material retained for grounding and reuse
- Archive-quality artifacts kept for provenance
- Source material that feeds active notes

**What the human expects:** When I retain something, I choose to keep it because I might need it again. I can search for it, cite it, and build new work from it. It is not lost just because I moved on to other work. It is not replaced by whatever I find most convenient to search for right now.

**Must never silently become:**
- Absorbed into the writing surface (so retained material is not lost to editing cycles)
- A dumping ground for runtime bookkeeping
- Treated as equivalent to indexes or search results (which are derived, not retained)
- Overwritten by system surface projections or indexes

**Contract:** See [DEFINE_RETENTION_SURFACE_CONTRACT.md](DEFINE_RETENTION_SURFACE_CONTRACT.md)

## The System Surface

**Identity:** Where the runtime keeps the structures it needs to do its own job — portable projections of human artifacts, indexes, receipts, execution traces, ingest state, audit rows, queue/outbox records, and similar machine-owned support structures. The system surface is structurally supportive, never central.

**Holds:**
- Mirrors (portable projections of human artifacts, used for continuity and identity)
- Receipts (human-legible accountability records of what happened, under what authority)
- Operational traces (runtime coordination and diagnostic records)
- Audit records (durable inspectable records for later review)
- Indexes, embeddings, retrieval documents (system-owned representations used to find or rank artifacts)
- Ingest state and healing metadata (runtime's own notes about what it has tracked and repaired)
- Queue/outbox records and execution artifacts (machine coordination records)

**What the human expects:** The system surface is honest about what the machine did. It tells me when something was found, when something was attempted, when something was cached, when something was repaired. But it is never the source of meaning for my artifacts. I can inspect it, but I do not author it.

**Must never silently become:**
- The only real source of meaning (this is the hardest invariant; if the system surface becomes the de facto center, the user loses the guarantee that central artifacts are intelligible without the runtime)
- The master of a human artifact (a mirror must never replace the human original)
- The replacement for the writing surface (no hidden master)
- The replacement for the retention surface (no quiet absorption of retained source material)
- Treated as human-legible accountability when it is only diagnostic (receipt ≠ trace; see task 5)
- Written to by user-facing flows as a shortcut to avoid writing-surface authorship rules
- The effective definition of an artifact (an index entry must never become the canonical truth about what an artifact contains)

**Contract:** See [DEFINE_SYSTEM_SURFACE_CONTRACT.md](DEFINE_SYSTEM_SURFACE_CONTRACT.md)

## Invariants across all three

1. **Surfaces interact but do not collapse.** The writing surface may cite retained material. Retained material may have system-surface projections. Human artifacts may have mirrors and receipts on the system surface. But these are *about* each other, not *instances* of each other. A mirror is not a copy of the note that the human reads; it is a machine representation *about* the note.

2. **The system surface must never silently become the only real source of meaning.** (Source: `docs/plans/V60_ARCHITECTURE_TARGET.md` §Pillar 3, §Pillar 4, §Delta 3.) This invariant defends the cognitive-prosthetic guarantee. Every time a mirror becomes the master, a receipt becomes just another log line, an index entry becomes the de-facto artifact, the user loses a piece of the "I can still read my own work without the runtime" promise. Naming this rule and placing it at the center of the contract is what stops that drift before it is rationalized into a convenience.

3. **Classification of any concrete artifact must be unambiguous.** When the runtime encounters a vault note, a companion note, a VaultMirror, a store payload, an outbox event, an audit row, an index record, or a status callout, there must be no ambiguity about which surface it belongs to. The three-surface model exists to make this classification clear and defensible.

---

## Purpose (Original Specification Section)

Establish the three persistence surfaces as first-class named concepts with stable identities, invariants, and "must never silently become" rules. This is the foundational naming task: every subsequent task in this capability refers back to the trichotomy defined here. Without this document the remaining specs have nothing to ground against.

## What This Task Does

Produces a single document whose body contains:

1. A short framing of why persistence surfaces need to be separated at all, anchored in the v6.0 target and the cognitive-prosthetic framing.
2. The three named surfaces:
   - **Writing surface** — human-authored editable artifacts;
   - **Retention surface** — retained source-rich artifacts kept for citation and later reuse;
   - **System surface** — mirrors, receipts, indexes, traces, execution artifacts, and runtime support structures.
3. For each surface:
   - a one-line identity,
   - a description of what it holds,
   - a description of what the human expects from it,
   - an explicit "must never silently become" list naming the collapses this document exists to prevent,
   - a reference to any subordinate surface contract (tasks 2, 3, 4).
4. The rule that these surfaces **interact** but must not be treated as one undifferentiated `notes/storage` layer (directly quoted from `V60_ARCHITECTURE_TARGET.md` §Pillar 4 at the level of invariant, not verbatim text).
5. The rule that the system surface must not silently become the only real source of meaning simply because it is structurally convenient (`V60_ARCHITECTURE_TARGET.md` §Pillar 4 implication, §Delta 3).

This document stops at naming. It does not define the internal contract of any single surface; those live in tasks 2, 3, and 4.

Establish the three persistence surfaces as first-class named concepts with stable identities, invariants, and "must never silently become" rules. This is the foundational naming task: every subsequent task in this capability refers back to the trichotomy defined here. Without this document the remaining specs have nothing to ground against.

## What This Task Does

Produces a single document whose body contains:

1. A short framing of why persistence surfaces need to be separated at all, anchored in the v6.0 target and the cognitive-prosthetic framing.
2. The three named surfaces:
   - **Writing surface** — human-authored editable artifacts;
   - **Retention surface** — retained source-rich artifacts kept for citation and later reuse;
   - **System surface** — mirrors, receipts, indexes, traces, execution artifacts, and runtime support structures.
3. For each surface:
   - a one-line identity,
   - a description of what it holds,
   - a description of what the human expects from it,
   - an explicit "must never silently become" list naming the collapses this document exists to prevent,
   - a reference to any subordinate surface contract (tasks 2, 3, 4).
4. The rule that these surfaces **interact** but must not be treated as one undifferentiated `notes/storage` layer (directly quoted from `V60_ARCHITECTURE_TARGET.md` §Pillar 4 at the level of invariant, not verbatim text).
5. The rule that the system surface must not silently become the only real source of meaning simply because it is structurally convenient (`V60_ARCHITECTURE_TARGET.md` §Pillar 4 implication, §Delta 3).

This document stops at naming. It does not define the internal contract of any single surface; those live in tasks 2, 3, and 4.

## Concretely

The final document should be readable as the "the three surfaces" one-pager a reviewer can point at when any question of the form *"which surface does X belong to?"* comes up. A reader finishing this document should be able to:

- name the three surfaces,
- say in one sentence each what they hold,
- state at least one thing each must never become,
- explain why the collapse is a user-facing problem, not merely an architectural taste issue.

Expected structure (not prescriptive wording):

```
# The Three Persistence Surfaces

## Why three, not one
[Cognitive-prosthetic framing: user must be able to point and say
  "mine / copy / bookkeeping" without hidden machinery.]

## The writing surface
- Identity: ...
- Holds: ...
- Must never silently become: ...
- Contract: DEFINE_WRITING_SURFACE_CONTRACT.md

## The retention surface
- Identity: ...
- Holds: ...
- Must never silently become: ...
- Contract: DEFINE_RETENTION_SURFACE_CONTRACT.md

## The system surface
- Identity: ...
- Holds: ...
- Must never silently become: ...
- Contract: DEFINE_SYSTEM_SURFACE_CONTRACT.md

## Invariants across all three
- surfaces may interact but must not be read as one "storage" layer,
- the system surface must not become the only real source of meaning,
- classification of any concrete artifact must be unambiguous.
```

## Why This Matters

If the three surfaces are not named, the existing runtime documentation keeps reading them as one loose storage layer, and each new runtime concern (a mirror, a receipt, an index, a trace) gets silently dropped into the nearest available bucket. That bucket then accretes meaning until the system surface becomes the real center of gravity and the user loses the ability to distinguish what is theirs from what is machine bookkeeping. The cognitive-prosthetic guarantee — that central artifacts remain intelligible without hidden machinery — collapses quietly long before anyone notices.

Naming the three surfaces is the smallest atomic move that blocks that drift. It is also a prerequisite for every other task in this capability: nothing downstream can ground its language without this anchor.

## Acceptance Criteria

- [ ] The document names all three surfaces with stable identities.
- [ ] Each surface has a "holds" description and a "must never silently become" list.
- [ ] Each surface points forward to its dedicated contract task file.
- [ ] The cognitive-prosthetic framing ("mine / copy / bookkeeping") is present.
- [ ] The invariant that the system surface must not become the only real source of meaning is present and cited to `V60_ARCHITECTURE_TARGET.md` §Pillar 4 / §Delta 3 / §Pillar 3.
- [ ] The document does not attempt to define the internal contract of any individual surface.
- [ ] The document does not prescribe storage layout, paths, schemas, or migration steps.
- [ ] The document does not reference companion-note implementation shape (naming-only; citation is fine).
- [ ] The document does not touch Finding 4 or Finding 5.

## How to Verify (Pre-Merge)

- Read the document top-to-bottom as a reviewer who has never seen the capability. Can they name the three surfaces afterward? Can they state one "must never become" rule per surface?
- Grep the document for any mention of field names, file paths, schema shapes, migration steps, or companion-note implementation details. There should be none.
- Grep for "Finding 4" and "Finding 5". These should not appear in this task file (they belong to `DISTINGUISH_MIRROR_RECEIPT_TRACE.md`).
- Confirm forward pointers to the three contract tasks are present.
- Confirm no file outside `docs/SEPARATING_PERSISTENCE_SURFACES/` is modified in the delivering PR.

## Out of Scope

- Defining the internal contract of any surface in detail (tasks 2, 3, 4).
- Distinguishing mirror, receipt, operational trace, and index/projection inside the system surface (task 5).
- Classifying concrete runtime artifacts (task 6).
- Moving files on disk, touching ingest, or changing VaultMirror.
- Designing schema, event payloads, paths, or graph shape.
- Prescribing the companion-note migration.
- Resolving Finding 4 or Finding 5.

## Related Docs

- `docs/plans/V60_ARCHITECTURE_TARGET.md` §Pillar 3, §Pillar 4, §Pillar 10, §Delta 3, §Delta 4
- `docs/CONCEPTS/ARTIFACT_PROJECTION_AND_SOURCE_CONTRACT.md`
- `docs/CONCEPTS/USER_NEEDS_MODEL.md`
- `docs/HUMAN-FLOWS.md`

## Related GitHub Issues

When implementing, a single GitHub issue is sufficient. Use: "Implements SEPARATING_PERSISTENCE_SURFACES/NAME_THE_THREE_PERSISTENCE_SURFACES". Use the acceptance criteria above as the issue contract.

---

**Status:** Specification ready. No blockers.
