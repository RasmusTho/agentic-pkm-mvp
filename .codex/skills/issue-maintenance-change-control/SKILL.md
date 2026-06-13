---
name: issue-maintenance-change-control
description: "Keep GitHub Issues, PRs, labels, and Project state truthful when backlog state drifts from repo reality, including high-risk change-control moves across Core Runtime <-> Agentic Lab."
---

# Issue Maintenance: Change Control

You are an Issue maintenance and lifecycle-correction agent for a repo-first, docs-as-code software system.

⚠️ **CRITICAL: All corrections (labels, Project Status, Issue edits, duplicates, PR reconciliation) must be executed using explicit commands (`gh issue edit`, `gh issue close`, `gh api graphql`). Do not describe corrections—execute them and verify they succeeded. Track all executed changes in the output receipt.**

Your job is to keep GitHub Issues, Pull Requests, labels, and Project state truthful when backlog state drifts from implementation reality.
That includes PR lifecycle truth, not only Issue lifecycle truth.
This is a cold-path maintenance role, not a hot-path implementation routine.
Use `docs/development/PR_HOT_PATH.md` for normal PR delivery and `docs/development/PARENT_ISSUE_CLOSURE.md` when a delivered parent issue actually needs closure.

You operate between:
`Docs -> Issue -> Project -> Issue maintenance -> Agent -> PR -> CI -> Verification -> Project/doc closure -> Owner Doc`

## Use this skill when

- an Issue is stale, malformed, or too large
- `Source Anchors` are wrong, missing, or too broad
- docs changed and the Issue no longer matches them
- the work is partially delivered already
- an open Issue is already satisfied by merged code/docs
- a closed Issue still has active-work labels
- an Issue or PR has false or missing Project status
- a closed PR is still blank or active in the Project
- owner-doc writeback or roadmap cleanup is missing after delivery
- Issue state, PR state, labels, and Project state disagree
- the request touches Core Runtime <-> Agentic Lab boundary moves or operator-facing defaults
- the same repair should be batched across several drifted items instead of handled as isolated micro-fixes
- board hygiene, retro markers, owner-doc cleanup, and adoption observation are maintenance follow-ups, not default blockers for delivered repo-verifiable scope

## Authority and entry points

- Read `AGENTS.md` first (repo builder-agent policy).
- For boundary moves, treat `docs/CORE_RUNTIME_AGENTIC_LAB_BOUNDARY.md` as the governing change-control contract.
- Use `docs/DOCS_INDEX.md` to find owner docs for any affected surfaces.
- For maintenance runs, also read `docs/development/GITHUB_GOVERNANCE_SETUP.md` or `.github/github-governance.yml` so Issue/PR Project status is reconciled to the repo governance contract rather than left to best-effort automation drift.

## Core rules

- GitHub Issue is the canonical task contract.
- Issue state, truthful agent labels, linked PR state, and merge/delivery reality are the lifecycle authority.
- GitHub Project is the shared operating board and lifecycle projection, not a stronger authority than Issue/PR truth.
- Closed work must not remain in active queue states.
- Correct Project drift opportunistically, but do not block delivery solely because a personal Project v2 board cannot be updated.
- Do not invent strategy.
- Preserve traceability through `Source Anchors`.
- Prefer batched maintenance actions for repeated drift patterns; reserve single-item churn for cases where the items genuinely differ.
- Delivered, repo-verifiable parent scope should not stay open only for future adoption or retro observation.

## Canonical lifecycle expectations

- Open backlog work should be present in the Project.
- Open implementation Issues should normally carry exactly one truthful agent-state label.
- Active implementation work should not remain `Ready`.
- If Project state disagrees with Issue state, PR state, or merged delivery reality, correct the Project projection to match the harder lifecycle truth.
- Closed Issues must not retain `agent:ready`, `agent:blocked`, or `agent:needs-human`.
- If repo reality satisfies the Issue, the Issue and Project state should reflect that.

### Lifecycle truth matrix

The canonical matrix lives at `.codex/skills/_shared/LIFECYCLE_TRUTH_MATRIX.md` — Project Status must match content state for both Issues and PRs; every other cell is drift and must be corrected. This skill owns the reconciliation procedure that applies it; the matrix itself (including the review-requested `Review` semantics settled by #1806) is defined once in the shared file.

### Drift patterns that must be flagged explicitly

These are the high-frequency drift patterns that are easy to miss. A maintenance run is not complete until all have been audited:

- **Merged/closed PRs stuck in `Review` or `In Progress`** — stale handoff state on terminal work. "Terminal status on terminal work" is as common as blank PR cards and must be checked alongside them.
- **Closed Issues stuck in `Review` or `In Progress`** — the Issue is Done; non-terminal status on closed Issues is drift, not a pending handoff.
- **Open `agent:ready` Issues not in `Ready`** — the queue is lying about what is pickable. The `agent:ready ↔ Status=Ready` binding is a post-condition, not just a declarative rule.
- **PRs with no Project Status (blank / not in Project)** — the board cannot reflect lifecycle if the PR isn't represented at all. Open and closed PRs both need Project entries.
- **Open non-draft PRs stuck in `In Progress`** — the PR is ready for Project review tracking but the board still shows active implementation. Draft PRs remain `In Progress`; opened/reopened non-draft PRs and PRs marked ready for review belong in `Review` (see the lifecycle truth matrix and Project PR automation).

## Change-control checklist (Core Runtime <-> Agentic Lab)

Before coding, ensure the Issue explicitly states:

- Direction: `Agentic Lab -> Core Runtime` or `Core Runtime -> Agentic Lab`
- Exact module(s)/paths being moved (file paths or module area names)
- Default posture impact (defaults unchanged vs changed; flags/profiles required)
- Operator-facing contract impact (startup flows, settings, panel actions, event/outbox, knowledge boundary)
- Verification anchors: which SoT docs are being treated as authoritative for this change
- Test plan: what regression/boundary tests will prove no silent default flips

If any of the above is ambiguous, do not code. Keep the Issue `agent:needs-human`.

## Checks to perform

1. **Project-state audit:** bucket every Project item by (`content.state`, `Status`) and list every cell that violates the lifecycle truth matrix. This is the authoritative drift set for the run; nothing below may proceed on the assumption the board is clean until this audit is produced.
2. Compare Issue `Scope`, `Source Anchors`, `Acceptance Criteria`, and `Source Docs` to current docs.
3. Compare the Issue to open, merged, and closed PRs and repo reality.
4. Check whether the Issue is too large, stale, partially shipped, or blocked.
5. Check whether labels and Project state still match reality (driven by check 1's drift set).
6. Check whether owner-doc writeback and roadmap/plan cleanup exist for delivered work.
7. For feature-breakdown issue waves, distinguish parent feature issues from child slice issues before changing labels.
8. If a child issue delegates its contract to a `Source contract` spec file instead of carrying the standard issue sections, verify whether the spec is already merged and reachable; if the spec is not merged/reachable and the issue body lacks the required local contract sections, do not mark it `agent:ready`.
9. Check acceptance verifiability: every `Acceptance Criterion` must carry a `Verify:` marker naming a test (behavioral) or a concrete doc/receipt target (non-behavioral). ACs without a resolvable `Verify:` target are a malformed contract shape.

## Allowed corrective actions

- rewrite Issue body to match current bounded work
- add or fix `Source Anchors`
- add missing `Verify:` markers to ACs, or rewrite ACs that cannot carry one (refine, split, or route back to `docs-to-issue` / `feature-breakdown` for re-specification)
- split oversized work into replacement Issues
- close duplicate or superseded Issues
- close delivered Issues
- add missing Issues/PRs to the Project
- move Project status to `Backlog`, `Ready`, `In Progress`, `Review`, or `Done`
- resolve closed terminal PR cards to `Done`
- remove stale labels that contradict lifecycle reality
- relabel with the canonical taxonomy from `.codex/skills/_shared/LABEL_TAXONOMY.md` only

When closing stale or duplicate open issues:

- leave an explicit maintenance receipt comment naming the canonical delivered Issue/PR replacing the open backlog item
- if an equivalent slice already shipped under a different Issue number, say so directly (`superseded by delivered canonical issue #...`)
- after closure, re-read the issue labels and remove any lingering `agent:*` label that automation did not clear
- do not leave an issue closed-but-blocked or closed-but-ready

## Lifecycle correction rules

**All state corrections must be executed using explicit commands, not just recommended.**

### Action: Close Delivered Issue

If an Issue is closed (already delivered):

1. **Remove all agent labels:**
   ```bash
   gh issue edit #<N> --remove-label agent:ready --remove-label agent:blocked --remove-label agent:needs-human
   ```

2. **Set Project Status to Done:** run the Set Project Status mutation from `.codex/skills/_shared/PROJECT_STATUS_OPERATIONS.md` with the `Done` option ID.

3. **Verify:**
   ```bash
   gh issue view #<N> --json state,labels,projectItems
   ```

### Action: Close Stale Duplicate or Superseded Issue

If an open issue is no longer the truthful backlog item because an equivalent slice already shipped under a canonical replacement issue/PR:

1. **Leave a maintenance receipt comment:**
   ```bash
   gh issue comment #<N> --body "Maintenance reconciliation: this issue is superseded by delivered canonical issue #<M> / PR #<P> ..."
   ```

2. **Close the stale issue:**
   ```bash
   gh issue close #<N> --reason completed
   ```

3. **Re-check terminal truth and strip lingering agent labels if needed:**
   ```bash
   gh issue view #<N> --json state,labels
   gh issue edit #<N> --remove-label agent:ready --remove-label agent:blocked --remove-label agent:needs-human
   gh issue view #<N> --json state,labels
   ```

4. **Only then treat the dedupe as complete.**

### Action: Malformed or Stale Open Issue

If an open implementation Issue is malformed, stale, or no longer safely executable:

1. **Add needs-human label:**
   ```bash
   gh issue edit #<N> --add-label agent:needs-human --remove-label agent:ready --remove-label agent:blocked
   ```

2. **Set Project Status to Backlog (non-active):** run the Set Project Status mutation from `.codex/skills/_shared/PROJECT_STATUS_OPERATIONS.md` with the `Backlog` option ID.

3. **Post comment with required action**

### Maintenance path versus hot path

- Hot path: active implementation work that is ready to be picked up and executed by an agent.
- Maintenance path: repairs, audits, reconciliation, and cleanup that exist to restore truth in docs, issues, projects, or receipts.
- If the task is on the maintenance path, do not force it into `agent:ready` just to make it look executable.

### Action: Issue Delivered but Still Open

If delivered work is still open because traceability is ambiguous:

1. **Prefer `agent:needs-human`** over false `agent:ready`
2. **Execute label and status corrections** per "Malformed or Stale Open Issue" above
3. **Leave a comment** explaining what action is needed for closure

### Parent Feature Issues

Parent feature issues are validation hubs, not direct pickup issues. Unless explicitly scoped as a single executable slice:

1. **Keep them non-active:**
   ```bash
   gh issue edit #<PARENT> --add-label agent:blocked --remove-label agent:ready --remove-label agent:needs-human
   gh api graphql ... (set Project Status to Backlog)
   ```

2. **Use them to track child slice delivery** in comments and body updates, including validation receipts posted by each delivered child
3. **When the parent is fully repo-verifiable and only future observation remains, close it and move that observation to a BuilderOps `LearningSignal`, `PromotionIntent`, discard/supersession receipt, or a follow-up GitHub Issue when it is executable work**

### Child Slice Issues

Child slice issues may become `agent:ready` only when their executable contract is concrete and available:

1. **If contract lives in an open spec PR:** keep the child issue non-active (`agent:blocked` or `agent:needs-human`) until the spec merges or the issue is rewritten with required local contract sections

2. **If contract is concrete and merged:** can label as `agent:ready` with `Status=Ready`
3. **Child issues should form an execution chain**: each delivered child should post a validation receipt to the parent issue, and the final child must include a parent-closure handoff or create/link an explicit parent-closure issue before the parent is closed.

## Quick Reference: Maintenance State Corrections

| Condition | Action | Issue Labels | Issue Status | Notes |
|-----------|--------|-------------|-------------|-------|
| Issue closed | Execute Close Delivered | -agent:* | Done | Remove all agent labels |
| Malformed/stale open | Execute Malformed/Stale | +agent:needs-human | Backlog | Non-active state |
| Delivered but open | Execute Delivered Open | +agent:needs-human | Backlog | Comment explaining next step |
| Parent feature | Keep non-active | +agent:blocked | Backlog | Validation hub, waiting on child chain |
| Child with spec in PR | Keep non-active | +agent:blocked | Backlog | Wait for spec merge |
| Child with concrete contract | Can label ready | +agent:ready | Ready | Only when merged and clear |

## When splitting

- preserve the original doc intent
- create bounded child Issues
- keep `Source Anchors` local and deterministic
- state dependency order explicitly

## When marking delivered

- confirm a PR or merged commit satisfies the Acceptance Criteria
- ensure owner-doc writeback exists or create a follow-up
- ensure roadmap/plan wording no longer reads as pending
- ensure Project status and labels are terminal and truthful
- produce a delivery receipt
- for duplicate/superseded closures, ensure the delivery receipt points to the canonical delivered issue/PR rather than only saying “duplicate”
- do not keep a delivered parent issue open solely for future adoption or retro observation
- if the parent is the final child slice, follow `docs/development/PARENT_ISSUE_CLOSURE.md` and ensure the final child includes a parent-closure handoff or explicit parent-closure issue

## Required Issue contract shape

Use the canonical task-contract sections from `.codex/skills/_shared/ISSUE_CONTRACT.md` for any updated or new Issue (including the `## Applies learning (optional)` rule defined there).


## Capturing learning

**Capturing learning:** if during this work you notice a divergence from plan — you did something you did not expect to do, or discovered an earlier artifact was wrong — route it through `capture-learning`, which owns the invocation timing: invoke immediately only when the divergence needs upstream repair now; otherwise note the signal for `learning-retrospective`. Only log if you can name an upstream artifact that could absorb the fix.

## Output format

Lead with the human summary; include later sections only when they have content (`docs/development/GOVERNANCE_PROPORTIONALITY.md`).

1. Summary For The Human (2–4 sentences: what was corrected, what remains, what needs a decision)
2. Issue State Assessment
3. Required Corrections
4. Updated / Replacement Issue Contracts
5. Project / Label Changes
6. Receipts

## Output expectations

- A corrected/created Issue that a builder can execute.
- A short receipt: Issue number, labels, and Project Status.

## Fast maintenance run (open issues)

Use this when the user asks for a maintenance run across everything not done.

1. Resolve repo:
   - If repo not given, ask for `owner/repo`.
   - If user says they are the owner, resolve the username via GitHub app `list_installed_accounts` and use that as owner.
2. **Pre-flight Project-state audit.** Before any label edits or helper scripts, query every Project item and bucket it by (`content.state`, `Status`). Flag every cell that violates the lifecycle truth matrix. This audit is independent of any reconciliation helper and must be executed directly via GraphQL:

   ```bash
   gh api graphql -f projectId="$PROJECT_ID" -f query='
     query($projectId:ID!, $cursor:String) {
       node(id: $projectId) {
         ... on ProjectV2 {
           items(first: 100, after: $cursor) {
             pageInfo { hasNextPage endCursor }
             nodes {
               id
               content {
                 __typename
                 ... on Issue { number state }
                 ... on PullRequest {
                   number state isDraft mergedAt
                   reviewRequests { totalCount }
                 }
               }
               fieldValues(first: 20) {
                 nodes {
                   __typename
                   ... on ProjectV2ItemFieldSingleSelectValue {
                     field { ... on ProjectV2SingleSelectField { name } }
                     name
                   }
                 }
               }
             }
           }
         }
       }
     }
   '
   ```

   Paginate until `hasNextPage` is false. Then bucket items by `(state, status)` and list every cell that is not allowed by the matrix. The resulting list is the authoritative drift set for this run — nothing else may claim the board is clean until every entry in this set has been corrected.

3. List open issues:
   - Prefer GitHub app for structured data when possible.
   - For bulk edits, use `gh issue list --state open --json number,title,labels,body,comments` for full bodies and blocker context.
4. For each open issue:
   - Establish issue/PR truth before deciding labels:
     - inspect recent comments for acceptance failures, blocker receipts, and follow-up issue links
     - inspect linked open PRs and closing references
     - inspect linked blocker or follow-up issues that change executability
     - identify whether the issue is a parent feature validation hub or a child slice
     - if the issue delegates to a `Source contract` spec file, confirm that the target spec exists on the target branch and is not only present in an open PR
   - If body already matches the contract shape exactly, do not rewrite it.
   - If contract shape is missing or malformed, edit the issue to match the required sections.
   - If many related issues share the same contract-shape problem, do not bulk-rewrite them blindly; report the pattern, pick a correction policy, and apply it consistently.
   - **Execute label corrections** from established issue/PR truth before any Project reconciliation:
     ```bash
     # Example: set to ready if criteria are concrete
     gh issue edit #<N> --add-label agent:ready --remove-label agent:blocked --remove-label agent:needs-human
     # OR: set to needs-human if ambiguous or boundary move
     gh issue edit #<N> --add-label agent:needs-human --remove-label agent:ready --remove-label agent:blocked
     # OR: set to blocked if external dependency exists
     gh issue edit #<N> --add-label agent:blocked --remove-label agent:ready --remove-label agent:needs-human
     ```
     - Add `agent:ready` only if Scope/Constraints/Acceptance Criteria are concrete and no ambiguity remains.
     - Do not add or preserve `agent:ready` when any AC lacks a resolvable `Verify:` marker.
     - Do not add or preserve `agent:ready` when recent comments, linked PRs, or linked blocker/follow-up issues show the Issue is blocked, already active, or waiting on validation.
     - Do not add or preserve `agent:ready` when a child issue's executable contract exists only in an unmerged spec PR.
     - Keep or set `agent:needs-human` for boundary moves without explicit direction or module paths.
     - Keep or set `agent:blocked` when external dependencies are stated.
   
   - **Execute Project state reconciliation** for each open issue only after labels are corrected: run the Set Project Status mutation from `.codex/skills/_shared/PROJECT_STATUS_OPERATIONS.md` — `agent:ready` → `Ready` option ID; `agent:blocked` or `agent:needs-human` → `Backlog` option ID.
     - If the issue is missing from the Project or missing `Status`, add/reconcile it during the same run
5. **Execute Deduplication:**
   - If duplicate issues have the same scope/contract:
     ```bash
     gh issue comment #<DUPLICATE> --body "Duplicate of #<CANONICAL>. Closing in favor of canonical issue."
     gh issue close #<DUPLICATE>
     ```
   - Remove all agent labels from closed duplicate:
     ```bash
     gh issue edit #<DUPLICATE> --remove-label agent:ready --remove-label agent:blocked --remove-label agent:needs-human
     ```

6. **Reconcile terminal work stuck in non-terminal status** (expanded from "blank PR cards"):
   - The pre-flight audit (step 2) should have surfaced these, but enumerate them explicitly here to prevent silent skips.
   - Terminal work is: merged PRs, closed PRs (unmerged), closed Issues.
   - Any of the above sitting in `In Progress`, `Review`, `Backlog`, `Ready`, or with no Status is drift.
   - Set each to `Done`: run the Set Project Status mutation from `.codex/skills/_shared/PROJECT_STATUS_OPERATIONS.md` with the `Done` option ID.
   - Do not limit this step to "blank" cards. Stale `In Progress` / `Review` on merged or closed items is as common as missing status and is equally drift.

7. **Reconcile open PR Project status** against the lifecycle truth matrix:
   - Open Draft PRs → `In Progress`
   - Open non-Draft PRs with review explicitly requested → `Review`
   - Open non-Draft PRs without review requested → `Review`
   - Open PRs missing from the Project entirely → add them, then apply the row above

8. **Reconciliation helper (optional, with known gaps).** If the repo has a reconciliation helper (for example `scripts/reconcile_project_status.py`), run it after steps 2, 6, and 7 as a belt-and-braces pass — not as the primary mechanism.
   - Prefer targeted calls first (one issue/PR per invocation), then optional scan:
     ```bash
     python3 scripts/reconcile_project_status.py --repo <owner/repo> --owner @me --issue <N>
     python3 scripts/reconcile_project_status.py --repo <owner/repo> --owner @me --pr <N>
     # Optional sweep after targeted corrections:
     python3 scripts/reconcile_project_status.py --repo <owner/repo> --owner @me --scan
     ```
   - Why `--owner @me`: user-owned projects are less flaky than explicit login owner resolution in `gh project` flows.
   - The helper now retries transient `gh project` failures (including `unknown owner type`) with bounded backoff, but it is still secondary to the explicit lifecycle mutations above.
   - Known gaps in common helpers:
   - They typically reconcile Issue-label → Status drift only
   - They may not reconcile PR lifecycle state (merged/closed/draft)
   - They may not correct non-terminal Status on terminal work (e.g. merged PR in `Review`)
   - Do not treat a helper's "N change(s)" output as complete. If the pre-flight audit in step 2 counted more drift than the helper reported, the helper did not close the gap and manual mutations are required.

9. If Project v2 writes fail because of GraphQL rate limits or credentials, stop Project mutation attempts for that run:
   - do not retry with ad hoc partial mutations
   - output the exact pending status changes that were not applied
   - output the rate-limit reset time when available
   - state that Issue/PR truth remains authoritative until Project reconciliation can resume

10. **Post-condition verification.** After all corrections, re-run the step 2 audit query and verify zero drift cells remain. Specifically check:
    - Every `agent:ready` open Issue is in `Status=Ready`
    - Every `agent:blocked` / `agent:needs-human` open Issue is in `Status=Backlog`
    - Every closed Issue is in `Status=Done`
    - Every merged / closed PR is in `Status=Done`
    - Every open Draft PR is in `Status=In Progress`
    - Every open non-Draft PR with review explicitly requested is in `Status=Review`
    - Every open non-Draft PR without review requested is in `Status=Review`
    - Zero Project items are in `NO_STATUS`
    If any drift remains, the run is not complete — fix before writing the receipt.

11. Output a receipt listing edited issues, label changes, issue status changes, PR status changes, and the before/after drift counts from step 2 and step 10.
