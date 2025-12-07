State: SoT v4.10 Reality-MVP (current; ops helper).
# Runbook — Ingest issues

Applies to the vault-first ingest path (`vault-alpha-ingest` / `pkm-alpha-ingest`). See `docs/INGEST.md` for the canonical flow.

## Common symptoms
- Duplicate or missing entries in `INDEX_OUTBOX_PATH` (default `tmp/index-outbox.jsonl`).
- Notes skipped unexpectedly (no UUID heal, fingerprint says unchanged).
- Panel text showing up in payloads or embeddings.

## Quick checklist
1) **Env and inputs** — Ensure `STORE_BACKEND=memory` or reachable PG; `LLM_PROVIDER=mock` for deterministic runs. Confirm vault path and `--limit/--max-notes` flags.
2) **UUID healing** — For a suspect note, check frontmatter `uuid` and the mirror `System/Metadata/VaultMirror/.../uuid.md` match. If missing, rerun with `--force` to heal.
3) **Fingerprint skips** — In `VaultMirror` entry, compare `ingest_fingerprint` with current file content/mtime. Use `--force` to bypass skips if needed.
4) **Outbox sanity** — Tail `INDEX_OUTBOX_PATH`; validate JSON lines and ensure entries include `source_ref` and `payload`. Delete or move the file to start clean if corrupted.
5) **Panel stripping** — Confirm the note body in Store/payload lacks AI panel blocks. If panels leak, re-run ingest; `app.agents.panel.filters.strip_ai_panels` should remove them.

## Recovery actions
- **Cold rebuild**: remove `tmp/index-outbox.jsonl` (or set a new path), set `STORE_BACKEND=memory`, and rerun `vault-alpha-ingest --force`.
- **Single-file reingest**: use `python -m app.cli normalize <PATH>` followed by `python -m app.cli pipe <PATH>` for ad-hoc fixes (legacy CLI).
- **Trace investigation**: rerun with `TRACE_ID=<id>` exported; inspect outbox entries with that trace.

## When to escalate
- Persistent JSON corruption in outbox even after reset.
- UUID conflicts between frontmatter and mirror that reruns do not heal.
- Indexer errors when embedding text (could indicate model/config issues).
