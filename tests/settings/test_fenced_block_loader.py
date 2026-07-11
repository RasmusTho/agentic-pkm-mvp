"""Shared fenced-block loader regressions (`app.settings.loader`).

The fence helper is shared by the settings substrate (tag ``settings``) and
the Episode stream registry (tag ``stream-registry``, PR #3498 round-2
FIX B): the closing fence is line-anchored so embedded triple-backticks
cannot silently truncate the block, and both fence lines tolerate CRLF --
in multiline mode `$` anchors before the `\n`, so without an explicit
`\r?` a well-formed CRLF document silently fails to match (parse_section
would return `{}` instead of the declared settings).

CRLF strings are fed to the helpers directly: file-based fixtures would not
exercise the regex because text-mode reads apply universal-newline
translation before the pattern ever sees the `\r`.
"""

from __future__ import annotations

from app.settings.loader import find_fenced_block, find_fenced_settings
from app.settings.parsers import parse_section

_SETTINGS_BLOCK = (
    "## general\n"
    "\n"
    "```yaml settings\n"
    "options:\n"
    "  alpha: true\n"
    "retention_window_days: 30\n"
    "```\n"
)


def test_find_fenced_settings_tolerates_crlf() -> None:
    lf_body = find_fenced_settings(_SETTINGS_BLOCK)
    assert lf_body is not None

    crlf = _SETTINGS_BLOCK.replace("\n", "\r\n")
    crlf_body = find_fenced_settings(crlf)
    assert crlf_body is not None, "CRLF settings block must match the fence pattern"

    # and the full settings parse path yields the same mapping either way
    assert parse_section(crlf) == parse_section(_SETTINGS_BLOCK) != {}


def test_find_fenced_block_tolerates_crlf_for_any_tag() -> None:
    doc = (
        "```yaml stream-registry\n"
        "streams:\n"
        "  - stream_id: some.stream\n"
        "```\n"
    ).replace("\n", "\r\n")
    body = find_fenced_block(doc, "stream-registry")
    assert body is not None
    assert "some.stream" in body


def test_closing_fence_is_line_anchored() -> None:
    """An embedded triple-backtick inside a YAML value must not truncate the
    block -- only a ``` alone at the start of a line closes it."""
    doc = (
        "```yaml settings\n"
        "note: 'contains ``` inline backticks'\n"
        "key: value\n"
        "```\n"
    )
    body = find_fenced_settings(doc)
    assert body is not None
    assert "key: value" in body, "embedded ``` truncated the fenced block"
