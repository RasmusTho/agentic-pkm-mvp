"""Architecture guards for the Focus and Conversation Port boundary."""

from __future__ import annotations

import ast
from pathlib import Path

from app.builderops.devui_overview import compose_overview_view


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_model_inquiry_adapter_reuses_existing_workflow() -> None:
    service = (REPO_ROOT / "app/builderops/control_plane/service.py").read_text()
    facade = (REPO_ROOT / "app/builderops/model_inquiry_workflow.py").read_text()
    destination = (REPO_ROOT / "app/builderops/model_inquiry_operation.py").read_text()
    assert "inquiry_workflow = SanctionedModelInquiryWorkflow()" in service
    assert "inquiry_workflow.start(approved)" in service
    assert 'WORKFLOW_REF = ".codex/skills/start-model-inquiry/SKILL.md"' in (REPO_ROOT / "app/builderops/devui_model_inquiry_command.py").read_text()
    tree = ast.parse(destination)
    runners = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "ModelInquiryRunner"]
    assert len(runners) == 1 and ast.unparse(runners[0].args[0]) == "self.service"
    starts = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "start"]
    assert len(starts) == 1 and any(keyword.arg == "inquiry_id" and ast.unparse(keyword.value) == "inquiry_id" for keyword in starts[0].keywords)
    assert "subprocess.run" in facade and "ModelInquiryRunner" not in facade
    assert "--approved-operation-stdin" in destination and "enter_command_invocation" in destination


def test_start_model_inquiry_has_no_forbidden_effect() -> None:
    paths = ("devui_model_inquiry_command.py", "model_inquiry_workflow.py", "model_inquiry_operation.py")
    forbidden = {"app.cli", "app.dispatcher", "app.builderops.ckm", "app.builderops.delivery_orchestration", "openai", "anthropic", "sqlite3", "requests"}
    for name in paths:
        tree = ast.parse((REPO_ROOT / "app/builderops" / name).read_text())
        imports = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        imports |= {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
        assert not any(module == denied or module.startswith(denied + ".") for module in imports for denied in forbidden)
        strings = [node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)]
        assert not any(value in {"git", "gh", "codex", "claude"} for value in strings)
        assert not {"create_task", "transition_task", "promote", "execute_command", "create_issue", "create_pull_request"} & {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}


def test_conversation_port_adds_no_authority_or_store() -> None:
    path = REPO_ROOT / "app" / "builderops" / "devui_conversation_port.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    forbidden_imports = {
        "httpx",
        "requests",
        "sqlite3",
        "subprocess",
        "app.dispatcher",
        "app.builderops.store",
    }

    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    assert not any(
        name == forbidden or name.startswith(f"{forbidden}.")
        for name in imported
        for forbidden in forbidden_imports
    )
    assert not {
        "discover_sessions",
        "list_sessions",
        "save_transcript",
        "create_task",
        "execute_command",
    } & {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}


def test_overview_source_authority_contract_is_explicit() -> None:
    """The production Overview composer withdraws zones without a source owner."""

    result = compose_overview_view(
        composition={
            "contract_version": "devui.composition.v1",
            "authority": "projection_only",
            "captured_at": "2026-08-11T00:00:00Z",
            "providers": {
                "work": {
                    "provider": "builderops_cockpit",
                    "status": "available",
                    "authority": "read_time_join",
                    "captured_at": "2026-08-11T00:00:00Z",
                    "snapshot": {"watermark": "work:0"},
                    "completeness": {"claim": {"kind": "counted"}},
                }
            },
        }
    )

    assert result["needs_you"] == []
    assert result["ready_to_try"] == []
    assert {
        (withdrawal["zone"], withdrawal["reason"])
        for withdrawal in result["limitations"]
    } == {
        ("needs_you", "the producer supplied no actionable classification evidence"),
        ("ready_to_try", "the producer supplied no actionable classification evidence"),
    }
