State: Delivered (v5.7 companion note contract — single write path, eligibility policy); stable invariant for v6 design
Doc role: Core SoT
Authority: Canonical definition of the companion note as a first-class system artifact for continuity, identity repair, and bounded system-side tracking of vault notes.

# Companion Note Contract

## Purpose

This document defines the `Companion Note` as a first-class system artifact.

Its job is to preserve continuity and support repair around a vault note without making the runtime
DB or index layers semantically primary.

This contract complements:
- `docs/plans/ARTIFACT_MODEL_AND_LIFECYCLES.md`
- `docs/plans/COMPANION_NOTE_AND_AGENT_CONTEXT_PLAN.md`
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
- `vault/<system_folder>/companions/<uuid>.md`

Where `<system_folder>` is the layout-configured system folder (e.g. `⚙️ System`), resolved via
`get_vault_system_dir_rel()`. The path is layout-aware: vault settings or `VAULT_SYSTEM_DIR_REL`
may override the default.

This path is system-owned. It belongs to the system surface, not the normal human writing surface.

**Single write path**: `write_companion()` writes to exactly one location — the canonical
layout-aware path above. The legacy dual-write to `_system/companions/` has been removed.
Read fallback to `_system/companions/` is retained temporarily for vaults that have not yet
migrated to the layout-aware path.

Compatibility note:
- older `System/Metadata/VaultMirror/...` files should be read as proto-companion continuity
  artifacts during transition
- the `_system/companions/` path is the legacy read-fallback location, not the write target
- vaults should migrate to the layout-aware system folder as part of normal ingest

## Creation eligibility policy

A companion note is only created when the source note passes all eligibility checks, in priority
order. Skipped companions are logged; they are never silently dropped.

1. **system_path** — note lives inside the system folder (e.g. `⚙️ System/`) or `_system/`.
   Companions are never created for system-plane files.
2. **placeholder_title** — filename stem is a known editor placeholder (Namnlös, Untitled,
   New Note, Unnamed, Sans titre, etc., with optional trailing number). These are transient
   cursor-landing files with no stable identity.
3. **empty_note** — note body has no meaningful non-structural content after panel-stripping. A
   body consisting only of headings, horizontal rules, or whitespace is considered empty.
4. **cooldown_active** — note mtime is within `create_cooldown_seconds` of `now`. The default is
   60 s; set `COMPANION_CREATE_COOLDOWN_SECONDS=0` to disable. The `rename_cooldown_seconds`
   (default 20 s; env `COMPANION_RENAME_COOLDOWN_SECONDS`) applies to rename/update events.

Settings precedence: vault `@Settings/watchers.md` companion section → env vars → defaults.

When a companion is not created for a **permanently ineligible** note (`system_path` or
`placeholder_title`), the ingest fingerprint stored in the object store is used as the fallback
skip-check signal so unchanged content is not re-ingested on subsequent runs. Transiently ineligible
notes (`cooldown_active`) are not skipped via this fallback — the ingest pipeline retries them on
each run until the cooldown expires and companion creation succeeds.
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

### `created_by_instance` provenance

`created_by_instance` records the runtime instance identity of the ingest process that created the
companion note. It is populated from the same settings-bundle resolver used by outbox event metadata
(`instance_provenance.instance_id`), so companion provenance and event provenance are consistent for
a given ingest run.

Resolution rules (in order):
1. `get_settings_bundle().instance.id` — the canonical runtime identity.
2. If the bundle is unavailable or the instance field is absent/empty, `created_by_instance` is set
   to the explicit sentinel value `"unknown"` — never an empty string.

An empty string value (`created_by_instance: ""`) is a bug, not a valid state. The field must always
carry either a resolved identity or the explicit sentinel `"unknown"`.

Additional bounded continuity or healing metadata may exist when consistent with this contract, but
the companion note must not silently become a dump for arbitrary runtime internals.

### Attachment manifest (bounded extension)

When a vault note references non-markdown files via Obsidian embed syntax (`![[file.png]]`,
`![[file.pdf]]`, etc.), the companion note may carry a bounded attachment manifest:

```yaml
attachments:
  - ref: <vault-relative path to file>
    content_hash: <sha256 or null if file missing>
```

The attachment manifest records which files are part of the artifact's observable surface. It is:
- bounded: only files explicitly referenced via `![[...]]` embed syntax in the note body,
- observational: it records what the system sees, not what the system enforces,
- not an ownership claim: the same file may appear in multiple companion manifests,
- not an auto-repair mechanism: if an embed reference disappears from the vault note, the
  attachment is removed from the manifest at next ingest. The system must never write `![[...]]`
  back into a vault note — that would rewrite human meaning.

### Fields explicitly not in the companion note

The companion note must not carry:
- `review_state` — owned by vault note frontmatter,
- `maturity` — owned by vault note frontmatter,
- `kind` — implicit for tracked vault artifacts,
- `origin` — implicit for vault-sourced companions,
- agent action history or classification results — these belong in the runtime DB,
- full note content or body text — read the vault note directly.
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

### Ingest states

Canonical forward-line `ingest_state` values:
- `untracked`
- `known`
- `indexed`
- `stale`
- `healing_needed`
- `soft_deleted`
- `archived`

Interpretation:
- `untracked` = continuity artifact exists but active runtime tracking is not yet established
- `known` = tracked identity exists, but full ingest/index completion is not yet the current state
- `indexed` = ingest/index cycle completed for the current known content/version
- `stale` = source content/path metadata changed and runtime state may need refresh
- `healing_needed` = continuity or identity inconsistency requires repair workflow
- `soft_deleted` = tracked note is treated as removed from active use without full continuity erasure
- `archived` = continuity artifact retained for long-horizon traceability after archival transition
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

## Forward implementation anchors

These abstractions are already meaningful in the docs, even where implementation is still
transitional:
- `KnowledgePort` = the normative write boundary for vault- and companion-note mutations
- `SyncLayer` = current watcher/worker/react-to-file-change flows, later to be made more explicit as
  a named abstraction
- `EmbeddingProvider` = the current provider/model-tagged embedding boundary, implemented today
  through the embedding configuration/runtime stack and later documentable as a clearer interface
## Human should never edit this

In practice, "human should never edit this" means:
- humans are not expected to author or maintain companion notes directly,
- manual editing is outside the normal supported workflow,
- the system may rely on bounded structural consistency in these files,
- and recovery logic may treat unexpected manual edits as damaged-system-artifact scenarios rather
  than as ordinary note edits.

This does not mean the file must be hidden from the user.
It means the file is system-owned, not user-authored.

## Role in agent context

The companion note is not the agent's working memory. It is the agent's **identity anchor** for a
tracked artifact.

When agents need rich per-artifact context, they should use a Note Context abstraction that
assembles information from all three surfaces:
- companion note (identity, content_hash, attachment manifest, ingest_state),
- vault note (full text, frontmatter, structure, embeds),
- runtime DB (relations, classification, agent history, policy).

The companion note contributes the portable identity and continuity kernel that makes the rest of
the context assembleable. Agent operational state (executed actions, classification results,
promotion history) belongs in the runtime DB, not in the companion note.

See `docs/plans/COMPANION_NOTE_AND_AGENT_CONTEXT_PLAN.md` for the implementation plan.

## Relation to VaultMirror (legacy)

The earlier `System/Metadata/VaultMirror/...` path and `note_mirror`/`note_log` code modules are
the legacy implementation of a subset of companion note functionality. They are being replaced by
the companion note service.

The companion note differs from VaultMirror in that it:
- uses flat UUID-based path (`_system/companions/<uuid>.md`) instead of directory-preserving path,
- does not duplicate human-owned fields (`review_state`, `maturity`),
- includes an attachment manifest,
- follows the bounded field set defined in this contract,
- and writes through KnowledgePort.
## Forward note on linking convention

The human-facing and system-facing linking conventions for vault note <-> companion note should be
documented more explicitly when the implementation is stabilized.

That future documentation should preserve:
- Obsidian-first title/file linking on the human surface,
- UUID-based continuity on the system side,
- and conservative repair behavior when those signals diverge.

## Required test baseline when implementation proceeds

When the companion-note contract is implemented or hardened in runtime code, the minimum expected
test/guardrail set should include:
- architecture/boundary tests proving companion-note writes route through `KnowledgePort`
- contract tests for healing-order behavior across note/companion/DB/path/hash scenarios
- regression tests for missing-companion rebuild and stale-companion repair
- explicit ambiguity tests proving semantic similarity never auto-assigns identity
- compatibility tests for transitional `VaultMirror` -> companion-note migration behavior
