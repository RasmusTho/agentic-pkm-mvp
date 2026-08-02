State: Development reference.
Doc role: Test strategy reference.
Authority: Defines the cheapest safe check ladder for hot-path PRs; does not override CI workflows, merge rules, or runtime acceptance.
Owner: Builder-agent governance
Temporal class: operational
Review cadence: event-driven
Source of truth: code, workflow files, and repo-local skill docs
Last reviewed: 2026-08-02
Last verified against: `.github/workflows/ci-smoke.yaml`, `.github/workflows/issue-pr-governance.yml`, `tests/architecture/test_agent_skill_entrypoints.py`, `tests/architecture/test_dispatcher_skill_integration.py`, `docs/development/PR_HOT_PATH.md`, `docs/development/PR_ESCALATION_PATHS.md`, `docs/development/PARENT_ISSUE_CLOSURE.md`, `.codex/skills/issue-to-code/SKILL.md`, `.codex/skills/pr-integration/SKILL.md`, `.codex/skills/verification-and-closure/SKILL.md`, `scripts/select_pr_tests.py`, `scripts/docs_guard_logic.py`, `tests/knowledge/linux_acl.py`, `tests/knowledge/test_linux_acl_fixture.py`, `tests/ops/test_review_before_ci_gate.py`, `tests/governance/test_ci_smoke_docs_only_gate.py`

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
- Every `builder_system` match includes `tests/architecture/test_builderops_store_boundary.py` as an exact run target, not only as an ownership prefix. Ordinary `app/builderops/**` changes must execute the audited store-access guard so new direct-store sites cannot bypass it while their own subsystem tests remain green.
- `_is_governance_only`/`_is_docs_only` tolerate a changed `tests/**` path inside `GOVERNANCE_TARGETS`/`DOCS_TARGETS` as scope-neutral so a *pure* governance-only/docs-only PR keeps resolving to that lane. Several of those tolerated directories/files are also real per-subsystem scope signal in `SUBSYSTEMS` (`tests/architecture/test_builderops_store_boundary.py` for `builder_system`, `tests/architecture/test_no_hardcoded_vault_layout.py` for `vault`, `tests/governance/`/`scripts/` for `builder_system`/`ops_deploy`, `tests/ops/` for `ops`) — on a mixed PR that also touches one of those subsystem's owned paths, the selector unions that subsystem's own targets into the governance/docs selection (`_foreign_subsystem_matches`) instead of silently narrowing to the governance/docs-only target set and dropping the other subsystem's real coverage (#4336). `subsystems` then lists every contributing subsystem (e.g. `governance,builder_system`), never just `governance`/`docs` alone, whenever this applies; `tests/scripts/test_select_pr_tests.py`'s mixed-PR cases are the executable proof.
- The neutral top-level `llm_contract/**` leaf is owned by the `model_access` selector. A kernel change runs its direct contract suite, the BuilderOps adapter/runner compatibility suites, and the exact neutral-kernel/import-boundary architecture guards.
- Every `vault` match includes `tests/architecture/test_no_hardcoded_vault_layout.py` as an exact run target, not only as an ownership prefix. Ordinary `app/vault/**` changes must execute the vault-layout guard without widening the subsystem to all architecture tests.
- The `properties` subsystem's trigger set is `tests/properties/` plus `PROPERTIES_CENSUSED_APP_SITES` in `scripts/select_pr_tests.py`: the exact `app/` files indexed by a (file, line)-keyed census registry in `tests/properties/_machinery.py` (`REGISTERED_MIRRORS`, `WRITE_FRONTMATTER_SITE_CLASSIFICATION`, `WRITE_MISSING_SITE_CLASSIFICATION`, `WRITE_NOTE_RELATIVE_SITE_CLASSIFICATION`, `STORE_PAYLOAD_SINK_CLASSIFICATION`). Without this, an ordinary edit to one of those files can shift a censused call site's line number without touching `tests/properties/` at all, so `tests/properties` would not run in that PR's affected-subsystem selection and the census would silently go stale until a later full-suite run caught it (#4269). This is additive: `properties` unions into whatever other subsystem already owns the same file (e.g. `store_ingest`, `promotion_panel`) rather than replacing it. Keep `PROPERTIES_CENSUSED_APP_SITES` in sync with those registries' key sets when either side changes.
- A vault-file replacement may claim Linux ACL preservation only after the real named-user ACL
  fixture in `tests/knowledge/test_linux_acl_fixture.py` passes. The fixture compares the complete
  numeric access ACL before and after a same-directory staged atomic replacement; mode bits alone
  are insufficient. `Unit tests (not pg)` installs Ubuntu's `acl` package before the selected suite,
  and a Linux runner without working `getfacl`/`setfacl` support fails loud rather than skipping or
  emulating the proof. Non-Linux local runs may skip because they do not implement the governed
  Ubuntu platform semantics. This fixture is prerequisite evidence only; it does not claim that an
  unpublished vault replacement mechanism is delivered.
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
