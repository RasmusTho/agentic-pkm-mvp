State: Development reference.
Doc role: Test strategy reference.
Authority: Defines the cheapest safe check ladder for hot-path PRs; does not override CI workflows, merge rules, or runtime acceptance.
Owner: Builder-agent governance
Temporal class: operational
Review cadence: event-driven
Source of truth: code, workflow files, and repo-local skill docs
Last reviewed: 2026-10-31 UTC (Issue #6504 exact Panel CLI test ownership)
Last verified against: `scripts/dev_delivery_liveness.py`, `tests/governance/test_dev_delivery_liveness_workflow.py`, `tests/scripts/test_select_pr_tests.py::test_liveness_checker_source_selects_its_contract_tests`, `.github/workflows/ci-smoke.yaml`, `.github/workflows/import-linter.yaml`, `.github/workflows/browser-runtime.yml`, `.github/workflows/issue-pr-governance.yml`, `.github/workflows/integration-nightly.yaml`, `.github/workflows/app-image-build.yml`, `scripts/deploy_channel.sh`, `tests/architecture/test_agent_skill_entrypoints.py`, `tests/architecture/test_dispatcher_skill_integration.py`, `docs/development/PR_HOT_PATH.md`, `docs/development/PR_ESCALATION_PATHS.md`, `docs/development/PARENT_ISSUE_CLOSURE.md`, `.codex/skills/issue-to-code/SKILL.md`, `.codex/skills/pr-integration/SKILL.md`, `.codex/skills/verification-and-closure/SKILL.md`, `scripts/select_pr_tests.py`, `scripts/plan_full_suite_node_shards.py`, `tests/scripts/test_select_pr_tests.py`, `tests/governance/test_issue_pr_governance.py`, `tests/governance/test_governed_vault_profile_contract.py`, `tests/governance/test_governed_vault_profile_proposals.py`, `tests/agents/test_reviewer.py`, `tests/agents/test_reviewer_single_note.py`, `scripts/docs_guard_logic.py`, `tests/scripts/test_docs_guard.py`, `tests/knowledge/linux_acl.py`, `tests/knowledge/test_linux_acl_fixture.py`, `tests/ops/test_ci_workflow.py`, `tests/ops/test_review_before_ci_gate.py`, `tests/governance/test_ci_smoke_docs_only_gate.py::test_product_reasoning_facade_selects_its_llm_tests`, `tests/governance/test_ci_smoke_post_merge_proof_concurrency.py`, `docs/plans/FAST_PR_TO_DEV_TEST_AUTOMATION.md`, Issues #5820 / PR #5838, #6498 and #6504 selector coverage using `tests/scripts/test_select_pr_tests.py::test_product_embedding_adapters_select_their_regression_coverage` and `tests/scripts/test_select_pr_tests.py::test_cli_rejects_an_unowned_path`, `scripts/await_pr_checks.sh`, `tests/scripts/test_await_pr_checks.py`, `.codex/skills/_shared/CI_WAIT_CONTRACT.md :: Rules`
Last verified against (reasoning_expansion UAT selector): Issue #6293, `scripts/select_pr_tests.py`, `tests/scripts/test_select_pr_tests.py::test_expansion_uat_paths_are_owned`, and the scoped Expansion runner suite; selector routing verified, live TEST remains opt-in and separate.

# Test Strategy for the Hot Path

This document classifies PRs by the cheapest safe check level.
The goal is to keep docs-only and governance/skill PRs cheap while preserving direct-repair safety and workflow truth.

## Text-only CI

The selector's `requires_runtime_checks` classifies diffs limited to root contributor Markdown,
`docs/**/*.md`, and `.codex/**/*.md` as text-only. They still execute the selected docs/governance
contract tests and documentation guards. The PR unit job skips repo-wide mypy, the product intent
classification golden gate and Linux ACL provisioning for those diffs. Sidecar dependencies remain
installed for conservative contract/collection compatibility.
Executable files outside the exact CI contract scope below, fixtures, mixed changes and runtime
configuration remain conservative and enable those gates. This classification does not turn a
required check into a bare skipped success or remove exact AC coverage. A Markdown suffix outside
these roots is not documentation proof.

The merge path stays distinct from post-merge runtime feedback. #5922 supplies exact-image admission
and private-controller `dev` → `test` support; #5932 adds isolated PostgreSQL acceptance to its native
verification phase. #5675 transfers the retained PG PR coverage only after actual equivalent native
execution passes in both channels. [`FAST_PR_TO_DEV_TEST_AUTOMATION`](../plans/FAST_PR_TO_DEV_TEST_AUTOMATION.md)
records activation and ten-candidate measurement; measurement does not gate ordinary candidates.

## Exact CI contract scope

`scripts/select_pr_tests.py :: CI_CONTRACT_PATHS` is the closed set of CI inspection/selection
sources, direct test modules and named development owner documents eligible for focused CI proof.
Every changed path must belong to that set. `CI_CONTRACT_TARGETS` retains common CI checks, the
complete governance suite, helper and replay regressions, actual workflow-command tests and direct
architecture consumers. It avoids unrelated script suites and Product source/DDL/projection scans
when no Product source can have changed. The static-target collectability check remains explicit.

Both selected tests and `runtime_checks=false` derive from this same predicate. The required
`Unit tests (not pg)` check still executes its substantive pytest command, markers, watchdog and
failure handling. It omits unrelated `mypy app`, classification replay and ACL provisioning for this
scope. Smoke consumes the real Git diff through the same selector and omits runtime smoke and
full-tree collection for contract-only PRs, while retaining lint, docs and other cheap checks.
Non-PR smoke and nightly execution retain broad discovery. Missing scope output does not waive
runtime work; a failed classifier keeps the job red. The exact CI sources still require their paired
development owner documents through the docs guard.

Product/operational code, migrations, dependencies, shared fixtures, foreign test modules, other
workflows and unknown paths disqualify the strict scope and retain their normal selection and
runtime checks. In mixed changes the exact CI files contribute CI contract tests, rather than
acquiring unrelated Ops/deploy ownership from their `scripts/` or `tests/ops/` location. Actual
operational paths retain their owners. When a CI helper under `scripts/` or `tests/scripts/`
accompanies a direct deploy input, retain the deploy proof formerly selected by that helper's
directory ownership. The heavy-target trigger inventory filters selected suites; it does not
establish new source-only ownership. A file copied into a deploy fixture does not by itself
justify running every deploy test. Other Product and operational selection stays unchanged.
`tests/scripts/test_select_pr_tests.py` covers these mixed-change boundaries and
changed-test inclusion. `tests/governance/test_ci_smoke_docs_only_gate.py` executes the actual YAML
classification command against real finite Git diffs and checks its consumers. Workflow failure,
timeout, coverage and process-cleanup proofs stay in `tests/ops/test_ci_workflow.py`.

The shared DEV/TEST activation helper `app/config/activation_scope.py` has exact
ownership in both `companion_ui` and `ops_deploy`, retaining API and native-deploy
proof after heavy-target filtering. Its exact heavy-input entry and the API
factory input read by the pre-scope-image regression retain selected deployment
coverage. Unknown sibling config paths remain unowned and refuse; no config
prefix or text-only runtime exception is introduced. The regression is
`tests/scripts/test_select_pr_tests.py::test_activation_scope_helper_selects_api_and_native_deploy_coverage`.

### Exact PR intake and publication source scope

The bounded route is available only when a change includes one of these exact source paths or one
of the seven additional direct-reader target modules named below, and every co-change belongs to
the explicit reader/owner-doc list or the existing exact CI contract paths:

- `.github/workflows/issue-pr-governance.yml`
- `app/builderops/publication.py`
- `app/dispatcher/verification_contract.py`
- `scripts/pr_body_generator.py`
- `scripts/review_before_ci_gate.py`

The exact direct-reader tests and owner documents are listed in `scripts/select_pr_tests.py`.
`docs/ARCHITECTURE.md` is admitted only alongside one of those sources or one of those seven direct
reader modules; an architecture-only or other docs-only PR keeps its existing route. For this exact scope,
the selector unions direct publication and fenced-dispatch readers (`tests/scripts/test_publication.py`,
`test_closure.py`, `test_pr_body_generator.py`, `test_build_pr_evidence_pack.py`,
`tests/dispatcher/test_verification_dispatch.py`, `test_verified_merge.py`, and
`tests/ops/test_builderops_package_smoke.py`) with the base `CI_CONTRACT_TARGETS`. Ordinary CI-helper
PRs do not pay for these additional modules. Existing governance, review-gate, architecture,
workflow, lint and static-target collectability proof stays in the selection. Non-closing intake
remains covered by the actual generator/publication and governance readers, and fenced merge
authority remains covered by the dispatcher merge tests.

Executable app and publication/review script sources in this scope keep `runtime_checks=true`,
including when a PR changes only one of those scripts. This preserves the mandatory `mypy app`
gate and the existing runtime checks while pytest uses the narrower direct-reader set. A workflow-only
or direct-reader-test-only change has no app type-check requirement. Any unrelated Product/native
source, other BuilderOps, dispatcher or script source, dependency, shared fixture, deploy input,
workflow, test outside both the explicit reader list and existing CI contract paths, or unknown path
disqualifies the scope and restores normal owner routing.

### Exact BWS control installation source scope

A change to `app/ops/bws_control_installation.py` may use its complete
`tests/ops/test_bws_control_installation.py` module plus `ALWAYS_TARGETS`, including CI integrity
and the common architecture checks. The only admitted co-changes are that test module and
`docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md`. The helper and its test must both exist as tracked
regular files; changed owner docs must also exist. This route retains the `ops` owner and
`runtime_checks=true`, including the normal type/runtime gates. It avoids the unrelated Ops sibling
suite while the helper has no operational caller; it does not classify arbitrary source as isolated.

The selector reuses its static Python dependency census to check consumers of both the helper and
its test fixtures. Imports, literal dynamic imports, bare/relative imports and literal file readers
outside the selected module and common CI/architecture surfaces restore normal owner coverage.
Plain selector and selector-regression literal path data do not count as execution consumers;
actual imports, file readers and opaque code in those files still restore coverage. Only complete
file/directory targets establish consumer coverage; a static collectability node does not cover
other tests in its module. File-reference matching normalizes an explicit `./` prefix. Missing files,
renames, unrelated co-changes, failed inventory/read/parse checks, or opaque known consumers also
restore normal routing. Test-only and docs-only changes keep their existing route. Static analysis
cannot establish every computed dependency; broad nightly/manual coverage remains the backstop.
`tests/scripts/test_select_pr_tests.py::test_bws_control_source_contract_keeps_ops_runtime_and_complete_proof`
and its consumer/refusal regressions cover this exact boundary.

### Native deployment-control serial coverage

Ops-only selections use the existing bounded process runner with complete whole-module
selected inventories. Their eight host-sensitive modules still start only after all parallel
processes exit successfully, including collected-node verification. A failed parallel pytest,
timeout or invalid node result keeps the verdict red after every parallel child is reaped;
its logs and evidence remain in the aggregate, and the serial log explicitly lists its targets
as `NOT RUN`. Green parallel runs retain the complete selected serial coverage. This also applies
to the legacy serial-last route. Shared configuration and mixed subsystem routing retain their existing paths.
The runner authenticates expansion of the complete Ops directory before execution.

When explicitly selected, only `tests/ops/test_native_source_diagnostic_admission.py` may refine
into two disjoint collected-node units through the existing finite planner. Its 394 current cases
split into 197 plus 197; the complete collected inventory and one result per node remain required,
without a permanent case count. Other Ops modules stay atomic and jobs=1 retains the whole file.
The `composed` fixture is function scoped: authority, vault, journals and witness files use each
case's temporary roots; external process/filesystem ports and shared environment/cache substitutes
are process local. The intentional runtime-UID proof subprocess reads fixture state with bytecode
writes disabled. Four-worker concurrency and serial-after-parallel ordering remain unchanged.

[Source PR #6428 Unit](https://github.com/RasmusTho/agentic-pkm-mvp/actions/runs/40788213835/job/123166626373)
took 745 seconds: 89 seconds before scoped pytest, a 483.41-second critical parallel unit, and
156.42 seconds of trailing serial pytest. Its other parallel units took 47.99, 51.62 and 159.28
seconds. The byte-identical diagnostic-admission module alone spanned at least 454.329 seconds
in PR #6411. These observations motivate the finite split; they do not establish a new speedup
or a ten-minute completion bound.

An additional closed source-installation profile permits only
`app/ops/bws_installation_transaction.py`, `app/ops/postgres_deploy_linux.py`,
`app/ops/bws_installation_lifecycle.py`, `tests/ops/test_bws_installation_lifecycle.py`,
`app/ops/bws_installation_admission.py`, `tests/ops/test_bws_installation_admission.py`,
`tests/ops/test_bws_installation_transaction.py`, `tests/ops/test_bws_control_installation.py`,
`tests/ops/bws_control_path_diagnostic_cases.py`,
`tests/deploy/test_bws_source_rpc_assembly.py`, `docs/OPERATIONS.md`,
the exact test-data path `tests/ops/fixtures/host_secret_contract_legacy.json`, and
`docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md`, plus exact inputset-repair cochanges to
`scripts/select_pr_tests.py`, `tests/scripts/test_select_pr_tests.py` and this owner document,
with at least one transaction or Linux-deploy source changed and
regular nonsymlink inputs. It omits only `test_dormant_ownership_initialization.py`;
all other Ops modules and seven serial boundaries remain. Unknown cochanges retain broad
coverage. The pre-existing native deployment-control profile below has precedence.

The admission/receipt and verified-RPC cochanges retain this same closed profile. The complete
RPC test file adds `ops_deploy` ownership even when the whole deploy directory is deferred;
successful profile qualification keeps the existing bounded execution route in that case.
Subsystem labels and deferred targets remain unchanged. The full RPC file stays in the nonserial
inventory with its per-case temporary roots and disposable resource-limited subprocess; all seven
existing serial suites still follow successful parallel work and node-evidence validation.
Unknown production paths and shared-fixture cochanges retain normal routing.

The exact synthetic diagnostic helper retains all four whole admission/lifecycle/transaction/RPC
consumer modules. Selector-repair cochanges retain their complete governance and CI coverage.
These paths are allowed cochanges, not additional qualifying sources or a general helper policy;
missing or symlinked inputs fail closed. Existing bounded execution, seven serial guards,
120-second per-test limits and the 75-minute scoped-step limit remain unchanged.

With explicit baseline evidence, an additional ordinary test module can be a neutral cochange
only when the unchanged closed BWS paths already qualify and their retained selection covers
the whole module before that cochange is considered. Partial node targets cannot supply this
proof. The CLI locks its base/head revisions and uses their unique merge-base; each extra module
must be a regular file in that commit and a regular nonsymlink file in the checkout. New modules,
missing or unavailable baseline evidence, ambiguous merge-bases, known helpers/fixtures/support
paths, conftest/configuration and the omitted Dormant module retain broader selection. Direct
selector calls without an explicit immutable baseline keep the exact path policy above.
The original subsystem labels and complete target union are preserved after qualification.

This is a bounded CI policy for ordinary test modules, not a complete dependency proof: a normally
named test module could have undeclared shared-helper consumers. That residual risk is accepted
within this profile because the changed module still runs in full and production paths remain
closed. Module-local fixtures are permitted; shared fixture paths and runtime gates are unchanged.

The control-installation module tests the Source transaction's public-file compensation port
with temporary files and explicit process/network/Product import guards. Its legacy contract
fixture is test data shared with the transaction tests; other fixture or configuration paths
retain normal routing.
The lifecycle pair covers the Source transaction's empty-control revalidation before backup.
It is an allowed cochange, not another qualifying source: lifecycle-only changes retain broad
coverage. These profile and red-run changes do not establish a ten-minute CI bound.

Dormant initialization protects Product/Runtime TEST vault and ledger ownership. Its actual
CLI is `app.instance.runtime`, not the generic application CLI. A conservative static import
closure of 453 local modules did not reach either source-installation module; the remaining
nonliteral import iterates five fixed runtime/ledger/inventory module names in
`legacy_owner_recovery.py`. Copying the source tree and checking its Git identity supplies
source-integrity evidence, not BWS behavior coverage. This is a specific independence claim,
not general Ops isolation; source/type/integrity checks remain required.

[PR #6411 Unit](https://github.com/RasmusTho/agentic-pkm-mvp/actions/runs/40694697597/job/122838247994)
completed in 28m56s, with 4434 passing tests in 1619.93s. Within-module log timestamps give
an eight-module serial lower bound of 841s, including 672s for dormant initialization.
These historical measurements do not establish a speedup or a ten-minute bound for the new route.


A diff containing at least one of `app/ops/host_secret_controller.py`,
`app/ops/postgres_deploy.py`, `app/ops/postgres_deploy_linux.py` or
`app/ops/postgres_deploy_host.py` may omit seven unrelated serial sibling modules.
The complete changed-path set must fit `NATIVE_DEPLOY_CONTROL_PATHS` in the selector:
the four sources, their explicitly listed existing test modules, and only
`docs/OPERATIONS.md`, `docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md` or
`docs/CLOUD_SECRET_PROVISIONING/README.md`. Missing/deleted or symlinked inputs,
launcher changes, shared fixtures/helpers, excluded tests, their instance/startup/git
producers, and any other co-change retain normal routing.

This route expands the normal `tests/ops` target to its complete current test-file
inventory, excluding only `test_git_hygiene.py`,
`test_dormant_ownership_initialization.py`, `test_instance_state_deployment_lease.py`,
`test_instance_state_volume_contract.py`, `test_instance_state_writer_inventory.py`,
`test_mvr05_mixed_version_fence.py` and `test_start_full_runtime_health.py`.
All other selected targets and runtime checks remain; `test_native_journaling_acceptance.py`
still runs after parallel work under the unchanged serial-boundary rules. Changed tests
remain selected. The existing bounded partitioner receives the explicit remaining Ops
modules; the omitted modules are not moved into parallel execution.

[PR #6385 CI2](https://github.com/RasmusTho/agentic-pkm-mvp/actions/runs/40618058533/job/122585111569)
measured 63m08 for Unit: its critical parallel shard took 2470.14 seconds, followed by
1149.26 seconds for the eight-module serial boundary. The CI-only #6378 run selected
1822 tests without that boundary and is not comparable protected-source coverage.
Removing unrelated serial work does not establish a ten-minute supervisor/recovery
check or a measured saving; the relevant process, journal and recovery tests remain.

## Test-only scope

Ordinary changes confined to existing test modules run those complete modules, their transitive
static import consumers, and `CI_INTEGRITY_TARGETS`. Imports of shared helpers exported by a test
module therefore retain their actual consumers without selecting entire sibling test directories.
The selector also retains test readers that name another test file literally. Its source parsing
is cached only in the current process, keyed by file metadata; there is no stored dependency graph.
This general route keeps `runtime_checks=true` and the usual dependencies, ACL provisioning,
markers and watchdog. It does not change Product-source selection or the exact CI contract route.

The Sources-zone caller census (`tests/architecture/test_sources_zone_writers.py`) has exact
ownership in the existing vault CI route. A census-only change retains the complete module,
its static test consumers and common CI checks; mixed changes retain vault/instance/knowledge
coverage. Unknown architecture siblings remain unowned and refuse selection.

Shared fixture/helper/support files, conftest, pytest hooks/plugins, configuration, dependencies,
Product or mixed changes, deleted/renamed or unknown paths keep their normal broader scope.
Outgoing computed imports, wildcard imports, and code/file loaders in the originally changed
owned test modules do not broaden selection: those complete modules still run. Explicit pytest
hooks/plugins retain precedence and disqualify even those changed modules. Additional incoming
consumers with computed imports or file loaders still disqualify the narrow route. Static
analysis cannot prove the absence of every dynamic dependency or collection-order coupling;
the existing broad nightly/manual execution remains the backstop. This trades delayed discovery
of those test-harness defects for shorter ordinary PR feedback, without weakening runtime guards.

When every changed path belongs to `ISOLATED_TEST_MODULES`, run its named representative tests and
`CI_INTEGRITY_TARGETS`. This mapping replaces the previous whole-module opt-in; it is not a generic
filename shortcut. The initial entry is the self-contained dormant-ownership fixture module:
eight cases cover admission, refusal, concurrency, real native success, foreign ownership,
source tampering, cleanup retry and durability failure. Named-node collectability and the
no-consumer boundary remain mandatory. The test environment, dependencies, markers and watchdog
remain enabled. `runtime_checks=false` omits
unrelated `mypy app`, Product classification replay, ACL provisioning, runtime smoke and full-tree
collection. The admitted module and common CI tests need no ACL command-line tools; their real
filesystem tests use POSIX operations. This opt-in smoke takes priority over the general test-module
route. Shared fixtures, helpers, configuration and mixed source changes retain their normal scope. A
test filename alone never qualifies for this smoke: existing
test modules also export shared helpers. The static-selector integrity check rejects imports of
an opted-in module from other tests, including literal dynamic imports.

This accepts delayed discovery of test/harness defects in the remaining fault matrix. The existing
nightly/manual broad run still executes all 118 cases; Product/native source or shared-fixture
co-changes retain full pre-merge coverage. Smoke success is not exhaustive verification. Explicit
contract requirements for the full matrix still require that evidence. Keep reusable support in
shared locations so changes to it retain broader coverage. There is no timeout shortcut and no
success without executing the selected tests.

## CI wait budgets

`scripts/await_pr_checks.sh` allows 90 minutes by default around the existing 75-minute unit-step
ceiling, with the existing 180-second initial pause and 90-second REST cadence. Callers may select a
shorter `--timeout` for a known workload. The read-only stall classifier uses 90 minutes for a running
`Unit tests (not pg)` check and 30 minutes for queued/other checks, unless the caller overrides the
budget. An elapsed budget or missing timestamp calls for inspecting progress and diagnostics;
neither establishes a hang or justifies a rerun. This fixes waiting guidance and does not speed up
test execution. `tests/scripts/test_await_pr_checks.py` exercises a long-running job through the real
shell helper with a fake clock; `tests/scripts/test_ci_stall_classifier.py` covers the budgets,
overrides, missing timing and terminal failures. The shared procedure remains
`.codex/skills/_shared/CI_WAIT_CONTRACT.md`. Required contexts are scoped to the target repository:
readable branch-protection contexts take precedence; when protection is unavailable, the Hub keeps
its documented `main` fallback (`Unit tests (not pg)`) and `stable` fallback (`smoke`,
`smoke-docker`, `pr-contract`). If protection is unavailable or returns no contexts, a non-Hub
target must supply its required contexts with one or more `--required-check` flags; without a profile,
the waiter fails closed before polling. `--sha` remains diagnostic and skips merge-gating
required-check resolution.

Diffs limited to the read-only CI wait helpers (`scripts/await_pr_checks.sh` and
`scripts/ci_stall_classifier.py`) plus their exact CI contract tests and existing governance/docs
surfaces use the existing governance contract selection, including their real shell/REST fixtures
in `tests/scripts`. Selector source/tests share this exact contract ownership. These changes
avoid unrelated host-global operations coverage. Co-changed runtime/operational sources still
select their normal coverage; migration and shared configuration changes still select the broad
suite. `tests/scripts/test_select_pr_tests.py` covers both the narrow selection and protected unions.
The exact CI-workflow contract test shares this ownership; unrelated ops tests retain their owners.
Smoke reuses `ffmpeg` and `ripgrep` when both runner tools are already available, avoiding an
unnecessary package-server dependency. If either is missing, the existing package installation runs
and any failure stays red. The actual YAML command is exercised with present/missing tools and an
installation failure in `tests/ops/test_ci_workflow.py`.

## PR latency evaluation

For the next five eligible ordinary PRs, evaluate required feedback and the complete relevant CI
critical path against a target below ten minutes. Prioritize test/CI improvements during this
evaluation. This is a target, not a timeout or a measured result. Use existing PR/job timestamps and
session evidence to compare selected scope, setup/type-check/test time, owner interventions, reruns
and escaped-defect recovery. Separate protected heavy changes from ordinary changes rather than
hiding them in one average. Do not create another tracker or claim that five deliveries establish a
rare-defect rate.

An eligible change is bounded and recoverable; migrations, destructive writes, source-data integrity,
credentials, writer concurrency and deployment-state transitions retain relevant deeper proof before
merge. Ordinary Product paths already select focused suites. Narrow an overbroad mapping only with
named behavioral coverage for the affected artifact and direct regression proof for mixed changes.
Broad regression coverage remains available in the existing nightly/manual workflow. Shared-host
isolation and current-head merge checks remain applicable. Evaluate whether usable delivery and owner
effort improved before adopting further changes.

## Current Protection Surface

- The existing Companion UI browser-runtime gate also executes
  `tests/companion_ui/test_vault_browser_state_runtime.py`: populated, empty,
  partial and error lists crossed with available/unavailable identity at desktop
  and narrow persistent-pane widths. The real renderer runs in offline Chromium;
  the suite checks healthy rows in partial results, distinct degraded states,
  exact read-only keyboard navigation, browser errors and unexpected egress or
  mutating requests. Run locally with
  `COMPANION_UI_BROWSER_TESTS=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/companion_ui/test_vault_browser_state_runtime.py`.
  Set `COMPANION_UI_STATE_EVIDENCE_DIR` to retain fixture-only screenshots and
  traces; CI archives these with JUnit at its exact checkout SHA. All twenty
  cases must pass, including the four regressions for simultaneous partial/error
  and unresolved-identity notices (repaired registry `KD-87DEE784B97A`, #5980).
  The advisory runner rejects skips, xfails, failed, missing or duplicate cases
  before any model dispatch. These results prove offline
  browser behavior, not mobile-overlay or deployed dev/test acceptance. Live
  core-flow coverage is separately tracked by Issue #5942.
- The optional Jev semantic pilot is versioned in `scripts/run_jev_browser_advisory.py`
  and protected by `tests/companion_ui/test_jev_advisory.py`. Browser CI retains a source-bound
  unassessed semantic report alongside its blocking exact matrix; live daily Mac checks use the
  existing direct helper and a retained no-replay report. Supported/contradicted/unknown judgments
  stay advisory. Execution, input limits and the one-month review are owned by
  `docs/TESTING.md :: Companion UI Browser Runtime Tests`.
- Managed Focus owner-fact identity is covered by sixteen blocking Playwright cases in
  `tests/companion_ui/test_focus_owner_facts_runtime.py`. The production listener and shell
  consume synthetic external receipt responses through the existing validated transport.
  Complete case-equivalent subjects retain source lineage; readiness-only, ask-only,
  unavailable, invalid-receipt and unrelated-source cases preserve independent facts and
  limitations. Browser CI runs `--surface focus-owner-facts` and archives source-bound
  screenshots, traces, JUnit and an unassessed advisory report. Daily Mac checks may assess
  new relevant Focus changes with the separate finite facts/authority rubric; they add no
  acceptance or execution authority.
- Focus evidence-state aggregation has a separate sixteen-case blocking matrix in
  `tests/companion_ui/test_focus_evidence_state_runtime.py`. It reaches the managed HTTP route,
  production composer and existing shell with finite synthetic source inputs. A fresh watermarked
  empty read is ready; stale/unknown empty, partial/unavailable/unread evidence and unavailable
  governing sources retain their warnings or blocking state without granting action authority.
  Browser CI archives the offline state/authority report and diagnostics; the existing Mac advisory
  checks may assess new relevant sources under the same no-replay and sixteen-question bounds.
- Skill entrypoints and shared skill-index routing are covered by `tests/architecture/test_agent_skill_entrypoints.py`.
- Dispatcher-oriented skill sequencing is covered by `tests/architecture/test_dispatcher_skill_integration.py`.
- The broad runtime smoke workflow lives in `.github/workflows/ci-smoke.yaml`; it also carries the skills-consistency lint that previously ran in the retired duplicate `smoke` workflow.
- CI Smoke, the nightly full suite and release-UAT produce fitness evidence with
  `python -m pytest -q -s -m "not pg" tests/fitness/test_ci_fitness.py::test_ci_report_entrypoint_uses_scoped_product_gateway_fixture`.
  That explicit functional test runs the actual `app.fitness.report` entrypoint with the canonical
  `product_model_access_gateway` fixture, the full golden corpus and the existing 32-sample latency
  probes. Only the model test boundary is isolated; metric algorithms, reranking, summary labels and
  gate thresholds remain unchanged. Bash pipefail preserves a failed report/test exit before the
  subsequent parser, and stderr plus the complete report are retained in `tmp/ci_summary.log` and
  an always-uploaded artifact. The executable caller tests reconcile coverage with the checked-in
  workflow producer inventory, run all three real YAML commands over finite
  seed copies and require failure for missing/malformed metric input, failed gates and missing
  thresholds. This synthetic-input evidence establishes no live provider-quality acceptance or
  unrelated full-suite result; outside the enrolled test, Product Model Access still fails closed.
- The full and scoped non-PG unit steps both retain finite 75-minute outer ceilings. The scoped step's
  former 35-minute ceiling cut off #6091 / PR #6092 at 91% without a reported assertion failure
  ([job 116083429844](https://github.com/RasmusTho/agentic-pkm-mvp/actions/runs/38631158811/job/116083429844));
  its six selected subsystem groups run serially. Additional outer margin does not prove completion
  or promise a speedup: current-head substantive CI must still pass. Both retain the 120-second per-test thread watchdog,
  every target, marker, required check, assertion and failure handler. #6084 records two independent
  35-minute cutoffs: [#6074 job 115700746542](https://github.com/RasmusTho/agentic-pkm-mvp/actions/runs/38514333873/job/115700746542)
  and [#6075 job 115693481077](https://github.com/RasmusTho/agentic-pkm-mvp/actions/runs/38515571086/job/115693481077).
  All parallel shards passed; the serial boundary was still running when cancelled. Their
  parallel phases alone took approximately 30m56s and 29m50s, leaving only about four to five
  minutes for serial coverage at the old ceiling. Current-head #6187 run 39100438771 later proved
  that repository growth can extend the full lane's parallel phase to 51m35s (including a 45m51s
  deploy shard), after which the host-sensitive serial boundary was cancelled at the 60-minute
  ceiling despite every parallel shard passing. The full lane's 75-minute bound restores finite
  serial-phase margin. The scoped lane later completed [#6222 run 39237406751](https://github.com/RasmusTho/agentic-pkm-mvp/actions/runs/39237406751/job/118009713887)
  in 59m05s: 38m23s of parallel work followed by 20m42s of serial coverage, leaving only 55 seconds
  below its former 60-minute ceiling. [#6224 run 39249448570](https://github.com/RasmusTho/agentic-pkm-mvp/actions/runs/39249448570/job/118049350845)
  passed all four parallel partitions in 40m57s, then reached that ceiling after 372 of 984 serial
  cases passed, without a reported assertion failure. Its 75-minute bound now matches the full
  lane's finite envelope; neither the failed run nor that larger ceiling proves completion.
  [#6311 run 39865892884](https://github.com/RasmusTho/agentic-pkm-mvp/actions/runs/39865892884/job/120127869151)
  then passed all 131 parallel shards in 57m46s, including the deploy group's 1,473 passing cases
  in 51m18s, but again exhausted 75 minutes during serial coverage. The bounded scheduling replan
  collects node IDs from the measured `tests/deploy/test_deploy_channel_script.py` module and
  runs those IDs in disjoint process units under the existing four-process cap. The non-shared nodes
  are count-balanced across up to three units; the two tests that temporarily remove the checkout's
  `config/deploy/dev.previous.env` stay together in the small `deploy-node-unit-0`. The planner
  checks that every collected node appears once. The later [#6519 run 41297345631](https://github.com/RasmusTho/agentic-pkm-mvp/actions/runs/41297345631/job/124820859611)
  spent 3,201 seconds in `tests/deploy/test_bws_source_rpc_assembly.py` before the serial phase
  timed out at the same outer limit. That module also uses its collected IDs, in two disjoint units
  with adjacent pairs interleaved across the units to distribute the long test families;
  its function-scoped protected temporary directories and disposable subprocesses isolate fixture
  effects. Each module's plan and result logs are checked independently. Other file and directory shards remain in the
  same full-suite inventory. Collection or planning errors fail the lane before execution; node units emit verbose
  per-node results, and a post-run verifier requires one result for every planned node. Per-unit
  logs and the exact node plan are retained with the existing phase receipt.
  The host-sensitive serial boundary still starts after every parallel unit exits. This replan uses
  the measured module's collected-node inventory and preserves the 75-minute ceiling, marker,
  watchdog, and serial boundary rather than changing selector coverage or timeout margin.
  Four-process concurrency remains unchanged; host-sensitive tests still start only after all
  parallel processes exit. The earlier changes supply execution margin,
  not a speedup or a completed-run duration measurement. The `required-unit-phase-margin.v1`
  receipt (`pytest-not-pg-shards/phase-margin.json`) records exact checkout SHA, budget, watchdog,
  phase durations and exit status. Only `phase=complete` with `exit_status=0` describes success;
  null/incomplete fields cannot prove a missing or cancelled phase. Initial and boundary receipts,
  partial logs, and status inventory survive cancellation for the always-run artifact upload;
  normal EXIT handling adds final timings/status when the shell can execute it. Actual current-head
  CI completion remains required; the ceiling and fixture receipt alone are not runtime proof.
  PR #6083's scoped serial job [115940412928](https://github.com/RasmusTho/agentic-pkm-mvp/actions/runs/38531981018/job/115940412928)
  separately reached 93% at the old 35-minute cutoff, with one failed result whose traceback
  was lost. The scoped command keeps the exact selector arguments and adds verbose node IDs,
  short tracebacks and unbuffered output; pipefail and the always-uploaded log retain failure
  evidence. Its increased ceiling is execution margin, not a completed-run measurement or a
  speedup. `tests/ops/test_ci_workflow.py::test_scoped_unit_budget_preserves_selected_command_and_failure`
  executes that YAML command against finite success/failure producers to verify selected arguments,
  watchdog, visible diagnostics, retained log and failure exit propagation.
- When `tests/deploy` is retained pre-merge because a changed source triggers its heavy coverage,
  the selector preserves the authenticated target inventory and emits a derived
  `scoped_execution_units_json` plan. The slow deploy directory is expanded to stable test files,
  directory/file overlap is removed, and the runner collects the effective parallel inventory once
  after dependency setup, with the same marker and serial-boundary exclusions as execution.
  Collected case counts weight both deploy work units and the unchanged atomic nondeploy roots
  across at most four bounded processes; `tests/ops` and `tests/scripts` no longer each weigh one.
  This single collection also supplies the measured deploy module's node plan.
  The selected-target union remains the authority: the runner rejects empty, missing, duplicate,
  escaped, incomplete, or non-exact collected coverage. Deploy and the remaining selected targets
  run with bounded parallelism; the bounded host-process/writer-census ops modules start only
  after every parallel process exits in a separate serial boundary. Every pytest process retains
  the PR marker expression and 120-second per-test thread watchdog; each work unit remains within
  the unchanged 3300-second shard budget, and per-unit plus aggregate logs are retained. Any
  failed, timed-out, missing, duplicate, incomplete, or serial-boundary failure stays red under the
  single required `Unit tests (not pg)` verdict.
  The measured `tests/deploy/test_deploy_channel_script.py` module reuses the full-suite node
  planner when more than one worker is available. Its two shared-checkout rollback tests remain
  together; its remaining collected nodes form disjoint units within the same four-process cap.
  The measured source RPC assembly module likewise uses two disjoint collected-node units when
  more than one worker is available. Other deploy files remain atomic. The runner authenticates the selected file inventory before
  expansion, rejects duplicate collected nodes, and verifies one pytest result for every planned
  node in its executing partition. Missing, duplicate, unexpected, or unrecognized node results
  fail that partition. A single-worker invocation retains file execution.
  The later [#6522 run 41304571659](https://github.com/RasmusTho/agentic-pkm-mvp/actions/runs/41304571659/job/124842227894)
  showed that count-only packing could place both source RPC units alongside native-admission nodes
  in one pytest process; it hit the scoped timeout even though the other processes completed. The
  runner now assigns the measured source RPC and native-admission units to different processes
  before packing other targets. Sibling units of either module never share a process; with four
  available processes all four long units start in different processes. This preserves the selected
  inventory and existing bounds; an actual current-head CI result remains the timing evidence.
  Each completed failed partition emits its diagnostic log immediately, before waiting for other
  workers or the serial boundary. The final aggregate retains every partition's log, and remaining
  parallel coverage still runs. After every parallel child exits, any failed pytest, timeout or
  invalid node result skips the serial phase with explicit `NOT RUN` targets in its retained log;
  green parallel runs retain the full selected serial phase. Partial execution remains red.
  [PR #6373 job 121343690509](https://github.com/RasmusTho/agentic-pkm-mvp/actions/runs/40251333352/job/121343690509)
  supplied the motivating measurement: the atomic deployment file took 2324.55 seconds and the
  serial boundary took 892.48 seconds. An earlier partition finished red at 00:57:33 UTC, while its
  detailed output was delayed until 01:47:34 UTC. That job had 87 failures across all five phases;
  its final one-failure summary described only the serial phase. These historical timings justify
  the bounded change but do not establish its resulting runtime or a ten-minute protected lane.
  [PR #6373 job 121395691072](https://github.com/RasmusTho/agentic-pkm-mvp/actions/runs/40268371054/job/121395691072)
  reached this scoped node-splitting path but packed roughly 2603 ops cases with 232 deploy nodes
  and other files because nondeploy roots still weighed one. That partition took 2932.76 seconds;
  the subsequent serial boundary added about 12m34. The job failed with one fixture assertion and
  four fixture setup errors. Correcting atomic-root weights avoids this packing defect without
  splitting those roots or changing the serial boundary. Case counts are not measured durations;
  the resulting protected-lane runtime and any ten-minute bound remain unproven.
  Other scoped selections retain the existing
  single pytest invocation. This mechanism addresses the critical-path failure recorded by
  [failed job 117620023504](https://github.com/RasmusTho/agentic-pkm-mvp/actions/runs/39108712261/job/117620023504)
  from PR #6193. The closed #6206 balancing contract retained its 60-minute ceiling and accepted
  the exact inventory comparison and `github-actions-scoped-balanced-current-head.v1` consumer
  proof from [PR #6239 run 39149060861](https://github.com/RasmusTho/agentic-pkm-mvp/actions/runs/39149060861/job/117738853771),
  with at least five minutes of measured margin, as recorded in
  [its acceptance receipt](https://github.com/RasmusTho/agentic-pkm-mvp/issues/6206#issuecomment-6254883699).
  The later #6224 envelope adjustment does not alter that historical scope or prove its margin
  for another selection. Do not blindly rerun an unchanged timeout or claim a completed run from
  configured limits alone.
- The shared native PostgreSQL acceptance profile retains the former `pr-index-pg-contracts`
  surface (#5587), including FCA-06 second-consumer conformance (#5405) and dormant host-candidate
  admission/history/live-refusal and managed-source proofs (#5593). Each test retains the
  pytest-timeout plugin's
  120-second thread watchdog; verbose node IDs, unbuffered output, and the slowest 20 durations
  identify a stalled or slow test. The closed result contract refuses missing selectors, skips,
  failures and errors; it permits additional coverage without a permanent collected-node count.
  `tests/ops/test_ci_workflow.py::test_pg_acceptance_handoff_preserves_required_coverage` guards
  baseline enrollment and the coverage handoff. Actual matching dev/test PG receipts are required;
  non-PG selection, collected nodes and earlier focused JUnits do not substitute. These finite
  repository proofs do not establish a second-consumer installation or production eligibility.
- Pure PR title/body metadata edits are validated by `Issue and PR Governance` while CI Smoke jobs
  remain skipped. An `edited` event carrying `changes.base.ref.from` is a merge-input retarget and
  therefore keeps full CI Smoke enabled. Metadata events use a separate concurrency suffix so a
  skipped metadata run cannot cancel a same-PR source/integration run. CI Smoke retains PR-number
  versus push-ref concurrency identities and latest-wins cancellation for source/integration events,
  without allowing a PR run to cancel an unrelated `main` push (or the reverse);
  `tests/governance/test_ci_smoke_post_merge_proof_concurrency.py` is the executable proof.
- Governance PR contract checks live in `.github/workflows/issue-pr-governance.yml`.
- The import-boundary contract runs once on the PR path in `.github/workflows/import-linter.yaml`; CI Smoke retains the same blocking command for non-PR pushes/tags and owns the remaining contract-validation checks.
- The hot-path and direct-repair invariants are covered by `tests/architecture/test_pr_hot_path_governance.py`, selected through the Unit tests (not pg) lane for governance changes rather than run as a second CI Smoke step.
- PR unit CI uses `scripts/select_pr_tests.py` to map changed files to subsystem-scoped pytest targets. Changes to `.github/workflows/ci-smoke.yaml` select the governance workflow and selector contract tests instead of recursively requiring the whole product suite merely to validate the test runner itself. Co-changed deploy-source paths still select the complete bounded `ops_deploy` partitions. Other shared test/runtime configuration, migrations, dependencies, and shared fixtures run the deterministic broad suite; the `Unit tests (not pg)` job runs each collectible deploy test module, other top-level test directory, or root-level test module as a serial process with bounded parallelism, then runs host/process-global and exact-FD-count compatibility tests after those processes exit. This keeps the shared runtime bounded without asking xdist workers to share process-global or host-wide assumptions. E2E coverage is deferred to post-merge and nightly validation. This document is `scripts/select_pr_tests.py`'s `docs/development/` contract for the `scripts/docs_guard_logic.py :: GOVERNANCE_TEMPORAL_ENFORCEMENT` temporal-owner-doc exemption, and the check enforces that pairing specifically: update this doc, not `docs/STATUS.md`/`docs/ROADMAP.md`/etc., when the selection script's behavior changes.
- The `reasoning_expansion` selector owns `tests/uat/test_expansion_connect_create_accept_test_channel.py` and the companion UAT runbook; these paths select `tests/reasoning`, `tests/expansion`, and `tests/invariants` plus the runner's direct contract test. The runner's technical and synthetic TEST phases remain explicitly opt-in and never become live-channel proof merely by appearing in PR selection.
- Pinned controller startup changes (`scripts/postmerge_controller.py`, #6225) select the deploy
  suite and the liveness workflow contract tests. The deploy-fixture census retains source-trigger
  completeness, while the selector CLI test proves these production targets remain on the PR path.
- Shared-suite shard discovery keeps each `tests/deploy` test file as a separate shard, including
  nested `test_*.py` and `*_test.py` modules. It starts `test_deploy_channel_script.py` first and
  keeps the remaining discovered paths sorted. Other nested directories collapse into their
  top-level owner because pytest already recurses. Directory-level heavy deferral still excludes
  every module under that owner. Eligible test files therefore run once across parallel shards and the
  serial host-sensitive boundary. Each shard prints its completion status and elapsed seconds;
  its log contains the slowest 20 tests, as does the scoped unit invocation. Partial shard logs and the status file live under the
  runner temporary directory and are uploaded even when a later shard fails or the test step is
  cancelled. The aggregate log remains available on normally completed runs. This removes known
  duplicate execution; it does not promise a particular wall-clock speedup or suppress failures.
- The nightly full suite reuses that non-overlapping process pattern with four parallel pytest
  processes and the same serial `tests/ops` / `test_vault_multiwriter.py` boundary. It preserves
  every selected test while discovering `tests/deploy` at file granularity; other top-level
  groups keep their existing discovery. The measured longest deploy file,
  `test_deploy_channel_script.py`, is queued first, with the remaining discovered paths sorted.
  Fully deselected files remain in the finite inventory and require their empty JUnit result.
  The selection remains
  `not pg and not alpha_llm and not eval`, including E2E and the other marker classes omitted on
  the PR path. The qualified real-eval lane remains opt-in; the ten deterministic SV/EN checks
  stay in this nightly selection. Every invocation retains the canonical temporary namespace,
  plugin autoload and importlib collection; each has the existing 120-second thread watchdog, verbose node IDs,
  short tracebacks, unbuffered output and the slowest 30 durations. The batch ceiling is 50 minutes
  with a 60-minute job ceiling for installation, later checks and uploads. The triggering #6063
  run exhausted the former 20-minute step after partial execution. Later, #6090's
  [Python 3.12 job](https://github.com/RasmusTho/agentic-pkm-mvp/actions/runs/38638069945/job/116106250882)
  completed all 132 shards and 20,208 reported cases at 35 minutes 6 seconds but timed out at the
  35-minute ceiling. A [later run](https://github.com/RasmusTho/agentic-pkm-mvp/actions/runs/38649149411)
  exhausted the 40-minute limit on both versions after their deploy groups took 31m31s and
  32m46s, leaving the serial phase incomplete. After file grouping,
  [run 38658078391](https://github.com/RasmusTho/agentic-pkm-mvp/actions/runs/38658078391)
  completed all 155 shards and 20,343 reported cases on both versions with zero failures, but
  Python 3.12 still timed out at 40m06s; Python 3.13 completed at 39m34s. The measured envelope
  allows 20% beyond the slower complete run plus one minute, with separate setup and upload
  reserves. Prior failed proof and timeout accounting remain unwaived. Neither grouping nor
  a larger ceiling establishes acceptance: complete current-head inventories, failure-free
  required targets, no timeout, and successful later checks still qualify the producer.
- Nightly shard inventory, raw exit statuses, per-shard logs and JUnit results live under
  `$RUNNER_TEMP/pytest-nightly-shards` and are uploaded with the aggregate log by an `always()`
  step. A completed phase requires each expected shard exactly once and a JUnit testcase count
  consistent with its declared result count. A fully deselected shard may report pytest exit 5,
  but an empty whole selection, missing/duplicate status, terminated process, missing result or
  failed test makes the producer fail. After a completed launcher wait, ordinary parallel failures
  remain recorded while the serial boundary still runs; validation then reports both phases and
  retains the failing result. An incomplete launcher stops before that boundary because child
  process exit cannot be established. Partial logs survive those failures and step cancellation.
  The executable nightly workflow fixtures in `tests/ops/test_ci_workflow.py` prove inventory,
  failure accounting and the serial boundary with finite synthetic populations; those producer
  proofs do not claim that unexecuted Product tests passed or replace current-head CI.
- A docs-only PR may include a changed `tests/e2e/**` scenario as its executable acceptance companion. That E2E path is scope-neutral for selection and remains deferred; the docs lane still runs its non-E2E contract targets and must not fall through to the unowned/full-suite refusal.
- The startup-redesign contract owner selects both its static contract suites and the exact docs-index Verify target `tests/architecture/test_docs_index.py::test_all_docs_are_listed_in_docs_index`. Its selector regression must include the mixed shape of startup docs, `docs/DOCS_INDEX.md`, the selector, and governance tests so a docs-index proof cannot disappear behind a green scoped run.
- A source-only change to `scripts/dev_delivery_liveness.py` explicitly selects
  `tests/governance/test_dev_delivery_liveness_workflow.py`, which owns the checker, admission and
  controller signal contract. Workflow-only changes retain governance coverage; unrelated script
  selection and heavy-test deferral remain unchanged.
- Statically declared selector file and node-id targets must be collectable. Before pytest receives a selected node id, the selector checks its file portion exists; its always-selected selector fitness test collect-checks every static file/node-id target so a rename or deletion fails in the changing PR rather than an unrelated downstream selection.
- The `pr-unit-tests-not-pg` (`Unit tests (not pg)`) job's `code` paths-filter in `.github/workflows/ci-smoke.yaml` includes `AGENTS.md`, `CLAUDE.md`, `.codex/**`, and `docs/**` (#4281): a PR touching only those paths runs the real lane (install and the selected contract pytest run; runtime-only gates follow the text classifier) instead of self-skipping to a bare `success`. Once the filter fires, `scripts/select_pr_tests.py`'s shared `GOVERNANCE_TARGETS` (used by both the governance-only branch and the `docs_authoring` subsystem) includes `tests/architecture` and `tests/ops/test_review_before_ci_gate.py` alongside `tests/governance`/`tests/scripts`/`tests/ops/test_ci_workflow.py`, because those are the suites that actually assert on `AGENTS.md`/`CLAUDE.md`/`.codex/**`/`docs/**` content; `CLAUDE.md` is also in the docs-only exact-match set alongside `AGENTS.md` so a `CLAUDE.md`-only PR resolves to the scoped docs lane rather than the unowned/full-suite fallback. `tests/governance/test_ci_smoke_docs_only_gate.py` is the executable proof for this pairing, including a reproduction of the exact diff shape from PR #4275.
- The `episodes` owner includes `app/episode_debrief/` and selects `tests/episode_debrief` alongside its existing episode and invariant targets. The selector CLI regression covers source-only trigger/store changes and the mixed runtime/test/spec shape; a similarly named sibling directory remains unowned and refused. PostgreSQL debrief acceptance still requires its explicit disposable-database proof; selecting the module does not claim that the `not pg` lane executed it.
- Every `builder_system` match includes `tests/architecture/test_builderops_store_boundary.py` as an exact run target, not only as an ownership prefix. Ordinary `app/builderops/**` changes must execute the audited store-access guard so new direct-store sites cannot bypass it while their own subsystem tests remain green.
- The `outbox_worker` owner includes `app/workers/outbox_binding_gate.py` alongside the worker implementation and `tests/workers/**`; changes to the binding admission/effect-window seam must select the worker regression lane instead of falling through to the fail-closed unowned-path result.
  Its exact test ownership and target inventory also include
  `tests/services/test_outbox_envelope_preflight.py`, which covers the worker's
  upgrade preflight. Direct test edits run the complete module and common CI
  integrity checks; worker-source edits retain that regression. Similarly named
  service-test siblings remain unowned and fail closed.
- `app/services/companion_note.py` is an exact-file owner of `watcher_sync`, `outbox_worker` and `store_ingest`: a helper-only edit runs the existing watcher, worker and ingestion source-boundary suites plus the direct companion-note/write-guard tests. The selector regression exercises the actual CLI and verifies similarly named service files remain unowned and refused.
- `_is_governance_only`/`_is_docs_only` tolerate a changed `tests/**` path inside `GOVERNANCE_TARGETS`/`DOCS_TARGETS` as scope-neutral so a *pure* governance-only/docs-only PR keeps resolving to that lane. Several of those tolerated directories/files are also real per-subsystem scope signal in `SUBSYSTEMS` (`tests/architecture/test_builderops_store_boundary.py` for `builder_system`, `tests/architecture/test_no_hardcoded_vault_layout.py` for `vault`, `tests/governance/`/`scripts/` for `builder_system`/`ops_deploy`, `tests/ops/` for `ops`) — on a mixed PR that also touches one of those subsystem's owned paths, the selector unions that subsystem's own targets into the governance/docs selection (`_foreign_subsystem_matches`) instead of silently narrowing to the governance/docs-only target set and dropping the other subsystem's real coverage (#4336). `subsystems` then lists every contributing subsystem (e.g. `governance,builder_system`), never just `governance`/`docs` alone, whenever this applies; `tests/scripts/test_select_pr_tests.py`'s mixed-PR cases are the executable proof.
- The neutral `llm_contract/**` kernel and policy-neutral `app/model_access/**` facade are owned by the `model_access` selector. Changes run the direct Model Access contract/facade suite, the BuilderOps adapter/runner compatibility suites, and the exact neutral-kernel/import-boundary architecture guards.
- The Product reasoning facade at `app/components/reasoning/facade.py` is an exact-file `llm_eval` selector owner, not a string prefix. It additionally selects `tests/components/reasoning/` alongside existing Product LLM targets; the selector regression proves a same-prefix sibling remains unowned and fail-closed.
- Product embedding seams are exact selector owners: `app/cli/embed_probe.py` selects `tests/cli/test_embed_probe.py` under `llm_eval`, and `app/components/retrieval.py` selects `tests/retrieval` under `memory_retrieval`. Issue #5820 routes these consumers through the Product model-access fabric; `tests/scripts/test_select_pr_tests.py::test_product_embedding_adapters_select_their_regression_coverage` proves each exact mapping and fail-closed selection.
- Issue #6498 gives the two Product reviewer modules exact `vault` ownership, the set-evaluator module exact `llm_eval` ownership, and the domain-separation and panel-exclusion modules exact `memory_retrieval` ownership. Their modules are included in the existing owner target lists so runtime changes retain those regressions; direct module changes select the complete modules, static consumers and common CI integrity checks. Unrelated siblings such as `tests/agents/test_normalizer.py` remain unowned and fail closed. The mixed selector regression verifies the ordinary governance, vault, memory-retrieval and LLM/evaluation union with runtime checks enabled.
- Issue #6504 gives the three Panel CLI functional modules (`tests/cli/test_panel_cli.py`, `tests/cli/test_panel_orchestrator_cli.py`, `tests/cli/test_panel_runtime_cli.py`) exact `promotion_panel` ownership and adds them to that owner's target list, so panel-runtime changes retain these end-to-end regressions and a direct module edit selects the complete module, its static consumers and the common CI integrity checks. Other `tests/cli` modules such as `tests/cli/test_external_ingest.py` remain unowned and fail closed; the mixed selector regression now includes the `promotion_panel` union.
- Every `vault` match includes `tests/architecture/test_no_hardcoded_vault_layout.py` as an exact run target, not only as an ownership prefix. Ordinary `app/vault/**` changes must execute the vault-layout guard without widening the subsystem to all architecture tests. The separator-only note-path helper at `app/path_utils.py` is also an exact `vault` owner: `app/vault/**` and `app/knowledge/**` already share this selector owner, so helper changes run both `tests/vault` and `tests/knowledge`. Its selector regression covers the helper together with its direct vault and knowledge consumers and proves a similarly named sibling remains unowned. The selector's `vault` ownership includes `app/agents/profile_agent/` and the `app/agents/reviewer/agent.py` path because they persist or read canonical vault-profile note content. These paths select the governed vault-profile contract/proposal tests and Reviewer tests; `tests/scripts/test_select_pr_tests.py::test_profile_authority_and_reviewer_paths_select_vault_regressions` guards that route and the no-unowned result.
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
- The shared `app/cli.py` entrypoint is a full-suite trigger because command wiring and shared
  imports can affect every runtime subsystem. The event diagnostic CLI
  (`app/cli/events_doctor.py`) and legacy event producer (`app/outbox/legacy_events.py`) are
  explicitly owned by `events_receipts`, while the derived orientation adapter
  (`app/orientation/runtime.py`) is owned by `observability`; these seams must not fail CI
  selection as unowned when their outbox-corruption behavior changes.
- The exact shared producer `app/objects/__init__.py` uses the same `store_ingest` selection: its
  canonical object-store facade writes through the store provider seam and emits ingest lifecycle
  events, and its selection includes the exact ObjectStore outbox-emission regression. The exact
  `app/outbox/events.py` producer belongs to both `outbox_worker` and `memory_retrieval`, so its
  selection unions delivery-worker/event, indexer, and event-envelope contract coverage. Other
  `app/objects/**` and `app/outbox/**` paths remain unowned unless explicitly mapped; the
  `legacy_events.py` exception above is deliberate and covered by selector regressions.
- The push-lane `CI gate: vaultwide panel verifier` step (`.github/workflows/ci-smoke.yaml ::
  smoke-docker`) exercises the MVR-01B instance-state deployment producer against the composed
  runtime only after merge. Its protected verification logic has pre-merge signal (#4371): every
  `vault` subsystem match (`app/instance/**`) runs
  `tests/ops/test_instance_state_volume_contract.py` as an exact target, including the staged-backup
  regression tests (`test_staged_backup_verification_succeeds_on_fresh_deployment`,
  `test_staged_backup_failure_surfaces_underlying_cause`,
  `test_inconsistent_registry_ledger_still_fails_closed`), so a backup/ownership verification defect
  fails the changing PR instead of first turning `main`'s post-merge smoke red. The CI fixture seeds
  its adopted binding through the same `/tmp` path mounted into `watcher` and
  `instance-state-init`; the final fixture starts that same single `watcher` owner, rather than
  additional consumers with overlapping live ownership. `tests/architecture/test_ci_smoke_contract.py::test_vaultwide_smoke_seeds_adopted_fixture_with_same_path_identity`
  protects that mount/seed contract without weakening genuine ledger inconsistency rejection. The
  docker-compose integration itself (mounts, launcher sequence, seeded vault) remains post-merge-only
  coverage.
- E2E tests under `tests/e2e/` run after merge and in the nightly suite, not on ordinary PRs. Opt-in classes (live LLM, browser, human UAT, eval) remain in their dedicated post-merge or nightly lanes.
- The #4841 production devUI transport is a security-boundary change. Its focused contract set is
  `tests/ops/test_prod_devui_gateway_config.py`,
  `tests/companion_ui/test_devui_gateway_admission.py`, and `tests/api/test_devui_api.py`, plus
  every production-producer target when a producer changes (`deploy`, `prod-up`, `prod-start-full`,
  and `prod-ui`). Merge evidence requires exact-head CI; stale checks from a prior branch head do
  not satisfy this transport contract.
- Combined devUI shell recovery #4836 keeps two browser protections in
  `.github/workflows/browser-runtime.yml`: ordinary pull-request runs execute all eight current
  Overview journeys, including the evidence-axis regressions, and reject empty, missing, duplicate,
  skipped, failed, or errored required evidence; the ordinary PR JUnit is retained as the regression
  proof. The separate exact-ref dispatch path remains the historical five-node proof: after
  publishing the candidate ref, an operator must dispatch the workflow against that exact ref (for
  example, `gh workflow run browser-runtime.yml --ref <published-candidate-ref>`). Native
  `workflow_dispatch` resolution binds the pinned checkout and the evidence artifact to exact
  `${{ github.sha }}`. The dispatch fails when
  `tests/companion_ui/test_devui_overview_journeys.py` is absent, collects zero tests, fails, or
  skips any required journey; a green run also requires its JUnit result, Overview browser receipt,
  Playwright trace, screenshots, and hashed manifest in the exact-SHA artifact. The receipt is the
  exact `devui-overview-browser-accessibility.v1` object: no fields may be missing or added; its
  `github_sha` and test-module identity must match the run, and fixture versions must name exactly
  `connected-overview-focus` and `hostile-source-state-matrix`. `token_sha256` must equal the
  accepted binding-token SHA-256
  `7d8cdd49f59061f895959159a08e82348e7e02eb8b8ba7426020a50c7fa915b1`, and the nonempty
  screenshot list must exactly match the archived screenshots. Accessibility results must report
  `passed` for exactly desktop, narrow, 200% zoom, keyboard, screen-reader name/focus order, print,
  and JavaScript-off checks; `failures` must be an empty string list, and unresolved visual
  questions must be a string list. The hashed manifest embeds that validated receipt and records the
  receipt, JUnit, trace, and screenshot files consistently. Runner-temporary paths are declared only
  at step scope, where the `runner` context is available for both push and dispatch evaluation. The
  ordinary PR unit CI does not provide this exact-ref browser receipt, and neither a local screenshot
  nor a post-merge run substitutes for the exact published #4836 candidate run. The exact required
  JUnit nodeid inventory for that candidate is:
  - `tests/companion_ui/test_devui_overview_journeys.py::test_real_gateway_overview_focus_return_journey_preserves_subject_context_and_sha`
  - `tests/companion_ui/test_devui_overview_journeys.py::test_focus_api_failure_renders_honest_visual_error_without_url_probing`
  - `tests/companion_ui/test_devui_overview_journeys.py::test_connected_shell_freezes_server_identity_selector_and_aria_contract`
  - `tests/companion_ui/test_devui_overview_journeys.py::test_connected_shell_renders_full_server_state_matrix_without_reclassification`
  - `tests/companion_ui/test_devui_overview_journeys.py::test_gateway_shell_is_safe_accessible_no_egress_and_effect_free`
  The dispatch rejects any missing, renamed, duplicated, unexpected, skipped, or unexecuted nodeid.
  The receipt's canonical `required_nodeids` list and `journey_assertions` map must name exactly that
  inventory, with every nodeid reporting passed URL assertions, network assertions, and status
  assertions plus an empty page errors list. The manifest records both required and executed nodeids
  plus per-node collected/executed/passed/skipped results and any JUnit-inventory error while hashing
  the bound evidence. This pre-merge #4836 candidate artifact must exist before M, but it is not a
  field or prerequisite reference inside the later strict #4748 receipt. #4748 runs its own distinct
  final-M browser proof and produces a separate self-describing
  `devui-overview-browser-accessibility.v1` receipt/artifact at M. Only the downstream
  `devui-stage-a-read-only-owner-pilot.v1` ledger is the later cross-run evidence authority: it
  records the exact final-M tested SHA and applicable deployed evidence with an
  `evidence_artifact_sha256` derived from the canonical archived artifact inventory. Candidate
  provenance may be preserved when available, but a candidate-to-final cross-run binding is not a
  prerequisite for the production-only path. Consequently, ordinary unit CI, a local screenshot,
  a post-merge run, or a matching Git SHA cannot substitute for the applicable final-M or deployed
  evidence required by the pilot contract.

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
- Subsystem-scoped CI must be conservative: dependency files, migrations, shared fixtures, and shared runtime/test configuration choose the broad deterministic suite. CI workflow-only changes run their owned workflow and selector contract tests; any co-changed runtime source still adds its subsystem coverage. Unmapped runtime paths fail selection until an owner is declared; they must never silently borrow the whole repository's suite.
- E2E coverage is reserved for post-merge, nightly, or explicit manual verification.
- Heavy test targets in `HEAVY_PR_DEFERRED_TARGETS` run on the PR path only when the PR changes a source they exercise; otherwise they run in `post-merge-heavy-tests.yml` (see `:: Post-merge heavy tests`).
- When a governing contract names an exact-ref browser proof, dispatch the dedicated workflow only
  after publishing the candidate and authenticate the result and artifacts against its resolved
  SHA; do not reinterpret ordinary unit CI as browser evidence.
- Slow or flaky test classes should be marked and routed to their dedicated subsystem, nightly, or manual workflow. They must not install dependencies or invoke pytest on unrelated PRs.
- Direct repair PRs are classified by the surfaces they touch, not by whether they carry a governing issue.
- Failing required checks must be classified, not ignored as out-of-scope.
- A required check that is stale, missing, or unrelated to the current head SHA is a blocking classification problem, not a silent pass.

## Post-merge heavy tests

Owner decision (verbal, 2026-10-16, recorded in #6154): heavy test sets do not run on the PR path. They run after merge on the ygg verification VM (option B, #6158), with the repository controller now qualifying `dev` before test promotion (#6227); a GitHub-hosted run remains only as the missing-verdict fallback.

The PG acceptance source read of `app/config/database.py` is a deploy retention trigger: changes
to this shared runtime source keep both full-suite selection and deploy coverage on the PR path.

- `scripts/select_pr_tests.py :: HEAVY_PR_DEFERRED_TARGETS` filters heavy targets already selected by subsystem ownership or the full-suite route. It keeps a selected heavy target only when the PR changes a listed input, or a non-test file inside the target (a `conftest.py` or helper). Otherwise the selector drops it and reports it as `deferred_targets` (stdout and `GITHUB_OUTPUT`). The full-suite lane skips the deferred shard and logs `SHARD DEFERRED`. A changed test module inside a deferred directory still runs as its own changed-file target.
- The only entry today is `tests/deploy`. Its retention triggers cover repo files it reads directly: deploy scripts and `scripts/lib/**`, compose files, requirements files, `Dockerfile`, `ops/**`, `config/deploy/**`, release-channel code (`app/release_channels/**`), and the `app/` modules it loads by path. These include copied fixture inputs, so the inventory is not an independent dependency-owner map. It took ~1497 s of PR #6134's 2287 s unit step and timed out PR #6152, because `ops_deploy` owns all of `scripts/`. A census test keeps the trigger set covering every existing repo file that `tests/deploy` references (#6155 review). The rolling channel-bug workflow (`.github/workflows/postmerge-channel-bug.yml`) and receiver (`scripts/postmerge_channel_bug.py`) are direct deploy-test inputs; the workflow also has exact `ops_deploy` ownership so a workflow-only edit selects that coverage alongside governance checks. Add a target only with a timing receipt.
- VM execution: after the private host controller (`scripts/postmerge_dev_test.py`) commits a candidate's native `dev` deployment, it runs `qualify-heavy dev <operation-id>` through the existing `yggdrasil-bws-deploy` launcher on `ygg-dev`, whose action allowlist admits `qualify-heavy` (#6205). This is repository support from #6227; live host activation remains #6170 and release qualification remains #3347. `app/ops/heavy_acceptance_runner.py` runs `app/ops/heavy_acceptance.py` (profile `postmerge-heavy.v1`) in the admitted image against a scratch depth-1 Git checkout of the exact candidate SHA (as `actions/checkout` provides): network none, read-only root, dropped capabilities, and the host Docker CLI and compose plugin mounted read-only without a socket. It resolves the targets with `select_pr_tests.py`'s own `HEAVY_PR_DEFERRED_TARGETS`, the PR marker expression and the 120-second thread watchdog. An empty selection, a failure, an error, or a docker-gated skip is not a pass. The controller promotes that exact candidate to `test` only after a passing heavy verdict. A failed/refused verdict holds that candidate without replay; later admitted builds still proceed to `dev`. No heavy result gates or reverts a merge to `main`, and `postmerge-pg.v1` is unchanged. The controller runs the profile synchronously, so the next candidate's deployment waits for it, bounded by the profile's 60-minute deadline.
- Verdict back to GitHub: the controller dispatches `.github/workflows/post-merge-heavy-tests.yml` once per dev candidate with bounded inputs (SHA, `passed`/`failed`/`refused`, operation ID, counts, refusal reason, up to 20 failing node IDs). The existing host client uses Actions read/write, Contents read and Metadata read only; no additional scope is required. Failing node IDs are masked to the input grammar, and the dispatch is retried twice before it is recorded as failed. Verdict runs are grouped per SHA, so one never displaces another commit's pending verdict. `scripts/post_merge_heavy_tests_verdict.py` validates the inputs and that the SHA is on `main`; the run records the `post-merge-heavy-tests/ygg` commit status and is red unless the verdict passed. A malformed or off-`main` verdict is red too.
- Missing-verdict watchdog: the workflow runs hourly. When no `main` commit at or after the newest commit older than 6 hours carries a ygg status (or an earlier fallback status), it is red with reason "no ygg verdict" and runs the GitHub-hosted heavy job for that SHA as fallback, recorded as `post-merge-heavy-tests/fallback`. The fallback is red even when its tests pass, because the VM path is broken; a fallback never grants controller test-promotion eligibility. A `workflow_dispatch` without a verdict runs the GitHub-hosted job on demand. The per-push GitHub-hosted run is retired.
- Crash/restart: a durable intent precedes both the heavy run and its dispatch. An interrupted run becomes a refused verdict instead of rerunning; an uncertain dispatch is not sent again after restart. A terminal native dev deployment failure persists a one-time `refused` verdict with reason `dev_deploy_failed`. Legacy terminal test-VM checkpoints remain readable and are not replayed.

- Red routing: every red run opens one rolling `type:bug` + `prio:high` + `agent:ready` alert Issue titled "bug: dev verification is red on main", rendered by `scripts/post_merge_heavy_tests_alert.py` (an open alert with the legacy heavy-tests title is reused), or comments on the open one, naming the SHA and reason. The alert job also exits red. The next green verdict comments and closes the alert. The workflow is not a required PR check; a green `Unit tests (not pg)` does not prove the deferred heavy targets.

Production remains a separate operator gate. #6228 requires the exact current green TEST candidate,
its immutable image and a durable signed functional PASS plus concrete-plan approval. A green
heavy, native PG or TEST deploy result alone is not production eligibility, and no production gate
delays or reverts merges to `main`. The [release owner](../RELEASE_CHANNELS/README.md#promotion-model)
owns the policy and generated protected-merge identity limits.

## Historical selector replay

`scripts/replay_pr_test_selection.py` measures how the current affected-test selector classifies
historical accepted-main deltas without changing CI or creating a second subsystem-policy source.
It walks a bounded first-parent sample, fingerprints `scripts/select_pr_tests.py`, and emits the
changed paths, selected subsystems and targets, plus aggregate full-suite, unowned-path, and
multi-subsystem rates:

```bash
python3 scripts/replay_pr_test_selection.py --ref origin/main --limit 100 --json
```

The report is a rebuildable observation, never delivery authority. It applies the selector at the
current checkout to historical changed-file sets; it does not reconstruct the selector revision
that existed at each merge. Git history alone also cannot establish historical failing-test recall,
CI duration or runner cost, review effort, or escaped-defect frequency. Those measurements require
separately attributable CI and delivery evidence and must remain `not observable` when that evidence
is unavailable rather than being inferred from this replay.


The Episode Debrief CLI (`app/cli/episode_debrief.py`) belongs to the existing `episodes`
selector owner alongside its runtime package. CLI changes retain Episodes, Episode Debrief and
invariant targets; unknown sibling CLI modules still fail closed as unowned. The covering check is
`tests/scripts/test_select_pr_tests.py::test_episode_debrief_cli_selects_existing_episodes_coverage`.
