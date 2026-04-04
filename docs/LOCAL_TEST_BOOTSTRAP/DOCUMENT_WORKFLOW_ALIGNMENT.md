---
name: Document Workflow Alignment
description: Align workflow and testing docs to reflect the supported bootstrap path
task_id: BOOTSTRAP-06
source_anchor: docs/plans/LOCAL_TEST_ENVIRONMENT_BOOTSTRAP.md :: Acceptance Criteria (roadmap/status docs state clearly...)
parent_capability: Local test environment bootstrap stabilization
prerequisites: []
depends_on: []
can_parallelize_with: [RESET_RUNTIME_STATE]
---

# Document Workflow Alignment

## Purpose

Ensure that the repo's workflow, testing, and operations documentation explicitly describe the local test bootstrap path as a supported operator-facing contract, with clear statements about what is working, what gaps remain, and what verification/acceptance gates exist.

## What This Task Does

Update the following docs to align with the bootstrap specification:

### 1. `docs/development/DEV_WORKFLOW.md`
- Add or clarify the planning chain: docs → parent feature issue → implementation tasks → PR → verification → merge → validation → acceptance → owner-doc promotion.
- Reference the local test bootstrap as the first real example of the feature-breakdown model.
- Explain that task specifications are system-specification documents, not issue templates (one spec can map to many issues).
- Link to the `docs/LOCAL_TEST_BOOTSTRAP/` directory.

### 2. `docs/TESTING.md`
- Clarify that the local test bootstrap path is a **first-class testable contract**, not informal setup glue.
- Update or reference `docs/TESTING.md :: Bootstrap As A Verification Contract` to state current posture:
  - Either: "The clean-state local test path is now fully supported and verified (as of [date])."
  - Or: "The clean-state local test path is partially working with known gaps (see GitHub issues #X, #Y, #Z)."
- Link to `docs/LOCAL_TEST_BOOTSTRAP/` specification.

### 3. `docs/STATUS.md :: Current Snapshot`
- Update the line: "The local test bootstrap/UAT path is still not fully self-contained end to end."
- Change it to reflect current status after tasks are merged:
  - If all tasks are done: "The local test bootstrap path is now fully supported, verified, and accepted as the canonical local verification flow."
  - If partial: "The local test bootstrap path is now fully specified and partially implemented (tasks 1–4 complete, UAT in progress)."

### 4. `docs/ENVIRONMENTS.md`
- Verify that the `test` environment is clearly documented as the canonical local verification environment.
- Confirm that the bootstrap golden path (`make test-bootstrap`) is named as the supported local operator workflow.
- Add a link to `docs/LOCAL_TEST_BOOTSTRAP/` directory if not present.

### 5. `docs/ROADMAP.md` (if needed)
- If the roadmap mentions local test bootstrap as "in progress," update it to reflect completion status.
- Keep the language future-oriented, not claiming work that is not yet complete.

## Concretely

**Before (current):**
```markdown
# docs/STATUS.md
The local test stack can be started successfully against a separate test vault,
and `uat-seed-vault-test` works.
The repo-supported local bootstrap/UAT path is still not fully self-contained end to end;
several concrete blocker issues already exist for that work.
```

**After (post-implementation):**
```markdown
# docs/STATUS.md
The local test bootstrap path is now fully supported, verified, and accepted as the
canonical local verification contract. See docs/LOCAL_TEST_BOOTSTRAP/ for the
specification and implementation status. The canonical path is: make test-bootstrap
```

## Why This Matters

If docs are vague or outdated, operators don't trust the bootstrap path. Clear, honest documentation gives operators **confidence in the supported workflow** and makes it easy to identify gaps.

## Acceptance Criteria

- [ ] `docs/development/DEV_WORKFLOW.md` clearly states the planning chain with LOCAL_TEST_BOOTSTRAP as an example.
- [ ] `docs/development/DEV_WORKFLOW.md` explains task specs as system-specification documents (one-to-many mapping to issues).
- [ ] `docs/TESTING.md :: Bootstrap As A Verification Contract` is updated to reflect current posture (full/partial/incomplete).
- [ ] `docs/TESTING.md` links to `docs/LOCAL_TEST_BOOTSTRAP/` directory.
- [ ] `docs/STATUS.md :: Current Snapshot` is updated (not vague, states clear support/gap status).
- [ ] `docs/ENVIRONMENTS.md` names the `test` environment and the bootstrap golden path.
- [ ] No conflicting or outdated statements remain in other docs (brief scan for consistency).
- [ ] Links between docs are correct and navigable.

## How to Verify (Pre-Merge)

**Documentation review:**
```bash
# Check that the planning chain is mentioned
grep -i "planning chain" docs/development/DEV_WORKFLOW.md
grep -i "LOCAL_TEST_BOOTSTRAP" docs/development/DEV_WORKFLOW.md

# Check that TESTING.md mentions bootstrap as a testable contract
grep -i "bootstrap.*testable contract" docs/TESTING.md

# Check that STATUS.md is clear (not vague)
grep -A2 -B2 "local test bootstrap" docs/STATUS.md

# Check ENVIRONMENTS.md
grep -i "test.*environment" docs/ENVIRONMENTS.md
grep -i "make test-bootstrap" docs/ENVIRONMENTS.md

# Verify relative links are correct
ls docs/LOCAL_TEST_BOOTSTRAP/*.md | wc -l  # Should be 7
```

**Human review:**
1. Read `docs/TESTING.md` and verify bootstrap is described as first-class.
2. Read `docs/STATUS.md :: Current Snapshot` and verify the support status is clear.
3. Read `docs/development/DEV_WORKFLOW.md` and verify the planning chain mentions LOCAL_TEST_BOOTSTRAP.
4. Follow links from DEV_WORKFLOW.md → LOCAL_TEST_BOOTSTRAP/README.md → task docs; verify navigation is smooth.

## Out of Scope

- Rewriting entire documents; only targeted updates.
- Changing the product architecture.
- Creating brand-new docs where existing ones suffice.
- Changing the verification or testing strategy itself.

## Related Docs

- `docs/plans/LOCAL_TEST_ENVIRONMENT_BOOTSTRAP.md` (parent capability plan)
- `docs/LOCAL_TEST_BOOTSTRAP/` (task specifications)
- `docs/development/DEV_WORKFLOW.md` (workflow model)
- `docs/TESTING.md` (testing strategy)
- `docs/STATUS.md` (current snapshot)
- `docs/ENVIRONMENTS.md` (environment contracts)

## Related GitHub Issues

When implementing, create GitHub issue(s) referencing this spec: "Implements LOCAL_TEST_BOOTSTRAP/DOCUMENT_WORKFLOW_ALIGNMENT". Use the acceptance criteria above as the issue contract. No blockers — can start immediately.

---

**Status:** Specification ready. No dependencies; ready to start immediately.
