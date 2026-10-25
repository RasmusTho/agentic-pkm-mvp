"""The finite native activation scope; absence preserves ordinary full serving."""
from __future__ import annotations

import os

from app.config.environment import active_environment


def validate_activation_scope(scope: str, channel: str) -> str:
    if scope not in {"full", "text-capture"} or (
        scope == "text-capture" and channel not in {"dev", "test"}
    ):
        raise ValueError("activation scope refused")
    return scope


def runtime_activation_scope() -> str:
    return validate_activation_scope(
        os.environ.get("PKM_ACTIVATION_SCOPE", "full"), active_environment()
    )
