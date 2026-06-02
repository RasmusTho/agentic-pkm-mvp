---
name: publish-pr
description: "Create or update the implementation, docs, or governance PR after local changes are ready."
---

# Publish PR

Use this skill when local work is complete enough to publish as a branch and pull request.

Goal:
turn validated local changes into a truthful branch, commit, pushed head, and PR artifact without mixing publication with implementation logic.

⚠️ **CRITICAL: All publication steps (branch creation, staging, commit, push, PR creation) must be executed using explicit git/gh commands. Do not describe these steps—execute them and verify they succeeded. Treat pr-integration as a conditional readiness/repair path, not an automatic immediate handoff.**

## Canonical workflow position

`Docs -> Issue -> Project -> Issue maintenance -> Agent -> Publish PR -> PR integration -> CI -> Verification -> Project/doc closure -> Owner Doc`

## Entry conditions

- Local changes are already implemented.
- Focused validation has already been run and captured.
- The correct lane is already known:
  - implementation
  - docs authoring
  - governance

## Responsibilities

- create or switch to the correct branch
- stage only the intended files
- create an intentional commit
- push the branch
- open or update the PR
- apply the correct PR template lane and linked-Issue metadata

## Core rules

- Do not expand implementation scope during publication.
- Do not publish unrelated local changes.
- For implementation lane PRs, the body must include `Fixes #<id>`, `Closes #<id>`, or `Resolves #<id>`.
- For docs-authoring or governance lane PRs, leave the linked Issue blank unless a governing Issue actually exists.
- Every PR body must include a `## BuilderOps Routing` section that names relevant BuilderOps
  records/projections/receipts or states `none` with a short reason.
- Default to opening an open PR.
- Use `--draft` only with an explicit reason that the PR is not yet ready for review or still needs integration/repair.
- Publication does not move work to `Done`.

## Publication workflow (all steps are executable)

### Step 1: Confirm File Set

Verify files belong to a single lane and single bounded change:

```bash
git status --porcelain
```

All modified/new files must align with a single lane (implementation, docs-authoring, or governance).

### Step 2: Create or Switch Branch

```bash
# Option A: Create new branch from main
git fetch origin main
git checkout -b <branch-name> origin/main

# OR Option B: Switch to existing branch
git checkout <branch-name>

# Verify correct branch
git status
```

Branch naming: Descriptive, hyphenated (e.g., `fix-auth-token-expiry`, `docs-roadmap-update`, `governance-skill-updates`).

### Step 3: Stage Intended Files

```bash
# Stage specific files (not all changes)
git add <file1> <file2> <file3>

# Verify staging
git status
```

Do not use `git add -A` or `git add .`—stage only intended files.

### Branch-Truth Gate — Pre-Commit (mandatory before Step 4) [branch-truth-gate]

**Worktree policy (doctrinal):** For multi-agent parallel work, a dedicated per-issue worktree (via `git worktree add`) is mandatory for the full issue lifecycle — from initial implementation through every review-fix push. Do NOT commit to an active PR from the shared root worktree. This mandate is enforced by policy; the branch-name check below does not verify worktree isolation.

**Branch-name check (scriptable):** Verify the branch context before committing:

```bash
EXPECTED_BRANCH="<branch-name from Step 2>"
ACTUAL_BRANCH=$(git branch --show-current)

if [ "$ACTUAL_BRANCH" != "$EXPECTED_BRANCH" ]; then
  echo "BRANCH-TRUTH GATE FAILED (pre-commit): on $ACTUAL_BRANCH (expected $EXPECTED_BRANCH)"
  echo "Switch to the correct worktree before committing."
  exit 1
fi
```

Branch name must match. Do not check the remote PR head SHA here — a new local commit will advance HEAD past the remote ref before push.

### Step 4: Create Commit

```bash
git commit -m "$(cat <<'EOF'
Brief summary of bounded outcome

Optional detailed explanation of why this change is needed.

Co-Authored-By: Claude Haiku 4.5 <noreply@anthropic.com>
EOF
)"
```

Commit message must:
- Start with imperative verb (Fix, Add, Update, Rebuild, etc.)
- Summarize the bounded outcome, not the mechanical changes
- Be truthful about scope

### Branch-Truth Gate — Pre-Push (mandatory before Step 5) [branch-truth-gate]

Verify the branch context is still correct before pushing:

```bash
EXPECTED_BRANCH="<branch-name from Step 2>"
ACTUAL_BRANCH=$(git branch --show-current)

if [ "$ACTUAL_BRANCH" != "$EXPECTED_BRANCH" ]; then
  echo "BRANCH-TRUTH GATE FAILED (pre-push): on $ACTUAL_BRANCH (expected $EXPECTED_BRANCH)"
  exit 1
fi
echo "Branch-truth gate passed — pushing to origin/$EXPECTED_BRANCH"
```

If branch name fails at pre-push: stop, switch to the correct worktree, and re-run both gates.

### Step 5: Push Branch

```bash
git push origin <branch-name>
```

Verify push succeeded and GitHub suggests PR creation.

### Step 6: Create or Update PR

Execute based on lane classification:

**Implementation Lane (Fixes an Issue):**
```bash
gh pr create \
  --title "<bounded outcome>" \
  --body "$(cat <<'EOF'
Fixes #<ISSUE_NUMBER>

## Summary
<1-2 sentence summary of the bounded change>

## Validation
<What validation actually ran>

## BuilderOps Routing
- Records/projections/receipts: <ids or "none">
- Reason: <why no BuilderOps material was created, or what was routed>

---
EOF
)"
```

**Docs Authoring Lane:**
```bash
gh pr create \
  --title "<docs update title>" \
  --body "$(cat <<'EOF'
- [x] Docs authoring lane

## Summary
<Summary of documentation changes>

## Changes
<What surfaces were updated>

## Validation
<Docs validation that ran>

## BuilderOps Routing
- Records/projections/receipts: <ids or "none">
- Reason: <why no BuilderOps material was created, or what was routed>

---
EOF
)"
```

**Governance Lane:**
```bash
gh pr create \
  --title "<governance change title>" \
  --body "$(cat <<'EOF'
- [x] Governance lane

## Summary
<Summary of governance/workflow change>

## Changes
<What surfaces were updated>

## Validation
<Governance validation that ran>

## BuilderOps Routing
- Records/projections/receipts: <ids or "none">
- Reason: <why no BuilderOps material was created, or what was routed>

---
EOF
)"
```

**Update Existing PR:**
```bash
gh pr edit <pr-number> --body "$(cat <<'EOF'
... updated body content ...
EOF
)"
```

Pre-push PR-body contract gate:
- Before `gh pr create` or `gh pr edit`, verify the body includes exactly one lane classifier:
  - implementation lane: `Fixes #<id>` or `Closes #<id>` or `Resolves #<id>`
  - docs lane: `- [x] Docs authoring lane`
  - governance lane: `- [x] Governance lane`
  - direct repair: a complete `## Direct Repair` block with `Type:`, `Reason:`, `Validation:`, and `Issue required: no`
- If none is present, stop and repair the PR body before publication.
- Verify the body includes `## BuilderOps Routing`. If no BuilderOps object was created, the
  section must still explain why the work did not produce operational BuilderOps material.

Direct Repair block placement: prefer placing the `## Direct Repair` block as the first section of the PR body (before `## Summary`). The governance check accepts the block in any position — first, middle, or last — but first placement is preferred for reviewer clarity.

### Step 7: Hand Off to pr-integration

After PR is created/updated, use pr-integration only when the PR still needs readiness/repair work before verification:

```bash
# Invoke pr-integration skill to verify, check CI, and prepare for verification
echo "Handing off to pr-integration skill"
```

**Do not force this as an immediate publication step.** PR integration resolves merge conflicts, verifies CI, and prepares the PR for verification/merge when the PR needs that readiness path.

## PR body requirements

Implementation lane:

- include `Fixes #<id>`
- summarize the bounded change
- state focused validation that actually ran

Docs authoring lane:

- mark `Docs authoring lane`
- confirm the change stays within approved docs surfaces

Governance lane:

- mark `Governance lane`
- confirm the change stays within approved governance surfaces


## Capturing learning

**Capturing learning:** if during this work you notice a divergence from plan — you did something you did not expect to do, or discovered an earlier artifact was wrong — invoke `capture-learning` before continuing. Do not batch to end of task; context is freshest now. Only log if you can name an upstream artifact that could absorb the fix.

## Output format

1. Publication Inputs
2. Branch and Commit Created
3. PR Created or Updated
4. Handoff Target
