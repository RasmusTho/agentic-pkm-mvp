"""BCP-04 AC3/AC4: production clients are API-only and secret-safe.

AC3 proves the production client CLI/config exposes no direct database path or
SSH-wrapped store mode while the explicit SQLite migration adapter keeps its
read-only source path. AC4 proves the repo-local automation wrapper routes
authority-bearing operations through the authenticated API client and documents
credential setup without inlining secrets.

The checks are structural (argparse tree, Python AST, comment-stripped shell)
rather than naive substring scans, so docstrings and error messages that
*describe the absence* of a direct-store mode are not mistaken for one.
"""

from __future__ import annotations

import argparse
import ast
import re
from pathlib import Path

from app.builderops.control_plane import client, client_cli, selection

REPO_ROOT = Path(__file__).resolve().parents[2]

# Modules and drivers that must never be used by the API-only client surface.
_FORBIDDEN_IMPORT_MODULES = ("sqlite3", "psycopg", "subprocess", "paramiko")
_STORE_CONSTRUCTORS = frozenset({"SqliteBuilderOpsStore", "PostgresBuilderOpsStore"})

# Real-credential-value shapes that must never be inlined in a wrapper or doc.
# (Environment-variable *names* like BUILDEROPS_API_TOKEN are allowed.)
_SECRET_VALUE_PATTERNS = (
    re.compile(r"ghp_[A-Za-z0-9]{10,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{10,}"),
    re.compile(r"\bsk-[A-Za-z0-9]{10,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]{12,}"),
    re.compile(r"bcp-(?:client|db|github|model|recovery)-[A-Za-z0-9._~+/=-]{6,}"),
)


def _iter_actions(parser: argparse.ArgumentParser):
    yield from parser._actions
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for sub in action.choices.values():
                yield from _iter_actions(sub)


def _module_tree(module) -> ast.AST:
    return ast.parse(Path(module.__file__).read_text(encoding="utf-8"))


def _imported_modules(tree: ast.AST) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module.split(".")[0])
    return modules


def _constructs_store(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if name in _STORE_CONSTRUCTORS:
                return True
    return False


def _non_comment_shell_lines(text: str) -> str:
    """Drop full-line ``#`` comments so a header describing absence is ignored."""
    kept = [line for line in text.splitlines() if not line.lstrip().startswith("#")]
    return "\n".join(kept)


def test_production_clients_expose_no_direct_store_mode() -> None:
    parser = client_cli.build_parser()

    # No CLI option anywhere in the parser tree exposes a direct DB path.
    for action in _iter_actions(parser):
        assert "--db-path" not in action.option_strings, "client CLI must not expose --db-path"
        if action.dest:
            assert action.dest != "db_path", "client CLI must not expose a db_path option"

    # The API-only client surface imports no DB driver / ssh / subprocess module
    # and constructs no store (structural, so prose about absence is fine).
    for module in (client, client_cli):
        tree = _module_tree(module)
        forbidden = _imported_modules(tree).intersection(_FORBIDDEN_IMPORT_MODULES)
        assert not forbidden, f"{module.__name__} imports a direct-store/ssh module: {forbidden}"
        assert not _constructs_store(tree), f"{module.__name__} constructs a store directly"

    # Migration tooling retains an explicit, read-only source path.
    assert hasattr(selection, "ExplicitSqliteAdapter")
    selection_source = Path(selection.__file__).read_text(encoding="utf-8")
    assert "read_only=True" in selection_source, (
        "the SQLite migration/test adapter must open its source read-only"
    )


def test_skills_and_automations_route_through_authenticated_api() -> None:
    wrapper = REPO_ROOT / "scripts" / "builderops_api_client.sh"
    assert wrapper.exists(), "the API-only automation wrapper must exist"
    text = wrapper.read_text(encoding="utf-8")
    code = _non_comment_shell_lines(text)

    # Routes through the authenticated API client module, not a local store CLI.
    assert re.search(r"-m\s+app\.builderops\.control_plane\b", code), (
        "wrapper must exec the API-only control-plane client module"
    )

    # Executable shell (comments stripped) exposes no direct-store/SSH mode.
    for marker in ("--db-path", "db_path", "BUILDEROPS_DB_PATH", "sqlite3"):
        assert marker.lower() not in code.lower(), f"automation wrapper uses '{marker}'"
    assert re.search(r"\bssh\b\s+\S+@", code) is None, "wrapper must not SSH into a host store"

    # Documents host-owned credential setup by env var, without inlining secrets.
    assert "BUILDEROPS_API_URL" in text
    assert "BUILDEROPS_API_TOKEN_FILE" in text or "BUILDEROPS_API_TOKEN" in text
    _assert_no_inlined_secret(text, wrapper)

    # The owner doc documents secret-safe credential setup for skills/automations.
    doc = REPO_ROOT / "docs" / "BUILDEROPS_CONTROL_PLANE" / "API_ONLY_CLIENT_CUTOVER.md"
    doc_text = doc.read_text(encoding="utf-8")
    assert "BUILDEROPS_API_URL" in doc_text
    assert "BUILDEROPS_API_TOKEN_FILE" in doc_text or "BUILDEROPS_API_TOKEN" in doc_text
    assert "python -m app.builderops.control_plane" in doc_text
    _assert_no_inlined_secret(doc_text, doc)


def _assert_no_inlined_secret(text: str, source: Path) -> None:
    for pattern in _SECRET_VALUE_PATTERNS:
        match = pattern.search(text)
        assert match is None, (
            f"{source} appears to inline a credential value matching {pattern.pattern!r}"
        )
