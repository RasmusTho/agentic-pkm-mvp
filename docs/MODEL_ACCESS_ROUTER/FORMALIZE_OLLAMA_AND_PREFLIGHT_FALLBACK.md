---
name: Formalize Ollama and Preflight Fallback
description: Add authenticated no-inference preflight to the thin executor API, put Ollama behind the adapter contract, and enforce capability-preserving fallback before completion.
task_id: MARR-03
github_issue: 5621
source_anchor: docs/adr/ADR-0066-shared-model-access-router-and-catalogs.md :: D3
parent_capability: MODEL_ACCESS_ROUTER
prerequisites: [MARR-01, MARR-02, MARR-08]
depends_on: [ESTABLISH_SHARED_ROUTE_AND_PROVENANCE_CONTRACTS.md, BUILD_ADAPTER_REGISTRY_AND_CODEX_CLI_TRANSPORT.md, ADD_TAILSCALE_CODEX_EXECUTOR_TRANSPORT.md]
can_parallelize_with: []
---

# FORMALIZE_OLLAMA_AND_PREFLIGHT_FALLBACK

## Purpose

Make current Ollama behavior a first-class adapter and enforce the accepted boundary: Ollama may replace the remote Codex executor only after failed preflight and only when it satisfies the complete declared intent. Extend the already-merged thin Mac API with one authenticated, bounded, no-inference `POST /v1/preflight`; Product remains the route/fallback policy authority.

## What This Task Does

Reuse current endpoint and timeout behavior behind `ollama_http`. The host's `POST /v1/preflight` accepts only an exact route, optional Codex reasoning effort, and capability intent; it accepts no prompts, schemas, credentials, or execution controls. It has a distinct Serve-forwarded `preflight` action and only probes the named adapter. Codex preflight validates the safe CLI profile, version, subscription auth, exact model, and requested reasoning effort. Ollama preflight performs bounded read-only model-list/show requests, verifies the exact local model, and reports only adapter-supported capabilities. Structured output is supported by the declared Ollama chat transport/schema-validation path; native tools remain false because this adapter does not execute tools.

Product may move from Codex CLI/Luna to Ollama only after a typed preflight failure and before sending any completion request. The Product-side client can issue a distinct route-bound preflight request; the executor never selects a fallback. Only minimal/low general text or JSON routes may use the configured Ollama fallback; stronger reasoning requirements and any literal-system-role requirement remain on the primary route or fail closed. A capability mismatch is not a successful fallback. Any failure after a completion request may have reached the executor is terminal/indeterminate; it does not start another provider request.

## Concretely

A text/JSON intent may use a compatible configured Ollama model after executor connectivity/auth/model preflight failure. Preflight is a no-inference `POST /v1/preflight` authenticated by its own Serve app-capability action. Native-tool requests fail closed when Ollama lacks native tools, and literal-system-role requests are never eligible for Ollama fallback even if the current profile can represent a system message. A timeout after the one remote completion request is sent returns a terminal/indeterminate result without calling Ollama.

## Why This Matters

Fallback can silently change model capabilities, duplicate external effects, or make a partial/failed call appear successful. Restricting fallback to preflight preserves the exact capability contract and avoids double execution.

## Acceptance Criteria

- [ ] The executor exposes an authenticated, bounded no-inference preflight for one exact route and capability intent; it validates the target without dispatching completion.
  - Verify: `tests/model_access/test_codex_executor_service.py::test_preflight_probes_exact_declared_route_without_completion`
- [ ] The Product remote client sends a route-bound preflight request before any completion request and returns only sanitized typed readiness/failure.
  - Verify: `tests/model_access/test_codex_remote_transport.py::test_remote_preflight_is_route_bound_and_single_request`
- [ ] Ollama preflight validates host reachability, requested local model, structured output, and only declared capabilities.
  - Verify: `tests/model_access/test_ollama_adapter.py::test_preflight_reports_model_and_declared_capabilities`
- [ ] Compatible fallback occurs only after a typed Codex/executor preflight failure and before any remote execute request can reach the host.
  - Verify: `tests/model_access/test_fallback_policy.py::test_compatible_fallback_occurs_before_first_model_call`
- [ ] Stronger reasoning requests do not downgrade to Ollama after a Codex preflight failure.
  - Verify: `tests/model_access/test_fallback_policy.py::test_strong_reasoning_failure_does_not_downgrade_to_ollama`
- [ ] A literal-system-role request is not downgraded to Ollama after a Codex preflight failure.
  - Verify: `tests/model_access/test_fallback_policy.py::test_literal_system_role_requirement_does_not_downgrade_to_ollama`
- [ ] A tool route is rejected when Ollama lacks native tools.
  - Verify: `tests/model_access/test_fallback_policy.py::test_ollama_is_rejected_when_native_tools_are_required`
- [ ] A timeout or error after remote execute may have reached the Codex executor is terminal and makes no second provider call.
  - Verify: `tests/model_access/test_fallback_policy.py::test_post_start_failure_never_calls_fallback_provider`
- [ ] Fallback route and failure reason are bound to provenance without endpoints or credentials.
  - Verify: `tests/model_access/test_fallback_policy.py::test_fallback_receipt_binds_preflight_reason_without_secrets`

## How to Verify (Pre-Merge)

- Run `pytest -q tests/model_access/test_ollama_adapter.py tests/model_access/test_fallback_policy.py tests/model_access/test_codex_executor_service.py tests/model_access/test_codex_remote_transport.py`.
- Use fake HTTP responses and a call counter to prove that fallback is pre-send only and an ambiguous remote execute timeout does not invoke another provider.
- Include missing-host, missing-model, undeclared-tool, structured-output, and timeout cases.

## Out of Scope

- Downloading, updating, or changing any Ollama model.
- Fallback for Model Inquiry or any Builder route that declares fallback_forbidden.
- Retry, failover, or shadow inference after execution starts.

## Related Docs

- docs/adr/ADR-0063-shared-llm-contract-kernel.md
- docs/adr/ADR-0064-model-access-substrate.md
- docs/adr/ADR-0066-shared-model-access-router-and-catalogs.md
- docs/LLM_ROUTING.md
- docs/MODEL_ACCESS_ROUTER/README.md

## Related GitHub Issues

Created from this specification; issue number is written here when filed.
