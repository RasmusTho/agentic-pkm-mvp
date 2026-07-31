"""Tests for the cockpit page and registry endpoint (#4438)."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.api.app import app
from app.builderops import cockpit_github_plane, cockpit_registry
from app.builderops.cockpit_github_plane import GithubLiveResult

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_registry_endpoint_and_page_served(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DISPATCHER_STATE_DIR", str(tmp_path / "dispatcher"))
    monkeypatch.setenv("COCKPIT_DEPLOY_RECEIPT_DIR", str(tmp_path / "deploys"))
    # Force the live GitHub plane off: an ambient COCKPIT_GITHUB_REPO in the
    # host/CI shell would otherwise make this "unit" test perform a real gh
    # api network call (BOPS-COCKPIT-03, #4450).
    monkeypatch.delenv("COCKPIT_GITHUB_REPO", raising=False)

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


def _github_live_source(payload: dict) -> dict:
    return next(
        source for source in payload["sources"] if source["name"] == "github-live"
    )


def test_configured_repo_reaches_the_live_github_read(tmp_path, monkeypatch) -> None:
    """#4484: a configured slug must survive the real route-to-transport path.

    The assertion is on the production chain — route `_github_repo` ->
    `build_registry` -> `_read_github_live` -> `fetch_github_live` — with only
    the outermost read boundary substituted, so no network is performed. A
    helper called in isolation would not prove the route passes the slug at
    all, which is exactly the defect #4484 fixes.
    """
    monkeypatch.setenv("DISPATCHER_STATE_DIR", str(tmp_path / "dispatcher"))
    monkeypatch.setenv("COCKPIT_DEPLOY_RECEIPT_DIR", str(tmp_path / "deploys"))
    monkeypatch.setenv("COCKPIT_GITHUB_REPO", "RasmusTho/agentic-pkm-mvp")

    seen: list[str | None] = []

    def _record(repo: str | None, **kwargs):
        seen.append(repo)
        return GithubLiveResult(
            snapshot=None,
            state="unavailable",
            last_successful_read=None,
            detail="stubbed read boundary",
        )

    monkeypatch.setattr(cockpit_registry, "fetch_github_live", _record)

    response = TestClient(app).get("/api/cockpit/registry")
    assert response.status_code == 200

    assert seen == ["RasmusTho/agentic-pkm-mvp"], (
        "the /api/cockpit/registry route must reach the live GitHub read with "
        "the configured slug; got: " + repr(seen)
    )
    # The plane was asked for, so its refusal is an outage rather than an
    # opt-out (EXT-8, #4481).
    assert _github_live_source(response.json())["configured"] is True


def test_unset_repo_still_refuses_the_live_plane(tmp_path, monkeypatch) -> None:
    """#4484 must not change the unconfigured path: no repo, no live read."""
    monkeypatch.setenv("DISPATCHER_STATE_DIR", str(tmp_path / "dispatcher"))
    monkeypatch.setenv("COCKPIT_DEPLOY_RECEIPT_DIR", str(tmp_path / "deploys"))
    monkeypatch.delenv("COCKPIT_GITHUB_REPO", raising=False)

    def _must_not_transport(repo: str) -> None:
        raise AssertionError(f"no live read may be attempted for {repo!r}")

    monkeypatch.setattr(
        cockpit_github_plane, "default_github_reader", _must_not_transport
    )

    response = TestClient(app).get("/api/cockpit/registry")
    assert response.status_code == 200

    source = _github_live_source(response.json())
    assert source["state"] == "unavailable"
    assert source["configured"] is False
    assert source["last_successful_read"] is None


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
