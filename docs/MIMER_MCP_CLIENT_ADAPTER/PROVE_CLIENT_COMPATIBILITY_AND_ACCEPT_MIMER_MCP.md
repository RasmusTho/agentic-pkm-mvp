---
name: Prove Client Compatibility and Accept Mimer MCP
description: Prove the composed MCP capability across protocol, governed capture, restart, and supported-client journeys, then reconcile acceptance truth
task_id: MIMER-MCP-04
source_anchor: "docs/MIMER_MCP_CLIENT_ADAPTER/README.md :: Validation / Acceptance Path"
parent_capability: Mimer MCP Client Adapter
prerequisites: [MIMER-MCP-02, MIMER-MCP-03]
depends_on: [EXPOSE_GOVERNED_MIMER_TOOLS_OVER_MCP.md, PACKAGE_AND_HARDEN_MIMER_MCP_TRANSPORT.md]
can_parallelize_with: []
---

# Prove Client Compatibility and Accept Mimer MCP

## Purpose

Verify that the semantic adapter and hardened transport work as one capability, retain durable
evidence of supported clients, and update current-state truth only to the level actually proven.

## What This Task Does

- Adds a hermetic composed MCP journey covering initialization, discovery, reads, governed capture,
  error behavior, and restart.
- Runs the documented smoke against the test channel or an equivalently isolated real runtime.
- Records a client/transport compatibility matrix and one governed capture receipt on the parent.
- Assembles the child verification ledger and reconciles owner docs, parent state, and roadmap truth.
- Creates a bounded follow-up rather than weakening acceptance if a client cannot be tested.

## Concretely

```text
initialize -> tools/list -> health -> retrieve -> read_note -> ask
           -> capture -> inspect governed receipt
           -> restart server -> health -> tools/list
           -> prove forbidden tool absent and blocked capture stays blocked
```

## Why This Matters

Unit-correct handlers and a healthy listener do not prove end-to-end protocol compatibility or
receipt fidelity. Acceptance evidence prevents owner docs from claiming “every MCP client” based on
one synthetic call.

## Acceptance Criteria

- [ ] A hermetic composed journey proves MCP initialization, exact discovery, health, retrieve,
      note read, ask, and one governed capture receipt through the packaged transport.
  Verify: `tests/mcp/test_mimer_server_smoke.py::test_composed_mimer_mcp_journey`
- [ ] The composed journey proves generic vault write and receipt read-back are absent, and a
      WriteGuard-blocked capture remains blocked without retry or fallback.
  Verify: `tests/mcp/test_mimer_server_smoke.py::test_composed_journey_preserves_write_boundary_and_failure`
- [ ] Restart recovery restores protocol health and discovery without replaying the prior capture or
      retaining adapter-owned durable state.
  Verify: `tests/mcp/test_mimer_server_smoke.py::test_restart_recovers_without_capture_replay`
- [ ] The parent issue records the tested client(s), transport(s), runtime head SHA, capture trace and
      AuthorityReceipt reference, restart result, and any untested-client follow-up.
  Verify: runtime acceptance receipt on the parent feature issue
- [ ] Every child has a delivery receipt and owner-doc resolution; current-state docs and the local
      spec state are reconciled to exactly the accepted support level.
  Verify: doc writeback at `docs/STATUS.md :: MCP`, `docs/ARCHITECTURE.md :: MCP/tools`, `docs/ROADMAP.md :: External-connectivity (MCP) sequencing`, `docs/MIMER_MCP_CLIENT_ADAPTER/README.md :: Relationship to GitHub Issues`, and `docs/MIMER_MCP_CLIENT_ADAPTER/PARENT_FEATURE_ISSUE.md :: State`

## How to Verify (Pre-Merge)

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/mcp/test_mimer_server.py tests/mcp/test_mimer_server_transport.py tests/mcp/test_mimer_server_security.py tests/mcp/test_mimer_server_smoke.py`
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/api/test_ask_contract.py tests/api/test_capture_inbox_api.py tests/api/test_search_canonical_substrate.py tests/api/test_artifact_note_read_api.py tests/api/test_health_contract_api.py`
- Run the documented test-channel/client smoke, attach its redacted receipt to the parent, and
  verify the recorded head SHA matches the tested runtime.
- Review every doc-target AC and the parent's child ledger before recommending closure.

## Out of Scope

- Expanding the contracted tool set to make a client pass.
- Claiming support for an untested client, changing third-party client configuration, or storing
  credentials in the repo.
- Direction C consumption, generic remote discovery, performance scaling, or new Mimer APIs.

## Restart / Durability Posture

Compatibility evidence is durable on GitHub and in merged docs; the adapter itself remains
stateless. The test deliberately destroys process-local state between calls. A lost response around
capture is reported as ambiguous and never “repaired” by an automatic replay.

## Related Docs

- `docs/MIMER_MCP_CLIENT_ADAPTER/README.md`
- `docs/contracts/MIMER_CLIENT_CONTRACT.md`
- `docs/ARCHITECTURE.md`
- `docs/STATUS.md`
- `docs/ROADMAP.md`

## Related GitHub Issues

Create the final child only after MIMER-MCP-02 and MIMER-MCP-03 merge. TCD hint: **Codex / high**
(Sonnet / high is also acceptable) because the work is integration- and evidence-heavy rather than
architecture-generative; escalate to xhigh on protocol/client divergence or ambiguous capture
behavior. Require the normal CI gate plus architecture/security review before parent closure.

