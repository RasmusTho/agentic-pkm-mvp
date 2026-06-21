---
name: Background Optional Vault Idle
description: Background workers and settings readers idle honestly when no vault is selected instead of resolving ./vault.
task_id: VAULT_OPTIONAL_RUNTIME-05B
source_anchor: docs/VAULT_OPTIONAL_RUNTIME/README.md :: Follow-up eager resolver migration
parent_capability: Vault Optional at Runtime
prerequisites: [RESOLVE_NO_VAULT_STATE.md, BOOT_RUNTIME_WITHOUT_VAULT.md]
depends_on: [API_ENDPOINT_OPTIONAL_VAULT_BOUNDARIES.md]
can_parallelize_with: []
---

# Background Optional Vault Idle

## Purpose
Background producers must match the runtime decision: when no vault is selected, they idle
or report no-vault state. They must not resurrect the legacy `./vault` fallback just because
they are outside a request path.

This is Slice B of #2311. It is separate from the API slice because worker/settings behavior
has a different user contract: no picker response, but a clear no-op or no-vault diagnostic.

## What This Task Does
- Migrates background and settings resolver sites to optional/no-vault behavior:
  - `app/workers/outbox_worker.py`
  - `app/settings/watcher_settings.py`
  - `app/settings/health_settings.py`
  - `app/health_contract.py` if the pickup audit still finds eager health vault resolution.
- When no vault is selected:
  - workers skip/idly return without creating files under `./vault`;
  - watcher settings report no configured/selected watcher notes rather than raising;
  - health settings expose an explicit no-vault status rather than a fake default root.
- Preserves set-but-missing behavior as loud/misconfigured where the existing contract
  distinguishes that from "no selected vault".
- Leaves API picker responses and import-time/CLI behavior to Slices A and C.

## Concretely
```python
# No selected vault, VAULT_ROOT unset: worker loop can tick without writing ./vault artifacts.
result = outbox_worker.run_once(vault_root=None)
assert result.state in {"idle", "skipped", "no_vault"}

# Health/settings call sites expose no-vault identity, not Path("vault").
assert health_payload["vault"]["status"] in {"none", "not_selected"}
assert "vault" not in created_paths_under_cwd
```

## Why This Matters
The runtime can boot without a vault only if background producers also tolerate that state.
A request path can show the picker; a worker cannot. The right behavior is to idle
truthfully until a vault is selected.

## Acceptance Criteria
- [ ] Outbox worker ticks with no selected vault without creating or reading CWD-relative
      `./vault`. Verify: `tests/workers/test_outbox_worker_no_vault_idle.py::test_outbox_worker_idles_without_selected_vault`
- [ ] Watcher settings resolve to an empty/no-vault state without fallback. Verify:
      `tests/settings/test_watcher_settings_no_vault.py::test_watcher_settings_returns_empty_when_no_vault`
- [ ] Health settings report no-vault identity without fake default root. Verify:
      `tests/settings/test_health_settings_no_vault.py::test_health_settings_reports_no_vault_without_fallback`
- [ ] Grep/AST guard covers background/settings eager resolver sites so new fallback
      regressions are caught. Verify: `tests/api/test_no_silent_cwd_vault_fallback.py::test_background_resolvers_do_not_fallback_to_cwd_vault`

## How to Verify (Pre-Merge)
```bash
pytest -q \
  tests/workers/test_outbox_worker_no_vault_idle.py \
  tests/settings/test_watcher_settings_no_vault.py \
  tests/settings/test_health_settings_no_vault.py \
  tests/api/test_no_silent_cwd_vault_fallback.py
ruff check app tests
RUN_INTEGRATED_RUNTIME_UAT=1 pytest -q tests/uat/
```

The IR-v1 UAT is required if worker/settings changes alter active-vault boundaries or hot
runtime paths.

## Out of Scope
- Request-path picker responses (Slice A).
- Promotion import-time resolver removal, CLI policy, and agent-memory helpers (Slice C).
- Changing the test-channel deterministic vault preflight.

## Related Docs
- Parent: `docs/VAULT_OPTIONAL_RUNTIME/README.md`
- `docs/VAULT_OPTIONAL_RUNTIME/BOOT_RUNTIME_WITHOUT_VAULT.md`
- #2311 (parent migration hub)

## Related GitHub Issues
One bounded child issue to be filed from this task after the spec lands on main. It remains
blocked/backlog until Slice A is delivered or explicitly released for parallel pickup.
