---
name: Separating Persistence Surfaces Specification
description: System specification for naming and separating the writing, retention, and system persistence surfaces as a v6.0 capability
type: specification
authority: SoT for the separation-of-persistence-surfaces capability; names semantic boundaries only, does not prescribe storage implementation
source_of_truth: docs/plans/V60_ARCHITECTURE_TARGET.md §Pillar 4, §Delta 4, §Pillar 10, §Delta 9
related_docs:
  - docs/plans/V60_ARCHITECTURE_TARGET.md
  - docs/CONCEPTS/ARTIFACT_PROJECTION_AND_SOURCE_CONTRACT.md
  - docs/CONCEPTS/MIRROR_RECEIPT_DECISION.md
  - docs/CONCEPTS/RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md
  - docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md
  - docs/CONCEPTS/CREATIVE_PROCESS_CONTRACT.md
  - docs/CONCEPTS/ARTIFACT_MODEL_AND_LIFECYCLES.md
  - docs/HUMAN-FLOWS.md
  - docs/ARCHITECTURE.md
---

State: Delivered docs/specification index for the v6.0 `SEPARATING_PERSISTENCE_SURFACES` capability. The parent feature was filed as GitHub Issue #394 and closed on 2026-04-17. This directory remains the local spec/source surface; GitHub is the authoritative backlog and validation record. Docs-only work. No code, no schema, no file moves on disk.

# Separating Persistence Surfaces Specification

This directory contains the system specification for the v6.0 capability that explicitly names and separates the three persistence surfaces currently collapsed into one fuzzy "storage" layer:

- the **writing surface** — human-authored editable artifacts, including fragments, alternatives, and selectively stabilized material;
- the **retention surface** — retained source-rich artifacts kept for citation, grounding, and later reuse;
- the **system surface** — mirrors, indexes, receipts, traces, execution artifacts, and other runtime support structures.

Each task specification here is the source of truth for a bounded piece of that naming work. These are **not** issue templates. Task specifications can map to one or many GitHub issues at implementation time; this capability is a docs-authoring lane and does not create issues itself in the current phase.

## Human needs this serves

This capability directly serves three of the user needs called out in `docs/CONCEPTS/USER_NEEDS_MODEL.md` and the cognitive-prosthetic framing of v6.0:

1. **Central artifacts must outlive the runtime.** The user has to be able to point at a file and know whether it is theirs, whether it is retained source material, or whether it is machine bookkeeping. If the three surfaces collapse, the system slowly starts to look like the only real source of meaning and the user loses the guarantee that their central work is intelligible without the runtime.
2. **Trust what the system did.** The user must be able to distinguish *what is mine*, *what is a copy*, and *what is machine bookkeeping* at a glance. Mirrors, receipts, and traces serve different trust functions; collapsing them into one "storage" idea destroys that distinction.
3. **Create without premature closure.** The writing surface must tolerate creative fragments, alternatives, and selective stabilization. The separation specified here routes `CREATIVE_PROCESS_CONTRACT` support through the writing surface explicitly, so exploratory material is not pushed into retention or system lanes just because it is unfinished.

## What this capability is NOT

This is spec/design work only. This capability does not and must not:

- move files around on disk;
- change the ingest pipeline (`app/ingest/*`);
- rewrite, remove, or reshape VaultMirror;
- implement or prescribe the companion note migration;
- change the ObjectStore payload shape, DB schema, event payload shape, or graph schema (explicitly out of scope per V60 §Non-goals);
- fix Finding 4 (mirror conflates identity with audit) or Finding 5 (promotion lacks receipt) — those are enabling work referenced here as cautionary tales only;
- define new UI surfaces, retrieval behavior, or promotion flow.

Every deliverable in this directory is satisfied by editing documents under `docs/SEPARATING_PERSISTENCE_SURFACES/`. If a proposed task would require touching code, ingest, or on-disk layout, it belongs to a different capability lane.

## Companion-note-migration dependency (MUST READ)

There is active implementation work on a parallel worktree (`claude/inspiring-jackson`) that is replacing `VaultMirror` with a companion-note surface. That surface is literally the per-note materialization of what this spec calls the *system surface sub-lane*.

This specification treats the companion-note migration as the **reference implementation for the per-note system-surface sub-lane**. It does **not** prescribe the companion-note implementation shape, field set, location, write path, or migration strategy. Where the companion-note contract and this spec touch, this spec stays at the naming / invariants / surface-identity level and cites `COMPANION_NOTE_CONTRACT.md` and `MIRROR_RECEIPT_DECISION.md` rather than duplicating or constraining them.

Scheduling implication: this capability should merge **after** the companion-note migration contract has stabilized, or any overlap must be resolved by updating the citation here, not by editing the companion-note contract from within this lane. Any tension found during spec-writing is surfaced as a flag in the relevant task file; it is not resolved here.

## Reading order for task files

Read the task files in this order. Each one builds on the naming established by the previous.

1. **[NAME_THE_THREE_PERSISTENCE_SURFACES.md](NAME_THE_THREE_PERSISTENCE_SURFACES.md)** — the core naming document. Establishes the writing / retention / system trichotomy, their identities, and the invariants that make them distinct.
2. **[DEFINE_WRITING_SURFACE_CONTRACT.md](DEFINE_WRITING_SURFACE_CONTRACT.md)** — what the writing surface holds, what it must tolerate (fragments, alternatives, selective stabilization), and what it must never silently become.
3. **[DEFINE_RETENTION_SURFACE_CONTRACT.md](DEFINE_RETENTION_SURFACE_CONTRACT.md)** — what the retention surface holds, what source-role function it serves, and how it stays distinct from the writing and system surfaces.
4. **[DEFINE_SYSTEM_SURFACE_CONTRACT.md](DEFINE_SYSTEM_SURFACE_CONTRACT.md)** — what the system surface holds, the explicit ban on silently becoming the only source of meaning, and the citation of the companion-note migration as the reference per-note sub-lane implementation.
5. **[DISTINGUISH_MIRROR_RECEIPT_TRACE.md](DISTINGUISH_MIRROR_RECEIPT_TRACE.md)** — the four sub-kinds inside the system surface (mirror, receipt, operational trace, index/projection) that must not collapse. Cites Finding 4 and Finding 5 as cautionary tales; does not fix them.
6. **[CLASSIFY_CURRENT_ARTIFACTS.md](CLASSIFY_CURRENT_ARTIFACTS.md)** — produces a mapping document where every current runtime artifact class is assigned to exactly one surface, with explicit flags where the companion-note migration leaves a pending state.

The [PARENT_FEATURE_ISSUE.md](PARENT_FEATURE_ISSUE.md) holds the full feature-issue contract shape used by `feature-breakdown` and is the validation hub once implementation issues are created from these specs.

## Execution order

Tasks 1, 2, 3, 4, 5 are authored against the same conceptual set and are best done in the listed order because each one depends on the naming set by the one above it. Task 6 depends on all five.

```
NAME_THE_THREE_PERSISTENCE_SURFACES
        ↓
DEFINE_WRITING_SURFACE_CONTRACT
        ↓
DEFINE_RETENTION_SURFACE_CONTRACT
        ↓
DEFINE_SYSTEM_SURFACE_CONTRACT
        ↓
DISTINGUISH_MIRROR_RECEIPT_TRACE
        ↓
CLASSIFY_CURRENT_ARTIFACTS
```

No task in this capability is parallel-safe with another task in this capability; the naming is deliberately sequential. Task 1 can be started immediately; the rest are downstream.

## Acceptance

The parent capability `Separating Persistence Surfaces` is accepted when **all** of the following are true:

- [ ] All six task documents are merged into `docs/SEPARATING_PERSISTENCE_SURFACES/`.
- [ ] The three persistence surfaces are named with stable identities, invariants, and "must never become" rules.
- [ ] The writing surface contract explicitly tolerates fragments, alternatives, and selective stabilization, routing `CREATIVE_PROCESS_CONTRACT` requirements through persistence naming.
- [ ] The system surface contract cites but does not prescribe the companion-note migration, and marks it as the reference per-note sub-lane implementation.
- [ ] Mirror, receipt, operational trace, and index/projection are named as distinct sub-kinds with stable invariants.
- [ ] `CLASSIFY_CURRENT_ARTIFACTS.md` assigns every current runtime artifact class (vault note, VaultMirror, companion note, store payload, outbox event, audit row, index record, AI status callout, etc.) to exactly one surface, with explicit pending flags where the companion-note migration has not yet converged.
- [ ] A reviewer can point at any current runtime artifact class and say unambiguously which of the three surfaces it belongs to.
- [ ] The capability does not change any code, schema, or on-disk layout; all acceptance evidence is satisfied by documents in this directory.

Post-merge validation evidence lives in the parent feature issue per `feature-breakdown`.

## Pointer to parent feature issue

See [PARENT_FEATURE_ISSUE.md](PARENT_FEATURE_ISSUE.md) for the full feature-issue contract shape, source anchors, constraints, and validation path. That document is the canonical parent-issue body text when an issue is created on GitHub.

## Navigation

- **V6.0 target anchors:** `docs/plans/V60_ARCHITECTURE_TARGET.md` §Pillar 3, §Pillar 4, §Pillar 10, §Delta 3, §Delta 4, §Delta 9, §Finding 4, §Finding 5
- **Projection/source contract:** `docs/CONCEPTS/ARTIFACT_PROJECTION_AND_SOURCE_CONTRACT.md`
- **Mirror vs receipt decision:** `docs/CONCEPTS/MIRROR_RECEIPT_DECISION.md`
- **Receipt vs trace vs audit contract:** `docs/CONCEPTS/RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md`
- **Companion note contract:** `docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md`
- **Creative process contract:** `docs/CONCEPTS/CREATIVE_PROCESS_CONTRACT.md`
- **Human flows:** `docs/HUMAN-FLOWS.md`

---

**Status:** Docs/spec lane delivered and parent feature issue #394 closed. This directory does not itself claim the broader runtime migration as fully complete; companion-note, receipt, and persistence-surface runtime truth remains tracked separately in owner docs and GitHub issue history.
