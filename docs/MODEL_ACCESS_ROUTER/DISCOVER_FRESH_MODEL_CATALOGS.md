---
name: Discover Fresh Model Catalogs
description: Implement provider discovery adapters, host-local hashed snapshots, freshness bounds, and safe latest-compatible selection from verifiable provider metadata.
task_id: MARR-04
github_issue: 5622
source_anchor: docs/adr/ADR-0066-shared-model-access-router-and-catalogs.md :: D4
parent_capability: MODEL_ACCESS_ROUTER
prerequisites: [MARR-01, MARR-02, MARR-03]
depends_on: [ESTABLISH_SHARED_ROUTE_AND_PROVENANCE_CONTRACTS.md, BUILD_ADAPTER_REGISTRY_AND_CODEX_CLI_TRANSPORT.md, FORMALIZE_OLLAMA_AND_PREFLIGHT_FALLBACK.md]
can_parallelize_with: []
---

# DISCOVER_FRESH_MODEL_CATALOGS

## Purpose

Keep model availability and capability metadata current without confusing a model catalog with policy, credentials, or an inference call. This is the only slice allowed to auto-select a newer compatible model, and only from verifiable source metadata.

## What This Task Does

Add a common descriptor and host-local CatalogSnapshot containing exact model ID, provider, allowed transports, declared capabilities, supported reasoning efforts, source release/created or explicit replacement metadata, deprecation/sunset status, limits/pricing where provided, source/fetched time, freshness, and deterministic hash.

Implement separate read-only discovery adapters:

- Codex app-server model/list using the existing host-local login; retain account-scoped available model IDs and reasoning efforts. Its list order is not release order. Use only a provider-supplied release timestamp or explicit upgrade relation to select a newer target; otherwise leave Luna or another explicit policy target pinned.
- Ollama local catalog/model metadata through the configured endpoint. Local modified_at/pull time is not model release chronology and cannot auto-promote a fallback.
- OpenAI and Anthropic model-list API adapters behind declared secret references. They may run only when an authorized credential is already configured; this task creates no API keys and enables no metered inference. Without credentials, source status is unavailable and Product retains an explicitly pinned target or fails closed.

Refresh on request when the five-minute TTL expires. Reject auto-promotion from stale data older than 24 hours, unordered sources, unknown timestamps, or invalid descriptors. Catalog fetch performs no model generation and never records secret values.

## Concretely

A request reads or refreshes one snapshot, filters it by owner policy, channel, permitted transport, required capabilities, and reasoning constraints, chooses only a verifier-ranked compatible target, then binds the model ID and snapshot hash to the resolved route. A changed catalog between two requests may change the selected model only when the newer snapshot proves the promotion order.

## Why This Matters

Monthly model releases make hand-maintained IDs stale, but guessing from names or response order risks routing to an unavailable or weaker model. A content hash and freshness contract make the selected catalog inspectable and reproducible.

## Acceptance Criteria

- [ ] Snapshot schema binds provider/model/transport, capabilities, reasoning, lifecycle, source/fetched time, freshness, and hash.
  - Verify: `tests/model_access/test_catalog.py::test_snapshot_hash_binds_complete_provider_descriptor`
- [ ] Request-time refresh enforces five-minute TTL and 24-hour maximum staleness.
  - Verify: `tests/model_access/test_catalog.py::test_refresh_ttl_and_max_stale_fail_closed`
- [ ] Codex account catalog discovery is read-only and does not infer release order from list position.
  - Verify: `tests/model_access/test_catalog_discovery.py::test_codex_model_list_order_does_not_auto_promote`
- [ ] An explicit provider replacement edge or verifier-valid release timestamp selects the latest compatible model; a deprecated or capability-incomplete model is filtered out.
  - Verify: `tests/model_access/test_catalog.py::test_latest_compatible_selection_uses_verified_release_metadata`
- [ ] OpenAI and Anthropic discovery adapters use injected credentials and fake HTTP only; absent credentials do not trigger ambient lookup or inference.
  - Verify: `tests/model_access/test_catalog_discovery.py::test_api_catalogs_fail_closed_without_declared_credentials`
- [ ] Catalog refresh makes no model invocation and no snapshot/receipt field contains a credential or endpoint secret.
  - Verify: `tests/model_access/test_catalog_discovery.py::test_catalog_refresh_is_read_only_and_secret_free`
- [ ] A catalog change between requests changes the bound snapshot hash and route only when policy accepts the new descriptor.
  - Verify: `tests/model_access/test_catalog.py::test_two_requests_bind_distinct_catalog_versions`

## How to Verify (Pre-Merge)

- Run pytest -q tests/model_access/test_catalog.py tests/model_access/test_catalog_discovery.py.
- Use fixtures for Codex app-server, Ollama HTTP, OpenAI model-list, and Anthropic model-list responses; no provider credential or model call is used.
- Test stale snapshot, source outage, invalid release ordering, explicit upgrade relation, deprecation, missing capabilities, and catalog drift across requests.

## Out of Scope

- Creating, rotating, or provisioning provider credentials.
- Enabling OpenAI or Anthropic inference or charging a provider account.
- Treating public documentation order, model-name suffixes, or local Ollama pull timestamps as recency proof.
- Mutating Product policy/registry values automatically from a catalog response.

## Related Docs

- docs/adr/ADR-0064-model-access-substrate.md
- docs/adr/ADR-0066-shared-model-access-router-and-catalogs.md
- docs/settings/models/providers.yaml
- docs/settings/models/registry.yaml
- docs/MODEL_ACCESS_ROUTER/README.md

## Related GitHub Issues

Created from this specification; issue number is written here when filed.
