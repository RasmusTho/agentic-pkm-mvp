---
name: Add Branch Truth Gate
description: Add a mandatory branch-truth check and per-issue worktree mandate to issue-to-code and pr-integration before any commit/push action.
task_id: PIH-02
source_anchor: docs/learning-log.md :: 2026-05-07 — #775
parent_capability: PR_INTEGRATION_HARDENING
prerequisites: []
depends_on: []
can_parallelize_with: [ADD_PLUGIN_LOAD_GUARD]
---

# Add Branch Truth Gate

## Purpose

During PR #796/#775 delivery, commits repeatedly landed on unrelated local branches because edits and commits were run from the shared root worktree where the active branch context had silently changed. This happens in multi-agent parallel work when an agent reuses the root worktree for a PR that is not on the root worktree's branch.

## What This Task Does

1. Adds a mandatory **branch-truth gate** step to `.codex/skills/issue-to-code/SKILL.md` (before any `git add/commit/push` action) that requires:
   - `git branch --show-current` must equal the expected PR head branch name.
   - `git rev-parse HEAD` must equal the head SHA reported by `gh pr view <PR> --json headRefOid`.
   If either check fails, the agent must stop and switch to the correct worktree before continuing.

2. Adds the same gate as a required preflight step to `.codex/skills/pr-integration/SKILL.md` (in its existing "Workspace Isolation Gate" section or as an addition to it), with the additional rule: **for active PRs in multi-agent parallel work, a dedicated per-issue worktree is mandatory for the full issue lifecycle (implementation through review-fix); committing from the shared root worktree for an active PR is prohibited.**

## Concretely

**issue-to-code/SKILL.md** addition (before the first commit action):

```
### Branch-Truth Gate (mandatory before any git add/commit/push)

```bash
EXPECTED_BRANCH="<PR head branch name>"
ACTUAL_BRANCH=$(git branch --show-current)
PR_HEAD_SHA=$(gh pr view <PR_NUMBER> --json headRefOid --jq '.headRefOid')
LOCAL_HEAD=$(git rev-parse HEAD)

if [ "$ACTUAL_BRANCH" != "$EXPECTED_BRANCH" ] || [ "$LOCAL_HEAD" != "$PR_HEAD_SHA" ]; then
  echo "BRANCH-TRUTH GATE FAILED: on $ACTUAL_BRANCH (expected $EXPECTED_BRANCH), HEAD=$LOCAL_HEAD (PR head=$PR_HEAD_SHA)"
  echo "Switch to the correct worktree before committing."
  exit 1
fi
```

Both conditions must pass. If either fails: stop, switch worktree, re-run gate.

For multi-agent parallel work: use a dedicated per-issue worktree (via `git worktree add`) for the full lifecycle — from initial implementation through every review-fix push. Do NOT commit to an active PR from the shared root worktree.
[branch-truth-gate]
```

**pr-integration/SKILL.md** addition (to the existing Workspace Isolation Gate section):

```
Additionally, before any review-fix commit or push:
- Confirm `git branch --show-current` equals the PR head branch.
- Confirm `git rev-parse HEAD` equals the PR `headRefOid` reported by `gh pr view`.
- For multi-agent parallel work, a per-issue worktree is mandatory. The shared root worktree must not be used to commit to an active PR.
[branch-truth-gate]
```

## Why This Matters

Commits landing on the wrong branch are hard to detect until CI fails on the intended PR. A branch-truth gate makes the error loud and immediate, preventing silent drift that causes CI-only failures hours later.

## Acceptance Criteria

- [ ] `.codex/skills/issue-to-code/SKILL.md` contains a branch-truth gate block with both the `git branch --show-current` and `git rev-parse HEAD` equality checks, labeled `[branch-truth-gate]`.
  Verify: doc writeback at `.codex/skills/issue-to-code/SKILL.md :: branch-truth-gate`
- [ ] `.codex/skills/issue-to-code/SKILL.md` states that per-issue worktrees are mandatory for multi-agent parallel work.
  Verify: doc writeback at `.codex/skills/issue-to-code/SKILL.md :: branch-truth-gate`
- [ ] `.codex/skills/pr-integration/SKILL.md` Workspace Isolation Gate section contains the branch-truth confirmation steps and the per-issue worktree mandate, labeled `[branch-truth-gate]`.
  Verify: doc writeback at `.codex/skills/pr-integration/SKILL.md :: branch-truth-gate`

## How to Verify (Pre-Merge)

```bash
grep -n "branch-truth-gate" .codex/skills/issue-to-code/SKILL.md
grep -n "branch-truth-gate" .codex/skills/pr-integration/SKILL.md
grep -n "per-issue worktree" .codex/skills/issue-to-code/SKILL.md
```

All commands must return hits. Confirm the gate block contains both equality checks.

## Out of Scope

- Automating worktree creation — the mandate is doctrinal, not enforced by a script.
- Adding the gate to skills other than `issue-to-code` and `pr-integration`.
- Changing `scripts/agent_workspace_preflight.sh` (that script is out of scope here).

## Related Docs

- [.codex/skills/issue-to-code/SKILL.md](../../.codex/skills/issue-to-code/SKILL.md)
- [.codex/skills/pr-integration/SKILL.md](../../.codex/skills/pr-integration/SKILL.md)
- [docs/learning-log.md](../learning-log.md) (entry 2026-05-07 — #775)
- [docs/PR_INTEGRATION_HARDENING/README.md](README.md)

## Related GitHub Issues

Create one bounded governance issue: `[PR-Integration-Hardening] add-branch-truth-gate: mandate branch check before commit/push`.
Label: `lane:governance`, `agent:ready`, `Status=Ready`.
