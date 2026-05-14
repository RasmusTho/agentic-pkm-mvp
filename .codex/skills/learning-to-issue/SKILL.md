---
name: learning-to-issue
description: "Convert retrospective learnings from learning-log entries, PR/CI failures, and live governance divergences into bounded canonical GitHub Issues. Use after capture-learning or learning-retrospective when a signal is concrete enough for the backlog, or to normalize raw intake issues that were created outside the standard contract."
---

# Learning To Issue

Convert retrospective learnings into bounded, verifiable GitHub Issues that match the repo's canonical issue contract.

This is the maintenance-learning intake lane. It is distinct from `docs-to-issue` (which converts active SoT docs into product-feature backlog) and from `capture-learning` (which appends a divergence entry to `docs/learning-log.md`).

## When to invoke

Invoke when:
- A `docs/learning-log.md` entry names a concrete upstream artifact and the repair is bounded enough for the backlog.
- `learning-retrospective` proposes a concrete edit and the edit requires implementation work (not just a doc change).
- During `pr-integration` or `verification-and-closure`, a live divergence was observed that needs a tracking issue rather than an inline fix.
- An issue was created informally (e.g., during a live incident) and needs normalization to the canonical contract.

Do NOT invoke when:
- The signal is vague or cannot name a concrete upstream artifact.
- The work is already tracked in an open issue (dedupe check first).
- The fix is a one-line doc correction — use `docs-authoring` or a direct repair PR instead.
- The learning-log entry itself is the right artifact (no backlog item needed yet).

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
If a matching closed issue or merged PR exists: the repair may already be delivered — verify before proceeding.

## Issue contract shape

Every issue created by this skill must use the same contract as `docs-to-issue`:

**Title:** `<type>: <short bounded outcome>`

**Required sections (in order):**

- `## Context` — background from the learning-log entry or observed divergence; link the source entry or PR
- `## Scope` — what changes, what files/artifacts are touched
- `## Source Anchors` — the named upstream artifact(s) that absorb the fix; use the most local actionable item
- `## Constraints` — what must not change; what approaches are excluded
- `## Acceptance Criteria` — checkboxes with `Verify:` markers (see below)
- `## Out of Scope` — what this issue deliberately excludes
- `## Suggested Validation` — commands that execute the `Verify:` targets
- `## Source Docs` — paths to referenced docs
- `## Applies learning (optional)` — link to the learning-log entry or retro marker that produced this issue

**Every AC must carry a `Verify:` line:**
- Behavioral AC → test pointer: `Verify: \`tests/<path>::<test_name>\``
- Non-behavioral AC → doc/artifact writeback: `Verify: doc writeback at \`<path> :: <anchor>\``

If an AC cannot carry a resolvable `Verify:` target, refine or split before marking `agent:ready`.

## Allowed labels (canonical only)

Only these labels are allowed. Do not create or use ad hoc labels (e.g., `governance`, `ci`, `maintenance` are not canonical):

| Label | When |
|-------|------|
| `type:task` | default for maintenance repairs |
| `type:bug` | confirmed runtime defect |
| `type:refactor` | code structure change with no behavior change |
| `prio:high` | blocks other work or has active regression |
| `prio:med` | normal maintenance priority |
| `prio:low` | nice-to-have, no urgency |
| `agent:ready` | bounded, testable, unblocked — safe for agent execution |
| `agent:blocked` | dependency unresolved |
| `agent:needs-human` | requires a human decision before work can proceed |

## Creating the issue

Choose the label set based on readiness before running `gh issue create`:

**Bounded, testable, and unblocked → `agent:ready`, Status=Ready:**
```bash
gh issue create \
  --repo <owner/repo> \
  --title "<type>: <bounded outcome>" \
  --label "type:task,prio:med,agent:ready" \
  --body "..."
# Then set Project Status=Ready
```

**Dependency unresolved → `agent:blocked`, Status=Backlog:**
```bash
gh issue create \
  --repo <owner/repo> \
  --title "<type>: <bounded outcome>" \
  --label "type:task,prio:med,agent:blocked" \
  --body "..."
# Then set Project Status=Backlog
```

**Requires human decision → `agent:needs-human`, Status=Backlog:**
```bash
gh issue create \
  --repo <owner/repo> \
  --title "<type>: <bounded outcome>" \
  --label "type:task,prio:med,agent:needs-human" \
  --body "..."
# Then set Project Status=Backlog
```

Do not apply `agent:ready` unless every AC has a resolvable `Verify:` target and no dependency blocks execution.

**Issue body template (all cases):**
```
## Context
<1-2 sentences from the learning-log entry or observed divergence. Link the source: `docs/learning-log.md :: YYYY-MM-DD entry` or `PR #N`>

## Scope
<What changes. Name files and artifacts.>

## Source Anchors
- `<path> :: <section or anchor>`

## Constraints
- <what must not change>

## Acceptance Criteria
- [ ] <bounded outcome>
  - Verify: `<test pointer or doc writeback>`

## Out of Scope
- <what this issue deliberately excludes>

## Suggested Validation
- <commands that execute the Verify: targets>

## Source Docs
- `<path>`

## Applies learning (optional)
Applies learning from `docs/learning-log.md :: YYYY-MM-DD — <entry title>`.
```

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
4. Fix labels — remove non-canonical, add correct ones:
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

**Example:** Issues #923–#925 (created during PR #922 follow-up) used labels `governance,ci,maintenance` which are not in the canonical taxonomy. Normalization would replace those with `type:task,prio:med,agent:ready` and verify all AC sections have `Verify:` markers.

## Receipt format

**Backlog receipt (new issue):**
```
BACKLOG RECEIPT: Issue #N created — "<title>", labeled type:task/prio:med/agent:ready, added to Project "Agent Delivery Control Plane", Status=Ready. Source: docs/learning-log.md :: YYYY-MM-DD entry.
```

**Normalization receipt (existing issue updated):**
```
NORMALIZATION RECEIPT: Issue #N normalized to canonical contract. Sections added: <list>. Labels corrected: <old> → <new>. Verify: markers added to N ACs.
```

**Delivery receipt template (filled by verification-and-closure at merge):**
```
DELIVERY RECEIPT: Issue #N delivered by PR #M. Merge commit: <sha>. CI: passed. Docs updated: yes/no. Upstream artifact repaired: <path>. Project Status: Done.
```

## Capturing learning

**Capturing learning:** if during this work you notice a divergence from plan — you did something you did not expect to do, or discovered an earlier artifact was wrong — invoke `capture-learning` before continuing. Do not batch to end of task. Only log if you can name an upstream artifact that could absorb the fix.
