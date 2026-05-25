"""Obsidian wikilink parsing and in-memory link resolution boundary.

This module intentionally stays read-only. It parses ``[[...]]`` references and
maps them to vault-relative navigation targets supplied by the caller.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import PurePosixPath
import re
from typing import Literal


_WIKILINK_RE = re.compile(r"(?<!!)\[\[(?P<body>[^\]\n]+)\]\]")


@dataclass(frozen=True)
class WikiLinkRef:
    """Issue-local shape matching the renderer contract's WikiLinkRef."""

    raw: str
    raw_target: str
    target: str
    alias: str | None = None
    heading: str | None = None
    block_id: str | None = None
    local_only: bool = False

    @property
    def display_text(self) -> str:
        return self.alias or self.raw_target


@dataclass(frozen=True)
class LinkResolution:
    """Issue-local shape matching the renderer contract's LinkResolution union."""

    kind: Literal["resolved", "missing", "ambiguous"]
    display_text: str
    note_path: str | None = None
    heading: str | None = None
    block_id: str | None = None
    reason: str | None = None
    candidates: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class NavigationIntent:
    """Read-only navigation command emitted after a resolved link click."""

    kind: Literal["navigate-note"]
    note_path: str
    heading: str | None = None
    block_id: str | None = None


def parse_wikilink(raw: str) -> WikiLinkRef:
    """Parse one Obsidian wikilink token.

    ``raw`` must be a complete ``[[...]]`` token. Embeds are intentionally out of
    scope here and should be handled by the asset resolver slice.
    """

    if raw.startswith("![["):
        raise ValueError("Embed syntax is not a wikilink")
    if not raw.startswith("[[") or not raw.endswith("]]"):
        raise ValueError("Wikilink must be wrapped in [[...]]")

    body = raw[2:-2]
    target_part, alias = _split_alias(body)
    raw_target = target_part.strip()
    target, heading, block_id, local_only = _split_target(raw_target)

    return WikiLinkRef(
        raw=raw,
        raw_target=raw_target,
        target=target,
        alias=alias,
        heading=heading,
        block_id=block_id,
        local_only=local_only,
    )


def parse_wikilinks(markdown: str) -> list[WikiLinkRef]:
    """Return all non-embed Obsidian wikilinks from a Markdown document."""

    return [parse_wikilink(match.group(0)) for match in _WIKILINK_RE.finditer(markdown)]


def link_display_label(resolution: LinkResolution) -> str:
    """Return a visible label for resolved and diagnostic link states."""

    if resolution.kind == "resolved":
        return resolution.display_text
    if resolution.kind == "missing":
        return f"{resolution.display_text} (missing link)"
    if resolution.kind == "ambiguous":
        return f"{resolution.display_text} (ambiguous link)"
    return f"{resolution.display_text} (unresolved link)"


def emit_navigation_intent(resolution: LinkResolution) -> NavigationIntent | None:
    """Convert a resolved link into a navigation intent without mutating vault state."""

    if resolution.kind != "resolved" or not resolution.note_path:
        return None
    return NavigationIntent(
        kind="navigate-note",
        note_path=resolution.note_path,
        heading=resolution.heading,
        block_id=resolution.block_id,
    )


class VaultLinkResolver:
    """In-memory resolver for vault-relative Obsidian note links.

    The caller supplies a note index. This class never reads vault files and
    never creates, renames, or rewrites notes.
    """

    def __init__(self, note_index: Mapping[str, str | Sequence[str]] | Iterable[str]) -> None:
        self._index: dict[str, tuple[str, ...]] = {}
        if isinstance(note_index, Mapping):
            for key, value in note_index.items():
                self._add_key(key, _as_candidates(value))
        else:
            for note_path in note_index:
                self._add_note_path(str(note_path))

    def resolve(
        self,
        link: WikiLinkRef | Mapping[str, object] | None = None,
        *,
        note_path: str = "",
        raw_target: str | None = None,
        target: str | None = None,
        heading: str | None = None,
        block_id: str | None = None,
        alias: str | None = None,
        local_only: bool | None = None,
    ) -> LinkResolution:
        """Resolve a parsed link or explicit contract-style params."""

        if isinstance(link, Mapping):
            note_path = _optional_str(link.get("notePath", link.get("note_path"))) or note_path
            raw_target = _optional_str(link.get("rawTarget", link.get("raw_target"))) or raw_target
            target = _optional_str(link.get("target")) or target
            heading = _optional_str(link.get("heading")) or heading
            block_id = _optional_str(link.get("blockId", link.get("block_id"))) or block_id
            alias = _optional_str(link.get("alias")) or alias
            local_only = bool(link.get("localOnly", link.get("local_only", False))) or local_only
        elif link is not None:
            raw_target = link.raw_target
            target = link.target
            heading = link.heading
            block_id = link.block_id
            alias = link.alias
            local_only = link.local_only

        raw_target = (raw_target or target or "").strip()
        if target is None:
            target, parsed_heading, parsed_block_id, parsed_local_only = _split_target(raw_target)
            heading = heading or parsed_heading
            block_id = block_id or parsed_block_id
            if local_only is None:
                local_only = parsed_local_only
        else:
            target = target.strip()
        display_text = alias or raw_target

        if local_only or (not target and (heading or block_id)):
            return self._resolve_local(
                note_path=note_path,
                display_text=display_text,
                heading=heading,
                block_id=block_id,
            )

        candidates = self._lookup(target)
        if not candidates:
            return LinkResolution(
                kind="missing",
                display_text=display_text,
                heading=heading,
                block_id=block_id,
                reason=f"No note matches {target!r}",
            )

        if len(candidates) > 1:
            return LinkResolution(
                kind="ambiguous",
                display_text=display_text,
                heading=heading,
                block_id=block_id,
                candidates=candidates,
            )

        return LinkResolution(
            kind="resolved",
            display_text=display_text,
            note_path=candidates[0],
            heading=heading,
            block_id=block_id,
        )

    def _resolve_local(
        self,
        *,
        note_path: str,
        display_text: str,
        heading: str | None,
        block_id: str | None,
    ) -> LinkResolution:
        if not note_path:
            return LinkResolution(
                kind="missing",
                display_text=display_text,
                heading=heading,
                block_id=block_id,
                reason="Local link requires the current note path",
            )
        return LinkResolution(
            kind="resolved",
            display_text=display_text,
            note_path=note_path,
            heading=heading,
            block_id=block_id,
        )

    def _lookup(self, target: str) -> tuple[str, ...]:
        keys = _candidate_keys(target)
        seen: list[str] = []
        for key in keys:
            for candidate in self._index.get(key, ()):
                if candidate not in seen:
                    seen.append(candidate)
        return tuple(seen)

    def _add_note_path(self, note_path: str) -> None:
        safe_path = _vault_relative_path(note_path)
        path = PurePosixPath(safe_path)
        stem_path = str(path.with_suffix("")) if path.suffix == ".md" else safe_path
        keys = {
            safe_path,
            stem_path,
            path.name,
            path.stem,
        }
        for key in keys:
            self._add_key(key, (safe_path,))

    def _add_key(self, key: str, candidates: tuple[str, ...]) -> None:
        normalized_key = _normalize_key(key)
        existing = list(self._index.get(normalized_key, ()))
        for candidate in candidates:
            safe_candidate = _vault_relative_path(candidate)
            if safe_candidate not in existing:
                existing.append(safe_candidate)
        self._index[normalized_key] = tuple(existing)


def _split_alias(body: str) -> tuple[str, str | None]:
    target_part, separator, alias_part = body.partition("|")
    if not separator:
        return target_part, None
    alias = alias_part.strip()
    return target_part, alias or None


def _split_target(raw_target: str) -> tuple[str, str | None, str | None, bool]:
    if raw_target.startswith("#"):
        fragment = raw_target[1:].strip()
        return "", fragment or None, None, True

    if raw_target.startswith("^"):
        block_id = raw_target[1:].strip()
        return "", None, block_id or None, True

    note_target, separator, fragment = raw_target.partition("#")
    target = note_target.strip()
    if not separator:
        return target, None, None, False

    fragment = fragment.strip()
    if fragment.startswith("^"):
        block_id = fragment[1:].strip()
        return target, None, block_id or None, False
    return target, fragment or None, None, False


def _as_candidates(value: str | Sequence[str]) -> tuple[str, ...]:
    if isinstance(value, str):
        return (_vault_relative_path(value),)
    return tuple(_vault_relative_path(candidate) for candidate in value)


def _candidate_keys(target: str) -> tuple[str, ...]:
    normalized = _normalize_key(target)
    path = PurePosixPath(normalized)
    keys = [normalized]
    if path.suffix == ".md":
        keys.append(str(path.with_suffix("")))
    else:
        keys.append(f"{normalized}.md")
    keys.extend([path.name, path.stem])
    return tuple(dict.fromkeys(key for key in keys if key))


def _normalize_key(value: str) -> str:
    return value.strip().replace("\\", "/").removeprefix("./")


def _vault_relative_path(value: str) -> str:
    normalized = _normalize_key(value)
    if normalized.startswith("/") or re.match(r"^[A-Za-z]:/", normalized):
        raise ValueError("Vault link resolver only accepts vault-relative note paths")
    return normalized


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)
