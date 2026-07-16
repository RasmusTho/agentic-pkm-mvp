---
name: Operate Sync from the CLI
description: Scriptable, secret-free command family with stable --json — youtube-auth connect/status/disconnect, youtube-sources list/configure/import-takeout, youtube-sync run/status/pause/resume/backfill/why/doctor.
task_id: YSS-10
source_anchor: "docs/YOUTUBE_SOURCE_SYNC/SOURCE_SYNC_CONTRACT.md :: Settings model"
parent_capability: YouTube Source Sync
prerequisites: [YSS-02, YSS-06]
depends_on: [BIND_YOUTUBE_ACCOUNT_WITH_OAUTH.md, SCHEDULE_AND_OPERATE_CONTINUOUS_SYNC.md]
can_parallelize_with: [REPAIR_GAPS_WITH_PREVIEWED_BACKFILL.md, SURFACE_SYNC_HEALTH_STATUS_AND_RECEIPTS.md]
---

# Operate Sync from the CLI

## Purpose

Everything the Companion UI can do, an operator or script can do headlessly with stable `--json`
output — the CLI is both the automation surface and the UI-independent fallback.

## What This Task Does

Two new click groups in the existing CLI structure (`app/cli/`, registered via
`cli.add_command`), thin wrappers over the core modules (no business logic in the CLI layer),
following the repo idioms: kebab-case, `--json`, `click.ClickException` for argument/precondition
errors, `SystemExit(1)` for ran-but-failed, secret-free output everywhere.

1. `youtube-auth` group (wraps YSS-02):
   - `connect [--device|--loopback] [--json]` — starts the flow; device mode prints
     `verification_url_complete` + `user_code` and polls to completion;
   - `status [--json]` — binding state, scopes, token-store posture, reason code;
   - `disconnect [--revoke/--no-revoke] [--json]` — the INV-YSS-4 disconnect semantics.
2. `youtube-sources` group (wraps YSS-01/07):
   - `list [--json]` — bindings with kind, title, enabled, interval, policy mode, last
     success/error;
   - `configure <binding_id> [--enable/--disable] [--interval N] [--policy MODE] [--set-inbox] [--json]`;
   - `add-playlist <playlist_ref> [--json]` — explicit public/unlisted/own playlist by id/URL
     (refuses `WL`/`HL` with the unsupported explanation);
   - `import-takeout <takeout-root> [--json]` — YSS-07 registry import (the existing
     `youtube-onboard` file-registry command remains unchanged for compatibility).
3. `youtube-sync` group (wraps YSS-06/08/09):
   - `run [--once] [--source <binding_id>] [--json]` — lease-guarded manual "Sync now";
   - `status [--json]` — the YSS-09 status projection (queue depth, quota, next due, degraded
     sources, last/next sync);
   - `pause [--source <binding_id>]` / `resume [--source <binding_id>]` — global or per-source;
   - `backfill --plan | --execute --confirm-plan <id> [--full-history] [--json]` — YSS-08 gate
     semantics verbatim;
   - `why <video_id> [--json]` — the YSS-09 receipt projection for one item;
   - `doctor [--json]` — the YSS-09 doctor check plus settings effective-value/scope/provenance
     table for every `youtubeSync.*` key (the capability's settings-explain surface).

## Concretely

```
$ python -m app.cli youtube-sources list --json | jq '.[0]'
{"binding_id": "…", "kind": "inbox_playlist", "title": "Mimer Inbox", "enabled": true,
 "interval_seconds": 180, "policy": "acquire_transcript", "last_success_at": "…", "last_error": null}
$ python -m app.cli youtube-sync pause && python -m app.cli youtube-sync status --json | jq .paused
true
```

## Why This Matters

The Mac mini is operated headlessly over SSH; live acceptance, automation, and every runbook step
stand on these commands. Unstable JSON or a secret in output breaks scripts or leaks credentials.

## Acceptance Criteria

- [ ] Every command above exists, supports `--json`, and the JSON shapes are covered by
      golden-shape assertions (stable keys, no incidental fields).
      Verify: `tests/cli/test_youtube_sync_cli.py::test_json_shapes_stable_across_command_family`
- [ ] No command output (human or JSON, success or failure) contains a planted sentinel secret
      from token store, env, or provider fixtures.
      Verify: `tests/cli/test_youtube_sync_cli.py::test_no_secret_in_any_command_output`
- [ ] Exit codes: precondition errors raise `ClickException`; ran-but-failed (degraded sync,
      failed auth poll) exits 1 with reason on stderr; success exits 0.
      Verify: `tests/cli/test_youtube_sync_cli.py::test_exit_code_conventions`
- [ ] `configure --set-inbox` performs the atomic inbox swap; `add-playlist WL` is refused with
      the unsupported explanation.
      Verify: `tests/cli/test_youtube_sync_cli.py::test_set_inbox_swap_and_unsupported_refusal`
- [ ] `doctor` shows effective value, scope, and source provenance for every `youtubeSync.*`
      setting.
      Verify: `tests/cli/test_youtube_sync_cli.py::test_doctor_settings_provenance_table`
- [ ] `run` respects the lease (second concurrent invocation reports lease-held instead of
      double-polling) — asserted at the production lease call site.
      Verify: `tests/cli/test_youtube_sync_cli.py::test_run_lease_guarded_at_call_site`

## How to Verify (Pre-Merge)

- `pytest -q tests/cli/test_youtube_sync_cli.py`
- `pytest -q -m "not pg"`
- `ruff check app tests && mypy app`

## Out of Scope

New business logic (everything wraps YSS-01..09 cores), Companion UI (YSS-11), the existing
`acquire-youtube`/`acquire-replay`/`youtube-onboard` commands (unchanged).

## Related Docs

- `docs/YOUTUBE_SOURCE_SYNC/SOURCE_SYNC_CONTRACT.md` (all sections — the CLI is its operator projection)
- `docs/YOUTUBE_SOURCE_SYNC/OPERATOR_RUNBOOK.md` (every runbook step uses these commands)

## Related GitHub Issues

One issue. TCD hint: Sonnet / medium — thin wrappers over fixed cores with golden-shape tests;
escalate only if the CLI layer starts accreting logic (that's a design smell to push back into
the cores).
