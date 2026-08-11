State: Development reference. Not an auto-loaded instruction file.
Owner: Builder System governance

# Git Hygiene Contract

`scripts/git_hygiene.py` provides the local safety checks and conservative
cleanup planning used by concurrent builder workflows. It is Builder System
tooling, not a Product/runtime control plane and not an authority for GitHub
Issue or pull-request lifecycle truth.

## Preflight

The `preflight` command is read-only. It checks the working tree, in-progress
Git operations, expected branch and worktree identity, the remote base branch,
and active lease conflicts before a local mutation. Dedicated worktrees use
the remote base as publication authority, so a stale shared local base ref is
advisory only when the dedicated `HEAD` already contains the remote head.

## Janitor

The `janitor` command defaults to report-only planning. It identifies stale
merged branches, orphaned worktrees, old stashes, and prune candidates while
preserving dirty, locked, unregistered, active, replaced-generation, and
orphaned lifecycle state. Apply mode is intentionally narrow: it may reclaim
only registered, expired, clean, unlocked worktrees whose current path,
branch, head, generation marker, lease state, and merge/closure eligibility
all agree. It records a generation-bound pending removal before Git removal
and retires that generation only after the removal succeeds.

Branch deletion is a separate irreversible step. The janitor rechecks both
the path and branch lease identities immediately before deletion and retains
prior path-to-branch bindings when a path is reused. A report, missing record,
or missing worktree is never evidence that cleanup is authorized.

This document is `scripts/git_hygiene.py`'s paired temporal-owner contract.
Update it whenever the preflight inputs, janitor preservation rules, cleanup
authority, or command behavior changes. Focused executable coverage lives in
`tests/ops/test_git_hygiene.py`; branch/worktree publication callers also use
`scripts/agent_workspace_preflight.sh`.
