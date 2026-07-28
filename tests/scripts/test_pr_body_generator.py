from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from app.dispatcher.verification_contract import resolve_issue_contract
from scripts.pr_body_generator import (
    PRBodyGeneratorError,
    TEMPLATE_SECTION_HEADINGS,
    generate_pr_body_from_mapping,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = REPO_ROOT / "tests/fixtures/pr_body_generator"

_BUILDEROPS_ROUTING_REGEX = re.compile(
    r"(?:^|\n)## BuilderOps Routing[\s\S]*?(?=\n##\s|\n---)|(?:^|\n)## BuilderOps Routing[\s\S]*",
    re.IGNORECASE,
)
_ISSUE_LINK_REGEX = re.compile(r"(Fixes|Closes|Resolves)\s+#\d+", re.IGNORECASE)


def _fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _builderops_routing_satisfied(body: str) -> bool:
    match = _BUILDEROPS_ROUTING_REGEX.search(body)
    if not match:
        return False
    section = match.group(0)
    for pattern in (
        re.compile(
            r"(?:^|\n)\s*-\s*Records/projections/receipts:\s*(.*?)\s*(?:\n|$)",
            re.IGNORECASE,
        ),
        re.compile(r"(?:^|\n)\s*-\s*Reason:\s*(.*?)\s*(?:\n|$)", re.IGNORECASE),
    ):
        field = pattern.search(section)
        if not field:
            return False
        value = field.group(1).strip()
        if not value or re.fullmatch(r"<.*>", value):
            return False
    return True


def test_generator_section_contract_matches_pr_template() -> None:
    template = (REPO_ROOT / ".github/pull_request_template.md").read_text(encoding="utf-8")
    headings = tuple(re.findall(r"^## (.+)$", template, flags=re.MULTILINE))

    assert headings == TEMPLATE_SECTION_HEADINGS


def test_generates_valid_governance_lane_body() -> None:
    body = generate_pr_body_from_mapping(_fixture("governance_issue.json"))

    assert "- [x] Governance lane" in body
    assert "Final-Review-Rounds: 1" in body
    assert "Closes #3275" in body
    assert "## SBS Impact" in body
    assert "- Primary subsystem: Builder System" in body
    assert "- [x] Owner-doc updated in this PR." in body
    assert _builderops_routing_satisfied(body)
    assert _ISSUE_LINK_REGEX.search(body)
    assert "<" not in body


def test_accepts_light_path_zero_final_review_rounds() -> None:
    mapping = dict(_fixture("governance_issue.json"))
    mapping["final_review_rounds"] = 0

    body = generate_pr_body_from_mapping(mapping)

    assert "Final-Review-Rounds: 0" in body


def test_rejects_out_of_range_final_review_rounds() -> None:
    mapping = dict(_fixture("governance_issue.json"))
    mapping["final_review_rounds"] = 3

    with pytest.raises(PRBodyGeneratorError, match="final_review_rounds must be 0, 1, or 2"):
        generate_pr_body_from_mapping(mapping)


def test_issue_backed_body_emits_governing_issue_identity() -> None:
    body = generate_pr_body_from_mapping(_fixture("governance_issue.json"))

    assert body.count("Governing-Issue: #3275") == 1
    assert "Closes #3275" in body


def test_generated_issue_identity_is_accepted_by_verification_dispatch_contract() -> None:
    body = generate_pr_body_from_mapping(_fixture("governance_issue.json"))

    assert resolve_issue_contract(body) == (3275, ())


def test_direct_repair_body_includes_required_section() -> None:
    body = generate_pr_body_from_mapping(_fixture("direct_repair.json"))

    assert body.startswith("## Direct Repair\n")
    assert "Type: governance\n" in body
    assert "Reason: Bounded correction to existing governance wording.\n" in body
    assert "Validation: python3 scripts/docs_guard.py\n" in body
    assert "Issue required: no\n" in body
    assert "Closes #" not in body
    assert "Governing-Issue:" not in body
    assert _builderops_routing_satisfied(body)


def test_missing_required_input_fails_fast() -> None:
    with pytest.raises(PRBodyGeneratorError, match="implementation lane requires issue_number"):
        generate_pr_body_from_mapping(_fixture("missing_implementation_issue.json"))


@pytest.mark.parametrize("issue_number", [0, -1])
def test_non_positive_issue_number_fails_fast(issue_number: int) -> None:
    data = _fixture("governance_issue.json")
    data["issue_number"] = issue_number

    with pytest.raises(PRBodyGeneratorError, match="issue_number must be positive"):
        generate_pr_body_from_mapping(data)


def test_missing_sbs_input_fails_fast() -> None:
    data = _fixture("governance_issue.json")
    sbs = dict(data["sbs_impact"])  # type: ignore[arg-type]
    sbs["owner_doc_impact"] = "TBD"
    data["sbs_impact"] = sbs

    with pytest.raises(PRBodyGeneratorError, match="missing SBS impact fields: owner_doc_impact"):
        generate_pr_body_from_mapping(data)


def test_cli_generates_body_from_fixture() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/pr_body_generator.py",
            "--input-json",
            str(FIXTURE_DIR / "governance_issue.json"),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "- [x] Governance lane" in completed.stdout
    assert "Closes #3275" in completed.stdout
