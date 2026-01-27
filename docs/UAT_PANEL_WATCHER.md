State: SoT v4.10 (Reality-MVP) and v5.0 (PanelAgent Runtime V1) are locked; watcher track v5.1–v5.4 is implemented (targeted ingest, multi-note panel runtime, snapshot watcher CLI, auto-panel policy, dry-run/limits).
# UAT — PanelAgent + Vault Watcher

Purpose: practical, low-risk UAT flow for exercising PanelAgent runtime and the snapshot-based Vault Watcher on a small subset of vault notes.

## 1) Preconditions
- Reality-MVP (SoT v4.10) is in place: ingest, ASK, observability, orchestrator runtime V1.
- PanelAgent Runtime V1 (SoT v5.0) is working (`panel.intent.*`, `panel.log.created`, `promote.intent.created`).
- Watcher features v5.1–v5.4 are available:
  - Targeted ingest via `ingest-vault-paths`.
  - Multi-note panel runtime via `panel run-many` (supports `--emit-only`).
  - Snapshot-based watcher CLI `vault-watcher-run` with policy gating, `--dry-run`, and `--max-notes` guards.
- Use a test vault or a clearly marked subset (3–10 notes) in PKM-Alpha.

## 2) Prepare test notes
- Pick a handful of notes (3–10) for UAT; keep the rest untouched.
- Add an AI panel block to each test note (per `docs/PANEL_AGENT.md`).
- The watcher treats any fenced note as a candidate once the global arm switch `WATCHER_AUTO_EXEC=1` is set; only add `ai_panel_auto_run: never` (or `ai_panel: { auto_run: never }`) when you explicitly want to skip a watcher run.
- Leave notes without AI fences or with the `never` opt-out untouched to avoid accidental automation.

## 3) Manual ingest + panel runs (sanity)
1. Ingest the test notes by path:
   ```bash
   python -m app.cli ingest-vault-paths --vault-root <vault_root> path/to/note1.md path/to/note2.md
   ```
2. Run PanelAgent runtime on the same notes (UUIDs):
   ```bash
   python -m app.cli panel run-many <uuid1> <uuid2>
   # add --emit-only to skip runtime execution if desired
   ```
3. Observe:
   - Outbox events: `panel.intent.created`, `panel.intent.executed`, `panel.action.*`, `panel.log.created`, `promote.intent.created` (when mappings include promotion).
   - `panel_logs` field on the note payload (via status/ASK surfaces) contains AI-log entries.
   - No note body rewrites; only frontmatter/mirror metadata changes.

## 4) Watcher flow — dry-run first
1. Run the watcher in dry-run mode with a safe limit:
   ```bash
   python -m app.cli vault-watcher-run \
     --vault-root <vault_root> \
     --snapshot-path <state_file_optional> \
     --dry-run \
     --max-notes 20
   ```
2. Interpret the summary:
   - `changed` notes,
   - `ingest_attempted`/`ingested` (0 in dry-run),
   - `panel_candidates`, `panel_runs` (0 in dry-run),
   - `skipped_policy` (notes without watcher permission),
   - `skipped_limit` (if over `max-notes`),
   - `errors`.
3. No side effects in dry-run: no ingest, no panel runtime, no outbox/panel logs.

## 5) Watcher flow — real run
1. Re-run without `--dry-run` (keep `--max-notes` set; use `--force` only if necessary):
   ```bash
   python -m app.cli vault-watcher-run \
     --vault-root <vault_root> \
     --snapshot-path <state_file_optional> \
     --max-notes 20
   ```
2. Watcher will:
   - ingest changed notes via `ingest-vault-paths`,
   - auto-run PanelAgent runtime only for notes that allow watcher via frontmatter policy,
   - refresh snapshot and print a structured summary.

## 6) What to observe & rollback posture
- Status: `python -m app.cli status` (or status API) should reflect ingest counts and runs; ASK should surface the UAT notes with source refs.
- Outbox: check JSONL for `panel.intent.*`, `panel.log.created`, `promote.intent.created`.
- ASK: query for known content in the UAT notes; answers should cite those notes.
- Safety: watcher does not rewrite note bodies; downstream agents may update frontmatter/mirrors only. UAT is scoped to the selected notes; the rest of the vault is untouched.

## 7) Limits and future work
- Scope: single-user UAT on a subset of notes; no multi-user or remote watcher yet.
- Watcher is snapshot-based CLI (polling) for now; services/daemons and richer schedulers are future v5.x work.
- Policy can be refined later (per-panel modes, additional triggers) without changing the current contract.
