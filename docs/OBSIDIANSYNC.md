State: SoT v4.10 Reality-MVP (current; limited automation).
# Obsidian-first sync

This doc describes how the Obsidian vault PKM-Alpha (Mimer) is synced and mirrored today. For flow semantics see `docs/HUMAN-FLOWS.md` (Capture & Ingest) and surfaces in `docs/SYSTEM_DESIGN_v4.10.md`.

## Principles
- Human-first: the system never edits the note body, only agreed frontmatter keys.
- UUID = identity; filename/path is cosmetic. VaultMirror stores per-note logs under `System/Metadata/VaultMirror/**`.
- Git is the preferred transport between machines; iCloud/Drive is fine as a file carrier. There is **no active watcher** in Reality-MVP—ingest is triggered manually via CLI.

## Plugins (recommended, not required by the runtime)
- Obsidian Git (sync), Dataview (dashboards), and light templating helpers (Templater/QuickAdd). The runtime does not depend on plugin APIs.

## Flows (Reality-MVP)
- Obsidian → system: edit notes → sync (Git/iCloud) → run CLI ingest (`vault-alpha-ingest` / `ingest-vault-root`). Ingest heals/frontfills `uuid` frontmatter, writes VaultMirror logs, and indexes into Stores.
- System → Obsidian: automated writes are limited to frontmatter UUID healing during ingest. There is no auto-rename/move. Panel content is stripped before indexing.

## Write/rename policy
- Bodies are untouched; only frontmatter keys such as `uuid`, `title`, `origin`, `review_state` are updated during ingest when needed.
- No auto-rename/move in Reality-MVP; moves require manual edits. Indexing is triggered only when content changes or ingest is forced.

## Notes on legacy tooling
- `scripts/fs_watcher.py` and Advanced-URI inbox flows are legacy placeholders; not active in the Reality-MVP pipeline.
- Settings hot-reload from vault markdown is not wired; runtime settings come from env/defaults (see `docs/SETTINGS.md`).
