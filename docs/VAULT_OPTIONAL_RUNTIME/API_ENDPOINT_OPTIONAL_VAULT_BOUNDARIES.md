---
name: API Endpoint Optional Vault Boundaries
description: Request-path API endpoints stop using eager vault resolution and return picker or empty no-vault responses instead of falling back to ./vault.
task_id: VAULT_OPTIONAL_RUNTIME-05A
source_anchor: docs/VAULT_OPTIONAL_RUNTIME/README.md :: Follow-up eager resolver migration
parent_capability: Vault Optional at Runtime
prerequisites: [RESOLVE_NO_VAULT_STATE.md, COMPANION_NO_VAULT_ROUTING.md]
depends_on: []
can_parallelize_with: [BACKGROUND_OPTIONAL_VAULT_IDLE.md, PROMOTION_CLI_AGENT_OPTIONAL_VAULT_RESOLUTION.md]
---

# API Endpoint Optional Vault Boundaries

## Purpose
The Option-2 vault-selection cutover made a selected vault the only active vault at startup.
Request-path endpoints must therefore stop calling the legacy eager `resolve_vault_root()`
path that can silently resolve to CWD-relative `./vault`. If no vault is selected, API
boundaries must return the picker state or an intentionally empty read response, never an
empty wrong vault and never a generic 500.

This is Slice A of #2311. It is the first implementation slice because it protects the
human-facing request paths while keeping background workers and CLI/import-time consumers
out of the same PR.

## What This Task Does
- Migrates the remaining request-path eager resolver sites in:
  - `app/api/routes/capture.py`
  - `app/api/routes/artifacts.py`
  - `app/api/routes/canvas.py`
  - `app/api/routes/debug.py`
  - `app/api/routes/companion.py` companion request helpers still found by pickup audit
    (`/now` is already optional on current main and should be verified, not reworked).
- Uses `resolve_optional_vault_root()` plus an explicit no-vault branch:
  - write/action endpoints return the existing `vault_selection_required` picker shape
    or an equivalent explicit no-vault response already accepted by their caller;
  - read-only companion glance surfaces that have an established empty-state contract
    return an empty list/object, not a fallback vault.
- Keeps set-but-missing vaults explicit. They must not turn into CWD fallback and must not
  hide as successful reads from `./vault`.
- Leaves background workers, settings, promotion queue, CLI, and agent-memory helpers to
  Slices B and C.

## Concretely
```python
# No selected vault, VAULT_ROOT unset.
response = client.get("/api/artifacts/note", params={"note_path": "Daily.md"})
assert response.status_code == 200
assert response.json()["state"] == "vault_selection_required"

# /api/companion/now keeps the existing quiet read contract.
assert client.get("/api/companion/now").json() == []

# A selected vault still resolves exactly as before.
get_vault_manager().select_vault(vault_root)
assert client.get("/api/artifacts/note", params={"note_path": "Daily.md"}).status_code == 200
```

## Why This Matters
These endpoints are human-facing paths. A silent `./vault` fallback here makes the UI appear
empty or wrong after startup, which is the failure mode the Option-2 cutover was designed to
remove. This slice makes the request boundary honest without taking on unrelated worker or
CLI behavior.

## Acceptance Criteria
- [ ] With no selected vault and unset `VAULT_ROOT`, capture/artifacts/canvas/debug request
      paths never resolve CWD-relative `./vault`; they return an explicit no-vault/picker
      response. Verify: `tests/api/test_no_silent_cwd_vault_fallback.py::test_api_request_endpoints_do_not_resolve_cwd_vault_without_selection`
- [ ] The same endpoints preserve selected-vault behavior. Verify: `tests/api/test_no_silent_cwd_vault_fallback.py::test_api_request_endpoints_preserve_selected_vault_behavior`
- [ ] `/api/companion/now` remains quiet and identity-accurate with no selected vault
      (`[]`, not `./vault`, not 500). Verify: `tests/api/test_companion_no_vault_routing.py::test_now_without_selected_vault_returns_empty_not_fallback`
- [ ] Any remaining companion request helper that still calls `resolve_vault_root()` after
      pickup audit is migrated or explicitly ruled out of request scope in the PR body.
      Verify: `tests/api/test_no_silent_cwd_vault_fallback.py::test_companion_request_helpers_do_not_fallback_to_cwd_vault`

## How to Verify (Pre-Merge)
```bash
pytest -q \
  tests/api/test_no_silent_cwd_vault_fallback.py \
  tests/api/test_companion_no_vault_routing.py
ruff check app tests
RUN_INTEGRATED_RUNTIME_UAT=1 pytest -q tests/uat/
```

The IR-v1 UAT is required because this slice touches active-vault request boundaries and
hot-path companion behavior.

## Out of Scope
- Background worker idle behavior (Slice B).
- Promotion queue import-time resolver removal, CLI policy, and agent-memory helpers
  (Slice C).
- Picker UI rendering changes.

## Related Docs
- Parent: `docs/VAULT_OPTIONAL_RUNTIME/README.md`
- `docs/VAULT_OPTIONAL_RUNTIME/RESOLVE_NO_VAULT_STATE.md`
- `docs/VAULT_OPTIONAL_RUNTIME/COMPANION_NO_VAULT_ROUTING.md`
- #2311 (parent migration hub)

## Related GitHub Issues
One bounded child issue to be filed from this task after the spec lands on main. It should be
the first #2311 child moved to `agent:ready`.
