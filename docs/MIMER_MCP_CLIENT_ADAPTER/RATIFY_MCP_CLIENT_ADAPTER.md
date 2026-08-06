---
name: Prepare MCP Client Adapter Decision
description: Draft the MCP topology, transport, and authentication decision for explicit owner ruling before any adapter is admitted
task_id: MIMER-MCP-01
source_anchor: "docs/audits/APP_MCP_CONNECTIVITY_2026-07-07.md :: §5 Build list — B1"
parent_capability: Mimer MCP Client Adapter
prerequisites: []
depends_on: []
can_parallelize_with: []
---

# Prepare MCP Client Adapter Decision

## Purpose

Current authority explicitly excludes MCP from Mimer's client transports, and only D1/D2—not MCP
topology, wire transport, or authentication—have been owner-ruled. This task prepares a decision
proposal and then waits for the owner's explicit receipt; it does not autonomously make the ruling.

## What This Task Does

- Drafts `docs/adr/ADR-0061-mimer-mcp-client-adapter.md` with `State: Proposed`, revisiting
  ADR-0047's concrete-server trigger and ADR-0056's fixed transport set.
- Presents explicit alternatives, consequences, and a reasoned recommendation for server ownership,
  protocol-tier topology, supported wire transport(s), authentication/trust posture, and the exact
  operation boundary.
- Leaves current authority and the Mimer client contract unchanged until an owner-decision receipt
  accepts one option. Only then may the ADR become Accepted and record supersession precisely.
- Resolves whether the internal tool-policy contract is unaffected or needs a narrow clarification;
  it never conflates the external server with the internal ToolProvider.

## Concretely

```text
current: transports = HTTP API + direct filesystem; MCP deferred
proposal: ADR-0061 State=Proposed
          options(topology, wire transport, auth) + consequences + recommendation
gate:     owner-decision receipt on #3371
accepted path only: update ADR state/supersession + client contract to the ruled option
```

## Why This Matters

Implementing first—or letting an agent label its own recommendation Accepted—would silently
overturn two accepted ADRs and usurp an explicitly deferred owner choice. A durable proposal plus
owner receipt makes later code review mechanical without fabricating authority.

## Acceptance Criteria

- [ ] ADR-0061 exists in Proposed state and enumerates topology, wire-transport, and authentication
      alternatives, consequences, and a recommendation without claiming acceptance or supersession.
  Verify: doc writeback at `docs/adr/ADR-0061-mimer-mcp-client-adapter.md :: Options and recommendation`
- [ ] The proposal fixes the invariant operation boundary—ask, governed capture, retrieve/search,
      note read, and health—and explicitly excludes generic vault write and receipt read-back across
      every option.
  Verify: doc writeback at `docs/adr/ADR-0061-mimer-mcp-client-adapter.md :: Invariants across all options`
- [ ] The explicit owner ruling is recorded on #3371 and linked from the ADR before its state becomes
      Accepted or it claims to supersede/reconcile ADR-0047/ADR-0056.
  Verify: owner-decision receipt on GitHub Issue #3371 linked from `docs/adr/ADR-0061-mimer-mcp-client-adapter.md :: Owner decision receipt`
- [ ] Only after an accepting owner receipt, the Mimer client contract reflects exactly the selected
      topology/transport/auth option while preserving its authority and ambiguous-write invariants.
  Verify: doc writeback at `docs/contracts/MIMER_CLIENT_CONTRACT.md :: Classification and transports` plus the linked owner-decision receipt on #3371
- [ ] Architecture and ecosystem-federation references distinguish the external client adapter
      from the internal MCP ToolProvider and carry no shipped-server claim.
  Verify: doc writeback at `docs/ARCHITECTURE.md :: MCP/tools` and `docs/architecture/ecosystem-federation.md :: Dual-role + MCP`
- [ ] All new/changed docs are indexed and the docs index remains mechanically valid.
  Verify: `tests/architecture/test_docs_index.py::test_all_docs_are_listed_in_docs_index`

## How to Verify (Pre-Merge)

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/architecture/test_docs_index.py`
- `rg -n "MCP adapter|MCP transport|receipt read-back|vault_tools|protocol-tier" docs/adr docs/contracts/MIMER_CLIENT_CONTRACT.md docs/ARCHITECTURE.md docs/architecture/ecosystem-federation.md`
- Confirm `docs/adr/ADR-0061-mimer-mcp-client-adapter.md` stays `State: Proposed` and contains no
  superseding/Accepted claim unless the linked #3371 owner-decision receipt exists.
- Review the selected client-contract writeback against that receipt, if and only if the owner has
  accepted an option; otherwise confirm the current contract is unchanged.

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

Issue #3371 remains **`agent:needs-human` after the specification merges**. An Opus/xhigh (or
equivalent frontier architecture capability) may draft alternatives, consequences, and a
recommendation to minimize owner review time, but it cannot choose for the owner or mark ADR-0061
Accepted. After the explicit owner receipt, use the same high-assurance architecture capability to
apply the selected decision exactly; architecture-quality review remains mandatory.
