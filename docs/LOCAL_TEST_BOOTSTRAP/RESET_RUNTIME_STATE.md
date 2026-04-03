---
name: Reset Runtime State
description: Clean runtime state; remove orphaned watcher artifacts and caches
task_id: BOOTSTRAP-01
source_anchor: docs/plans/LOCAL_TEST_ENVIRONMENT_BOOTSTRAP.md :: Target Golden Path (step 1)
parent_capability: Local test environment bootstrap stabilization
prerequisites: none
depends_on: []
can_parallelize_with: [DOCUMENT_WORKFLOW_ALIGNMENT]
---

# Reset Runtime State

## Purpose

Establish a clean, known-good runtime state by removing all artifacts from previous runs. This is the foundation for all subsequent implementation tasks.

## What This Task Does

When the operator runs `make reset-zero-force` (or equivalent), the system should:

1. Remove test vault directory (`vault-test/` or equivalent).
2. Remove watcher pause/state files that could affect the next run.
3. Remove local caches, temporary files, or lock files that could interfere.
4. Emit a clear success message.
5. Leave the reset idempotent: running it twice produces identical clean state.

## Concretely

```bash
make reset-zero-force
# → Removes vault-test/
# → Removes .watcher_pause, state.json, or similar
# → Removes /tmp or cache artifacts
# → Exits 0 with "✓ Runtime state reset successfully"

make reset-zero-force  # Run again
# → Same clean state; no errors
```

## Why This Matters

If watcher pause files or stale state remain after reset, the next startup will appear to succeed while the watcher is silently paused. This creates a false-positive bootstrap experience. Reset must be **thorough and provable**.

## Acceptance Criteria

- [ ] `make reset-zero-force` removes all expected artifacts:
  - test vault directory
  - watcher pause files (`.pause`, state.json, etc.)
  - local caches or lock files
- [ ] Running the command twice produces identical output and state.
- [ ] The command exits 0 on success, non-zero on failure.
- [ ] The command emits a clear human-readable success or failure message.
- [ ] The command completes in under 5 seconds.
- [ ] CI integration test confirms reset works in a clean checkout.

## How to Verify (Pre-Merge)

**Local verification:**
```bash
# First run
make reset-zero-force
ls -la vault-test 2>&1 | grep -i "no such file"  # Should pass
[ ! -f .watcher_pause ] && echo "✓ pause file cleared"

# Second run (idempotence check)
make reset-zero-force
# Same output both times
```

**CI verification:**
```bash
make reset-zero-force
ls vault-test 2>&1 | grep -i "no such file"
test ! -f .watcher_pause
```

## Out of Scope

- Fixing the broader Makefile structure.
- Implementing new environment models.
- Changing the vault format or note structure.

## Related Docs

- `docs/plans/LOCAL_TEST_ENVIRONMENT_BOOTSTRAP.md` (parent capability plan)
- `docs/TESTING.md :: Local test bootstrap contract`
- `Makefile` (implementation)

## Related GitHub Issues

When implementing, create GitHub issue(s) referencing this spec: "Implements LOCAL_TEST_BOOTSTRAP/RESET_RUNTIME_STATE". Use the acceptance criteria above as the issue contract.

---

**Status:** Specification ready. No blockers.
