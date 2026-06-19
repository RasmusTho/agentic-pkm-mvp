"""ADR-0013 import-boundary completeness checks.

Two residuals from the 2026-06-18 terminal review-thread audit (#2148, issue #2194):

1. ``importlinter.ini`` ``source_modules`` omitted several real ``app.*`` packages, so
   the interaction-protected contract silently failed to evaluate them. This asserts
   that every real non-interaction ``app.*`` package is listed (coverage is complete).

2. ``app/observability/status_service.py`` (Foundation layer) dynamically imported
   interaction-layer modules (``app.api.routes.*``, ``app.resurfacing``) via the v6.0
   seam probe — an upward/backward dependency that ADR-0013 forbids and that
   import-linter cannot see through a runtime ``importlib`` string. This asserts the
   probe now lives in the interaction layer and the Foundation status service stays
   upward-free (no interaction import, static or dynamic) and reaches the probe through
   a registered provider.

See docs/adr/ADR-0013-code-dependency-direction.md and importlinter.ini.
"""

from __future__ import annotations

import ast
import configparser
from pathlib import Path
from typing import Set

REPO_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = REPO_ROOT / "app"
IMPORTLINTER_INI = REPO_ROOT / "importlinter.ini"

INTERACTION_LAYER = {"api", "chat", "cli", "web"}
# Migrations dir, not an application package; intentionally excluded from the contract.
NON_PACKAGE_DIRS = {"alembic"}


def _contract_section() -> configparser.SectionProxy:
    parser = configparser.ConfigParser()
    parser.read(IMPORTLINTER_INI)
    return parser["importlinter:contract:interaction-protected"]


def _module_list(raw: str) -> Set[str]:
    # configparser drops full-line "#" comments inside multiline values, so the
    # surviving lines are real module names.
    return {line.strip() for line in raw.splitlines() if line.strip()}


def _real_app_packages() -> Set[str]:
    packages: Set[str] = set()
    for child in APP_ROOT.iterdir():
        if not child.is_dir():
            continue
        if child.name in NON_PACKAGE_DIRS:
            continue
        if (child / "__init__.py").is_file():
            packages.add(child.name)
    return packages


def _imported_modules(path: Path) -> Set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def _importlib_string_targets(path: Path) -> Set[str]:
    """Collect string-literal first args to importlib.import_module / __import__.

    These are the *dynamic* imports import-linter cannot see statically.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    targets: Set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = None
        if isinstance(func, ast.Attribute) and func.attr == "import_module":
            name = "import_module"
        elif isinstance(func, ast.Name) and func.id == "__import__":
            name = "__import__"
        if name is None:
            continue
        if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
            targets.add(node.args[0].value)
    return targets


# ---------------------------------------------------------------------------
# AC1 — importlinter.ini source_modules coverage is complete.
# ---------------------------------------------------------------------------


def test_import_contract_covers_all_non_interaction_packages() -> None:
    """Every real non-interaction app.* package must be listed in the contract.

    Either as a protected source_module or as a forbidden (interaction) module —
    so no current package escapes the interaction-protected contract silently.
    """
    section = _contract_section()
    source = {m.removeprefix("app.") for m in _module_list(section["source_modules"])}
    forbidden = {m.removeprefix("app.") for m in _module_list(section["forbidden_modules"])}

    covered = source | forbidden
    real = _real_app_packages()

    missing = sorted(real - covered)
    assert not missing, (
        "importlinter.ini does not cover these real app.* packages "
        f"(add them to source_modules): {missing}"
    )


def test_interaction_packages_are_the_forbidden_set() -> None:
    """The forbidden (protected) set is exactly the interaction layer."""
    section = _contract_section()
    forbidden = {m.removeprefix("app.") for m in _module_list(section["forbidden_modules"])}
    assert forbidden == INTERACTION_LAYER


def test_source_modules_exclude_interaction_and_resolve() -> None:
    """source_modules must not include interaction packages and must all be real."""
    section = _contract_section()
    source = {m.removeprefix("app.") for m in _module_list(section["source_modules"])}
    real = _real_app_packages()

    leaked_interaction = sorted(source & INTERACTION_LAYER)
    assert not leaked_interaction, (
        f"interaction packages must stay in forbidden_modules, not source_modules: {leaked_interaction}"
    )

    unresolvable = sorted(source - real)
    assert not unresolvable, (
        f"source_modules names packages that do not exist under app/: {unresolvable}"
    )


# ---------------------------------------------------------------------------
# AC2 — v6 seam probe moved out of the Foundation observability layer.
# ---------------------------------------------------------------------------


def test_status_service_has_no_interaction_imports() -> None:
    """Foundation status_service must not import the interaction layer (static)."""
    path = APP_ROOT / "observability" / "status_service.py"
    imports = _imported_modules(path)
    offenders = sorted(
        mod
        for mod in imports
        for layer in INTERACTION_LAYER
        if mod == f"app.{layer}" or mod.startswith(f"app.{layer}.")
    )
    assert not offenders, (
        "app/observability/status_service.py (Foundation) must not import the "
        f"interaction layer; found: {offenders}"
    )


def test_status_service_has_no_dynamic_interaction_imports() -> None:
    """The v6 seam probe must not dynamically import interaction modules from Foundation."""
    path = APP_ROOT / "observability" / "status_service.py"
    targets = _importlib_string_targets(path)
    offenders = sorted(
        target
        for target in targets
        for layer in INTERACTION_LAYER
        if target == f"app.{layer}" or target.startswith(f"app.{layer}.")
    )
    assert not offenders, (
        "app/observability/status_service.py must not importlib-import the interaction "
        f"layer; the seam probe belongs in the interaction layer. Found: {offenders}"
    )


def test_v6_seam_probe_lives_in_interaction_layer() -> None:
    """The seam probe is owned by an interaction-layer module."""
    probe = APP_ROOT / "api" / "v6_seams.py"
    assert probe.is_file(), "expected the v6 seam probe at app/api/v6_seams.py"
    tree = ast.parse(probe.read_text(encoding="utf-8"))
    funcs = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert "check_v6_seams" in funcs


def test_status_service_consumes_seam_probe_via_provider() -> None:
    """Foundation status_service exposes a provider hook instead of importing the probe."""
    from app.observability import status_service

    assert hasattr(status_service, "register_v6_seams_provider")
    saved = status_service._v6_seams_provider
    try:
        # With no provider registered, the Foundation path stays upward-free and
        # returns None (it never imports the interaction layer to find the probe).
        status_service.register_v6_seams_provider(None)  # type: ignore[arg-type]
        assert status_service._get_v6_seams() is None

        # The interaction-layer probe registers itself on import; register it
        # explicitly here (idempotent) so the assertion does not depend on whether
        # app.api.v6_seams was already imported by an earlier test.
        from app.api.v6_seams import check_v6_seams

        status_service.register_v6_seams_provider(check_v6_seams)
        seams = status_service._get_v6_seams()
        assert isinstance(seams, dict)
        for key in ("orientation", "resurfacing", "commitments", "canvas"):
            assert key in seams
            assert seams[key] in ("enabled", "disabled")
    finally:
        status_service.register_v6_seams_provider(saved)  # type: ignore[arg-type]
