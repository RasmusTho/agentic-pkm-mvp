from app.builderops.blocker_actions import LEGACY_HUMAN_ACTIONS, intake, parse_blocker_action_receipt, receipt_for_action
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


def test_plan_removes_only_legacy_label_when_exact_successor_is_already_live() -> None:
    result = plan({"number": 1, "state": "open", "labels": ["agent:needs-human", "human:decision", "action:human-decision"]})
    assert result["after"] == ["action:human-decision", "agent:needs-human"]
    assert result["changes"] == [{"remove": "human:decision", "add": ""}]
    assert not result["errors"]


def test_plan_fails_closed_for_legacy_label_with_other_live_successor() -> None:
    result = plan({"number": 1, "state": "open", "labels": ["agent:needs-human", "human:decision", "action:human-authorization"]})
    assert result["changes"] == []
    assert "legacy_successor_conflict" in result["errors"]


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


def _receipt_body(action: str, owner: str = "builder") -> str:
    receipt = receipt_for_action(action)
    receipt["owner"] = owner
    return "```yaml\n" + "\n".join(
        f"{key}: {value if key != 'dependency_refs' else '[]'}" for key, value in receipt.items()
    ) + "\n```"


def _receipt_repair_api(labels: list[str], comments: list[dict[str, object]], calls: list[tuple], *, drift_after_write: bool = False, unreadable_exact: bool = False):
    state = {"number": 1, "state": "open", "labels": labels}

    def fake_api(repo, endpoint, *, method="GET", payload=None):
        calls.append((endpoint, method, payload))
        if endpoint.endswith("/comments?per_page=100"):
            return list(comments)
        if endpoint.endswith("/comments") and method == "POST":
            comments.append({"id": 9, "body": payload["body"]})
            return {"id": 9}
        if endpoint.endswith("/comments/9"):
            return None if unreadable_exact else comments[-1]
        if endpoint.endswith("/issues/1"):
            if drift_after_write and comments:
                return {**state, "labels": ["agent:in-progress"]}
            return dict(state)
        raise AssertionError((endpoint, method, payload))

    return fake_api


def test_plan_routes_invalid_legacy_receipt_to_receipt_only_repair() -> None:
    labels = ["agent:blocked", "action:wait-dependency"]
    result = plan({"number": 1, "state": "open", "labels": labels}, [{"body": _receipt_body("action:wait-dependency", "builder-system-maintenance")}])
    assert result["disposition"] == "receipt_repair"
    assert result["changes"] == []
    assert result["receipt_errors"] == ["missing_or_invalid_blocker_action_receipt"]


def test_plan_keeps_valid_current_receipt_as_idempotent_noop() -> None:
    labels = ["agent:blocked", "action:wait-dependency"]
    result = plan({"number": 1, "state": "open", "labels": labels}, [{"body": _receipt_body("action:wait-dependency")}])
    assert result["disposition"] == "receipt_current"
    assert result["changes"] == []
    assert not result["receipt_errors"]


def test_apply_receipt_only_recovery_is_label_free_and_fully_read_back(monkeypatch) -> None:
    labels = ["agent:blocked", "action:wait-dependency"]
    item = plan({"number": 1, "state": "open", "labels": labels}, [])
    calls: list[tuple] = []
    monkeypatch.setattr("scripts.reconcile_blocker_actions._api", _receipt_repair_api(labels, [], calls))
    result = apply_plan("o/r", "o", "r", item)
    assert result["disposition"] == "receipt_repaired"
    assert result["action"] == "action:wait-dependency"
    assert any(endpoint.endswith("/comments/9") for endpoint, _, _ in calls)
    assert not any("/labels" in endpoint for endpoint, _, _ in calls)


def test_apply_receipt_only_recovery_aborts_on_lifecycle_or_action_drift(monkeypatch) -> None:
    labels = ["agent:blocked", "action:wait-dependency"]
    item = plan({"number": 1, "state": "open", "labels": labels}, [])
    calls: list[tuple] = []
    monkeypatch.setattr("scripts.reconcile_blocker_actions._api", _receipt_repair_api(labels, [], calls, drift_after_write=True))
    with pytest.raises(RuntimeError, match="post-receipt lifecycle/action drift"):
        apply_plan("o/r", "o", "r", item)
    assert not any("/labels" in endpoint for endpoint, _, _ in calls)


def test_receipt_only_retry_converges_after_partial_apply(monkeypatch) -> None:
    labels = ["agent:blocked", "action:wait-dependency"]
    comments: list[dict[str, object]] = [{"id": 9, "body": _receipt_body("action:wait-dependency")}]
    item = plan({"number": 1, "state": "open", "labels": labels}, [])
    calls: list[tuple] = []
    monkeypatch.setattr("scripts.reconcile_blocker_actions._api", _receipt_repair_api(labels, comments, calls))
    result = apply_plan("o/r", "o", "r", item)
    assert result["disposition"] == "receipt_current"
    assert not any(endpoint.endswith("/comments") and method == "POST" for endpoint, method, _ in calls)


def test_receipt_only_readback_failure_is_not_reported_as_success(monkeypatch) -> None:
    labels = ["agent:blocked", "action:wait-dependency"]
    item = plan({"number": 1, "state": "open", "labels": labels}, [])
    calls: list[tuple] = []
    monkeypatch.setattr("scripts.reconcile_blocker_actions._api", _receipt_repair_api(labels, [], calls, unreadable_exact=True))
    with pytest.raises(RuntimeError, match="receipt readback mismatch"):
        apply_plan("o/r", "o", "r", item)


def test_report_distinguishes_receipt_repair_current_and_drift() -> None:
    labels = ["agent:blocked", "action:wait-dependency"]
    assert plan({"number": 1, "state": "open", "labels": labels}, [])["disposition"] == "receipt_repair"
    assert plan({"number": 1, "state": "open", "labels": labels}, [{"body": _receipt_body("action:repair-contract")}])["disposition"] == "receipt_repair"
    assert plan({"number": 1, "state": "open", "labels": labels}, [{"body": _receipt_body("action:wait-dependency")}])["disposition"] == "receipt_current"
    assert plan({"number": 1, "state": "open", "labels": ["agent:blocked", "action:human-decision"]}, [])["disposition"] == "drift"
    assert plan({"number": 1, "state": "open", "labels": ["agent:in-progress"]}, [])["disposition"] == "not_applicable"


def test_intake_parses_real_comment_receipt_and_rejects_invalid_placeholder() -> None:
    receipt = receipt_for_action("action:wait-dependency")
    comment = {"body": "```yaml\n" + "\n".join(f"{key}: {value if key != 'dependency_refs' else '[]'}" for key, value in receipt.items()) + "\n```"}
    payload = intake([{"number": 1, "state": "open", "labels": ["agent:blocked", "action:wait-dependency"], "comments": [comment]}])
    item = payload["queues"]["action:wait-dependency"][0]
    assert item["owner"] == "builder"
    assert item["next_action"]
    assert not payload["drift"]


def test_receipt_parser_rejects_noncanonical_owner() -> None:
    receipt = receipt_for_action("action:wait-dependency")
    for owner in ("", "builder-system-maintenance", "external:", "external:bad name", "external:UPPER"):
        receipt["owner"] = owner
        body = "```yaml\n" + "\n".join(f"{key}: {value if key != 'dependency_refs' else '[]'}" for key, value in receipt.items()) + "\n```"
        assert parse_blocker_action_receipt({"body": body}) is None


def test_receipt_parser_accepts_canonical_external_owner() -> None:
    receipt = receipt_for_action("action:wait-dependency")
    receipt["owner"] = "external:github-bot_1"
    body = "```yaml\n" + "\n".join(f"{key}: {value if key != 'dependency_refs' else '[]'}" for key, value in receipt.items()) + "\n```"
    assert parse_blocker_action_receipt({"body": body}) == receipt
