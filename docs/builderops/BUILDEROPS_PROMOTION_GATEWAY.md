State: Explicit BuilderOps Vault promotion gateway implemented for #1504. The gateway renders proposals, appends receipts, and transitions PromotionIntent records; it does not directly create GitHub Issues, write repo docs, open PRs, update generated projections, or mutate product/runtime authority.
Doc role: BuilderOps promotion gateway reference
Authority: Documents the #1504 proposal/receipt/state-transition gateway. Authority boundaries remain owned by ADR-0010; object semantics remain owned by `docs/builderops/BUILDEROPS_VAULT_OBJECT_MODEL.md`; store mechanics remain owned by `docs/builderops/BUILDEROPS_VAULT_STORE.md`.
Owner: BuilderOps governance
Temporal class: operational
Review cadence: event-driven
Source of truth: app/builderops/promotion_gateway.py, app/cli/builderops.py
Last reviewed: 2026-06-01
Last verified against: issue #1504

# BuilderOps Promotion Gateway

## Scope

#1504 implements an explicit gateway for `PromotionIntent` material.

The gateway can:

- validate allowed promotion targets
- render proposal/dry-run output for GitHub Issue, PR/branch, ADR/doc writeback, owner-doc writeback, generated projection, and discard-receipt targets
- append traceable `BuilderOpsReceipt` records for dry runs and transitions
- transition `PromotionIntent` records to accepted, promoted, rejected, or discarded states under the store lease/idempotency rules

The gateway is exposed through explicit local CLI commands:

- `builderops promotion-preview <intent_id>`
- `builderops promotion-dry-run <intent_id>`
- `builderops promotion-transition <intent_id> --decision accepted|promoted|rejected|discarded`

## Authority Boundary

The gateway is proposal and receipt infrastructure. It does not silently mutate any authority
surface.

- GitHub Issue promotion produces a draft body with `Parent`, `Source Anchors`, and serialized
  `source_refs`; creating or editing the actual issue remains an explicit GitHub action.
- PR/branch, ADR/doc, owner-doc, skill, and `AGENTS.md` promotions produce proposal material only;
  repo changes still require the normal PR workflow.
- Generated projection promotion produces projection-update material only; projections are not
  source-of-truth.
- Discard promotion records a discard decision and receipt; it does not delete or rewrite the
  original source records.

No BuilderOps object changes product/runtime truth unless an explicit promotion crosses into the
target authority surface through its normal gate.

## State Transitions

Gateway transitions are narrower than raw store transitions:

| Decision | Resulting lifecycle_state | Resulting promotion_status | Notes |
| --- | --- | --- | --- |
| `accepted` | `accepted` | `promotion_pending` | May start from `draft` or `review_pending`. |
| `promoted` | `promoted` | `promoted` | Requires prior `accepted` state and an explicit external/result reference when available. |
| `rejected` | `discarded` | `rejected` | Review declined the promotion target. Receipt must include rationale. |
| `discarded` | `discarded` | `discarded` | Signal is obsolete or intentionally not promoted. Receipt must include rationale. |

Terminal intents cannot be accepted, promoted, rejected, or discarded again.

## CLI Examples

```bash
python -m app.cli builderops promotion-preview prom_example --json

python -m app.cli builderops promotion-dry-run prom_example \
  --actor codex \
  --idempotency-key dry-run:prom_example \
  --json

python -m app.cli builderops acquire-lease prom_example --actor codex --json

python -m app.cli builderops promotion-transition prom_example \
  --decision accepted \
  --actor codex \
  --lease-id lease_from_acquire_lease \
  --idempotency-key transition:prom_example:accepted \
  --rationale "Accepted as BuilderOps promotion material." \
  --json
```

## Out Of Scope

This slice intentionally does not implement:

- automatic GitHub Issue creation
- automatic PR branch creation
- direct ADR/doc/owner-doc writes
- generated projection file writes
- public remote deployment or rich UI
- product/runtime authority changes
