---
name: Bootstrap and Sync Wiring
description: Add make dispatcher-init, make dispatcher-sync, a dispatcher pull CLI command, and a missing-DB guard
task_id: DISPATCHER-ADOPTION-01
source_anchor: docs/DISPATCHER_AGENT_ADOPTION/BOOTSTRAP_AND_SYNC_WIRING.md
parent_capability: Dispatcher Agent Adoption
prerequisites: []
depends_on: []
can_parallelize_with: [COMPLETE_COMMAND.md]
---

# Bootstrap and Sync Wiring

## Purpose

Agents cannot use the dispatcher without a live, populated SQLite DB. Currently nothing initialises or populates the DB as part of normal repo setup. This task wires a `dispatcher pull` CLI command and two `make` targets so a fresh checkout can have a working queue in one command, and so that re-syncing stale queue state is equally simple.

It also adds a guard so that calling any dispatcher command on a missing or uninitialised DB produces a clear error rather than silently creating an empty queue.

## What This Task Does

1. Adds `python -m app.dispatcher pull --repo <owner/repo>` command to `cli.py` — calls `PullSyncAdapter.pull()` against open `agent:ready` issues using the `gh` CLI as the GitHub source, prints a compact sync receipt.
2. Adds `make dispatcher-init` — runs `python -m app.dispatcher init` then `python -m app.dispatcher pull --repo <owner/repo>`.
3. Adds `make dispatcher-sync` — runs `python -m app.dispatcher pull --repo <owner/repo>` only (no re-init).
4. Adds a not-initialised guard: if `dispatcher status --json` shows `db_exists: false`, commands that require a live DB (`next`, `claim`, `queue`, `pull`) exit non-zero with `{"ok": false, "error": "dispatcher not initialised — run: make dispatcher-init"}`.

The `gh`-backed `GitHubIssueSource` implementation lives in `app/dispatcher/sync_github.py` (or a thin wrapper); existing tests must not require `gh` access (offline protocol-based tests stay intact).

## Concretely

```sh
# initialise and populate queue from GitHub on a fresh checkout
make dispatcher-init
# => {"ok": true, "state_dir": "runtime/dispatcher", "db_path": "...", ...}
# => {"ok": true, "upserted": 7, "skipped": 0, "provider": "github"}

# re-sync stale queue without reinitialising
make dispatcher-sync
# => {"ok": true, "upserted": 9, "skipped": 0, ...}

# guard on missing DB
python -m app.dispatcher next --json
# => {"ok": false, "error": "dispatcher not initialised — run: make dispatcher-init"}
# exit code 1

# direct pull command
python -m app.dispatcher pull --repo <owner>/<repo> --json
# => {"ok": true, "upserted": 9, "skipped": 0, ...}
```

## Why This Matters

Without this, every agent in a fresh worktree starts with an empty dispatcher queue. The `next` command returns `{"empty": true}` and the agent falls through to GitHub label scanning — defeating the entire dispatcher. This task is the prerequisite for every other adoption task.

## Acceptance Criteria

- [ ] `python -m app.dispatcher pull --repo <repo> --json` upserts open `agent:ready` issues and prints a sync receipt.
  Verify: `tests/dispatcher/test_cli.py::test_pull_command_upserts_issues`
- [ ] `make dispatcher-init` runs `init` then `pull` and exits 0 on a clean state dir.
  Verify: `tests/dispatcher/test_bootstrap.py::test_make_dispatcher_init`
- [ ] `make dispatcher-sync` runs `pull` only (does not reinitialise schema) and exits 0.
  Verify: `tests/dispatcher/test_bootstrap.py::test_make_dispatcher_sync`
- [ ] `dispatcher next --json` on a missing DB exits 1 with `{"ok": false, "error": "..."}`.
  Verify: `tests/dispatcher/test_cli.py::test_guard_missing_db`
- [ ] `gh`-backed `GitHubIssueSource` implementation exists; offline unit tests remain green.
  Verify: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/dispatcher/`

## How to Verify (Pre-Merge)

```sh
# all dispatcher tests green
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/dispatcher/

# lint and types
ruff check app/dispatcher tests/dispatcher
mypy app/dispatcher

# manual smoke (requires gh auth)
make dispatcher-init
python -m app.dispatcher queue --json
python -m app.dispatcher next --json
```

## Out of Scope

- Scheduling sync on a cron/timer — manual `make dispatcher-sync` is sufficient for MVP adoption.
- Push/write-back to GitHub — pull-only per the contract.
- Multi-worktree shared DB coordination — single worktree use is the MVP target.

## Related Docs

- `docs/AGENT_ISSUE_DISPATCHER.md` — contract and non-goals
- `app/dispatcher/sync_github.py` — PullSyncAdapter and GitHubIssueSource protocol
- `app/dispatcher/cli.py` — existing CLI; `pull` command to be added here

## Related GitHub Issues

One issue. Implement `pull` command in `cli.py`, add `gh`-backed source, add `make` targets, add guard, add tests. All in one PR.
