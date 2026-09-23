---
name: Build Adapter Registry and Codex CLI Transport
description: Add the shared adapter factory and a bounded local Codex CLI executor while retaining the Model Inquiry codex_subscription compatibility alias.
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

Deliver the bounded local Codex CLI executor and a registry that binds provider-neutral routes to explicit adapters. The Product-side remote transport is a separate MARR-08 slice. The executor uses the existing host-local subscription login without creating a metered API key.

## What This Task Does

Register `codex_cli`, `ollama_http`, `openai_api`, `anthropic_api`, `deepseek_api`, and `mock` adapters behind the shared contract. Generalize the existing Model Inquiry bridge internally to the local Codex CLI adapter while retaining `codex_subscription` as a Model Inquiry compatibility name. Keep DeepSeek on an explicit adapter backed by its already-declared Product provider/model configuration; do not require new credentials or implicitly retire its current route.

The Codex executor runs only on the designated macOS host. It preflights the executable/version/login status from the same active interactive user session that owns the existing Keychain-backed Codex login; fresh non-interactive SSH is not supported. It binds one exact model and reasoning effort, then runs `codex exec --ephemeral` in a dedicated empty work directory—not the Product workspace or repository. It enforces `--sandbox read-only`, ignores user/project configuration, and applies a version-reviewed safe profile. Before each inference it inspects the CLI's bundled model catalog, rejects unknown catalog shapes or missing exact model IDs, and injects a temporary sanitized catalog with model-derived tool surfaces neutralized alongside the declared CLI tool gates. Unknown CLI versions, flags, catalog fields, or profiles fail closed before inference. The read-only sandbox and empty cwd are defense-in-depth, not substitutes for the no-tools requirement; fixture tests validate the adapter's effective catalog/config, while designated-host acceptance remains necessary before activation.

The Codex invocation preserves trusted and untrusted prompt channels. Product system-instruction content is passed only as the CLI's separate `developer_instructions` override; user content is passed only as the user prompt. Do not concatenate the fields. This does not claim that the CLI's developer role is literally a system role: reject requests whose policy requires that exact role. A CLI-version-pinned test verifies the mapping and that ambient files/config cannot replace it. The executor exposes no Product shell, file, browser/computer, MCP, app, plugin, agent-spawn, or other tool capability. It requests `--output-schema` only when the installed CLI supports it and strictly validates the result either way. It classifies missing CLI, auth/session expiry, unsupported safe-execution profile, timeout, CLI exit, output-bound, and schema errors separately. It does not retry with a new model or provider after execution begins.

Host path, CODEX_HOME, login session, and credential values remain host-local. This task implements the local executor only; it does not install or activate its host service, configure Tailscale Serve, or edit tailnet grants. The executor does not enable unrestricted shell or write execution merely because Codex CLI can run tools; tool capability is never declared by this slice.

## Concretely

The executor receives an exact resolved target such as provider=openai, model=<catalog-resolved-id>, transport=codex_cli; preflight either returns ready or a typed preflight failure. The host-local profile is loaded by path and binds the exact CLI version, tool-surface inventory version, and model-catalog schema version; callers cannot inject a profile object. Before each inference the executor reads the bundled model catalog, rejects unknown fields or an absent exact model, and supplies Codex a temporary catalog with every known model-derived tool surface neutralized. Fixture tests verify the sanitized catalog, disabled configuration gates, isolated working directory, separate instruction/user fields, and process-group cleanup on the outer bridge timeout. This is adapter-level evidence, not a substitute for the designated-host runtime acceptance before activation. The factory never picks the next catalog model itself.

The checked-in adapter declaration contains transport metadata only; concrete provider/model IDs
continue to come from `providers.yaml`. Only the local Codex CLI process executor is introduced in
this slice; the Ollama/API executor implementations and Product caller migration remain later tasks.
Model Inquiry's `codex_subscription` bridge delegates to the same Codex executor but remains
single-target and fallback-forbidden. A Mac host must supply its exact CLI-version safe profile
through `CODEX_CLI_SAFE_PROFILE_PATH` outside Git. No host profile, subscription state, or live CLI
call is part of this repository change.

## Why This Matters

Model Inquiry already has a bounded CLI bridge, but Product cannot route through it and the current adapter name is policy-specific. Generalizing transport code without preserving policy isolation could silently make a Builder subscription exception available to Product or introduce unbounded host effects.

## Acceptance Criteria

- [x] Factory registration is derived from declared provider/transport configuration and resolves the six supported adapter IDs, including the existing DeepSeek route.
  - Verify: `tests/model_access/test_adapter_factory.py::test_factory_resolves_only_declared_adapter_ids`
- [x] Codex preflight checks CLI version, login status, and the bundled catalog for the exact model; it reports typed missing-cli/session-expired/model-unavailable failures without exposing host secrets.
  - Verify: `tests/model_access/test_codex_cli_adapter.py::test_preflight_classifies_cli_auth_and_version_failures`
- [x] Codex execution pins one exact model/reasoning value, uses ephemeral execution, bounds output, and never retries another model after start.
  - Verify: `tests/model_access/test_codex_cli_adapter.py::test_execution_is_ephemeral_pinned_bounded_and_single_target`
- [x] Schema handling uses --output-schema only when supported and otherwise strictly validates JSON locally.
  - Verify: `tests/model_access/test_codex_cli_adapter.py::test_schema_support_and_strict_validation_fallback`
- [x] Codex execution preserves trusted instruction and user channels by using separate `developer_instructions` and user-prompt inputs; it never concatenates them or claims literal system-role equivalence.
  - Verify: `tests/model_access/test_codex_cli_adapter.py::test_trusted_instruction_and_user_content_use_separate_channels`
- [x] Codex execution uses a read-only sandbox and isolated work directory, neutralizes the version-pinned model catalog and declared CLI tool gates, and fails closed on an unknown CLI version/catalog shape or missing exact model.
  - Verify: `tests/model_access/test_codex_cli_adapter.py::test_execution_is_ephemeral_pinned_bounded_and_single_target`, `tests/model_access/test_codex_cli_adapter.py::test_versioned_no_tools_profile_fails_closed_on_unknown_features`, `tests/model_access/test_codex_cli_adapter.py::test_catalog_schema_drift_and_unknown_model_fail_before_model_execution`
- [x] The subscription bridge outer timeout terminates the Codex CLI process tree rather than leaving inference running after the caller times out.
  - Verify: `tests/model_access/test_codex_cli_adapter.py::test_local_bridge_timeout_kills_codex_process_group`
- [x] DeepSeek routes retain a declared adapter and existing configured endpoint/model behavior without requiring new credentials.
  - Verify: `tests/model_access/test_adapter_factory.py::test_deepseek_route_remains_available_from_declared_provider_config`
- [x] codex_subscription remains an alias that keeps Model Inquiry single-target and fallback-forbidden.
  - Verify: `tests/builderops/test_model_inquiry_adapters.py::test_codex_subscription_alias_preserves_no_fallback_contract`
- [x] No Product tool capability is advertised without a tested, bounded tool contract.
  - Verify: `tests/model_access/test_codex_cli_adapter.py::test_unimplemented_product_tools_are_not_advertised`

## How to Verify (Pre-Merge)

- Run pytest -q tests/model_access/test_adapter_factory.py tests/model_access/test_codex_cli_adapter.py tests/builderops/test_model_inquiry_adapters.py.
- Use fake Codex executables and model-catalog/config fixtures for version, login, no-tools profile, catalog drift, prompt-channel mapping, isolated cwd/environment, timeout/process cleanup, exit, schema, and output-size cases; do not invoke a live model.
- Inspect route/receipt fixtures and logs for secret redaction.

## Out of Scope

- Installing or activating a designated-host service, changing Tailscale policy/Serve configuration, or changing subscription state.
- Enabling arbitrary command execution, writes, or Product native tools without a separately verified sandbox/contract.
- Selecting a replacement model after the route was resolved.

## Related Docs

- docs/adr/ADR-0064-model-access-substrate.md
- docs/adr/ADR-0066-shared-model-access-router-and-catalogs.md
- docs/BUILDEROPS_MODEL_INQUIRY/MODEL_TURN_ADAPTERS.md
- docs/MODEL_ACCESS_ROUTER/README.md

## Related GitHub Issues

Created from this specification; issue number is written here when filed.
