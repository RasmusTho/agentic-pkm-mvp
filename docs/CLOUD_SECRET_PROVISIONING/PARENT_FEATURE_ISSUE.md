State: Active validation hub #5667; specification, repository children, and owner-doc promotion are delivered. The specific BWS entitlement, reader, MARR, encrypted-token, and normal-writer evidence is recorded; integrated target/action-bound DEV/TEST/PROD deployment/runtime acceptance remains open.
Parent feature issue: https://github.com/RasmusTho/agentic-pkm-mvp/issues/5667
Capability: CLOUD_SECRET_PROVISIONING
Owner: Yggdrasil Platform and Operations, with Product/Runtime Heimdal and database owner review
Last reviewed: 2026-10-15
Last verified against: merged PRs #5683, #5703, #5717, #5725, #5732, #5734, and #6015; #5667 comments #5868385351, #6114638077, #6114724380, and #6114787299.

# Parent Feature Issue — Cloud Secret Provisioning

Issue #5667 is the live validation hub. The specification directory and child task files define repository work; the issue tracks the child ledger, merge receipts, integrated verification, owner-doc promotion, and the remaining live deployment/runtime acceptance. Current receipts verify the Free-plan entitlement, both existing reader tokens' access to both projects, active encrypted reader services on all three channel VMs, the exact MARR non-prod binding, and the accepted normal-writer model. They do not establish integrated acceptance for all required DEV/TEST/PROD operations or bind that acceptance to each authorized target/action.

The delegated policy decision recorded in #5667 comment #5868385351 defers production `heimdal.raw-store-key` rotation or deletion until a bounded rekey path is delivered; keep the current key active and refuse protected writes. `archive-pass` remains separately protected pending its own lifecycle policy. The [2026-10-11 normal-writer receipt](https://github.com/RasmusTho/agentic-pkm-mvp/issues/5667#issuecomment-6114787299) accepts Demerzel login Keychain custody plus `scripts/secrets` as the sole supported normal writer. The human Organization Owner remains break-glass; deliberate same-user bearer use outside the controller is an accepted residual. No separate writer daemon or shared fencing is required for this one-owner setup. Reassess before extra operators/controllers or prod secrets requiring confidentiality. Supported operations retain their local locks, history/parity and durable terminal receipts; bootstrap retains its local qualification receipt requirement. This resolves the protected-key policy and normal-writer decision; #5667 remains open for integrated deployment/runtime acceptance.

## Specification delivery

BWS-00 / #5682 was delivered by PR #5683, which closed #5682 only. The four repository children were delivered and closed: #5677 by #5703, #5678 by #5717, #5679 by #5732, and #5680 by #5725. The parent remains open for integrated acceptance and full live deployment/runtime qualification.

## Child tasks

All four implementation issues are delivered and closed. Their merge receipts and current acceptance status are recorded on #5667; the remaining parent work is not a child-implementation dependency.

1. BWS-01 Resolve BWS channel secrets — #5677
2. BWS-02 Administer secrets value-free — #5678; depends on #5677
3. BWS-03 Install VM secret tokens — #5679; depends on #5677
4. BWS-04 Deploy PostgreSQL with Compose secrets — #5680; depends on #5677 and #5678

See docs/CLOUD_SECRET_PROVISIONING/README.md for task order, unknown-provider-outcome behavior, durable remote token receipts, supervised deploy recovery and quiescence, the accepted normal-writer model and remaining broader live qualification, and cross-task invariants.
