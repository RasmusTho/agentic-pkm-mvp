State: SoT v4.10 Reality-MVP (current).
# Frontmatter (vault plane)

Reality-MVP keeps vault frontmatter minimal and human-readable. UUID is the only required field; system metadata lives in the VaultMirror log (`System/Metadata/VaultMirror/**`), not in the note body.

## Required (vault notes)
- `uuid: [[<uuid>]]` — stable identity written/healed by ingest when missing.

## Optional (human-facing)
- `title` — human title (falls back to first heading/text).
- `origin` — usually `vault` (ingest sets this in mirrors; not required in the note).
- `review_state` / `maturity` / `trust` — human-declared only; ingest preserves values but does not overwrite them.
- `tags` / `aliases` / `related` — optional human context; relation extraction may read these for RelationIndex.

## System metadata
- Stored in VaultMirror (`uuid.md`) and store payloads: ingest fingerprints, agent decisions, promotion history, relations, zones.
- Panels are stripped before indexing; panel text is not part of frontmatter or the knowledge base.

## Write policy
- Ingest updates frontmatter only to insert/heal `uuid` (as a wikilink) and to remove stale `ingest_fingerprint` fields. No automatic renames or body edits occur.
