"""Durable, best-effort receipt seam shared by every settings writer."""

from __future__ import annotations

import json
import logging
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

    def __post_init__(self) -> None:
        if self.new_value is _NEW_VALUE_UNSET:
            object.__setattr__(self, "new_value", self.value)


def emit_settings_write_receipt(receipt: SettingsWriteReceipt) -> None:
    """Append one receipt to both existing sinks without gating the write."""

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
                "timestamp": receipt.timestamp,
                "is_runtime_gating": receipt.is_runtime_gating,
            },
        )
        record = envelope.model_dump(mode="json")
    except Exception:
        logger.warning("settings.write.receipt envelope construction failed", exc_info=True)
        return

    try:
        from app.outbox.events import get_index_outbox_path  # noqa: PLC0415

        outbox_path = get_index_outbox_path()
        outbox_path.parent.mkdir(parents=True, exist_ok=True)
        with outbox_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False))
            handle.write("\n")
    except Exception:
        logger.warning("settings.write.receipt jsonl append failed", exc_info=True)

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


def emit_settings_write_receipts_for_changes(
    *,
    old_values: Mapping[str, Any],
    new_values: Mapping[str, Any],
    surface: str,
    actor: str,
    file: Path | str,
    key_prefix: str | None = None,
    flatten_nested: bool = False,
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
        emit_settings_write_receipt(receipt)
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
    "emit_settings_write_receipt",
    "emit_settings_write_receipts_for_changes",
    "resolve_settings_receipt_old_value",
    "settings_receipt_old_value",
]
