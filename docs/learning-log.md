State: Append-only delivery learning log
Doc role: Reference
Authority: Canonical log of plan divergences across delivery. Does not override issue contracts or skill prompts.
Owner: docs/development/DELIVERY_FEEDBACK_LOOP.md
Temporal class: operational
Review cadence: per retrospective
Source of truth: this file
Last reviewed: 2026-04-20
Last verified against: docs/development/DELIVERY_FEEDBACK_LOOP.md, PR #523, current repo state at 17eef96 on 2026-04-20

# Learning Log

Append-only flat file. One entry per divergence from plan. Do not edit past entries.

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

This lets `learning-retrospective` scope its next read to entries since the last marker.

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
