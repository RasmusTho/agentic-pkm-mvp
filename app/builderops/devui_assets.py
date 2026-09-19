"""The finite shipped DevUI asset inventory, shared without gateway startup."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROUTES = {
    "/devui/overview": ("text/html; charset=utf-8", "overview.html"),
    "/devui/focus": ("text/html; charset=utf-8", "focus.html"),
    "/devui/assets/devui.css": ("text/css; charset=utf-8", "devui.css"),
    "/devui/assets/overview.js": ("text/javascript; charset=utf-8", "overview.js"),
    "/devui/assets/focus.js": ("text/javascript; charset=utf-8", "focus.js"),
}
# Exact reviewed managed candidate bytes; historical Companion assets remain separate.
ASSET_SHA256 = {
    "devui.css": "9bd853fe5007b960d58525a5029f3a2687fdeab5aae161363ec944f19be4a36a",
    "focus.html": "ea1dcbaf91a93c8016e22f80cf967e5eda5cb670ba04c0ab2b59fce5130c4361",
    "focus.js": "5c7e96a5786e46457919a8e2cb45322f7e2713a471ff42c0476d7f97941d2fc1",
    "overview.html": "71070fe77686d033502c983aac687a6a75997422ca3578c48a4797f9be27a8fb",
    "overview.js": "a578f24e0eecb431cdeb7e60f61483d89b20ab16289106ed881ba479703f7ea2",
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
