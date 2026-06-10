---
name: issue-to-code
description: "Implement a bounded GitHub slice issue as the canonical task contract in this repository."
---

# Issue To Code

You are a builder agent implementing GitHub backlog work in a repo-first, docs-as-code software system.

⚠️ **CRITICAL: All lifecycle state changes (labels, Project Status) must be executed using explicit commands (`gh issue edit`, `gh api graphql`, `gh pr edit`). Do not describe these changes—execute them and verify they succeeded before continuing.**

Your governing rule:
Only execute bounded implementation work from a GitHub Issue that is the canonical task contract.
After PR creation or publish, route normal PRs to `docs/development/PR_HOT_PATH.md`.
Route only triggered cases to `docs/development/PR_ESCALATION_PATHS.md` or the heavier `pr-integration` path.
If the slice is the final child slice, route parent closure to `docs/development/PARENT_ISSUE_CLOSURE.md` after merge.
Bounded direct repair PRs may proceed without a governing Issue when the PR body supplies the full contract via a complete Direct Repair block.

## Pre-implementation classification check

Before claiming an Issue or producing any implementation, answer the following. Stop as indicated if the answer is unresolvable.

**Artifact class** — which class does this change produce or mutate?

- Human Knowledge Artifact (vault notes, plans, research)
- Agentic Memory Artifact (memory candidates, promoted memory)
- Machine Mirror Artifact (embeddings, index projections)
- Bridge / Assembly Artifact (context bundles, composite panels)
- Companion Metadata Note (`.meta.md` companions, frontmatter sidecars)
- Runtime state (outbox rows, dispatcher DB, watcher tick state)
- Governance-bearing state (GitHub labels, Project status, release pointer)

**Environment / channel risk** — which environment or release channel does this touch?

- `none / docs-only` — no runtime change
- `dev` — local dev environment, `app_dev` DB, alpha path
- `test` — test bootstrap, `app_test` DB, `vault-test/`
- `prod` — `app` DB, real vault, watcher execution, panel actions
- `stable promotion` — moving the `stable` pointer, irreversible migrations, prod process restart

**Stop conditions** — stop and resolve before coding if any of these is true:

- Authority boundary is unclear (plan/spec doc treated as shipped runtime without code/test evidence).
- Task touches `prod`, `stable`, migrations, vault paths, DSNs, or watcher execution without reading `docs/RELEASE_CHANNELS/README.md` and `docs/ENVIRONMENTS.md` first.
- Task depends on target-state or spec docs as shipped behavior but no code path, passing test, or owner-doc acceptance record confirms the behavior is live.
- Any Acceptance Criterion lacks a concrete `Verify:` target (a test pointer for behavioral ACs, a doc anchor / roadmap diff / runtime receipt for non-behavioral ACs).

Apply `docs/development/AGENT_OPERATING_PROTOCOL.md` for the full classification reference.

## Canonical workflow

Hot path:
`Docs -> Feature issue -> Slice issue -> Agent -> Fast claim (Ready -> In Progress + remove agent:ready) -> Publish PR -> PR integration (conditional readiness/repair) -> CI -> Slice verification -> Merge -> Feature validation -> Acceptance -> Owner Doc`

Conditional / maintenance path:
`Issue maintenance -> Agent` and `Publish PR -> PR integration` only when mergeability, CI attachment, or review repair is still needed.

## BuilderOps routing checkpoint

Before editing and again before PR handoff, decide whether the work produced BuilderOps material.
This is a required workflow checkpoint, not an optional memory aid.

- Raw handoff/recovery notes or temporary evidence that should survive the turn -> create an
  `AgentWorklog`.
- Plan/doc/skill/issue divergence that names an upstream artifact -> invoke `capture-learning` and
  create a `LearningSignal` immediately.
- Docs freshness observations or review queues -> create a `DocsFreshnessRecord`.
- Roadmap execution movement, active blockers, shipped refs, or issue movement that is operational
  rather than strategic roadmap truth -> create a `RoadmapExecutionItem`.
- Material that should cross into GitHub, PR, ADR, owner-doc, skill/AGENTS, generated projection, or
  discard handling -> create a `PromotionIntent` and leave the authority crossing to the normal
  reviewed path.
- Completed projections, transitions, promotions, supersessions, or discards -> create or cite a
  `BuilderOpsReceipt`.

If no BuilderOps record is needed, record `BuilderOps routing: none` with the reason in the PR
handoff. Never append to `docs/learning-log.md` except as an explicit compatibility fallback when a
BuilderOps write is unavailable.

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
2. **Run pickup preflight before lease acquisition:** `scripts/issue_pickup_claim.sh --issue <ISSUE_NUMBER> --preflight-only`
3. **Claim with dispatcher:** `python -m app.dispatcher claim <task_id> --agent <agent_id> --ttl-minutes 90 --json` — acquire 90-minute lease.
4. **Confirm in GitHub (label mutation after successful preflight):** `scripts/issue_pickup_claim.sh --issue <ISSUE_NUMBER> --skip-preflight`
5. **If step 4 fails, immediately release lease:** `python -m app.dispatcher release <task_id> --agent <agent_id> --json`
6. **Mid-work heartbeat** (~every 30 min of active execution): `python -m app.dispatcher heartbeat <task_id> --agent <agent_id> --json` — renew lease before 90-min expiry.
7. **On closure:** `python -m app.dispatcher complete <task_id> --agent <agent_id> --json` (successful) or `python -m app.dispatcher release <task_id> --agent <agent_id> --json` (abandoned).
8. **Fallback on dispatcher failure:** If any dispatcher command fails (non-zero exit) during work, log the failure and continue with local work (do not retry dispatcher commands in a loop). At closure, attempt `dispatcher complete`; if it fails, continue with PR closure via GitHub.

**If dispatcher is unavailable (db_exists: false or dispatcher status fails):**

- Skip dispatcher entirely and use GitHub-label-only claim (step 2 below, unchanged current behaviour).
- **Log the fallback reason in the PR body** (e.g., "Dispatcher unavailable (db_exists: false) — used GitHub-label-only claim").

#### GitHub-Based Claim (Fallback or Non-Dispatcher Flow)

1. **Ensure Issue is in Project** (if missing, add it first):
   ```bash
   gh api graphql -f query='query { repository(owner:"OWNER", name:"REPO") { issue(number:N) { projectItems(first:1) { nodes { id } } } } }'
   ```

2. **Fast-claim the Issue via mandatory preflight wrapper:**
   ```bash
   scripts/issue_pickup_claim.sh --issue <N>
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
- For a bounded direct repair PR, treat the PR body as the contract and validate the Direct Repair block directly instead of requiring a governing Issue.
- Read the owner docs and source docs referenced by `Source Anchors` before editing code.
- Stay strictly within Issue scope.
- Do not expand scope without updating the Issue contract first.
- Preserve architecture boundaries and event/outbox compatibility where relevant.
- Update docs in the same change if behavior, contracts, or architecture change.
- If the work turns a roadmap/plan item into shipped reality, update the owner doc and rewrite roadmap/plan wording so it no longer reads as pending.
- For any PR that changes files under `app/` or `tests/`, run the repo-standard lint gate, currently `ruff check app tests`, before merge and include the lint output or explicit tooling limitation in the PR body.
- Keep docs-only validation lightweight: docs-only PRs should run appropriate docs/governance checks, not the full code/test smoke by default.
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
2. Run mandatory pickup claim wrapper before any lifecycle mutation:
   - `scripts/issue_pickup_claim.sh --issue <N>`
   - This wrapper enforces workspace isolation preflight before removing `agent:ready`.
   - If preflight fails, stop and resolve branch/worktree collisions before claiming.
3. Run delivered-state preflight before claim when target implementation paths are explicit:
   - Verify whether referenced target modules already exist in the repo.
   - If core implementation already exists, do not proceed as fresh implementation; route to `issue-maintenance-change-control` to correct stale or drifted contract state.
   - Treat passing acceptance tests as supporting evidence, not the sole gate for delivered classification.
   - If source specs still say "Not yet implemented" while shipped code exists, route the spec-state writeback through docs/governance repair rather than opening duplicate implementation work.
4. **Execute Action: Begin Implementation Work** (update labels, Issue Project Status, verify).
5. Run the BuilderOps routing checkpoint and create any needed operational record before the context
   becomes hidden local memory.
6. Restate the bounded outcome from the Issue.
7. Read source-anchored docs and owning code paths.
8. If anchor drift exists, resolve it using the rules above before coding.
9. **Verify acceptance verifiability**: every Acceptance Criterion must carry a resolvable `Verify:` target. If any AC lacks one, stop implementation and route through `issue-maintenance-change-control` to repair the contract before coding.
10. **Test-first for behavioral ACs**: for each AC whose `Verify:` names a test, ensure that test exists in the repo and currently fails against the unchanged code path. If the test is missing, write it first from the AC; if it is present but does not fail, either the AC is already satisfied (stop and validate) or the test does not actually exercise the AC (fix the test).
11. Implement the smallest complete change that turns every behavioral `Verify:` test green without breaking unrelated tests.
12. **Writeback for non-behavioral ACs**: perform each non-behavioral `Verify:` target in the same change (doc anchor writeback, roadmap wording cleanup, runtime receipt, etc.).
13. Update owner docs if shipped behavior/contracts changed.
14. Rewrite roadmap/plan wording if the delivered work was previously listed as pending.
15. Run `Suggested Validation` plus any obviously necessary focused checks. Confirm every AC's `Verify:` target now resolves green.
15a. **Branch-Truth Gate — Phase 1: Pre-Commit (mandatory before `git add`/`git commit`)** [branch-truth-gate]

    For multi-agent parallel work, a dedicated per-issue worktree (via `git worktree add`) is mandatory for the full issue lifecycle — from initial implementation through every review-fix push. Do NOT commit to an active PR from the shared root worktree.

    `publish-pr` owns the hardened gate. Run the workspace preflight documented at `.codex/skills/publish-pr/SKILL.md :: Branch-Truth Gate — Pre-Commit`:

    ```bash
    scripts/agent_workspace_preflight.sh \
      --expected-branch "$EXPECTED_BRANCH" \
      --expected-worktree "$EXPECTED_WORKTREE" \
      --allow-dirty
    ```

    Fallback when the preflight script cannot run: assert the branch name directly (`git branch --show-current` must equal the PR head branch). Do not check the remote PR head SHA here — a new local commit will advance HEAD past the remote ref before push.

15b. **Branch-Truth Gate — Phase 2: Pre-Push (mandatory before `git push`)** [branch-truth-gate]

    Re-run the same `publish-pr` gate before pushing (`.codex/skills/publish-pr/SKILL.md :: Branch-Truth Gate — Pre-Push`), with the same branch-name fallback when the script cannot run.

    If the gate fails at pre-push: stop, switch to the correct worktree, relocate the commit if needed, and re-run both phases.

16. Run `.codex/skills/publish-pr/SKILL.md` to create or update the implementation PR linked to the governing Issue unless a concrete blocker or explicit user instruction prevents it.
17. For a normal PR, hand off to `docs/development/PR_HOT_PATH.md` through `pr-integration` only as needed.
18. If any hot-path trigger applies, read `docs/development/PR_ESCALATION_PATHS.md` and use the relevant escalation procedure.
19. **Execute Action: Request Review** only when review is explicitly requested.
20. If the slice merges and this is not the final child slice, keep the parent issue open for later acceptance.
21. If this is the final child slice, route post-merge parent closure through `docs/development/PARENT_ISSUE_CLOSURE.md`.

## PR handoff requirements

Before handing off to `publish-pr`, confirm:

- change stays within Issue scope
- constraints were followed
- every Acceptance Criterion's `Verify:` target now resolves green (behavioral tests pass, non-behavioral writebacks present)
- acceptance criteria are satisfied
- docs were updated in the same change when needed
- owner docs and roadmap/plan wording were updated when the work became shipped reality
- BuilderOps routing is represented by records/projections/receipts or by a short `none` reason
- the next step is the short PR hot path unless an escalation trigger exists


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
