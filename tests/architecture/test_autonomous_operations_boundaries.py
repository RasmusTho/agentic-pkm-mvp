import ast
from pathlib import Path


def test_operation_contracts_are_provider_free_and_non_writing() -> None:
    source = Path("app/operations/contracts.py").read_text()
    tree = ast.parse(source)
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
        elif isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
    assert all(
        not module.startswith(("app.api", "app.adapters", "app.stores", "app.governance"))
        for module in imports
    )
    assert ".write_" not in source and ".execute(" not in source


def test_effect_surfaces_share_production_operation_runtime() -> None:
    from app.api.app import app
    from app.api.routes.operations import execute
    routes = [route for route in app.routes if getattr(route, "path", None) == "/api/operations"]
    assert len(routes) == 1 and routes[0].endpoint is execute
    source = Path("app/api/routes/operations.py").read_text()
    assert "build_production_operation_runtime" in source
    assert "runtime.invoke(operation)" in source
    assert not any(term in source for term in ("OperationExecutionKernel(", "write_note", "append_note", "build_write_operation_handlers"))
    # Broader consumers are intentionally still uninstalled. The later slices
    # must use this shared boundary; v1 keeps its finite existing schema.
    assert not any("mcp/v2" in getattr(route, "path", "") for route in app.routes)
    v1 = Path("app/mcp").exists()
    assert v1
