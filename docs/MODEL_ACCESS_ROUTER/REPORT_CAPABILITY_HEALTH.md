---
name: Report provider-neutral model capability health
description: Specify provider-neutral health reporting for the logical model capabilities required by a configured workload.
task_id: MARR-10
source_anchor: docs/adr/ADR-0066-shared-model-access-router-and-catalogs.md :: D5, D6
parent_capability: MODEL_ACCESS_ROUTER
depends_on: [MARR-01, MARR-02, MARR-05, MARR-08]
---

# REPORT_CAPABILITY_HEALTH

## Purpose

Make system health answer which capabilities required by the configured workload are available.
Health must remain stable when a compatible model adapter or provider changes, and it must not
require a provider-specific environment variable or installation just to report system health.

## Contract

- The Product health evaluator reads the configured workload's required logical capabilities and
  asks the access abstraction for a no-inference readiness result.
- A model adapter maps its internal diagnostics into provider-neutral capability statuses. The
  aggregate health contract does not branch on provider names, require unrelated providers, select
  a model, perform inference, or authorize provider/model fallback.
- The health result reports required capability IDs and status (`available`, `degraded`,
  `unavailable`, or `unknown`), plus safe reason codes and freshness where applicable. It omits
  provider identity, concrete endpoint, host identity, credentials, prompts, and raw adapter output.
- Capability status is evaluated against the exact configured route/profile and adapter-declared
  capabilities. An unselected provider being absent does not affect aggregate health. A required
  capability that cannot be provided by the selected route is unavailable; a route using a
  transport the Product completion facade rejects is unavailable even if another transport for the
  same provider is configured. Health must not silently weaken the requirement.
- The health route inventory carries the caller contract for schema-backed task kinds, including
  `decide`, `plan`, `tool`, and registered extraction workloads, so required `structured_output` is
  checked even though health never invokes inference. When remote preflight rejects one requested
  capability, that capability is reported as unavailable; other capability results remain unknown
  if preflight stopped before checking runtime readiness.
- Aggregate semantics are deterministic: `available` is healthy; `degraded`, `unavailable`, and
  `unknown` are unhealthy for a required capability. A missing, malformed, or stale observation is
  treated as `unknown`. The required `llm_access` check is `ok` only when every required capability
  is freshly `available`; any other status makes that check `ok: false`, and therefore makes both
  top-level `/api/health.required_ok` and `/api/health.ok` false. Optional diagnostics do not change
  required-capability aggregation. `/healthz`, `/readyz`, and embedding-index checks keep their
  separate contracts.
- Network-path reachability is reported as a separate transport observation. A configured
  pre-completion path fallback may preserve capability availability and is reported as degraded
  transport; route/path identity is excluded from the observation. A typed path outage makes the
  required capability unavailable; an unclassified path failure or invalid local preflight request
  leaves capability status unknown because no adapter capability result exists. The health evaluator
  does not change the route, promote a catalog model, or trigger inference.
- Embedding identity/index compatibility remains in the embedding subsystem. `/readyz` remains
  governed by store/Postgres readiness.
- Internal, access-controlled diagnostics may retain adapter-specific detail for operator
  troubleshooting. That detail does not change the provider-neutral health schema.

The capability vocabulary and mapping must conform to the neutral contracts in
`app/model_access/` and preserve the separation between availability discovery and policy authority
defined by ADR-0063. The current request fields such as `structured_output`, `native_tools`,
`literal_system_role_required`, and `max_output_tokens_required` are capability inputs, not a
provider list. This task defines the health mapping without declaring unsupported capabilities
available.

## Acceptance Criteria

- [x] Aggregate LLM health evaluates configured logical capabilities through adapter descriptors
  and has no provider-name-specific readiness branches.
  - Verify: `tests/model_access/test_capability_health.py::test_health_uses_provider_neutral_capability_contract`
- [x] Removing an unselected provider does not degrade health when the selected route supplies every
  required capability.
  - Verify: `tests/model_access/test_capability_health.py::test_unselected_provider_absence_does_not_fail_health`
- [x] Every required status aggregates deterministically: only fresh `available` keeps `llm_access`
  healthy; `degraded`, `unavailable`, `unknown`, missing, malformed, stale, or future-dated
  observations make `llm_access.ok`, top-level `/api/health.required_ok`, and `/api/health.ok` false
  with a safe capability-level reason and no provider identity in the public result. Duplicate
  observations reduce deterministically independent of input order.
  - Verify: `tests/model_access/test_capability_health.py::test_required_capability_status_controls_aggregate_health`
  - Verify: `tests/model_access/test_capability_health.py::test_duplicate_capability_observations_are_order_independent`
- [x] Network-path reachability is separate from logical capability status. Successful configured
  path fallback is reported as degraded transport while available capabilities remain available;
  typed path failures report capability unavailability, unclassified path failures report capability
  uncertainty, and route/capability failures remain distinguishable. Public health omits path identity.
  - Verify: `tests/model_access/test_capability_health.py::test_configured_path_fallback_preserves_capability_health`
  - Verify: `tests/model_access/test_capability_health.py::test_transport_failure_is_separate_from_route_capability_failure`
  - Verify: `tests/cli/test_health_llm_routing.py::test_unclassified_remote_path_failure_reports_unknown_capability`
  - Verify: `tests/cli/test_health_llm_routing.py::test_typed_remote_path_failure_keeps_capability_unavailable`
  - Verify: `tests/cli/test_health_llm_routing.py::test_product_health_rejects_local_codex_cli_transport`
  - Verify: `tests/api/test_health_api.py::test_health_api_omits_selected_route_identity`
- [x] Replacing one compatible provider adapter with another leaves the health schema and logical
  capability identifiers unchanged.
  - Verify: `tests/model_access/test_capability_health.py::test_provider_substitution_preserves_health_schema`
- [x] A required capability with no bounded observation, including a requested output-token limit,
  remains `unknown` and keeps required capability health false.
  - Verify: `tests/model_access/test_capability_health.py::test_unknown_output_limit_capability_fails_closed`
- [x] Health checks perform no inference, do not select a fallback, and keep embedding-index and
  `/readyz` contracts separate. Health also disables catalog promotion on the production route
  facade so the probe checks the exact configured route without mutating catalog selection state.
  - Verify: `tests/model_access/test_capability_health.py::test_health_is_no_inference_and_preserves_readiness_boundaries`

## Out of Scope

- Changing provider/model selection or fallback policy.
- Adding an inference-based synthetic probe.
- Moving embedding identity or store readiness into the model capability-health contract.
- Changing Builder health ownership.
