from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from app.builderops.__main__ import _root as builderops_standalone_root
from app.builderops.evidence_bridge import (
    EvidenceBridgeError,
    build_evidence_bridge_report,
)


def _ref(ref_type: str = "pull_request", ref: str = "#3281") -> dict[str, str]:
    return {"ref_type": ref_type, "ref": ref}


def _evidence() -> dict[str, object]:
    return {
        "observed": [
            {
                "id": "obs-ci-repeat",
                "kind": "ci_failure",
                "summary": "Architecture CI failed twice on docs guard drift.",
                "source_refs": [_ref("ci_run", "https://github.test/runs/1")],
            },
            {
                "id": "obs-review-repeat",
                "kind": "review_finding",
                "summary": "Review repeatedly asked for source-ref validation.",
                "source_refs": [_ref("review_thread", "PRRT_1")],
            },
            {
                "id": "obs-missing-evidence",
                "kind": "missing_evidence",
                "summary": "Owner-doc receipt was missing from the PR body.",
                "source_refs": [_ref("pull_request", "#3281")],
            },
        ],
        "unknown": [
            {
                "id": "unk-human-exception-cause",
                "kind": "unknown_for_retro",
                "summary": "The upstream artifact for a Human Exception cause is unclear.",
            }
        ],
        "candidate": [
            {
                "id": "cand-learning",
                "route": "learning_signal",
                "summary": "Docs guard drift should be captured for retrospective handling.",
                "evidence_ids": ["obs-ci-repeat"],
                "source_refs": [_ref("ci_artifact", "ci-failure-context-3281.json")],
                "upstream_artifact": ".codex/skills/publish-pr/SKILL.md",
                "recommendation": "Create a LearningSignal with the CI artifact as source evidence.",
            },
            {
                "id": "cand-issue",
                "route": "issue_candidate",
                "summary": "Repeated missing owner-doc receipts need a bounded follow-up issue.",
                "evidence_ids": ["obs-missing-evidence"],
                "source_refs": [_ref("pull_request", "#3281")],
                "upstream_artifact": ".codex/skills/publish-pr/SKILL.md",
                "recommendation": "Open a governance-lane issue if the pattern repeats.",
            },
            {
                "id": "cand-debt",
                "route": "debt_fitness_candidate",
                "summary": "Source-ref validation has become a repeated review finding.",
                "evidence_ids": ["obs-review-repeat"],
                "source_refs": [_ref("review_thread", "PRRT_1")],
                "upstream_artifact": "docs/architecture/SBS_TRANSITION_DEBT.md::D12",
                "recommendation": "Record the repeated failure mode as transition debt or a fitness rule.",
            },
            {
                "id": "cand-discard",
                "route": "discard",
                "summary": "The Human Exception cause has no named upstream artifact yet.",
                "evidence_ids": ["unk-human-exception-cause"],
                "source_refs": [_ref("github_issue", "#3263")],
                "unknown_for_retro": True,
                "recommendation": "Keep in the unknown-for-retro bucket until a named artifact exists.",
            },
        ],
    }


def test_evidence_bridge_distinguishes_observed_unknown_and_candidate() -> None:
    report = build_evidence_bridge_report(_evidence())

    assert set(["observed", "unknown", "candidate"]).issubset(report)
    assert report["observed"][0]["id"] == "obs-ci-repeat"
    assert report["unknown"][0]["id"] == "unk-human-exception-cause"
    assert report["candidate"][0]["route"] == "learning_signal"
    assert report["mutations_performed"] is False


def test_evidence_bridge_rejects_candidate_without_source_refs_or_artifact() -> None:
    missing_refs = _evidence()
    missing_refs["candidate"] = [
        {
            "id": "cand-bad",
            "route": "learning_signal",
            "summary": "Missing source refs.",
            "evidence_ids": ["obs-ci-repeat"],
            "upstream_artifact": ".codex/skills/publish-pr/SKILL.md",
            "recommendation": "Reject this candidate.",
        }
    ]

    with pytest.raises(EvidenceBridgeError, match="source_refs"):
        build_evidence_bridge_report(missing_refs)

    missing_artifact = _evidence()
    missing_artifact["candidate"] = [
        {
            "id": "cand-bad",
            "route": "learning_signal",
            "summary": "Missing upstream artifact.",
            "evidence_ids": ["obs-ci-repeat"],
            "source_refs": [_ref()],
            "recommendation": "Reject this candidate.",
        }
    ]

    with pytest.raises(EvidenceBridgeError, match="upstream_artifact"):
        build_evidence_bridge_report(missing_artifact)


def test_evidence_bridge_routes_repeated_patterns_to_supported_outcomes() -> None:
    report = build_evidence_bridge_report(_evidence())

    routes = {item["route"] for item in report["candidate"]}
    assert routes == {
        "learning_signal",
        "issue_candidate",
        "debt_fitness_candidate",
        "discard",
    }
    assert "cand-learning=learning_signal" in report["receipt_body"]
    assert "cand-debt=debt_fitness_candidate" in report["receipt_body"]


def test_evidence_bridge_rejects_unknown_evidence_ids() -> None:
    evidence = _evidence()
    evidence["candidate"] = [
        {
            "id": "cand-bad",
            "route": "issue_candidate",
            "summary": "Unknown evidence id.",
            "evidence_ids": ["obs-missing"],
            "source_refs": [_ref()],
            "upstream_artifact": ".codex/skills/issue-to-code/SKILL.md",
            "recommendation": "Reject this candidate.",
        }
    ]

    with pytest.raises(EvidenceBridgeError, match="unknown evidence"):
        build_evidence_bridge_report(evidence)


def test_evidence_bridge_cli_is_observe_only(tmp_path: Path) -> None:
    evidence_file = tmp_path / "evidence.json"
    evidence_file.write_text(json.dumps(_evidence()), encoding="utf-8")

    result = CliRunner().invoke(
        builderops_standalone_root,
        [
            "builderops",
            "evidence-bridge",
            "classify",
            "--evidence-file",
            str(evidence_file),
            "--json",
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["observe_only"] is True
    assert payload["mutations_performed"] is False
    assert payload["mutation_channels"] == {
        "git_push": False,
        "github_label": False,
        "github_merge": False,
        "github_project": False,
        "product_runtime": False,
    }
    assert payload["candidate"][0]["id"] == "cand-learning"
