from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ALLOWED_COMPAT_MODULES = {
    Path("app/settings/locations.py"),
    Path("app/settings/migration.py"),
}
LEGACY_SEGMENTS = ("@Settings", "_system/settings", "_system/Settings")


def _literal_path(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Path" and node.args:
        return _literal_path(node.args[0])
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        left = _literal_path(node.left)
        right = _literal_path(node.right)
        if left is not None and right is not None:
            return f"{left.rstrip('/')}/{right.lstrip('/')}"
    return None


def test_no_new_settings_paths() -> None:
    violations: set[str] = set()
    code_paths = [
        *(ROOT / "app").rglob("*.py"),
        *(ROOT / "scripts").rglob("*.py"),
    ]
    for path in sorted(code_paths):
        relative = path.relative_to(ROOT)
        if relative in ALLOWED_COMPAT_MODULES:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(relative))
        for node in ast.walk(tree):
            value = _literal_path(node)
            if value is None:
                continue
            normalized = value.replace("\\", "/")
            if any(segment in normalized for segment in LEGACY_SEGMENTS):
                violations.add(f"{relative}:{node.lineno}: {value!r}")
    assert not violations, "new settings locations are forbidden outside the compat seam:\n" + "\n".join(sorted(violations))
