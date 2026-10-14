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
    "control.html": "f6f2496dbaecdd042255fa4aa568cd8d5a32c0a1b1ed7542ed8a86316a8a245f",
    "devui.css": "04f248ebed67ed91cf4356a280d90eac05ea6f811faa3323c1370537de7661ce",
    "focus.html": "34fefea890511220d74c458a26fa2a71008ccb9529c71192466dbbf4c70a2081",
    "focus.js": "199c9c47b92232dcf584472de38a3a0370eca9f90992f48e50f8dcc5ec291053",
    "overview.html": "950402b8c8bea8443f9fe40e1402f393a3a6ba210366a74adf2a6013961ee6c1",
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
