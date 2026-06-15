"""Architecture map — guarded memory recall (diagram arrow 4; issue #1959)."""

from __future__ import annotations

from pathlib import Path

import app
from app.agent_memory.recall_activation import activate_guarded_recall


def test_guarded_recall_capability_exists() -> None:
    """Sanity anchor: the recall capability is importable and callable."""

    assert callable(activate_guarded_recall)


def test_guarded_recall_is_invoked_by_an_agent() -> None:
    """Arrow 4 wiring: some module under app/agents must call guarded recall.

    Recall must not sit dormant as an isolated capability. This test finds the
    ASK graph call site that closes the first runtime wiring gap.
    """

    agents_dir = Path(app.__file__).resolve().parent / "agents"
    callers = [
        path.relative_to(agents_dir).as_posix()
        for path in agents_dir.rglob("*.py")
        if "activate_guarded_recall" in path.read_text(encoding="utf-8")
    ]
    assert callers, "no agent runtime path invokes activate_guarded_recall yet"
