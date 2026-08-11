"""Architecture guards for the Focus and Conversation Port boundary."""

from __future__ import annotations

import ast
from pathlib import Path

from app.builderops.devui_overview import compose_overview_view


REPO_ROOT = Path(__file__).resolve().parents[2]


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
