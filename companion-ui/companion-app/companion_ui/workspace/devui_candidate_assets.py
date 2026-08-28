"""Load only the committed #4836 constrained-reuse candidate assets."""

from __future__ import annotations

import json
from pathlib import Path


_CANDIDATE_ROOT = Path(__file__).with_name("devui_candidate")
_PROVENANCE = Path(__file__).with_name("devui_candidate_provenance.json")
_ROUTES = {
    "/devui/overview": ("text/html; charset=utf-8", "overview.html"),
    "/devui/focus": ("text/html; charset=utf-8", "focus.html"),
    "/devui/assets/devui.css": ("text/css; charset=utf-8", "devui.css"),
    "/devui/assets/overview.js": ("text/javascript; charset=utf-8", "overview.js"),
    "/devui/assets/focus.js": ("text/javascript; charset=utf-8", "focus.js"),
}


def load_devui_candidate_asset(path: str) -> tuple[str, bytes] | None:
    if path == "/devui/assets/provenance.json":
        manifest = json.loads(_PROVENANCE.read_text(encoding="utf-8"))
        public = {
            "schema": manifest["schema"],
            "candidate_tree": manifest["candidate"]["tree"],
            "source_commit": manifest["source"]["commit"],
        }
        return "application/json; charset=utf-8", json.dumps(
            public, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    route = _ROUTES.get(path)
    if route is None:
        return None
    content_type, filename = route
    return content_type, (_CANDIDATE_ROOT / filename).read_bytes()


__all__ = ["load_devui_candidate_asset"]
