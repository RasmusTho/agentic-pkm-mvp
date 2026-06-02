from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.api.routes.companion as companion_module
import app.panel.confirmation as confirm_module
from app.api.app import app
from app.components.settings.panel_actions_loader import load_panel_action_catalog
from app.write_guard import WritesBlockedError


@pytest.fixture(autouse=True)
def _clear_panel_state():
    confirm_module._proposal_store.clear()
    confirm_module._idempotency_store.clear()
    yield
    confirm_module._proposal_store.clear()
    confirm_module._idempotency_store.clear()


def _write_note(
    root: Path,
    relative: str,
    *,
    title: str = "Queue Review",
    uuid: str | None = "queue-review-uuid",
    body: str = "Body.\n",
) -> Path:
    note = root / relative
    note.parent.mkdir(parents=True, exist_ok=True)
    uuid_line = f"uuid: {uuid}\n" if uuid is not None else ""
    note.write_text(
        f"---\ntitle: {title}\n{uuid_line}---\n\n{body}",
        encoding="utf-8",
    )
    return note


def _proposal_count() -> int:
    return len(getattr(confirm_module._proposal_store, "_proposals", {}))


def _staged_proposal(proposal_id: str):
    return confirm_module._proposal_store.get(proposal_id)


def _outbox_records(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_queue_review_exists_in_default_panel_action_catalog() -> None:
    descriptor = load_panel_action_catalog().get("queue_review")

    assert descriptor is not None
    assert descriptor.intent_type == "note_lifecycle"
    assert descriptor.trust_verb == "APPLY"
    assert descriptor.downstream_event == "panel.governance.requested"
    assert descriptor.capability_class == "governed_execution"
    assert descriptor.authority_class == "governed_effect"
    assert descriptor.requires_human_gate is True
    assert descriptor.params["operation"] == "queue_review"


def test_queue_review_stages_panel_proposal_and_returns_pending_intent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = tmp_path / "vault"
    note = _write_note(vault, "notes/review.md", uuid="uuid-1472")
    before = note.read_text(encoding="utf-8")
    outbox = tmp_path / "index-outbox.jsonl"
    monkeypatch.setenv("VAULT_ROOT", str(vault))
    monkeypatch.setenv("PKM_ENVIRONMENT", "dev")
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox))

    resp = TestClient(app).post(
        "/api/companion/vault-browser/actions/queue-review",
        json={"note_path": "notes/review.md"},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["intent_id"]
    assert data["proposal_id"] == data["intent_id"]
    assert data["artifact_id"] == "uuid-1472"
    assert data["artifact_uuid"] == "uuid-1472"
    assert data["note_path"] == "notes/review.md"
    assert data["state"] == "pending_intent"
    assert data["action_type"] == "note_lifecycle"
    assert data["operation"] == "queue_review"
    assert data["receipt_state"] == "pending_intent_not_durable_receipt"
    assert data["execution_path"] == "/api/panel/confirm"

    proposal = _staged_proposal(data["proposal_id"])
    assert proposal is not None
    assert proposal.artifact_id == "uuid-1472"
    assert proposal.intent_event.payload.note.uuid == "uuid-1472"
    assert proposal.intent_event.payload.note.path == "notes/review.md"
    action = proposal.intent_event.payload.actions[0]
    assert action.checked is True
    assert action.mapping is not None
    assert action.mapping.id == "queue_review"
    assert action.mapping.intent_type == "note_lifecycle"
    assert action.mapping.params["operation"] == "queue_review"
    assert action.mapping.params["note_path"] == "notes/review.md"
    assert action.mapping.params["artifact_uuid"] == "uuid-1472"

    assert note.read_text(encoding="utf-8") == before
    assert _outbox_records(outbox) == []


def test_queue_review_accepts_artifact_uuid_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = tmp_path / "vault"
    _write_note(vault, "notes/by-uuid.md", uuid="uuid-only-1472")
    monkeypatch.setenv("VAULT_ROOT", str(vault))
    monkeypatch.setenv("PKM_ENVIRONMENT", "dev")

    resp = TestClient(app).post(
        "/api/companion/vault-browser/actions/queue-review",
        json={"artifact_uuid": "uuid-only-1472"},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["artifact_id"] == "uuid-only-1472"
    assert data["note_path"] == "notes/by-uuid.md"
    assert _proposal_count() == 1


def test_queue_review_accepts_matching_note_path_and_uuid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = tmp_path / "vault"
    _write_note(vault, "notes/matching.md", uuid="matching-1472")
    monkeypatch.setenv("VAULT_ROOT", str(vault))
    monkeypatch.setenv("PKM_ENVIRONMENT", "dev")

    resp = TestClient(app).post(
        "/api/companion/vault-browser/actions/queue-review",
        json={"note_path": "notes/matching.md", "artifact_uuid": "matching-1472"},
    )

    assert resp.status_code == 200
    assert resp.json()["artifact_uuid"] == "matching-1472"
    assert _proposal_count() == 1


def test_queue_review_rejects_missing_scope() -> None:
    resp = TestClient(app).post(
        "/api/companion/vault-browser/actions/queue-review",
        json={},
    )

    assert resp.status_code == 400
    assert resp.json()["detail"]["error"] == "artifact_scope_required"
    assert _proposal_count() == 0


def test_queue_review_rejects_unknown_note(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VAULT_ROOT", str(tmp_path / "vault"))
    monkeypatch.setenv("PKM_ENVIRONMENT", "dev")

    resp = TestClient(app).post(
        "/api/companion/vault-browser/actions/queue-review",
        json={"note_path": "notes/missing.md"},
    )

    assert resp.status_code == 404
    assert resp.json()["detail"]["error"] == "artifact_not_found"
    assert _proposal_count() == 0


def test_queue_review_rejects_unknown_artifact_uuid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = tmp_path / "vault"
    _write_note(vault, "notes/known.md", uuid="known-uuid")
    monkeypatch.setenv("VAULT_ROOT", str(vault))
    monkeypatch.setenv("PKM_ENVIRONMENT", "dev")

    resp = TestClient(app).post(
        "/api/companion/vault-browser/actions/queue-review",
        json={"artifact_uuid": "missing-uuid"},
    )

    assert resp.status_code == 404
    assert resp.json()["detail"]["error"] == "artifact_not_found"
    assert _proposal_count() == 0


def test_queue_review_rejects_mismatched_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = tmp_path / "vault"
    _write_note(vault, "notes/a.md", uuid="uuid-a")
    _write_note(vault, "notes/b.md", uuid="uuid-b")
    monkeypatch.setenv("VAULT_ROOT", str(vault))
    monkeypatch.setenv("PKM_ENVIRONMENT", "dev")

    resp = TestClient(app).post(
        "/api/companion/vault-browser/actions/queue-review",
        json={"note_path": "notes/a.md", "artifact_uuid": "uuid-b"},
    )

    assert resp.status_code == 409
    assert resp.json()["detail"]["error"] == "artifact_scope_mismatch"
    assert _proposal_count() == 0


def test_queue_review_writeguard_block_does_not_stage_or_mutate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = tmp_path / "vault"
    note = _write_note(vault, "notes/blocked.md", uuid="blocked-1472")
    before = note.read_text(encoding="utf-8")
    outbox = tmp_path / "index-outbox.jsonl"
    monkeypatch.setenv("VAULT_ROOT", str(vault))
    monkeypatch.setenv("PKM_ENVIRONMENT", "dev")
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox))

    def _blocked(action: str) -> None:
        raise WritesBlockedError(state="safe_mode", reason="test lock", action=action)

    monkeypatch.setattr(
        companion_module.DEFAULT_WRITE_GUARD,
        "assert_writes_allowed",
        _blocked,
    )

    resp = TestClient(app).post(
        "/api/companion/vault-browser/actions/queue-review",
        json={"note_path": "notes/blocked.md"},
    )

    assert resp.status_code == 409
    assert resp.json()["detail"]["error"] == "writeguard_blocked"
    assert resp.json()["detail"]["state"] == "blocked"
    assert _proposal_count() == 0
    assert note.read_text(encoding="utf-8") == before
    assert _outbox_records(outbox) == []
