"""Durability guard for ``SettingsWriteReceipt`` (#2787, RESEARCH-01 divergence D-1).

The control-action boundary contract (#2475,
``docs/INTERACTION_SURFACES_AND_AUTHORITY/DEFINE_RUNTIME_CONTROL_ACTION_BOUNDARY.md``) pairs every
runtime-gating settings write with a receipt as the accountability half of "proportional guard +
receipt". Until this change ``SettingsWriteReceipt`` was an in-memory dataclass only
(``app/vault/settings_service.py``) — lost on restart, so the accountability evidence could not be
produced later.

This test asserts:
- ``SettingsService.update_setting`` (the production call site) emits a durable outbox event
  (topic ``settings.write.receipt``) in addition to returning the in-memory receipt.
- The durable event is queryable via a projection reader after the writing process "restarts"
  (i.e. reading from a fresh outbox path/query call, not from any in-memory cache).
"""

from __future__ import annotations

from pathlib import Path

from app.events.types import SETTINGS_WRITE_RECEIPT
from app.receipts.settings_receipts import (
    SettingsReceiptQuery,
    query_settings_receipts,
)
from app.vault.app_local import AppLocalSettingsStore
from app.vault.manager import VaultManager
from app.vault.settings_service import SettingsService, SettingsWriteReceipt


def _manager(tmp_path: Path) -> tuple[VaultManager, Path]:
    manager = VaultManager(app_local_store=AppLocalSettingsStore(tmp_path / "app-local.md"))
    vault = tmp_path / "vault-primary"
    manager.initialize_vault(vault, machine_role="primary", remember=False)
    return manager, vault


def test_emitted_from_update_setting(tmp_path: Path, monkeypatch) -> None:
    """The production ``SettingsService.update_setting`` call site emits a durable
    outbox event for every governed settings write, not just the in-memory receipt."""
    outbox_path = tmp_path / "outbox.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))

    manager, _vault = _manager(tmp_path)
    context = manager.context

    service = SettingsService()
    effective, receipt = service.update_setting(
        context, "enableVaultWatcher", False, surface="cli", actor="human"
    )

    # In-memory receipt contract is unchanged (additive durability only).
    assert isinstance(receipt, SettingsWriteReceipt)
    assert effective.key == "enableVaultWatcher"

    assert outbox_path.exists(), "update_setting must emit a durable outbox record"
    lines = [line for line in outbox_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 1
    import json

    record = json.loads(lines[0])
    assert record.get("event") == SETTINGS_WRITE_RECEIPT
    assert record.get("event") == "settings.write.receipt"
    payload = record.get("payload") or {}
    assert payload.get("key") == "enableVaultWatcher"
    assert payload.get("value") is False
    assert payload.get("surface") == "cli"
    assert payload.get("actor") == "human"
    assert payload.get("is_runtime_gating") is True
    assert record.get("event_id"), "durable event must carry an idempotency-capable event_id"


def test_receipt_survives_restart(tmp_path: Path, monkeypatch) -> None:
    """A receipt emitted by one process is queryable by a fresh projection read,
    simulating a restart (no in-memory state is reused)."""
    outbox_path = tmp_path / "outbox.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))

    manager, vault = _manager(tmp_path)
    context = manager.context

    service = SettingsService()
    service.update_setting(context, "enableAutoIndexing", False, surface="api", actor="human")

    # Simulate "restart": drop all in-process references and re-query from disk only.
    del service
    del manager

    result = query_settings_receipts(vault_root=vault, outbox_path=outbox_path)
    assert result.source_available is True
    assert len(result.rows) == 1
    row = result.rows[0]
    assert row.key == "enableAutoIndexing"
    assert row.value is False
    assert row.surface == "api"
    assert row.actor == "human"
    assert row.is_runtime_gating is True

    # Query filtering works too.
    filtered = query_settings_receipts(
        SettingsReceiptQuery(key="enableAutoIndexing"),
        vault_root=vault,
        outbox_path=outbox_path,
    )
    assert len(filtered.rows) == 1
    empty = query_settings_receipts(
        SettingsReceiptQuery(key="nonexistentKey"),
        vault_root=vault,
        outbox_path=outbox_path,
    )
    assert len(empty.rows) == 0


def test_non_runtime_gating_write_also_durable(tmp_path: Path, monkeypatch) -> None:
    """Durability is unconditional on every governed write, not only runtime-gating keys
    (mirrors the existing in-memory receipt behavior)."""
    outbox_path = tmp_path / "outbox.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))

    manager, vault = _manager(tmp_path)
    context = manager.context

    service = SettingsService()
    service.update_setting(context, "handoffFolder", "Client Projects", surface="api", actor="human")

    result = query_settings_receipts(vault_root=vault, outbox_path=outbox_path)
    assert len(result.rows) == 1
    assert result.rows[0].key == "handoffFolder"
    assert result.rows[0].is_runtime_gating is False
