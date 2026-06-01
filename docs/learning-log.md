State: Historical compatibility view for delivery learning captured before BuilderOps LearningSignal became the primary operational source in #1506.
Doc role: Historical / compatibility reference
Authority: Historical record of pre-BuilderOps delivery learning entries and explicit compatibility fallbacks. Does not override BuilderOps Vault records, issue contracts, or skill prompts.
Owner: docs/development/DELIVERY_FEEDBACK_LOOP.md
Temporal class: snapshot
Review cadence: per retrospective
Source of truth: BuilderOps Vault LearningSignal records for operational learning after #1506; this file for historical entries and explicit compatibility fallbacks
Last reviewed: 2026-06-01
Last verified against: docs/development/DELIVERY_FEEDBACK_LOOP.md, docs/builderops/BUILDEROPS_VAULT_OBJECT_MODEL.md, docs/builderops/BUILDEROPS_VAULT_PROJECTIONS.md, issue #1506

# Learning Log Compatibility View

This file preserves historical delivery learning entries that existed before the BuilderOps Vault
learning workflow landed. New operational learning capture should create `LearningSignal` records in
BuilderOps Vault, not treat this Markdown file as the primary store.

`docs/learning-log.md` may still be used as an explicit compatibility fallback when a BuilderOps
write is unavailable, but such fallback entries are not the source of truth once a corresponding
`LearningSignal` exists. Do not edit past entries.

The repo-readable generated view for current learning is the `learning-summary` BuilderOps
projection, generated from `LearningSignal` records.

## Entry shape

```markdown
## YYYY-MM-DD — #<issue> (<slice title>)
**Source:** <skill name or "human">
**Diverged:** <one sentence: the plan said X, reality was Y>
**Upstream artifact:** <path or section — e.g. AGENTS.md §X, .codex/skills/issue-to-code/, task-contract template>
```

## Trigger heuristic

Log only when you did something you did not expect to do, or discovered an earlier artifact was wrong. Not when work went as planned.

If the next agent doing a similar task would benefit from an upstream artifact being different, log it — otherwise don't.

The "name an artifact" gate: you cannot log without proposing where the fix lives. If genuinely unknown, write `"unknown — flag for retro"`.

## Retrospective marker shape

Retrospective completions append:

```
--- retro YYYY-MM-DD: applied N/M proposals ---
```

For historical entries, this lets `learning-retrospective` scope its compatibility read to entries
since the last marker. New retrospective state should be recorded with BuilderOps receipts over the
LearningSignal records being processed.

---

## 2026-04-19 — #514 (Delivery feedback loop — governance lane delivery)
**Source:** human (observed during issue creation)
**Diverged:** The issue-creation workflow made multiple GraphQL calls (label lookup, issue creation, project board operations) and hit the per-hour GraphQL rate limit mid-run, blocking project board assignment.
**Upstream artifact:** `.codex/skills/` — all skills that interact with GitHub; prefer REST endpoints over GraphQL; resolve GraphQL identifiers once per run and cache in variables; defer project board mutations to a single batched pass at the end.

## 2026-04-22 — temporal-docs-audit (Temporal docs audit)
**Source:** temporal-doc-governance
**Diverged:** The audit expected high-risk docs to be clean after recent temporal refreshes, but `docs/ARCHITECTURE.md` still contained a merge-conflict marker on `main`.
**Upstream artifact:** `.codex/skills/pr-integration/SKILL.md` and CI docs checks — add conflict-marker detection to doc validation before merge.

## 2026-04-29 — #683 (CANVAS-01: Write Session Logs)
**Source:** issue-to-code
**Diverged:** The issue was filed for unimplemented work, but `app/chat/session_log.py` and all six acceptance tests already existed in the repo and passed on first run — no implementation was required.
**Upstream artifact:** `docs-to-issue` / `issue-to-code` — before filing a new issue from a spec, verify that the spec's target module does not already exist in the repo; add a pre-flight check step to the docs-to-issue intake lane.

## 2026-05-02 — #684/#685/#686 (CANVAS-02/03/04: Co-Author, Gate, API)
**Source:** verification-and-closure
**Diverged:** All three remaining canvas slices (#684 co-author body, #685 governance gate, #686 API/CLI) were filed as unimplemented, but `app/chat/canvas_writer.py`, `app/chat/governance_router.py`, API routes, and CLI commands already existed with 19 passing tests. All four spec files had `State: Specification. Not yet implemented.` despite the whole canvas surface having shipped via PRs #605/#618/#619/#626.
**Upstream artifact:** `docs-to-issue` pre-flight check (now patched in PR #701) + spec-state writeback in `verification-and-closure` (PR #701) — confirms the governance repair was correctly scoped; the three previously-untracked spec State: lines are now promoted in the follow-up docs PR.

## 2026-05-03 — #748 (Dispatcher wrapper docs fix)
**Source:** human
**Diverged:** I performed PR creation and local-memory updates ad hoc before explicitly routing through the repo workflow skill boundary, while the expected process is to use the matching in-repo skill for each workflow step.
**Upstream artifact:** `AGENTS.md` + `.codex/skills/publish-pr/SKILL.md` / `.codex/skills/pr-integration/SKILL.md` usage discipline in agent execution.

## 2026-05-03 — #748 (PR workflow skill routing)
**Source:** human
**Diverged:** The process question clarified that PR creation should have been routed explicitly through `publish-pr` as the publication boundary instead of being treated as a generic git/gh step.
**Upstream artifact:** `.codex/skills/publish-pr/SKILL.md` (canonical PR creation workflow) and `AGENTS.md` workflow sequencing discipline.

--- retro 2026-05-03: applied 4/4 proposals ---

## 2026-05-04 — CI baseline audit (ruff + mypy drift on main)
**Source:** backlog-reconciliation-drift-audit
**Diverged:** `docs/development/DEV_WORKFLOW.md` states that `ruff check app tests` and `mypy app` must be run before merging code-affecting changes, but 34 ruff violations (F401/F841/F811, predominantly test files) and 7 mypy errors exist on main today — no CI gate prevents them from landing.
**Upstream artifact:** `docs/development/DEV_WORKFLOW.md` — add a hard pre-merge requirement note, or wire ruff + mypy as blocking CI checks so the policy is enforced rather than advisory.

## 2026-05-04 — v2_runtime duplicate _load_checkpoint (orchestrator V2)
**Source:** backlog-reconciliation-drift-audit
**Diverged:** `app/orchestrator/v2_runtime.py` defines `_load_checkpoint` twice (lines 616 and 625); the second definition silently shadows the first and survived merge because mypy is not a blocking CI gate.
**Upstream artifact:** `app/orchestrator/v2_runtime.py` — remove the duplicate definition; one of the two `_load_checkpoint` bodies is unreachable.
Resolution note (2026-05-06): verified `app/orchestrator/v2_runtime.py` now contains a single `_load_checkpoint` definition; no further upstream edit required from this entry.

## 2026-05-04 — ruff --fix conftest re-export breakage (sync test suite)
**Source:** backlog-reconciliation-drift-audit
**Diverged:** `ruff --fix` removed F401 imports from `tests/sync/conftest.py` that were locally unused but served as re-exports consumed by 4 other test modules, breaking their collection.
**Upstream artifact:** `docs/development/DEV_WORKFLOW.md` — add a caution: review F401 removals manually in conftest files and re-export modules, or mark intentional re-exports with `# noqa: F401` before running `--fix`.

## 2026-05-05 — PR #765 (Backlog drift audit 2026-05-05)
**Source:** pr-integration
**Diverged:** The plan said PR body should be compliant with the PR template's "Change Lane" section, reality was the PR body lacked the required lane classification checkbox (Fixes #/Closes #/Resolves # OR Docs authoring lane OR Governance lane), causing pr-contract CI to fail and requiring manual repair during pr-integration.
**Upstream artifact:** `.codex/skills/publish-pr/SKILL.md` — add pre-publication validation gate to verify PR body includes required lane classification before pushing; currently only `.github/workflows/issue-pr-governance.yml` enforces it post-push. For docs/governance lane PRs, template sections should be auto-populated or validation should occur at publish-time.

--- retro 2026-05-06: applied 3/3 proposals ---

## 2026-05-06 — #783 (Smoke/e2e feedback loop parallelization)
**Source:** pr-integration
**Diverged:** The plan assumed installing `pytest-xdist` was sufficient for `-n/--dist`, but CI still failed because `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` prevented xdist from loading unless explicitly added with `-p xdist.plugin`.
**Upstream artifact:** `docs/TESTING.md` + `.codex/skills/pr-integration/SKILL.md` — add a note that plugin-provided pytest flags require explicit plugin loading when autoload is disabled, and verify this in CI failure triage before dependency changes.

## 2026-05-07 — #775 (Outbox contract reconcile branch drift during review-fix loop)
**Source:** issue-to-code / pr-integration
**Diverged:** The plan was to apply Codex review fixes directly on PR #796 branch (`codex/issue-775-outbox-contract-reconcile`), but commits repeatedly landed on unrelated local branches because edits/commits were run from the shared root worktree where active branch context had changed.
**Upstream artifact:** `.codex/skills/issue-to-code/SKILL.md` + `.codex/skills/pr-integration/SKILL.md` — require a hard branch-truth gate before any `git add/commit/push` (`git branch --show-current` must equal PR head branch and `git rev-parse HEAD == gh pr view <PR> --json headRefOid`). For multi-agent parallel work, require a dedicated per-issue worktree for the full lifecycle (implementation through review-fix), and prohibit committing from the shared root worktree for active PRs.

## 2026-05-07 — PR #800 (merge-ref drift causing CI-only NameError)
**Source:** pr-integration
**Diverged:** CI `smoke` failed on PR merge-ref with `NameError: _upsert_executed_ids is not defined` even though branch HEAD had the alias import locally. The merge-ref carried the call site while import context diverged during conflict churn, creating a CI-only failure mode.
**Upstream artifact:** `.codex/skills/pr-integration/SKILL.md` — add a merge-ref validation step after review-fix pushes: fetch `pull/<id>/merge`, inspect touched symbols in that tree (not only branch HEAD), and run at least one target test against the same path before declaring PR ready.

## 2026-05-14 — PR #922 (path-filter legacy smoke workflow)
**Source:** pr-integration
**Diverged:** The plan said a `## Direct Repair` block in the PR body is sufficient for `pr-contract` to pass; reality was that the block must not be the last section — the detection regex `## Direct Repair[\s\S]*?(?=\n## |\n---|\n$)` requires a following `\n##` or `\n---` lookahead, and the `\n$` alternative only fires if GitHub stores a trailing newline (it does not). Placing `## Direct Repair` last silently returns null and `isDirectRepair = false`.
**Upstream artifact:** `.codex/skills/publish-pr/SKILL.md` — require `## Direct Repair` to be the first section of the PR body (not the last), matching the passing pattern in PR #921 and matching the regex contract in `.github/workflows/issue-pr-governance.yml`.

## 2026-05-14 — PR #922 (governance lane file allowlist excludes most workflow files)
**Source:** pr-integration
**Diverged:** The governance lane's allowed-file set in `issue-pr-governance.yml` includes only `.github/workflows/issue-pr-governance.yml` by exact match; other workflow files (e.g. `smoke.yml`, `ci-smoke.yaml`) are not included. A PR that classifies as `Governance lane` but touches these files will fail the file-restriction check. The Direct Repair path bypasses file restrictions entirely and is the correct route for workflow-file repairs.
**Upstream artifact:** `docs/development/PR_HOT_PATH.md` — add a note that workflow-file repairs (other than `issue-pr-governance.yml`) must use `Direct Repair`, not the `Governance lane` checkbox, because the governance lane allowlist is narrower than `.github/workflows/**`.

## 2026-05-15 — #973 (watcher lifecycle observability)
**Source:** issue-to-code / pr-integration
**Diverged:** After CI went green on PR #988, the plan (hot-path step 3) required triaging review feedback before handoff — instead the agent declared "awaiting human review" without checking whether a review was already posted. A Codex P2 comment (stale-log masking in `_get_watcher_lifecycle_status`) was present and needed addressing before merge.
**Upstream artifact:** `docs/development/PR_HOT_PATH.md` §"Review feedback triage" — make explicit that the agent must check for existing review comments immediately after CI is confirmed green, before any handoff or merge recommendation. The normal next step after CI green + review triage is `verification-and-closure`, not a park for human review.

## 2026-06-01 — #1490 (Recent merged PR review sweep)
**Source:** human / verification-and-closure
**Diverged:** The review-feedback skills could identify and repair actionable comments, but multiple merged PRs still had unresolved inline review threads because follow-up fixes did not consistently reply to and resolve the original thread after landing on `main`.
**Upstream artifact:** `.codex/skills/verification-and-closure/SKILL.md` and `.codex/skills/pr-integration/SKILL.md` — add a thread-state closure step for review-follow-up repairs: when a PR or direct repair addresses prior review feedback, verify the fixing commit is on the target base, reply with the fixing PR/merge commit, and resolve the original review thread before declaring the sweep complete.

## 2026-06-01 — #1490 (Post-merge owner-doc receipt backfill)
**Source:** human / post-merge-owner-doc
**Diverged:** The post-merge owner-doc watchdog detected missing receipts, but several merged PRs remained with only watchdog reminders because the delivery loop did not enforce that a `post-merge owner-doc check:` receipt existed before final closure.
**Upstream artifact:** `.codex/skills/verification-and-closure/SKILL.md` and `.codex/skills/post-merge-owner-doc/SKILL.md` — make receipt verification scriptable after merge, including direct-repair and docs/governance-lane PRs with no closing issue, so a watchdog reminder cannot be mistaken for loop closure.

## 2026-06-01 — #1490 (Branch-chain review repair truth)
**Source:** human / pr-integration
**Diverged:** Some review fixes appeared addressed on intermediate branches before they were actually present on `main`, so the merged-PR sweep had to verify branch-chain repairs against the final target branch rather than trusting the side branch where a fix first landed.
**Upstream artifact:** `.codex/skills/pr-integration/SKILL.md` and `.codex/skills/verification-and-closure/SKILL.md` — require base-branch truth checks for review repairs that land through chained PRs: the repair is not complete until the fixing commit is reachable from the merge target, or a final integration PR carries it there.

## 2026-06-01 — PR #1486 (Panel checkbox projection merge verification)
**Source:** human / verification-and-closure
**Diverged:** The recovery plan assumed the Panel checkbox projection implementation still needed to be published from the current checkout, but current `main` already contained the merged implementation via PR #1486 and the active root checkout had switched back to `main`.
**Upstream artifact:** `.codex/skills/pr-integration/SKILL.md` + `.codex/skills/verification-and-closure/SKILL.md` — add an explicit post-resume/current-state gate to re-check branch, `origin/main`, merged PRs, and expected implementation files before continuing publication or reimplementation work.

## 2026-06-01 — learning retro (redirected workspace patch path)
**Source:** learning-retrospective
**Diverged:** The startup rule said to switch context to the canonical repo root, but a file-edit patch attempt still resolved relative paths against `/Users/rasmusthornberg/Documents/New project` until the repo-root patch command was run from the canonical cwd.
**Upstream artifact:** `/Users/rasmusthornberg/Documents/New project/AGENTS.md` — make the workspace redirect rule explicit about verifying file-edit tool path resolution before trusting a patch.

--- retro 2026-06-01: applied 11/11 proposals ---
