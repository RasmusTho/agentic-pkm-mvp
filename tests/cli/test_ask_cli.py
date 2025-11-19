from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from app.cli import cli
from app.planner.schema import Plan, PlanMetadata, PlanStep
from app.stores.plan_store import reset_plan_store


def _run_cli(args: list[str], env: dict[str, str] | None = None):
    runner = CliRunner()
    return runner.invoke(cli, args, env=env)


@pytest.fixture(autouse=True)
def clear_mcp_vault_env(monkeypatch):
    monkeypatch.delenv("MCP_VAULT_ENABLE", raising=False)


def test_ask_cli_dry_run(tmp_path: Path):
    reset_plan_store()
    result = _run_cli(["ask", "Why is the sky blue?", "--vault-root", str(tmp_path)])
    assert result.exit_code == 0
    output = result.output
    assert "Why is the sky blue?" in output
    assert "vault writes disabled" in output.lower()
    assert not any(tmp_path.rglob("*.md"))


def test_ask_cli_real_vault_write(tmp_path: Path):
    reset_plan_store()
    result = _run_cli(["ask", "What is PKM?", "--vault-root", str(tmp_path), "--enable-mcp-vault"])
    assert result.exit_code == 0
    files = list(tmp_path.rglob("*.md"))
    assert len(files) == 1
    note_path = files[0]
    text = note_path.read_text(encoding="utf-8")
    assert "title" in text.lower()
    assert text.strip().endswith("Summaries from ingest-agent")
    assert str(note_path) in result.output


def test_ask_cli_reports_tool_errors(monkeypatch):
    reset_plan_store()

    class StubPlanner:
        def plan(self, inp):
            return Plan(
                id="plan-cli-stub",
                meta=PlanMetadata(goal=inp.goal, source_object_uuid=inp.object_uuid, created_by="stub"),
                steps=[
                    PlanStep(
                        id="s1",
                        kind="tool_call",
                        description="Broken tool",
                        tool="mcp.vault.append_note",
                        tool_args={"title": "missing body"},
                    )
                ],
                context={"flow_ids": ["qa"]},
                tags=["qa"],
            )

    monkeypatch.setattr("app.planner.events.get_planner", lambda: StubPlanner())
    result = _run_cli(["ask", "Cause an error"])
    assert result.exit_code == 1
    assert "invalid_tool_args" in result.output.lower()
