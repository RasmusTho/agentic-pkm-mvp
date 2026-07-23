"""BCP-04 AC7: only control-plane data-layer and migration/test adapters may
reach a store.

The authenticated client transport (``client.py``), its CLI, delivery-manifest
routing, the service, auth, and models must never import a raw database driver
(``sqlite3``/``psycopg``) or construct a ``SqliteBuilderOpsStore`` /
``PostgresBuilderOpsStore``. That is what makes the API boundary real: a client
cannot silently reopen a worktree-local database or reach PostgreSQL directly.

Only these control-plane modules are permitted store access:

* ``store.py`` — the PostgreSQL data layer.
* ``selection.py`` — the fail-closed production selector plus the explicit
  SQLite migration/test adapter seam.
* ``legacy_migration.py`` — BCP-03's deterministic, read-only legacy-authority
  import mechanism (merged after this slice via #3929); it hash-verifies each
  source before and after every read and performs no production cutover.

A new control-plane module that imports a database driver or constructs a store
outside this allowlist fails this test. This inventory is the completeness proof
for BCP-04's no-local-authority-fallback guarantee; the legacy
``app.dispatcher`` / ``app.builderops`` SQLite writers are a separate concern
owned by the BCP-06 legacy-writer freeze, not by this control-plane boundary.

A second, separate guard below widens the walk to the rest of ``app/builderops/``
(the pre-existing Vault record store, outside ``control_plane/``) against an
explicit, audited allowlist of its known legitimate store-access sites
(BCP-04 review finding H5). This closes the regression gap for *new* files
without requiring those pre-existing, still-legacy sites to migrate in this
slice — their migration is BCP-03/06 territory.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTROL_PLANE = REPO_ROOT / "app" / "builderops" / "control_plane"
BUILDEROPS_ROOT = REPO_ROOT / "app" / "builderops"

# Relative paths (from REPO_ROOT) permitted to access a store.
DATA_LAYER_AND_MIGRATION_ALLOWLIST: frozenset[str] = frozenset(
    {
        "app/builderops/control_plane/store.py",  # PostgreSQL data layer
        "app/builderops/control_plane/selection.py",  # selector + migration/test adapter
        "app/builderops/control_plane/legacy_migration.py",  # BCP-03 read-only import mechanism
    }
)

# The pre-existing BuilderOps Vault record store (LearningSignal, worklogs,
# promotion intents, receipts as vault-adjacent artifacts) is a genuinely
# separate system from the control plane above — see
# docs/builderops/BUILDEROPS_VAULT_BOUNDARY.md :: Scope and the README's
# backlog-reconciliation note that BCP-03/06, not BCP-04, migrate this
# authority. These are its known, audited legitimate store-access sites as of
# BCP-04 (issue #3791 review finding H5); a NEW file outside this allowlist
# that touches a store fails this test rather than silently extending the
# surface. Do not add a new entry here without an accompanying migration/
# audit — extending this allowlist is never the fix for a failing test.
VAULT_STORE_ALLOWLIST: frozenset[str] = frozenset(
    {
        "app/builderops/store.py",  # the Vault record store's own data layer
        "app/builderops/cli.py",  # legacy Vault CLI (this session's own coordination path)
        "app/builderops/boundary.py",  # local Vault HTTP/tool boundary (#1503), Product-adjacent
        "app/builderops/completeness_report.py",  # read-only Vault inventory report
        "app/builderops/cutover_evidence.py",  # #3686 audited one-time receipt producer/validator
        "app/builderops/ckm/store.py",  # CKM receipt store built on the Vault store
        "app/builderops/ckm/query_service.py",  # CKM projection-only read path: I-MA11 requires direct SQLite mode=ro
        "app/builderops/ckm/metrics.py",  # outer adapter over query_service; own small versioned SQLite receipt store, non-authoritative
        "app/builderops/ckm/comparison.py",  # fail-closed, descriptive-only comparison of retained metrics observations
        "app/builderops/ckm/observation_capture.py",  # privacy-safe observations over already-returned CKM outcomes; own adjacent SQLite store, no policy/promotion authority
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


def _vault_files() -> list[Path]:
    """Every app/builderops/**/*.py file OUTSIDE the control_plane/ subtree."""
    return sorted(
        path
        for path in BUILDEROPS_ROOT.rglob("*.py")
        if CONTROL_PLANE not in path.parents and path != CONTROL_PLANE
    )


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


def test_no_new_vault_store_access_sites_outside_the_audited_allowlist() -> None:
    """A NEW app/builderops/**/*.py file (outside control_plane/) that touches
    a database driver or constructs a Vault store must be explicitly audited
    and added to VAULT_STORE_ALLOWLIST, not silently introduced.

    This does not require migrating the existing legitimate Vault-record sites
    (they remain BCP-03/06 territory per the module docstring); it only closes
    the regression gap the control-plane-scoped guard above cannot see,
    because those files are outside app/builderops/control_plane/.
    """
    assert BUILDEROPS_ROOT.is_dir()
    violations: list[str] = []
    for path in _vault_files():
        rel = str(path.relative_to(REPO_ROOT))
        if rel in VAULT_STORE_ALLOWLIST:
            continue
        if _accesses_store(path):
            violations.append(rel)

    assert not violations, (
        "New app/builderops/ store-access sites outside the audited allowlist "
        "(add to VAULT_STORE_ALLOWLIST only after confirming this is a "
        "legitimate Vault-record data-layer site, not a new authority-bearing "
        "caller that should use the control-plane API client instead):\n"
        + "\n".join(f"  {v}" for v in sorted(violations))
    )


def test_vault_store_allowlist_is_accurate() -> None:
    """Every VAULT_STORE_ALLOWLIST entry still exists and still accesses a store."""
    stale: list[str] = []
    for rel in VAULT_STORE_ALLOWLIST:
        path = REPO_ROOT / rel
        if not path.exists() or not _accesses_store(path):
            stale.append(rel)
    assert not stale, (
        "Stale Vault store-boundary allowlist entries (remove or fix):\n"
        + "\n".join(f"  {s}" for s in sorted(stale))
    )
