"""CodeMirror 6 source-mode NoteEditorAdapter spike.

This module is deliberately isolated from the production note surface. It
models the adapter boundary needed for a future browser CodeMirror integration
while proving that raw Obsidian-flavored Markdown can round-trip without
normalization, autosave, or direct vault writes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class SelectionRange:
    """Simple text selection range for the conceptual adapter contract."""

    start: int
    end: int


@dataclass(frozen=True)
class BodyPatch:
    """Governed in-memory body patch supplied by Canvas/Panel in future wiring."""

    start: int
    end: int
    replacement: str
    governed: bool = True


class CodeMirrorNoteEditorAdapter:
    """In-memory source-mode adapter for the CodeMirror spike.

    The spike does not instantiate the browser CodeMirror package because this
    repository has no npm/React frontend module yet. The boundary deliberately
    mirrors CodeMirror's source document behavior: content is stored as raw
    text and returned byte-for-byte unless an explicit governed patch is
    applied.
    """

    runtime = "codemirror-6-source-mode-spike"
    production_wired = False
    autosave_enabled = False
    recommendation = "defer"

    def __init__(self, markdown: str = "") -> None:
        self._markdown = str(markdown)
        self._selection: SelectionRange | None = None
        self._write_calls: tuple[str, ...] = ()

    @property
    def write_calls(self) -> tuple[str, ...]:
        return self._write_calls

    def getMarkdown(self) -> str:
        """Return raw Markdown exactly as held by the adapter."""

        return self._markdown

    def setMarkdown(self, markdown: str) -> None:
        """Replace in-memory editor content without normalization or autosave."""

        self._markdown = str(markdown)

    def getSelection(self) -> SelectionRange | None:
        """Return the current selection range, if one is known."""

        return self._selection

    def setSelection(self, start: int, end: int) -> None:
        """Test helper matching the conceptual selection state CodeMirror exposes."""

        bounded_start = _clamp(start, 0, len(self._markdown))
        bounded_end = _clamp(end, bounded_start, len(self._markdown))
        self._selection = SelectionRange(start=bounded_start, end=bounded_end)

    def applyBodyPatch(self, patch: BodyPatch | Mapping[str, object]) -> None:
        """Apply a governed in-memory body patch.

        This is intentionally not a persistence operation. Ungoverned patches
        are rejected because future production wiring must route through the
        Panel/Canvas governance path.
        """

        normalized = _coerce_patch(patch)
        if not normalized.governed:
            raise ValueError("CodeMirror adapter spike rejects ungoverned body patches")

        start = _clamp(normalized.start, 0, len(self._markdown))
        end = _clamp(normalized.end, start, len(self._markdown))
        self._markdown = (
            self._markdown[:start]
            + normalized.replacement
            + self._markdown[end:]
        )
        self._selection = SelectionRange(
            start=start,
            end=start + len(normalized.replacement),
        )

    def focusBlock(self, block_id: str) -> bool:
        """Move selection to an Obsidian block id marker when present."""

        marker = f"^{block_id}"
        index = self._markdown.find(marker)
        if index < 0:
            return False
        self._selection = SelectionRange(start=index, end=index + len(marker))
        return True


def _coerce_patch(patch: BodyPatch | Mapping[str, object]) -> BodyPatch:
    if isinstance(patch, BodyPatch):
        return patch
    return BodyPatch(
        start=int(patch.get("start", 0)),
        end=int(patch.get("end", 0)),
        replacement=str(patch.get("replacement", "")),
        governed=bool(patch.get("governed", True)),
    )


def _clamp(value: int, lower: int, upper: int) -> int:
    return max(lower, min(int(value), upper))
