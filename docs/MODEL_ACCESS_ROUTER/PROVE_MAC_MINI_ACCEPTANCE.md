---
name: Prove Designated macOS Executor Profile and Acceptance
description: Validate the private Product-to-Codex executor route, host-local subscription, and Ollama fallback posture, producing one sanitized acceptance receipt.
task_id: MARR-06
github_issue: 5624
source_anchor: docs/adr/ADR-0066-shared-model-access-router-and-catalogs.md :: Delivery gates
parent_capability: MODEL_ACCESS_ROUTER
prerequisites: [MARR-01, MARR-02, MARR-03, MARR-04, MARR-05, MARR-08]
depends_on: [ESTABLISH_SHARED_ROUTE_AND_PROVENANCE_CONTRACTS.md, BUILD_ADAPTER_REGISTRY_AND_CODEX_CLI_TRANSPORT.md, FORMALIZE_OLLAMA_AND_PREFLIGHT_FALLBACK.md, DISCOVER_FRESH_MODEL_CATALOGS.md, MIGRATE_PRODUCT_LLM_CALLERS.md, ADD_TAILSCALE_CODEX_EXECUTOR_TRANSPORT.md]
can_parallelize_with: []
---

# PROVE_DESIGNATED_MACOS_EXECUTOR_ACCEPTANCE

## Purpose

Prove that the shipped cross-host route works using the existing host-local Codex auth and installed Ollama models. The receipt is the acceptance gate before any release-channel rollout. This is a read-only acceptance task; it does not itself change tailnet policy, enable Serve, install/start a host service, or modify host credentials.

## What This Task Does

After a separate operator-authorized host/tailnet activation is complete, inspect Tailscale/Serve profile readiness, the app-capability grant readback, loopback-only backend binding, `codex --version`, `codex login status` from the service's interactive login session, the account-scoped model catalog, Ollama host health, and already-present model metadata. From the Product Linux runtime, run the smallest bounded acceptance calls required by the parent: Luna via the remote route, compatible preflight fallback, and correct tool-capability refusal. Exercise the trusted-instruction/user separation using only a fixed non-sensitive test prompt. The receipt contains exact logical route metadata and status only; no prompt contents, capability claim, credential values, endpoint URL/secrets, environment variables, CODEX_HOME, Tailscale identity, concrete machine identity, or raw session output.

Host-local PATH, CODEX_HOME, Codex subscription session, and Ollama endpoint settings remain outside Git. Do not download a model or change auth to make the receipt pass. If a required model is absent, record the unavailable state and leave the parent blocked.

## Concretely

The operator runs the acceptance command from the Product-to-executor path and receives a versioned `model_access_router.macos_executor_acceptance.v2` receipt with Tailscale/Serve profile status, authorized-caller result, loopback-bind result, exact Codex CLI version, login-status enum, Luna model/effort/transport, instruction-channel mapping id, Ollama health/model probe, preflight fallback evidence, rejected tool route, and secret-redaction result.

## Why This Matters

Fake-provider tests cannot establish that this host's subscription session, CLI version, and local Ollama installation are usable. A receipt proves the actual target environment without moving secrets into the repository.

## Acceptance Criteria

- [ ] Receipt proves a policy-authorized Product Linux caller reaches only the Serve endpoint, the backend is loopback-only, and requests fail without the scoped app-capability grant.
  - Verify: runtime receipt: model_access_router.macos_executor_acceptance.v2
- [ ] Receipt records exact Codex CLI version, successful auth status from the interactive login session, Luna route, transport, logical executor profile, and catalog hash without credential/session/host identity data.
  - Verify: runtime receipt: model_access_router.macos_executor_acceptance.v2
- [ ] The already-installed Ollama host/model is healthy and its capabilities are recorded without claiming undeclared tools.
  - Verify: runtime receipt: model_access_router.macos_executor_acceptance.v2
- [ ] A compatible task demonstrates preflight-only fallback, an ambiguous post-send timeout makes no second call, and a tool route is refused when Ollama lacks required native tools.
  - Verify: runtime receipt: model_access_router.macos_executor_acceptance.v2
- [ ] The real Product caller preserves the trusted-instruction and user-input channels through the executor using the approved versioned mapping.
  - Verify: runtime receipt: model_access_router.macos_executor_acceptance.v2
- [ ] Receipt validation rejects credentials, endpoint URLs/secrets, raw Tailscale identities/capability claims, full environment, prompt, and raw CLI output.
  - Verify: `tests/model_access/test_macos_executor_acceptance_receipt.py::test_acceptance_receipt_is_route_bound_and_secret_free`
- [ ] Missing grant, Serve capability support, interactive CLI auth, or local model leaves acceptance incomplete without changing tailnet/host configuration or downloading a model.
  - Verify: `tests/model_access/test_macos_executor_acceptance_receipt.py::test_missing_host_prerequisite_is_reported_without_mutation`

## How to Verify (Pre-Merge)

- Run pytest -q tests/model_access/test_macos_executor_acceptance_receipt.py.
- From the Product Linux runtime and designated macOS executor, follow the checked-in cross-host acceptance procedure and attach only the sanitized receipt; do not include raw stdout, environment, keychain output, capability claims, concrete machine identity, or session files.
- The acceptance operator must hold separate authorization for any host-service or tailnet-policy activation; the acceptance command itself must not mutate them.
- Verify no host configuration, tailnet policy, or repository credential files changed as a side effect of read-only acceptance.

## Out of Scope

- Provisioning or rotating provider credentials, subscription changes, changing CODEX_HOME, or committing host-local config.
- Editing tailnet policy, applying Tailscale tags, enabling Serve, installing/starting the executor service, or changing host firewall/listener configuration. Those require a separate explicitly authorized operational step before this read-only acceptance can run.
- Downloading or updating Ollama models.
- Production deployment or release-pointer mutation.

## Related Docs

- docs/adr/ADR-0064-model-access-substrate.md
- docs/adr/ADR-0066-shared-model-access-router-and-catalogs.md
- docs/LLM.md
- docs/RELEASE_CHANNELS/README.md
- docs/MODEL_ACCESS_ROUTER/README.md

## Related GitHub Issues

Created from this specification; issue number is written here when filed.
