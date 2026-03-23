State: v5.4 delivered (watcher MVP + hardening); v5.5D auto-exec gated on concurrency guards.
# Track — Watcher (v5.1–v5.4 delivered)

Scope: snapshot-based vault watcher CLI/daemon, policy-gated panel auto-runs, ergonomics (dry-run, max-notes), Docker-first deployment. Runtime now standardizes on the registry watcher (`configs/watchers.yaml` + `python -m app.cli watcher run`).

## Delivered (v5.1–v5.4)
- Targeted ingest: `ingest-vault-paths` ingests specific markdown files (reused by watcher) — v5.1.
- Panel run-many CLI: `panel run-many` runs parse/runtime for multiple notes; watcher uses the same entrypoint — v5.1.
- Legacy snapshot watcher (dev-only): `vault-watcher-run` performs snapshot diff, runs ingest for changed notes, optionally panel runtime, prints summary, refreshes snapshot — v5.2.
- Auto-panel policy: v5.3 watchers treat any note with an AI panel fence as a candidate once `WATCHER_AUTO_EXEC=1` is armed; frontmatter only blocks via `ai_panel_auto_run: never` (nested form accepted), while manual CLI is always allowed.
- Hardening & ergonomics: `--dry-run`, `--max-notes` + `--force`, structured summaries, policy skip counters — v5.4.
- Legacy daemon (dev-only): `vault-watcher-daemon` for Docker-first polling with snapshot at `/state/vault_watcher_state.json`; host service fallback (launchd/systemd) for unreliable mounts.
- Registry watcher: config-driven watcher loop (`configs/watchers.yaml`, `python -m app.cli watcher run`) becomes runtime standard; start-system flows use this path.

## v5.5D: Auto-exec Safety (CRITICAL)
- Concurrency & Idempotency Guards MUST be green before watcher auto-exec is enabled.
- Deduplicate concurrent watcher runs and auto-exec triggers to avoid duplicate events/intents.
- Note writes MUST use optimistic locking; conflicts fail safe with no corruption.
- Panel actions MUST be idempotent (`ai:id` executes at most once).
- Reference: `docs/CONCURRENCY.md`.

## Operational notes
- Watcher remains polling/snapshot-based (no OS file events).
- DB outbox is the authoritative queue; `index-outbox.jsonl` is telemetry only. The watcher enqueues intents/events to the DB outbox so the worker processes them.
- Once watcher auto-exec is armed, any AI-fenced note is a candidate unless explicitly opted out with `ai_panel_auto_run: never`.
- Summaries report changed, ingest_attempted/ingested, panel_candidates/runs, skipped_policy/limit, promotions, errors, dry_run flag.

## Links
- Forward plan items: see `docs/ROADMAP.md` (Now/Next).
- Human flow/UAT: `docs/HUMAN-FLOWS.md`.
- Observability counters: `docs/OBSERVABILITY.md` (watcher_runs, panel_runs, promotion intents/executions).
