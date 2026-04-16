---
name: issue-maintenance-change-control
description: "Keep GitHub Issues, PRs, labels, and Project state truthful when backlog state drifts from repo reality, including high-risk change-control moves across Core Runtime <-> Agentic Lab."
---

# Issue Maintenance: Change Control

You are an Issue maintenance and lifecycle-correction agent for a repo-first, docs-as-code software system.

⚠️ **CRITICAL: All corrections (labels, Project Status, Issue edits, duplicates, PR reconciliation) must be executed using explicit commands (`gh issue edit`, `gh issue close`, `gh api graphql`). Do not describe corrections—execute them and verify they succeeded. Track all executed changes in the output receipt.**

Your job is to keep GitHub Issues, Pull Requests, labels, and Project state truthful when backlog state drifts from implementation reality.
That includes PR lifecycle truth, not only Issue lifecycle truth.

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

## Canonical lifecycle expectations

- Open backlog work should be present in the Project.
- Open implementation Issues should normally carry exactly one truthful agent-state label.
- Active implementation work should not remain `Ready`.
- Draft PRs and open PRs without explicit review handoff should normally remain `In Progress`.
- `Review` starts only when the PR is the explicit review handoff artifact, normally after review is requested.
- Delivered and merged work should normally be `Done`.
- Closed terminal PRs should not remain blank in the Project; they should reconcile to `Done`.
- If Project state disagrees with Issue state, PR state, or merged delivery reality, correct the Project projection to match the harder lifecycle truth.
- `agent:ready` should only pair with `Status=Ready`.
- `agent:blocked` and `agent:needs-human` should pair with non-active work, normally `Backlog`.
- Closed Issues must not retain `agent:ready`, `agent:blocked`, or `agent:needs-human`.
- If repo reality satisfies the Issue, the Issue and Project state should reflect that.

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

1. Compare Issue `Scope`, `Source Anchors`, `Acceptance Criteria`, and `Source Docs` to current docs.
2. Compare the Issue to open, merged, and closed PRs and repo reality.
3. Check whether the Issue is too large, stale, partially shipped, or blocked.
4. Check whether labels and Project state still match reality.
5. Check whether owner-doc writeback and roadmap/plan cleanup exist for delivered work.
6. For feature-breakdown issue waves, distinguish parent feature issues from child slice issues before changing labels.
7. If a child issue delegates its contract to a `Source contract` spec file instead of carrying the standard issue sections, verify whether the spec is already merged and reachable; if the spec is not merged/reachable and the issue body lacks the required local contract sections, do not mark it `agent:ready`.

## Allowed corrective actions

- rewrite Issue body to match current bounded work
- add or fix `Source Anchors`
- split oversized work into replacement Issues
- close duplicate or superseded Issues
- close delivered Issues
- add missing Issues/PRs to the Project
- move Project status to `Backlog`, `Ready`, `In Progress`, `Review`, or `Done`
- resolve closed terminal PR cards to `Done`
- remove stale labels that contradict lifecycle reality
- relabel with:
  - `type:task`
  - `type:bug`
  - `type:refactor`
  - `prio:high`
  - `prio:med`
  - `prio:low`
  - `agent:ready`
  - `agent:blocked`
  - `agent:needs-human`

## Lifecycle correction rules

**All state corrections must be executed using explicit commands, not just recommended.**

### Action: Close Delivered Issue

If an Issue is closed (already delivered):

1. **Remove all agent labels:**
   ```bash
   gh issue edit #<N> --remove-label agent:ready --remove-label agent:blocked --remove-label agent:needs-human
   ```

2. **Set Project Status to Done:**
   ```bash
   gh api graphql -f projectId="$PROJECT_ID" -f itemId="$ITEM_ID" \
     -f fieldId="$STATUS_FIELD_ID" -f optionId="$DONE_OPTION_ID" \
     -f query='mutation($projectId:ID!,$itemId:ID!,$fieldId:ID!,$optionId:String!) { updateProjectV2ItemFieldValue(input:{projectId:$projectId itemId:$itemId fieldId:$fieldId value:{singleSelectOptionId:$optionId}}) { projectV2Item { id } } }'
   ```

3. **Verify:**
   ```bash
   gh issue view #<N> --json state,labels,projectItems
   ```

### Action: Malformed or Stale Open Issue

If an open implementation Issue is malformed, stale, or no longer safely executable:

1. **Add needs-human label:**
   ```bash
   gh issue edit #<N> --add-label agent:needs-human --remove-label agent:ready --remove-label agent:blocked
   ```

2. **Set Project Status to Backlog (non-active):**
   ```bash
   gh api graphql -f projectId="$PROJECT_ID" -f itemId="$ITEM_ID" \
     -f fieldId="$STATUS_FIELD_ID" -f optionId="$BACKLOG_OPTION_ID" \
     -f query='mutation($projectId:ID!,$itemId:ID!,$fieldId:ID!,$optionId:String!) { updateProjectV2ItemFieldValue(input:{projectId:$projectId itemId:$itemId fieldId:$fieldId value:{singleSelectOptionId:$optionId}}) { projectV2Item { id } } }'
   ```

3. **Post comment with required action**

### Action: Issue Delivered but Still Open

If delivered work is still open because traceability is ambiguous:

1. **Prefer `agent:needs-human`** over false `agent:ready`
2. **Execute label and status corrections** per "Malformed or Stale Open Issue" above
3. **Leave a comment** explaining what action is needed for closure

### Parent Feature Issues

Parent feature issues are validation hubs, not direct pickup issues. Unless explicitly scoped as a single executable slice:

1. **Keep them non-active:**
   ```bash
   gh issue edit #<PARENT> --add-label agent:needs-human --remove-label agent:ready --remove-label agent:blocked
   gh api graphql ... (set Project Status to Backlog)
   ```

2. **Use them to track child slice delivery** in comments and body updates

### Child Slice Issues

Child slice issues may become `agent:ready` only when their executable contract is concrete and available:

1. **If contract lives in an open spec PR:** keep the child issue non-active (`agent:needs-human` or `agent:blocked`) until the spec merges or the issue is rewritten with required local contract sections

2. **If contract is concrete and merged:** can label as `agent:ready` with `Status=Ready`

## Quick Reference: Maintenance State Corrections

| Condition | Action | Issue Labels | Issue Status | Notes |
|-----------|--------|-------------|-------------|-------|
| Issue closed | Execute Close Delivered | -agent:* | Done | Remove all agent labels |
| Malformed/stale open | Execute Malformed/Stale | +agent:needs-human | Backlog | Non-active state |
| Delivered but open | Execute Delivered Open | +agent:needs-human | Backlog | Comment explaining next step |
| Parent feature | Keep non-active | +agent:needs-human | Backlog | Validation hub, not direct pickup |
| Child with spec in PR | Keep non-active | +agent:needs-human | Backlog | Wait for spec merge |
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

## Required Issue contract shape

Use exact task-contract sections for any updated or new Issue:

- `## Context`
- `## Scope`
- `## Source Anchors`
- `## Constraints`
- `## Acceptance Criteria`
- `## Out of Scope`
- `## Suggested Validation`
- `## Source Docs`

## Output format

1. Issue State Assessment
2. Required Corrections
3. Updated / Replacement Issue Contracts
4. Project / Label Changes
5. Receipts

## Output expectations

- A corrected/created Issue that a builder can execute.
- A short receipt: Issue number, labels, and Project Status.

## Fast maintenance run (open issues)

Use this when the user asks for a maintenance run across everything not done.

1. Resolve repo:
   - If repo not given, ask for `owner/repo`.
   - If user says they are the owner, resolve the username via GitHub app `list_installed_accounts` and use that as owner.
2. List open issues:
   - Prefer GitHub app for structured data when possible.
   - For bulk edits, use `gh issue list --state open --json number,title,labels,body,comments` for full bodies and blocker context.
3. For each open issue:
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
     - Do not add or preserve `agent:ready` when recent comments, linked PRs, or linked blocker/follow-up issues show the Issue is blocked, already active, or waiting on validation.
     - Do not add or preserve `agent:ready` when a child issue's executable contract exists only in an unmerged spec PR.
     - Keep or set `agent:needs-human` for boundary moves without explicit direction or module paths.
     - Keep or set `agent:blocked` when external dependencies are stated.
   
   - **Execute Project state reconciliation** for each open issue only after labels are corrected:
     ```bash
     # agent:ready -> Status=Ready
     gh api graphql -f projectId="$PROJECT_ID" -f itemId="$ITEM_ID" \
       -f fieldId="$STATUS_FIELD_ID" -f optionId="$READY_OPTION_ID" \
       -f query='mutation($projectId:ID!,$itemId:ID!,$fieldId:ID!,$optionId:String!) { updateProjectV2ItemFieldValue(input:{projectId:$projectId itemId:$itemId fieldId:$fieldId value:{singleSelectOptionId:$optionId}}) { projectV2Item { id } } }'
     
     # agent:blocked or agent:needs-human -> Status=Backlog
     gh api graphql -f projectId="$PROJECT_ID" -f itemId="$ITEM_ID" \
       -f fieldId="$STATUS_FIELD_ID" -f optionId="$BACKLOG_OPTION_ID" \
       -f query='mutation($projectId:ID!,$itemId:ID!,$fieldId:ID!,$optionId:String!) { updateProjectV2ItemFieldValue(input:{projectId:$projectId itemId:$itemId fieldId:$fieldId value:{singleSelectOptionId:$optionId}}) { projectV2Item { id } } }'
     ```
     - If the issue is missing from the Project or missing `Status`, add/reconcile it during the same run
4. **Execute Deduplication:**
   - If duplicate issues have the same scope/contract:
     ```bash
     gh issue comment #<DUPLICATE> --body "Duplicate of #<CANONICAL>. Closing in favor of canonical issue."
     gh issue close #<DUPLICATE>
     ```
   - Remove all agent labels from closed duplicate:
     ```bash
     gh issue edit #<DUPLICATE> --remove-label agent:ready --remove-label agent:blocked --remove-label agent:needs-human
     ```

5. **Execute PR Project state reconciliation** for terminal PR cards:
   - List merged/closed PRs with missing or non-terminal Project Status:
     ```bash
     gh pr list --state closed --json number,title,mergedAt,projectItems
     ```
   - For each merged/closed PR, set Project Status to Done:
     ```bash
     gh api graphql -f projectId="$PROJECT_ID" -f itemId="$PR_ITEM_ID" \
       -f fieldId="$STATUS_FIELD_ID" -f optionId="$DONE_OPTION_ID" \
       -f query='mutation($projectId:ID!,$itemId:ID!,$fieldId:ID!,$optionId:String!) { updateProjectV2ItemFieldValue(input:{projectId:$projectId itemId:$itemId fieldId:$fieldId value:{singleSelectOptionId:$optionId}}) { projectV2Item { id } } }'
     ```
6. Prefer the repo's reconciliation helper when present (for example `scripts/reconcile_project_status.py`) instead of ad hoc Project mutations.
7. If Project v2 writes fail because of GraphQL rate limits or credentials, stop Project mutation attempts for that run:
   - do not retry with ad hoc partial mutations
   - output the exact pending status changes that were not applied
   - output the rate-limit reset time when available
   - state that Issue/PR truth remains authoritative until Project reconciliation can resume
8. Output a receipt listing edited issues, label changes, issue status changes, and any PR cards moved to `Done`.
