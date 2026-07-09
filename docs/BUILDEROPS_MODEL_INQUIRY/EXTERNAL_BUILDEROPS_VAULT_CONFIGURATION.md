---
name: External BuilderOps Vault Configuration
description: Configure a shared artifact vault with advisory claims while retaining local SQLite and authoritative leases.
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

Add a validated `BUILDEROPS_VAULT_ROOT` configuration path for shared Markdown artifacts, queue
files, receipts, transient worker state, and TTL-based advisory claim signals. Preserve the existing
local `BUILDEROPS_DB_PATH` behavior and local authoritative dispatcher leases. Bootstrap must
initialize the external artifact vault without creating SQLite files or provider credentials.

## Concretely

```bash
scripts/builderops_cli.sh builderops vault init "$BUILDEROPS_VAULT_ROOT" --json
scripts/builderops_cli.sh builderops vault paths --json
```

The paths command reports the shared artifact root, local SQLite path, and shared advisory claims
root. Validation fails if the configured shared vault contains SQLite or if the requested root does
not match `BUILDEROPS_VAULT_ROOT`.

## Why This Matters

iCloud synchronizes files but does not provide transactional SQLite or distributed lock semantics.
Treating advisory files as authoritative leases creates false safety across developer devices.

## Acceptance Criteria

- [ ] BuilderOps resolves a shared vault root independently of the local SQLite path.
  Verify: `tests/builderops/test_builderops_paths.py::test_resolves_shared_vault_and_local_state_independently`.
- [ ] Bootstrap creates Markdown queue/artifact directories plus advisory claim state, but no
  SQLite. Verify:
  `tests/builderops/test_builderops_paths.py::test_shared_vault_bootstrap_creates_advisory_claims_but_never_sqlite`.
- [ ] Validation rejects SQLite and mismatched configured roots while allowing advisory claim
  state. Verify:
  `tests/builderops/test_builderops_paths.py::test_rejects_sqlite_but_allows_advisory_claim_state_inside_shared_vault`.
- [ ] Concurrent agents may publish advisory claims without implying an exclusive distributed
  lock, and stale signals remain visible. Verify: `tests/builderops/test_builderops_claims.py`.
- [ ] The BuilderOps store contract documents the shared-artifact/local-state separation.
  Verify: doc writeback at `docs/builderops/BUILDEROPS_VAULT_STORE.md :: Store Location`.

## How to Verify (Pre-Merge)

- `pytest -q tests/builderops/test_builderops_paths.py`
- `scripts/builderops_cli.sh builderops vault paths --json`
- Review the documented location contract.

## Out of Scope

- cross-device distributed or authoritative leases;
- moving existing local SQLite records into iCloud;
- model orchestration or desktop skills.

## Related Docs

- `docs/BUILDEROPS_MODEL_INQUIRY/README.md`
- `docs/builderops/BUILDEROPS_VAULT_STORE.md`

## Related GitHub Issues

- Parent feature: [#3288](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3288)
- Implementation: [#3289](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3289)
