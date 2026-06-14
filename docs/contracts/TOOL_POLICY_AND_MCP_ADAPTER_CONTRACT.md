State: Aligned (forward line v5.x)
Doc role: Reference contract
Authority: Canonical current-state contract for the repo's tool descriptor registry, validation posture, timeout handling, and MCP adapter behavior. This document describes enacted behavior only and must stay aligned with `app/planner/tools.py`, `app/components/settings/tools_loader.py`, `docs/settings/tools/`, `app/orchestrator/executor.py`, and `app/orchestrator/mcp_tool_provider.py`.

# Tool Policy And MCP Adapter Contract

This document describes the current tool descriptor registry, validation rules, timeout handling, and the MCP adapter boundary inside the repository for bounded tool execution.
It is a current-state contract for tool descriptor completeness, allowed-argument validation, mock/deterministic test behavior, and audit expectations.
It does not claim rich descriptor versioning or future permission-model expansion as shipped.

Use this document with:
- `docs/ARCHITECTURE.md` for current runtime boundaries and the planner/orchestrator pipeline.
- `docs/AGENTS.md` for the current agent matrix and tool authorization semantics.
- `docs/tracks/TRACK_AGENTOPS_A2A_MCP.md` for backlog/track context and planned MCP/LangGraph integration.
- `docs/contracts/A2A_CONTRACT_AND_TRACE.md` for agent-to-agent coordination.
- `docs/security/AGENT_TOOL_EXECUTION_SECURITY_ADDENDUM.md` for security review framing over
  descriptor trust, remote MCP admission, egress/secrets, trace/audit, and tool-output
  manipulation.

## Current posture

- Tool descriptors are loaded from YAML files referenced by a registry file (`docs/settings/tools/registry.yaml`).
- Two descriptor sources coexist: `app/planner/tools.py` (hardcoded in-repo descriptors) and the YAML registry (external settings-driven descriptors).
- The current tool kinds are: `mcp` (MCP-backed tools), `internal` (repo-owned step handlers), and `cli` (future; not currently dispatched).
- Tool validation happens at execution time in the orchestrator (MockPlanExecutor) and includes argument type checking, required-field validation, and agent authorization checks via `POLICY_ENFORCE`.
- Tool execution supports deterministic/mock behavior for CI and development, real vault append for enabled MCP tools, and internal step handlers for repo-specific operations.
- A local MCP ToolProvider boundary exposes registry-loaded descriptors and delegates execution through the existing executor validation/policy/timeout/mock-real paths.
- A bounded remote multiplex seam is available behind explicit flag `mcp_remote_multiplex_enable`; default behavior remains local registry execution.
- If remote multiplex is enabled but unavailable or failing, execution deterministically falls back to local registry with route reason codes.
- When remote multiplex is enabled and a remote provider is configured, remote descriptors are merged into the local registry on a best-effort basis (try/except; failures are silent and local registry remains available).

## Descriptor sources and structure

### Registry file location
`docs/settings/tools/registry.yaml`

The registry file lists all active tool descriptors:

| Field | Type | Current requirement | Meaning |
| --- | --- | --- | --- |
| `version` | integer | required | Registry schema version (currently 1). |
| `tools` | array | required | List of tool descriptor entries. |

Each registry entry:

| Field | Type | Current requirement | Meaning |
| --- | --- | --- | --- |
| `id` | string | required, non-empty | Stable tool identifier (e.g., `vault.read_note.v1`). |
| `path` | string | required, non-empty | Path to the YAML descriptor file relative to repo root. |
| `status` | string | optional, defaults to `active` | Current status flag (`active`, other values reserved). |

### YAML descriptor file structure

Tool descriptor files live in `docs/settings/tools/*.yaml` and define the complete tool contract.

| Field | Type | Current requirement | Meaning |
| --- | --- | --- | --- |
| `id` | string | required, non-empty | Stable tool identifier (must match registry entry). |
| `status` | string | optional, defaults to `active` | Current status flag. |
| `protocol` | string | required, non-empty | Protocol identifier (e.g., `mcp`, `internal`, `cli`). |
| `server` | string | required, non-empty | Server/handler label (e.g., `vault`, for contextual routing). |
| `description` | string | required, non-empty | Human-readable tool description. |
| `allowed_args` | object | optional, defaults to `{}` | JSON Schema subset defining allowed argument names and types. |
| `mock_result` | object | optional | Result returned by deterministic/mock execution paths. |

The `allowed_args` field uses a constrained schema format:

```yaml
allowed_args:
  type: object
  additionalProperties: false
  properties:
    <arg_name>:
      type: <json_schema_type>  # e.g., "string", "integer", "array", "object"
      description: <optional_string>
    # ... more args
  required: [<required_arg_names>]  # Optional; enforced separately in tests and docs
```

The `<json_schema_type>` values currently recognized by the executor are: `string`, `integer`, `number`, `boolean`, `array`, `object`.
For registry-loaded descriptors, simple top-level unions may also be expressed as `oneOf` entries that each declare one of those `type` values. The executor currently normalizes those unions into pipe-delimited type sets such as `object|string`.

Current behavior: the executor validates that any argument present in the plan step matches the type declared in `allowed_args`. When a descriptor declares a top-level union, the argument may match any normalized member type in that union. The executor separately validates that all `required` fields from the descriptor schema are present in the step's `tool_args`.

### In-repo hardcoded descriptors (legacy coexistence)

`app/planner/tools.py` defines a `MCP_TOOL_DESCRIPTORS` dict with ToolDescriptor objects for backwards compatibility and testing. These can coexist with the YAML registry descriptors but should not overlap on `id`.

Current hardcoded tools include:
- `mcp.vault.append_note`
- `mcp.search.objects`
- `mcp.builderops.list_records`
- `mcp.builderops.read_record`
- `mcp.builderops.create_worklog`
- `mcp.builderops.create_learning_signal`
- `mcp.builderops.create_promotion_intent`
- `mcp.builderops.append_receipt`
- `internal.ingest_external`
- `promotion.emit_intent`

This dual-source pattern is not designed as a long-term feature; the YAML registry is the preferred source for new tool definitions.

## Argument validation posture

The executor (`MockPlanExecutor`) applies two-phase validation:

1. **Type validation** (line 235-243 in `executor.py`):
   - For each argument in the plan step's `tool_args`, check that its value type matches the declared type in `allowed_args`.
   - Example: if `allowed_args` says `{"query": "string"}` and the step provides `tool_args={"query": 123}`, validation fails with error type `invalid_tool_args`.

2. **Required-field validation** (line 245-248 in `executor.py`):
   - Check that all fields listed in the descriptor schema's `required` array are present in `tool_args`.
   - Example: if the schema declares `required: ["title", "body"]` and the step omits `body`, validation fails with error type `invalid_tool_args`.

Current behavior does NOT:
- Coerce or transform argument values (e.g., string to integer).
- Validate nested object structure beyond the top-level type.
- Apply min/max constraints even if the JSON Schema declares them.

## Mock and deterministic test behavior

The executor supports deterministic tool execution for CI and development:

1. **Mock result default**:
   - If a tool descriptor defines `mock_result`, the executor returns that payload during mock execution.
   - If `mock_result` is absent, the executor returns `{"status": "ok"}`.

2. **Real vs. mock decision**:
   - Currently only `mcp.vault.append_note` has a real implementation path.
   - The decision to use real vs. mock is made in `_should_use_real_tool(...)` (line 250-263):
     - If the tool is not `mcp.vault.append_note`, always return mock result.
     - If the tool is `mcp.vault.append_note`:
       - Check `settings.allowed_mcp_tools` (allowlist) and `settings.mcp_vault_enable` or `settings.mcp.enable` (feature flag).
       - Only use the real implementation if the allowlist includes the tool AND the feature flag is enabled.

3. **Determinism guarantee**:
   - Mock execution is deterministic: the same plan step with the same mock result always produces the same output.
   - Real execution (vault append) is non-deterministic but emits outbox events with the result.

## Timeout and execution settings

### Timeout configuration

The executor supports per-plan timeout configuration via `StepContext.tool_settings`:

| Setting | Type | Default | Meaning |
| --- | --- | --- | --- |
| `tool_timeout_seconds` | float (string-parsed) | none (no timeout) | Maximum seconds to allow for a single tool execution. |
| `tool_calls` | integer (tracked in context) | 0 | Current count of tool calls executed in the plan. |
| `max_tool_calls` | integer (string-parsed) | none (unlimited) | Maximum tool calls allowed in the plan. |

Current behavior (lines 184-189):
- If `tool_timeout_seconds` is present in settings, it is parsed as a float.
- If parsing fails, no timeout is applied.
- The executor wraps the tool invocation with `timeout_wrapper(call, timeout_secs)` if a timeout is set.
- A timeout failure raises `StepExecutionError` with error type `tool_timeout`.

### Vault append settings

The executor respects vault-specific settings when executing `mcp.vault.append_note`:

| Setting | Type | Meaning |
| --- | --- | --- |
| `vault_root` | string (path) | Root directory for the vault. If not provided, `append_note(...)` uses default resolution. |
| `mcp_vault_enable` or `mcp.enable` | boolean-like | Feature flag to enable real vault execution. |
| `allowed_mcp_tools` | list | Allowlist of tools to execute in real mode. |

### BuilderOps settings

The executor respects BuilderOps-specific settings when executing `mcp.builderops.*` tools:

| Setting | Type | Meaning |
| --- | --- | --- |
| `builderops_db_path` | string path | Optional BuilderOps SQLite database path. If omitted, normal BuilderOps path resolution applies. |
| `mcp_builderops_enable` | boolean-like | Feature flag to enable real BuilderOps tool execution. Disabled tools return deterministic mock payloads. |
| `allowed_mcp_tools` | list | Allowlist of BuilderOps tools to execute in real mode. |

BuilderOps MCP tools are autonomous-agent-safe only for BuilderOps operational records. They do not
execute promotions, create GitHub Issues, mutate repo docs, or change product/runtime truth.

## Policy enforcement and authorization

Tool execution respects the agent-level policy gate defined in `POLICY_ENFORCE` environment variable:

| Setting | Behavior |
| --- | --- |
| `POLICY_ENFORCE=1` | Enforce agent_id requirement: a tool step without an agent_id raises `policy_denied` error. Check tool authorization via `assert_tool_allowed(agent_id, tool_name)`. |
| `POLICY_ENFORCE=0` or unset | Allow any tool step regardless of agent_id; no authorization check. |

Current authorization (line 157):
- The executor calls `assert_tool_allowed(agent_id, descriptor.name)`.
- This check is defined in `app/policy/enforce.py` and is currently minimal: by default, it allows all known tools for all agents if the policy is enforced.

Current error on policy denial: error type `policy_denied`.

## Tool execution events and audit

The executor emits outbox events for tool execution:

### Event types

| Event | Source | Timing | Fields |
| --- | --- | --- | --- |
| `mcp.tool.call.started` | `emit_mcp_tool_call_started(...)` | Before tool execution | `plan_id`, `step_id`, `tool_name`, `object_id`, `trace_id`, `provider_route`, optional route reason metadata |
| `mcp.tool.call.finished` | `emit_mcp_tool_call_finished(...)` | After successful tool execution | `plan_id`, `step_id`, `tool_name`, `result`, `object_id`, `trace_id`, `provider_route`, optional route reason metadata |
| (vault-specific) `mcp.vault.append_note` | `OutboxEvent(event=..., source="orchestrator.runtime", ...)` (line 276-283) | After real vault append | `trace_id` if available |

### Trace propagation

- If `StepContext.trace_id` is provided, it is included in all emitted events.
- Correlation is implicit: all events for one plan step share the same `plan_id` and `step_id`.

### Current limitation

- Tool errors (validation failures, timeouts, policy denials) do not emit a separate error event; they raise `StepExecutionError` which is handled at the orchestrator level.
- See `ORCHESTRATOR_STEP_ERROR` event type in `app/events/types.py` for the higher-level error handling.

## Internal tool handlers

The executor defines built-in handlers for `internal` protocol tools:

| Tool | Behavior | Error type on failure |
| --- | --- | --- |
| `internal.ingest_external` | Calls `ingest_external_folder(root_dir, limit=...)` with validation of required args. | `internal_tool_error` |
| `promotion.emit_intent` | Calls `_run_promotion_intent(...)` which emits a `promote.intent.created` event to the outbox. | `internal_tool_error` |

Both are handled synchronously during plan execution and do not support real vs. mock branching (they always execute).

## MCP discovery

Dynamic MCP descriptor discovery is best-effort and bounded:

- Discovery runs only when `mcp_remote_multiplex_enable` is truthy and a remote provider is configured.
- When enabled, `list_descriptors` calls the remote provider and merges the returned descriptors into the local registry. If the remote call fails, the exception is silently swallowed and local registry descriptors remain available.
- There is no admission-allowlist gate. Enabling `mcp_remote_multiplex_enable` is sufficient to route to the remote provider.
- Unsupported discovered tools (not in the local `MCP_TOOL_DESCRIPTORS` supported set) are filtered out by `_filter_supported`.
- Route reason codes are deterministic:
  - `remote_disabled` — `mcp_remote_multiplex_enable` is falsy
  - `remote_unavailable` — flag enabled but no remote provider is injected
  - `remote_provider_error` — remote execution failed; fell back to local registry
  - `remote_descriptor_list_error` — remote descriptor fetch failed during execution resolution
  - `ok` — routed successfully

## MCP integration boundary

This contract explicitly bounds current tool execution behavior and reserves future expansion space:

- **Currently implemented**: local registry-backed ToolProvider default path, plus optional remote multiplex seam with best-effort descriptor merging (no admission gate).
- **Fallback behavior**: when remote multiplex is enabled but no remote adapter is present or the adapter errors, route falls back to local registry with deterministic reason codes (`remote_unavailable`, `remote_provider_error`).
- **Not currently implemented**: descriptor versioning/evolution policies across remote providers.
- **Current implementation boundary**: execution semantics still run through the existing executor contract and policy checks.
- **Planned**: The repo still tracks broader LangGraph and remote MCP integration work in the v5.6 forward line (see `docs/tracks/TRACK_AGENTOPS_A2A_MCP.md`).
- **Scope boundary**: This contract describes enacted descriptor-registry, ToolProvider boundary, validation, and executor behavior only.
- **Descriptor stability**: Adding new tools via the YAML registry does not require changes to this contract; only changes to the descriptor format, validation rules, or execution semantics should trigger contract updates.

## Validation and compliance checklist

When adding or modifying tools, ensure:

- [ ] Tool id is listed in `docs/settings/tools/registry.yaml`.
- [ ] Corresponding YAML descriptor file exists and passes the loader schema validation.
- [ ] `id`, `status`, `protocol`, `server`, and `description` fields are present and non-empty.
- [ ] `allowed_args` accurately reflects the accepted argument names and JSON Schema types.
- [ ] `mock_result` is defined (either as the expected mock payload or absent to default to `{"status": "ok"}`).
- [ ] Descriptor id matches the registry entry id.
- [ ] If the tool has required arguments, they are documented in the descriptor schema's `required` array.
- [ ] Integration tests cover the tool's happy path and at least one error case (e.g., missing required arg).
- [ ] If the tool behavior changes, this contract is updated to reflect the new semantics.
