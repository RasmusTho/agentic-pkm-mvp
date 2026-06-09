"""Back-compat re-export of the BuilderOps CLI command group.

The command implementation lives in :mod:`app.builderops.cli` so that the
standalone automation entry point (``python3 -m app.builderops``) can load it
WITHOUT importing the broad ``app.cli`` package (whose ``__init__`` pulls in
``httpx``/``watchfiles`` and other runtime-only deps). This module keeps the
historical ``app.cli.builderops`` import path working for the full CLI
(``python3 -m app.cli builderops ...``), which already requires those deps.
"""
from __future__ import annotations

from app.builderops.cli import builderops

__all__ = ["builderops"]
