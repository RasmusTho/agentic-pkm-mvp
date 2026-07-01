# GitHub API Exhaustion Runbook

State: Active runbook for diagnosing and recovering from GitHub API rate-limit exhaustion (kill switch, observability).

## overview

This runbook covers diagnosis and recovery when the system approaches or
reaches the GitHub API rate limit (5 000 requests/hour on the shared REST
token, lower for GraphQL).

Source: `docs/audits/GITHUB_API_EXHAUSTION_2026-06-29.md :: GHAPI-H3`

---

## Symptoms

| Signal | Where to look |
|--------|--------------|
| Kill switch active warning in logs | `logs/github_api_calls.jsonl` — field `"direction": "read"`, warning line in structured log |
| `rate_limit_remaining` below 200 | `logs/github_api_calls.jsonl` or sync-meta DB row `_sync_meta_github` |
| `gh` CLI returning HTTP 403 / 429 | stderr of the process, or `error` field in call log |
| Hourly scan skipped | `kill_switch_active: true` in the sync-meta `extra` blob |

---

## Diagnosis

### 1. Check current remaining quota

```bash
gh api rate_limit | python3 -m json.tool
```

The `rate.remaining` field shows current REST quota.

### 2. Read the call log

```bash
tail -50 logs/github_api_calls.jsonl | python3 -m json.tool
```

Look for entries with `"remaining"` near zero or `"error"` fields.

### 3. Read the last sync-meta record

```sql
SELECT sync_state FROM tasks WHERE task_id = '_sync_meta_github';
```

The `extra.rate_limit_remaining` and `extra.kill_switch_active` fields reflect
the state at the last successful pull.

---

## Kill switch behaviour

When `rate_limit_remaining` falls below the threshold (default 200, env var
`GITHUB_RATELIMIT_KILL_THRESHOLD`):

- The full open-issues scan is **skipped** — `kill_switch_active: true`
  recorded in sync-meta. (When it does run, it fetches bounded cursor pages,
  not one `--limit 1000` burst — GHAPI-M3.)
- The essential `agent:ready` label query still runs (read-only, bounded cost).
- Stale-ready reconcile is disabled until quota recovers.
- `scripts/reconcile_project_status.py` skips before project discovery with a
  `github.budget.skip` receipt carrying `kill_switch_active: true` (GHAPI-C2).
- `app/dispatcher/poll_backoff.py::gh_graphql` (CI/Codex wait loops) refuses to
  issue the call and raises `GitHubKillSwitchActive` (GHAPI-H1).

This is a **fail-safe** design: uncertain state allows essential reads and
disables expensive scans only.

The decision itself lives in one place:
`app/dispatcher/github_call_logger.py::is_kill_switch_active` is the shared
enforcement point — new GitHub-API consumers must wire through it instead of
adding parallel gates (#2746).

---

## Recovery

### Option A — Wait for quota reset

GitHub rate limits reset every hour at the UTC time shown in
`x-ratelimit-reset`. No action needed; the next sync cycle will re-enable the
full scan automatically.

### Option B — Raise the threshold temporarily

If you need scanning now and quota is partially recovered:

```bash
export GITHUB_RATELIMIT_KILL_THRESHOLD=50
# Restart the sync process / scheduler
```

Restore the default (200) once quota is healthy.

### Option C — Use a dedicated token

If the shared token is exhausted by other consumers, configure a dedicated
`GITHUB_TOKEN` for the sync process with its own quota pool.

---

## Pre-exhaustion alert

A `WARNING` log line is emitted by `app/dispatcher/github_call_logger.py`
whenever a call records `remaining < threshold`:

```
github_call_logger: rate limit low remaining=N threshold=200 — kill switch active
```

Route this to your monitoring stack (e.g. grep on `kill switch active`).

---

## Contacts / escalation

Operator: check `docs/OPERATIONS.md` for on-call rotation.
Audit source: `docs/audits/GITHUB_API_EXHAUSTION_2026-06-29.md`
