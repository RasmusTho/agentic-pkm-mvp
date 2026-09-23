---
name: Establish Shared Route and Provenance Contracts
description: Extend the neutral LLM contract with explicit transport, catalog, preflight, host, capability, and fallback provenance while preserving separate Product and Builder policy profiles.
task_id: MARR-01
github_issue: 5619
source_anchor: docs/adr/ADR-0066-shared-model-access-router-and-catalogs.md :: D1
parent_capability: MODEL_ACCESS_ROUTER
prerequisites: []
depends_on: []
can_parallelize_with: []
---

# ESTABLISH_SHARED_ROUTE_AND_PROVENANCE_CONTRACTS

## Purpose

Define the neutral route/result contract needed by one shared facade without transferring policy authority from Product to Builder or vice versa. This is the compatibility foundation for every adapter and migration slice.

## What This Task Does

Extend llm_contract with provider-neutral route provenance: exact transport_id, catalog snapshot reference/hash, preflight status, logical execution-host profile, execution-boundary/authentication scheme, logical caller profile, resolved capability set, trusted-instruction channel mapping, and capability/fallback provenance. None of these fields may contain a concrete hostname, endpoint, raw Tailscale identity/capability claim, secret, prompt, or CLI environment. Define a policy-agnostic ModelAccessRouter seam that accepts an owner resolver/profile and adapter registry. Keep Product LLMRoute as a compatibility projection and keep existing Builder resolution independent.

Used fallback provenance identifies the original and selected effective targets, both transports, the preflight reason, and the owner policy profile; the selected target must match the route, which must carry visible degradation and a closed reason code. This preserves ADR-0063's fallback lineage without granting the facade fallback authority.

The owner resolver returns per-request fallback provenance with the selected target; caller profile metadata cannot invent or replace that outcome. Adapter descriptors declare their supported capability envelope, and the facade rejects any resolved capability outside it. When capability provenance uses `adapter_attestation`, its logical source reference must be the selected adapter ID.

The request distinguishes a trusted channel separate from user content from an intent that requires the literal system role. A `developer_instructions` mapping may satisfy only the former; it must not be projected as a literal system channel.

The kernel remains side-effect-free: it does not load provider policy, credentials, host sessions, Product settings, BuilderOps, or runtime stores.

## Concretely

Product policy + intent → ModelAccessRouter → Product-resolved target

Builder policy + intent → ModelAccessRouter → Builder-resolved target

Both results use one neutral schema, while each caller retains its own resolver, credentials, fallback decision, and receipt authority. The resolver's selected fallback provenance flows into the route, and the facade binds it to the selected policy, transport, effective identity, and degradation state. The facade also bounds target capabilities by the adapter descriptor's declared support.

## Why This Matters

Without one neutral contract, each transport can invent incompatible route/provenance fields. If the facade imports Product policy, Builder's separate authority boundary is broken.

## Acceptance Criteria

- [ ] Route and receipt contracts carry transport, snapshot reference/hash, preflight status, logical execution host/boundary/caller profile, requested/resolved capabilities, trusted-instruction mapping, and fallback provenance without raw host or Tailscale identity.
  - Verify: `tests/model_access/test_contracts.py::test_route_contract_carries_transport_catalog_preflight_host_and_fallback_provenance`
- [ ] Resolver-selected fallback provenance reaches the route and is rejected if its policy, selected transport/identity, or degradation does not match the final target.
  - Verify: `tests/model_access/test_router_facade.py::test_facade_preserves_and_binds_resolver_fallback_provenance`
- [ ] The facade rejects resolved capability claims outside the selected adapter descriptor's supported capability envelope.
  - Verify: `tests/model_access/test_router_facade.py::test_facade_rejects_capabilities_not_attested_by_adapter`
- [ ] Adapter-attestation capability provenance is bound to the selected adapter ID.
  - Verify: `tests/model_access/test_router_facade.py::test_adapter_attestation_provenance_must_match_selected_adapter`
- [ ] The facade composes Product and Builder policy resolvers without importing either authority into the neutral kernel.
  - Verify: `tests/model_access/test_router_facade.py::test_product_and_builder_profiles_resolve_without_policy_leakage`
- [ ] LLMRoute remains a lossless compatibility projection for its currently represented fields.
  - Verify: `tests/components/llm/test_router.py::test_legacy_llmroute_projects_from_neutral_route`
- [ ] Serialization and validation reject credential values, endpoint secrets, prompts, raw network identity/capability claims, and CLI environment content.
  - Verify: `tests/model_access/test_contracts.py::test_route_provenance_rejects_secret_bearing_fields`
- [ ] The decision remains explicitly target-state and does not claim shipped Product routing.
  - Verify: doc writeback at `docs/adr/ADR-0066-shared-model-access-router-and-catalogs.md :: D1`

## How to Verify (Pre-Merge)

- Run pytest -q tests/model_access/test_contracts.py tests/model_access/test_router_facade.py tests/components/llm/test_router.py.
- Run the existing Builder import-boundary tests and add a call-site assertion that the neutral facade is the only shared seam.
- Review the diff to ensure no credentials, settings, or runtime-store imports entered llm_contract.

## Out of Scope

- Provider adapters, catalog fetching, policy selection changes, Product caller migration, host configuration, or live model calls.
- Changing Model Inquiry's current resolver or fallback behavior.

## Related Docs

- docs/adr/ADR-0063-shared-llm-contract-kernel.md
- docs/adr/ADR-0064-model-access-substrate.md
- docs/adr/ADR-0066-shared-model-access-router-and-catalogs.md
- docs/LLM_ROUTING.md
- docs/MODEL_ACCESS_ROUTER/README.md

## Related GitHub Issues

Created from this specification; issue number is written here when filed.
