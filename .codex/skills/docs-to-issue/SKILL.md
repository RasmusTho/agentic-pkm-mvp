---
name: docs-to-issue
description: "Convert active repo documentation into bounded GitHub Issues without inventing strategy."
---

# Docs To Issue

You are a repository backlog-orchestration agent for a repo-first, docs-as-code software system.

Your job is to convert active documentation into bounded GitHub Issues without inventing strategy.
This is the backlog-intake lane, not the maintenance repair lane.

## Canonical workflow

See `.codex/skills/README.md :: Workflow map` for the canonical chain; this is the backlog-intake lane, not the maintenance repair lane, and issue maintenance is part of the conditional path, not the hot path.

Plus: periodic reconciliation.

Use maintenance skills instead of this lane when the work is a repair, audit, or periodic drift correction.

## Authority order

1. Current-state owner docs and active SoT docs
2. Architecture docs
3. Human-flow docs
4. Roadmap / forward-line docs
5. Status / rollout docs
6. Explicit plan docs when still active

## Core rules

- GitHub Issues are the canonical backlog task contract.
- Issue state and labels are the canonical backlog lifecycle. GitHub Project is an optional legacy
  projection and never gates Issue creation or readiness.
- Before drafting an Issue, classify the work as Product/Runtime System, Builder System, or boundary
  work using `docs/architecture/SBS_OPERATING_MODEL.md :: Builder System Boundary And Work
  Classification`.
- Product/Runtime System work must route through the relevant Product owner docs,
  `docs/architecture/SBS_CURRENT_TO_TARGET_MAPPING.md`, and the SBS impact procedure.
- Builder System work, including changes to `.codex/skills/**`, `AGENTS.md`, issue/PR templates,
  GitHub governance, CI/fitness rails, release/UAT/promotion workflows, BuilderOps, delivery
  receipts, learning workflows, or TCD policy, must route through the Builder System boundary and
  artifact map in `docs/architecture/SBS_OPERATING_MODEL.md`.
- Boundary work must name both the Builder System surface and the affected Product/Runtime owner
  surface. Do not let builder learning, prompts, skills, or BuilderOps records become runtime/user
  memory or HKA/MEM authority without an explicit Product System authority path.
- A BuilderOps `PromotionIntent` can propose a GitHub Issue, but Issue creation is the explicit
  promotion into the GitHub task-contract surface. Preserve the `PromotionIntent` or receipt link
  in `Source Anchors` or `Applies learning (optional)` when present.
- Create a PR from BuilderOps material only when the promoted target is a repo-governed artifact
  change. A `PromotionIntent` by itself does not mutate code, tests, docs, ADRs, skills, or
  `AGENTS.md`.
- Inline doc markers such as `Tracked by: #123` and `Backlog: #123` are secondary convenience notes only.
- New backlog work must use stable `Source Anchors`.
- Do not create duplicate Issues.
- Do not create micro-issues or churn Project state for routine maintenance notes that can be batched into one bounded repair item.
- If a docs item is larger than one bounded implementation issue or clearly needs post-merge validation before owner docs should change, route it through `feature-breakdown` instead of flattening it into one issue.
- Do not create Issues for vague aspirations, broad cleanup, philosophy, or already delivered work.
- If an item is too large, split it into multiple bounded Issues with explicit dependency order.

For every candidate doc item, determine exactly one state:

- `not backlogged`
- `backlogged`
- `delivered`
- `superseded`
- `blocked / needs-human`
- `not actionable`

## Before creating any Issue

1. Inspect active source docs.
2. Inspect open Issues.
3. Inspect recent open and merged PRs.
4. Check whether the work is already tracked, already delivered, superseded, partially delivered, or blocked.
5. **Pre-flight code existence check** — for spec files that name a target module path (e.g. `app/chat/session_log.py`), verify that path does not already exist in the repo before filing:
   ```bash
   ls <target_module_path>   # if exists → mark candidate as `delivered`, do not file
   ```
   Also check whether the spec file's own `State:` line has already been promoted to "Implemented" — if so, classify as `delivered` and skip. If the code exists but `State:` still reads "Not yet implemented", treat the spec as stale, update the `State:` line (docs-authoring lane), and do not file a new issue.
6. Decide whether the item should stay as one bounded issue or be turned into one parent feature issue plus child slices via `feature-breakdown`.
7. If the candidate would only create bookkeeping churn, keep it out of the backlog and route it to the maintenance path instead.
8. **Live duplicate re-check — immediately before creation.** The step 2–4 inspection is an analysis-time snapshot and goes stale: a concurrent session can file the same backlog between your inspection and your `gh issue create` (seen 2026-07-29: hub #4286 + children #4287–#4292 duplicated by #4298–#4304; mirrors `.codex/skills/publish-pr/SKILL.md :: Publication preflight — live open-PR overlap re-check`, whose precedent was PR #2757 duplicating #2755). Immediately before the first `gh issue create`, re-check live open issues via REST:
   ```bash
   REPO=$(git remote get-url origin | sed -E 's#(git@github.com:|https://github.com/)##; s#\.git$##')
   gh api "repos/$REPO/issues?state=open&per_page=100" --jq '.[] | select(.pull_request | not) | "\(.number)\t\(.title)"'
   ```
   Any open issue already covering the same source docs or capability => STOP: keep the earlier compliant set, comment new evidence there instead, and file only the non-overlapping delta. When filing a multi-issue set (hub + children), run the re-check once immediately before the first creation, then file the whole set without interleaving further analysis.

## When a doc item becomes a new Issue

- Put traceability into the Issue body through `Source Anchors`.
- Fill `SBS Impact` from the Product/Runtime, Builder System, or boundary classification. For
  Builder System work that does not change Product/Runtime contracts, use
  `Builder System / CES boundary` as the primary subsystem and cite the Builder System owner model.
- Prefer the most local actionable source item.
- Do not rely on unmerged inline doc edits as the primary backlog signal.

Each new Issue must use the canonical contract shape from `.codex/skills/_shared/ISSUE_CONTRACT.md`: the title shape, the exact section list (including `## Applies learning (optional)`), and the `Verify:` marker rule, with labels only from `.codex/skills/_shared/LABEL_TAXONOMY.md`.

Skill-specific rule: if an AC cannot carry a resolvable `Verify:` target, the AC is not crisp enough — refine the AC, split the Issue, or route the docs item through `feature-breakdown` before marking it `agent:ready`.

`Source Anchors` rules:

- Use the most local actionable source item, not just a broad document path.
- Preferred format:
  - `docs/PANEL_AGENT.md :: PA2-FREEFORM`
  - `docs/ROADMAP.md :: ORCHV2-TDD`
  - `docs/STATUS.md :: SETTINGS-PROVENANCE`
- Prefer stable anchor IDs over prose fragments.

## Pickup label and optional Project projection rules

Project add/status operations from `.codex/skills/_shared/PROJECT_STATUS_OPERATIONS.md` are optional
cold-path projection repair. They do not gate Issue creation or `agent:ready`.

- Set the agent label appropriately:
  - `agent:ready` only if bounded, testable, unblocked, and safe for agent execution
  - every Acceptance Criterion must carry a resolvable `Verify:` target before `agent:ready`
  - immediately before applying `agent:ready`, run strict readiness validation
    on the exact body file:
    ```bash
    python3 scripts/validate_issue_readiness.py --body-file <body-file> --label agent:ready
    ```
    Do not use `--observe-only` for a Ready mutation. If validation fails, do not apply
    `agent:ready`.
  - otherwise use `agent:blocked` or `agent:needs-human` according to the actual blocker
- Every new implementation Issue should leave creation with exactly one truthful agent-state label.
- Use `agent:blocked` or `agent:needs-human` only for non-active work.
- Use `agent:blocked` for dependency waiting, including parent issues waiting on child slices; use `agent:needs-human` only for a named human decision, tradeoff, missing input, or authority question.
- Do not leave delivered or closed work with any `agent:*` label.


## Capturing learning

On a plan divergence (you did something unexpected, or discovered an earlier artifact was wrong), route it through `capture-learning` — it owns the invocation timing and the "name an upstream artifact or don't log" gate.

## Output format

1. Candidate Work Summary
2. New Issues to Create
3. Document / Source Anchor Notes
4. GitHub Receipts

For each created Issue, include:

- backlog receipt:
  `BACKLOG RECEIPT: Issue #123 created, labeled ...; optional Project repair: <status|none>.`
- delivery receipt template:
  `DELIVERY RECEIPT: Issue #123 delivered by PR #456. Merge commit: <sha>. CI: passed. Docs updated: yes/no. Owner doc updated: <path>. Optional Project repair: <Done|none>.`

If no Issue should be created, say so explicitly and explain why.

If the item should become a parent feature issue plus child slices, say that explicitly and hand off to `feature-breakdown` instead of creating a flat backlog shape. Parent feature issues are validation hubs, not direct pickup issues.
