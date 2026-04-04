---
name: Run Scripted UAT
description: Scripted UAT with idempotence assertions; prove operator outcomes work
task_id: BOOTSTRAP-05
source_anchor: docs/plans/LOCAL_TEST_ENVIRONMENT_BOOTSTRAP.md :: Target Golden Path (step 6)
parent_capability: Local test environment bootstrap stabilization
prerequisites: [BOOTSTRAP-01, BOOTSTRAP-02, BOOTSTRAP-03, BOOTSTRAP-04]
depends_on: [VERIFY_RUNTIME_HEALTH.md]
can_parallelize_with: []
---

# Run Scripted UAT

## Purpose

Run automated operator-level tests that prove the system works for the intended use cases, and demonstrate idempotence (second run produces no unexpected changes).

## What This Task Does

When the operator runs:
```bash
VAULT_ROOT="$(pwd)/vault-test" python -m app.cli uat-run-vault-test --vault-root "$(pwd)/vault-test" --assert
```

The system should:

1. Run the watcher and panel agent against the seeded vault.
2. Assert that at least one `promote.intent.created` event is emitted.
3. Assert that at least one promotion is applied without errors.
4. Assert that policy-gated notes remain skipped (if policy is configured).
5. Assert that the seeded evergreen note reaches the expected maturity state.
6. Emit machine-readable assertion results (pass count, totals).
7. On a second run over the same snapshot:
   - Confirm no new `promote.intent.created` events are created (idempotence).
   - Confirm no unexpected panel side effects occur.
8. Emit a final idempotence signal (e.g., `IDEMPOTENT=true`).

## Concretely

```bash
# First run
VAULT_ROOT="$(pwd)/vault-test" python -m app.cli uat-run-vault-test --vault-root "$(pwd)/vault-test" --assert
# → [UAT] Running registry watcher against test vault...
# → [UAT] Watcher ticks: 3
# → [ASSERT] promote.intent.created: 2 events emitted ✓
# → [ASSERT] promotion.executed: 2 successful ✓
# → [ASSERT] policy-gated notes skipped: 1 ✓
# → [ASSERT] evergreen note maturity: promoted ✓
# → ASSERTIONS_PASSED=4/4
# → Exits 0

# Capture state (event count, maturity)
python -m app.cli status --json > /tmp/state1.json
PROMOTE_COUNT_1=$(jq '.promote.intent.created' /tmp/state1.json)

# Second run (idempotence check)
VAULT_ROOT="$(pwd)/vault-test" python -m app.cli uat-run-vault-test --vault-root "$(pwd)/vault-test" --assert
# → [UAT] Running registry watcher against test vault...
# → [UAT] Watcher ticks: 1  (fewer because already promoted)
# → [ASSERT] promote.intent.created: 0 new events ✓  (idempotence)
# → [ASSERT] promotion.executed: 0 new executions ✓
# → [ASSERT] evergreen note maturity: still promoted ✓
# → ASSERTIONS_PASSED=3/3
# → IDEMPOTENT=true
# → Exits 0

python -m app.cli status --json > /tmp/state2.json
PROMOTE_COUNT_2=$(jq '.promote.intent.created' /tmp/state2.json)
test "$PROMOTE_COUNT_1" -eq "$PROMOTE_COUNT_2"  # Counts unchanged
```

## Why This Matters

Automated assertions prove the system actually works for its intended purpose, not just starts cleanly. Idempotence proof shows the system is safe to run repeatedly without side effects.

## Acceptance Criteria

- [ ] UAT harness runs end-to-end without errors against the seeded vault.
- [ ] At least one `promote.intent.created` event is asserted and counted.
- [ ] At least one promotion is applied; no errors occur during application.
- [ ] Policy-gated notes remain skipped (if policy is configured).
- [ ] The seeded evergreen note reaches the expected maturity state.
- [ ] Assertion results are human-readable (e.g., `ASSERTIONS_PASSED=4/4`).
- [ ] Second run over the same snapshot produces no new promote events.
- [ ] Idempotence is explicitly confirmed in output (e.g., `IDEMPOTENT=true`).
- [ ] The script exits 0 when all assertions pass, non-zero if any fail.
- [ ] CI integration test confirms the harness works end-to-end.

## How to Verify (Pre-Merge)

**Local verification (after VERIFY_RUNTIME_HEALTH passes):**
```bash
# Run UAT
VAULT_ROOT="$(pwd)/vault-test" python -m app.cli uat-run-vault-test --vault-root "$(pwd)/vault-test" --assert > /tmp/uat1.log
UAT_EXIT=$?
test $UAT_EXIT -eq 0
grep "ASSERTIONS_PASSED" /tmp/uat1.log

# Capture event counts
python -m app.cli status --json > /tmp/state1.json
PROMOTE_COUNT_1=$(jq '.promote.intent.created' /tmp/state1.json)

# Run UAT again (idempotence check)
VAULT_ROOT="$(pwd)/vault-test" python -m app.cli uat-run-vault-test --vault-root "$(pwd)/vault-test" --assert > /tmp/uat2.log
UAT_EXIT=$?
test $UAT_EXIT -eq 0
grep "IDEMPOTENT=true" /tmp/uat2.log

# Verify counts unchanged
python -m app.cli status --json > /tmp/state2.json
PROMOTE_COUNT_2=$(jq '.promote.intent.created' /tmp/state2.json)
test "$PROMOTE_COUNT_1" -eq "$PROMOTE_COUNT_2"
```

**CI verification:**
```bash
make reset-zero-force
make test-vault-init
timeout 40 bash -c 'VAULT_ROOT="$(pwd)/vault-test" scripts/start_full_system.sh' &
sleep 15
VAULT_ROOT="$(pwd)/vault-test" bash scripts/verify_runtime_stack.sh
test $? -eq 0
VAULT_ROOT="$(pwd)/vault-test" python -m app.cli uat-run-vault-test --vault-root "$(pwd)/vault-test" --assert
test $? -eq 0
kill %1 2>/dev/null || true
```

## Out of Scope

- Fixing the watcher/panel/promotion logic itself.
- Implementing new UAT scenarios beyond the core operator path.
- Changing assertion thresholds or maturity expectations.

## Related Docs

- `docs/plans/LOCAL_TEST_ENVIRONMENT_BOOTSTRAP.md` (parent capability plan)
- `docs/TESTING.md :: Local test bootstrap contract :: UAT contract`
- `tests/quality_wave/test_uat_harness.py` (reference deterministic harness)

## Related GitHub Issues

When implementing, create GitHub issue(s) referencing this spec: "Implements LOCAL_TEST_BOOTSTRAP/RUN_SCRIPTED_UAT". Use the acceptance criteria above as the issue contract. Blocked by: VERIFY_RUNTIME_HEALTH.

---

**Status:** Specification ready. Blocked on VERIFY_RUNTIME_HEALTH.
