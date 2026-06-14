---
name: Boot Runtime Without a Vault
description: The watcher and start_full_system boot and idle with no vault bound; the #1991 fail-exit precondition flips to idle-until-opened.
task_id: VAULT_OPTIONAL_RUNTIME-02
source_anchor: docs/VAULT_OPTIONAL_RUNTIME/README.md :: Capability boundary
parent_capability: Vault Optional at Runtime
prerequisites: [VAULT_OPTIONAL_RUNTIME-01]
depends_on: [RESOLVE_NO_VAULT_STATE.md]
can_parallelize_with: [COMPANION_NO_VAULT_ROUTING.md]
---

# Boot Runtime Without a Vault

## Purpose
The runtime stack must start with no vault bound and idle until one is opened — not fail-exit.
This flips the #1991 hard precondition (added when vault-init became mandatory) into an
idle-until-opened posture, the symmetric reverse of an invariant.

## What This Task Does
- **Watcher idles instead of raising** when no vault is bound or the vault is `uninitialized`:
  `app/watcher/config.py:61` and `app/watcher/registry.py:692` currently raise; they move to an
  idle/skip posture mirroring the existing precedent at
  `app/watcher/relevance_tick.py:54` ("Never raises for a not-selected vault — it skips").
  The `FileNotFoundError` paths (`registry.py:59`, `registry.py:1099`) likewise resolve to
  idle when there is simply no vault (distinct from a *set-but-missing* misconfig, which stays
  loud).
- **`scripts/start_full_system.sh` boots with no vault**: the `VAULT_ROOT` requirement
  (currently exit 2 at the unset check) becomes a no-vault idle bring-up; the watcher comes up
  idle and the API serves the picker state.
- **F4 symmetric producer/preflight update (issue #1997 rule, in reverse):** every producer
  and preflight that encodes "a vault is required" is updated in the **same change** — the
  watcher startup gate, `start_full_system.sh`, and any vault-init precondition doc. The
  *test-channel* preflight (`app/ops/channel_preflight.py`) deliberately keeps requiring a
  vault (the test channel provisions one); this task must NOT relax it.

## Concretely
```bash
# No vault bound: the stack comes up, the watcher idles, nothing crashes.
unset VAULT_ROOT
START_MODE=runtime scripts/start_full_system.sh     # no exit 2; watcher idle
curl -fsS http://127.0.0.1:18000/healthz            # {"ok": true}
# Watcher heartbeat shows an idle / no-vault status rather than a fail-exit.
```

## Why This Matters
If the watcher fail-exits with no vault, the product cannot start without a vault — directly
contradicting the owner decision. A half-applied flip (e.g. resolver returns no-vault but the
watcher still raises) is the mirror image of the #1991 outage and exactly what the F4 rule
exists to prevent.

## Acceptance Criteria
- [ ] With no vault bound, the watcher config/registry build an idle (not-selected) runtime instead of raising. Verify: `tests/watcher/test_watcher_idle_without_vault.py::test_watcher_idles_when_no_vault`
- [ ] An `uninitialized` vault no longer fail-exits the watcher; it idles until initialized/opened. Verify: `tests/watcher/test_watcher_idle_without_vault.py::test_uninitialized_vault_idles_not_exits`
- [ ] A *set-but-missing* `VAULT_ROOT` still fails loud (no regression). Verify: `tests/watcher/test_watcher_idle_without_vault.py::test_set_but_missing_still_fails_loud`
- [ ] `start_full_system.sh` boots with `VAULT_ROOT` unset (no exit 2) into a no-vault idle posture. Verify: `tests/runtime/test_start_full_system_no_vault.py::test_boots_idle_without_vault_root`
- [ ] The test-channel preflight still requires a vault (the flip is product-only). Verify: `tests/ops/test_channel_preflight.py::test_rejects_inconsistent_channel_config` (unchanged, still green)
- [ ] No remaining producer asserts a vault is mandatory at boot. Verify: grep/audit recorded in the PR body + the above tests.

## How to Verify (Pre-Merge)
```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q \
  tests/watcher/test_watcher_idle_without_vault.py \
  tests/runtime/test_start_full_system_no_vault.py \
  tests/ops/test_channel_preflight.py
```
CI: add these to the runtime/watcher unit jobs; the start_full_system test uses the
fake-docker pattern from `tests/uat/test_negative_safety_integrated_runtime.py::test_missing_vault_fails_loud`.

## Out of Scope
- The config resolver itself (task 1, prerequisite).
- Companion routing / picker (task 3, parallel).
- Relaxing the test-channel preflight (intentionally kept strict).

## Related Docs
- Parent: `docs/VAULT_OPTIONAL_RUNTIME/README.md`
- `app/watcher/config.py:61`, `app/watcher/registry.py:692`/`:59`/`:1099`, `app/watcher/relevance_tick.py:54`
- `scripts/start_full_system.sh` (VAULT_ROOT requirement)
- #1991 (precondition being flipped), #1997 F4 (invariant→producers rule)

## Related GitHub Issues
One bounded issue (may split watcher-idle and start_full_system if either grows). Implements
VAULT_OPTIONAL_RUNTIME/BOOT_RUNTIME_WITHOUT_VAULT. Blocked on task 1 (`agent:blocked`).
