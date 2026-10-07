---
name: Route Product chat and embeddings through the Mac portal
description: Route every Product model call through the Mac Model Access API while keeping model/profile choice in per-clone settings.
task_id: MARR-13
github_issue: 5820
source_anchor: docs/adr/ADR-0067-mac-mini-product-model-access-portal.md :: D1-D6
parent_feature: Mac mini Product model-access portal (#5819)
prerequisites: []
depends_on: [5821]
can_parallelize_with: []
---

# Route Product chat and embeddings through the Mac portal

## Purpose

Product chat already uses the shared routing facade and the current Mac executor path, but Product
embeddings still use a separate provider client. Clone-local profiles also select chat models only.
This task completes the Product side of the owner-approved single-portal topology.

## What This Task Does

Route Product chat/reasoning/constrained/evaluation and embedding inference through the Mac Model
Access API. This task depends on the merged MARR-12 server endpoint (`POST /v1/product/embed`); do
not substitute a fake-only gateway for the endpoint contract. Keep the shared Product settings as the route authority and extend clone-local profiles
so different satellites can select registry-backed models for each supported model kind, including
embeddings. Preserve capability validation, exact route receipts, and embedding identity/dimension
guards. Provider and harness details stay behind the Model Access adapter boundary. Health reports
the selected logical `llm_access` capability; an unselected Ollama service is not required.

The Product `mock` test adapter remains available for deterministic tests. Builder routing and Model
Inquiry are unchanged.

## Concretely

The default Product clone can use the Luna profile while a work satellite selects a different
registry-backed chat or embedding profile in its gitignored local settings. Both send inference
requests through the same configured VLAN Model Access API; neither calls OpenAI, Anthropic,
Gemini, or Ollama endpoints directly.

## Why This Matters

Without the embedding path and profile extension, “Mac mini is the portal for all models” would be
only a chat claim. A silent embedding model switch could also mix vector identities and corrupt
retrieval assumptions.

## Acceptance Criteria

- [ ] Product chat/reasoning/constrained/evaluation call sites use the Mac Model Access client for
  every non-mock model route; two clone settings can select different compatible registry models.
  - Verify: `tests/components/llm/test_product_model_access_gateway.py::test_product_chat_route_uses_remote_gateway_and_clone_profile`
- [ ] Product embeddings call the real `POST /v1/product/embed` contract, and a satellite can select
  a registry-backed embedding model without bypassing identity/dimension validation. Test through
  the ASGI service + `CodexRemoteTransport`, not a standalone fake `ProductGateway`.
  - Verify: `tests/components/llm/test_product_model_access_gateway.py::test_embedding_route_uses_gateway_and_preserves_identity`
- [ ] Unknown profiles, stale catalog routes, incompatible dimensions, and unsupported capabilities
  fail before inference or index writes; no hidden local provider call is made.
  - Verify: `tests/components/llm/test_product_model_access_gateway.py::test_invalid_route_fails_before_provider_dispatch`
- [ ] Provider-neutral health remains green when the selected model access route is healthy and
  Ollama is absent or unselected.
  - Verify: `tests/model_access/test_capability_health.py::test_unselected_provider_absence_does_not_fail_health`
- [ ] Owner docs distinguish current shipped Luna chat support from the full portal until the
  parent acceptance is complete.
  - Verify: doc writeback at `docs/LLM_ROUTING.md :: Current policy and future work`

## How to Verify (Pre-Merge)

- Run `pytest tests/components/llm/test_product_model_access_gateway.py tests/components/llm/test_router.py tests/settings/test_llm_routing_profiles.py tests/components/embeddings/test_cross_provider_guard.py tests/model_access/test_capability_health.py`.
- Run settings validation and lint/type checks selected for changed Product call sites.
- Use fake transports; do not make paid provider calls or rebuild a live index.

## Out of Scope

- Mac server adapter/discovery implementation (MARR-12), live credential provisioning, index rebuild,
  account/subscription changes, or release promotion. The integration contract must target the
  real MARR-12 request/response path; integrated live acceptance follows both merges.
- Changing Luna as the default, choosing a specific work-satellite model, or committing local
  settings.
- Product/Builder policy sharing, Model Inquiry fallback, Tailscale, or mandatory Ollama service.

## Related Docs

- [ADR-0067](../adr/ADR-0067-mac-mini-product-model-access-portal.md)
- [Model Access Router](README.md)
- [LLM Routing](../LLM_ROUTING.md)
- [Embedding identity contract](../EMBEDDING_RELIABILITY/README.md)

## Related GitHub Issues

- Parent feature validation: #5819
- Implementation issue: #5820.
