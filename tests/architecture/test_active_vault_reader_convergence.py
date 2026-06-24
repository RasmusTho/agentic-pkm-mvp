"""Fitness check: named non-HTTP active-vault readers funnel through canonical resolver.

AC1 for #2476: the named non-HTTP runtime readers that derive vault identity
must route through the canonical active-vault resolver
(``resolve_optional_vault_root`` / ``resolve_active_vault_root`` /
``ActiveContextResolver``) or the HTTP-vs-background split must be explicitly
documented.

This test operates at the code level (AST inspection) to prevent silent
re-introduction of direct ``os.getenv("VAULT_ROOT")`` reads in the named
non-HTTP reader modules.

Source: docs/architecture/SBS_TRANSITION_DEBT.md :: D1
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Non-HTTP reader modules that were named in the issue as split-brain sites.
# Each must NOT contain a bare ``os.getenv("VAULT_ROOT")`` call — they must
# route through one of the canonical resolvers or have an explicit documented
# HTTP-vs-background split.
#
# Excluded from this check:
# - app/api/routes/* — HTTP path, owns its own canonical resolver
# - app/watcher/config.py — deliberate documented split (WATCHER_VAULT_PATH);
#   the docstring in watcher/config.py carries the rationale
# - app/config/paths.py — owns the canonical resolver itself
NAMED_READER_MODULES = (
    REPO_ROOT / "app" / "agents" / "panel_agent" / "wiring.py",
    REPO_ROOT / "app" / "agents" / "panel_agent" / "cognition.py",
    REPO_ROOT / "app" / "agent_memory" / "recall_retrieval.py",
)

# The canonical resolver imports that satisfy the convergence requirement.
CANONICAL_RESOLVER_NAMES = frozenset(
    {
        "resolve_optional_vault_root",
        "resolve_active_vault_root",
        "ActiveContextResolver",
    }
)


def _has_bare_vault_root_getenv(tree: ast.AST) -> list[int]:
    """Return line numbers of ``os.getenv("VAULT_ROOT")`` calls in *tree*."""
    hits: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        is_getenv = (
            isinstance(func, ast.Attribute)
            and func.attr == "getenv"
            and isinstance(func.value, ast.Name)
            and func.value.id == "os"
        )
        if not is_getenv or not node.args:
            continue
        first_arg = node.args[0]
        if isinstance(first_arg, ast.Constant) and first_arg.value == "VAULT_ROOT":
            hits.append(node.lineno)
    return hits


def _imports_canonical_resolver(tree: ast.AST) -> bool:
    """Return True if the module imports a canonical active-vault resolver."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name in CANONICAL_RESOLVER_NAMES or alias.asname in CANONICAL_RESOLVER_NAMES:
                    return True
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in CANONICAL_RESOLVER_NAMES or alias.asname in CANONICAL_RESOLVER_NAMES:
                    return True
    return False


def test_vault_readers_funnel_through_resolver() -> None:
    """Named non-HTTP readers must not read VAULT_ROOT directly outside canonical resolver.

    Each named module must either:
    (a) not contain a bare ``os.getenv("VAULT_ROOT")`` call, OR
    (b) import a canonical resolver alongside any ``os.getenv("VAULT_ROOT")``
        usage (indicating transitional dual-read or a legitimate override path
        that still acknowledges the canonical resolver).

    The watcher (``app/watcher/config.py``) is excluded: it carries an explicit
    documented HTTP-vs-background split with rationale in its module docstring.
    """
    violations: list[str] = []

    for path in NAMED_READER_MODULES:
        if not path.exists():
            violations.append(f"{path.relative_to(REPO_ROOT)}: file not found")
            continue

        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))

        bare_getenv_lines = _has_bare_vault_root_getenv(tree)
        if not bare_getenv_lines:
            # No direct env reads — compliant
            continue

        # Has direct env reads: must also import the canonical resolver
        if not _imports_canonical_resolver(tree):
            relative = path.relative_to(REPO_ROOT)
            for lineno in bare_getenv_lines:
                violations.append(
                    f"{relative}:{lineno}: bare os.getenv('VAULT_ROOT') without "
                    f"canonical resolver import ({sorted(CANONICAL_RESOLVER_NAMES)})"
                )

    assert not violations, (
        "Named non-HTTP vault readers must funnel through the canonical "
        "active-vault resolver (resolve_optional_vault_root, "
        "resolve_active_vault_root, or ActiveContextResolver) or have an "
        "explicit documented HTTP-vs-background split. Violations:\n"
        + "\n".join(violations)
    )


def test_watcher_split_is_documented() -> None:
    """The watcher's HTTP-vs-background split must be documented in its module docstring.

    The watcher (app/watcher/config.py) uses WATCHER_VAULT_PATH independently
    of the HTTP vault-selection path — an intentional split. This test guards
    that the rationale remains documented rather than silently drifting.
    """
    watcher_config = REPO_ROOT / "app" / "watcher" / "config.py"
    assert watcher_config.exists(), f"Expected watcher config at {watcher_config}"

    source = watcher_config.read_text(encoding="utf-8")
    # The documented split must name the key design decision
    assert "HTTP-vs-background split" in source, (
        f"{watcher_config.relative_to(REPO_ROOT)}: missing HTTP-vs-background "
        "split rationale in module docstring. The watcher's independent vault "
        "binding (WATCHER_VAULT_PATH) must be explicitly documented."
    )
