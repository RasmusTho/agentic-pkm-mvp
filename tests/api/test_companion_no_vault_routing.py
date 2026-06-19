"""No-vault runtime routing contract (#2184).

Closes the residual no-vault anchors from the 2026-06-18 terminal review-thread
audit (#2148). With no vault selected and ``VAULT_ROOT`` unset, the runtime must
NOT fall through to a CWD-relative ``./vault``; it must route the human to the
vault picker on every companion boundary, idle the watcher on boot, and the
queue-review client must treat the 200 picker payload as a picker route rather
than a staged review.

Three production-path assertions, one per acceptance criterion:

1. Active-vault read boundaries return the ``no_vault_bound`` picker state
   (200) when no vault is bound and ``VAULT_ROOT`` is unset — never a
   silent ``./vault`` default and never a 500
   (``app/api/routes/companion.py`` shared resolution).
2. ``scripts/start_full_system.sh`` forces ``START_WATCHERS=0`` in
   ``NO_VAULT_MODE`` so idle boot does not hang waiting for a watcher heartbeat
   that never arrives, and the heartbeat wait stays gated on ``START_WATCHERS``.
3. The rendered ``vaultBrowserQueueReview`` client branches on
   ``state === 'vault_selection_required'`` and routes to the picker instead of
   marking the action ``pending_intent`` (the queued-review masquerade).

Shape mirrors ``tests/api/test_companion_vault_routing.py``: in-process
``TestClient(app)`` with the global ``get_vault_manager`` monkeypatched to a
``VaultManager`` backed by a tmp app-local store.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.api.routes.companion as companion_module
from app.api.app import app
from app.vault.app_local import AppLocalSettingsStore
from app.vault.manager import VaultManager

_REPO_ROOT = Path(__file__).resolve().parents[2]
_START_FULL_SYSTEM = _REPO_ROOT / "scripts" / "start_full_system.sh"
_SERVE_DEV_PAGE = (
    _REPO_ROOT
    / "companion-ui"
    / "companion-app"
    / "companion_ui"
    / "workspace"
    / "serve_dev_page.py"
)


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture()
def no_vault_manager(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> VaultManager:
    """A fresh no-vault manager wired into the companion routes.

    No ``VAULT_ROOT`` is set, so the optional resolver reports the explicit
    no-vault state. ``DESIGN_HANDOFF_APP_LOCAL_SETTINGS`` is redirected so any
    ``known_vaults`` write lands in tmp, never the real app-local file.
    """
    monkeypatch.delenv("VAULT_ROOT", raising=False)
    monkeypatch.delenv("VAULT_ROOT_DEV", raising=False)
    monkeypatch.delenv("VAULT_ROOT_TEST", raising=False)
    app_local_path = tmp_path / "app-local.md"
    monkeypatch.setenv("DESIGN_HANDOFF_APP_LOCAL_SETTINGS", str(app_local_path))
    mgr = VaultManager(app_local_store=AppLocalSettingsStore(app_local_path))
    monkeypatch.setattr(companion_module, "get_vault_manager", lambda: mgr)
    if hasattr(mgr, companion_module._LAST_ACTIVE_LOAD_ATTEMPTED_ATTR):
        delattr(mgr, companion_module._LAST_ACTIVE_LOAD_ATTEMPTED_ATTR)
    return mgr


# --- AC1: shared no-vault resolution on active-vault read boundaries --------


def _no_vault_picker_endpoints() -> list[tuple[str, str, str, str | None]]:
    """(id, method, url, expected_requested_note_path)."""
    note_path = "notes/x.md"
    return [
        ("orientation", "GET", "/api/companion/orientation", None),
        ("vault_browser", "GET", "/api/companion/vault-browser", None),
        ("vault_link_index", "GET", "/api/companion/vault-link-index", None),
        (
            "vault_related",
            "GET",
            f"/api/companion/vault-related?note_path={note_path}",
            note_path,
        ),
        ("vault_notes", "GET", "/api/companion/vault/notes", None),
        (
            "workspace",
            "GET",
            f"/api/companion/workspace?note_path={note_path}",
            note_path,
        ),
    ]


@pytest.mark.parametrize(
    "method, url, expected_requested_note_path",
    [case[1:] for case in _no_vault_picker_endpoints()],
    ids=[case[0] for case in _no_vault_picker_endpoints()],
)
def test_unset_vault_root_routes_to_no_vault_picker(
    client: TestClient,
    no_vault_manager: VaultManager,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    url: str,
    expected_requested_note_path: str | None,
) -> None:
    """Unset VAULT_ROOT + no selection -> the no_vault_bound picker state (200).

    A CWD ``./vault`` directory must NOT be picked up implicitly: the response
    is the picker, with ``configured_vault_root`` null, never a 500 and never an
    empty default note list.
    """
    # Materialize a ./vault under the cwd to prove it is NOT silently adopted.
    monkeypatch.chdir(tmp_path)
    cwd_vault = tmp_path / "vault" / "notes"
    cwd_vault.mkdir(parents=True, exist_ok=True)
    (cwd_vault / "leaked.md").write_text("# Leaked\n\nbody\n", encoding="utf-8")

    resp = client.request(method, url)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["state"] == "vault_selection_required"
    assert body["reason"] == "no_vault_bound"
    assert body["configured_vault_root"] is None
    # The endpoint did not resolve a default ./vault note list / workspace.
    assert "notes" not in body
    assert "artifact" not in body
    if expected_requested_note_path is not None:
        assert body["requested_note_path"] == expected_requested_note_path


def test_unset_vault_root_does_not_leak_cwd_vault_notes(
    client: TestClient,
    no_vault_manager: VaultManager,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """/vault/notes must never surface a CWD ./vault note when no vault is bound."""
    monkeypatch.chdir(tmp_path)
    cwd_vault = tmp_path / "vault" / "notes"
    cwd_vault.mkdir(parents=True, exist_ok=True)
    (cwd_vault / "leaked.md").write_text("# Leaked\n\nbody\n", encoding="utf-8")

    resp = client.get("/api/companion/vault/notes")

    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "vault_selection_required"
    assert "leaked.md" not in resp.text


# --- AC2: watcher idled in no-vault boot (start_full_system.sh) --------------


def test_start_full_system_forces_watcher_off_in_no_vault_mode() -> None:
    """No-vault idle boot must force START_WATCHERS=0 so it does not hang.

    The watcher heartbeat wait (and the watcher bring-up) are gated on
    START_WATCHERS=1; in NO_VAULT_MODE the script must set START_WATCHERS=0
    inside the no-vault branch, after the runtime default has been decided.
    """
    script = _START_FULL_SYSTEM.read_text(encoding="utf-8")

    # The no-vault branch (NO_VAULT_MODE -eq 1) forces the watcher off.
    no_vault_branch = re.search(
        r'if \[ "\$NO_VAULT_MODE" -eq 1 \]; then(.*?)\nelse',
        script,
        re.S,
    )
    assert no_vault_branch is not None, "no-vault branch not found"
    assert "START_WATCHERS=0" in no_vault_branch.group(1), (
        "no-vault mode must force START_WATCHERS=0 to avoid the watcher "
        "heartbeat-wait hang"
    )

    # The watcher heartbeat wait remains gated on START_WATCHERS so the forced-off
    # value actually skips it.
    assert 'if [ "$START_WATCHERS" -eq 1 ]; then' in script
    assert "watcher heartbeat not detected" in script


# --- AC3: queue-review client routes the 200 picker payload to the picker ----


def test_queue_review_client_routes_picker_payload_to_picker() -> None:
    """The rendered queue-review client must branch on the picker state.

    A 200 ``vault_selection_required`` payload is the no-vault / missing-vault
    picker state, not a staged review. The client must route to the vault picker
    instead of marking the action ``pending_intent`` (the masquerade fixed by
    #2184).
    """
    import sys

    companion_app_root = (
        _REPO_ROOT / "companion-ui" / "companion-app"
    )
    if str(companion_app_root) not in sys.path:
        sys.path.insert(0, str(companion_app_root))
    from companion_ui.workspace.serve_dev_page import render_index_html

    html = render_index_html(
        api_base_url="http://127.0.0.1:18000",
        note_path="notes/a.md",
        fields={
            "note_path": "notes/a.md",
            "title": "A",
            "body": "body",
            "raw_body": "body",
        },
    )

    assert "function vaultBrowserQueueReview" in html
    # The picker branch exists and routes to the picker (page reload re-resolves
    # the no-vault entry state and surfaces the picker).
    assert "result.data.state === 'vault_selection_required'" in html
    picker_branch = html[html.index("function vaultBrowserQueueReview"):]
    picker_branch = picker_branch[
        : picker_branch.index("window.location.reload();") + len("window.location.reload();")
    ]
    assert "vault_selection_required" in picker_branch
    assert "window.location.reload();" in picker_branch
    # The picker branch must precede / not fall through to the pending_intent
    # success marking for the picker payload.
    reload_idx = html.index("window.location.reload();")
    # The first pending_intent affordance assignment after the reload guard is
    # only reached when the payload is a real staged review.
    pending_idx = html.index(
        "action.setAttribute('data-affordance-status', 'pending_intent');"
    )
    assert reload_idx < pending_idx
