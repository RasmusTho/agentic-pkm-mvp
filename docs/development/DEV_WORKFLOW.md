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

- Docs-only changes:
  - run any repo docs validation command if one exists
  - when `.codex/skills/**` changed, run `python3 scripts/lint_skills_consistency.py` (exit 0, zero output = clean)
  - otherwise run lightweight repo checks that are still appropriate
- Code-affecting changes:
  - `ruff check app tests`
  - `mypy app`
  - `pytest -q -m "not pg"`
- Settings/runtime contract changes:
  - `python -m app.cli settings-validate --json`

Run narrower or broader suites when the touched area requires it.

Enforcement note:
- The command list above is a required pre-merge gate, not advisory.
- Any PR that changes files under `app/` or `tests/` must run the repo-standard lint gate, currently `ruff check app tests`, before merge.
- Docs-only PRs can keep validation lightweight and should not run full smoke by default unless their touched surface requires it.
- When `app/` or `tests/` changed, include the `ruff check app tests` output or an explicit tooling limitation in the PR body.
- If CI is not currently blocking these checks, treat merge as blocked until either:
  - the checks pass locally and evidence is attached to the PR, or
  - blocking CI coverage is added for the missing check and enabled.
- For `ruff --fix` in `conftest.py` or known re-export modules, review F401 removals manually and preserve intentional re-exports with `# noqa: F401` where needed.

### CI / validation expectations

The CI workflow runs a non-required `Unit tests (not pg)` check automatically on `pull_request`.
That check executes `pytest -q -m "not pg"` without a Postgres
service so unit regressions are visible before merge.

This PR check is intentionally non-required until it has been observed green on real PRs. Promoting
the check to a required branch-protection gate, or adding `pg`-marked tests with a Postgres service
to the PR path, is deferred to follow-up work based on observed signal and CI cost/flakiness.

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

Use this lane only when:

- changed files stay inside approved governance surfaces:
  - `docs/**`
  - `AGENTS.md`
  - `CLAUDE.md`
  - `.codex/AGENTS.md`
  - `.codex/skills/**`
  - `.github/github-governance.yml`
  - `.github/ISSUE_TEMPLATE/*.yml`
  - `.github/pull_request_template.md`
  - `.github/workflows/issue-pr-governance.yml`
  - `scripts/docs_guard.py`
  - `tests/architecture/test_agent_skill_entrypoints.py`
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
- `issue-to-code` owns fast issue claim (`Ready` -> `In Progress` and remove `agent:ready`) to prevent double-pick.
  - Claim must run through `scripts/issue_pickup_claim.sh --issue <N>` so workspace preflight is enforced before label mutation.
- Open PR is the default publication mode. Draft PR is opt-in and requires an explicit reason.
- `Review` is the agent-review gate before verification, not a generic waiting state.
- `pr-integration` is conditional and should be used when mergeability/CI attachment/reviewability needs repair; it is not required after every publication.
- Workspace isolation is mandatory for multi-agent work: one active Codex session per worktree/branch checkout.
- Prefer automation for PR/project-item projection (especially `Done` on terminal PR state) and use manual skill writes as fallback correction when drift is detected.

Execution rule:

- do not start non-trivial implementation without a governing Issue
- prefer Issues with `Status=Ready` and label `agent:ready`
- use the linked Issue as the bounded source of truth for scope and acceptance
- implementation PRs should usually link the governing slice / child issue
- do not implement directly from a feature / capability issue when the work is clearly multi-slice
- when a capability spans multiple PRs, keep verification and acceptance attached to the capability rather than scattering them across unrelated roadmap bullets

Docs-authoring and governance-lane PRs are separate lanes and do not replace this implementation contract.

Optional repo-local Codex skills may assist with either lane from `.codex/skills/`, but they do not replace the governing repo policy. Implementation-facing skills should route larger work through `feature-breakdown`, then execute slices through the same `Docs -> Feature -> Slice -> PR -> Slice verification -> Feature validation -> Acceptance` sequence and keep `AGENTS.md` as the canonical builder-agent policy surface.

Lifecycle truth rule:

- GitHub Issue state and linked PR/merge state are the harder lifecycle authority.
- Project `Status` is the preferred projection of that lifecycle for pickup and board visibility.
- `agent:ready` qualifies an Issue for pickup only when `Status=Ready`.
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
- Enforcement ACs — behavioral ACs asserting a guard, gate, or invariant holds on the live runtime path — must point to a test that exercises the production call site, not the guard function in isolation. "Module exists and is unit-tested" does not discharge an enforcement AC; "invoked on the runtime path and asserted there" does.
- Non-behavioral ACs point to a concrete observable target: doc writeback path plus anchor, roadmap diff, or runtime receipt.
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
  - The base-branch check asserts what matters at the publication boundary: HEAD already contains `origin/main`. A local `main` ref that merely lags `origin/main` (`status: "behind"`) is advisory, because `main` stays checked out in the root worktree and cannot be fast-forwarded from a dedicated worktree. A diverged or unresolvable base ref, or a HEAD without `origin/main`, still fails the gate.
- Safe cleanup report:
  - `scripts/agent_workspace_cleanup.sh --report`
- Safe cleanup apply (clean tree required):
  - `scripts/agent_workspace_cleanup.sh --apply`
- Cleanup apply only removes merged `codex/` branches/worktrees and old `preserve-local-drift` stashes; it skips the current checkout.
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
4. Keep the GitHub Issue/Project as the authoritative record of backlog state history.
5. If only a slice was delivered, update the parent feature issue with validation evidence and keep owner docs stable until acceptance.
6. If the work closed a larger capability, make sure the owner docs also record what verified it and what accepted it.

Owner docs are the source of shipped reality. Generated receipt pages (if adopted) may summarize Issue state from GitHub, but they do not replace the owner doc as the canonical truth for shipped behavior.
