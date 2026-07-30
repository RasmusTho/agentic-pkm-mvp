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
import importlib
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


def _instance_storage_contract_section() -> configparser.SectionProxy:
    parser = configparser.ConfigParser()
    parser.read(IMPORTLINTER_INI)
    return parser["importlinter:contract:instance-storage-mutation-protected"]


def _instance_storage_capability_contract_section() -> configparser.SectionProxy:
    parser = configparser.ConfigParser()
    parser.read(IMPORTLINTER_INI)
    return parser["importlinter:contract:instance-storage-capability-protected"]


def _builder_llm_authority_contract_section() -> configparser.SectionProxy:
    parser = configparser.ConfigParser()
    parser.read(IMPORTLINTER_INI)
    return parser["importlinter:contract:builder-llm-authority"]


def _neutral_llm_contract_section() -> configparser.SectionProxy:
    parser = configparser.ConfigParser()
    parser.read(IMPORTLINTER_INI)
    return parser["importlinter:contract:neutral-llm-contract-kernel"]


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


def _builder_to_product_llm_imports() -> Set[tuple[str, str]]:
    """Return static Builder imports of the Product LLM package by source module."""
    imports: Set[tuple[str, str]] = set()
    for path in (APP_ROOT / "builderops").rglob("*.py"):
        relative = path.relative_to(APP_ROOT).with_suffix("")
        module_parts = relative.parts[:-1] if relative.name == "__init__" else relative.parts
        source_module = ".".join(("app", *module_parts))
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules = (alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_modules = (node.module,)
            else:
                continue
            for imported_module in imported_modules:
                if imported_module.startswith("app.components.llm"):
                    imports.add((source_module, imported_module))
    return imports


def _is_direct_dynamic_import_call(node: ast.Call) -> bool:
    func = node.func
    if isinstance(func, ast.Attribute) and func.attr == "import_module":
        return True
    return isinstance(func, ast.Name) and func.id == "__import__"


def _string_literal_first_arg(node: ast.Call) -> str | None:
    if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
        return node.args[0].value
    return None


def _local_import_wrapper_names(tree: ast.AST) -> Set[str]:
    """Find local functions that wrap direct dynamic imports."""
    functions = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]
    wrappers: Set[str] = set()
    changed = True
    while changed:
        changed = False
        for func in functions:
            if func.name in wrappers:
                continue
            for node in ast.walk(func):
                if not isinstance(node, ast.Call):
                    continue
                is_wrapper_call = isinstance(node.func, ast.Name) and node.func.id in wrappers
                if _is_direct_dynamic_import_call(node) or is_wrapper_call:
                    wrappers.add(func.name)
                    changed = True
                    break
    return wrappers


def _importlib_string_targets(path: Path) -> Set[str]:
    """Collect string-literal targets for dynamic imports and local wrappers.

    These are the *dynamic* imports import-linter cannot see statically, including
    helper calls such as ``_module_importable("app.api...")`` that wrap
    ``__import__`` or ``importlib.import_module``.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    wrapper_names = _local_import_wrapper_names(tree)
    targets: Set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        is_wrapper_call = isinstance(node.func, ast.Name) and node.func.id in wrapper_names
        if not (_is_direct_dynamic_import_call(node) or is_wrapper_call):
            continue
        target = _string_literal_first_arg(node)
        if target is not None:
            targets.add(target)
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


def test_llm_contract_kernel_is_covered_by_import_boundary() -> None:
    section = _neutral_llm_contract_section()
    assert _module_list(section["source_modules"]) == {"llm_contract"}
    assert _module_list(section["forbidden_modules"]) == {"app"}


# ---------------------------------------------------------------------------
# MAS-06 — Builder CKM model access is fully separated from Product LLM policy.
# ---------------------------------------------------------------------------


def test_builder_does_not_import_product_llm_without_exemption() -> None:
    """No Builder module may cross into the Product LLM authority."""
    contract = _builder_llm_authority_contract_section()
    assert contract["type"] == "forbidden"
    assert _module_list(contract["source_modules"]) == {"app.builderops"}
    assert _module_list(contract["forbidden_modules"]) == {"app.components.llm"}

    # Both PR workflows invoke this same config, so this proves the production
    # CI gate rather than a test-local reimplementation of the contract.
    for workflow in (".github/workflows/import-linter.yaml", ".github/workflows/ci-smoke.yaml"):
        assert "lint-imports --config importlinter.ini" in (REPO_ROOT / workflow).read_text(
            encoding="utf-8"
        )

    assert _builder_to_product_llm_imports() == set()


def test_interim_exemption_is_removed_with_last_import() -> None:
    """The MAS-02 exemption disappears atomically with the Product imports."""
    raw = IMPORTLINTER_INI.read_text(encoding="utf-8")
    section = raw.split("[importlinter:contract:builder-llm-authority]", maxsplit=1)[1]
    section = section.split("[importlinter:contract:", maxsplit=1)[0]

    assert "ignore_imports =" not in section
    assert "MAS-06" not in section
    contract = _builder_llm_authority_contract_section()
    assert "ignore_imports" not in contract


def test_importlinter_header_states_blocking_gate_posture() -> None:
    """The config header describes the two workflows that block on this gate."""
    header = IMPORTLINTER_INI.read_text(encoding="utf-8").split("[importlinter]", maxsplit=1)[0]
    assert "Run BLOCKING" in header
    assert ".github/workflows/import-linter.yaml" in header
    assert ".github/workflows/ci-smoke.yaml" in header
    assert "non-blocking" not in header.lower()


def test_interaction_protected_contract_coverage_is_unchanged() -> None:
    """MAS-02 adds a separate contract without weakening the existing one."""
    section = _contract_section()
    assert section["type"] == "forbidden"
    assert _module_list(section["source_modules"])
    assert _module_list(section["forbidden_modules"]) == {
        "app.api",
        "app.chat",
        "app.cli",
        "app.web",
    }


def test_instance_storage_mutation_import_contract_is_complete() -> None:
    """Only the sanctioned transaction modules may import storage mutators."""

    section = _instance_storage_contract_section()
    assert section["type"] == "protected"
    assert section.getboolean("as_packages") is False
    assert _module_list(section["protected_modules"]) == {
        "app.instance.instance_state",
        "app.instance.ownership_ledger",
    }
    assert _module_list(section["allowed_importers"]) == {
        "app.instance.instance_state",
        "app.instance.runtime",
    }
    capability_section = _instance_storage_capability_contract_section()
    assert capability_section["type"] == "protected"
    assert capability_section.getboolean("as_packages") is False
    assert _module_list(capability_section["protected_modules"]) == {
        "app.instance._storage_boundary",
    }
    assert _module_list(capability_section["allowed_importers"]) == {
        "app.instance.ownership_ledger",
        "app.instance.runtime",
        "app.instance.vault_registry",
    }
    runtime_module = importlib.import_module("app.instance.runtime")
    assert not hasattr(runtime_module, "_STORAGE_MUTATION_CAPABILITY")


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


def test_status_service_consumes_source_understanding_availability_via_provider() -> None:
    """Foundation status_service consumes API route availability through a provider."""
    from app.observability import status_service

    assert hasattr(status_service, "register_source_understanding_availability_provider")
    saved = status_service._source_understanding_availability_provider
    try:
        status_service.register_source_understanding_availability_provider(None)
        assert status_service._source_understanding_available() is False

        status_service.register_source_understanding_availability_provider(lambda: True)
        assert status_service._source_understanding_available() is True
    finally:
        status_service.register_source_understanding_availability_provider(saved)
