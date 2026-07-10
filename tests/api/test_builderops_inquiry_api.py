from __future__ import annotations

from pathlib import Path
import json

from fastapi.testclient import TestClient

from app.api.app import app


def test_inquiry_api_start_trace_resume(tmp_path: Path, monkeypatch) -> None:
    vault = tmp_path / "shared-vault"
    vault.mkdir()
    monkeypatch.setenv("BUILDEROPS_VAULT_ROOT", str(vault))
    monkeypatch.setenv("BUILDEROPS_DB_PATH", str(tmp_path / "local" / "builderops.sqlite3"))
    client = TestClient(app)
    payload = {
        "question": "What should become a ticket?",
        "workflow": "fable-gpt-architecture",
        "inquiry_id": "inq_test_api",
        "source_refs": [{"ref_type": "github_issue", "ref": "#3290"}],
        "created_by": {"actor_type": "agent", "id": "api-codex"},
    }

    started = client.post("/api/builderops/inquiries", json=payload)
    assert started.status_code == 200, started.text
    assert started.json()["trace"]["question"]["content"] == payload["question"]

    traced = client.get("/api/builderops/inquiries/inq_test_api/trace")
    assert traced.status_code == 200, traced.text
    assert traced.json()["trace"] == started.json()["trace"]

    resumed = client.post("/api/builderops/inquiries/inq_test_api/resume")
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["resume"] == {
        "inquiry_id": "inq_test_api",
        "skipped_turn_ids": [],
        "pending_turn_ids": [],
        "terminal_receipt_ids": [],
        "next_sequence": 0,
    }

    assert not (vault / ".git").exists()

    receipt_path = (
        vault
        / "model-inquiries"
        / "inq_test_api"
        / "receipts"
        / "inquiry-started.json"
    )
    malformed = json.loads(receipt_path.read_text(encoding="utf-8"))
    malformed["actor"] = 1
    receipt_path.write_text(json.dumps(malformed), encoding="utf-8")
    rejected = client.get("/api/builderops/inquiries/inq_test_api/trace")
    assert rejected.status_code == 400, rejected.text
    assert "invalid BuilderOpsReceipt" in rejected.text
