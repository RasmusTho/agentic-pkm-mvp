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
- For the repo-supported clean-state path, use `make test-bootstrap` and the default `vault-test/` vault.
- For manual exploratory runs, use a test vault or a clearly marked subset (3–10 notes) in PKM-Alpha.
- Before any auto-exec enablement, run `python -m app.cli settings-explain` and `python -m app.cli status`; these are the canonical enablement checks.
- Confirm the watcher gate, allowlist validity, write guard/provenance context, and recent skip reasons are coherent across both CLI surfaces.
- Treat `WATCHER_AUTO_EXEC=1` as necessary but not sufficient; do not treat the env var alone as rollout approval.

## Canonical Clean-State Path

Use this when validating the supported local test bootstrap from scratch:

```bash
make test-bootstrap
```

What it does:
- resets runtime state
- creates the vault layout in `vault-test/`
- seeds the UAT pack
- starts the stack against that vault
- runs runtime verification
- runs `uat-run-vault-test --assert`

If you need to inspect the phases individually, use:

```bash
make test-vault-init
VAULT_ROOT="$(pwd)/vault-test" scripts/start_full_system.sh
VAULT_ROOT="$(pwd)/vault-test" bash scripts/verify_runtime_stack.sh
VAULT_ROOT="$(pwd)/vault-test" python -m app.cli uat-run-vault-test --vault-root "$(pwd)/vault-test" --assert
```

## 2) Prepare test notes
- Pick a handful of notes (3–10) for UAT; keep the rest untouched.
- Add an AI panel fence to each test note (per `docs/PANEL_AGENT.md`). Any fence line `%% ...ai... %%` makes a note a watcher candidate by default.
- Per-note opt-out only: `ai_panel_auto_run: never` (or `ai_panel: { auto_run: never }`) blocks watcher panel runs.
- Inbox UUID healing is automatic during watcher/ingest runs; inbox notes should not remain without a `uuid` after a watcher pass.

## 3) Manual ingest + panel runs (sanity)

**Store backend requirement:** `ingest-vault-paths` and `panel run-many` are separate CLI processes. Each process creates its own in-process store. With `STORE_BACKEND=memory` (the default when no `DATABASE_URL` is set), notes ingested by `ingest-vault-paths` are discarded when that process exits — they are not visible to a subsequent `panel run-many` invocation. The "Note not found in ObjectStore" error is expected in this mode.

To run this manual sanity flow you need either:
- `DATABASE_URL=<pg_dsn>` — notes are persisted in Postgres across CLI invocations (full stack)
- or skip this section and use the host-only watcher path in section 4a instead, where ingest and panel run inside the same watcher process

With `DATABASE_URL` set:

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

## 4a) Host-only acceptance path (no Docker / no DATABASE_URL)

Use this section when you need to validate watcher + panel behavior on a real vault subset without a running Postgres instance. The registry watcher runs ingest and panel in-process per tick, so the cross-process store limitation in section 3 does not apply.

**Prerequisites:**
- `STORE_BACKEND` not set (defaults to `memory`) — no Postgres required
- `INDEX_OUTBOX_PATH` set to a writable JSONL file (e.g. `tmp/index-outbox.jsonl`) so status can read watcher activity

```bash
export WATCHER_ENABLE=1
export WATCHER_VAULT_PATH=<vault_root>
export VAULT_INBOX_DIR_REL=<inbox_dir_rel>       # e.g. Inbox
export WATCHER_SCOPE_GLOB='_CodexUAT/**/*.md'    # bounded subset
export INDEX_OUTBOX_PATH=tmp/index-outbox.jsonl
export WATCHER_AUTO_EXEC=0
python -m app.cli watcher run --max-ticks 1
```

Then check status:
```bash
python -m app.cli status
```

Expected after the watcher tick:
- `watcher runs: total` increments by 1 (or more for multi-spec configs).
- `Watcher automation` shows `mode=emit-only`, `panel_candidates` > 0, `panel_skipped_auto_exec` = panel_candidates.
- `tmp/watcher_tick.jsonl` and `tmp/index-outbox.jsonl` contain consistent tick records.
- `vault: 0 objects` is expected in memory mode after the watcher exits — memory is not persisted across CLI processes. This is correct behavior, not a bug.

To also exercise panel runs inline:
```bash
export WATCHER_AUTO_EXEC=1
python -m app.cli watcher run --max-ticks 1
```

After a full auto-exec tick:
- `watcher runs: total` increments again.
- JSONL outbox contains `panel.scan.requested` entries for candidate notes.
- Tick log shows non-zero `panel_candidates` and zero (or low) `panel_skipped_auto_exec`.

**What this path does not validate:**
- Persistent store state across CLI boundaries (requires DATABASE_URL).
- `panel run-many` on previously ingested notes (requires DATABASE_URL).
- Worker/outbox delivery (requires DATABASE_URL + worker process).

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
- Status: `python -m app.cli status` (or status API) should reflect ingest counts and watcher runs; ASK should surface the UAT notes with source refs (requires DATABASE_URL for cross-process note persistence).
- Watcher runs counter: after `watcher run --max-ticks 1`, `status` should show `watcher runs: total >= 1`. If still 0, check that `INDEX_OUTBOX_PATH` resolves to a writable path and re-run.
- Memory mode store: `store-stats` and `status vault: N objects` will report 0 in memory mode after a watcher process exits. This is expected — memory store is per-process. Use `DATABASE_URL` for persistent object counts.
- Enablement signals: `settings-explain` should agree with `status` on auto-exec mode, allowlist, skip counters, and write-guard/provenance context before an operator treats watcher auto-run as safe.
- DB outbox: inspect `outbox` table (or `/api/events/tail` if available) for `panel.intent.*` and `promote.intent.created`.
- JSONL audit: `INDEX_OUTBOX_PATH` lines contain `watcher.run` and `panel.scan.requested` entries after a watcher tick; these are the basis for `status watcher runs` counts.
- CI corroboration: when this UAT flow is part of a release or merge gate, require `CI SUMMARY GATES ok=true` in addition to the local operator signals.
- Safety: watcher does not rewrite note bodies; downstream agents may update frontmatter/mirrors only. UAT is scoped to the selected notes; the rest of the vault is untouched.
- Scripted UAT report: `uat-run-vault-test --assert` writes `.agentic-pkm/uat_report.json` inside the seeded folder. Treat that report as the machine-readable release/UAT artifact; it includes first-run results, rerun idempotence, and pass/fail checks.
- Repo-supported startup alignment: `uat-seed-vault-test` also updates the ingest override so the seeded UAT folder is part of the startup bootstrap ingest contract for the local test path.

## 7) Limits and future work
- Scope: single-user UAT on a subset of notes; no multi-user or remote watcher yet.
- Registry watcher is the runtime standard; legacy snapshot watchers are dev-only.
- Policy can be refined later (per-panel modes, additional triggers) without changing the current contract.
- This runbook should be read together with `docs/DESIGN_PRINCIPLES.md` and `docs/ARCHITECTURE.md` so operational validation does not get mistaken for the full design model.
