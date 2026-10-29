import ast
from pathlib import Path


def test_dormant_archival_handlers_are_not_installed_on_external_surfaces() -> None:
    """#5352 owns the sole runtime installation; transports cannot add a bypass."""
    roots = (Path("app/api"), Path("app/mcp"), Path("app/companion"), Path("app/gui"))
    sources = [path for root in roots if root.exists() for path in root.rglob("*.py")]
    forbidden = {"run_single_record_archive_operation", "run_single_record_restore_operation"}
    for path in sources:
        if path == Path("app/api/operation_runtime.py"):
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom):
                assert node.module != "app.operations.archival_operations", path
                if node.module == "app.heimdal.local_archive":
                    assert not forbidden.intersection(alias.name for alias in node.names), path
            elif isinstance(node, ast.Import):
                assert all(alias.name != "app.operations.archival_operations" for alias in node.names), path
