"""A UI-initialized vault must be capture-ready immediately (#3120).

Playwright verification of #3102 (2026-07-06/07) found a real onboarding dead
end: initializing a brand-new vault entirely through the Companion UI's
"Initialize a vault here" action (``POST /api/companion/vault/initialize``)
left ``vault.layout.md`` unwritten, so the very first quick-capture attempt
failed with a correctly-surfaced but blocking error — "The vault inbox note
convention could not be resolved; nothing was written." — until an operator
ran ``python -m app.cli vault-layout-ensure --vault-root <path>`` by hand. A
browser-only new user has no way to run that CLI command.

This suite drives the exact two-step user path end-to-end through the real
HTTP surface — ``POST /vault/initialize`` then ``POST /capture`` — with the
autouse ``default_vault_layout_env`` env defaults cleared, so it reproduces
the true init-only state instead of the env override masking the gap (mirrors
``tests/relevance/test_relevance_tick_initialized_vault.py``'s
``clear_layout_env`` pattern).

Shape mirrors ``tests/api/test_vault_initialize_from_picker.py`` and
``tests/api/test_no_silent_cwd_vault_fallback.py``: in-process
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

# Layout-folder env vars the autouse ``default_vault_layout_env`` fixture
# (tests/conftest.py) injects when unset. Clearing them is what makes this
# test exercise the real init-only vault state instead of the fixture's
# explicit defaults masking the missing layout note (same rationale as
# tests/relevance/test_relevance_tick_initialized_vault.py::clear_layout_env).
_LAYOUT_ENV_VARS = (
    "VAULT_SYSTEM_DIR_REL",
    "VAULT_INBOX_DIR_REL",
    "VAULT_DESK_DIR_REL",
    "VAULT_RUNTIME_DIR_REL",
    "VAULT_LAYOUT_NOTE_REL",
    "VAULT_CAPTURE_NOTE_REL",
)


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture()
def manager_no_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> VaultManager:
    """Fresh no-vault manager wired into the companion routes, layout env cleared."""
    monkeypatch.delenv("VAULT_ROOT", raising=False)
    monkeypatch.delenv("VAULT_ROOT_DEV", raising=False)
    monkeypatch.delenv("VAULT_ROOT_TEST", raising=False)
    for name in _LAYOUT_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    app_local_path = tmp_path / ".app-local.md"
    monkeypatch.setenv("DESIGN_HANDOFF_APP_LOCAL_SETTINGS", str(app_local_path))
    mgr = VaultManager(app_local_store=AppLocalSettingsStore(app_local_path))
    monkeypatch.setattr(companion_module, "get_vault_manager", lambda: mgr)
    if hasattr(mgr, companion_module._LAST_ACTIVE_LOAD_ATTEMPTED_ATTR):
        delattr(mgr, companion_module._LAST_ACTIVE_LOAD_ATTEMPTED_ATTR)
    return mgr


def test_initialize_then_capture_succeeds(
    client: TestClient,
    manager_no_vault: VaultManager,
    tmp_path: Path,
) -> None:
    """UI-driven initialize, then an immediate quick-capture, must succeed.

    No manual ``vault-layout-ensure`` CLI step, no ``VAULT_INBOX_DIR_REL``
    override — exactly the browser-only new-user path.
    """
    new_vault = tmp_path / "MyNewVault"
    assert not new_vault.exists()

    init_resp = client.post(
        "/api/companion/vault/initialize",
        json={"path": str(new_vault), "vault_name": "My New Vault"},
    )
    assert init_resp.status_code == 200, init_resp.text
    assert init_resp.json()["context"]["status"] == "selected"

    # The layout note must exist post-init (capture-ready immediately) — the
    # regression symptom was precisely its absence at this point.
    layout_candidates = list(new_vault.rglob("vault.layout.md"))
    assert layout_candidates, "vault.layout.md must exist immediately after UI initialize"

    capture_resp = client.post(
        "/api/companion/capture", json={"text": "first capture after UI init"}
    )
    assert capture_resp.status_code == 200, capture_resp.text
    body = capture_resp.json()
    assert body.get("error") is None, body
    # The write actually landed in the resolved inbox note, not just a 200 shell.
    from app.vault.paths import get_vault_inbox_dir_rel

    inbox_rel = get_vault_inbox_dir_rel(new_vault)
    inbox_note = new_vault / inbox_rel / "inbox.md"
    assert inbox_note.exists(), f"expected inbox note at {inbox_note}"
    assert "first capture after UI init" in inbox_note.read_text(encoding="utf-8")


def test_layout_ensure_is_idempotent_across_reinitialize(
    client: TestClient,
    manager_no_vault: VaultManager,
    tmp_path: Path,
) -> None:
    """Re-initializing (no-op path) must not rewrite or duplicate the layout note."""
    vault = tmp_path / "ReinitVault"

    first = client.post(
        "/api/companion/vault/initialize",
        json={"path": str(vault), "vault_name": "Reinit Vault"},
    )
    assert first.status_code == 200, first.text
    layout_paths = list(vault.rglob("vault.layout.md"))
    assert len(layout_paths) == 1
    original_content = layout_paths[0].read_text(encoding="utf-8")

    # The vault folder is non-empty after the first init (settings/ + layout
    # folders now exist), so the #2518 non-empty-target guard requires an
    # explicit confirm on the second call — unrelated to the layout-ensure
    # idempotency this test targets.
    second = client.post(
        "/api/companion/vault/initialize",
        json={"path": str(vault), "vault_name": "Reinit Vault", "confirm": True},
    )
    assert second.status_code == 200, second.text
    layout_paths_after = list(vault.rglob("vault.layout.md"))
    assert len(layout_paths_after) == 1, "re-initialize must not create a second layout note"
    assert layout_paths_after[0].read_text(encoding="utf-8") == original_content
