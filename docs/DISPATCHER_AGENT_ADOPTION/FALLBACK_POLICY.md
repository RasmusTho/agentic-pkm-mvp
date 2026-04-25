---
name: Fallback Policy
description: Document dispatcher fallback contract in AGENTS.md and issue-to-code skill
task_id: DISPATCHER-ADOPTION-03
source_anchor: docs/DISPATCHER_AGENT_ADOPTION/FALLBACK_POLICY.md
parent_capability: Dispatcher Agent Adoption
prerequisites: [DISPATCHER-ADOPTION-01]
depends_on: [BOOTSTRAP_AND_SYNC_WIRING.md]
can_parallelize_with: []
---

# Fallback Policy

## Purpose

Agents need to know what to do when the dispatcher is unavailable. The dispatcher is a local SQLite file — it can be absent (fresh worktree, deleted state dir, wrong `DISPATCHER_STATE_DIR`), corrupted, or stale. Without a documented fallback, agents either block on a broken tool or skip coordination silently.

This task writes the dispatcher policy and fallback contract into the two authoritative agent instruction surfaces: `AGENTS.md` and `issue-to-code/SKILL.md`.

## What This Task Does

1. Adds a `## Dispatcher policy` section to `AGENTS.md` (under GitHub delivery governance) covering:
   - where the DB lives (`runtime/dispatcher/`), configurable via `DISPATCHER_STATE_DIR`
   - expected agent loop: `status` check → `next` → `claim` → work → `heartbeat` (every ~30 min) → `complete` or `release`
   - TTL: 90 minutes default; agents must heartbeat before expiry
   - fallback rule: if `dispatcher status --json` returns `db_exists: false` or exits non-zero, skip dispatcher and fall back to GitHub-label-only claim (remove `agent:ready`)
   - log the fallback in the PR body with reason
2. Adds a `### Dispatcher integration` subsection to `issue-to-code/SKILL.md` under the "Begin Implementation Work" action, covering:
   - pre-claim: `python -m app.dispatcher status --json` — check `db_exists`
   - if available: `dispatcher next --json` to get candidate, then `dispatcher claim <task_id> --agent <agent_id>`; GitHub label removal is the confirmation step, not the primary claim
   - if unavailable: fall back to `gh issue edit --remove-label agent:ready` (current behaviour unchanged)
   - mid-work: `dispatcher heartbeat <task_id> --agent <agent_id>` approximately every 30 minutes of active execution
   - on closure: `dispatcher complete <task_id> --agent <agent_id>` (or `dispatcher release` if work is abandoned)
   - if any dispatcher command fails during work (non-zero exit): log it, continue with GitHub-only state, do not retry in a loop

No new code in this task — docs-only. Uses the governance lane because it changes agent workflow instruction surfaces.

## Concretely

After this task, an agent running `issue-to-code` does:

```sh
# 1. pre-claim check
python -m app.dispatcher status --json
# => {"ok": true, "db_exists": true} → proceed with dispatcher
# => {"ok": false} or db_exists: false → fall back to gh label only

# 2. dispatcher-first claim
python -m app.dispatcher next --json          # get candidate task
python -m app.dispatcher claim github-issue-614 --agent claude-worktree-abc --json
gh issue edit 614 --remove-label agent:ready  # confirmation

# 3. mid-work heartbeat (~every 30 min)
python -m app.dispatcher heartbeat github-issue-614 --agent claude-worktree-abc --json

# 4. closure
python -m app.dispatcher complete github-issue-614 --agent claude-worktree-abc --json
```

Fallback (dispatcher unavailable):
```sh
gh issue edit 614 --remove-label agent:ready  # unchanged current behaviour
# log in PR body: "Dispatcher unavailable (db_exists: false) — used GitHub-label-only claim"
```

## Why This Matters

Without explicit fallback policy, agents either hard-fail on a missing DB (blocking work) or call both claim paths inconsistently (leaving ghost leases or dangling labels). Explicit fallback preserves single-agent delivery unblocked while multi-agent lease coordination remains the happy path.

## Acceptance Criteria

- [ ] `AGENTS.md` contains a `## Dispatcher policy` section under GitHub delivery governance with: DB location, agent loop, TTL/heartbeat cadence, fallback rule, and PR-body log instruction.
  Verify: doc writeback at `AGENTS.md :: dispatcher-policy`
- [ ] `issue-to-code/SKILL.md` contains a `### Dispatcher integration` subsection in the "Begin Implementation Work" action with: status check, dispatcher-first claim, fallback path, heartbeat cadence, and closure call.
  Verify: doc writeback at `.codex/skills/issue-to-code/SKILL.md :: dispatcher-integration`
- [ ] Both doc sections are internally consistent: same TTL (90 min), same heartbeat cadence (~30 min), same fallback trigger (`db_exists: false` or non-zero exit).
  Verify: human review — cross-read both sections for consistency before merge

## How to Verify (Pre-Merge)

```sh
# docs lint if available
python scripts/docs_guard.py 2>/dev/null || echo "no docs guard"

# spot-check consistency
grep -A 30 "dispatcher-policy" AGENTS.md
grep -A 40 "dispatcher-integration" .codex/skills/issue-to-code/SKILL.md
```

## Out of Scope

- Changing the GitHub-label fallback implementation — it already exists and works.
- Adding enforcement/automation for the dispatcher call — adoption evidence is sufficient for MVP.
- Documenting future dispatcher modes (service, MCP) — not in scope.

## Related Docs

- `AGENTS.md` — builder-agent canonical instruction file
- `.codex/skills/issue-to-code/SKILL.md` — implementation pickup skill
- `docs/AGENT_ISSUE_DISPATCHER.md :: Agent Interaction Contract` — canonical loop definition

## Related GitHub Issues

One issue. Governance lane (no code changes). Docs-only edits to `AGENTS.md` and `issue-to-code/SKILL.md`. One PR.
