State: SoT v4.10 Reality-MVP (current).
# Obsidian-first sync

This doc describes how the Obsidian vault PKM-Alpha (Mimer) is synced and mirrored. For how this fits into the overall system, see `docs/HUMAN-FLOWS.md` (Capture & Ingest flow) and the surfaces in `docs/SYSTEM_DESIGN_v4.10.md`.
Watcher note: Runtime now uses the registry watcher (`configs/watchers.yaml` + `python -m app.cli watcher run`) and the DB outbox as the canonical queue. Legacy snapshot watchers (`vault-watcher-run`/`vault-watcher-daemon`) are dev-only. For a hands-on walkthrough, see `docs/UAT_PANEL_WATCHER.md`.

## Principles
- Human-first: the system never edits the note body, only agreed frontmatter keys.
- UUID = identity, filename = cosmetic.
- Git is the primary change channel; iCloud can be used as transport.

## Plugins
- Required: Obsidian Git, Dataview
- Recommended: Templater/QuickAdd, MetaEdit/Properties++, Advanced URI, Linter

## Flows
- Obsidian → DB: commit → registry watcher → ingest/update pipeline → DB outbox → worker/indexer
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

## Knowledge Port abstraction (vNext)
- Obsidian interactions are now specified behind `app/knowledge` contract types (`KnowledgePort`, `NoteLocator`, `WriteReceipt`) so domain/runtime code does not bind directly to transport details.
- Current adapters:
  - `FsVaultAdapter` for deterministic local/test writes.
  - `ObsidianCliAdapter` for Obsidian CLI-driven operations.
- Inbox service writes (change/conflict logs) now append via `KnowledgePort` rather than direct file I/O.
- Vault sync note writes (UUID heal/frontmatter write path) now write via `KnowledgePort`.
- UUID heal writes in `note_uuid` service now write via `KnowledgePort` as well.
- Promotion queue frontmatter update writes now route via `KnowledgePort`.
- `panel-update` CLI writes now route via `KnowledgePort`.
- Settings auto-heal/writeback (`app/settings/compiler.py`, `app/settings/writeback.py`) now writes markdown settings notes via `KnowledgePort`.
- Vault layout/system-note creation (`app/vault/layout.py`) now writes notes via `KnowledgePort`.
- Vault identity resolution for Obsidian (`OBSIDIAN_VAULT_NAME`, blank-safe default) is centralized in `app/knowledge/vault_identity.py`.
- `NoteLocator` creation is centralized via `app/knowledge/locators.py` so path separator and relative-path rules stay consistent across adapters/services.
- Policy + startup posture is governed by `KNOWLEDGE_*` settings and health-gated via `python -m app.cli health --json`.
- See `docs/contracts/OBSIDIAN_KNOWLEDGE_PORT.md`.
