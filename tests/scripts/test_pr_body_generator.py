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
    resolve_native_issue_authority,
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
    assert "Final-Review-Rounds: 0" in body
    assert "Closes #3275" in body
    assert "## SBS Impact" in body
    assert "- Primary subsystem: Builder System" in body
    assert "- [x] Owner-doc updated in this PR." in body
    assert _builderops_routing_satisfied(body)
    assert _ISSUE_LINK_REGEX.search(body)
    assert "<" not in body


def test_accepts_full_path_final_review_rounds() -> None:
    mapping = dict(_fixture("governance_issue.json"))
    mapping["final_review_rounds"] = 1

    body = generate_pr_body_from_mapping(mapping)

    assert "Final-Review-Rounds: 1" in body


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


def test_explicit_nonclosing_body_retains_governing_pickup_without_closure() -> None:
    data = {**_fixture("governance_issue.json"), "non_closing": True, "closing_issues": []}
    body = generate_pr_body_from_mapping(data)
    authority = resolve_native_issue_authority(body)
    assert authority is not None
    assert (authority.governing_issue, authority.closing_issues) == (3275, ())
    assert "Issue-Lifecycle: non-closing" in body
    assert f"Pickup-Receipt: {data['pickup_receipt']}" in body
    assert not _ISSUE_LINK_REGEX.search(body)
    assert "Verified-Closing-Issues" not in body
    assert resolve_issue_contract(body) is None  # no dispatched closure authority


@pytest.mark.parametrize("changes", [
    {"closing_issues": None}, {"closing_issues": [3275]}, {"issue_number": None},
    {"pickup_receipt": None}, {"pickup_receipt": "pickup-claim-complete issue=999"},
    {"non_closing": "true"}, {"non_closing": 1}, {"non_closing": False},
    {"notes": "Closes #3275"}, {"notes": "Verified-Closing-Issues: #3275"},
    {"notes": "Issue-Lifecycle: non-closing"},
])
def test_nonclosing_generator_refuses_implicit_mixed_or_unclaimed_scope(changes: dict) -> None:
    data = {**_fixture("governance_issue.json"), "non_closing": True, "closing_issues": [], **changes}
    with pytest.raises(PRBodyGeneratorError):
        generate_pr_body_from_mapping(data)


@pytest.mark.parametrize("flags", [
    ["--non-closing", "--non-closing"],
    ["--non-closing", "--closing-issue", "3275"],
])
def test_nonclosing_cli_refuses_duplicate_or_mixed_flags(flags: list[str]) -> None:
    completed = subprocess.run([sys.executable, "scripts/pr_body_generator.py", *flags], cwd=REPO_ROOT, capture_output=True, text=True, check=False)
    assert completed.returncode == 2
    assert completed.stdout == ""


@pytest.mark.parametrize("free_text", [
    "plain", "two words", "worker agent=TBD session=TBD", "  spaced\t value  ",
    "worker coordination_mode=github-label-only-fallback fallback_reason=x agent=TBD session=TBD",
])
def test_pickup_receipt_is_in_first_generated_body(free_text: str, tmp_path: Path) -> None:
    dispatcher = _fixture("governance_issue.json")
    dispatcher["pickup_receipt"] = str(dispatcher["pickup_receipt"]).replace(
        "holder=codex-slice-implementer", f"holder={free_text}"
    ).replace("worktree=/tmp/issue-3275-pr-body", f"worktree=/tmp/{free_text}/worktree")
    fallback = {
        **dispatcher,
        "pickup_receipt": (
            "pickup-claim-complete issue=3275 branch=codex/issue-3275-pr-body "
            "worktree=/tmp/issue-3275-pr-body coordination_mode=github-label-only-fallback "
            f"fallback_reason={free_text} agent={free_text} "
            f"session={free_text} evidence=github-comment:3275"
        ),
    }

    for inputs in (dispatcher, fallback):
        body = generate_pr_body_from_mapping(inputs)
        assert f"Pickup-Receipt: {inputs['pickup_receipt']}" in body
        assert body.count("Governing-Issue: #3275") == 1
        assert body.count("Closes #3275") == 1
        inputs_file = tmp_path / "inputs.json"
        inputs_file.write_text(json.dumps(inputs), encoding="utf-8")
        cli = subprocess.run(
            [sys.executable, "scripts/pr_body_generator.py", "--input-json", str(inputs_file)],
            cwd=REPO_ROOT, capture_output=True, text=True, check=False,
        )
        assert cli.returncode == 0, cli.stderr
        assert cli.stdout == body

    detached_claim = {
        **dispatcher,
        "pickup_receipt": dispatcher["pickup_receipt"].replace(
            "branch=codex/issue-3275-pr-body", "branch="
        ),
    }
    assert "branch= worktree=" in generate_pr_body_from_mapping(detached_claim)


def test_pickup_receipt_validation_preserves_scope_and_issue_free_lanes() -> None:
    issue_free = {**_fixture("governance_issue.json"), "issue_number": None, "pickup_receipt": None}
    issue_free_body = generate_pr_body_from_mapping(issue_free)
    assert "Pickup-Receipt:" not in issue_free_body
    batch = {
        **_fixture("governance_issue.json"),
        "closing_issues": [3276, 3277],
    }
    batch_body = generate_pr_body_from_mapping(batch)
    assert "Governing-Issue: #3275" in batch_body
    assert "Closes #3275" not in batch_body
    child_claim = {**batch, "pickup_receipt": str(batch["pickup_receipt"]).replace("3275", "3276")}
    child_body = generate_pr_body_from_mapping(child_claim)
    assert "Pickup-Receipt: pickup-claim-complete issue=3276" in child_body
    assert "Closes #3275" not in child_body

    for receipt in (
        None,
        "TBD",
        str(batch["pickup_receipt"]).replace("branch=codex/issue-3275-pr-body", "branch=<branch>"),
        str(batch["pickup_receipt"]).replace("-issue-3275 lease_id", "-issue-9999 lease_id"),
        "pickup-claim-complete issue=3275 branch=<branch> worktree=/tmp/x "
        "coordination_mode=dispatcher-backed fallback_reason=none task_id=t "
        "lease_id=l holder=h evidence=not-a-lease",
        "pickup-claim-complete issue=9999 branch=b worktree=/tmp/x "
        "coordination_mode=dispatcher-backed fallback_reason=none task_id=t "
        "lease_id=l holder=h evidence=verified-dispatcher-lease",
    ):
        invalid = {**_fixture("governance_issue.json"), "pickup_receipt": receipt}
        with pytest.raises(PRBodyGeneratorError, match="pickup_receipt"):
            generate_pr_body_from_mapping(invalid)


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


@pytest.mark.parametrize("success_count", [0, 1, 2])
def test_cli_accepts_pickup_receipt_file(tmp_path: Path, success_count: int) -> None:
    data = _fixture("governance_issue.json")
    receipt_file = tmp_path / "pickup-receipt.txt"
    receipt_file.write_text(
        '{"workspace_preflight": "passed"}\n' + (str(data["pickup_receipt"]) + "\n") * success_count,
        encoding="utf-8",
    )
    command = [
        sys.executable,
        "scripts/pr_body_generator.py",
        "--lane",
        "governance",
        "--issue-number",
        str(data["issue_number"]),
        "--pickup-receipt-file",
        str(receipt_file),
        "--summary",
        "generate a governed body",
        "--owner-doc-resolution",
        "updated",
        "--builderops-records",
        "none",
        "--builderops-reason",
        "fixture",
    ]
    for key, value in data["sbs_impact"].items():  # type: ignore[union-attr]
        command.extend(["--sbs", f"{key}={value}"])
    completed = subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True, check=False)

    if success_count == 1:
        assert completed.returncode == 0, completed.stderr
        assert f"Pickup-Receipt: {data['pickup_receipt']}\nCloses" in completed.stdout
    else:
        assert completed.returncode == 2
        assert "exactly one" in completed.stderr


def test_explicit_batch_preserves_open_governing_parent() -> None:
    from app.dispatcher.verification_contract import resolve_issue_authority

    data = {**_fixture("governance_issue.json"), "closing_issues": [3277, 3276]}
    body = generate_pr_body_from_mapping(data)
    authority = resolve_issue_authority(body)
    assert authority is not None
    assert authority.governing_issue == 3275
    assert authority.closing_issues == (3276, 3277)
    assert body.count("Governing-Issue:") == 1
    assert "Closes #3275" not in body


@pytest.mark.parametrize(
    "closing", [[], [1, 1], list(range(1, 12)), [True], [0], [-1], ["12"], "12"]
)
def test_body_generator_rejects_malformed_explicit_closing_sets(closing: object) -> None:
    data = {**_fixture("governance_issue.json"), "closing_issues": closing}
    with pytest.raises(PRBodyGeneratorError, match="closing_issues"):
        generate_pr_body_from_mapping(data)
