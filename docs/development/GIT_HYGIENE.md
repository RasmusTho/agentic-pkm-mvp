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
before archive publication. The final source mutation uses the bounded linearization
section described below. Any drift stops the batch before later candidates are touched.

Repository identity is the live GitHub REST repository ID and canonical full name plus
exactly one effective `origin` fetch URL and one effective push URL. HTTPS fetch and
GitHub SSH push forms may differ, but both must identify that REST repository. The
REST client fixes every authority request to `github.com` and gives each invocation a
fresh mode-0700 empty `GH_CONFIG_DIR`. Ambient gh/XDG config paths, host/repository/API
selectors, alternate HTTP sockets, and enterprise tokens are absent from that process.
Only `GH_TOKEN` or `GITHUB_TOKEN` authentication for github.com is normalized into the
clean call; when environment auth is absent, `gh auth token --hostname github.com`
performs a local credential lookup and only its single token value crosses the boundary.
No other gh config is copied, and temporary config is removed after the call. The
captured literal push URL—not the mutable remote name—is passed to
every `ls-remote` and `push`; the fetch URL is used to obtain the exact source object.
Every candidate PR
must freshly be closed, unmerged, same-repository, and at the named full head ref and
SHA. The candidate's Issue/no-Issue routing fields are not authority: the live PR body
is parsed with the same canonical governance classifier used by publication and
verification. An issue-backed candidate must match the body's unique positive
`Governing-Issue`; an issue-free candidate must match exactly one authenticated
`docs-authoring`, `governance`, or `direct-repair` lane. Missing, malformed, duplicate,
ambiguous, or mismatched contract identity refuses cleanup, and its exact PR-body digest
plus resolved Issue/lane identity is part of the durable receipt identity. Protected
target `#4728` is resolved as a closed Issue and must not be fabricated
as a pull head; `#4813` is resolved as a closed-unmerged pull request and protects its
number, full head ref, and head SHA. Lookup, kind, repository, or shape ambiguity is a
batch-wide refusal.

Every Git operation that derives repository, lifecycle, dispatcher, receipt-store, or
remote transport authority starts from the explicit `cwd` with ambient repository
redirection removed. In particular, `GIT_DIR`, `GIT_WORK_TREE`, `GIT_COMMON_DIR`,
alternate object/index/namespace paths, and related discovery context cannot redirect
cleanup from repository A into repository B. Intentional Git configuration and
transport configuration remain available; only local repository-context selectors are
sanitized. The already-captured literal fetch and push URLs remain the network targets
for the destructive sequence.

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
relevant task/lease/resource disagreement, changed census, or any live relevant task
or orphan resource claim fails closed. Candidate resources include canonical
`issue:<positive governing_issue>` identities, so an orphan Issue lease protects the
source even without a task row. Relevant `ready`, `review`, `claimed`, `in_progress`,
`blocked`, or `backlog` task state preserves the source even after its pickup lease is
released or expires, because that canonical state can still represent retained or
resumable work. The dispatcher producer's only positively terminal stored status is
`completed`; every unknown or legacy raw status remains ambiguous and fails closed. A
task-referenced lease must exist, be uniquely referenced, carry the canonical
`issue:<task.issue_number>` resource, and have a nonempty `claimed_by` exactly equal to
the lease holder. Missing or mismatched holder identity fails closed even when the lease
is released or expired. No canonical legacy contract authorizes a terminal `completed`
row to retain `lease_id`, so every such shape fails closed, including a matching holder.
The canonical claim-then-complete transition clears both `lease_id` and `claimed_by` but
intentionally retains the historical `lease_expires_at`; that exact shape is accepted
only after the exhaustive census proves there is no relevant live task or orphan resource
lease. Narrow legacy
blank-repository history is ignored only
when it has the current terminal `completed`/`blocked` or sync-meta shape, has no
candidate Issue/PR/ref/branch/path resource, and has no live or unreleased lease. A
blank row that is live, unreleased, relevant, malformed beyond that bounded legacy
shape, or otherwise cannot prove irrelevance remains fail-closed. These short snapshots
remain unlocked during planning and archive preparation; the bounded final source-CAS
section below is the deliberate exception that fences canonical local writers.

The blank-repository compatibility path calls the same task/lease relationship validator
as repository-bound tasks. Any retained `lease_id` therefore requires one exact lease,
one canonical Issue resource, one unique task reference, exact nonempty holder identity,
and a complete inactive relationship; `completed` plus retained lease remains
noncanonical and fails closed even with a matching holder. A canonical `completed` row
with null lease/holder and an optional valid historical expiry remains admissible when it
is provably unrelated.

Receipts live under the repository Git common directory at
`git-hygiene/targeted-remote-cleanup/v1/`, keyed by
`sha256("v1\\0" + repository-id + "\\0" + full-source-ref)`. The resource key
deliberately excludes disposition and SHA so a rebinding attempt collides with and is
rejected by the existing record. Persistent per-resource files use non-blocking kernel
`flock`; filenames are never unlinked as ownership signals. Prepared, compensated, and completed
receipts reject symlinks, duplicate JSON keys, unknown fields, wrong identity or
resource key, invalid states, completed regression, and compensated-to-prepared regression. Every transition
uses a mode-0600 temporary file, complete write and file `fsync`, atomic replace, then
directory `fsync`.

The archive ref is deterministically derived from repository ID, full source ref, and
frozen source SHA. Archive creation uses an expected-absence remote CAS, reads the exact
SHA back, and durably records `prepared` before source deletion. Source deletion uses a
fully qualified expected-old-SHA CAS inside one final-authority critical section. The
canonical lock order is dispatcher SQLite writer reservation (`BEGIN IMMEDIATE`) first,
then lifecycle-registry `flock`. Dispatcher claim/complete producers use the same SQLite
writer serialization, and lifecycle register/heartbeat producers use the same registry
lock; the normal claim-then-register workflow never nests these locks in the opposite
order. The section is bounded to final local authority rereads, one source CAS, immediate
ref readback, a final external/local authority reread, and the receipt transition. It is
never held across batch planning, archive creation, or long-running validation.

GitHub PR, Issue, body-contract, and protected-target authority cannot join the local
lock domain. Cleanup reads that authority immediately before acquiring the local fences,
then reads it again after the delete CAS while both local fences remain held. Source
absence, exact archive identity, a clear final external reread, and a clear fenced local
reread are all required before `completed` becomes durable. A dispatcher claim or
lifecycle registration that begins after the locks are released is new authority after
the completed deletion linearization; a writer that started earlier cannot become live
until the critical section exits.

If external drift or any local preservation signal appears after deletion, cleanup
restores the exact archived object with an expected-absence source CAS, verifies both
source and archive at the frozen SHA, records durable `compensated`, and stops the batch.
It never overwrites a concurrently recreated or advanced source. Restore-CAS or readback
ambiguity is a hard failure that leaves the archive retained and the receipt non-completed.
Crash retry also recognizes a candidate-bound prepared/compensated receipt whose live PR
contract has since changed: it restores an absent source or verifies the already-restored
exact source, persists `compensated` under the same fences, and refuses advanced source or
archive drift. A missing receipt plus an already absent source is never adoptable: only a
matching `prepared` receipt loaded from disk before observing absence authorizes ordinary
crash recovery. A completed receipt is monotonic and idempotent only while the same live
ref facts still agree. This slice never deletes an archive ref.

Archive refs are retained by default. `review_at` is only a review trigger for
`safety_archive` and `quarantine`; elapsed time never authorizes archive deletion,
and a missing or non-explicit discard receipt remains a retain decision.

This document is `scripts/git_hygiene.py`'s paired temporal-owner contract.
Update it whenever the preflight inputs, janitor preservation rules, cleanup
authority, or command behavior changes. Focused executable coverage lives in
`tests/ops/test_git_hygiene.py`; branch/worktree publication callers also use
`scripts/agent_workspace_preflight.sh`.


## Rescue-backed serial maintenance policy

Each destructive phase starts with a new, private rescue snapshot. The snapshot
is recovery evidence, never PR, lease, lifecycle, or discard authority. Run:

```bash
python3 scripts/git_hygiene.py --cwd /absolute/repository rescue-snapshot \
  --destination /absolute/new-timestamped-rescue-directory
```

The command refuses an existing destination, captures refs, worktrees and stash
identities, includes reflog objects in the bundle, runs `git bundle verify`, and
unbundles into an empty repository to check all captured ref, worktree HEAD and
stash objects. A second inventory must match before `manifest.json` is written.
Snapshot failure leaves incomplete files for diagnosis and forbids cleanup. A
bundle does not preserve dirty working files, untracked files, Git configuration,
leases or lifecycle authority. Dirty or unavailable targets must remain untouched.
Save fresh GitHub, dispatcher and lifecycle readbacks alongside the manifest;
those observations must be refreshed again at each mutation boundary.

Recovery is additive: verify the bundle checksum against the manifest, unbundle
into a new empty repository, and recover the required object there first. Use an
expected-absence ref creation when restoring an absent source ref. Never overwrite
an advanced ref, recreate a worktree at a reused path, or import historical lease
or lifecycle state as current authority. Older stashes are recoverable by the SHA
in the manifest; positional stash selectors are not stable identities.

The public CLI rejects apply without both exact selectors before reading evidence
or invoking cleanup. Local maintenance uses only `agent_worktree.py janitor --mode apply` with both
`--target-worktree` and `--target-generation`. Each phase targets one exact
registered identity, including a removed-generation branch continuation. Preserve
missing generation, dirty/unavailable state, unknown merge state, active lease,
open/draft PR, protected branch and current/root worktree. Require a fresh matching
PR head and live dispatcher readback; rereading an old JSON file is insufficient.
Stop on drift, take a new readback after each phase, and do not use broad apply,
`branch -D`, mass pruning or directory removal. The low-level compatibility API
is not a replacement for these operational gates.

The separate remote/archive/stash policy is:

| Artifact | Allowed disposition | Additional authority |
| --- | --- | --- |
| Remote branch | Existing bounded `targeted_remote_cleanup`, only after the caller proves a fresh verified rescue bundle | Its authenticated PR/body, dispatcher, lifecycle, archive CAS, final readback and compensation contract above remains mandatory. |
| Archive/rescue ref | Retain by default | Deletion requires an explicit object-bound owner discard decision, successor/retention disposition, verified independent rescue coverage, fresh authority, expected-old-SHA CAS and post-effect readback. The bounded legacy local archive entrypoint below is available; modern remote archive receipts remain retained. |
| Stash | Retain by default | Deletion requires an explicit owner decision for the exact stash SHA and contents, verified independent rescue coverage, and exclusive coordination with stash writers. Age, message markers, or positional indices never authorize deletion. Only the exact complete-stack entrypoint below is enabled; mixed active/inactive stacks remain retained. |

The remote function does not itself create or validate the rescue bundle. This is
an external caller precondition: absent or stale proof means retain and do not
invoke the function.

These are separate maintenance phases. Missing discard authority means retain,
not permission to infer low value. Remote merged-branch and archive/stash deletion
extensions require their own bounded implementation and verification before use.
The daily automation remains unchanged and retains its snapshot, lease,
exact-target and stop-on-drift gates.

## Bounded repository probes

`status` and `merge-base` probes have a ten-second subprocess deadline. Status
failure or timeout yields unavailable worktree state. Merge-base exit codes other
than 0/1, launch failure or timeout yield unknown merge state, with no fallback to
PR-based deletion eligibility. Planning continues with the remaining candidates.
Preflight fails closed when base ancestry is unavailable. Focused coverage lives
in `tests/ops/test_git_hygiene.py`, including recovery of older stashes, snapshot
drift, stale lifecycle bindings and probe failure with closed or merged PRs.


## Explicit retirement of inactive legacy archives

An explicit owner decision may prefer retaining an independent verified bundle
and discarding inactive Git artifacts over spending development effort integrating
old work. That decision does not authorize deleting active work or protected refs.
`retire_legacy_archive_refs` implements only the first bounded phase: caller-supplied
exact `refs/archive/git-hygiene/*` names and expected object IDs. No branch, stash,
worktree, remote ref, modern archive-receipt namespace or wildcard is accepted.
The nonempty owner decision is recorded in the receipt; callers must possess actual
user authority, not synthesize it from the argument's presence.

The phase creates its own fresh verified rescue snapshot and requires every target
to match the captured manifest. A missing lifecycle registry, unknown activity
shape, source SHA drift or GitHub failure refuses progress. Each batch contains at
most 25 named refs and uses an atomic expected-old-SHA Git ref transaction. GitHub
open-PR heads, every linked worktree HEAD (including stale/unregistered paths), live dispatcher resource leases and
direct artifact references in resumable dispatcher tasks protect targets. The
canonical dispatcher writer reservation is acquired before the lifecycle registry
lock. Fresh authority is read before every batch; open-PR state is also reread
before releasing the fences after deletion. External drift triggers an atomic
expected-absence restore of the just-deleted batch and stops the phase. It never
overwrites a racing recreated ref. Failed compensation records `recovery_required`
and the exact affected refs for additive recovery from the independent bundle.

A private durable `retirement.json` records the explicit decision, exact targets,
verified snapshot path, retained artifacts, completed batches and authority digests.
A crash may leave a prepared receipt and absent refs: preserve that receipt and the
bundle, reconcile exact live refs before any retry, and restore only absent refs
with expected-absence creation if recovery is required. Never infer completion
from absence. The receipt and independent bundle replace the redundant local
archive ref as recovery evidence; they do not replace live lifecycle authority.
The daily automation is unchanged and cannot infer this explicit owner decision.


## Explicit retirement of a frozen inactive stash stack

`retire_inactive_stash_stack` accepts the exact ordered SHA list of one complete
stash stack plus the explicit owner discard decision. It creates and verifies a
new independent rescue snapshot, verifies every stash object is covered, and saves
the raw reflog with its SHA256. Current open-PR branches, live lifecycle branches,
linked worktree HEADs and explicit live/resumable resource bindings preserve the
whole stack. It never applies or merges old changes into the current checkout.

Deletion is one native Git expected-old-OID ref transaction for `refs/stash`.
A command-scoped private `reference-transaction` prepared hook verifies the exact
single delete and the frozen raw reflog digest while Git holds the ref lock.
Changed top, reordered/edited reflog or concurrent additions therefore abort before
commit. This replaces positional `stash drop` and blanket `stash clear`; the
operator selects an exact immutable stack and the hook verifies its identity.
The command does not change persistent repository configuration or hook files.

The dispatcher writer reservation and lifecycle lock cover the final activity
check and Git transaction. After commit, both ref and reflog must be absent and
GitHub activity must still agree before the durable receipt becomes completed.
If a new writer creates a stash after commit, preserve the new stack and record
`recovery_required`; never delete it or overwrite its reflog with historical data.
The independent bundle and raw reflog remain retained for additive recovery.
This owner-authorized entrypoint does not change the daily automation's policy.


## Owner-authorized retirement of inactive local branches

When the owner explicitly chooses to discard inactive work rather than integrate
it, `retire_inactive_local_branches` accepts exact `refs/heads/*` and expected SHAs.
This is a separate operator disposition path, not a relaxation of automatic
janitor eligibility. It creates a fresh verified bundle and uses the same serial
expected-old-SHA transactions and compensation as legacy archive retirement.
No `branch -D`, merge, reset, checkout switch or worktree removal is performed.

The source ref must be neither protected nor checked out anywhere. Current open
PR branches, linked worktree HEADs, live registrations, branch/Issue/worktree-path
leases (including historical path bindings), and the designated protected targets
remain retained. A complete locked lifecycle snapshot is frozen and reread before
every batch; any generation/record drift stops progress. Relevant current/prior
bindings must pass the canonical lifecycle record validator; malformed generations
remain retained. This operator path also retains all branches while any canonical
dispatcher lease is live. Missing historical branch
bindings are recorded as absent, never reconstructed or fabricated. For a branch
with no checkout, this explicit owner discard decision plus frozen ref identity
and live inactivity evidence supplies disposition authority; absence alone never
authorizes automatic cleanup. Existing worktrees still require their separate
identity, generation, cleanliness and activity checks.

The durable receipt captures the owner decision and verified snapshot for every
exact branch, including unmerged branches. Its recovery path is additive object
recovery from the bundle, not an obligation to resolve old merge conflicts. This
operator path does not change or grant authority to the daily automation.

## Owner-authorized retirement of registered inactive worktrees

`retire_inactive_worktrees` accepts up to 25 exact path, branch, HEAD and existing
lifecycle-generation tuples and an explicit owner decision to discard inactive
work without integration. A new verified bundle covers the entire phase. Each
checkout is removed serially using `git worktree remove` without force, with fresh
GitHub state, canonical dispatcher serialization, and the existing lifecycle
pending/removal guard. A known unmerged HEAD may be retired under this decision;
a timed-out or invalid merge probe remains a stop. The branch itself remains for
a separate branch-retirement phase.

Root/current/protected checkouts, open PRs, live leases, directly referenced
resumable tasks, dirty or unavailable checkouts, locks and invalid, missing or
changed generations remain protected. This path does not register old worktrees
or fabricate historical ownership. After each removal, it verifies path and Git
registration absence and rereads GitHub before continuing. Any post-effect drift
stops the phase with recovery-required evidence; the branch and verified bundle
retain the exact HEAD, and recovery must never overwrite a recreated path.
The daily automation does not inherit this explicit owner disposition.

## Owner-authorized retirement of closed-PR remote heads

`retire_inactive_remote_branches` is a separate explicit-disposition entrypoint
for up to 500 exact ref/SHA/PR tuples. It accepts closed PRs, including merged PRs,
only when the authenticated head repository, ref and SHA match. Open/draft PRs,
protected heads, checked-out or live lifecycle bindings, malformed relevant
generations, resumable references and any live canonical dispatcher lease remain
retained. Remote heads without a matching closed PR are outside this policy.
The existing `targeted_remote_cleanup` contract remains unchanged.

A new independent bundle must contain every exact target SHA before any effect.
The phase records the repository identity, bundle checksum and exact disposition
in its own `remote_owner_retirement.v1` receipt. Each remote deletion is a separate
serial batch using expected-old-SHA `--force-with-lease` against the authenticated
literal push URL. Canonical dispatcher and lifecycle locks remain held through
fresh PR, repository, protected-target and open-head checks, deletion and readback.
The complete lifecycle snapshot must stay unchanged throughout the phase.

On post-delete drift, compensation verifies the bundle checksum, unbundles into a
new temporary bare repository and restores only an absent remote source with
expected-absence CAS. A concurrently recreated head is never overwritten. Failure
persists `recovery_required`. A retry using the same snapshot directory validates
the exact receipt identity and compensates a pending deletion before returning;
it never resumes deletion using an old snapshot. A new phase requires a new
snapshot. This path adds no remote archive refs and grants no new authority to
the daily automation.

## Owner-authorized retirement of inactive local auxiliary refs

`retire_inactive_auxiliary_refs` reuses the verified-snapshot and serial CAS/readback
mechanism with a closed namespace allowlist: `refs/codex/snapshots/<40-hex>`,
`refs/codex/pr-<number>-merge`, and children of `refs/review`, `refs/tmp`,
`refs/recovered-stash`, `refs/closure-a`, `refs/codex-tmp`, `refs/merge_validation`
and `refs/pr`, plus the historical exact ref `refs/pr_862_head`. Callers must
supply every exact ref and expected SHA; no glob deletion is performed.

Explicit owner disposition is mandatory. Every linked HEAD, current open-PR head,
review ref naming an open PR, designated protected SHA/Issue, direct resumable
reference and any live dispatcher lease preserves the target. Tags, ordinary
branches, remote refs and modern archive receipts are outside this allowlist.
A new bundle preserves exact objects before retirement; generation drift stops
progress. This is an operator phase and does not change the automation.
