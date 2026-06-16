"""Shared text helpers — foundation/leaf util; stdlib only.

These helpers are used across interaction (api/routes, chat) and cognition
(orientation, panel) layers.  They live here so that cognition consumers can
import them without creating a backward dependency on the interaction layer.

ADR-0013: import direction must flow downward (cognition → foundation).
"""

from __future__ import annotations

import hashlib
import re


# ---------------------------------------------------------------------------
# Hash
# ---------------------------------------------------------------------------

def content_hash(text: str) -> str:
    """Return a 16-char SHA-1 hex digest of ``text`` (UTF-8 encoded)."""
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Title extraction
# ---------------------------------------------------------------------------

def _plain_title(text: str) -> str:
    """Strip Markdown formatting from a heading text string."""
    text = text.strip(" #\t")
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"(\*\*|__)(.+?)\1", r"\2", text)
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"\1", text)
    text = re.sub(r"(?<!_)_(?!_)(.+?)(?<!_)_(?!_)", r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


def extract_title(body: str, fallback: str) -> str:
    """Return the first H1 heading from ``body``, or ``fallback`` if none found."""
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return _plain_title(stripped[2:])
    return fallback


# ---------------------------------------------------------------------------
# Frontmatter
# ---------------------------------------------------------------------------

def body_contains_frontmatter(body: str) -> bool:
    """Return True if ``body`` starts with a YAML frontmatter block (``---``)."""
    stripped = body.lstrip()
    if not stripped.startswith("---"):
        return False
    # Must have a closing --- line to count as frontmatter
    rest = stripped[3:]
    return bool(re.search(r"\n---", rest))


def split_frontmatter(content: str) -> tuple[str | None, str]:
    """Split a note's content into (frontmatter_inner, body).

    Returns ``(None, content)`` if there is no frontmatter block.
    ``frontmatter_inner`` is the text between the opening and closing ``---``
    delimiters (not including the delimiters or trailing newline).
    """
    if not content.startswith("---"):
        return None, content

    # Find the closing --- after the opening (handle both with body and EOF cases)
    rest = content[3:]
    # Try matching with newline after --- (has body)
    close = re.search(r"\n---(?:\s*\n|\s*$)", rest)
    if close is None:
        return None, content

    frontmatter_inner = rest[: close.start()]  # exclude trailing newline
    body = rest[close.end() :]
    return frontmatter_inner, body


__all__ = [
    "body_contains_frontmatter",
    "content_hash",
    "extract_title",
    "split_frontmatter",
]
