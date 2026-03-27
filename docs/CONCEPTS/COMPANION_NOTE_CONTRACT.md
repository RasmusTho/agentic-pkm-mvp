State: Active contract — companion note replaces VaultMirror as the system-owned identity surface per vault note.
---
type: concept-contract
status: active
---

# Companion Note Contract

## Role

A companion note is the **system-owned identity file** for a vault note. Together with the vault note it forms the complete filbaserade artefakt for that knowledge object. It is portable (moves with the vault via Git), bounded (fixed field set, no free-form content), and flat (keyed by UUID, not by vault path).

The companion note is **not** a mirror of the vault note. It does not duplicate human-owned fields. It is the system's half of the artefakt.

## Path

```
vault/_system/companions/<uuid>.md
```

Flat directory — one file per UUID, no sub-folders. The path is determined by UUID, not vault path, so moves/renames do not invalidate it.

## Bounded Field Set

```yaml
uuid: <uuid>                        # REQUIRED — the canonical object UUID
source_ref: <vault-relative path>   # REQUIRED — current vault path (repair cache on move)
title: <string>                     # repair cache; NOT authoritative
content_hash: <sha256>              # sha256 of AI-panel-stripped note text
ingest_state: tracked | stale | soft_deleted
last_ingested: <ISO 8601>
created_by_instance: <instance id>
attachments:                        # optional; observed embeds, not authoritative claims
  - ref: <vault-relative path>
    content_hash: <sha256 | null>   # null if file not found at ingest time
```

## What the Companion Note Must NOT Contain

| Field | Reason |
|---|---|
| `review_state` | Human-authorised state — lives in vault note frontmatter only |
| `maturity` | Human-authorised state — lives in vault note frontmatter only |
| `kind` | Implicit; companion notes only exist for tracked vault artefacts |
| `origin` | Implicit; always `vault` in MVP |
| `ingest_fingerprint` (dict) | Replaced by `content_hash` (scalar) |
| Any LLM output | Companion note must not accumulate agent decisions |

Violating these rules would break the human/system ownership boundary established in `docs/CONCEPTS/LAYERING_MODEL.md`.

## Attachment Manifest Rules

The attachment manifest is an **observed reference list**, not an ownership claim:

- Each companion lists attachments referenced via `![[file.ext]]` embed syntax in the note body.
- A shared attachment (image referenced from two notes) appears in both companions — no exclusivity.
- An attachment removed from the note body is removed from the manifest at next ingest.
- The system **never writes** `![[file.ext]]` into a vault note to "repair" missing embeds. Companion note is a diagnostic surface, not an auto-repair mechanism.
- `![[note]]` wiki-links are NOT attachments; only `![[file.ext]]` embed-syntax is scanned.
- Retained artefacts (PDFs, emails in retention plane) are NOT vault note attachments and do not appear here.

## Ingest States

| State | Meaning |
|---|---|
| `tracked` | Note was present and ingested at `last_ingested` |
| `stale` | Companion exists but note has not been re-ingested since the hash changed |
| `soft_deleted` | Note was removed from vault but companion is retained for provenance |

## Ownership

- The companion note is **system-owned**. Humans should not edit it.
- The `_system/companions/` directory is excluded from watcher scope and ignored by ingest (`ignore_glob: _system/companions/**`).
- Writes go through `write_companion()` in `app/services/companion_note.py`; never written ad-hoc.

## Implementation

- Service: `app/services/companion_note.py`
- Tests: `tests/services/test_companion_note.py`
- Plan: `docs/plans/COMPANION_NOTE_AND_NOTE_CONTEXT.md`
