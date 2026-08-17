State: Development reference. Not an auto-loaded instruction file.
# Development Workflow

Use this document for the builder-agent working loop and validation expectations after reading `AGENTS.md`.

For normal PR delivery, read [`PR_HOT_PATH.md`](PR_HOT_PATH.md) first. It is the default short path for routine PR work. Read [`PR_ESCALATION_PATHS.md`](PR_ESCALATION_PATHS.md) only when the hot-path classification finds a risk trigger, stale SHA, blocking review feedback, CI failure, or another escalation condition.

This document applies to development-time contributors. It does not define runtime/system-agent behavior.

## Working loop

For non-trivial changes:

1. Identify the owning document via `docs/DOCS_INDEX.md`.
2. Read the owner doc before changing code or neighboring docs.
3. Confirm the planning chain for the work: docs/SoT/plan -> feature/capability issue -> slice/child issue -> code/PR -> slice verification -> merge -> feature validation -> acceptance -> owner-doc promotion.
4. Add or update tests for the intended change when the work is not docs-only.
5. Implement the smallest change that fits the documented architecture.
6. Update owner docs in the same change when behavior, contracts, or architecture changed.
7. Run the relevant validation commands and record any gaps.

For larger `type:bug` issue sets, apply `AGENTS.md :: Transition-period bug-delivery policy`: a
minimal coordinator dispatches each bug to its own end-to-end Codex task/session and isolated
worktree, with serial implementation as the default. This is Builder System transition guidance,
not Product/Runtime behavior or evidence of a shipped deterministic orchestrator.

## Lightweight breakdown model

Use the following practical breakdown model across docs, GitHub, and implementation:

- **Docs / SoT / plan docs** define direction, constraints, and feature intent. Task specifications in plan docs (such as `docs/LOCAL_TEST_BOOTSTRAP/`) function as system-specification documents that capture one feature intent but spawn multiple implementation issues (one-to-many mapping).
- **Feature / capability issues** define the target outcome, child-slice map, verification path, and validation / acceptance path.
- **Slice / child issues** define the bounded implementation steps that coding agents should pick up.
- **PRs** should usually map to one slice / child issue, not to a vague roadmap heading.
- **Slice verification** proves the implemented slice works at the intended layer.
- **Feature validation** proves the overall feature works from the operator or product point of view, sometimes after merge.
- **Acceptance** is the explicit decision to promote that feature into supported owner-doc truth.

Example: The local test bootstrap path is documented as a single system-specification contract in `docs/LOCAL_TEST_BOOTSTRAP/` (one specification), but implementation may span multiple feature and child issues (multiple implementation tasks), each proving one slice of the complete flow.

Interpretation rule:
- slices may be done at merge while the parent feature remains open
- larger capabilities should define both a verification path and a validation / acceptance path before they are treated as complete
- this is a lightweight delivery spine, not a heavyweight process rewrite

Recommended planning chain:

`Docs / SoT / plan -> Feature / capability issue -> Slice / child issues -> Code / PR -> Slice verification -> Merge -> Feature validation -> Acceptance -> Owner-doc promotion`

## Evidence surfaces

Use different surfaces for stable intent versus live delivery evidence:

- Docs define the intended verification path and acceptance path up front.
- Feature / capability issues hold the live validation evidence and acceptance checklist, usually in the issue body and follow-up comments.
- Slice / child issues hold the bounded implementation contract.
- PRs hold the slice verification receipt.
- Owner docs change when accepted/shipped truth changes, not for every post-merge rerun.

Practical rule:
- do not open a new docs PR just because more post-merge evidence arrived
- do record that evidence on the parent feature issue so acceptance can be decided from one place
- do create a docs PR when owner-doc truth changes, for example from planned to accepted or supported

## Validation baseline

### Repository documentation language

Repository documentation uses English as its primary prose. The policy covers root contributor
documents, `docs/**`, repo-local skills and agent adapters, Companion UI documentation, and governed
design handoffs. It deliberately does not reclassify Product/vault Markdown or multilingual test
corpora as documentation; those surfaces contain Swedish and other languages by design.

`python3 scripts/docs_guard.py --language-only` scans the complete tracked documentation surface on
every PR, including implementation PRs. It removes fenced code, inline code, URLs, and comments
before applying a deterministic primary-language check. Explicit bilingual Markdown tables whose
headers name at least two languages are treated as localization data, while ordinary technical
tables remain part of the prose check. Bounded quotations, localization strings, and SV/EN examples
are permitted inside an otherwise-English document. A document whose primary prose is detected as
non-English fails with the path and marker evidence; there is no per-file bypass.

The dependency-free detector uses closed-class markers for common Latin-script languages and a
Unicode-script threshold for non-Latin prose. It is intentionally a CI fitness heuristic, not
universal language identification: very terse text with too little language evidence, an uncommon
Latin-script language outside the marker sets, or an unlabeled mixed-language table can remain
ambiguous. Review remains responsible for those cases.

- Docs-only changes:
  - run any repo docs validation command if one exists
  - when `.codex/skills/**` changed, run `python3 scripts/lint_skills_consistency.py` (exit 0, zero output = clean)
  - otherwise run lightweight repo checks that are still appropriate
- Code-affecting changes:
  - `ruff check app tests`
  - `mypy app`
  - run the governing Issue's `Verify:` targets and the affected subsystem's focused tests
- Settings/runtime contract changes:
  - `python -m app.cli settings-validate --json`

### Pointing the PG lane at a scratch database

The `pg` lane has **no default database** (#4573). It runs destructive DDL, `TRUNCATE`, and
`CREATE DATABASE` / `DROP DATABASE` against whatever `DATABASE_URL` / `DB_DSN` resolves to, so it
refuses to guess:

- Nothing configured → every `pg`-marked test **skips**, with a terminal banner naming what to set.
  A skipped PG lane is never silent, including under `pytest-xdist` (`make smoke`, `CI Smoke`).
- A DSN that `app/db/dsn.py :: looks_like_prod_dsn` flags → the run **aborts in `pytest_configure`,
  before the first test module is imported**, so nothing opens a connection. That classifier flags a
  DSN whose database name is exactly `app` or whose port is the prod-published `15432`.

The same classification runs again at all three psycopg connection entry points during pytest. That
side-effect-boundary guard classifies positional conninfo together with libpq keyword parameters, so
late overrides cannot hide a production target. It also refuses implicit or explicit local-socket
targets and service indirection, whose server cannot be proven safe. The AST census under
`tests/architecture/` deliberately checks only hard-coded defaults; it is not a Python dataflow analyzer.

The gate checks **four** ways this repo can name a database, not just the obvious one:

| Writer | Reached through | Checked |
|---|---|---|
| `DATABASE_URL` / `DB_DSN` | `app/db/dsn.py :: resolve_dsn` | always |
| `PKM_DB_HOST` / `PKM_DB_PORT` / `PKM_DB_NAME_*` / `POSTGRES_*` | `app/config/database.py :: resolve_runtime_database_url` → `app/db/db.py :: conn_rw` | always when explicitly configured |
| `PGHOST` / `PGHOSTADDR` / `PGPORT` / `PGDATABASE` / `PGUSER` | libpq's own defaults, whenever an empty conninfo is passed | always when any target field is explicitly configured |
| `PGSERVICE` / `PGSERVICEFILE` | libpq service indirection | fail closed whenever either is configured because its effective target cannot be inspected safely before imports |
| `BUILDEROPS_DATABASE_URL` | the control plane's own `CREATE SCHEMA` path | always |

Service indirection is fail-closed whether selected through `PGSERVICE` / `PGSERVICEFILE` or embedded
as a `service` option in an explicit conninfo/URI: the service file can supply a target the pre-import
guard cannot inspect safely.

The second and third are the reason `DATABASE_URL` alone is not sufficient: a run with
`PKM_DB_HOST=127.0.0.1 PKM_DB_PORT=15432` and no `DATABASE_URL` reaches production through
`conn_rw()` while the documented pair still looks unconfigured. Each writer is checked independently:
a safe primary DSN cannot hide a production runtime or ambient libpq target. The unconditional
compose-internal fallback is ignored only when no runtime writer was explicitly configured.

Collection authorization stays consumer-specific. `DATABASE_URL` / `DB_DSN` authorizes the ordinary
`pg` lane; `BUILDEROPS_DATABASE_URL` authorizes only the control-plane tests and BuilderOps recovery
test that consume it. Runtime and ambient libpq variables never globally unskip destructive tests
that consume the documented pair.

The refusal is deliberately placed before imports rather than after collection: several test modules
probe Postgres at import time (`tests/stores/test_capabilities_matrix.py` evaluates `pg_available()`
inside a `skipif`), and every import happens after collection begins. A collection-time check
refuses only *after* the suite has already dialled the server. The consequence is that the check
reads the environment, not the selected test set: a run whose marker expression happens to exclude
`pg` still aborts if a prod-looking DSN is exported, unless the expression contains the literal
`not pg`, which makes `tests/conftest.py` drop both variables up front. Unset the variable, or use
`-m "not pg"`, when you want that run to proceed.

Name a non-production target explicitly:

```bash
DATABASE_URL=postgresql://app:app@127.0.0.1:15434/app_test python3 -m pytest -q -m pg
```

Per `docs/ENVIRONMENTS.md`, `dev` publishes `15433` / `app_dev` and `test` publishes `15434` /
`app_test`; `15432` / `app` is production and is exactly what the guard exists to refuse. The
scratch-database factories under `tests/migrations/**` derive their admin DSN from the same
resolution, so this one setting also decides where `CREATE DATABASE` lands. CI supplies its own
`app_test` service DSN and is unaffected.

Escalate to the repo-wide non-PG suite only when the governing Issue/owner document names it or the
change has cross-system blast radius that focused subsystem tests cannot cover:

`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 scripts/run_with_host_lease.py --resource pytest-not-pg --execution-id <issue-or-pr>:<sha> -- pytest -p pytest_asyncio.plugin -p anyio.pytest_plugin -p xdist.plugin -q -m "not pg" -n auto --dist=loadfile`

### Resource-bounded local `not pg` fallback

Use the canonical command above first. When it cannot execute on the local host because its
single pytest process exhausts a host resource (for example file descriptors), run the following
sanctioned fallback instead. It retains the same `not pg` marker selection, runs every top-level
test directory and root-level `test_*.py` file, and holds the same host-global lease for the whole
run. It is a local execution fallback, not a way to narrow the required validation standard.

```bash
export PYTHONPATH="${PWD}:${PWD}/companion-ui/companion-app${PYTHONPATH:+:${PYTHONPATH}}"
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 scripts/run_with_host_lease.py \
  --resource pytest-not-pg \
  --execution-id <issue-or-pr>:<sha> \
  -- zsh -o pipefail -c '
    shard_list="$(mktemp)" || exit $?
    trap "rm -f -- \"$shard_list\"" EXIT
    find tests -mindepth 1 -maxdepth 1 \
      \( -type d -name "__pycache__" -prune \) -o \
      \( -type d -o \( -type f -name "test_*.py" \) \) -print0 | \
      LC_ALL=C sort -z >"$shard_list"
    discovery_pipeline_status=$?
    (( discovery_pipeline_status == 0 )) || exit "$discovery_pipeline_status"
    selected_shards=()
    while IFS= read -r -d "" shard; do
      if [[ -d "$shard" ]]; then
        collectible="$(find "$shard" -type f -name "test_*.py" -print -quit)"
        discovery_status=$?
        (( discovery_status == 0 )) || exit "$discovery_status"
        [[ -n "$collectible" ]] || continue
      fi
      selected_shards+=("$shard")
    done <"$shard_list"
    (( ${#selected_shards[@]} > 0 )) || { print -u2 -- "no collectible not-pg shards discovered"; exit 1; }
    failed=0
    for shard in "${selected_shards[@]}"; do
      python3 -m pytest -p pytest_asyncio.plugin -p anyio.pytest_plugin -p xdist.plugin \
        -q -m "not pg" "$shard"
      shard_status=$?
      if (( shard_status != 0 )); then
        print -u2 -- "uncovered shard: $shard (pytest exit $shard_status)"
        failed=1
      fi
    done
    (( failed == 0 ))'
```

The explicit `PYTHONPATH` is part of this one sanctioned command because tests outside
`tests/companion_ui` import the nested `companion_ui` package during collection. Do not add
one-off path exports to Issue or PR handoffs. Record the canonical command's host-resource failure,
the fallback command, and every failed shard. The command selects a directory only after finding a
collectible `test_*.py` file beneath it, so helper-only directories are never passed to pytest. Its
`pipefail` discovery pipeline is checked before its output is used, and its per-directory collection
checks fail the leased command before a partial shard list can produce a receipt. A fallback run is complete only when every selected shard
passes; if a shard cannot run, the command reports it as an `uncovered shard` and exits nonzero, so
record the uncovered shard as a validation gap rather than claiming the full `not pg` selection
passed.

The full non-PG suite is host-global. The wrapper above holds an atomic repo-common kernel lock for
the entire child process and releases it automatically when the process exits. A chat handshake,
process census, or quiet-period check is useful diagnosis but is not mutual exclusion. If the lock
is already held, do not start another suite and do not kill the holder; retry only with bounded wait
or after the holder's receipt shows terminal state.

The closed canonical resource allowlist is declared once as `HOST_GLOBAL_RESOURCE_NAMES` in
`scripts/run_with_host_lease.py`. Callers must use a name from that allowlist; the wrapper rejects
ad-hoc aliases before creating a lock file, and the host-lease regression tests keep this documented
command aligned with the allowlist.

Enforcement note:
- The applicable command list above is a required pre-merge gate, not advisory; do not substitute a
  repo-wide suite for identifying and running the affected subsystem's verification targets.
- Any PR that changes files under `app/` or `tests/` must run the repo-standard lint gate, currently `ruff check app tests`, before merge.
- Docs and governance PRs keep validation focused and do not run full smoke by default unless their touched surface requires it.
- When `app/` or `tests/` changed, include the `ruff check app tests` output or an explicit tooling limitation in the PR body.
- If CI is not currently blocking these checks, treat merge as blocked until either:
  - the checks pass locally and evidence is attached to the PR, or
  - blocking CI coverage is added for the missing check and enabled.
- For `ruff --fix` in `conftest.py` or known re-export modules, review F401 removals manually and preserve intentional re-exports with `# noqa: F401` where needed.

### CI / validation expectations

`CI Smoke` (`.github/workflows/ci-smoke.yaml`) runs the `Unit tests (not pg)` check
(`pr-unit-tests-not-pg`) automatically on `pull_request`. That check
uses `scripts/select_pr_tests.py` to execute affected-subsystem pytest targets without a Postgres
service, so relevant unit regressions are visible before merge without paying for the repo-wide
suite on every PR. [`TEST_STRATEGY_HOT_PATH.md`](TEST_STRATEGY_HOT_PATH.md) owns that selection
behavior and its paths filter.

`Unit tests (not pg)` is a **required** status check in `main` branch protection. A red run blocks
merge at the platform level: the REST merge API rejects the merge with HTTP 405 while the check is
failing. `main` protection requires this single check, requires no approving review, does not
require the branch to be up to date (`strict=false`), and applies to admins. Verified against
`gh api repos/RasmusTho/agentic-pkm-mvp/branches/main/protection` on 2026-07-29; the durable receipt
lives in [`GITHUB_GOVERNANCE_SETUP.md`](GITHUB_GOVERNANCE_SETUP.md).

Platform enforcement is a floor, not the process gate. [`PR_HOT_PATH.md`](PR_HOT_PATH.md) still
governs when a PR may merge, and the absence of a protection rule on any other surface never waives
it.

`pg`-marked tests reach the PR path only through the narrow `Index PG contracts`
(`pr-index-pg-contracts`) job, which runs `pytest -m "pg"` against a pgvector service for the exact
index/outbox/YouTube-quota acceptance files when those paths change. That job is not a required
check. Broad `pg` and integration coverage stays on `integration-nightly.yaml` (nightly schedule
plus `workflow_dispatch`).

## Documentation rules

- Update the owner doc first.
- Keep current-state docs descriptive of shipped reality.
- Put future-state intent in roadmap/plan docs instead of current-state owner docs.
- Replace duplicated policy with links or short boundary notes.
- When a capability is still being stabilized, make the intended verification path and acceptance path explicit instead of implying they will emerge later.

## Pre-implementation classification

Before starting implementation on a non-trivial task, apply `docs/development/AGENT_OPERATING_PROTOCOL.md` to classify the task class (Architecture / Implementation / Operations / Governance / Cost-control), confirm artifact class and environment/channel risk, identify the governing owner doc, and verify that every AC carries a resolvable `Verify:` target. This is a routing and orientation step, not a process gate — it keeps implementation bounded and stops misclassified work before it reaches code.

## Docs-authoring lane

Docs authoring is the docs-only path for evolving or clarifying authoritative repo docs before backlog extraction.

Use this lane only when:

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
  - `companion-ui/docs/`
  - `companion-ui/design_handoff/`
- the PR does not change code, runtime behavior, contracts, or shipped reality

Docs-authoring rules:

- a governing GitHub Issue is not required
- the PR must be explicitly classified as docs authoring
- the skills consistency lint runs on every PR in the smoke gate (`python3 scripts/lint_skills_consistency.py`, stdlib-only); run it locally when touching `.codex/skills/**` — the pytest wrapper is `tests/governance/test_skills_consistency_lint.py`
- docs authoring does not automatically create backlog work or Project state
- use `docs-to-issue` later when the authored docs are ready to become bounded implementation tasks
- use `feature-breakdown` later when one docs-defined feature should become one parent feature issue plus child slices
- if the change starts affecting implementation or delivered behavior, switch back to the Issue-first implementation lane

## Governance lane

Governance lane is the separate PR path for bounded repository-governance changes that are not product/runtime implementation but are broader than docs-only authoring.

The executable authority for these surfaces is
`.github/workflows/issue-pr-governance.yml`'s
`governanceAllowedExact` and `governanceAllowedPrefixes`.  The list below is
the intentionally checked human-readable mirror; the governance regression
suite rejects drift between the two.  It is distinct from
`scripts/docs_guard_logic.py :: GOVERNANCE_TEMPORAL_ENFORCEMENT`, which is a
narrow temporal owner-doc pairing map rather than a governance-lane admission
allowlist.  `GITHUB_GOVERNANCE_SETUP.md` records this ownership decision
instead of maintaining a second partial list.

Use this lane only when:

- changed files stay inside approved governance surfaces:
  - `README.md`
  - `docs/**`
  - `AGENTS.md`
  - `CLAUDE.md`
  - `.codex/AGENTS.md`
  - `.codex/skills/**`
  - `.codex/agents/**`
  - `.codex/config.toml`
  - `.github/github-governance.yml`
  - `.github/ISSUE_TEMPLATE/**`
  - `.github/pull_request_template.md`
  - `.github/workflows/ci-smoke.yaml`
  - `.github/workflows/issue-pr-governance.yml`
  - `Makefile`
  - `scripts/docs_guard.py`
  - `scripts/docs_guard_logic.py`
  - `scripts/install_skills.sh`
  - `scripts/agent_workspace_preflight.sh`
  - `scripts/agent_workspace_cleanup.sh`
  - `scripts/agent_worktree.py`
  - `scripts/git_hygiene.py`
  - `scripts/git_hygiene_preflight.py`
  - `scripts/git_hygiene_janitor.py`
  - `scripts/issue_pickup_claim.sh`
  - `scripts/reconcile_project_status.py`
  - `scripts/pr_body_generator.py`
  - `scripts/py312_smoke_test.sh`
  - `scripts/await_pr_checks.sh`
  - `scripts/review_before_ci_gate.py`
  - `scripts/workflow_review_risk.py`
  - `scripts/run_with_host_lease.py`
  - `scripts/verify_runtime_chain.sh`
  - `scripts/validate_source_anchors.py`
  - `tests/ops/test_agent_worktree.py`
  - `scripts/validate_issue_readiness.py`
  - `scripts/lint_skills_consistency.py`
  - `companion-ui/design_handoff/README.md`
  - `companion-ui/docs/DESIGN_HANDOFF_GOVERNANCE.md`
  - `companion-ui/prompts/claude-design/**`
  - `companion-ui/prompts/codex/deliver-epic-autonomous-runner.md`
  - `tests/ops/test_git_hygiene.py`
  - `tests/architecture/test_agent_skill_entrypoints.py`
  - `tests/architecture/test_pr_hot_path_governance.py`
  - `tests/governance/test_codex_agents_contract.py`
  - `tests/governance/test_ci_smoke_docs_only_gate.py`
  - `tests/governance/test_issue_pr_governance.py`
  - `tests/governance/test_known_defects_registry.py`
  - `tests/governance/test_resume_work_contract.py`
  - `tests/governance/test_skills_consistency_lint.py`
  - `tests/ops/test_project_status_reconcile.py`
  - `tests/ops/test_review_before_ci_gate.py`
  - `tests/ops/test_review_before_ci_workflow_risk.py`
  - `tests/ops/test_host_global_lease.py`
  - `tests/scripts/test_validate_issue_readiness.py`
  - `tests/scripts/test_docs_guard.py`
  - `tests/scripts/test_pr_body_generator.py`
  - `tests/fixtures/issue_readiness/**`
  - `tests/fixtures/pr_body_generator/**`
- the PR is limited to repo governance, agent workflow, or lightweight enforcement
- the PR does not change product/runtime implementation or shipped feature behavior

Governance-lane rules:

- a governing GitHub Issue is not required
- the PR must be explicitly classified as governance lane
- governance lane is for repository policy and workflow maintenance, not backlog delivery
- if the change starts affecting implementation or delivered behavior, switch back to the Issue-first implementation lane

Issues are the normal workflow contract. Direct repair PRs are allowed for bounded immediate fixes when the PR body is the contract, but they should stay narrow and avoid inventing backlog work after the fact.

## Runtime separation

- Builder-agent instruction lives in `AGENTS.md` and the development reference docs.
- Runtime/system-agent architecture lives in `docs/AGENTS.md` and related runtime/concept docs.
- Do not treat runtime semantics as builder-agent instructions, and do not write builder-agent workflow into runtime docs.

## GitHub issue-first execution loop

For implementation work, the delivery loop is:

1. Docs/owner docs define the intended contract.
2. Feature / capability Issue defines the target outcome plus verification and validation / acceptance path.
3. Slice / child Issue defines the bounded implementation task.
4. Builder agent implements the slice in a PR.
5. CI/test workflows verify the slice and its changed seams.
6. Merge closes the slice when its bounded contract is satisfied.
7. Feature validation continues on the parent issue until the operator/product path is proven.
8. Acceptance closes the feature and triggers owner-doc promotion when the support claim changes.

State model for lane-based delivery:

- Issue state supports claim and bounded execution truth: `Ready`, `In Progress`, `Blocked`, `Done`.
- PR/Project-item state supports review/integration projection: `Review`, `In Progress`, `Blocked`, `Done`.
- Keep issue and PR state separate in multi-slice lanes where several implementation issues can feed the same lane PR.
- `issue-to-code` owns fast issue claim (verified dispatcher lease when available; otherwise remove
  `agent:ready` only through the durable claimant-receipt fallback) to prevent double-pick.
  - Claim must run through
    `scripts/issue_pickup_claim.sh --issue <N> --agent <agent_id> --session <session_id>` so workspace
    preflight and actual claim evidence are verified before label mutation.
- Open PR is the default publication mode. Draft PR is opt-in and requires an explicit reason.
- `Review` is the agent-review gate before verification, not a generic waiting state.
- `pr-integration` is conditional and should be used when mergeability/CI attachment/reviewability needs repair; it is not required after every publication.
- Workspace isolation is mandatory for multi-agent work: one active Codex session per worktree/branch checkout.
- Prefer automation for PR/project-item projection (especially `Done` on terminal PR state) and use manual skill writes as fallback correction when drift is detected.

Execution rule:

- do not start non-trivial implementation without a governing Issue
- select Issues with a strictly validated `agent:ready` label; Project Status is not a pickup gate
- use the linked Issue as the bounded source of truth for scope and acceptance
- implementation PRs should usually link the governing slice / child issue
- do not implement directly from a feature / capability issue when the work is clearly multi-slice
- when a capability spans multiple PRs, keep verification and acceptance attached to the capability rather than scattering them across unrelated roadmap bullets

Docs-authoring and governance-lane PRs are separate lanes and do not replace this implementation contract.

Optional repo-local Codex skills may assist with either lane from `.codex/skills/`, but they do not replace the governing repo policy. Implementation-facing skills should route larger work through `feature-breakdown`, then execute slices through the same `Docs -> Feature -> Slice -> PR -> Slice verification -> Feature validation -> Acceptance` sequence and keep `AGENTS.md` as the canonical builder-agent policy surface.

Lifecycle truth rule:

- GitHub Issue state and linked PR/merge state are the harder lifecycle authority.
- Project `Status` is an optional legacy projection for board visibility.
- `agent:ready` qualifies an Issue for pickup after strict contract validation; dispatcher claim state prevents active collisions when available.
- `In Progress` covers active implementation, including draft PRs and open PRs before explicit review handoff.
- `Review` begins only when the PR becomes the explicit review handoff artifact, normally after review is requested.
- closed or delivered work must not retain `agent:*` labels.
- if Project state drifts because automation cannot update the board, correct it opportunistically without treating the drift itself as a delivery blocker

## Acceptance verifiability

Every Acceptance Criterion on a backlog Issue must declare its verification inline with a `Verify:` marker. This is a contract-shape rule, not a test-methodology rule: it covers behavioral and non-behavioral ACs alike.

Form:

```
## Acceptance Criteria

- [ ] Ingest rejects entries whose domain fails boundary validation.
  Verify: `tests/ingest/test_domain_boundary.py::test_rejects_invalid_domain`
- [ ] `docs/CONCEPTS/DOMAIN.md` describes the ingest boundary as shipped.
  Verify: doc writeback at `docs/CONCEPTS/DOMAIN.md :: ingest-boundary`
- [ ] Roadmap no longer lists domain-at-ingest as pending.
  Verify: `docs/ROADMAP.md :: DOMAIN-INGEST` removed or rewritten as delivered.
```

Rules:

- Behavioral ACs point to a concrete test (existing or to-be-added) by file and test name.
- Ready-label validation permits a behavioral `tests/...py::test_name` target to name a new test
  file that the builder will add. Other file-based `Verify:` targets must resolve to existing
  repository files.
- Enforcement ACs — behavioral ACs asserting a guard, gate, or invariant holds on the live runtime path — must point to a test that exercises the production call site, not the guard function in isolation. "Module exists and is unit-tested" does not discharge an enforcement AC; "invoked on the runtime path and asserted there" does.
- Non-behavioral ACs point to a concrete observable target: doc writeback path plus anchor, roadmap diff, runtime receipt, a bare repo anchor (`` `<path> :: <anchor>` ``), a diff-of-file target (``diff of `<repo path>` <what the diff adds>``), or a marker-presence target (`` `<literal>` present in `<repo path>` ``). A durable repository path or anchor is what makes the target concrete.
- A backticked canonical target may carry a trailing prose annotation on the same marker line (as the roadmap example above shows); the target stays the backticked segment. The `Verify:` marker opens its own line per the template; an inline tail on the AC line declares a marker only when its target is grammar-resolvable — any other mid-line mention inside AC prose is not a marker.
- An AC that needs several targets declares one `Verify:` line per target, as sub-bullets of the same acceptance item — splitting the targets does not split the AC and does not change the AC count. Targets joined on one marker line (` + `, `and`, or a comma between two backticked targets) are read as a single target whose backticks no longer pair, so the line fails resolution and validation reports a missing file for a path that exists (#3857, #3859).
- If an AC cannot carry a resolvable `Verify:` target, refine or split it before marking the Issue `agent:ready`.
- `Suggested Validation` remains the section that lists the commands and procedures that execute the declared `Verify:` targets. ACs and Suggested Validation are coupled: commands exist to resolve the Verify targets, not to duplicate them.

Enforcement surfaces:

- Creation: `docs-to-issue`, `feature-breakdown`, and `bug-to-issue` must produce ACs with `Verify:` lines.
- Repair: `issue-maintenance-change-control` treats missing `Verify:` as malformed contract shape.
- Consumption: `issue-to-code` gates on `Verify:` presence and implements test-first for behavioral ACs, writeback-first for non-behavioral ACs.

## Multi-Agent Workspace Guardrails

- Preflight before claim/integration:
  - `scripts/agent_workspace_preflight.sh --expected-branch "$(git branch --show-current)" --expected-worktree "$(git rev-parse --show-toplevel)"`
- Preflight at the publication boundary (pre-commit and pre-push, every lane):
  - `scripts/agent_workspace_preflight.sh --expected-branch "$EXPECTED_BRANCH" --expected-worktree "$EXPECTED_WORKTREE" --allow-dirty`
  - The branch-truth gate lives in `publish-pr` and applies to implementation, feature-breakdown, docs-authoring, and governance lanes — not only `issue-to-code`. `--allow-dirty` tolerates the intentionally dirty tree at publish time while still failing on branch or worktree drift, so a concurrent agent switching the shared root worktree's branch cannot land a commit on the wrong branch.
  - The base-branch check asserts what matters at the publication boundary: HEAD already contains `origin/main`. A local `main` ref that lags or diverges from `origin/main` is advisory when HEAD already contains `origin/main`, because `main` stays checked out in the shared root worktree and another task may advance or diverge it. A local base ref that does not prove `origin/main` reachability, or a HEAD without `origin/main`, still fails the gate.
- Safe cleanup report:
  - `scripts/agent_workspace_cleanup.sh --report`
- Safe cleanup apply (clean tree required):
  - `scripts/agent_workspace_cleanup.sh --apply --pr-state-file <path> --lease-file <path>`
  - To reclaim exactly one completed worktree, add both `--target-worktree <absolute-path>` and
    `--target-generation <32-hex-generation>`. Targeted apply limits mutations to that eligible
    worktree and its associated local branch; it never acts on unrelated worktrees, branches,
    remotes, stashes, or prune candidates. Missing, mismatched, or non-candidate selectors fail
    closed before removal.
- Register dedicated issue worktrees with `scripts/agent_worktree.py register`, renew them with
  `heartbeat`, and record `release` or `complete` when ownership ends. Cleanup is report-only by
  default. Apply may remove only a registered, expired, clean, unlocked worktree whose live
  path/branch/HEAD and generation marker still match, with no active lease and proven merge/closure
  eligibility; active, dirty, locked, mismatched, replaced-generation, orphaned, and unregistered
  worktrees are preserved. Apply requires explicit PR-state and active-lease files and a present,
  readable lifecycle registry; absence or corruption of any of those proofs is fail-closed. Fetch and planning use a locked lifecycle snapshot without retaining the
  registry lock; lease and lifecycle authority are revalidated at the targeted removal boundary,
  with the lifecycle lock held through that one command. Before Git removal it durably records a
  generation-bound `removal_pending` transition. Successful removal durably retires the exact
  generation before branch deletion; restart reconciliation completes only a pending transition
  and never infers removal from an ordinary missing lifecycle record. Branch deletion after a
  removal revalidates both the `worktree:<path>` and the `branch:<branch>` lease identity
  immediately before the irreversible delete and fails closed if either is claimed. That
  revalidation reads a foreign lease file it cannot lock, so it is a check-then-act guard, not
  mutual exclusion: a lease that first becomes active between that read and the delete is not seen.
  The removal tombstone keeps the path→branch association, so a later cleanup run still binds the
  branch to its former worktree path and preserves it while that path lease is active. The registry
  is keyed by path, so re-registering that path for a new branch carries the displaced binding
  forward on the new record (`prior_bindings`, deduplicated by branch and bounded to the 8 most
  recent) rather than dropping it. Broad `git worktree prune`
  remains report-only. The current checkout is always skipped.
  Registration, heartbeat, release, and completion resolve potentially slow live Git identity and
  generation-marker state without holding the shared lifecycle-registry lock. Each update first
  snapshots any existing target authority under a short lock, captures live path, branch, and
  generation outside it, and serializes first-time generation-marker creation with a checkout-local
  lock. It then re-reads the registry at the atomic write boundary and refuses the write if the
  target path, branch, owner, generation, or lifecycle state changed. Unrelated lifecycle writers
  therefore remain independent without weakening generation-bound, fail-closed cleanup authority.
- Stash cleanup within the same apply run only ever drops a stash it resolved as a
  `preserve-local-drift`-marked, age-eligible candidate; it never drops by a stale positional
  index. `stash@{N}` is a position in the stash reflog, not a stable name — worktree paths and
  branch names do not shift when a sibling is removed, but every drop of an earlier stash renumbers
  every later one, and (independently) capturing that selector from a `--date`-formatted listing
  can make it unresolvable to any real reflog position at all. Each candidate is instead identified
  by its stash commit hash, captured once at plan time; immediately before every drop, `janitor_apply`
  re-resolves that hash to whichever `stash@{N}` currently holds it and verifies the match. A
  candidate that cannot be re-resolved, or whose re-resolved entry no longer matches, aborts the
  remaining stash cleanup for that run with a recorded error rather than dropping a different,
  non-candidate stash.
- Resuming interrupted work: when a session breaks mid-task (quota, network, hung command, tool failure) and the tree is dirty or the branch has unmerged work, reconstruct state from git first, then continue — see `.codex/skills/resume-work/SKILL.md`.
- Closure: `verification-and-closure` resolves every AC's `Verify:` target and blocks merge if any behavioral test is missing, skipped, or xfailed.

The builder-agent effect: test-first discipline emerges automatically for behavioral work — the failing test is the AC's declared proof, so the agent writes or confirms it before code, then implements the smallest change to turn it green.

## Source-anchor rule for backlog creation

For new backlog work, GitHub is the live tracking surface and docs provide the semantic source.

Use this split:

- owner docs, SoT docs, roadmap docs, and active plans define intent, constraints, sequencing, verification posture, validation posture, and acceptance posture
- GitHub Issues define backlog task truth; GitHub Project provides the shared board projection
- owner-doc updates are required when work is delivered and the shipped reality changes

When converting a doc item into a GitHub Issue:

1. Add a stable `Source Anchors` section to the Issue.
2. Reference the most local actionable doc item, not only a broad document path.
3. Prefer stable item IDs such as `PA2-FREEFORM` or `ORCHV2-TDD-PILOT` over prose fragments.
4. Keep the anchor stable even if the surrounding paragraph is reworded.

Recommended anchor format:

- uppercase kebab-case or compact uppercase tokens
- short family prefix tied to the track or owning doc
- examples:
  - `docs/PANEL_AGENT.md :: PA2-FREEFORM`
  - `docs/ROADMAP.md :: ORCHV2-PILOT`
  - `docs/STATUS.md :: SETTINGS-PROVENANCE`

Do not rely on inline `Tracked by: #...` or `Backlog: #...` markers as the primary backlog receipt.
Those markers are now secondary convenience notes because they are not visible to other collaborators until merged.

## Delivery writeback rule

When an Issue is delivered:

1. Update the owner document to reflect the new shipped state.
2. Move the truth from the Issue into the owner doc (e.g., `STATUS.md`, roadmap sections, etc.).
3. Remove or rewrite roadmap/plan wording so it no longer reads as pending when work is delivered.
4. Keep GitHub Issue/PR history and labels as the authoritative backlog and delivery record;
   Project Status, when maintained, is a rebuildable projection.
5. If only a slice was delivered, update the parent feature issue with validation evidence and keep owner docs stable until acceptance.
6. If the work closed a larger capability, make sure the owner docs also record what verified it and what accepted it.

Owner docs are the source of shipped reality. Generated receipt pages (if adopted) may summarize Issue state from GitHub, but they do not replace the owner doc as the canonical truth for shipped behavior.
