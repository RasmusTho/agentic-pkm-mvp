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
from app.vault.manager import VaultManager
from app.vault.settings_service import SettingsService
from app.write_guard import DEFAULT_WRITE_GUARD

pytestmark = pytest.mark.not_pg


@pytest.fixture(autouse=True)
def reset(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setattr(DEFAULT_WRITE_GUARD, "snapshot_fn", lambda: {"state": "healthy"})
    reset_memory_raw_store(); reset_memory_deletion_receipts()


def test_frames_age_out_bounded_and_receipted(tmp_path, monkeypatch):
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(tmp_path / "outbox.jsonl"))
    root = tmp_path / "vault"; root.mkdir()
    with pytest.raises(RetentionWindowMissingError): enforce_screen_frame_retention(vault_root=root)
    context = VaultManager().initialize_vault(root, machine_role="testNode", remember=False).context
    SettingsService().update_setting(context, "screen_frame_retention_minutes", 1, surface="cli", actor="operator")
    ciphertext, nonce = encrypt_raw_bytes(b"frame", key=b"x" * 32)
    insert_raw_record(content_identity=compute_raw_content_identity(b"frame"), capture_chain=["screen"], sensor={"machine": "mac"}, consent={"grant_ref": "g"}, ciphertext=ciphertext, nonce=nonce, key_ref="test", key=b"x" * 32, source_path="screen", payload={"modality": "screen"})
    result = enforce_screen_frame_retention(vault_root=root, now=datetime.now(timezone.utc) + timedelta(minutes=2))
    assert result.deleted_count == 1
    assert result.deletions[0].reason == REASON_SCREEN_FRAME_RETENTION_BUFFER
    assert result.deletions[0].payload["screen_frame_retention_minutes"] == 1
