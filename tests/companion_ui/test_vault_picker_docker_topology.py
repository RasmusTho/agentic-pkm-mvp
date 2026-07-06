"""Vault-picker reachability in the documented docker-compose topology (#3102).

In the shipped ``docker compose`` deployment the browser never talks to the
FastAPI runtime directly: it talks to the ``companion-ui`` container, which
relays over the Docker bridge network to the ``api`` container. Neither hop is
loopback, so the loopback/API-key-gated vault-selection routes 401'd on every
onboarding action (browse / select / initialize) — the picker was unreachable.

The fix trusts the Companion UI container's *own server-side proxy call* by
construction: the runtime resolves the configured companion-ui proxy host(s)
(``settings.companion_ui_proxy_hosts``) and authorises a request whose immediate
peer is that container, without laundering the forwarded browser address into
loopback. The #2706 hardening (an untrusted non-loopback caller — including an
unrelated bridge peer — cannot spoof loopback via ``X-Forwarded-For``) is
preserved; those regressions live in ``tests/api``.

AC1/AC2 exercise the real FastAPI routes through a simulated container peer.
AC3 asserts the front-door picker surfaces a visible, human-readable error when
a selection still fails, instead of a console-only 401 and a silent reset.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import app.api.routes.companion as companion_module
import app.auth as auth_module
from app.api.app import app
from app.vault.app_local import AppLocalSettingsStore
from app.vault.manager import VaultManager
from companion_ui.workspace.serve_dev_page import handle_get

# The companion-ui container's bridge address as the api sees it (the immediate
# peer of the proxied call). Configured as the trusted proxy host below.
COMPANION_UI_PROXY_IP = "172.19.0.7"
# The browser's address as forwarded by the companion-ui container: the Docker
# gateway (or a LAN client) — always non-loopback in this topology, which is
# exactly why the naive loopback gate + XFF look-through 401'd onboarding.
FORWARDED_BROWSER_IP = "172.19.0.1"


@pytest.fixture(autouse=True)
def reset_auth_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_module.settings, "api_key", None)
    monkeypatch.setattr(auth_module.settings, "companion_trusted_proxy_hosts", "")
    monkeypatch.setattr(auth_module.settings, "companion_ui_proxy_hosts", "")


@pytest.fixture()
def manager(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> VaultManager:
    store_path = tmp_path / "app-local.md"
    mgr = VaultManager(app_local_store=AppLocalSettingsStore(store_path))
    monkeypatch.setattr(companion_module, "get_vault_manager", lambda: mgr)
    return mgr


def _container_proxy_client() -> TestClient:
    """A TestClient whose immediate peer is the companion-ui container."""

    return TestClient(app, client=(COMPANION_UI_PROXY_IP, 50000))


def test_browse_succeeds_through_container_proxy(
    manager: VaultManager,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC1: Browse for a vault folder lists folders instead of 401ing."""

    monkeypatch.setattr(
        auth_module.settings, "companion_ui_proxy_hosts", COMPANION_UI_PROXY_IP
    )
    browse_root = tmp_path / "vaults"
    browse_root.mkdir()
    manager.initialize_vault(
        browse_root / "Niflheim", vault_name="Niflheim", remember=False
    )

    response = _container_proxy_client().get(
        "/api/companion/vault/browse",
        params={"path": str(browse_root)},
        # The companion-ui container forwards the (non-loopback) browser address;
        # the container's own peer identity is what authorises the call.
        headers={"X-Forwarded-For": FORWARDED_BROWSER_IP},
    )

    assert response.status_code == 200
    body = response.json()
    entry_names = {entry["name"] for entry in body.get("entries", [])}
    assert "Niflheim" in entry_names


def test_select_succeeds_through_container_proxy(
    manager: VaultManager,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC2: Selecting a vault reflects ``status: selected`` via vault/context."""

    monkeypatch.setattr(
        auth_module.settings, "companion_ui_proxy_hosts", COMPANION_UI_PROXY_IP
    )
    vault = tmp_path / "vault-a"
    manager.initialize_vault(vault, vault_name="Vault A", remember=True)
    client = _container_proxy_client()

    response = client.post(
        "/api/companion/vault/select",
        json={"path": str(vault), "remember": True},
        headers={"X-Forwarded-For": FORWARDED_BROWSER_IP},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "selected"

    # The backend vault context reflects the selection through the same path.
    context = client.get("/api/companion/vault/context")
    assert context.status_code == 200
    assert context.json()["status"] == "selected"


def test_service_name_resolution_trusts_container(
    manager: VaultManager,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The shipped default: the runtime resolves the `companion-ui` compose
    service name to its bridge address and trusts that immediate peer — the
    zero-config `docker compose up` path (no IP literal, no operator tweak)."""

    monkeypatch.setattr(
        auth_module.settings, "companion_ui_proxy_hosts", "companion-ui"
    )

    def _fake_getaddrinfo(host: str, *args: Any, **kwargs: Any) -> list:
        assert host == "companion-ui"
        return [(2, 1, 6, "", (COMPANION_UI_PROXY_IP, 0))]

    monkeypatch.setattr(auth_module.socket, "getaddrinfo", _fake_getaddrinfo)
    auth_module._proxy_dns_cache.clear()

    vault = tmp_path / "vault-a"
    manager.initialize_vault(vault, vault_name="Vault A", remember=True)

    response = _container_proxy_client().post(
        "/api/companion/vault/select",
        json={"path": str(vault), "remember": True},
        headers={"X-Forwarded-For": FORWARDED_BROWSER_IP},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "selected"


def test_untrusted_bridge_peer_still_rejected(
    manager: VaultManager,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#2706 guard: an unrelated bridge peer is NOT trusted by the #3102 escape
    hatch. Only the configured companion-ui container address is."""

    monkeypatch.setattr(
        auth_module.settings, "companion_ui_proxy_hosts", COMPANION_UI_PROXY_IP
    )
    vault = tmp_path / "vault-a"
    manager.initialize_vault(vault, vault_name="Vault A", remember=True)

    # A different bridge peer forging XFF=loopback must still be rejected.
    response = TestClient(app, client=("172.19.0.99", 50000)).post(
        "/api/companion/vault/select",
        json={"path": str(vault), "remember": True},
        headers={"X-Forwarded-For": "127.0.0.1"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "API key required for non-loopback request"


# --- AC3: visible, human-readable picker error on failed selection ----------

_PICKER_PAYLOAD: dict[str, Any] = {
    "state": "vault_selection_required",
    "reason": "no_vault_bound",
    "message": "No vault is selected. Open the configured vault to continue.",
    "configured_vault_root": "/Users/me/Vaults/Niflheim",
    "requested_note_path": "note.md",
    "context": {"status": "none"},
    "recent_vaults": [],
    "actions": [],
}


class _PickerClient:
    """Fake WorkspaceHttpClient whose every boundary returns the picker payload."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def get(self, url: str, *, params: dict[str, Any]) -> dict[str, Any]:
        return self._payload

    def post(self, url: str, *, json: dict[str, Any]) -> dict[str, Any]:  # pragma: no cover
        return {}


def _select_function_body(html: str) -> str:
    """Extract the ``selectVault`` controller function body from the page JS."""

    start = html.index("function selectVault(")
    # The next top-level function declaration bounds the body.
    end = html.index("function ", start + len("function selectVault("))
    return html[start:end]


def test_failed_selection_shows_visible_error() -> None:
    """AC3: a failed vault selection surfaces a visible error in the picker,
    not just a data-attribute / console-only 401."""

    html = handle_get(
        query_string="note_path=note.md",
        client=_PickerClient(_PICKER_PAYLOAD),
        api_base_url="http://127.0.0.1:18001",
    )

    # The front-door picker renders a dedicated, human-visible error surface,
    # hidden until a selection fails.
    assert 'data-testid="vault-picker-select-error"' in html
    assert re.search(
        r'data-testid="vault-picker-select-error"[^>]*\bhidden\b', html
    ), "picker select-error surface must be hidden by default"

    # The selectVault controller routes a failure into that visible surface
    # (rather than only stamping a data-* attribute on the clicked button).
    select_body = _select_function_body(html)
    assert "showSelectError(" in select_body, (
        "selectVault must surface failures via the visible picker error element"
    )
