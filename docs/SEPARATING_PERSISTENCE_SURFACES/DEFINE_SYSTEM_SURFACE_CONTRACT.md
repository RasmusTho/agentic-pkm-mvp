---
name: Define System Surface Contract
description: Contract for the system surface - mirrors, receipts, indexes, traces, and execution artifacts; cites but does not prescribe companion-note migration
task_id: SEPSURF-04
source_anchor: docs/plans/V60_ARCHITECTURE_TARGET.md :: Pillar 3, Pillar 4, Pillar 10, Delta 3, Delta 4, Delta 9
parent_capability: Separating Persistence Surfaces
prerequisites: [SEPSURF-01, SEPSURF-02, SEPSURF-03]
depends_on: [NAME_THE_THREE_PERSISTENCE_SURFACES.md, DEFINE_WRITING_SURFACE_CONTRACT.md, DEFINE_RETENTION_SURFACE_CONTRACT.md]
can_parallelize_with: []
---

State: Specification ready. Docs-only. Downstream of SEPSURF-01/02/03. Heavy companion-note-migration dependency.

# Define System Surface Contract

## Purpose

Define the contract for the **system surface** — the persistence surface that holds mirrors, receipts, indexes, traces, execution artifacts, and other runtime support structures. Make explicit that the system surface is structurally *supportive*, never *central*; and that per-note system surface implementation is being realized by the companion-note migration, which this contract cites but does not prescribe.

## What This Task Does

Produces a single document whose body contains:

1. **Identity.** The system surface is where the runtime keeps the structures it needs to do its own job: portable projections of human artifacts, indexes, receipts, execution traces, ingest state, audit rows, queue/outbox records, and similar machine-owned support structures.
2. **Holds (kinds, not implementations).** The document lists the kinds of things the system surface holds, at the naming level only:
   - **mirrors** (portable machine-side projections of a human artifact, used for continuity, identity, portability, and rebuild) — cite `MIRROR_RECEIPT_DECISION.md`;
   - **receipts** (human-legible accountability records of what happened, under what authority, on what basis) — cite `RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md`;
   - **operational traces** (runtime coordination and diagnostic records) — cite the same contract;
   - **audit records** (durable inspectable records preserved for later review);
   - **indexes, embeddings, retrieval documents, and scoring projections** (system-owned representations used to find or rank artifacts);
   - **ingest state and healing metadata** (the runtime's own notes about what it has tracked and repaired);
   - **queue/outbox records and execution artifacts** (machine coordination records).
   Task 5 will separate mirror ≠ receipt ≠ trace in detail; this task only lists them as kinds.
3. **Authority.** The system surface is machine-owned. The user can inspect it but does not author it. Read access is expected; write authority belongs to the runtime. The user's trust relationship with the system surface is that *it is honest about what the system did*, not that *it contains human meaning*.
4. **Hard invariant: the system surface must never silently become the only real source of meaning.** This is the single most important rule in this contract, inherited directly from `V60_ARCHITECTURE_TARGET.md` §Pillar 3 and §Delta 3. The document must state this rule in strong terms and explain why it is the invariant that defends the cognitive-prosthetic guarantee: if the system surface becomes the *de facto* center, the user can no longer trust that their central artifacts remain intelligible without the runtime.
5. **Additional "must never silently become" list.**
   - The system surface must never replace the writing surface (no hidden master of the human artifact).
   - The system surface must never replace the retention surface (no quiet absorption of retained source material).
   - Mirrors must never become receipts (cite task 5).
   - Receipts must never become mere traces (cite task 5).
   - Traces must never be treated as human-legible accountability (cite `RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md`).
   - Indexes, embeddings, and retrieval documents must never become the effective definition of an artifact.
   - The system surface must never be written to by user-facing flows as a shortcut to avoid writing-surface authorship rules.
6. **Companion-note migration citation (explicit).** The document must:
   - name the companion-note migration as the **reference implementation for the per-note system-surface sub-lane**;
   - cite `COMPANION_NOTE_CONTRACT.md` and `MIRROR_RECEIPT_DECISION.md` as the upstream authorities on what the per-note continuity artifact is;
   - state that this contract does **not** prescribe the companion-note field set, path, write path, migration sequencing, or implementation shape;
   - state that if tension ever arises between this contract and the companion-note contract, the resolution lives in this file (citation update), not in the companion-note contract;
   - use language compatible with companion-note migration being in-flight on a parallel worktree (transitional compatibility shapes are acceptable to reference as cautionary context but must not be frozen into the contract).
7. **Relation to writing and retention surfaces.** A writing-surface artifact and a retention-surface artifact may each have one or more system-surface projections (mirror, receipt, index entry, trace). Those projections are *about* the human artifact; they are not *instances* of it.

The document defines naming, identity, authority, and invariants only. It does not prescribe schema, paths, or migration.

## Concretely

Expected structure:

```
# System Surface Contract

## Identity
[Machine-owned support structures; never the center of meaning.]

## What the system surface holds (kinds)
- Mirrors
- Receipts
- Operational traces
- Audit records
- Indexes, embeddings, retrieval documents
- Ingest state and healing metadata
- Queue/outbox records and execution artifacts

## Authority
[Machine-owned. User inspects, does not author.]

## Hard invariant
The system surface must never silently become the only
real source of meaning. [Cite V60 §Pillar 3, §Delta 3,
§Pillar 4.]

## What the system surface must never silently become
- The writing surface
- The retention surface
- A de-facto human meaning center
- A place for mirror-as-receipt or receipt-as-trace collapse
- ...

## Companion-note migration (reference implementation, not prescribed here)
[Cite COMPANION_NOTE_CONTRACT.md and MIRROR_RECEIPT_DECISION.md.
  Name the companion-note migration as the reference per-note
  sub-lane implementation. Do NOT prescribe shape, path, or migration.
  State that any tension is resolved by updating this contract's
  citation, not by editing the companion-note contract from this lane.]

## Relation to the other two surfaces
[Forward pointers to DEFINE_WRITING_SURFACE_CONTRACT.md,
  DEFINE_RETENTION_SURFACE_CONTRACT.md, and DISTINGUISH_MIRROR_RECEIPT_TRACE.md.]
```

## Why This Matters

This contract is the one that most directly defends the cognitive-prosthetic guarantee. Every time the system surface silently accretes meaning — a mirror becomes the master of the note, a receipt becomes just another log line, an index entry becomes the de-facto artifact — the user loses a piece of the "I can still read my own work without the runtime" guarantee. Naming the "must never become only source of meaning" rule and placing it in a contract the runtime can point at is what stops that drift before it is rationalized into a convenience.

This is also the contract that protects the in-flight companion-note migration from being prematurely frozen. The companion-note migration is the *implementation* of the per-note system-surface sub-lane; this contract must cite it as the reference implementation without constraining its shape, so the two lanes can converge rather than collide.

## Acceptance Criteria

- [ ] The system surface identity is defined in one short paragraph.
- [ ] The "holds" list names mirrors, receipts, operational traces, audit records, indexes/embeddings/retrieval documents, ingest state, and queue/outbox records as distinct kinds.
- [ ] The authority rule (machine-owned; user inspects, does not author) is present.
- [ ] The hard invariant ("must never silently become the only real source of meaning") is present, stated strongly, and cited to `V60_ARCHITECTURE_TARGET.md` §Pillar 3 / §Delta 3 / §Pillar 4.
- [ ] The "must never silently become" list includes both surface-level collapses and the mirror/receipt/trace sub-collapses (forwarded to task 5).
- [ ] The companion-note migration is explicitly cited as the reference implementation for the per-note system-surface sub-lane.
- [ ] The document explicitly states it does **not** prescribe the companion-note field set, path, write path, or migration sequencing.
- [ ] The document states that tension with the companion-note contract is resolved by updating this citation, not by editing the companion-note contract.
- [ ] `MIRROR_RECEIPT_DECISION.md` and `RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md` are cited.
- [ ] The document does not define schema, paths, field sets, write paths, or migration steps.
- [ ] The document does not resolve Finding 4 or Finding 5 (task 5 cites them as cautionary tales).

## How to Verify (Pre-Merge)

- Read `COMPANION_NOTE_CONTRACT.md` side-by-side with the new contract. Confirm no constraint in this file would force a change to the companion-note contract.
- Read `MIRROR_RECEIPT_DECISION.md` side-by-side and confirm the mirror/receipt/trace distinctions are cited at the naming level without being redefined here.
- Grep this contract for field names, path fragments (`vault/`, `_system/`, `VaultMirror`), schema, payload. None should appear beyond bare citations.
- Confirm the hard-invariant language is present and attributed.
- Confirm forward pointers to all previous and subsequent tasks are present.
- Diff the branch and confirm no file outside `docs/SEPARATING_PERSISTENCE_SURFACES/` is touched.

## Out of Scope

- Prescribing companion-note field set, path, write path, or migration sequencing.
- Defining the internal shape of any mirror, receipt, trace, audit record, index, or outbox record.
- Distinguishing mirror/receipt/trace in detail (task 5).
- Classifying concrete runtime artifacts (task 6).
- Designing retrieval, indexing, or ingest behavior.
- Fixing Finding 4 (mirror conflates identity with audit).
- Fixing Finding 5 (promotion lacks receipt).
- Designing new UI surfaces for accountability.
- Any code or on-disk change.

## Related Docs

- `docs/plans/V60_ARCHITECTURE_TARGET.md` §Pillar 3, §Pillar 4, §Pillar 10, §Delta 3, §Delta 4, §Delta 9
- `docs/CONCEPTS/MIRROR_RECEIPT_DECISION.md`
- `docs/CONCEPTS/RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md`
- `docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md` (cited as reference, not prescribed)
- `docs/CONCEPTS/ARTIFACT_PROJECTION_AND_SOURCE_CONTRACT.md`

## Related GitHub Issues

When implementing, a single issue is sufficient: "Implements SEPARATING_PERSISTENCE_SURFACES/DEFINE_SYSTEM_SURFACE_CONTRACT". Flag the companion-note-migration scheduling dependency in the issue body.

---

**Status:** Specification ready. Scheduling dependency: companion-note migration contract must be stable before this can be finalized on main.
