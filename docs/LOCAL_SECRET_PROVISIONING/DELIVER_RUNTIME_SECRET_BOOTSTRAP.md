---
name: Deliver Runtime Secret Bootstrap
task_id: HSP-02
source_anchor: docs/LOCAL_SECRET_PROVISIONING/README.md :: Cross-task invariants
parent_capability: Local Secret Provisioning
prerequisites: [HSP-01]
depends_on: [HSP-01]
can_parallelize_with: []
---

State: Authored task specification (future-state; child issue not yet filed)

# Deliver Runtime Secret Bootstrap

## Purpose

Implement the approved Keychain-backed bootstrap and integrate it only where a channel deploy needs
it. The runtime must not need Keychain access itself after startup, and no ordinary configuration file
may become a second source of truth.

## What this task does

1. Resolve declared Keychain identifiers for an explicit `{channel, consumer}` pair.
2. Materialize only that consumer's values in a temporary owner-only runtime surface, launch the
   intended process, then remove the material on normal exit and failure.
3. Redact values from diagnostics, deploy receipts, and failure messages while retaining logical
   identifiers and remediation instructions.
4. Add dev-channel integration for `heimdal-capture-watch`; do not touch test, prod, stable, or
   provider-routing behavior.

## Acceptance criteria

- [ ] A declared dev consumer receives only its allowlisted runtime values; unrelated values are
      unavailable.
      Verify: `tests/ops/test_host_secret_bootstrap.py::test_consumer_gets_only_allowlisted_values`
- [ ] Missing, malformed, or permission-denied Keychain entries fail before process startup and leak
      no value.
      Verify: `tests/ops/test_host_secret_bootstrap.py::test_missing_or_malformed_secret_fails_closed`
- [ ] Temporary material is owner-readable only and removed on success and controlled failure.
      Verify: `tests/ops/test_host_secret_bootstrap.py::test_runtime_secret_file_is_mode_0600_and_cleaned_up`
- [ ] `heimdal-capture-watch` receives `HEIMDAL_RAW_STORE_KEY` through this path without a repository
      secret or changed product code.
      Verify: `tests/ops/test_host_secret_bootstrap.py::test_capture_watch_uses_bootstrap_not_tracked_env`

## Out of scope

Actual capture-folder/key provisioning and dev deployment verification (#3830), key rotation,
multi-host sharing, CI, and 1Password.

## How to verify

`pytest -q tests/ops/test_host_secret_bootstrap.py`
