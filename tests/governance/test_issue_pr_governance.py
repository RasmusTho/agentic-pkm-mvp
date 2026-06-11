from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

_BUILDEROPS_ROUTING_REGEX = re.compile(
    r"(?:^|\n)## BuilderOps Routing[\s\S]*?(?=\n##\s|\n---)|(?:^|\n)## BuilderOps Routing[\s\S]*",
    re.IGNORECASE,
)
_BUILDEROPS_ROUTING_FIELDS = (
    re.compile(
        r"(?:^|\n)\s*-\s*Records/projections/receipts:\s*(.*?)\s*(?:\n|$)",
        re.IGNORECASE,
    ),
    re.compile(r"(?:^|\n)\s*-\s*Reason:\s*(.*?)\s*(?:\n|$)", re.IGNORECASE),
)
_TIER1_LANE_REGEX = re.compile(
    r"^\-\s+\[x\]\s+(?:Docs authoring|Governance) lane\b",
    re.IGNORECASE | re.MULTILINE,
)
_ISSUE_LINK_REGEX = re.compile(r"(Fixes|Closes|Resolves)\s+#\d+", re.IGNORECASE)


def _read_workflow() -> str:
    return (REPO_ROOT / ".github/workflows/issue-pr-governance.yml").read_text(
        encoding="utf-8"
    )


def _has_builderops_routing(body: str) -> bool:
    match = _BUILDEROPS_ROUTING_REGEX.search(body)
    if not match:
        return False
    section = match.group(0)
    for pattern in _BUILDEROPS_ROUTING_FIELDS:
        field = pattern.search(section)
        if not field:
            return False
        value = field.group(1).strip()
        if not value or re.fullmatch(r"<.*>", value):
            return False
    return True


def _builderops_routing_satisfied(body: str) -> bool:
    if _has_builderops_routing(body):
        return True
    return (
        _TIER1_LANE_REGEX.search(body) is not None
        and _ISSUE_LINK_REGEX.search(body) is None
        and _BUILDEROPS_ROUTING_REGEX.search(body) is None
    )


def test_issue_backed_code_pr_requires_builderops_routing_even_with_tier1_checkbox() -> None:
    body = (
        "Fixes #123\n\n"
        "- [x] Governance lane\n\n"
        "## Summary\n"
        "Implementation change."
    )

    assert not _builderops_routing_satisfied(body)


def test_mixed_tier_pr_uses_highest_required_tier() -> None:
    mixed_without_routing = (
        "Closes #456\n\n"
        "- [x] Docs authoring lane\n\n"
        "## Summary\n"
        "Changes code and docs."
    )
    tier1_without_issue = "- [x] Docs authoring lane\n\n## Summary\nDocs-only wording."
    mixed_with_routing = (
        "Closes #456\n\n"
        "- [x] Docs authoring lane\n\n"
        "## BuilderOps Routing\n"
        "- Records/projections/receipts: none\n"
        "- Reason: no operational BuilderOps material produced\n"
    )

    assert not _builderops_routing_satisfied(mixed_without_routing)
    assert _builderops_routing_satisfied(tier1_without_issue)
    assert _builderops_routing_satisfied(mixed_with_routing)


def test_workflow_checks_issue_link_before_allowing_tier1_builderops_omission() -> None:
    text = _read_workflow()

    assert "const hasIssueLink = issueLinkPattern.test(body);" in text
    assert "isTier1Lane && !hasIssueLink && !builderOpsRoutingSection" in text
    assert text.index("const hasIssueLink = issueLinkPattern.test(body);") < text.index(
        "const builderOpsRoutingSatisfied ="
    )
