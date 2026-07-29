State: Development reference.
Doc role: Test strategy reference.
Authority: Defines the cheapest safe check ladder for hot-path PRs; does not override CI workflows, merge rules, or runtime acceptance.
Owner: Builder-agent governance
Temporal class: operational
Review cadence: event-driven
Source of truth: code, workflow files, and repo-local skill docs
Last reviewed: 2026-07-29
Last verified against: `.github/workflows/ci-smoke.yaml`, `.github/workflows/architecture-ci.yaml`, `scripts/docs_guard.py`, `.github/workflows/issue-pr-governance.yml`, `tests/architecture/test_agent_skill_entrypoints.py`, `tests/architecture/test_dispatcher_skill_integration.py`, `docs/development/PR_HOT_PATH.md`, `docs/development/PR_ESCALATION_PATHS.md`, `docs/development/PARENT_ISSUE_CLOSURE.md`, `.codex/skills/issue-to-code/SKILL.md`, `.codex/skills/pr-integration/SKILL.md`, `.codex/skills/verification-and-closure/SKILL.md`, `scripts/select_pr_tests.py`, `scripts/docs_guard_logic.py`, `tests/ops/test_review_before_ci_gate.py`, `tests/governance/test_ci_smoke_docs_only_gate.py`

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
- Statically declared selector file and node-id targets must be collectable. Before pytest receives a selected node id, the selector checks its file portion exists; its always-selected selector fitness test collect-checks every static file/node-id target so a rename or deletion fails in the changing PR rather than an unrelated downstream selection.
- The `pr-unit-tests-not-pg` (`Unit tests (not pg)`) job's `code` paths-filter in `.github/workflows/ci-smoke.yaml` includes `AGENTS.md`, `CLAUDE.md`, `.codex/**`, and `docs/**` (#4281): a PR touching only those paths runs the real lane (install, mypy, the KERNEL-13 gate, the selected pytest run) instead of self-skipping to a bare `success`. Once the filter fires, `scripts/select_pr_tests.py`'s shared `GOVERNANCE_TARGETS` (used by both the governance-only branch and the `docs_authoring` subsystem) includes `tests/architecture` and `tests/ops/test_review_before_ci_gate.py` alongside `tests/governance`/`tests/scripts`/`tests/ops/test_ci_workflow.py`, because those are the suites that actually assert on `AGENTS.md`/`CLAUDE.md`/`.codex/**`/`docs/**` content; `CLAUDE.md` is also in the docs-only exact-match set alongside `AGENTS.md` so a `CLAUDE.md`-only PR resolves to the scoped docs lane rather than the unowned/full-suite fallback. `tests/governance/test_ci_smoke_docs_only_gate.py` is the executable proof for this pairing, including a reproduction of the exact diff shape from PR #4275.
- `DOCS_TARGETS` includes `tests/governance` alongside `tests/docs`, `tests/architecture`, and `tests/ops/test_review_before_ci_gate.py`. Only `docs/development/**` matches `_is_governance_only`'s prefixes, so every other governance-relevant doc — `docs/AGENT_ISSUE_DISPATCHER.md`, `docs/ARCHITECTURE.md`, `docs/architecture/SBS_OPERATING_MODEL.md`, `docs/STATUS.md`, `docs/ROADMAP.md`, `docs/DESIGN_HANDOFF_GOVERNANCE.md`, `docs/adr/**`, `docs/testing/invariant-tests.md` — resolved to the docs branch, whose targets omitted `tests/governance` entirely. Editing one of those files could break the governance module that reads it (`test_project_pickup_deprecation.py`, `test_codex_agents_contract.py`, `test_known_defects_registry.py`, `test_issue_pr_governance.py`, `test_vault_multiwriter_frontmatter.py`) while the required check still reported success. `tests/governance/test_ci_smoke_docs_only_gate.py::test_docs_only_lane_runs_the_governance_suite_that_asserts_on_docs` is the executable proof. Cost: the docs lane grows by the `tests/governance` directory; it stays a scoped selection and never escalates to the full suite.
- `scripts/docs_guard.py` runs on the PR path from the `smoke` job in `.github/workflows/ci-smoke.yaml`, gated on a `governance_docs` paths-filter (`AGENTS.md`, `CLAUDE.md`, `.codex/**`, `docs/**`) **and** `heavy_smoke != 'true'`. Its only previous caller was `architecture-ci.yaml`, which has been `workflow_dispatch`-only since #3892, so the guard ran on no pull request at all. The scoping is deliberate: the guard's `app/**`-versus-docs and temporal-owner-doc rules fire on `app/**`, `scripts/**`, and `config/**` changes, so an unscoped step would newly fail a large class of ordinary runtime PRs — a separate decision from closing the docs-side coverage gap. `heavy_smoke` is the exact complement of that runtime surface, so the step can only fire on the governance/docs-only shape the guard was written for.
  - Known consequence, accepted deliberately: `docs/settings/**` is in `scripts/docs_guard_logic.py :: TEMPORAL_CODE_PREFIXES`, so a PR that changes only `docs/settings/**` (agent prompts, panel-action wiring, model config) now fails this step unless it also touches one of the six `TEMPORAL_DOCS`. That is the guard's declared contract for a temporal config surface rather than an incidental side effect; `DOCS_GUARD_ALLOW_TEMPORAL_SKIP=1` is the documented escape hatch. If this proves too strict in practice, the narrow revert is to exclude `docs/settings/**` from the `governance_docs` filter, not to unscope the step.
- `heavy_smoke` is intentionally **not** widened to `AGENTS.md`, `CLAUDE.md`, `.codex/**`, or `docs/**`. Every step it gates is runtime-code-only (`tests/smoke`, `test_indexer`, `test_fs_watcher`, the import/port/vault contracts, the Quality Wave UAT harness) and none of them read those paths, so including them would buy a docs typo the full runtime smoke and no additional assertion. The coverage that surface needs comes from the `Unit tests (not pg)` selector and the docs guard above, not from the heavy slices. `tests/governance/test_ci_smoke_docs_only_gate.py::test_heavy_smoke_stays_off_the_docs_surface` holds this line.
- Every `builder_system` match includes `tests/architecture/test_builderops_store_boundary.py` as an exact run target, not only as an ownership prefix. Ordinary `app/builderops/**` changes must execute the audited store-access guard so new direct-store sites cannot bypass it while their own subsystem tests remain green.
- Every `vault` match includes `tests/architecture/test_no_hardcoded_vault_layout.py` as an exact run target, not only as an ownership prefix. Ordinary `app/vault/**` changes must execute the vault-layout guard without widening the subsystem to all architecture tests.
- Runtime-start harness tests that exercise `scripts/start_full_system.sh` and its process-cleanup behavior are owned by the `ops_deploy` selector, even when the touched files live under `tests/helpers/` or `tests/runtime/`.
- Store and vault-ingest changes are owned by the `store_ingest` selection and run its focused
  `tests/stores`, `tests/ingest`, and architecture contracts in the ordinary `not pg` job. That job
  intentionally excludes live-Postgres tests; a PR that changes a Postgres store or vault ingest
  path must record its explicit `pg`/integrated-runtime validation separately rather than treating
  the selected CI result as database-path evidence.
- The exact shared producer `app/objects/__init__.py` uses the same `store_ingest` selection: its
  canonical object-store facade writes through the store provider seam and emits ingest lifecycle
  events, and its selection includes the exact ObjectStore outbox-emission regression. The exact
  `app/outbox/events.py` producer belongs to both `outbox_worker` and `memory_retrieval`, so its
  selection unions delivery-worker/event, indexer, and event-envelope contract coverage. Other
  `app/objects/**` and `app/outbox/**` paths remain unowned unless explicitly mapped.
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
