from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from app.orchestrator.runtime import Orchestrator
from app.planner.schema import Plan, PlanMetadata, PlanStep

pytestmark = pytest.mark.not_pg


def _simple_plan(*, step_args: dict[str, object]) -> Plan:
    return Plan(
        id="plan-vault",
        meta=PlanMetadata(goal="Store note", source_object_uuid="obj-vault", created_by="tester"),
        steps=[
            PlanStep(
                id="step-1",
                kind="tool_call",
                description="Write vault note",
                tool="mcp.vault.append_note",
                tool_args=step_args,
            )
        ],
    )


def _read_frontmatter(path: Path) -> dict[str, object]:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    remainder = text[4:]
    divider = remainder.index("\n---\n\n")
    frontmatter_block = remainder[:divider]
    return yaml.safe_load(frontmatter_block) or {}


def test_tool_call_creates_vault_file(tmp_path: Path) -> None:
    orchestrator = Orchestrator(tool_settings={"mcp_vault_enable": True, "vault_root": tmp_path})
    plan = _simple_plan(step_args={"title": "Ask Summary", "body": "Hello world", "tags": ["ask"]})
    results = orchestrator.run_plan(plan)
    assert len(results) == 1
    assert results[0]["status"] == "ok"
    note_path = Path(results[0]["result"]["result"]["note_path"])
    assert note_path.is_file()
    assert note_path.parent == tmp_path / "_mcp"
    frontmatter = _read_frontmatter(note_path)
    assert frontmatter["title"] == "Ask Summary"
    assert frontmatter["tags"] == ["ask"]


def test_tool_call_missing_body_surfaces_error(tmp_path: Path) -> None:
    orchestrator = Orchestrator(tool_settings={"mcp_vault_enable": True, "vault_root": tmp_path})
    plan = _simple_plan(step_args={"title": "Broken"})
    results = orchestrator.run_plan(plan)
    assert results[0]["status"] == "error"
    assert results[0]["error_type"] == "invalid_tool_args"
    assert "missing required argument" in results[0]["error"]
    assert not any(tmp_path.rglob("*.md"))
