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
closed-unmerged pull request, frozen source SHA, archive ref, owner, governing Issue
(or explicit no-Issue lane), successor, retention class, review trigger, and explicit
retain state. Candidate input has one exact schema; disposition metadata is never
mutation authority. The entrypoint obtains repository, pull-request, protected-target,
lifecycle-registry, and dispatcher authority itself and rereads all of it immediately
before archive publication and immediately before source deletion. Any drift stops the
batch before later candidates are touched.

Repository identity is the live GitHub REST repository ID and canonical full name plus
exactly one effective `origin` fetch URL and one effective push URL. HTTPS fetch and
GitHub SSH push forms may differ, but both must identify that REST repository. The
captured literal push URL—not the mutable remote name—is passed to every `ls-remote`
and `push`; the fetch URL is used to obtain the exact source object. Every candidate PR
must freshly be closed, unmerged, same-repository, and at the named full head ref and
SHA. Protected target `#4728` is resolved as a closed Issue and must not be fabricated
as a pull head; `#4813` is resolved as a closed-unmerged pull request and protects its
number, full head ref, and head SHA. Lookup, kind, repository, or shape ambiguity is a
batch-wide refusal.

Lifecycle authority comes from the generation-bound registry under its kernel lock.
Candidate branch, live candidate path, and prior-binding records receive complete
semantic and live-generation validation; an unrelated record with sufficient branch
and prior-binding identity does not make old unavailable checkout state a global
cleanup dependency. Missing or corrupt registry state, identity-ambiguous rows, and
relevant malformed, mismatched, unavailable, live, or prior-path binding evidence
preserve the source.

Dispatcher authority ignores dispatcher path environment overrides and always resolves
the repo-common production SQLite database from Git's primary worktree. Each optimistic
snapshot exhaustively reads every task and every lease, including orphan leases with no
task. Candidate Issue, PR, ref, branch, and lifecycle path identity is classified before
an unrelated expired task/lease disagreement is evaluated. Missing canonical state,
identity-ambiguous or relevant malformed rows, missing relevant referenced leases,
relevant released/current-task disagreement, changed census, or any live relevant task
or orphan resource claim fails closed. These short snapshots never hold lifecycle or
SQLite locks across REST or Git network I/O.

Receipts live under the repository Git common directory at
`git-hygiene/targeted-remote-cleanup/v1/`, keyed by
`sha256("v1\\0" + repository-id + "\\0" + full-source-ref)`. The resource key
deliberately excludes disposition and SHA so a rebinding attempt collides with and is
rejected by the existing record. Persistent per-resource files use non-blocking kernel
`flock`; filenames are never unlinked as ownership signals. Prepared and completed
receipts reject symlinks, duplicate JSON keys, unknown fields, wrong identity or
resource key, invalid states, and completed-to-prepared regression. Every transition
uses a mode-0600 temporary file, complete write and file `fsync`, atomic replace, then
directory `fsync`.

The archive ref is deterministically derived from repository ID, full source ref, and
frozen source SHA. Archive creation uses an expected-absence remote CAS, reads the exact
SHA back, and durably records `prepared` before source deletion. Source deletion uses a
fully qualified expected-old-SHA CAS and must be followed by source-absence plus
exact-archive readback before `completed` is durable. A missing receipt plus an already
absent source is never adoptable: only a matching `prepared` receipt loaded from disk
before observing absence authorizes crash recovery. A completed receipt is monotonic
and idempotent only while the same live ref facts still agree. This slice never deletes
an archive ref.

Archive refs are retained by default. `review_at` is only a review trigger for
`safety_archive` and `quarantine`; elapsed time never authorizes archive deletion,
and a missing or non-explicit discard receipt remains a retain decision.

This document is `scripts/git_hygiene.py`'s paired temporal-owner contract.
Update it whenever the preflight inputs, janitor preservation rules, cleanup
authority, or command behavior changes. Focused executable coverage lives in
`tests/ops/test_git_hygiene.py`; branch/worktree publication callers also use
`scripts/agent_workspace_preflight.sh`.
