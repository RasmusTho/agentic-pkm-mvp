State: SoT v5.x forward line (v5.6 artifact model)
Doc role: Plan — foundational
Authority: Foundational artifact-model plan for the v5.6 forward line. This document must be stable before companion-note contract or related architecture/data-model changes are extended further.

# Artifact Model and Lifecycles

## Purpose

This document establishes the holistic artifact model used by the current forward line.

It exists to make the following explicit before narrower docs add detail:
- which artifact types exist,
- which surface each artifact belongs to,
- how recovery between surfaces works,
- how identity healing works,
- and how authority changes by scenario rather than through one global rule.

This is a foundational artifact-model plan.
It does not define runtime schemas, DB tables, or exact implementation APIs.

Related docs:
- `docs/CORE_CONTRACT.md`
- `docs/FRONTMATTER.md`
- `docs/DATA_MODEL.md`
- `docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md`
- `docs/CONCEPTS/INSTANCE_DEVICE_AND_REPLICA_CONTRACT.md`
- `docs/contracts/OBSIDIAN_KNOWLEDGE_PORT.md`

## Why this plan is needed

The runtime now operates across multiple persistence and exposure surfaces:
- a human-facing vault note,
- a system-facing companion artifact,
- and runtime-facing DB/index representations.

Without an explicit artifact model, the system risks:
- treating DB rows as semantically stronger than the vault,
- treating the companion note as a cache rather than a first-class artifact,
- using one oversimplified authority rule such as "frontmatter wins" everywhere,
- or letting retrieval/index artifacts quietly become identity anchors.

This plan prevents that drift.

## Quick map

| Artifact type | Primary surface | Normal authority posture | Rebuild / recovery role |
| --- | --- | --- | --- |
| Vault Note | Human surface | Primary human artifact; frontmatter UUID is strongest direct identity signal in the normal case | Together with companion note, rebuilds runtime state |
| Companion Note | System surface | Primary portable system continuity artifact for tracked vault notes | Supports identity repair; may be rebuilt from runtime state when missing |
| DB Object | Runtime surface | Runtime record, not semantic source of truth | Rebuilt from vault note + companion note; may rebuild missing companion note in recovery cases |
| Chunks / Embeddings | Runtime surface | Derived only; never identity authority | Invalidated/rebuilt from runtime content |
| Summaries / derived views | Runtime surface | Derived only; non-authoritative by default | Refreshed or rebuilt from source/runtime state |
## Artifact types

### Vault Note

A `Vault Note` is the human-facing editable artifact in the writing surface.

It is:
- the primary human artifact,
- the place where Obsidian title-based linking lives,
- and a portable artifact that must retain its `uuid` in frontmatter.

It is not:
- a DB row,
- an embedding/chunk container,
- or merely a projection generated from runtime state.

### Companion Note

A `Companion Note` is a first-class system artifact in the system surface.

It exists to:
- preserve continuity,
- support identity repair,
- record bounded system-side state about the note,
- and remain portable enough that vault + companion notes can rebuild runtime state.

It is not:
- a cache,
- a convenience projection,
- or a replacement for the vault note.

### DB Object

A `DB Object` is the local runtime representation of an artifact used for ingest, retrieval,
policy, and orchestration.

It is:
- a runtime mirror/record,
- local to an instance,
- and rebuildable from vault + companion notes.

It is not:
- the semantic source of truth for the human artifact,
- or the authority from which companion notes are conceptually derived.

### Chunks and Embeddings

`Chunks` and `Embeddings` are derived runtime index artifacts.

They exist to support:
- retrieval,
- ranking,
- semantic search,
- and related runtime operations.

They are:
- rebuildable,
- model-dependent,
- and operational rather than primary semantic artifacts.

They are not:
- identity anchors,
- portable canonical artifacts,
- or part of the authority model for healing except as diagnostic support.

### Summaries and other derived views

Summaries and other generated reductions are derived artifacts.

They may be persisted for performance or UX, but they remain rebuildable and must not become the
only surviving source of meaning or identity.

## Three surfaces

### Human surface

The `human surface` is where the human reads, writes, links, and orients.

Current primary artifact:
- `Vault Note`

Ownership:
- human meaning and authorship remain primary here,
- bounded system-owned metadata may appear in frontmatter when policy allows.

### System surface

The `system surface` holds durable system artifacts that support continuity, repair, and bounded
inspectability without polluting the human writing surface.

Current primary artifact:
- `Companion Note`

Ownership:
- system-owned,
- portable enough for backup/sync/rebuild,
- not intended for direct human authoring.

### Runtime surface

The `runtime surface` holds local operational representations used by retrieval, orchestration,
indexing, and policy.

Current primary artifacts:
- `DB Object`
- `Chunks`
- `Embeddings`
- derived summaries and similar runtime views

Ownership:
- system-owned,
- local/runtime-facing,
- rebuildable from the human + system surfaces.

## Recovery and rebuild relationship

The rebuild relationship is intentionally bidirectional for recovery, but not symmetrical in
semantic authority.

### Human + system surfaces -> runtime surface

Vault notes plus companion notes must be sufficient to rebuild:
- DB objects,
- chunks,
- embeddings,
- and other derived runtime artifacts.

This is the primary cold-rebuild path.

### Runtime surface -> system surface

If a companion note is missing but the runtime still has a valid DB object and identity metadata,
the system may rebuild the companion note from runtime state.

This is a recovery path, not proof that DB is semantically primary.

### Runtime surface -> human surface

The runtime may write bounded healing metadata back to the vault note, especially `uuid`, but only
through `KnowledgePort` and only under the healing/authority rules defined here and in the
frontmatter contract.

## Lifecycles by artifact type

### Vault Note lifecycle

Typical lifecycle:
- created by human or capture flow,
- ingested by the system,
- assigned or healed with a `uuid` when needed,
- updated by human over time,
- renamed or moved as Obsidian usage evolves,
- may be soft-deleted or archived,
- may be recovered and re-ingested later.

Lifecycle notes:
- title/file-based linking is Obsidian-first and remains human-facing,
- `uuid` must remain in the file for portability,
- vault note meaning is not replaced by runtime mirrors.

### Companion Note lifecycle

Typical lifecycle:
- created when the system first ingests and tracks a vault note,
- updated as identity-metadata changes,
- updated when path/title/content-hash or ingest state changes,
- retained through repair scenarios,
- retained through soft delete,
- may remain after permanent vault deletion as a bounded continuity/audit artifact.

Lifecycle notes:
- companion notes are durable system artifacts,
- they exist to preserve continuity and enable repair,
- they are not ephemeral caches.

### DB Object lifecycle

Typical lifecycle:
- created during ingest,
- updated during re-ingest or metadata refresh,
- read by retrieval/policy/orchestration,
- invalidated or rebuilt as source content changes,
- recoverable from vault + companion notes.

Lifecycle notes:
- DB objects are runtime mirrors,
- local instance state may be discarded and rebuilt.

### Chunks and Embeddings lifecycle

Typical lifecycle:
- generated from DB object content,
- invalidated when source content or embedding model assumptions change,
- replaced rather than slowly-history-versioned,
- rebuildable on demand.

Lifecycle notes:
- they are derivative runtime artifacts only,
- semantic similarity is not identity.

### Summary / derived-view lifecycle

Typical lifecycle:
- generated from source/runtime content,
- refreshed or invalidated when source changes,
- discarded and rebuilt when needed.

Lifecycle notes:
- summaries are derived and non-authoritative unless explicitly elevated elsewhere by another
  contract.

## Authority matrix

No single global rule such as "frontmatter wins" is valid in every scenario.
Authority is scenario-bound.

### Normal known-note scenario

Situation:
- vault note has a valid `uuid`,
- no conflicting signals appear.

Authority:
- note frontmatter `uuid` is the strongest direct identity signal.

### UUID missing from note

Situation:
- vault note exists,
- `uuid` is missing or unreadable.

Authority order:
1. companion note identity record,
2. DB identity record,
3. path/source_ref match,
4. exact content-hash match,
5. no match -> generate new `uuid`.

### Note-companion UUID conflict

Situation:
- note frontmatter `uuid` and companion `uuid` disagree.

Authority:
- no blind dominance rule applies,
- repair must be conservative,
- scenario classification and logging are required,
- ambiguous cases should be flagged rather than silently rewritten.

### Companion missing

Situation:
- note and/or DB exist,
- companion note is absent.

Authority:
- the system may rebuild the companion from valid existing identity/runtime state,
- but this does not itself decide a new identity.

### DB missing

Situation:
- local runtime state is gone or stale.

Authority:
- rebuild from vault note + companion note,
- DB absence does not reduce the authority of the file-based artifacts.

### Path-only recovery

Situation:
- `uuid` is absent,
- path/source_ref gives the only strong continuity clue.

Authority:
- path/source_ref may justify reuse with logging,
- but path remains mutable and therefore weaker than stable identity records.

### Exact content-hash recovery

Situation:
- rename/copy-like scenario,
- exact content hash matches a known identity record.

Authority:
- exact content hash is a valid continuity signal for reuse,
- but should still be logged as scenario-based healing rather than as universal identity truth.

### Semantic-similarity scenario

Situation:
- lexical or semantic closeness suggests a likely relation,
- but stronger identity anchors are missing or conflicting.

Authority:
- semantic similarity is triage/diagnostic only,
- it may flag candidates for human review,
- it must never be treated as an automatic identity decision.

## Healing principles

Healing exists to restore continuity conservatively.

Core rules:
- all healing writes go through `KnowledgePort`,
- all healing decisions must be logged with scenario type and confidence,
- all automatic healing must be reversible,
- semantic similarity is never enough for automatic identity assignment,
- DB may assist healing but must not be described as semantically stronger than the vault.

### Healing priority order

1. UUID in frontmatter matches known UUID -> use directly
2. Companion note identity record -> recover UUID from there
3. DB identity record -> recover UUID from there
4. source_ref / path matching -> reuse UUID with logging
5. exact content-hash match -> reuse UUID in rename/copy scenario
6. semantic similarity -> triage signal only, human review if ambiguous
7. no match -> generate new UUID

## Obsidian-first constraints

The system must remain compatible with Obsidian's title/file-first linking model.

Implications:
- `[[link]]` is title-based, not UUID-based, on the human surface,
- titles, filenames, and aliases remain real human-facing continuity signals,
- the system must not require humans to think in UUIDs in order to navigate the vault,
- healing and continuity logic therefore need a title/alias/path-to-UUID resolver rather than an
  attempt to replace Obsidian's linking model outright.

Obsidian-first does **not** mean title is the sole identity anchor.
It means:
- title-based linking is part of human-surface reality,
- while UUID remains the primary stable system identity.

## What this document defers

This document intentionally defers:
- exact companion-note field semantics and lifecycle details to
  `docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md`,
- frontmatter write constraints to `docs/FRONTMATTER.md`,
- KnowledgePort API/allowed writes to `docs/contracts/OBSIDIAN_KNOWLEDGE_PORT.md`,
- runtime persistence details to `docs/DATA_MODEL.md`,
- physical DB tables and SCD-style schema detail to `docs/DB_SCHEMA.md`,
- current operational topology and deployment reality to `docs/ARCHITECTURE.md` and `docs/HUMAN-FLOWS.md`.
