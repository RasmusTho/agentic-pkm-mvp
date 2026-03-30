State: SoT v4.10 (Reality-MVP) and v5.x (PanelAgent Runtime + registry watcher) are locked baselines; watcher track v5.1–v5.4 is implemented and now runs via the registry watcher; v5.6A adds explicit operator enablement checks.
# UAT — PanelAgent + Registry Watcher

Purpose: practical, low-risk UAT flow for exercising PanelAgent runtime and the registry watcher on a small subset of vault notes.

Reading note:
- this runbook validates the current runtime path,
- not the full target-state architecture,
- and not a permanent commitment to one agent/event decomposition beyond the current baseline.

## 1) Preconditions
- Reality-MVP (SoT v4.10) is in place: ingest, ASK, observability, orchestrator runtime V1.
- PanelAgent Runtime V1 (SoT v5.x) is working (`panel.intent.*`, `panel.log.created`, `promote.intent.created`).
- Registry watcher is available:
  - `configs/watchers.yaml` defines two watchers: `panel` and `ingest`.
  - Runtime entrypoint: `python -m app.cli watcher run`.
- Runtime DB outbox is available (`DATABASE_URL` or `DB_DSN`); JSONL outbox is audit/diagnostic only.
- Use a test vault or a clearly marked subset (3–10 notes) in PKM-Alpha.
- Before any auto-exec enablement, run `python -m app.cli settings-explain` and `python -m app.cli status`; these are the canonical enablement checks.
- Confirm the watcher gate, allowlist validity, write guard/provenance context, and recent skip reasons are coherent across both CLI surfaces.
- Treat `WATCHER_AUTO_EXEC=1` as necessary but not sufficient; do not treat the env var alone as rollout approval.

## 2) Prepare test notes
- Pick a handful of notes (3–10) for UAT; keep the rest untouched.
- Add an AI panel fence to each test note (per `docs/PANEL_AGENT.md`). Any fence line `%% ...ai... %%` makes a note a watcher candidate by default.
- Per-note opt-out only: `ai_panel_auto_run: never` (or `ai_panel: { auto_run: never }`) blocks watcher panel runs.
- Inbox UUID healing is automatic during watcher/ingest runs; inbox notes should not remain without a `uuid` after a watcher pass.

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
   - Outbox events (DB): `panel.intent.created`, `panel.intent.executed`, `panel.action.*`, `panel.log.created`, `promote.intent.created` (when mappings include promotion).
   - `panel_logs` field on the note payload (via status/ASK surfaces) contains AI-log entries.
   - No note body rewrites; only frontmatter/mirror metadata changes.

## 4) Registry watcher pass — no panel mutations
1. Run a limited tick with panel auto-exec disabled:
   ```bash
   export WATCHER_ENABLE=1
   export WATCHER_VAULT_PATH=<vault_root>
   export VAULT_INBOX_DIR_REL=<inbox_dir_rel>
   export WATCHER_AUTO_EXEC=0
   export DATABASE_URL=<db_dsn>
   python -m app.cli watcher run --max-ticks 1
   ```
2. Expected behavior:
   - Watcher computes panel candidacy and emits summaries.
   - Panel auto-exec is skipped when `WATCHER_AUTO_EXEC=0`.
   - Ingest still runs for changed notes; inbox UUID healing can occur as part of ingest.
   - `python -m app.cli status` should show `Watcher automation` with `mode=emit-only` and non-error skip counters.

## 5) Registry watcher pass — full run
1. Re-run with panel auto-exec armed:
   ```bash
   export WATCHER_AUTO_EXEC=1
   python -m app.cli watcher run --max-ticks 1
   ```
2. Watcher will:
   - emit DB outbox events for ingest and panel runs,
   - run PanelAgent runtime only for candidate notes that are not opted out,
   - keep JSONL outbox as an audit log only.
   - `python -m app.cli settings-explain` should show the effective gate as enabled, the allowlist, and watcher settings provenance.

## 6) What to observe & rollback posture
- Status: `python -m app.cli status` (or status API) should reflect ingest counts and runs; ASK should surface the UAT notes with source refs.
- Enablement signals: `settings-explain` should agree with `status` on auto-exec mode, allowlist, skip counters, and write-guard/provenance context before an operator treats watcher auto-run as safe.
- DB outbox: inspect `outbox` table (or `/api/events/tail` if available) for `panel.intent.*` and `promote.intent.created`.
- JSONL audit: `INDEX_OUTBOX_PATH` lines should mirror watcher emissions but are not consumed by the worker.
- CI corroboration: when this UAT flow is part of a release or merge gate, require `CI SUMMARY GATES ok=true` in addition to the local operator signals.
- Safety: watcher does not rewrite note bodies; downstream agents may update frontmatter/mirrors only. UAT is scoped to the selected notes; the rest of the vault is untouched.
- Scripted UAT report: `uat-run-vault-test --assert` now writes `.agentic-pkm/uat_report.json` inside the seeded folder. Treat that report as the machine-readable release/UAT artifact; it includes first-run results, rerun idempotence, and pass/fail checks.

## 7) Limits and future work
- Scope: single-user UAT on a subset of notes; no multi-user or remote watcher yet.
- Registry watcher is the runtime standard; legacy snapshot watchers are dev-only.
- Policy can be refined later (per-panel modes, additional triggers) without changing the current contract.
- This runbook should be read together with `docs/DESIGN_PRINCIPLES.md` and `docs/ARCHITECTURE.md` so operational validation does not get mistaken for the full design model.
