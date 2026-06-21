---
name: Legacy Vault Mount Removal
description: The legacy /app/vault compose and runtime-env fallback is removed or re-baselined after eager resolver consumers no longer require it.
task_id: VAULT_OPTIONAL_RUNTIME-05D
source_anchor: docs/VAULT_OPTIONAL_RUNTIME/README.md :: Follow-up eager resolver migration
parent_capability: Vault Optional at Runtime
prerequisites: [VAULT_OPTIONAL_RUNTIME-01, VAULT_OPTIONAL_RUNTIME-02, VAULT_OPTIONAL_RUNTIME-03]
depends_on: [API_ENDPOINT_OPTIONAL_VAULT_BOUNDARIES.md, BACKGROUND_OPTIONAL_VAULT_IDLE.md, PROMOTION_CLI_AGENT_OPTIONAL_VAULT_RESOLUTION.md]
can_parallelize_with: []
---

# Legacy Vault Mount Removal

## Purpose
Once request paths, background workers, helper APIs, CLI, MCP, and knowledge consumers no
longer require the legacy eager resolver, the container/runtime surfaces must stop preserving
`./vault:/app/vault` as an implicit fallback. The broad `/Users` and `/Volumes` mounts from
#2310 allow selected host-absolute vault paths to resolve in-container without translating
through `/app/vault`.

This is Slice D of #2311. It is intentionally last because removing or re-baselining the
legacy mount before 05A-05C land can break still-migrating consumers that depend on
`resolve_vault_root()` returning `/app/vault` in containerized runs.

## What This Task Does
- Removes or re-baselines the legacy compose mount fallback in:
  - `docker-compose.yaml`
  - `docker-compose.watcher.yml`
- Updates runtime-env/startup surfaces so no-vault idle does not bind or imply
  `./vault:/app/vault`, and any retained `/app/vault` compatibility path requires an
  explicit operator/configured vault rather than being a default fallback:
  - `scripts/export_runtime_env.sh`
  - `scripts/start_full_system.sh`
- Updates the environment docs that currently state the legacy mount remains until #2311:
  - `docs/ENVIRONMENTS.md`
- Re-baselines tests that currently preserve the legacy mount as a #2311 placeholder:
  - `tests/ops/test_full_host_mount.py`
  - `tests/ops/test_export_runtime_env.py`

## Concretely
```yaml
# No selected/configured vault: compose must not synthesize ./vault as /app/vault.
services:
  api:
    volumes:
      - /Users:/Users
      - /Volumes:/Volumes
```

If a compatibility `/app/vault` mount remains for explicit startup flows, it must be
documented as a compatibility mount for an explicitly bound vault, not as an active-vault
selection source and not as a no-vault fallback.

## Why This Matters
#2311 is the "no silent ./vault" migration hub. Closing it while compose still defaults to
`${VAULT_HOST_ROOT:-${VAULT_ROOT:-./vault}}:/app/vault` leaves an infrastructure-level
fallback even if Python call sites have moved to optional/no-vault behavior.

## Acceptance Criteria
- [ ] No-vault compose/runtime startup does not bind repo-local `./vault` to `/app/vault`.
      Verify: `tests/ops/test_full_host_mount.py::test_no_vault_startup_does_not_preserve_legacy_app_vault_mount`
- [ ] Any remaining `/app/vault` compatibility path is explicit and cannot be selected by
      unset `VAULT_ROOT` or unset `VAULT_HOST_ROOT`. Verify:
      `tests/ops/test_export_runtime_env.py::test_legacy_app_vault_mount_requires_explicit_vault`
- [ ] `docs/ENVIRONMENTS.md` no longer says the legacy mount remains until #2311; it either
      documents the removed mount or the explicit compatibility contract. Verify:
      `tests/ops/test_full_host_mount.py::test_environment_docs_match_legacy_mount_contract`
- [ ] The #2310 full-host mounts remain unchanged for `/Users:/Users` and
      `/Volumes:/Volumes`. Verify:
      `tests/ops/test_full_host_mount.py::test_compose_mounts_users_and_volumes_same_path`

## How to Verify (Pre-Merge)
```bash
pytest -q \
  tests/ops/test_full_host_mount.py \
  tests/ops/test_export_runtime_env.py
ruff check app tests
RUN_INTEGRATED_RUNTIME_UAT=1 pytest -q tests/uat/
```

The IR-v1 UAT is required because this slice changes active-vault/container runtime
boundaries.

## Out of Scope
- Migrating Python resolver consumers still covered by Slices A-C.
- Changing the #2310 `/Users` and `/Volumes` same-path mount contract.
- Reopening nested-vault boundary or vault-initialization owner decisions.

## Related Docs
- Parent: `docs/VAULT_OPTIONAL_RUNTIME/README.md`
- `docs/ENVIRONMENTS.md`
- #2310 (same-path full-host mounts)
- #2311 (parent migration hub)

## Related GitHub Issues
One bounded child issue to be filed from this task after the spec lands on main. It should
remain blocked/backlog until Slices A-C are delivered and the remaining eager resolver
consumers no longer require `/app/vault`.
