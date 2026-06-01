from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.api.app import app


def _source_ref(ref: str = "#1503") -> list[dict[str, str]]:
    return [{"ref_type": "github_issue", "ref": ref, "authority_surface": "github"}]


def _actor(actor_id: str = "api-codex") -> dict[str, str]:
    return {"actor_type": "agent", "id": actor_id}


def test_builderops_api_create_list_read_and_receipts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("BUILDEROPS_DB_PATH", str(tmp_path / "builderops.sqlite3"))
    client = TestClient(app)

    health = client.get("/api/builderops/health")
    assert health.status_code == 200
    assert "create_agent_worklog" in health.json()["autonomous_agent_safe_operations"]
    assert "execute_promotion" in health.json()["requires_human_governance_review"]

    worklog_payload = {
        "summary": "API worklog",
        "body": "Created through the BuilderOps API boundary.",
        "task_context": {"issue": "#1503"},
        "source_refs": _source_ref(),
        "created_by": _actor(),
        "idempotency_key": "api:create-worklog",
    }
    created = client.post("/api/builderops/worklogs", json=worklog_payload)
    assert created.status_code == 200, created.text
    worklog = created.json()["record"]
    assert worklog["object_type"] == "AgentWorklog"
    assert worklog["created_by"] == _actor()
    assert worklog["idempotency_key"] == "api:create-worklog"

    duplicate = client.post("/api/builderops/worklogs", json=worklog_payload)
    assert duplicate.status_code == 200
    assert duplicate.json()["record"] == worklog

    learning = client.post(
        "/api/builderops/learning-signals",
        json={
            "summary": "API learning",
            "content": "The API boundary preserves store validation.",
            "signal_type": "workflow",
            "source_refs": _source_ref(),
            "created_by": _actor(),
            "idempotency_key": "api:create-learning",
        },
    )
    assert learning.status_code == 200, learning.text
    assert learning.json()["record"]["object_type"] == "LearningSignal"

    promotion = client.post(
        "/api/builderops/promotion-intents",
        json={
            "summary": "API promotion intent",
            "target_authority_surface": "github_issue",
            "target_action": "create",
            "target_ref": "pending",
            "target_authority_class": "operational",
            "intended_output": "Draft a follow-up issue.",
            "source_refs": [
                {
                    "ref_type": "builderops_object",
                    "ref": learning.json()["record"]["id"],
                    "authority_surface": "builderops",
                }
            ],
            "created_by": _actor(),
            "idempotency_key": "api:create-promotion",
        },
    )
    assert promotion.status_code == 200, promotion.text
    assert promotion.json()["record"]["object_type"] == "PromotionIntent"

    listed = client.get("/api/builderops/records", params={"type": "AgentWorklog"})
    assert listed.status_code == 200
    assert [record["id"] for record in listed.json()["records"]] == [worklog["id"]]

    promotions = client.get("/api/builderops/records", params={"type": "PromotionIntent"})
    assert promotions.status_code == 200
    assert [record["id"] for record in promotions.json()["records"]] == [
        promotion.json()["record"]["id"]
    ]

    read = client.get(f"/api/builderops/records/{worklog['id']}")
    assert read.status_code == 200
    assert read.json()["record"] == worklog

    receipt = client.post(
        "/api/builderops/receipts",
        json={
            "summary": "API receipt",
            "event_type": "object_created",
            "actor": _actor(),
            "occurred_at": "2026-06-01T00:00:00Z",
            "target_refs": [
                {
                    "ref_type": "builderops_object",
                    "ref": worklog["id"],
                    "authority_surface": "builderops",
                }
            ],
            "action": "create",
            "receipt_body": "Recorded the API worklog creation.",
            "idempotency_key": "api:receipt-worklog",
            "source_refs": _source_ref(),
        },
    )
    assert receipt.status_code == 200, receipt.text
    receipt_record = receipt.json()["record"]
    assert receipt_record["object_type"] == "BuilderOpsReceipt"
    assert receipt_record["actor"] == _actor()
    assert receipt_record["idempotency_key"] == "api:receipt-worklog"

    read_receipt = client.get(f"/api/builderops/records/{receipt_record['id']}")
    assert read_receipt.status_code == 200
    assert read_receipt.json()["record"] == receipt_record


def test_builderops_api_rejects_invalid_object_type(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("BUILDEROPS_DB_PATH", str(tmp_path / "builderops.sqlite3"))
    client = TestClient(app)

    invalid = client.get("/api/builderops/records", params={"type": "InvalidType"})
    assert invalid.status_code == 400
    assert "unsupported object_type" in invalid.json()["detail"]

    missing = client.get("/api/builderops/records/missing-record")
    assert missing.status_code == 404
