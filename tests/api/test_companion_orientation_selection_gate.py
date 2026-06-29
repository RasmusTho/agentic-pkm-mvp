"""Orientation endpoint selection gate (#2653).

The ``/api/companion/orientation`` entry projection must apply the
``status == "selected"`` selection gate the write boundary already uses: with a
configured ``VAULT_ROOT`` but nothing *selected* (``status != "selected"`` /
``active_vault_id is null`` — including a selected-but-``uninitialized`` bare
directory), orientation must return the ``vault_selection_required`` picker
state (200), never a ``VAULT_ROOT``-derived orientation that the UI maps to
``cold_start`` (the #2309 Option-2 split-brain on the entry path).

Reconciliation with #2312: an ``uninitialized`` selected directory stays
*readable* on the content surfaces (note read, vault-browser enumeration); only
the orientation/entry *projection* — whose ``cold_start`` claim
``SYSTEM_ENTRY_POINT_SPEC.md`` gates on a **bound/selected** vault — requires
``selected``. A genuinely selected (initialized) vault still resolves to a real
orientation, so the ``cold_start`` path for a selected vault is preserved.

Shape mirrors ``tests/api/test_companion_no_vault_routing.py``: in-process
``TestClient(app)`` with the global ``get_vault_manager`` monkeypatched to a
``VaultManager`` backed by a tmp app-local store.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.api.routes.companion as companion_module
from app.api.app import app
from app.vault.app_local import AppLocalSettingsStore
from app.vault.manager import VaultManager


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def _wire_manager(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, vault_root: Path
) -> VaultManager:
    monkeypatch.setenv("VAULT_ROOT", str(vault_root))
    monkeypatch.delenv("VAULT_ROOT_DEV", raising=False)
    monkeypatch.delenv("VAULT_ROOT_TEST", raising=False)
    app_local_path = tmp_path / "app-local.md"
    monkeypatch.setenv("DESIGN_HANDOFF_APP_LOCAL_SETTINGS", str(app_local_path))
    mgr = VaultManager(app_local_store=AppLocalSettingsStore(app_local_path))
    monkeypatch.setattr(companion_module, "get_vault_manager", lambda: mgr)
    if hasattr(mgr, companion_module._LAST_ACTIVE_LOAD_ATTEMPTED_ATTR):
        delattr(mgr, companion_module._LAST_ACTIVE_LOAD_ATTEMPTED_ATTR)
    return mgr


def test_orientation_unselected_does_not_resolve_vault_root(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """VAULT_ROOT set + selected-but-uninitialized vault → picker, not orientation.

    This is the #2653 repro: ``GET /api/companion/vault/context`` reports
    ``status: "uninitialized"`` / ``active_vault_id: null`` while
    ``GET /api/companion/orientation`` USED to return a ``VAULT_ROOT``-derived
    ``scope.vault_id`` with ``leave_point.status: absent`` (which the page maps
    to ``data-entry-state="cold_start"``). The orientation entry projection must
    instead route to the ``vault_selection_required`` picker, NOT resolve the
    configured root as the active vault.
    """
    vault_root = tmp_path / "Niflheim"
    (vault_root / "notes").mkdir(parents=True, exist_ok=True)
    (vault_root / "notes" / "a.md").write_text("# A\n\nbody\n", encoding="utf-8")
    mgr = _wire_manager(tmp_path, monkeypatch, vault_root)
    # Select the bare directory → ``uninitialized`` (no Design-Handoff settings):
    # readable, but not a *selected* (bound) vault. ``active_vault_id`` is null.
    mgr.select_vault(vault_root, remember=False)
    assert mgr.context.status == "uninitialized"
    assert mgr.context.active_vault_id is None

    # Precondition mirror: vault/context reports the uninitialized residual state.
    ctx = client.get("/api/companion/vault/context")
    assert ctx.status_code == 200, ctx.text
    ctx_body = ctx.json()
    assert ctx_body["status"] == "uninitialized"
    assert ctx_body.get("active_vault_id") is None

    resp = client.get("/api/companion/orientation")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    # The orientation path routes to the picker — it does NOT resolve VAULT_ROOT
    # into an orientation frame.
    assert body["state"] == "vault_selection_required"
    # No VAULT_ROOT-derived orientation scope/leave_point leaked through.
    assert "scope" not in body
    assert "leave_point" not in body
    # The configured-but-unselected root is offered to the picker, not read.
    assert body.get("configured_vault_root") == str(vault_root)


def test_orientation_no_vault_bound_routes_to_picker(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """VAULT_ROOT set + nothing selected (``status: none``) → no_vault picker.

    The already-correct branch (#2309): with a configured root but no selection
    at all, orientation returns the ``no_vault_bound`` picker and never reads the
    configured root. Pinned here so the gate covers both non-selected statuses.
    """
    vault_root = tmp_path / "Niflheim"
    (vault_root / "notes").mkdir(parents=True, exist_ok=True)
    _wire_manager(tmp_path, monkeypatch, vault_root)

    resp = client.get("/api/companion/orientation")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["state"] == "vault_selection_required"
    assert body["reason"] == "no_vault_bound"
    assert body.get("configured_vault_root") == str(vault_root)


def test_orientation_selected_initialized_vault_resolves_orientation(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A *selected* (initialized) vault still resolves a real orientation.

    The selection gate must not over-fire: an initialized vault is
    ``status == "selected"`` with a real ``active_vault_id`` and must yield the
    orientation frame (with ``scope``), NOT the picker — so the legitimate
    selected-vault ``cold_start`` path (absent leave point) is preserved (#2453).
    """
    vault_root = tmp_path / "Niflheim"
    vault_root.mkdir(parents=True, exist_ok=True)
    mgr = _wire_manager(tmp_path, monkeypatch, vault_root)
    mgr.initialize_vault(vault_root, vault_name="Niflheim", remember=False)
    assert mgr.context.status == "selected"
    assert mgr.context.active_vault_id is not None

    resp = client.get("/api/companion/orientation")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    # A real orientation frame, not the picker.
    assert body.get("state") != "vault_selection_required"
    assert "scope" in body
    assert body["scope"]["vault_id"]
