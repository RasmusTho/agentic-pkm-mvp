"""Load only the committed #4836 constrained-reuse candidate assets."""

from __future__ import annotations

from pathlib import Path


_CANDIDATE_ROOT = Path(__file__).with_name("devui_candidate")
_ROUTES = {
    "/devui/overview": ("text/html; charset=utf-8", "overview.html"),
    "/devui/focus": ("text/html; charset=utf-8", "focus.html"),
    "/devui/assets/devui.css": ("text/css; charset=utf-8", "devui.css"),
    "/devui/assets/overview.js": ("text/javascript; charset=utf-8", "overview.js"),
    "/devui/assets/focus.js": ("text/javascript; charset=utf-8", "focus.js"),
}


def load_devui_candidate_asset(path: str) -> tuple[str, bytes] | None:
    route = _ROUTES.get(path)
    if route is None:
        return None
    content_type, filename = route
    return content_type, (_CANDIDATE_ROOT / filename).read_bytes()


__all__ = ["load_devui_candidate_asset"]
