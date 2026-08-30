from app.builderops.blocker_actions import LEGACY_HUMAN_ACTIONS, intake, parse_blocker_action_receipt, receipt_for_action
from scripts.reconcile_blocker_actions import apply_plan, plan, required_action_labels
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
        if "/comments?per_page=100&page=" in endpoint:
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


def test_plan_uses_newest_receipt_marker_before_validation() -> None:
    labels = ["agent:blocked", "action:wait-dependency"]
    valid = {"body": _receipt_body("action:wait-dependency")}
    invalid = {"body": "```yaml\nreceipt: blocker_action.v1\nowner: builder\n```"}
    assert plan({"number": 1, "state": "open", "labels": labels}, [valid, invalid])["disposition"] == "receipt_repair"
    assert plan({"number": 1, "state": "open", "labels": labels}, [invalid, valid])["disposition"] == "receipt_current"


def test_apply_reads_second_comment_page_and_retry_does_not_duplicate_receipt(monkeypatch) -> None:
    labels = ["agent:blocked", "action:wait-dependency"]
    pages = [{"id": index, "body": "ordinary comment"} for index in range(100)]
    pages.append({"id": 101, "body": _receipt_body("action:wait-dependency")})
    item = plan({"number": 1, "state": "open", "labels": labels}, pages)
    calls: list[tuple] = []

    def fake_api(repo, endpoint, *, method="GET", payload=None):
        calls.append((endpoint, method, payload))
        if endpoint.endswith("page=1"):
            return pages[:100]
        if endpoint.endswith("page=2"):
            return pages[100:]
        if endpoint.endswith("/issues/1"):
            return {"number": 1, "state": "open", "labels": labels}
        raise AssertionError((endpoint, method, payload))

    monkeypatch.setattr("scripts.reconcile_blocker_actions._api", fake_api)
    result = apply_plan("o/r", "o", "r", item)
    assert result["disposition"] == "receipt_current"
    assert any(endpoint.endswith("page=2") for endpoint, _, _ in calls)
    assert not any(endpoint.endswith("/comments") and method == "POST" for endpoint, method, _ in calls)


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


def test_action_only_cleanup_finishes_not_applicable_after_readback(monkeypatch) -> None:
    item = plan({"number": 1, "state": "open", "labels": ["action:wait-dependency"]}, [])
    state = {"labels": ["action:wait-dependency"]}

    def fake_api(repo, endpoint, *, method="GET", payload=None):
        if "/comments?per_page=100&page=" in endpoint:
            return []
        if endpoint.endswith("/labels/action:wait-dependency") and method == "DELETE":
            state["labels"] = []
            return None
        if endpoint.endswith("/issues/1"):
            return {"number": 1, "state": "open", "labels": state["labels"]}
        raise AssertionError((endpoint, method, payload))

    monkeypatch.setattr("scripts.reconcile_blocker_actions._api", fake_api)
    assert apply_plan("o/r", "o", "r", item)["disposition"] == "not_applicable"


def test_unexpected_not_applicable_state_fails_closed(monkeypatch) -> None:
    labels = ["agent:blocked", "action:wait-dependency"]
    item = plan({"number": 1, "state": "open", "labels": labels}, [])
    reads = iter([
        {"number": 1, "state": "open", "labels": labels},
        {"number": 1, "state": "open", "labels": []},
    ])

    def fake_api(repo, endpoint, *, method="GET", payload=None):
        if "/comments?per_page=100&page=" in endpoint:
            return []
        if endpoint.endswith("/issues/1"):
            return next(reads)
        raise AssertionError((endpoint, method, payload))

    monkeypatch.setattr("scripts.reconcile_blocker_actions._api", fake_api)
    with pytest.raises(RuntimeError, match="post-apply receipt drift"):
        apply_plan("o/r", "o", "r", item)


def test_main_skips_label_bootstrap_for_receipt_only_batch(monkeypatch) -> None:
    from scripts import reconcile_blocker_actions

    labels = ["agent:blocked", "action:wait-dependency"]
    comments: list[dict[str, object]] = []
    calls: list[tuple] = []
    monkeypatch.setattr(reconcile_blocker_actions, "_api", _receipt_repair_api(labels, comments, calls))
    monkeypatch.setattr(sys, "argv", ["reconcile_blocker_actions.py", "--repo", "o/r", "--issue", "1", "--apply"])
    assert reconcile_blocker_actions.main() == 0
    assert not any(endpoint == "repos/o/r/labels?per_page=100" for endpoint, _, _ in calls)
    assert not any(endpoint == "repos/o/r/labels" for endpoint, _, _ in calls)


def test_mixed_batch_bootstraps_only_actual_label_additions() -> None:
    receipt_only = plan({"number": 1, "state": "open", "labels": ["agent:blocked", "action:wait-dependency"]}, [])
    add_action = plan({"number": 2, "state": "open", "labels": ["agent:blocked"]}, [])
    cleanup_only = plan({"number": 3, "state": "open", "labels": ["action:wait-dependency"]}, [])
    assert required_action_labels([receipt_only, cleanup_only]) == set()
    assert required_action_labels([receipt_only, add_action, cleanup_only]) == {"action:repair-contract"}


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
