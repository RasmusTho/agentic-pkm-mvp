---
name: Promotion CLI Agent Optional Vault Resolution
description: Promotion, CLI, agent, MCP, and knowledge consumers make vault resolution lazy or explicit instead of resolving at import time or falling back to ./vault.
task_id: VAULT_OPTIONAL_RUNTIME-05C
source_anchor: docs/VAULT_OPTIONAL_RUNTIME/README.md :: Follow-up eager resolver migration
parent_capability: Vault Optional at Runtime
prerequisites: [VAULT_OPTIONAL_RUNTIME-01]
depends_on: [API_ENDPOINT_OPTIONAL_VAULT_BOUNDARIES.md, BACKGROUND_OPTIONAL_VAULT_IDLE.md]
can_parallelize_with: []
---

# Promotion CLI Agent Optional Vault Resolution

## Purpose
The remaining non-request consumers must stop treating the legacy eager resolver as an
ambient global. Promotion must not resolve a vault at import time, CLI commands must make
vault requirements explicit per command, and agent/helper/MCP/knowledge reads or writes must
return optional/empty results or explicit no-vault errors rather than using CWD-relative
`./vault`.

This is Slice C of #2311. It is intentionally later than the API slice because it spans
import-time code, CLI policy, agent-memory helper behavior, MCP write helpers, and knowledge
adapter fallback behavior.

## What This Task Does
- Removes import-time vault resolution from `app/promotion/queue.py` by making vault access
  lazy and optional at the call site.
- Audits and updates CLI resolver calls in `app/cli/__init__.py`:
  - commands that can operate without a vault use optional/no-vault behavior;
  - commands that truly require a vault fail with an explicit operator-facing error or
    explicit flag requirement;
  - no command silently falls back to `./vault` unless the command contract deliberately
    names a legacy/default-vault mode.
- Migrates agent and helper consumers that still use eager/no-argument resolution:
  - `app/agents/panel_agent/cognition.py`
  - `app/agent_memory/recall_retrieval.py`
  - `app/panel/checkbox_projection.py`
- Migrates MCP and knowledge paths that can still synthesize `./vault` without an explicit
  selected/configured vault:
  - `app/orchestrator/executor.py::_run_vault_append`
  - `app/mcp/vault_tools.py::get_vault_root`
  - `app/mcp/vault_tools.py::append_note`
  - `app/knowledge/service.py::_resolve_fs_root`
  - `app/knowledge/service.py::resolve_knowledge_port`
- Preserves selected-vault behavior and write guards for rollback/write helpers.

## Concretely
```python
# Importing promotion queue no longer requires a vault or creates a ./vault assumption.
import app.promotion.queue

# CLI commands that require a vault fail explicitly.
result = runner.invoke(cli, ["some-vault-command"], env={"VAULT_ROOT": ""})
assert result.exit_code != 0
assert "select or pass a vault" in result.output.lower()

# Agent memory read helpers return no candidates when no vault is selected.
assert recall_retrieval.search("topic", vault_root=None) == []

# MCP/knowledge write helpers fail explicitly instead of creating ./vault artifacts.
with pytest.raises(VaultToolError, match="vault root"):
    append_note(title="T", body="B", vault_root=None, settings={})
```

## Why This Matters
Import-time and CLI fallbacks are harder to see than API failures. They can bind the wrong
vault before the runtime has selected one, or write rollback artifacts into `./vault`.
Making these consumers lazy or explicit completes the migration without overloading the API
slice.

## Acceptance Criteria
- [ ] `app/promotion/queue.py` imports without requiring or resolving a vault. Verify:
      `tests/promotion/test_queue_lazy_vault.py::test_queue_import_does_not_require_vault`
- [ ] CLI commands either accept an explicit vault or fail clearly when they need one; none
      silently fall back to CWD-relative `./vault`. Verify:
      `tests/cli/test_no_vault_resolution.py::test_cli_commands_do_not_fallback_to_cwd_vault`
- [ ] Agent/panel/agent-memory helpers return optional/empty results or explicit no-vault
      errors without fallback. Verify:
      `tests/agents/test_panel_agent_no_vault.py::test_panel_agent_no_vault_skips_without_fallback`
      and `tests/agent_memory/test_recall_retrieval_no_vault.py::test_recall_retrieval_no_vault_returns_empty`
- [ ] MCP vault append and knowledge adapter resolution require an explicit selected or
      configured vault and do not synthesize `Path("vault")`. Verify:
      `tests/orchestrator/test_executor_no_vault.py::test_mcp_vault_append_requires_explicit_vault_root`,
      `tests/mcp/test_vault_tools_no_vault.py::test_append_note_requires_explicit_vault_without_default`,
      and `tests/knowledge/test_service_no_vault.py::test_resolve_knowledge_port_does_not_fallback_to_cwd_vault`
- [ ] A grep/AST guard covers the promotion/CLI/agent/MCP/knowledge eager resolver sites. Verify:
      `tests/api/test_no_silent_cwd_vault_fallback.py::test_promotion_cli_agent_resolvers_do_not_fallback_to_cwd_vault`

## How to Verify (Pre-Merge)
```bash
pytest -q \
  tests/promotion/test_queue_lazy_vault.py \
  tests/cli/test_no_vault_resolution.py \
  tests/agents/test_panel_agent_no_vault.py \
  tests/agent_memory/test_recall_retrieval_no_vault.py \
  tests/orchestrator/test_executor_no_vault.py \
  tests/mcp/test_vault_tools_no_vault.py \
  tests/knowledge/test_service_no_vault.py \
  tests/api/test_no_silent_cwd_vault_fallback.py
ruff check app tests
RUN_INTEGRATED_RUNTIME_UAT=1 pytest -q tests/uat/
```

The IR-v1 UAT is required if the implementation changes active-vault resolution or hot-path
runtime behavior.

## Out of Scope
- API picker/empty responses (Slice A).
- Background worker idle behavior (Slice B).
- Legacy `/app/vault` compose/runtime-env mount cleanup (Slice D).
- Reopening the owner decision for nested-vault boundaries or vault initialization.

## Related Docs
- Parent: `docs/VAULT_OPTIONAL_RUNTIME/README.md`
- `docs/VAULT_OPTIONAL_RUNTIME/RESOLVE_NO_VAULT_STATE.md`
- #2311 (parent migration hub)

## Related GitHub Issues
One bounded child issue to be filed from this task after the spec lands on main. It should
remain blocked/backlog until Slices A and B are either delivered or intentionally sequenced
around it.
