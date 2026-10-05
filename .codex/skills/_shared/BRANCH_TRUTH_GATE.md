State: Shared skill contract. Canonical branch-truth gate for every publication lane.

# Branch-Truth Gate

Single source for the workspace gate that prevents committing or pushing from a drifted branch or
worktree. Applies to every lane — implementation, feature-breakdown, docs-authoring, and
governance. `publish-pr` owns the publication procedure that invokes it.

## Worktree policy (doctrinal)

For multi-agent parallel work, a dedicated worktree (via `git worktree add`) is mandatory for the
full lifecycle of an active change — from initial edits through every review-fix push. Do NOT
commit to an active PR from the shared root worktree: a concurrent agent switching that worktree's
branch can land your commit on the wrong branch. The worktree is prevention by construction; the
gate below is detection.

## Procedure

Capture the publication target when you create or switch to the working branch — the capture is
required; if these variables are empty the wrapper omits both drift checks and the gate passes
without enforcing anything:

```bash
EXPECTED_BRANCH="<branch-name>"
EXPECTED_WORKTREE="$(git rev-parse --show-toplevel)"
```

**Pre-commit (mandatory before `git add`/`git commit`)** [branch-truth-gate]:

```bash
scripts/agent_workspace_preflight.sh \
  --expected-branch "$EXPECTED_BRANCH" \
  --expected-worktree "$EXPECTED_WORKTREE" \
  --allow-dirty || exit 1
# Non-zero exit => the workspace drifted. STOP. Do not commit. Switch to the
# correct worktree and re-run the gate. Do not "fix" it by editing
# EXPECTED_BRANCH to match reality.
```

⚠️ **Wire the gate as a hard exit.** The gate only protects you if a non-zero exit actually stops
publication. Do NOT compose it as `preflight && echo ok || echo 'GATE FAILED'` or any `|| echo`
form — that swallows the non-zero exit and the subsequent `git commit`/`git push` runs anyway. Use
`|| exit 1` (or run the bare command under `set -e`). The gate line must be able to terminate the
script it is pasted into. A failing gate is STOP regardless of which check failed — never read one
failing condition (such as `base_branch: behind`) as automatically benign.

At the publish boundary the tree is intentionally dirty, so pass `--allow-dirty` — branch and
worktree drift still fail the gate. At issue pickup (clean tree expected), run the same wrapper
without `--allow-dirty`; `scripts/issue_pickup_claim.sh` does this automatically.

For an authorized additive merge of `origin/main`, a pending `MERGE_HEAD` cannot
pass ordinary preflight. Capture `INTEGRATION_TARGET` as the exact full
`origin/main` SHA before starting that merge; preserve the declared branch and
worktree identities. After resolving and reviewing the working files, use the
two explicit integration steps below. The staging step permits the still
unmerged index; the commit step requires the resolved index to match the
working files. Both prove the exact pending target is still the fresh remote
`main`, retain lease checks, and refuse other operations or unknown state.
They also recompute builtin `ort` in a disposable bare repository with isolated
configuration and objects, selecting versioned attributes only from exact
`HEAD` with `--attr-source` (unsupported Git refuses). Outside its actual conflict paths, the complete
index and tracked working files must preserve the automatic result, including
additions, deletions, renames and modes. Only those conflict paths may be
manually resolved or remain unmerged before staging. The oracle cannot run
custom merge drivers, clean/process filters or external diff/textconv, and
writes no source Git state. Working proof uses physical bytes and modes;
marker/whitespace checks use temporary trees, never source status/diff.
Only syntax proof neutralizes diff/binary/whitespace suppression; it retains
the actual `HEAD` marker width, while ort keeps its immutable `HEAD` attributes.
If removing syntax suppression changes an effective marker width through an
attribute macro, the unsupported state refuses integration.
Unsupported index hints/conversions, gitlinks and special files refuse
integration. NUL-containing physical or staged manual conflict resolutions
also refuse; unchanged automatic binary paths remain eligible.
The dirty census is not run in this explicitly dirty lane.
An unavailable oracle, `ours` merge or discarded automatic content is a refusal.

```bash
# Use the wrapper from an approved merged source checkout. Its --cwd binds the
# worktree being checked even when that checkout's older script lacks this path.
APPROVED_PREFLIGHT="<absolute-approved-checkout>/scripts/agent_workspace_preflight.sh"
"$APPROVED_PREFLIGHT" --cwd "$EXPECTED_WORKTREE" \
  --expected-branch "$EXPECTED_BRANCH" --expected-worktree "$EXPECTED_WORKTREE" \
  --base-branch main --allow-dirty \
  --integration-merge-target "$INTEGRATION_TARGET" --integration-step stage || exit 1
# Stage only the reviewed resolution paths, then run this before git commit:
"$APPROVED_PREFLIGHT" --cwd "$EXPECTED_WORKTREE" \
  --expected-branch "$EXPECTED_BRANCH" --expected-worktree "$EXPECTED_WORKTREE" \
  --base-branch main --allow-dirty \
  --integration-merge-target "$INTEGRATION_TARGET" --integration-step commit || exit 1
```

This opt-in path is limited to pre-staging and pre-commit. It cannot authorize
an outdated merge target, an octopus merge, or shared-root work, including with
`PKM_ALLOW_SHARED_ROOT=1`. A stale pending merge returns to `pr-integration` for
resolution backup and normal merge recovery; do not edit Git metadata, change
the captured target to match a refusal, or copy scripts into the pending merge.

**Pre-push (mandatory before `git push`)** [branch-truth-gate]:

Re-run ordinary preflight without either integration flag — the commit you just made could be on the wrong branch if the workspace
drifted between the gates. Non-zero exit => STOP, do not push; relocate the commit to the correct
branch (for example cherry-pick onto `$EXPECTED_BRANCH` and reset the drifted branch) before
pushing.

This gate answers whether publication comes from the intended isolated branch and contains the
current base. It does not by itself decide whether expensive validation must be repeated after an
otherwise irrelevant rebase. That separate decision is fail-closed and owned by
`docs/development/GOVERNANCE_PROPORTIONALITY.md :: Post-validation base-drift evidence reuse` as
invoked by `publish-pr`.

## Fallback (no script available)

If the preflight script cannot run, assert the branch name directly:

```bash
ACTUAL_BRANCH=$(git branch --show-current)
if [ "$ACTUAL_BRANCH" != "$EXPECTED_BRANCH" ]; then
  echo "BRANCH-TRUTH GATE FAILED: on $ACTUAL_BRANCH (expected $EXPECTED_BRANCH)"
  exit 1
fi
```

The fallback catches branch drift but, unlike the preflight, does not verify worktree isolation.
Do not check the remote PR head SHA at the pre-commit gate — a new local commit advances HEAD past
the remote ref before push.

## Shared-root refusal

`scripts/agent_workspace_preflight.sh` refuses the shared root worktree by default. Set
`PKM_ALLOW_SHARED_ROOT=1` to override for deliberate solo work in the root.
