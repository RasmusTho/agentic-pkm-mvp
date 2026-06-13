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

**Pre-push (mandatory before `git push`)** [branch-truth-gate]:

Re-run the same preflight — the commit you just made could be on the wrong branch if the workspace
drifted between the gates. Non-zero exit => STOP, do not push; relocate the commit to the correct
branch (for example cherry-pick onto `$EXPECTED_BRANCH` and reset the drifted branch) before
pushing.

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
