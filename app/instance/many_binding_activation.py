"""MVR-06D: the fail-loud activation of many-binding enrollment/start and claim dispatch.

`docs/MULTI_VAULT_RUNTIME/BIND_BACKGROUND_LIFECYCLES.md` (MVR-06D). Activation is one
registry generation -- ``minimumRuntimeSchema=mvr-06d`` plus registry schema v4 -- and it
runs inside the proved stopped window (every API/watcher/worker stopped), so the
all-process floor commits before the first queue-state write. Before it, the gate
validates MVR-05's committed classification result:

- the MVR-05 cutover fence receipt is complete (all old scalar clients were stopped);
- the outbox carries the MVR-06D claim columns, sequence, and constraint;
- no undelivered row is still unscoped (``legacy-compatibility-binding``): such a row has
  no binding a many-binding lifecycle could claim it under, so the outbox must be drained
  through the singleton worker first (KD-A42F26A9AD87);
- no queue-state field was written before the floor.

MVR-05's unprovable rows stay quarantined (never dispatched or acknowledged), global rows
keep their one canonical lineage, and already-scoped rows are revalidated against current
intent by the many-binding worker before any dispatch. The receipt carries counts only.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from app.instance._storage_boundary import (
    CapabilityNotReadyError,
    RegistryError,
    _require_storage_mutation_capability,
)
from app.instance.vault_registry import (
    RegistrySnapshot,
    VaultRegistryStore,
    many_binding_dispatch_enabled,
)

_MVR05_FENCE_SCHEMA = "agentic-pkm.mvr05-cutover-fence.v1"


def _require_mvr05_receipt(snapshot: RegistrySnapshot) -> None:
    floors = snapshot.extensions.get("runtimeFloors") or {}
    fence = floors.get("mvr05CutoverFence") if isinstance(floors, Mapping) else None
    if (
        not isinstance(fence, Mapping)
        or fence.get("schema") != _MVR05_FENCE_SCHEMA
        or fence.get("all_old_scalar_clients_stopped") is not True
    ):
        raise CapabilityNotReadyError(
            "capability_not_ready: MVR-06D requires MVR-05's complete committed "
            "classification/cutover receipt"
        )


def validate_mvr05_classification(
    snapshot: RegistrySnapshot,
    *,
    conn_factory: Callable[[], Any] | None = None,
) -> dict[str, object]:
    """Validate MVR-05's classification receipt; return the bounded census (counts only)."""

    from app.instance.background_supervisor import handoff_complete

    _require_mvr05_receipt(snapshot)
    if not handoff_complete(snapshot):
        raise CapabilityNotReadyError(
            "capability_not_ready: MVR-06D requires the completed MVR-06B supervisor handoff"
        )
    from app.workers.many_binding_dispatch import queue_configured

    if not queue_configured():
        return {"mvr05_receipt": "valid", "outbox": "absent"}
    from app.services.outbox import _open_conn
    from app.services.outbox_claims import classify_for_activation

    conn = (conn_factory or _open_conn)()
    try:
        census = classify_for_activation(conn)
    finally:
        try:
            conn.close()
        except Exception:  # pragma: no cover - defensive close
            pass
    if census["unscoped"]:
        raise CapabilityNotReadyError(
            f"capability_not_ready: {census['unscoped']} unscoped compatibility outbox "
            "row(s) remain dispatchable; drain them through the singleton worker before "
            "many-binding activation"
        )
    if census["queue_state"]:
        raise RegistryError(
            "MVR-06D queue-state fields exist before the MVR-06D floor; refuse activation"
        )
    scoped_bindings = list(census["scoped_bindings"])  # type: ignore[call-overload]
    return {
        "mvr05_receipt": "valid",
        "outbox": "postgres",
        "unprovable_quarantined": census["unprovable"],
        "global_pending": census["global_rows"],
        "scoped_pending": census["scoped"],
        "scoped_unregistered_bindings": sum(
            1 for binding in scoped_bindings if binding not in snapshot.registrations
        ),
    }


def activate_many_binding_dispatch(
    registry: VaultRegistryStore,
    *,
    conn_factory: Callable[[], Any] | None = None,
    _capability: Any = None,
) -> dict[str, object]:
    """Validate, then commit the MVR-06D floor in one generation. Idempotent."""

    _require_storage_mutation_capability(_capability)
    snapshot = registry.load()
    if many_binding_dispatch_enabled(snapshot):
        floors = snapshot.extensions.get("runtimeFloors") or {}
        return {
            "activated": False,
            "minimum_runtime_schema": "mvr-06d",
            "registry_revision": snapshot.revision,
            "classification": dict(floors["mvr06dFloorCutover"]["classification"]),
        }
    classification = validate_mvr05_classification(snapshot, conn_factory=conn_factory)
    committed = registry.advance_mvr06d_runtime_floor(
        classification=classification, _capability=_capability
    )
    from app.instance.background_supervisor import emit_background_intent_event

    emit_background_intent_event(committed, reason="mvr06d_many_binding_activation")
    return {
        "activated": True,
        "minimum_runtime_schema": "mvr-06d",
        "registry_revision": committed.revision,
        "classification": classification,
    }


__all__ = ["activate_many_binding_dispatch", "validate_mvr05_classification"]
