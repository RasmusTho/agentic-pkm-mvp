---
name: Prove VLAN-only macOS executor and Luna acceptance
description: Validate Product access to the designated macOS Codex executor over VLAN and produce a provider-neutral, sanitized acceptance receipt.
task_id: MARR-06
github_issue: 5624
source_anchor: docs/adr/ADR-0066-shared-model-access-router-and-catalogs.md :: Delivery gates
parent_capability: MODEL_ACCESS_ROUTER
prerequisites: [MARR-01, MARR-02, MARR-03, MARR-04, MARR-05, MARR-08, MARR-09, MARR-10]
depends_on: [ESTABLISH_SHARED_ROUTE_AND_PROVENANCE_CONTRACTS.md, BUILD_ADAPTER_REGISTRY_AND_CODEX_CLI_TRANSPORT.md, FORMALIZE_OLLAMA_AND_PREFLIGHT_FALLBACK.md, DISCOVER_FRESH_MODEL_CATALOGS.md, MIGRATE_PRODUCT_LLM_CALLERS.md, ADD_TAILSCALE_CODEX_EXECUTOR_TRANSPORT.md, CONFIGURE_EXECUTOR_NETWORK_PATHS.md, REPORT_CAPABILITY_HEALTH.md]
can_parallelize_with: []
---

# PROVE_CONFIGURED_MACOS_EXECUTOR_ACCEPTANCE

## Purpose

Prove that the Product runtime reaches the designated macOS Codex CLI executor over the shared VLAN
and reports required Product capabilities through provider-neutral health. VLAN is the only path in
the current Ygg profile; Tailscale configuration, Serve, and fallback evidence are not required.
Produce a sanitized receipt before any release-channel rollout.

Issue #5624 now carries this VLAN-only, Luna, provider-neutral v3 acceptance scope. This document
records the accepted target and does not itself authorize host/network activation or change GitHub
state. The offline receipt validator is tracked separately in #5694; delivering that validator does
not constitute live host acceptance. MARR-08 is a dependency for the bounded cross-host executor
API/client; its historical Tailscale transport name does not require Tailscale Serve for this VLAN
profile.

## What This Task Does

After the explicitly authorized VLAN mTLS and executor-service activation in Issue #5624, inspect
the VLAN ingress authorization and loopback-only executor backend, `codex --version`, and
`codex login status` from the service's interactive login session. From the Product Linux runtime,
first run a no-inference catalog/preflight check that verifies the exact Luna route, VLAN path, and
capability intent. Before each distinct request, refresh the catalog and exact-route no-inference
preflight. Each request is sent once; do not retry or replay an ambiguous request and do not try
another provider or path. After diagnosing the previous outcome, Issue #5624's current owner
authorization permits a new, uniquely identified acceptance request only after fresh preflight
succeeds. Also prove that common-policy denial, malformed/mismatched preflight, and missing
capability fail before inference; inspect required capability health.

The receipt contains logical executor and path-profile IDs, path selection reason, capability IDs
and statuses, Codex version/auth status, and route/catalog provenance. It contains no prompts,
concrete endpoint or machine identity, raw authorization claims, credentials, environment, or raw
CLI output. A passed receipt binds the successful completion to the exact Luna route and the sole
configured/selected path `[ygg_vlan_primary]`; path-authorization evidence names only VLAN and
`fallback_preflight` is absent. An incomplete receipt reports only configured paths and the
prerequisites that actually block acceptance. No Tailscale or Ollama installation, service, model,
health check, or fallback is required for Luna acceptance.

## Concretely

The operator runs the acceptance command from the Product-to-executor path and receives a
versioned `model_access_router.macos_executor_acceptance.v3` receipt with VLAN reachability,
VLAN channel/action authorization results, loopback-bind result,
Codex CLI version and login-status enum, Luna model/effort, selected logical path, provider-neutral
capability health, unsupported-capability refusal with no-completion evidence, instruction-channel
mapping id, ambiguous-completion no-retry evidence, and secret-redaction result.

## Acceptance Criteria

- [ ] Receipt proves the configured and selected path list is exactly `[ygg_vlan_primary]` and the
  executor backend remains loopback-only; it contains no Tailscale fallback evidence.
  - Verify: runtime receipt: model_access_router.macos_executor_acceptance.v3
- [ ] VLAN mTLS ingress and executor enforce the Product channel and operation-specific action;
  missing or caller-forged authorization fails closed.
  - Verify: runtime receipt: model_access_router.macos_executor_acceptance.v3
- [ ] Receipt records exact Codex CLI version, successful auth status from the interactive login
  session, Luna route, logical executor/path profile, and catalog hash without credential, session,
  host identity, or endpoint data.
  - Verify: runtime receipt: model_access_router.macos_executor_acceptance.v3
- [ ] Public health reports required capability IDs/statuses without requiring or exposing a named
  provider. It reports the Luna route's capabilities as available and any unsupported capability
  as unavailable; only fresh `available` satisfies a required capability and aggregate health.
  - Verify: runtime receipt: model_access_router.macos_executor_acceptance.v3
- [ ] A request requiring an unsupported capability (for example native tools on a route that does
  not support them) is rejected during no-inference preflight; the receipt proves no completion was
  dispatched and includes only a safe capability-level reason.
  - Verify: runtime receipt: model_access_router.macos_executor_acceptance.v3
- [ ] The Product caller preserves trusted-instruction and user-input channels through the executor
  using the approved versioned mapping.
  - Verify: runtime receipt: model_access_router.macos_executor_acceptance.v3
- [ ] An ambiguous completion request is never replayed or automatically retried. Every separate
  acceptance attempt follows a fresh no-inference catalog and exact-route preflight and uses the
  same Luna/Codex CLI route; no provider/path fallback occurs.
  - Verify: runtime receipt: model_access_router.macos_executor_acceptance.v3
- [ ] Receipt validation rejects credential fields, recognized credential-shaped model/version
  identifiers, endpoint URLs, host/IP identities, raw path identities/authorization claims, full
  environment, prompts, raw CLI output, and duplicate JSON object keys at any nesting level in
  either input file; invalid CLI arguments produce only a safe error identifier and do not echo
  argument values.
  - Verify: `tests/model_access/test_macos_executor_acceptance_receipt.py::test_acceptance_receipt_is_route_bound_and_secret_free`
- [ ] Missing VLAN path, authorization, interactive CLI auth, or required capability leaves acceptance
  incomplete without changing host/network configuration or downloading a model.
  - Verify: `tests/model_access/test_macos_executor_acceptance_receipt.py::test_missing_host_prerequisite_is_reported_without_mutation`

## How to Verify (Pre-Merge)

- Run `pytest -q tests/model_access/test_macos_executor_acceptance_receipt.py`.
- After the offline validator is delivered, validate the sanitized receipt against an independently
  prepared expected-route JSON from trusted Product route provenance, containing the exact route,
  catalog snapshot hash, logical executor profile, and exactly `[ygg_vlan_primary]`. The validator binds
  the receipt to that file but does not authenticate its producer and is not a general-purpose
  secret scanner; callers remain responsible for sanitizing both inputs. It rejects declared
  credential fields and recognized credential-shaped identifiers and rejects duplicate keys before
  schema validation so an earlier unsafe value cannot be shadowed by a later valid value:
  `python3 scripts/validate_macos_executor_acceptance_receipt.py --input <receipt-path> --expected-route <expected-route-path>`.
  This command only reads those two local JSON files. It does not contact or inspect a host, network,
  service, Codex CLI, Ollama, or model; an `incomplete` result is not live acceptance.
- From the Product Linux runtime and designated macOS executor, follow the checked-in
  cross-host acceptance procedure and attach only the sanitized v3 receipt. Run the independent
  no-inference catalog and exact-route preflight before each distinct acceptance request; never
  repeat an earlier ambiguous request or auto-retry a request that becomes ambiguous. Do not include raw
  stdout, environment, keychain output, capability claims, concrete machine identity, endpoint
  values, or session files.
- The acceptance command itself is read-only. VLAN mTLS and executor-service activation are covered
  by the explicit, bounded authorization in Issue #5624; no Tailscale or firewall change is needed.
- Verify no host or network configuration changed as a side effect of read-only acceptance.

## Out of Scope

- Tailscale/Serve configuration, firewall changes, or changing host credentials/session.
- Downloading or updating models, provisioning provider credentials, or changing subscription/account
  settings.
- Ollama health or fallback as a Luna acceptance prerequisite.
- Production deployment or release-pointer mutation.

## Related Docs

- docs/adr/ADR-0064-model-access-substrate.md
- docs/adr/ADR-0066-shared-model-access-router-and-catalogs.md
- docs/LLM.md
- docs/RELEASE_CHANNELS/README.md
- docs/MODEL_ACCESS_ROUTER/README.md
- docs/MODEL_ACCESS_ROUTER/CONFIGURE_EXECUTOR_NETWORK_PATHS.md
- docs/MODEL_ACCESS_ROUTER/REPORT_CAPABILITY_HEALTH.md
