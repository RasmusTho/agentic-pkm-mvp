---
name: Define Writing Surface Contract
description: Contract for the writing surface - human-authored editable artifacts that must tolerate fragments, alternatives, and selective stabilization
task_id: SEPSURF-02
source_anchor: docs/plans/V60_ARCHITECTURE_TARGET.md :: Pillar 4, Pillar 12; docs/CONCEPTS/CREATIVE_PROCESS_CONTRACT.md
parent_capability: Separating Persistence Surfaces
prerequisites: [SEPSURF-01]
depends_on: [NAME_THE_THREE_PERSISTENCE_SURFACES.md]
can_parallelize_with: []
---

State: Specification ready. Docs-only. Downstream of `NAME_THE_THREE_PERSISTENCE_SURFACES.md`.

# Define Writing Surface Contract

## Purpose

Define the contract for the **writing surface** — the persistence surface that holds human-authored editable artifacts. Make explicit, at the naming level, that this surface must tolerate creative fragments, alternatives, and selective stabilization, so `CREATIVE_PROCESS_CONTRACT.md` requirements flow through persistence naming rather than being quietly pushed onto the retention or system surfaces because they are "not finished knowledge."

## What This Task Does

Produces a single document whose body contains:

1. **Identity.** The writing surface is the persistence surface the human owns outright. Authorship, editability, and intelligibility-without-the-runtime are its defining properties.
2. **Holds.** The surface holds human-authored artifacts in all their states, including:
   - settled notes,
   - in-progress notes,
   - creative fragments,
   - parallel alternatives,
   - revision variants,
   - partially stabilized creative threads,
   - drafts the human chooses never to finish,
   - hobby/RPG/world-building material that may mix settled and exploratory content.
3. **Authority.** The human is the final author. No runtime component may silently rewrite writing-surface artifacts. The runtime may assist (suggest, annotate, mirror, cite), but the writing surface remains the human-owned original.
4. **Creative-process tolerance (hard requirement).** The writing surface must explicitly tolerate:
   - fragments as first-class citizens, not as defective or immature notes;
   - alternatives carried in parallel without forced resolution;
   - selective stabilization, where only parts of a thread become more settled while other parts remain exploratory;
   - return visits that recombine, re-vary, or re-shape earlier material.
   This requirement is routed through `CREATIVE_PROCESS_CONTRACT.md` and must be cited explicitly so downstream readers can see the link.
5. **Must never silently become.** The writing surface must never:
   - become a source of meaning *for* the system (i.e., be treated as machine-owned state);
   - become a dumping ground for retained source material (that is the retention surface);
   - become a log of system action (that is the system surface);
   - be used as a replica/mirror of runtime state;
   - be mutated by runtime components on the assumption that "the note is just data";
   - be forced to resolve fragments into finished notes before it will accept them.
6. **Relation to the retention surface.** A writing-surface artifact may *cite* retained material but must not *be* retained material. Retention is a different surface with different expectations (task 3).
7. **Relation to the system surface.** The writing surface may have companion artifacts on the system surface (e.g., identity continuity) — those are not part of the writing surface. The system-surface companion must never become the master of the human artifact (task 4).
8. **User-facing implication.** The user must be able to point at any writing-surface artifact and say *"this is mine"* without having to reason about runtime state.

The document stops at the contract level. It does not name files, paths, schemas, or formats. It does not overlap with the companion-note contract beyond citing it.

## Concretely

Expected structure:

```
# Writing Surface Contract

## Identity
[Human-authored, editable, intelligible without runtime.]

## What the writing surface holds
- Settled human notes
- In-progress notes
- Creative fragments
- Parallel alternatives
- Revision variants
- Partially stabilized creative threads
- ...

## Authority
[Human is the final author. Runtime assists, never silently rewrites.]

## Creative process tolerance (routed through CREATIVE_PROCESS_CONTRACT.md)
- Fragments are first-class.
- Alternatives may exist in parallel.
- Selective stabilization is normal.
- Iteration and return-visits are expected.

## What the writing surface must never silently become
- A source of meaning for the system.
- A dumping ground for retained source material.
- A log of system action.
- A replica of runtime state.
- ...

## Relation to the other two surfaces
[Short prose pointing at DEFINE_RETENTION_SURFACE_CONTRACT.md
  and DEFINE_SYSTEM_SURFACE_CONTRACT.md.]
```

## Why This Matters

Without this contract, the runtime drifts toward treating human notes as "just data" and creative fragments as "notes that have not matured yet." Both drifts are silent failures of the cognitive-prosthetic guarantee. Users stop trusting the writing surface as theirs the first time the runtime reshapes a fragment or forces closure on an exploratory thread. Naming fragment tolerance at the persistence-surface level prevents that drift from being rationalized as "normal knowledge maturation."

This is also the task that prevents the writing surface from becoming a convenient overflow bucket for retained source material or system bookkeeping. Without the "must never silently become" list, each new runtime concern will be tempted to live in the writing surface because the vault is structurally the easiest place to write a file.

## Acceptance Criteria

- [ ] The writing surface identity is defined in one short paragraph.
- [ ] The "holds" list explicitly includes fragments, alternatives, and selective stabilization.
- [ ] `CREATIVE_PROCESS_CONTRACT.md` is cited as the upstream source for fragment tolerance.
- [ ] The authority rule (human is final author; runtime may assist but not silently rewrite) is present.
- [ ] The "must never silently become" list names at least four collapses this contract prevents.
- [ ] The document distinguishes the writing surface from both the retention and system surfaces at the contract level, with forward pointers to those tasks.
- [ ] The document does not prescribe paths, file formats, schemas, or ingest behavior.
- [ ] The document does not prescribe companion-note implementation shape.
- [ ] The document does not touch Finding 4 or Finding 5.

## How to Verify (Pre-Merge)

- Read `CREATIVE_PROCESS_CONTRACT.md` side-by-side with the new contract and confirm every creative-process requirement has a home in the writing-surface contract (either directly or via explicit deferral).
- Grep for schema, payload, field, path — the contract should not define any of these.
- Confirm the "must never silently become" list is substantive (not a single bullet).
- Confirm forward pointers to tasks 3 and 4 are present.
- Confirm the document is readable standalone as "what the writing surface is and what it must tolerate."
- Diff the branch and confirm no file outside `docs/SEPARATING_PERSISTENCE_SURFACES/` is touched.

## Out of Scope

- Defining the retention surface (task 3).
- Defining the system surface (task 4).
- Distinguishing mirror/receipt/trace (task 5).
- Classifying concrete runtime artifacts (task 6).
- Naming paths, file formats, frontmatter, or runtime schemas.
- Prescribing how creative fragments are stored, versioned, or surfaced in UI.
- Prescribing how the runtime assists without rewriting.
- Designing editor or ingest behavior.
- Prescribing companion-note shape or migration.
- Resolving Finding 4 or Finding 5.

## Related Docs

- `docs/plans/V60_ARCHITECTURE_TARGET.md` §Pillar 4, §Pillar 12 (creative-process support)
- `docs/CONCEPTS/CREATIVE_PROCESS_CONTRACT.md`
- `docs/CONCEPTS/ARTIFACT_MODEL_AND_LIFECYCLES.md`
- `docs/CONCEPTS/ARTIFACT_PROJECTION_AND_SOURCE_CONTRACT.md`
- `docs/HUMAN-FLOWS.md`

## Related GitHub Issues

When implementing, a single issue is sufficient: "Implements SEPARATING_PERSISTENCE_SURFACES/DEFINE_WRITING_SURFACE_CONTRACT".

---

**Status:** Specification ready. Blocked on SEPSURF-01 naming merge.
