"""Guard against new callers of deprecated app.store and app.stores packages.

These packages are deprecated per docs/CODE_INVENTORY.md §Deprecated Packages:
  - app.store  — superseded by app.objects (DomainObject, ObjectStore, etc.)
  - app.stores — transitional store layer; migrate toward service+outbox boundaries

The test walks app/**/*.py and detects any file that imports from either deprecated
package (both ``import app.store...`` / ``from app.store... import ...`` forms,
including submodules).  Files in app/store/ and app/stores/ themselves are excluded.

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


def _imports_deprecated_store(path: Path) -> bool:
    """Return True if the file contains any import of app.store or app.stores."""
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
                name = alias.name
                if name in ("app.store", "app.stores") or name.startswith(
                    ("app.store.", "app.stores.")
                ):
                    return True
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module in ("app.store", "app.stores") or module.startswith(
                ("app.store.", "app.stores.")
            ):
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
    """Every file in the allowlist still exists.

    If a file is removed or migrated, remove it from the allowlist to keep
    the guard minimal and accurate.
    """
    stale: list[str] = []
    for rel in ALLOWLIST:
        if not (REPO_ROOT / rel).exists():
            stale.append(rel)

    assert not stale, (
        "Stale allowlist entries found in test_deprecated_store_callers.py.\n"
        "These files no longer exist — remove them from ALLOWLIST:\n"
        + "\n".join(f"  {s}" for s in sorted(stale))
    )
