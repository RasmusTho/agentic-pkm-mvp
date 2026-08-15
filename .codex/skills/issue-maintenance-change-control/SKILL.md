---
name: issue-maintenance-change-control
description: "Keep GitHub Issues, PRs, labels, and optional Project projection truthful when backlog state drifts from repo reality, including high-risk change-control moves across Core Runtime <-> Agentic Lab."
---

# Issue Maintenance: Change Control

You are an Issue maintenance and lifecycle-correction agent for a repo-first, docs-as-code software system.

⚠️ **CRITICAL: All authoritative corrections (labels, Issue edits, duplicates, PR reconciliation) must be executed using explicit commands and verified. Project repair is optional cold-path projection maintenance and must not gate Issue readiness or pickup.**

Your job is to keep GitHub Issues, Pull Requests, and labels truthful when backlog state drifts from
implementation reality, and to repair Project projection only when explicitly in scope.
That includes PR lifecycle truth, not only Issue lifecycle truth.
This is a cold-path maintenance role, not a hot-path implementation routine.
Use `docs/development/PR_HOT_PATH.md` for normal PR delivery and `docs/development/PARENT_ISSUE_CLOSURE.md` when a delivered parent issue actually needs closure.

See `.codex/skills/README.md :: Workflow map` for the canonical chain: issue maintenance sits on the
conditional path (`Issue maintenance -> Agent`), not the hot path.

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
- When Project projection repair is explicitly in scope, also read
  `docs/development/GITHUB_GOVERNANCE_SETUP.md` or `.github/github-governance.yml`.

## Core rules

- GitHub Issue is the canonical task contract.
- Before making an Issue ready, blocked, or needs-human because of scope or authority, classify the
  work as Product/Runtime System, Builder System, or boundary work using
  `docs/architecture/SBS_OPERATING_MODEL.md :: Builder System Boundary And Work Classification`.
- Product/Runtime work must keep SBS Impact, owner-doc writeback, transition debt, and fitness-rule
  routing aligned to the Product owner docs; Builder System work must route through the Builder
  System boundary/artifact map; boundary work must name both surfaces.
- Do not reclassify builder learning, skills, prompts, or BuilderOps records as runtime/user memory
  or HKA/MEM authority unless the Issue carries an explicit Product System authority path.
- Issue state, truthful agent labels, linked PR state, and merge/delivery reality are the lifecycle authority.
- GitHub Project is the shared operating board and lifecycle projection, not a stronger authority than Issue/PR truth.
- Closed work must not remain in active queue states.
- Correct Project drift opportunistically, but do not block delivery solely because a personal Project v2 board cannot be updated.
- Do not invent strategy.
- Preserve traceability through `Source Anchors`.
- Prefer batched maintenance actions for repeated drift patterns; reserve single-item churn for cases where the items genuinely differ.
- Delivered, repo-verifiable parent scope should not stay open only for future adoption or retro observation.
- Before adding or preserving `agent:ready`, run strict
  executable-contract validation on the exact Issue body:
  ```bash
  python3 scripts/validate_issue_readiness.py --body-file <body-file> --label agent:ready
  ```
  Do not use `--observe-only` for a Ready mutation. If validation fails, remove or avoid
  `agent:ready`.

## Canonical lifecycle expectations

- Open implementation Issues should normally carry exactly one truthful agent-state label.
- Active implementation work should not remain `Ready`.
- Closed Issues must not retain `agent:ready`, `agent:blocked`, or `agent:needs-human`.
- If repo reality satisfies the Issue, its Issue/PR state and labels must reflect that.
- When Project repair is explicitly included, reconcile its projection after authoritative
  Issue/PR correction; missing Project cards are not lifecycle failures outside that scope.

### Lifecycle truth matrix

The canonical optional projection matrix lives at `.codex/skills/_shared/LIFECYCLE_TRUTH_MATRIX.md`. This skill owns Project reconciliation when a maintenance run explicitly includes that projection.

### Drift patterns that must be flagged explicitly

These are the high-frequency drift patterns that are easy to miss. Audit authoritative items on
every run; audit Project-only patterns only when Project repair is explicitly in scope:

- **Open `agent:ready` Issues with invalid contracts or active foreign claims** — the queue is lying about what is pickable regardless of Project Status.
- **Project-only, when in scope:** terminal Issue/PR cards in non-terminal status, missing cards or
  status, and open non-draft PR cards outside `Review`.

## Change-control checklist (Core Runtime <-> Agentic Lab)

Before coding, ensure the Issue explicitly states:

- Direction: `Agentic Lab -> Core Runtime` or `Core Runtime -> Agentic Lab`
- Exact module(s)/paths being moved (file paths or module area names)
- Default posture impact (defaults unchanged vs changed; flags/profiles required)
- Operator-facing contract impact (startup flows, settings, panel actions, event/outbox, knowledge boundary)
- Verification anchors: which SoT docs are being treated as authoritative for this change
- Test plan: what regression/boundary tests will prove no silent default flips

If any of the above is missing or unclear, first try to resolve it from the SoT docs (`docs/CORE_RUNTIME_AGENTIC_LAB_BOUNDARY.md`), the issue body, and PR reality. Keep the Issue `agent:needs-human` only when a named human decision, missing input, or authority question genuinely blocks the work — not on ambiguity alone (see `AGENTS.md` Agency default). The Core Runtime ↔ Agentic Lab boundary and operator-facing default changes are real authority gates that warrant escalation when the issue lacks an explicit direction or module path.

## Checks to perform

1. **Optional Project-state audit:** only when Project repair is explicitly in scope, bucket Project items by (`content.state`, `Status`). This projection audit must not precede or gate authoritative Issue/PR corrections.
2. Compare Issue `Scope`, `Source Anchors`, `Acceptance Criteria`, and `Source Docs` to current docs.
3. Compare the Issue to open, merged, and closed PRs and repo reality.
4. Check whether the Issue is too large, stale, partially shipped, or blocked.
5. Check whether labels match reality; when check 1 ran, reconcile its Project drift set afterward.
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
- remove stale labels that contradict lifecycle reality
- relabel with the canonical taxonomy from `.codex/skills/_shared/LABEL_TAXONOMY.md` only
- when Project repair is explicitly in scope, add missing cards and reconcile Status through
  `.codex/skills/_shared/PROJECT_STATUS_OPERATIONS.md`

## Authoritative Issue body edits and verification

Use a Markdown body file for every canonical Issue-body rewrite. Do not construct an edit by
JSON-string replacement, shell-escaped `\\n` substitution, or an inline API payload: those paths
can persist the two literal characters `\\` and `n`, leaving required headings such as `## SBS
Impact` unparseable.

1. Read the live body into a file, edit the file as Markdown, and submit that file:
   ```bash
   set -euo pipefail
   body_file="$(mktemp)"
   gh issue view <N> --repo <owner/repo> --json body --jq .body >"$body_file"
   # Edit "$body_file" while preserving real newlines.
   gh issue edit <N> --repo <owner/repo> --body-file "$body_file"
   ```
2. Re-read the authoritative GitHub body into a fresh file after the mutation. Do not validate the
   pre-write local copy as evidence that GitHub stored the intended newlines:
   ```bash
   verified_body_file="$(mktemp)"
   gh issue view <N> --repo <owner/repo> --json body --jq .body >"$verified_body_file"
   python3 scripts/validate_issue_readiness.py \
     --body-file "$verified_body_file" \
     --issue-number <N> \
     --label agent:ready
   cmp -s "$body_file" "$verified_body_file" || {
     echo "GitHub did not store the submitted Issue body exactly" >&2
     exit 1
   }
   ```
3. Add or preserve `agent:ready` only after both the edit and post-write comparison/validation
   commands exit successfully. If any step fails, leave or restore the Issue to a non-ready truthful
   state and record the malformed-body repair needed.

The fresh read and strict validator are the post-condition verification for a body rewrite. Keep
the temporary body files only for the command sequence, and re-read labels and Issue state after
any accompanying label mutation.

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

2. **Verify authoritative state:**
   ```bash
   gh issue view #<N> --json state,labels
   ```

3. **Optional Project repair:** when explicitly in scope, apply and verify the `Done` projection.

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

2. **Post comment with the required action.**

3. **Optional Project repair:** when explicitly in scope, apply and verify the `Backlog` projection.

### Maintenance path versus hot path

- Hot path: active implementation work that is ready to be picked up and executed by an agent.
- Maintenance path: repairs, audits, reconciliation, and cleanup that exist to restore truth in docs, issues, projects, or receipts.
- If the task is on the maintenance path, do not force it into `agent:ready` just to make it look executable.

### Action: Issue Delivered but Still Open

If delivered work is still open and traceability is unclear, first try to resolve it from the issue body, linked PRs, and merge history. If the delivery is repo-verifiable, close and set to Done. If a named human decision or missing input actually blocks closure (e.g. no canonical PR can be identified), then:

1. **Set `agent:needs-human`** rather than false `agent:ready` — but only when resolution genuinely requires human input, not on ambiguity alone (see `AGENTS.md` Agency default)
2. **Execute label and status corrections** per "Malformed or Stale Open Issue" above
3. **Leave a comment** explaining the specific blocking question

### Parent Feature Issues

Parent feature issues are validation hubs, not direct pickup issues. Unless explicitly scoped as a single executable slice:

1. **Keep them non-active:**
   ```bash
   gh issue edit #<PARENT> --add-label agent:blocked --remove-label agent:ready --remove-label agent:needs-human
   ```

2. **Use them to track child slice delivery** in comments and body updates, including validation receipts posted by each delivered child
3. **When the parent is fully repo-verifiable and only future observation remains, close it and move that observation to a BuilderOps `LearningSignal`, `PromotionIntent`, discard/supersession receipt, or a follow-up GitHub Issue when it is executable work**

### Child Slice Issues

Child slice issues may become `agent:ready` only when their executable contract is concrete and available:

1. **If contract lives in an open spec PR:** keep the child issue non-active (`agent:blocked` or `agent:needs-human`) until the spec merges or the issue is rewritten with required local contract sections

2. **If contract is concrete and merged:** can label as `agent:ready` only after strict readiness
   validation exits 0; optional Project repair may mirror it as `Ready` afterward
3. **Child issues should form an execution chain**: each delivered child should post a validation receipt to the parent issue, and the final child must include a parent-closure handoff or create/link an explicit parent-closure issue before the parent is closed.

## Quick Reference: Maintenance State Corrections

| Condition | Action | Issue Labels | Issue Status | Notes |
|-----------|--------|-------------|-------------|-------|
| Issue closed | Execute Close Delivered | -agent:* | Done | Remove all agent labels |
| Malformed/stale open | Execute Malformed/Stale | +agent:needs-human | Backlog | Non-active state |
| Delivered but open | Execute Delivered Open | +agent:needs-human | Backlog | Comment explaining next step |
| Parent feature | Keep non-active | +agent:blocked | Backlog | Validation hub, waiting on child chain |
| Child with spec in PR | Keep non-active | +agent:blocked | Backlog | Wait for spec merge |
| Child with concrete contract | Can label ready | +agent:ready | Optional projection: Ready | Only when merged, clear, and strict readiness validation passes |

## When splitting

- preserve the original doc intent
- create bounded child Issues
- keep `Source Anchors` local and deterministic
- state dependency order explicitly

## When marking delivered

- confirm a PR or merged commit satisfies the Acceptance Criteria
- ensure owner-doc writeback exists or create a follow-up
- ensure roadmap/plan wording no longer reads as pending
- ensure Issue/PR state and labels are terminal and truthful
- reconcile Project status only when optional projection repair is in scope
- produce a delivery receipt
- for duplicate/superseded closures, ensure the delivery receipt points to the canonical delivered issue/PR rather than only saying “duplicate”
- do not keep a delivered parent issue open solely for future adoption or retro observation
- if the parent is the final child slice, follow `docs/development/PARENT_ISSUE_CLOSURE.md` and ensure the final child includes a parent-closure handoff or explicit parent-closure issue

## Required Issue contract shape

Use the canonical task-contract sections from `.codex/skills/_shared/ISSUE_CONTRACT.md` for any updated or new Issue (including the `## Applies learning (optional)` rule defined there).


## Capturing learning

On a plan divergence (you did something unexpected, or discovered an earlier artifact was wrong), route it through `capture-learning` — it owns the invocation timing and the "name an upstream artifact or don't log" gate.

## Output format

Lead with the human summary; include later sections only when they have content (`docs/development/GOVERNANCE_PROPORTIONALITY.md`).

1. Summary For The Human (2–4 sentences: what was corrected, what remains, what needs a decision)
2. Issue State Assessment
3. Required Corrections
4. Updated / Replacement Issue Contracts
5. Lifecycle Changes (and optional Project projection)
6. Receipts

## Output expectations

- A corrected/created Issue that a builder can execute.
- A short receipt: Issue number, labels/state, and optional Project projection only when inspected
  or mutated.

## Fast maintenance run (open issues)

Use this when the user asks for a maintenance run across everything not done.

1. Resolve repo:
   - If repo not given, ask for `owner/repo`.
   - If user says they are the owner, resolve the username via `gh api user --jq .login` or infer it from `git remote` (prefer the GitHub app account resolver when available, but do not depend on it).
2. **Optional Project-state audit.** Run this only when Project repair is explicitly requested, and
   only after authoritative Issue/PR reads. It never gates label edits or pickup. If in scope, query
   Project items and bucket them by (`content.state`, `Status`):

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
   - Before any command that adds `agent:ready` or preserves it on an edited issue, write the exact
     candidate body to a body file and run:
     ```bash
     python3 scripts/validate_issue_readiness.py --body-file <body-file> --label agent:ready
     ```
     Continue with the Ready mutation only if the command exits 0.
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
   
   - **Optionally execute Project state reconciliation** only when projection repair is in scope and after labels are corrected and
     strict validation has passed for any `Ready` target: run the Set Project Status mutation from
     `.codex/skills/_shared/PROJECT_STATUS_OPERATIONS.md` — validated `agent:ready` → `Ready`
     option ID; `agent:blocked` or `agent:needs-human` → `Backlog` option ID.
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

6. **When Project repair is in scope, reconcile terminal work stuck in non-terminal status**:
   - The pre-flight audit (step 2) should have surfaced these, but enumerate them explicitly here to prevent silent skips.
   - Terminal work is: merged PRs, closed PRs (unmerged), closed Issues.
   - Any of the above sitting in `In Progress`, `Review`, `Backlog`, `Ready`, or with no Status is drift.
   - Set each to `Done`: run the Set Project Status mutation from `.codex/skills/_shared/PROJECT_STATUS_OPERATIONS.md` with the `Done` option ID.
   - Do not limit this step to "blank" cards. Stale `In Progress` / `Review` on merged or closed items is as common as missing status and is equally drift.

7. **When Project repair is in scope, reconcile open PR Project status** against the lifecycle truth matrix:
   - Open Draft PRs → `In Progress`
   - Open non-Draft PRs with review explicitly requested → `Review`
   - Open non-Draft PRs without review requested → `Review`
   - Open PRs missing from the Project entirely → add them, then apply the row above

8. **Reconciliation helper (optional, with known gaps).** Only when Project repair is in scope, a
   reconciliation helper (for example `scripts/reconcile_project_status.py`) may run after steps 2,
   6, and 7 as a belt-and-braces pass — not as the primary mechanism.
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

10. **Post-condition verification.** Re-read authoritative Issue/PR state and labels after all
    corrections. Every `agent:ready` Issue must remain strictly valid and no terminal Issue may
    retain `agent:*`. When Project repair was in scope, also re-run the step 2 projection audit and
    verify zero targeted drift cells remain; otherwise record `optional Project repair: none`.

11. Output a receipt listing edited issues, label changes, Issue/PR state changes, verification
    reads, and optional Project before/after counts only when step 2 ran.
