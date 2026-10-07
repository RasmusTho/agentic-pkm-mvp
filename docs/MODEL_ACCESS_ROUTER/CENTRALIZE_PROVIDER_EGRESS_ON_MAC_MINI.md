---
name: Centralize Product provider egress on the Mac mini
description: Extend the bounded Mac Model Access API to execute the registry-declared Product provider routes without exposing harness or credentials to callers.
task_id: MARR-12
github_issue: 5821
source_anchor: docs/adr/ADR-0067-mac-mini-product-model-access-portal.md :: D1-D4
parent_feature: Mac mini Product model-access portal (#5819)
prerequisites: []
depends_on: []
can_parallelize_with: [Route Product chat and embeddings through the portal]
---

# Centralize Product provider egress on the Mac mini

## Purpose

The current executor API can run the accepted Luna/Codex CLI path but does not act as the egress
point for every provider in the Product registry. This task adds only the provider dispatch and
catalog behavior needed for the thin Product API; it does not move Product route-selection policy
onto the Mac.

## What This Task Does

Extend the Mac-hosted Model Access API to accept a bounded, exact Product provider/model request and
dispatch it through the host's configured adapter. The API owns provider transport and
credential resolution; callers do not select a harness, supply an endpoint, or send credentials.
Discovery covers the current provider census using provider-supplied metadata, including OpenAI and
Anthropic updates. Unsupported, unconfigured, or stale routes fail before inference. The request and
receipt bind the exact provider, model, transport, capabilities, and catalog snapshot without
secrets.

Provider-reported structured-output and reasoning-effort metadata can confirm or veto the checked-in
Product allowlist. If a provider catalog omits a field, that value remains unknown rather than an
explicit negative; unknown metadata does not authorize newly discovered models or effort values for
automatic promotion. OpenAI's list endpoint supplies model IDs and creation times but no per-model
capability metadata, so its existing pinned Product allowlist remains the capability authority.

The current census in `docs/settings/models/providers.yaml` is the scope boundary; adding a new
provider is not part of this task. Local Ollama remains optional and is not a readiness prerequisite
for Codex CLI or API-provider routes.

## Concretely

Product policy resolves `openai/gpt-6-luna` from its selected profile. The caller sends the exact
provider/model plus bounded prompt and capability intent to the Mac API. The API resolves the
configured host adapter and credentials, executes once, and returns route provenance. The request
does not contain `CODEX_HOME`, an API key, an arbitrary URL, or shell arguments.

## Why This Matters

If Product satellites keep calling providers directly, the Mac mini is not the promised portal and
provider secrets/harness behavior remain distributed. If the server invents a route or retries after
dispatch, the result is no longer bound to the model selected in settings.

## Acceptance Criteria

- [ ] The Mac API dispatches every currently declared, configured Product provider/model route via
  its host-local adapter and does not accept arbitrary transport commands, endpoints, or credentials.
  - Verify: `tests/model_access/test_product_provider_gateway.py::test_dispatches_exact_declared_route_without_caller_credentials`
- [ ] OpenAI and Anthropic discovery updates a snapshot only from verifiable provider metadata; stale,
  unsupported, or capability-incompatible descriptors are not promoted.
  - Verify: `tests/model_access/test_product_provider_gateway.py::test_catalog_refresh_uses_verifiable_provider_metadata`
- [ ] One inference request causes at most one provider dispatch; preflight failure is typed and a
  post-dispatch failure is terminal, with secret-free route provenance.
  - Verify: `tests/model_access/test_product_provider_gateway.py::test_dispatch_failure_is_terminal_and_receipt_is_secret_free`
- [ ] Missing Ollama does not fail preflight or health for a selected healthy Codex/API route.
  - Verify: `tests/model_access/test_capability_health.py::test_unselected_provider_absence_does_not_fail_health`

## How to Verify (Pre-Merge)

- Run `pytest tests/model_access/test_product_provider_gateway.py tests/model_access/test_catalog_discovery.py tests/model_access/test_capability_health.py`.
- Run the repository lint/type checks selected for changed Product model-access modules.
- Use fake provider transports and credentials; do not make paid provider calls in tests.

## Out of Scope

- Product call-site migration, clone-local profile changes, embeddings transport, or live host
  deployment; those are tracked by the sibling MARR task and parent acceptance.
- Provider accounts, API-key creation, model downloads, Tailscale, or per-channel credentials.
- Builder scheduler/policy changes or Model Inquiry fallback.

## Related Docs

- [ADR-0067](../adr/ADR-0067-mac-mini-product-model-access-portal.md)
- [Model Access Router](README.md)
- [Provider census](../settings/models/providers.yaml)
- [Catalog discovery spec](DISCOVER_FRESH_MODEL_CATALOGS.md)

## Related GitHub Issues

- Parent feature validation: #5819
- Implementation issue: #5821.
