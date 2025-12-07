# Obsidian-first sync

This doc describes how the Obsidian vault PKM-Alpha (Mimer) is synced and mirrored. For how this fits into the overall system, see `docs/HUMAN-FLOWS.md` (Capture & Ingest flow) and the surfaces in `docs/SYSTEM_DESIGN_v4.10.md`.

## Principles
- Human-first: the system never edits the note body, only agreed frontmatter keys.
- UUID = identity, filename = cosmetic.
- Git is the primary change channel; iCloud can be used as transport.

## Plugins
- Required: Obsidian Git, Dataview
- Recommended: Templater/QuickAdd, MetaEdit/Properties++, Advanced URI, Linter

## Flows
- Obsidian → DB: commit → watcher → /ingest|/update → outbox → indexer
- DB → Obsidian: event → frontmatter write (if inactive) otherwise suggestion into /Inbox

## Write policy
- Never touch the body, no auto-rename, debounce + hash; rename/move only updates path.

## Rename policy
- File rename or move only updates `objects.path` and `file_state.path` via the watcher.
- No re-embedding is triggered on rename/move; indexing runs only when the file body changes.

## Settings hot-reload
- Backend reloads `vault/_system/settings/system-settings.yaml` on mtime change and applies policies without restart.
- Invalid YAML (validated against `schemas/system-settings.schema.json`) is logged and does not stop existing policies.

## Filesystem fallback
- `scripts/fs_watcher.py` mirrors the same policy as the git watcher and provides offline idempotence.
- An active file (detected via `settings.policy()`) is not written back; instead a triage message is added to Inbox with an Advanced-URI link.

## Advanced-URI UX
- All Inbox items get `obsidian://advanced-uri` links for quick navigation to the affected file.
- The `System/Dashboards/*.md` dashboard shows the latest events via Dataview tables.
