from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import app.api.routes.canvas as canvas_module
import app.api.routes.panel as panel_routes
import app.panel.checkbox_projection as projection_module
import app.panel.confirmation as confirm_module
from app.agents.panel.writeback import stable_action_id
from app.api.app import app
from app.api.routes.artifacts import _content_hash
from app.events.panel import (
    NoteRef,
    PanelInfo,
    PanelIntentAction,
    PanelIntentEvent,
    PanelIntentPayload,
    PanelRuntimeActionResult,
)
from app.panel.checkbox_projection import extract_panel_selectable_options
from app.panel.confirmation import StagedProposal
from app.write_guard import DEFAULT_WRITE_GUARD, WriteGuard, WritesBlockedError

pytestmark = [
    pytest.mark.uat_integrated_runtime,
    pytest.mark.skipif(
        os.getenv("RUN_INTEGRATED_RUNTIME_UAT", "").strip().lower()
        not in {"1", "true", "yes", "on"},
        reason="opt-in integrated runtime UAT; set RUN_INTEGRATED_RUNTIME_UAT=1",
    ),
]


def _write_note(
    root: Path,
    relative: str,
    *,
    title: str = "UAT Note",
    uuid: str = "uat-note-uuid",
    body: str = "Body.\n",
) -> Path:
    note = root / relative
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text(
        f"---\ntitle: {title}\nuuid: {uuid}\n---\n\n{body}",
        encoding="utf-8",
    )
    return note


def _panel_markdown(*, checked: bool = False) -> str:
    mark = "x" if checked else " "
    return (
        "---\n"
        "title: Panel UAT\n"
        "uuid: panel-uat-uuid\n"
        "---\n\n"
        "# Panel UAT\n\n"
        "%% AI:Start %%\n"
        "## AI-instruktion\n"
        "Queue this note for review.\n"
        "## AI-åtgärder\n"
        f"- [{mark}] Send email <!--ai:option_id=opt_uat--> <!--ai:id=send.email--> <!--ai:proposed=979-->\n"
        "## AI-logg\n"
        "%% AI:End %%\n"
    )


def _write_panel_note(root: Path, relative: str = "notes/panel.md") -> Path:
    return _write_note(
        root,
        relative,
        uuid="panel-uat-uuid",
        body=_panel_markdown().split("---\n\n", 1)[1],
    )


def _checkbox_request(note: Path) -> dict[str, str]:
    content = note.read_text(encoding="utf-8")
    option = extract_panel_selectable_options(
        content,
        artifact_id="panel-uat-uuid",
        note_path="notes/panel.md",
        content_hash=_content_hash(content),
    )[0]
    return {
        "artifact_id": option.artifact_id,
        "note_path": option.note_path,
        "panel_id": option.panel_id,
        "option_id": option.option_id,
        "expected_content_hash": option.content_hash,
        "expected_source_hash": option.source_hash,
        "idempotency_key": "idem-checkbox-uat",
    }


def _panel_intent(note: Path, *, label: str = "send report") -> PanelIntentEvent:
    return PanelIntentEvent(
        payload=PanelIntentPayload(
            note=NoteRef(uuid="panel-uat-uuid", path=str(note)),
            panel=PanelInfo(panel_id="panel-uat", instruction="do it"),
            actions=[
                PanelIntentAction(
                    id=stable_action_id(label),
                    label=label,
                    checked=True,
                )
            ],
        )
    )


def _stage_proposal(note: Path, proposal_id: str = "prop-uat") -> None:
    confirm_module._proposal_store.stage(
        proposal_id,
        StagedProposal(
            artifact_id="panel-uat-uuid",
            intent_event=_panel_intent(note),
            proposed_at=0.0,
        ),
    )


def _confirm_body(
    *,
    proposal_id: str = "prop-uat",
    artifact_id: str = "panel-uat-uuid",
    idempotency_key: str = "idem-confirm-uat",
) -> dict[str, str]:
    return {
        "proposal_id": proposal_id,
        "artifact_id": artifact_id,
        "action": "confirm",
        "idempotency_key": idempotency_key,
    }


def _outbox_events(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


@pytest.fixture(autouse=True)
def _clear_runtime_state(monkeypatch: pytest.MonkeyPatch):
    panel_routes.UnknownProposalError = confirm_module.UnknownProposalError
    panel_routes.SameTurnExecutionError = confirm_module.SameTurnExecutionError
    confirm_module._proposal_store.clear()
    confirm_module._idempotency_store.clear()
    projection_module._idempotency_store.clear()
    projection_module._service._guard = DEFAULT_WRITE_GUARD
    confirm_module._service._guard = DEFAULT_WRITE_GUARD
    canvas_module._sessions.clear()
    canvas_module._edit_history.clear()
    canvas_module._undone_history.clear()
    monkeypatch.setenv("PKM_ENVIRONMENT", "test")
    monkeypatch.setenv("PANEL_AGENT_DECIDER", "rule")
    yield
    confirm_module._proposal_store.clear()
    confirm_module._idempotency_store.clear()
    projection_module._idempotency_store.clear()
    projection_module._service._guard = DEFAULT_WRITE_GUARD
    confirm_module._service._guard = DEFAULT_WRITE_GUARD
    canvas_module._sessions.clear()
    canvas_module._edit_history.clear()
    canvas_module._undone_history.clear()


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def test_writeguard_blocked_confirm(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
) -> None:
    vault = tmp_path / "vault-test"
    note = _write_note(
        vault,
        "notes/panel.md",
        uuid="panel-uat-uuid",
        body="# Note\n- [ ] send report\n",
    )
    outbox = tmp_path / "index-outbox.jsonl"
    monkeypatch.setenv("VAULT_ROOT", str(vault))
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox))
    _stage_proposal(note)
    guard = MagicMock(spec=WriteGuard)
    guard.assert_writes_allowed.side_effect = WritesBlockedError(
        "safe_mode",
        "test write lock",
        "panel.confirm",
    )
    confirm_module._service._guard = guard

    resp = client.post("/api/panel/confirm", json=_confirm_body())

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "blocked"
    assert data["receipt"] is None
    assert data["receipt_visibility"] == "blocked_no_durable_receipt"
    assert data["block_reason"]["gate"] == "writeguard"
    assert "panel.action.blocked" in data["events_emitted"]
    written = note.read_text(encoding="utf-8")
    assert "- [ ] send report" in written
    assert "- [x] send report" not in written
    assert _outbox_events(outbox)[0]["event"] == "panel.action.blocked"


def test_content_hash_mismatch_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
) -> None:
    vault = tmp_path / "vault-test"
    note = _write_note(vault, "notes/save.md", uuid="save-uat", body="Original.\n")
    panel = _write_panel_note(vault)
    monkeypatch.setenv("VAULT_ROOT", str(vault))
    before_note = note.read_text(encoding="utf-8")
    before_panel = panel.read_text(encoding="utf-8")

    save_resp = client.post(
        "/api/companion/note/save",
        json={
            "note_path": "notes/save.md",
            "new_body": "Changed.\n",
            "expected_content_hash": "stale",
        },
    )
    projection_body = _checkbox_request(panel)
    projection_body["expected_content_hash"] = "stale"
    projection_resp = client.post("/api/panel/checkbox-projection", json=projection_body)

    assert save_resp.status_code == 409
    assert save_resp.json()["detail"]["error"] == "content_hash_mismatch"
    assert projection_resp.status_code == 409
    assert projection_resp.json()["detail"]["status"] == "stale"
    assert projection_resp.json()["detail"]["block_reason"] == "content_hash_mismatch"
    assert note.read_text(encoding="utf-8") == before_note
    assert panel.read_text(encoding="utf-8") == before_panel


def test_provider_unavailable_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
) -> None:
    vault = tmp_path / "vault-test"
    outbox = tmp_path / "index-outbox.jsonl"
    note = _write_note(vault, "notes/provider.md", uuid="provider-uat", body="# Provider\nBody.\n")
    monkeypatch.setenv("VAULT_ROOT", str(vault))
    monkeypatch.setenv("VAULT_INBOX_DIR_REL", "Inbox")
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox))
    monkeypatch.setenv("CANVAS_ENABLED", "1")
    for key in ("LLM_PROVIDER", "LLM_MODEL", "OLLAMA_URL", "OPENAI_BASE_URL", "LLM_BACKEND"):
        monkeypatch.delenv(key, raising=False)

    capture = client.post("/api/companion/capture", json={"text": "Provider-free capture"})
    browse = client.get("/api/companion/vault-browser")
    queue = client.post(
        "/api/companion/vault-browser/actions/queue-review",
        json={"note_path": "notes/provider.md"},
    )
    proposal_id = queue.json()["proposal_id"]
    proposal = confirm_module._proposal_store.get(proposal_id)
    assert proposal is not None
    proposal.proposed_at = time.time() - 10

    result = PanelRuntimeActionResult(
        id=stable_action_id("Queue for review"),
        label="Queue for review",
        checked=True,
        status="logged",
    )
    runtime_result = MagicMock(actions=[result], emitted_events=[])
    with patch.object(confirm_module, "execute_panel_intent", return_value=runtime_result):
        confirm = client.post(
            "/api/panel/confirm",
            json=_confirm_body(
                proposal_id=proposal_id,
                artifact_id=queue.json()["artifact_id"],
                idempotency_key="idem-provider-confirm",
            ),
        )

    canvas_open = client.post(
        "/api/canvas/sessions",
        json={"note_path": "notes/provider.md", "label": "provider-unavailable"},
    )
    before_canvas = note.read_text(encoding="utf-8")
    coauthor = client.post(
        f"/api/canvas/sessions/{canvas_open.json()['session_id']}/coauthor",
        json={"intent": "expand this note"},
    )

    assert capture.status_code == 200, capture.text
    assert browse.status_code == 200, browse.text
    assert queue.status_code == 200, queue.text
    assert confirm.status_code == 200, confirm.text
    assert confirm.json()["status"] == "logged"
    assert coauthor.status_code == 503, coauthor.text
    assert "edit-capable LLM provider" in coauthor.json()["detail"]
    assert note.read_text(encoding="utf-8") == before_canvas


def test_missing_receipt_source_honest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
) -> None:
    vault = tmp_path / "vault-test"
    note = _write_note(vault, "notes/no-source.md", uuid="receipt-source-uat")
    before = note.read_text(encoding="utf-8")
    monkeypatch.setenv("VAULT_ROOT", str(vault))
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(tmp_path / "missing-outbox.jsonl"))

    resp = client.get("/api/companion/vault-browser")

    assert resp.status_code == 200, resp.text
    data = resp.json()
    item = next(row for row in data["notes"] if row["note_path"] == "notes/no-source.md")
    assert "receipts" not in item
    assert note.read_text(encoding="utf-8") == before


def test_missing_vault_fails_loud(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    missing_vault = tmp_path / "missing-vault-test"
    fallback_vault = repo_root / "vault"
    before_fallback_exists = fallback_vault.exists()
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_docker = fake_bin / "docker"
    fake_docker.write_text("#!/usr/bin/env bash\necho fake docker should not run >&2\nexit 99\n", encoding="utf-8")
    fake_docker.chmod(0o755)

    env = {
        "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}",
        "HOME": str(Path.home()),
        "VAULT_ROOT": str(missing_vault),
        "PKM_ENVIRONMENT": "test",
    }
    result = subprocess.run(
        ["bash", "scripts/start_full_system.sh"],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )

    combined = result.stdout + result.stderr
    assert result.returncode == 1
    assert "Vault root is missing" in combined
    assert str(missing_vault) in combined
    assert missing_vault.exists() is False
    assert fallback_vault.exists() is before_fallback_exists
    # Positive leg: a properly-set, existing VAULT_ROOT_TEST resolves. The
    # runtime now fails loud on a *missing* env-scoped vault root (the
    # open-vault-on-missing-vault change), so the dir must exist for the success
    # path — creating it here exercises the real resolution instead of the stale
    # pre-fail-loud expectation that rotted this leg (issues #1999 / #1997 F1).
    explicit_vault_test = tmp_path / "explicit-vault-test"
    explicit_vault_test.mkdir()
    monkeypatch.setenv("VAULT_ROOT_TEST", str(explicit_vault_test))
    from app.config.paths import resolve_vault_root

    assert resolve_vault_root(environment="test").name.endswith("-test")


def test_replay_and_foreign_intent_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
) -> None:
    vault = tmp_path / "vault-test"
    note = _write_note(
        vault,
        "notes/replay.md",
        uuid="panel-uat-uuid",
        body="# Replay\n- [ ] send report\n",
    )
    monkeypatch.setenv("VAULT_ROOT", str(vault))
    _stage_proposal(note)
    result = PanelRuntimeActionResult(
        id=stable_action_id("send report"),
        label="send report",
        checked=True,
        status="logged",
    )
    runtime_result = MagicMock(actions=[result], emitted_events=[])

    with patch.object(confirm_module, "execute_panel_intent", return_value=runtime_result) as execute:
        first = client.post("/api/panel/confirm", json=_confirm_body())
        replay = client.post("/api/panel/confirm", json=_confirm_body())
        foreign = client.post(
            "/api/panel/confirm",
            json=_confirm_body(
                proposal_id="foreign-intent",
                idempotency_key="idem-foreign",
            ),
        )

    assert first.status_code == 200, first.text
    assert replay.status_code == 200, replay.text
    assert first.json() == replay.json()
    assert execute.call_count == 1
    assert foreign.status_code == 404
    assert foreign.json()["detail"]["error"] == "unknown_proposal"
    # There is no LLM-triggered confirm path in the runtime; confirm requires an
    # explicit HTTP request carrying a known staged proposal and idempotency key.
