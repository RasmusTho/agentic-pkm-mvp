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

See `.codex/skills/README.md :: Workflow map` for the canonical chain. `PR integration` sits on the
conditional path — only when readiness/repair work is still needed before verification.

## Entry conditions

- Local changes are already implemented.
- Focused validation has already been run and captured.
- The correct lane is already known:
  - implementation
  - docs authoring
  - governance
  - direct repair

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
- For issue-backed PRs, the body must include exactly one `Governing-Issue: #<id>` line and at
  least one `Fixes #<id>`, `Closes #<id>`, or `Resolves #<id>` closing keyword for work fully
  delivered by the PR. In the normal single-Issue case the identities are the same. In an approved
  multi-Issue PR, the governing parent may remain open (`Refs #<id>`) while closing keywords name
  only fully delivered children; follow `docs/development/PR_HOT_PATH.md :: Multi-Issue PR Scope`.
- For docs-authoring or governance lane PRs, leave the linked Issue blank unless a governing Issue actually exists.
- PR-body machinery scales with risk tier per `docs/development/GOVERNANCE_PROPORTIONALITY.md`:
  - Tier 2+ PR bodies must include a `## BuilderOps Routing` section that names relevant BuilderOps
    records/projections/receipts or states `none` with a short reason.
  - Tier 1 PRs (docs-authoring or governance lane) may omit the section entirely when nothing was
    routed — absence means `none`. If the section is present, it must be filled in.
- Default to opening an open PR.
- Use `--draft` only with an explicit reason that the PR is not yet ready for review or still needs integration/repair.
- Publication does not move work to `Done`.

### Container candidate and channel boundary

Opening or updating a normal PR is a source-control publication action only. It must not publish a
container image, change a channel image pin, restart a channel, or trigger a deploy/rollback.

The `Build SHA-tagged app image` check on a pull request is validation-only: it builds an image in
the ephemeral CI runner with `push: false`. A passing check is not evidence that
`ghcr.io/<owner>/pkm-app:<pr-sha>` exists or is pullable by a runtime channel. Nightly test runs do
not create that artifact either. The deployment authority for this policy is
`docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md :: PR validation is not artifact publication
(current policy)`.

When a PR's acceptance criteria require live UAT against its exact SHA:

1. Identify whether the selected non-prod channel is in checkout mode or pinned-image mode.
   Checkout-mode UAT may start the selected channel from the exact isolated PR worktree using the
   explicit `APP_CODE_BIND_COMPOSE=docker-compose.app-bind.yml` overlay; record the worktree SHA,
   selected vault/channel, and runtime proof. This does not publish an image or change a pin.
2. For a pinned-image channel, verify the exact candidate tag is present in GHCR before changing or
   restarting that channel. If it is absent, report a blocked UAT receipt with the exact tag and
   command result. Do not make the normal PR workflow push images, and do not substitute a local or
   older image as proof.
3. Only a separately approved, manually initiated candidate-artifact flow may publish a selected
   SHA for UAT. That flow must produce an artifact identity receipt and must not deploy it; channel
   changes remain under the release/promotion skills.

This boundary prevents a high-volume PR stream from silently becoming a high-volume image-publication
or deployment stream. It does not prohibit the existing `main` image publication path.

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
  --allow-dirty || exit 1
# Non-zero exit => the workspace drifted. STOP. Do not commit. See the shared gate file.
# Never wrap this in `|| echo ...`; that swallows the failure and the commit runs anyway.
```

Publication-boundary base-branch semantics (specific to this skill): the gate asserts the publication HEAD already contains `origin/main`. A local `main` ref that lags or diverges from `origin/main` is advisory when HEAD already contains `origin/main` — in the doctrinal worktree flow `main` is checked out in the shared root worktree and another task may advance or diverge it. A `behind` or `diverged` status where HEAD does **not** yet contain `origin/main` fails the gate and means "rebase onto `origin/main`". Either way a failing gate is STOP: fix it by fetching and rebasing onto `origin/main`, never by bypassing with `--base-branch ""` or by treating local-base drift as safe without proving origin/main reachability.

### Step 4: Create Commit

```bash
git commit -m "$(cat <<'EOF'
Brief summary of bounded outcome

Optional detailed explanation of why this change is needed.

Co-Authored-By: <agent identity> <agent noreply address>
EOF
)"
```

Commit message must:
- Start with imperative verb (Add, Update, Rebuild, etc.)
- Summarize the bounded outcome, not the mechanical changes
- Be truthful about scope
- Never use `Fix`, `Fixes`, `Fixed`, `Close`, `Closes`, `Closed`, `Resolve`, `Resolves`, or `Resolved` as an issue-closing reference in the commit subject or body. Ordinary non-target prose such as `Fix runtime env` is allowed. The workflow owns the supported separator, target, case, and malformed-reference recognition; see `.github/workflows/issue-pr-governance.yml :: pr-contract closing authority`. Use evidence-only `Refs #<id>` when an Issue reference is useful; authenticated closing keywords belong only in the PR body.
- Replace `<agent identity> <agent noreply address>` in the `Co-Authored-By` trailer with the actual agent identity and its own noreply address producing the commit (e.g. Claude's `noreply@anthropic.com`, Codex/ChatGPT's own noreply domain); do not copy a hardcoded model name or a different agent's domain from this template

### Branch-Truth Gate — Pre-Push (mandatory before Step 5) [branch-truth-gate]

Re-run the pre-push phase of `.codex/skills/_shared/BRANCH_TRUTH_GATE.md :: Procedure` (same preflight command as above, same fallback) — the commit you just made could be on the wrong branch if the workspace drifted between the gates. If the gate fails at pre-push: stop, do not push, relocate the commit to the correct branch (e.g. cherry-pick onto `$EXPECTED_BRANCH` and reset the drifted branch), and re-run both gates.

### Review-Before-CI Gate — Before expensive validation and pre-push (mandatory when triggered)

For docs-authoring, governance, and direct-repair PRs, run the cheap local review/contract gate before
the push creates or updates an expensive GitHub CI head. For implementation, governance, or direct-repair work
touching auth, security, data, migrations, concurrency, external APIs, credential durability, or an
explicit state machine, run the same gate before the first expensive validation as well as before
push. Every implementation, governance, and direct-repair lane must explicitly attest that its TCD risk assessment is complete,
including when the resulting risk-surface set is empty; supply every applicable risk surface. This local ordering gate does
not replace required GitHub checks, branch protection, or final review triage.

Use `--review-gate-complete` only after the checks returned by the script have run. For a high-risk
implementation, governance, or direct repair this means a mechanism convergence packet plus a fresh independent high-capability
review of the local publishable SHA before the selected expensive validation; see
`AUTONOMOUS_REVIEW_REPAIR_GATE_CONTRACTS.md :: Mechanism Convergence Gate`. If an emergency direct
repair with no declared high-risk surface must bypass this local gate, use `--bypass-reason` and name
the bypass in the PR/issue receipt. A declared high-risk surface is never bypassable.

```bash
PR_LANE="<implementation|docs-authoring|governance|direct-repair>"
TCD_RISK_SURFACES="<space-separated applicable surfaces, or empty>"
if [ "$PR_LANE" = "implementation" ] || [ "$PR_LANE" = "docs-authoring" ] || [ "$PR_LANE" = "governance" ] || [ "$PR_LANE" = "direct-repair" ]; then
  # Portable read loop, not `mapfile`/`readarray` (bash 4+ only) — macOS ships bash 3.2.
  review_gate_args=(--lane "$PR_LANE" --review-gate-complete)
  if [ "$PR_LANE" = "implementation" ] || [ "$PR_LANE" = "governance" ] || [ "$PR_LANE" = "direct-repair" ]; then
    review_gate_args+=(--risk-assessment-complete)
  fi
  while IFS= read -r file; do
    [ -n "$file" ] && review_gate_args+=(--changed-file "$file")
  done < <(git diff --name-only origin/main...HEAD)
  for risk_surface in $TCD_RISK_SURFACES; do
    review_gate_args+=(--risk-surface "$risk_surface")
  done
  python3 scripts/review_before_ci_gate.py "${review_gate_args[@]}" || exit 1
fi
```

Allowed risk-surface values are: auth, security, data, migration, concurrency, external-api,
credential-durability, and state-machine. After a multi-blocker or adjacent
repeat finding in one mechanism, do not set `--review-gate-complete` again until the low-convergence
circuit breaker in `verification-and-closure` has produced and reviewed a new convergence packet.

For any implementation, governance, or direct-repair lane with a declared high-risk surface, the
executable order is mandatory and fail-closed:

1. Run focused local checks and prepare the mechanism convergence packet.
2. Commit the local publishable SHA and obtain the fresh independent high-capability review.
3. Only after that review passes, run the proportionate validation selected by the governing
   contract and affected subsystem. A repo-wide full suite is not automatic: require it only when
   the Issue/owner doc names it or the changed behavior has cross-system blast radius. When it is
   required, run it through the host lease from
   `docs/development/DEV_WORKFLOW.md :: Validation baseline` and use the publishable SHA in the
   execution id. Governance-only changes default to targeted governance/contract tests plus their
   lint/docs checks.
4. Re-run the branch-truth pre-push gate and the `review_before_ci_gate.py` command above against
   the still-unchanged SHA. A changed SHA invalidates both the review and validation evidence and
   restarts this sequence.
5. Push only after all four preceding steps pass. Never proceed directly from review to push.

### Step 5: Push Branch

```bash
git push origin <branch-name>
```

Verify push succeeded and GitHub suggests PR creation.

### Publication preflight — live open-PR overlap re-check (direct-repair and lane PRs without a claimed Issue)

The snapshot that motivated this PR may be stale by publication time — a concurrent session can push the same fix between your audit and your `gh pr create` (seen: PR #2757 duplicated #2755). Immediately before Step 6, re-check live GitHub state via REST:

```bash
REPO=$(git remote get-url origin | sed -E 's#(git@github.com:|https://github.com/)##; s#\.git$##')
gh api "repos/$REPO/pulls?state=open&per_page=100" --jq '.[] | "\(.number)\t\(.head.ref)\t\(.title)"'
# For any open PR whose title/head suggests the same surface, compare its file set:
gh api "repos/$REPO/pulls/<N>/files?per_page=100" --jq '.[].filename'
```

Any overlap with your staged file set => STOP: keep the earlier compliant PR, close your duplicate or rebase it to the non-overlapping delta (mirrors `deliver-issue-set`'s pre-dispatch reconcile rule). Issue-claimed implementation-lane PRs may skip this — the Issue claim is the collision guard there.

### Step 6: Create or Update PR

Execute based on lane classification. Every template below defaults to the light path with the
required `Final-Review-Rounds: 0` line (the `pr-contract` gate rejects a body with zero or more than
one match of `/^Final-Review-Rounds:[ \t]*[012][ \t]*$/`). Raise it to `1` or `2` only when
`AGENTS.md :: Proportional delivery` selects the full path. The templates also carry concrete
`## BuilderOps Routing` defaults instead of `<...>` placeholders
(the gate rejects any routing value matching `^<.*>$`). The `none` / reason defaults shown match what
`scripts/pr_body_generator.py` emits (`_builderops_section`) — replace them with the actual
records/projections/receipts and reason whenever BuilderOps material was in fact routed.

**Implementation Lane (Fixes an Issue):**
```bash
gh pr create \
  --title "<bounded outcome>" \
  --body "$(cat <<'EOF'
Governing-Issue: #<ISSUE_NUMBER>

Fixes #<ISSUE_NUMBER>

Final-Review-Rounds: 0

## Summary
<1-2 sentence summary of the bounded change>

## BuilderOps Routing
- Records/projections/receipts: none
- Reason: Tier 1 lane with no BuilderOps material routed.

## Notes
Validation: <What validation actually ran>
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

Final-Review-Rounds: 0

## Summary
<Summary of documentation changes>

## Changes
<What surfaces were updated>

## BuilderOps Routing
- Records/projections/receipts: none
- Reason: Tier 1 lane with no BuilderOps material routed.

## Notes
Validation: <Docs validation that ran>
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

Final-Review-Rounds: 0

## Summary
<Summary of governance/workflow change>

## Changes
<What surfaces were updated>

## BuilderOps Routing
- Records/projections/receipts: none
- Reason: Tier 1 lane with no BuilderOps material routed.

## Notes
Validation: <Governance validation that ran>
---
EOF
)"
```

**Direct Repair Lane (bounded immediate fix, no governing Issue):**
```bash
gh pr create \
  --title "<bounded repair outcome>" \
  --body "$(cat <<'EOF'
## Direct Repair
Type: governance
Reason: state why this qualifies as a bounded, immediate direct repair
Validation: state the checks that were actually run
Issue required: no

Final-Review-Rounds: 0

## Summary
<1-2 sentence summary of the bounded repair>

## BuilderOps Routing
- Records/projections/receipts: none
- Reason: Tier 1 lane with no BuilderOps material routed.

## Notes
Validation: <What validation actually ran>
---
EOF
)"
```

`Type:` must be exactly one of `docs`, `governance`, or `code` (`docs/development/PR_HOT_PATH.md ::
Direct Repair`). No lane checkbox and no `Governing-Issue`/closing-keyword line are needed when this
block is complete — the gate accepts the `## Direct Repair` block as the standalone contract.

**Update Existing PR:**
```bash
gh pr edit <pr-number> --body "$(cat <<'EOF'
... updated body content ...
EOF
)"
```

Pre-push PR-body contract gate:
- Before `gh pr create` or `gh pr edit`, verify the body includes exactly one lane classifier:
  - issue-backed lane: exactly one `Governing-Issue: #<id>` plus `Fixes #<id>`, `Closes #<id>`, or
    `Resolves #<id>` for fully delivered work; the IDs match for a single-Issue PR, while an
    approved multi-Issue PR may reference an open governing parent and close delivered children
  - docs lane: `- [x] Docs authoring lane`
  - governance lane: `- [x] Governance lane`
  - direct repair: a complete `## Direct Repair` block with `Type:`, `Reason:`, `Validation:`, and `Issue required: no`
- If none is present, stop and repair the PR body before publication.
- Verify exactly one `Final-Review-Rounds: 0`, `1`, or `2` line is present — every lane requires
  it, including direct repair; `0` declares the light delivery path per
  `AGENTS.md :: Proportional delivery`.
- Verify BuilderOps Routing per tier — see the `## Core rules` PR-body machinery rule above
  (`docs/development/GOVERNANCE_PROPORTIONALITY.md`); never leave the section present but unfilled,
  and never leave a `<...>` placeholder in a value the gate reads (`Records/projections/receipts:`
  or `Reason:`).

Direct Repair block placement: prefer placing the `## Direct Repair` block as the first section of the PR body (before `## Summary`). The governance check accepts the block in any position — first, middle, or last — but first placement is preferred for reviewer clarity.

### Step 7: Conditional pr-integration handoff

After PR is created/updated, use pr-integration only when the PR still needs readiness/repair work before verification:

Invoke the `pr-integration` skill only for a concrete mergeability, CI-attachment, branch-drift, or
review-repair need. Otherwise hand the published PR directly to `verification-and-closure`.

## PR body requirements

Every lane, with no exception:

- include exactly one `Final-Review-Rounds: 0`, `1`, or `2` line (`0` = light delivery path)
- include a `## BuilderOps Routing` section with concrete `Records/projections/receipts:` and
  `Reason:` values (never a `<...>` placeholder) unless the Tier 1 omission rule in `## Core rules`
  applies

Implementation lane:

- include exactly one `Governing-Issue: #<id>` line and closing keywords only for fully delivered
  Issues; the normal single-Issue body uses a matching `Fixes #<id>`, while approved multi-Issue
  delivery may keep the governing parent open and close delivered children
- put each closing keyword on its own dedicated declaration line; never use a closing keyword
  directly adjacent to `#<id>` in narrative prose, including BuilderOps routing or learning notes
- summarize the bounded change
- state focused validation that actually ran

Docs authoring lane:

- mark `Docs authoring lane`
- confirm the change stays within approved docs surfaces

Governance lane:

- mark `Governance lane`
- confirm the change stays within approved governance surfaces

Direct repair lane:

- include a complete `## Direct Repair` block: `Type:` (one of `docs`, `governance`, `code`),
  `Reason:`, `Validation:`, and `Issue required: no`
- no lane checkbox and no `Governing-Issue`/closing-keyword line — the Direct Repair block is the
  standalone contract


## Capturing learning

On a plan divergence (you did something unexpected, or discovered an earlier artifact was wrong), route it through `capture-learning` — it owns the invocation timing and the "name an upstream artifact or don't log" gate.

## Output format

Lead with the human summary; scale the rest to the tier (`docs/development/GOVERNANCE_PROPORTIONALITY.md`). For Tier 1, the summary plus a receipt line (branch, commit, PR link) is enough.

1. Summary For The Human (2–4 sentences: what was published, what remains, what needs a decision)
2. Publication Inputs
3. Branch and Commit Created
4. PR Created or Updated
5. Handoff Target
