"""Architecture map — commitment surfacing (arrow 5; #1960) and canvas write guard (arrow 6; #1961).

* Commitments: the companion ``RuntimeState`` now exposes a read-only commitment
  surface backed by the durable vault artefacts (slice 2, #2074; parent #1960).
* Canvas: the ``/coauthor`` body-edit path now asserts the WriteGuard in
  ``CanvasWriter.apply_edit`` — the single chokepoint it shares with ``/edits`` —
  matching the ``/governance`` path. The guard shipped in #1966 (#1961).
"""

from __future__ import annotations

import inspect

from app.api.routes.companion import RuntimeState
from app.chat import governance_router
from app.chat.canvas_writer import CanvasWriter


def test_commitments_surface_in_workspace_state() -> None:
    """Arrow 5: the companion RuntimeState must expose commitments to the human.

    Surfaced read-only from the durable vault artefacts in slice 2 (#2074); the
    xfail guard flipped to pass when the commitment field landed on RuntimeState.
    """

    fields = " ".join(RuntimeState.model_fields).lower()
    assert "commitment" in fields, "RuntimeState exposes no commitment surface yet"


def test_coauthor_enforces_the_write_guard() -> None:
    """Arrow 6: the co-authoring write path must check the WriteGuard, like /governance.

    The guard lives in ``CanvasWriter.apply_edit`` — the single chokepoint the
    ``/coauthor`` and ``/edits`` routes both call. Guarded since #1966 (#1961).
    """

    assert "assert_writes_allowed" in inspect.getsource(CanvasWriter.apply_edit), (
        "the canvas body-edit chokepoint is not gated by the WriteGuard"
    )


def test_governance_path_is_guarded_today() -> None:
    """Baseline (PASS): the governance-bearing path already asserts the WriteGuard.

    The canvas ``/governance`` route delegates to ``GovernanceRouter``, which
    checks the guard — this is the reference behavior #1961 brings to ``/coauthor``.
    """

    guarded = "assert_writes_allowed" in inspect.getsource(governance_router)
    assert guarded, "expected GovernanceRouter to assert the WriteGuard"
