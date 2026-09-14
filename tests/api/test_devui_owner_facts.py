"""Production DevUI readers consume authenticated source outcome readback."""

from __future__ import annotations

import copy
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.api.routes import devui
from app.builderops.control_plane.client import BuilderOpsControlPlaneClient
from app.builderops.devui_focus_inputs import read_focus_inputs
from app.builderops.control_plane import service as control_service
from app.builderops import devui_sources
from tests.builderops import inquiry_operation_fixture
from tests.builderops.control_plane.conftest import control_plane_store  # noqa: F401
from tests.builderops.test_owner_fact_producers import REPO, SUBJECT, owner_writer  # noqa: F401
from tests.builderops.test_devui_overview import _composition

pytestmark = pytest.mark.pg


def test_production_reads_use_source_facts_without_label_or_model_inference(owner_writer, monkeypatch):  # noqa: F811
    w = owner_writer
    trial = w.submit(w.request(), "trial").json()["receipt"]["id"]
    accepted = w.submit(w.request("owner_acceptance", "accepted", trial_receipt_ref=trial), "acceptance").json()["receipt"]
    original_init = BuilderOpsControlPlaneClient.__init__
    def local_transport(self, config, **kwargs):
        original_init(self, config, http_client=w.client, max_retries=0)
    monkeypatch.setattr(BuilderOpsControlPlaneClient, "__init__", local_transport)
    monkeypatch.setenv("BUILDEROPS_API_URL", "http://testserver")
    monkeypatch.setenv("BUILDEROPS_API_TOKEN", "owner-test-only-key")
    monkeypatch.setenv("DEVUI_REPOSITORY", REPO)
    monkeypatch.setenv("DEVUI_BUILDEROPS_AUTHORITY_EPOCH", "1")
    monkeypatch.setattr(devui, "compose_owner_snapshot", lambda **kwargs: copy.deepcopy(_composition()))
    response = TestClient(app).get("/api/devui/overview")
    assert response.status_code == 200, response.text
    assert accepted["hash"] in response.text
    assert '"outcome":"accepted"' in response.text
    assert "owner_trial" in response.text
    issue = {"number": 5404, "title": "Source subject", "body": "## Context\nDeclared only.\n\n## Acceptance Criteria\n- [ ] Exact source only. Verify: owner source\n",
             "state": "open", "updated_at": w.binding()["observed_at"],
             "html_url": "https://github.com/example/fixture/issues/5404",
             "labels": [{"name": "agent:needs-human"}]}
    monkeypatch.setattr(devui, "read_focus_inputs", lambda subject: read_focus_inputs(subject, repository=REPO, issue_reader=lambda repo, number: issue))
    focus = TestClient(app).get("/api/devui/focus", params={"subject": SUBJECT})
    assert focus.status_code == 200, focus.text
    assert accepted["hash"] in focus.text
    assert "Owner decision: accepted" in focus.text
    assert focus.json()["next_legal_step"]["legality"] == "unavailable"
    # Publish a real source-validated inquiry ask through the existing action
    # boundary. The finite graph fakes only host/provider I/O; no inquiry starts.
    monkeypatch.setattr(inquiry_operation_fixture, "REPOSITORY", REPO)
    graph_root = w.root / "ask-graph"
    graph_root.mkdir()
    graph = inquiry_operation_fixture.InquiryGraph(graph_root, monkeypatch)
    graph.store = w.store
    graph.credentials["credentials"][0]["scopes"].extend(["records:write", "receipts:read"])
    graph.credentials["credentials"].append({**w.credentials[0], "id": "outcome-owner"})
    graph.write_credentials()
    graph.http = TestClient(control_service.production_app())
    monkeypatch.setenv("DEVUI_GITHUB_ENABLED", "true")
    monkeypatch.setenv("GH_CONFIG_DIR", str(graph_root))
    monkeypatch.setattr(devui_sources.cockpit_github_plane, "_run_gh", lambda args: copy.deepcopy(issue))
    preview = graph.preview(issue=issue)
    published = graph.http.post("/v1/records", headers={**graph.headers(), "X-BuilderOps-Authority-Epoch": "1"},
        json={"record_type": "BuilderOpsReceipt", "owner_ask": {"proposal": preview["proposal"], "material": preview["material"]}})
    assert published.status_code == 200, published.text
    assert published.json()["action_effects"] == [] and graph.launches == 0
    monkeypatch.setattr(BuilderOpsControlPlaneClient, "__init__", lambda self, config, **kwargs: original_init(self, config, http_client=graph.http, max_retries=0))
    monkeypatch.setenv("BUILDEROPS_API_TOKEN", "owner-fixture")
    asks = TestClient(app).get("/api/devui/overview")
    assert asks.status_code == 200 and len(asks.json()["needs_you"]) == 1, asks.text
    assert preview["proposal"]["proposal_hash"] in asks.text
    assert "Canonical owner ask: Start or Hold" in asks.text
    config = devui_sources.load_source_configuration({"DEVUI_REPOSITORY": REPO, "DEVUI_GITHUB_ENABLED": "true", "GH_CONFIG_DIR": str(graph_root),
        "BUILDEROPS_API_URL": "http://127.0.0.1:8131", "BUILDEROPS_API_TOKEN": "owner-fixture", "DEVUI_BUILDEROPS_AUTHORITY_EPOCH": "1"},
        candidate_root=graph_root / "candidate", source_sha="1" * 40)
    managed = devui_sources.read_managed_focus(config, SUBJECT)
    assert any("Canonical owner ask" in row["claim"] for row in managed["evidence"])
    assert any(accepted["hash"] == row["source_ref"]["version"] for row in managed["evidence"])
    issue["updated_at"] = datetime.now(timezone.utc).isoformat()
    stale_ask = TestClient(app).get("/api/devui/overview")
    assert stale_ask.json()["needs_you"] == []
    assert '"outcome":"accepted"' in stale_ask.text
    assert graph.launches == 0
    w.profile["version"] = "2"
    w.write_sources()
    changed = TestClient(app).get("/api/devui/overview")
    assert '"outcome":"accepted"' not in changed.text
    (w.root / "devui-runtime-prerequisites.json").unlink()
    unavailable = TestClient(app).get("/api/devui/focus", params={"subject": SUBJECT})
    assert unavailable.status_code == 200
    assert "owner_facts_unavailable" in unavailable.text
    assert "Owner decision: accepted" not in unavailable.text
    unavailable_overview = TestClient(app).get("/api/devui/overview")
    assert unavailable_overview.status_code == 200
    assert "owner_facts_source_unavailable" in unavailable_overview.text
