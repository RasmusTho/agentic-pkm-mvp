from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from app.services.companion_note import read_companion
from app.store.object_store import ObjectStore
from app.workers import outbox_worker
from app.events.types import INGEST_VAULT_CHANGED, PANEL_SCAN_REQUESTED
from scripts.yaml_roundtrip import load_frontmatter
from tests.helpers.pkm_alpha_helper import reset_memory_stores


def _read_events(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [
        str((json.loads(line) or {}).get("event") or "")
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _write_layout_note(vault_root: Path, *, inbox_folder: str) -> None:
    system = vault_root / "⚙️ System"
    system.mkdir(parents=True, exist_ok=True)
    note = system / "vault.layout.md"
    note.write_text(
        "---\n"
        "version: '1'\n"
        "system_folder: '⚙️ System'\n"
        f"inbox_folder: '{inbox_folder}'\n"
        "desk_folder: '🛠️ Workbench'\n"
        "root_folders: []\n"
        "---\n\n"
        "# layout\n",
        encoding="utf-8",
    )


def test_handle_ingest_vault_changed_ingests_note(tmp_path: Path, monkeypatch) -> None:
    reset_memory_stores()
    monkeypatch.setenv("STORE_BACKEND", "memory")

    vault_root = tmp_path / "vault"
    inbox = vault_root / "Inbox"
    inbox.mkdir(parents=True, exist_ok=True)

    note_path = inbox / "_gap_test.md"

    note_uuid = str(uuid.uuid4())
    note_path.write_text(
        f"---\nuuid: [[{note_uuid}]]\n---\n\nGAP_TEST_MARKER: worker-ingest\n",
        encoding="utf-8",
    )

    payload = {
        "vault_path": str(note_path),
        "relative_path": "Inbox/_gap_test.md",
        "hash": "test-hash",
        "mtime": 123.0,
    }

    summary = outbox_worker.handle_ingest_vault_changed(payload, vault_root=vault_root)
    assert summary.ingested == 1

    obj = ObjectStore().get_object(note_uuid)
    assert obj is not None
    assert "GAP_TEST_MARKER" in str(obj.payload.get("raw_text") or obj.payload.get("text") or "")


def test_handle_ingest_vault_changed_heals_uuid_using_vault_layout_inbox(
    tmp_path: Path, monkeypatch
) -> None:
    reset_memory_stores()
    monkeypatch.setenv("STORE_BACKEND", "memory")

    vault_root = tmp_path / "vault"
    _write_layout_note(vault_root, inbox_folder="📥 Inbox")

    inbox = vault_root / "📥 Inbox"
    inbox.mkdir(parents=True, exist_ok=True)

    note_path = inbox / "uuidless.md"
    note_path.write_text(
        "---\n"
        "title: uuidless\n"
        "---\n\n"
        "Body\n",
        encoding="utf-8",
    )

    monkeypatch.delenv("VAULT_INBOX_DIR_REL", raising=False)

    payload = {
        "vault_path": str(note_path),
        "relative_path": "📥 Inbox/uuidless.md",
        "hash": "test-hash",
        "mtime": 123.0,
    }

    summary = outbox_worker.handle_ingest_vault_changed(payload, vault_root=vault_root)
    assert summary.ingested == 1

    healed_raw = note_path.read_text(encoding="utf-8")
    frontmatter, _ = load_frontmatter(healed_raw)
    assert isinstance(frontmatter, dict)
    healed_uuid = str(frontmatter.get("uuid") or "").strip()
    assert healed_uuid
    companion = read_companion(vault_root, healed_uuid)
    assert companion is not None, "Companion note should exist after ingest"
    assert companion.uuid == healed_uuid
    assert companion.source_ref == "📥 Inbox/uuidless.md"

    obj = ObjectStore().get_object(healed_uuid)
    assert obj is not None


def test_handle_ingest_vault_changed_creates_companion_for_existing_uuid(
    tmp_path: Path, monkeypatch
) -> None:
    reset_memory_stores()
    monkeypatch.setenv("STORE_BACKEND", "memory")

    vault_root = tmp_path / "vault"
    inbox = vault_root / "📥 Inbox"
    inbox.mkdir(parents=True, exist_ok=True)

    note_uuid = str(uuid.uuid4())
    note_path = inbox / "existing-uuid.md"
    note_path.write_text(
        f"---\nuuid: {note_uuid}\ntitle: Existing UUID\n---\n\nBody\n",
        encoding="utf-8",
    )

    payload = {
        "vault_path": str(note_path),
        "relative_path": "📥 Inbox/existing-uuid.md",
        "hash": "test-hash",
        "mtime": 123.0,
    }

    summary = outbox_worker.handle_ingest_vault_changed(payload, vault_root=vault_root)
    assert summary.ingested == 1

    companion = read_companion(vault_root, note_uuid)
    assert companion is not None, "Companion note should exist after ingest"
    assert companion.uuid == note_uuid
    assert companion.source_ref == "📥 Inbox/existing-uuid.md"


def test_handle_ingest_vault_changed_heals_uuid_outside_inbox(
    tmp_path: Path, monkeypatch
) -> None:
    reset_memory_stores()
    monkeypatch.setenv("STORE_BACKEND", "memory")

    vault_root = tmp_path / "vault"
    workbench = vault_root / "🛠️ Workbench"
    workbench.mkdir(parents=True, exist_ok=True)

    note_path = workbench / "uuidless.md"
    note_path.write_text(
        "---\n"
        "title: uuidless-workbench\n"
        "---\n\n"
        "Body\n",
        encoding="utf-8",
    )

    payload = {
        "vault_path": str(note_path),
        "relative_path": "🛠️ Workbench/uuidless.md",
        "hash": "test-hash",
        "mtime": 123.0,
    }

    summary = outbox_worker.handle_ingest_vault_changed(payload, vault_root=vault_root)
    assert summary.ingested == 1

    healed_raw = note_path.read_text(encoding="utf-8")
    frontmatter, _ = load_frontmatter(healed_raw)
    assert isinstance(frontmatter, dict)
    healed_uuid = str(frontmatter.get("uuid") or "").strip()
    assert healed_uuid
    companion = read_companion(vault_root, healed_uuid)
    assert companion is not None
    assert companion.source_ref == "🛠️ Workbench/uuidless.md"


def test_handle_ingest_vault_changed_uses_relative_path_when_payload_path_is_host_absolute(
    tmp_path: Path, monkeypatch
) -> None:
    reset_memory_stores()
    monkeypatch.setenv("STORE_BACKEND", "memory")

    mounted_vault_root = tmp_path / "mounted-vault"
    inbox = mounted_vault_root / "📥 Inbox"
    inbox.mkdir(parents=True, exist_ok=True)

    note_uuid = str(uuid.uuid4())
    note_path = inbox / "host-path-note.md"
    note_path.write_text(
        f"---\nuuid: {note_uuid}\n---\n\nRuntime path translation works.\n",
        encoding="utf-8",
    )

    host_style_root = Path("/Users/rasmus/Library/Mobile Documents/iCloud~md~obsidian/Documents/PKM - Alpha")
    payload = {
        "vault_path": str(host_style_root / "📥 Inbox" / "host-path-note.md"),
        "relative_path": "📥 Inbox/host-path-note.md",
        "hash": "test-hash",
        "mtime": 123.0,
    }

    summary = outbox_worker.handle_ingest_vault_changed(payload, vault_root=mounted_vault_root)
    assert summary.ingested == 1

    obj = ObjectStore().get_object(note_uuid)
    assert obj is not None
    assert "Runtime path translation works." in str(obj.payload.get("raw_text") or obj.payload.get("text") or "")


def test_handle_ingest_vault_changed_skips_missing_note(tmp_path: Path, monkeypatch) -> None:
    reset_memory_stores()
    monkeypatch.setenv("STORE_BACKEND", "memory")

    vault_root = tmp_path / "vault"
    (vault_root / "📥 Inbox").mkdir(parents=True, exist_ok=True)

    payload = {
        "vault_path": str(vault_root / "📥 Inbox" / "missing.md"),
        "relative_path": "📥 Inbox/missing.md",
        "hash": "test-hash",
        "mtime": 123.0,
    }

    summary = outbox_worker.handle_ingest_vault_changed(payload, vault_root=vault_root)
    assert summary.ingested == 0


def test_handle_panel_scan_requested_emits_panel_events(tmp_path: Path, monkeypatch) -> None:
    reset_memory_stores()
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("PANEL_AGENT_DECIDER", "rule")
    outbox_path = tmp_path / "index-outbox.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))

    vault_root = tmp_path / "vault"
    inbox = vault_root / "📥 Inbox"
    inbox.mkdir(parents=True, exist_ok=True)

    note_uuid = str(uuid.uuid4())
    note_path = inbox / "panel-note.md"
    note_path.write_text(
        "---\n"
        f"uuid: {note_uuid}\n"
        "ai_panel_auto_run: watcher\n"
        "---\n"
        "%% AI:Start %%\n"
        "## AI-instruktion\n"
        "Promote this test note when checked.\n\n"
        "## AI-åtgärder\n"
        "- [x] Make this note evergreen <!--ai:id=promote.evergreen-->\n\n"
        "## AI-logg\n"
        "%% AI:End %%\n",
        encoding="utf-8",
    )

    payload = {
        "vault_path": str(note_path),
        "relative_path": "📥 Inbox/panel-note.md",
        "hash": "test-hash",
        "mtime": 123.0,
    }

    summary = outbox_worker.handle_panel_scan_requested(payload, vault_root=vault_root)
    events = _read_events(outbox_path)
    assert summary.emitted >= 3
    assert "panel.intent.created" in events
    assert "panel.intent.executed" in events
    assert "promote.intent.created" in events


def test_handle_panel_scan_requested_emits_promotion_after_checked_transition(
    tmp_path: Path, monkeypatch
) -> None:
    reset_memory_stores()
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("PANEL_AGENT_DECIDER", "rule")
    outbox_path = tmp_path / "index-outbox.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))

    vault_root = tmp_path / "vault"
    inbox = vault_root / "📥 Inbox"
    inbox.mkdir(parents=True, exist_ok=True)

    note_uuid = str(uuid.uuid4())
    note_path = inbox / "panel-transition.md"
    unchecked = (
        "---\n"
        f"uuid: {note_uuid}\n"
        "ai_panel_auto_run: watcher\n"
        "---\n"
        "%% AI:Start %%\n"
        "## AI-instruktion\n"
        "Promote this test note when checked.\n\n"
        "## AI-åtgärder\n"
        "- [ ] Make this note evergreen <!--ai:id=promote.evergreen-->\n\n"
        "## AI-logg\n"
        "%% AI:End %%\n"
    )
    note_path.write_text(unchecked, encoding="utf-8")

    payload = {
        "vault_path": str(note_path),
        "relative_path": "📥 Inbox/panel-transition.md",
        "hash": "test-hash",
        "mtime": 123.0,
        "trace_id": "trace-transition",
    }

    seed_summary = outbox_worker.handle_panel_scan_requested(payload, vault_root=vault_root)
    assert seed_summary.emitted >= 1

    checked = unchecked.replace("- [ ]", "- [x]")
    note_path.write_text(checked, encoding="utf-8")

    summary = outbox_worker.handle_panel_scan_requested(payload, vault_root=vault_root)
    events = _read_events(outbox_path)
    assert summary.emitted >= 4
    assert "panel.intent.created" in events
    assert "panel.intent.executed" in events
    assert "promote.intent.created" in events


def test_handle_panel_scan_requested_defers_unstable_file(tmp_path: Path, monkeypatch) -> None:
    reset_memory_stores()
    monkeypatch.setenv("STORE_BACKEND", "memory")

    vault_root = tmp_path / "vault"
    inbox = vault_root / "📥 Inbox"
    inbox.mkdir(parents=True, exist_ok=True)

    note_path = inbox / "panel-note.md"
    note_path.write_text("stub", encoding="utf-8")

    monkeypatch.setattr(outbox_worker, "_stabilized_note_text", lambda *_args, **_kwargs: None)

    payload = {
        "vault_path": str(note_path),
        "relative_path": "📥 Inbox/panel-note.md",
        "hash": "test-hash",
        "mtime": 123.0,
    }

    summary = outbox_worker.handle_panel_scan_requested(payload, vault_root=vault_root)
    assert summary.emitted == 0
    assert summary.deferred is True


def test_handle_panel_scan_requested_queues_retry_for_unstable_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reset_memory_stores()
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DB_DSN", raising=False)

    vault_root = tmp_path / "vault"
    inbox = vault_root / "📥 Inbox"
    inbox.mkdir(parents=True, exist_ok=True)

    note_path = inbox / "panel-note.md"
    note_path.write_text("stub", encoding="utf-8")

    monkeypatch.setattr(outbox_worker, "_stabilized_note_text", lambda *_args, **_kwargs: None)

    queued: list[tuple[Path, object, str]] = []

    def fake_append(path: Path, event, default_source: str = "worker") -> None:
        queued.append((path, event, default_source))

    monkeypatch.setattr(outbox_worker, "append_jsonl_outbox_event", fake_append)

    payload = {
        "vault_path": str(note_path),
        "relative_path": "📥 Inbox/panel-note.md",
        "hash": "test-hash",
        "mtime": 123.0,
    }

    summary = outbox_worker.handle_panel_scan_requested(payload, vault_root=vault_root, trace_id="trace-panel-envelope")
    assert summary.emitted == 0
    assert summary.deferred is True
    assert len(queued) == 1

    retry_event = queued[0][1]
    assert retry_event.event_type == PANEL_SCAN_REQUESTED
    assert retry_event.trace_id == "trace-panel-envelope"
    assert retry_event.payload["_worker_retry_count"] == 1
    assert retry_event.payload["_worker_retry_reason"] == "file_unstable"


def test_handle_panel_scan_requested_aborts_when_retry_enqueue_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reset_memory_stores()
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DB_DSN", raising=False)

    vault_root = tmp_path / "vault"
    inbox = vault_root / "📥 Inbox"
    inbox.mkdir(parents=True, exist_ok=True)

    note_path = inbox / "panel-note.md"
    note_path.write_text("stub", encoding="utf-8")

    monkeypatch.setattr(outbox_worker, "_stabilized_note_text", lambda *_args, **_kwargs: None)

    def fail_append(*_args, **_kwargs) -> None:
        raise OSError("outbox unavailable")

    monkeypatch.setattr(outbox_worker, "append_jsonl_outbox_event", fail_append)

    payload = {
        "vault_path": str(note_path),
        "relative_path": "📥 Inbox/panel-note.md",
        "hash": "test-hash",
        "mtime": 123.0,
    }

    with pytest.raises(outbox_worker.TransientRetryEnqueueError):
        outbox_worker.handle_panel_scan_requested(payload, vault_root=vault_root, trace_id="trace-panel-envelope")


def test_handle_panel_scan_requested_drops_missing_uuid_after_retry_budget_exhausted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reset_memory_stores()
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DB_DSN", raising=False)

    vault_root = tmp_path / "vault"
    inbox = vault_root / "📥 Inbox"
    inbox.mkdir(parents=True, exist_ok=True)

    note_path = inbox / "panel-note.md"
    note_path.write_text("---\ntitle: No UUID\n---\nbody\n", encoding="utf-8")

    monkeypatch.setattr(outbox_worker, "_maybe_heal_uuid", lambda *_args, **_kwargs: "")

    payload = {
        "vault_path": str(note_path),
        "relative_path": "📥 Inbox/panel-note.md",
        "hash": "test-hash",
        "mtime": 123.0,
        "_worker_retry_count": 3,
    }

    summary = outbox_worker.handle_panel_scan_requested(payload, vault_root=vault_root, trace_id="trace-panel-envelope")
    assert summary.emitted == 0
    assert summary.deferred is False


def test_handle_ingest_vault_changed_queues_retry_for_missing_note(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reset_memory_stores()
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DB_DSN", raising=False)

    vault_root = tmp_path / "vault"
    (vault_root / "📥 Inbox").mkdir(parents=True, exist_ok=True)
    note_path = vault_root / "📥 Inbox" / "missing.md"

    queued: list[tuple[Path, object, str]] = []

    def fake_append(path: Path, event, default_source: str = "worker") -> None:
        queued.append((path, event, default_source))

    monkeypatch.setattr(outbox_worker, "append_jsonl_outbox_event", fake_append)

    payload = {
        "vault_path": str(note_path),
        "relative_path": "📥 Inbox/missing.md",
        "hash": "test-hash",
        "mtime": 123.0,
    }

    summary = outbox_worker.handle_ingest_vault_changed(payload, vault_root=vault_root, trace_id="trace-ingest-envelope")
    assert summary.ingested == 0
    assert len(queued) == 1

    retry_event = queued[0][1]
    assert retry_event.event_type == INGEST_VAULT_CHANGED
    assert retry_event.trace_id == "trace-ingest-envelope"
    assert retry_event.payload["_worker_retry_count"] == 1
    assert retry_event.payload["_worker_retry_reason"] == "missing_or_unstable_note"


def test_handle_ingest_vault_changed_aborts_when_retry_enqueue_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reset_memory_stores()
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DB_DSN", raising=False)

    vault_root = tmp_path / "vault"
    (vault_root / "📥 Inbox").mkdir(parents=True, exist_ok=True)
    note_path = vault_root / "📥 Inbox" / "missing.md"

    def fail_append(*_args, **_kwargs) -> None:
        raise OSError("outbox unavailable")

    monkeypatch.setattr(outbox_worker, "append_jsonl_outbox_event", fail_append)

    payload = {
        "vault_path": str(note_path),
        "relative_path": "📥 Inbox/missing.md",
        "hash": "test-hash",
        "mtime": 123.0,
    }

    with pytest.raises(outbox_worker.TransientRetryEnqueueError):
        outbox_worker.handle_ingest_vault_changed(payload, vault_root=vault_root, trace_id="trace-ingest-envelope")
