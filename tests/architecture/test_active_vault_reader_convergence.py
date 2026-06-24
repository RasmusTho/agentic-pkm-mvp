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
    REPO_ROOT / "app" / "agents" / "panel_agent" / "runtime.py",
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

# Vault-identity env vars a named non-HTTP reader must NOT read directly.
# watcher/config.py owns the documented WATCHER_VAULT_PATH split and is excluded
# from this module list, so the panel/recall readers may not honor it either.
_VAULT_ENV_VAR_NAMES = frozenset(
    {
        "VAULT_ROOT",
        "VAULT_ROOT_DEV",
        "VAULT_ROOT_TEST",
        "WATCHER_VAULT_PATH",
    }
)


def _is_os_environ(node: ast.AST) -> bool:
    """Return True if *node* is the ``os.environ`` attribute access."""
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "environ"
        and isinstance(node.value, ast.Name)
        and node.value.id == "os"
    )


def _vault_env_literal(node: ast.AST) -> str | None:
    """Return the vault env-var name if *node* is a vault-identity string literal."""
    if isinstance(node, ast.Constant) and node.value in _VAULT_ENV_VAR_NAMES:
        return node.value
    return None


def _has_bare_vault_root_getenv(tree: ast.AST) -> list[str]:
    """Return ``"<lineno>: <detail>"`` for every direct vault-env read in *tree*.

    Detects, for any of the vault-identity env vars in ``_VAULT_ENV_VAR_NAMES``:
      * ``os.getenv("VAULT_ROOT")`` / ``os.getenv("WATCHER_VAULT_PATH")`` etc.
      * ``os.environ.get("VAULT_ROOT")``
      * ``os.environ["VAULT_ROOT"]`` subscript access

    The pre-#2476 ``os.getenv("VAULT_ROOT") or os.getenv("WATCHER_VAULT_PATH")``
    pattern in panel_agent/runtime.py must trip this.
    """
    hits: list[str] = []
    for node in ast.walk(tree):
        # os.getenv("VAULT_ROOT") / os.environ.get("VAULT_ROOT")
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and node.args:
                env_var = _vault_env_literal(node.args[0])
                if env_var is not None:
                    is_os_getenv = (
                        func.attr == "getenv"
                        and isinstance(func.value, ast.Name)
                        and func.value.id == "os"
                    )
                    is_environ_get = func.attr == "get" and _is_os_environ(func.value)
                    if is_os_getenv or is_environ_get:
                        accessor = "os.getenv" if is_os_getenv else "os.environ.get"
                        hits.append(f"{node.lineno}: {accessor}('{env_var}')")
            continue
        # os.environ["VAULT_ROOT"] subscript
        if isinstance(node, ast.Subscript) and _is_os_environ(node.value):
            env_var = _vault_env_literal(node.slice)
            if env_var is not None:
                hits.append(f"{node.lineno}: os.environ['{env_var}']")
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
    """Named non-HTTP readers must funnel vault identity through a canonical resolver.

    Two positive requirements, both enforced per named module:

    1. **No direct vault-env reads.** The module must not read any vault-identity
       env var directly — ``VAULT_ROOT``, ``VAULT_ROOT_DEV``, ``VAULT_ROOT_TEST``,
       or ``WATCHER_VAULT_PATH`` — via ``os.getenv(...)``, ``os.environ.get(...)``,
       or ``os.environ[...]`` subscript.
    2. **Positive resolver import.** The module must import one of the canonical
       active-vault resolvers (``resolve_optional_vault_root``,
       ``resolve_active_vault_root``, ``ActiveContextResolver``).

    Requirement 2 closes the weak-guard gap (flagged by adversarial review): the
    previous test passed *trivially* for a module with no bare env read, without
    ever asserting that vault identity actually flows through the canonical
    resolver. A module that silently stopped resolving a vault — or resolved one
    via some other un-converged path — would have slipped through. Now every
    named reader must positively demonstrate convergence.

    The watcher (``app/watcher/config.py``) is excluded from ``NAMED_READER_MODULES``:
    it carries an explicit documented HTTP-vs-background split (``WATCHER_VAULT_PATH``)
    with rationale in its module docstring, guarded separately below.
    """
    violations: list[str] = []

    for path in NAMED_READER_MODULES:
        if not path.exists():
            violations.append(f"{path.relative_to(REPO_ROOT)}: file not found")
            continue

        relative = path.relative_to(REPO_ROOT)
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))

        # (1) No direct vault-env reads of any vault-identity env var.
        for hit in _has_bare_vault_root_getenv(tree):
            violations.append(
                f"{relative}:{hit}: direct vault-env read; must route through a "
                f"canonical resolver ({sorted(CANONICAL_RESOLVER_NAMES)})"
            )

        # (2) Positively require a canonical resolver import.
        if not _imports_canonical_resolver(tree):
            violations.append(
                f"{relative}: does not import a canonical active-vault resolver "
                f"({sorted(CANONICAL_RESOLVER_NAMES)}); vault identity must flow "
                "through the canonical resolver, not an un-converged path"
            )

    assert not violations, (
        "Named non-HTTP vault readers must funnel through the canonical "
        "active-vault resolver (resolve_optional_vault_root, "
        "resolve_active_vault_root, or ActiveContextResolver) and must not read "
        "any vault-identity env var directly. Violations:\n"
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
