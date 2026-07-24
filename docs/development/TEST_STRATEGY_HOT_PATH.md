State: Development reference.
Doc role: Test strategy reference.
Authority: Defines the cheapest safe check ladder for hot-path PRs; does not override CI workflows, merge rules, or runtime acceptance.
Owner: Builder-agent governance
Temporal class: operational
Review cadence: event-driven
Source of truth: code, workflow files, and repo-local skill docs
Last reviewed: 2026-07-23
Last verified against: `.github/workflows/ci-smoke.yaml`, `.github/workflows/issue-pr-governance.yml`, `tests/architecture/test_agent_skill_entrypoints.py`, `tests/architecture/test_dispatcher_skill_integration.py`, `docs/development/PR_HOT_PATH.md`, `docs/development/PR_ESCALATION_PATHS.md`, `docs/development/PARENT_ISSUE_CLOSURE.md`, `.codex/skills/issue-to-code/SKILL.md`, `.codex/skills/pr-integration/SKILL.md`, `.codex/skills/verification-and-closure/SKILL.md`, `scripts/select_pr_tests.py`, `scripts/docs_guard_logic.py`

# Test Strategy for the Hot Path

This document classifies PRs by the cheapest safe check level.
The goal is to keep docs-only and governance/skill PRs cheap while preserving direct-repair safety and workflow truth.

## Current Protection Surface

- Skill entrypoints and shared skill-index routing are covered by `tests/architecture/test_agent_skill_entrypoints.py`.
- Dispatcher-oriented skill sequencing is covered by `tests/architecture/test_dispatcher_skill_integration.py`.
- The broad runtime smoke workflow lives in `.github/workflows/ci-smoke.yaml`; it also carries the skills-consistency lint that previously ran in the retired duplicate `smoke` workflow.
- Governance PR contract checks live in `.github/workflows/issue-pr-governance.yml`.
- The hot-path and direct-repair invariants are covered by `tests/architecture/test_pr_hot_path_governance.py`.
- PR unit CI uses `scripts/select_pr_tests.py` to map changed files to subsystem-scoped pytest targets. Shared CI/test configuration, migrations, dependencies, and shared fixtures run the deterministic broad suite; E2E coverage is deferred to post-merge and nightly validation. This document is `scripts/select_pr_tests.py`'s `docs/development/` contract for the `scripts/docs_guard_logic.py :: GOVERNANCE_TEMPORAL_ENFORCEMENT` temporal-owner-doc exemption, and the check enforces that pairing specifically: update this doc, not `docs/STATUS.md`/`docs/ROADMAP.md`/etc., when the selection script's behavior changes.
- Every `builder_system` match includes `tests/architecture/test_builderops_store_boundary.py` as an exact run target, not only as an ownership prefix. Ordinary `app/builderops/**` changes must execute the audited store-access guard so new direct-store sites cannot bypass it while their own subsystem tests remain green.
- Runtime-start harness tests that exercise `scripts/start_full_system.sh` and its process-cleanup behavior are owned by the `ops_deploy` selector, even when the touched files live under `tests/helpers/` or `tests/runtime/`.
- Store and vault-ingest changes are owned by the `store_ingest` selection and run its focused
  `tests/stores`, `tests/ingest`, and architecture contracts in the ordinary `not pg` job. That job
  intentionally excludes live-Postgres tests; a PR that changes a Postgres store or vault ingest
  path must record its explicit `pg`/integrated-runtime validation separately rather than treating
  the selected CI result as database-path evidence.
- E2E tests under `tests/e2e/` run after merge and in the nightly suite, not on ordinary PRs. Opt-in classes (live LLM, browser, human UAT, eval) remain in their dedicated post-merge or nightly lanes.

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
   - Examples: the heavy slices in `.github/workflows/ci-smoke.yaml`.

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
- Run level 4 for the touched runtime surface. In PR CI, the touched System of Interest is selected from changed paths and mapped to focused pytest targets; cross-subsystem paths union their owners' targets, while unknown runtime code fails selection until an owner is declared.
- Run level 5 after merge when the touched runtime surface is the thing smoke is meant to prove.
- Use level 6 for promotion or release validation.

### Release / Promotion PRs

- Run levels 1 through 6 as appropriate, with level 5 and 6 treated as mandatory for the promoted surface.

## Rules

- Docs-only PRs should not run full runtime smoke by default.
- Governance/skill PRs should run cheap skill coherence and workflow invariant tests before any broader smoke.
- Runtime PRs should run focused tests first and add smoke only when the runtime surface is actually touched.
- Subsystem-scoped CI must be conservative: workflow/test configuration, dependency files, migrations, and shared fixtures choose the broad deterministic suite. Unmapped runtime paths fail selection until an owner is declared; they must never silently borrow the whole repository's suite.
- E2E coverage is reserved for post-merge, nightly, or explicit manual verification.
- Slow or flaky test classes should be marked and routed to their dedicated subsystem, nightly, or manual workflow. They must not install dependencies or invoke pytest on unrelated PRs.
- Direct repair PRs are classified by the surfaces they touch, not by whether they carry a governing issue.
- Failing required checks must be classified, not ignored as out-of-scope.
- A required check that is stale, missing, or unrelated to the current head SHA is a blocking classification problem, not a silent pass.
