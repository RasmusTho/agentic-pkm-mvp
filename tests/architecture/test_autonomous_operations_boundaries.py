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



def test_batch_effect_surfaces_use_shared_runtime_and_existing_coordinator():
    from app.api.app import app
    from app.api.routes import operations
    expected = {
        ("/api/operations/batches/preview", "POST"): operations.batch_preview,
        ("/api/operations/batches/{batch_id}", "GET"): operations.batch_inspect,
        ("/api/operations/batches/{batch_id}/execute", "POST"): operations.batch_execute,
        ("/api/operations/batches/{batch_id}/cancel", "POST"): operations.batch_cancel,
    }
    for (path, method), endpoint in expected.items():
        routes = [route for route in app.routes if getattr(route, "path", None) == path
                  and method in getattr(route, "methods", ())]
        assert len(routes) == 1 and routes[0].endpoint is endpoint
    route_source = Path("app/api/routes/operations.py").read_text()
    assert "build_production_batch_runtime" in route_source
    assert not any(name in route_source for name in ("BatchOperationCoordinator(", "OperationExecutionKernel(",
        "write_note_from_absolute", "KnowledgePlacementOwner(", "JsonReceiptStore("))
    composition = ast.parse(Path("app/api/batch_operation_runtime.py").read_text())
    imports = {node.module for node in ast.walk(composition) if isinstance(node, ast.ImportFrom)}
    assert "app.operations.batch_operations" in imports and "app.api.operation_runtime" in imports
    assert not any(module and module.startswith(("app.mcp", "companion")) for module in imports)
    # Transport adapters cannot construct a second coordinator/native owner.
    for root in (Path("app/mcp"), Path("companion-ui/companion-app")):
        for path in root.rglob("*.py"):
            source = path.read_text()
            assert not any(name in source for name in ("BatchOperationCoordinator(", "ProductionBatchRuntime("))


def test_companion_operations_use_only_public_operations_client():
    root = Path("companion-ui/companion-app/companion_ui/workspace")
    for name in ("operations_workspace.py", "operations_client.py"):
        source = (root / name).read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("app")
            if isinstance(node, ast.Import):
                assert not any(alias.name.startswith("app") for alias in node.names)
        assert not any(token in source for token in ("write_note", "StorePort", "BatchOperationCoordinator(", "OperationExecutionKernel("))
    workspace = (root / "operations_workspace.py").read_text()
    assert "fetch(" not in workspace
    assert "window.operationsClient" in workspace
    client = (root / "operations_client.py").read_text()
    assert "'/api/operations'" in client
    assert "executeBatch" in client and "expected_digest:digest" in client
    assert "localStorage" not in workspace and "sessionStorage" not in workspace
    from companion_ui.workspace.serve_dev_page import make_handler
    handler = make_handler(client=object(), api_base_url="http://127.0.0.1:18001")
    for path in ("/api/operations/batches/x/unknown", "/api/operations/receipts/x/extra", "/api/operations/effects"):
        assert not handler.route_allowed("GET", path)
        assert not handler.route_allowed("POST", path)
