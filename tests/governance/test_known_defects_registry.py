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
            and (state == "all" or issue["state"] == state)
        ]

    def get_issue(self, number: int) -> dict[str, Any]:
        return self.issues[number]

    def create_registry_issue(self) -> dict[str, Any]:
        issue = {
            "number": self.next_issue,
            "state": "open",
            "locked": False,
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

    def lock_registry_issue(self, issue_number: int) -> None:
        self.issues[issue_number]["locked"] = True

    def list_comments(self, issue_number: int) -> list[dict[str, Any]]:
        return list(self.comments.get(issue_number, []))

    def add_comment(self, issue_number: int, body: str) -> dict[str, Any]:
        comment = {
            "id": self.next_comment,
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
- Authority impact: bounded defect repair
- Persistence impact: none
- Derived/rebuildable impact: none
- Human knowledge impact: none
- Memory impact: none
- Retrieval/context impact: none
- Sync/deployment impact: none
- External boundary impact: none
- New or changed contract: none
- Owner-doc impact: none
- Transition debt impact: reduces
- Fitness rule impact: strengthens

## Constraints

- Preserve unrelated behavior.

## Acceptance Criteria

- [ ] Regression no longer reproduces.
  Verify: `tests/x.py::test_x`

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
                "- [ ] A bounded outcome.\n  Verify: `tests/x.py::test_x`"
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
            "- Fitness rule impact: strengthens",
            "- Other impact: none",
        ),
        "labels": [
            {"name": "type:bug"},
            {"name": "prio:med"},
            {"name": "agent:ready"},
        ],
    }
    with pytest.raises(known_defects.KnownDefectsError, match="Fitness rule"):
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
                "Verify: `tests/x.py::test_x`",
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


def test_registry_rejects_missing_type_bug_any_agent_state_and_unlocked_history() -> None:
    for mutation, expected in (
        (
            lambda issue: issue.update(
                labels=[{"name": known_defects.REGISTRY_LABEL}]
            ),
            "type:bug",
        ),
        (
            lambda issue: issue["labels"].append({"name": "agent:blocked"}),
            "must carry no agent state",
        ),
        (
            lambda issue: issue.update(locked=False),
            "must be locked",
        ),
    ):
        gateway = FakeGateway()
        issue = gateway.create_registry_issue()
        gateway.lock_registry_issue(issue["number"])
        mutation(issue)
        with pytest.raises(known_defects.KnownDefectsError, match=expected):
            known_defects.lookup_defect("KD-000000000000", gateway)


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

    with pytest.raises(known_defects.KnownDefectsError, match="entry shape"):
        known_defects.lookup_defect("KD-000000000000", gateway)


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
                f"authority_sha256={'0' * 64} -->"
            ),
            (
                f"Promotion receipt: {defect_id} is now tracked for implementation "
                f"by #{issue_text}."
            ),
            f"Validated target authority: sha256:{'0' * 64}.",
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
    with pytest.raises(known_defects.KnownDefectsError, match="multiple open registries"):
        known_defects.lookup_defect(defect.defect_id, gateway)


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

    with pytest.raises(known_defects.KnownDefectsError, match="malformed"):
        known_defects.lookup_defect(defect.defect_id, gateway)


@pytest.mark.parametrize(
    "body",
    [
        "prefix\n" + known_defects.render_registry_body(),
        known_defects.render_registry_body() + "\nsuffix",
        "manual text " + known_defects.REGISTRY_MARKER,
    ],
)
def test_registry_body_marker_must_be_exact_first_line_schema(
    body: str,
) -> None:
    gateway = FakeGateway()
    issue = gateway.create_registry_issue()
    gateway.lock_registry_issue(issue["number"])
    issue["body"] = body

    with pytest.raises(known_defects.KnownDefectsError, match="malformed"):
        known_defects.lookup_defect("KD-000000000000", gateway)


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
                ),
                (
                    f"Promotion receipt: {defect.defect_id} is now tracked for "
                    "implementation by #901."
                ),
                f"Validated target authority: sha256:{'0' * 64}.",
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


def test_registry_close_after_append_compensates_and_retries_once() -> None:
    gateway = CloseAfterAppendGateway()

    receipt = known_defects.intake_defect(_defect(), gateway)

    assert receipt["status"] == "created"
    assert receipt["registry_issue"] == 901
    assert gateway.comments[900] == []
    assert len(gateway.comments[901]) == 1


class MalformedAfterAppendGateway(FakeGateway):
    def add_comment(self, issue_number: int, body: str) -> dict[str, Any]:
        comment = super().add_comment(issue_number, body)
        if issue_number == 900 and body.startswith("<!-- known-defect-entry:"):
            self.issues[issue_number]["labels"].append({"name": "agent:blocked"})
        return comment


def test_registry_authority_drift_after_append_is_compensated_and_fails_closed() -> None:
    gateway = MalformedAfterAppendGateway()

    with pytest.raises(known_defects.KnownDefectsError, match="agent state"):
        known_defects.intake_defect(_defect(), gateway)

    assert gateway.comments[900] == []


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


def test_indeterminate_post_append_read_compensates_before_failing() -> None:
    gateway = PostAppendReadFailureGateway()

    with pytest.raises(known_defects.KnownDefectsError, match="indeterminate"):
        known_defects.intake_defect(_defect(), gateway)

    assert gateway.comments[900] == []


def test_promotion_requires_concrete_verify_target_on_every_ac() -> None:
    gateway = FakeGateway()
    defect = _defect()
    known_defects.intake_defect(defect, gateway)
    body = _canonical_bug_body().replace(
        "- [ ] Regression no longer reproduces.\n  Verify: `tests/x.py::test_x`",
        (
            "- [ ] Regression no longer reproduces.\n"
            "  Verify: `tests/x.py::test_x`\n"
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

    with pytest.raises(known_defects.KnownDefectsError, match="lack concrete Verify"):
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
                        ),
                        (
                            f"Promotion receipt: {defect_id} is now tracked for "
                            "implementation by #902."
                        ),
                        f"Validated target authority: sha256:{authority_sha256}.",
                        (
                            "The bounded bug Issue owns scope, acceptance criteria, "
                            "Verify targets, and execution state."
                        ),
                    )
                ),
            )
        return comment


def test_concurrent_conflicting_promotions_never_choose_a_canonical_target() -> None:
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

    with pytest.raises(known_defects.KnownDefectsError, match="promotion conflict"):
        known_defects.promote_defect(defect.defect_id, 901, gateway)

    receipt = known_defects.lookup_defect(defect.defect_id, gateway)
    assert receipt["status"] == "promotion_conflict"
    assert receipt["promotion_issue"] is None
    assert receipt["promotion_issues"] == [901, 902]
    assert receipt["registry_issue"] == intake["registry_issue"]


class PromotionTargetRaceGateway(FakeGateway):
    def __init__(self, transition: str) -> None:
        super().__init__()
        self.transition = transition
        self.transitioned = False

    def add_comment(self, issue_number: int, body: str) -> dict[str, Any]:
        comment = super().add_comment(issue_number, body)
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
        return comment


@pytest.mark.parametrize("transition", ["body", "label"])
def test_first_promotion_compensates_target_authority_drift(
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

    with pytest.raises(known_defects.KnownDefectsError, match="authority drifted"):
        known_defects.promote_defect(defect.defect_id, 901, gateway)

    assert len(gateway.comments[intake["registry_issue"]]) == 1


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


def test_indeterminate_promotion_post_write_read_compensates_marker() -> None:
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

    with pytest.raises(known_defects.KnownDefectsError, match="indeterminate"):
        known_defects.promote_defect(defect.defect_id, 901, gateway)

    assert len(gateway.comments[intake["registry_issue"]]) == 1


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
