"""Vault initialize-from-picker flow contract (#2312).

Wire test for the "initialize a new folder as a vault from the picker"
acceptance path. Tests that:

1. A human can initialize a brand-new empty folder via
   ``POST /api/companion/vault/initialize`` and land in ``selected``.
2. Scaffolding placement (Option A): the initialization writes
   ``settings/*`` into the vault folder itself (the explicit, human-chosen
   folder, not a sidecar). This is the intended behavior for a folder the
   human is deliberately creating *as* a vault.
3. The init endpoint does NOT write into any folder the human has not
   explicitly targeted: selecting an existing folder via
   ``POST /api/companion/vault/select`` leaves the folder untouched.

Acceptance Criteria from #2312:
- AC1: ``tests/api/test_vault_initialize_from_picker.py::test_initialize_new_folder_selects_it``
- AC2: behavior test for the scaffolding placement decision (Option A).

Shape mirrors ``tests/api/test_companion_vault_routing.py``: in-process
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
from app.vault.manager import REQUIRED_SETTINGS_FILES, SETTINGS_DIR_NAME, VaultManager


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture()
def manager_no_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> VaultManager:
    """Fresh no-vault manager wired into the companion routes.

    No VAULT_ROOT is set. DESIGN_HANDOFF_APP_LOCAL_SETTINGS is redirected so
    any known_vaults write lands in tmp, never the real app-local file.
    """
    monkeypatch.delenv("VAULT_ROOT", raising=False)
    monkeypatch.delenv("VAULT_ROOT_DEV", raising=False)
    monkeypatch.delenv("VAULT_ROOT_TEST", raising=False)
    app_local_path = tmp_path / ".app-local.md"
    monkeypatch.setenv("DESIGN_HANDOFF_APP_LOCAL_SETTINGS", str(app_local_path))
    mgr = VaultManager(app_local_store=AppLocalSettingsStore(app_local_path))
    monkeypatch.setattr(companion_module, "get_vault_manager", lambda: mgr)
    if hasattr(mgr, companion_module._LAST_ACTIVE_LOAD_ATTEMPTED_ATTR):
        delattr(mgr, companion_module._LAST_ACTIVE_LOAD_ATTEMPTED_ATTR)
    return mgr


# ---------------------------------------------------------------------------
# AC1: initialize a brand-new folder and land in ``selected``
# ---------------------------------------------------------------------------


def test_initialize_new_folder_selects_it(
    client: TestClient,
    manager_no_vault: VaultManager,
    tmp_path: Path,
) -> None:
    """POST /vault/initialize on a brand-new folder resolves to ``selected``.

    The picker offers "Initialize" for a bare/empty folder (status ``none``
    or ``uninitialized``). After initialization the vault context must be
    ``selected`` — not ``uninitialized``. The human can then proceed with
    writes without a separate selection step.
    """
    new_vault = tmp_path / "MyNewVault"
    # The folder does not exist yet — initialize must create it.
    assert not new_vault.exists()

    resp = client.post(
        "/api/companion/vault/initialize",
        json={"path": str(new_vault), "vault_name": "My New Vault"},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()

    # The returned context must be ``selected`` — not ``uninitialized``.
    assert body["context"]["status"] == "selected", (
        f"Expected 'selected' after initialize, got {body['context']['status']!r}. "
        f"Full response: {body}"
    )
    assert body["context"]["active_vault_path"] == str(new_vault)
    assert body["context"]["active_vault_name"] == "My New Vault"
    # At least one file was created (scaffolding was written).
    assert body["created_files"], "Expected scaffolding files to be created"
    # The in-process manager context must also reflect ``selected``.
    assert manager_no_vault.context.status == "selected"
    assert manager_no_vault.context.active_vault_path == str(new_vault)


def test_initialize_new_folder_creates_and_then_selects(
    client: TestClient,
    manager_no_vault: VaultManager,
    tmp_path: Path,
) -> None:
    """Initialize a folder that exists but is bare — must create scaffolding and select.

    Tests the "existing bare folder" path: the folder exists but has no
    Design Handoff settings (status ``uninitialized``). After initialization
    it must be ``selected``.
    """
    bare_vault = tmp_path / "BareVault"
    bare_vault.mkdir(parents=True, exist_ok=True)
    # Bare folder: no settings dir.
    assert not (bare_vault / SETTINGS_DIR_NAME).exists()

    resp = client.post(
        "/api/companion/vault/initialize",
        json={"path": str(bare_vault)},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["context"]["status"] == "selected", body
    # The vault folder now has the settings directory.
    assert (bare_vault / SETTINGS_DIR_NAME).is_dir()
    for fname in REQUIRED_SETTINGS_FILES:
        assert (bare_vault / SETTINGS_DIR_NAME / fname).is_file(), (
            f"Expected scaffolding file {fname} to exist after initialize"
        )


# ---------------------------------------------------------------------------
# AC2: scaffolding placement decision — Option A (into the vault folder)
# ---------------------------------------------------------------------------


def test_scaffolding_written_into_vault_folder_not_sidecar(
    client: TestClient,
    manager_no_vault: VaultManager,
    tmp_path: Path,
) -> None:
    """Option A: scaffolding lands inside the vault folder, not a sidecar.

    The Design Handoff settings (settings/vault.md, settings/local.md, etc.)
    are vault-identity manifests intended to be seen, committed, and shared
    with the vault. Writing them into the vault folder is the explicit,
    understood choice the human makes when they click "Initialize" — they
    are not hidden system state injected silently.

    This test documents and verifies the placement decision: Option A.
    """
    new_vault = tmp_path / "ScaffoldingTest"
    resp = client.post(
        "/api/companion/vault/initialize",
        json={"path": str(new_vault), "vault_name": "Scaffolding Test"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["context"]["status"] == "selected"

    # Every reported created_file must be inside the vault folder. Reject
    # absolute paths and parent-relative ('..') escapes *before* the
    # containment check: ``Path.is_relative_to`` is purely lexical, so an
    # unresolved ``<vault>/../sidecar/...`` would otherwise satisfy it while
    # the resolved file lives outside the vault (a silent sidecar regression).
    new_vault_resolved = new_vault.resolve()
    for rel_path in body["created_files"]:
        candidate = Path(rel_path)
        assert not candidate.is_absolute(), (
            f"created_file {rel_path!r} is an absolute path, not vault-relative"
        )
        assert ".." not in candidate.parts, (
            f"created_file {rel_path!r} contains a parent-relative '..' segment"
        )
        absolute = (new_vault / candidate).resolve()
        assert absolute.is_file(), (
            f"Scaffolding file {rel_path!r} was reported but does not exist at {absolute}"
        )
        # Must not be a sidecar outside the vault folder (resolved, not lexical).
        assert absolute.is_relative_to(new_vault_resolved), (
            f"Scaffolding file {absolute} is not inside the vault folder {new_vault_resolved}"
        )

    # The settings dir is inside the vault folder (not in a sidecar location).
    settings_dir = new_vault / SETTINGS_DIR_NAME
    assert settings_dir.is_dir(), "settings/ directory must be inside the vault folder"
    assert body["context"]["settings_path"] == str(settings_dir)


def test_select_existing_folder_does_not_write_scaffolding(
    client: TestClient,
    manager_no_vault: VaultManager,
    tmp_path: Path,
) -> None:
    """Selecting an existing folder via /vault/select does NOT write scaffolding.

    The constraint: must not write into a human's personal vault without an
    explicit, understood choice. The ``/vault/select`` endpoint is read-only
    selection — it never writes scaffolding. Only ``/vault/initialize``
    writes. A human's existing Obsidian vault must be openable/browsable
    without system files being injected.
    """
    existing_vault = tmp_path / "PersonalVault"
    (existing_vault / "notes").mkdir(parents=True, exist_ok=True)
    (existing_vault / "notes" / "my-note.md").write_text(
        "# My Note\n\nPersonal content\n", encoding="utf-8"
    )
    original_entries = set(existing_vault.rglob("*"))

    resp = client.post(
        "/api/companion/vault/select",
        json={"path": str(existing_vault), "remember": False},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Selecting a bare existing folder resolves to ``uninitialized``, not
    # ``selected`` (no scaffolding written, no Design Handoff settings found).
    assert body["status"] == "uninitialized", (
        f"Expected 'uninitialized' for a bare existing folder, got {body['status']!r}"
    )
    # No new files were written — folder contents are unchanged.
    current_entries = set(existing_vault.rglob("*"))
    assert current_entries == original_entries, (
        f"select_vault wrote new files into an existing folder: "
        f"added={current_entries - original_entries}"
    )
