from __future__ import annotations

import json
import uuid
from pathlib import Path

from app.services.note_log import note_log_path
from app.store.object_store import ObjectStore
from app.workers import outbox_worker
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
    mirror_path = vault_root / note_log_path(healed_uuid, Path("📥 Inbox/uuidless.md"))
    assert mirror_path.exists()
    mirror_frontmatter, _ = load_frontmatter(mirror_path.read_text(encoding="utf-8"))
    assert mirror_frontmatter.get("uuid") == healed_uuid
    assert mirror_frontmatter.get("source_ref") == "📥 Inbox/uuidless.md"

    obj = ObjectStore().get_object(healed_uuid)
    assert obj is not None


def test_handle_ingest_vault_changed_creates_missing_mirror_for_existing_uuid(
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

    mirror_path = vault_root / note_log_path(note_uuid, Path("📥 Inbox/existing-uuid.md"))
    assert mirror_path.exists()
    mirror_frontmatter, _ = load_frontmatter(mirror_path.read_text(encoding="utf-8"))
    assert mirror_frontmatter.get("uuid") == note_uuid
    assert mirror_frontmatter.get("source_ref") == "📥 Inbox/existing-uuid.md"


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
