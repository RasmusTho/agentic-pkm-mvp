---
name: Formalize Ollama and Preflight Fallback
description: Put Ollama behind the shared adapter contract and enforce capability-preserving fallback only before a remote execute request can reach the Codex executor.
task_id: MARR-03
github_issue: 5621
source_anchor: docs/adr/ADR-0066-shared-model-access-router-and-catalogs.md :: D3
parent_capability: MODEL_ACCESS_ROUTER
prerequisites: [MARR-01, MARR-02]
depends_on: [ESTABLISH_SHARED_ROUTE_AND_PROVENANCE_CONTRACTS.md, BUILD_ADAPTER_REGISTRY_AND_CODEX_CLI_TRANSPORT.md]
can_parallelize_with: []
---

# FORMALIZE_OLLAMA_AND_PREFLIGHT_FALLBACK

## Purpose

Make current Ollama behavior a first-class adapter and enforce the accepted boundary: Ollama may replace the remote Codex executor only after failed preflight and only when it satisfies the complete declared intent.

## What This Task Does

Reuse current endpoint and timeout behavior behind ollama_http. Preflight checks the configured host, model presence, structured-output support, and model-declared capabilities. Native tools are false unless actual model metadata plus adapter-level behavior establish them.

The router may move from Codex CLI/Luna to Ollama only when remote executor/Tailscale authorization, CLI authentication, or model preflight fails before an inference request is sent. A capability mismatch is not a successful fallback. Any failure after an execute request may have reached the executor is terminal/indeterminate; it does not start another provider request.

## Concretely

A text/JSON intent may use a compatible configured Ollama model after executor connectivity/auth preflight failure. A route requiring native tools or a literal system role is rejected when the current Ollama profile does not provide the exact required capability. A timeout after the remote execute request is sent returns a terminal/indeterminate result without calling Ollama.

## Why This Matters

Fallback can silently change model capabilities, duplicate external effects, or make a partial/failed call appear successful. Restricting fallback to preflight preserves the exact capability contract and avoids double execution.

## Acceptance Criteria

- [ ] Ollama preflight validates host reachability, requested local model, structured output, and only declared capabilities.
  - Verify: `tests/model_access/test_ollama_adapter.py::test_preflight_reports_model_and_declared_capabilities`
- [ ] Compatible fallback occurs only after a typed Codex/executor preflight failure and before any remote execute request can reach the host.
  - Verify: `tests/model_access/test_fallback_policy.py::test_compatible_fallback_occurs_before_first_model_call`
- [ ] A tool route is rejected when Ollama lacks native tools.
  - Verify: `tests/model_access/test_fallback_policy.py::test_ollama_is_rejected_when_native_tools_are_required`
- [ ] A timeout or error after remote execute may have reached the Codex executor is terminal and makes no second provider call.
  - Verify: `tests/model_access/test_fallback_policy.py::test_post_start_failure_never_calls_fallback_provider`
- [ ] Fallback route and failure reason are bound to provenance without endpoints or credentials.
  - Verify: `tests/model_access/test_fallback_policy.py::test_fallback_receipt_binds_preflight_reason_without_secrets`

## How to Verify (Pre-Merge)

- Run pytest -q tests/model_access/test_ollama_adapter.py tests/model_access/test_fallback_policy.py.
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
