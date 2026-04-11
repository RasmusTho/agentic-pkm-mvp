---
name: Classify current runtime artifacts against the three persistence surfaces
description: Produce a mapping document assigning every current runtime artifact class to exactly one persistence surface, validating the boundaries.
task_id: SEPSURF-06
source_anchor: docs/plans/V60_ARCHITECTURE_TARGET.md :: Pillar 4
parent_capability: Separating Persistence Surfaces
prerequisites: [SEPSURF-01, SEPSURF-02, SEPSURF-03, SEPSURF-04, SEPSURF-05]
depends_on: [NAME_THE_THREE_PERSISTENCE_SURFACES.md, DEFINE_WRITING_SURFACE_CONTRACT.md, DEFINE_RETENTION_SURFACE_CONTRACT.md, DEFINE_SYSTEM_SURFACE_CONTRACT.md, DISTINGUISH_MIRROR_RECEIPT_TRACE.md]
can_parallelize_with: []
---

State: Specification ready. Docs-only. Downstream of SEPSURF-01 through SEPSURF-05. This is the last task in the capability and the validation hub for the five naming tasks above it.

# Classify current runtime artifacts against the three persistence surfaces

## Purpose

Force the writing / retention / system trichotomy to survive contact with the actual runtime. This task specifies the production of a mapping document in which every currently-known runtime artifact class is assigned to **exactly one** persistence surface. If any artifact class cannot be placed, or fits in two surfaces at once, that is treated as a signal that the upstream surface contracts (tasks 2, 3, 4, 5) are wrong and must be tightened — not as a license to give the artifact a dual assignment.

This task does **not** produce the classification itself. It specifies the classification document: the artifact classes that must be covered, the assignment rule, the ambiguity-handling rule, and the pending-state rule for companion-note entries that are mid-migration.

## What This Task Does

Produces a single document whose body contains:

1. **Framing.** The three surfaces have been named (task 1), contracted (tasks 2, 3, 4), and sub-divided inside the system surface (task 5). None of that naming work is credible until every current runtime artifact class can be pointed at and placed on exactly one surface without hesitation. This document is where that walk-through lives.
2. **Assignment rule.** Every listed artifact class is assigned to exactly one of: **writing surface**, **retention surface**, or **system surface**. Within the system surface, the document may additionally tag the sub-kind from task 5 (*mirror*, *receipt*, *operational trace*, *audit record*, *index/retrieval projection*, etc.) for clarity, but the surface assignment itself remains singular.
3. **Ambiguity-as-signal rule.** If an artifact class resists a single assignment, the document does *not* give it two. Instead, it flags the artifact as a **boundary problem** and points back at whichever surface contract (task 2, 3, 4, or 5) needs to be tightened. The resolution lives upstream, not here. A dual-assignment is a capability-level failure.
4. **Pending-state rule (companion notes).** Companion-note entries are marked "**pending companion-note migration**" in the classification. The label means: the artifact class belongs on the system surface as a per-note sub-lane implementation (per `DEFINE_SYSTEM_SURFACE_CONTRACT.md`), but the concrete shape, path, field set, and write path are owned by the companion-note migration on the `claude/inspiring-jackson` worktree and are not finalized inside this capability. This document must not prescribe the companion-note implementation; it must only record that the assignment is conditional on the migration converging.
5. **The artifact classes that must be classified.** The document enumerates, at minimum, the following current runtime artifact classes. Each class is a *category*, not a file path; the goal is category-level unambiguous placement, not a byte-level inventory.
   - **Vault notes** (human-authored Obsidian notes in the vault).
   - **Companion notes** (per-note machine-side continuity artifact being introduced on `claude/inspiring-jackson`) — marked *pending companion-note migration*.
   - **VaultMirror entries** (legacy per-note projection currently being replaced by companion notes).
   - **ObjectStore payloads** (`store_objects` table rows and their payload blobs).
   - **Outbox events** (DB outbox rows in the canonical runtime queue; JSONL outbox is audit/diagnostic only).
   - **Index records** (vector index entries, hybrid store entries, retrieval/scoring projections).
   - **Worker and runtime logs / operational traces** (trace_id-linked logs, orchestration traces, worker run records).
   - **Ingest run receipts** (per-run records produced by ingestion flows).
   - **Promotion receipts** (the surface implied by Finding 5; classified here as what a receipt *would* be — **not** fixed, only placed).
   - **Settings compiler provenance records** (compiled-settings provenance / source-of-truth records).
   - **Status and health snapshots** (CLI/API/GUI status surfaces, health reports, runtime status callouts).
   - **Watcher tick logs** (registry watcher tick/run records, watcher.run events, dedup skip telemetry).
   - **External source ingests** (`external_raw` plane artifacts from cloud connectors / inbox sources before they become vault or retention material). Per the retention surface contract (task 3), the pre-curation `external_raw` staging plane is **system-surface ingest-state**, not retention; curated material joins the retention surface only after the user's curation event.
   - **Any other current artifact classes found while reading `docs/ARCHITECTURE.md`.** The author of the eventual classification document is responsible for sweeping the architecture doc one more time and adding anything missing. The list above is a floor, not a ceiling.
6. **Shape of the mapping.** The mapping is presented as a table with columns `artifact class | surface | sub-kind (if system) | notes / pending flags | upstream contract reference`. The table is the deliverable; prose framing around it is minimal.
7. **Bridge to follow-up.** The document ends by noting which artifact classes (if any) surfaced a boundary problem and which upstream surface contracts would need to be tightened if those classes were taken seriously. This bridge text is prose, not a task list, and never takes the form of prescriptive implementation steps.

This task produces the **specification** of the classification document. The actual classification document is produced during implementation of this spec (i.e., when the GitHub issue for SEPSURF-06 is worked). The spec itself only describes what the deliverable must contain, how ambiguity is handled, and which artifact classes must appear in the table.

## Concretely

Expected structure of the eventual classification document:

```
# Classification of Current Runtime Artifacts

## Purpose
[Walk-through that validates tasks 1–5 against the current runtime.]

## Assignment rule
- Every artifact class → exactly one surface.
- Ambiguity is a boundary problem, not a dual assignment.
- Companion-note entries carry "pending companion-note migration".

## Mapping table

| Artifact class             | Surface    | Sub-kind       | Notes / pending                              | Upstream contract |
|----------------------------|------------|----------------|----------------------------------------------|-------------------|
| Vault notes                | writing    | —              |                                              | task 2            |
| Companion notes            | system     | mirror         | pending companion-note migration             | task 4, task 5    |
| VaultMirror entries        | system     | mirror         | legacy; being replaced by companion notes    | task 4, task 5    |
| ObjectStore payloads       | …          | …              |                                              | …                 |
| Outbox events              | system     | operational trace |                                           | task 5            |
| Index records              | system     | index/projection |                                            | task 4            |
| Worker/runtime traces      | system     | operational trace |                                           | task 5            |
| Ingest run receipts        | system     | receipt        |                                              | task 5            |
| Promotion receipts         | system     | receipt        | cautionary tale: Finding 5, not fixed here   | task 5            |
| Settings compiler prov.    | system     | audit/provenance |                                            | task 4            |
| Status/health snapshots    | system     | operational trace |                                           | task 4            |
| Watcher tick logs          | system     | operational trace |                                           | task 5            |
| External source ingests    | system     | ingest-state   | pre-curation external_raw staging plane      | task 4            |
| …                          | …          | …              |                                              | …                 |

## Boundary problems encountered
[If any artifact resisted a single assignment, name it and say which
 upstream contract would need to tighten. Do not resolve here.]

## Bridge to validation
[This table is the evidence the parent feature issue's validation path
 walks over.]
```

The example surfaces in the table above are illustrative of shape, not authoritative assignments. The author of the eventual classification document makes the actual assignments using the contracts from tasks 2, 3, 4, 5 as the rulebook. If the contracts and the runtime reality disagree, the contracts — not the table — are the thing that gets re-examined.

## Why This Matters

The cognitive-prosthetic guarantee of v6.0 is that the user can point at any artifact the runtime is holding and say, without hesitation, *"this is mine"*, *"this is a retained source"*, or *"this is machine bookkeeping"*. That guarantee is not carried by the naming documents alone — it is carried by the claim that every artifact the runtime actually produces lands cleanly in one of those three buckets. If even one artifact class leaves the user fuzzy about which category it belongs to, the capability has failed, regardless of how clean the upstream naming looks.

This task is therefore the validation hub for the five tasks above it. The classification table is the place where the trichotomy is proved against reality. Ambiguity encountered here is not a paperwork failure; it is the capability telling us the boundaries are still wrong and one of the upstream contracts must be tightened before merge.

It is also the place where the companion-note migration intersects with this capability most sharply. Companion-note entries are classified on the system surface, but the classification is explicitly conditional on a migration this capability does not own. Marking those rows "pending companion-note migration" keeps the capability honest about what it has and has not locked down, without dragging it into prescribing the migration itself.

## Acceptance Criteria

- [ ] The classification document exists at `docs/SEPARATING_PERSISTENCE_SURFACES/` as the deliverable for SEPSURF-06.
- [ ] Every listed artifact class (vault notes, companion notes, VaultMirror entries, ObjectStore payloads, outbox events, index records, worker/runtime logs and operational traces, ingest run receipts, promotion receipts, settings compiler provenance records, status/health snapshots, watcher tick logs, external source ingests, and any additional classes swept in from `docs/ARCHITECTURE.md`) appears in the mapping table.
- [ ] Every listed artifact class is assigned to **exactly one** of the three persistence surfaces. No dual assignments.
- [ ] Any ambiguity surfaces as a **flagged boundary problem** that points back at the specific upstream surface contract (task 2, 3, 4, or 5) that would need to be tightened — not as a dual assignment, not as a fudge.
- [ ] Companion-note entries are assigned to the system surface and explicitly labeled "pending companion-note migration" in the notes column.
- [ ] Promotion receipts are classified as what a receipt would be (system surface, receipt sub-kind) without prescribing a fix for Finding 5.
- [ ] VaultMirror entries are classified as mirror sub-kind without prescribing a fix for Finding 4 or dictating the replacement strategy.
- [ ] For each row in the table, the upstream contract reference points at the correct task file (task 2, 3, 4, or 5).
- [ ] A reviewer can walk the table top-to-bottom and, for every row, state the surface assignment in one sentence without consulting external context beyond the five prior task files.
- [ ] The document does not move any file on disk.
- [ ] The document does not change any runtime code, schema, event payload shape, or on-disk layout.
- [ ] The document does not resolve Finding 4 or Finding 5.
- [ ] The document does not prescribe companion-note migration implementation shape, field set, path, or sequencing.
- [ ] No file outside `docs/SEPARATING_PERSISTENCE_SURFACES/` is modified.

## How to Verify (Pre-Merge)

- Read the classification table with each of `DEFINE_WRITING_SURFACE_CONTRACT.md`, `DEFINE_RETENTION_SURFACE_CONTRACT.md`, `DEFINE_SYSTEM_SURFACE_CONTRACT.md`, and `DISTINGUISH_MIRROR_RECEIPT_TRACE.md` open side-by-side. Confirm every row's surface assignment and sub-kind tag are consistent with the upstream contract.
- Sweep `docs/ARCHITECTURE.md` once more and check that no additional artifact class mentioned there is missing from the table. If anything was added to the architecture document after this spec was authored, fold it in.
- Grep the document for dual assignments (commas or slashes in the `surface` column). There must be none.
- Confirm every companion-note-related row carries the "pending companion-note migration" flag in the notes column and that none of those rows prescribes companion-note implementation shape.
- Grep for prescriptive verbs against Finding 4 or Finding 5 ("fix", "replace", "introduce", "emit", "refactor"). These must not appear as prescriptive actions in the classification document.
- Confirm the boundary-problem section either lists specific artifacts with pointers at upstream contracts or states explicitly that no boundary problem was encountered during classification.
- Diff the branch and confirm no file outside `docs/SEPARATING_PERSISTENCE_SURFACES/` is touched.

## Out of Scope

- **Does not move any files on disk.** This is a docs-only classification.
- **Does not change any runtime code, schema, event payload shape, graph shape, or on-disk layout.**
- **Does not resolve Finding 4 (mirror conflates identity with audit log).** VaultMirror is classified, not fixed.
- **Does not resolve Finding 5 (promotion mutates state without a clear transition record).** Promotion receipts are classified as what a receipt would be, but the capability does not prescribe a fix.
- **Does not prescribe the companion-note migration implementation.** Companion-note rows are placed on the system surface and marked pending; their shape, field set, path, write path, and sequencing remain owned by the migration on `claude/inspiring-jackson`.
- **Does not redefine mirror, receipt, operational trace, or audit record.** Those definitions are owned by task 5 and the upstream concept contracts.
- **Does not design retention policy, salience, resurfacing, or retrieval behavior.** Those belong to other capability lanes.
- **Does not create GitHub issues.** Issue creation is phase-3 work of the parent capability.
- **Does not modify `docs/DOCS_INDEX.md`, `docs/ARCHITECTURE.md`, concept contracts, or any file owned by the companion-note migration worktree.**

## Related Docs

- `docs/plans/V60_ARCHITECTURE_TARGET.md` §Pillar 3, §Pillar 4, §Pillar 10, §Delta 3, §Delta 4, §Delta 9, §Finding 4, §Finding 5
- `docs/SEPARATING_PERSISTENCE_SURFACES/NAME_THE_THREE_PERSISTENCE_SURFACES.md`
- `docs/SEPARATING_PERSISTENCE_SURFACES/DEFINE_WRITING_SURFACE_CONTRACT.md`
- `docs/SEPARATING_PERSISTENCE_SURFACES/DEFINE_RETENTION_SURFACE_CONTRACT.md`
- `docs/SEPARATING_PERSISTENCE_SURFACES/DEFINE_SYSTEM_SURFACE_CONTRACT.md`
- `docs/SEPARATING_PERSISTENCE_SURFACES/DISTINGUISH_MIRROR_RECEIPT_TRACE.md`
- `docs/CONCEPTS/ARTIFACT_PROJECTION_AND_SOURCE_CONTRACT.md`
- `docs/CONCEPTS/MIRROR_RECEIPT_DECISION.md`
- `docs/CONCEPTS/RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md`
- `docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md` (cited as reference, never prescribed)
- `docs/ARCHITECTURE.md` (sweep once more for missing artifact classes)

## Related GitHub Issues

When implementing, a single GitHub issue is sufficient: "Implements SEPARATING_PERSISTENCE_SURFACES/CLASSIFY_CURRENT_ARTIFACTS". The issue body must explicitly flag that: (a) companion-note rows are marked pending and do not prescribe migration shape, (b) Finding 4 and Finding 5 are not resolved here, (c) any ambiguity encountered during classification is reported as a boundary problem against the relevant upstream task file rather than resolved as a dual assignment.

---

**Status:** Specification ready. Blocked on SEPSURF-01 through SEPSURF-05 merging. Companion-note rows remain "pending companion-note migration" until the `claude/inspiring-jackson` worktree converges.
