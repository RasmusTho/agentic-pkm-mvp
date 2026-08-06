---
name: Package and Harden Mimer MCP Transport
description: Package the owner-accepted MCP wire transport with explicit trust enforcement, configuration, lifecycle, and health
task_id: MIMER-MCP-03
source_anchor: "docs/MIMER_MCP_CLIENT_ADAPTER/README.md :: Cross-Task Invariants / Interaction Safety"
parent_capability: Mimer MCP Client Adapter
prerequisites: [MIMER-MCP-01]
depends_on: [RATIFY_MCP_CLIENT_ADAPTER.md]
can_parallelize_with: [Expose Governed Mimer Tools Over MCP]
---

# Package and Harden Mimer MCP Transport

## Purpose

Turn the owner-accepted adapter boundary into a deterministic, installable process without widening the
current LAN/loopback/tailnet trust envelope or relying on shell-history startup.

## What This Task Does

- Adds the owner-selected MCP SDK/runtime dependency and a stable executable entrypoint.
- Implements only the transport(s), bind defaults, authentication, and origin/trust checks selected
  by MIMER-MCP-01.
- Adds typed configuration with fail-closed validation and secret-safe diagnostics.
- Adds deterministic liveness/readiness, structured logs, graceful shutdown, and supervised restart
  behavior.
- Adds packaging/deployment documentation that contains no concrete private endpoint or credential.

## Concretely

```text
python -m app.mimer_mcp --transport <owner-selected-value>
  -> validate typed config
  -> refuse an unapproved bind/auth posture
  -> start MCP lifecycle
  -> health/readiness identify configured transport without exposing secrets
```

## Why This Matters

A correct tool handler can still be unsafe if packaging exposes it broadly, silently disables
authentication, leaks secrets, or leaves an unsupervised process that disappears after restart.

## Acceptance Criteria

- [ ] The packaged entrypoint negotiates the owner-selected MCP transport and shuts down cleanly without
      orphaned listeners or requests.
  Verify: `tests/mcp/test_mimer_server_transport.py::test_transport_lifecycle_negotiates_and_shuts_down_cleanly`
- [ ] Typed configuration rejects unsupported transports, unapproved network exposure, missing
      required auth, and malformed secrets before listener startup.
  Verify: `tests/mcp/test_mimer_server_security.py::test_invalid_or_unsafe_configuration_fails_before_bind`
- [ ] The production request path rejects an untrusted or unauthenticated caller according to the
      owner-accepted posture; header-only/unit-guard tests are insufficient.
  Verify: `tests/mcp/test_mimer_server_security.py::test_transport_rejects_untrusted_production_call`
- [ ] Health/readiness and logs identify transport state and dependency degradation without exposing
      credentials; a supervised restart restores service without replaying in-flight capture.
  Verify: `tests/mcp/test_mimer_server_transport.py::test_supervised_restart_restores_service_without_replay`
- [ ] Dependency metadata, lock surfaces, executable packaging, and operator docs remain consistent.
  Verify: `tests/architecture/test_requirements_consistency.py::test_pyproject_and_requirements_are_consistent` and doc writeback at `docs/OPERATIONS.md :: Mimer MCP adapter`

## How to Verify (Pre-Merge)

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/mcp/test_mimer_server_transport.py tests/mcp/test_mimer_server_security.py`
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/architecture/test_requirements_consistency.py`
- Start the executable against an isolated test runtime, run its health probe, stop it, and confirm
  the listener exits; repeat once under the documented supervisor fixture.
- `ruff check app tests`

## Out of Scope

- Tool semantics owned by MIMER-MCP-02.
- Concrete private host bindings, credentials, desktop-client edits, or operator fleet cutover.
- A shared ecosystem registry, dynamic remote discovery, or support for transports not selected in
  the owner-accepted ADR-0061 decision.

## Restart / Durability Posture

The transport is stateless and restartable. Configuration is durable only in existing typed
operator settings/secret surfaces; credentials never enter logs or receipts. Connections and
in-flight responses do not survive restart. No capture request is durably queued or replayed by the
transport, preventing a restart from duplicating an append whose acknowledgement was lost.

## Related Docs

- `docs/contracts/MIMER_CLIENT_CONTRACT.md`
- `docs/SECURITY_TRUST_BOUNDARIES.md`
- `docs/OPERATIONS.md`
- `docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md`
- `docs/contracts/TOOL_POLICY_AND_MCP_ADAPTER_CONTRACT.md`

## Related GitHub Issues

Issue #3369 stays blocked until ADR-0061 is Accepted and links the explicit owner-decision receipt;
merging the spec or a Proposed ADR is insufficient. It may then run in parallel with MIMER-MCP-02
under an isolated worktree. TCD hint: **Codex / xhigh** because this is security-sensitive external transport
and deployment work; require security review and production-call-site trust tests.
