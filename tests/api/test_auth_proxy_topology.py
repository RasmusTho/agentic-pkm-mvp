"""Trusted-proxy topology regression tests for companion auth (#2697)."""

from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

import app.auth as auth_module
from app.auth import require_loopback_or_api_key


@pytest.fixture(autouse=True)
def reset_auth_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_module.settings, "api_key", None)
    monkeypatch.setattr(auth_module.settings, "companion_trusted_proxy_hosts", "")


@pytest.fixture()
def guarded_app() -> FastAPI:
    api = FastAPI()

    @api.post("/guarded", dependencies=[Depends(require_loopback_or_api_key)])
    def guarded() -> dict[str, bool]:
        return {"ok": True}

    return api


def _client_from(app: FastAPI, host: str) -> TestClient:
    return TestClient(app, client=(host, 50000))


def test_loopback_local_proxy_xff_is_trusted(guarded_app: FastAPI) -> None:
    response = _client_from(guarded_app, "127.0.0.1").post(
        "/guarded",
        headers={"X-Forwarded-For": "127.0.0.1, 172.18.0.5"},
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_untrusted_non_loopback_caller_rejected_even_with_xff(
    guarded_app: FastAPI,
) -> None:
    response = _client_from(guarded_app, "203.0.113.10").post(
        "/guarded",
        headers={"X-Forwarded-For": "127.0.0.1"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "API key required for non-loopback request"
