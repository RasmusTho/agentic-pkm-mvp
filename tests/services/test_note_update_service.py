from __future__ import annotations

import textwrap
import uuid
from pathlib import Path

import pytest

from app.agents.panel import integration as panel_integration
from app.agents.panel import writeback as panel_writeback
from app.knowledge.contracts import NoteLocator, WriteReceipt
from app.knowledge.errors import KnowledgeWriteConflict
from app.orchestrator.handler import OrchestratorContext
from app.planner.schema import make_simple_plan
from app.services.note_update import NoteUpdateResult, process_note_update
from app.settings.panel_actions import PanelActionMapping
from scripts.yaml_roundtrip import load_frontmatter


def _staged_conflict() -> KnowledgeWriteConflict:
    receipt = WriteReceipt(
        operation="write_note",
        locator=NoteLocator(vault="Vault", path="note.md"),
        adapter="fs_vault",
        outcome="conflict_staged",
        conflict_artifact="note (conflicted copy runtime).md",
    )
    return KnowledgeWriteConflict(
        "rewritten note conflict staged",
        receipt=receipt,
    )


def _note_content(uuid: str, checked: bool) -> str:
    checkbox = "x" if checked else " "
    return textwrap.dedent(
        f"""
        ---
        uuid: {uuid}
        title: Sample
        ---
        
        ## AI-instruktion
        Gör något fint.
        
        ## AI-åtgärder
        - [{checkbox}] Skapa en separat sammanfattningsanteckning
        """
    ).strip() + "\n"


def _write_snapshot(snapshot_dir: Path, uuid: str, content: str) -> None:
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    (snapshot_dir / f"{uuid}.md").write_text(content, encoding="utf-8")


def _mapping() -> dict[str, PanelActionMapping]:
    return {
        "Skapa en separat sammanfattningsanteckning": PanelActionMapping(
            text="Skapa en separat sammanfattningsanteckning",
            event_type="ask.query.received",
            payload_template={"question": "What now?", "object_id": "svc"},
        )
    }


@pytest.fixture(autouse=True)
def disable_panel_events(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PANEL_EVENTS_ENABLE", "0")
    monkeypatch.setenv("EVENT_ORCHESTRATOR_ENABLE", "1")


def test_process_note_update_happy_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    note_path = tmp_path / "note.md"
    uuid = "note-123"
    snapshot_dir = tmp_path / "snapshots"
    old_content = _note_content(uuid, checked=False)
    new_content = _note_content(uuid, checked=True)
    note_path.write_text(new_content, encoding="utf-8")
    _write_snapshot(snapshot_dir, uuid, old_content)
    monkeypatch.setattr("app.settings.panel_actions.load_panel_action_mappings", lambda: _mapping())
    ctx = OrchestratorContext(settings={"panel_events_enable": False, "origin": "test.note_update"})

    result = process_note_update(note_path, ctx, snapshot_dir=snapshot_dir)

    assert isinstance(result, NoteUpdateResult)
    assert result.uuid == uuid
    assert result.current_path == note_path.resolve()
    assert result.changed is True
    updated = note_path.read_text(encoding="utf-8")
    assert "- [x]" not in updated
    assert "> [!info]- AI status" in updated
    snapshot_text = (snapshot_dir / f"{uuid}.md").read_text(encoding="utf-8")
    assert snapshot_text == updated


def test_process_note_update_changed_writes_via_knowledge_port(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    note_path = tmp_path / "note.md"
    note_uuid = "note-port-1"
    markdown = _note_content(note_uuid, checked=True)
    note_path.write_text(markdown, encoding="utf-8")
    snapshot_dir = tmp_path / "snapshots"
    _write_snapshot(snapshot_dir, note_uuid, _note_content(note_uuid, checked=False))
    writes: list[str] = []

    def _fake_write(
        path: Path, content: str, *, vault_root: Path | None = None, expected_version: str | None = None
    ):  # type: ignore[no-untyped-def]
        writes.append(Path(path).resolve().relative_to(Path(path).anchor).as_posix())
        note_path.write_text(content, encoding="utf-8")
        return None

    monkeypatch.setattr("app.settings.panel_actions.load_panel_action_mappings", lambda: _mapping())
    monkeypatch.setattr("app.services.note_update.write_note_from_absolute", _fake_write)
    ctx = OrchestratorContext(settings={"panel_events_enable": False, "origin": "test.note_update"})

    result = process_note_update(note_path, ctx, snapshot_dir=snapshot_dir)

    assert result.changed is True
    assert writes
    assert "- [x]" not in note_path.read_text(encoding="utf-8")


def test_process_note_update_staged_conflict_returns_stale_before_acknowledgements(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    note_path = tmp_path / "note.md"
    note_uuid = "note-staged-1"
    current = _note_content(note_uuid, checked=True)
    note_path.write_text(current, encoding="utf-8")
    snapshot_dir = tmp_path / "snapshots"
    snapshot_before = _note_content(note_uuid, checked=False)
    _write_snapshot(snapshot_dir, note_uuid, snapshot_before)
    executed_id_writes: list[object] = []

    monkeypatch.setattr("app.settings.panel_actions.load_panel_action_mappings", lambda: _mapping())
    monkeypatch.setattr(
        "app.services.note_update.write_note_from_absolute",
        lambda *args, **kwargs: (_ for _ in ()).throw(_staged_conflict()),
    )
    monkeypatch.setattr(
        panel_writeback,
        "upsert_executed_ids",
        lambda *args, **kwargs: executed_id_writes.append((args, kwargs)),
    )
    monkeypatch.setattr(
        panel_integration,
        "upsert_executed_ids",
        lambda *args, **kwargs: executed_id_writes.append((args, kwargs)),
    )
    monkeypatch.setattr(
        panel_integration,
        "handle_event",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("staged conflict must stop event dispatch")
        ),
    )
    ctx = OrchestratorContext(settings={"panel_events_enable": True, "origin": "test.note_update"})

    result = process_note_update(note_path, ctx, snapshot_dir=snapshot_dir)

    assert result.stale is True
    assert result.changed is False
    assert executed_id_writes == []
    assert (snapshot_dir / f"{note_uuid}.md").read_text(encoding="utf-8") == snapshot_before
    assert note_path.read_text(encoding="utf-8") == current


def test_process_note_update_propagates_receiptless_conflict_before_acknowledgements(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    note_path = tmp_path / "note.md"
    note_uuid = "note-indeterminate-1"
    current = _note_content(note_uuid, checked=True)
    note_path.write_text(current, encoding="utf-8")
    snapshot_dir = tmp_path / "snapshots"
    snapshot_before = _note_content(note_uuid, checked=False)
    _write_snapshot(snapshot_dir, note_uuid, snapshot_before)
    acknowledgements: list[str] = []

    monkeypatch.setattr(
        "app.settings.panel_actions.load_panel_action_mappings",
        lambda: _mapping(),
    )
    monkeypatch.setattr(
        "app.services.note_update.write_note_from_absolute",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            KnowledgeWriteConflict("indeterminate post-exchange failure")
        ),
    )
    monkeypatch.setattr(
        panel_integration,
        "upsert_executed_ids",
        lambda *args, **kwargs: acknowledgements.append("persist_ids"),
    )
    monkeypatch.setattr(
        panel_integration,
        "handle_event",
        lambda *args, **kwargs: acknowledgements.append("dispatch"),
    )

    with pytest.raises(
        KnowledgeWriteConflict,
        match="indeterminate post-exchange failure",
    ):
        process_note_update(
            note_path,
            OrchestratorContext(
                settings={"panel_events_enable": True, "origin": "test.note_update"}
            ),
            snapshot_dir=snapshot_dir,
        )

    assert acknowledgements == []
    assert (snapshot_dir / f"{note_uuid}.md").read_text(encoding="utf-8") == snapshot_before


def test_process_note_update_commits_acknowledgements_only_after_canonical_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    note_path = tmp_path / "note.md"
    note_uuid = "note-ordered-1"
    note_path.write_text(_note_content(note_uuid, checked=True), encoding="utf-8")
    snapshot_dir = tmp_path / "snapshots"
    _write_snapshot(snapshot_dir, note_uuid, _note_content(note_uuid, checked=False))
    order: list[str] = []

    def write_canonical(
        path: Path,
        content: str,
        *,
        vault_root: Path | None = None,
        expected_version: str | None = None,
    ) -> None:
        order.append("write")
        Path(path).write_text(content, encoding="utf-8")

    def persist_ids(*args, **kwargs):  # type: ignore[no-untyped-def]
        order.append("persist_ids")

    def dispatch_event(*args, **kwargs):  # type: ignore[no-untyped-def]
        order.append("dispatch")
        return make_simple_plan(goal="test", source_object_uuid=note_uuid)

    monkeypatch.setattr("app.settings.panel_actions.load_panel_action_mappings", lambda: _mapping())
    monkeypatch.setattr("app.services.note_update.write_note_from_absolute", write_canonical)
    monkeypatch.setattr(panel_integration, "upsert_executed_ids", persist_ids)
    monkeypatch.setattr(panel_integration, "handle_event", dispatch_event)
    ctx = OrchestratorContext(settings={"panel_events_enable": True, "origin": "test.note_update"})

    result = process_note_update(note_path, ctx, snapshot_dir=snapshot_dir)

    assert result.stale is False
    assert result.changed is True
    assert result.dispatch_count == 1
    assert order == ["write", "persist_ids", "dispatch"]
    assert (snapshot_dir / f"{note_uuid}.md").read_text(encoding="utf-8") == note_path.read_text(
        encoding="utf-8"
    )


def test_process_note_update_detects_stale_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    uuid = "note-stale"
    old_content = _note_content(uuid, checked=True)
    original_path = tmp_path / "old" / "note.md"
    original_path.parent.mkdir(parents=True, exist_ok=True)
    original_path.write_text(old_content, encoding="utf-8")
    new_path = tmp_path / "new" / "note.md"
    new_path.parent.mkdir(parents=True, exist_ok=True)
    new_path.write_text(old_content, encoding="utf-8")
    monkeypatch.setattr("app.settings.panel_actions.load_panel_action_mappings", lambda: _mapping())
    ctx = OrchestratorContext(settings={"panel_events_enable": False})

    result = process_note_update(new_path, ctx, expected_path=original_path)

    assert result.stale is True
    assert result.changed is False
    assert new_path.read_text(encoding="utf-8") == old_content


def test_process_note_update_no_panel_noop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    uuid = "note-noop"
    content = textwrap.dedent(
        f"""
        ---
        uuid: {uuid}
        title: Plain
        ---
        
        # Body
        """
    ).strip() + "\n"
    note_path = tmp_path / "note.md"
    note_path.write_text(content, encoding="utf-8")
    snapshot_dir = tmp_path / "snapshots"
    monkeypatch.setattr("app.settings.panel_actions.load_panel_action_mappings", lambda: _mapping())
    ctx = OrchestratorContext(settings={"panel_events_enable": False})

    result = process_note_update(note_path, ctx, snapshot_dir=snapshot_dir)

    assert result.changed is False
    assert result.events_count == 0
    assert note_path.read_text(encoding="utf-8") == content
    snapshot_text = (snapshot_dir / f"{uuid}.md").read_text(encoding="utf-8")
    assert snapshot_text == content


def test_process_note_update_adds_uuid_without_frontmatter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    generated = uuid.UUID("00000000-0000-0000-0000-00000000A001")
    calls: list[str] = []

    def fake_new_note_uuid() -> str:
        # Count only note-identity allocations. Patching the single-purpose
        # seam (not the global ``uuid.uuid4``) keeps this assertion immune to
        # the write adapter's infrastructure UUIDs (``.rewrite-swap`` staging
        # name, ``concurrent-save-*`` conflict-artifact identity), which are a
        # separate concern and must not be conflated with note identity (#3622).
        calls.append("called")
        return str(generated)

    monkeypatch.setattr("app.services.note_uuid._new_note_uuid", fake_new_note_uuid)
    monkeypatch.setattr("app.settings.panel_actions.load_panel_action_mappings", lambda: _mapping())
    note_path = tmp_path / "note.md"
    note_path.write_text("Just content\n", encoding="utf-8")
    snapshot_dir = tmp_path / "snapshots"
    ctx = OrchestratorContext(settings={"panel_events_enable": False})

    first_result = process_note_update(note_path, ctx, snapshot_dir=snapshot_dir)

    assert first_result.uuid == str(generated)
    assert first_result.uuid_added is True
    assert first_result.changed is False
    after_first = note_path.read_text(encoding="utf-8")
    frontmatter, body = load_frontmatter(after_first)
    assert frontmatter["uuid"] == str(generated)
    assert body.strip() == "Just content"
    assert calls == ["called"]
    snapshot_text = (snapshot_dir / f"{first_result.uuid}.md").read_text(encoding="utf-8")
    assert snapshot_text == after_first

    second_result = process_note_update(note_path, ctx, snapshot_dir=snapshot_dir)
    assert second_result.uuid == str(generated)
    assert second_result.uuid_added is False
    assert second_result.changed is False
    assert note_path.read_text(encoding="utf-8") == after_first
    assert calls == ["called"]


def test_process_note_update_adds_uuid_to_frontmatter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    generated = uuid.UUID("00000000-0000-0000-0000-00000000B002")
    monkeypatch.setattr(
        "app.services.note_uuid._new_note_uuid",
        lambda: str(generated),
    )
    monkeypatch.setattr("app.settings.panel_actions.load_panel_action_mappings", lambda: _mapping())
    note_path = tmp_path / "note.md"
    note_path.write_text(
        textwrap.dedent(
            """
            ---
            title: Sample Note
            tags:
              - alpha
              - beta
            ---
            
            Body text
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    snapshot_dir = tmp_path / "snapshots"
    ctx = OrchestratorContext(settings={"panel_events_enable": False})

    result = process_note_update(note_path, ctx, snapshot_dir=snapshot_dir)

    frontmatter, body = load_frontmatter(note_path.read_text(encoding="utf-8"))
    assert frontmatter == {"title": "Sample Note", "tags": ["alpha", "beta"], "uuid": str(generated)}
    assert body.strip() == "Body text"
    assert result.uuid == str(generated)
    assert result.uuid_added is True
    assert result.changed is False
    snapshot_text = (snapshot_dir / f"{result.uuid}.md").read_text(encoding="utf-8")
    assert snapshot_text == note_path.read_text(encoding="utf-8")


def test_process_note_update_preserves_existing_uuid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    note_uuid = "stable-uuid-123"
    content = textwrap.dedent(
        f"""
        ---
        uuid: {note_uuid}
        title: Stable
        ---
        
        Body text
        """
    ).strip() + "\n"
    note_path = tmp_path / "note.md"
    note_path.write_text(content, encoding="utf-8")
    snapshot_dir = tmp_path / "snapshots"
    monkeypatch.setattr("app.settings.panel_actions.load_panel_action_mappings", lambda: _mapping())
    ctx = OrchestratorContext(settings={"panel_events_enable": False})

    first_result = process_note_update(note_path, ctx, snapshot_dir=snapshot_dir)
    after_first = note_path.read_text(encoding="utf-8")

    second_result = process_note_update(note_path, ctx, snapshot_dir=snapshot_dir)

    assert first_result.uuid == note_uuid
    assert second_result.uuid == note_uuid
    assert first_result.uuid_added is False
    assert second_result.uuid_added is False
    assert first_result.changed is False
    assert second_result.changed is False
    assert note_path.read_text(encoding="utf-8") == after_first


def test_process_note_update_handles_malformed_frontmatter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    generated = uuid.UUID("00000000-0000-0000-0000-00000000C003")
    monkeypatch.setattr(
        "app.services.note_uuid._new_note_uuid",
        lambda: str(generated),
    )
    monkeypatch.setattr("app.settings.panel_actions.load_panel_action_mappings", lambda: _mapping())
    note_path = tmp_path / "note.md"
    note_path.write_text(
        textwrap.dedent(
            """
            ---
            title: "Unclosed
            tags: [alpha
            ---

            Body text
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    snapshot_dir = tmp_path / "snapshots"
    ctx = OrchestratorContext(settings={"panel_events_enable": False})

    result = process_note_update(note_path, ctx, snapshot_dir=snapshot_dir)

    assert result.uuid == str(generated)
    assert result.uuid_added is True
    assert result.changed is False
    frontmatter, body = load_frontmatter(note_path.read_text(encoding="utf-8"))
    assert frontmatter == {"uuid": str(generated)}
    assert body.strip() == "Body text"
