---
name: docs-authoring
description: "Docs-only authoring lane for agentic-pkm-mvp. Use when evolving or clarifying authoritative docs/specification surfaces without implementation changes or a governing Issue."
---

# Docs Authoring

Use this skill when the task is a docs-only change that evolves or clarifies authoritative repo docs before backlog extraction.

## First context to load

- Read `AGENTS.md` first.
- Use `docs/DOCS_INDEX.md` to identify the owner doc for the touched surface.
- Read `docs/development/DEV_WORKFLOW.md`, especially the `Docs-authoring lane` and `GitHub issue-first execution loop` sections.
- Read `docs/development/GITHUB_GOVERNANCE_SETUP.md`, especially `Enforcement intent` and `Docs-authoring PR lane`.
- Read `.github/pull_request_template.md` and `.github/workflows/issue-pr-governance.yml` before opening or updating a PR.

## Use this lane only when

- the PR is docs-only
- changed files stay inside approved docs-authoring surfaces:
  - `docs/**`
  - `README.md`
  - `AGENTS.md`
  - `CLAUDE.md`
  - `.codex/AGENTS.md`
  - `.github/github-governance.yml`
  - `.github/ISSUE_TEMPLATE/*.yml`
  - `.github/pull_request_template.md`
  - `.github/workflows/issue-pr-governance.yml`
- the change does not alter code, runtime behavior, contracts, or shipped reality

## Working rules

- Classify the PR explicitly as `Docs authoring lane`.
- A governing GitHub Issue is not required for this lane.
- Do not create backlog work automatically; use `docs-to-issue` later if the authored docs should become bounded implementation work.
- Keep current-state docs honest. Do not write future-state intent as shipped reality.
- If the task starts affecting implementation or delivered behavior, stop using this lane and switch back to the normal Issue-first implementation workflow.

## Publication discipline

- Route branch / commit / push / PR actions through `.codex/skills/publish-pr/SKILL.md` — do not run an ad hoc commit/push from this lane. `publish-pr` owns the branch-truth gate.
- Branch-truth gate (mandatory) [branch-truth-gate]: run the canonical gate from `.codex/skills/_shared/BRANCH_TRUTH_GATE.md :: Procedure` — dedicated worktree preferred, capture `EXPECTED_BRANCH`/`EXPECTED_WORKTREE` at branch creation (the capture is required; empty variables disable the drift checks), hardened preflight with `--allow-dirty` before commit and again before push.

## Output posture

- Treat this skill as a routing guide, not a second policy surface.
- Point back to the governing repo docs rather than re-explaining them in detail.

## Capturing learning

**Capturing learning:** if during this work you notice a divergence from plan — you did something you did not expect to do, or discovered an earlier artifact was wrong — route it through `capture-learning`, which owns the invocation timing: invoke immediately only when the divergence needs upstream repair now; otherwise note the signal for `learning-retrospective`. Only log if you can name an upstream artifact that could absorb the fix.
