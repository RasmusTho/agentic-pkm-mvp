from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ALLOWED_COMPAT_MODULES = {
    Path("app/settings/health_settings.py"),
    Path("app/settings/locations.py"),
    Path("app/settings/migration.py"),
    Path("app/vault/manager.py"),
    Path("app/watcher/settings_delta.py"),
}
LEGACY_SEGMENTS = ("@Settings", "_system/settings", "_system/Settings")
SETTINGS_ARTIFACT_NAMES = {
    "agents.md",
    "global.md",
    "health.md",
    "models.md",
    "providers.md",
    "routing.md",
    "standards.md",
    "system-settings.md",
    "watchers.md",
}


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
        if right is not None:
            return right
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
            path_value = Path(normalized.removeprefix("vault://"))
            canonical_shape = (
                path_value.parts[-2:] == ("settings", path_value.name)
                and (
                    len(path_value.parts) == 2
                    or path_value.parts[-3:] == ("vault", "settings", path_value.name)
                )
            )
            if (
                path_value.name in SETTINGS_ARTIFACT_NAMES
                and len(path_value.parts) > 1
                and not canonical_shape
            ):
                violations.add(
                    f"{relative}:{node.lineno}: settings artifact outside canonical root {value!r}"
                )
    for path in sorted((ROOT / "scripts").rglob("*.sh")):
        relative = path.relative_to(ROOT)
        normalized = path.read_text(encoding="utf-8").replace("\\", "/")
        for segment in LEGACY_SEGMENTS:
            if segment in normalized:
                violations.add(f"{relative}: shell contains retired settings path {segment!r}")
    operational_paths = {
        *(ROOT / ".github").rglob("*.yml"),
        *(ROOT / ".github").rglob("*.yaml"),
        *(ROOT / "config").rglob("*.yml"),
        *(ROOT / "config").rglob("*.yaml"),
        *(ROOT / "scripts").rglob("*.yml"),
        *(ROOT / "scripts").rglob("*.yaml"),
        *ROOT.glob("*compose*.yml"),
        *ROOT.glob("*compose*.yaml"),
    }
    for path in sorted(operational_paths):
        relative = path.relative_to(ROOT)
        normalized = path.read_text(encoding="utf-8").replace("\\", "/")
        for segment in LEGACY_SEGMENTS:
            if segment in normalized:
                violations.add(f"{relative}: operational config contains retired settings path {segment!r}")
    assert not violations, "new settings locations are forbidden outside the compat seam:\n" + "\n".join(sorted(violations))
