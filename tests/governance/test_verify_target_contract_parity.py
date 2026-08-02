"""Classifier <-> contract parity for ``Verify:`` target grammar (#4464).

`.codex/skills/_shared/ISSUE_CONTRACT.md :: Verify: marker rule` (skill-facing
summary) and `docs/development/DEV_WORKFLOW.md :: Acceptance verifiability`
(canonical long form) enumerate the accepted target forms. The strict grammar
in `app.builderops.issue_contract_validation.is_resolvable_verify_target` must
accept every enumerated form; a contract form the classifier rejects fails
this test, so the two surfaces cannot drift silently again (#4448 fallback).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.builderops.issue_contract_validation import is_resolvable_verify_target

REPO_ROOT = Path(__file__).resolve().parents[2]
ISSUE_CONTRACT = REPO_ROOT / ".codex/skills/_shared/ISSUE_CONTRACT.md"
DEV_WORKFLOW = REPO_ROOT / "docs/development/DEV_WORKFLOW.md"

# One concrete example per form the contract enumerates. The companion test
# below asserts each form's identifying phrase is present in the contract
# text, so removing or renaming a form in the docs breaks this table loudly.
CONTRACT_FORM_EXAMPLES: dict[str, str] = {
    "test pointer": (
        "`tests/scripts/test_validate_issue_readiness.py::"
        "test_fixture_classifications`"
    ),
    "doc writeback": (
        "doc writeback at "
        "`docs/development/DEV_WORKFLOW.md :: Acceptance verifiability`"
    ),
    "roadmap diff": "roadmap diff: `docs/ROADMAP.md :: DDO-03`",
    "runtime receipt": "runtime receipt: delivery_receipt.v1",
    "diff of file": (
        "diff of `.github/workflows/browser-runtime.yml` adding a step "
        "running `tests/companion_ui/test_cockpit_journeys.py`"
    ),
    "marker presence": (
        "`pytestmark = pytest.mark.browser_runtime` present in "
        "`tests/companion_ui/test_cockpit_journeys.py`, deselected by the "
        "PR marker expression"
    ),
    "repo anchor": "`docs/development/DEV_WORKFLOW.md :: Acceptance verifiability`",
    "annotated target": (
        "`docs/ROADMAP.md :: DOMAIN-INGEST` removed or rewritten as delivered."
    ),
}

FORM_PHRASE_IN_CONTRACT: dict[str, str] = {
    "test pointer": "test pointer",
    "doc writeback": "doc writeback at",
    "roadmap diff": "roadmap diff",
    "runtime receipt": "runtime receipt",
    "diff of file": "diff of",
    "marker presence": "present in",
    "repo anchor": " :: ",
    "annotated target": "trailing prose",
}


def _contract_text() -> str:
    return (
        ISSUE_CONTRACT.read_text(encoding="utf-8")
        + DEV_WORKFLOW.read_text(encoding="utf-8")
    )


def test_contract_verify_forms_all_classify_ready() -> None:
    rejected = {
        form: example
        for form, example in CONTRACT_FORM_EXAMPLES.items()
        if not is_resolvable_verify_target(example)
    }
    assert rejected == {}, (
        "contract-enumerated Verify forms rejected by the classifier "
        f"grammar: {rejected}"
    )


def test_contract_text_enumerates_each_classifier_form() -> None:
    text = _contract_text()
    missing = {
        form: phrase
        for form, phrase in FORM_PHRASE_IN_CONTRACT.items()
        if phrase not in text
    }
    assert missing == {}, (
        "classifier-accepted forms no longer named in the contract docs: "
        f"{missing}"
    )


def test_dev_workflow_canonical_example_targets_are_accepted() -> None:
    """Every marker line in the fenced example under 'Acceptance
    verifiability' must be accepted by the grammar."""
    text = DEV_WORKFLOW.read_text(encoding="utf-8")
    heading = text.find("## Acceptance verifiability")
    assert heading != -1
    # The fenced example embeds a `## Acceptance Criteria` heading, so slice
    # from the section heading and take the first fence that follows it.
    fence = re.search(r"```\n(.*?)```", text[heading:], re.DOTALL)
    assert fence is not None, "expected a fenced example block in the section"
    block = fence.group(1)
    assert "Acceptance Criteria" in block
    targets = [
        match.group(1).strip()
        for match in re.finditer(r"(?m)^\s*Verify:\s*(.+)$", block)
    ]
    assert targets, "expected Verify lines in the canonical example"
    rejected = [t for t in targets if not is_resolvable_verify_target(t)]
    assert rejected == [], (
        f"canonical DEV_WORKFLOW example targets rejected by grammar: {rejected}"
    )


JOINED_MULTI_TARGET_LINE = (
    "doc writeback at `docs/DB_SCHEMA.md :: DB Schema (Current Reality)` + "
    "doc writeback at"
)


def test_joined_multi_target_verify_line_is_rejected() -> None:
    """Several targets on one AC are one `Verify:` line each (#3857, #3859).

    Joining them on a single marker line leaves the line's backticks unpaired,
    so the grammar cannot resolve it; the contract must forbid the joined form
    rather than let authors invent it.
    """
    assert not is_resolvable_verify_target(JOINED_MULTI_TARGET_LINE)


def test_contract_documents_one_verify_line_per_target() -> None:
    text = _contract_text()
    assert "one `Verify:` line each" in text or "one `Verify:` line per target" in text, (
        "contract docs no longer state that multiple targets for one AC are "
        "expressed as one Verify: line each"
    )


@pytest.mark.parametrize(
    "target",
    [
        "diff of `docs//broken.md` adding a step",
        "diff of uncommitted local changes",
        "`some marker` present in the deployed environment",
        "diff of `<workflow file>` adding a step",
        "`<marker>` present in `tests/scripts/test_validate_issue_readiness.py`",
        "`docs/development/DEV_WORKFLOW.md :: later` removed as delivered.",
        "manual QA",
    ],
)
def test_grammar_still_rejects_unresolvable_targets(target: str) -> None:
    assert not is_resolvable_verify_target(target)
