"""Shared governing-Issue identity for verification dispatch."""

from __future__ import annotations

import re
from dataclasses import dataclass


_GOVERNING_KEYWORD = r"[Gg][Oo][Vv][Ee][Rr][Nn][Ii][Nn][Gg]-[Ii][Ss][Ss][Uu][Ee]"
_CLOSING_KEYWORD = (
    r"(?:[Ff][Ii][Xx](?:[Ee][Ss]|[Ee][Dd])?|"
    r"[Cc][Ll][Oo][Ss][Ee](?:[Ss]|[Dd])?|"
    r"[Rr][Ee][Ss][Oo][Ll][Vv][Ee](?:[Ss]|[Dd])?)"
)
_SUPPORTING_KEYWORD = rf"(?:{_CLOSING_KEYWORD}|[Rr][Ee][Ff][Ss])"
_ISSUE_TOKEN_PREFIX = r"(?:^|[^0-9A-Za-z_])"
_ISSUE_TOKEN_TERMINATOR = r"(?=$|[ \t\r\n.,;:)\]}])"
_ASCII_CLOSING_SEPARATOR = r"(?:[ \t]+|[ \t]*:[ \t]*)"
_EXPLICIT_WHITESPACE = (
    r"[ \t\n\v\f\r\x85\u00a0\u1680\u2000-\u200a"
    r"\u2028\u2029\u202f\u205f\u3000\ufeff]"
)
_CLOSING_ATTEMPT_SEPARATOR = (
    rf"(?:{_EXPLICIT_WHITESPACE}+|{_EXPLICIT_WHITESPACE}*:"
    rf"{_EXPLICIT_WHITESPACE}*)"
)
_GITHUB_ISSUE_URL_ATTEMPT_TARGET = (
    r"[Hh][Tt][Tt][Pp][Ss]?://[Gg][Ii][Tt][Hh][Uu][Bb][.][Cc][Oo][Mm]/"
    r"[0-9A-Za-z_.-]+/[0-9A-Za-z_.-]+/[Ii][Ss][Ss][Uu][Ee][Ss]/"
)
_CLOSING_ATTEMPT_TARGET = (
    rf"(?:#|[0-9A-Za-z_.-]+/[0-9A-Za-z_.-]+#|"
    rf"{_GITHUB_ISSUE_URL_ATTEMPT_TARGET})"
)

# Keep every issue-snapshot producer and verification consumer inside one
# bounded multi-issue authority contract. The normal case remains one closing
# issue; ten leaves room for an explicitly approved batch without permitting
# PR-controlled API fan-out.
MAX_CLOSING_ISSUES = 10
NEUTRALIZED_CLOSING_ISSUES_PREFIX = "Verified-Closing-Issues:"
FINAL_REVIEW_ROUNDS_LINE_PATTERN = re.compile(
    r"(?m)^Final-Review-Rounds:[ \t]*.*$"
)
FINAL_REVIEW_ROUNDS_PATTERN = re.compile(
    r"(?m)^Final-Review-Rounds:[ \t]*([012])[ \t]*$"
)


def resolve_final_review_rounds(body: object) -> int | None:
    """Return one strict declaration; zero explicitly selects the light path."""
    if not isinstance(body, str):
        return None
    if re.search(r"\r(?!\n)|[\u2028\u2029]", body):
        return None
    canonical_body = body.replace("\r\n", "\n")
    lines = FINAL_REVIEW_ROUNDS_LINE_PATTERN.findall(canonical_body)
    matches = FINAL_REVIEW_ROUNDS_PATTERN.findall(canonical_body)
    if len(lines) != 1 or len(matches) != 1:
        return None
    return int(matches[0])


# --- pr-contract gate twins (issue #4272; line-terminator parity #4341) -----
#
# The two functions below are a distinct concern from resolve_final_review_rounds
# above: that function resolves how many verified-merge review rounds the
# full-path ceremony needs (1 or 2; 0 has no ceremony, so it resolves to None
# there on purpose). The `pr-contract` CI gate instead only checks the PR
# body's *shape* \u2014 exactly one Final-Review-Rounds declaration with a value of
# 0, 1, or 2 \u2014 regardless of which path that value selects. These twins mirror
# the workflow's own JS shape checks (the `// final-review-rounds:start`/`:end`
# and `// builderops-routing:start`/`:end` marker-delimited blocks in
# .github/workflows/issue-pr-governance.yml), proven equivalent on a corpus
# that now spans every ECMAScript `LineTerminator` (`\n`, `\r\n`, lone `\r`,
# U+2028, U+2029) by tests/governance/test_issue_pr_governance.py
# ::test_final_review_rounds_check_executes_via_canonical_implementation and
# ::test_builderops_routing_stub_detection_matches_workflow_js, following the
# same marker-extraction parity pattern as
# ::test_javascript_and_python_authority_grammar_are_identical. JS's `$`/`^`
# under the `/m` flag, and its `.` without `/s`, treat all four LineTerminator
# code points as line breaks; Python's `re.MULTILINE`/dot semantics only
# recognize `\n`. `_canonicalize_pr_contract_line_terminators` below folds all
# four into `\n` before either twin matches -- the same `\r\n` -> `\n` step
# `resolve_final_review_rounds` already applies -- so declared/valid line
# counts agree with the JS gate regardless of which terminator a PR body uses.

PR_CONTRACT_FINAL_REVIEW_ROUNDS_ALL_LINES_PATTERN = re.compile(
    r"^Final-Review-Rounds:[ \t]*.*$", re.MULTILINE
)
PR_CONTRACT_FINAL_REVIEW_ROUNDS_VALID_LINE_PATTERN = re.compile(
    r"^Final-Review-Rounds:[ \t]*[012][ \t]*$", re.MULTILINE
)
# Pattern text kept byte-identical to the workflow's `tier1LanePattern` JS
# literal on purpose (`scripts/lint_skills_consistency.py` Check 10, issue
# #4342, asserts textual/flag parity between this constant and the JS regex
# literal). The `\s` divergence this issue fixes -- Python's Unicode-mode
# `\s` matches the C0 "information separator" controls \x1c-\x1f that JS's
# `\s` does not (`chr(0x1c).isspace()` is `True` in Python, `/\s/.test("\x1c")`
# is `false` in JS) -- is therefore repaired by canonicalizing those controls
# out of the input in `_canonicalize_pr_contract_line_terminators` below, not
# by rewriting this pattern's source text.
TIER1_LANE_PATTERN = re.compile(
    r"^\-\s+\[x\]\s+(?:Docs authoring|Governance) lane\b", re.IGNORECASE | re.MULTILINE
)
BUILDEROPS_ROUTING_SECTION_PATTERN = re.compile(
    r"(?:^|\n)## BuilderOps Routing[\s\S]*?(?=\n##\s|\n---)|(?:^|\n)## BuilderOps Routing[\s\S]*",
    re.IGNORECASE,
)
BUILDEROPS_ROUTING_RECORDS_PATTERN = re.compile(
    r"(?:^|\n)\s*-\s*Records/projections/receipts:\s*(.*?)\s*(?:\n|$)",
    re.IGNORECASE,
)
BUILDEROPS_ROUTING_REASON_PATTERN = re.compile(
    r"(?:^|\n)\s*-\s*Reason:\s*(.*?)\s*(?:\n|$)", re.IGNORECASE
)
BUILDEROPS_ROUTING_PLACEHOLDER_PATTERN = re.compile(r"^<.*>$")


# Python's Unicode-mode `\s` treats these four C0 "information separator"
# controls and U+0085 as whitespace; JS's `\s` does not. ECMAScript instead
# treats U+FEFF as whitespace while Python does not. BuilderOps patterns are
# intentionally source-aligned with the hosted JS, so their dedicated
# canonicalizer maps the Python-only set to NUL and U+FEFF to NBSP. NBSP is
# whitespace in both engines but cannot synthesize ASCII-space literal syntax.
# The Final-Review-Rounds twin uses explicit `[ \t]`, so it only needs the
# pre-existing line/C0 canonicalization and must not receive the U+FEFF map.
_C0_INFORMATION_SEPARATORS = "\x1c\x1d\x1e\x1f"
_PYTHON_ONLY_WHITESPACE = _C0_INFORMATION_SEPARATORS + "\x85"


def _canonicalize_pr_contract_line_terminators(text: str) -> str:
    """Normalize line-terminator and whitespace-class divergences from the JS gate.

    JS `$`/`^` under `/m`, and JS `.` without `/s`, treat `\\r\\n`, lone `\\r`,
    U+2028, and U+2029 as line breaks; Python's `re.MULTILINE`/dot semantics
    only recognize `\\n`. Canonicalizing first (the same `\\r\\n` -> `\\n` step
    `resolve_final_review_rounds` already applies) keeps the pr-contract gate
    twins aligned with the workflow's own JS across all four terminators
    (#4341), instead of `resolve_final_review_rounds`'s stricter fail-closed
    rejection of non-LF/CRLF bodies, which is specific to that function's own
    ceremony-round semantics and not shared by these shape-only twins. Also
    neutralizes `_C0_INFORMATION_SEPARATORS` (see above) for the same reason.
    """
    text = (
        text.replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\u2028", "\n")
        .replace("\u2029", "\n")
    )
    for separator in _C0_INFORMATION_SEPARATORS:
        text = text.replace(separator, "\x00")
    return text


def _canonicalize_ecmascript_whitespace_for_python(text: str) -> str:
    r"""Make Python ``\s``/``strip`` agree with ECMAScript for BuilderOps parsing.

    NUL cannot occur in a GitHub PR body and is whitespace in neither engine.
    NBSP is whitespace and trimmed by both engines, while remaining distinct
    from literal ASCII spaces in lane names and section headings.
    """
    text = _canonicalize_pr_contract_line_terminators(text)
    for whitespace in _PYTHON_ONLY_WHITESPACE:
        text = text.replace(whitespace, "\x00")
    return text.replace("\ufeff", "\xa0")


@dataclass(frozen=True)
class PrContractFinalReviewRounds:
    declared_count: int
    valid_count: int
    satisfied: bool


def resolve_pr_contract_final_review_rounds(body: object) -> PrContractFinalReviewRounds:
    """Shape-check twin of the `pr-contract` gate's Final-Review-Rounds assertion.

    Unlike :func:`resolve_final_review_rounds`, this accepts a value of ``0``
    (the light-delivery-path declaration) and only asserts shape, never
    ceremony-round semantics.
    """
    text = _canonicalize_pr_contract_line_terminators(body if isinstance(body, str) else "")
    declared = PR_CONTRACT_FINAL_REVIEW_ROUNDS_ALL_LINES_PATTERN.findall(text)
    valid = PR_CONTRACT_FINAL_REVIEW_ROUNDS_VALID_LINE_PATTERN.findall(text)
    return PrContractFinalReviewRounds(
        declared_count=len(declared),
        valid_count=len(valid),
        satisfied=len(declared) == 1 and len(valid) == 1,
    )


@dataclass(frozen=True)
class BuilderOpsRoutingStatus:
    is_tier1_lane: bool
    has_section: bool
    has_builderops_routing: bool
    satisfied: bool


def resolve_builderops_routing_status(
    body: object, *, has_issue_authority: bool
) -> BuilderOpsRoutingStatus:
    """Twin of the `pr-contract` gate's `## BuilderOps Routing` filled-vs-stub check."""
    text = _canonicalize_ecmascript_whitespace_for_python(
        body if isinstance(body, str) else ""
    )
    is_tier1_lane = TIER1_LANE_PATTERN.search(text) is not None
    section_match = BUILDEROPS_ROUTING_SECTION_PATTERN.search(text)
    section = section_match.group(0) if section_match else ""

    def _has_concrete_value(pattern: re.Pattern[str]) -> bool:
        match = pattern.search(section)
        if not match:
            return False
        value = match.group(1).strip()
        return len(value) > 0 and BUILDEROPS_ROUTING_PLACEHOLDER_PATTERN.match(value) is None

    has_builderops_routing = bool(section) and _has_concrete_value(
        BUILDEROPS_ROUTING_RECORDS_PATTERN
    ) and _has_concrete_value(BUILDEROPS_ROUTING_REASON_PATTERN)
    satisfied = has_builderops_routing or (
        is_tier1_lane and not has_issue_authority and not section
    )
    return BuilderOpsRoutingStatus(
        is_tier1_lane=is_tier1_lane,
        has_section=bool(section),
        has_builderops_routing=has_builderops_routing,
        satisfied=satisfied,
    )


GOVERNING_ISSUE_LINE_PATTERN = re.compile(
    rf"(?m)^[ \t]*{_GOVERNING_KEYWORD}[ \t]*:.*$"
)
GOVERNING_ISSUE_PATTERN = re.compile(
    rf"(?m)^[ \t]*{_GOVERNING_KEYWORD}:[ \t]*#([1-9][0-9]*)[ \t]*$"
)
CLOSING_ISSUE_ATTEMPT_PATTERN = re.compile(
    rf"{_ISSUE_TOKEN_PREFIX}{_CLOSING_KEYWORD}{_CLOSING_ATTEMPT_SEPARATOR}"
    rf"{_CLOSING_ATTEMPT_TARGET}",
    re.M,
)
CLOSING_ISSUE_PATTERN = re.compile(
    rf"(?m)^[ \t]*{_CLOSING_KEYWORD}{_ASCII_CLOSING_SEPARATOR}"
    rf"#([1-9][0-9]*)[ \t]*$",
    re.M,
)
SUPPORTING_ISSUE_PATTERN = re.compile(
    rf"{_ISSUE_TOKEN_PREFIX}(?:{_CLOSING_KEYWORD}{_ASCII_CLOSING_SEPARATOR}|"
    rf"[Rr][Ee][Ff][Ss][ \t]+)#([1-9][0-9]*)"
    rf"{_ISSUE_TOKEN_TERMINATOR}",
    re.M,
)
_NEUTRALIZABLE_CLOSING_ISSUE_PATTERN = re.compile(
    rf"(?P<prefix>{_ISSUE_TOKEN_PREFIX})"
    rf"{_CLOSING_KEYWORD}{_ASCII_CLOSING_SEPARATOR}"
    rf"#(?P<issue>[1-9][0-9]*)"
    rf"{_ISSUE_TOKEN_TERMINATOR}",
    re.M,
)
_NEUTRALIZED_CLOSING_LINE_PATTERN = re.compile(
    r"(?m)^[ \t]*Verified-Closing-Issues[ \t]*:.*$"
)
_NEUTRALIZED_CLOSING_PATTERN = re.compile(
    r"(?m)^[ \t]*Verified-Closing-Issues:[ \t]*"
    r"(#[1-9][0-9]*(?:,[ \t]*#[1-9][0-9]*)*)[ \t]*$"
)


@dataclass(frozen=True)
class IssueAuthority:
    governing_issue: int
    closing_issues: tuple[int, ...]
    supporting_issues: tuple[int, ...]


def resolve_issue_authority(pr_body: object) -> IssueAuthority | None:
    """Resolve governing, closing, and evidence-only issue identities."""
    if not isinstance(pr_body, str):
        return None
    # GitHub bodies can arrive with CRLF at API boundaries. Canonicalize that
    # transport representation, but reject lone CR and JavaScript-only Unicode
    # line separators so the workflow and consumer cannot disagree on lines.
    if re.search(r"\r(?!\n)|[\u2028\u2029]", pr_body):
        return None
    canonical_body = pr_body.replace("\r\n", "\n")
    governing_lines = GOVERNING_ISSUE_LINE_PATTERN.findall(canonical_body)
    matches = GOVERNING_ISSUE_PATTERN.findall(canonical_body)
    if len(governing_lines) != 1 or len(matches) != 1:
        return None
    closing_mentions = CLOSING_ISSUE_ATTEMPT_PATTERN.findall(canonical_body)
    closing_matches = CLOSING_ISSUE_PATTERN.findall(canonical_body)
    if not closing_matches or len(closing_mentions) != len(closing_matches):
        return None
    governing = int(matches[0])
    closing = tuple(sorted({int(match) for match in closing_matches}))
    if len(closing) > MAX_CLOSING_ISSUES:
        return None
    supporting = tuple(
        sorted(
            {
                int(match)
                for match in SUPPORTING_ISSUE_PATTERN.findall(canonical_body)
                if int(match) != governing
            }
        )
    )
    return IssueAuthority(governing, closing, supporting)


def closing_issue_authority_exceeds_limit(pr_body: object) -> bool:
    """Return whether exact unique closing references exceed the shared limit."""
    if not isinstance(pr_body, str):
        return False
    canonical_body = pr_body.replace("\r\n", "\n")
    closing = {
        int(match) for match in CLOSING_ISSUE_PATTERN.findall(canonical_body)
    }
    return len(closing) > MAX_CLOSING_ISSUES


def has_closing_issue_attempt(value: object) -> bool:
    """Return whether a title/body contains any recognized closing attempt."""
    return isinstance(value, str) and CLOSING_ISSUE_ATTEMPT_PATTERN.search(value) is not None


def neutralize_closing_issue_references(
    pr_body: object,
    expected: IssueAuthority,
) -> str:
    """Replace authenticated closing references with evidence-only ``Refs``.

    The caller must already hold the immutable verification authority. This
    helper refuses malformed or changed bodies, uses the same ASCII-exact
    grammar as dispatch, and proves that every closing attempt was removed
    without dropping the governing identity or cumulative supporting refs.
    """
    authority = resolve_issue_authority(pr_body)
    if authority != expected or not isinstance(pr_body, str):
        raise ValueError("PR body does not match authenticated issue authority")

    def _replace(match: re.Match[str]) -> str:
        return f"{match.group('prefix')}Refs #{match.group('issue')}"

    if _NEUTRALIZED_CLOSING_LINE_PATTERN.search(pr_body):
        raise ValueError("PR body already contains neutralized closing authority")
    neutralized, replacements = _NEUTRALIZABLE_CLOSING_ISSUE_PATTERN.subn(
        _replace,
        pr_body,
    )
    if replacements == 0 or has_closing_issue_attempt(neutralized):
        raise ValueError("PR closing authority was not fully neutralized")

    canonical = neutralized.replace("\r\n", "\n")
    governing_lines = GOVERNING_ISSUE_LINE_PATTERN.findall(canonical)
    governing_matches = GOVERNING_ISSUE_PATTERN.findall(canonical)
    referenced = {
        int(match) for match in SUPPORTING_ISSUE_PATTERN.findall(canonical)
    }
    referenced_without_governor = referenced - {expected.governing_issue}
    if (
        len(governing_lines) != 1
        or governing_matches != [str(expected.governing_issue)]
        or not set(expected.closing_issues).issubset(referenced)
        or referenced_without_governor != set(expected.supporting_issues)
    ):
        raise ValueError("neutralized PR body changed issue evidence authority")
    marker = NEUTRALIZED_CLOSING_ISSUES_PREFIX + " " + ", ".join(
        f"#{issue}" for issue in expected.closing_issues
    )
    separator = "" if neutralized.endswith("\n") else "\n"
    result = f"{neutralized}{separator}{marker}\n"
    if resolve_neutralized_issue_authority(result) != expected:
        raise ValueError("neutralized PR body changed issue authority")
    return result


def has_neutralized_closing_marker(pr_body: object) -> bool:
    """Return whether a body still advertises a neutralized closing marker.

    This is the deliberately loose companion to
    :func:`resolve_neutralized_issue_authority`, and the same predicate
    :func:`neutralize_closing_issue_references` uses to refuse re-neutralizing an
    already-neutralized body. The strict resolver returns ``None`` both for a
    canonical body and for a body whose marker survives but whose grammar no
    longer parses; only this predicate separates those, so a stranded
    neutralization is never mistaken for a clean body.
    """

    return (
        isinstance(pr_body, str)
        and _NEUTRALIZED_CLOSING_LINE_PATTERN.search(pr_body) is not None
    )


def resolve_neutralized_issue_authority(pr_body: object) -> IssueAuthority | None:
    """Resolve the bounded non-closing authority used only during exact-head merge."""
    if not isinstance(pr_body, str) or re.search(r"\r(?!\n)|[\u2028\u2029]", pr_body):
        return None
    canonical_body = pr_body.replace("\r\n", "\n")
    governing_lines = GOVERNING_ISSUE_LINE_PATTERN.findall(canonical_body)
    governing_matches = GOVERNING_ISSUE_PATTERN.findall(canonical_body)
    marker_lines = _NEUTRALIZED_CLOSING_LINE_PATTERN.findall(canonical_body)
    marker_matches = _NEUTRALIZED_CLOSING_PATTERN.findall(canonical_body)
    if (
        len(governing_lines) != 1
        or len(governing_matches) != 1
        or len(marker_lines) != 1
        or len(marker_matches) != 1
        or CLOSING_ISSUE_ATTEMPT_PATTERN.search(canonical_body)
    ):
        return None
    try:
        closing = tuple(
            int(token[1:])
            for token in re.split(r",[ \t]*", marker_matches[0])
        )
    except ValueError:
        return None
    if (
        tuple(sorted(set(closing))) != closing
        or len(closing) > MAX_CLOSING_ISSUES
    ):
        return None
    governing = int(governing_matches[0])
    supporting = tuple(
        sorted(
            {
                int(match)
                for match in SUPPORTING_ISSUE_PATTERN.findall(canonical_body)
                if int(match) != governing
            }
        )
    )
    if not set(closing).issubset({governing, *supporting}):
        return None
    return IssueAuthority(governing, closing, supporting)


def resolve_issue_contract(pr_body: object) -> tuple[int, tuple[int, ...]] | None:
    """Compatibility projection for callers that need governor + evidence."""
    authority = resolve_issue_authority(pr_body)
    if authority is None:
        return None
    return authority.governing_issue, authority.supporting_issues
