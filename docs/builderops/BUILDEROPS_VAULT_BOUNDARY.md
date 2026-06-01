State: Controlled BuilderOps Vault API/tool boundary implemented for #1503. Promotion gateway mechanics are documented separately in `docs/builderops/BUILDEROPS_PROMOTION_GATEWAY.md`; generated projection mechanics are documented separately in `docs/builderops/BUILDEROPS_VAULT_PROJECTIONS.md`; this API/tool boundary still does not execute promotion gateway or projection-generation operations. No migrations, rich UI, public remote deployment, or product/runtime authority changes are implemented here.
Doc role: BuilderOps API and tool boundary reference
Authority: Documents the #1503 controlled boundary over the BuilderOps store. Store mechanics remain owned by `docs/builderops/BUILDEROPS_VAULT_STORE.md`; object semantics remain owned by `docs/builderops/BUILDEROPS_VAULT_OBJECT_MODEL.md`; authority boundaries remain owned by ADR-0010.
Owner: BuilderOps governance
Temporal class: operational
Review cadence: event-driven
Source of truth: app/builderops/boundary.py, app/api/routes/builderops.py, app/planner/tools.py, docs/settings/tools/mcp.builderops.*.yaml
Last reviewed: 2026-06-01
Last verified against: issue #1503

# BuilderOps Vault Boundary

## Scope

#1503 exposes a controlled local boundary over BuilderOps Vault records for agent use.

The HTTP API is mounted under `/api/builderops/*`:

- `GET /api/builderops/health`
- `GET /api/builderops/records?type=<object_type>`
- `GET /api/builderops/records/{record_id}`
- `POST /api/builderops/worklogs`
- `POST /api/builderops/learning-signals`
- `POST /api/builderops/promotion-intents`
- `POST /api/builderops/receipts`

The MCP-style tool boundary exposes these descriptor IDs:

- `mcp.builderops.list_records`
- `mcp.builderops.read_record`
- `mcp.builderops.create_worklog`
- `mcp.builderops.create_learning_signal`
- `mcp.builderops.create_promotion_intent`
- `mcp.builderops.append_receipt`

Both routes use the same `BuilderOpsBoundary` facade and delegate persistence/validation to the
BuilderOps store. They preserve actor identity, idempotency keys, source refs, and receipt fields
instead of bypassing the store layer.

## Agent Safety

The following operations are autonomous-agent-safe when source refs and actor identity are truthful:

- health checks
- list/read BuilderOps records
- create `AgentWorklog`
- create `LearningSignal`
- create staged `PromotionIntent`
- append `BuilderOpsReceipt` for a BuilderOps operation the agent performed

The following operations require human/governance review and are not implemented by this API/tool
boundary:

- execute a `PromotionIntent`
- generate or publish repo projection files
- mutate repo authority surfaces
- mutate GitHub authority surfaces
- mutate product/runtime truth
- publish a generated projection as truth

Creating a `PromotionIntent` is not promotion execution. Explicit promotion proposal and receipt
work is handled by the separate promotion gateway, not by autonomous MCP/API calls.

## Tool Execution

Real `mcp.builderops.*` tool execution is disabled unless `mcp_builderops_enable` is true. When real
execution is enabled, `allowed_mcp_tools` should name the exact BuilderOps tool IDs the agent may
call. If `builderops_db_path` is set in tool settings, the tool boundary uses that database;
otherwise normal BuilderOps path resolution applies.

Disabled BuilderOps tools return deterministic mock payloads through the existing MCP tool provider,
matching the repo's tool-policy posture.

## Authority Boundary

This boundary is BuilderOps operational infrastructure. It does not replace GitHub Issues as the
current executable task-contract surface, does not bypass PR review, and does not make BuilderOps
records into repo/product/runtime truth.

Promotion across authority classes remains explicit and is handled by the separate promotion gateway
plus the normal target authority gate.
