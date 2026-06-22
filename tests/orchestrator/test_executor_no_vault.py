from __future__ import annotations

from pathlib import Path

import pytest

from app.orchestrator.runtime import Orchestrator
from app.planner.schema import Plan, PlanMetadata, PlanStep

pytestmark = pytest.mark.not_pg


def test_mcp_vault_append_requires_explicit_vault_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    for name in ("VAULT_ROOT", "VAULT_ROOT_DEV", "VAULT_ROOT_TEST", "MCP_VAULT_ROOT", "VAULT_DIR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "vault").mkdir()
    orchestrator = Orchestrator(tool_settings={"mcp_vault_enable": True})
    plan = Plan(
        id="plan-no-vault",
        meta=PlanMetadata(goal="Store note", source_object_uuid="obj-no-vault", created_by="tester"),
        steps=[
            PlanStep(
                id="step-1",
                kind="tool_call",
                description="Write vault note",
                tool="mcp.vault.append_note",
                tool_args={"title": "No Vault", "body": "Should not write"},
            )
        ],
    )

    results = orchestrator.run_plan(plan)

    assert results[0]["status"] == "error"
    assert results[0]["error_type"] == "mcp_tool_error"
    assert "vault root is required" in results[0]["error"].lower()
    assert not (tmp_path / "vault" / "_mcp").exists()
