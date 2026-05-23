from __future__ import annotations

import errno
from pathlib import Path

from app.services.note_uuid import ensure_note_uuid as real_ensure_note_uuid
from app.objects import ObjectStore
from app.workers import outbox_worker
from scripts.yaml_roundtrip import load_frontmatter
from tests.runtime.test_worker_ingest_event import _write_layout_note
from tests.helpers.pkm_alpha_helper import reset_memory_stores


def test_handle_ingest_vault_changed_retries_uuid_heal_on_eperm(tmp_path: Path, monkeypatch) -> None:
    reset_memory_stores()
    monkeypatch.setenv("STORE_BACKEND", "memory")

    vault_root = tmp_path / "vault"
    _write_layout_note(vault_root, inbox_folder="📥 Inbox")

    inbox = vault_root / "📥 Inbox"
    inbox.mkdir(parents=True, exist_ok=True)

    note_path = inbox / "uuidless_retry.md"
    note_path.write_text(
        "---\n"
        "title: uuidless_retry\n"
        "---\n\n"
        "Body\n",
        encoding="utf-8",
    )

    monkeypatch.delenv("VAULT_INBOX_DIR_REL", raising=False)

    attempts = {"n": 0}

    def flaky_ensure(path: Path, *, preferred_uuid: str | None = None) -> str:
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise OSError(errno.EPERM, "Operation not permitted")
        return real_ensure_note_uuid(path, preferred_uuid=preferred_uuid)

    monkeypatch.setattr(outbox_worker, "ensure_note_uuid", flaky_ensure)
    monkeypatch.setattr(outbox_worker.time, "sleep", lambda _seconds: None)

    payload = {
        "vault_path": str(note_path),
        "relative_path": "📥 Inbox/uuidless_retry.md",
        "hash": "test-hash",
        "mtime": 123.0,
    }

    summary = outbox_worker.handle_ingest_vault_changed(payload, vault_root=vault_root)
    assert summary.ingested == 1
    assert attempts["n"] == 3

    healed_raw = note_path.read_text(encoding="utf-8")
    frontmatter, _ = load_frontmatter(healed_raw)
    assert isinstance(frontmatter, dict)
    healed_uuid = str(frontmatter.get("uuid") or "").strip()
    assert healed_uuid

    obj = ObjectStore().get_object(healed_uuid)
    assert obj is not None
