---
name: Prove configured macOS executor paths and Luna acceptance
description: Validate VLAN-primary and Tailscale-fallback Product access to the designated macOS Codex executor and produce a provider-neutral, sanitized acceptance receipt.
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

Prove that the Product runtime reaches the designated macOS Codex CLI executor over the shared VLAN first,
uses configured private Tailscale only after a typed, recoverable VLAN path failure before
completion, and
reports required Product capabilities through provider-neutral health. Produce a sanitized receipt
before any release-channel rollout.

Issue #5624 now carries this VLAN-first, Luna, provider-neutral v3 acceptance scope. This document
records the accepted target and does not itself authorize host/network activation or change GitHub
state. The offline receipt validator is tracked separately in #5694; delivering that validator does
not constitute live host acceptance.

## What This Task Does

After separate operator-authorized host/network activation, inspect configured VLAN and Tailscale
path profiles, both paths' caller/channel/action authorization, loopback-only executor backend,
`codex --version`, and `codex login status` from the service's interactive login session. From the
Product Linux runtime, run a bounded Luna completion through the VLAN path; induce or safely
simulate a typed, recoverable VLAN path failure and prove the configured Tailscale path reaches the
same executor and exact route; prove common policy denial, malformed/mismatched preflight, and
missing capability do not fail over; inspect required capability health; and prove an ambiguous
completion does not retry.

The receipt contains logical executor and path-profile IDs, path selection reason, capability IDs
and statuses, Codex version/auth status, and route/catalog provenance. It contains no prompts,
concrete endpoint or machine identity, raw authorization claims, credentials, environment, or raw
CLI output. A passed receipt binds both a successful VLAN-primary completion and a successful
Tailscale fallback preflight after a typed VLAN failure to the same exact route; the fallback
preflight itself must not dispatch a completion. An incomplete receipt may report only the path
profiles actually configured and must identify missing required paths. No Ollama installation,
model, or fallback is required for Luna acceptance.

## Concretely

The operator runs the acceptance command from the Product-to-executor path and receives a
versioned `model_access_router.macos_executor_acceptance.v3` receipt with VLAN-primary reachability,
Tailscale-fallback reachability, common channel/action authorization results, loopback-bind result,
Codex CLI version and login-status enum, Luna model/effort, selected logical path, provider-neutral
capability health, unsupported-capability refusal with no-completion evidence, instruction-channel
mapping id, ambiguous-completion no-retry evidence, and secret-redaction result.

## Acceptance Criteria

- [ ] Receipt proves the configured VLAN path is selected first and the backend remains
  loopback-only.
  - Verify: runtime receipt: model_access_router.macos_executor_acceptance.v3
- [ ] Receipt proves typed VLAN `PATH_UNAVAILABLE`, `CONNECT_TIMEOUT`, `PREFLIGHT_TIMEOUT`, or
  `PATH_AUTHENTICATION_FAILED` selects configured Tailscale before completion for the same
  executor, exact Luna route, reasoning effort, and capability intent. Common Product policy
  denial, malformed request, route mismatch, missing path configuration, and missing capability
  fail closed without trying Tailscale.
  - Verify: runtime receipt: model_access_router.macos_executor_acceptance.v3
- [ ] Both path profiles enforce the same common Product channel and operation-specific action
  authorization. A common-policy denial is terminal even when another path is reachable; the
  transport-specific ingress authentication is tested separately under the typed path-failover
  rule.
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
- [ ] An ambiguous completion outcome causes no second completion and no path/provider retry.
  - Verify: runtime receipt: model_access_router.macos_executor_acceptance.v3
- [ ] Receipt validation rejects credentials, endpoint URLs, raw path identities/authorization
  claims, full environment, prompts, raw CLI output, and duplicate JSON object keys at any nesting
  level in either input file; invalid CLI arguments produce only a safe error identifier and do
  not echo argument values.
  - Verify: `tests/model_access/test_macos_executor_acceptance_receipt.py::test_acceptance_receipt_is_route_bound_and_secret_free`
- [ ] Missing path, authorization, interactive CLI auth, or required capability leaves acceptance
  incomplete without changing host/network configuration or downloading a model.
  - Verify: `tests/model_access/test_macos_executor_acceptance_receipt.py::test_missing_host_prerequisite_is_reported_without_mutation`

## How to Verify (Pre-Merge)

- Run `pytest -q tests/model_access/test_macos_executor_acceptance_receipt.py`.
- After the offline validator is delivered, validate the sanitized receipt against an independently
  prepared expected-route JSON containing the exact route, catalog snapshot hash, logical executor
  profile, and ordered path profiles. It rejects duplicate keys before schema validation so an
  earlier unsafe value cannot be shadowed by a later valid value:
  `python3 scripts/validate_macos_executor_acceptance_receipt.py --input <receipt-path> --expected-route <expected-route-path>`.
  This command only reads those two local JSON files. It does not contact or inspect a host, network,
  service, Codex CLI, Ollama, or model; an `incomplete` result is not live acceptance.
- From the Product Linux runtime and designated macOS executor, follow the checked-in
  cross-host acceptance procedure and attach only the sanitized v3 receipt. Do not include raw
  stdout, environment, keychain output, capability claims, concrete machine identity, endpoint
  values, or session files.
- The acceptance operator must hold separate authorization for any host-service, VLAN, firewall,
  or Tailscale activation; this acceptance command does not mutate those settings.
- Verify no host or network configuration changed as a side effect of read-only acceptance.

## Out of Scope

- Editing VLAN/firewall/Tailscale policy, enabling Serve, installing or starting the executor
  service, or changing host credentials/session.
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
