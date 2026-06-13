"""Architecture map — guarded memory recall (diagram arrow 4; issue #1959).

``activate_guarded_recall`` is built and unit-tested, but no agent calls it at
runtime — recall never fires during an ASK/Panel run. That dormancy is the gap
#1959 closes. The wiring test is XFAIL until an agent runtime path invokes recall.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import app
from app.agent_memory.recall_activation import activate_guarded_recall


def test_guarded_recall_capability_exists() -> None:
    """Sanity anchor: the recall capability is importable and callable."""

    assert callable(activate_guarded_recall)


@pytest.mark.xfail(reason="guarded recall not yet invoked by any agent runtime path (#1959)", strict=False)
def test_guarded_recall_is_invoked_by_an_agent() -> None:
    """Arrow 4 wiring: some module under app/agents must call guarded recall.

    Today ``git grep activate_guarded_recall app/agents`` is empty — recall is
    dormant. When #1959 wires it into the ASK/PanelAgent retrieval path, this
    test finds the call site and passes.
    """

    agents_dir = Path(app.__file__).resolve().parent / "agents"
    callers = [
        path.relative_to(agents_dir).as_posix()
        for path in agents_dir.rglob("*.py")
        if "activate_guarded_recall" in path.read_text(encoding="utf-8")
    ]
    assert callers, "no agent runtime path invokes activate_guarded_recall yet"
