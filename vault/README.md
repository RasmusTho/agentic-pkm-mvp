State: SoT v4.10 Reality-MVP (current, with known debt).
# Vault

This is the PKM-Alpha vault surface for Reality-MVP. Human-authored notes live here; the system ingests via CLI (`vault-alpha-ingest`), heals UUID frontmatter when missing, and mirrors metadata under `System/Metadata/VaultMirror`.

Orientation:
- Inbox/@Desk: working surfaces for new notes.
- Minimal frontmatter: `uuid` (recommended), optional `title`/trust/state fields (see `docs/FRONTMATTER.md`).
- AI panels are optional and stripped before indexing (see `docs/PANEL_AGENT.md`).
- System settings live under `_system/` (YAML) and `@Settings/` (examples); runtime config is mostly env-based (`docs/SETTINGS.md`).

See `docs/INGEST.md` and `docs/HUMAN-FLOWS.md` for the ingest flow; `docs/OBSIDIANSYNC.md` covers vault sync expectations.
