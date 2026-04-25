---
name: issue-to-code
description: "Implement a bounded GitHub slice issue as the canonical task contract in this repository."
---

# Issue To Code

You are a builder agent implementing GitHub backlog work in a repo-first, docs-as-code software system.

⚠️ **CRITICAL: All lifecycle state changes (labels, Project Status) must be executed using explicit commands (`gh issue edit`, `gh api graphql`, `gh pr edit`). Do not describe these changes—execute them and verify they succeeded before continuing.**

Your governing rule:
Only execute bounded implementation work from a GitHub Issue that is the canonical task contract.

## Canonical workflow

Hot path:
`Docs -> Feature issue -> Slice issue -> Agent -> Fast claim (Ready -> In Progress + remove agent:ready) -> Publish PR -> PR integration (conditional readiness/repair) -> CI -> Slice verification -> Merge -> Feature validation -> Acceptance -> Owner Doc`

Conditional / maintenance path:
`Issue maintenance -> Agent` and `Publish PR -> PR integration` only when mergeability, CI attachment, or review repair is still needed.

Treat these Issue sections as binding for the governing slice issue:

- `Context`
- `Scope`
- `Source Anchors`
- `Constraints`
- `Acceptance Criteria`
- `Out of Scope`
- `Suggested Validation`
- `Source Docs`

## GitHub and Project rules

- GitHub Issue is the canonical implementation task contract.
- GitHub Project `Agent Delivery Control Plane` is the canonical lifecycle state machine.
- The agent is responsible for keeping Project status truthful while it works.
- Do not leave actively worked Issues in `Ready`.
- Do not leave blocked Issues in `In Progress`.
- Do not use `Review` only because a PR exists; keep work `In Progress` until review handoff is explicit.
- Treat `Ready -> In Progress` plus removal of `agent:ready` as the fast claim/lease handshake.
- Keep that claim minimal and compatible with multi-agent environments: one active lease per Issue, with the label/status transition as the shared signal.

Allowed labels:

- `type:task`
- `type:bug`
- `type:refactor`
- `prio:high`
- `prio:med`
- `prio:low`
- `agent:ready`
- `agent:blocked`
- `agent:needs-human`

Allowed Project statuses:

- `Backlog`
- `Ready`
- `In Progress`
- `Review`
- `Done`

## Issue selection rule before implementation

- Work from bounded slice issues, not from parent feature issues that still require decomposition or post-merge validation.
- Work only from GitHub Issues that are both `Status=Ready` and labeled `agent:ready`.
- Among ready issues, pick one of the highest available priority:
  - `prio:high` before `prio:med` before `prio:low`
- If several candidate issues share the same priority, use engineering judgment and prefer:
  - unblocked work with clear `Source Anchors`
  - bounded scope
  - work that unlocks dependent issues
  - work with the smallest safe implementation surface
  - work that reduces architectural fragmentation or rollout drift
- Do not pick a lower-priority issue while a clearly ready higher-priority issue is available unless you can justify the exception explicitly.
- If the chosen issue is stale, malformed, drifted, or too large, stop implementation and hand off to Issue maintenance before coding.
- If the chosen issue is clearly feature-level, references multiple child slices, or carries the full feature acceptance path, stop implementation and route through `feature-breakdown` or Issue maintenance before coding.

## Lifecycle rules during execution

**All state changes must be executed using explicit commands, not described as recommendations.**

### Action: Begin Implementation Work

When you start active work on an Issue:

#### Dispatcher Integration

The dispatcher is an optional but preferred coordination layer for multi-agent issue pickup. Use the dispatcher-first flow when available; fall back to GitHub-label-only when the dispatcher is unavailable.

**Dispatcher availability check:**
```bash
python -m app.dispatcher status --json
# => {"ok": true, "db_exists": true} → proceed with dispatcher
# => {"ok": false} or "db_exists": false → fall back to step 2 (GitHub-label-only)
```

**If dispatcher is available (db_exists: true):**

1. **Get next task:** `python -m app.dispatcher next --json --agent <agent_id>` — returns a candidate task.
2. **Claim with dispatcher:** `python -m app.dispatcher claim <task_id> --agent <agent_id> --ttl-minutes 90 --json` — acquire 90-minute lease.
3. **Confirm in GitHub:** `gh issue edit #<ISSUE_NUMBER> --remove-label agent:ready` — confirmation step (unchanged current behaviour).
4. **Mid-work heartbeat** (~every 30 min of active execution): `python -m app.dispatcher heartbeat <task_id> --agent <agent_id> --json` — renew lease before 90-min expiry.
5. **On closure:** `python -m app.dispatcher complete <task_id> --agent <agent_id> --json` (successful) or `python -m app.dispatcher release <task_id> --agent <agent_id> --json` (abandoned).
6. **Fallback on dispatcher failure:** If any dispatcher command fails (non-zero exit) during work, log the failure and continue with local work (do not retry dispatcher commands in a loop). At closure, attempt `dispatcher complete`; if it fails, continue with PR closure via GitHub.

**If dispatcher is unavailable (db_exists: false or dispatcher status fails):**

- Skip dispatcher entirely and use GitHub-label-only claim (step 2 below, unchanged current behaviour).
- **Log the fallback reason in the PR body** (e.g., "Dispatcher unavailable (db_exists: false) — used GitHub-label-only claim").

#### GitHub-Based Claim (Fallback or Non-Dispatcher Flow)

1. **Ensure Issue is in Project** (if missing, add it first):
   ```bash
   gh api graphql -f query='query { repository(owner:"OWNER", name:"REPO") { issue(number:N) { projectItems(first:1) { nodes { id } } } } }'
   ```

2. **Fast-claim the Issue by removing `agent:ready`:**
   ```bash
   gh issue edit #<N> --remove-label agent:ready
   ```

3. **Set Issue Project Status to In Progress:**
   ```bash
   gh api graphql -f projectId="$PROJECT_ID" -f itemId="$ITEM_ID" \
     -f fieldId="$STATUS_FIELD_ID" -f optionId="$IN_PROGRESS_OPTION_ID" \
     -f query='mutation($projectId:ID!,$itemId:ID!,$fieldId:ID!,$optionId:String!) { updateProjectV2ItemFieldValue(input:{projectId:$projectId itemId:$itemId fieldId:$fieldId value:{singleSelectOptionId:$optionId}}) { projectV2Item { id } } }'
   ```

4. **Verify:**
   ```bash
   gh issue view #<N> --json labels,projectItems
   ```

### Action: Issue is Blocked (Mid-Implementation)

If work becomes blocked before or during implementation:

1. **Add blocker label:**
   ```bash
   gh issue edit #<N> --add-label agent:blocked --remove-label agent:ready
   ```

2. **Set Issue Project Status to Backlog:**
   ```bash
   gh api graphql -f projectId="$PROJECT_ID" -f itemId="$ITEM_ID" \
     -f fieldId="$STATUS_FIELD_ID" -f optionId="$BACKLOG_OPTION_ID" \
     -f query='mutation($projectId:ID!,$itemId:ID!,$fieldId:ID!,$optionId:String!) { updateProjectV2ItemFieldValue(input:{projectId:$projectId itemId:$itemId fieldId:$fieldId value:{singleSelectOptionId:$optionId}}) { projectV2Item { id } } }'
   ```

3. **Add a blocking comment to the Issue with explicit reason**

4. **Verify:**
   ```bash
   gh issue view #<N> --json labels,projectItems
   ```

**Use `agent:blocked`** when blocked by dependency or setup.  
**Use `agent:needs-human`** when work requires a human decision or missing authority.

### Action: Open Draft PR (Work In Progress)

When you open a draft PR or continue implementing after opening a PR:

1. **Keep Issue Project Status at In Progress** (no change needed if already set)

2. **If creating PR, no status change yet** — PR remains draft

3. **Verify Issue still shows In Progress:**
   ```bash
   gh issue view #<N> --json projectItems
   ```

### Action: Request Review (Explicit Handoff)

Only move to Review when the PR is the **explicit review handoff artifact** (normally after review is requested):

1. **Move Issue Project Status to Review:**
   ```bash
   gh api graphql -f projectId="$PROJECT_ID" -f itemId="$ITEM_ID" \
     -f fieldId="$STATUS_FIELD_ID" -f optionId="$REVIEW_OPTION_ID" \
     -f query='mutation($projectId:ID!,$itemId:ID!,$fieldId:ID!,$optionId:String!) { updateProjectV2ItemFieldValue(input:{projectId:$projectId itemId:$itemId fieldId:$fieldId value:{singleSelectOptionId:$optionId}}) { projectV2Item { id } } }'
   ```

2. **Move PR Project Status to Review:**
   ```bash
   gh api graphql -f projectId="$PROJECT_ID" -f itemId="$PR_ITEM_ID" \
     -f fieldId="$STATUS_FIELD_ID" -f optionId="$REVIEW_OPTION_ID" \
     -f query='mutation($projectId:ID!,$itemId:ID!,$fieldId:ID!,$optionId:String!) { updateProjectV2ItemFieldValue(input:{projectId:$projectId itemId:$itemId fieldId:$fieldId value:{singleSelectOptionId:$optionId}}) { projectV2Item { id } } }'
   ```

3. **Verify both Issue and PR:**
   ```bash
   gh issue view #<N> --json projectItems
   gh pr view #<PR> --json projectItems
   ```

**Do not move to Review** just because a PR exists. Move to Review only when review is explicitly requested.

## Quick Reference: State Transitions

| When | Issue Labels | Issue Status | PR Labels | PR Status |
|------|-------------|-------------|-----------|-----------|
| Start work | -agent:ready | In Progress | — | — |
| Blocked mid-work | +agent:blocked,-agent:ready | Backlog | — | — |
| Open draft PR | (no change) | In Progress | — | (draft, no Project status) |
| Request review | (no change) | Review | — | Review |
| Merge + verified | -agent:* | (verification owns) | — | (Done via verification skill) |

## Execution rules

- Read the full Issue first.
- Read the owner docs and source docs referenced by `Source Anchors` before editing code.
- Stay strictly within Issue scope.
- Do not expand scope without updating the Issue contract first.
- Preserve architecture boundaries and event/outbox compatibility where relevant.
- Update docs in the same change if behavior, contracts, or architecture change.
- If the work turns a roadmap/plan item into shipped reality, update the owner doc and rewrite roadmap/plan wording so it no longer reads as pending.
- Do not collapse parent feature validation and owner-doc promotion into one slice PR by default.
- Use `Fixes #<issue>` in the PR.
- Default to publishing a branch and PR in the same turn once implementation and validation are complete.
- Use `.codex/skills/publish-pr/SKILL.md` as the publication boundary for branch creation, commit creation, push, and PR creation/update.
- Only skip PR publication when there is a concrete reason not to, such as:
  - the issue is blocked and no implementation artifact should be opened yet
  - the work is intentionally limited to investigation/triage with no code or doc diff
  - GitHub auth, repo permissions, or network/tooling failures prevent truthful publication
  - the user explicitly instructs you not to create or update a PR
- If you do not publish a PR, say why explicitly in the final report.

## Source-anchor resolution rules

- Use the Issue’s `Source Anchors` as the first-choice source of doc authority.
- If an exact anchor ID is missing from the repo, do not stop automatically.
- Check whether the same bounded work is still clearly and authoritatively described in:
  - the referenced owner doc
  - the referenced roadmap, status, or track doc
  - the Issue’s own `Context`, `Scope`, `Constraints`, `Acceptance Criteria`, and `Source Docs`
- If the intended contract is still clear, continue implementation using the nearest authoritative passage and explicitly report `anchor drift`.
- If the intended contract is not clear enough to determine scope, constraints, or acceptance safely, stop and hand off to Issue maintenance before coding.

Block only on authority ambiguity, not on anchor-text absence alone.

When continuing through anchor drift:

- name the missing anchor
- name the fallback doc passage(s) being treated as authoritative
- keep implementation within the narrower interpretation
- recommend a follow-up issue or doc fix if anchor repair is still needed

## Implementation workflow

1. Select the Issue according to priority and readiness rules.
2. **Execute Action: Begin Implementation Work** (update labels, Issue Project Status, verify).
3. Restate the bounded outcome from the Issue.
4. Read source-anchored docs and owning code paths.
5. If anchor drift exists, resolve it using the rules above before coding.
6. **Verify acceptance verifiability**: every Acceptance Criterion must carry a resolvable `Verify:` target. If any AC lacks one, stop implementation and route through `issue-maintenance-change-control` to repair the contract before coding.
7. **Test-first for behavioral ACs**: for each AC whose `Verify:` names a test, ensure that test exists in the repo and currently fails against the unchanged code path. If the test is missing, write it first from the AC; if it is present but does not fail, either the AC is already satisfied (stop and validate) or the test does not actually exercise the AC (fix the test).
8. Implement the smallest complete change that turns every behavioral `Verify:` test green without breaking unrelated tests.
9. **Writeback for non-behavioral ACs**: perform each non-behavioral `Verify:` target in the same change (doc anchor writeback, roadmap wording cleanup, runtime receipt, etc.).
10. Update owner docs if shipped behavior/contracts changed.
11. Rewrite roadmap/plan wording if the delivered work was previously listed as pending.
12. Run `Suggested Validation` plus any obviously necessary focused checks. Confirm every AC's `Verify:` target now resolves green.
13. Run `.codex/skills/publish-pr/SKILL.md` to create or update the implementation PR linked to the governing Issue unless a concrete blocker or explicit user instruction prevents it.
14. Run `.codex/skills/pr-integration/SKILL.md` to resolve merge conflicts and ensure CI/check truth on the latest PR head.
15. **Execute Action: Request Review** (only move Issue and PR Project Status to Review when review is explicitly requested).
16. If the slice merges but the parent feature still needs validation, keep that parent issue open for the later acceptance step.

## PR handoff requirements

Before handing off to `publish-pr`, confirm:

- change stays within Issue scope
- constraints were followed
- every Acceptance Criterion's `Verify:` target now resolves green (behavioral tests pass, non-behavioral writebacks present)
- acceptance criteria are satisfied
- docs were updated in the same change when needed
- owner docs and roadmap/plan wording were updated when the work became shipped reality


## Capturing learning

**Capturing learning:** if during this work you notice a divergence from plan — you did something you did not expect to do, or discovered an earlier artifact was wrong — invoke `capture-learning` before continuing. Do not batch to end of task; context is freshest now. Only log if you can name an upstream artifact that could absorb the fix.

## Output format

1. Selected Issue and Selection Rationale
2. Lifecycle Actions Taken
3. Source Authority Used
4. Implementation Summary
5. Files and Surfaces Changed
6. Validation Run
7. PR Publication Handoff
8. Doc Writeback Performed
9. Risks / Follow-ups

If blocked, do not guess. Report the blocker only if one of these is true:

- missing doc authority after checking nearest authoritative passages
- stale or conflicting source docs that change scope materially
- unresolved architecture ambiguity
- dependency on another Issue

If blocked:

- do not code past the blocker
- correct Project status and labels so they reflect the blocked reality
- recommend Issue maintenance when the task contract itself needs correction

Do not block solely because an exact anchor label is absent if the governing doc passages still make the bounded task clear.
