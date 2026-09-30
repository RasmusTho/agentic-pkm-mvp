"""The finite shipped DevUI asset inventory, shared without gateway startup."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROUTES = {
    "/devui/overview": ("text/html; charset=utf-8", "overview.html"),
    "/devui/focus": ("text/html; charset=utf-8", "focus.html"),
    "/devui/assets/yggdrasil.css": ("text/css; charset=utf-8", "yggdrasil.css"),
    "/devui/assets/devui.css": ("text/css; charset=utf-8", "devui.css"),
    "/devui/assets/overview.js": ("text/javascript; charset=utf-8", "overview.js"),
    "/devui/assets/focus.js": ("text/javascript; charset=utf-8", "focus.js"),
}
# Exact reviewed managed candidate bytes; historical Companion assets remain separate.
ASSET_SHA256 = {
    "devui.css": "04f248ebed67ed91cf4356a280d90eac05ea6f811faa3323c1370537de7661ce",
    "focus.html": "464e2f2ee5ba59268177261ac6f8f9464cb024caac567d8054e13c058a3a753e",
    "focus.js": "47454f62ab51cde497741504669903f235eee3e131380ea7692f0bcc78d25f0b",
    "overview.html": "6e0b20cf2aca808d1330bc6033994e9f9acb7b17c9cf46d3f61479995fa7b2b5",
    "overview.js": "873c9de9bbc8eb85410f0f6450b477cfc52346ff42a921588d8d33494581b4b2",
    "yggdrasil.css": "1cffbb6d4226a1ad593902b7b72ec54fb76a39f071ae64bd74bc1176331a203b",
}
INVENTORY_SHA256 = (
    "sha256:"
    + hashlib.sha256(
        json.dumps(ASSET_SHA256, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
)
CSP = (
    "default-src 'none'; base-uri 'none'; connect-src 'self'; "
    "font-src 'none'; form-action 'none'; frame-ancestors 'none'; "
    "img-src 'self' data:; object-src 'none'; script-src 'self'; style-src 'self'"
)


class CandidateAssetError(ValueError):
    """Missing or inconsistent addressed shell packaging; withdraw the journey."""


def load_asset(root: Path, path: str) -> tuple[str, bytes] | None:
    route = ROUTES.get(path)
    if route is None:
        return None
    content_type, filename = route
    return content_type, (root / filename).read_bytes()


def validate_packaged_assets(
    root: Path, *, source_sha: str, repository: str | None
) -> dict[str, Any]:
    """Read and validate one complete asset snapshot before a source read.

    Manifest identity is an image diagnostic, not independent image attestation.
    Return the checked bytes so a response cannot reread a different file.
    """
    try:
        if (
            root.is_symlink()
            or (root / "manifest.json").is_symlink()
            or (root / "assets").is_symlink()
        ):
            raise CandidateAssetError()
        manifest = json.loads((root / "manifest.json").read_text())
        if manifest["source_sha"] != source_sha or (
            repository and manifest["repository"] != repository
        ):
            raise CandidateAssetError()
        if not isinstance(manifest.get("repository"), str) or not manifest["repository"]:
            raise CandidateAssetError()
        paths = list((root / "assets").iterdir())
        if {path.name for path in paths} != set(ASSET_SHA256):
            raise CandidateAssetError()
        contents = {}
        for path in paths:
            if path.is_symlink() or not path.is_file():
                raise CandidateAssetError()
            content = path.read_bytes()
            digest = hashlib.sha256(content).hexdigest()
            if (
                digest != ASSET_SHA256[path.name]
                or manifest["files"].get("assets/" + path.name) != digest
            ):
                raise CandidateAssetError()
            contents[path.name] = content
        return contents
    except (KeyError, TypeError, ValueError, OSError, AttributeError) as exc:
        raise CandidateAssetError(
            "Managed DevUI candidate assets or metadata are unavailable"
        ) from exc
