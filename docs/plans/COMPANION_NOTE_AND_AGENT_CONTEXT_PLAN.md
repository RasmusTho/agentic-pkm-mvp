State: Re-baselined implementation plan — companion note + note context remain forward-line work
Doc role: Plan — implementation (re-baselined against current codebase)
Authority: Implementation plan for companion note service, VaultMirror removal, attachment manifest, and Note Context abstraction. This document is re-baselined against the current repository state and complements docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md and docs/plans/ARTIFACT_MODEL_AND_LIFECYCLES.md.

# Companion Note Implementation and Agent Context Plan

This file remains the active implementation plan for the companion note + Note Context track even
though its filename still says "Agent Context Plan".

## Purpose

This plan specifies how to implement the companion note as the canonical system-surface artifact,
remove the legacy VaultMirror implementation, introduce an attachment manifest, and provide agents
with rich per-artifact context through a Note Context abstraction.

It is based on an architecture investigation that analyzed all relevant docs, code, tests, and
runtime behavior. The current repository shows a mixed state:

1. Companion note is now implemented at `vault/_system/companions/<uuid>.md`, and active ingest /
   worker / CLI paths use it rather than `System/Metadata/VaultMirror/...`.
2. Note Context is implemented, and PanelAgent now uses it as the primary prompt context path.
3. A compatibility fallback still exists in PanelAgent: if Note Context assembly fails, the runtime
   falls back to the legacy truncated snippet rather than hard-failing.
4. Active docs still contain rollout-language drift in some places, which is why this plan remains
   necessary as an implementation/status tracker.

## Current implementation status

Historical phase ordering is retained below, but the status must be read against the current
codebase rather than older plan text.

### Shipped

- `app/services/companion_note.py` exists and includes the main companion-note read/write,
  content-hash lookup, attachment scanning, and healing helpers.
- `app/services/note_context.py` exists and assembles runtime note context from companion note,
  vault note content, and optional runtime-store data.
- Active ingest/runtime paths now use companion-note wiring, including
  `app/ingest/vault_alpha.py`, `app/ingest/config.py`, `app/workers/outbox_worker.py`, and
  `app/cli/alpha_human_flows.py`.
- PanelAgent now uses Note Context as its primary path, and focused tests cover the integration.

### Shipped but compatibility fallback retained

- PanelAgent retains the legacy truncated snippet fallback when Note Context assembly fails. This is
  compatibility/safety behavior, not the primary path.

### Remaining verification and doc-sync items

- Active SoT and roadmap docs still need to separate "implemented/integrated" from "remaining
  cleanup/doc-sync" precisely. Tracked by: #229
- Legacy/VaultMirror references still need a final audit so active docs do not describe the removed
  mirror path as current runtime behavior.
- Companion note + Note Context should still be treated as forward-line work for broader rollout
  hardening and doc cleanup, even though the core implementation is now present.

## Repo re-baseline (2026-03-29)

The current repository disproves the earlier "nothing is implemented yet" assumption for this plan.
As of this re-baseline:

- companion note service is implemented,
- Note Context is implemented,
- ingest ignore-glob defaults exclude `_system/companions/**`,
- PanelAgent uses Note Context first and retains a legacy fallback,
- and the remaining work is now rollout verification plus doc sync, not first implementation.

The historical implementation sequence below is retained as the intended migration order, but it
should now be read as forward work rather than partially shipped work.

## Three problems being solved

### Problem 1: File-based continuity (companion note)

The system lacks a portable, file-based artifact that preserves a vault note's identity, surface
(including attachments), and system state. VaultMirror fills this role poorly.

### Problem 2: Agent context starvation (Note Context)

Every agent operates with a shockingly narrow view of the artifact it is meant to help with. There
is no unified context assembly.

### Problem 3: Healing contract compliance

Current healing logic mixes mirror-reading, fingerprint-searching, and uuid-derivation in ways
that do not follow the scenario-based authority matrix defined in the contracts.

## Design decisions

### Companion note replaces VaultMirror entirely

There is no coexistence period. Legacy VaultMirror files are not migrated — they are discarded.
The companion note subsumes the continuity/identity function that VaultMirror performed.

Rationale:
- Docs already describe VaultMirror as transitional compatibility language.
- VaultMirror's directory-preserving path creates unnecessary rename/move complexity.
- VaultMirror's field set duplicates human-owned metadata.
- Two parallel system files per note is unnecessary complexity.

### Companion note path

`vault/_system/companions/<uuid>.md`

Already defined in COMPANION_NOTE_CONTRACT:49 and confirmed by OBSIDIAN_KNOWLEDGE_PORT:75 as a
system-owned vault path.

### Companion note field set (bounded)

From COMPANION_NOTE_CONTRACT:61-68:

```yaml
uuid: <uuid>
source_ref: <vault-relative path>
title: <repair cache — not authoritative>
content_hash: <sha256 of stripped text>
ingest_state: tracked | stale | soft_deleted
last_ingested: <ISO 8601>
created_by_instance: <instance id>
```

Fields explicitly NOT included:
- `review_state` — vault note frontmatter owns this
- `maturity` — vault note frontmatter owns this
- `kind` — implicit (companion notes exist only for tracked artifacts)
- `origin` — implicit (always "vault" in MVP)
- `ingest_fingerprint` (dict) — replaced by `content_hash` (scalar)

### Attachment manifest (bounded extension)

Permitted by COMPANION_NOTE_CONTRACT:70-71 as bounded continuity metadata.

```yaml
attachments:
  - ref: <vault-relative path to file>
    content_hash: <sha256>
```

Boundaries:
- Shared attachments: each companion lists the reference independently. No ownership claim.
- Delete semantics: if an attachment is no longer referenced in note text, it is removed from the
  manifest at next ingest. The system never writes `![[...]]` back into a vault note.
- Retained artifacts (PDFs, emails): these are NOT note attachments. They are their own artifacts
  in the retention plane and do not need companions in MVP.
- Repair: companion note records that an attachment existed. The system never auto-repairs embed
  references in vault notes — that would rewrite human meaning.

### Note Context abstraction

A runtime-assembled context that agents consume. Not a file — an in-memory structure built
on-demand from all three surfaces:

- **Identity layer** (from companion note): uuid, source_ref, content_hash, ingest_state,
  attachment manifest
- **Human artifact layer** (from vault note): full text, frontmatter, structure, embeds
- **Relations layer** (from runtime index): outgoing links, backlinks
- **Agent history layer** (from runtime DB): classification, executed actions, promotion history
- **Policy layer** (from settings): kind policy, trust level

Each agent specifies a context budget. Note Context truncates intelligently per budget.

### Ignore scope

Ingest ignore-glob for companion notes: `_system/companions/**` specifically.
NOT `_system/**` broadly — other future system surfaces under `_system/` must not be excluded.

### Write path

All companion note writes through `KnowledgePort` or approved helpers built on top of it
(OBSIDIAN_KNOWLEDGE_PORT:67-76). The current `note_mirror.py` uses `write_note_from_absolute` —
the new module uses the same helpers with companion path.

## Healing specification (contract-compliant)

### Healing priority order (ARTIFACT_MODEL:356-362)

1. UUID in frontmatter → use directly
2. Companion note identity record → recover UUID
3. DB identity record → recover UUID
4. source_ref / path match → reuse with logging
5. Exact content-hash match → reuse in rename/copy scenario
6. Semantic similarity → triage only, human review if ambiguous
7. No match → generate new UUID

### Missing companion (COMPANION_NOTE_CONTRACT:92-99)

- If vault note has uuid AND DB has identity record: rebuild companion from DB + vault note, log
  as recovery scenario
- If vault note has uuid but DB is missing: create companion from vault note metadata, log as
  cold-start scenario
- Otherwise: companion is created during normal ingest

### Damaged companion (COMPANION_NOTE_CONTRACT:101-106)

- Repair bounded fields conservatively
- Log repair scenario with old/new values
- If uuid ambiguity: flag, do NOT rewrite silently

### Note-companion UUID conflict (ARTIFACT_MODEL:285-291)

- No blind dominance rule
- Log the conflict
- Frontmatter UUID wins unless companion UUID has stronger provenance
- Flag for human review if ambiguous

## Implementation phases

### Phase 1: Companion Note Service

Goal: `companion_note.py` with read, write, healing scenarios, and attachment scanning.

Create:
- `app/services/companion_note.py` — path, read, write, `scan_attachments()`
- `tests/services/test_companion_note.py`

Remove:
- `app/services/note_log.py`
- `app/services/note_mirror.py`
- `tests/services/test_note_log.py`
- `tests/services/test_note_mirror.py`

Test coverage for healing:
- Normal create (ingest new note)
- Missing companion + DB exists → rebuild companion
- Missing companion + DB missing → create from vault note
- Damaged companion → conservative repair + logging
- Note-companion UUID conflict → logging, flag
- Path change → update source_ref

Exit criteria: companion service with full healing coverage; legacy mirror modules removed.

### Phase 2: Ingest and Worker Migration

Goal: `vault_alpha.py` and `outbox_worker.py` write companion notes instead of mirrors.

Changes:
- `app/ingest/vault_alpha.py`:
  - `_write_mirror()` → `upsert_companion()`
  - `_load_mirror_frontmatter()` → `read_companion()` (flat UUID lookup)
  - `_find_mirror_uuid_by_fingerprint()` → `find_companion_by_content_hash()`
  - Cold rebuild logic: check `_system/companions/` instead of `System/Metadata/VaultMirror`
  - Fingerprint skip: compare `content_hash` (scalar) instead of `ingest_fingerprint` (dict)
- `app/workers/outbox_worker.py`: `upsert_note_mirror()` → `upsert_companion()`
- `app/cli/alpha_human_flows.py`: `note_log_path()` → `companion_path()`
- `app/ingest/config.py`: ensure `_system/companions/**` in ignore_glob

Verification:
- All existing ingest tests (adapted to companion paths)
- Cold rebuild: empty DB + companions → full rebuild works
- Cold rebuild: empty DB + no companions → clean start works
- Fingerprint skip: identical content → skip, changed content → re-ingest
- Event/outbox compatibility: `ingest.vault.changed` events unchanged
- Idempotency: double ingest → same result
- Watcher chain: companion writes do NOT trigger new watcher events

Exit criteria: no import of `note_mirror` or `note_log` in codebase; all ingest paths via
companion; event contracts unchanged.

### Phase 3: Note Context Abstraction

Goal: `note_context.py` that assembles rich context from companion + vault note + runtime.

Create:
- `app/services/note_context.py` — `build_note_context()`, `NoteContext` dataclass
- `tests/services/test_note_context.py`

Changes:
- `app/agents/panel_agent/graph.py` — use Note Context instead of 800-char snippet
- `app/agents/classifier/agent.py` — receive title + metadata via Note Context

Budget strategy:
- Each agent specifies a `ContextBudget` with max_chars, include_relations, include_attachments
- Note Context truncates intelligently per budget
- Panel Agent default: 2000 chars body + frontmatter + relations summary
- Classifier default: title + 4000 chars + tags

Exit criteria: Note Context service works; at least Panel Agent uses it.

### Phase 4: Attachment Manifest

Goal: ingest parses `![[...]]` embeds and populates attachment manifest in companion note.

Changes:
- `app/services/companion_note.py` — `scan_attachments()` implementation
- `app/ingest/vault_alpha.py` — call scan_attachments during ingest
- `app/services/note_context.py` — expose attachments in NoteContext

Embed syntax to handle:
- `![[file.png]]` — inline image embed
- `![[file.pdf]]` — inline document embed
- `![[file.png|caption]]` — embed with alias
- `![[file.png#heading]]` — embed with anchor (extract filename)
- NOT: `[[note]]` — that is a note link, not an attachment

Resolve strategy: search relative to vault root. If Obsidian-configured attachment folder exists,
search there too. If file not found: include in manifest with `content_hash: null`.

Exit criteria: companion notes contain attachment manifest; Note Context exposes it.

### Phase 5: Doc Sync and Cleanup

Goal: docs and code consistent; no VaultMirror references in active codebase.

Changes:
- `docs/CONCEPTS/MIRROR_RECEIPT_DECISION.md` — update current implementation section
- `docs/DATA_MODEL.md` — update mirror references
- `docs/ARCHITECTURE.md` — remove transitional language
- Other docs referencing VaultMirror path — update

Exit criteria: docs and implementation tell the same story.

## What this plan defers

- Retained artifact companions (PDFs, emails) — future, when retention plane is implemented
- Multi-modal ingest of attachment content (OCR, vision) — future
- Full receipt artifact implementation — separate concern per MIRROR_RECEIPT_DECISION
- Cross-note relation extraction during ingest — future (currently runtime-only)
