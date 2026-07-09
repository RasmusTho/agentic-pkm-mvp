---
name: External BuilderOps Vault Configuration
description: Configure a dedicated shared artifact vault while retaining local SQLite and lease state.
task_id: BMI-01
source_anchor: docs/BUILDEROPS_MODEL_INQUIRY/README.md :: Scope
parent_capability: BuilderOps Model Inquiry
prerequisites: []
depends_on: []
can_parallelize_with: []
---

# External BuilderOps Vault Configuration

## Purpose

Make the Yggdrasil-owned iCloud BuilderOps vault an explicit artifact root without turning iCloud
into a database or lock service.

## What This Task Does

Add a validated `BUILDEROPS_VAULT_ROOT` configuration path for shared Markdown artifacts. Preserve
the existing local `BUILDEROPS_DB_PATH` behavior and introduce a local-only claims root. Bootstrap
must initialize the external artifact vault without creating SQLite files or live leases inside it.

## Concretely

```bash
scripts/builderops_cli.sh builderops vault init "$BUILDEROPS_VAULT_ROOT" --json
scripts/builderops_cli.sh builderops vault paths --json
```

The paths command reports the shared artifact root, local SQLite path, and local claims root. It
fails if the configured shared vault contains `builderops.sqlite3` or `.builderops/claims`.

## Why This Matters

iCloud synchronizes files but does not provide transactional SQLite or distributed lock semantics.
Putting active coordination state there creates false safety across developer devices.

## Acceptance Criteria

- [ ] BuilderOps resolves a shared vault root independently of the local SQLite path.
  Verify: `tests/builderops/test_builderops_paths.py::test_resolves_shared_vault_and_local_state_independently`.
- [ ] Bootstrap creates only Markdown queue/artifact directories in the shared vault.
  Verify: `tests/builderops/test_builderops_paths.py::test_shared_vault_bootstrap_never_creates_sqlite_or_claims`.
- [ ] Validation rejects a shared vault containing SQLite or active claim state.
  Verify: `tests/builderops/test_builderops_paths.py::test_rejects_operational_state_inside_shared_vault`.
- [ ] The BuilderOps store contract documents the shared-artifact/local-state separation.
  Verify: doc writeback at `docs/builderops/BUILDEROPS_VAULT_STORE.md :: Store Location`.

## How to Verify (Pre-Merge)

- `pytest -q tests/builderops/test_builderops_paths.py`
- `scripts/builderops_cli.sh builderops vault paths --json`
- Review the documented location contract.

## Out of Scope

- cross-device distributed leases;
- moving existing local SQLite records into iCloud;
- model orchestration or desktop skills.

## Related Docs

- `docs/BUILDEROPS_MODEL_INQUIRY/README.md`
- `docs/builderops/BUILDEROPS_VAULT_STORE.md`

## Related GitHub Issues

- Parent feature: [#3288](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3288)
- Implementation: [#3289](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3289)
