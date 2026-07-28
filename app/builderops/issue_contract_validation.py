"""Pure validation for strict Issue-contract authority references.

These validators intentionally inspect only canonical string shape.  They do
not touch the repository filesystem, GitHub, BuilderOps, or any provider, so
captured contract evidence can be validated deterministically by every
consumer.
"""

from __future__ import annotations

import re
from typing import Final

VAGUE_AUTHORITY_TOKENS: Final[frozenset[str]] = frozenset(
    {
        "anchor",
        "heading",
        "later",
        "path",
        "section",
        "tbd",
        "todo",
        "unknown",
    }
)

_REPO_PATH = re.compile(
    r"^(?:\.[A-Za-z0-9_-]+|[A-Za-z0-9_-]+)"
    r"(?:/[A-Za-z0-9_.-]+)*\.[A-Za-z0-9_-]+$"
)
_REPO_ANCHOR = re.compile(
    r"^(?P<path>[^\s`]+) :: (?P<anchor>\S(?:.*\S)?)$"
)
_TEST_VERIFY_TARGET = re.compile(
    r"^(?P<path>(?:tests|companion-ui/companion-app/tests)/"
    r"[^\s`]+\.py)"
    r"(?P<selectors>(?:::[A-Za-z_][A-Za-z0-9_]*"
    r"(?:\[[^\]\s]+\])?)+)$"
)
_RUNTIME_RECEIPT_TARGET = re.compile(
    r"^runtime receipt: "
    r"(?P<identity>[a-z0-9_-]+(?:\.[a-z0-9_-]+)*)"
    r"\.v(?P<version>[1-9][0-9]*)$"
)
_PLACEHOLDER = re.compile(r"<[^>]+>")
_AUTHORITY_TOKEN = re.compile(r"[A-Za-z0-9]+")


def _contains_vague_authority_token(value: str) -> bool:
    return any(
        token.casefold() in VAGUE_AUTHORITY_TOKENS
        for token in _AUTHORITY_TOKEN.findall(value)
    )


def _strip_backtick_pair(value: str) -> str:
    if len(value) >= 2 and value.startswith("`") and value.endswith("`"):
        return value[1:-1]
    return value


def is_durable_repo_path(value: str) -> bool:
    """Return whether *value* is one canonical, durable repository file path."""

    if (
        not value
        or value != value.strip()
        or "\\" in value
        or _PLACEHOLDER.search(value) is not None
        or _REPO_PATH.fullmatch(value) is None
    ):
        return False
    parts = value.split("/")
    return (
        all(part not in {"", ".", ".."} for part in parts)
        and not _contains_vague_authority_token(value)
    )


def is_durable_anchor(value: str) -> bool:
    """Return whether *value* is a canonical, non-placeholder anchor."""

    return (
        bool(value)
        and value == " ".join(value.split())
        and _PLACEHOLDER.search(value) is None
        and "`" not in value
        and not _contains_vague_authority_token(value)
    )


def is_durable_repo_anchor(value: str) -> bool:
    """Return whether *value* is ``<repo path> :: <durable anchor>``."""

    match = _REPO_ANCHOR.fullmatch(value)
    return (
        match is not None
        and is_durable_repo_path(match.group("path"))
        and is_durable_anchor(match.group("anchor"))
    )


def is_resolvable_verify_target(value: str) -> bool:
    """Return whether one strict-contract ``Verify:`` target is resolvable."""

    target = value.strip()
    if not target or _PLACEHOLDER.search(target) is not None:
        return False
    unquoted_target = _strip_backtick_pair(target)
    if unquoted_target != target and "`" in unquoted_target:
        return False
    target = unquoted_target

    test_target = _TEST_VERIFY_TARGET.fullmatch(target)
    if test_target is not None:
        return is_durable_repo_path(test_target.group("path"))

    repo_path, separator, selector = target.partition("::")
    if separator and selector and is_durable_repo_path(repo_path):
        return True

    doc_prefix = "doc writeback at "
    if target.startswith(doc_prefix):
        repo_anchor = _strip_backtick_pair(target.removeprefix(doc_prefix))
        return (
            repo_anchor.startswith(("docs/", ".codex/"))
            and is_durable_repo_anchor(repo_anchor)
        )

    roadmap_prefix = "roadmap diff: "
    if target.startswith(roadmap_prefix):
        repo_anchor = _strip_backtick_pair(
            target.removeprefix(roadmap_prefix)
        )
        return (
            repo_anchor.startswith("docs/")
            and is_durable_repo_anchor(repo_anchor)
        )

    runtime_receipt = _RUNTIME_RECEIPT_TARGET.fullmatch(target)
    return (
        runtime_receipt is not None
        and not _contains_vague_authority_token(
            runtime_receipt.group("identity")
        )
    )
