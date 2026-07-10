---
name: Expose Governed Mimer Tools Over MCP
description: Implement the exact MCP tool surface by delegating to existing Mimer client operations and preserving governed receipts
task_id: MIMER-MCP-02
source_anchor: "docs/MIMER_MCP_CLIENT_ADAPTER/README.md :: Capability-Level Acceptance Criteria"
parent_capability: Mimer MCP Client Adapter
prerequisites: [MIMER-MCP-01]
depends_on: [RATIFY_MCP_CLIENT_ADAPTER.md]
can_parallelize_with: [Package and Harden Mimer MCP Transport]
---

# Expose Governed Mimer Tools Over MCP

## Purpose

Provide MCP clients the useful Mimer surface without inventing a second application API or
weakening the governed capture path.

## What This Task Does

- Adds a server/tool module that declares the exact owner-accepted tools and schemas.
- Delegates ask, retrieve/search, note-read, and health to their existing client-contract
  operations.
- Delegates capture to the existing governed capture operation and returns its receipt envelope
  unchanged.
- Maps validation, timeout, unavailable, ambiguous-write, WriteGuard, vault-selection, and index-lag
  outcomes into legible MCP results/errors.
- Keeps the semantic adapter independently testable from the chosen process/wire packaging.

## Concretely

```text
tools/list -> [mimer.ask, mimer.capture, mimer.retrieve, mimer.read_note, mimer.health]
mimer.capture({text, trace_id?})
  -> governed HTTP/client operation
  -> {outcome, note_path, trace_id, governed_write, ingest_warning, ...}
```

No tool calls `app/mcp/vault_tools.py`, opens the vault, or retries an ambiguous append.

## Why This Matters

The adapter is the authority chokepoint. A superficially convenient direct write, fabricated
acknowledgement, or swallowed error would let MCP bypass guarantees that existing clients must obey.

## Acceptance Criteria

- [ ] Tool discovery exposes exactly the contracted tool names and JSON schemas, with no generic
      vault-write or receipt-readback tool.
  Verify: `tests/mcp/test_mimer_server.py::test_server_exposes_exact_contracted_tool_set`
- [ ] Ask, retrieve/search, note-read, and health delegate to existing client operations and preserve
      their result and error semantics.
  Verify: `tests/mcp/test_mimer_server.py::test_read_tools_delegate_to_existing_client_contract`
- [ ] Capture invokes the production governed capture call path and returns PolicyDecision,
      DecisionToken, AuthorityReceipt, trace, and ingest warning without fabrication or loss.
  Verify: `tests/mcp/test_mimer_server.py::test_capture_preserves_governed_receipt_at_production_callsite`
- [ ] WriteGuard denial, vault-selection failure, validation failure, timeout, and
      `not_acknowledged` remain legible failures; none triggers filesystem fallback or blind retry.
  Verify: `tests/mcp/test_mimer_server.py::test_capture_failures_never_retry_or_fallback_to_filesystem`
- [ ] The external server imports neither internal vault tooling nor orchestrator execution as a
      substitute transport.
  Verify: `tests/architecture/test_mimer_mcp_server_boundaries.py::test_external_server_does_not_import_internal_vault_tools`

## How to Verify (Pre-Merge)

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/mcp/test_mimer_server.py tests/architecture/test_mimer_mcp_server_boundaries.py`
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/api/test_ask_contract.py tests/api/test_capture_inbox_api.py tests/api/test_search_canonical_substrate.py tests/api/test_artifact_note_read_api.py tests/api/test_health_contract_api.py`
- `ruff check app tests`
- Run the full `pytest -q -m "not pg"` suite because the adapter touches an authority-bearing write
  call path.

## Out of Scope

- Selecting or hosting the wire transport, service supervision, TLS, client installation, or live
  compatibility acceptance.
- Adding new API operations, receipt lookup, uuid/path resolution, or capture fields.
- Direct filesystem writes and internal orchestrator tool exposure.

## Restart / Durability Posture

The semantic adapter owns no durable state. Process loss drops only in-flight connection/request
state. It must not queue capture retries across restart: if the runtime accepted a capture before
the response was lost, the client contract's ambiguous-write verification posture applies and the
human may see an uncertain outcome rather than a duplicate hidden replay.

## Related Docs

- `docs/contracts/MIMER_CLIENT_CONTRACT.md`
- `docs/contracts/GOVERNED_WRITE_PROTOCOL.md`
- `docs/contracts/TOOL_POLICY_AND_MCP_ADAPTER_CONTRACT.md`
- `docs/CONCEPTS/TRUST_SEMANTICS_CONTRACT.md`

## Related GitHub Issues

Issue #3368 stays blocked until ADR-0058 is Accepted and links the explicit owner-decision receipt;
merging the spec or a Proposed ADR is insufficient. It may then run in parallel with MIMER-MCP-03
when file ownership is isolated. TCD hint: **Codex / xhigh** because an external protocol maps an
authority-bearing write and subtle ambiguous-failure semantics; require architecture/security
review plus the full non-Postgres suite.
