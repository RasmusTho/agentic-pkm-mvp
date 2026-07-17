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

import os
from pathlib import Path
from textwrap import dedent

from app.events.types import SETTINGS_WRITE_RECEIPT
from app.receipts.settings_receipts import (
    SettingsReceiptQuery,
    query_settings_receipts,
)
from app.receipts.settings_write import (
    durable_settings_write_receipt_exists,
    emit_settings_write_receipt,
)
from app.settings import compiler
from app.vault.app_local import AppLocalSettingsStore, KnownVaultRef
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


def test_required_receipt_fsyncs_before_return(tmp_path: Path, monkeypatch) -> None:
    outbox_path = tmp_path / "outbox.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setenv("STORE_BACKEND", "memory")
    fsync_calls: list[int] = []
    monkeypatch.setattr(
        "app.receipts.settings_write.os.fsync", lambda descriptor: fsync_calls.append(descriptor)
    )

    emit_settings_write_receipt(
        SettingsWriteReceipt(
            key="settings.location",
            value={"canonical": "settings"},
            surface="migration",
            actor="operator",
        ),
        require_durable=True,
    )

    assert fsync_calls
    assert outbox_path.read_text(encoding="utf-8").endswith("\n")


def test_required_receipt_appends_each_record_with_one_os_write(
    tmp_path: Path, monkeypatch
) -> None:
    outbox_path = tmp_path / "outbox.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setenv("STORE_BACKEND", "memory")
    real_write = os.write
    writes: list[bytes] = []

    def _record_write(descriptor: int, payload: bytes) -> int:
        writes.append(payload)
        return real_write(descriptor, payload)

    monkeypatch.setattr("app.receipts.settings_write.os.write", _record_write)

    emit_settings_write_receipt(
        SettingsWriteReceipt(
            key="settings.location",
            value={"canonical": "settings"},
            surface="migration",
            actor="operator",
        ),
        require_durable=True,
    )

    assert len(writes) == 1
    assert writes[0].endswith(b"\n")


def test_operation_scoped_receipt_has_exact_durable_readback(
    tmp_path: Path, monkeypatch
) -> None:
    outbox_path = tmp_path / "outbox.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setenv("STORE_BACKEND", "memory")
    receipt = SettingsWriteReceipt(
        key="ingest.override.include_folders",
        value=["Test"],
        old_value=None,
        new_value=["Test"],
        file=str(tmp_path / "settings" / "ingest.override.md"),
        surface="uat-bootstrap",
        actor="uat-seed",
        operation_id="uat-operation:0",
    )

    assert durable_settings_write_receipt_exists(receipt) is False
    emit_settings_write_receipt(receipt, require_durable=True)
    assert durable_settings_write_receipt_exists(receipt) is True

    different_payload = SettingsWriteReceipt(
        key=receipt.key,
        value=["Other"],
        old_value=receipt.old_value,
        new_value=["Other"],
        file=receipt.file,
        surface=receipt.surface,
        actor=receipt.actor,
        operation_id=receipt.operation_id,
    )
    assert durable_settings_write_receipt_exists(different_payload) is False


def test_durable_receipt_readback_requires_operation_identity(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(tmp_path / "outbox.jsonl"))
    receipt = SettingsWriteReceipt(
        key="settings.location",
        value="settings",
        surface="migration",
        actor="operator",
    )

    try:
        durable_settings_write_receipt_exists(receipt)
    except ValueError as exc:
        assert "operation_id" in str(exc)
    else:
        raise AssertionError("readback without an operation identity must fail closed")


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


def _write_settings_source(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(body).strip() + "\n", encoding="utf-8")


def test_autoheal_writeback_receipted(tmp_path: Path, monkeypatch) -> None:
    outbox_path = tmp_path / "outbox.jsonl"
    settings_dir = tmp_path / "vault" / "settings"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setattr(compiler, "RUNTIME", tmp_path / "runtime" / "settings")
    _write_settings_source(
        settings_dir / "global.md",
        """
        ---
        uuid: global
        ---
        ## Runtime
        ```yaml settings
        timeout_ms: fast
        ```
        """,
    )

    compiler.compile_all(auto_heal=True, vault_dir=settings_dir)

    result = query_settings_receipts(outbox_path=outbox_path)
    row = next(row for row in result.rows if row.key == "global.timeout_ms")
    assert row.surface == "auto-heal"
    assert row.actor == "agent"
    assert row.file == str(settings_dir / "global.md")
    assert row.old_value == "fast"
    assert row.new_value == 8000


def test_autoheal_reference_only_writeback_receipted(tmp_path: Path, monkeypatch) -> None:
    outbox_path = tmp_path / "outbox.jsonl"
    settings_dir = tmp_path / "vault" / "settings"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setattr(compiler, "RUNTIME", tmp_path / "runtime" / "settings")
    global_path = settings_dir / "global.md"
    _write_settings_source(
        global_path,
        """
        ---
        uuid: global
        ---
        ## Runtime
        ```yaml settings
        timeout_ms: 8000
        ```
        """,
    )

    compiler.compile_all(auto_heal=True, vault_dir=settings_dir)

    row = next(
        row
        for row in query_settings_receipts(outbox_path=outbox_path).rows
        if row.key == "global.__reference__"
    )
    assert row.surface == "auto-heal"
    assert row.actor == "agent"
    assert row.file == str(global_path)
    assert row.old_value is None
    assert "Reference — Global" in row.new_value


def test_app_local_write_receipted(tmp_path: Path, monkeypatch) -> None:
    outbox_path = tmp_path / "outbox.jsonl"
    app_local_path = tmp_path / "app-local.md"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setenv("STORE_BACKEND", "memory")
    store = AppLocalSettingsStore(app_local_path)

    store.upsert_known_vault(
        KnownVaultRef(ref="path:/vault", path="/vault"),
        make_active=True,
    )

    result = query_settings_receipts(outbox_path=outbox_path)
    app_local_rows = [row for row in result.rows if row.surface == "app-local"]
    assert app_local_rows
    assert {row.key for row in app_local_rows} >= {
        "appInstallId",
        "knownVaults",
        "lastActiveVaultRef",
    }
    assert all(row.file == str(app_local_path) for row in app_local_rows)


def test_all_writers_queryable(tmp_path: Path, monkeypatch) -> None:
    outbox_path = tmp_path / "outbox.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setenv("STORE_BACKEND", "memory")
    manager, vault = _manager(tmp_path)
    SettingsService().update_setting(
        manager.context,
        "handoffFolder",
        "Projects",
        surface="api",
        actor="human",
    )
    AppLocalSettingsStore(tmp_path / "secondary-app-local.md").load()

    result = query_settings_receipts(vault_root=vault, outbox_path=outbox_path)

    assert {row.surface for row in result.rows} >= {"api", "app-local"}
    assert len(query_settings_receipts(SettingsReceiptQuery(surface="api"), outbox_path=outbox_path).rows) == 1
    assert query_settings_receipts(
        SettingsReceiptQuery(surface="app-local"), outbox_path=outbox_path
    ).rows


def test_receipt_sink_failure_never_gates_settings_write(tmp_path: Path, monkeypatch) -> None:
    outbox_path = tmp_path / "outbox.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setenv("STORE_BACKEND", "memory")
    manager, _vault = _manager(tmp_path)
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(tmp_path))  # a directory cannot be appended

    effective, receipt = SettingsService().update_setting(
        manager.context,
        "handoffFolder",
        "Still Written",
        surface="api",
        actor="human",
    )

    assert effective.value == "Still Written"
    assert receipt.new_value == "Still Written"

    def _broken_envelope(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("synthetic envelope failure")

    monkeypatch.setattr("app.events.schema.make_outbox_event", _broken_envelope)
    effective, _receipt = SettingsService().update_setting(
        manager.context,
        "handoffFolder",
        "Written Again",
        surface="api",
        actor="human",
    )
    assert effective.value == "Written Again"
