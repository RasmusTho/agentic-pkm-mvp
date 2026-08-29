State: Parent feature contract. #5056 amends the deployment durability posture.

# Parent feature issue — BuilderOps independent control plane

## Context

The BuilderOps control plane remains a target-state capability. The deployment path is rebuildable operational state; backup/restore is deferred and cannot block the parent or any child activation gate.

## Scope

Track bounded BCP deliveries and the final live validation hub without treating deployment receipts, Project cards, or backup work as authority.

## Source Anchors

- `docs/BUILDEROPS_CONTROL_PLANE/README.md :: Builder-system rebuildable deployment posture`
- `docs/BUILDEROPS_CONTROL_PLANE/INDEPENDENT_AUTHENTICATED_DEPLOYMENT.md :: Rebuildable VM deployment contract`

## SBS Impact

- Primary subsystem: Builder System / CES boundary
- Persistence impact: BuilderOps operational state is rebuildable
- New or changed contract: backup/restore deferred and non-gating

## Constraints

- Child work keeps immutable pins, independent engine/project, VM-local secret references, private authenticated loopback ingress, migrations, fencing, no dual writer, rebuild receipts, health/readiness, and local WAL/disk guardrails.
- No child uses backup, restore, manual `pg_wal` deletion, `pg_resetwal`, or reset/cleanup tooling as a readiness or rollback substitute.

## Acceptance Criteria

- [ ] BCP children prove one API/PostgreSQL authority and Product separation.
  Verify: BCP child receipts and `tests/architecture/test_builderops_product_separation.py::test_product_runtime_has_no_builderops_ownership`.
- [ ] A live BuilderOps activation records private authenticated ingress, no dual writer, source/image pins, schema/epoch, health/readiness, and rebuild posture.
  Verify: runtime receipt: builderops_vm_rebuild_activation.v1.
- [ ] Parent closure uses only truthful child, CI, review, merge, and activation evidence; a deferred backup/restore capability is not a closure blocker.
  Verify: `docs/BUILDEROPS_CONTROL_PLANE/OWNER_DOC_ENACTMENT_AND_CLOSURE.md :: Closure evidence`.

## Out of Scope

- Backup/restore implementation or acceptance.

## Suggested Validation

- Resolve child `Verify:` targets and the live activation receipt before closure.
