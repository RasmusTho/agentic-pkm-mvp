---
name: Complete Command
description: Add dispatcher complete as a clean terminal signal for agents finishing a task
task_id: DISPATCHER-ADOPTION-02
source_anchor: docs/DISPATCHER_AGENT_ADOPTION/COMPLETE_COMMAND.md
parent_capability: Dispatcher Agent Adoption
prerequisites: []
depends_on: []
can_parallelize_with: [BOOTSTRAP_AND_SYNC_WIRING.md]
---

# Complete Command

## Purpose

The dispatcher CLI has `release` and `update --status completed` but no single `complete` command. Agents need one unambiguous terminal call to close out a task after a PR merges. Without it, the closure step in `issue-to-code` would require two commands and would be easy to skip or miscall.

## What This Task Does

1. Adds `python -m app.dispatcher complete <task_id> --agent <id>` to `cli.py`.
2. `complete` must: verify the task exists and is held by `agent_id`; release the lease (set `released_at`, `release_reason=completed`); set task `status=completed`; emit `task.completed` event.
3. `complete` is terminal — a completed task is not re-queued by `next`.
4. Adds `queue.complete()` function in `queue.py` (parallel to `block`/`release` in `leases.py`).

## Concretely

```sh
python -m app.dispatcher complete github-issue-614 --agent claude-worktree-abc --json
# => {"ok": true, "task": {"task_id": "github-issue-614", "status": "completed", ...}}

# completed task does not appear in next
python -m app.dispatcher next --json
# => {"ok": true, "task": <next uncompleted task or null>}

# completed task appears in queue summary under by_status.completed
python -m app.dispatcher queue --json
# => {"ok": true, "total": N, "by_status": {"completed": 1, "ready": M, ...}, ...}
```

## Why This Matters

Agents closing out a task need one unambiguous command. `update --status completed` leaves the lease in place. `release` sets status back to `ready`. Neither is the correct terminal signal. Without `complete`, every agent closure either leaves a dangling lease or re-queues a finished task.

## Acceptance Criteria

- [ ] `dispatcher complete <task_id> --agent <id>` sets status to `completed`, releases the lease, and emits `task.completed`.
  Verify: `tests/dispatcher/test_cli.py::test_complete_command`
- [ ] Completing a task by a non-holder agent exits 1 with `{"ok": false, "error": "..."}`.
  Verify: `tests/dispatcher/test_cli.py::test_complete_wrong_holder`
- [ ] `dispatcher next` does not return a completed task.
  Verify: `tests/dispatcher/test_cli.py::test_next_skips_completed`
- [ ] `task.completed` event appears in `dispatcher events --json`.
  Verify: `tests/dispatcher/test_cli.py::test_complete_event_emitted`

## How to Verify (Pre-Merge)

```sh
pytest -q tests/dispatcher/
ruff check app/dispatcher tests/dispatcher
mypy app/dispatcher
```

## Out of Scope

- Reopening or uncompleting tasks — not in MVP scope.
- Cascade actions on completion (e.g. auto-projecting GitHub Project status) — projection is optional and not in the hot path.

## Related Docs

- `docs/AGENT_ISSUE_DISPATCHER.md :: Status Model` — `completed` is listed as a terminal status
- `app/dispatcher/queue.py` — `block` is the closest analogue; `complete` follows the same pattern
- `app/dispatcher/cli.py` — `complete` subcommand added here

## Related GitHub Issues

One issue. Add `queue.complete()`, add `complete` subcommand in `cli.py`, add tests. One PR.
