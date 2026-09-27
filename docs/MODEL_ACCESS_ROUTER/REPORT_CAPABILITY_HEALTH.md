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
  capability that cannot be provided by the selected route is unavailable; health must not silently
  weaken the requirement.
- Network-path reachability is reported as a separate transport observation. A configured
  pre-completion path fallback may preserve capability availability, but the health evaluator does
  not change the route or trigger inference.
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

- [ ] Aggregate LLM health evaluates configured logical capabilities through adapter descriptors
  and has no provider-name-specific readiness branches.
  - Verify: `tests/model_access/test_capability_health.py::test_health_uses_provider_neutral_capability_contract`
- [ ] Removing an unselected provider does not degrade health when the selected route supplies every
  required capability.
  - Verify: `tests/model_access/test_capability_health.py::test_unselected_provider_absence_does_not_fail_health`
- [ ] A required capability missing from the selected adapter degrades or fails health with a safe
  capability-level reason and no provider identity in the public health result.
  - Verify: `tests/model_access/test_capability_health.py::test_missing_required_capability_is_reported_without_provider_identity`
- [ ] Replacing one compatible provider adapter with another leaves the health schema and logical
  capability identifiers unchanged.
  - Verify: `tests/model_access/test_capability_health.py::test_provider_substitution_preserves_health_schema`
- [ ] Health checks perform no inference, do not select a fallback, and keep embedding-index and
  `/readyz` contracts separate.
  - Verify: `tests/model_access/test_capability_health.py::test_health_is_no_inference_and_preserves_readiness_boundaries`

## Out of Scope

- Changing provider/model selection or fallback policy.
- Adding an inference-based synthetic probe.
- Moving embedding identity or store readiness into the model capability-health contract.
- Changing Builder health ownership.
