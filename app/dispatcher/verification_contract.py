"""Shared governing-Issue identity for verification dispatch."""

from __future__ import annotations

import re


GOVERNING_ISSUE_PATTERN = re.compile(
    r"(?im)^\s*Governing-Issue:\s*#([1-9][0-9]*)\s*$"
)
SUPPORTING_ISSUE_PATTERN = re.compile(
    r"\b(?:Fixes|Closes|Resolves|Refs)\s+#([1-9][0-9]*)\b", re.I
)


def resolve_issue_contract(pr_body: object) -> tuple[int, tuple[int, ...]] | None:
    if not isinstance(pr_body, str):
        return None
    matches = GOVERNING_ISSUE_PATTERN.findall(pr_body)
    if len(matches) != 1:
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
