---
name: Verify Runtime Health
description: Deterministic health checks; prove all components are actually working
task_id: BOOTSTRAP-04
source_anchor: docs/plans/LOCAL_TEST_ENVIRONMENT_BOOTSTRAP.md :: Target Golden Path (step 5)
parent_capability: Local test environment bootstrap stabilization
prerequisites: [BOOTSTRAP-01, BOOTSTRAP-02, BOOTSTRAP-03]
depends_on: [START_FULL_SYSTEM.md]
can_parallelize_with: []
---

State: BOOTSTRAP-04 remains ready/open; deterministic runtime verification is the active bootstrap stabilization slice.

# Verify Runtime Health

## Purpose

Run deterministic health checks that prove the startup was successful and all components are actually working, not just started.

## What This Task Does

When the operator runs:
```bash
VAULT_ROOT="$(pwd)/vault-test" bash scripts/verify_runtime_stack.sh
```

The system should:

1. Check that the watcher process is running and its heartbeat is fresh.
2. Check that the worker process is running and accepting tasks.
3. Check that the API is responding to `/api/health` and `/api/status`.
4. Check that the store is accessible and seeded correctly.
5. Emit pass/fail signals for each check.
6. Provide machine-readable output for CI integration.
7. Exit 0 if all checks pass, non-zero if any fail.
8. Fail loudly and clearly if any check fails (do not continue silently).

## Concretely

```bash
VAULT_ROOT="$(pwd)/vault-test" bash scripts/verify_runtime_stack.sh
# → Checking watcher process... ✓ Running (heartbeat age: 2s)
# → Checking worker process... ✓ Running
# → Checking API health... ✓ OK (response time: 45ms)
# → Checking store access... ✓ Store initialized
# → WATCHER_READY=true
# → WORKER_READY=true
# → API_READY=true
# → STORE_READY=true
# → All checks passed
# → Exits 0

# If something is broken:
VAULT_ROOT="$(pwd)/vault-test" bash scripts/verify_runtime_stack.sh
# → Checking watcher process... ✗ Not running
# → WATCHER_READY=false
# → Error: Watcher process not found
# → Exits 1
```

## Why This Matters

"The stack is running" does not mean "the stack is working." A process can start without being healthy. Deterministic health checks give operators **clear go/no-go signals** before proceeding to UAT.

## Acceptance Criteria

- [ ] `verify_runtime_stack.sh` checks all four components: watcher, worker, API, store.
- [ ] Each check emits a clear pass (✓) or fail (✗) message.
- [ ] Machine-readable output includes flags like `WATCHER_READY=true/false`.
- [ ] The script exits 0 if all checks pass, non-zero if any fail.
- [ ] The script provides a clear error message if a check fails (no silent failures).
- [ ] Running the script multiple times produces identical output (idempotent).
- [ ] The script completes within 20 seconds.
- [ ] CI integration test confirms the script works in a clean checkout.

## How to Verify (Pre-Merge)

**Local verification (after START_FULL_SYSTEM startup):**
```bash
# Keep system running
VAULT_ROOT="$(pwd)/vault-test" bash scripts/verify_runtime_stack.sh

# Check output
echo $?  # Should be 0
grep -i "WATCHER_READY=true" output.txt
grep -i "WORKER_READY=true" output.txt
grep -i "API_READY=true" output.txt
grep -i "STORE_READY=true" output.txt

# Run again (idempotence check)
VAULT_ROOT="$(pwd)/vault-test" bash scripts/verify_runtime_stack.sh
# Same output both times

# Kill a component and rerun
killall watcher  # Simulate failure
VAULT_ROOT="$(pwd)/vault-test" bash scripts/verify_runtime_stack.sh
echo $?  # Should be 1
grep -i "WATCHER_READY=false" output.txt
```

**CI verification:**
```bash
make reset-zero-force
make test-vault-init
timeout 40 bash -c 'VAULT_ROOT="$(pwd)/vault-test" scripts/start_full_system.sh' &
sleep 15
VAULT_ROOT="$(pwd)/vault-test" bash scripts/verify_runtime_stack.sh
test $? -eq 0
kill %1 2>/dev/null || true
```

## Out of Scope

- Fixing the underlying watcher/worker/API issues.
- Implementing new health checks beyond the core stack.
- Changing the health check thresholds or timing.

## Related Docs

- `docs/plans/LOCAL_TEST_ENVIRONMENT_BOOTSTRAP.md` (parent capability plan)
- `docs/TESTING.md :: System / bootstrap testing`
- `docs/STATUS.md :: Health spine` (health/readiness signals)
- `scripts/verify_runtime_stack.sh` (implementation)

## Related GitHub Issues

When implementing, create GitHub issue(s) referencing this spec: "Implements LOCAL_TEST_BOOTSTRAP/VERIFY_RUNTIME_HEALTH". Use the acceptance criteria above as the issue contract. Blocked by: START_FULL_SYSTEM.

---

**Status:** Specification ready. Blocked on START_FULL_SYSTEM.
