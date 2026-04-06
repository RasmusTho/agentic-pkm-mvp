# Local Test Environment Bootstrap

**Purpose:** Canonical plan for the scripted bootstrap chain that brings up a deterministic local test environment suitable for UAT and CI system-level validation.

**Status:** Steps 1–2 shipped. Steps 3–5 tracked by open issues.

---

## Target Golden Path

The full bootstrap sequence, in order:

| Step | Make Target | Governing Spec | Issue | Status |
|------|-------------|----------------|-------|--------|
| 1 | `make reset-zero-force` | `docs/LOCAL_TEST_BOOTSTRAP/RESET_RUNTIME_STATE.md :: BOOTSTRAP-01` | #331 | Shipped |
| 2 | `make test-vault-init` | `docs/LOCAL_TEST_BOOTSTRAP/INITIALIZE_TEST_VAULT.md :: BOOTSTRAP-02` | #332 | Shipped |
| 3 | `make start-test-system` | `docs/LOCAL_TEST_BOOTSTRAP/START_FULL_SYSTEM.md :: BOOTSTRAP-03` | #333 | Shipped |
| 4 | `make verify-runtime` | `docs/LOCAL_TEST_BOOTSTRAP/VERIFY_RUNTIME_HEALTH.md :: BOOTSTRAP-04` | #334 | Ready |
| 5 | `uat-run-vault-test --assert` | `docs/LOCAL_TEST_BOOTSTRAP/RUN_SCRIPTED_UAT.md :: BOOTSTRAP-05` | #335 | Ready |

### Full bootstrap (operator)

```bash
make reset-zero-force      # BOOTSTRAP-01: wipe all prior runtime artifacts
make test-vault-init       # BOOTSTRAP-02: create vault-test/ with UAT notes
make start-test-system     # BOOTSTRAP-03: bring up full system against vault-test
make verify-runtime        # BOOTSTRAP-04: confirm all components healthy
python -m app.cli uat-run-vault-test --assert  # BOOTSTRAP-05: run UAT, assert pass
```

---

## Constraints

- Each step must be idempotent.
- Each step must exit 0 on success, non-zero on failure, with a human-readable summary.
- The chain must work in a clean checkout without undocumented side-channel files.
- Steps 3–5 require Docker (steps 1–2 do not).

---

## Governing Docs

- `docs/TESTING.md` — test pyramid, UAT contract, CI roles.
- `docs/ENVIRONMENTS.md` — vault/runtime path model, environment scoping.
- `docs/LOCAL_TEST_BOOTSTRAP/` — per-step spec anchors (BOOTSTRAP-01 through BOOTSTRAP-05).
