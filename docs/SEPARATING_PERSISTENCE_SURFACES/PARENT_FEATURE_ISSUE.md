State: Created on GitHub as Issue #394 and closed on 2026-04-17. This file is the local source for the delivered parent feature issue; GitHub is the authoritative backlog and validation record.
---
name: Parent Feature Issue - Separating Persistence Surfaces
description: Feature-breakdown parent issue body text for the v6.0 capability that names and separates writing, retention, and system persistence surfaces
type: feature-issue-body
parent_capability: Separating Persistence Surfaces
source_anchor: docs/plans/V60_ARCHITECTURE_TARGET.md :: Pillar 4, Delta 4, Pillar 10, Delta 9
---

# [Feature] Separate writing, retention, and system persistence surfaces

> **Created and delivered.** GitHub Issue #394: https://github.com/RasmusTho/agentic-pkm-mvp/issues/394. Keep this file aligned with the issue contract and delivered capability history; the live GitHub issue remains the authoritative backlog and validation surface.

## Context

The `v6.0` architecture target requires the runtime to explicitly name three persistence surfaces — a **writing surface** for human-authored editable artifacts, a **retention surface** for retained source-rich artifacts kept for citation and later reuse, and a **system surface** for mirrors, receipts, indexes, traces, and execution artifacts (`docs/plans/V60_ARCHITECTURE_TARGET.md` §Pillar 4, §Delta 4). Today the docs and the runtime still read all three as one loose "storage/notes" layer, and within the system lane, mirrors, receipts, and traces are still collapsed at runtime level even though `MIRROR_RECEIPT_DECISION.md` and `RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md` have already separated them conceptually. Finding 4 and Finding 5 of the architecture review are the runtime manifestation of that collapse.

The companion-note migration is now complete. `VaultMirror` (**deprecated**; replaced by companion notes — see `docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md`) was the prior per-note projection; companion notes are its settled replacement and the reference per-note implementation of the system surface sub-lane this feature names. The implementation shape, field set, and write contract are locked in `COMPANION_NOTE_CONTRACT.md`.

This is docs-only work. It does not move files, touch ingest, modify VaultMirror, or change any schema. It produces the stable names, identities, invariants, and classification map that subsequent runtime work can use without re-litigating the ontology.

## Scope

Produce a specification directory at `docs/SEPARATING_PERSISTENCE_SURFACES/` containing:

- a README framing the capability, its human needs, its non-goals, and the companion-note dependency;
- this parent feature issue body;
- a core naming document for the three surfaces;
- contract documents for each of the three surfaces;
- a sub-document distinguishing mirror, receipt, operational trace, and index/projection inside the system surface;
- a classification document mapping every current runtime artifact class to exactly one surface.

The outcome boundary is **semantic clarity**: a reviewer can point at any current runtime artifact and say unambiguously which surface it belongs to, and downstream runtime work has a stable ontology to build against.

## Source Anchors

- `docs/plans/V60_ARCHITECTURE_TARGET.md` §Pillar 3 (artifact-centric, not projection-centric)
- `docs/plans/V60_ARCHITECTURE_TARGET.md` §Pillar 4 (explicit persistence surfaces)
- `docs/plans/V60_ARCHITECTURE_TARGET.md` §Pillar 10 (surface/authority/accountability distinctions)
- `docs/plans/V60_ARCHITECTURE_TARGET.md` §Delta 3 (artifact-centric semantics)
- `docs/plans/V60_ARCHITECTURE_TARGET.md` §Delta 4 (explicit persistence surfaces)
- `docs/plans/V60_ARCHITECTURE_TARGET.md` §Delta 9 (authority and accountability seams)
- `docs/plans/V60_ARCHITECTURE_TARGET.md` §Finding 4 (mirror conflates identity with audit) — cautionary tale only
- `docs/plans/V60_ARCHITECTURE_TARGET.md` §Finding 5 (promotion lacks receipt) — cautionary tale only
- `docs/CONCEPTS/ARTIFACT_PROJECTION_AND_SOURCE_CONTRACT.md`
- `docs/CONCEPTS/MIRROR_RECEIPT_DECISION.md`
- `docs/CONCEPTS/RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md`
- `docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md`
- `docs/CONCEPTS/CREATIVE_PROCESS_CONTRACT.md`
- `docs/CONCEPTS/ARTIFACT_MODEL_AND_LIFECYCLES.md`
- `docs/CONCEPTS/USER_NEEDS_MODEL.md`
- `docs/HUMAN-FLOWS.md`
- `docs/ARCHITECTURE.md`

## Constraints

- **Docs-only.** No changes outside `docs/SEPARATING_PERSISTENCE_SURFACES/`. No code, no schema, no tests, no on-disk layout changes.
- **Must not prescribe companion-note migration implementation.** Cite `COMPANION_NOTE_CONTRACT.md` at the naming/contract level only. Do not constrain field set, path, write path, or migration sequencing.
- **Must not design DB schema, event payloads, or graph schema.** This is explicitly prohibited by `V60_ARCHITECTURE_TARGET.md` §Non-goals.
- **Must not fix Finding 4 or Finding 5.** They are enabling work and belong to a different lane. Reference them as cautionary tales.
- **Must not modify** `docs/DOCS_INDEX.md`, `docs/ARCHITECTURE.md`, concept contracts, or any file owned by the companion-note migration worktree.
- **Must not create GitHub issues** during this phase.
- **Writing surface contract must tolerate fragments.** It must explicitly route `CREATIVE_PROCESS_CONTRACT` requirements (fragments, alternatives, selective stabilization) through the writing surface, not push exploratory material into retention or system lanes.
- **System surface must not silently become the only real source of meaning.** This is a hard invariant inherited from `V60_ARCHITECTURE_TARGET.md` §Pillar 3 and §Delta 3.
- **Parallel-safety.** Every task in this breakdown must be deliverable by editing documents only.

## Acceptance Criteria

- [ ] `docs/SEPARATING_PERSISTENCE_SURFACES/` exists and contains README.md, PARENT_FEATURE_ISSUE.md, and all six task specification files.
- [ ] Each of the three persistence surfaces has a named identity, a description of what it holds, and an explicit "must never become" list.
- [ ] The writing surface contract explicitly tolerates creative fragments, alternatives, and selective stabilization.
- [ ] The retention surface contract distinguishes retention from both writing and system surfaces and clarifies the *source role* interpretation (per `ARTIFACT_PROJECTION_AND_SOURCE_CONTRACT.md`).
- [ ] The system surface contract cites the companion-note migration as the reference per-note sub-lane implementation without prescribing it, and forbids the system surface from becoming the sole source of meaning.
- [ ] Mirror, receipt, operational trace, and index/projection are named as distinct sub-kinds inside the system surface with stable invariants and the six hard non-equivalences: mirror ≠ receipt, receipt ≠ trace, trace ≠ audit record, index ≠ mirror, index ≠ receipt, index ≠ source-of-truth.
- [ ] The classification document maps every currently-known runtime artifact class (vault note, VaultMirror, companion note, store payload, outbox event, audit row, index record, AI status callout, attachment, etc.) to exactly one surface, and flags companion-note-related entries as "pending companion-note migration" where appropriate.
- [ ] A reviewer can point at any current runtime artifact class and unambiguously say which surface it belongs to.
- [ ] No file outside `docs/SEPARATING_PERSISTENCE_SURFACES/` is modified.

## Out of Scope

- Moving any file on disk.
- Any change to `app/ingest/*`, `app/store/*`, VaultMirror, or promotion code.
- Any new DB schema, event payload shape, or graph schema.
- Fixing Finding 4 (mirror conflates identity with audit).
- Fixing Finding 5 (promotion lacks receipt).
- Implementing, redesigning, or sequencing the companion-note migration.
- Designing new UI surfaces for accountability or receipts.
- Retrieval, orientation, resurfacing, or salience work (different capability lane).

## Suggested Validation

1. Walk the six task files top-to-bottom as a reviewer and verify that by the end of each file a new distinction is established and never walked back.
2. Take the list of runtime artifact classes from `CLASSIFY_CURRENT_ARTIFACTS.md` and cross-check against `docs/ARCHITECTURE.md` to confirm nothing important is missing.
3. Open `COMPANION_NOTE_CONTRACT.md` side-by-side with `DEFINE_SYSTEM_SURFACE_CONTRACT.md` and verify that the system surface contract *cites* the companion note without prescribing it.
4. Open `CREATIVE_PROCESS_CONTRACT.md` side-by-side with `DEFINE_WRITING_SURFACE_CONTRACT.md` and verify that fragments, alternatives, and selective stabilization are explicitly tolerated by the writing surface.
5. Verify that `DISTINGUISH_MIRROR_RECEIPT_TRACE.md` references Finding 4 and Finding 5 as cautionary tales without fixing or prescribing fixes.
6. Confirm no file outside `docs/SEPARATING_PERSISTENCE_SURFACES/` is touched by diffing the branch.

## Source Docs

Same as Source Anchors above. The specification directory itself is the deliverable; the source documents are stable inputs that must not be rewritten from within this lane.

## Implementation Tasks

The breakdown lives at [`docs/SEPARATING_PERSISTENCE_SURFACES/`](./README.md). Read in this order:

1. [NAME_THE_THREE_PERSISTENCE_SURFACES.md](NAME_THE_THREE_PERSISTENCE_SURFACES.md) — core naming spec.
2. [DEFINE_WRITING_SURFACE_CONTRACT.md](DEFINE_WRITING_SURFACE_CONTRACT.md) — writing surface contract; tolerates fragments.
3. [DEFINE_RETENTION_SURFACE_CONTRACT.md](DEFINE_RETENTION_SURFACE_CONTRACT.md) — retention surface contract.
4. [DEFINE_SYSTEM_SURFACE_CONTRACT.md](DEFINE_SYSTEM_SURFACE_CONTRACT.md) — system surface contract; cites companion-note migration.
5. [DISTINGUISH_MIRROR_RECEIPT_TRACE.md](DISTINGUISH_MIRROR_RECEIPT_TRACE.md) — mirror ≠ receipt ≠ trace ≠ index; six hard non-equivalences.
6. [CLASSIFY_CURRENT_ARTIFACTS.md](CLASSIFY_CURRENT_ARTIFACTS.md) — classification map.

Execution order is strictly sequential. No parallel tasks in this capability.

## Verification Path

Each task is verified pre-merge by:

- reading the task file in isolation and confirming it respects the "docs-only / no implementation" rule;
- confirming the frontmatter matches the `feature-breakdown` shape;
- confirming that all cited concept contracts exist and the citations are accurate;
- confirming that no text inside the task file prescribes companion-note implementation shape;
- confirming that Finding 4 and Finding 5 are only mentioned as cautionary tales, not resolved;
- diffing the branch to confirm no file outside `docs/SEPARATING_PERSISTENCE_SURFACES/` is touched.

Task acceptance is each task's own acceptance checklist. The parent capability is accepted only after all six are merged **and** the classification walkthrough in the validation section below completes cleanly.

## Validation / Acceptance Path

Post-merge validation of the whole capability:

1. **Classification walkthrough.** A reviewer opens `CLASSIFY_CURRENT_ARTIFACTS.md` and, for every currently known runtime artifact class, confirms the assignment is unambiguous. Any ambiguity is recorded as a parent-issue comment and, if substantive, becomes a follow-up task.
2. **Companion-note migration alignment check.** Once the companion-note migration lands on `main`, a reviewer re-reads `DEFINE_SYSTEM_SURFACE_CONTRACT.md` and `CLASSIFY_CURRENT_ARTIFACTS.md` and confirms no contradiction exists. Any contradiction is resolved by updating this spec, not the companion-note contract.
3. **V6.0 target cross-check.** A reviewer confirms that `V60_ARCHITECTURE_TARGET.md` §Pillar 4, §Delta 4, §Pillar 10, and §Delta 9 are each addressed by at least one task document in this directory.
4. **Creative-process tolerance check.** A reviewer confirms that `DEFINE_WRITING_SURFACE_CONTRACT.md` routes `CREATIVE_PROCESS_CONTRACT` requirements through persistence surface language without forcing fragments into the retention or system lane.
5. **Owner-doc promotion trigger.** When all four checks pass, a single owner-doc promotion PR may update `docs/ARCHITECTURE.md` and/or `docs/plans/V60_ARCHITECTURE_TARGET.md` to claim the separation as specified. That promotion is outside the scope of this feature issue.

Validation evidence should live as comments on the parent feature issue once it exists on GitHub, not as churn against owner docs.
