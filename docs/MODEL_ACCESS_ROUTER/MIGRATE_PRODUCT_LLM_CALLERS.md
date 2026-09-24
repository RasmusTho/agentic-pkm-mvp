---
name: Migrate Product LLM Callers
description: Replace Product provider/model dispatch branches with the shared router/factory while retaining LLMRoute compatibility, remote Tailscale Codex execution, existing provider routes, and separate embedding identity.
task_id: MARR-05
github_issue: 5623
source_anchor: docs/adr/ADR-0066-shared-model-access-router-and-catalogs.md :: D6
parent_capability: MODEL_ACCESS_ROUTER
prerequisites: [MARR-01, MARR-02, MARR-03, MARR-04, MARR-08]
depends_on: [ESTABLISH_SHARED_ROUTE_AND_PROVENANCE_CONTRACTS.md, BUILD_ADAPTER_REGISTRY_AND_CODEX_CLI_TRANSPORT.md, FORMALIZE_OLLAMA_AND_PREFLIGHT_FALLBACK.md, DISCOVER_FRESH_MODEL_CATALOGS.md, ADD_TAILSCALE_CODEX_EXECUTOR_TRANSPORT.md]
can_parallelize_with: []
---

# MIGRATE_PRODUCT_LLM_CALLERS

## Purpose

Move Product route execution to the shared facade without changing caller-level semantics, breaking route introspection, or routing embeddings through the chat/completion provider path.

## What This Task Does

Migrate get_chat_client, reasoning, constrained completion, eval, and health/provider projections from hard-coded provider/model dispatch to the shared router and adapter factory. Keep LLMRoute as a compatibility projection until all in-scope callers use the new route. Derive dispatch/prober membership from declared provider/transport configuration and the selected registry snapshot. Preserve policy settings authority, route explanation, deterministic mock behavior, existing DeepSeek provider/configuration support, and existing embedding identity.

Product policy initially selects the configured Luna/Codex route through `codex_cli_tailscale` for general agent/text work. The Product runtime remains on Linux; host/session execution remains on the separate macOS executor. Product system instructions and user content must remain separate through the adapter boundary. Compatible text/JSON work may declare Ollama preflight fallback; native-tool, literal-system-role, or stronger reasoning routes must meet their complete capability intent and fail closed when they cannot. Existing configured DeepSeek calls continue through `deepseek_api` until a separate reviewed retirement.

Evaluation compatibility is route-bound rather than OpenAI-client-bound. In `run` mode, `EVAL_LLM_MODEL` selects one exact Product-declared chat model; it does not request latest-family promotion. `EVAL_LLM_BASE_URL` takes precedence over `OPENAI_BASE_URL`, and `EVAL_LLM_API_KEY` over `OPENAI_API_KEY`, but these values are private runtime adapter configuration only. They never choose provider/model/transport and never enter intent, route, receipt, logs, or CLI environment. The selected model's descriptor and transport allowlist determine the adapter. The local Ollama adapter accepts the resolved base URL and ignores the legacy API-key placeholder; Codex CLI uses its subscription session and receives neither value. Global forced provider/model and provider enforcement remain authoritative: a conflicting exact eval route fails before adapter I/O. `skip` mode resolves no route and reads no credentials.

## Concretely

get_chat_client(intent) resolves one owner policy, receives one exact route from ModelAccessRouter, and obtains the bound adapter from the factory. Health reports that route, logical executor/caller profiles, prompt-channel mapping, and snapshot/fallback provenance without exposing host identity or secrets. The Product call preserves `system_prompt` as trusted instructions separate from `user` content at the remote executor boundary. Embedding clients continue through their current identity resolver.

## Why This Matters

Updating only the low-level adapter would leave other Product code paths on different provider/model branches. Updating only Product would violate the accepted shared contract and preserve a second dispatch registry.

## Acceptance Criteria

- [ ] Chat, reasoning, constrained completion, eval, and health use the shared facade on the production call path.
  - Verify: `tests/components/llm/test_fabric.py::test_product_call_sites_use_shared_model_access_router`
- [ ] Reasoning structured and tool-use calls forward their JSON Schema through the bound chat client to remote transports; tool-use output restricts the tool name to the declared set.
  - Verify: `tests/components/reasoning/test_facade.py::TestStructured::test_forwards_schema_to_bound_remote_route` and `tests/components/reasoning/test_facade.py::TestToolUse::test_forwards_tool_call_schema_to_bound_remote_route`
- [ ] The configured Luna route returns exact route/transport/snapshot provenance and does not alter embedding identity.
  - Verify: `tests/components/llm/test_fabric.py::test_luna_route_provenance_and_embedding_identity_are_separate`
- [ ] Product system instructions and user content reach the Tailscale Codex executor in distinct fields; the factory does not concatenate them or claim literal system-role semantics.
  - Verify: `tests/components/llm/test_fabric.py::test_product_trusted_and_user_messages_remain_separate_on_remote_route`
- [ ] Dispatch sets, health probes, and model registry projections match declared provider/transport configuration.
  - Verify: `tests/settings/test_provider_census.py::test_product_dispatch_and_health_projections_match_declared_transports`
- [ ] Product code adds no new hard-coded model IDs outside registry descriptors and explicit compatibility aliases.
  - Verify: `tests/architecture/test_product_model_ids_are_registry_backed.py::test_product_runtime_model_ids_are_registry_backed`
- [ ] Existing deterministic mock, env override, route enforcement, and route explanation behavior remains compatible.
  - Verify: `tests/components/llm/test_router_enforced_provider.py::test_legacy_route_projection_and_enforcement_compatibility`
- [ ] Existing declared DeepSeek route remains dispatchable through `deepseek_api` and no migration silently drops its provider/configuration support.
  - Verify: `tests/components/llm/test_router_enforced_provider.py::test_deepseek_legacy_route_projects_to_declared_adapter`

## Lifecycle Boundary Matrix

Convergence packet — mechanism key `product.catalog-route-binding.v1`. The invariant is that one facade call binds one exact model/transport and its preflight plus optional catalog hash before inference; discovery is read-only and cannot mutate an already-returned client. The cache has cold, fresh, expired-within-stale, expired-beyond-stale, and validated-refresh states. `CatalogCache.get` is the only writer, serialized by its process-local lock per cache instance; the Codex catalog operation is a read-only producer. Snapshots are memory-only and disappear on process reconstruction.

Only recognized network unavailability may serve an in-age stale snapshot, and that selection stays pinned rather than promoting. Authentication failure, malformed/mismatched data, and unexpected exceptions fail closed. Route preflight may choose a fully capable fallback before the first inference only; once completion starts, failure is terminal/indeterminate with no retry, replay, compensation, or provider switch. A process stop before dispatch loses the ephemeral client; after dispatch, outcome recovery is not promised. Prior review findings on auth/mismatch and untyped-exception classification are covered by the route-level refresh test below and the remote-transport test.

The public caller binds an immutable route before completion. A catalog refresh may change a later client's target, but cannot mutate a client already returned by the facade. The following rows are the executable boundary for this slice; test names marked “new” are added by its implementation.

| Initial state | Event | Required observable postcondition | Verification |
| --- | --- | --- | --- |
| Unresolved request | Unknown/ambiguous model, disallowed transport/capability, or conflict with active global route enforcement | Typed failure before catalog/preflight/completion; no route receipt | `tests/components/llm/test_fabric.py::test_explicit_route_obeys_global_enforcement`; new `tests/eval/test_eval_llm_client.py::test_eval_rejects_undeclared_exact_model` and `::test_eval_conflicting_force_fails_before_preflight` |
| Cold catalog cache; concurrent same-key callers | Simultaneous cache miss | One in-process load publishes one immutable snapshot; callers receive the same hash; cache is not shared across processes | `tests/model_access/test_catalog.py::test_concurrent_cache_miss_publishes_one_immutable_snapshot` |
| Client A bound to snapshot A | A later facade request refreshes cache to B before A dispatches | Client A dispatches exact route/hash A; the new client binds B | New `tests/components/llm/test_fabric.py::test_bound_client_keeps_catalog_route_after_cache_refresh`; `tests/model_access/test_catalog.py::test_two_requests_bind_distinct_catalog_versions` |
| Cached snapshot is within TTL | Another request reads it | Return same immutable snapshot without provider discovery | `tests/model_access/test_catalog.py::test_refresh_ttl_and_max_stale_fail_closed` |
| TTL expired with cached A | Valid refresh returns B | Publish B for future clients; already-bound A is unchanged | New fabric interleaving test above |
| TTL expired with cached A no older than max-stale | Provider reports `catalog_unavailable` | Return A marked stale; selector may retain pinned model only, never promote | `tests/model_access/test_catalog.py::test_refresh_ttl_and_max_stale_fail_closed` |
| No cache, or cached snapshot beyond max-stale | Provider outage | Fail closed; no route/preflight/completion | `tests/model_access/test_catalog.py::test_refresh_ttl_and_max_stale_fail_closed` |
| Cached A; refresh returns auth failure, transport mismatch, invalid/hash-mismatched data, or an unexpected error | Refresh validation fails | Preserve `catalog_auth_failed` or raise `catalog_invalid`; do not serve stale A for this request or overwrite cache | New `tests/components/llm/test_fabric.py::test_product_catalog_auth_or_invalid_refresh_never_routes_stale_snapshot`; `tests/model_access/test_catalog.py::test_invalid_refresh_is_not_downgraded_to_a_stale_route` |
| Catalog load in progress; no route bound | Cache-owning process is reconstructed | A new cache instance has no persisted snapshot and must load again; no cross-process cache is claimed | New `tests/model_access/test_catalog.py::test_catalog_cache_is_process_local_and_empty_after_reconstruction` |
| Route A bound; completion not started | Another request binds B, then the pending caller dispatches A | No completion occurs during binding/refresh; if the process ends before chat, the client is ephemeral; no recovery/replay promise is made | New `tests/components/llm/test_fabric.py::test_bound_client_keeps_catalog_route_after_cache_refresh` (asserts zero completion before dispatch and A after B) |
| Completion dispatched | Provider returns an ambiguous timeout/error (the process-crash analogue at the adapter boundary) | Terminal/indeterminate; no retry, fallback, route switch, or second completion. Actual OS process termination/outcome is not claimed or simulated | `tests/model_access/test_fallback_policy.py::test_post_start_failure_never_calls_fallback_provider` |
| Primary preflight succeeds | Completion begins | Exactly one completion on primary route | `tests/components/llm/test_fabric.py::test_product_remote_fallback_is_selected_before_one_completion` |
| Eligible typed primary preflight failure and fully capable fallback | Fallback preflight succeeds | Bind fallback before inference; issue exactly one completion; record sanitized reason | `tests/model_access/test_fallback_policy.py::test_compatible_fallback_occurs_before_first_model_call` and `::test_fallback_receipt_binds_preflight_reason_without_secrets` |
| Fallback is ineligible or lacks a required capability | Fallback would weaken intent (including native tools, strong reasoning, or literal system role) | Refuse before completion; do not dispatch fallback | `tests/model_access/test_fallback_policy.py::test_ollama_is_rejected_when_native_tools_are_required`, `::test_strong_reasoning_failure_does_not_downgrade_to_ollama`, and `::test_literal_system_role_requirement_does_not_downgrade_to_ollama` |
| Eval mode is `skip` | Eval client configured | No model/catalog/preflight call and no credential binding | `tests/eval/test_eval_llm_client.py::test_eval_skip_mode_needs_no_credentials_or_route` |
| Eval mode is `run`, exact model is declared | Endpoint/key overrides are resolved; generation occurs | Bind exact declared model/transport, no catalog promotion or process-env mutation; keep endpoint/key private and out of route/receipt/log; execute through facade | New `tests/eval/test_eval_llm_client.py::test_eval_env_precedence_and_private_runtime_config` and `tests/components/llm/test_fabric.py::test_eval_exact_model_binds_declared_transport_without_catalog_promotion` |
| Health inspects a Tailscale executor route | Health preflights through the facade | Report bound route/preflight status without completion; no direct executor bypass | `tests/cli/test_health_llm_routing.py::test_health_codex_transport_uses_remote_preflight_not_api_key` |
| Health probes an Ollama endpoint containing credentials, path, or query | Diagnostic response is formed | Report only the sanitized origin; do not expose URL credentials or endpoint path/query | `tests/cli/test_health_ollama_env.py::test_health_ollama_output_redacts_url_credentials_query_and_path` |

Caller-level facade regression coverage is required for QA, Planner, reflection, ReasoningFacade, reasoning provider, and constrained completion. Those tests exercise their production entrypoints, not only the facade helper: new `tests/test_agent_smoke.py::test_qa_agent_uses_shared_model_access_router`, `tests/planner/test_llm_planner.py::test_llm_planner_uses_shared_model_access_router`, `tests/reasoning/test_provider_planning.py::test_planning_mode_uses_shared_model_access_router`, and `tests/chat/test_intent_unknown_route.py::test_default_constrained_completion_uses_shared_model_access_router`, plus `tests/journaling/test_lead_reflection_conversation.py::test_real_provider_receives_day_context_and_transcript_in_user_messages` and `tests/components/reasoning/test_facade.py::TestChat::test_routes_through_router`.

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
