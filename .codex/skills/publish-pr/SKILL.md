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
- PR-body machinery scales with risk tier per `docs/development/GOVERNANCE_PROPORTIONALITY.md`:
  - Tier 2+ PR bodies must include a `## BuilderOps Routing` section that names relevant BuilderOps
    records/projections/receipts or states `none` with a short reason.
  - Tier 1 PRs (docs-authoring or governance lane) may omit the section entirely when nothing was
    routed — absence means `none`. If the section is present, it must be filled in.
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

# Capture the publication target so the branch-truth gate can detect drift later.
# In a heavily parallel multi-worktree setup, a concurrent agent can switch the
# shared root worktree's branch mid-session; these captured values are what the
# gate asserts against.
EXPECTED_BRANCH="<branch-name>"
EXPECTED_WORKTREE="$(git rev-parse --show-toplevel)"
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

The canonical gate (worktree doctrine, hardened preflight, and the no-script branch-name fallback) is defined once at `.codex/skills/_shared/BRANCH_TRUTH_GATE.md :: Procedure`. Run the pre-commit phase now with `--allow-dirty` — `EXPECTED_BRANCH` and `EXPECTED_WORKTREE` were captured in Step 2:

```bash
scripts/agent_workspace_preflight.sh \
  --expected-branch "$EXPECTED_BRANCH" \
  --expected-worktree "$EXPECTED_WORKTREE" \
  --allow-dirty
# Non-zero exit => the workspace drifted. STOP. Do not commit. See the shared gate file.
```

Publication-boundary base-branch semantics (specific to this skill): the gate asserts the publication HEAD already contains `origin/main`. A local `main` ref that merely lags `origin/main` is reported (`status: "behind"`) but does not fail — in the doctrinal worktree flow `main` is checked out in the root worktree and cannot be fast-forwarded from here. A diverged or unresolvable base ref, or a HEAD that does not contain `origin/main`, still fails; fix it by fetching and rebasing onto `origin/main`, never by bypassing with `--base-branch ""`.

### Step 4: Create Commit

```bash
git commit -m "$(cat <<'EOF'
Brief summary of bounded outcome

Optional detailed explanation of why this change is needed.

Co-Authored-By: <agent identity> <noreply@anthropic.com>
EOF
)"
```

Commit message must:
- Start with imperative verb (Fix, Add, Update, Rebuild, etc.)
- Summarize the bounded outcome, not the mechanical changes
- Be truthful about scope
- Replace `<agent identity>` in the `Co-Authored-By` trailer with the actual agent identity producing the commit; do not copy a hardcoded model name from this template

### Branch-Truth Gate — Pre-Push (mandatory before Step 5) [branch-truth-gate]

Re-run the pre-push phase of `.codex/skills/_shared/BRANCH_TRUTH_GATE.md :: Procedure` (same preflight command as above, same fallback) — the commit you just made could be on the wrong branch if the workspace drifted between the gates. If the gate fails at pre-push: stop, do not push, relocate the commit to the correct branch (e.g. cherry-pick onto `$EXPECTED_BRANCH` and reset the drifted branch), and re-run both gates.

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
- Verify BuilderOps Routing per tier (`docs/development/GOVERNANCE_PROPORTIONALITY.md`):
  - Tier 2+: the body must include `## BuilderOps Routing`. If no BuilderOps object was created,
    the section must still explain why the work did not produce operational BuilderOps material.
  - Tier 1 (docs/governance lane): the section may be omitted when nothing was routed — absence
    means `none`. Never leave the section present but unfilled.

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

**Capturing learning:** if during this work you notice a divergence from plan — you did something you did not expect to do, or discovered an earlier artifact was wrong — route it through `capture-learning`, which owns the invocation timing: invoke immediately only when the divergence needs upstream repair now; otherwise note the signal for `learning-retrospective`. Only log if you can name an upstream artifact that could absorb the fix.

## Output format

Lead with the human summary; scale the rest to the tier (`docs/development/GOVERNANCE_PROPORTIONALITY.md`). For Tier 1, the summary plus a receipt line (branch, commit, PR link) is enough.

1. Summary For The Human (2–4 sentences: what was published, what remains, what needs a decision)
2. Publication Inputs
3. Branch and Commit Created
4. PR Created or Updated
5. Handoff Target
