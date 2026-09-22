---
name: Build Adapter Registry and Codex CLI Transport
description: Add the shared adapter factory and a bounded Codex CLI adapter while retaining the Model Inquiry codex_subscription compatibility alias.
task_id: MARR-02
github_issue: 5620
source_anchor: docs/adr/ADR-0066-shared-model-access-router-and-catalogs.md :: D2
parent_capability: MODEL_ACCESS_ROUTER
prerequisites: [MARR-01]
depends_on: [ESTABLISH_SHARED_ROUTE_AND_PROVENANCE_CONTRACTS.md]
can_parallelize_with: []
---

# BUILD_ADAPTER_REGISTRY_AND_CODEX_CLI_TRANSPORT

## Purpose

Deliver the first-class Codex CLI transport and a registry that binds provider-neutral routes to explicit adapters. Product can use its existing host-local subscription login without creating a metered API key.

## What This Task Does

Register codex_cli, ollama_http, openai_api, anthropic_api, and mock adapters behind the shared contract. Generalize the existing Model Inquiry bridge internally to the Codex CLI adapter while retaining codex_subscription as a Model Inquiry compatibility name.

The Codex adapter preflights executable/version/login status, binds one exact model and reasoning effort, and runs `codex exec --ephemeral` in a dedicated empty work directory—not the Product workspace or repository. It enforces `--sandbox read-only`, disables `shell_tool` and `unified_exec`, ignores ambient user/project tool configuration, and passes only an explicit host-local environment allowlist needed for authentication. It exposes no Product shell, file, MCP, app, or other tool capability. If the installed CLI cannot enforce this profile, preflight fails closed before inference. It requests `--output-schema` only when the installed CLI supports it and strictly validates the result either way. It classifies missing CLI, auth/session expiry, unsupported safe-execution profile, timeout, CLI exit, output-bound, and schema errors separately. It does not retry with a new model or provider after execution begins.

Host path, CODEX_HOME, login session, and credential values remain host-local. The adapter does not enable unrestricted shell or write execution merely because Codex CLI can run tools; tool capability is declared only after the Product tool contract and sandbox are explicitly tested.

## Concretely

The factory receives an exact resolved target such as provider=openai, model=gpt-5.6-luna, transport=codex_cli; preflight either returns ready or a typed preflight failure. The fake executable verifies the safe sandbox flags, isolated working directory, and environment allowlist without reading host state. The factory never picks the next catalog model itself.

## Why This Matters

Model Inquiry already has a bounded CLI bridge, but Product cannot route through it and the current adapter name is policy-specific. Generalizing transport code without preserving policy isolation could silently make a Builder subscription exception available to Product or introduce unbounded host effects.

## Acceptance Criteria

- [ ] Factory registration is derived from declared provider/transport configuration and resolves the five supported adapter IDs.
  - Verify: `tests/model_access/test_adapter_factory.py::test_factory_resolves_only_declared_adapter_ids`
- [ ] Codex preflight checks CLI version and login status and reports typed missing-cli/session-expired failures without exposing host secrets.
  - Verify: `tests/model_access/test_codex_cli_adapter.py::test_preflight_classifies_cli_auth_and_version_failures`
- [ ] Codex execution pins one exact model/reasoning value, uses ephemeral execution, bounds output, and never retries another model after start.
  - Verify: `tests/model_access/test_codex_cli_adapter.py::test_execution_is_ephemeral_pinned_bounded_and_single_target`
- [ ] Schema handling uses --output-schema only when supported and otherwise strictly validates JSON locally.
  - Verify: `tests/model_access/test_codex_cli_adapter.py::test_schema_support_and_strict_validation_fallback`
- [ ] Product Codex execution uses a read-only sandbox, disables shell/execution features, ignores ambient tool configuration, and runs in the isolated work directory; unsupported CLI profiles fail before inference.
  - Verify: `tests/model_access/test_codex_cli_adapter.py::test_exec_disables_host_tools_and_uses_isolated_readonly_workdir`
- [ ] codex_subscription remains an alias that keeps Model Inquiry single-target and fallback-forbidden.
  - Verify: `tests/builderops/test_model_inquiry_adapters.py::test_codex_subscription_alias_preserves_no_fallback_contract`
- [ ] No Product tool capability is advertised without a tested, bounded tool contract.
  - Verify: `tests/model_access/test_codex_cli_adapter.py::test_unimplemented_product_tools_are_not_advertised`

## How to Verify (Pre-Merge)

- Run pytest -q tests/model_access/test_adapter_factory.py tests/model_access/test_codex_cli_adapter.py tests/builderops/test_model_inquiry_adapters.py.
- Use a fake Codex executable for version, login, safe-profile flags, isolated cwd/environment, timeout, exit, schema, and output-size cases; do not invoke a live model.
- Inspect route/receipt fixtures and logs for secret redaction.

## Out of Scope

- Modifying Mac mini configuration or subscription state.
- Enabling arbitrary command execution, writes, or Product native tools without a separately verified sandbox/contract.
- Selecting a replacement model after the route was resolved.

## Related Docs

- docs/adr/ADR-0064-model-access-substrate.md
- docs/adr/ADR-0066-shared-model-access-router-and-catalogs.md
- docs/BUILDEROPS_MODEL_INQUIRY/MODEL_TURN_ADAPTERS.md
- docs/MODEL_ACCESS_ROUTER/README.md

## Related GitHub Issues

Created from this specification; issue number is written here when filed.
