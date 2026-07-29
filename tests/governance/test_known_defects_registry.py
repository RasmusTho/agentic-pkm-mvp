"""Focused contract tests for deterministic deferred-defect intake."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

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
        self.registry_identity_numbers: set[int] = set()

    def ensure_registry_label(self) -> None:
        self.label_ensured += 1

    def list_registry_issues(self, state: str) -> list[dict[str, Any]]:
        return [
            issue
            for issue in self.issues.values()
            if (
                known_defects.REGISTRY_LABEL
                in {
                    label["name"] if isinstance(label, dict) else label
                    for label in issue.get("labels", [])
                }
                or issue.get("title") == known_defects.REGISTRY_TITLE
                or int(issue["number"]) in self.registry_identity_numbers
            )
            and (state == "all" or issue["state"] == state)
        ]

    def get_issue(self, number: int) -> dict[str, Any]:
        return self.issues[number]

    def refresh_registry_identities(self) -> None:
        self.registry_identity_numbers.update(
            int(issue["number"])
            for issue in self.issues.values()
            if (
                known_defects.REGISTRY_LABEL
                in {
                    label["name"] if isinstance(label, dict) else label
                    for label in issue.get("labels", [])
                }
                or issue.get("title") == known_defects.REGISTRY_TITLE
                or str(issue.get("body") or "").startswith(
                    f"{known_defects.REGISTRY_MARKER}\n"
                )
            )
        )
        for issue_number, comments in self.comments.items():
            for comment in comments:
                body = str(comment.get("body") or "")
                first_line = body.splitlines()[0] if body.splitlines() else ""
                if (
                    str(comment.get("author_association") or "").upper()
                    in known_defects.TRUSTED_AUTHOR_ASSOCIATIONS
                    and (
                        first_line.startswith("<!-- known-defect-entry:")
                        or first_line.startswith("<!-- known-defect-promotion:")
                    )
                ):
                    known_defects._validate_schema_comment(comment)
                    self.registry_identity_numbers.add(issue_number)

    def create_registry_issue(self) -> dict[str, Any]:
        while self.next_issue in self.issues:
            self.next_issue += 1
        issue = {
            "number": self.next_issue,
            "state": "open",
            "locked": False,
            "title": known_defects.REGISTRY_TITLE,
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

    def lock_registry_issue(self, issue_number: int) -> None:
        self.issues[issue_number]["locked"] = True

    def list_comments(self, issue_number: int) -> list[dict[str, Any]]:
        return list(self.comments.get(issue_number, []))

    def add_comment(self, issue_number: int, body: str) -> dict[str, Any]:
        comment = {
            "id": self.next_comment,
            "created_at": f"2026-07-27T00:00:{self.next_comment:02d}Z",
            "body": body,
            "author_association": "OWNER",
            "html_url": (
                f"https://github.com/RasmusTho/agentic-pkm-mvp/"
                f"issues/{issue_number}#issuecomment-{self.next_comment}"
            ),
        }
        self.next_comment += 1
        self.comments.setdefault(issue_number, []).append(comment)
        return comment

    def delete_comment(self, comment_id: int) -> None:
        for issue_comments in self.comments.values():
            issue_comments[:] = [
                comment
                for comment in issue_comments
                if int(comment["id"]) != comment_id
            ]

    def update_comment(self, comment_id: int, body: str) -> dict[str, Any]:
        for issue_comments in self.comments.values():
            for comment in issue_comments:
                if int(comment["id"]) == comment_id:
                    comment["body"] = body
                    return comment
        raise KeyError(comment_id)


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
        "severity": "P2",
        "impact": "Operators may misread repair progress.",
        "workaround": "Read the raw attempt events.",
        "trigger": "Promote after a second occurrence or when this blocks closure.",
        "defect_key": None,
    }
    values.update(overrides)
    return known_defects.KnownDefect.validated(**values)


def _canonical_bug_body() -> str:
    return """## Context

The confirmed defect needs a bounded implementation contract.

## Scope

Change the affected helper and its focused regression test.

## Source Anchors

- `.codex/skills/bug-to-issue/SKILL.md :: Promotion`

## SBS Impact

- Primary subsystem: Builder System / CES boundary
- Secondary subsystem(s): none
- Write class: governance/docs/process
- Persistence impact: none
- Derived/rebuildable impact: none
- New or changed contract: none
- Owner-doc impact: none
- Transition debt impact: reduces
- Boundary risk: bounded defect repair must not bypass the canonical issue contract

## Constraints

- Preserve unrelated behavior.

## Acceptance Criteria

- [ ] Regression no longer reproduces.
  Verify: `tests/governance/test_known_defects_registry.py::test_promotion_requires_concrete_verify_target_on_every_ac`

## Out of Scope

- Unrelated refactors.

## Suggested Validation

- `pytest -q tests/x.py`

## Source Docs

- `.codex/skills/_shared/ISSUE_CONTRACT.md`"""


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

    assert known_defects.ENTRY_MARKER_TEMPLATE.format(
        defect_id=defect.defect_id,
        phase="final",
    ) in entry
    for field in (
        "Source: PR #4321",
        "Reproducible symptom:",
        "Evidence:",
        "Impact/severity: P2",
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


def test_review_url_host_is_canonicalized_before_schema_rendering() -> None:
    defect = _defect(
        review_url=(
            "https://GitHub.com/RasmusTho/agentic-pkm-mvp/"
            "pull/4321#discussion_r123"
        )
    )

    receipt = known_defects.intake_defect(defect, FakeGateway())

    assert receipt["status"] == "created"
    assert defect.review_url.startswith("https://github.com/")


def test_review_url_must_round_trip_through_the_entry_schema() -> None:
    gateway = FakeGateway()

    with pytest.raises(known_defects.KnownDefectsError, match="round-trip"):
        known_defects.KnownDefect.validated(
            **{
                **_defect().__dict__,
                "review_url": (
                    "https://github.com/RasmusTho/agentic-pkm-mvp/"
                    "pull/4321/(invalid)"
                ),
            }
        )

    assert gateway.issues == {}
    assert gateway.comments == {}


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


def test_p3_is_informational_and_excluded_before_github_mutation(
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
            "P3",
            "--source-pr",
            "4321",
            "--source-sha",
            "a" * 40,
            "--review-url",
            "https://github.com/RasmusTho/agentic-pkm-mvp/pull/4321",
            "--symptom",
            "Informational review observation.",
            "--evidence",
            "No P2 defect impact.",
            "--impact",
            "Informational only.",
            "--workaround",
            "Not applicable.",
            "--trigger",
            "Reclassify only if impact reaches P2.",
        ]
    )

    receipt = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert receipt == {
        "reason": "severity:P3_non_defect",
        "schema": "known-defect-receipt.v1",
        "status": "excluded",
    }
    with pytest.raises(known_defects.KnownDefectsError, match="only confirmed"):
        _defect(severity="P3")

    bug_skill = (
        REPO_ROOT / ".codex" / "skills" / "bug-to-issue" / "SKILL.md"
    ).read_text(encoding="utf-8")
    verification_skill = (
        REPO_ROOT / ".codex" / "skills" / "verification-and-closure" / "SKILL.md"
    ).read_text(encoding="utf-8")
    skill_index = (REPO_ROOT / ".codex" / "skills" / "README.md").read_text(
        encoding="utf-8"
    )
    assert "P3 is informational/non-defect" in bug_skill
    assert "P3 observations may remain informational" in verification_skill
    assert "confirmed deferred\n    P2 review findings" in skill_index
    assert "confirmed deferred\n    P2/P3 review findings" not in skill_index


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
        "title": "bug: prevent stale retry receipts",
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


@pytest.mark.parametrize(
    ("state", "agent_labels"),
    [
        ("open", []),
        ("closed", []),
    ],
)
def test_promotion_retry_converges_after_target_claim_or_closure(
    state: str,
    agent_labels: list[dict[str, str]],
) -> None:
    gateway = FakeGateway()
    defect = _defect()
    known_defects.intake_defect(defect, gateway)
    gateway.issues[901] = {
        "number": 901,
        "title": "bug: prevent stale retry receipts",
        "state": "open",
        "body": _canonical_bug_body(),
        "labels": [
            {"name": "type:bug"},
            {"name": "prio:med"},
            {"name": "agent:ready"},
        ],
    }
    promoted = known_defects.promote_defect(defect.defect_id, 901, gateway)
    gateway.issues[901]["state"] = state
    gateway.issues[901]["labels"] = [
        {"name": "type:bug"},
        {"name": "prio:med"},
        *agent_labels,
    ]

    duplicate = known_defects.promote_defect(defect.defect_id, 901, gateway)

    assert promoted["status"] == "promoted"
    assert duplicate == {
        **promoted,
        "status": "promotion_duplicate",
    }


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
        "title": "bug: reject incomplete promotion contracts",
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


@pytest.mark.parametrize(
    "title",
    [
        "fix stale retry receipts",
        "BUG: stale retry receipts",
        "bug: ",
        "bug: " + "x" * 156,
    ],
)
def test_promotion_rejects_noncanonical_bug_title(title: str) -> None:
    gateway = FakeGateway()
    defect = _defect()
    known_defects.intake_defect(defect, gateway)
    gateway.issues[901] = {
        "number": 901,
        "title": title,
        "state": "open",
        "body": _canonical_bug_body(),
        "labels": [
            {"name": "type:bug"},
            {"name": "prio:med"},
            {"name": "agent:ready"},
        ],
    }

    with pytest.raises(known_defects.KnownDefectsError, match="title"):
        known_defects.promote_defect(defect.defect_id, 901, gateway)


def test_promotion_rejects_empty_or_placeholder_canonical_sections() -> None:
    gateway = FakeGateway()
    defect = _defect()
    known_defects.intake_defect(defect, gateway)
    body = "\n\n".join(
        (
            f"## {heading}\n\n"
            + (
                "- [ ] A bounded outcome.\n  Verify: `tests/governance/test_known_defects_registry.py::test_promotion_requires_concrete_verify_target_on_every_ac`"
                if heading == "Acceptance Criteria"
                else "<placeholder>"
            )
        )
        for heading in known_defects.REQUIRED_ISSUE_SECTIONS
    )
    gateway.issues[901] = {
        "number": 901,
        "title": "bug: reject empty promotion contracts",
        "state": "open",
        "body": body,
        "labels": [
            {"name": "type:bug"},
            {"name": "prio:med"},
            {"name": "agent:ready"},
        ],
    }

    with pytest.raises(known_defects.KnownDefectsError, match="placeholder"):
        known_defects.promote_defect(defect.defect_id, 901, gateway)


def test_promotion_rejects_missing_sbs_fields_and_unexpected_top_level_section() -> None:
    gateway = FakeGateway()
    defect = _defect()
    known_defects.intake_defect(defect, gateway)
    gateway.issues[901] = {
        "number": 901,
        "title": "bug: reject incomplete SBS contracts",
        "state": "open",
        "body": _canonical_bug_body().replace(
            "- Boundary risk: bounded defect repair must not bypass the canonical issue contract",
            "- Other impact: none",
        ),
        "labels": [
            {"name": "type:bug"},
            {"name": "prio:med"},
            {"name": "agent:ready"},
        ],
    }
    with pytest.raises(known_defects.KnownDefectsError, match="Boundary risk"):
        known_defects.promote_defect(defect.defect_id, 901, gateway)

    gateway.issues[901]["body"] = (
        _canonical_bug_body() + "\n\n## Manual Notes\n\nNot canonical."
    )
    with pytest.raises(known_defects.KnownDefectsError, match="unexpected"):
        known_defects.promote_defect(defect.defect_id, 901, gateway)


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (
            _canonical_bug_body().replace("## Context", "## context"),
            "canonical section",
        ),
        (
            _canonical_bug_body().replace(
                "`.codex/skills/bug-to-issue/SKILL.md :: Promotion`",
                "`<path> :: <anchor>`",
            ),
            "placeholder",
        ),
        (
            _canonical_bug_body().replace(
                "Verify: `tests/governance/test_known_defects_registry.py::test_promotion_requires_concrete_verify_target_on_every_ac`",
                "Verify: later",
            ),
            "resolvable Verify",
        ),
    ],
)
def test_promotion_rejects_noncanonical_heading_anchor_and_verify_target(
    body: str,
    expected: str,
) -> None:
    gateway = FakeGateway()
    defect = _defect()
    known_defects.intake_defect(defect, gateway)
    gateway.issues[901] = {
        "number": 901,
        "title": "bug: reject malformed implementation authority",
        "state": "open",
        "body": body,
        "labels": [
            {"name": "type:bug"},
            {"name": "prio:med"},
            {"name": "agent:ready"},
        ],
    }

    with pytest.raises(known_defects.KnownDefectsError, match=expected):
        known_defects.promote_defect(defect.defect_id, 901, gateway)


@pytest.mark.parametrize("extra_label", ["maintenance", "state:other"])
def test_promotion_rejects_labels_outside_the_canonical_issue_axes(
    extra_label: str,
) -> None:
    gateway = FakeGateway()
    defect = _defect()
    known_defects.intake_defect(defect, gateway)
    gateway.issues[901] = {
        "number": 901,
        "title": "bug: reject noncanonical labels",
        "state": "open",
        "body": _canonical_bug_body(),
        "labels": [
            {"name": "type:bug"},
            {"name": "prio:med"},
            {"name": "agent:ready"},
            {"name": extra_label},
        ],
    }

    with pytest.raises(known_defects.KnownDefectsError, match="unexpected label"):
        known_defects.promote_defect(defect.defect_id, 901, gateway)


def test_registry_reads_require_identity_but_survive_later_state_drift() -> None:
    gateway = FakeGateway()
    issue = gateway.create_registry_issue()
    gateway.lock_registry_issue(issue["number"])
    issue["labels"] = [{"name": known_defects.REGISTRY_LABEL}]
    with pytest.raises(known_defects.KnownDefectsError, match="readable registry"):
        known_defects.lookup_defect("KD-000000000000", gateway)

    for mutation in (
        lambda candidate: candidate["labels"].append({"name": "agent:blocked"}),
        lambda candidate: candidate.update(locked=False),
    ):
        gateway = FakeGateway()
        issue = gateway.create_registry_issue()
        gateway.lock_registry_issue(issue["number"])
        mutation(issue)
        assert known_defects.lookup_defect("KD-000000000000", gateway)[
            "status"
        ] == "not_found"


def test_marker_injection_in_manual_comment_is_not_registry_authority() -> None:
    gateway = FakeGateway()
    issue = gateway.create_registry_issue()
    gateway.lock_registry_issue(issue["number"])
    gateway.add_comment(
        issue["number"],
        "Manual note with injected marker "
        "<!-- known-defect-entry:v1 id=KD-000000000000 -->",
    )

    receipt = known_defects.lookup_defect("KD-000000000000", gateway)

    assert receipt["status"] == "not_found"


def test_malformed_first_line_schema_marker_fails_closed() -> None:
    gateway = FakeGateway()
    issue = gateway.create_registry_issue()
    gateway.lock_registry_issue(issue["number"])
    gateway.add_comment(
        issue["number"],
        "<!-- known-defect-entry:v1 id=KD-000000000000 -->\nnot the schema",
    )

    with pytest.raises(known_defects.KnownDefectsError, match="entry marker"):
        known_defects.lookup_defect("KD-000000000000", gateway)


def test_schema_comment_requires_stable_creation_authority() -> None:
    gateway = FakeGateway()
    issue = gateway.create_registry_issue()
    gateway.lock_registry_issue(issue["number"])
    comment = gateway.add_comment(issue["number"], _defect().render_entry())
    del comment["created_at"]

    with pytest.raises(known_defects.KnownDefectsError, match="creation authority"):
        known_defects.lookup_defect(_defect().defect_id, gateway)


@pytest.mark.parametrize(
    ("line_index", "replacement", "expected"),
    [
        (4, "- Source: PR #0 @ `" + "a" * 40 + "` ([review evidence](https://github.com/RasmusTho/agentic-pkm-mvp/pull/4321))", "source"),
        (4, "- Source: PR #4321 @ `abc` ([review evidence](https://github.com/RasmusTho/agentic-pkm-mvp/pull/4321))", "source"),
        (4, "- Source: PR #4321 @ `" + "a" * 40 + "` ([review evidence](https://github.com/RasmusTho/agentic-pkm-mvp/pull/9999))", "review URL"),
        (5, "- Reproducible symptom: ", "symptom"),
        (6, "- Evidence: ", "evidence"),
        (7, "- Impact/severity: P1 — invalid", "impact/severity"),
        (7, "- Impact/severity: P2 — ", "impact/severity"),
        (8, "- Workaround: ", "workaround"),
        (9, "- Re-evaluation/promotion trigger: ", "trigger"),
    ],
)
def test_prefix_complete_but_invalid_entry_fields_fail_closed(
    line_index: int,
    replacement: str,
    expected: str,
) -> None:
    gateway = FakeGateway()
    issue = gateway.create_registry_issue()
    gateway.lock_registry_issue(issue["number"])
    lines = _defect().render_entry().splitlines()
    lines[line_index] = replacement
    gateway.add_comment(issue["number"], "\n".join(lines))

    with pytest.raises(known_defects.KnownDefectsError, match=expected):
        known_defects.lookup_defect(_defect().defect_id, gateway)


@pytest.mark.parametrize("issue_text", ["0", "001"])
def test_noncanonical_promotion_issue_number_fails_closed(issue_text: str) -> None:
    defect_id = "KD-000000000000"
    body = "\n".join(
        (
            (
                "<!-- known-defect-promotion:v1 "
                f"id={defect_id} issue={issue_text} "
                f"authority_sha256={'0' * 64} phase=final -->"
            ),
            (
                f"Promotion receipt: {defect_id} is now tracked for implementation "
                f"by #{issue_text}."
            ),
            f"Validated target snapshot: sha256:{'0' * 64}.",
            (
                "The bounded bug Issue owns scope, acceptance criteria, Verify targets, "
                "and execution state."
            ),
        )
    )

    with pytest.raises(known_defects.KnownDefectsError, match="promotion marker"):
        known_defects._promotion_from_comment(body)


def test_multiple_open_registries_fail_closed() -> None:
    gateway = FakeGateway()
    first = gateway.create_registry_issue()
    gateway.lock_registry_issue(first["number"])
    second = gateway.create_registry_issue()
    gateway.lock_registry_issue(second["number"])

    with pytest.raises(known_defects.KnownDefectsError, match="multiple open registries"):
        known_defects.intake_defect(_defect(), gateway)


def test_entry_in_first_of_two_open_registries_does_not_bypass_ambiguity() -> None:
    gateway = FakeGateway()
    defect = _defect()
    first = gateway.create_registry_issue()
    gateway.lock_registry_issue(first["number"])
    gateway.add_comment(first["number"], defect.render_entry())
    second = gateway.create_registry_issue()
    gateway.lock_registry_issue(second["number"])

    with pytest.raises(known_defects.KnownDefectsError, match="multiple open registries"):
        known_defects.intake_defect(defect, gateway)
    assert known_defects.lookup_defect(defect.defect_id, gateway)[
        "status"
    ] == "deferred"


def test_later_malformed_registry_candidate_is_not_skipped_after_entry_match() -> None:
    gateway = FakeGateway()
    defect = _defect()
    first = gateway.create_registry_issue()
    gateway.lock_registry_issue(first["number"])
    gateway.add_comment(first["number"], defect.render_entry())
    second = gateway.create_registry_issue()
    gateway.lock_registry_issue(second["number"])
    second["state"] = "closed"
    second["body"] = "not a registry"

    with pytest.raises(known_defects.KnownDefectsError, match="readable registry"):
        known_defects.lookup_defect(defect.defect_id, gateway)


@pytest.mark.parametrize("body", [
    "prefix\n" + known_defects.render_registry_body(),
    "manual text " + known_defects.REGISTRY_MARKER,
])
def test_registry_read_identity_requires_marker_on_first_line(body: str) -> None:
    gateway = FakeGateway()
    issue = gateway.create_registry_issue()
    gateway.lock_registry_issue(issue["number"])
    issue["body"] = body

    with pytest.raises(known_defects.KnownDefectsError, match="readable registry"):
        known_defects.lookup_defect("KD-000000000000", gateway)


def test_registry_read_survives_later_body_suffix_drift() -> None:
    gateway = FakeGateway()
    issue = gateway.create_registry_issue()
    gateway.lock_registry_issue(issue["number"])
    issue["body"] = known_defects.render_registry_body() + "\nsuffix"

    assert known_defects.lookup_defect("KD-000000000000", gateway)[
        "status"
    ] == "not_found"


def test_crash_after_comment_before_receipt_is_safe_to_retry() -> None:
    gateway = FakeGateway()
    issue = gateway.create_registry_issue()
    gateway.lock_registry_issue(issue["number"])
    defect = _defect()
    original = gateway.add_comment(issue["number"], defect.render_entry())

    receipt = known_defects.intake_defect(defect, gateway)

    assert receipt["status"] == "duplicate"
    assert receipt["url"] == original["html_url"]
    assert len(gateway.comments[issue["number"]]) == 1


def test_crash_after_create_before_lock_recovers_one_canonical_registry() -> None:
    gateway = FakeGateway()
    issue = gateway.create_registry_issue()

    receipt = known_defects.intake_defect(_defect(), gateway)

    assert receipt["status"] == "created"
    assert receipt["registry_issue"] == issue["number"]
    assert gateway.issues[issue["number"]]["locked"] is True
    assert len(gateway.issues) == 1
    assert len(gateway.comments[issue["number"]]) == 1


class AmbiguousCreateGateway(FakeGateway):
    def __init__(self) -> None:
        super().__init__()
        self.fail_create_response = True

    def create_registry_issue(self) -> dict[str, Any]:
        issue = super().create_registry_issue()
        if self.fail_create_response:
            self.fail_create_response = False
            raise known_defects.KnownDefectsError(
                "GitHub REST request failed after registry creation"
            )
        return issue


def test_ambiguous_create_response_converges_on_retry_without_duplicate_issue() -> None:
    gateway = AmbiguousCreateGateway()
    defect = _defect()

    with pytest.raises(known_defects.KnownDefectsError, match="after registry creation"):
        known_defects.intake_defect(defect, gateway)
    receipt = known_defects.intake_defect(defect, gateway)

    assert receipt["status"] == "created"
    assert receipt["registry_issue"] == 900
    assert gateway.issues[900]["locked"] is True
    assert len(gateway.issues) == 1
    assert len(gateway.comments[900]) == 1


def test_trusted_entry_written_before_lock_is_reused_after_bootstrap_recovery() -> None:
    gateway = FakeGateway()
    issue = gateway.create_registry_issue()
    defect = _defect()
    original = gateway.add_comment(issue["number"], defect.render_entry())

    receipt = known_defects.intake_defect(defect, gateway)

    assert receipt["status"] == "duplicate"
    assert receipt["url"] == original["html_url"]
    assert gateway.issues[issue["number"]]["locked"] is True
    assert len(gateway.comments[issue["number"]]) == 1


def test_untrusted_entry_written_before_lock_fails_closed_after_recovery() -> None:
    gateway = FakeGateway()
    issue = gateway.create_registry_issue()
    comment = gateway.add_comment(issue["number"], _defect().render_entry())
    comment["author_association"] = "NONE"

    with pytest.raises(known_defects.KnownDefectsError, match="untrusted author"):
        known_defects.intake_defect(_defect(), gateway)

    assert gateway.issues[issue["number"]]["locked"] is True
    assert len(gateway.issues) == 1


def test_untrusted_promotion_written_before_lock_fails_closed_after_entry_match() -> None:
    gateway = FakeGateway()
    issue = gateway.create_registry_issue()
    defect = _defect()
    gateway.add_comment(issue["number"], defect.render_entry())
    promotion = gateway.add_comment(
        issue["number"],
        "\n".join(
            (
                known_defects.PROMOTION_MARKER_TEMPLATE.format(
                    defect_id=defect.defect_id,
                    issue_number=901,
                    authority_sha256="0" * 64,
                    phase="final",
                ),
                (
                    f"Promotion receipt: {defect.defect_id} is now tracked for "
                    "implementation by #901."
                ),
                f"Validated target snapshot: sha256:{'0' * 64}.",
                (
                    "The bounded bug Issue owns scope, acceptance criteria, Verify "
                    "targets, and execution state."
                ),
            )
        ),
    )
    promotion["author_association"] = "CONTRIBUTOR"

    with pytest.raises(known_defects.KnownDefectsError, match="untrusted author"):
        known_defects.intake_defect(defect, gateway)

    assert gateway.issues[issue["number"]]["locked"] is True


def test_closed_registry_is_read_for_duplicates_but_never_appended() -> None:
    gateway = FakeGateway()
    issue = gateway.create_registry_issue()
    gateway.lock_registry_issue(issue["number"])
    issue["state"] = "closed"
    defect = _defect()
    gateway.add_comment(issue["number"], defect.render_entry())

    duplicate = known_defects.intake_defect(defect, gateway)
    created = known_defects.intake_defect(
        _defect(defect_key="different-defect"),
        gateway,
    )

    assert duplicate["status"] == "duplicate"
    assert duplicate["registry_issue"] == issue["number"]
    assert created["status"] == "created"
    assert created["registry_issue"] != issue["number"]
    assert len(gateway.comments[issue["number"]]) == 1


def test_selector_label_loss_fails_closed_without_duplicate_authority() -> None:
    gateway = FakeGateway()
    defect = _defect()
    receipt = known_defects.intake_defect(defect, gateway)
    registry_number = int(receipt["registry_issue"])
    gateway.issues[registry_number]["labels"] = [{"name": "type:bug"}]

    with pytest.raises(known_defects.KnownDefectsError, match="registry container"):
        known_defects.lookup_defect(defect.defect_id, gateway)
    with pytest.raises(known_defects.KnownDefectsError, match="registry container"):
        known_defects.intake_defect(defect, gateway)

    assert len(gateway.issues) == 1
    assert len(gateway.comments[registry_number]) == 1
    assert "phase=final" in (
        gateway.comments[registry_number][0]["body"].splitlines()[0]
    )


class CloseBeforeAppendGateway(FakeGateway):
    def __init__(self) -> None:
        super().__init__()
        self.closed_once = False

    def get_issue(self, number: int) -> dict[str, Any]:
        issue = super().get_issue(number)
        if number == 900 and issue["locked"] and not self.closed_once:
            issue["state"] = "closed"
            self.closed_once = True
        return issue


def test_registry_close_before_append_retries_without_stale_mutation() -> None:
    gateway = CloseBeforeAppendGateway()

    receipt = known_defects.intake_defect(_defect(), gateway)

    assert receipt["status"] == "created"
    assert receipt["registry_issue"] == 901
    assert gateway.comments[900] == []
    assert len(gateway.comments[901]) == 1


class CloseDuringFinalEntryAuthorityCheckGateway(FakeGateway):
    def __init__(self) -> None:
        super().__init__()
        self.close_on_next_inventory = False

    def get_issue(self, number: int) -> dict[str, Any]:
        issue = super().get_issue(number)
        if number == 900 and issue["locked"]:
            self.close_on_next_inventory = True
        return issue

    def list_registry_issues(self, state: str) -> list[dict[str, Any]]:
        if self.close_on_next_inventory:
            self.issues[900]["state"] = "closed"
            self.close_on_next_inventory = False
        return super().list_registry_issues(state)


def test_final_entry_authority_check_closure_retries_without_write() -> None:
    gateway = CloseDuringFinalEntryAuthorityCheckGateway()

    receipt = known_defects.intake_defect(_defect(), gateway)

    assert receipt["status"] == "created"
    assert receipt["registry_issue"] == 901
    assert gateway.comments[900] == []
    assert len(gateway.comments[901]) == 1
    assert "phase=final" in gateway.comments[901][0]["body"].splitlines()[0]


class HiddenPriorAtFinalEntryFenceGateway(FakeGateway):
    def __init__(self, defect: Any) -> None:
        super().__init__()
        self.defect = defect
        self.identity_refreshes = 0

    def refresh_registry_identities(self) -> None:
        self.identity_refreshes += 1
        if self.identity_refreshes == 3:
            self.issues[899] = {
                "number": 899,
                "state": "closed",
                "locked": True,
                "title": "Renamed registry",
                "body": known_defects.render_registry_body(),
                "labels": [{"name": "type:bug"}],
            }
            self.comments[899] = []
            super().add_comment(899, self.defect.render_entry(phase="final"))
        super().refresh_registry_identities()


def test_final_entry_fence_enumerates_hidden_prior_before_write() -> None:
    defect = _defect()
    gateway = HiddenPriorAtFinalEntryFenceGateway(defect)

    with pytest.raises(known_defects.KnownDefectsError, match="registry title"):
        known_defects.intake_defect(defect, gateway)

    assert gateway.identity_refreshes == 3
    assert gateway.comments[900] == []
    assert len(gateway.comments[899]) == 1
    assert "phase=final" in gateway.comments[899][0]["body"].splitlines()[0]


class CloseAfterAppendGateway(FakeGateway):
    def __init__(self) -> None:
        super().__init__()
        self.closed_once = False

    def add_comment(self, issue_number: int, body: str) -> dict[str, Any]:
        comment = super().add_comment(issue_number, body)
        if (
            issue_number == 900
            and body.startswith("<!-- known-defect-entry:")
            and not self.closed_once
        ):
            self.issues[issue_number]["state"] = "closed"
            self.closed_once = True
        return comment


def test_registry_close_after_append_preserves_reserved_entry() -> None:
    gateway = CloseAfterAppendGateway()

    receipt = known_defects.intake_defect(_defect(), gateway)

    assert receipt["status"] == "created"
    assert receipt["registry_issue"] == 900
    assert len(gateway.comments[900]) == 1
    assert "phase=final" in gateway.comments[900][0]["body"].splitlines()[0]


class MalformedAfterAppendGateway(FakeGateway):
    def add_comment(self, issue_number: int, body: str) -> dict[str, Any]:
        comment = super().add_comment(issue_number, body)
        if issue_number == 900 and body.startswith("<!-- known-defect-entry:"):
            self.issues[issue_number]["labels"].append({"name": "agent:blocked"})
        return comment


def test_registry_authority_drift_after_append_preserves_reservation() -> None:
    gateway = MalformedAfterAppendGateway()

    receipt = known_defects.intake_defect(_defect(), gateway)

    assert receipt["status"] == "created"
    assert receipt["registry_issue"] == 900
    assert len(gateway.comments[900]) == 1
    assert "phase=final" in gateway.comments[900][0]["body"].splitlines()[0]


class PostAppendReadFailureGateway(FakeGateway):
    def __init__(self) -> None:
        super().__init__()
        self.fail_next_get = False

    def add_comment(self, issue_number: int, body: str) -> dict[str, Any]:
        comment = super().add_comment(issue_number, body)
        if body.startswith("<!-- known-defect-entry:"):
            self.fail_next_get = True
        return comment

    def get_issue(self, number: int) -> dict[str, Any]:
        if self.fail_next_get:
            self.fail_next_get = False
            raise known_defects.KnownDefectsError("indeterminate post-write read")
        return super().get_issue(number)


def test_entry_commit_needs_no_post_append_issue_read() -> None:
    gateway = PostAppendReadFailureGateway()

    receipt = known_defects.intake_defect(_defect(), gateway)

    assert receipt["status"] == "created"
    assert gateway.fail_next_get is True
    assert len(gateway.comments[900]) == 1
    assert "phase=final" in gateway.comments[900][0]["body"].splitlines()[0]


class AmbiguousEntryCreateGateway(FakeGateway):
    def __init__(self, *, close_registry: bool = True) -> None:
        super().__init__()
        self.ambiguous_once = True
        self.close_registry = close_registry

    def add_comment(self, issue_number: int, body: str) -> dict[str, Any]:
        comment = super().add_comment(issue_number, body)
        if body.startswith("<!-- known-defect-entry:") and self.ambiguous_once:
            self.ambiguous_once = False
            if self.close_registry:
                self.issues[issue_number]["state"] = "closed"
            raise known_defects.KnownDefectsError(
                "ambiguous entry comment-create response"
            )
        return comment


def test_ambiguous_entry_create_response_preserves_closed_reservation() -> None:
    gateway = AmbiguousEntryCreateGateway()

    receipt = known_defects.intake_defect(_defect(), gateway)

    assert receipt["status"] == "created"
    assert receipt["registry_issue"] == 900
    assert len(gateway.comments[900]) == 1
    assert "phase=final" in gateway.comments[900][0]["body"].splitlines()[0]


def test_ambiguous_entry_create_response_completes_from_open_inventory() -> None:
    gateway = AmbiguousEntryCreateGateway(close_registry=False)

    receipt = known_defects.intake_defect(_defect(), gateway)

    assert receipt["status"] == "created"
    assert receipt["registry_issue"] == 900
    assert len(gateway.comments[900]) == 1


class EntryFinalizeFailureGateway(FakeGateway):
    def __init__(self, *, apply_before_failure: bool) -> None:
        super().__init__()
        self.apply_before_failure = apply_before_failure
        self.fail_once = True

    def update_comment(self, comment_id: int, body: str) -> dict[str, Any]:
        if self.fail_once:
            self.fail_once = False
            if self.apply_before_failure:
                super().update_comment(comment_id, body)
            raise known_defects.KnownDefectsError(
                "ambiguous entry comment-update response"
            )
        return super().update_comment(comment_id, body)


def test_ambiguous_entry_finalize_response_recovers_applied_final_comment() -> None:
    gateway = EntryFinalizeFailureGateway(apply_before_failure=True)

    receipt = known_defects.intake_defect(_defect(), gateway)

    assert receipt["status"] == "created"
    assert "phase=final" in gateway.comments[900][0]["body"].splitlines()[0]


def test_failed_entry_finalize_leaves_nonauthoritative_pending_for_retry() -> None:
    gateway = EntryFinalizeFailureGateway(apply_before_failure=False)
    defect = _defect()

    with pytest.raises(known_defects.KnownDefectsError, match="ambiguous entry"):
        known_defects.intake_defect(defect, gateway)

    assert "phase=pending" in gateway.comments[900][0]["body"].splitlines()[0]
    assert known_defects.lookup_defect(defect.defect_id, gateway)["status"] == "not_found"

    receipt = known_defects.intake_defect(defect, gateway)

    assert receipt["status"] == "duplicate"
    assert "phase=final" in gateway.comments[900][0]["body"].splitlines()[0]


def test_closed_pending_entry_remains_canonical_across_registry_generations() -> None:
    gateway = FakeGateway()
    defect = _defect()
    first = gateway.create_registry_issue()
    gateway.lock_registry_issue(int(first["number"]))
    canonical = gateway.add_comment(
        int(first["number"]),
        defect.render_entry(phase="pending"),
    )
    first["state"] = "closed"
    second = gateway.create_registry_issue()
    gateway.lock_registry_issue(int(second["number"]))
    later = gateway.add_comment(
        int(second["number"]),
        defect.render_entry(phase="final"),
    )

    assert known_defects.lookup_defect(defect.defect_id, gateway)[
        "status"
    ] == "not_found"

    receipt = known_defects.intake_defect(defect, gateway)

    assert receipt["status"] == "duplicate"
    assert receipt["registry_issue"] == int(first["number"])
    assert receipt["url"] == canonical["html_url"]
    assert "phase=final" in canonical["body"].splitlines()[0]
    assert "phase=final" in later["body"].splitlines()[0]
    lookup = known_defects.lookup_defect(defect.defect_id, gateway)
    assert lookup["status"] == "deferred"
    assert lookup["registry_issue"] == int(first["number"])
    assert lookup["url"] == canonical["html_url"]


def test_failed_entry_finalize_retries_after_registry_closes() -> None:
    gateway = EntryFinalizeFailureGateway(apply_before_failure=False)
    defect = _defect()

    with pytest.raises(known_defects.KnownDefectsError, match="ambiguous entry"):
        known_defects.intake_defect(defect, gateway)

    gateway.issues[900]["state"] = "closed"
    current = gateway.create_registry_issue()
    gateway.lock_registry_issue(int(current["number"]))

    receipt = known_defects.intake_defect(defect, gateway)

    assert receipt["status"] == "duplicate"
    assert receipt["registry_issue"] == 900
    assert len(gateway.comments[900]) == 1
    assert "phase=final" in gateway.comments[900][0]["body"].splitlines()[0]
    assert gateway.comments[int(current["number"])] == []


class EntryRetryFinalizeRaceGateway(FakeGateway):
    def __init__(self) -> None:
        super().__init__()
        self.entry_updates = 0

    def update_comment(self, comment_id: int, body: str) -> dict[str, Any]:
        if body.startswith("<!-- known-defect-entry:"):
            self.entry_updates += 1
            if self.entry_updates == 1:
                raise known_defects.KnownDefectsError(
                    "entry finalization failed before apply"
                )
            updated = super().update_comment(comment_id, body)
            self.issues[900]["state"] = "closed"
            return updated
        return super().update_comment(comment_id, body)


def test_retry_entry_finalize_treats_final_patch_as_commit_point() -> None:
    gateway = EntryRetryFinalizeRaceGateway()
    defect = _defect()

    with pytest.raises(known_defects.KnownDefectsError, match="before apply"):
        known_defects.intake_defect(defect, gateway)

    receipt = known_defects.intake_defect(defect, gateway)

    assert receipt["status"] == "duplicate"
    assert len(gateway.comments[900]) == 1
    assert "phase=final" in gateway.comments[900][0]["body"].splitlines()[0]


class ConcurrentEntryFinalDuringAmbiguousPatchGateway(FakeGateway):
    def __init__(self) -> None:
        super().__init__()
        self.inject_once = True

    def update_comment(self, comment_id: int, body: str) -> dict[str, Any]:
        if (
            self.inject_once
            and body.startswith("<!-- known-defect-entry:")
            and "phase=final" in body.splitlines()[0]
        ):
            self.inject_once = False
            super().add_comment(900, body)
            raise known_defects.KnownDefectsError(
                "ambiguous entry PATCH with concurrent final"
            )
        return super().update_comment(comment_id, body)


def test_ambiguous_entry_patch_keeps_earliest_reservation_canonical() -> None:
    gateway = ConcurrentEntryFinalDuringAmbiguousPatchGateway()
    defect = _defect()

    with pytest.raises(known_defects.KnownDefectsError, match="ambiguous entry"):
        known_defects.intake_defect(defect, gateway)
    duplicate = known_defects.intake_defect(defect, gateway)

    assert duplicate["status"] == "duplicate"
    assert len(gateway.comments[900]) == 2
    assert "phase=final" in gateway.comments[900][0]["body"].splitlines()[0]
    assert known_defects.lookup_defect(defect.defect_id, gateway)["url"].endswith(
        "issuecomment-1"
    )


class RegistryCloseDuringEntryFinalizeGateway(FakeGateway):
    def __init__(self) -> None:
        super().__init__()
        self.closed_once = False

    def update_comment(self, comment_id: int, body: str) -> dict[str, Any]:
        if (
            not self.closed_once
            and body.startswith("<!-- known-defect-entry:")
            and "phase=final" in body.splitlines()[0]
        ):
            self.issues[900]["state"] = "closed"
            self.closed_once = True
        return super().update_comment(comment_id, body)


def test_registry_close_before_entry_finalize_preserves_reserved_entry() -> None:
    gateway = RegistryCloseDuringEntryFinalizeGateway()
    defect = _defect()

    receipt = known_defects.intake_defect(defect, gateway)

    assert receipt["status"] == "created"
    assert receipt["registry_issue"] == 900
    assert len(gateway.comments[900]) == 1
    assert "phase=final" in gateway.comments[900][0]["body"].splitlines()[0]
    assert known_defects.lookup_defect(defect.defect_id, gateway)[
        "status"
    ] == "deferred"


class SecondRegistryDuringFinalizeGateway(FakeGateway):
    def __init__(self, marker_type: str) -> None:
        super().__init__()
        self.marker_type = marker_type
        self.inject_once = True

    def update_comment(self, comment_id: int, body: str) -> dict[str, Any]:
        if (
            self.inject_once
            and body.startswith(f"<!-- known-defect-{self.marker_type}:")
            and "phase=final" in body.splitlines()[0]
        ):
            self.inject_once = False
            registry = super().create_registry_issue()
            super().lock_registry_issue(int(registry["number"]))
        return super().update_comment(comment_id, body)


def test_second_registry_before_entry_finalize_cannot_hide_reserved_entry() -> None:
    gateway = SecondRegistryDuringFinalizeGateway("entry")
    defect = _defect()

    receipt = known_defects.intake_defect(defect, gateway)

    assert receipt["status"] == "created"
    assert "phase=final" in gateway.comments[900][0]["body"].splitlines()[0]
    assert known_defects.lookup_defect(defect.defect_id, gateway)[
        "status"
    ] == "deferred"
    assert len(
        [
            issue
            for issue in gateway.issues.values()
            if issue.get("state") == "open"
            and known_defects.REGISTRY_LABEL
            in {label["name"] for label in issue.get("labels", [])}
        ]
    ) == 2


class RegistryDriftDuringEntryFinalizeGateway(FakeGateway):
    def __init__(self, transition: str) -> None:
        super().__init__()
        self.transition = transition
        self.transitioned = False

    def update_comment(self, comment_id: int, body: str) -> dict[str, Any]:
        if (
            not self.transitioned
            and body.startswith("<!-- known-defect-entry:")
            and "phase=final" in body.splitlines()[0]
        ):
            if self.transition == "unlock":
                self.issues[900]["locked"] = False
            elif self.transition == "body":
                self.issues[900]["body"] += "\nDrifted."
            elif self.transition == "label":
                self.issues[900]["labels"].append({"name": "agent:blocked"})
            self.transitioned = True
        return super().update_comment(comment_id, body)


@pytest.mark.parametrize(
    "transition",
    ["unlock", "body", "label"],
)
def test_registry_drift_before_entry_finalize_does_not_hide_reservation(
    transition: str,
) -> None:
    gateway = RegistryDriftDuringEntryFinalizeGateway(transition)

    receipt = known_defects.intake_defect(_defect(), gateway)

    assert receipt["status"] == "created"
    assert len(gateway.comments[900]) == 1
    assert "phase=final" in gateway.comments[900][0]["body"].splitlines()[0]
    assert known_defects.lookup_defect(_defect().defect_id, gateway)[
        "status"
    ] == "deferred"


class EntryRevocationWithoutDeleteGateway(
    RegistryDriftDuringEntryFinalizeGateway
):
    def __init__(self) -> None:
        super().__init__("body")

    def delete_comment(self, comment_id: int) -> None:
        raise known_defects.KnownDefectsError(
            f"DELETE unavailable for comment {comment_id}"
        )


def test_entry_commit_never_requires_a_post_commit_delete() -> None:
    gateway = EntryRevocationWithoutDeleteGateway()
    defect = _defect()

    receipt = known_defects.intake_defect(defect, gateway)

    assert receipt["status"] == "created"
    phases = [item["body"].splitlines()[0] for item in gateway.comments[900]]
    assert sum("phase=final" in marker for marker in phases) == 1
    assert sum("phase=revoked" in marker for marker in phases) == 0


class PostFinalizeReadFailureGateway(FakeGateway):
    def __init__(self, marker_type: str) -> None:
        super().__init__()
        self.marker_type = marker_type
        self.fail_next_get = False

    def update_comment(self, comment_id: int, body: str) -> dict[str, Any]:
        updated = super().update_comment(comment_id, body)
        if (
            body.startswith(f"<!-- known-defect-{self.marker_type}:")
            and "phase=final" in body.splitlines()[0]
        ):
            self.fail_next_get = True
        return updated

    def list_registry_issues(self, state: str) -> list[dict[str, Any]]:
        if self.fail_next_get:
            self.fail_next_get = False
            raise known_defects.KnownDefectsError(
                "indeterminate post-finalization authority read"
            )
        return super().list_registry_issues(state)


def test_entry_commit_has_no_post_finalize_authority_read() -> None:
    gateway = PostFinalizeReadFailureGateway("entry")

    receipt = known_defects.intake_defect(_defect(), gateway)

    assert receipt["status"] == "created"
    assert len(gateway.comments[900]) == 1
    assert "phase=final" in gateway.comments[900][0]["body"].splitlines()[0]


def test_promotion_requires_concrete_verify_target_on_every_ac() -> None:
    gateway = FakeGateway()
    defect = _defect()
    known_defects.intake_defect(defect, gateway)
    body = _canonical_bug_body().replace(
        "- [ ] Regression no longer reproduces.\n  Verify: `tests/governance/test_known_defects_registry.py::test_promotion_requires_concrete_verify_target_on_every_ac`",
        (
            "- [ ] Regression no longer reproduces.\n"
            "  Verify: `tests/governance/test_known_defects_registry.py::test_promotion_requires_concrete_verify_target_on_every_ac`\n"
            "- [ ] A second behavioral claim is satisfied."
        ),
    )
    gateway.issues[901] = {
        "number": 901,
        "title": "bug: require a Verify target on every criterion",
        "state": "open",
        "body": body,
        "labels": [
            {"name": "type:bug"},
            {"name": "prio:med"},
            {"name": "agent:ready"},
        ],
    }

    with pytest.raises(known_defects.KnownDefectsError, match="lack resolvable Verify"):
        known_defects.promote_defect(defect.defect_id, 901, gateway)


@pytest.mark.parametrize("invalid_target", ["manual QA", ""])
def test_promotion_rejects_mixed_resolvable_verify_markers(
    invalid_target: str,
) -> None:
    gateway = FakeGateway()
    defect = _defect()
    known_defects.intake_defect(defect, gateway)
    body = _canonical_bug_body().replace(
        "- [ ] Regression no longer reproduces.\n"
        "  Verify: `tests/governance/test_known_defects_registry.py::test_promotion_requires_concrete_verify_target_on_every_ac`",
        (
            "- [ ] Regression no longer reproduces.\n"
            "  Verify: `tests/governance/test_known_defects_registry.py::test_promotion_requires_concrete_verify_target_on_every_ac`\n"
            f"  Verify: {invalid_target}"
        ),
    )
    gateway.issues[901] = {
        "number": 901,
        "title": "bug: reject mixed verification authority",
        "state": "open",
        "body": body,
        "labels": [
            {"name": "type:bug"},
            {"name": "prio:med"},
            {"name": "agent:ready"},
        ],
    }

    with pytest.raises(
        known_defects.KnownDefectsError,
        match="lack resolvable Verify",
    ):
        known_defects.promote_defect(defect.defect_id, 901, gateway)


def test_promotion_rejects_duplicate_resolvable_verify_markers() -> None:
    gateway = FakeGateway()
    defect = _defect()
    known_defects.intake_defect(defect, gateway)
    marker = "Verify: `tests/governance/test_known_defects_registry.py::test_promotion_requires_concrete_verify_target_on_every_ac`"
    body = _canonical_bug_body().replace(marker, f"{marker}\n  {marker}")
    gateway.issues[901] = {
        "number": 901,
        "title": "bug: reject duplicate verification authority",
        "state": "open",
        "body": body,
        "labels": [
            {"name": "type:bug"},
            {"name": "prio:med"},
            {"name": "agent:ready"},
        ],
    }

    with pytest.raises(
        known_defects.KnownDefectsError,
        match="lack resolvable Verify",
    ):
        known_defects.promote_defect(defect.defect_id, 901, gateway)


@pytest.mark.parametrize(
    "path",
    [
        "tests/../../tmp/x.py",
        "tests/./x.py",
        "docs/../outside.md",
        ".codex/skills/../../outside.md",
    ],
)
def test_durable_authority_paths_reject_traversal(path: str) -> None:
    assert not known_defects.is_durable_repo_path(path)


def test_promotion_rejects_repository_escaping_verify_target() -> None:
    gateway = FakeGateway()
    defect = _defect()
    known_defects.intake_defect(defect, gateway)
    body = _canonical_bug_body().replace(
        "tests/governance/test_known_defects_registry.py::test_promotion_requires_concrete_verify_target_on_every_ac",
        "tests/../../tmp/x.py::test_x",
    )
    gateway.issues[901] = {
        "number": 901,
        "title": "bug: reject repository escaping verification",
        "state": "open",
        "body": body,
        "labels": [
            {"name": "type:bug"},
            {"name": "prio:med"},
            {"name": "agent:ready"},
        ],
    }

    with pytest.raises(known_defects.KnownDefectsError, match="resolvable Verify"):
        known_defects.promote_defect(defect.defect_id, 901, gateway)


@pytest.mark.parametrize("extra_label", ["prio:urgent", "agent:paused"])
def test_promotion_rejects_unknown_labels_on_canonical_axes(
    extra_label: str,
) -> None:
    gateway = FakeGateway()
    defect = _defect()
    known_defects.intake_defect(defect, gateway)
    gateway.issues[901] = {
        "number": 901,
        "title": "bug: reject ambiguous promotion labels",
        "state": "open",
        "body": _canonical_bug_body(),
        "labels": [
            {"name": "type:bug"},
            {"name": "prio:med"},
            {"name": "agent:ready"},
            {"name": extra_label},
        ],
    }

    expected = "priority" if extra_label.startswith("prio:") else "agent-state"
    with pytest.raises(known_defects.KnownDefectsError, match=expected):
        known_defects.promote_defect(defect.defect_id, 901, gateway)


def test_promotion_accepts_the_canonical_governance_lane_exception() -> None:
    gateway = FakeGateway()
    defect = _defect()
    known_defects.intake_defect(defect, gateway)
    gateway.issues[901] = {
        "number": 901,
        "title": "bug: repair governance behavior",
        "state": "open",
        "body": _canonical_bug_body(),
        "labels": [
            {"name": "type:bug"},
            {"name": "prio:med"},
            {"name": "agent:ready"},
            {"name": "lane:governance"},
        ],
    }

    promoted = known_defects.promote_defect(defect.defect_id, 901, gateway)
    duplicate = known_defects.promote_defect(defect.defect_id, 901, gateway)

    assert promoted["status"] == "promoted"
    assert duplicate["status"] == "promotion_duplicate"


class ConflictingPromotionGateway(FakeGateway):
    def add_comment(self, issue_number: int, body: str) -> dict[str, Any]:
        comment = super().add_comment(issue_number, body)
        if body.startswith("<!-- known-defect-promotion:"):
            defect_id = known_defects.PROMOTION_MARKER_RE.fullmatch(
                body.splitlines()[0]
            ).group(1)
            authority_sha256 = known_defects.PROMOTION_MARKER_RE.fullmatch(
                body.splitlines()[0]
            ).group(3)
            super().add_comment(
                issue_number,
                "\n".join(
                    (
                        known_defects.PROMOTION_MARKER_TEMPLATE.format(
                            defect_id=defect_id,
                            issue_number=902,
                            authority_sha256=authority_sha256,
                            phase="final",
                        ),
                        (
                            f"Promotion receipt: {defect_id} is now tracked for "
                            "implementation by #902."
                        ),
                        f"Validated target snapshot: sha256:{authority_sha256}.",
                        (
                            "The bounded bug Issue owns scope, acceptance criteria, "
                            "Verify targets, and execution state."
                        ),
                    )
                ),
            )
        return comment


def test_earliest_promotion_reservation_wins_a_concurrent_conflict() -> None:
    gateway = ConflictingPromotionGateway()
    defect = _defect()
    intake = known_defects.intake_defect(defect, gateway)
    gateway.issues[901] = {
        "number": 901,
        "title": "bug: prevent conflicting promotion authority",
        "state": "open",
        "body": _canonical_bug_body(),
        "labels": [
            {"name": "type:bug"},
            {"name": "prio:med"},
            {"name": "agent:ready"},
        ],
    }
    gateway.issues[902] = {
        **gateway.issues[901],
        "number": 902,
    }

    promoted = known_defects.promote_defect(defect.defect_id, 901, gateway)

    assert promoted["status"] == "promoted"
    receipt = known_defects.lookup_defect(defect.defect_id, gateway)
    assert receipt["status"] == "promoted"
    assert receipt["promotion_issue"] == 901
    assert receipt["registry_issue"] == intake["registry_issue"]


class PromotionTargetRaceGateway(FakeGateway):
    def __init__(self, transition: str) -> None:
        super().__init__()
        self.transition = transition
        self.transitioned = False

    def add_comment(self, issue_number: int, body: str) -> dict[str, Any]:
        if (
            body.startswith("<!-- known-defect-promotion:")
            and not self.transitioned
        ):
            target = self.issues[901]
            if self.transition == "body":
                target["body"] += "\n\nDrifted outside the validated contract."
            elif self.transition == "label":
                target["labels"].append({"name": "maintenance"})
            elif self.transition == "closed":
                target["state"] = "closed"
                target["labels"] = [
                    {"name": "type:bug"},
                    {"name": "prio:med"},
                ]
            elif self.transition == "claimed":
                target["labels"] = [
                    {"name": "type:bug"},
                    {"name": "prio:med"},
                ]
            self.transitioned = True
        return super().add_comment(issue_number, body)


class RegistryDriftDuringPromotionTargetReadGateway(FakeGateway):
    def __init__(self, transition: str) -> None:
        super().__init__()
        self.transition = transition
        self.transitioned = False

    def get_issue(self, number: int) -> dict[str, Any]:
        issue = super().get_issue(number)
        if number == 901 and not self.transitioned:
            self.transitioned = True
            if self.transition == "closed":
                self.issues[900]["state"] = "closed"
            else:
                competing = super().create_registry_issue()
                super().lock_registry_issue(int(competing["number"]))
        return issue


@pytest.mark.parametrize(
    ("transition", "error"),
    [
        ("closed", "expected one open registry"),
        ("competing", "multiple open registries"),
    ],
)
def test_promotion_rechecks_registry_after_target_read_before_reservation(
    transition: str,
    error: str,
) -> None:
    gateway = RegistryDriftDuringPromotionTargetReadGateway(transition)
    defect = _defect()
    intake = known_defects.intake_defect(defect, gateway)
    gateway.issues[901] = {
        "number": 901,
        "title": "bug: recheck registry before promotion reservation",
        "state": "open",
        "body": _canonical_bug_body(),
        "labels": [
            {"name": "type:bug"},
            {"name": "prio:med"},
            {"name": "agent:ready"},
        ],
    }

    with pytest.raises(known_defects.KnownDefectsError, match=error):
        known_defects.promote_defect(defect.defect_id, 901, gateway)

    promotion_comments = [
        item
        for item in gateway.comments[intake["registry_issue"]]
        if item["body"].startswith("<!-- known-defect-promotion:")
    ]
    assert promotion_comments == []


@pytest.mark.parametrize("transition", ["body", "label"])
def test_promotion_receipt_is_an_immutable_validation_snapshot(
    transition: str,
) -> None:
    gateway = PromotionTargetRaceGateway(transition)
    defect = _defect()
    intake = known_defects.intake_defect(defect, gateway)
    gateway.issues[901] = {
        "number": 901,
        "title": "bug: guard promotion authority",
        "state": "open",
        "body": _canonical_bug_body(),
        "labels": [
            {"name": "type:bug"},
            {"name": "prio:med"},
            {"name": "agent:ready"},
        ],
    }

    receipt = known_defects.promote_defect(defect.defect_id, 901, gateway)

    assert receipt["status"] == "promoted"
    assert len(gateway.comments[intake["registry_issue"]]) == 2
    assert known_defects.lookup_defect(defect.defect_id, gateway)[
        "promotion_issue"
    ] == 901


def test_promotion_snapshot_digest_binds_lifecycle_and_agent_state() -> None:
    issue = {
        "title": "bug: bind snapshot authority",
        "state": "open",
        "body": _canonical_bug_body(),
        "labels": [
            {"name": "type:bug"},
            {"name": "prio:med"},
            {"name": "agent:ready"},
        ],
    }
    baseline = known_defects._promotion_target_authority_sha256(issue)
    claimed = {
        **issue,
        "labels": [
            {"name": "type:bug"},
            {"name": "prio:med"},
            {"name": "agent:blocked"},
        ],
    }
    closed = {**issue, "state": "closed"}

    assert known_defects._promotion_target_authority_sha256(claimed) != baseline
    assert known_defects._promotion_target_authority_sha256(closed) != baseline


@pytest.mark.parametrize("transition", ["closed", "claimed"])
def test_first_promotion_accepts_normal_target_lifecycle_transition(
    transition: str,
) -> None:
    gateway = PromotionTargetRaceGateway(transition)
    defect = _defect()
    known_defects.intake_defect(defect, gateway)
    gateway.issues[901] = {
        "number": 901,
        "title": "bug: guard promotion authority",
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

    assert promoted["status"] == "promoted"
    assert duplicate["status"] == "promotion_duplicate"


class ExistingPromotionReadFailureGateway(FakeGateway):
    def __init__(self) -> None:
        super().__init__()
        self.fail_target_read_once = False

    def get_issue(self, number: int) -> dict[str, Any]:
        if number == 901 and self.fail_target_read_once:
            self.fail_target_read_once = False
            raise known_defects.KnownDefectsError(
                "indeterminate existing-promotion target read"
            )
        return super().get_issue(number)


def test_existing_promotion_read_failure_preserves_committed_authority() -> None:
    gateway = ExistingPromotionReadFailureGateway()
    defect = _defect()
    known_defects.intake_defect(defect, gateway)
    gateway.issues[901] = {
        "number": 901,
        "title": "bug: preserve committed promotion authority",
        "state": "open",
        "body": _canonical_bug_body(),
        "labels": [
            {"name": "type:bug"},
            {"name": "prio:med"},
            {"name": "agent:ready"},
        ],
    }
    known_defects.promote_defect(defect.defect_id, 901, gateway)
    committed_marker = gateway.comments[900][-1]["body"]
    gateway.fail_target_read_once = True

    duplicate = known_defects.promote_defect(defect.defect_id, 901, gateway)

    assert duplicate["status"] == "promotion_duplicate"
    assert gateway.comments[900][-1]["body"] == committed_marker
    assert known_defects.lookup_defect(defect.defect_id, gateway)[
        "status"
    ] == "promoted"


def test_closed_history_entry_promotes_through_current_open_registry() -> None:
    gateway = FakeGateway()
    defect = _defect()
    intake = known_defects.intake_defect(defect, gateway)
    gateway.issues[intake["registry_issue"]]["state"] = "closed"
    gateway.issues[902] = {
        "number": 902,
        "title": "bug: promote a closed-history defect",
        "state": "open",
        "body": _canonical_bug_body(),
        "labels": [
            {"name": "type:bug"},
            {"name": "prio:med"},
            {"name": "agent:ready"},
        ],
    }

    promoted = known_defects.promote_defect(defect.defect_id, 902, gateway)
    duplicate = known_defects.promote_defect(defect.defect_id, 902, gateway)
    lookup = known_defects.lookup_defect(defect.defect_id, gateway)

    assert promoted["status"] == "promoted"
    assert promoted["registry_issue"] == 901
    assert duplicate["status"] == "promotion_duplicate"
    assert duplicate["registry_issue"] == 901
    assert lookup["status"] == "promoted"
    assert len(gateway.comments[900]) == 1
    assert len(gateway.comments[901]) == 1


def test_old_final_authority_removes_current_pending_before_reconciliation() -> None:
    gateway = FakeGateway()
    defect = _defect()
    known_defects.intake_defect(defect, gateway)
    gateway.issues[902] = {
        "number": 902,
        "title": "bug: preserve old final promotion authority",
        "state": "open",
        "body": _canonical_bug_body(),
        "labels": [
            {"name": "type:bug"},
            {"name": "prio:med"},
            {"name": "agent:ready"},
        ],
    }
    first = known_defects.promote_defect(defect.defect_id, 902, gateway)
    gateway.issues[900]["state"] = "closed"
    current = gateway.create_registry_issue()
    gateway.lock_registry_issue(int(current["number"]))
    final_body = gateway.comments[900][-1]["body"]
    gateway.add_comment(
        int(current["number"]),
        final_body.replace(" phase=final -->", " phase=pending -->", 1),
    )

    duplicate = known_defects.promote_defect(defect.defect_id, 902, gateway)

    assert first["status"] == "promoted"
    assert duplicate["status"] == "promotion_duplicate"
    assert gateway.comments[int(current["number"])] == []
    promotion_phases = [
        item["body"].splitlines()[0]
        for item in gateway.comments[900]
        if item["body"].startswith("<!-- known-defect-promotion:")
    ]
    assert promotion_phases == [
        known_defects.PROMOTION_MARKER_TEMPLATE.format(
            defect_id=defect.defect_id,
            issue_number=902,
            authority_sha256=known_defects._promotion_target_authority_sha256(
                gateway.issues[902]
            ),
            phase="final",
        )
    ]


class CrossRegistryConflictDuringFinalPatchGateway(FakeGateway):
    def __init__(self) -> None:
        super().__init__()
        self.inject_once = True

    def update_comment(self, comment_id: int, body: str) -> dict[str, Any]:
        if (
            self.inject_once
            and body.startswith("<!-- known-defect-promotion:")
            and "phase=final" in body.splitlines()[0]
        ):
            self.inject_once = False
            marker = known_defects.PROMOTION_MARKER_RE.fullmatch(
                body.splitlines()[0]
            )
            assert marker is not None
            defect_id, _issue, authority_sha256, _phase = marker.groups()
            conflict_body = "\n".join(
                (
                    known_defects.PROMOTION_MARKER_TEMPLATE.format(
                        defect_id=defect_id,
                        issue_number=903,
                        authority_sha256=authority_sha256,
                        phase="final",
                    ),
                    (
                        f"Promotion receipt: {defect_id} is now tracked for "
                        "implementation by #903."
                    ),
                    f"Validated target snapshot: sha256:{authority_sha256}.",
                    (
                        "The bounded bug Issue owns scope, acceptance criteria, "
                        "Verify targets, and execution state."
                    ),
                )
            )
            super().add_comment(900, conflict_body)
        return super().update_comment(comment_id, body)


def test_cross_registry_conflict_cannot_preempt_earlier_reservation() -> None:
    gateway = CrossRegistryConflictDuringFinalPatchGateway()
    defect = _defect()
    known_defects.intake_defect(defect, gateway)
    gateway.issues[900]["state"] = "closed"
    target = {
        "title": "bug: detect a cross-registry promotion conflict",
        "state": "open",
        "body": _canonical_bug_body(),
        "labels": [
            {"name": "type:bug"},
            {"name": "prio:med"},
            {"name": "agent:ready"},
        ],
    }
    gateway.issues[902] = {"number": 902, **target}
    gateway.issues[903] = {"number": 903, **target}

    receipt = known_defects.promote_defect(defect.defect_id, 902, gateway)

    assert receipt["status"] == "promoted"
    lookup = known_defects.lookup_defect(defect.defect_id, gateway)
    assert lookup["status"] == "promoted"
    assert lookup["promotion_issue"] == 902


class PromotionPostWriteReadFailureGateway(FakeGateway):
    def __init__(self) -> None:
        super().__init__()
        self.fail_next_get = False

    def add_comment(self, issue_number: int, body: str) -> dict[str, Any]:
        comment = super().add_comment(issue_number, body)
        if body.startswith("<!-- known-defect-promotion:"):
            self.fail_next_get = True
        return comment

    def get_issue(self, number: int) -> dict[str, Any]:
        if self.fail_next_get:
            self.fail_next_get = False
            raise known_defects.KnownDefectsError(
                "indeterminate promotion post-write read"
            )
        return super().get_issue(number)


def test_promotion_reservation_needs_no_post_write_target_read() -> None:
    gateway = PromotionPostWriteReadFailureGateway()
    defect = _defect()
    intake = known_defects.intake_defect(defect, gateway)
    gateway.issues[901] = {
        "number": 901,
        "title": "bug: guard promotion authority",
        "state": "open",
        "body": _canonical_bug_body(),
        "labels": [
            {"name": "type:bug"},
            {"name": "prio:med"},
            {"name": "agent:ready"},
        ],
    }

    receipt = known_defects.promote_defect(defect.defect_id, 901, gateway)

    assert receipt["status"] == "promoted"
    assert len(gateway.comments[intake["registry_issue"]]) == 2


class AmbiguousPromotionCreateGateway(FakeGateway):
    def __init__(self, *, close_registry: bool = True) -> None:
        super().__init__()
        self.ambiguous_once = True
        self.close_registry = close_registry

    def add_comment(self, issue_number: int, body: str) -> dict[str, Any]:
        comment = super().add_comment(issue_number, body)
        if body.startswith("<!-- known-defect-promotion:") and self.ambiguous_once:
            self.ambiguous_once = False
            if self.close_registry:
                self.issues[issue_number]["state"] = "closed"
            raise known_defects.KnownDefectsError(
                "ambiguous promotion comment-create response"
            )
        return comment


def test_ambiguous_promotion_reservation_survives_later_registry_close() -> None:
    gateway = AmbiguousPromotionCreateGateway()
    defect = _defect()
    intake = known_defects.intake_defect(defect, gateway)
    gateway.issues[901] = {
        "number": 901,
        "title": "bug: guard ambiguous promotion creation",
        "state": "open",
        "body": _canonical_bug_body(),
        "labels": [
            {"name": "type:bug"},
            {"name": "prio:med"},
            {"name": "agent:ready"},
        ],
    }

    promoted = known_defects.promote_defect(defect.defect_id, 901, gateway)

    assert promoted["status"] == "promoted"
    assert promoted["registry_issue"] == intake["registry_issue"]
    assert "phase=final" in gateway.comments[900][-1]["body"].splitlines()[0]


def test_ambiguous_promotion_create_response_completes_from_open_inventory() -> None:
    gateway = AmbiguousPromotionCreateGateway(close_registry=False)
    defect = _defect()
    known_defects.intake_defect(defect, gateway)
    gateway.issues[901] = {
        "number": 901,
        "title": "bug: guard ambiguous promotion creation",
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

    assert promoted["status"] == "promoted"
    assert duplicate["status"] == "promotion_duplicate"


class CrossGenerationFinalDuringAmbiguousPromotionCreateGateway(FakeGateway):
    def __init__(self) -> None:
        super().__init__()
        self.inject_once = True

    def add_comment(self, issue_number: int, body: str) -> dict[str, Any]:
        comment = super().add_comment(issue_number, body)
        if (
            self.inject_once
            and body.startswith("<!-- known-defect-promotion:")
        ):
            self.inject_once = False
            marker = known_defects.PROMOTION_MARKER_RE.fullmatch(
                body.splitlines()[0]
            )
            assert marker is not None
            defect_id, _issue, authority_sha256, _phase = marker.groups()
            final_body = "\n".join(
                (
                    known_defects.PROMOTION_MARKER_TEMPLATE.format(
                        defect_id=defect_id,
                        issue_number=903,
                        authority_sha256=authority_sha256,
                        phase="final",
                    ),
                    (
                        f"Promotion receipt: {defect_id} is now tracked for "
                        "implementation by #903."
                    ),
                    f"Validated target snapshot: sha256:{authority_sha256}.",
                    (
                        "The bounded bug Issue owns scope, acceptance criteria, "
                        "Verify targets, and execution state."
                    ),
                )
            )
            super().add_comment(900, final_body)
            raise known_defects.KnownDefectsError(
                "ambiguous promotion comment-create response"
            )
        return comment


def test_ambiguous_promotion_uses_earliest_cross_generation_reservation() -> None:
    gateway = CrossGenerationFinalDuringAmbiguousPromotionCreateGateway()
    defect = _defect()
    known_defects.intake_defect(defect, gateway)
    gateway.issues[900]["state"] = "closed"
    current = gateway.create_registry_issue()
    gateway.lock_registry_issue(int(current["number"]))
    target = {
        "title": "bug: scan all promotion generations",
        "state": "open",
        "body": _canonical_bug_body(),
        "labels": [
            {"name": "type:bug"},
            {"name": "prio:med"},
            {"name": "agent:ready"},
        ],
    }
    gateway.issues[902] = {"number": 902, **target}
    gateway.issues[903] = {"number": 903, **target}

    promoted = known_defects.promote_defect(defect.defect_id, 902, gateway)

    assert promoted["status"] == "promoted"
    assert known_defects.lookup_defect(defect.defect_id, gateway)[
        "promotion_issue"
    ] == 902
    assert not any(
        "phase=pending" in item["body"].splitlines()[0]
        for item in gateway.comments[901]
    )


class PromotionFinalizeFailureGateway(FakeGateway):
    def __init__(self, *, apply_before_failure: bool) -> None:
        super().__init__()
        self.apply_before_failure = apply_before_failure
        self.fail_promotion_update_once = True

    def update_comment(self, comment_id: int, body: str) -> dict[str, Any]:
        if (
            self.fail_promotion_update_once
            and body.startswith("<!-- known-defect-promotion:")
        ):
            self.fail_promotion_update_once = False
            if self.apply_before_failure:
                super().update_comment(comment_id, body)
            raise known_defects.KnownDefectsError(
                "ambiguous promotion comment-update response"
            )
        return super().update_comment(comment_id, body)


@pytest.mark.parametrize("apply_before_failure", [False, True])
def test_ambiguous_promotion_finalize_is_retry_safe(
    apply_before_failure: bool,
) -> None:
    gateway = PromotionFinalizeFailureGateway(
        apply_before_failure=apply_before_failure
    )
    defect = _defect()
    known_defects.intake_defect(defect, gateway)
    gateway.issues[901] = {
        "number": 901,
        "title": "bug: make promotion finalization retry safe",
        "state": "open",
        "body": _canonical_bug_body(),
        "labels": [
            {"name": "type:bug"},
            {"name": "prio:med"},
            {"name": "agent:ready"},
        ],
    }

    if apply_before_failure:
        promoted = known_defects.promote_defect(defect.defect_id, 901, gateway)
        assert promoted["status"] == "promoted"
    else:
        with pytest.raises(
            known_defects.KnownDefectsError,
            match="ambiguous promotion",
        ):
            known_defects.promote_defect(defect.defect_id, 901, gateway)
        marker = gateway.comments[900][-1]["body"].splitlines()[0]
        assert "phase=pending" in marker
        assert known_defects.lookup_defect(defect.defect_id, gateway)[
            "status"
        ] == "deferred"

    duplicate = known_defects.promote_defect(defect.defect_id, 901, gateway)

    assert duplicate["status"] == "promotion_duplicate"
    assert "phase=final" in gateway.comments[900][-1]["body"].splitlines()[0]


class PromotionRetryFinalizeRaceGateway(FakeGateway):
    def __init__(self) -> None:
        super().__init__()
        self.promotion_updates = 0

    def update_comment(self, comment_id: int, body: str) -> dict[str, Any]:
        if body.startswith("<!-- known-defect-promotion:"):
            self.promotion_updates += 1
            if self.promotion_updates == 1:
                raise known_defects.KnownDefectsError(
                    "promotion finalization failed before apply"
                )
            updated = super().update_comment(comment_id, body)
            self.issues[900]["state"] = "closed"
            return updated
        return super().update_comment(comment_id, body)


def test_retry_promotion_finalize_treats_final_patch_as_commit_point() -> None:
    gateway = PromotionRetryFinalizeRaceGateway()
    defect = _defect()
    intake = known_defects.intake_defect(defect, gateway)
    gateway.issues[901] = {
        "number": 901,
        "title": "bug: fence retry promotion finalization",
        "state": "open",
        "body": _canonical_bug_body(),
        "labels": [
            {"name": "type:bug"},
            {"name": "prio:med"},
            {"name": "agent:ready"},
        ],
    }

    with pytest.raises(known_defects.KnownDefectsError, match="before apply"):
        known_defects.promote_defect(defect.defect_id, 901, gateway)

    receipt = known_defects.promote_defect(defect.defect_id, 901, gateway)

    assert receipt["status"] == "promotion_duplicate"
    assert len(gateway.comments[intake["registry_issue"]]) == 2
    assert "phase=final" in gateway.comments[900][-1]["body"].splitlines()[0]


class ConcurrentPromotionFinalDuringAmbiguousPatchGateway(FakeGateway):
    def __init__(self) -> None:
        super().__init__()
        self.inject_once = True

    def update_comment(self, comment_id: int, body: str) -> dict[str, Any]:
        if (
            self.inject_once
            and body.startswith("<!-- known-defect-promotion:")
            and "phase=final" in body.splitlines()[0]
        ):
            self.inject_once = False
            super().add_comment(900, body)
            raise known_defects.KnownDefectsError(
                "ambiguous promotion PATCH with concurrent final"
            )
        return super().update_comment(comment_id, body)


def test_ambiguous_promotion_patch_keeps_earliest_reservation_canonical() -> None:
    gateway = ConcurrentPromotionFinalDuringAmbiguousPatchGateway()
    defect = _defect()
    known_defects.intake_defect(defect, gateway)
    gateway.issues[901] = {
        "number": 901,
        "title": "bug: bind promotion finalization to its comment",
        "state": "open",
        "body": _canonical_bug_body(),
        "labels": [
            {"name": "type:bug"},
            {"name": "prio:med"},
            {"name": "agent:ready"},
        ],
    }

    with pytest.raises(known_defects.KnownDefectsError, match="ambiguous promotion"):
        known_defects.promote_defect(defect.defect_id, 901, gateway)

    receipt = known_defects.promote_defect(defect.defect_id, 901, gateway)

    assert receipt["status"] == "promotion_duplicate"
    promotion_comments = [
        item
        for item in gateway.comments[900]
        if item["body"].startswith("<!-- known-defect-promotion:")
    ]
    assert len(promotion_comments) == 2
    assert "phase=final" in promotion_comments[0]["body"].splitlines()[0]
    assert known_defects._single_committed_promotion(
        gateway,
        defect.defect_id,
    )[3]["id"] == promotion_comments[0]["id"]


class AuthorityDriftDuringPromotionFinalizeGateway(FakeGateway):
    def __init__(self, transition: str) -> None:
        super().__init__()
        self.transition = transition
        self.transitioned = False

    def update_comment(self, comment_id: int, body: str) -> dict[str, Any]:
        if (
            not self.transitioned
            and body.startswith("<!-- known-defect-promotion:")
            and "phase=final" in body.splitlines()[0]
        ):
            if self.transition == "target_body":
                self.issues[901]["body"] += "\n\nDrifted during finalization."
            elif self.transition == "registry_close":
                self.issues[900]["state"] = "closed"
            self.transitioned = True
        return super().update_comment(comment_id, body)


@pytest.mark.parametrize(
    "transition",
    ["target_body", "registry_close"],
)
def test_target_or_registry_drift_before_finalize_cannot_rewrite_snapshot(
    transition: str,
) -> None:
    gateway = AuthorityDriftDuringPromotionFinalizeGateway(transition)
    defect = _defect()
    intake = known_defects.intake_defect(defect, gateway)
    gateway.issues[901] = {
        "number": 901,
        "title": "bug: fence promotion finalization",
        "state": "open",
        "body": _canonical_bug_body(),
        "labels": [
            {"name": "type:bug"},
            {"name": "prio:med"},
            {"name": "agent:ready"},
        ],
    }

    receipt = known_defects.promote_defect(defect.defect_id, 901, gateway)

    assert receipt["status"] == "promoted"
    assert len(gateway.comments[intake["registry_issue"]]) == 2
    assert "phase=final" in gateway.comments[900][-1]["body"].splitlines()[0]
    lookup = known_defects.lookup_defect(defect.defect_id, gateway)
    assert lookup["status"] == "promoted"


def test_second_registry_ordered_after_promotion_commit_is_later_drift() -> None:
    gateway = SecondRegistryDuringFinalizeGateway("promotion")
    defect = _defect()
    known_defects.intake_defect(defect, gateway)
    gateway.issues[901] = {
        "number": 901,
        "title": "bug: reject a late second promotion registry",
        "state": "open",
        "body": _canonical_bug_body(),
        "labels": [
            {"name": "type:bug"},
            {"name": "prio:med"},
            {"name": "agent:ready"},
        ],
    }

    receipt = known_defects.promote_defect(defect.defect_id, 901, gateway)

    assert receipt["status"] == "promoted"
    assert "phase=final" in gateway.comments[900][-1]["body"].splitlines()[0]


class PromotionRevocationWithoutDeleteGateway(
    AuthorityDriftDuringPromotionFinalizeGateway
):
    def __init__(self) -> None:
        super().__init__("target_body")

    def delete_comment(self, comment_id: int) -> None:
        raise known_defects.KnownDefectsError(
            f"DELETE unavailable for comment {comment_id}"
        )


def test_promotion_commit_never_requires_a_post_commit_delete() -> None:
    gateway = PromotionRevocationWithoutDeleteGateway()
    defect = _defect()
    known_defects.intake_defect(defect, gateway)
    gateway.issues[901] = {
        "number": 901,
        "title": "bug: revoke invalid promotion authority",
        "state": "open",
        "body": _canonical_bug_body(),
        "labels": [
            {"name": "type:bug"},
            {"name": "prio:med"},
            {"name": "agent:ready"},
        ],
    }

    receipt = known_defects.promote_defect(defect.defect_id, 901, gateway)

    assert receipt["status"] == "promoted"
    promotion_markers = [
        item["body"].splitlines()[0]
        for item in gateway.comments[900]
        if item["body"].startswith("<!-- known-defect-promotion:")
    ]
    assert sum("phase=final" in marker for marker in promotion_markers) == 1
    assert sum("phase=revoked" in marker for marker in promotion_markers) == 0


def test_promotion_commit_has_no_post_finalize_authority_read() -> None:
    gateway = PostFinalizeReadFailureGateway("promotion")
    defect = _defect()
    intake = known_defects.intake_defect(defect, gateway)
    gateway.issues[901] = {
        "number": 901,
        "title": "bug: fence promotion finalization reads",
        "state": "open",
        "body": _canonical_bug_body(),
        "labels": [
            {"name": "type:bug"},
            {"name": "prio:med"},
            {"name": "agent:ready"},
        ],
    }

    receipt = known_defects.promote_defect(defect.defect_id, 901, gateway)

    assert receipt["status"] == "promoted"
    assert len(gateway.comments[intake["registry_issue"]]) == 2
    assert "phase=final" in gateway.comments[900][-1]["body"].splitlines()[0]


def test_later_duplicate_promotion_markers_cannot_preempt_canonical_link() -> None:
    gateway = FakeGateway()
    defect = _defect()
    known_defects.intake_defect(defect, gateway)
    gateway.issues[901] = {
        "number": 901,
        "title": "bug: reject duplicate promotion authority",
        "state": "open",
        "body": _canonical_bug_body(),
        "labels": [
            {"name": "type:bug"},
            {"name": "prio:med"},
            {"name": "agent:ready"},
        ],
    }
    known_defects.promote_defect(defect.defect_id, 901, gateway)
    promotion = gateway.comments[900][-1]
    gateway.add_comment(900, promotion["body"])

    gateway.issues[901]["body"] += "\n\nLater implementation detail."
    duplicate = known_defects.promote_defect(defect.defect_id, 901, gateway)
    receipt = known_defects.lookup_defect(defect.defect_id, gateway)

    assert duplicate["status"] == "promotion_duplicate"
    assert receipt["status"] == "promoted"
    assert receipt["promotion_issue"] == 901


def test_unrelated_prose_cannot_make_placeholder_authority_concrete() -> None:
    gateway = FakeGateway()
    defect = _defect()
    known_defects.intake_defect(defect, gateway)
    body = (
        _canonical_bug_body()
        .replace(
            "- `.codex/skills/bug-to-issue/SKILL.md :: Promotion`",
            "Unrelated prose.\n\n- `<path> :: <anchor>`",
        )
        .replace(
            "- `.codex/skills/_shared/ISSUE_CONTRACT.md`",
            "Unrelated prose.\n\n- `<path>`",
        )
        .replace(
            "Verify: `tests/governance/test_known_defects_registry.py::test_promotion_requires_concrete_verify_target_on_every_ac`",
            "Verify: runtime receipt: later",
        )
    )
    gateway.issues[901] = {
        "number": 901,
        "title": "bug: reject placeholder promotion authority",
        "state": "open",
        "body": body,
        "labels": [
            {"name": "type:bug"},
            {"name": "prio:med"},
            {"name": "agent:ready"},
        ],
    }

    with pytest.raises(known_defects.KnownDefectsError, match="Source Anchors"):
        known_defects.promote_defect(defect.defect_id, 901, gateway)


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        (
            "- `.codex/skills/bug-to-issue/SKILL.md :: Promotion`",
            "- `TBD :: later`",
            "Source Anchors",
        ),
        (
            "- `.codex/skills/_shared/ISSUE_CONTRACT.md`",
            "- `later`",
            "Source Docs",
        ),
        (
            "Verify: `tests/governance/test_known_defects_registry.py::test_promotion_requires_concrete_verify_target_on_every_ac`",
            "Verify: doc writeback at `docs/later :: later`",
            "resolvable Verify",
        ),
        (
            "Verify: `tests/governance/test_known_defects_registry.py::test_promotion_requires_concrete_verify_target_on_every_ac`",
            "Verify: runtime receipt: later",
            "resolvable Verify",
        ),
        (
            "Verify: `tests/governance/test_known_defects_registry.py::test_promotion_requires_concrete_verify_target_on_every_ac`",
            "Verify: runtime receipt: later.v1",
            "resolvable Verify",
        ),
    ],
)
def test_promotion_rejects_vague_authority_shapes(
    old: str,
    new: str,
    expected: str,
) -> None:
    gateway = FakeGateway()
    defect = _defect()
    known_defects.intake_defect(defect, gateway)
    gateway.issues[901] = {
        "number": 901,
        "title": "bug: reject vague promotion authority",
        "state": "open",
        "body": _canonical_bug_body().replace(old, new),
        "labels": [
            {"name": "type:bug"},
            {"name": "prio:med"},
            {"name": "agent:ready"},
        ],
    }

    with pytest.raises(known_defects.KnownDefectsError, match=expected):
        known_defects.promote_defect(defect.defect_id, 901, gateway)


@pytest.mark.parametrize(
    "source_anchor",
    [
        "TBD",
        "docs/../STATUS.md :: Delivery status",
        "./docs/STATUS.md :: Delivery status",
        "docs//STATUS.md :: Delivery status",
        "<path> :: <anchor>",
        "docs/later.md :: Delivery status",
        "docs/STATUS.md :: Delivery later",
        "docs/later.md :: later",
    ],
)
def test_promotion_rejects_noncanonical_source_anchor_parity_cases(
    source_anchor: str,
) -> None:
    gateway = FakeGateway()
    defect = _defect()
    known_defects.intake_defect(defect, gateway)
    gateway.issues[901] = {
        "number": 901,
        "title": "bug: reject noncanonical source authority",
        "state": "open",
        "body": _canonical_bug_body().replace(
            "- `.codex/skills/bug-to-issue/SKILL.md :: Promotion`",
            f"- `{source_anchor}`",
        ),
        "labels": [
            {"name": "type:bug"},
            {"name": "prio:med"},
            {"name": "agent:ready"},
        ],
    }

    with pytest.raises(
        known_defects.KnownDefectsError,
        match="Source Anchors|placeholder",
    ):
        known_defects.promote_defect(defect.defect_id, 901, gateway)


@pytest.mark.parametrize(
    "verify_target",
    [
        "`tests/../x.py::test_x`",
        "doc writeback at `docs/../STATUS.md :: Delivery status`",
        "doc writeback at `./docs/STATUS.md :: Delivery status`",
        "doc writeback at `<path> :: <anchor>`",
        "doc writeback at `docs/STATUS.md :: Delivery later`",
        (
            "`doc writeback at "
            "`docs/STATUS.md :: Delivery status``"
        ),
        "roadmap diff: `docs//ROADMAP.md :: DDO-03`",
        "runtime receipt: later",
        "runtime receipt: later.v1",
        "runtime receipt: delivery_receipt",
    ],
)
def test_promotion_rejects_unresolvable_verify_target_parity_cases(
    verify_target: str,
) -> None:
    gateway = FakeGateway()
    defect = _defect()
    known_defects.intake_defect(defect, gateway)
    gateway.issues[901] = {
        "number": 901,
        "title": "bug: reject unresolvable verification authority",
        "state": "open",
        "body": _canonical_bug_body().replace(
            "Verify: `tests/governance/test_known_defects_registry.py::test_promotion_requires_concrete_verify_target_on_every_ac`",
            f"Verify: {verify_target}",
        ),
        "labels": [
            {"name": "type:bug"},
            {"name": "prio:med"},
            {"name": "agent:ready"},
        ],
    }

    with pytest.raises(
        known_defects.KnownDefectsError,
        match="concrete Verify|resolvable Verify",
    ):
        known_defects.promote_defect(defect.defect_id, 901, gateway)


@pytest.mark.parametrize(
    "verify_target",
    [
        "doc writeback at `docs/STATUS.md :: Delivery status`",
        "roadmap diff: `docs/ROADMAP.md :: DDO-03`",
        "runtime receipt: delivery_receipt.v1",
    ],
)
def test_promotion_accepts_canonical_non_test_verify_target_parity_cases(
    verify_target: str,
) -> None:
    gateway = FakeGateway()
    defect = _defect()
    intake = known_defects.intake_defect(defect, gateway)
    gateway.issues[901] = {
        "number": 901,
        "title": "bug: accept resolvable verification authority",
        "state": "open",
        "body": _canonical_bug_body().replace(
            "Verify: `tests/governance/test_known_defects_registry.py::test_promotion_requires_concrete_verify_target_on_every_ac`",
            f"Verify: {verify_target}",
        ),
        "labels": [
            {"name": "type:bug"},
            {"name": "prio:med"},
            {"name": "agent:ready"},
        ],
    }

    receipt = known_defects.promote_defect(
        defect.defect_id,
        901,
        gateway,
    )

    assert receipt["status"] == "promoted"
    assert receipt["registry_issue"] == intake["registry_issue"]


def test_rest_gateway_fails_closed_on_transport_and_non_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway = known_defects.GhRegistryGateway("RasmusTho/agentic-pkm-mvp")

    def transport_failure(*_args: Any, **_kwargs: Any) -> Any:
        return type(
            "Completed",
            (),
            {"returncode": 1, "stdout": "", "stderr": "network down"},
        )()

    monkeypatch.setattr(known_defects.subprocess, "run", transport_failure)
    with pytest.raises(known_defects.KnownDefectsError, match="network down"):
        gateway.get_issue(1)

    def invalid_json(*_args: Any, **_kwargs: Any) -> Any:
        return type(
            "Completed",
            (),
            {"returncode": 0, "stdout": "not-json", "stderr": ""},
        )()

    monkeypatch.setattr(known_defects.subprocess, "run", invalid_json)
    with pytest.raises(known_defects.KnownDefectsError, match="invalid JSON"):
        gateway.get_issue(1)


def test_rest_pagination_bound_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    gateway = known_defects.GhRegistryGateway("RasmusTho/agentic-pkm-mvp")
    monkeypatch.setattr(
        gateway,
        "_request",
        lambda *_args, **_kwargs: [{"number": number} for number in range(100)],
    )

    with pytest.raises(known_defects.KnownDefectsError, match="pagination bound"):
        gateway._list_paginated("repos/RasmusTho/agentic-pkm-mvp/issues")


def test_rest_selector_discovery_is_cached_before_label_loss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway = known_defects.GhRegistryGateway("RasmusTho/agentic-pkm-mvp")
    label_present = True
    labeled = {
        "number": 900,
        "title": known_defects.REGISTRY_TITLE,
        "state": "open",
        "locked": True,
        "body": known_defects.render_registry_body(),
        "labels": [
            {"name": "type:bug"},
            {"name": known_defects.REGISTRY_LABEL},
        ],
    }
    unlabeled = {
        **labeled,
        "labels": [{"name": "type:bug"}],
    }

    def request(
        method: str,
        endpoint: str,
        _payload: dict[str, Any] | None = None,
    ) -> Any:
        assert method == "GET"
        if endpoint.startswith(
            "repos/RasmusTho/agentic-pkm-mvp/issues?state=all&labels="
        ):
            return [labeled] if label_present else []
        if endpoint == "repos/RasmusTho/agentic-pkm-mvp/issues/900":
            return unlabeled
        raise AssertionError(endpoint)

    monkeypatch.setattr(gateway, "_request", request)

    assert gateway.list_registry_issues("all") == [labeled]
    assert gateway._registry_identity_numbers == {900}
    label_present = False
    assert gateway.list_registry_issues("all") == [unlabeled]
    with pytest.raises(known_defects.KnownDefectsError, match="canonical label"):
        known_defects._select_registry(gateway, None)


def test_rest_precreate_enumeration_finds_hidden_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway = known_defects.GhRegistryGateway("RasmusTho/agentic-pkm-mvp")
    authoritative_reads = 0
    unlabeled = {
        "number": 4200,
        "title": "Renamed registry",
        "state": "open",
        "locked": True,
        "body": known_defects.render_registry_body(),
        "labels": [{"name": "type:bug"}],
    }

    def request(
        method: str,
        endpoint: str,
        _payload: dict[str, Any] | None = None,
    ) -> Any:
        nonlocal authoritative_reads
        assert method == "GET"
        if endpoint.startswith(
            "repos/RasmusTho/agentic-pkm-mvp/issues?state=all&labels="
        ):
            return []
        if endpoint.startswith(
            "repos/RasmusTho/agentic-pkm-mvp/issues/comments?since="
        ):
            return []
        if (
            endpoint.startswith(
                "repos/RasmusTho/agentic-pkm-mvp/issues?state=all&since="
            )
            and "&sort=updated&direction=asc" in endpoint
        ):
            authoritative_reads += 1
            return [unlabeled]
        if endpoint == "repos/RasmusTho/agentic-pkm-mvp/issues/4200":
            return unlabeled
        raise AssertionError(endpoint)

    monkeypatch.setattr(gateway, "_request", request)

    with pytest.raises(known_defects.KnownDefectsError, match="registry title"):
        known_defects._select_registry(gateway, None)

    assert authoritative_reads == 2
    assert gateway._registry_identity_numbers == {4200}


def test_authoritative_enumeration_exhausts_pages_without_numeric_cutoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway = known_defects.GhRegistryGateway("RasmusTho/agentic-pkm-mvp")
    candidate = {
        "number": 4200,
        "title": "Renamed registry",
        "state": "closed",
        "locked": True,
        "body": known_defects.render_registry_body(),
        "labels": [{"name": "type:bug"}],
    }
    pages: list[int] = []

    def request(
        method: str,
        endpoint: str,
        _payload: dict[str, Any] | None = None,
    ) -> Any:
        assert method == "GET"
        if endpoint.startswith(
            "repos/RasmusTho/agentic-pkm-mvp/issues/comments?since="
        ):
            return []
        if not (
            endpoint.startswith(
                "repos/RasmusTho/agentic-pkm-mvp/issues?state=all&since="
            )
            and "&sort=updated&direction=asc" in endpoint
        ):
            raise AssertionError(endpoint)
        page = int(endpoint.rsplit("page=", 1)[1])
        pages.append(page)
        if page == 1:
            return [
                {
                    "number": number,
                    "title": f"Ordinary Issue {number}",
                    "state": "closed",
                    "body": "",
                    "labels": [],
                }
                for number in range(1, 101)
            ]
        if page == 2:
            return [candidate]
        raise AssertionError(endpoint)

    monkeypatch.setattr(gateway, "_request", request)

    gateway.refresh_registry_identities()

    assert pages == [1, 2, 1, 2]
    assert gateway._registry_identity_numbers == {4200}


def test_precreate_convergence_replays_interpage_identity_move(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway = known_defects.GhRegistryGateway("RasmusTho/agentic-pkm-mvp")
    candidate = {
        "number": 4200,
        "title": "Renamed registry",
        "state": "open",
        "locked": True,
        "body": known_defects.render_registry_body(),
        "labels": [{"name": "type:bug"}],
    }
    pass_number = 0

    def request(
        method: str,
        endpoint: str,
        _payload: dict[str, Any] | None = None,
    ) -> Any:
        nonlocal pass_number
        assert method == "GET"
        if endpoint.startswith(
            "repos/RasmusTho/agentic-pkm-mvp/issues?state=all&labels="
        ):
            return []
        if endpoint.startswith(
            "repos/RasmusTho/agentic-pkm-mvp/issues/comments?since="
        ):
            return []
        if (
            endpoint.startswith(
                "repos/RasmusTho/agentic-pkm-mvp/issues?state=all&since="
            )
            and "&sort=updated&direction=asc" in endpoint
        ):
            page = int(endpoint.rsplit("page=", 1)[1])
            if page == 1:
                pass_number += 1
                ordinary = [
                    {
                        "number": number,
                        "title": f"Ordinary Issue {number}",
                        "state": "closed",
                        "body": "",
                        "labels": [],
                    }
                    for number in range(1, 101)
                ]
                if pass_number >= 2:
                    return [candidate, *ordinary[:99]]
                return ordinary
            if page == 2:
                return []
        if endpoint == "repos/RasmusTho/agentic-pkm-mvp/issues/4200":
            return candidate
        raise AssertionError(endpoint)

    monkeypatch.setattr(gateway, "_request", request)

    with pytest.raises(known_defects.KnownDefectsError, match="registry title"):
        known_defects._select_registry(gateway, None)

    assert pass_number == 3
    assert gateway._registry_identity_numbers == {4200}


def test_authoritative_identity_nonconvergence_fails_without_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway = known_defects.GhRegistryGateway("RasmusTho/agentic-pkm-mvp")
    passes = 0

    def request(
        method: str,
        endpoint: str,
        _payload: dict[str, Any] | None = None,
    ) -> Any:
        nonlocal passes
        assert method == "GET"
        if endpoint.startswith(
            "repos/RasmusTho/agentic-pkm-mvp/issues/comments?since="
        ):
            return []
        passes += 1
        if passes % 2 == 0:
            return []
        return [
            {
                "number": 4200,
                "title": known_defects.REGISTRY_TITLE,
                "state": "open",
                "body": known_defects.render_registry_body(),
                "labels": [{"name": known_defects.REGISTRY_LABEL}],
            }
        ]

    monkeypatch.setattr(gateway, "_request", request)

    with pytest.raises(known_defects.KnownDefectsError, match="did not converge"):
        gateway.refresh_registry_identities()

    assert passes == known_defects.REGISTRY_DISCOVERY_MAX_PASSES
    assert gateway._registry_identity_numbers is None


def test_precreate_convergence_never_forgets_observed_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway = known_defects.GhRegistryGateway("RasmusTho/agentic-pkm-mvp")
    canonical = {
        "number": 4200,
        "title": known_defects.REGISTRY_TITLE,
        "state": "open",
        "locked": True,
        "body": known_defects.render_registry_body(),
        "labels": [
            {"name": "type:bug"},
            {"name": known_defects.REGISTRY_LABEL},
        ],
    }
    drifted = {
        **canonical,
        "title": "Renamed after discovery",
        "body": "Ordinary Issue body",
        "labels": [{"name": "type:bug"}],
    }
    passes = 0

    def request(
        method: str,
        endpoint: str,
        _payload: dict[str, Any] | None = None,
    ) -> Any:
        nonlocal passes
        assert method == "GET"
        if endpoint.startswith(
            "repos/RasmusTho/agentic-pkm-mvp/issues?state=all&labels="
        ):
            return []
        if endpoint.startswith(
            "repos/RasmusTho/agentic-pkm-mvp/issues/comments?since="
        ):
            return []
        if (
            endpoint.startswith(
                "repos/RasmusTho/agentic-pkm-mvp/issues?state=all&since="
            )
            and "&sort=updated&direction=asc" in endpoint
        ):
            passes += 1
            return [canonical] if passes == 1 else []
        if endpoint == "repos/RasmusTho/agentic-pkm-mvp/issues/4200":
            return drifted
        raise AssertionError(endpoint)

    monkeypatch.setattr(gateway, "_request", request)

    with pytest.raises(known_defects.KnownDefectsError, match="registry title"):
        known_defects._select_registry(gateway, None)

    assert passes == 3
    assert gateway._registry_identity_numbers == {4200}


def test_rest_public_lookup_enumerates_hidden_prior_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway = known_defects.GhRegistryGateway("RasmusTho/agentic-pkm-mvp")
    hidden = {
        "number": 4200,
        "title": "Renamed registry",
        "state": "closed",
        "locked": True,
        "body": known_defects.render_registry_body(),
        "labels": [{"name": "type:bug"}],
    }
    current = {
        "number": 4201,
        "title": known_defects.REGISTRY_TITLE,
        "state": "open",
        "locked": True,
        "body": known_defects.render_registry_body(),
        "labels": [
            {"name": "type:bug"},
            {"name": known_defects.REGISTRY_LABEL},
        ],
    }
    authoritative_reads = 0
    hidden_reads = 0

    def request(
        method: str,
        endpoint: str,
        _payload: dict[str, Any] | None = None,
    ) -> Any:
        nonlocal authoritative_reads, hidden_reads
        assert method == "GET"
        if endpoint.startswith(
            "repos/RasmusTho/agentic-pkm-mvp/issues/comments?since="
        ):
            return []
        if (
            endpoint.startswith(
                "repos/RasmusTho/agentic-pkm-mvp/issues?state=all&since="
            )
            and "&sort=updated&direction=asc" in endpoint
        ):
            authoritative_reads += 1
            return [current, hidden]
        if endpoint.startswith(
            "repos/RasmusTho/agentic-pkm-mvp/issues?state=all&labels="
        ):
            return [current]
        if endpoint == "repos/RasmusTho/agentic-pkm-mvp/issues/4200":
            hidden_reads += 1
            return hidden
        raise AssertionError(endpoint)

    monkeypatch.setattr(gateway, "_request", request)

    with pytest.raises(known_defects.KnownDefectsError, match="registry container"):
        known_defects.lookup_defect(_defect().defect_id, gateway)

    assert authoritative_reads == 2
    assert hidden_reads == 1
    assert gateway._registry_identity_numbers == {4200, 4201}


@pytest.mark.parametrize("phase", ["pending", "final"])
def test_authoritative_comment_ledger_recovers_hidden_generation_on_cold_start(
    monkeypatch: pytest.MonkeyPatch,
    phase: str,
) -> None:
    gateway = known_defects.GhRegistryGateway("RasmusTho/agentic-pkm-mvp")
    comment = {
        "id": 8801,
        "created_at": "2026-07-27T01:02:03Z",
        "author_association": "OWNER",
        "body": _defect().render_entry(phase=phase),
        "issue_url": (
            "https://api.github.com/repos/RasmusTho/agentic-pkm-mvp/issues/899"
        ),
    }
    issue_reads = 0
    comment_reads = 0

    def request(
        method: str,
        endpoint: str,
        _payload: dict[str, Any] | None = None,
    ) -> Any:
        nonlocal issue_reads, comment_reads
        assert method == "GET"
        if (
            endpoint.startswith(
                "repos/RasmusTho/agentic-pkm-mvp/issues?state=all&since="
            )
            and "&sort=updated&direction=asc" in endpoint
        ):
            issue_reads += 1
            return []
        if (
            endpoint.startswith(
                "repos/RasmusTho/agentic-pkm-mvp/issues/comments?since="
            )
            and "&sort=created&direction=asc" in endpoint
        ):
            comment_reads += 1
            return [comment]
        raise AssertionError(endpoint)

    monkeypatch.setattr(gateway, "_request", request)

    gateway.refresh_registry_identities()

    assert issue_reads == 2
    assert comment_reads == 2
    assert gateway._registry_identity_numbers == {899}


@pytest.mark.parametrize("association", [None, 123, "", "MYSTERY"])
def test_cold_start_indeterminate_schema_author_fails_before_intake_mutation(
    monkeypatch: pytest.MonkeyPatch,
    association: Any,
) -> None:
    gateway = known_defects.GhRegistryGateway("RasmusTho/agentic-pkm-mvp")
    comment = {
        "id": 8801,
        "created_at": "2026-07-27T01:02:03Z",
        "author_association": association,
        "body": _defect().render_entry(phase="final"),
        "issue_url": (
            "https://api.github.com/repos/RasmusTho/agentic-pkm-mvp/issues/899"
        ),
    }
    mutations: list[tuple[str, str]] = []

    def request(
        method: str,
        endpoint: str,
        _payload: dict[str, Any] | None = None,
    ) -> Any:
        if method != "GET":
            mutations.append((method, endpoint))
            raise AssertionError(f"unexpected mutation: {method} {endpoint}")
        if endpoint.startswith(
            "repos/RasmusTho/agentic-pkm-mvp/issues?state=all&since="
        ):
            return []
        if endpoint.startswith(
            "repos/RasmusTho/agentic-pkm-mvp/issues/comments?since="
        ):
            return [comment]
        raise AssertionError(endpoint)

    monkeypatch.setattr(gateway, "_request", request)

    with pytest.raises(
        known_defects.KnownDefectsError,
        match="invalid author association",
    ):
        known_defects.intake_defect(_defect(), gateway)

    assert mutations == []
    assert gateway._registry_identity_numbers is None


def test_explicit_untrusted_global_schema_comment_grants_no_registry_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway = known_defects.GhRegistryGateway("RasmusTho/agentic-pkm-mvp")
    comment = {
        "id": 8801,
        "created_at": "2026-07-27T01:02:03Z",
        "author_association": "CONTRIBUTOR",
        "body": _defect().render_entry(phase="final"),
        "issue_url": (
            "https://api.github.com/repos/RasmusTho/agentic-pkm-mvp/issues/899"
        ),
    }

    def request(
        method: str,
        endpoint: str,
        _payload: dict[str, Any] | None = None,
    ) -> Any:
        assert method == "GET"
        if endpoint.startswith(
            "repos/RasmusTho/agentic-pkm-mvp/issues?state=all&since="
        ):
            return []
        if endpoint.startswith(
            "repos/RasmusTho/agentic-pkm-mvp/issues/comments?since="
        ):
            return [comment]
        raise AssertionError(endpoint)

    monkeypatch.setattr(gateway, "_request", request)

    gateway.refresh_registry_identities()

    assert gateway._registry_identity_numbers == set()


@pytest.mark.parametrize("operation", ["intake", "lookup", "promote"])
def test_cold_start_schema_ledger_blocks_duplicate_after_total_container_drift(
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    gateway = known_defects.GhRegistryGateway("RasmusTho/agentic-pkm-mvp")
    defect = _defect()
    drifted = {
        "number": 899,
        "title": "Ordinary renamed Issue",
        "state": "closed",
        "locked": True,
        "body": "All registry identity surfaces were removed.",
        "labels": [],
    }
    comment = {
        "id": 8801,
        "created_at": "2026-07-27T01:02:03Z",
        "author_association": "OWNER",
        "body": defect.render_entry(phase="final"),
        "issue_url": (
            "https://api.github.com/repos/RasmusTho/agentic-pkm-mvp/issues/899"
        ),
    }
    mutations: list[tuple[str, str]] = []

    def request(
        method: str,
        endpoint: str,
        _payload: dict[str, Any] | None = None,
    ) -> Any:
        if method != "GET":
            mutations.append((method, endpoint))
            raise AssertionError(f"unexpected mutation: {method} {endpoint}")
        if endpoint.endswith("/labels/state%3Aknown-defect"):
            return {
                "name": known_defects.REGISTRY_LABEL,
                "color": known_defects.REGISTRY_LABEL_COLOR,
                "description": known_defects.REGISTRY_LABEL_DESCRIPTION,
            }
        if (
            endpoint.startswith(
                "repos/RasmusTho/agentic-pkm-mvp/issues?state=all&since="
            )
            and "&sort=updated&direction=asc" in endpoint
        ):
            return []
        if (
            endpoint.startswith(
                "repos/RasmusTho/agentic-pkm-mvp/issues/comments?since="
            )
            and "&sort=created&direction=asc" in endpoint
        ):
            return [comment]
        if endpoint.startswith(
            "repos/RasmusTho/agentic-pkm-mvp/issues?state=all&labels="
        ):
            return []
        if endpoint == "repos/RasmusTho/agentic-pkm-mvp/issues/899":
            return drifted
        raise AssertionError(endpoint)

    monkeypatch.setattr(gateway, "_request", request)

    with pytest.raises(
        known_defects.KnownDefectsError,
        match="registry title|readable registry container",
    ):
        if operation == "intake":
            known_defects.intake_defect(defect, gateway)
        elif operation == "lookup":
            known_defects.lookup_defect(defect.defect_id, gateway)
        else:
            known_defects.promote_defect(defect.defect_id, 901, gateway)

    assert mutations == []
    assert gateway._registry_identity_numbers == {899}


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
    assert "locked_required: true" in governance
    governance_contract = yaml.safe_load(governance)
    registry_contract = governance_contract["issues"]["special_containers"][
        "known_defects_registry"
    ]
    assert registry_contract["canonical_title"] == known_defects.REGISTRY_TITLE
    assert (
        registry_contract["authoritative_discovery_since"]
        == known_defects.REGISTRY_ROLLOUT_SINCE
    )
    assert registry_contract["authoritative_consecutive_scans"] == 2
    assert (
        registry_contract["authoritative_max_passes"]
        == known_defects.REGISTRY_DISCOVERY_MAX_PASSES
    )
    assert (
        registry_contract["authoritative_identity_cache"]
        == "monotonic_issue_numbers"
    )
    assert registry_contract["authoritative_identity_sources"] == [
        "issue_surfaces",
        "trusted_schema_comments",
    ]
    workflow = (
        REPO_ROOT / ".github" / "workflows" / "issue-pr-governance.yml"
    ).read_text(encoding="utf-8")
    assert known_defects.REGISTRY_TITLE in workflow


def test_governance_lane_label_is_declared_on_every_authoritative_surface() -> None:
    taxonomy = (
        REPO_ROOT / ".codex" / "skills" / "_shared" / "LABEL_TAXONOMY.md"
    ).read_text(encoding="utf-8")
    governance = (REPO_ROOT / ".github" / "github-governance.yml").read_text(
        encoding="utf-8"
    )
    setup = (
        REPO_ROOT / "docs" / "development" / "GITHUB_GOVERNANCE_SETUP.md"
    ).read_text(encoding="utf-8")

    assert "`lane:governance`" in taxonomy
    assert "lane:\n    - lane:governance" in governance
    assert "`lane:governance`" in setup
    assert known_defects.ALLOWED_LANE_LABELS == {"lane:governance"}
