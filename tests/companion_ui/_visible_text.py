"""Shared visible-text extractor for Companion UI render tests.

Companion UI render tests assert on the *human-visible* text of rendered HTML
(e.g. "this label must not leak into the rendered copy"). Doing that with a
regex ``<script>``/tag stripper is unsafe: a regex cannot robustly match
``</script >``, ``<SCRIPT>``, or ``</script\\t\\n bar>``, so inert markup can
leak into the scanned copy and defeat the very "assert on visible text"
guarantee. That fragility is exactly what CodeQL ``py/bad-tag-filter``
(high severity) flags.

This helper uses ``html.parser.HTMLParser`` (NOT regex), mirroring the
skip-subtree / void-tag logic already proven in ``_orphan_text.py``:

- whole subtrees for ``head``/``script``/``style``/``template`` are skipped,
  so their contents never count as visible text;
- void tags (``<br>``, ``<img>``, ...) never open a subtree;
- ``convert_charrefs=True`` so entities resolve to their text.

Casing convention
-----------------
``visible_text`` returns whitespace-collapsed, **lower-cased** text. This is
the convention the Round-2 remediation tests (PRs #2490-#2493) adopted: their
call sites compare against lower-cased expectations, and case-insensitive
comparison is what the re-entry card/panel de-dup checks rely on. Keeping the
lowering inside the shared helper preserves every existing assertion. Callers
that genuinely need original casing should extract text themselves rather than
re-upper-casing this result.
"""
from __future__ import annotations

from html.parser import HTMLParser

# Tags whose entire subtree is non-visible and must be skipped.
_VISIBLE_SKIP_TAGS = frozenset({"head", "script", "style", "template"})

# Void tags never open a subtree, so they must not affect skip depth.
_VISIBLE_VOID_TAGS = frozenset(
    {
        "area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr",
    }
)


class _VisibleTextExtractor(HTMLParser):
    """Collect on-screen text via a real HTML parser (no regex tag-filter), so
    whitespace-padded or upper-case close tags (``</script >``, ``<SCRIPT>``)
    cannot leak inert markup into the scanned copy."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: object) -> None:
        if tag in _VISIBLE_VOID_TAGS:
            return
        if self._skip_depth or tag in _VISIBLE_SKIP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in _VISIBLE_VOID_TAGS:
            return
        if self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self._chunks.append(data)


def visible_text(html: str) -> str:
    """Rendered human-visible text: tags removed and ``script``/``style``/
    ``head``/``template`` bodies dropped. Whitespace-collapsed and lower-cased
    for substring scans (see module docstring for the casing rationale)."""
    extractor = _VisibleTextExtractor()
    extractor.feed(html)
    extractor.close()
    return " ".join("".join(extractor._chunks).split()).lower()
