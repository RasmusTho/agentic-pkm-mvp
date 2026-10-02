from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from app.orchestrator.runtime import Orchestrator
from app.planner.provider import build_vault_append_steps
from app.planner.schema import Plan, PlanMetadata

pytestmark = pytest.mark.not_pg


def _simple_plan(*, step_args: dict[str, object]) -> Plan:
    return Plan(
        id="plan-vault",
        meta=PlanMetadata(goal="Store note", source_object_uuid="obj-vault", created_by="tester"),
        steps=build_vault_append_steps(
            step_id="step-1",
            description="Write vault note",
            tool_args=step_args,
            reason="Exercise the guarded append path",
        ),
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
    assert len(results) == 3
    assert results[1]["status"] == "ok"
    note_path = Path(results[1]["result"]["result"]["note_path"])
    assert note_path.is_file()
    assert note_path.parent == tmp_path / "_mcp"
    frontmatter = _read_frontmatter(note_path)
    assert frontmatter["title"] == "Ask Summary"
    assert frontmatter["tags"] == ["ask"]


def test_executor_mcp_append_uses_guarded_default_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("VAULT_SOURCES_DIR_REL", "_mcp")
    orchestrator = Orchestrator(
        tool_settings={"mcp_vault_enable": True, "vault_root": tmp_path}
    )

    results = orchestrator.run_plan(
        _simple_plan(step_args={"title": "Reserved", "body": "must not land in Sources"})
    )

    assert results[1]["status"] == "error"
    assert results[1]["error_type"] == "mcp_tool_error"
    assert "inside the selected vault Sources zone" in results[1]["error"]
    assert not (tmp_path / "_mcp").exists()
    assert not any(tmp_path.rglob(".mcp-append-stage-*.md"))


def test_tool_call_missing_body_surfaces_error(tmp_path: Path) -> None:
    orchestrator = Orchestrator(tool_settings={"mcp_vault_enable": True, "vault_root": tmp_path})
    plan = _simple_plan(step_args={"title": "Broken"})
    results = orchestrator.run_plan(plan)
    assert results[1]["status"] == "error"
    assert results[1]["error_type"] == "invalid_tool_args"
    assert "missing required argument" in results[1]["error"]
    assert not any(tmp_path.rglob("*.md"))


def test_tool_call_disabled_flag_string(tmp_path: Path) -> None:
    orchestrator = Orchestrator(tool_settings={"mcp_vault_enable": "0", "vault_root": tmp_path})
    plan = _simple_plan(step_args={"title": "Ask Summary", "body": "Hello world"})
    results = orchestrator.run_plan(plan)
    assert results[1]["status"] == "ok"
    assert not any(tmp_path.rglob("*.md"))

def test_tool_call_accepts_content_alias(tmp_path: Path) -> None:
    orchestrator = Orchestrator(tool_settings={"mcp_vault_enable": True, "vault_root": tmp_path})
    plan = _simple_plan(step_args={"title": "Ask Summary", "content": "Hello world"})
    results = orchestrator.run_plan(plan)
    assert len(results) == 3
    assert results[1]["status"] == "ok"
    note_path = Path(results[1]["result"]["result"]["note_path"])
    assert note_path.is_file()
    text = note_path.read_text(encoding="utf-8")
    assert "Hello world" in text
