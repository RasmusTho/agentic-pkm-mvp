"""Shared governing-Issue identity for verification dispatch."""

from __future__ import annotations

import re


_GOVERNING_KEYWORD = r"[Gg][Oo][Vv][Ee][Rr][Nn][Ii][Nn][Gg]-[Ii][Ss][Ss][Uu][Ee]"
_CLOSING_KEYWORD = (
    r"(?:[Ff][Ii][Xx][Ee][Ss]|[Cc][Ll][Oo][Ss][Ee][Ss]|"
    r"[Rr][Ee][Ss][Oo][Ll][Vv][Ee][Ss])"
)
_SUPPORTING_KEYWORD = rf"(?:{_CLOSING_KEYWORD}|[Rr][Ee][Ff][Ss])"
_ISSUE_TOKEN_PREFIX = r"(?:^|[^0-9A-Za-z_])"
_ISSUE_TOKEN_TERMINATOR = r"(?=$|[ \t\r\n.,;:)\]}])"

GOVERNING_ISSUE_LINE_PATTERN = re.compile(
    rf"(?m)^[ \t]*{_GOVERNING_KEYWORD}[ \t]*:.*$"
)
GOVERNING_ISSUE_PATTERN = re.compile(
    rf"(?m)^[ \t]*{_GOVERNING_KEYWORD}:[ \t]*#([1-9][0-9]*)[ \t]*$"
)
CLOSING_ISSUE_MENTION_PATTERN = re.compile(
    rf"{_ISSUE_TOKEN_PREFIX}{_CLOSING_KEYWORD}[ \t]+#\S+", re.M
)
CLOSING_ISSUE_PATTERN = re.compile(
    rf"{_ISSUE_TOKEN_PREFIX}{_CLOSING_KEYWORD}[ \t]+#([1-9][0-9]*)"
    rf"{_ISSUE_TOKEN_TERMINATOR}",
    re.M,
)
SUPPORTING_ISSUE_PATTERN = re.compile(
    rf"{_ISSUE_TOKEN_PREFIX}{_SUPPORTING_KEYWORD}[ \t]+#([1-9][0-9]*)"
    rf"{_ISSUE_TOKEN_TERMINATOR}",
    re.M,
)


def resolve_issue_contract(pr_body: object) -> tuple[int, tuple[int, ...]] | None:
    if not isinstance(pr_body, str):
        return None
    governing_lines = GOVERNING_ISSUE_LINE_PATTERN.findall(pr_body)
    matches = GOVERNING_ISSUE_PATTERN.findall(pr_body)
    if len(governing_lines) != 1 or len(matches) != 1:
        return None
    closing_mentions = CLOSING_ISSUE_MENTION_PATTERN.findall(pr_body)
    closing_matches = CLOSING_ISSUE_PATTERN.findall(pr_body)
    if not closing_matches or len(closing_mentions) != len(closing_matches):
        return None
    governing = int(matches[0])
    supporting = tuple(
        sorted(
            {
                int(match)
                for match in SUPPORTING_ISSUE_PATTERN.findall(pr_body)
                if int(match) != governing
            }
        )
    )
    return governing, supporting
