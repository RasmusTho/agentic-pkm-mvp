import ast
from pathlib import Path


def test_operation_contracts_are_provider_free_and_non_writing() -> None:
    source = Path("app/operations/contracts.py").read_text()
    tree = ast.parse(source)
    imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    assert all(not module.startswith(("app.api", "app.adapters", "app.stores", "app.governance")) for module in imports)
    assert ".write_" not in source and ".execute(" not in source
