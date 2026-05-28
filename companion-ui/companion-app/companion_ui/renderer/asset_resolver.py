"""Obsidian embed parsing and asset-resolution boundary for Companion UI."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import re
from typing import Literal
from urllib.parse import quote, urlparse

EmbedKind = Literal["image", "note", "pdf", "audio", "video", "canvas", "unknown"]
AssetInputKind = Literal["markdown-image", "obsidian-embed"]
AssetResolutionKind = Literal["allowed", "missing", "blocked", "unsupported"]

IMAGE_EXTENSIONS = {".avif", ".bmp", ".gif", ".jpeg", ".jpg", ".png", ".svg", ".webp"}
AUDIO_EXTENSIONS = {".flac", ".m4a", ".mp3", ".ogg", ".opus", ".wav"}
VIDEO_EXTENSIONS = {".avi", ".m4v", ".mov", ".mp4", ".mpeg", ".mpg", ".ogv", ".webm"}

_OBSIDIAN_EMBED_RE = re.compile(r"!\[\[(?P<target>[^\]\n]+)\]\]")
_SIZE_HINT_RE = re.compile(r"^(?P<width>\d+)(?:[xX](?P<height>\d+))?$")
_WINDOWS_ABSOLUTE_PATH_RE = re.compile(r"^[A-Za-z]:[\\/]")
_LOCAL_PATH_PREFIXES = (
    "/Users/",
    "/home/",
    "/private/",
    "/tmp/",
    "/var/",
    "/Volumes/",
)


@dataclass(frozen=True)
class EmbedRef:
    """Issue-local EmbedRef model until the shared renderer models module lands."""

    raw: str
    target: str
    kind: EmbedKind
    width: int | None = None
    height: int | None = None
    heading: str | None = None
    block_id: str | None = None
    fragment: str | None = None

    @property
    def blockId(self) -> str | None:
        """Compatibility accessor matching the contract field spelling."""
        return self.block_id


@dataclass(frozen=True)
class AssetResolution:
    """Issue-local AssetResolution model for resolver contract tests."""

    kind: AssetResolutionKind
    display_name: str
    src: str | None = None
    width: int | None = None
    height: int | None = None
    reason: str | None = None

    @property
    def displayName(self) -> str:
        """Compatibility accessor matching the contract field spelling."""
        return self.display_name

    def to_dict(self) -> dict[str, str | int | None]:
        return {
            "kind": self.kind,
            "displayName": self.display_name,
            "src": self.src,
            "width": self.width,
            "height": self.height,
            "reason": self.reason,
        }

    def __getitem__(self, key: str) -> str | int | None:
        return self.to_dict()[key]


def parse_obsidian_embed(raw_embed: str) -> EmbedRef:
    """Parse one Obsidian embed token or raw target into an EmbedRef."""

    raw = raw_embed.strip()
    inner = _extract_embed_inner(raw)
    target_with_fragment, size_hint = _split_size_hint(inner)
    width, height = _parse_size_hint(size_hint)
    target, fragment = _split_fragment(target_with_fragment)

    block_id = None
    heading = None
    if fragment:
        if fragment.startswith("^"):
            block_id = fragment[1:] or None
        else:
            heading = fragment

    target, legacy_block_id = _split_legacy_block_id(target)
    if legacy_block_id and block_id is None:
        block_id = legacy_block_id

    kind = classify_embed_target(target)
    if not raw.startswith("![["):
        raw = f"![[{inner}]]"

    return EmbedRef(
        raw=raw,
        target=target,
        kind=kind,
        width=width,
        height=height,
        heading=heading,
        block_id=block_id,
        fragment=fragment,
    )


def parse_obsidian_embeds(markdown: str) -> list[EmbedRef]:
    """Return every Obsidian embed token in markdown source order."""

    return [parse_obsidian_embed(match.group(0)) for match in _OBSIDIAN_EMBED_RE.finditer(markdown)]


extract_obsidian_embeds = parse_obsidian_embeds


def classify_embed_target(target: str) -> EmbedKind:
    """Classify an Obsidian embed target without touching the filesystem."""

    normalized = target.strip()
    if not normalized or normalized.lower().startswith("query/"):
        return "unknown"

    extension = _extension_from_target(normalized)
    if extension in IMAGE_EXTENSIONS:
        return "image"
    if extension == ".pdf":
        return "pdf"
    if extension in AUDIO_EXTENSIONS:
        return "audio"
    if extension in VIDEO_EXTENSIONS:
        return "video"
    if extension == ".canvas":
        return "canvas"
    if extension:
        return "unknown"
    return "note"


class VaultAssetResolver:
    """In-memory resolver stub that enforces the browser asset boundary."""

    def __init__(
        self,
        allowed_assets: Mapping[str, str | None | bool] | Iterable[str] | None = None,
        *,
        allow_remote: bool = False,
    ) -> None:
        self.allow_remote = allow_remote
        self._allowed_assets = _coerce_allowed_assets(allowed_assets)

    def resolve(
        self,
        params: Mapping[str, object] | None = None,
        *,
        note_path: str | None = None,
        raw_target: str | None = None,
        kind: AssetInputKind | str | None = None,
    ) -> AssetResolution:
        """Resolve an asset request without filesystem access or file URLs."""

        if params is not None:
            note_path = str(params.get("notePath") or params.get("note_path") or note_path or "")
            raw_target = str(
                params.get("rawTarget") or params.get("raw_target") or raw_target or ""
            )
            kind = str(params.get("kind") or kind or "")

        _ = note_path
        raw_target = (raw_target or "").strip()
        input_kind = _normalize_input_kind(kind, raw_target)

        if input_kind == "obsidian-embed":
            embed = parse_obsidian_embed(raw_target)
            return self._resolve_obsidian_embed(embed)
        return self._resolve_markdown_image(raw_target)

    def _resolve_obsidian_embed(self, embed: EmbedRef) -> AssetResolution:
        display_name = _display_name(embed.target)
        if _is_blocked_target(embed.target, allow_remote=self.allow_remote):
            return AssetResolution(
                kind="blocked",
                display_name=display_name,
                reason="Remote and file-scheme embeds are blocked by default policy.",
            )

        if embed.kind != "image":
            return AssetResolution(
                kind="unsupported",
                display_name=display_name,
                reason=f"{embed.kind} embeds are diagnostic-only in this phase.",
            )

        return self._resolve_local_asset(embed.target, width=embed.width, height=embed.height)

    def _resolve_markdown_image(self, raw_target: str) -> AssetResolution:
        display_name = _display_name(raw_target)
        if _is_blocked_target(raw_target, allow_remote=self.allow_remote):
            return AssetResolution(
                kind="blocked",
                display_name=display_name,
                reason="Remote and file-scheme images are blocked by default policy.",
            )
        return self._resolve_local_asset(raw_target)

    def _resolve_local_asset(
        self,
        target: str,
        *,
        width: int | None = None,
        height: int | None = None,
    ) -> AssetResolution:
        normalized = _normalize_asset_key(target)
        display_name = _display_name(normalized)

        if normalized not in self._allowed_assets:
            return AssetResolution(
                kind="missing",
                display_name=display_name,
                reason="Asset is not available through the resolver boundary.",
            )

        configured_src = self._allowed_assets[normalized]
        src = configured_src or _default_asset_src(normalized)
        if not _is_browser_safe_src(src):
            return AssetResolution(
                kind="blocked",
                display_name=display_name,
                reason="Resolved asset source is not browser-safe.",
            )

        return AssetResolution(
            kind="allowed",
            display_name=display_name,
            src=src,
            width=width,
            height=height,
        )


def _extract_embed_inner(raw: str) -> str:
    match = _OBSIDIAN_EMBED_RE.fullmatch(raw)
    if match:
        return match.group("target").strip()
    return raw.strip()


def _split_size_hint(inner: str) -> tuple[str, str | None]:
    target, separator, hint = inner.partition("|")
    if not separator:
        return target.strip(), None
    return target.strip(), hint.strip()


def _parse_size_hint(size_hint: str | None) -> tuple[int | None, int | None]:
    if not size_hint:
        return None, None

    match = _SIZE_HINT_RE.fullmatch(size_hint.strip())
    if not match:
        return None, None

    width = int(match.group("width"))
    height = int(match.group("height")) if match.group("height") else None
    return width, height


def _split_fragment(target: str) -> tuple[str, str | None]:
    base, separator, fragment = target.partition("#")
    if not separator:
        return target.strip(), None
    return base.strip(), fragment.strip() or None


def _split_legacy_block_id(target: str) -> tuple[str, str | None]:
    base, separator, block_id = target.partition("^")
    if not separator:
        return target.strip(), None
    return base.strip(), block_id.strip() or None


def _extension_from_target(target: str) -> str:
    parsed = urlparse(target)
    path = parsed.path or target
    filename = path.rsplit("/", 1)[-1].lower()
    if "." not in filename:
        return ""
    return f".{filename.rsplit('.', 1)[-1]}"


def _normalize_input_kind(kind: AssetInputKind | str | None, raw_target: str) -> AssetInputKind:
    if kind in {"markdown-image", "obsidian-embed"}:
        return kind
    if raw_target.strip().startswith("![["):
        return "obsidian-embed"
    return "markdown-image"


def _coerce_allowed_assets(
    allowed_assets: Mapping[str, str | None | bool] | Iterable[str] | None,
) -> dict[str, str | None]:
    if allowed_assets is None:
        return {}

    if isinstance(allowed_assets, Mapping):
        return {
            _normalize_asset_key(str(target)): None if src is True else (str(src) if src else None)
            for target, src in allowed_assets.items()
        }

    return {_normalize_asset_key(str(target)): None for target in allowed_assets}


def _normalize_asset_key(target: str) -> str:
    if target.strip().startswith("![["):
        return parse_obsidian_embed(target).target
    return target.strip()


def _is_blocked_target(target: str, *, allow_remote: bool) -> bool:
    parsed = urlparse(target.strip())
    if parsed.scheme in {"file", "javascript", "data"}:
        return True
    if parsed.scheme in {"http", "https"}:
        return not allow_remote
    return False


def _is_browser_safe_src(src: str) -> bool:
    stripped = src.strip()
    parsed = urlparse(stripped)
    if parsed.scheme in {"file", "javascript", "data"}:
        return False
    if _WINDOWS_ABSOLUTE_PATH_RE.match(stripped):
        return False
    return not stripped.startswith(_LOCAL_PATH_PREFIXES)


def _default_asset_src(target: str) -> str:
    return f"/api/companion/vault-assets/{quote(target, safe='')}"


def _display_name(target: str) -> str:
    parsed = urlparse(target.strip())
    path = parsed.path or target.strip()
    name = path.rstrip("/").rsplit("/", 1)[-1]
    return name or target.strip() or "asset"
