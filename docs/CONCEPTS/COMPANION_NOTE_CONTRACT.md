State: SoT v5.6 forward line (companion note contract)
Doc role: Core SoT
Authority: Canonical definition of the companion note as a first-class system artifact for continuity, identity repair, and bounded system-side tracking of vault notes.

# Companion Note Contract

## Purpose

This document defines the `Companion Note` as a first-class system artifact.

Its job is to preserve continuity and support repair around a vault note without making the runtime
DB or index layers semantically primary.

This contract complements:
- `docs/plans/ARTIFACT_MODEL_AND_LIFECYCLES.md`
- `docs/FRONTMATTER.md`
- `docs/CORE_CONTRACT.md`
- `docs/contracts/OBSIDIAN_KNOWLEDGE_PORT.md`
- `docs/DATA_MODEL.md`

## What a companion note is

A companion note is:
- a system-plane artifact,
- 1:1 linked to a vault note in the normal case,
- durable enough to participate in rebuild and repair,
- portable enough to move with the vault's system-owned files,
- and the canonical file-based continuity artifact for note identity tracking.

Its primary functions are:
- identity continuity,
- repair support,
- bounded ingest/healing state,
- and preserving enough system-side note history that vault + companion notes can rebuild runtime state.

## What a companion note is not

A companion note is not:
- a cache,
- a convenience projection,
- merely a temporary mirror generated from DB,
- the human-authored note,
- the full receipt/audit model,
- or a general license to move arbitrary runtime state into the vault.

## Location convention

Current forward-line convention:
- `vault/_system/companions/<uuid>.md`

This path is system-owned.
It belongs to the system surface, not the normal human writing surface.

If runtime compatibility still references older mirror-oriented paths, that should be treated as a
transitional implementation detail rather than a contradiction of this contract.

## Minimal field set

The companion note must carry a bounded field set sufficient for continuity and repair.

Minimum field list:
- `uuid`
- `source_ref`
- `title`
- `content_hash`
- `ingest_state`
- `last_ingested`
- `created_by_instance`

Additional bounded continuity or healing metadata may exist when consistent with this contract, but
the companion note must not silently become a dump for arbitrary runtime internals.

## Lifecycle

### Creation trigger

A companion note is created when the system first ingests and begins tracking a vault note after
the note's UUID has been established or healed.

### Update triggers

The companion note may be updated when:
- note content changes and `content_hash` must change,
- note path changes and `source_ref` must be updated,
- title changes and continuity metadata must stay aligned,
- ingest completes and ingest state transitions to the appropriate tracked state,
- healing occurs and the identity-tracking record must be updated,
- a note becomes stale relative to runtime/index state,
- a note is soft-deleted,
- or a permanent deletion is recognized and the companion is retained as a bounded continuity/audit artifact.

### Missing companion handling

If the companion note is missing:
- the system should rebuild it from valid runtime identity metadata when available,
- or recreate it during re-ingest from the vault note when runtime state is also absent.

Missing companion handling must not be described as proof that DB is primary.
It is a recovery path only.

### Damaged companion handling

If the companion note exists but is malformed, incomplete, or internally inconsistent:
- the system may repair bounded fields conservatively,
- should log the repair scenario,
- and should avoid silent identity changes when ambiguity remains.

### Soft delete / archive handling

If a tracked note is soft-deleted or archived:
- the companion may remain as the durable continuity artifact,
- with ingest state reflecting that scenario.

Permanent disappearance of the human-facing note does not require the immediate disappearance of
the companion note.

## Relation to the vault note

The vault note remains the primary human artifact.
The companion note remains the primary portable system artifact for continuity and repair.

This means:
- the companion note does not replace the vault note,
- the vault note does not erase the need for the companion note,
- and no single unconditional rule such as "frontmatter always wins" applies in every conflict.

Scenario-bound interpretation:
- normal case: note frontmatter UUID is the strongest direct signal,
- missing UUID: companion note is the first recovery source,
- note/companion UUID conflict: repair must be conservative and scenario-bound,
- missing companion: rebuild may occur from valid runtime state without creating a new identity rule.

## Relation to the DB

The DB is the runtime mirror/record of tracked artifacts.
It is local, operational, and rebuildable.

The companion note differs from the DB because it is:
- file-based,
- portable across transport and rebuild scenarios,
- and part of the file-based continuity set together with the vault note.

The DB may help recover or regenerate a missing companion note, but the companion note must not be
described as a mere projection of the DB.

## Relation to KnowledgePort

All companion-note writes must go through `KnowledgePort` or approved helpers built on top of it.

This includes:
- initial creation,
- healing-related updates,
- source-ref updates,
- ingest-state transitions,
- and bounded continuity repairs.

The companion note contract does not permit direct ad-hoc file writes as the normative write path.

## Relation to the healing pipeline

The companion note is a central artifact in the healing pipeline.

Healing order remains:
1. note frontmatter UUID
2. companion note identity record
3. DB identity record
4. source_ref/path match
5. exact content-hash match
6. semantic similarity as triage only
7. new UUID

The companion note therefore acts as:
- the first file-based recovery source after direct frontmatter identity,
- and a durable continuity artifact when runtime state is missing or stale.

## Human should never edit this

In practice, "human should never edit this" means:
- humans are not expected to author or maintain companion notes directly,
- manual editing is outside the normal supported workflow,
- the system may rely on bounded structural consistency in these files,
- and recovery logic may treat unexpected manual edits as damaged-system-artifact scenarios rather
  than as ordinary note edits.

This does not mean the file must be hidden from the user.
It means the file is system-owned, not user-authored.

## Forward note on linking convention

The human-facing and system-facing linking conventions for vault note <-> companion note should be
documented more explicitly when the implementation is stabilized.

That future documentation should preserve:
- Obsidian-first title/file linking on the human surface,
- UUID-based continuity on the system side,
- and conservative repair behavior when those signals diverge.
