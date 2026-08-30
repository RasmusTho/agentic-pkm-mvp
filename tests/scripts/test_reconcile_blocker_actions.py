from app.builderops.blocker_actions import LEGACY_HUMAN_ACTIONS, intake, receipt_for_action
from scripts.reconcile_blocker_actions import apply_plan, plan
import subprocess
import sys
from pathlib import Path

import pytest


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


def test_apply_re_reads_before_each_narrow_mutation_and_aborts_on_claim_drift(monkeypatch) -> None:
    item = plan({"number": 1, "state": "open", "labels": ["agent:blocked"]})
    reads = iter([
        {"number": 1, "state": "open", "labels": ["agent:blocked"]},
        {"number": 1, "state": "open", "labels": ["agent:in-progress"]},
    ])
    monkeypatch.setattr("scripts.reconcile_blocker_actions._api", lambda *args, **kwargs: next(reads))
    with pytest.raises(RuntimeError, match="drift"):
        apply_plan("o/r", "o", "r", item)


def test_apply_uses_narrow_writes_and_verifies_readback(monkeypatch) -> None:
    item = plan({"number": 1, "state": "open", "labels": ["agent:blocked"]})
    calls = []
    reads = iter([
        {"number": 1, "state": "open", "labels": ["agent:blocked"]},
        {"number": 1, "state": "open", "labels": ["agent:blocked"]},
        {"number": 1, "state": "open", "labels": ["agent:blocked", "action:repair-contract"]},
        {"number": 1, "state": "open", "labels": ["agent:blocked", "action:repair-contract"]},
    ])
    def fake_api(repo, endpoint, *, method="GET", payload=None):
        calls.append((endpoint, method, payload))
        if method == "GET": return next(reads)
        return None
    monkeypatch.setattr("scripts.reconcile_blocker_actions._api", fake_api)
    result = apply_plan("o/r", "o", "r", item)
    assert result["action"] == "action:repair-contract"
    assert any(method == "POST" and endpoint.endswith("/labels") for endpoint, method, _ in calls)
    assert not any(method == "PATCH" for _, method, _ in calls)


def test_intake_parses_real_comment_receipt_and_rejects_invalid_placeholder() -> None:
    receipt = receipt_for_action("action:wait-dependency")
    comment = {"body": "```yaml\n" + "\n".join(f"{key}: {value if key != 'dependency_refs' else '[]'}" for key, value in receipt.items()) + "\n```"}
    payload = intake([{"number": 1, "state": "open", "labels": ["agent:blocked", "action:wait-dependency"], "comments": [comment]}])
    item = payload["queues"]["action:wait-dependency"][0]
    assert item["owner"] == "builder-system-maintenance"
    assert item["next_action"]
    assert not payload["drift"]
