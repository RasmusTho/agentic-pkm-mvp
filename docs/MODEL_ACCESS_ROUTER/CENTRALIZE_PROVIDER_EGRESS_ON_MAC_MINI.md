---
name: Centralize Product provider egress on the Mac mini
description: Extend the bounded Mac Model Access API to execute the registry-declared Product provider routes without exposing harness or credentials to callers.
task_id: MARR-12
github_issue: 5821
source_anchor: docs/adr/ADR-0067-mac-mini-product-model-access-portal.md :: D1-D4
parent_feature: Mac mini Product model-access portal (#5819)
prerequisites: []
depends_on: []
can_parallelize_with: []
---

# Centralize Product provider egress on the Mac mini

## Purpose

The current executor API can run the accepted Luna/Codex CLI path but does not act as the egress
point for every provider in the Product registry. This task adds only the provider dispatch and
catalog behavior needed for the thin Product API; it does not move Product route-selection policy
onto the Mac.

## What This Task Does

Extend the Mac-hosted Model Access API with bounded logical Product requests containing provider,
model, task capability/input, and no caller-selected transport or catalog provenance. The Product
surface is `POST /v1/product/catalog`, `POST /v1/product/preflight`, `POST /v1/product/complete`,
and `POST /v1/product/embed`. The API resolves the provider's configured host adapter and
credentials, then returns the exact transport and host-loaded catalog hash. Callers do not select a
harness, supply an endpoint, or send credentials. The legacy exact-route `/v1` operations remain
for compatibility; provider API and embedding inference use the logical Product surface.
Discovery covers the current provider census using provider-supplied metadata, including OpenAI and
Anthropic updates; pinned embedding models are intersected with their declared provider census and
must be present/usable in the host catalog. Unsupported, unconfigured, stale, or dimension-incompatible
routes fail before inference. The request and receipt bind the exact provider, model, transport,
capabilities, and catalog snapshot without secrets.

Provider-reported structured-output and reasoning-effort metadata can confirm or veto the checked-in
Product allowlist. If a provider catalog omits a field, that value remains unknown rather than an
explicit negative; unknown metadata does not authorize newly discovered models or effort values for
automatic promotion. OpenAI's list endpoint supplies model IDs and creation times but no per-model
capability metadata, so the pinned Product census carries its per-model reasoning-effort allowlist.
A missing allowlist means unknown and denies a requested effort; an empty list explicitly declares a
non-reasoning model. Provider attestations, when present, can only narrow the declared allowlist.
The gateway also refuses inference against a stale catalog snapshot, even while the cache retains
that snapshot as a bounded availability aid for read-only callers.

The current census in `docs/settings/models/providers.yaml` is the scope boundary; adding a new
provider is not part of this task. Local Ollama remains optional and is not a readiness prerequisite
for Codex CLI or API-provider routes.

Embedding requests are one text item and one exact provider dispatch. The current Product
embedding census is `gemini/gemini-embedding-001`, `ollama/nomic-embed-text:latest`, and the
deterministic `mock/mock-embed` test route. The gateway verifies the declared embedding capability
and requested dimensions before dispatch, bounds and validates exactly one returned vector, and
never retries through a different endpoint/provider. Ollama uses its single `/api/embed` endpoint;
the legacy local client's `/v1/embeddings` fallback is not used by the Mac portal. Gemini key lookup
is host-local. The returned vector remains subject to the existing Product normalization and
embedding-identity guards before any index write.

Structured-output schemas are bounded inline JSON Schema only. `$ref`, `$dynamicRef`, and
`$recursiveRef` are rejected recursively, and the response validator cannot retrieve remote schema
resources. Caller-controlled schema URLs must never create a second egress path from the portal.

## Concretely

Product settings resolve `openai/gpt-6-luna` from the selected profile. The caller sends provider,
model, bounded prompt, and capability intent to the Mac API. The API resolves the configured host
adapter and credentials, binds a fresh host-discovered catalog snapshot, executes once, and returns
route provenance. The request does not contain a transport, catalog hash, `CODEX_HOME`, an API key,
an arbitrary URL, or shell arguments.

## Why This Matters

If Product satellites keep calling providers directly, the Mac mini is not the promised portal and
provider secrets/harness behavior remain distributed. If the server invents a route or retries after
dispatch, the result is no longer bound to the model selected in settings.

## Acceptance Criteria

- [ ] The Mac API dispatches every currently declared, configured Product provider/model route via
  its host-local adapter; Product requests cannot choose transport or catalog provenance and cannot
  accept arbitrary commands, endpoints, or credentials.
  - Verify: `tests/model_access/test_product_provider_gateway.py::test_dispatches_exact_declared_route_without_caller_credentials`
- [ ] Exact-route compatibility requests bind the host's actual fresh catalog and reject fabricated
  snapshot references or hashes before preflight or inference.
  - Verify: `tests/model_access/test_codex_executor_service.py::test_exact_route_rejects_fabricated_catalog_provenance_before_dispatch`
- [ ] OpenAI and Anthropic discovery updates a snapshot only from verifiable provider metadata; stale,
  unsupported, or capability-incompatible descriptors are not promoted, and requested reasoning
  effort is checked against the selected model's declared capability before inference. Unknown and
  explicitly unsupported effort sets fail closed.
  - Verify: `tests/model_access/test_product_provider_gateway.py::test_catalog_refresh_uses_verifiable_provider_metadata`
  - Verify: `tests/model_access/test_product_provider_gateway.py::test_reasoning_requires_static_model_declared_efforts`
  - Verify: `tests/model_access/test_product_provider_gateway.py::test_stale_catalog_cannot_authorize_preflight_or_inference`
  - Verify: `tests/model_access/test_product_provider_gateway.py::test_declared_openai_luna_reasoning_effort_passes_preflight_and_dispatch`
- [ ] One inference request causes at most one provider dispatch; preflight failure is typed and a
  post-dispatch failure is terminal, with secret-free route provenance.
  - Verify: `tests/model_access/test_product_provider_gateway.py::test_dispatch_failure_is_terminal_and_receipt_is_secret_free`
- [ ] Missing Ollama does not fail preflight or health for a selected healthy Codex/API route.
  - Verify: `tests/model_access/test_capability_health.py::test_unselected_provider_absence_does_not_fail_health`
- [ ] The real Mac Product API accepts only declared embedding provider/model/dimension/input,
  binds a fresh host route/catalog, dispatches once, returns one validated vector, and rejects
  unsupported dimensions/capabilities before provider inference.
  - Verify: `tests/model_access/test_product_embedding_gateway.py::test_product_api_dispatches_declared_embedding_once_with_host_provenance`
  - Verify: `tests/model_access/test_product_embedding_gateway.py::test_dimension_mismatch_fails_before_embedding_dispatch`
- [ ] Caller-supplied schema references are rejected before provider access, and result validation
  cannot retrieve caller-controlled schema resources.
  - Verify: `tests/model_access/test_product_provider_gateway.py::test_reference_schema_is_rejected_before_provider_or_schema_egress`

## How to Verify (Pre-Merge)

- Run `pytest tests/model_access/test_product_provider_gateway.py tests/model_access/test_catalog_discovery.py tests/model_access/test_capability_health.py`.
- Run the repository lint/type checks selected for changed Product model-access modules.
- Use fake provider transports and credentials; do not make paid provider calls in tests.

## Out of Scope

- Product call-site migration, clone-local profile changes, or live host deployment; those are
  tracked by the dependent MARR task and parent acceptance.
- Provider accounts, API-key creation, model downloads, Tailscale, or per-channel credentials.
- Builder scheduler/policy changes or Model Inquiry fallback.

## Related Docs

- [ADR-0067](../adr/ADR-0067-mac-mini-product-model-access-portal.md)
- [Model Access Router](README.md)
- [Provider census](../settings/models/providers.yaml)
- [Catalog discovery spec](DISCOVER_FRESH_MODEL_CATALOGS.md)
- [Gemini embedContent API](https://ai.google.dev/api/embeddings)
- [Ollama embed API](https://docs.ollama.com/api/embed)

## Related GitHub Issues

- Parent feature validation: #5819
- Implementation issue: #5821.
