State: Development reference.
Doc role: Test strategy reference.
Authority: Defines the cheapest safe check ladder for hot-path PRs; does not override CI workflows, merge rules, or runtime acceptance.
Owner: Builder-agent governance
Temporal class: operational
Review cadence: event-driven
Source of truth: code, workflow files, and repo-local skill docs
Last reviewed: 2026-05-14
Last verified against: `.github/workflows/smoke.yml`, `.github/workflows/ci-smoke.yaml`, `.github/workflows/issue-pr-governance.yml`, `tests/architecture/test_agent_skill_entrypoints.py`, `tests/architecture/test_dispatcher_skill_integration.py`, `docs/development/PR_HOT_PATH.md`, `docs/development/PR_ESCALATION_PATHS.md`, `docs/development/PARENT_ISSUE_CLOSURE.md`, `.codex/skills/issue-to-code/SKILL.md`, `.codex/skills/pr-integration/SKILL.md`, `.codex/skills/verification-and-closure/SKILL.md`

# Test Strategy for the Hot Path

This document classifies PRs by the cheapest safe check level.
The goal is to keep docs-only and governance/skill PRs cheap while preserving direct-repair safety and workflow truth.

## Current Protection Surface

- Skill entrypoints and shared skill-index routing are covered by `tests/architecture/test_agent_skill_entrypoints.py`.
- Dispatcher-oriented skill sequencing is covered by `tests/architecture/test_dispatcher_skill_integration.py`.
- The broad runtime smoke workflows live in `.github/workflows/smoke.yml` and `.github/workflows/ci-smoke.yaml`.
- Governance PR contract checks live in `.github/workflows/issue-pr-governance.yml`.
- The hot-path and direct-repair invariants are covered by `tests/architecture/test_pr_hot_path_governance.py`.
- PR unit CI uses `scripts/select_pr_tests.py` to map changed files to subsystem-scoped pytest targets. Shared CI/test configuration, migrations, dependencies, and shared fixtures run the deterministic broad suite; an unmapped code or E2E path fails selection until it is assigned to a subsystem.
- E2E tests under `tests/e2e/` are selected by owned file targets, not by the whole directory, for subsystem-scoped PR CI. Opt-in classes (live LLM, browser, human UAT, eval) are excluded from generic PR pytest and run only in their dedicated subsystem lane.

## Check Levels

1. Formatting/static sanity
   - Examples: `ruff`, docs guardrails, YAML/JSON sanity, PR-template classification, and basic file presence.

2. Skill reference/coherence tests
   - Examples: architecture tests that confirm canonical skill entrypoints and declared references stay connected.

3. Governance workflow invariant tests
   - Examples: cheap text checks on `PR_HOT_PATH.md`, `PR_ESCALATION_PATHS.md`, `PARENT_ISSUE_CLOSURE.md`, and the repo-local skill docs.

4. Focused unit/integration tests
   - Examples: tests limited to the changed code path, including narrow behavior tests around touched modules.

5. Runtime smoke tests
   - Examples: `.github/workflows/smoke.yml` and the heavy slices in `.github/workflows/ci-smoke.yaml`.

6. Release/promotion smoke
   - Examples: promotion-channel or release-specific smoke that proves the runtime surface being released is healthy.

## PR Type Mapping

### Docs-only PRs

- Run level 1 always.
- Run level 2 when docs changes touch skills, routing, or entrypoints.
- Run level 3 when docs change workflow or governance contracts.
- Do not run full runtime smoke by default.
- Run level 5 only if the docs change alters a runtime surface or a release contract.

### Governance / Skill PRs

- Run level 1.
- Run level 2 for skill entrypoint or routing changes.
- Run level 3 for workflow, hot-path, direct-repair, or closure invariants.
- Run level 4 only if the change also touches executable code.
- Do not run full runtime smoke unless the PR touches runtime surface, CI logic that gates runtime, or a release contract.

### Runtime / Code PRs

- Run level 1.
- Run level 2 if the change affects skills or agent entrypoints.
- Run level 4 for the touched runtime surface. In PR CI, the touched System of Interest is selected from changed paths and mapped to focused pytest targets; cross-subsystem paths union their owners' targets, while unknown code and E2E paths fail selection until an owner is declared.
- Run level 5 only when the touched runtime surface is the thing smoke is meant to prove.
- Use level 6 for promotion or release validation.

### Release / Promotion PRs

- Run levels 1 through 6 as appropriate, with level 5 and 6 treated as mandatory for the promoted surface.

## Rules

- Docs-only PRs should not run full runtime smoke by default.
- Governance/skill PRs should run cheap skill coherence and workflow invariant tests before any broader smoke.
- Runtime PRs should run focused tests first and add smoke only when the runtime surface is actually touched.
- Subsystem-scoped CI must be conservative: workflow/test configuration, dependency files, migrations, and shared fixtures choose the broad deterministic suite. Unmapped runtime or E2E paths fail closed until an owning subsystem and focused test target are declared; they must never silently borrow the whole repository's suite.
- E2E coverage must be split by subsystem-owned files. A subsystem target may include only the e2e flows it owns or shares; `tests/e2e` as a whole is reserved for full fallback, nightly, or explicit manual verification.
- Slow or flaky test classes should be marked and routed to their dedicated subsystem, nightly, or manual workflow. They must not install dependencies or invoke pytest on unrelated PRs.
- Direct repair PRs are classified by the surfaces they touch, not by whether they carry a governing issue.
- Failing required checks must be classified, not ignored as out-of-scope.
- A required check that is stale, missing, or unrelated to the current head SHA is a blocking classification problem, not a silent pass.
