from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.api.app import app
from app.dispatcher.events import JsonlEventWriter
from app.dispatcher.leases import claim
from app.dispatcher.models import TaskRecord
from app.dispatcher.signboard import STATUS_COLUMNS, VALID_STATUSES
from app.dispatcher.store import SqliteStore

ROUTE_SOURCE = Path(__file__).parents[2] / "app/api/routes/signboard.py"


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
    monkeypatch.delenv("SIGNBOARD_ROOT", raising=False)
    store = SqliteStore(state / "dispatcher.sqlite3", JsonlEventWriter(state / "events.jsonl"))
    store.initialize()
    return store


def _write_projection_card(root: Path, *, column: str, task_id: str, title: str) -> Path:
    """Write a card the retired Markdown reader would have accepted."""
    directory = root / column
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{task_id}--card.md"
    path.write_text(
        "---\n"
        "generated_by: dispatcher.signboard\n"
        f"id: {task_id}\n"
        "issue_number: 999\n"
        f"title: {title}\n"
        "status: ready\n"
        f"column: {column}\n"
        "---\n"
        f"# {title}\n",
        encoding="utf-8",
    )
    return path


def _cards(payload: dict) -> list[dict]:
    return [card for column in payload["columns"] for card in column["cards"]]


def test_board_is_served_from_store(tmp_path: Path, monkeypatch) -> None:
    """The board is built from the dispatcher store, not from Markdown on disk.

    A projection directory that still exists on the host is not board input:
    the store is the authority and reading a second copy back is exactly the
    loop #4401 removes.
    """
    store = _configure(tmp_path, monkeypatch)
    _seed(store)
    decoy = tmp_path / "stale-board"
    _write_projection_card(decoy, column="Ready", task_id="task-from-disk", title="Card from disk")
    monkeypatch.setenv("SIGNBOARD_ROOT", str(decoy))

    payload = TestClient(app).get("/api/signboard/board").json()

    assert payload["status"] == "ok"
    assert payload["errors"] == []
    assert payload["authority"] == "dispatcher_store"
    assert [card["id"] for card in _cards(payload)] == ["task-signboard-1"]
    ready = {column["name"]: column["cards"] for column in payload["columns"]}["Ready"]
    assert ready[0]["title"] == "Build a visible board"
    assert ready[0]["repo"] == "RasmusTho/agentic-pkm-mvp"
    assert ready[0]["labels"] == ["ui", "kanban"]
    assert ready[0]["github_url"] == "https://example.test/issues/42"

    # The response no longer carries a filesystem root, and the route no longer
    # owns the machinery that resolved or parsed one.
    assert "root" not in payload
    from app.api.routes import signboard as signboard_route

    for retired in ("signboard_root", "read_signboard", "parse_signboard_markdown"):
        assert not hasattr(signboard_route, retired)
    source = ROUTE_SOURCE.read_text(encoding="utf-8")
    for read_call in (".glob(", ".rglob(", ".read_text(", "yaml"):
        assert read_call not in source


def test_board_served_without_any_projection_directory(tmp_path: Path, monkeypatch) -> None:
    """No board root has to exist, or resolve, for the board to be correct."""
    store = _configure(tmp_path, monkeypatch)
    _seed(store)

    payload = TestClient(app).get("/api/signboard/board").json()

    assert payload["status"] == "ok"
    assert payload["errors"] == []
    assert [card["id"] for card in _cards(payload)] == ["task-signboard-1"]
    assert not any(child.name != "dispatcher" for child in tmp_path.iterdir())


def test_missing_store_reports_error_not_empty_board(tmp_path: Path, monkeypatch) -> None:
    """A store that cannot be read is a visible error, never a healthy board.

    This is the invariant #4279 was filed to protect: "no work" and
    "misconfigured" must not look the same. It has to survive the projection
    being retired, so it is asserted against the store rather than against a
    board root.
    """
    state = tmp_path / "dispatcher"
    monkeypatch.setenv("DISPATCHER_STATE_DIR", str(state))
    monkeypatch.setenv("DISPATCHER_DB_PATH", str(state / "dispatcher.sqlite3"))
    monkeypatch.setenv("DISPATCHER_EVENTS_PATH", str(state / "events.jsonl"))
    monkeypatch.delenv("SIGNBOARD_ROOT", raising=False)
    client = TestClient(app)

    absent = client.get("/api/signboard/board")
    assert absent.status_code == 503
    assert "dispatcher is not initialised" in absent.json()["detail"]

    # A store file that exists but was never initialised is the same failure:
    # it must not answer with six healthy empty columns.
    state.mkdir(parents=True)
    (state / "dispatcher.sqlite3").touch()

    uninitialised = client.get("/api/signboard/board")
    assert uninitialised.status_code == 503
    assert "dispatcher store is not readable" in uninitialised.json()["detail"]


def test_move_is_visible_without_export(tmp_path: Path, monkeypatch) -> None:
    """A dispatcher write is the whole durable change; nothing is exported."""
    store = _configure(tmp_path, monkeypatch)
    task = _seed(store)
    board_root = tmp_path / "board"
    monkeypatch.setenv("SIGNBOARD_ROOT", str(board_root))
    client = TestClient(app)

    response = client.post(
        f"/api/signboard/cards/{task.task_id}/move",
        json={"status": "Review", "actor": "tester"},
    )

    assert response.status_code == 200, response.text
    assert store.get_task(task.task_id).status == "review"
    assert any(event.event_type == "task.moved" for event in store.list_events())
    moved = {column["name"]: column["cards"] for column in response.json()["columns"]}
    assert [card["id"] for card in moved["Review"]] == [task.task_id]
    assert moved["Ready"] == []

    # Nothing was written to disk, and the next plain read already agrees.
    assert not board_root.exists()
    reread = {
        column["name"]: column["cards"]
        for column in client.get("/api/signboard/board").json()["columns"]
    }
    assert [card["id"] for card in reread["Review"]] == [task.task_id]
    assert not board_root.exists()


def test_columns_follow_dispatcher_status_columns(tmp_path: Path, monkeypatch) -> None:
    """Column identity, order, and status mapping have one source."""
    from app.api.routes import signboard as signboard_route

    store = _configure(tmp_path, monkeypatch)
    for index, status in enumerate(sorted(VALID_STATUSES)):
        store.upsert_task(
            TaskRecord(
                task_id=f"task-{status}", issue_number=100 + index, title=f"Task {status}",
                status=status, priority="med", source_anchor_refs=[],
                created_at="2026-07-10T10:00:00Z", updated_at="2026-07-10T10:00:00Z",
            )
        )

    payload = TestClient(app).get("/api/signboard/board").json()

    expected_columns = tuple(dict.fromkeys(STATUS_COLUMNS.values()))
    assert signboard_route.COLUMNS == expected_columns
    assert [column["name"] for column in payload["columns"]] == list(expected_columns)
    placed = {card["id"]: card for card in _cards(payload)}
    for column in payload["columns"]:
        for card in column["cards"]:
            assert card["column"] == column["name"]
    for status in VALID_STATUSES:
        assert placed[f"task-{status}"]["column"] == STATUS_COLUMNS[status]

    # The route must not carry a second copy of the status -> column table.
    source = ROUTE_SOURCE.read_text(encoding="utf-8")
    for name in set(STATUS_COLUMNS.values()):
        assert f'"{name}"' not in source
        assert f"'{name}'" not in source


def test_board_hides_sync_metadata_rows(tmp_path: Path, monkeypatch) -> None:
    """The dispatcher's ``_meta`` row is synchronization state, not a card."""
    store = _configure(tmp_path, monkeypatch)
    _seed(store)
    store.upsert_task(
        TaskRecord(
            task_id="_meta", issue_number=0, title="metadata", status="_meta", priority="low",
            source_anchor_refs=[], created_at="x", updated_at="x",
        )
    )

    payload = TestClient(app).post("/api/signboard/refresh").json()

    assert payload["status"] == "ok"
    assert [card["id"] for card in _cards(payload)] == ["task-signboard-1"]


def test_board_reports_an_unmappable_status_instead_of_dropping_it(
    tmp_path: Path, monkeypatch
) -> None:
    """A task the column table cannot place is reported, not silently lost."""
    store = _configure(tmp_path, monkeypatch)
    _seed(store)
    store.upsert_task(
        TaskRecord(
            task_id="task-weird", issue_number=7, title="Unknown status", status="parked",
            priority="low", source_anchor_refs=[],
            created_at="2026-07-10T10:00:00Z", updated_at="2026-07-10T10:00:00Z",
        )
    )

    payload = TestClient(app).get("/api/signboard/board").json()

    assert payload["status"] == "error"
    assert any("task-weird" in error for error in payload["errors"])
    assert [card["id"] for card in _cards(payload)] == ["task-signboard-1"]


def test_empty_store_renders_every_column(tmp_path: Path, monkeypatch) -> None:
    """An initialised store with no tasks is a genuinely empty, healthy board."""
    _configure(tmp_path, monkeypatch)

    payload = TestClient(app).get("/api/signboard/board").json()

    assert payload["status"] == "ok"
    assert payload["errors"] == []
    assert [column["name"] for column in payload["columns"]] == [
        "Backlog", "Ready", "In Progress", "Review", "Blocked", "Done",
    ]
    assert _cards(payload) == []


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
    assert "Refresh board" in response.text
    assert "API key for remote moves" in response.text


def test_signboard_remote_mutations_send_api_key_header() -> None:
    script = (Path(__file__).parents[2] / "app/web/static/signboard.js").read_text(encoding="utf-8")
    assert "X-API-Key" in script
    assert "sessionStorage" not in script
    assert "actor = 'signboard-ui'" in script
    assert "card.claimed_by || 'signboard-ui'" in script
