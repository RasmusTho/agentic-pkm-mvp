State: Filed active validation hub #5667; child issues are filed as blocked dependencies while the specification PR is open and become ready after it merges.
Parent feature issue: https://github.com/RasmusTho/agentic-pkm-mvp/issues/5667
Capability: CLOUD_SECRET_PROVISIONING
Owner: Yggdrasil Platform and Operations, with Product/Runtime Heimdal and database owner review
Last reviewed: 2026-10-12

# Parent Feature Issue — Cloud Secret Provisioning

Issue #5667 is the live validation hub. The specification directory and child task files define repository work; the issue tracks the child ledger, merge receipts, integrated verification, owner-doc promotion, and the separate live operator qualification gate.

The owner decision on production Heimdal data-key rotation is open in the issue thread. Do not create or ready a task that changes the active raw-store-key or archive-pass until that answer is recorded and the task contract names the approved behavior. The [2026-10-11 owner receipt](https://github.com/RasmusTho/agentic-pkm-mvp/issues/5667#issuecomment-6114787299) accepts Demerzel login Keychain custody plus `scripts/secrets` as the sole supported normal writer. The human Organization Owner remains break-glass; deliberate same-user bearer use outside the controller is an accepted residual. No separate writer daemon or shared fencing is required for this one-owner setup. Reassess before extra operators/controllers or prod secrets requiring confidentiality. Supported operations retain their local locks, history/parity and durable terminal receipts; bootstrap retains its local qualification receipt requirement. This resolves only the normal-writer decision: #5667 remains open for broader deployment/runtime acceptance.

## Specification delivery

BWS-00 / #5682 tracks the specification PR. That PR closes #5682 only; the parent and implementation issues remain open for their respective delivery and acceptance.

## Child tasks

All four issues are filed with agent:blocked / action:wait-dependency while the specification PR is open. The spec PR merge is required before any child becomes pickup-ready.

1. BWS-01 Resolve BWS channel secrets — #5677
2. BWS-02 Administer secrets value-free — #5678; depends on #5677
3. BWS-03 Install VM secret tokens — #5679; depends on #5677
4. BWS-04 Deploy PostgreSQL with Compose secrets — #5680; depends on #5677 and #5678

See docs/CLOUD_SECRET_PROVISIONING/README.md for task order, unknown-provider-outcome behavior, durable remote token receipts, supervised deploy recovery and quiescence, the accepted normal-writer model and remaining broader live qualification, and cross-task invariants.
