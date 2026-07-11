from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.api.app import app
from app.dispatcher.events import JsonlEventWriter
from app.dispatcher.leases import claim
from app.dispatcher.models import TaskRecord
from app.dispatcher.store import SqliteStore


def _seed(store: SqliteStore, *, status: str = "ready") -> TaskRecord:
    task = TaskRecord(
        task_id="task-signboard-1", issue_number=42, title="Build a visible board",
        status=status, priority="high", repo="RasmusTho/agentic-pkm-mvp",
        source_anchor_refs=["#42"],
        created_at="2026-07-10T10:00:00Z", updated_at="2026-07-10T10:00:00Z",
        sync_state={"labels": ["ui", "kanban"], "url": "https://example.test/issues/42"},
    )
    store.upsert_task(task)
    return task


def _configure(tmp_path: Path, monkeypatch) -> SqliteStore:
    state = tmp_path / "dispatcher"
    monkeypatch.setenv("DISPATCHER_STATE_DIR", str(state))
    monkeypatch.setenv("DISPATCHER_DB_PATH", str(state / "dispatcher.sqlite3"))
    monkeypatch.setenv("DISPATCHER_EVENTS_PATH", str(state / "events.jsonl"))
    monkeypatch.setenv("SIGNBOARD_ROOT", str(tmp_path / "board"))
    store = SqliteStore(state / "dispatcher.sqlite3", JsonlEventWriter(state / "events.jsonl"))
    store.initialize()
    return store


def test_signboard_refresh_parses_projection_and_hides_meta(tmp_path: Path, monkeypatch) -> None:
    store = _configure(tmp_path, monkeypatch)
    _seed(store)
    store.upsert_task(TaskRecord(task_id="_meta", issue_number=0, title="metadata", status="_meta", priority="low", source_anchor_refs=[], created_at="x", updated_at="x"))
    client = TestClient(app)

    response = client.post("/api/signboard/refresh")
    assert response.status_code == 200, response.text
    columns = {column["name"]: column["cards"] for column in response.json()["columns"]}
    assert columns["Ready"][0]["title"] == "Build a visible board"
    assert columns["Ready"][0]["repo"] == "RasmusTho/agentic-pkm-mvp"
    assert columns["Ready"][0]["labels"] == ["ui", "kanban"]
    assert all(card["id"] != "_meta" for cards in columns.values() for card in cards)


def test_signboard_rejects_malformed_and_wrong_column_cards(tmp_path: Path, monkeypatch) -> None:
    _configure(tmp_path, monkeypatch)
    root = tmp_path / "board"
    (root / "Ready").mkdir(parents=True)
    (root / "Ready" / "bad.md").write_text("---\ngenerated_by: dispatcher.signboard\nid: broken\n", encoding="utf-8")
    (root / "Ready" / "wrong.md").write_text("---\ngenerated_by: dispatcher.signboard\nid: task-wrong\nstatus: ready\ncolumn: Done\n---\n", encoding="utf-8")
    response = TestClient(app).get("/api/signboard/board")
    assert response.status_code == 200
    assert response.json()["columns"][1]["cards"] == []


def test_signboard_renders_all_empty_columns_and_reports_bad_column_path(tmp_path: Path, monkeypatch) -> None:
    _configure(tmp_path, monkeypatch)
    root = tmp_path / "board"
    root.mkdir()
    (root / "Review").write_text("not a directory", encoding="utf-8")
    response = TestClient(app).get("/api/signboard/board")
    assert response.status_code == 200
    payload = response.json()
    assert [column["name"] for column in payload["columns"]] == [
        "Backlog", "Ready", "In Progress", "Review", "Blocked", "Done",
    ]
    assert all(column["cards"] == [] for column in payload["columns"])
    assert payload["errors"] == ["Review is not a directory"]


def test_move_uses_dispatcher_then_reexports(tmp_path: Path, monkeypatch) -> None:
    store = _configure(tmp_path, monkeypatch)
    task = _seed(store)
    client = TestClient(app)
    client.post("/api/signboard/refresh")

    response = client.post(f"/api/signboard/cards/{task.task_id}/move", json={"status": "Review", "actor": "tester"})
    assert response.status_code == 200, response.text
    assert store.get_task(task.task_id).status == "review"
    assert len(list((tmp_path / "board" / "Review").glob("task-signboard-1--*.md"))) == 1
    assert any(event.event_type == "task.moved" for event in store.list_events())


def test_claimed_card_completes_with_its_lease_holder(tmp_path: Path, monkeypatch) -> None:
    store = _configure(tmp_path, monkeypatch)
    task = _seed(store)
    claim(store, task.task_id, "signboard-agent")

    response = TestClient(app).post(
        f"/api/signboard/cards/{task.task_id}/move",
        json={"status": "Done", "actor": "signboard-agent"},
    )

    assert response.status_code == 200, response.text
    assert store.get_task(task.task_id).status == "completed"
    assert store.get_task(task.task_id).lease_id is None


def test_block_requires_reason_and_path_traversal_is_rejected(tmp_path: Path, monkeypatch) -> None:
    store = _configure(tmp_path, monkeypatch)
    task = _seed(store)
    client = TestClient(app)
    no_reason = client.post(f"/api/signboard/cards/{task.task_id}/move", json={"status": "Blocked"})
    assert no_reason.status_code == 409
    traversal = client.post("/api/signboard/cards/../secret/move", json={"status": "Review"})
    assert traversal.status_code in {404, 405}


def test_signboard_page_is_served() -> None:
    response = TestClient(app).get("/signboard")
    assert response.status_code == 200
    assert "Refresh projection" in response.text
    assert "API key for remote moves" in response.text


def test_signboard_remote_mutations_send_api_key_header() -> None:
    script = (Path(__file__).parents[2] / "app/web/static/signboard.js").read_text(encoding="utf-8")
    assert "X-API-Key" in script
    assert "sessionStorage" not in script
    assert "actor = 'signboard-ui'" in script
    assert "card.claimed_by || 'signboard-ui'" in script
