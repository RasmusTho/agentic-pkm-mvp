"""Obsidian callout rendering for the Companion UI note surface."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import html
import re


CALLOUT_HEADER_RE = re.compile(
    r"^\s*>\s*\[!([A-Za-z0-9_-]+)\]([+-])?(?:\s+(.*))?\s*$"
)
_QUOTED_LINE_RE = re.compile(r"^\s*>\s?(.*)$")

_CALLOUT_TYPE_ALIASES = {
    "abstract": "abstract",
    "summary": "abstract",
    "tldr": "abstract",
    "info": "info",
    "todo": "todo",
    "tip": "tip",
    "hint": "tip",
    "important": "tip",
    "success": "success",
    "check": "success",
    "done": "success",
    "question": "question",
    "help": "question",
    "faq": "question",
    "warning": "warning",
    "caution": "warning",
    "attention": "warning",
    "failure": "failure",
    "fail": "failure",
    "missing": "failure",
    "danger": "danger",
    "error": "danger",
    "bug": "bug",
    "example": "example",
    "quote": "quote",
    "cite": "quote",
    "note": "note",
}


@dataclass(frozen=True)
class ObsidianCallout:
    """Parsed Obsidian callout block."""

    callout_type: str
    visual_type: str
    title: str
    fold_state: str
    body_markdown: str
    supported: bool


class ObsidianCalloutRenderer:
    """Render Obsidian `> [!type]` callouts without mutating Markdown."""

    def parse(self, lines: list[str], start: int) -> tuple[ObsidianCallout, int]:
        match = CALLOUT_HEADER_RE.match(lines[start])
        if not match:
            raise ValueError("line is not an Obsidian callout header")

        callout_type = match.group(1).lower()
        fold_marker = match.group(2)
        explicit_title = (match.group(3) or "").strip()
        index = start + 1
        body_lines: list[str] = []

        while index < len(lines):
            quoted_line = _QUOTED_LINE_RE.match(lines[index])
            if not quoted_line:
                break
            body_lines.append(quoted_line.group(1))
            index += 1

        visual_type = _CALLOUT_TYPE_ALIASES.get(callout_type, "note")
        body_markdown = "\n".join(body_lines).strip("\n")

        return (
            ObsidianCallout(
                callout_type=callout_type,
                visual_type=visual_type,
                title=explicit_title or _default_title(callout_type),
                fold_state=_fold_state(fold_marker),
                body_markdown=body_markdown,
                supported=callout_type in _CALLOUT_TYPE_ALIASES,
            ),
            index,
        )

    def render_from_lines(
        self,
        lines: list[str],
        start: int,
        *,
        render_body: Callable[[str], str],
        render_title: Callable[[str], str] | None = None,
    ) -> tuple[str, int]:
        callout, index = self.parse(lines, start)
        return (
            self.render(
                callout,
                render_body=render_body,
                render_title=render_title,
            ),
            index,
        )

    def render(
        self,
        callout: ObsidianCallout,
        *,
        render_body: Callable[[str], str],
        render_title: Callable[[str], str] | None = None,
    ) -> str:
        body_html = render_body(callout.body_markdown) if callout.body_markdown else ""
        title_html = (
            render_title(callout.title) if render_title is not None else html.escape(callout.title)
        )
        classes = " ".join(
            [
                "vault-callout",
                f"vault-callout--{_class_token(callout.visual_type)}",
                f"vault-callout-source--{_class_token(callout.callout_type)}",
            ]
        )
        attrs = (
            f'class="{classes}" '
            f'data-callout-type="{_e(callout.callout_type)}" '
            f'data-callout-visual-type="{_e(callout.visual_type)}" '
            f'data-callout-supported="{str(callout.supported).lower()}"'
        )
        title = (
            '<span class="vault-callout-title">'
            f"{title_html}"
            "</span>"
        )
        icon = (
            '<span class="vault-callout-icon" aria-hidden="true">'
            f"{_e(_icon_label(callout.visual_type))}"
            "</span>"
        )
        body = (
            '<div class="vault-callout-body">'
            f"{body_html}"
            "</div>"
            if body_html
            else ""
        )

        if callout.fold_state != "none":
            open_attr = " open" if callout.fold_state == "expanded" else ""
            return (
                f"<details {attrs} "
                f'data-callout-fold="{_e(callout.fold_state)}"{open_attr}>'
                f'<summary class="vault-callout-header">{icon}{title}</summary>'
                f"{body}"
                "</details>"
            )

        return (
            f"<section {attrs}>"
            f'<div class="vault-callout-header">{icon}{title}</div>'
            f"{body}"
            "</section>"
        )


def is_obsidian_callout_start(line: str) -> bool:
    """Return true when a Markdown line begins an Obsidian callout block."""

    return bool(CALLOUT_HEADER_RE.match(line))


def _fold_state(marker: str | None) -> str:
    if marker == "-":
        return "collapsed"
    if marker == "+":
        return "expanded"
    return "none"


def _default_title(callout_type: str) -> str:
    return callout_type.replace("-", " ").replace("_", " ").title()


def _class_token(value: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", value.lower()).strip("-") or "note"


def _icon_label(visual_type: str) -> str:
    return {
        "abstract": "A",
        "bug": "B",
        "danger": "!",
        "example": "E",
        "failure": "X",
        "info": "i",
        "note": "N",
        "question": "?",
        "quote": '"',
        "success": "+",
        "tip": "*",
        "todo": "T",
        "warning": "!",
    }.get(visual_type, "N")


def _e(value: str) -> str:
    return html.escape(value, quote=True)
