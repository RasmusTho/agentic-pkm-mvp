---
name: Initialize Test Vault
description: Create test vault with correct structure and seeded UAT notes
task_id: BOOTSTRAP-02
source_anchor: docs/plans/LOCAL_TEST_ENVIRONMENT_BOOTSTRAP.md :: Target Golden Path (step 2)
parent_capability: Local test environment bootstrap stabilization
prerequisites: [BOOTSTRAP-01]
depends_on: [RESET_RUNTIME_STATE.md]
can_parallelize_with: []
---

# Initialize Test Vault

## Purpose

Create a clean test vault with the correct directory structure and seeded UAT notes, without requiring undocumented folder hints or magical assumptions.

## What This Task Does

When the operator runs `make test-vault-init` (or equivalent), the system should:

1. Create `vault-test/` directory (or clear it if it exists).
2. Create required top-level folders: `System/Config`, `Test`, and any other documented folders.
3. Create `System/Config/` files needed for bootstrap (e.g., panel-action-wiring.yaml if required).
4. Seed the UAT notes into `Test/` folder.
5. Verify the vault structure matches expected layout.
6. Emit clear success/failure signals.
7. Ensure running twice produces identical vault structure.

## Concretely

```bash
make test-vault-init
# → Creates vault-test/System/Config/
# → Creates vault-test/Test/
# → Seeds UAT notes into vault-test/Test/
# → Exits 0 with "✓ Test vault initialized"

ls vault-test/System/Config/
# → Shows config files (panel-action-wiring.yaml, etc.)

ls vault-test/Test/
# → Shows seeded UAT notes

make test-vault-init  # Run again
# → Identical structure both times
```

## Why This Matters

If the vault structure relies on undocumented folder hints (e.g., "the system detects the Test folder and automatically enables UAT"), bootstrap is fragile. The seeding must be **explicit, documented, and reproducible**.

## Acceptance Criteria

- [ ] `make test-vault-init` creates `vault-test/System/Config/` with required files.
- [ ] `vault-test/Test/` is created and seeded with UAT notes.
- [ ] The vault structure matches documented expectations (see `docs/ENVIRONMENTS.md`).
- [ ] No undocumented folder magic or hidden assumptions are required.
- [ ] Running the command twice produces identical vault structure (idempotent).
- [ ] The command exits 0 on success, non-zero on failure.
- [ ] The command emits clear success/failure messages.
- [ ] CI integration test confirms vault init works in a clean checkout.

## How to Verify (Pre-Merge)

**Local verification:**
```bash
# First run
make test-vault-init
find vault-test -type f | sort > /tmp/vault1.txt
find vault-test -type d | sort > /tmp/dirs1.txt

# Second run (idempotence check)
rm -rf vault-test
make test-vault-init
find vault-test -type f | sort > /tmp/vault2.txt
find vault-test -type d | sort > /tmp/dirs2.txt

diff /tmp/vault1.txt /tmp/vault2.txt
diff /tmp/dirs1.txt /tmp/dirs2.txt
# Should show no differences
```

**CI verification:**
```bash
make test-vault-init
test -d vault-test/System/Config
test -d vault-test/Test
ls vault-test/Test/*.md | grep -i uat
```

## Out of Scope

- Changing the vault schema or note format.
- Fixing broader vault layout issues.
- Implementing vault storage backends.

## Related Docs

- `docs/plans/LOCAL_TEST_ENVIRONMENT_BOOTSTRAP.md` (parent capability plan)
- `docs/ENVIRONMENTS.md` (vault structure contract)
- `docs/TESTING.md :: Local test bootstrap contract`
- `scripts/` or `app/cli/` vault initialization code

## Related GitHub Issues

When implementing, create GitHub issue(s) referencing this spec: "Implements LOCAL_TEST_BOOTSTRAP/INITIALIZE_TEST_VAULT". Use the acceptance criteria above as the issue contract. Blocked by: RESET_RUNTIME_STATE.

---

**Status:** Specification ready. Blocked on RESET_RUNTIME_STATE.
