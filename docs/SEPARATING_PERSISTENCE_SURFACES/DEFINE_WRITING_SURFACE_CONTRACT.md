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

State: Implementation complete. Docs-only. Downstream of SEPSURF-01.

# Writing Surface Contract

## Identity

The writing surface is the persistence surface the human owns outright. Authorship, editability, and intelligibility-without-the-runtime are its defining properties. Everything on the writing surface is authored, shaped, and controlled by the human. The runtime may assist, suggest, annotate, and mirror, but the human retains final authority.

## What the writing surface holds

- Settled human notes (finished, stable work)
- In-progress notes (active work, not yet finalized)
- Creative fragments (incomplete thoughts, partial explorations, one-off ideas)
- Parallel alternatives (multiple versions of the same theme explored in parallel)
- Revision variants (earlier attempts kept for reference or potential recombination)
- Partially stabilized creative threads (some parts settled, other parts still exploratory)
- Drafts the human chooses never to finish (intentional incompleteness)
- Hobby material, world-building, and exploratory play (including material that mixes settled and exploratory content)

All of these are *first-class citizens* on the writing surface. None are defective or immature versions of "real" notes. A fragment is complete as a fragment. An alternative is a valid path even if not chosen. An unfinished draft belongs here.

## Authority

The human is the final author. No runtime component may silently rewrite writing-surface artifacts. The runtime may:
- Assist (suggest, offer alternatives, assist with formatting or structure)
- Annotate (add metadata, cross-references, indexes)
- Mirror (create system-surface projections for continuity or repair)
- Cite (link to retained source material)

But the writing surface remains the human-owned original. The user's trust relationship with the writing surface is that *this is my work, my voice, my shape*.

## Creative process tolerance (routed through CREATIVE_PROCESS_CONTRACT.md)

The writing surface must explicitly tolerate creative work patterns as named in `docs/CONCEPTS/CREATIVE_PROCESS_CONTRACT.md`:

- **Fragments as first-class citizens**: A one-sentence thought, an incomplete exploration, a single quote, a brainstorm note — all are valid writing-surface artifacts. They do not need to "mature" or "graduate" to be accepted.

- **Alternatives carried in parallel**: The human may explore multiple approaches to the same problem or theme without forced resolution. Both can coexist on the writing surface. Neither is subordinate to the other.

- **Selective stabilization**: Parts of a creative thread may become more settled (outline-like, structured) while other parts remain fluid and exploratory. This mixture is normal and expected, not a sign of incomplete work.

- **Return visits and recombination**: The human may return to earlier material weeks or months later and rework, recombine, re-vary, or cannibalize it. The writing surface is a space where this return journey is not just tolerated but expected.

- **Incompletion as a choice**: The human may intentionally leave work unfinished, partially explored, or genuinely abandoned. These belong on the writing surface as witnesses to the creative process, not as "failed notes."

The runtime must not force fragments toward completion, must not demand that alternatives resolve into a single chosen path, must not collapse exploratory and settled material into a false unified structure. Creative work is not defective note-taking; it is legitimate use of the writing surface.

## What the writing surface must never silently become

- **A source of meaning for the system**: Writing-surface artifacts must never be read as machine-owned state or runtime configuration. They are not inputs to be parsed and acted upon without human intent.

- **A dumping ground for retained source material**: Retained, cited source material belongs on the retention surface. If writing-surface artifacts become the place the runtime stores source quotes "for safekeeping," the writing surface becomes confused with retention.

- **A log of system action**: System events, traces, receipts, and audit records belong on the system surface. The writing surface must not become a append-only record of what the machine did.

- **A replica of runtime state**: The writing surface must not become a cache or mirror of what is "really" in the DB. If the runtime treats the writing surface as a convenience copy of truth that lives elsewhere, the human loses confidence in the artifact.

- **A place mutated by runtime components on the assumption that "the note is just data"**: The runtime must not silently edit, reformat, or restructure writing-surface artifacts as a side effect of other operations. Mutation requires human intent.

- **Subject to forced completion**: The runtime must not demand that fragments resolve, alternatives narrow, or exploratory threads conclude before accepting them as valid writing-surface residents.

## Relation to the retention surface

A writing-surface artifact may *cite* retained material — that is, link to or quote from source documents, research notes, or archived references. But a writing-surface artifact must not *be* retained material. If the human consciously moves source material into a retention surface for long-term safekeeping and later rediscovery, that material is no longer authorship; it is source. These belong to different surfaces. See [DEFINE_RETENTION_SURFACE_CONTRACT.md](DEFINE_RETENTION_SURFACE_CONTRACT.md) for the retention surface contract.

## Relation to the system surface

The writing surface may have companion artifacts on the system surface. A system-surface mirror records identity continuity and portability. A system-surface receipt records what happened when the human saved or published the artifact. These companions are *about* the human artifact; they are not *instances* of it. The human's relationship to the writing surface must not be mediated through these companions. The writing surface is the human original; the system surface is the machine's record *about* it.

The system-surface companion must never become the master. If the mirror is more up-to-date than the original note, or if the receipt is consulted as the source of truth about what was meant, the writing surface has failed its purpose.

See [DEFINE_SYSTEM_SURFACE_CONTRACT.md](DEFINE_SYSTEM_SURFACE_CONTRACT.md) for the system surface contract.

## User-facing implication

The user must be able to point at any writing-surface artifact and say *"this is mine"* without having to reason about runtime state, system projections, or machine bookkeeping. This is what the cognitive-prosthetic guarantee means for the writing surface: the user is never forced to become a system administrator in order to trust their own work.

---

## Purpose (Original Specification Section)

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

- [x] The writing surface identity is defined in one short paragraph.
- [x] The "holds" list explicitly includes fragments, alternatives, and selective stabilization.
- [x] `CREATIVE_PROCESS_CONTRACT.md` is cited as the upstream source for fragment tolerance.
- [x] The authority rule (human is final author; runtime may assist but not silently rewrite) is present.
- [x] The "must never silently become" list names at least four collapses this contract prevents.
- [x] The document distinguishes the writing surface from both the retention and system surfaces at the contract level, with forward pointers to those tasks.
- [x] The document does not prescribe paths, file formats, schemas, or ingest behavior.
- [x] The document does not prescribe companion-note implementation shape.
- [x] The document does not touch Finding 4 or Finding 5.

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

**Status:** Implementation complete.
