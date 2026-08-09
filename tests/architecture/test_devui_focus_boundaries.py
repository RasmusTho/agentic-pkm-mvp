"""Architecture guards for the Focus and Conversation Port boundary."""

from __future__ import annotations

import ast
from pathlib import Path


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
