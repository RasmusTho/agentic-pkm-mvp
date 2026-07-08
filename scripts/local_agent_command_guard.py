#!/usr/bin/env python3
"""Classify local agent shell commands as allowed or blocked for hook use."""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class GuardResult:
    allowed: bool
    reason: str


_DENY_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\brm\s+-(?:[^\n]*[rf]|[^\n]*[fr])\b"), "destructive rm command"),
    (re.compile(r"\bgit\s+push\b"), "git push is not allowed from local hooks"),
    (re.compile(r"\bgh\s+pr\s+merge\b"), "PR merge is not allowed from local hooks"),
    (re.compile(r"\bgh\s+issue\s+(?:close|edit|comment)\b"), "issue mutation is not allowed from local hooks"),
    (re.compile(r"\bgh\s+pr\s+(?:comment|edit|review)\b"), "PR mutation is not allowed from local hooks"),
    (re.compile(r"\bgh\s+api\s+graphql\b"), "Project/GitHub GraphQL mutation risk is not allowed from local hooks"),
    (re.compile(r"\bstable\b.*\b(?:promote|promotion|push|reset)\b"), "stable promotion commands require explicit workflow authority"),
    (re.compile(r"\bprod(?:uction)?\b.*\b(?:migrate|restart|deploy|dump|restore)\b"), "production commands require explicit workflow authority"),
    (re.compile(r"\b(?:vault|secret|token)\b.*\b(?:write|delete|rotate|export)\b"), "vault/secret mutation is not allowed from local hooks"),
    (re.compile(r"\balembic\s+(?:upgrade|downgrade|revision)\b"), "database migration commands require explicit workflow authority"),
)


_ALLOW_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^\s*(?:python3?|pytest|ruff|mypy|git\s+(?:status|diff|show|log)|rg|sed|cat|ls|find|scripts/agent_workspace_preflight\.sh)\b"),
)


def classify_command(command: str) -> GuardResult:
    normalized = " ".join(command.strip().split())
    if not normalized:
        return GuardResult(allowed=False, reason="empty command")
    for pattern, reason in _DENY_PATTERNS:
        if pattern.search(normalized):
            return GuardResult(allowed=False, reason=reason)
    if any(pattern.search(normalized) for pattern in _ALLOW_PATTERNS):
        return GuardResult(allowed=True, reason="allowed local validation or inspection command")
    return GuardResult(allowed=True, reason="allowed by default; no denied authority pattern matched")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--command", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    result = classify_command(args.command)
    print(result.reason)
    return 0 if result.allowed else 1


if __name__ == "__main__":
    raise SystemExit(main())
