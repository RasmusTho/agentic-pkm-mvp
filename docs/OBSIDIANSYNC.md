State: SoT v4.10 Reality-MVP (current).
# Obsidian-first sync

This doc describes how the Obsidian vault PKM-Alpha (Mimer) is synced and mirrored. For how this fits into the overall system, see `docs/HUMAN-FLOWS.md` (Capture & Ingest flow) and the surfaces in `docs/SYSTEM_DESIGN_v4.10.md`.
Watcher note: This document reflects the current v4.10 baseline assumptions (git watcher primary, filesystem watcher fallback). Planned v5.x watcher work (v5.1–v5.4) keeps the same Obsidian → watcher → ingest/update → outbox → indexer pattern, using the same CLI/service entrypoints; see HUMAN-FLOWS watcher section. The v5.2 CLI polling watcher (`vault-watcher-run`) implements this pattern via snapshot diff + `ingest-vault-paths` + optional `panel run-many`; v5.4 adds dry-run and max-notes safety guards. A Docker-first daemon (`vault-watcher-daemon`) is now available for continuous polling with snapshots outside the vault (e.g., `/state`), with host-service fallback if mounts are flaky. For a hands-on walkthrough, see `docs/UAT_PANEL_WATCHER.md`.

## Principles
- Human-first: the system never edits the note body, only agreed frontmatter keys.
- UUID = identity, filename = cosmetic.
- Git is the primary change channel; iCloud can be used as transport.

## Plugins
- Required: Obsidian Git, Dataview
- Recommended: Templater/QuickAdd, MetaEdit/Properties++, Advanced URI, Linter

## Flows
- Obsidian → DB: commit → watcher (git preferred, filesystem fallback) → /ingest|/update CLI/service → outbox → indexer
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
