State: Development reference. Not an auto-loaded instruction file.
# Development Workflow

Use this document for the builder-agent working loop and validation expectations after reading `AGENTS.md`.

This document applies to development-time contributors. It does not define runtime/system-agent behavior.

## Working loop

For non-trivial changes:

1. Identify the owning document via `docs/DOCS_INDEX.md`.
2. Read the owner doc before changing code or neighboring docs.
3. Confirm the planning chain for the work: docs/SoT/plan -> capability/epic -> slice/child issue -> code/PR -> verification -> acceptance.
4. Add or update tests for the intended change when the work is not docs-only.
5. Implement the smallest change that fits the documented architecture.
6. Update owner docs in the same change when behavior, contracts, or architecture changed.
7. Run the relevant validation commands and record any gaps.

## Lightweight breakdown model

Use the following practical breakdown model across docs, GitHub, and implementation:

- Docs / SoT / plan docs define direction, constraints, and capability intent.
- Capability / epic issues define the target outcome and the acceptance path for a meaningful piece of work.
- Slice / child issues define the bounded implementation steps that coding agents should pick up.
- PRs should usually map to one slice / child issue, not to a vague roadmap heading.
- Verification proves the implemented slice works at the intended layer.
- Acceptance proves the capability works from the operator or product point of view.

Interpretation rule:
- capabilities are not done merely because code landed
- larger capabilities should define both a verification path and an acceptance path before they are treated as complete
- this is a lightweight delivery spine, not a heavyweight process rewrite

Recommended planning chain:

`Docs / SoT / plan -> Capability / Epic -> Slice / Child issue -> Code / PR -> Verification -> Acceptance`

## Validation baseline

- Docs-only changes:
  - run any repo docs validation command if one exists
  - otherwise run lightweight repo checks that are still appropriate
- Code-affecting changes:
  - `ruff check app tests`
  - `mypy app`
  - `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q -m "not pg"`
- Settings/runtime contract changes:
  - `python -m app.cli settings-validate --json`

Run narrower or broader suites when the touched area requires it.

## Documentation rules

- Update the owner doc first.
- Keep current-state docs descriptive of shipped reality.
- Put future-state intent in roadmap/plan docs instead of current-state owner docs.
- Replace duplicated policy with links or short boundary notes.
- When a capability is still being stabilized, make the intended verification path and acceptance path explicit instead of implying they will emerge later.

## Docs-authoring lane

Docs authoring is the docs-only path for evolving or clarifying authoritative repo docs before backlog extraction.

Use this lane only when:

- changed files stay inside approved docs-authoring surfaces:
  - `docs/**`
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
- docs authoring does not automatically create backlog work or Project state
- use `docs-to-issue` later when the authored docs are ready to become bounded implementation tasks
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
- the PR is limited to repo governance, agent workflow, or lightweight enforcement
- the PR does not change product/runtime implementation or shipped feature behavior

Governance-lane rules:

- a governing GitHub Issue is not required
- the PR must be explicitly classified as governance lane
- governance lane is for repository policy and workflow maintenance, not backlog delivery
- if the change starts affecting implementation or delivered behavior, switch back to the Issue-first implementation lane

## Runtime separation

- Builder-agent instruction lives in `AGENTS.md` and the development reference docs.
- Runtime/system-agent architecture lives in `docs/AGENTS.md` and related runtime/concept docs.
- Do not treat runtime semantics as builder-agent instructions, and do not write builder-agent workflow into runtime docs.

## GitHub issue-first execution loop

For implementation work, the delivery loop is:

1. Docs/owner docs define the intended contract.
2. Capability/epic Issue defines the target outcome.
3. Slice/child Issue defines the bounded implementation task.
4. Builder agent implements the slice in a PR.
5. CI/test workflows verify the slice and its changed seams.
6. Acceptance closes the capability when the operator/product path is proven.

Execution rule:

- do not start non-trivial implementation without a governing Issue
- prefer Issues with `Status=Ready` and label `agent:ready`
- use the linked Issue as the bounded source of truth for scope and acceptance
- implementation PRs should usually link the governing slice / child issue
- when a capability spans multiple PRs, keep verification and acceptance attached to the capability rather than scattering them across unrelated roadmap bullets

Docs-authoring and governance-lane PRs are separate lanes and do not replace this implementation contract.

Optional repo-local Codex skills may assist with either lane from `.codex/skills/`, but they do not replace the governing repo policy. Implementation-facing skills must still route work through the same `Docs -> Capability -> Slice -> PR -> Verification -> Acceptance` sequence and keep `AGENTS.md` as the canonical builder-agent policy surface.

Lifecycle truth rule:

- GitHub Issue state and linked PR/merge state are the harder lifecycle authority.
- Project `Status` is the preferred projection of that lifecycle for pickup and board visibility.
- `agent:ready` qualifies an Issue for pickup only when `Status=Ready`.
- `In Progress` covers active implementation, including draft PRs and open PRs before explicit review handoff.
- `Review` begins only when the PR becomes the explicit review handoff artifact, normally after review is requested.
- closed or delivered work must not retain `agent:*` labels.
- if Project state drifts because automation cannot update the board, correct it opportunistically without treating the drift itself as a delivery blocker

## Source-anchor rule for backlog creation

For new backlog work, GitHub is the live tracking surface and docs provide the semantic source.

Use this split:

- owner docs, SoT docs, roadmap docs, and active plans define intent, constraints, sequencing, verification posture, and acceptance posture
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
5. If the work closed a larger capability, make sure the owner docs also record what verified it and what accepted it.

Owner docs are the source of shipped reality. Generated receipt pages (if adopted) may summarize Issue state from GitHub, but they do not replace the owner doc as the canonical truth for shipped behavior.
