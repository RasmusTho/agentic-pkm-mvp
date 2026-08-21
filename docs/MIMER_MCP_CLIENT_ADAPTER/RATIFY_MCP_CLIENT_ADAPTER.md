---
name: Ratify Accepted MCP Client Adapter Decision
description: Apply the owner's accepted A2/B1/C1 topology, transport, and authentication decision without claiming implementation
task_id: MIMER-MCP-01
source_anchor: "docs/audits/APP_MCP_CONNECTIVITY_2026-07-07.md :: §5 Build list — B1"
parent_capability: Mimer MCP Client Adapter
prerequisites: []
depends_on: []
can_parallelize_with: []
---

# Ratify Accepted MCP Client Adapter Decision

## Purpose

ADR-0061 was published as a Proposed decision and the owner has now accepted its recommended
A2/B1/C1 bundle in the durable #3371 receipt. This task applies that decision exactly at the docs
contract layer; it does not implement or claim a running server.

## What This Task Does

- Preserves ADR-0061's considered alternatives and records `State: Accepted` with the linked
  2026-08-21 owner-decision receipt.
- Selects exactly A2 constituent-owned sidecar topology, B1 stdio-only v1 transport, and C1 inherited
  trust posture with no network listener or new authentication.
- Updates the Mimer client contract and narrow architecture/ecosystem references while preserving
  the fixed five-operation boundary and every authority/ambiguous-write invariant.
- Clarifies that the external producer-side adapter is distinct from the internal consumer-side
  ToolProvider; no runtime or downstream lifecycle claim is made.

## Concretely

```text
decision: owner receipt on #3371 accepts A2 + B1 + C1
contract: ADR-0061 State=Accepted
          MCP = constituent-owned stdio sidecar -> governed HTTP API
          tools = ask + capture + retrieve/search + note-read + health
excluded: network listener + new auth + generic vault write + receipt read-back + direct-FS fallback
runtime:  not implemented or operationally accepted by this task
```

## Why This Matters

The linked receipt makes the previously owner-gated decision mechanical to apply. Keeping admission
truth separate from runtime truth prevents the accepted design from being mistaken for a shipped
server or an implicit network/auth expansion.

## Acceptance Criteria

- [ ] ADR-0061 preserves the Proposed-stage alternatives and recommendation while recording the
      accepted A2/B1/C1 decision and linked owner receipt.
  Verify: doc writeback at `docs/adr/ADR-0061-mimer-mcp-client-adapter.md :: Options and recommendation`
- [ ] The proposal fixes the invariant operation boundary—ask, governed capture, retrieve/search,
      note read, and health—and explicitly excludes generic vault write and receipt read-back across
      every option.
  Verify: doc writeback at `docs/adr/ADR-0061-mimer-mcp-client-adapter.md :: Invariants across all options`
- [ ] The explicit owner ruling is linked from the Accepted ADR before it claims precise
      supersession/reconciliation of ADR-0047 and ADR-0056.
  Verify: doc writeback at `docs/adr/ADR-0061-mimer-mcp-client-adapter.md :: Owner decision receipt`
- [ ] The Mimer client contract reflects exactly A2/B1/C1 while preserving its authority and
      ambiguous-write invariants and stating that no server is shipped.
  Verify: doc writeback at `docs/contracts/MIMER_CLIENT_CONTRACT.md :: Classification and transports`
- [ ] Architecture and ecosystem-federation references distinguish the external client adapter
      from the internal MCP ToolProvider and carry no shipped-server claim.
  Verify: doc writeback at `docs/ARCHITECTURE.md :: MCP/tools` and `docs/architecture/ecosystem-federation.md :: Dual-role + MCP`
- [ ] All new/changed docs are indexed and the docs index remains mechanically valid.
  Verify: `tests/architecture/test_docs_index.py::test_all_docs_are_listed_in_docs_index`

## How to Verify (Pre-Merge)

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/architecture/test_docs_index.py`
- `rg -n "MCP adapter|MCP transport|receipt read-back|vault_tools|protocol-tier" docs/adr docs/contracts/MIMER_CLIENT_CONTRACT.md docs/ARCHITECTURE.md docs/architecture/ecosystem-federation.md`
- Confirm `docs/adr/ADR-0061-mimer-mcp-client-adapter.md` is `State: Accepted`, links the exact
  #3371 receipt, and selects only A2/B1/C1.
- Confirm no changed doc claims a shipped server or enables Streamable HTTP/per-device auth.

## Out of Scope

- MCP server code, dependencies, transport processes, service units, or client configuration.
- Reworking the existing HTTP API, direct-filesystem permission, or internal MCP ToolProvider.
- Direction A and Direction C work.

## Related Docs

- `docs/adr/ADR-0047-mcp-topology-federation-stance.md`
- `docs/adr/ADR-0056-mimer-client-contract-and-transports.md`
- `docs/contracts/MIMER_CLIENT_CONTRACT.md`
- `docs/architecture/ecosystem-federation.md`
- `docs/contracts/TOOL_POLICY_AND_MCP_ADAPTER_CONTRACT.md`

## Related GitHub Issues

Issue #3371 carries the explicit owner-decision receipt and governs this accepted docs writeback.
Use high-assurance architecture capability to apply the selected decision exactly;
architecture-quality review remains mandatory. Do not change #3368/#3369 lifecycle state until
this contract is merged and independently reconciled as ready.
