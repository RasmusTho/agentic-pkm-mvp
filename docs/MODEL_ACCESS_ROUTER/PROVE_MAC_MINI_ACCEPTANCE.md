---
name: Prove Mac Mini Host Profile and Acceptance
description: Validate the host-local Codex subscription and Ollama routes on the designated Mac mini and produce one sanitized acceptance receipt.
task_id: MARR-06
github_issue: 5624
source_anchor: docs/adr/ADR-0066-shared-model-access-router-and-catalogs.md :: Delivery gates
parent_capability: MODEL_ACCESS_ROUTER
prerequisites: [MARR-01, MARR-02, MARR-03, MARR-04, MARR-05]
depends_on: [ESTABLISH_SHARED_ROUTE_AND_PROVENANCE_CONTRACTS.md, BUILD_ADAPTER_REGISTRY_AND_CODEX_CLI_TRANSPORT.md, FORMALIZE_OLLAMA_AND_PREFLIGHT_FALLBACK.md, DISCOVER_FRESH_MODEL_CATALOGS.md, MIGRATE_PRODUCT_LLM_CALLERS.md]
can_parallelize_with: []
---

# PROVE_MAC_MINI_ACCEPTANCE

## Purpose

Prove that the shipped route works on the intended execution host using existing host-local auth and installed local models. The receipt is the acceptance gate before any release-channel rollout.

## What This Task Does

On the designated Mac mini, inspect codex --version, codex login status, the account-scoped model catalog, Ollama host health, and already-present model metadata. Run the smallest bounded acceptance calls required by the parent: Luna route, compatible preflight fallback, and correct tool-capability refusal. The receipt contains exact route metadata and status only; no prompt contents, credential values, endpoint secrets, environment variables, CODEX_HOME, or raw session output.

Host-local PATH, CODEX_HOME, Codex subscription session, and Ollama endpoint settings remain outside Git. Do not download a model or change auth to make the receipt pass. If a required model is absent, record the unavailable state and leave the parent blocked.

## Concretely

The operator runs a host-local acceptance command and receives a versioned model_access_router.mac_mini_acceptance.v1 receipt with exact Codex CLI version, login-status enum, Luna model/effort/transport, Ollama health/model probe, preflight fallback evidence, rejected tool route, and secret-redaction result.

## Why This Matters

Fake-provider tests cannot establish that this host's subscription session, CLI version, and local Ollama installation are usable. A receipt proves the actual target environment without moving secrets into the repository.

## Acceptance Criteria

- [ ] Receipt records exact Codex CLI version, successful auth status, Luna route, transport, host, and catalog hash without credential/session data.
  - Verify: runtime receipt: model_access_router.mac_mini_acceptance.v1
- [ ] The already-installed Ollama host/model is healthy and its capabilities are recorded without claiming undeclared tools.
  - Verify: runtime receipt: model_access_router.mac_mini_acceptance.v1
- [ ] A compatible task demonstrates preflight-only fallback and a tool route is refused when Ollama lacks required native tools.
  - Verify: runtime receipt: model_access_router.mac_mini_acceptance.v1
- [ ] Receipt validation rejects credentials, endpoint secrets, full environment, prompt, and raw CLI output.
  - Verify: `tests/model_access/test_mac_mini_acceptance_receipt.py::test_acceptance_receipt_is_route_bound_and_secret_free`
- [ ] Missing CLI auth or local model leaves acceptance incomplete without downloading a model or changing host credentials.
  - Verify: `tests/model_access/test_mac_mini_acceptance_receipt.py::test_missing_host_prerequisite_is_reported_without_mutation`

## How to Verify (Pre-Merge)

- Run pytest -q tests/model_access/test_mac_mini_acceptance_receipt.py.
- On the designated Mac mini, follow the checked-in host-local acceptance procedure and attach its sanitized receipt; do not include raw stdout, environment, keychain output, or session files.
- Verify no host configuration or repository credential files changed as a side effect.

## Out of Scope

- Provisioning or rotating provider credentials, subscription changes, changing CODEX_HOME, or committing host-local config.
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
