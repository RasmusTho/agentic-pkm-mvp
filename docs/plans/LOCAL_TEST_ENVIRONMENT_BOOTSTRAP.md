State: Local test bootstrap plan with steps 1-5 shipped; deterministic runtime verification is delivered and remains part of the supported local verification lane. Automated latency harness available for multi-device sync validation, with bounded timeout and provider-free rule-mode default for operator runs.
Doc role: Plan
Authority: Canonical plan for the scripted local test bootstrap chain; step specs and current-state SoT docs win on implementation detail and shipped runtime claims.
Owner: Runtime / local test bootstrap stabilization
Temporal class: strategic
Review cadence: event-driven
Source of truth: mixed
Last reviewed: 2026-04-19
Last verified against: docs/TESTING.md, docs/ENVIRONMENTS.md, Makefile, scripts/start_full_system.sh, scripts/verify_runtime_stack.sh, app/cli/uat.py, app/cli/latency_harness.py, tests/cli/test_latency_harness.py, merged PRs #340/#346/#348/#349/#365/#367/#376/#386, GitHub Issues #334/#357/#358/#385, current repo state at 89525d7 on 2026-04-19

# Local Test Environment Bootstrap

**Purpose:** Canonical plan for the scripted bootstrap chain that brings up a deterministic local test environment suitable for UAT and CI system-level validation.

**Status:** Steps 1-5 shipped. Step 4 was delivered by issue #334 / PR #365 and remains the supported runtime verification check.

---

## Target Golden Path

The full bootstrap sequence, in order:

| Step | Make Target | Governing Spec | Issue | Status |
|------|-------------|----------------|-------|--------|
| 1 | `make reset-zero-force` | `docs/LOCAL_TEST_BOOTSTRAP/RESET_RUNTIME_STATE.md :: BOOTSTRAP-01` | #331 | Shipped |
| 2 | `make test-vault-init` | `docs/LOCAL_TEST_BOOTSTRAP/INITIALIZE_TEST_VAULT.md :: BOOTSTRAP-02` | #332 | Shipped |
| 3 | `make start-test-system` | `docs/LOCAL_TEST_BOOTSTRAP/START_FULL_SYSTEM.md :: BOOTSTRAP-03` | #333 | Shipped |
| 4 | `make verify-runtime` | `docs/LOCAL_TEST_BOOTSTRAP/VERIFY_RUNTIME_HEALTH.md :: BOOTSTRAP-04` | #334 | Shipped |
| 5 | `uat-run-vault-test --assert` | `docs/LOCAL_TEST_BOOTSTRAP/RUN_SCRIPTED_UAT.md :: BOOTSTRAP-05` | #335 | Shipped |

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
- The full path is the supported local verification lane; further bootstrap hardening should stay bounded to explicit follow-up slices.

---

## Governing Docs

- `docs/TESTING.md` — test pyramid, UAT contract, CI roles.
- `docs/ENVIRONMENTS.md` — vault/runtime path model, environment scoping.
- `docs/LOCAL_TEST_BOOTSTRAP/` — per-step spec anchors (BOOTSTRAP-01 through BOOTSTRAP-05).
