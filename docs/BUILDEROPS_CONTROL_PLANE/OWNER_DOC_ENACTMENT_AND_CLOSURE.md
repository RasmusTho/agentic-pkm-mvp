State: Target-state closure contract. #5056 supplies the rebuildable deployment amendment.

# Owner-Doc Enactment And Closure

## Purpose

Promote only shipped BuilderOps reality into owner docs and close the parent only when its actual live authority gates are evidenced.

## Closure evidence

Parent closure requires linked source/image pin, separate engine/project, VM-local secret-reference, loopback plus Tailscale Serve-without-Funnel private ingress, bearer-authenticated readiness, schema/migration, authority epoch/fencing, no-dual-writer, local disk/WAL guard, rebuild receipt, CI/review/merge, and Product-separation evidence. It does not require a backup or restore drill.

Rollback is code/config/image selection without data rewind. The owner-doc writeback must retain the rule that operators never manually delete `pg_wal`, run `pg_resetwal`, or use reset/cleanup tools as a substitute for rebuildability.

## Acceptance Criteria

- [ ] Current owner docs describe only the delivered rebuildable BuilderOps posture.
  Verify: doc writeback at `docs/BUILDEROPS_CONTROL_PLANE/README.md :: Builder-system rebuildable deployment posture`.
- [ ] The parent has a truthful receipt for every live activation gate and no false backup/restore closure gate.
  Verify: runtime receipt: builderops_vm_rebuild_activation.v1.

## Out of Scope

- Inventing backup/restore implementation, accepting a live rollout without its genuine receipts, or editing historical audit records.
