"""Integrated Runtime v1 golden-path UAT skeleton.

The green core path intentionally uses the test channel, a real temporary vault,
and real in-process API routes. It does not patch Panel/DB dependencies or touch
the operator vault. Confirm/receipt and restart-survival legs are implemented
as capability-gated tests: a missing capability is only skipped while its named
blocker is still open.
"""

from __future__ import annotations

import importlib
import io
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

_COMPANION_APP_ROOT = Path(__file__).resolve().parents[2] / "companion-ui" / "companion-app"
if str(_COMPANION_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(_COMPANION_APP_ROOT))

import app.api.routes.canvas as canvas_module
import app.api.routes.companion as companion_module
import app.panel.confirmation as confirm_module
from app.api.app import app
from app.panel.confirmation import SAME_TURN_TTL_SECONDS
from companion_ui.workspace.serve_dev_page import make_handler


pytestmark = [
    pytest.mark.uat_integrated_runtime,
    pytest.mark.skipif(
        os.getenv("RUN_INTEGRATED_RUNTIME_UAT", "").strip().lower()
        not in {"1", "true", "yes", "on"},
        reason="opt-in integrated runtime UAT; set RUN_INTEGRATED_RUNTIME_UAT=1",
    ),
]


REPO = "RasmusTho/agentic-pkm-mvp"
CONFIRM_ROUTE_PARITY_BLOCKERS = (1851, 1875)
RESUME_PERSISTENCE_BLOCKERS = (1877,)


@dataclass(frozen=True)
class GoldenPathContext:
    client: TestClient
    vault: Path
    outbox: Path
    note_path: str


@pytest.fixture(autouse=True)
def _clear_runtime_state() -> None:
    canvas_module._sessions.clear()
    canvas_module._edit_history.clear()
    canvas_module._undone_history.clear()
    yield
    canvas_module._sessions.clear()
    canvas_module._edit_history.clear()
    canvas_module._undone_history.clear()
    confirm_module._proposal_store.clear()
    confirm_module._idempotency_store.clear()


@pytest.fixture()
def golden_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> GoldenPathContext:
    vault = tmp_path / "vault-test"
    outbox = tmp_path / "tmp-test" / "index-outbox.jsonl"
    outbox.parent.mkdir(parents=True, exist_ok=True)
    note = vault / "notes" / "golden-path.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text(
        "---\n"
        "title: Golden Path Note\n"
        "uuid: golden-path-uuid\n"
        "review_state: needs_review\n"
        "trust: assert\n"
        "---\n\n"
        "# Golden Path Note\n\n"
        "Original body.\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("PKM_ENVIRONMENT", "test")
    monkeypatch.setenv("PKM_CHANNEL", "test")
    monkeypatch.setenv("VAULT_ROOT", str(vault))
    monkeypatch.setenv("VAULT_ROOT_TEST", str(vault))
    monkeypatch.setenv("VAULT_INBOX_DIR_REL", "Inbox")
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox))
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("PANEL_STAGING_STATE_DIR", str(tmp_path / "panel-staging"))
    monkeypatch.delenv("PANEL_STAGING_DB_PATH", raising=False)
    monkeypatch.delenv("PANEL_CONFIRMATION_DB_PATH", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DB_DSN", raising=False)
    monkeypatch.delenv("CANVAS_ENABLED", raising=False)
    monkeypatch.delenv("WORKSPACE_UPDATE_FLOW_ENABLED", raising=False)
    monkeypatch.setattr(companion_module, "_configured_vault_name", lambda: "vault-test")
    importlib.reload(confirm_module)
    confirm_module._proposal_store.clear()
    confirm_module._idempotency_store.clear()

    return GoldenPathContext(
        client=TestClient(app),
        vault=vault,
        outbox=outbox,
        note_path="notes/golden-path.md",
    )


def _json_lines(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _post(client: TestClient, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    resp = client.post(path, json=payload)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _get(client: TestClient, path: str, **params: Any) -> dict[str, Any]:
    resp = client.get(path, params=params or None)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _issue_state_from_gh(issue: int) -> str | None:
    try:
        proc = subprocess.run(
            [
                "gh",
                "issue",
                "view",
                str(issue),
                "--repo",
                REPO,
                "--json",
                "state",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    try:
        return str(json.loads(proc.stdout).get("state") or "").upper() or None
    except json.JSONDecodeError:
        return None


@lru_cache(maxsize=None)
def _dependency_is_open(issue: int) -> bool | None:
    return {
        "OPEN": True,
        "CLOSED": False,
    }.get(_issue_state_from_gh(issue) or "")


def _skip_if_blocked(reason: str, blockers: tuple[int, ...]) -> None:
    states = {issue: _dependency_is_open(issue) for issue in blockers}
    closed = [issue for issue, is_open in states.items() if is_open is False]
    if closed:
        pytest.fail(
            f"{reason} is still missing, but blocker(s) {closed} are closed. "
            "Unskip this UAT leg or repair the runtime capability."
        )
    open_issues = [f"#{issue}" for issue, is_open in states.items() if is_open is True]
    unknown = [f"#{issue}" for issue, is_open in states.items() if is_open is None]
    detail = ", ".join(open_issues + [f"{item} state unknown" for item in unknown])
    pytest.skip(f"{reason}; blocked by {detail}")


def _same_origin_post_allowed(path: str) -> bool:
    handler_cls = make_handler(client=object(), api_base_url="http://127.0.0.1:18002")  # type: ignore[arg-type]
    return bool(handler_cls._post_path_allowed(handler_cls.__new__(handler_cls), path))  # type: ignore[attr-defined]


class _RuntimeClient:
    def __init__(self, client: TestClient) -> None:
        self.client = client
        self.post_calls: list[tuple[str, dict[str, Any]]] = []

    def post(self, url: str, *, json: dict[str, Any]) -> dict[str, Any]:
        self.post_calls.append((url, json))
        resp = self.client.post(url, json=json)
        assert resp.status_code == 200, resp.text
        return resp.json()


class _PostDriver:
    def __init__(self, handler_cls: type, path: str, body: dict[str, Any]) -> None:
        raw = json.dumps(body).encode("utf-8")
        self._instance = handler_cls.__new__(handler_cls)
        self._instance.path = path
        self._instance.rfile = io.BytesIO(raw)
        self._instance.wfile = io.BytesIO()
        self._instance.headers = {"Content-Length": str(len(raw))}
        self.status_code: int | None = None
        self.payload: dict[str, Any] | None = None

        def _send_json(status_code: int, payload: dict[str, Any]) -> None:
            self.status_code = status_code
            self.payload = payload

        self._instance._send_json = _send_json  # type: ignore[method-assign]

    def run_post(self) -> None:
        self._instance.do_POST()


def _queue_review(context: GoldenPathContext) -> dict[str, Any]:
    return _post(
        context.client,
        "/api/companion/vault-browser/actions/queue-review",
        {"note_path": context.note_path},
    )


def _confirm_via_same_origin_proxy(
    context: GoldenPathContext,
    queued: dict[str, Any],
) -> dict[str, Any]:
    if not _same_origin_post_allowed("/api/panel/confirm"):
        _skip_if_blocked(
            "same-origin /api/panel/confirm proxy route is unavailable",
            CONFIRM_ROUTE_PARITY_BLOCKERS,
        )

    time.sleep(SAME_TURN_TTL_SECONDS + 0.1)
    runtime_client = _RuntimeClient(context.client)
    handler_cls = make_handler(
        client=runtime_client,
        api_base_url="http://127.0.0.1:18002",
    )
    driver = _PostDriver(
        handler_cls,
        "/api/panel/confirm",
        {
            "proposal_id": queued["proposal_id"],
            "artifact_id": queued["artifact_id"],
            "action": "confirm",
            "idempotency_key": f"uat-{queued['proposal_id']}",
        },
    )
    driver.run_post()

    assert runtime_client.post_calls[-1][0] == "/api/panel/confirm"
    assert driver.status_code == 200
    assert driver.payload is not None
    return driver.payload


def _proposal_persistence_available() -> bool:
    posture = confirm_module.panel_staging_store_posture()
    return (
        posture["proposal_store_mode"] == "sqlite"
        and posture["idempotency_store_mode"] == "sqlite"
        and posture["degraded"] is False
        and bool(posture["db_path"])
    )


@pytest.mark.uat_integrated_runtime
def test_start_orient_work_review_legs(golden_path: GoldenPathContext) -> None:
    client = golden_path.client

    # Start: core health/readiness/status routes resolve under the test channel.
    assert _get(client, "/healthz") == {"ok": True}
    assert client.get("/readyz").status_code in {200, 503}
    health = _get(client, "/api/health")
    status = _get(client, "/api/status")
    assert health
    assert status
    assert os.environ["PKM_ENVIRONMENT"] == "test"
    assert golden_path.vault.name == "vault-test"
    assert "vault" in str(golden_path.vault)

    # Orient: Companion orientation is a real read-only route.
    orientation = _get(client, "/api/companion/orientation")
    assert orientation["scope"]["kind"] == "workspace"
    assert orientation["scope"]["channel"] == "test"
    assert orientation["guards"]["read_only"] is True
    assert orientation["meta"]["contract_version"] == "workspace_orientation.v1"

    # Work: governed capture lands in the test-vault inbox and emits an event.
    capture = _post(
        client,
        "/api/companion/capture",
        {"text": "Integrated Runtime v1 golden-path capture"},
    )
    assert capture["note_path"] == "Inbox/inbox.md"
    inbox_note = golden_path.vault / "Inbox" / "inbox.md"
    assert "golden-path capture" in inbox_note.read_text(encoding="utf-8")
    assert "capture.inbox.appended" in capture["events_emitted"]
    assert any(event.get("event") == "capture.inbox.appended" for event in _json_lines(golden_path.outbox))

    # Work: Vault Browser inspect plus workspace re-anchor, then human note save round-trips.
    browser_before_save = _get(client, "/api/companion/vault-browser")
    assert any(
        note["note_path"] == golden_path.note_path for note in browser_before_save["notes"]
    )
    workspace = _get(client, "/api/companion/workspace", note_path=golden_path.note_path)
    content_hash = workspace["artifact"]["content_hash"]
    saved = _post(
        client,
        "/api/companion/note/save",
        {
            "note_path": golden_path.note_path,
            "new_body": "# Golden Path Note\n\nHuman test-channel save.\n",
            "expected_content_hash": content_hash,
        },
    )
    assert saved["status"] == "ok"
    assert "Human test-channel save." in (golden_path.vault / golden_path.note_path).read_text(
        encoding="utf-8"
    )

    # Review: inspect through Vault Browser, then stage a pending queue-review proposal.
    browser = _get(client, "/api/companion/vault-browser")
    note = next(n for n in browser["notes"] if n["note_path"] == golden_path.note_path)
    assert note["title"] == "Golden Path Note"
    queued = _queue_review(golden_path)
    assert queued["loop_stage"] == "queued_pending_confirmation"
    assert queued["receipt_state"] == "pending_intent_not_durable_receipt"
    assert queued["execution_path"] == "/api/panel/confirm"
    assert confirm_module._proposal_store.get(queued["proposal_id"]) is not None
    assert "promotion.transition.applied" not in {
        event.get("event") for event in _json_lines(golden_path.outbox)
    }


@pytest.mark.uat_integrated_runtime
def test_confirm_and_receipt_leg(golden_path: GoldenPathContext) -> None:
    queued = _queue_review(golden_path)
    confirmed = _confirm_via_same_origin_proxy(golden_path, queued)

    assert confirmed["status"] in {"executed", "logged"}
    assert confirmed["receipt"] is not None
    assert confirmed["receipt_visibility"] == "durable_vault_visible"
    browser = _get(golden_path.client, "/api/companion/vault-browser")
    receipt_note = next(
        n for n in browser["notes"] if n["note_path"] == golden_path.note_path
    )
    assert "receipts" in receipt_note
    assert confirmed["events_emitted"]


@pytest.mark.uat_integrated_runtime
def test_resume_leg_after_restart(golden_path: GoldenPathContext) -> None:
    queued = _queue_review(golden_path)
    assert confirm_module._proposal_store.get(queued["proposal_id"]) is not None

    if not _proposal_persistence_available():
        _skip_if_blocked(
            "Panel proposal/idempotency staging is not restart-persistent",
            RESUME_PERSISTENCE_BLOCKERS,
        )

    importlib.reload(confirm_module)
    resumed = TestClient(app)
    workspace = _get(resumed, "/api/companion/workspace", note_path=golden_path.note_path)
    assert workspace["artifact"]["note_path"] == golden_path.note_path
    assert confirm_module._proposal_store.get(queued["proposal_id"]) is not None


@pytest.mark.uat_integrated_runtime
def test_receipts_and_events_distinct(golden_path: GoldenPathContext) -> None:
    queued = _queue_review(golden_path)
    confirmed = _confirm_via_same_origin_proxy(golden_path, queued)

    assert confirmed["receipt"] is not None
    assert isinstance(confirmed["events_emitted"], list)
    assert confirmed["events_emitted"]
    assert all(isinstance(event_name, str) for event_name in confirmed["events_emitted"])
    assert confirmed["receipt"]["action_taken"] == "confirm"
    assert confirmed["receipt"] not in confirmed["events_emitted"]
