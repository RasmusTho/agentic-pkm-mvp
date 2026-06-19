"""v6.0 feature-seam importability probe (interaction layer).

ADR-0013 (docs/adr/ADR-0013-code-dependency-direction.md): the interaction layer is
import-protected — nothing in a deeper layer may import it. The seam probe imports
interaction-layer modules (``app.api.routes.*``) and downward capabilities
(``app.resurfacing``, ``app.domain.commitments``) to report which v6.0 feature seams
are wired. That reach is legitimate *from here* (intra-interaction + downward) but is a
backward/upward import from the Foundation observability layer, so the probe lives here
and the Foundation status service consumes it through a registered provider
(``app.observability.status_service.register_v6_seams_provider``) instead of importing
it. This keeps the Foundation layer upward-free and statically enforceable by
import-linter.
"""

from __future__ import annotations

import importlib
import os

from app.observability.status_service import register_v6_seams_provider

_TRUE_VALUES = {"1", "true", "yes", "on"}


def _seam(module: str) -> str:
    try:
        importlib.import_module(module)
        return "enabled"
    except Exception:
        return "disabled"


def check_v6_seams() -> dict[str, str]:
    """Probe importability of v6.0 feature seam modules.

    Returns a mapping of seam name -> "enabled" | "disabled". Canvas is only
    "enabled" when both ``CANVAS_ENABLED`` is on AND the router imports; if the
    gate is on but the import fails, report "disabled" so a broken-import case is
    not masked as an active route.
    """

    canvas_gate_on = os.getenv("CANVAS_ENABLED", "0").strip().lower() in _TRUE_VALUES
    canvas_importable = _seam("app.api.routes.canvas") == "enabled"
    canvas_state = "enabled" if (canvas_gate_on and canvas_importable) else "disabled"
    return {
        "orientation": _seam("app.api.routes.orientation"),
        "resurfacing": _seam("app.resurfacing"),
        "commitments": _seam("app.domain.commitments"),
        "canvas": canvas_state,
    }


# Register this interaction-layer probe with the Foundation status service so
# get_system_status() can report seam state without importing the interaction
# layer (ADR-0013). Importing this module (which both app.api and app.cli do) is
# what activates the seam field in /api/status output.
register_v6_seams_provider(check_v6_seams)


__all__ = ["check_v6_seams", "register_v6_seams_provider"]
