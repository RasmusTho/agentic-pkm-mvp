State: Target-state BCP-06 contract. BuilderOps deployment durability is amended by #5056: rebuildability is required; backup/restore is deferred and non-gating.
Doc role: BCP-06 owner contract
Authority: Defines the eventual authority cutover and Product separation boundary.

# Authority Cutover And Product Separation

## Purpose

Activate one BuilderOps PostgreSQL authority without reintroducing Product ownership, a second writer, or a data-rewind rollback path.

This owner contract follows the [RSC-01 continuity classification](../REBUILDABLE_SYSTEM_CONTINUITY/README.md#rsc-01-continuity-classification): BuilderOps operational state is rebuildable from declared repository, image, configuration, and secret-custody sources; its journals, leases, epochs, and fences are operational safety state; and any missing lineage starts an inactive new fenced bootstrap with GitHub readback before activation. Diagnostic dumps and optional backups are evidence/ergonomics only, never semantic authority or a mandatory restore proof. The historical July 2026 restore-first/WAL proposal is superseded and not an active capability; no generalized backup/restore is shipped by this contract.

## Builder-system authority activation

Before a live activation, the operator must prove an immutable source/image candidate, separate BuilderOps Docker engine/project, VM-local secret references, loopback API, Tailscale Serve private HTTPS without Funnel, scoped bearer authentication, schema/migrations, authority epoch/fencing, no dual writer, health/readiness, local disk/WAL guardrails, and a rebuild receipt. The BuilderOps database is rebuildable operational state: a failed deployment is rebuilt from repository, attested images, configuration, and secret custody. Backup or restore evidence is not an activation gate.

Rollback selects compatible code/config/image only. It never rewinds surviving database data, manually deletes `pg_wal`, invokes `pg_resetwal`, or uses reset/cleanup tools as an alternative to recovery.

## Constraints

- Freeze and inventory legacy writers before any authority handoff; no live SQLite/JSONL/JSON writer may remain.
- Product Runtime has no BuilderOps route, startup hook, state mount, secret, health path, Docker project, or lifecycle ownership.
- Rebuild after a failed candidate preserves the truth boundary: reconcile external effects against GitHub before writes resume and retain authority fencing.
- A future backup/restore capability is separately governed. It cannot be inferred from a pin, image, volume, or this contract.

## Acceptance Criteria

- [ ] Cutover activates exactly one fenced BuilderOps authority epoch and proves no legacy writer remains.
  Verify: runtime receipt: builderops_vm_rebuild_activation.v1.
- [ ] Product Runtime remains healthy and independent while BuilderOps is stopped or rebuilt.
  Verify: `tests/architecture/test_builderops_product_separation.py::test_product_runtime_has_no_builderops_ownership`.
- [ ] A failed BuilderOps candidate returns to a compatible pinned release without database rewind and records the attempted and previous pins.
  Verify: `tests/ops/test_builderops_deploy_contract.py::test_readiness_failure_reactivates_previous_live_release`.
- [ ] Activation does not accept WAL-G, recovery targets, backup services, or restore proofs as readiness/cutover gates.
  Verify: `tests/ops/test_builderops_compose_contract.py::test_rebuildable_candidate_path_has_no_backup_or_restore_gate`.

## Out of Scope

- Product feature changes, live Proxmox/Tailscale/Docker/secret/PostgreSQL mutation, and backup/restore implementation.

## How to Verify (Pre-Merge)

- Run focused deployment, Compose, health, and Product-separation tests.
- Keep the parent open until the live activation receipt proves the named private-ingress and no-dual-writer gates.

## Related Docs

- `docs/BUILDEROPS_CONTROL_PLANE/README.md`
- `docs/BUILDEROPS_CONTROL_PLANE/INDEPENDENT_AUTHENTICATED_DEPLOYMENT.md`
