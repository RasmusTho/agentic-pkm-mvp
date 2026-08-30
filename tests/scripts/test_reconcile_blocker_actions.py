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
        {"number": 1, "state": "open", "labels": ["agent:blocked", "action:repair-contract"]},
        {"number": 1, "state": "open", "labels": ["agent:blocked", "action:repair-contract"]},
    ])
    posted_body = None
    def fake_api(repo, endpoint, *, method="GET", payload=None):
        nonlocal posted_body
        calls.append((endpoint, method, payload))
        if method == "POST" and endpoint.endswith("/comments"):
            posted_body = payload["body"]
            return {"id": 9}
        if method == "GET" and "comments?" in endpoint:
            return [{"id": 9, "body": posted_body}]
        if method == "GET": return next(reads)
        return None
    monkeypatch.setattr("scripts.reconcile_blocker_actions._api", fake_api)
    result = apply_plan("o/r", "o", "r", item)
    assert result["action"] == "action:repair-contract"
    assert any(method == "POST" and endpoint.endswith("/labels") for endpoint, method, _ in calls)
    assert not any(method == "PATCH" for _, method, _ in calls)


def test_apply_retries_partial_legacy_migration_with_only_safe_removal(monkeypatch) -> None:
    item = plan({"number": 1, "state": "open", "labels": ["agent:needs-human", "human:decision", "action:human-decision"]})
    reads = iter([
        {"number": 1, "state": "open", "labels": item["before"]},
        {"number": 1, "state": "open", "labels": item["before"]},
        {"number": 1, "state": "open", "labels": item["after"]},
        {"number": 1, "state": "open", "labels": item["after"]},
        {"number": 1, "state": "open", "labels": item["after"]},
    ])
    calls = []
    posted_body = None

    def fake_api(repo, endpoint, *, method="GET", payload=None):
        nonlocal posted_body
        calls.append((endpoint, method, payload))
        if method == "DELETE":
            return None
        if method == "POST" and endpoint.endswith("/comments"):
            posted_body = payload["body"]
            return {"id": 9}
        if method == "GET" and "comments?" in endpoint:
            return [{"id": 9, "body": posted_body}]
        return next(reads)

    monkeypatch.setattr("scripts.reconcile_blocker_actions._api", fake_api)
    assert apply_plan("o/r", "o", "r", item)["action"] == "action:human-decision"
    assert any(method == "DELETE" and endpoint.endswith("/labels/human:decision") for endpoint, method, _ in calls)
    assert not any(method == "POST" and endpoint.endswith("/labels") for endpoint, method, _ in calls)


def test_apply_aborts_when_posted_receipt_cannot_be_read_back(monkeypatch) -> None:
    item = plan({"number": 1, "state": "open", "labels": ["agent:blocked"]})
    reads = iter([
        {"number": 1, "state": "open", "labels": ["agent:blocked"]},
        {"number": 1, "state": "open", "labels": ["agent:blocked"]},
        {"number": 1, "state": "open", "labels": ["agent:blocked", "action:repair-contract"]},
        {"number": 1, "state": "open", "labels": ["agent:blocked", "action:repair-contract"]},
    ])
    def fake_api(repo, endpoint, *, method="GET", payload=None):
        if method == "POST" and endpoint.endswith("/comments"):
            return {"id": 9}
        if method == "POST" and endpoint.endswith("/labels"):
            return None
        if method == "GET" and "comments?" in endpoint:
            return []
        return next(reads)
    monkeypatch.setattr("scripts.reconcile_blocker_actions._api", fake_api)
    with pytest.raises(RuntimeError, match="receipt readback mismatch"):
        apply_plan("o/r", "o", "r", item)


def test_apply_aborts_when_posted_receipt_action_mismatches_live_label(monkeypatch) -> None:
    item = plan({"number": 1, "state": "open", "labels": ["agent:blocked"]})
    reads = iter([
        {"number": 1, "state": "open", "labels": ["agent:blocked"]},
        {"number": 1, "state": "open", "labels": ["agent:blocked"]},
        {"number": 1, "state": "open", "labels": ["agent:blocked", "action:repair-contract"]},
        {"number": 1, "state": "open", "labels": ["agent:blocked", "action:repair-contract"]},
    ])
    wrong = receipt_for_action("action:human-decision")
    wrong_body = "```yaml\n" + "\n".join(f"{key}: {value if key != 'dependency_refs' else '[]'}" for key, value in wrong.items()) + "\n```"

    def fake_api(repo, endpoint, *, method="GET", payload=None):
        if method == "POST" and endpoint.endswith("/comments"):
            return {"id": 9}
        if method == "POST" and endpoint.endswith("/labels"):
            return None
        if method == "GET" and "comments?" in endpoint:
            return [{"id": 9, "body": wrong_body}]
        return next(reads)

    monkeypatch.setattr("scripts.reconcile_blocker_actions._api", fake_api)
    with pytest.raises(RuntimeError, match="receipt readback mismatch"):
        apply_plan("o/r", "o", "r", item)


def test_apply_aborts_when_terminal_lifecycle_drifts_after_receipt(monkeypatch) -> None:
    item = plan({"number": 1, "state": "open", "labels": ["agent:blocked"]})
    reads = iter([
        {"number": 1, "state": "open", "labels": ["agent:blocked"]},
        {"number": 1, "state": "open", "labels": ["agent:blocked"]},
        {"number": 1, "state": "open", "labels": ["agent:blocked", "action:repair-contract"]},
        {"number": 1, "state": "open", "labels": ["agent:blocked", "action:repair-contract"]},
        {"number": 1, "state": "closed", "labels": ["agent:blocked", "action:repair-contract"]},
    ])
    posted_body = None

    def fake_api(repo, endpoint, *, method="GET", payload=None):
        nonlocal posted_body
        if method == "POST" and endpoint.endswith("/labels"):
            return None
        if method == "POST" and endpoint.endswith("/comments"):
            posted_body = payload["body"]
            return {"id": 9}
        if method == "GET" and "comments?" in endpoint:
            return [{"id": 9, "body": posted_body}]
        return next(reads)

    monkeypatch.setattr("scripts.reconcile_blocker_actions._api", fake_api)
    with pytest.raises(RuntimeError, match="post-receipt lifecycle/action drift"):
        apply_plan("o/r", "o", "r", item)


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
