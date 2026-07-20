"""Durable, best-effort receipt seam shared by every settings writer."""

from __future__ import annotations

import json
import logging
import os
import fcntl
from contextlib import contextmanager
from contextvars import ContextVar
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from app.events.types import SETTINGS_WRITE_RECEIPT


logger = logging.getLogger(__name__)
_OLD_VALUE_UNSET = object()
_NEW_VALUE_UNSET = object()
_old_value_override: ContextVar[Any] = ContextVar(
    "settings_receipt_old_value",
    default=_OLD_VALUE_UNSET,
)


class ReceiptDurabilityUncertainError(RuntimeError):
    """Receipt bytes are fsynced, but creation-directory durability is uncertain."""


def _fsync_parent(path: Path) -> None:
    """Durably link the file's full parent chain, including fresh nested dirs."""

    parent = path.parent
    while True:
        parent_descriptor = os.open(parent, os.O_RDONLY)
        try:
            os.fsync(parent_descriptor)
        finally:
            os.close(parent_descriptor)
        if parent.parent == parent:
            break
        parent = parent.parent


def _confirm_file_and_parent_durable(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    _fsync_parent(path)


@dataclass(frozen=True)
class SettingsWriteReceipt:
    """Actor-tagged observation of one settings value mutation."""

    key: str
    value: Any
    surface: str
    actor: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    is_runtime_gating: bool = False
    file: str | None = None
    old_value: Any = None
    new_value: Any = field(default=_NEW_VALUE_UNSET, repr=False)
    operation_id: str | None = None
    vault_id: str | None = None
    local_instance_id: str | None = None

    def __post_init__(self) -> None:
        if self.new_value is _NEW_VALUE_UNSET:
            object.__setattr__(self, "new_value", self.value)


def emit_settings_write_receipt(
    receipt: SettingsWriteReceipt, *, require_durable: bool = False
) -> None:
    """Append one receipt to both sinks, optionally requiring the JSONL sink."""

    # Deferred to keep the settings compiler import graph acyclic:
    # events.schema -> settings.runtime -> settings.compiler -> settings.writeback.
    from app.events.schema import make_outbox_event  # noqa: PLC0415

    try:
        envelope = make_outbox_event(
            SETTINGS_WRITE_RECEIPT,
            source="settings_receipts",
            payload={
                "key": receipt.key,
                "value": receipt.value,
                "old_value": receipt.old_value,
                "new_value": receipt.new_value,
                "file": receipt.file,
                "surface": receipt.surface,
                "actor": receipt.actor,
                "operation_id": receipt.operation_id,
                "vault_id": receipt.vault_id,
                "local_instance_id": receipt.local_instance_id,
                "timestamp": receipt.timestamp,
                "is_runtime_gating": receipt.is_runtime_gating,
            },
        )
        record = envelope.model_dump(mode="json")
    except Exception as exc:
        logger.warning("settings.write.receipt envelope construction failed", exc_info=True)
        if require_durable:
            raise RuntimeError("settings receipt envelope construction failed") from exc
        return

    try:
        from app.outbox.events import get_index_outbox_path  # noqa: PLC0415

        outbox_path = get_index_outbox_path()
        outbox_path.parent.mkdir(parents=True, exist_ok=True)
        serialized = (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8")
        if require_durable:
            descriptor = os.open(
                outbox_path,
                os.O_APPEND | os.O_CREAT | os.O_WRONLY,
                0o600,
            )
            try:
                written = os.write(descriptor, serialized)
                if written != len(serialized):
                    raise OSError("partial durable settings receipt append")
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            try:
                _fsync_parent(outbox_path)
            except OSError as exc:
                raise ReceiptDurabilityUncertainError(
                    "settings receipt is visible but parent fsync failed"
                ) from exc
        else:
            with outbox_path.open("ab") as handle:
                handle.write(serialized)
    except ReceiptDurabilityUncertainError:
        raise
    except Exception as exc:
        logger.warning("settings.write.receipt jsonl append failed", exc_info=True)
        if require_durable:
            raise RuntimeError("durable settings receipt append failed") from exc

    try:
        from app.services.outbox import (  # noqa: PLC0415
            EVENT_ID_FINGERPRINT,
            derive_idempotency_key,
            write_outbox_event,
        )

        idempotency_key = derive_idempotency_key(
            SETTINGS_WRITE_RECEIPT,
            envelope.event_id,
            EVENT_ID_FINGERPRINT,
        )
        write_outbox_event(envelope, idempotency_key=idempotency_key)
    except Exception:
        logger.debug("settings.write.receipt db outbox write skipped/failed", exc_info=True)


def durable_settings_write_receipt_exists(receipt: SettingsWriteReceipt) -> bool:
    """Return whether the exact operation-scoped receipt is in the durable JSONL sink."""

    if not receipt.operation_id:
        raise ValueError("durable receipt readback requires operation_id")

    from app.outbox.events import get_index_outbox_path  # noqa: PLC0415

    outbox_path = get_index_outbox_path()
    operation_id_collision = False
    exact_match_count = 0
    try:
        with outbox_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if record.get("event") != SETTINGS_WRITE_RECEIPT:
                    continue
                payload = record.get("payload")
                if not isinstance(payload, dict):
                    continue
                if payload.get("operation_id") != receipt.operation_id:
                    continue
                exact_match = all(
                    payload.get(key) == expected
                    for key, expected in {
                        "key": receipt.key,
                        "value": receipt.value,
                        "old_value": receipt.old_value,
                        "new_value": receipt.new_value,
                        "file": receipt.file,
                        "surface": receipt.surface,
                        "actor": receipt.actor,
                        "timestamp": receipt.timestamp,
                        "is_runtime_gating": receipt.is_runtime_gating,
                        "vault_id": receipt.vault_id,
                        "local_instance_id": receipt.local_instance_id,
                    }.items()
                )
                if exact_match:
                    exact_match_count += 1
                else:
                    operation_id_collision = True
    except FileNotFoundError:
        return False
    if operation_id_collision or exact_match_count > 1:
        raise RuntimeError("settings receipt operation_id collision")
    if exact_match_count == 1:
        _confirm_file_and_parent_durable(outbox_path)
        return True
    return False


def emit_durable_settings_write_receipt_once(receipt: SettingsWriteReceipt) -> None:
    """Durably append and read back one operation-scoped receipt exactly once.

    The sibling lock serializes check-and-append across settings writers.  If a
    prior attempt appended the exact receipt but failed while confirming parent
    durability, the retry observes and re-confirms that record instead of
    creating a second accepted operation.
    """

    if not receipt.operation_id:
        raise ValueError("durable receipt emission requires operation_id")

    from app.outbox.events import get_index_outbox_path  # noqa: PLC0415

    outbox_path = get_index_outbox_path()
    outbox_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = outbox_path.with_name(f".{outbox_path.name}.settings-receipt.lock")
    with lock_path.open("a+b") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        try:
            if durable_settings_write_receipt_exists(receipt):
                return
            try:
                emit_settings_write_receipt(receipt, require_durable=True)
            except ReceiptDurabilityUncertainError:
                if durable_settings_write_receipt_exists(receipt):
                    return
                raise
            if not durable_settings_write_receipt_exists(receipt):
                raise RuntimeError("durable settings receipt readback failed")
        finally:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)


def emit_settings_write_receipts_for_changes(
    *,
    old_values: Mapping[str, Any],
    new_values: Mapping[str, Any],
    surface: str,
    actor: str,
    file: Path | str,
    key_prefix: str | None = None,
    flatten_nested: bool = False,
    require_durable: bool = False,
) -> tuple[SettingsWriteReceipt, ...]:
    """Emit key-scoped receipts for changed leaves in two settings mappings."""

    old_flat = _flatten(old_values) if flatten_nested else dict(old_values)
    new_flat = _flatten(new_values) if flatten_nested else dict(new_values)
    receipts: list[SettingsWriteReceipt] = []
    for key in sorted(old_flat.keys() | new_flat.keys()):
        old_value = old_flat.get(key)
        new_value = new_flat.get(key)
        if old_value == new_value:
            continue
        receipt_key = f"{key_prefix}.{key}" if key_prefix else key
        receipt = SettingsWriteReceipt(
            key=receipt_key,
            value=new_value,
            old_value=old_value,
            new_value=new_value,
            file=str(file),
            surface=surface,
            actor=actor,
        )
        emit_settings_write_receipt(receipt, require_durable=require_durable)
        receipts.append(receipt)
    return tuple(receipts)


@contextmanager
def settings_receipt_old_value(value: Any) -> Iterator[None]:
    """Temporarily supply the pre-write value without widening writer APIs."""

    token = _old_value_override.set(value)
    try:
        yield
    finally:
        _old_value_override.reset(token)


def resolve_settings_receipt_old_value(default: Any) -> Any:
    value = _old_value_override.get()
    return default if value is _OLD_VALUE_UNSET else value


def _flatten(values: Mapping[str, Any], prefix: str = "") -> dict[str, Any]:
    flattened: dict[str, Any] = {}
    for key, value in values.items():
        name = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, Mapping):
            flattened.update(_flatten(value, name))
        else:
            flattened[name] = value
    return flattened


__all__ = [
    "SettingsWriteReceipt",
    "durable_settings_write_receipt_exists",
    "emit_durable_settings_write_receipt_once",
    "emit_settings_write_receipt",
    "emit_settings_write_receipts_for_changes",
    "resolve_settings_receipt_old_value",
    "settings_receipt_old_value",
]
