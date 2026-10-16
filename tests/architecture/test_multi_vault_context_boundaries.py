"""Structural guard for MVR-05B request consumers (MVR-05B1, #6136).

The gate scans the real production request entrypoints (derived, not listed),
detects global vault resolution by AST, and compares the measured offenders to a
named compatibility-adapter allowlist in both directions. The helper module
``context_boundary_inventory`` owns the derivation and the allowlist; 05B2-05B4
shrink the allowlist and never edit this test.
"""

from __future__ import annotations

import ast

import pytest

from tests.architecture import context_boundary_inventory as inventory
from tests.architecture.context_boundary_inventory import (
    COMPATIBILITY_ADAPTERS,
    ROOT,
    CompatibilityAdapter,
    adapter_key,
    compare_to_allowlist,
    scan_production_entrypoints,
    scan_source,
)

_MIGRATED_ROUTE_MODULES = ("app/api/routes/search.py",)


def _names_in(relative: str, scope: str) -> set[str]:
    tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == scope:
            return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)} | {
                n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)
            }
    raise AssertionError(f"{scope} not found in {relative}")


def test_request_consumers_use_context_seam() -> None:
    """No request-bound production code resolves the vault globally outside the allowlist."""

    measured = scan_production_entrypoints()
    unlisted, _ = compare_to_allowlist(measured, COMPATIBILITY_ADAPTERS)
    assert not unlisted, (
        "new direct global vault resolution in a production request entrypoint; route it "
        "through the scoped seam (app/api/request_active_context.py) instead of adding an "
        "allowlist entry:\n" + "\n".join(unlisted)
    )

    # The consumers already migrated by #5456 stay on the seam: they use it and
    # hold no allowlist entry.
    for module in _MIGRATED_ROUTE_MODULES:
        assert not [k for k in measured if k[0] == module], module
    assert not [k for k in measured if k == ("app/api/routes/ask.py", "ask")]
    assert "require_scoped_read_context" in _names_in(
        "app/api/routes/companion.py", "list_scoped_vault_notes"
    )
    assert ("app/api/routes/companion.py", "list_scoped_vault_notes") not in measured


def test_context_boundary_inventory_and_allowlist_are_exact() -> None:
    """Inventory is derived and fully classified; the allowlist is neither short nor stale."""

    assert not inventory.missing_registered_modules()
    assert not inventory.unclassified_route_modules(), (
        "request-handling route module is neither registered in app/api/app.py nor named in "
        "UNREGISTERED_ROUTE_MODULES"
    )
    assert not inventory.stale_route_classifications()

    modules = set(inventory.entrypoint_modules())
    assert {
        "app/api/routes/companion.py",
        "app/api/routers/agent.py",
        "app/agents/ask/graph.py",
        "app/mcp/vault_tools.py",
        "app/cli/__init__.py",
    } <= modules
    assert inventory.registered_router_modules() <= modules

    measured = scan_production_entrypoints()
    unlisted, stale = compare_to_allowlist(measured, COMPATIBILITY_ADAPTERS)
    assert not unlisted, "unlisted global resolution:\n" + "\n".join(unlisted)
    assert not stale, "stale or mismatched allowlist entries (the list may only shrink):\n" + "\n".join(
        stale
    )

    keys = [adapter_key(entry) for entry in COMPATIBILITY_ADAPTERS]
    assert len(keys) == len(set(keys)), "duplicate allowlist entry"
    for entry in COMPATIBILITY_ADAPTERS:
        assert entry.module in modules, entry
        assert entry.why.strip(), entry
        assert entry.retired_by in inventory.RETIRING_STAGES, entry
        assert entry.symbols, entry


# --------------------------------------------------------------------------- #
# The gate must fail on what it claims to catch.
# --------------------------------------------------------------------------- #


def test_gate_fails_on_injected_unlisted_global_lookup() -> None:
    injected = scan_source(
        "from app.vault.manager import get_vault_manager\n"
        "def brand_new_route():\n"
        "    return get_vault_manager().context\n",
        "app/api/routes/injected.py",
    )
    measured = scan_production_entrypoints()
    measured[("app/api/routes/injected.py", "brand_new_route")] = injected["brand_new_route"]
    unlisted, stale = compare_to_allowlist(measured, COMPATIBILITY_ADAPTERS)
    assert unlisted == ["app/api/routes/injected.py :: brand_new_route -> ['get_vault_manager']"]
    assert not stale


def test_gate_fails_on_new_symbol_in_a_listed_function() -> None:
    entry = COMPATIBILITY_ADAPTERS[0]
    measured = scan_production_entrypoints()
    measured[adapter_key(entry)] = entry.symbols | {"env:VAULT_ROOT"}
    _, stale = compare_to_allowlist(measured, COMPATIBILITY_ADAPTERS)
    assert len(stale) == 1 and entry.scope in stale[0]


def test_gate_fails_on_stale_allowlist_entry() -> None:
    ghost = CompatibilityAdapter(
        "app/api/routes/capture.py",
        "migrated_away",
        frozenset({"get_vault_manager"}),
        "pretends to resolve globally",
        "05B3",
    )
    unlisted, stale = compare_to_allowlist(
        scan_production_entrypoints(), (*COMPATIBILITY_ADAPTERS, ghost)
    )
    assert not unlisted
    assert stale == ["app/api/routes/capture.py :: migrated_away no longer resolves globally; delete the entry"]


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("def f():\n    return get_vault_manager()\n", {"get_vault_manager"}),
        ("def f():\n    return mod.get_vault_manager()\n", {"get_vault_manager"}),
        (
            "from x import get_vault_manager as gvm\ndef f():\n    return gvm()\n",
            {"get_vault_manager"},
        ),
        (
            "from fastapi import Depends\ndef f(m=Depends(get_vault_manager)):\n    return m\n",
            {"get_vault_manager"},
        ),
        ("import os\ndef f():\n    return os.getenv('VAULT_ROOT')\n", {"env:VAULT_ROOT"}),
        ("import os\ndef f():\n    return os.environ.get('VAULT_DIR')\n", {"env:VAULT_DIR"}),
        ("import os\ndef f():\n    return os.environ['VAULT_ROOT']\n", {"env:VAULT_ROOT"}),
        (
            "def f():\n    return active_vault_root_or_selection_required()\n",
            {"active_vault_root_or_selection_required"},
        ),
        ("def f():\n    return resolve_optional_vault_root()\n", {"resolve_optional_vault_root"}),
        ("def f():\n    return resolve_active_vault_root()\n", {"resolve_active_vault_root"}),
    ],
)
def test_detector_sees_structural_forms_not_substrings(source: str, expected: set[str]) -> None:
    found = scan_source(source)
    assert set().union(*found.values()) == expected


def test_detector_ignores_import_only_comments_and_docstrings() -> None:
    source = (
        "from x import get_vault_manager\n"
        "def f():\n"
        '    """Mentions get_vault_manager and VAULT_ROOT in prose."""\n'
        "    # get_vault_manager()\n"
        "    return require_scoped_read_context()\n"
    )
    assert scan_source(source) == {}


def test_gate_fails_on_unclassified_request_module(monkeypatch: pytest.MonkeyPatch) -> None:
    real = inventory._python_modules

    def with_extra(relative_dir: str) -> frozenset[str]:
        extra = {"app/api/routes/surprise.py"} if relative_dir == inventory.API_ROUTES_DIR else set()
        return real(relative_dir) | frozenset(extra)

    monkeypatch.setattr(inventory, "_python_modules", with_extra)
    assert inventory.unclassified_route_modules() == frozenset({"app/api/routes/surprise.py"})


def test_gate_fails_on_stale_route_classification(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(inventory.UNREGISTERED_ROUTE_MODULES, "app/api/routes/ghost.py", "gone")
    monkeypatch.setitem(inventory.UNREGISTERED_ROUTE_MODULES, "app/api/routes/ask.py", "registered")
    assert inventory.stale_route_classifications() == frozenset(
        {"app/api/routes/ghost.py", "app/api/routes/ask.py"}
    )
