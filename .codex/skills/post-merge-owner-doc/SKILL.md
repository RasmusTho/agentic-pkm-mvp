---
name: post-merge-owner-doc
description: "After an implementation PR merges, read the diff and decide whether any owner doc needs to change. Act on the decision."
---

# Post-Merge Owner Doc

You are invoked at the end of `verification-and-closure`, after a PR has merged. Your job is one question: **did this merge change something an owner doc currently claims?**

You act on the answer. You do not ask the user to classify, attest, or unblock.
This is a cold-path maintenance check, not a hot-path implementation step.

## The one question

For the merged PR, read:

1. The merge diff (files changed, with their before/after).
2. The closed issue(s) referenced by the PR, including their `Source Docs` list.
3. Every owner doc the diff could plausibly affect. Pick these by judgment from:
   - paths touched in the diff (e.g. changes under `app/retrieval/` implicate `docs/ARCHITECTURE.md` and any retrieval-specific owner doc),
   - the closed issue's `Source Docs`,
   - the registered SoT docs in `docs/DOCS_INDEX.md` (filter to rows marked `Aligned` or similar current-state status).

Then answer: does the diff change something those owner docs currently claim?

Classify the diff before deciding owner-doc impact:

- Product/Runtime System changes use the relevant Product owner docs and SBS impact procedure from
  `docs/architecture/SBS_OPERATING_MODEL.md`.
- Builder System changes to `.codex/skills/**`, `AGENTS.md`, issue/PR governance, CI/fitness,
  release/UAT/promotion workflows, BuilderOps, learning, TCD, or delivery receipts use the Builder
  System boundary and artifact map in `docs/architecture/SBS_OPERATING_MODEL.md` plus the skill index.
- Boundary changes, such as owner-doc writeback or BuilderOps promotion into repo artifacts, inspect
  both the Builder System owner model and the affected Product/Runtime owner docs.

Builder System receipts, learning, skills, or prompts are not runtime/user memory and do not require
Product MEM/HKA owner-doc promotion unless the merged diff explicitly changed Product memory
semantics or followed a Product System authority path.

## Receipt placement

The receipt comment always goes on the **closed issue** that the PR fixes. If the PR closed multiple issues, post the receipt on each one. If the PR closed no issues (docs-only lane, governance lane), post the receipt as a **PR comment** instead — the PR is then the auditable artifact.

After posting, verify the receipt exists by reading back the issue or PR comments. A watchdog reminder, stale notification, or planned follow-up is not a `post-merge owner-doc check:` receipt. [owner-doc-receipt-gate]

## Three outcomes

Classify the claim into one of three lanes: immediate action, queued follow-up, or no change.

**1. Yes, and the wording change is clear. Immediate action.**

Open a docs-only PR via `docs-authoring` that updates the owner doc(s). Title: `docs: owner-doc promotion for #<closed-issue>`. Body links back to the closed issue and names the specific claim(s) being corrected. Add a comment on the closed issue: `post-merge owner-doc check: docs PR opened at #<docs-pr>`.

**2. Yes, but the right wording needs human judgment. Queue a follow-up.**

Open one bounded follow-up issue. Title: `docs: owner-doc promotion needed for #<closed-issue>`. Body names:

- the exact owner-doc claim that is now wrong or incomplete,
- the exact behavior change from the merge,
- one or two candidate rewordings, framed as options not decisions.

Add a comment on the closed issue: `post-merge owner-doc check: follow-up issue #<N> opened (wording needs judgment).`

**3. No owner-doc change is implied.**

Add one comment on the closed issue, verbatim: `post-merge owner-doc check: no owner-doc change implied.` Nothing else.

That comment is the receipt. If it is missing on a closed implementation issue, this skill did not run.

If the merge implies no owner-doc change but reveals future adoption, workflow learning, docs
freshness, roadmap execution, or promotion material, route that material to BuilderOps first:
`LearningSignal`, `DocsFreshnessRecord`, `RoadmapExecutionItem`, `PromotionIntent`, or
`BuilderOpsReceipt` as applicable. Create a GitHub Issue only when the material is bounded executable
work with `Verify:` targets.

## Judgment rules

- **Trust the diff, not metadata.** Do not rely on labels, PR-body tokens, or issue classification as primary signal. Read the code/doc change itself.
- **Owner docs claim current-state truth.** If a shipped change makes an owner-doc sentence false, outdated, or misleading, the sentence needs to change. Stylistic preference is not a reason to open a PR.
- **Target-state and plan docs are not owner docs.** `docs/plans/*`, `docs/{CAPABILITY}/*` specs, and v6.0 target docs describe intent, not current-state truth. Do not open promotion PRs against them unless the merge itself changes target-state intent, which is rare.
- **Prefer the smallest correct change.** A single sentence fix in `STATUS.md` beats a chapter rewrite. If the wording gap is small, just fix it (outcome 1). Only escalate to outcome 2 when the correct phrasing genuinely needs the user's judgment.
- **Split immediate action from queued repair.** If the owner-doc claim is clearly wrong, open the docs PR now. If the claim is only plausibly wrong or needs interpretation, queue one bounded follow-up issue instead of creating churn or guessing.
- **When unsure between outcomes 1 and 2, pick 2.** A follow-up issue is cheaper than an incorrect owner-doc PR.
- **When unsure between outcomes 2 and 3, pick 2.** A false negative (silent drift) is worse than a spurious follow-up issue the user can close in ten seconds.
- **Never open more than one PR or one issue per merge.** If multiple owner docs need changes, bundle them. If the bundle is too large to review, that is signal that the merge itself should have been split — file one follow-up issue noting the scope, not many.

## Inputs you can rely on

- `gh pr view <n> --json title,body,files,closingIssuesReferences`
- `gh issue view <n> --json title,body,labels,comments`
- `git show <merge-sha>` for the diff
- `docs/DOCS_INDEX.md` as the registry of owner docs
- `AGENTS.md` for the classification rules that define what counts as owner-doc-relevant

## Routing

- You write owner-doc PRs through `docs-authoring`. You do not write code.
- You file follow-up issues following the canonical issue contract (`.codex/skills/_shared/ISSUE_CONTRACT.md`), with `Verify:` markers on every AC.
- You do not add `agent:needs-human`. Follow-up issues are `agent:ready` when the wording is bounded; otherwise they stay `Backlog` with no agent label and wait for the user's next pass.

## Backfill mode

When invoked against a batch of recent closed issues (not a single just-merged PR), run the same decision per issue. Produce one summary comment on a rollup issue listing every decision and the artifact produced (PR link, follow-up issue link, or "no change implied"). Do not open more than ~10 docs PRs in a single backfill pass; if more are needed, split the pass.

## What you do not do

- Do not add labels, tokens, attestations, or CI-gate metadata. The delivery chain does not have those.
- Do not ask the user to classify the merge or approve the check.
- Do not edit owner docs in-place as part of this skill; always route through a docs-only PR.
- Do not touch plan docs, spec directories, or target-state docs.
- Do not block anything. Your only outputs are: a docs PR, a follow-up issue, or a receipt comment.


## Capturing learning

On a plan divergence (you did something unexpected, or discovered an earlier artifact was wrong), route it through `capture-learning` — it owns the invocation timing and the "name an upstream artifact or don't log" gate.

## Output format

One receipt line per invocation, printed to the orchestrator:

- `POST-MERGE OWNER-DOC RECEIPT: PR #<n> merged closing #<m>. Outcome: docs-pr #<p> | follow-up #<f> | no-change. Evidence: <one-sentence justification>.`
