---
name: Local Test Bootstrap Specification
description: System specification for the local test environment bootstrap capability
type: specification
authority: SoT for local test bootstrap implementation sequencing
source_of_truth: docs/plans/LOCAL_TEST_ENVIRONMENT_BOOTSTRAP.md (parent capability plan)
related_docs:
  - docs/TESTING.md
  - docs/ENVIRONMENTS.md
  - docs/development/DEV_WORKFLOW.md
---

# Local Test Bootstrap Specification

This directory contains the system specification for the local test environment bootstrap capability. Each document describes a discrete implementation task — its purpose, acceptance criteria, verification approach, and how to know when it is complete.

These are **not** issue templates. Each task specification can map to one or many GitHub issues depending on implementation choices. The specification document is the source of truth; the GitHub issues are the execution artifacts.

## Canonical Path

The intended local test bootstrap golden path:

```bash
make reset-zero-force
make test-vault-init
VAULT_ROOT="$(pwd)/vault-test" scripts/start_full_system.sh
VAULT_ROOT="$(pwd)/vault-test" bash scripts/verify_runtime_stack.sh
VAULT_ROOT="$(pwd)/vault-test" python -m app.cli uat-run-vault-test --vault-root "$(pwd)/vault-test" --assert
```

Wrapper: `make test-bootstrap`

## Implementation Tasks (Execution Order)

### Foundation (Start Here)

1. **[RESET_RUNTIME_STATE.md](RESET_RUNTIME_STATE.md)**
   Clean runtime state; no orphaned watcher artifacts.
   Prerequisite for all other tasks.

2. **[DOCUMENT_WORKFLOW_ALIGNMENT.md](DOCUMENT_WORKFLOW_ALIGNMENT.md)**
   Document the bootstrap path in workflow and testing docs.
   No dependencies; can start immediately.

### Sequence (Each Builds on Previous)

3. **[INITIALIZE_TEST_VAULT.md](INITIALIZE_TEST_VAULT.md)**
   Create test vault structure and seed UAT notes.
   Prerequisite: RESET_RUNTIME_STATE merged.

4. **[START_FULL_SYSTEM.md](START_FULL_SYSTEM.md)**
   Start full system (watcher, worker, API, status service) against test vault.
   Prerequisite: RESET_RUNTIME_STATE + INITIALIZE_TEST_VAULT merged.

5. **[VERIFY_RUNTIME_HEALTH.md](VERIFY_RUNTIME_HEALTH.md)**
   Verify deterministic health checks; all components ready.
   Prerequisite: START_FULL_SYSTEM merged.

6. **[RUN_SCRIPTED_UAT.md](RUN_SCRIPTED_UAT.md)**
   Run scripted UAT with idempotence assertions.
   Prerequisite: VERIFY_RUNTIME_HEALTH merged.

## Acceptance

The parent capability "Local test environment bootstrap stabilization" is accepted when:

- [ ] All 6 tasks are merged (code + docs changes).
- [ ] The canonical `make test-bootstrap` path runs end-to-end from a clean checkout.
- [ ] Each layer emits deterministic, operator-readable signals.
- [ ] The scripted UAT runs idempotently (second run produces no new promote events).
- [ ] Workflow and testing docs explicitly claim the path as supported.

When all conditions are met, create one owner-doc promotion PR to update `docs/STATUS.md` from "partially working" to "fully supported and verified."

## Quick Reference

| Task | What | Why | Done When |
| --- | --- | --- | --- |
| **Reset runtime state** | Clean slate, no orphaned artifacts | Foundation for repeatability | `make reset-zero-force` idempotent |
| **Initialize test vault** | Create vault structure + seed UAT | Explicit, documented bootstrapping | Vault structure correct, repeatable |
| **Start full system** | Boot all components | Deterministic startup | All processes start, reach stable state |
| **Verify runtime health** | Prove components work | Go/no-go signal before UAT | Health checks deterministic, pass |
| **Run scripted UAT** | Automated operator tests | Proof of intended behavior | Assertions pass, idempotence confirmed |
| **Document alignment** | Reflect in workflow docs | Operator knows path is supported | Docs name path as supported |

## Relationship to GitHub Issues

Each task specification may be tracked by one or more GitHub issues. The specification document is the source of truth for what needs to be done. Examples:

- One task might map to one issue: "Implement health check script"
- One task might map to multiple issues: "Reset → watcher pause cleanup" + "Reset → vault cleanup" (if implementation splits them)
- Multiple related tasks might share context in one epic issue

When creating GitHub issues:
1. Reference the task spec: "Implements LOCAL_TEST_BOOTSTRAP/INITIALIZE_TEST_VAULT"
2. Use the task's acceptance criteria as the issue acceptance criteria
3. Use the task's verification approach as the PR verification approach
4. Link related issues together

## Navigation

- **Parent capability plan:** `docs/plans/LOCAL_TEST_ENVIRONMENT_BOOTSTRAP.md`
- **Testing strategy:** `docs/TESTING.md :: Bootstrap As A Verification Contract`
- **Workflow model:** `docs/development/DEV_WORKFLOW.md :: Lightweight breakdown model`
- **Environment contracts:** `docs/ENVIRONMENTS.md`

---

**Status:** Specification complete. Ready for GitHub issue creation and implementation pickup.
