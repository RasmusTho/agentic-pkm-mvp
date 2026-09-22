---
name: Migrate Product LLM Callers
description: Replace Product provider/model dispatch branches with the shared router/factory while retaining LLMRoute compatibility and separate embedding identity.
task_id: MARR-05
github_issue: 5623
source_anchor: docs/adr/ADR-0066-shared-model-access-router-and-catalogs.md :: D6
parent_capability: MODEL_ACCESS_ROUTER
prerequisites: [MARR-01, MARR-02, MARR-03, MARR-04]
depends_on: [ESTABLISH_SHARED_ROUTE_AND_PROVENANCE_CONTRACTS.md, BUILD_ADAPTER_REGISTRY_AND_CODEX_CLI_TRANSPORT.md, FORMALIZE_OLLAMA_AND_PREFLIGHT_FALLBACK.md, DISCOVER_FRESH_MODEL_CATALOGS.md]
can_parallelize_with: []
---

# MIGRATE_PRODUCT_LLM_CALLERS

## Purpose

Move Product route execution to the shared facade without changing caller-level semantics, breaking route introspection, or routing embeddings through the chat/completion provider path.

## What This Task Does

Migrate get_chat_client, reasoning, constrained completion, eval, and health/provider projections from hard-coded provider/model dispatch to the shared router and adapter factory. Keep LLMRoute as a compatibility projection until all in-scope callers use the new route. Derive dispatch/prober membership from declared provider/transport configuration and the selected registry snapshot. Preserve policy settings authority, route explanation, deterministic mock behavior, and existing embedding identity.

Product policy initially selects the configured Luna/Codex route for general agent/text work. Compatible text/JSON work may declare Ollama preflight fallback; native-tool or stronger reasoning routes must meet their complete capability intent and fail closed when they cannot.

## Concretely

get_chat_client(intent) resolves one owner policy, receives one exact route from ModelAccessRouter, and obtains the bound adapter from the factory. Health reports that route and its snapshot/fallback provenance without exposing secrets. Embedding clients continue through their current identity resolver.

## Why This Matters

Updating only the low-level adapter would leave other Product code paths on different provider/model branches. Updating only Product would violate the accepted shared contract and preserve a second dispatch registry.

## Acceptance Criteria

- [ ] Chat, reasoning, constrained completion, eval, and health use the shared facade on the production call path.
  - Verify: `tests/components/llm/test_fabric.py::test_product_call_sites_use_shared_model_access_router`
- [ ] The configured Luna route returns exact route/transport/snapshot provenance and does not alter embedding identity.
  - Verify: `tests/components/llm/test_fabric.py::test_luna_route_provenance_and_embedding_identity_are_separate`
- [ ] Dispatch sets, health probes, and model registry projections match declared provider/transport configuration.
  - Verify: `tests/settings/test_provider_census.py::test_product_dispatch_and_health_projections_match_declared_transports`
- [ ] Product code adds no new hard-coded model IDs outside registry descriptors and explicit compatibility aliases.
  - Verify: `tests/architecture/test_product_model_ids_are_registry_backed.py::test_product_runtime_model_ids_are_registry_backed`
- [ ] Existing deterministic mock, env override, route enforcement, and route explanation behavior remains compatible.
  - Verify: `tests/components/llm/test_router_enforced_provider.py::test_legacy_route_projection_and_enforcement_compatibility`

## How to Verify (Pre-Merge)

- Run focused router/fabric, service, eval, health, and provider-census tests.
- Run pytest -q tests/components/llm tests/services tests/settings/test_provider_census.py.
- Use monkeypatched/fake adapters; no live provider call is made by CI.
- Confirm embeddings tests and identity invariants are unchanged.

## Out of Scope

- Embedding provider/model identity migration.
- Provisioning or activating metered provider API keys.
- Removing LLMRoute compatibility before all current consumers are migrated.
- Shadow execution or dual provider requests.

## Related Docs

- docs/LLM_ROUTING.md
- docs/LLM.md
- docs/HEALTH.md
- docs/adr/ADR-0063-shared-llm-contract-kernel.md
- docs/adr/ADR-0066-shared-model-access-router-and-catalogs.md

## Related GitHub Issues

Created from this specification; issue number is written here when filed.
