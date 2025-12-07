State: SoT v4.10 Reality-MVP (current).
# Ingest (Reality-MVP)

Goal: ingest vault notes safely and deterministically into Stores + HybridStore, with UUID healing and panel stripping. External ingest is manual/minimal in this slice.

## Primary commands
```bash
# Non-recursive, quick scan of vault root
python -m app.cli ingest-vault-root --limit 10

# Canonical ingest for PKM-Alpha vault (Concepts + optional test note)
python -m app.cli vault-alpha-ingest --max-notes 200 [--include-test-note] [--force]

# Convenience wrapper for vault root
python -m app.cli pkm-alpha-ingest --limit 50
```

## Flow (vault-alpha-ingest)
1. Read notes under `Concepts/` (and optional Test note), strip AI panels from bodies.
2. Ensure frontmatter `uuid: [[<uuid>]]` (heal/write when missing), preserve human fields.
3. Compute ingest fingerprint (text SHA + mtime); skip unchanged unless `--force` or cold-rebuild (empty store but mirrors exist).
4. Write/update VaultMirror log (`System/Metadata/VaultMirror/**/uuid.md`) with Core-6 projection + fingerprint.
5. Persist to Store abstraction (`store_objects`) and HybridStore (ObjectStore + VectorIndex) with payload `{title, origin=vault, source_ref, text, ingest_fingerprint}`.
6. Run Classifier heuristics (LLM mock by default) and append an outbox JSONL entry at `INDEX_OUTBOX_PATH` (default `tmp/index-outbox.jsonl`).
7. Emit embeddings via Indexer (component-based embeddings; rerank optional).

## Data/identity rules
- UUID is the stable identity; mirror and frontmatter must agree. Frontmatter wins if there is a conflict.
- Panel text is stripped before indexing; not part of payloads or embeddings.
- Moves/renames are not automated; ingest does not change paths beyond frontmatter UUID healing.

## External ingest (limited)
- There is no automated external drop ingest in Reality-MVP. External objects appear only if inserted directly into the Store with `origin=external_raw`; they are indexed alongside vault objects.

## Legacy commands (still available)
- `python -m app.cli normalize <PATH|URL>` — normalize a single file/URL into Core-6 + outbox payload.
- `python -m app.cli pipe <PATH|URL|AUDIO>` — normalize → classify (+ transcribe for audio).
These remain for ad-hoc ingest but the vault-first CLI commands above are the supported path.

## Troubleshooting
- For quick checks (UUID healing, fingerprint skips, outbox corruption), see the runbook: `docs/runbooks/ingest.md`.
