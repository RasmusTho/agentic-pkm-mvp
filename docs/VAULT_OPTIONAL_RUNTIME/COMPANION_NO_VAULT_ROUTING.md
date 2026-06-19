---
name: Companion No-Vault Routing
description: The companion boundary returns vault_selection_required for the unset / no-vault case, and open/switch/register-multiple is verified end-to-end.
task_id: VAULT_OPTIONAL_RUNTIME-03
source_anchor: docs/VAULT_OPTIONAL_RUNTIME/README.md :: Capability boundary
parent_capability: Vault Optional at Runtime
prerequisites: [VAULT_OPTIONAL_RUNTIME-01]
depends_on: [RESOLVE_NO_VAULT_STATE.md]
can_parallelize_with: [BOOT_RUNTIME_WITHOUT_VAULT.md]
---

# Companion No-Vault Routing

## Purpose
The companion already routes a *set-but-missing* vault to the open-vault picker state (#1757).
This task closes the **unset / no-vault** gap so the picker also appears when no vault has ever
been bound, and verifies open / switch / register-multiple end-to-end against the existing
`VaultManager` registry — the foundation is built (`/api/companion/vault/{context,select,initialize}`,
`vault_selection_required`, `known_vaults`, `load_last_active`); this task closes gaps, it does
not rebuild.

## What This Task Does
- `app/api/routes/companion.py` returns the `vault_selection_required` state for the
  **no-vault** case (the optional resolver from task 1 returns no vault), not only when it
  catches `VaultRootMisconfiguredError`. The existing `_vault_selection_required_response`
  (offering `/vault/select` and `/vault/initialize`) is reused.
- The recent list (payload field `recent_vaults`, fed from the `known_vaults` registry) is
  surfaced in the selection-required payload so the picker can show registered vaults to switch between.
- End-to-end verification: select vault A, then switch to vault B (both registered in
  `known_vaults`), confirming in-process re-resolution and persisted last-active (#1895). Any
  gap found (e.g. an explicit "register/forget vault" affordance) is closed minimally here.

## Concretely
```bash
# No vault bound -> picker state (200), not 500, not an empty ./vault note list.
curl -fsS http://127.0.0.1:18000/api/companion/vault/context
# {"state":"vault_selection_required", "recent_vaults":[...], "actions":[{"endpoint":"/api/companion/vault/select"},...]}

# Open vault A, then switch to vault B; last-active persists across re-resolution.
curl -fsS -X POST .../vault/select -d '{"path":"/vaults/A"}'
curl -fsS -X POST .../vault/select -d '{"path":"/vaults/B"}'   # switch; A and B both in known_vaults
```

## Why This Matters
Without the unset-case routing, a fresh install (no vault ever bound) would hit the
relative-`./vault` footgun or a 500 instead of the picker — the human has no recovery path.
Switching/registering is the multi-vault half of the owner decision.

## Acceptance Criteria
- [ ] With no vault bound, `/api/companion/vault/context` returns `vault_selection_required` (200), not 500 and not an empty default-vault note list. Verify: `tests/api/test_companion_vault_routing.py::test_no_vault_returns_selection_required`
- [ ] The selection-required payload includes the `recent_vaults` list (from the `known_vaults` registry) for switching. Verify: `tests/api/test_companion_vault_routing.py::test_selection_required_lists_known_vaults`
- [ ] Selecting a vault re-resolves in-process and subsequent reads render full note bodies (no restart). Verify: `tests/api/test_companion_vault_routing.py::test_select_vault_reresolves_in_process`
- [ ] Switching between two registered vaults persists the last-active pointer. Verify: `tests/api/test_companion_vault_routing.py::test_switch_between_known_vaults_persists_last_active`

## How to Verify (Pre-Merge)
```bash
pytest -q tests/api/test_companion_vault_routing.py
```
CI: companion API tests run in-process (`TestClient(app)`, `STORE_BACKEND=memory`), no Docker —
same shape as `tests/uat/test_golden_path_integrated_runtime.py`.

## Out of Scope
- Picker **UI rendering** (#1867 / companion-ui).
- Runtime watcher boot (task 2).
- Config resolver (task 1, prerequisite).

## Related Docs
- Parent: `docs/VAULT_OPTIONAL_RUNTIME/README.md`
- `app/api/routes/companion.py :: _vault_selection_required_response`, `/vault/context`, `/vault/select`, `/vault/initialize`, `known_vaults`
- `app/vault/manager.py :: select_vault`, `load_last_active`, `known_vaults`
- #1757 (set-but-missing seam), #1867 (picker UI), #1895 (last-active)

## Related GitHub Issues
One bounded issue. Implements VAULT_OPTIONAL_RUNTIME/COMPANION_NO_VAULT_ROUTING. Blocked on
task 1 (`agent:blocked`); parallelizable with task 2.
