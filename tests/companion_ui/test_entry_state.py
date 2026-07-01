"""Entry-state model invariants for the no-selection vs cold_start boundary (#2653).

The five-state entry model (``entry_state.py``) must not change: a *selected*
vault with an absent ``leave_point`` still resolves to ``cold_start`` (the
anti-dashboard first-contact / >7d cold trajectory of a bound vault, per the
#2513 reconciliation to ADR-0008/#2489), and the ``cold_start`` state is
reserved for a vault that is already bound/selected.

This file pins the entry-model half of #2653 (the no-selection case routes to
the picker is pinned API-side in ``tests/api/test_companion_orientation_selection_gate.py``
and UI-side in ``tests/companion_ui/test_workspace_no_vault_picker.py``). Here we
assert the *non-regression*: ``resolve_entry_state`` still yields ``cold_start``
for a selected vault whose leave point is absent.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from companion_ui.workspace.entry_state import resolve_entry_state

_AS_OF = datetime(2026, 6, 10, 12, 0, 0, tzinfo=timezone.utc)


def _iso(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def _selected_vault_orientation(*, leave_status: str) -> dict[str, Any]:
    """A normal orientation payload for a *selected, bound* vault.

    Mirrors the shape the runtime emits once a vault is selected: a real
    ``scope.vault_id`` plus a ``leave_point`` whose ``status`` drives the
    cold/orienting decision.
    """
    return {
        "scope": {"kind": "workspace", "vault_id": "dev-vault", "channel": "dev"},
        "meta": {
            "contract_version": "workspace_orientation.v1",
            "as_of": _iso(_AS_OF),
            "trace_id": "trace-entry-state",
            "freshness": "fresh",
            "stale_after": _iso(_AS_OF + timedelta(minutes=5)),
            "degraded_reasons": [],
        },
        "leave_point": {"status": leave_status},
        "open_loops": [],
        "notable_changes": [],
        "resurface": {"candidates": []},
        "guards": {"read_only": True, "degraded": False, "reasons": []},
        "mutation_intents": [],
    }


def test_selected_vault_absent_leave_point_still_cold_start() -> None:
    """A *selected* vault with an absent leave point resolves to cold_start.

    #2653 changes only the *no-selection* case (which must route to the picker);
    the five-state entry model is unchanged. A bound vault whose ``leave_point``
    is absent is the canonical ``cold_start`` (first contact / >7d cold
    trajectory of an already-selected vault, #2453) and must NOT regress to any
    other state or to the picker.
    """
    resolution = resolve_entry_state(
        orientation=_selected_vault_orientation(leave_status="absent")
    )

    assert resolution.state == "cold_start"
    # cold_start carries no re-entry overlay shape and no degraded/stale flags.
    assert resolution.reentry_shape is None
    assert resolution.degraded is False
    assert resolution.stale is False


def test_selected_vault_present_recent_leave_point_is_orienting() -> None:
    """Sanity guard: a present, recent leave point is still ``orienting``.

    Ensures the cold_start assertion above is meaningful — the same payload
    shape with a *present* recent leave point resolves to ``orienting`` (a
    re-entry shape), so the entry model still discriminates bound-vault
    trajectories and #2653 did not collapse everything to cold_start.
    """
    payload = _selected_vault_orientation(leave_status="present")
    # A leave point captured seconds ago → the freshest re-entry shape.
    payload["leave_point"]["captured_at"] = _iso(_AS_OF - timedelta(seconds=30))

    resolution = resolve_entry_state(orientation=payload)

    assert resolution.state == "orienting"
    assert resolution.reentry_shape == "no_mist"
