State: Filed active validation hub #5667; child issues are filed as blocked dependencies while the specification PR is open and become ready after it merges.
Parent feature issue: https://github.com/RasmusTho/agentic-pkm-mvp/issues/5667
Capability: CLOUD_SECRET_PROVISIONING
Owner: Yggdrasil Platform and Operations, with Product/Runtime Heimdal and database owner review
Last reviewed: 2026-09-25

# Parent Feature Issue — Cloud Secret Provisioning

Issue #5667 is the live validation hub. The specification directory and child task files define repository work; the issue tracks the child ledger, merge receipts, integrated verification, owner-doc promotion, and the separate live operator qualification gate.

The owner decision on production Heimdal data-key rotation is open in the issue thread. Do not create or ready a task that changes the active raw-store-key or archive-pass until that answer is recorded and the task contract names the approved behavior. A separate live qualification receipt is required for shared BWS parity: the local operation lock only coordinates cooperating calls on one host, so the owner must approve the sole admin writer and show its credential is restricted to that controller, or select a shared fencing mechanism. Keep deploy admission blocked until that gate passes.

## Specification delivery

BWS-00 / #5682 tracks the specification PR. That PR closes #5682 only; the parent and implementation issues remain open for their respective delivery and acceptance.

## Child tasks

All four issues are filed with agent:blocked / action:wait-dependency while the specification PR is open. The spec PR merge is required before any child becomes pickup-ready.

1. BWS-01 Resolve BWS channel secrets — #5677
2. BWS-02 Administer secrets value-free — #5678; depends on #5677
3. BWS-03 Install VM secret tokens — #5679; depends on #5677
4. BWS-04 Deploy PostgreSQL with Compose secrets — #5680; depends on #5677 and #5678

See docs/CLOUD_SECRET_PROVISIONING/README.md for task order, unknown-provider-outcome behavior, durable remote token receipts, supervised deploy recovery and quiescence, the sole-writer qualification gate, and cross-task invariants.
