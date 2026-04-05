---
name: Start Full System
description: Start full system (watcher, worker, API, status) against test vault
task_id: BOOTSTRAP-03
source_anchor: docs/plans/LOCAL_TEST_ENVIRONMENT_BOOTSTRAP.md :: Target Golden Path (step 4)
parent_capability: Local test environment bootstrap stabilization
prerequisites: [BOOTSTRAP-01, BOOTSTRAP-02]
depends_on: [INITIALIZE_TEST_VAULT.md]
can_parallelize_with: []
---

# Start Full System

## Purpose

Boot the entire local runtime (watcher, worker, API, status service) pointing at the test vault, and reach a stable, ready state within a defined timeout.

## What This Task Does

When the operator runs:
```bash
VAULT_ROOT="$(pwd)/vault-test" scripts/start_full_system.sh
```

The system should:

1. Start the watcher process against the test vault.
2. Start the worker process (if separate).
3. Start the API server (if separate).
4. Start the status service (if separate).
5. All components initialize cleanly without critical errors.
6. The system reaches a stable state (no thrashing, all processes settled).
7. Emit startup logs that an operator can read and understand.
8. Complete within 30 seconds.

## Concretely

```bash
VAULT_ROOT="$(pwd)/vault-test" scripts/start_full_system.sh
# → [INFO] Watcher starting...
# → [INFO] Worker starting...
# → [INFO] API listening on localhost:8000
# → [INFO] Status service ready
# → System stable after 15 seconds

ps aux | grep -E 'watcher|worker|api'
# → All processes visible

curl http://localhost:8000/api/health
# → {"status": "ok"}
```

## Why This Matters

If startup hangs, fails silently, or leaves components in an undefined state, the bootstrap path is not reproducible. Operators need **deterministic startup behavior** with clear signal of readiness.

## Acceptance Criteria

- [ ] `scripts/start_full_system.sh` accepts `VAULT_ROOT` environment variable.
- [ ] All required components start cleanly:
  - [ ] Watcher process is running.
  - [ ] Worker process is running (if separate).
  - [ ] API server is listening (if separate).
  - [ ] Status service is ready (if separate).
- [ ] No critical errors are emitted during startup.
- [ ] The system reaches a stable state within 30 seconds.
- [ ] Startup logs are human-readable and show component readiness.
- [ ] Restarting the stack produces the same startup logs (idempotent).
- [ ] CI integration test confirms startup works in a clean checkout.

## How to Verify (Pre-Merge)

**Local verification:**
```bash
# Clean state
make reset-zero-force
make test-vault-init

# Start system
timeout 40 bash -c 'VAULT_ROOT="$(pwd)/vault-test" scripts/start_full_system.sh' &
STARTUP_PID=$!

# Wait for stability
sleep 15

# Check processes
ps -p $STARTUP_PID
ps aux | grep -E 'watcher|worker|api' | grep -v grep

# Cleanup
kill $STARTUP_PID 2>/dev/null || true
```

**CI verification:**
```bash
make reset-zero-force
make test-vault-init
timeout 40 bash -c 'VAULT_ROOT="$(pwd)/vault-test" scripts/start_full_system.sh' &
STARTUP_PID=$!
sleep 15
ps -p $STARTUP_PID  # Should still be running
kill $STARTUP_PID
```

## Out of Scope

- Fixing the underlying watcher/worker/API logic.
- Implementing new components.
- Optimizing startup performance (just needs to be < 30s).

## Related Docs

- `docs/plans/LOCAL_TEST_ENVIRONMENT_BOOTSTRAP.md` (parent capability plan)
- `docs/TESTING.md :: System / bootstrap testing`
- `scripts/start_full_system.sh` (implementation)

## Related GitHub Issues

When implementing, create GitHub issue(s) referencing this spec: "Implements LOCAL_TEST_BOOTSTRAP/START_FULL_SYSTEM". Use the acceptance criteria above as the issue contract. Blocked by: INITIALIZE_TEST_VAULT.

---

**Status:** Shipped. `make start-test-system` delivered by #333. CI contract: `tests/quality_wave/test_bootstrap_start.py`.
