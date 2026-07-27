import json
import importlib
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from app.knowledge.multiwriter import is_conflict_artifact
from app.knowledge.write_ops import write_note_from_absolute
from app.settings.panel_actions import PanelActionMapping
import app.watcher.vault_watcher as watcher_module
from app.watcher.vault_watcher import VaultWatcher, compute_changes, load_snapshot, run_watcher_tick, save_snapshot


def _write_note(base: Path, rel: str, content: str = "Body") -> Path:
    path = base / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_first_run_marks_all_changed(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _write_note(vault, "Concepts/A.md")
    _write_note(vault, "Concepts/B.md")

    watcher = VaultWatcher(vault, snapshot_path=vault / ".state.json")
    result = watcher.run()

    assert set(p.relative_to(vault) for p in result.changed) == {
        Path("Concepts/A.md"),
        Path("Concepts/B.md"),
    }
    assert result.deleted == []
    assert load_snapshot(vault / ".state.json")


def test_second_run_detects_only_modified(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    a = _write_note(vault, "Concepts/A.md")
    b = _write_note(vault, "Concepts/B.md")

    watcher = VaultWatcher(vault, snapshot_path=vault / ".state.json")
    first = watcher.run()
    assert len(first.changed) == 2

    time.sleep(0.01)
    b.write_text("Updated", encoding="utf-8")

    second = watcher.run()
    assert second.deleted == []
    assert set(p.relative_to(vault) for p in second.changed) == {Path("Concepts/B.md")}


def test_detects_new_and_deleted_files(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    a = _write_note(vault, "Concepts/A.md")
    _write_note(vault, "Concepts/B.md")

    snapshot_path = vault / ".state.json"
    save_snapshot(snapshot_path, {"Concepts/A.md": a.stat().st_mtime})

    changed, deleted, current = compute_changes(vault, load_snapshot(snapshot_path))
    assert set(p.relative_to(vault) for p in changed) == {Path("Concepts/B.md")}
    assert set(p.relative_to(vault) for p in deleted) == set()
    assert "Concepts/A.md" in current
    assert "Concepts/B.md" in current


def test_run_watcher_tick_emits_event_when_no_changes(tmp_path: Path, monkeypatch) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    outbox = tmp_path / "events.jsonl"
    telemetry_log = tmp_path / "watcher_run.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox))
    # Route watcher.run telemetry to a controlled tmp path (not the default tmp/ dir).
    monkeypatch.setenv("WATCHER_RUN_LOG_PATH", str(telemetry_log))

    summary, _ = run_watcher_tick(
        vault_root=vault,
        snapshot_path=vault / ".state.json",
        skip_panel=True,
        emit_only=True,
        dry_run=False,
        max_notes=10,
        force=False,
        outbox_path=None,
    )

    assert summary["changed"] == 0
    # watcher.run events must land in the dedicated telemetry log, not index-outbox.
    payloads = [json.loads(line) for line in telemetry_log.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert any(ev.get("event") == "watcher.run" for ev in payloads)
    # index-outbox must NOT contain watcher.run records.
    if outbox.exists():
        outbox_payloads = [json.loads(line) for line in outbox.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert not any(ev.get("event") == "watcher.run" for ev in outbox_payloads)


def test_run_watcher_tick_uses_watcher_settings_default_when_env_unset(tmp_path: Path, monkeypatch) -> None:
    vault = tmp_path / "vault"
    inbox = vault / "Inbox"
    inbox.mkdir(parents=True)
    (inbox / "n.md").write_text(
        "---\ntitle: N\n---\n\n%% AI:Start %%\n- [ ] Do thing\n%% AI:End %%\n",
        encoding="utf-8",
    )
    settings_dir = vault / "@Settings"
    settings_dir.mkdir(parents=True, exist_ok=True)
    (settings_dir / "watchers.md").write_text(
        "---\nauto_run:\n  auto_exec_env: WATCHER_AUTO_EXEC\n  auto_exec_default: false\n---\n",
        encoding="utf-8",
    )
    outbox = tmp_path / "events.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox))
    monkeypatch.delenv("WATCHER_AUTO_EXEC", raising=False)
    monkeypatch.setattr(
        "app.watcher.vault_watcher.run_vault_alpha_ingest_paths",
        lambda *_args, **_kwargs: SimpleNamespace(ingested=1, errors=0),
    )
    monkeypatch.setattr(
        "app.watcher.vault_watcher.handle_note_update",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("panel runtime should not run")),
    )

    summary, _ = run_watcher_tick(
        vault_root=vault,
        snapshot_path=vault / ".state.json",
        skip_panel=False,
        emit_only=False,
        dry_run=False,
        max_notes=10,
        force=False,
        outbox_path=None,
    )

    assert summary["panel_candidates"] == 1
    assert summary["panel_skipped_auto_exec"] == 1


def test_watcher_panel_writeback_uses_canonical_identity_for_retained_uuid(
    tmp_path: Path, monkeypatch
) -> None:
    """A retained frontmatter UUID must never mint a second canonical parent."""
    vault = tmp_path / "vault"
    inbox = vault / "Inbox"
    inbox.mkdir(parents=True)
    vault_uuid = str(uuid4())
    canonical_id = str(uuid4())
    note = inbox / "retained.md"
    note.write_text(
        "---\n"
        f"uuid: {vault_uuid}\n"
        "ai_panel_auto_run: watcher\n"
        "---\n\n"
        "%% AI:Start %%\n"
        "- [x] Do thing\n"
        "%% AI:End %%\n",
        encoding="utf-8",
    )

    canonical = SimpleNamespace(
        uuid=canonical_id,
        kind="note",
        payload={},
        source_ref=str(note),
        created_at=datetime.now(timezone.utc),
    )
    rows = {canonical_id: canonical}

    class FakeObjectStore:
        def get_object(self, object_id: str, **_kwargs):
            return rows.get(object_id)

        def save_object(self, obj, **_kwargs) -> None:
            rows[obj.uuid] = obj

    monkeypatch.setenv("WATCHER_AUTO_EXEC", "1")
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(tmp_path / "events.jsonl"))
    monkeypatch.setenv("WATCHER_RUN_LOG_PATH", str(tmp_path / "watcher_run.jsonl"))
    monkeypatch.setattr(
        "app.watcher.vault_watcher.run_vault_alpha_ingest_paths",
        lambda *_args, **_kwargs: SimpleNamespace(ingested=1, errors=0),
    )
    monkeypatch.setattr(
        "app.watcher.vault_watcher.resolve_canonical_object_id",
        lambda value: canonical_id if value == vault_uuid else value,
    )
    monkeypatch.setattr("app.watcher.vault_watcher.ObjectStore", FakeObjectStore)
    panel_agent_module = importlib.import_module("app.agents.panel.agent")
    panel_writeback_module = importlib.import_module("app.agents.panel.writeback")
    monkeypatch.setattr(panel_agent_module, "ObjectStore", FakeObjectStore)
    monkeypatch.setattr(panel_writeback_module, "ObjectStore", FakeObjectStore)

    summary, _ = run_watcher_tick(
        vault_root=vault,
        snapshot_path=vault / ".state.json",
        skip_panel=False,
        emit_only=False,
        dry_run=False,
        max_notes=10,
        force=False,
        outbox_path=None,
    )

    assert summary["applied_actions"] == 1
    assert set(rows) == {canonical_id}
    assert rows[canonical_id].payload["executed_action_ids"]


def test_vault_watcher_stale_panel_write_has_no_acknowledgement_effects(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vault = tmp_path / "vault"
    inbox = vault / "Inbox"
    inbox.mkdir(parents=True)
    note = inbox / "stale.md"
    note.write_text(
        "---\n"
        "uuid: note-stale-watcher\n"
        "ai_panel_auto_run: watcher\n"
        "---\n\n"
        "%% AI:Start %%\n"
        "## AI-åtgärder\n"
        "- [x] Do thing\n"
        "%% AI:End %%\n",
        encoding="utf-8",
    )
    concurrent = "Concurrent human snapshot\n"
    persisted_ids: list[object] = []
    emitted_events: list[object] = []
    mapping = PanelActionMapping(
        text="Do thing",
        event_type="promote.intent.created",
        payload_template={"maturity": "evergreen"},
        action_id="promote.evergreen",
    )

    class EmptyObjectStore:
        def get_object(self, *_args, **_kwargs):
            return None

    monkeypatch.setenv("WATCHER_AUTO_EXEC", "1")
    monkeypatch.setenv("WATCHER_RUN_LOG_PATH", str(tmp_path / "watcher-run.jsonl"))
    monkeypatch.setattr(
        watcher_module,
        "run_vault_alpha_ingest_paths",
        lambda *_args, **_kwargs: SimpleNamespace(ingested=1, errors=0),
    )
    monkeypatch.setattr(
        watcher_module,
        "load_panel_action_mappings",
        lambda: {"Do thing": mapping},
    )
    monkeypatch.setattr(
        watcher_module,
        "_disallowed_actions",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(watcher_module, "ObjectStore", EmptyObjectStore)
    panel_agent_module = importlib.import_module("app.agents.panel.agent")
    monkeypatch.setattr(panel_agent_module, "ObjectStore", EmptyObjectStore)
    monkeypatch.setattr(
        watcher_module,
        "upsert_executed_ids",
        lambda *args, **kwargs: persisted_ids.append((args, kwargs)),
    )
    monkeypatch.setattr(
        watcher_module,
        "_write_outbox_events",
        lambda _path, events: emitted_events.extend(events),
    )

    def interleave_human_write(
        path: Path,
        content: str,
        **kwargs: object,
    ):
        note.write_text(concurrent, encoding="utf-8")
        return write_note_from_absolute(path, content, **kwargs)

    monkeypatch.setattr(
        watcher_module,
        "write_note_from_absolute",
        interleave_human_write,
    )

    summary, messages = run_watcher_tick(
        vault_root=vault,
        snapshot_path=vault / ".state.json",
        skip_panel=False,
        emit_only=False,
        dry_run=False,
        max_notes=10,
        force=False,
        outbox_path=tmp_path / "events.jsonl",
    )

    assert summary["errors"] == 1
    assert summary["applied_actions"] == 0
    assert persisted_ids == []
    assert emitted_events == []
    assert note.read_text(encoding="utf-8") == concurrent
    assert any("stale write staged" in message for message in messages)
    artifacts = [
        path
        for path in note.parent.iterdir()
        if path != note and is_conflict_artifact(path.name)
    ]
    assert len(artifacts) == 1
    staged = artifacts[0].read_text(encoding="utf-8")
    assert "Do thing" in staged
    assert staged != concurrent


def test_vault_watcher_emit_only_emits_created_without_acknowledgement_effects(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vault = tmp_path / "vault"
    inbox = vault / "Inbox"
    inbox.mkdir(parents=True)
    note = inbox / "emit-only.md"
    original = (
        "---\n"
        "uuid: note-emit-only\n"
        "ai_panel_auto_run: watcher\n"
        "---\n\n"
        "%% AI:Start %%\n"
        "- [x] Do thing\n"
        "%% AI:End %%\n"
    )
    note.write_text(original, encoding="utf-8")
    persisted_ids: list[object] = []
    emitted_events: list[object] = []
    events = [
        SimpleNamespace(event="panel.intent.created"),
        SimpleNamespace(event="panel.intent.executed"),
        SimpleNamespace(event="promote.intent.created"),
    ]
    prepared = SimpleNamespace(
        state=SimpleNamespace(actions=[]),
        intents=[SimpleNamespace(kind="action_triggered")],
        events=events,
        updated_markdown="Prepared but intentionally not written\n",
        executed_action_ids=["action-1"],
    )

    class EmptyObjectStore:
        def get_object(self, *_args, **_kwargs):
            return None

    monkeypatch.setenv("WATCHER_AUTO_EXEC", "1")
    monkeypatch.setenv("WATCHER_RUN_LOG_PATH", str(tmp_path / "watcher-run.jsonl"))
    monkeypatch.setattr(
        watcher_module,
        "run_vault_alpha_ingest_paths",
        lambda *_args, **_kwargs: SimpleNamespace(ingested=1, errors=0),
    )
    monkeypatch.setattr(
        watcher_module,
        "handle_note_update",
        lambda *args, **kwargs: prepared,
    )
    monkeypatch.setattr(
        watcher_module,
        "_disallowed_actions",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(watcher_module, "ObjectStore", EmptyObjectStore)
    monkeypatch.setattr(
        watcher_module,
        "upsert_executed_ids",
        lambda *args, **kwargs: persisted_ids.append((args, kwargs)),
    )
    monkeypatch.setattr(
        watcher_module,
        "_write_outbox_events",
        lambda _path, selected: emitted_events.extend(selected),
    )
    monkeypatch.setattr(
        watcher_module,
        "write_note_from_absolute",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("emit-only must not write canonical Markdown")
        ),
    )

    summary, _ = run_watcher_tick(
        vault_root=vault,
        snapshot_path=vault / ".state.json",
        skip_panel=False,
        emit_only=True,
        dry_run=False,
        max_notes=10,
        force=False,
        outbox_path=tmp_path / "events.jsonl",
    )

    assert summary["applied_actions"] == 0
    assert persisted_ids == []
    assert [event.event for event in emitted_events] == ["panel.intent.created"]
    assert note.read_text(encoding="utf-8") == original
