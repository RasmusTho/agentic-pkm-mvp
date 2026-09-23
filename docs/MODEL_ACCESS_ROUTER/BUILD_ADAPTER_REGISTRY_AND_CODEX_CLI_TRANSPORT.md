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

The Codex executor runs only on the designated macOS host. It preflights the executable/version/login status from the same active interactive user session that owns the existing Codex subscription login; fresh non-interactive SSH is not supported. Subscription execution requires the exact `Logged in using ChatGPT` auth mode; API-key, workload-identity, expired, or otherwise ambiguous modes fail closed before inference. The executor reads only the host-local `cli_auth_credentials_store` setting (bounded and parsed from `CODEX_HOME/config.toml`, or the default `~/.codex/config.toml`) and explicitly pins that same approved `file` or `keyring` backend for both login-status preflight and inference. Credential material and the selected backend are not copied into prompts, intent, receipts, or diagnostics. It binds one exact model and reasoning effort, then runs `codex exec --ephemeral` in a dedicated empty work directory—not the Product workspace or repository. It enforces `--sandbox read-only`, ignores user/project configuration, and applies a version-reviewed safe profile. Before each inference it inspects the CLI's bundled model catalog, validates the pinned descriptor schema and value types, rejects missing exact model IDs, and injects a temporary sanitized catalog with model-derived tool surfaces neutralized alongside the declared CLI tool gates. Unknown CLI versions, flags, catalog fields, malformed descriptors, or profiles fail closed before inference. The read-only sandbox and empty cwd are defense-in-depth, not substitutes for the no-tools requirement; fixture tests validate the adapter's effective catalog/config, while designated-host acceptance remains necessary before activation.

The Codex invocation preserves trusted and untrusted prompt channels. Product system-instruction content is passed only as the CLI's separate `developer_instructions` override; user content is passed only as the user prompt. Do not concatenate the fields. This does not claim that the CLI's developer role is literally a system role: reject requests whose policy requires that exact role. A CLI-version-pinned test verifies the mapping and that ambient files/config cannot replace it. The executor exposes no Product shell, file, browser/computer, MCP, app, plugin, agent-spawn, or other tool capability, and its implementation-owned capability ceiling cannot be raised by registry configuration. It requests `--output-schema` only when the installed CLI supports it; regardless of CLI support, the parent snapshots and validates a byte/depth/node-bounded inline JSON Schema before any provider call. References, regexes, and unsupported keywords fail closed. Responses are byte/depth bounded, reject duplicate keys and non-finite numeric values, and map parser/validator exhaustion to a typed schema error. The last-message file has an OS-enforced per-file size ceiling during execution. A separate guardian process owns the CLI process group, watches direct-parent and original-caller liveness pipes, enforces its own deadline, and cleans descendants promptly after leader exit. The Model Inquiry local-command adapter passes the original caller's liveness pipe through its compatibility bridge to that guardian, so caller death cannot leave a separately-sessioned bridge performing inference. Status-pipe descriptors are closed on EOF. The executor validates the opened source executable and launches a copy-on-write snapshot in the same resolved install `bin` directory, preserving Codex's `current_exe()` resource discovery while preventing a source-path replacement from substituting another binary. On APFS, snapshot creation does not copy the full standalone CLI image. Both caller and guardian clean the snapshot after normal completion or cancellation. It classifies missing CLI, auth/session expiry, unsupported safe-execution profile, timeout, CLI exit, output-bound, and schema errors separately. It does not retry with a new model or provider after execution begins.

Adapter metadata follows the actual transport channel: Codex's reviewed developer-prompt mapping resolves to `developer_instructions`, while provider API, Ollama, and mock declarations using `profile.instructions_separate_v1` resolve to a literal `system` channel. The real factory-to-router path preserves literal-system-role requests for compatible provider transports.

Host path, CODEX_HOME, login session, and credential values remain host-local. This task implements the local executor only; it does not install or activate its host service, configure Tailscale Serve, or edit tailnet grants. The executor does not enable unrestricted shell or write execution merely because Codex CLI can run tools; tool capability is never declared by this slice.

## Concretely

The executor receives an exact resolved target such as provider=openai, model=<catalog-resolved-id>, transport=codex_cli; preflight either returns ready or a typed preflight failure. The host-local profile is loaded by path and binds the exact CLI version, tool-surface inventory version, and model-catalog schema version; callers cannot inject a profile object. Before each inference the executor reads the bundled model catalog, validates every required field and nested descriptor shape/value type, requires the selected model to declare the requested reasoning effort, rejects unknown fields or an absent exact model, and supplies Codex a temporary catalog with model message/tool metadata and all known model-derived tool surfaces neutralized. Fixture tests verify exact ChatGPT-only auth (including mixed-status refusal), malformed/deep-catalog rejection, typed deep-profile failure, the hard file-size ceiling, bounded schema admission independent of CLI schema support, strict JSON constants/depth, status-pipe descriptor cleanup, the sanitized catalog, immutable capability ceilings, disabled configuration gates, isolated working directory, separate instruction/user fields, factory/router literal-system compatibility, original-Inquiry-caller and direct-parent/deadline cleanup, leader/descendant cleanup, a snapshot cloned from the identity-checked open descriptor, and preservation of the resolved install-bin context. On APFS the snapshot is a copy-on-write clone; it does not copy the full standalone CLI image for each preflight command. This is adapter-level evidence, not a substitute for the designated-host runtime acceptance before activation. The factory never picks the next catalog model itself.

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
- [x] Codex preflight checks CLI version, ChatGPT subscription login mode, and the bundled catalog for the exact model; it preserves the approved host-local credential backend across status and execution, rejects API-key auth, and reports typed missing-cli/session-expired/model-unavailable failures without exposing host secrets.
  - Verify: `tests/model_access/test_codex_cli_adapter.py::test_preflight_classifies_cli_auth_and_version_failures`
- [x] Codex execution pins one exact model/reasoning value, uses ephemeral execution, hard-bounds the last-message file during execution, cleans descendants after leader exit, and never retries another model after start.
  - Verify: `tests/model_access/test_codex_cli_adapter.py::test_execution_is_ephemeral_pinned_bounded_and_single_target`
- [x] Schema handling snapshots, bounds, and validates an inline schema before inference; it uses --output-schema only when supported and otherwise strictly validates standards-compliant response JSON locally, rejecting recursion and non-finite numbers.
  - Verify: `tests/model_access/test_codex_cli_adapter.py::test_schema_support_and_strict_validation_fallback`
- [x] Codex execution preserves trusted instruction and user channels by using separate `developer_instructions` and user-prompt inputs; it never concatenates them or claims literal system-role equivalence.
  - Verify: `tests/model_access/test_codex_cli_adapter.py::test_trusted_instruction_and_user_content_use_separate_channels`
- [x] Codex execution uses a read-only sandbox and isolated work directory, neutralizes the version-pinned model catalog and declared CLI tool gates, and fails closed on an unknown CLI version/catalog shape or missing exact model.
  - Verify: `tests/model_access/test_codex_cli_adapter.py::test_execution_is_ephemeral_pinned_bounded_and_single_target`, `tests/model_access/test_codex_cli_adapter.py::test_versioned_no_tools_profile_fails_closed_on_unknown_features`, `tests/model_access/test_codex_cli_adapter.py::test_catalog_schema_drift_and_unknown_model_fail_before_model_execution`
- [x] The subscription bridge outer timeout terminates the Codex CLI process tree rather than leaving inference running after the caller times out.
  - Verify: `tests/model_access/test_codex_cli_adapter.py::test_local_bridge_timeout_kills_codex_process_group`
- [x] A successfully exiting CLI cannot leave same-group descendants running after the final response returns.
  - Verify: `tests/model_access/test_codex_cli_adapter.py::test_exit_cleanup_kills_descendant_with_redirected_output` (inherited and redirected child streams)
- [x] Killing the original Model Inquiry caller propagates through the local-command bridge and terminates both the bridge and Codex process tree, not only the Codex executor's immediate parent.
  - Verify: `tests/model_access/test_codex_cli_adapter.py::test_model_inquiry_caller_loss_terminates_codex_process_tree`
- [x] Repeated preflight calls close status-pipe descriptors, and over-nested safe-profile/catalog JSON becomes a typed fail-closed error.
  - Verify: `tests/model_access/test_codex_cli_adapter.py::test_repeated_preflight_closes_status_pipe_descriptors`, `tests/model_access/test_codex_cli_adapter.py::test_deeply_nested_profile_and_catalog_fail_with_typed_errors`
- [x] Provider API/Ollama/mock adapter declarations map trusted instructions to the literal system channel while Codex retains its developer-instructions mapping; a literal-system requirement survives the real factory/router path.
  - Verify: `tests/model_access/test_adapter_factory.py::test_factory_resolves_only_declared_adapter_ids`, `tests/model_access/test_router_facade.py::test_declared_provider_api_keeps_literal_system_role_through_router`
- [x] Caller death, including before the CLI child establishes its session, or the guardian's independent deadline terminates the Codex CLI process group with bounded cleanup; execution uses a copy-on-write snapshot in the resolved install bin cloned from the identity-checked open descriptor, preserving `current_exe()` resource discovery while preventing source-path replacement from substituting the candidate.
  - Verify: `tests/model_access/test_codex_cli_adapter.py::test_guardian_caller_loss_before_setsid_cannot_release_cli`, `tests/model_access/test_codex_cli_adapter.py::test_guardian_deadline_alone_kills_cli_process_group`, `tests/model_access/test_codex_cli_adapter.py::test_parent_loss_terminates_codex_process_tree`, `tests/model_access/test_codex_cli_adapter.py::test_verified_open_executable_snapshot_survives_path_replacement`, `tests/model_access/test_codex_cli_adapter.py::test_cli_self_replacement_is_confined_to_staged_snapshot`, `tests/model_access/test_codex_cli_adapter.py::test_cli_snapshot_preserves_install_bin_context`
- [x] Model-catalog nested reasoning/service/truncation descriptors are validated, requested effort must be model-declared, and model-message/tool metadata is removed from the sanitized catalog.
  - Verify: `tests/model_access/test_codex_cli_adapter.py::test_catalog_schema_drift_and_unknown_model_fail_before_model_execution`, `tests/model_access/test_codex_cli_adapter.py::test_requested_reasoning_effort_must_be_declared_by_selected_model`
- [x] Codex CLI registry metadata cannot raise the implementation-owned no-tools ceiling or change its subscription/local-subprocess trust boundary.
  - Verify: `tests/model_access/test_adapter_factory.py::test_codex_declaration_cannot_raise_tool_capability_or_change_auth_boundary`
- [x] DeepSeek routes retain a declared adapter and existing configured endpoint/model behavior without requiring new credentials.
  - Verify: `tests/model_access/test_adapter_factory.py::test_deepseek_route_remains_available_from_declared_provider_config`
- [x] codex_subscription remains an alias that keeps Model Inquiry single-target and fallback-forbidden.
  - Verify: `tests/builderops/test_model_inquiry_adapters.py::test_codex_subscription_alias_preserves_no_fallback_contract`
- [x] No Product tool capability is advertised without a tested, bounded tool contract.
  - Verify: `tests/model_access/test_codex_cli_adapter.py::test_unimplemented_product_tools_are_not_advertised`

## How to Verify (Pre-Merge)

- Run pytest -q tests/model_access/test_adapter_factory.py tests/model_access/test_codex_cli_adapter.py tests/builderops/test_model_inquiry_adapters.py.
- Use fake Codex executables and model-catalog/config fixtures for version, login, no-tools profile, catalog drift, prompt-channel mapping, isolated cwd/environment, pre-`setsid` caller cancellation, guardian-only deadline cleanup, inherited and redirected descendant streams, schema, and output-size cases; do not invoke a live model.
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
