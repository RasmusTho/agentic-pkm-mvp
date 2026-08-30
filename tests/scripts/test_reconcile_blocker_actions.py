from app.builderops.blocker_actions import LEGACY_HUMAN_ACTIONS
from scripts.reconcile_blocker_actions import plan
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_report_and_apply_are_bounded_idempotent_and_exact() -> None:
    issue = {"number": 1, "state": "open", "labels": ["agent:blocked"]}
    first = plan(issue)
    assert first["after"] == ["action:repair-contract", "agent:blocked"]
    assert plan({**issue, "labels": first["after"]})["changes"] == []


def test_legacy_human_labels_map_to_canonical_successors() -> None:
    for old, new in LEGACY_HUMAN_ACTIONS.items():
        result = plan({"number": 1, "state": "open", "labels": ["agent:needs-human", old]})
        assert new in result["after"] and old not in result["after"]


def test_unclassified_blocked_routes_to_repair_contract_without_cause_inference() -> None:
    result = plan({"number": 1, "state": "open", "labels": ["agent:blocked"]})
    assert result["after"] == ["action:repair-contract", "agent:blocked"]


def test_script_entrypoints_execute_from_repo_root() -> None:
    for script in ("reconcile_blocker_actions.py", "report_blocker_actions.py"):
        result = subprocess.run(
            [sys.executable, f"scripts/{script}", "--help"],
            cwd=ROOT, text=True, capture_output=True, check=False,
        )
        assert result.returncode == 0, result.stderr
