"""Tests for the cockpit page and registry endpoint (#4438)."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.api.app import app

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_registry_endpoint_and_page_served(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DISPATCHER_STATE_DIR", str(tmp_path / "dispatcher"))
    monkeypatch.setenv("COCKPIT_DEPLOY_RECEIPT_DIR", str(tmp_path / "deploys"))

    client = TestClient(app)

    response = client.get("/api/cockpit/registry")
    assert response.status_code == 200
    payload = response.json()
    assert payload["authority"] == "read_time_join"
    # No dispatcher store exists in this environment: the claim must be a
    # refusal, and the read must not have fabricated a database.
    assert payload["claim"]["kind"] == "refused"
    assert not (tmp_path / "dispatcher").exists()

    page = client.get("/cockpit")
    assert page.status_code == 200
    assert "Cockpit" in page.text
    assert "/static/cockpit.js" in page.text


def test_token_sheet_parity_with_binding_source() -> None:
    served = (REPO_ROOT / "app/web/static/colors_and_type.css").read_bytes()
    binding = (
        REPO_ROOT / "companion-ui/companion-app/colors_and_type.css"
    ).read_bytes()
    assert served == binding, (
        "app/web/static/colors_and_type.css must stay byte-identical to the"
        " binding token source companion-ui/companion-app/colors_and_type.css"
        " (Yggdrasil token parity; see docs/BUILDEROPS_COCKPIT/README.md)"
    )
