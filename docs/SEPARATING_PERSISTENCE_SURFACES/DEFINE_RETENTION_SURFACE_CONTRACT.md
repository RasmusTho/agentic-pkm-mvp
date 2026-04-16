---
name: Define Retention Surface Contract
description: Contract for the retention surface - retained source-rich artifacts kept for citation, grounding, and later reuse, distinct from writing and system surfaces
task_id: SEPSURF-03
source_anchor: docs/plans/V60_ARCHITECTURE_TARGET.md :: Pillar 4, Pillar 10; docs/CONCEPTS/ARTIFACT_PROJECTION_AND_SOURCE_CONTRACT.md
parent_capability: Separating Persistence Surfaces
prerequisites: [SEPSURF-01, SEPSURF-02]
depends_on: [NAME_THE_THREE_PERSISTENCE_SURFACES.md, DEFINE_WRITING_SURFACE_CONTRACT.md]
can_parallelize_with: []
---

State: Implementation complete. Docs-only. Downstream of SEPSURF-01 and SEPSURF-02.

# Retention Surface Contract

## Identity

The retention surface is where the system keeps source-rich material the user has chosen to retain because it matters later. PDFs, long-form external documents, transcripts, newsletters, reference captures, retained excerpts, and similar artifacts whose primary value is being *citable* and *re-readable*. These are received, not authored.

## What the retention surface holds

- Externally authored documents (PDFs, articles, whitepapers, newsletters, transcripts)
- Long-form reference captures from external sources
- Retained excerpts with provenance intact
- Archived material the user intends to return to for citation or grounding
- Documentation and specifications kept as reference
- Any artifact whose primary function is to serve as a source for future reference, citation, or reuse

All of these share a defining property: the user chose to keep them because they have ongoing value as *source material*, not because they are actively being written or worked on. The retention surface is defined by the user's curatorial decision to maintain these artifacts as accessible, citable references.

## Authority

Retention-surface artifacts are *received*, not *authored*. The user's authority over them is:
- **Curatorial**: choosing what to keep, organizing and annotating it
- **Not authorial**: not rewriting the source material itself

The user can annotate a retained document, copy excerpts into writing-surface notes, index it for search, and cite it. But the user does not *author* the retention-surface artifact in place. Its voice and shape remain as received.

## Source as role, not type (Cited from ARTIFACT_PROJECTION_AND_SOURCE_CONTRACT.md)

It is essential to understand that *retention* and *source* are not the same idea.

- **Retention is a function**: retention-surface artifacts are kept because the user wants to return to them and refer to them later.
- **Source is a role**: any artifact (writing-surface, retention-surface, or system-surface) may play the role of source material in a particular context — cited, consulted, grounded against.

A writing-surface note may play a source role (cited by a later note) without being a retention-surface artifact. A retention-surface artifact is *typically* consulted as source, but the retention function is what defines it, not the source role in any particular query.

The system surface also creates projections of retained material (indexes, embeddings, retrieval documents). These projections are *about* retained source material; they do not *become* retained source material by virtue of being created. See [DEFINE_SYSTEM_SURFACE_CONTRACT.md](DEFINE_SYSTEM_SURFACE_CONTRACT.md) for system-surface clarification.

## Post-curation, not pre-curation

A critical distinction: **the retention surface holds curated material only**.

Raw external material sitting in a staging plane before the user has decided to keep it is *not* on the retention surface yet. It is **system-surface ingest-state** (see task 4). Once the user curates it as "kept," the curated artifact joins the retention surface; the system-surface ingest record remains a system surface artifact recording the history of what was ingested and when.

The staging plane is not retention-in-progress; it is machine-owned observation. Conflating them would mean the retention surface slowly fills with every external document that ever passed through the ingest pipeline, whether the user wanted to keep it or not.

## What the retention surface must never silently become

- **The writing surface**: Retained material must never silently become re-authored work. The user must not find that source material has been edited, reformatted, or combined in place as if it were a writing-surface artifact. Retention means the original voice is preserved.

- **The system surface**: Retained material must never be treated as machine bookkeeping. The fact that the runtime indexes, embeds, or creates retrieval documents for retained material does not make the retained artifact itself a system-surface artifact. Retention is first-class; projections are derived.

- **The only remaining place a piece of human meaning lives**: Writing-surface artifacts must not decay into retention artifacts simply because they have not been edited in a while. If a note you wrote ages out of activity and drifts into retention just by force of disuse, you lose the guarantee that your own work lives where you put it.

- **An absorber of creative fragments**: Creative fragments belong on the writing surface (see task 2). If fragments are pushed onto the retention surface because "they are not yet finished," fragments lose their home and creative work becomes institutionalized as "not-yet-ready source material."

- **A substitute for a receipt of what the system did**: If the system performs an action (ingest, retrieval, promotion, transformation) on or with retained material, the record of that action belongs on the system surface as a receipt or trace (see tasks 4 and 5). The system-surface receipt should never be confused with the retained artifact itself. "The system found this" is not the same as "this is retained source."

- **A repository for pre-curation staging material**: Raw external ingest in a staging plane is system-surface ingest-state (see task 4), not retained source. The staging row belongs on the system surface as an ingest-metadata artifact. Only curated material joins the retention surface.

## Relation to the writing surface

A writing-surface artifact may cite retained material. The human may copy excerpts from retained sources into notes and work with them. The human may be inspired by retained material and author new notes based on it. But the writing-surface artifact and the retained artifact remain distinct. Migration of material from retention to writing (the user turning source into authored note) is a writing-surface *event* (a new note is created), not a retention-surface *demotion* (the source is not moved). The retained artifact stays retained.

See [DEFINE_WRITING_SURFACE_CONTRACT.md](DEFINE_WRITING_SURFACE_CONTRACT.md) for the writing surface contract.

## Relation to the system surface

The retention surface may have system-surface projections. Indexes, embeddings, retrieval documents, and ingest-state records are all system-surface artifacts that *reference* or *describe* retained material. These projections exist to support retrieval, search, and operational observability. But the projections are not the retention-surface artifact. A retrieval document is not the source; it is a machine representation *about* the source. An index entry is not the artifact; it is a machine representation that helps us find the artifact.

The critical rule: the retained artifact is not defined by its projections. If the index is more up-to-date than the source, the source remains the source. If a retrieval document is what the system found most convenient, the retrieval document is not what you chose to keep.

See [DEFINE_SYSTEM_SURFACE_CONTRACT.md](DEFINE_SYSTEM_SURFACE_CONTRACT.md) for the system surface contract.

## User-facing implication

The user must be able to point at a retention-surface artifact and say *"this is a copy of something I chose to keep"* without conflating it with their own authored work or with machine bookkeeping. When you return to a retained source document months later, it should be recognizable as the same thing you kept — not edited, not absorbed into your notes, not replaced by an index entry or a summary.

---

## Purpose (Original Specification Section)

Define the contract for the **retention surface** — the persistence surface that holds retained source-rich artifacts kept for citation, grounding, later reuse, and long-horizon reference. Clarify that *retention* is a distinct function from *authorship* (writing surface) and from *system bookkeeping* (system surface), and that *source* is an epistemic role an artifact plays in context rather than an intrinsic type.

Define the contract for the **retention surface** — the persistence surface that holds retained source-rich artifacts kept for citation, grounding, later reuse, and long-horizon reference. Clarify that *retention* is a distinct function from *authorship* (writing surface) and from *system bookkeeping* (system surface), and that *source* is an epistemic role an artifact plays in context rather than an intrinsic type.

## What This Task Does

Produces a single document whose body contains:

1. **Identity.** The retention surface is where the system keeps source-rich material the user has chosen to retain because it matters later — PDFs, long-form external documents, transcripts, newsletters, reference captures, retained excerpts, and similar artifacts whose primary value is being citable and re-readable.
2. **Holds.** The retention surface holds artifacts that:
   - were externally authored or externally captured,
   - are valuable to the user because they can be *referred back to*, cited, or re-read,
   - carry their own provenance,
   - may function as *source material* in a retrieval, citation, or grounding context without being re-authored by the user,
   - **and have already been curated by the user as "kept"** — retention is a post-curation state, not a pre-curation state.
3. **Post-curation, not pre-curation.** The retention surface is defined by the user's (or the user's delegated process's) decision to keep an artifact as citable/re-readable material. Raw external ingest that is still sitting in a staging plane (see the `external_raw` disclaim in rule 5) is **not** on the retention surface yet — it has not been curated as retained. Staging is system-surface ingest-state; retention is what that material *becomes* if and when it is curated.
4. **Source as role, not type.** The document must explicitly cite `ARTIFACT_PROJECTION_AND_SOURCE_CONTRACT.md` and name that:
   - a retention-surface artifact often plays a source role, but "retained" and "source" are not the same idea;
   - a writing-surface artifact may also play a source role in a later context without moving onto the retention surface;
   - the retention surface is defined by the *retention function*, not by the source role in any particular query.
5. **Authority.** Retention-surface artifacts are treated as *received*, not *authored*. The user's authority over them is curatorial (choosing to keep them, organize them, annotate them) rather than authorial (rewriting them).
6. **Must never silently become.**
   - The retention surface must never silently become the writing surface (do not let retained material be rewritten in place as if it were human-authored).
   - The retention surface must never silently become a system surface (do not treat retained material as machine bookkeeping just because the runtime stores it; retained material has its own first-class identity).
   - The retention surface must never become the only remaining place a piece of human meaning lives — writing-surface artifacts must not decay into retention artifacts simply because they have not been edited in a while.
   - The retention surface must never absorb creative fragments (fragments belong to the writing surface; see task 2).
   - The retention surface must never silently substitute for a receipt of *what the system did with* the retained material (that is a system-surface concern; see tasks 4 and 5).
   - **The retention surface must never absorb the pre-curation `external_raw` staging plane.** Raw external ingest sitting in a staging plane before the user has curated it as "kept" is machine staging, not retained source material. It lives on the **system surface** as an ingest-state sub-kind (see task 4) until and unless the user curates it into retention. Once curated, the curated artifact joins the retention surface; the staging row remains a system-surface ingest record.
7. **Relation to the writing surface.** A writing-surface artifact may cite a retention-surface artifact and may carry excerpts, but the retention-surface artifact remains its own thing with its own provenance. Migration of material from retention to writing (the user turning source into authored note) is a writing-surface event, not a retention-surface demotion.
8. **Relation to the system surface.** The retention surface may have system-surface projections (indexes, embeddings, retrieval documents, ingest metadata), but those projections are system-surface artifacts and are governed by task 4. The retained artifact itself is not defined by its projections.
9. **User-facing implication.** The user must be able to point at a retention-surface artifact and say *"this is a copy of something I chose to keep"* without conflating it with their own writing or with machine bookkeeping.

This task defines the contract only. It does not specify storage layout, retrieval strategy, or ingest behavior.

## Concretely

Expected structure:

```
# Retention Surface Contract

## Identity
[Retained source-rich material; received, not authored.]

## What the retention surface holds
- Externally authored documents (PDFs, newsletters, transcripts)
- Long-form reference captures
- Retained excerpts
- Any artifact whose primary value is being citable and re-readable
- ...

## Source as role, not type
[Cite ARTIFACT_PROJECTION_AND_SOURCE_CONTRACT.md.
  Retained != source; source is a role in context.]

## Authority
[Curatorial, not authorial. The user chose to keep it;
  the user does not rewrite it in place.]

## What the retention surface must never silently become
- The writing surface (no silent rewriting)
- The system surface (not machine bookkeeping)
- The only remaining place human meaning lives
- A place for creative fragments
- A substitute for a receipt of system action
- ...

## Relation to the other two surfaces
[Forward pointers to DEFINE_WRITING_SURFACE_CONTRACT.md
  and DEFINE_SYSTEM_SURFACE_CONTRACT.md.]
```

## Why This Matters

Without this contract, retained material drifts. Either the runtime treats retained PDFs and captured documents as "just another note" and they start looking like authored material, or it treats them as indexing fodder and they lose their first-class identity. Both drifts hurt the user: in the first case the authorship guarantee collapses, in the second case retained material becomes invisible to the user because it lives inside system surfaces. The separation also matters because source-role confusion is one of the easiest ways for projections (retrieval documents, store rows, index entries) to slowly become the effective center of meaning (V60 §Delta 3, §Pillar 3).

## Acceptance Criteria

- [ ] The retention surface identity is defined in one short paragraph.
- [ ] The "holds" list explicitly includes externally authored material, retained excerpts, and long-form reference captures.
- [ ] The contract states retention is post-curation and explicitly disclaims the pre-curation `external_raw` staging plane, assigning staging to the system surface (ingest-state sub-kind).
- [ ] `ARTIFACT_PROJECTION_AND_SOURCE_CONTRACT.md` is cited, and the *source-as-role* distinction is present.
- [ ] The authority rule (curatorial, not authorial) is present.
- [ ] The "must never silently become" list includes at least: writing surface collapse, system surface collapse, fragment absorption, the "only remaining place" warning, and the `external_raw` staging disclaim.
- [ ] The document distinguishes the retention surface from both the writing and system surfaces at the contract level, with forward pointers to those tasks.
- [ ] The document does not prescribe paths, file formats, ingest shape, retrieval behavior, or schema.
- [ ] The document does not prescribe companion-note shape or migration.
- [ ] The document does not resolve Finding 4 or Finding 5.

## How to Verify (Pre-Merge)

- Read `ARTIFACT_PROJECTION_AND_SOURCE_CONTRACT.md` side-by-side with the new contract and confirm the source-role framing is preserved.
- Confirm the "must never silently become" list prevents the retention surface from absorbing either writing-surface or system-surface concerns.
- Grep for path, schema, frontmatter, field, payload — should not appear.
- Confirm forward pointers to tasks 2 and 4 are present.
- Diff the branch and confirm no file outside `docs/SEPARATING_PERSISTENCE_SURFACES/` is touched.

## Out of Scope

- Defining the writing surface (task 2).
- Defining the system surface (task 4).
- Distinguishing mirror/receipt/trace (task 5).
- Classifying concrete runtime artifacts (task 6).
- Prescribing ingest pipeline, retrieval behavior, or index structure for retained material.
- Designing external-corpus workflows.
- Naming paths or file formats.
- Resolving Finding 4 or Finding 5.
- Prescribing companion-note migration.

## Related Docs

- `docs/plans/V60_ARCHITECTURE_TARGET.md` §Pillar 4, §Pillar 10
- `docs/CONCEPTS/ARTIFACT_PROJECTION_AND_SOURCE_CONTRACT.md`
- `docs/CONCEPTS/ARTIFACT_MODEL_AND_LIFECYCLES.md`
- `docs/HUMAN-FLOWS.md`

## Related GitHub Issues

When implementing, a single issue is sufficient: "Implements SEPARATING_PERSISTENCE_SURFACES/DEFINE_RETENTION_SURFACE_CONTRACT".

---

**Status:** Specification ready. Blocked on SEPSURF-02 merge.
