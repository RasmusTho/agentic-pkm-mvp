from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from app.builderops.__main__ import _root as builderops_standalone_root
from app.builderops.pattern_routing import (
    PatternRoutingError,
    build_pattern_routing_report,
)


def _ref(ref: str = "#3260") -> dict[str, str]:
    return {"ref_type": "github_issue", "ref": ref}


def _pattern(
    pattern_id: str,
    route: str,
    target_ref: str,
    terminal_outcome: str,
    repeat_count: int = 3,
) -> dict[str, object]:
    return {
        "id": pattern_id,
        "route": route,
        "summary": f"{route} repeated pattern",
        "repeat_count": repeat_count,
        "source_refs": [_ref("#3260"), {"ref_type": "pull_request", "ref": "#3295"}],
        "target_ref": target_ref,
        "terminal_outcome": terminal_outcome,
        "recommendation": "Route through the governed Builder destination path.",
    }


def _payload() -> dict[str, object]:
    return {
        "patterns": [
            _pattern(
                "pat-debt",
                "transition_debt",
                "docs/architecture/SBS_TRANSITION_DEBT.md::D12",
                "debt_or_fitness_recorded",
            ),
            _pattern(
                "pat-fitness",
                "fitness_rule_candidate",
                "docs/architecture/SBS_FITNESS_RULES.md::No Builder learning or TCD signal bypasses governed Builder destinations",
                "debt_or_fitness_recorded",
            ),
            _pattern("pat-issue", "issue_candidate", "#3265-follow-up", "issue_created"),
            _pattern(
                "pat-discard",
                "discard_supersession",
                "receipt:discard-low-signal",
                "discarded_or_superseded",
                repeat_count=1,
            ),
        ]
    }


def test_pattern_routing_names_thresholds_and_routes() -> None:
    report = build_pattern_routing_report(_payload())

    assert report["observe_only"] is True
    assert report["mutations_performed"] is False
    assert set(report["routing_outcomes"]) == {
        "transition_debt",
        "fitness_rule_candidate",
        "issue_candidate",
        "discard_supersession",
    }
    assert "repeat" in report["routing_criteria"]["transition_debt"].lower()
    assert "mechanically detectable" in report["routing_criteria"]["fitness_rule_candidate"]


def test_repeated_failure_can_route_to_debt_or_fitness_with_source_refs() -> None:
    report = build_pattern_routing_report(_payload())
    by_id = {item["id"]: item for item in report["pattern"]}

    assert by_id["pat-debt"]["terminal_outcome"] == "debt_or_fitness_recorded"
    assert by_id["pat-debt"]["target_ref"] == "docs/architecture/SBS_TRANSITION_DEBT.md::D12"
    assert by_id["pat-debt"]["source_refs"]
    assert by_id["pat-fitness"]["route"] == "fitness_rule_candidate"
    assert "pat-fitness=fitness_rule_candidate" in report["receipt_body"]
    assert "pat-fitness=debt_or_fitness_recorded" in report["receipt_body"]


def test_one_off_signal_can_be_discarded_with_receipt_target() -> None:
    report = build_pattern_routing_report(_payload())
    discard = [item for item in report["pattern"] if item["route"] == "discard_supersession"][0]

    assert discard["repeat_count"] == 1
    assert discard["terminal_outcome"] == "discarded_or_superseded"
    assert discard["target_ref"] == "receipt:discard-low-signal"


def test_non_discard_routes_require_repetition() -> None:
    payload = {
        "patterns": [
            _pattern(
                "pat-bad",
                "transition_debt",
                "docs/architecture/SBS_TRANSITION_DEBT.md::D12",
                "debt_or_fitness_recorded",
                repeat_count=1,
            )
        ]
    }

    with pytest.raises(PatternRoutingError, match="repeat_count >= 2"):
        build_pattern_routing_report(payload)


def test_pattern_routing_rejects_wrong_terminal_outcome() -> None:
    payload = {
        "patterns": [
            _pattern("pat-bad", "issue_candidate", "#4000", "debt_or_fitness_recorded")
        ]
    }

    with pytest.raises(PatternRoutingError, match="issue_created"):
        build_pattern_routing_report(payload)


def test_pattern_routing_cli_is_observe_only(tmp_path: Path) -> None:
    patterns_file = tmp_path / "patterns.json"
    patterns_file.write_text(json.dumps(_payload()), encoding="utf-8")

    result = CliRunner().invoke(
        builderops_standalone_root,
        [
            "builderops",
            "pattern-routing",
            "classify",
            "--patterns-file",
            str(patterns_file),
            "--json",
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["mutation_channels"] == {
        "git_push": False,
        "github_issue": False,
        "github_label": False,
        "github_project": False,
        "product_runtime": False,
        "runtime_memory": False,
    }
    assert len(payload["pattern"]) == 4
