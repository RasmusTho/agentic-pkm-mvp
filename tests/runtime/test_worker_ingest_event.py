from __future__ import annotations

import uuid
from pathlib import Path

from app.store.object_store import ObjectStore
from app.vault.paths import get_vault_inbox_dir_rel
from app.workers import outbox_worker
from tests.helpers.pkm_alpha_helper import reset_memory_stores


def test_handle_ingest_vault_changed_ingests_note(tmp_path: Path, monkeypatch) -> None:
    reset_memory_stores()
    monkeypatch.setenv("STORE_BACKEND", "memory")

    vault_root = tmp_path / "vault"
    note_rel = Path(get_vault_inbox_dir_rel(vault_root)) / "_gap_test.md"
    note_path = vault_root / note_rel
    note_path.parent.mkdir(parents=True, exist_ok=True)

    note_uuid = str(uuid.uuid4())
    note_path.write_text(
        f"---\nuuid: [[{note_uuid}]]\n---\n\nGAP_TEST_MARKER: worker-ingest\n",
        encoding="utf-8",
    )

    payload = {
        "vault_path": str(note_path),
        "relative_path": str(note_rel),
        "hash": "test-hash",
        "mtime": 123.0,
    }

    summary = outbox_worker.handle_ingest_vault_changed(payload, vault_root=vault_root)
    assert summary.ingested == 1

    obj = ObjectStore().get_object(note_uuid)
    assert obj is not None
    assert "GAP_TEST_MARKER" in str(obj.payload.get("raw_text") or obj.payload.get("text") or "")
