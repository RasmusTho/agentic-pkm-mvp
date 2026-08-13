from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.heimdal.raw_store import (
    compute_raw_content_identity,
    encrypt_raw_bytes,
    insert_raw_record,
    reset_memory_raw_store,
)
from app.heimdal.retention import (
    REASON_SCREEN_FRAME_RETENTION_BUFFER,
    RetentionWindowMissingError,
    enforce_screen_frame_retention,
    reset_memory_deletion_receipts,
)
from app.heimdal.settings_notes import SETTINGS, SettingsNote, write_settings_note
from app.write_guard import WriteGuard

pytestmark = pytest.mark.not_pg


@pytest.fixture(autouse=True)
def reset(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("STORE_BACKEND", "memory")
    reset_memory_raw_store(); reset_memory_deletion_receipts()


def test_frames_age_out_bounded_and_receipted(tmp_path):
    root = tmp_path / "vault"; root.mkdir()
    with pytest.raises(RetentionWindowMissingError): enforce_screen_frame_retention(vault_root=root)
    write_settings_note(root, SettingsNote(spec=SETTINGS, values={"screen_frame_retention_minutes": 1}), write_guard=WriteGuard(lambda: {"state": "healthy"}))
    ciphertext, nonce = encrypt_raw_bytes(b"frame", key=b"x" * 32)
    insert_raw_record(content_identity=compute_raw_content_identity(b"frame"), capture_chain=["screen"], sensor={"machine": "mac"}, consent={"grant_ref": "g"}, ciphertext=ciphertext, nonce=nonce, key_ref="test", key=b"x" * 32, source_path="screen", payload={"modality": "screen"})
    result = enforce_screen_frame_retention(vault_root=root, now=datetime.now(timezone.utc) + timedelta(minutes=2))
    assert result.deleted_count == 1
    assert result.deletions[0].reason == REASON_SCREEN_FRAME_RETENTION_BUFFER
    assert result.deletions[0].payload["screen_frame_retention_minutes"] == 1
