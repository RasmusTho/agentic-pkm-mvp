"""BCP-04 AC7: only control-plane data-layer and migration/test adapters may
reach a store.

The authenticated client transport (``client.py``), its CLI, delivery-manifest
routing, the service, auth, and models must never import a raw database driver
(``sqlite3``/``psycopg``) or construct a ``SqliteBuilderOpsStore`` /
``PostgresBuilderOpsStore``. That is what makes the API boundary real: a client
cannot silently reopen a worktree-local database or reach PostgreSQL directly.

Only two control-plane modules are permitted store access:

* ``store.py`` — the PostgreSQL data layer.
* ``selection.py`` — the fail-closed production selector plus the explicit
  SQLite migration/test adapter seam.

A new control-plane module that imports a database driver or constructs a store
outside this allowlist fails this test. This inventory is the completeness proof
for BCP-04's no-local-authority-fallback guarantee; the legacy
``app.dispatcher`` / ``app.builderops`` SQLite writers are a separate concern
owned by the BCP-06 legacy-writer freeze, not by this control-plane boundary.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTROL_PLANE = REPO_ROOT / "app" / "builderops" / "control_plane"

# Relative paths (from REPO_ROOT) permitted to access a store.
DATA_LAYER_AND_MIGRATION_ALLOWLIST: frozenset[str] = frozenset(
    {
        "app/builderops/control_plane/store.py",  # PostgreSQL data layer
        "app/builderops/control_plane/selection.py",  # selector + migration/test adapter
    }
)

# Raw database drivers that only the data layer / migration adapter may import.
_DRIVER_MODULES = ("sqlite3", "psycopg")
# Store classes whose *construction* is store access anywhere it appears.
_STORE_CONSTRUCTORS = frozenset({"SqliteBuilderOpsStore", "PostgresBuilderOpsStore"})

# The authority-bearing client surface must be provably store-free.
_CLIENT_SURFACE = frozenset(
    {
        "app/builderops/control_plane/client.py",
        "app/builderops/control_plane/client_cli.py",
        "app/builderops/control_plane/routing.py",
        "app/builderops/control_plane/__main__.py",
    }
)


def _imports_driver(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in _DRIVER_MODULES or alias.name.startswith(
                    tuple(f"{module}." for module in _DRIVER_MODULES)
                ):
                    return True
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module in _DRIVER_MODULES or module.startswith(
                tuple(f"{driver}." for driver in _DRIVER_MODULES)
            ):
                return True
    return False


def _constructs_store(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = None
        if isinstance(func, ast.Name):
            name = func.id
        elif isinstance(func, ast.Attribute):
            name = func.attr
        if name in _STORE_CONSTRUCTORS:
            return True
    return False


def _accesses_store(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return _imports_driver(tree) or _constructs_store(tree)


def _control_plane_files() -> list[Path]:
    return sorted(CONTROL_PLANE.rglob("*.py"))


def test_only_control_plane_data_layer_and_migration_adapters_access_stores() -> None:
    assert CONTROL_PLANE.is_dir()
    violations: list[str] = []
    for path in _control_plane_files():
        rel = str(path.relative_to(REPO_ROOT))
        if rel in DATA_LAYER_AND_MIGRATION_ALLOWLIST:
            continue
        if _accesses_store(path):
            violations.append(rel)

    assert not violations, (
        "Control-plane modules accessing a store outside the data-layer/"
        "migration adapter allowlist (they must go through the authenticated "
        "API client instead):\n" + "\n".join(f"  {v}" for v in sorted(violations))
    )


def test_client_surface_is_store_free() -> None:
    """The client, its CLI, routing, and entry point never touch a store."""
    for rel in sorted(_CLIENT_SURFACE):
        path = REPO_ROOT / rel
        assert path.exists(), f"expected client-surface module missing: {rel}"
        assert not _accesses_store(path), (
            f"{rel} imports a database driver or constructs a store; the API-only "
            "client surface must reach authority exclusively over the API."
        )


def test_store_boundary_allowlist_is_accurate() -> None:
    """Every allowlisted module still exists and still accesses a store.

    A stale allowlist entry (deleted, or migrated off store access) would hide a
    real regression, so keep the allowlist minimal and truthful.
    """
    stale: list[str] = []
    for rel in DATA_LAYER_AND_MIGRATION_ALLOWLIST:
        path = REPO_ROOT / rel
        if not path.exists() or not _accesses_store(path):
            stale.append(rel)
    assert not stale, (
        "Stale store-boundary allowlist entries (remove or fix):\n"
        + "\n".join(f"  {s}" for s in sorted(stale))
    )
