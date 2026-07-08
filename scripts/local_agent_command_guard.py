#!/usr/bin/env python3
"""Classify local agent shell commands as allowed or blocked for hook use."""

from __future__ import annotations

import argparse
import os
import re
import shlex
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class GuardResult:
    allowed: bool
    reason: str


_GH_GLOBAL_FLAGS_WITH_VALUE = {
    "--hostname",
    "-R",
    "--repo",
}


_DENY_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\brm\s+-(?:[^\n]*[rf]|[^\n]*[fr])\b"), "destructive rm command"),
    (re.compile(r"\bgit\s+push\b"), "git push is not allowed from local hooks"),
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
    gh_result = _classify_gh_command(normalized)
    if gh_result is not None:
        return gh_result
    for pattern, reason in _DENY_PATTERNS:
        if pattern.search(normalized):
            return GuardResult(allowed=False, reason=reason)
    if any(pattern.search(normalized) for pattern in _ALLOW_PATTERNS):
        return GuardResult(allowed=True, reason="allowed local validation or inspection command")
    return GuardResult(allowed=True, reason="allowed by default; no denied authority pattern matched")


def _classify_gh_command(command: str) -> GuardResult | None:
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()
    for index, token in enumerate(tokens):
        if _token_invokes_gh(token):
            return _classify_gh_tokens(tokens, index)
        if "gh " in token:
            nested_result = _classify_gh_command(token)
            if nested_result is not None:
                return nested_result
    return None


def _token_invokes_gh(token: str) -> bool:
    if os.path.basename(token) == "gh":
        return True
    return re.search(r"(?:^|[^A-Za-z0-9_.-])(?:[\w./-]+/)?gh$", token) is not None


def _classify_gh_tokens(tokens: Sequence[str], gh_index: int) -> GuardResult | None:
    index = gh_index + 1
    while index < len(tokens):
        token = tokens[index]
        if token in _GH_GLOBAL_FLAGS_WITH_VALUE:
            index += 2
            continue
        if any(token.startswith(flag + "=") for flag in _GH_GLOBAL_FLAGS_WITH_VALUE):
            index += 1
            continue
        if token.startswith("-"):
            index += 1
            continue
        break

    if index >= len(tokens):
        return None
    group = tokens[index]
    action = tokens[index + 1] if index + 1 < len(tokens) else ""
    if group == "api":
        return GuardResult(allowed=False, reason="GitHub API calls are not allowed from local hooks")
    if group == "project":
        return GuardResult(allowed=False, reason="Project mutation is not allowed from local hooks")
    if group == "label" and action in {"create", "delete", "edit", "clone"}:
        return GuardResult(allowed=False, reason="label mutation is not allowed from local hooks")
    if group == "issue" and action in {"close", "edit", "comment"}:
        return GuardResult(allowed=False, reason="issue mutation is not allowed from local hooks")
    if group == "pr" and action in {"close", "comment", "edit", "merge", "review"}:
        return GuardResult(allowed=False, reason="PR mutation is not allowed from local hooks")
    return None


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
