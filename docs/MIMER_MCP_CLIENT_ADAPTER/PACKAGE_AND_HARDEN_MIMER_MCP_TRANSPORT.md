---
name: Package and Harden Mimer MCP Transport
description: Package the owner-accepted stdio-only MCP sidecar with fail-closed transport configuration, lifecycle, and health
task_id: MIMER-MCP-03
source_anchor: "docs/MIMER_MCP_CLIENT_ADAPTER/README.md :: Cross-Task Invariants / Interaction Safety"
parent_capability: Mimer MCP Client Adapter
prerequisites: [MIMER-MCP-01]
depends_on: [RATIFY_MCP_CLIENT_ADAPTER.md]
can_parallelize_with: [Expose Governed Mimer Tools Over MCP]
---

# Package and Harden Mimer MCP Transport

## Purpose

Turn the owner-accepted adapter boundary into a deterministic, client-spawned stdio process without
widening the current trust envelope, adding a network listener, or relying on shell-history setup.

## What This Task Does

- Adds the owner-selected MCP SDK/runtime dependency in the standalone sidecar distribution and a stable stdio executable entrypoint.
- Implements **B1 stdio only**. It opens no network listener and accepts no Streamable HTTP, bind, origin,
  TLS, or per-device-auth configuration in v1.
- Adds typed, fail-closed configuration that rejects every non-stdio transport or network option.
- Adds deterministic health, stderr-safe structured diagnostics, graceful EOF/shutdown, and clean
  client-spawned restart behavior without durable replay.
- Adds packaging documentation with no service unit, private endpoint, credential, or startup change.

## Concretely

```text
pip install ./mimer-mcp-sidecar
mimer-mcp --transport stdio
  -> validate typed config
  -> reject every network/listener/auth option
  -> start stdio MCP lifecycle with no socket bind
  -> health identifies stdio transport without exposing private runtime configuration
```

## Why This Matters

A correct tool handler can still violate the owner decision if packaging opens a listener, admits a
second transport, treats deferred auth as implemented, leaks configuration, or replays an ambiguous
capture after a client restart.

## Acceptance Criteria

- [ ] The installed packaged entrypoint negotiates stdio and shuts down cleanly on EOF without orphaned
      requests or durable adapter state.
  Verify: `tests/mcp/test_mimer_server_transport.py::test_stdio_transport_lifecycle_negotiates_and_shuts_down_cleanly`
- [ ] Typed configuration rejects Streamable HTTP, bind/listener, TLS, and auth options before the
      adapter starts.
  Verify: `tests/mcp/test_mimer_server_security.py::test_network_transport_and_listener_configuration_are_rejected`
- [ ] The production entrypoint opens no **listening** network socket and exposes no transport other
      than stdio; the required allowlisted outbound loopback HTTP calls remain permitted and a
      unit-only config assertion is insufficient.
  Verify: `tests/mcp/test_mimer_server_security.py::test_stdio_production_entrypoint_opens_no_network_listener`
- [ ] The A2 sidecar keeps the MCP SDK outside core dependencies/imports and cannot access vault
      files, runtime credentials, authority internals, or routes outside the five-operation allowlist.
  Verify: `tests/architecture/test_mimer_mcp_sidecar_isolation.py::test_sidecar_dependency_import_filesystem_credential_and_route_boundaries`
- [ ] The standalone package is the single semantic implementation; compatibility imports do not
      duplicate behavior and preserve every #3368 schema, trace, error, receipt, and no-retry invariant.
  Verify: `tests/mcp/test_mimer_sidecar_semantic_parity.py::test_standalone_sidecar_is_single_implementation_with_v1_parity`
- [ ] Health and diagnostics identify stdio/dependency state without exposing private runtime
      configuration; a client-spawned restart during an unacknowledged capture leaves no child or
      in-flight request and does not replay.
  Verify: `tests/mcp/test_mimer_server_transport.py::test_client_spawned_restart_restores_stdio_without_replay`
- [ ] Dependency metadata, lock surfaces, executable packaging, and operator docs remain consistent.
  Verify: `tests/architecture/test_requirements_consistency.py::test_pyproject_and_requirements_are_consistent` and doc writeback at `docs/OPERATIONS.md :: Mimer MCP adapter`

## How to Verify (Pre-Merge)

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/mcp/test_mimer_server_transport.py tests/mcp/test_mimer_server_security.py`
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/architecture/test_requirements_consistency.py`
- Spawn the executable against an isolated test runtime, negotiate over stdio, run its health tool,
  stop it, and prove no listener was opened; repeat once through the client-spawn fixture.
- `ruff check app tests`

## Out of Scope

- Tool semantics owned by MIMER-MCP-02.
- Concrete private host bindings, credentials, desktop-client edits, or operator fleet cutover.
- A shared ecosystem registry, dynamic remote discovery, or support for transports not selected in
  the owner-accepted ADR-0061 decision.
- Streamable HTTP over tailnet/LAN, any network listener, and per-device authentication. B2 + C2 are
  separately gated follow-ons and must not be enabled by this task.

## Restart / Durability Posture

The transport is stateless and client-spawned. v1 has no listener credentials or service state;
configuration selects stdio and the governed loopback API only. Connections and in-flight responses
do not survive restart. No capture request is durably queued or replayed by the transport,
preventing a restart from duplicating an append whose acknowledgement was lost.

## Related Docs

- `docs/adr/ADR-0061-mimer-mcp-client-adapter.md`
- `docs/contracts/MIMER_CLIENT_CONTRACT.md`
- `docs/SECURITY_TRUST_BOUNDARIES.md`
- `docs/OPERATIONS.md`
- `docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md`
- `docs/contracts/TOOL_POLICY_AND_MCP_ADAPTER_CONTRACT.md`

## Related GitHub Issues

Issue #3369 follows the delivered #3371 ADR/client-contract writeback and #3368 semantic adapter.
It stays blocked until #3371's Accepted ADR/client-contract writeback lands; that historical gate
is now satisfied and remains recorded here for the stable decision-reference contract.
Its terminal relationship is governed verification and closure after this package's exact-head
transport, isolation, parity, and no-replay evidence is current. TCD hint: **Codex / xhigh** because
this is a security-sensitive external transport boundary; require production-entrypoint proof that
no listening network socket exists.
