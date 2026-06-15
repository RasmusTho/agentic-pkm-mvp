---
name: Resolve No-Vault State
description: The config resolver returns a no-vault state when VAULT_ROOT is unset instead of defaulting to a relative ./vault.
task_id: VAULT_OPTIONAL_RUNTIME-01
source_anchor: docs/VAULT_OPTIONAL_RUNTIME/README.md :: Capability boundary
parent_capability: Vault Optional at Runtime
prerequisites: []
depends_on: []
can_parallelize_with: []
---

# Resolve No-Vault State

## Purpose
A vault is no longer required at initiation. The runtime config layer must be able to say
"no vault is bound" without falling back to a CWD-relative `./vault` default — that silent
fallback is the exact footgun behind the 2026-06-09 "notes won't render" incident.

## What This Task Does
Introduce an explicit no-vault resolution path in `app/config/paths.py`:
- when `VAULT_ROOT` (and any env-scoped `VAULT_ROOT_TEST`/`_DEV`) is **unset**, the resolver
  reports **no vault bound** rather than returning `_DEFAULT_VAULT` (`./vault`);
- a new resolver API (e.g. `resolve_optional_vault_root()` returning `Path | None`, or a
  small `VaultResolution` result) lets callers distinguish *no vault* from *a resolved vault*
  and from *set-but-missing* (which keeps raising `VaultRootMisconfiguredError`);
- the legacy `resolve_vault_root()` signature is preserved for the bound-vault path; callers
  that must tolerate no-vault migrate to the optional API (the watcher in task 2, the
  companion boundary in task 3).

This aligns the config layer with `app/vault/manager.py`, which already models the state:
`VaultStatus = "none"` and `no_vault_context()`.

## Concretely
```python
# unset VAULT_ROOT -> no vault, no ./vault default, no raise
os.environ.pop("VAULT_ROOT", None)
assert resolve_optional_vault_root() is None          # was: Path("vault")

# set-but-missing still fails loud (unchanged from #1757)
os.environ["VAULT_ROOT"] = "/does/not/exist"
with pytest.raises(VaultRootMisconfiguredError):
    resolve_optional_vault_root()

# bound + existing resolves as before
os.environ["VAULT_ROOT"] = str(real_vault)
assert resolve_optional_vault_root() == real_vault
```

## Why This Matters
If "no vault" silently becomes `./vault`, the runtime serves an empty/wrong vault (the
`provenance="fallback"` failure mode) instead of routing the human to the picker. This task
is the foundation every other task in the capability builds on.

## Acceptance Criteria
- [ ] Unset `VAULT_ROOT` resolves to an explicit no-vault state (not `./vault`, no raise). Verify: `tests/settings/test_paths_resolver.py::test_unset_vault_root_resolves_to_no_vault`
- [ ] Set-but-missing `VAULT_ROOT` still raises `VaultRootMisconfiguredError` (no regression of #1757 hardening). Verify: `tests/settings/test_paths_resolver.py::test_set_but_missing_vault_root_still_fails_loud`
- [ ] A bound, existing `VAULT_ROOT` resolves unchanged. Verify: `tests/settings/test_paths_resolver.py::test_bound_vault_root_resolves`
- [ ] The optional resolver result is consumable by callers without catching exceptions for the no-vault case. Verify: `tests/settings/test_paths_resolver.py::test_optional_resolver_returns_none_for_no_vault`

## How to Verify (Pre-Merge)
```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/settings/test_paths_resolver.py
```
CI: covered by the existing unit-test job (paths resolver is store-agnostic, no Docker).

## Out of Scope
- Changing watcher boot behaviour (task 2) or companion routing (task 3).
- Changing the set-but-missing semantics (#1757 already handled it).

## Related Docs
- Parent: `docs/VAULT_OPTIONAL_RUNTIME/README.md`
- `app/config/paths.py :: resolve_optional_vault_root`, `resolve_vault_root`, `_DEFAULT_VAULT`, `VaultRootMisconfiguredError`
- `app/vault/manager.py :: no_vault_context`, `VaultStatus`

## Related GitHub Issues
One bounded issue (#2004). Implements VAULT_OPTIONAL_RUNTIME/RESOLVE_NO_VAULT_STATE.
**Delivered** — `resolve_optional_vault_root()` in `app/config/paths.py` returns `None` for an
unset `VAULT_ROOT` (no `./vault` default), preserves the set-but-missing
`VaultRootMisconfiguredError` raise, and resolves a bound, existing vault unchanged. The
legacy `resolve_vault_root()` is preserved for the bound-vault path; the watcher (#2005) and
companion boundary (#2006) migrate to the optional API.
