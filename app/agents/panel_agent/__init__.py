from __future__ import annotations

import sys

__all__ = [
    "run_panel_intent_for_note",
    "execute_panel_intent",
    "PanelRuntimeResult",
    "agent",
]

from .agent import run_panel_intent_for_note
from .runtime import PanelRuntimeResult, execute_panel_intent

# Importing ``app.journaling.draft`` can reach this package through a circular
# path where Python has already cached the agent submodule but does not restore
# it as a parent-package attribute.  Bind the cached module explicitly so
# normal dotted traversal (including pytest monkeypatch resolution) remains
# import-order independent.
agent = sys.modules[f"{__name__}.agent"]
