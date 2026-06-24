"""Guard against new callers of deprecated app.store and app.stores packages.

These packages are deprecated per docs/CODE_INVENTORY.md §Deprecated Packages:
  - app.store  — superseded by app.objects (DomainObject, ObjectStore, etc.)
  - app.stores — transitional store layer; migrate toward service+outbox boundaries

The test walks app/**/*.py and detects any file that imports from either deprecated
package (both ``import app.store...`` / ``from app.store... import ...`` forms,
including submodules AND relative imports that resolve to those packages).
Files in app/store/ and app/stores/ themselves are excluded.

ALLOWLIST contains the set of files that existed as callers on origin/main at the
time ADR-0013 was flipped to blocking (2026-06-24, issue #2481).  A new file that
imports from app.store or app.stores will fail this test.  Remove a file from the
allowlist once it has been migrated.

Do NOT extend this allowlist without an accompanying migration issue.  Adding a new
caller extends a deprecated surface and is never the right answer.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = REPO_ROOT / "app"

# Deprecated packages — submodule imports are also covered.
DEPRECATED_PREFIXES = ("app.store.", "app.stores.", "app.store", "app.stores")

# Exact relative paths (from REPO_ROOT) of files that were already importing from
# the deprecated packages when the guard was introduced.  These are allowed to
# continue until their respective migration issues are resolved.
# DO NOT ADD new entries here.  Open a migration issue instead.
ALLOWLIST: frozenset[str] = frozenset(
    [
        # app/objects re-exports types from app.store (compatibility shim — intentional
        # until all callers migrate to app.objects)
        "app/objects/__init__.py",
        # agents area — tracked by cleanup follow-up (see CODE_INVENTORY.md §Cleanup)
        "app/agents/_test_helpers.py",
        "app/agents/classifier/agent.py",
        "app/agents/classify.py",
        "app/agents/panel_agent/planning.py",
        "app/agents/pipeline.py",
        "app/agents/projector/agent.py",
        "app/agents/set_evaluator/agent.py",
        # api / interaction layer
        "app/api/routes/ask.py",
        # cli area — tracked by cleanup follow-up (see CODE_INVENTORY.md §Cleanup)
        "app/cli/__init__.py",
        "app/cli/alpha_human_flows.py",
        "app/cli/debug_list_objects.py",
        "app/cli/health.py",
        "app/cli/index_rebuild.py",
        "app/cli/smoke.py",
        # fitness
        "app/fitness/metrics.py",
        # health contract
        "app/health_contract.py",
        # index
        "app/index/doctor.py",
        "app/index/vector_index_memory.py",
        # indexer
        "app/indexer/consumer.py",
        # ingest + vault
        "app/ingest/external.py",
        "app/ingest/vault_alpha.py",
        "app/ingest/vault_root.py",
        # observability
        "app/observability/status_service.py",
        # orchestrator
        "app/orchestrator/handler.py",
        # planner
        "app/planner/events.py",
        # promotion
        "app/promotion/gates.py",
        # reasoning
        "app/reasoning/multi.py",
        "app/reasoning/provider.py",
        # search
        "app/search/service.py",
        # services
        "app/services/audit.py",
        "app/services/indexer.py",
    ]
)


def _resolve_relative_import(file_path: Path, level: int, module: str | None) -> str:
    """Resolve a relative import to its absolute dotted module path.

    Given a file at e.g. ``app/agents/classifier/agent.py`` and a relative
    import ``from ..store import Foo`` (level=2, module="store"), compute the
    absolute dotted path ``app.store``.

    Algorithm:
      1. Derive the file's package as its parent dirs relative to REPO_ROOT,
         joined with dots (e.g. ``app.agents.classifier``).
      2. Split into components; drop ``level - 1`` trailing components to find
         the anchor package (level=1 → same package; level=2 → parent; etc.).
      3. Append ``module`` (if present) to the anchor components.
      4. Return the joined dotted string.
    """
    rel_parts = list(file_path.parent.relative_to(REPO_ROOT).parts)
    # level=1 means current package; drop (level-1) trailing components
    drop = max(0, level - 1)
    if drop:
        anchor_parts = rel_parts[:-drop] if drop < len(rel_parts) else []
    else:
        anchor_parts = rel_parts

    if module:
        anchor_parts = anchor_parts + module.split(".")

    return ".".join(anchor_parts)


def _is_deprecated_module(dotted: str) -> bool:
    """Return True if ``dotted`` refers to app.store or app.stores (or a submodule)."""
    return dotted in ("app.store", "app.stores") or dotted.startswith(
        ("app.store.", "app.stores.")
    )


def _imports_deprecated_store(path: Path) -> bool:
    """Return True if the file contains any import of app.store or app.stores.

    Detects:
    - Absolute ``import app.store...`` / ``from app.store... import ...``
    - Relative imports that resolve to app.store / app.stores, e.g.
      ``from .store import X`` inside app/something/ or
      ``from ..stores.foo import Bar`` from a nested package.
    """
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return False

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_deprecated_module(alias.name):
                    return True
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                # Relative import — resolve to absolute dotted path first.
                # Case A: ``from .store import X`` / ``from ..stores.foo import Y``
                #   node.module is set ("store", "stores.foo") — resolve directly.
                # Case B: ``from .. import store`` / ``from . import stores``
                #   node.module is None — the imported *name* is the sub-package;
                #   check each alias name as a potential sub-package reference.
                if node.module is not None:
                    resolved = _resolve_relative_import(path, node.level, node.module)
                    if _is_deprecated_module(resolved):
                        return True
                else:
                    # node.module is None: anchor is the package reached by `level`
                    anchor = _resolve_relative_import(path, node.level, None)
                    for alias in node.names:
                        candidate = f"{anchor}.{alias.name}" if anchor else alias.name
                        if _is_deprecated_module(candidate):
                            return True
            else:
                # Absolute import
                module = node.module or ""
                if _is_deprecated_module(module):
                    return True
    return False


def _all_app_py_files() -> list[Path]:
    """Walk app/ and return all .py files, excluding app/store/ and app/stores/ themselves."""
    result: list[Path] = []
    for py_file in APP_ROOT.rglob("*.py"):
        parts = py_file.relative_to(REPO_ROOT).parts
        # Skip files inside the deprecated packages themselves
        if len(parts) >= 2 and parts[1] in ("store", "stores"):
            continue
        result.append(py_file)
    return result


def test_no_new_store_callers() -> None:
    """No app/*.py file outside the allowlist may import from app.store or app.stores.

    These are deprecated packages (docs/CODE_INVENTORY.md §Deprecated Packages).
    New callers extend a deprecated surface.  Migrate instead.

    Both absolute imports (``from app.store import X``) and relative imports that
    resolve to the deprecated packages (``from .store import X`` inside app/) are
    detected.
    """
    violations: list[str] = []

    for py_file in _all_app_py_files():
        rel = str(py_file.relative_to(REPO_ROOT))
        if not _imports_deprecated_store(py_file):
            continue
        # Known existing callers are allowed to remain
        if rel in ALLOWLIST:
            continue
        violations.append(rel)

    assert not violations, (
        "New callers of deprecated app.store / app.stores detected.\n"
        "Do NOT add new imports from these packages — they are deprecated.\n"
        "Migrate to app.objects (for DomainObject/ObjectStore types) or to\n"
        "service+outbox boundaries (for app.stores functionality).\n"
        "New callers (not in the allowlist):\n"
        + "\n".join(f"  {v}" for v in sorted(violations))
    )


def test_allowlist_entries_still_exist() -> None:
    """Every allowlisted file still exists AND still imports from app.store / app.stores.

    Two conditions are checked for each entry:

    1. **File existence** — if the file was deleted, remove it from the allowlist.
    2. **Deprecated import still present** — if the file no longer imports from
       the deprecated packages, it has been migrated.  Remove it from the allowlist
       so it is no longer skipped by ``test_no_new_store_callers`` (an allowlisted
       file is invisible to that test, so a reintroduced import would go undetected).

    Failing either check means the allowlist is stale.  Fix it to keep the guard
    minimal and accurate.
    """
    missing_files: list[str] = []
    migrated_files: list[str] = []

    for rel in ALLOWLIST:
        abs_path = REPO_ROOT / rel
        if not abs_path.exists():
            missing_files.append(rel)
            continue
        # File exists — confirm it still imports a deprecated package
        if not _imports_deprecated_store(abs_path):
            migrated_files.append(rel)

    messages: list[str] = []
    if missing_files:
        messages.append(
            "Allowlist entries whose files no longer exist"
            " — remove them from ALLOWLIST:\n"
            + "\n".join(f"  {s}" for s in sorted(missing_files))
        )
    if migrated_files:
        messages.append(
            "Allowlist entries that no longer import a deprecated package"
            " — the file has been migrated, remove it from ALLOWLIST:\n"
            + "\n".join(f"  {s}" for s in sorted(migrated_files))
        )

    assert not (missing_files or migrated_files), (
        "Stale allowlist entries found in test_deprecated_store_callers.py.\n"
        + "\n".join(messages)
    )


def test_resolver_catches_alias_import_form() -> None:
    """_imports_deprecated_store must flag the ``from .. import store`` alias form.

    When ``node.module is None`` and level > 0, the imported name sits in
    ``node.names`` rather than in ``node.module``.  This test uses a synthetic
    file path inside app/ to ensure the resolver correctly expands
    ``from .. import store`` to ``app.store`` and flags it as deprecated.

    Also covers:
    - ``from .. import stores`` → app.stores (flagged)
    - ``from . import store``  → app.agents.store (NOT flagged — not deprecated)
    - ``from .. import objects`` → app.objects (NOT flagged — not deprecated)
    """
    import tempfile, textwrap

    # Synthetic file that lives at app/agents/some_module.py so that:
    #   level=2, module=None, name="store"  → resolves to app.store (deprecated)
    #   level=2, module=None, name="stores" → resolves to app.stores (deprecated)
    synthetic_dir = APP_ROOT / "agents"  # real dir; file won't be written there

    # --- Case 1: from .. import store  (should be flagged) ---
    with tempfile.NamedTemporaryFile(
        suffix=".py",
        dir=synthetic_dir,
        mode="w",
        encoding="utf-8",
        delete=False,
    ) as tmp:
        tmp.write(textwrap.dedent("""\
            from .. import store
        """))
        tmp_path = Path(tmp.name)
    try:
        assert _imports_deprecated_store(tmp_path), (
            "Expected 'from .. import store' inside app/agents/ to be flagged as "
            "a deprecated-store import, but _imports_deprecated_store returned False."
        )
    finally:
        tmp_path.unlink(missing_ok=True)

    # --- Case 2: from .. import stores  (should be flagged) ---
    with tempfile.NamedTemporaryFile(
        suffix=".py",
        dir=synthetic_dir,
        mode="w",
        encoding="utf-8",
        delete=False,
    ) as tmp:
        tmp.write(textwrap.dedent("""\
            from .. import stores
        """))
        tmp_path = Path(tmp.name)
    try:
        assert _imports_deprecated_store(tmp_path), (
            "Expected 'from .. import stores' inside app/agents/ to be flagged."
        )
    finally:
        tmp_path.unlink(missing_ok=True)

    # --- Case 3: from .. import objects  (should NOT be flagged) ---
    with tempfile.NamedTemporaryFile(
        suffix=".py",
        dir=synthetic_dir,
        mode="w",
        encoding="utf-8",
        delete=False,
    ) as tmp:
        tmp.write(textwrap.dedent("""\
            from .. import objects
        """))
        tmp_path = Path(tmp.name)
    try:
        assert not _imports_deprecated_store(tmp_path), (
            "Expected 'from .. import objects' NOT to be flagged."
        )
    finally:
        tmp_path.unlink(missing_ok=True)
