"""Load only the committed #4836 constrained-reuse candidate assets and the generated
CSP-compatible Yggdrasil token sheet they link (#5637)."""

from __future__ import annotations

from pathlib import Path


_CANDIDATE_ROOT = Path(__file__).with_name("devui_candidate")
_ROUTES = {
    "/devui/overview": ("text/html; charset=utf-8", _CANDIDATE_ROOT / "overview.html"),
    "/devui/focus": ("text/html; charset=utf-8", _CANDIDATE_ROOT / "focus.html"),
    "/devui/assets/yggdrasil.css": ("text/css; charset=utf-8", Path(__file__).with_name("devui_yggdrasil.css")),
    "/devui/assets/devui.css": ("text/css; charset=utf-8", _CANDIDATE_ROOT / "devui.css"),
    "/devui/assets/overview.js": ("text/javascript; charset=utf-8", _CANDIDATE_ROOT / "overview.js"),
    "/devui/assets/focus.js": ("text/javascript; charset=utf-8", _CANDIDATE_ROOT / "focus.js"),
}


def load_devui_candidate_asset(path: str) -> tuple[str, bytes] | None:
    route = _ROUTES.get(path)
    if route is None:
        return None
    content_type, asset_path = route
    with open(asset_path, "rb") as asset_file:
        return content_type, asset_file.read()


__all__ = ["load_devui_candidate_asset"]
