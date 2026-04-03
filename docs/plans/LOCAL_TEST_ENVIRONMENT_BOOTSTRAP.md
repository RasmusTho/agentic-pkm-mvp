State: Plan
Doc role: Plan
Authority: Coordination plan for the first docs-first stabilization wave around the local test bootstrap path.
Owner: Runtime / docs-first stabilization
Temporal class: strategic
Review cadence: weekly
Source of truth: mixed
Last reviewed: 2026-04-02
Last verified against: docs/ENVIRONMENTS.md, docs/OPERATIONS.md, docs/TESTING.md, docs/ROADMAP.md, docs/STATUS.md, Makefile, docs/runbooks/UAT_PANEL_WATCHER.md, current repo state on 2026-04-02
# Local Test Environment Bootstrap

## Purpose

Define the repo-supported local `test` environment as a productized verification path rather than a loose collection of scripts.

This plan exists to make one intended path explicit before more implementation work continues.

## Scope

This wave is docs-first and covers:

- the minimal `dev` / `test` / `prod` environment model
- the canonical local test bootstrap golden path
- the planning chain from docs and capability intent down to slices and PRs
- the verification and acceptance spine for bootstrap-related work
- honest status/roadmap wording about what is already working and what is still incomplete

## Out of Scope

This wave does not:

- fix the already-known runtime/bootstrap bugs except for tiny doc-supporting corrections if absolutely necessary
- introduce a heavyweight Scrum process
- introduce a formal V-model process
- redefine the product architecture through the bootstrap flow
- claim that `prod` is fully implemented as an end-state environment contract

## Target Golden Path

The intended supported local verification path is:

1. Reset runtime state.
2. Initialize a clean test vault.
3. Seed the UAT notes.
4. Start the local stack against that vault.
5. Verify health and status.
6. Run scripted UAT.

Current canonical command path:

```bash
make test-bootstrap
```

Expanded form:

```bash
make reset-zero-force
make test-vault-init
VAULT_ROOT="$(pwd)/vault-test" scripts/start_full_system.sh
VAULT_ROOT="$(pwd)/vault-test" bash scripts/verify_runtime_stack.sh
VAULT_ROOT="$(pwd)/vault-test" python -m app.cli uat-run-vault-test --vault-root "$(pwd)/vault-test" --assert
```

## Acceptance Criteria

This docs-first wave is complete when:

- the planning chain is explicit in workflow docs and used consistently in roadmap/status wording
- `test` is documented as the first concrete reference environment for local verification
- the local test bootstrap path is described as the canonical repo-supported golden path
- testing docs treat bootstrap as a testable contract and a stabilization gate
- roadmap/status docs state clearly that the path is partially working but not yet self-contained end to end
- follow-up implementation work can be broken into bounded capability and slice issues without re-arguing the intended path

## Verification And Acceptance Spine

For this capability:

- verification means the repo can prove the bootstrap flow at the unit, integration, system/bootstrap, and scripted UAT layers
- acceptance means the clean-state local test path works as a repeatable operator-facing contract against the seeded test vault

Interpretation rule:
- bootstrap work is not complete when a script merely starts
- bootstrap work is complete when the intended path is verified and accepted as a repo-supported local flow

## Recommended Execution Mapping

Use this plan as the first practical `feature-breakdown` candidate:

- parent feature issue: local test environment bootstrap stabilization
- child slices: bounded fixes or hardening steps in reset, vault init, startup, health verification, UAT execution, and acceptance evidence
- PRs: carry slice verification receipts
- parent feature issue: carries post-merge validation evidence and the acceptance checklist
- owner docs: are promoted again only when the bootstrap path is accepted as supported truth

## Relationship To Existing Blocker Issues

This plan does not replace the already-open bootstrap blocker issues.

Use this document as the capability-level framing above those blocker issues:

- capability / epic: local test environment bootstrap stabilization
- slices / child issues: specific blockers in reset, vault init, startup, health verification, and UAT execution

If new issues are opened from this plan, they should reference this document plus the local owning doc section that defines the relevant contract.
