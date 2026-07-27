"""Focused contract tests for deterministic deferred-defect intake."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HELPER_PATH = (
    REPO_ROOT
    / ".codex"
    / "skills"
    / "bug-to-issue"
    / "scripts"
    / "known_defects.py"
)


def _load_helper() -> ModuleType:
    spec = importlib.util.spec_from_file_location("known_defects", HELPER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


known_defects = _load_helper()


class FakeGateway:
    def __init__(self) -> None:
        self.label_ensured = 0
        self.issues: dict[int, dict[str, Any]] = {}
        self.comments: dict[int, list[dict[str, Any]]] = {}
        self.next_issue = 900
        self.next_comment = 1

    def ensure_registry_label(self) -> None:
        self.label_ensured += 1

    def list_registry_issues(self, state: str) -> list[dict[str, Any]]:
        return [
            issue
            for issue in self.issues.values()
            if known_defects.REGISTRY_LABEL
            in {
                label["name"] if isinstance(label, dict) else label
                for label in issue.get("labels", [])
            }
            and known_defects.REGISTRY_MARKER in (issue.get("body") or "")
            and (state == "all" or issue["state"] == state)
        ]

    def get_issue(self, number: int) -> dict[str, Any]:
        return self.issues[number]

    def create_registry_issue(self) -> dict[str, Any]:
        issue = {
            "number": self.next_issue,
            "state": "open",
            "title": "Known Defects Registry (rolling)",
            "body": known_defects.render_registry_body(),
            "labels": [
                {"name": "type:bug"},
                {"name": known_defects.REGISTRY_LABEL},
            ],
        }
        self.issues[self.next_issue] = issue
        self.comments[self.next_issue] = []
        self.next_issue += 1
        return issue

    def list_comments(self, issue_number: int) -> list[dict[str, Any]]:
        return list(self.comments.get(issue_number, []))

    def add_comment(self, issue_number: int, body: str) -> dict[str, Any]:
        comment = {
            "id": self.next_comment,
            "body": body,
            "html_url": (
                f"https://github.com/RasmusTho/agentic-pkm-mvp/"
                f"issues/{issue_number}#issuecomment-{self.next_comment}"
            ),
        }
        self.next_comment += 1
        self.comments.setdefault(issue_number, []).append(comment)
        return comment


def _defect(**overrides: Any) -> Any:
    values = {
        "repo": "RasmusTho/agentic-pkm-mvp",
        "source_pr": 4321,
        "source_sha": "a" * 40,
        "review_url": (
            "https://github.com/RasmusTho/agentic-pkm-mvp/"
            "pull/4321#discussion_r123"
        ),
        "symptom": "Retry receipts can display the stale attempt count.",
        "evidence": "The review reproduced count=1 after the second attempt.",
        "severity": "P3",
        "impact": "Operators may misread repair progress.",
        "workaround": "Read the raw attempt events.",
        "trigger": "Promote after a second occurrence or when this blocks closure.",
        "defect_key": None,
    }
    values.update(overrides)
    return known_defects.KnownDefect.validated(**values)


def _canonical_bug_body() -> str:
    sections = []
    for heading in known_defects.REQUIRED_ISSUE_SECTIONS:
        content = "Concrete content."
        if heading == "Acceptance Criteria":
            content = "- [ ] Regression no longer reproduces.\n  Verify: `tests/x.py::test_x`"
        sections.append(f"## {heading}\n\n{content}")
    return "\n\n".join(sections)


def test_repeated_intake_is_idempotent_and_reuses_one_registry() -> None:
    gateway = FakeGateway()
    defect = _defect()

    created = known_defects.intake_defect(defect, gateway)
    duplicate = known_defects.intake_defect(defect, gateway)

    assert created["status"] == "created"
    assert duplicate == {
        **created,
        "status": "duplicate",
    }
    assert created["defect_id"].startswith("KD-")
    assert len(gateway.issues) == 1
    assert len(gateway.comments[created["registry_issue"]]) == 1
    assert gateway.label_ensured == 2


def test_entry_records_every_required_field() -> None:
    defect = _defect()

    entry = defect.render_entry()

    assert known_defects.ENTRY_MARKER_TEMPLATE.format(defect_id=defect.defect_id) in entry
    for field in (
        "Source: PR #4321",
        "Reproducible symptom:",
        "Evidence:",
        "Impact/severity: P3",
        "Workaround:",
        "Re-evaluation/promotion trigger:",
    ):
        assert field in entry


def test_explicit_defect_key_keeps_id_stable_across_new_evidence() -> None:
    first = _defect(defect_key="receipt-attempt-count")
    later = _defect(
        defect_key="  Receipt-Attempt-Count  ",
        source_sha="b" * 40,
        symptom="Updated wording after a later reproduction.",
    )

    assert first.defect_id == later.defect_id


@pytest.mark.parametrize("classification", ["maintainability", "unproven"])
def test_non_defects_are_excluded_before_github_mutation(
    classification: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = known_defects.main(
        [
            "intake",
            "--repo",
            "RasmusTho/agentic-pkm-mvp",
            "--classification",
            classification,
            "--severity",
            "P3",
            "--source-pr",
            "4321",
            "--source-sha",
            "a" * 40,
            "--review-url",
            "https://github.com/RasmusTho/agentic-pkm-mvp/pull/4321",
            "--symptom",
            "Suggestion only.",
            "--evidence",
            "No confirmed defect.",
            "--impact",
            "None proven.",
            "--workaround",
            "Not applicable.",
            "--trigger",
            "Reclassify only after reproduction.",
        ]
    )

    receipt = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert receipt == {
        "reason": f"classification:{classification}",
        "schema": "known-defect-receipt.v1",
        "status": "excluded",
    }


def test_p0_and_p1_require_normal_bug_issue_instead_of_deferred_intake(
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = known_defects.main(
        [
            "intake",
            "--repo",
            "RasmusTho/agentic-pkm-mvp",
            "--classification",
            "confirmed-defect",
            "--severity",
            "P1",
            "--source-pr",
            "4321",
            "--source-sha",
            "a" * 40,
            "--review-url",
            "https://github.com/RasmusTho/agentic-pkm-mvp/pull/4321",
            "--symptom",
            "Severe regression.",
            "--evidence",
            "Confirmed.",
            "--impact",
            "High.",
            "--workaround",
            "None.",
            "--trigger",
            "Immediate.",
        ]
    )

    receipt = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert receipt["status"] == "promotion_required"
    assert receipt["reason"] == "severity:P1"


def test_promotion_links_only_a_canonical_normal_bug_issue() -> None:
    gateway = FakeGateway()
    defect = _defect()
    intake = known_defects.intake_defect(defect, gateway)
    gateway.issues[901] = {
        "number": 901,
        "state": "open",
        "body": _canonical_bug_body(),
        "labels": [
            {"name": "type:bug"},
            {"name": "prio:med"},
            {"name": "agent:ready"},
        ],
    }

    promoted = known_defects.promote_defect(defect.defect_id, 901, gateway)
    duplicate = known_defects.promote_defect(defect.defect_id, 901, gateway)
    looked_up = known_defects.lookup_defect(defect.defect_id, gateway)

    assert promoted["status"] == "promoted"
    assert duplicate["status"] == "promotion_duplicate"
    assert looked_up["status"] == "promoted"
    assert looked_up["promotion_issue"] == 901
    assert promoted["registry_issue"] == intake["registry_issue"]


def test_promotion_rejects_another_registry_or_incomplete_issue() -> None:
    gateway = FakeGateway()
    defect = _defect()
    intake = known_defects.intake_defect(defect, gateway)

    with pytest.raises(known_defects.KnownDefectsError, match="registry Issue"):
        known_defects.promote_defect(
            defect.defect_id,
            intake["registry_issue"],
            gateway,
        )

    gateway.issues[901] = {
        "number": 901,
        "state": "open",
        "body": "## Context\n\nToo small.",
        "labels": [
            {"name": "type:bug"},
            {"name": "prio:med"},
            {"name": "agent:ready"},
        ],
    }
    with pytest.raises(known_defects.KnownDefectsError, match="canonical section"):
        known_defects.promote_defect(defect.defect_id, 901, gateway)


def test_known_defect_label_is_canonical_and_registry_only() -> None:
    taxonomy = (
        REPO_ROOT / ".codex" / "skills" / "_shared" / "LABEL_TAXONOMY.md"
    ).read_text(encoding="utf-8")
    governance = (REPO_ROOT / ".github" / "github-governance.yml").read_text(
        encoding="utf-8"
    )
    setup = (REPO_ROOT / "docs" / "development" / "GITHUB_GOVERNANCE_SETUP.md").read_text(
        encoding="utf-8"
    )
    skill = (
        REPO_ROOT / ".codex" / "skills" / "bug-to-issue" / "SKILL.md"
    ).read_text(encoding="utf-8")

    for surface in (taxonomy, governance, setup, skill):
        assert "`state:known-defect`" in surface or "state:known-defect" in surface
    assert "must never carry `agent:ready`" in taxonomy
    assert "normal bounded `type:bug` Issue" in skill
