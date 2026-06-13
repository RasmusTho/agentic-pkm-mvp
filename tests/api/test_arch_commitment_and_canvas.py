"""Architecture map — commitment surfacing (arrow 5; #1960) and canvas write guard (arrow 6; #1961).

* Commitments: the domain model ships, but no companion surface exposes them.
  XFAIL until #1960 adds commitments to the workspace state.
* Canvas: the ``/coauthor`` body-edit path applies edits without asserting the
  WriteGuard (the ``/governance`` path does). XFAIL pins the bug; it flips to
  pass when #1961 adds the guard.
"""

from __future__ import annotations

import inspect

import pytest

from app.api.routes.companion import RuntimeState
from app.chat import governance_router
from app.chat.canvas_writer import CanvasWriter


@pytest.mark.xfail(reason="commitments not yet surfaced in the companion workspace state (#1960)", strict=False)
def test_commitments_surface_in_workspace_state() -> None:
    """Arrow 5: the companion RuntimeState must expose commitments to the human."""

    fields = " ".join(RuntimeState.model_fields).lower()
    assert "commitment" in fields, "RuntimeState exposes no commitment surface yet"


@pytest.mark.xfail(reason="canvas body-edit path does not assert the WriteGuard (#1961 / PR #1966)", strict=False)
def test_coauthor_enforces_the_write_guard() -> None:
    """Arrow 6: the co-authoring write path must check the WriteGuard, like /governance.

    The guard belongs in ``CanvasWriter.apply_edit`` — the single chokepoint the
    ``/coauthor`` and ``/edits`` routes both call. Flips to pass when #1966 lands.
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
