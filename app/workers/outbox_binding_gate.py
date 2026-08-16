"""MVR-05A8 binding authorization and shared-effect window for the scalar worker."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from app.instance.binding_ids import (
    COMPATIBILITY_BINDING_ID,
    OUTBOX_GLOBAL_BINDING_ID,
)
from app.instance.scalar_binding_runtime import (
    ScalarBindingRuntime,
    frozen_binding_effect,
    validate_frozen_binding_runtime,
)
from app.instance.vault_registry import RegistryError


class OutboxBindingDeferred(RegistryError):
    """A row belongs to another binding/revision and must remain pending."""


def eligible_worker_bindings(runtime: ScalarBindingRuntime | None) -> tuple[str, ...] | None:
    if runtime is None:
        return None
    return (
        runtime.vault_binding_id,
        COMPATIBILITY_BINDING_ID,
        OUTBOX_GLOBAL_BINDING_ID,
    )


def required_worker_binding_stamp(
    runtime: ScalarBindingRuntime | None,
) -> Mapping[str, object] | None:
    if runtime is None:
        return None
    return {
        "vault_binding_id": runtime.vault_binding_id,
        "binding_authority": runtime.authority,
        "binding_authorization_epoch": runtime.authorization_epoch,
        "binding_revision": runtime.binding_revision,
        "vault_root": str(runtime.root),
    }


def _message_meta(message: Mapping[str, Any]) -> Mapping[str, Any]:
    event = message.get("event")
    meta = getattr(event, "meta", None)
    return meta if isinstance(meta, Mapping) else {}


def _require_current_stamp(
    message: Mapping[str, Any], runtime: ScalarBindingRuntime
) -> None:
    row_binding = str(message.get("vault_binding_id") or "")
    # Rows backfilled from the scalar schema carry the compatibility identity
    # and no envelope stamp. They are translated at consume time under the same
    # live ownership + shared-effect lease as new compatibility ingress.
    if row_binding == COMPATIBILITY_BINDING_ID:
        return
    meta = _message_meta(message)
    expected = {
        "vault_binding_id": runtime.vault_binding_id,
        "binding_authority": runtime.authority,
        "binding_authorization_epoch": runtime.authorization_epoch,
        "binding_revision": runtime.binding_revision,
        "vault_root": str(runtime.root),
    }
    if any(meta.get(key) != value for key, value in expected.items()):
        raise OutboxBindingDeferred(
            "outbox row binding authority/revision/root is stale; leaving it pending"
        )


@contextmanager
def worker_effect_window(
    message: Mapping[str, Any],
    *,
    runtime: ScalarBindingRuntime | None,
) -> Iterator[None]:
    """Hold shared binding authority across dispatch, receipts, and final ack."""

    row_binding = str(message.get("vault_binding_id") or "")
    if row_binding == OUTBOX_GLOBAL_BINDING_ID:
        yield
        return
    if runtime is None:
        # Unit/non-runtime compatibility path. Production Compose always supplies
        # both instance-state paths, so it cannot silently take this branch.
        yield
        return
    if row_binding not in {runtime.vault_binding_id, COMPATIBILITY_BINDING_ID}:
        raise OutboxBindingDeferred("outbox row belongs to another binding")
    with runtime.effect_leases.shared_effect(
        runtime.vault_binding_id,
        channel_id=runtime.channel_id,
        root=Path(runtime.root),
    ):
        # Rotation/revocation must take the exclusive side of this lease. Once
        # shared is held, a fresh registry/GOV read is stable through ack and
        # all receipt writes. The frozen context prevents those nested writes
        # from reacquiring the host-global ownership lock in reverse order.
        validate_frozen_binding_runtime(runtime)
        _require_current_stamp(message, runtime)
        with frozen_binding_effect(runtime):
            yield


__all__ = [
    "OutboxBindingDeferred",
    "eligible_worker_bindings",
    "required_worker_binding_stamp",
    "worker_effect_window",
]
