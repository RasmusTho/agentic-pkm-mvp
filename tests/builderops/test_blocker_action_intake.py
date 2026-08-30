import json
import subprocess
import sys

from app.builderops.blocker_actions import intake, receipt_for_action


def _comment(action: str) -> dict[str, str]:
    receipt = receipt_for_action(action)
    return {"body": "```yaml\n" + "\n".join(
        f"{key}: {value if key != 'dependency_refs' else '[]'}"
        for key, value in receipt.items()
    ) + "\n```"}


def test_intake_routes_every_canonical_action_without_claiming() -> None:
    actions = ["action:repair-contract", "action:wait-dependency", "action:restore-environment", "action:wait-external", "action:review-at", "action:human-decision", "action:human-authorization", "action:human-access", "action:human-operation", "action:human-acceptance"]
    issues = []
    for index, action in enumerate(actions, 1):
        receipt = receipt_for_action(action)
        comment = {"body": "```yaml\n" + "\n".join(f"{key}: {value if key != 'dependency_refs' else '[]'}" for key, value in receipt.items()) + "\n```"}
        issues.append({"number": index, "title": action, "state": "open", "labels": ["agent:blocked" if "human" not in action else "agent:needs-human", action], "comments": [comment]})
    payload = intake(issues)
    assert not payload["drift"]
    assert set(payload["queues"]) == set(actions)
    assert all(item["claim_posture"].startswith("read-only") for queue in payload["queues"].values() for item in queue)


def test_report_surface_is_rest_oriented_and_read_only() -> None:
    from pathlib import Path
    script = (Path(__file__).resolve().parents[2] / "scripts/report_blocker_actions.py").read_text()
    assert '"gh", "api"' in script
    assert "claim" not in script.lower().replace("read-only", "")


def test_report_entrypoint_rejects_noncanonical_owner_receipts(monkeypatch, capsys) -> None:
    from scripts import report_blocker_actions

    invalid = """```yaml
receipt: blocker_action.v1
action: action:wait-dependency
owner: builder-system-maintenance
next_action: wait
unblocks_when: dependency closes
dependency_refs: []
review_at: null
last_verified_at: 2026-08-30T11:00:00Z
```"""
    responses = iter([
        subprocess.CompletedProcess([], 0, json.dumps([{"number": 71, "state": "open", "labels": [{"name": "agent:blocked"}, {"name": "action:wait-dependency"}]}]), ""),
        subprocess.CompletedProcess([], 0, json.dumps([{"body": invalid}]), ""),
    ])
    monkeypatch.setattr(report_blocker_actions.subprocess, "run", lambda *args, **kwargs: next(responses))
    monkeypatch.setattr(sys, "argv", ["report_blocker_actions.py", "--repo", "o/r"])

    assert report_blocker_actions.main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["drift"][0]["owner"] is None
    assert payload["drift"][0]["next_action"] is None


def test_intake_rejects_receipts_that_do_not_bind_to_live_action_context() -> None:
    cases = [
        (["agent:blocked", "action:wait-dependency"], "action:human-decision", "receipt_action_mismatch"),
        (["agent:blocked", "action:wait-dependency"], "action:repair-contract", "receipt_action_mismatch"),
        (["agent:blocked", "action:wait-dependency", "action:wait-external"], "action:wait-dependency", "multiple_action_labels"),
        (["agent:blocked"], "action:wait-dependency", "missing_action_label"),
        (["agent:blocked", "agent:needs-human", "action:wait-dependency"], "action:wait-dependency", "action_without_blocker_lifecycle"),
    ]
    for labels, receipt_action, expected_error in cases:
        payload = intake([{"number": 71, "state": "open", "labels": labels, "comments": [_comment(receipt_action)]}])
        item = payload["drift"][0]
        assert expected_error in item["errors"]
        assert item["owner"] is None and item["next_action"] is None
        assert not any(payload["queues"].values())


def test_report_entrypoint_keeps_mismatched_receipt_out_of_label_queue(monkeypatch, capsys) -> None:
    from scripts import report_blocker_actions

    responses = iter([
        subprocess.CompletedProcess([], 0, json.dumps([{"number": 72, "state": "open", "labels": [{"name": "agent:blocked"}, {"name": "action:wait-dependency"}]}]), ""),
        subprocess.CompletedProcess([], 0, json.dumps([_comment("action:human-decision")]), ""),
    ])
    monkeypatch.setattr(report_blocker_actions.subprocess, "run", lambda *args, **kwargs: next(responses))
    monkeypatch.setattr(sys, "argv", ["report_blocker_actions.py", "--repo", "o/r"])

    assert report_blocker_actions.main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert not payload["queues"]["action:wait-dependency"]
    assert payload["drift"][0]["errors"] == ["receipt_action_mismatch"]
