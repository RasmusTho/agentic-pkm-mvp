---
name: Ratify MCP Client Adapter
description: Admit a constituent-owned Mimer MCP adapter through the ADR and client-contract authority path
task_id: MIMER-MCP-01
source_anchor: "docs/audits/APP_MCP_CONNECTIVITY_2026-07-07.md :: §5 Build list — B1"
parent_capability: Mimer MCP Client Adapter
prerequisites: []
depends_on: []
can_parallelize_with: []
---

# Ratify MCP Client Adapter

## Purpose

Current authority explicitly excludes MCP from Mimer's client transports. This task makes the
architecture decision that must exist before implementation can truthfully begin.

## What This Task Does

- Authors a superseding ADR that revisits ADR-0047's concrete-server trigger and ADR-0056's fixed
  transport set.
- Ratifies Mimer/constituent ownership, protocol-tier status, supported wire transport(s), trust
  posture, and the exact operation boundary.
- Updates the Mimer client contract and architecture references without claiming a running server.
- Resolves whether the internal tool-policy contract is unaffected or needs a narrow clarification;
  it never conflates the external server with the internal ToolProvider.

## Concretely

```text
before: transports = HTTP API + direct filesystem; MCP deferred
after:  transports = HTTP API + direct filesystem + ratified MCP adapter
        MCP capture -> existing governed capture operation -> existing receipt
        internal app/mcp/vault_tools.py remains non-transport plumbing
```

## Why This Matters

Implementing first would silently overturn two accepted ADRs and leave server ownership, exposure,
and authority ambiguous. A durable decision makes later code review mechanical rather than
re-litigating topology in every PR.

## Acceptance Criteria

- [ ] A new ADR explicitly supersedes/reconciles ADR-0047 and ADR-0056 for this concrete adapter,
      including constituent ownership, protocol-tier status, selected transport(s), binding/auth
      posture, and consequences.
  Verify: doc writeback at `docs/adr/ :: Mimer MCP adapter decision`
- [ ] The Mimer client contract admits MCP as an additional adapter while preserving the three hard
      authority invariants, both existing transports, and ambiguous-write handling.
  Verify: doc writeback at `docs/contracts/MIMER_CLIENT_CONTRACT.md :: Classification and transports`
- [ ] The contracted MCP operation table contains exactly ask, governed capture, retrieve/search,
      note read, and health; it explicitly excludes generic vault write and receipt read-back.
  Verify: doc writeback at `docs/contracts/MIMER_CLIENT_CONTRACT.md :: MCP adapter surface`
- [ ] Architecture and ecosystem-federation references distinguish the external client adapter
      from the internal MCP ToolProvider and carry no shipped-server claim.
  Verify: doc writeback at `docs/ARCHITECTURE.md :: MCP/tools` and `docs/architecture/ecosystem-federation.md :: Dual-role + MCP`
- [ ] All new/changed docs are indexed and the docs index remains mechanically valid.
  Verify: `tests/architecture/test_docs_index.py::test_all_docs_are_listed_in_docs_index`

## How to Verify (Pre-Merge)

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/architecture/test_docs_index.py`
- `rg -n "MCP adapter|MCP transport|receipt read-back|vault_tools|protocol-tier" docs/adr docs/contracts/MIMER_CLIENT_CONTRACT.md docs/ARCHITECTURE.md docs/architecture/ecosystem-federation.md`
- Review the new ADR and client-contract table against every doc-target AC above and confirm no line
  claims implementation exists.

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

Create one ready child issue under the parent. TCD hint: **Opus / xhigh** (or equivalent
frontier architecture capability) because this changes an external protocol/security boundary and
two durable decisions; architecture-quality review is mandatory.
