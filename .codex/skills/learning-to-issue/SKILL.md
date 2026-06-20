---
name: learning-to-issue
description: "Convert retrospective learnings from BuilderOps LearningSignal records, historical learning-log compatibility entries, PR/CI failures, and live governance divergences into bounded canonical GitHub Issues. Use after capture-learning or learning-retrospective when a signal is concrete enough for the backlog, or to normalize raw intake issues that were created outside the standard contract."
---

# Learning To Issue

Convert retrospective learnings into bounded, verifiable GitHub Issues that match the repo's canonical issue contract.

This is the maintenance-learning intake lane. It is distinct from `docs-to-issue` (which converts active SoT docs into product-feature backlog) and from `capture-learning` (which creates a BuilderOps `LearningSignal`).

## When to invoke

Invoke when:
- A BuilderOps `LearningSignal` names a concrete upstream artifact and the repair is bounded enough for the backlog.
- A BuilderOps `PromotionIntent` targets `github_issue` and the promoted material is bounded,
  executable work with resolvable `Verify:` targets.
- A historical `docs/learning-log.md` compatibility entry names a concrete upstream artifact and has not yet been represented by a `LearningSignal`.
- `learning-retrospective` proposes a concrete edit and the edit requires implementation work (not just a doc change).
- During `pr-integration` or `verification-and-closure`, a live divergence was observed that needs a tracking issue rather than an inline fix.
- An issue was created informally (e.g., during a live incident) and needs normalization to the canonical contract.

Do NOT invoke when:
- The signal is vague or cannot name a concrete upstream artifact.
- The work is already tracked in an open issue (dedupe check first).
- The fix is a one-line doc correction - use `docs-authoring` or a direct repair PR instead.
- The `LearningSignal` or compatibility entry itself is the right artifact (no backlog item needed yet).

## Pre-flight: dedupe check (required before creating any issue)

Run all three checks before creating a new issue:

```bash
# 1. Search open issues for same symptom/artifact
gh issue list --repo <owner/repo> --state open --search "<keyword from learning>" --json number,title

# 2. Search recently merged PRs (last 30 days)
gh pr list --repo <owner/repo> --state merged --search "<keyword>" --limit 20 --json number,title,mergedAt

# 3. Search closed issues
gh issue list --repo <owner/repo> --state closed --search "<keyword>" --limit 10 --json number,title
```

If a matching open issue exists: add evidence as a comment, do not create a duplicate.
If a matching closed issue or merged PR exists: the repair may already be delivered - verify before proceeding.

## Issue contract shape

Every issue created by this skill must use the same contract as `docs-to-issue`:

Use the canonical contract shape from `.codex/skills/_shared/ISSUE_CONTRACT.md` — title shape, exact section list, and the `Verify:` marker rule — with these learning-specific requirements:

- `## Context` links the source record: `BuilderOps LearningSignal <id>`, `BuilderOps PromotionIntent <id>`, `docs/learning-log.md :: YYYY-MM-DD entry`, or `PR #N`.
- `## Source Anchors` names the upstream artifact(s) that absorb the fix; use the most local actionable item.
- `## Applies learning` is filled for learning issues (not left blank): link the BuilderOps LearningSignal/receipt, historical learning-log entry, or retro marker that produced this issue.

If an AC cannot carry a resolvable `Verify:` target, refine or split before marking `agent:ready`.

## Allowed labels (canonical only)

Use the canonical taxonomy from `.codex/skills/_shared/LABEL_TAXONOMY.md`, including its governance-lane exception: governance-lane learning issues add `lane:governance` in addition to the canonical delivery label set so Project filtering and verification routing stay aligned with `AGENTS.md` and `docs/development/DELIVERY_FEEDBACK_LOOP.md`.

## Creating the issue

Choose the label set based on readiness before running `gh issue create`:

**Bounded, testable, and unblocked -> `agent:ready`, Status=Ready:**
```bash
gh issue create \
  --repo <owner/repo> \
  --title "<type>: <bounded outcome>" \
  --label "type:task,prio:med,agent:ready" \
  --body "..."
# Then set Project Status=Ready
```
For governance-lane learning issues, also add `--label "lane:governance"` so the issue is visible in the governance lane filter and keeps the relaxed governance verification path.

**Dependency unresolved -> `agent:blocked`, Status=Backlog:**
```bash
gh issue create \
  --repo <owner/repo> \
  --title "<type>: <bounded outcome>" \
  --label "type:task,prio:med,agent:blocked" \
  --body "..."
# Then set Project Status=Backlog
```

**Requires human decision -> `agent:needs-human`, Status=Backlog:**
```bash
gh issue create \
  --repo <owner/repo> \
  --title "<type>: <bounded outcome>" \
  --label "type:task,prio:med,agent:needs-human" \
  --body "..."
# Then set Project Status=Backlog
```

Do not apply `agent:ready` unless every AC has a resolvable `Verify:` target and no dependency blocks execution.

**Issue body (all cases):** use the body template from `.codex/skills/_shared/ISSUE_CONTRACT.md`, with the learning-specific requirements above (`## Context` links the source record; `## Applies learning` filled, e.g. `Applies learning from \`BuilderOps LearningSignal <id>\``).

After creation, add to Project `Agent Delivery Control Plane` and verify Status matches the chosen readiness state.

## Raw-intake normalization path

Use this path when an issue was created informally (e.g., during a live incident or by an agent that bypassed the standard contract) and needs to be brought up to standard.

Signs a raw-intake issue needs normalization:
- Missing required sections (`Source Anchors`, `Constraints`, `Out of Scope`, `Suggested Validation`, `Source Docs`)
- AC checkboxes lack `Verify:` markers
- Non-canonical labels (`governance`, `ci`, `maintenance`, etc.)
- Title does not follow `<type>: <bounded outcome>` format

**Normalization steps:**

1. Read the issue body and identify what is missing.
2. Draft the missing sections based on the issue context.
3. Update the body:
   ```bash
   gh issue edit <N> --repo <owner/repo> --body "$(cat <<'EOF'
   <corrected full body>
   EOF
   )"
   ```
4. Fix labels - remove non-canonical, add correct ones:
   ```bash
   gh issue edit <N> --repo <owner/repo> \
     --remove-label "governance,ci,maintenance" \
     --add-label "type:task,prio:med,agent:ready"
   ```
5. Fix title if needed:
   ```bash
   gh issue edit <N> --repo <owner/repo> --title "type:task: <bounded outcome>"
   ```
6. Verify:
   ```bash
   gh issue view <N> --repo <owner/repo> --json title,labels,body
   ```

**Example:** Issues #923-#925 (created during PR #922 follow-up) used labels `governance`, `ci`, `maintenance` which are not in the canonical taxonomy. Normalization would replace those with `type:task,prio:med,agent:ready` and verify all AC sections have `Verify:` markers.

## Receipt format

**Backlog receipt (new issue):**
```
BACKLOG RECEIPT: Issue #N created - "<title>", labeled type:task/prio:med/agent:ready, added to Project "Agent Delivery Control Plane", Status=Ready. Source: BuilderOps LearningSignal <id>, BuilderOps PromotionIntent <id>, or docs/learning-log.md :: YYYY-MM-DD compatibility entry.
```

**Normalization receipt (existing issue updated):**
```
NORMALIZATION RECEIPT: Issue #N normalized to canonical contract. Sections added: <list>. Labels corrected: <old> -> <new>. Verify: markers added to N ACs.
```

**Delivery receipt template (filled by verification-and-closure at merge):**
```
DELIVERY RECEIPT: Issue #N delivered by PR #M. Merge commit: <sha>. CI: passed. Docs updated: yes/no. Upstream artifact repaired: <path>. Project Status: Done.
```

## Capturing learning

On a plan divergence (you did something unexpected, or discovered an earlier artifact was wrong), route it through `capture-learning` — it owns the invocation timing and the "name an upstream artifact or don't log" gate.
