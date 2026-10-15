"""Bootstrap YouTube subscriptions and playlists from a Google Takeout export.

The onboarding file is deliberately source metadata only. It does not contact YouTube,
fetch videos, or write vault notes. The later sync worker can use the registry to poll
subscription RSS feeds and backfill explicit playlists through the existing plugin.
"""

from __future__ import annotations

import csv
import json
import re
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse, parse_qs


REGISTRY_FILENAME = "youtube-sources.json"


@dataclass(frozen=True)
class YouTubeSource:
    """A followed collection, independent of any acquired video."""

    source_id: str
    kind: str  # subscription | playlist
    title: str
    url: str
    channel_id: str | None = None
    playlist_id: str | None = None
    cursor: str | None = None


@dataclass(frozen=True)
class OnboardingRegistry:
    version: int
    sources: tuple[YouTubeSource, ...]

    def as_dict(self) -> dict[str, object]:
        return {"version": self.version, "sources": [asdict(source) for source in self.sources]}


@dataclass(frozen=True)
class TakeoutImportResult:
    imported: int
    deduplicated: int
    binding_ids: tuple[str, ...]


def _value(row: dict[str, str], *names: str) -> str:
    normalized = {key.strip().lower().replace(" ", "_"): value.strip() for key, value in row.items()}
    for name in names:
        value = normalized.get(name)
        if value:
            return value
    return ""


def _channel_id_from_url(url: str) -> str | None:
    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) == 2 and parts[0] == "channel" and parts[1].startswith("UC"):
        return parts[1]
    return None


def _playlist_id_from_url(url: str) -> str | None:
    value = parse_qs(urlparse(url).query).get("list", [None])[0]
    return value or None


def _read_csv(path: Path) -> Iterable[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        yield from csv.DictReader(handle)


def parse_takeout(takeout_root: Path) -> OnboardingRegistry:
    """Parse subscriptions.csv and playlist CSV exports into a stable registry.

    Takeout has changed column spelling over time, so headers are matched by semantic
    aliases. Unknown CSVs are ignored; malformed rows are skipped rather than allowing
    one unrelated export file to abort the whole bootstrap.
    """
    root = takeout_root.expanduser().resolve()
    subscriptions: list[YouTubeSource] = []
    playlists: list[YouTubeSource] = []
    seen: set[tuple[str, str]] = set()

    subscription_files = list(root.rglob("subscriptions.csv"))
    for path in subscription_files:
        for row in _read_csv(path):
            channel_id = _value(row, "channel_id", "channelid")
            title = _value(row, "channel_title", "channeltitle", "title")
            url = _value(row, "channel_url", "channelurl", "url")
            channel_id = channel_id or _channel_id_from_url(url) or ""
            if not channel_id:
                continue
            source_url = f"https://www.youtube.com/channel/{channel_id}"
            key = ("subscription", channel_id)
            if key not in seen:
                subscriptions.append(YouTubeSource(channel_id, "subscription", title or channel_id, source_url, channel_id=channel_id))
                seen.add(key)

    for path in root.rglob("*.csv"):
        if path.name.lower() == "subscriptions.csv":
            continue
        for row in _read_csv(path):
            playlist_id = _value(row, "playlist_id", "playlistid") or _playlist_id_from_url(_value(row, "playlist_url", "playlisturl", "url"))
            title = _value(row, "playlist_title", "playlisttitle", "title")
            if not playlist_id:
                continue
            key = ("playlist", playlist_id)
            if key not in seen:
                playlists.append(YouTubeSource(playlist_id, "playlist", title or playlist_id, f"https://www.youtube.com/playlist?list={playlist_id}", playlist_id=playlist_id))
                seen.add(key)

    return OnboardingRegistry(version=1, sources=tuple(sorted((*subscriptions, *playlists), key=lambda item: (item.kind, item.title.casefold(), item.source_id))))


def load_registry(path: Path) -> OnboardingRegistry:
    payload = json.loads(path.read_text(encoding="utf-8"))
    sources = tuple(YouTubeSource(**item) for item in payload.get("sources", []))
    return OnboardingRegistry(version=int(payload.get("version", 1)), sources=sources)


def save_registry(path: Path, registry: OnboardingRegistry) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(registry.as_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


_CHANNEL_ID_RE = re.compile(r"UC[A-Za-z0-9_-]{22}\Z")
_PLAYLIST_ID_RE = re.compile(r"PL[A-Za-z0-9_-]+\Z")


def import_takeout_registry(
    takeout_root: Path,
    *,
    registry: Any,
    account_binding_id: str | None = None,
) -> TakeoutImportResult:
    """Import Takeout sources into the durable YSS-01 registry idempotently.

    The snapshot never removes rows absent from a later export, and existing
    bindings are not rewritten (their cursor, policy, enablement, and history
    are live operator state rather than Takeout snapshot data).
    """
    from app.knowledge_acquisition.source_registry import (
        DuplicateBindingError,
        SourceRegistryValidationError,
    )

    if account_binding_id is None:
        normalized_account_id = None
    elif isinstance(account_binding_id, str):
        try:
            normalized_account_id = str(uuid.UUID(account_binding_id.strip()))
        except (ValueError, AttributeError) as exc:
            raise SourceRegistryValidationError("account_binding_id must be a valid UUID or None") from exc
    else:
        raise SourceRegistryValidationError("account_binding_id must be a UUID string or None")

    snapshot = parse_takeout(takeout_root)
    planned: list[tuple[str, str, str]] = []
    for source in snapshot.sources:
        if source.kind == "subscription":
            channel_id = source.channel_id or source.source_id
            if _CHANNEL_ID_RE.fullmatch(channel_id) is None:
                raise SourceRegistryValidationError("Takeout subscription contained an invalid channel id")
            planned.append(("subscription_feed", channel_id, source.title))
        elif source.kind == "playlist":
            playlist_id = source.playlist_id or source.source_id
            if playlist_id == "LL":
                collection_kind = "liked_videos"
            elif _PLAYLIST_ID_RE.fullmatch(playlist_id):
                collection_kind = "owned_playlist"
            else:
                raise SourceRegistryValidationError("Takeout playlist contained an invalid playlist id")
            if normalized_account_id is None:
                raise SourceRegistryValidationError(
                    "account_binding_id is required to import Takeout playlist bindings"
                )
            planned.append((collection_kind, playlist_id, source.title))
        else:
            raise SourceRegistryValidationError(f"unsupported Takeout source kind: {source.kind!r}")

    existing = {
        (binding.collection_kind, binding.collection_ref, binding.account_binding_id): binding.binding_id
        for binding in registry.list_all()
    }
    imported = deduplicated = 0
    binding_ids: list[str] = []
    for collection_kind, collection_ref, title in planned:
        binding_account_id = (
            normalized_account_id
            if collection_kind in {"owned_playlist", "liked_videos"}
            else None
        )
        key = (collection_kind, collection_ref, binding_account_id)
        binding_id = existing.get(key)
        if binding_id is None:
            try:
                binding = registry.register(
                    collection_kind=collection_kind,
                    collection_ref=collection_ref,
                    title=title,
                    account_binding_id=binding_account_id,
                    acquisition_policy={"mode": "discover_only"},
                    provenance={"origin": "takeout_import"},
                )
                binding_id = binding.binding_id
                imported += 1
                existing[key] = binding_id
            except DuplicateBindingError:
                # A concurrent import won the unique-key race. Re-read the
                # key and count it as the same idempotent outcome.
                latest = registry.list_all()
                duplicate = next(
                    (
                        item
                        for item in latest
                        if (item.collection_kind, item.collection_ref, item.account_binding_id) == key
                    ),
                    None,
                )
                if duplicate is None:
                    raise
                binding_id = duplicate.binding_id
                existing[key] = binding_id
                deduplicated += 1
        else:
            deduplicated += 1
        binding_ids.append(binding_id)
    return TakeoutImportResult(imported, deduplicated, tuple(binding_ids))


__all__ = [
    "OnboardingRegistry",
    "REGISTRY_FILENAME",
    "TakeoutImportResult",
    "YouTubeSource",
    "import_takeout_registry",
    "load_registry",
    "parse_takeout",
    "save_registry",
]
