---
name: pr-integration
description: "Prepare a slice-implementation PR for verification by resolving merge conflicts, enforcing PR contract metadata, and ensuring CI is green on the latest head SHA."
---

# PR Integration

Use this skill when a PR needs readiness/repair before verification; it is the conditional path after `publish-pr`, not a mandatory immediate publication step.

Goal:
produce a mergeable, policy-compliant PR with CI **green** on the latest head SHA so verification can run on truthful state.

This skill does NOT merge the PR. Merge is owned by the verification skill after it confirms the delivery contract is satisfied.

⚠️ **CRITICAL: All integration actions (merge conflict resolution, CI verification, review comment handling) must be executed using explicit git/gh/API commands. Do not describe these actions—execute them and verify they succeeded. The handoff decision must be explicit: `ready-for-verification`, `blocked-merge-conflict`, `blocked-ci-failure`, `blocked-contract-drift`, or `blocked-review-feedback`.**

## Canonical workflow position

Hot path:
`Docs -> Feature issue -> Slice issue -> Agent -> Publish PR -> CI -> Slice verification -> Merge -> Feature validation -> Acceptance -> Owner Doc`

Conditional / readiness-repair path:
`Docs -> Feature issue -> Slice issue -> Agent -> Publish PR -> PR integration -> CI -> Slice verification -> Merge -> Feature validation -> Acceptance -> Owner Doc`

## First context to load

- `AGENTS.md`
- `docs/development/DEV_WORKFLOW.md`
- `.github/pull_request_template.md`
- `.github/workflows/issue-pr-governance.yml`
- `.github/workflows/project-status-reconcile.yml`

## Entry conditions

- A bounded governing slice implementation Issue exists.
- A PR exists (draft or ready) and links the governing branch.
- The PR was just created or updated by `.codex/skills/publish-pr/SKILL.md` or equivalent truthful publication flow.
- Implementation changes are already in place.
- Use this skill when the PR still needs mergeability, CI attachment, or review-feedback repair before verification.

## Exit conditions

ALL of these must be true before handing off to verification:

- PR `mergeable` state is `MERGEABLE`, confirmed by local merge simulation.
- No unresolved merge conflicts remain.
- PR body/classification satisfies governance contract.
- CI/checks are attached to the current head SHA and **all required checks have completed successfully**.
- All review comments are addressed or explicitly marked as out-of-scope.

If any exit condition is not met, do not hand off. Loop or block.

## Required gates (all executable)

### 0) Workspace Isolation Gate

**Action: enforce clean single-session workspace before integration**

```bash
scripts/agent_workspace_preflight.sh \
  --expected-branch "$(git branch --show-current)" \
  --expected-worktree "$(git rev-parse --show-toplevel)"
```

If this gate fails, stop immediately. Resolve concurrent-session drift before continuing.

Additionally, before any review-fix commit or push: [branch-truth-gate]

- **Before committing:** confirm `git branch --show-current` equals the PR head branch. If it does not, stop — do not commit. Switch to the correct worktree first.
- **Before pushing:** confirm `git branch --show-current` still equals the PR head branch. Do not compare HEAD SHA to the remote PR `headRefOid` here — the local commit has already advanced HEAD past the remote ref.
- **For multi-agent parallel work:** a per-issue worktree is mandatory for the full issue lifecycle (implementation through review-fix). The shared root worktree must not be used to commit to an active PR.

### 1) Contract and Metadata Gate

**Action: Verify PR Contract**

```bash
# Get PR metadata
gh pr view <PR_NUMBER> --json number,state,isDraft,mergeable,headRefOid,baseRefName,labels,body,statusCheckRollup

# Get current check status
gh pr checks <PR_NUMBER>
```

**Verification:**
- ✅ Implementation lane: PR body includes `Fixes #<id>`, `Closes #<id>`, or `Resolves #<id>`
- ✅ Docs authoring lane: PR body has `- [x] Docs authoring lane` and files are within `docs/` or allowed-surface
- ✅ Governance lane: PR body has `- [x] Governance lane` and files are within `.codex/skills/` or other allowed governance surfaces
- ✅ No scope drift: PR scope still matches Issue contract
- ✅ Checklists: No contradictory unchecked items in body

**If contract fails:** Stop and route through issue-maintenance with explicit contract-drift context.

### 1.5) Conflict Marker Gate (Changed Files)

**Action: scan changed files for unresolved merge-conflict markers before CI interpretation**

```bash
# Prefer PR base ref when available; default to origin/main
PR_BASE_REF=$(gh pr view <PR_NUMBER> --json baseRefName --jq '.baseRefName' 2>/dev/null || echo "main")
git fetch origin "$PR_BASE_REF"

git diff --name-only --diff-filter=ACMRT "origin/$PR_BASE_REF...HEAD" > /tmp/pr_files.txt
if [ -s /tmp/pr_files.txt ]; then
  if xargs -a /tmp/pr_files.txt rg -n '^(<<<<<<<|>>>>>>>)'; then
    echo "❌ BLOCKED: unresolved merge-conflict markers present"
    echo "Handoff decision: blocked-merge-conflict"
    exit 1
  fi
fi
echo "✅ No conflict markers detected in changed files"
```

If markers are found, resolve them, re-run focused validation, push, and restart from mergeability checks.

### 2) Mergeability Gate

**Critical: Never trust the GitHub API `mergeable` field alone.** GitHub returns `null` while computing and `dirty` for multiple unrelated reasons. Always verify locally.

**Action: Verify Merge Locally**

```bash
# Step 1: Fetch latest base branch
git fetch origin main

# Step 2: Simulate merge locally
git merge-tree $(git merge-base origin/main HEAD) origin/main HEAD > /tmp/merge-sim.txt
cat /tmp/merge-sim.txt

# Step 3: Check for CONFLICT keyword
if grep -q "CONFLICT" /tmp/merge-sim.txt; then
  echo "❌ MERGE CONFLICTS DETECTED"
else
  echo "✅ Local merge simulation clean (no CONFLICT output)"
fi
```

**If merge clean, verify API state:**

```bash
gh pr view <PR_NUMBER> --json mergeable
```

Expected: `mergeable: MERGEABLE` or `mergeable: true`

**If merge conflicts exist:**

**Action: Resolve Merge Conflicts**

```bash
# Step 1: Sync with latest base
git fetch origin main
git rebase origin/main
# OR (follow repo norm)
git merge origin/main

# Step 2: Resolve conflicts manually in files
# (User must edit conflicted files)

# Step 3: Stage resolved files
git add <resolved-files>
git commit -m "Resolve merge conflicts from origin/main"

# Step 4: Re-run local merge simulation
git merge-tree $(git merge-base origin/main HEAD) origin/main HEAD | grep CONFLICT
# Should show NO output if resolved

# Step 5: Rerun focused validation for touched surfaces
# (Run tests relevant to changed files)

# Step 6: Push updated branch
git push origin <branch-name>

# Step 7: Re-verify mergeable state
gh pr view <PR_NUMBER> --json mergeable
```

**Handoff if still blocked:** Mark as `blocked-merge-conflict` with explicit conflict paths and resolution context.

### 3) CI Attachment Gate

**Critical: branch truth must be established before you trust CI attachment state.**

**Action: Verify Checks Attached to Current Head**

```bash
# Get current head SHA
HEAD_SHA=$(git rev-parse HEAD)

# Get tracked remote branch SHA
BRANCH_NAME=$(git branch --show-current)
REMOTE_HEAD_SHA=$(git rev-parse origin/$BRANCH_NAME)

# Get PR head SHA from GitHub
PR_HEAD_SHA=$(gh pr view <PR_NUMBER> --json headRefOid --jq '.headRefOid')

# Verify all three match
if [ "$HEAD_SHA" = "$REMOTE_HEAD_SHA" ] && [ "$HEAD_SHA" = "$PR_HEAD_SHA" ]; then
  echo "✅ Local HEAD, origin branch head, and PR head SHA all match"
else
  echo "❌ HEAD mismatch:"
  echo "   local  $HEAD_SHA"
  echo "   origin $REMOTE_HEAD_SHA"
  echo "   pr     $PR_HEAD_SHA"
fi

# Check for attached checks
gh pr checks <PR_NUMBER>
```

**If the three SHAs do not match, stop CI interpretation and repair branch truth first.**

Common causes:
- local branch contains unpublished commits
- remote PR branch moved since local validation
- unrelated local drift was left on the PR branch

**Action: Isolate unrelated local drift before repairing branch truth**

```bash
# Inspect working tree first
git status -sb

# If unexpected local changes exist, preserve them explicitly
git stash push -u -m "preserve-local-drift-before-pr-integration"

# Optional: preserve local divergent history before resetting the PR branch name
git switch -c <branch-name>-local-backup

# Re-point the PR branch name at the remote branch tip and switch back
git branch -f <branch-name> origin/<branch-name>
git switch <branch-name>

# Re-check truth
git branch --show-current
git status -sb
git rev-parse HEAD
git rev-parse origin/<branch-name>
gh pr view <PR_NUMBER> --json headRefOid --jq '.headRefOid'
```

If branch truth still cannot be re-established without mixing unrelated changes into the PR, hand off as:
- `blocked-contract-drift`

Do not continue to CI result evaluation on a branch whose local `HEAD`, tracked remote branch, and PR head SHA disagree.

**If checks missing on current head, retry with exponential backoff:**

```bash
# Poll every 15 seconds for up to 2 minutes (8 attempts)
for i in {1..8}; do
  echo "Attempt $i/8: Polling for checks..."
  gh pr checks <PR_NUMBER> | grep -q "pass\|fail\|pending" && echo "✅ Checks attached" && break
  sleep 15
done

# If still missing after 2 minutes, retrigger CI
if ! gh pr checks <PR_NUMBER> | grep -q "pass\|fail\|pending"; then
  echo "⚠️ Checks missing after 2 minutes. Triggering retrigger..."
  git commit --allow-empty -m "Retrigger CI: checks not attached to current SHA"
  git push origin <branch-name>
  
  # Poll again for up to 3 minutes after retrigger
  for i in {1..12}; do
    echo "Post-retrigger attempt $i/12: Polling for checks..."
    gh pr checks <PR_NUMBER> | grep -q "pass\|fail\|pending" && echo "✅ Checks re-attached" && break
    sleep 15
  done
fi

# Final check: if still no checks, mark as blocked
if ! gh pr checks <PR_NUMBER> | grep -q "pass\|fail\|pending"; then
  echo "❌ BLOCKED: Checks not attached to current SHA after retrigger"
  echo "Handoff decision: blocked-ci-failure (missing CI attachment)"
  exit 1
fi
```

**Do not proceed to CI result gate until at least one check is attached.**

### 4) CI Result Gate

**Critical: Do not hand off while checks are pending or absent.** Wait until all checks reach terminal state.

**Action: Poll for CI Completion**

```bash
# Poll every 30 seconds until all checks terminal, max 15 minutes
START=$(date +%s)
TIMEOUT=$((START + 900))  # 15 minutes

while [ $(date +%s) -lt $TIMEOUT ]; do
  gh pr checks <PR_NUMBER> | tee /tmp/checks.txt
  
  # Check for pending/in-progress
  if grep -E "pending|in_progress|queued" /tmp/checks.txt > /dev/null; then
    echo "⏳ Checks still in progress... waiting 30 seconds"
    sleep 30
  else
    echo "✅ All checks reached terminal state"
    break
  fi
done

# If timeout, mark as blocked
if grep -E "pending|in_progress|queued" /tmp/checks.txt > /dev/null; then
  echo "❌ BLOCKED: CI timeout (15 minutes exceeded)"
  echo "Handoff decision: blocked-ci-failure (CI timed out)"
  exit 1
fi
```

**Action: Analyze CI Results**

```bash
# Get detailed check results
gh pr checks <PR_NUMBER> --json name,conclusion,detailsUrl | tee /tmp/results.json

# Check for failures
FAILURES=$(jq '.[] | select(.conclusion=="FAILURE" or .conclusion=="failure")' /tmp/results.json)

if [ -z "$FAILURES" ]; then
  echo "✅ All checks passed"
else
  echo "❌ Failed checks detected:"
  echo "$FAILURES" | jq '.name, .detailsUrl'
fi
```

**If any check fails:**

1. **Analyze failure:** Review log URLs and determine if fixable within Issue scope
   - If CI reports "unrecognised option" or "no such option" for a pytest flag that corresponds to
     an installed plugin, check whether `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` is set and the plugin
     is not explicitly loaded. Add `-p <plugin_name>` to the pytest invocation.
     [plugin-load-guard]
2. **If fixable:** Fix code/config, push, **restart from Mergeability Gate** (head SHA changed)
3. **If not fixable:** Mark as `blocked-ci-failure` with failing job names and log links

**Never declare `ready-for-verification` while any check is `pending`, `in_progress`, `queued`, or absent.**

### 5) Review Comment Detection and Addressing Gate

**Purpose**: Surface and address review feedback before handoff to avoid back-and-forth delays.

**Action: Post-CI Review Arrival Poll (bounded, 60 s max)**

Automated reviewers (e.g. `chatgpt-codex-connector`) use CI completion as their trigger and post their comments *after* CI reaches terminal state. Sampling reviews immediately at Gate 4 exit misses these comments. Wait up to 60 s (4 × 15 s polls) for new review activity before proceeding to the fetch step.

```bash
# Record review count before the poll window
REVIEWS_BEFORE=$(gh pr view <PR_NUMBER> --json reviews --jq '.reviews | length')

echo "Post-CI poll: waiting up to 60 s for automated reviewer comments..."
for i in 1 2 3 4; do
  sleep 15
  REVIEWS_NOW=$(gh pr view <PR_NUMBER> --json reviews --jq '.reviews | length')
  if [ "$REVIEWS_NOW" -gt "$REVIEWS_BEFORE" ]; then
    echo "✅ New review activity detected after ${i}×15 s — proceeding to fetch"
    break
  fi
  echo "  Poll $i/4: no new reviews yet (${REVIEWS_NOW} reviews)"
done
echo "Post-CI poll complete — sampling reviews now"
```

This poll is optional and bounded: it adds at most 60 s of wall-clock time and never blocks if no reviews arrive.

**Action: Fetch and Classify Reviews**

```bash
# Get all reviews
gh pr view <PR_NUMBER> --json reviews | tee /tmp/reviews.json

# Get inline comments
gh api repos/{owner}/{repo}/pulls/<PR_NUMBER>/comments | tee /tmp/inline-comments.json

# Count unresolved comments
UNRESOLVED=$(jq '.[] | select(.state != "COMMENTED" or .state != "APPROVED" or .state != "DISMISSED")' /tmp/reviews.json | wc -l)

if [ "$UNRESOLVED" -eq 0 ]; then
  echo "✅ No unresolved review comments"
else
  echo "⚠️ Found $UNRESOLVED unresolved comments"
  jq '.[].body' /tmp/reviews.json
fi
```

**Classification & Response:**

For each unresolved comment:

**A) Actionable Within Scope**
- Examples: missing edge case, clearer wording, additional validation
- Action:
  ```bash
  # Implement the fix
  # (code changes)
  
  # Re-run focused validation
  # (tests relevant to change)
  
  # Stage and push
  git add <files>
  git commit -m "Address review feedback: <summary>"
  git push origin <branch-name>
  
  # Post comment explaining fix
  gh pr comment <PR_NUMBER> --body "✅ Addressed feedback: <explanation>. Changes pushed."
  
  # Restart from Mergeability Gate (head SHA changed)
  ```

**B) Out-of-Scope**
- Examples: feature requests, alternative approaches, future improvements
- Action:
  ```bash
  # Post comment with rationale
  gh pr comment <PR_NUMBER> --body "This feedback is out-of-scope for #<ISSUE>. The Issue scope is <reference to scope>. Suggested as follow-up in <new Issue or backlog item>."
  ```

**C) Blocking**
- Feedback indicating Issue requirements are not met or contract is violated
- Action: Stop and mark as `blocked-review-feedback` with explicit context

**Note:** If any code was pushed, **restart from Mergeability Gate** (head SHA changed).

## Gate Re-Entry After Any Push

**Any push to the PR branch changes the head SHA. After pushing:**

```bash
# Verify push succeeded
git push origin <branch-name>

# Wait for GitHub to update PR head
sleep 5

# Get new head SHA
NEW_HEAD=$(gh pr view <PR_NUMBER> --json headRefOid --jq '.headRefOid')
echo "New PR head SHA: $NEW_HEAD"
```

**Then restart gates in this order:**

1. **Restart Mergeability Gate** (step 2)
   - Re-run local merge simulation against new SHA
   
2. **Wait for CI Attachment** (step 3)
   - Poll for checks to attach to new SHA
   
3. **Wait for CI Completion** (step 4)
   - Poll until all checks terminal on new SHA
   
4. **Re-check Review Comments** (step 5)
   - New comments may have been added
   - Previous review feedback context may have changed

**Do not carry forward check results from a previous SHA.**

### 6) Merge-Ref Validation (mandatory after any review-fix push) [merge-ref-validation]

After pushing a review-fix, GitHub assembles a merge-ref at `refs/pull/<PR_NUMBER>/merge`.
Branch HEAD may be clean while the merge-ref carries a divergent context that causes CI-only failures (learning-log 2026-05-07 — PR #800).

**Action: Fetch and inspect the merge-ref tree**

```bash
PR_NUMBER=<PR_NUMBER>
git fetch origin +refs/pull/${PR_NUMBER}/merge:refs/merge_validation

# Inspect touched symbols using git show — do NOT checkout into the active worktree
git show refs/merge_validation:app/<changed_module>.py | grep -n "<changed_symbol>"
```

Do not use `git checkout refs/merge_validation -- .`: that mutates the active working tree and index, leaving the PR branch dirty and risking accidental commits.

**Action: Run a targeted smoke check against the merge-ref in a temporary worktree**

```bash
MERGE_WORKTREE=$(mktemp -d)
git worktree add --detach "$MERGE_WORKTREE" refs/merge_validation
(cd "$MERGE_WORKTREE" && PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/<relevant_test_file>.py -k "<key_test>")
SMOKE_EXIT=$?
git worktree remove --force "$MERGE_WORKTREE"
[ $SMOKE_EXIT -ne 0 ] && echo "❌ Merge-ref smoke test failed (exit $SMOKE_EXIT)" && exit $SMOKE_EXIT
```

**If the symbol is absent in the merge-ref or any test fails:**

- Do NOT declare `ready-for-verification`.
- Report `blocked-ci-failure` with the merge-ref tree context.
- Push a corrective fix to the branch and repeat this section from the fetch step.

**If both checks pass:**

```bash
echo "✅ Merge-ref validation passed — merge-ref tree consistent with branch HEAD"
```

Proceed to the Handoff Decision.

## Quick Reference: Integration Outcomes

| Gate | Condition | Action | Outcome |
|------|-----------|--------|---------|
| Contract | Lane + scope correct | Continue | ✅ pass |
| Contract | Lane/scope wrong | Re-evaluate/route to maintenance | ❌ blocked-contract-drift |
| Mergeability | Local merge clean | Continue | ✅ pass |
| Mergeability | Conflicts exist, resolve them | Fix + push + re-verify | ✅ pass (after resolution) |
| Mergeability | Conflicts unresolved | Mark blocked | ❌ blocked-merge-conflict |
| CI Attach | Checks on head SHA | Continue | ✅ pass |
| CI Attach | Missing after retrigger | Mark blocked | ❌ blocked-ci-failure |
| CI Result | All terminal success | Continue | ✅ pass |
| CI Result | Any terminal failure (fixable) | Fix + push + restart gates 2-4 | ✅ pass (after fix) |
| CI Result | Failures not fixable | Mark blocked | ❌ blocked-ci-failure |
| Reviews | No blocking comments | Continue | ✅ pass |
| Reviews | Actionable within scope | Fix + push + restart gates 2-5 | ✅ pass (after fix) |
| Reviews | Out-of-scope | Comment + continue | ✅ pass |
| Reviews | Blocking comments remain | Mark blocked | ❌ blocked-review-feedback |
| **All gates** | **All pass** | **Hand off** | **ready-for-verification** |

## Lifecycle Truth Rules During Integration

- Keep Issue/Project state truthful:
  - active work remains `In Progress`
  - move to `Review` only when review handoff is explicit (normally after review requested)
- Do not mark lifecycle `Done` in this stage.
- Do not close the governing Issue in this stage.
- **Do not merge the PR in this stage.** Merge is owned by verification-and-closure after delivery contract verification.

## Handoff Decision (Executable)

**ONLY ONE of these outcomes must be declared. Each outcome has explicit conditions and next steps.**

### Outcome 1: ✅ `ready-for-verification`

**Conditions (ALL must be true):**
```bash
# 1. Local merge clean
git merge-tree $(git merge-base origin/main HEAD) origin/main HEAD | grep -q CONFLICT && exit 1 || echo "✅ No CONFLICT"

# 2. GitHub mergeable is true/MERGEABLE
gh pr view <PR_NUMBER> --json mergeable | grep -E "MERGEABLE|true" || exit 1

# 3. All checks passed on current head SHA
gh pr checks <PR_NUMBER> | grep -E "fail|pending|in_progress" && exit 1 || echo "✅ All checks passed"

# 4. No blocking review comments
gh pr view <PR_NUMBER> --json reviews | jq '.[].state' | grep -iE "request_changes" && exit 1 || echo "✅ No blocking reviews"
```

**Handoff:**
```bash
echo "HANDOFF DECISION: ready-for-verification"
echo "Execute: .codex/skills/verification-and-closure/SKILL.md"
```

### Outcome 2: ❌ `blocked-merge-conflict`

**Condition:** Merge conflicts remain after attempted resolution.

**Handoff:**
```bash
echo "HANDOFF DECISION: blocked-merge-conflict"
echo "Conflicted files: $(git diff --name-only --diff-filter=U)"
echo "Route back to: Issue or manual conflict resolution"
```

### Outcome 3: ❌ `blocked-ci-failure`

**Conditions:**
- Required CI checks failed and not fixable within Issue scope
- CI checks not attaching to head SHA after retrigger
- CI timeout (exceeded 15 minutes)

**Handoff:**
```bash
echo "HANDOFF DECISION: blocked-ci-failure"
echo "Failing jobs: $(gh pr checks <PR_NUMBER> | grep fail)"
echo "Log URLs: $(gh pr checks <PR_NUMBER> | grep fail | awk '{print $NF}')"
echo "Route back to: Issue maintenance or CI configuration review"
```

### Outcome 4: ❌ `blocked-contract-drift`

**Condition:** PR body or scope no longer matches Issue contract.

**Handoff:**
```bash
echo "HANDOFF DECISION: blocked-contract-drift"
echo "Contract mismatch: <specific difference>"
echo "Route to: issue-maintenance skill"
```

### Outcome 5: ❌ `blocked-review-feedback`

**Condition:** Unresolved blocking review comments (request-changes).

**Handoff:**
```bash
echo "HANDOFF DECISION: blocked-review-feedback"
echo "Blocking comments: $(gh pr view <PR_NUMBER> --json reviews | jq '.[].body')"
echo "Route back to: Issue maintenance or implementer for resolution"
```

---

## Output Format

1. PR Integration Inputs
2. Contract Gate Result (✅ pass or ❌ fail)
3. Mergeability Gate Result (✅ pass or ❌ fail + actions taken)
4. CI Attachment and Status (✅ attached + results or ❌ missing/timeout)
5. Review Comment Assessment (✅ none/addressed or ❌ blocking comments)
6. **Explicit Handoff Decision** (one of the 5 outcomes above)

## Capturing learning

**Capturing learning:** if during this work you notice a divergence from plan — you did something you did not expect to do, or discovered an earlier artifact was wrong — invoke `capture-learning` before continuing. Do not batch to end of task; context is freshest now. Only log if you can name an upstream artifact that could absorb the fix.
