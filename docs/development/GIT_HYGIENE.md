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

Remote branch disposition is not a broad-janitor action. The bounded
`targeted_remote_cleanup` production entrypoint accepts at most five caller-supplied
candidates and requires each to bind the repository, fully qualified source ref,
frozen source SHA, archive ref, owner, governing Issue (or explicit no-Issue lane),
successor, retention class, review trigger, and explicit retain/discard state. It
publishes and reads back the archive at the frozen SHA, writes a durable `prepared`
receipt, and only then uses an expected-old-SHA remote CAS delete. It completes the
receipt only after source absence and exact archive-SHA readback; a retry is valid
only when the same identity receipt and both live refs agree. Any drift stops the
batch before later candidates are touched.

The entrypoint canonicalises `origin` to the caller's repository identity and requires
fresh candidate authority with empty lifecycle/lease conflicts plus the live protected
heads for PR #4728 and #4813. Receipt ownership is exclusive per identity digest;
prepared and completed transitions use write+fsync, atomic replace, and directory fsync.
Batch archive refs are preflighted for collisions before any remote side effect.

Archive refs are retained by default. `review_at` is only a review trigger for
`safety_archive` and `quarantine`; elapsed time never authorizes archive deletion,
and a missing or non-explicit discard receipt remains a retain decision.

This document is `scripts/git_hygiene.py`'s paired temporal-owner contract.
Update it whenever the preflight inputs, janitor preservation rules, cleanup
authority, or command behavior changes. Focused executable coverage lives in
`tests/ops/test_git_hygiene.py`; branch/worktree publication callers also use
`scripts/agent_workspace_preflight.sh`.
