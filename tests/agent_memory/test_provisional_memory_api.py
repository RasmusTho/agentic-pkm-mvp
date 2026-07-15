from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.auth as auth_module
from app.agent_memory import provisional_write as provisional_write_module
from app.api.app import app
from tests.api._vault_test_helpers import bind_initialized_vault


def _setup_vault(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, Path]:
    vault = tmp_path / "vault"
    vault.mkdir(parents=True)
    bind_initialized_vault(monkeypatch, vault, store_dir=tmp_path)
    receipts = tmp_path / "provisional-receipts.jsonl"
    monkeypatch.setenv("PROVISIONAL_MEMORY_RECEIPTS_PATH", str(receipts))
    monkeypatch.setenv("PKM_ENVIRONMENT", "dev")
    return vault, receipts


def _payload() -> dict[str, object]:
    return {
        "scope_id": "scope-personal",
        "principal_id": "principal-1",
        "memory_type": "preference_memory",
        "sensitivity": "private",
        "content": "The user prefers explicit verification.",
        "provenance_event_ids": ["event-1"],
    }


def test_direct_write_creates_provisional_artifact_and_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault, receipts_path = _setup_vault(tmp_path, monkeypatch)
    guard_calls: list[str] = []
    real_guard = provisional_write_module.assert_provisional_trust_tier

    def _spy_guard(artifact: object) -> None:
        guard_calls.append("called")
        real_guard(artifact)  # type: ignore[arg-type]

    monkeypatch.setattr(
        provisional_write_module,
        "assert_provisional_trust_tier",
        _spy_guard,
    )

    response = TestClient(app).post(
        "/api/companion/memory/provisional",
        json=_payload(),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    record = body["reconciliation"]["record"]
    assert guard_calls == ["called"]
    assert record["authority_state"] == "noncanonical"
    assert record["review_state"] == "unreviewed"
    assert record["may_apply"] is False
    assert record["may_write"] is False
    note_path = vault / body["reconciliation"]["artifact_ref"].removeprefix("vault://")
    assert note_path.exists()

    persisted = [
        json.loads(line)
        for line in receipts_path.read_text(encoding="utf-8").splitlines()
    ]
    assert [item["transition"] for item in persisted] == ["write_staged", "created"]
    assert body["lifecycle_receipt"]["receipt_id"] == persisted[-1]["receipt_id"]
    assert "The user prefers explicit verification." not in receipts_path.read_text(
        encoding="utf-8"
    )


def test_provisional_artifact_is_visibly_distinct_from_promoted_memory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault, _ = _setup_vault(tmp_path, monkeypatch)

    response = TestClient(app).post(
        "/api/companion/memory/provisional",
        json=_payload(),
    )

    assert response.status_code == 200, response.text
    artifact_ref = response.json()["reconciliation"]["artifact_ref"]
    assert artifact_ref.startswith("vault://Memory/Provisional/")
    markdown = (vault / artifact_ref.removeprefix("vault://")).read_text(
        encoding="utf-8"
    )
    assert "artifact_type: provisional_memory" in markdown
    assert "review_state: unreviewed" in markdown
    assert "authority_state: noncanonical" in markdown
    assert "Provisional / low trust — not authority" in markdown
    assert "agent_promoted" not in markdown


def test_non_loopback_provisional_write_requires_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(auth_module.settings, "api_key", None)
    monkeypatch.setattr(auth_module.settings, "companion_trusted_proxy_hosts", "")
    monkeypatch.setattr(auth_module.settings, "companion_ui_proxy_hosts", "")
    client = TestClient(app, client=("203.0.113.10", 50000))

    response = client.post(
        "/api/companion/memory/provisional",
        json=_payload(),
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "API key required for non-loopback request"
