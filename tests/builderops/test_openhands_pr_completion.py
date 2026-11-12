from copy import deepcopy

from app.builderops.epic_run_state import create_epic_run_state, load_epic_run_state
from app.builderops.openhands_pr_completion import REPOSITORY, intake, work_identity


def receipt(binding, key="identity"):
    return {"status": "pass", "trusted": True, key: binding, "ref": "durable:1"}


def outcome(result, status):
    return {"status": status, "trusted": True, "operation_id": result["operation_id"], "ref": "durable:outcome"}


def observation(number=1):
    pr = dict(repository=REPOSITORY, number=number, state="open", head_repository=REPOSITORY,
              head_sha="abc", body="contract", draft=False, labels=[], base_ref="main",
              base_sha="def", governing_issue={"body": "issue", "state": "open"},
              reviews=[], verification={}, restrictions=[], owner="none", route="native",
              effect_outcome="none", effect_outcomes={}, ci="success", verify_evidence="pass",
              review_outcome="pass", independent_review_identity=None, closure_authorized=True)
    pr["independent_review_identity"] = work_identity(pr)
    pr["verify_evidence"] = receipt(work_identity(pr))
    pr["ci"] = receipt(pr["head_sha"], "head_sha")
    pr["closure_authorized"] = receipt(work_identity(pr))
    return pr


def setup_run(tmp_path):
    create_epic_run_state(6615, "test-run", root=tmp_path)


def run(tmp_path, prs):
    return intake(prs, run_id="test-run", root=tmp_path, expected_run_id="test-run", expected_root=tmp_path)


def records(tmp_path):
    return load_epic_run_state("test-run", root=tmp_path)["dispatch_decisions"]


def test_intake_preserves_holds_and_progresses_unrelated_prs(tmp_path):
    setup_run(tmp_path)
    held, pending, good = observation(1), observation(2), observation(3)
    held["restrictions"] = ["#6588 hold"]
    pending["ci"] = "pending"
    result = run(tmp_path, [held, pending, good])
    assert [r["action"] for r in result] == ["wait", "wait", "verification-and-closure"]
    assert [r["kind"] for r in records(tmp_path)] == ["openhands_pr_wait", "openhands_pr_wait", "openhands_pr_completion"]


def test_restart_reconciles_effects_without_duplicate_dispatch(tmp_path):
    setup_run(tmp_path)
    pr = observation()
    first = run(tmp_path, [pr])[0]
    second = run(tmp_path, [pr])[0]
    assert second["action"] == "reconcile"
    assert first["operation_id"] == second["operation_id"]
    assert len(records(tmp_path)) == 1


def test_contract_change_reconciles_unknown_then_dispatches_new_review(tmp_path):
    setup_run(tmp_path)
    pr = observation()
    first = run(tmp_path, [pr])[0]
    changed = deepcopy(pr)
    changed["governing_issue"]["body"] = "changed"
    pending = run(tmp_path, [changed])[0]
    assert pending["action"] == "reconcile"
    assert pending["operation_id"] == first["operation_id"]
    changed["effect_outcomes"][first["operation_id"]] = outcome(first, "completed")
    review = run(tmp_path, [changed])[0]
    assert review["action"] == "independent-review"
    assert review["operation_id"] != first["operation_id"]
    assert len(records(tmp_path)) == 2


def test_review_can_run_with_owner_but_repairs_return_to_owner(tmp_path):
    setup_run(tmp_path)
    pr = observation()
    pr.update(owner="active", review_outcome="missing")
    result = run(tmp_path, [pr])[0]
    assert result["action"] == "independent-review"
    pr["effect_outcomes"][result["operation_id"]] = outcome(result, "completed")
    pr.update(review_outcome="changes_requested")
    assert run(tmp_path, [pr])[0]["reason"] == "review repair belongs to current owner"


def test_missing_verify_requests_verification_and_closure_requires_boolean(tmp_path):
    setup_run(tmp_path)
    pr = observation()
    pr["verify_evidence"] = "missing"
    result = run(tmp_path, [pr])[0]
    assert result["action"] == "repository-verification"
    pr["effect_outcomes"][result["operation_id"]] = outcome(result, "completed")
    pr["verify_evidence"] = receipt(work_identity(pr))
    pr["closure_authorized"] = 1
    assert run(tmp_path, [pr])[0]["action"] == "wait"
    pr["closure_authorized"] = receipt(work_identity(pr))
    assert run(tmp_path, [pr])[0]["action"] == "verification-and-closure"


def test_owner_stale_review_unknown_effect_and_executor_fail_closed(tmp_path):
    setup_run(tmp_path)
    variants = []
    for field, value in [("owner", "active"), ("effect_outcome", "unknown"),
                         ("route", "executor"), ("route", "fenced"),
                         ("head_repository", "fork/repo"), ("review_outcome", "unknown")]:
        pr = observation(len(variants) + 1)
        pr[field] = value
        variants.append(pr)
    assert all(r["action"] == "wait" for r in run(tmp_path, variants))
    stale = observation(10)
    stale["independent_review_identity"] = "stale"
    assert run(tmp_path, [stale])[0]["action"] == "independent-review"


def test_stable_identity_and_stale_evidence(tmp_path):
    setup_run(tmp_path)
    pr = observation()
    identity = work_identity(pr)
    pr["reviews"] = [{"user": {"login": "reviewer"}, "state": "APPROVED",
                      "submitted_at": "2026-01-01T00:00:00Z"}]
    pr["verification"] = {"result": "pass"}
    assert work_identity(pr) == identity
    for field in ("ci", "verify_evidence", "closure_authorized"):
        bad = deepcopy(pr)
        bad[field] = receipt("stale", "head_sha" if field == "ci" else "identity")
        assert run(tmp_path, [bad])[0]["action"] == "wait"
    pr["review_outcome"] = "changes_requested"
    assert run(tmp_path, [pr])[0]["action"] == "wait"


def test_no_effect_retry_and_completed_requires_authorization(tmp_path):
    setup_run(tmp_path)
    pr = observation()
    first = run(tmp_path, [pr])[0]
    pr["effect_outcomes"][first["operation_id"]] = outcome(first, "no_effect")
    second = run(tmp_path, [pr])[0]
    assert second["action"] == first["action"]
    assert second["operation_id"] != first["operation_id"]
    pr["effect_outcomes"][second["operation_id"]] = outcome(second, "completed")
    assert run(tmp_path, [pr])[0]["action"] == "reconcile"
    pr["retry_authorization"] = {**receipt(work_identity(pr)), "operation_id": second["operation_id"]}
    assert run(tmp_path, [pr])[0]["action"] == first["action"]


def test_invalid_batch_and_binding(tmp_path):
    import pytest
    setup_run(tmp_path)
    bad = observation(2)
    bad["verification"] = {"bad": object()}
    result = run(tmp_path, [observation(1), bad, observation(3)])
    assert [r["action"] for r in result] == ["verification-and-closure", "wait", "verification-and-closure"]
    with pytest.raises(ValueError, match="authority"):
        intake([observation()], run_id="other", root=tmp_path, expected_run_id="test-run", expected_root=tmp_path)
    with pytest.raises(ValueError, match="authority"):
        intake([observation()], run_id="test-run", root=tmp_path / "other", expected_run_id="test-run", expected_root=tmp_path)


def test_governing_issue_contract_is_validated_before_reservation(tmp_path):
    setup_run(tmp_path)
    invalid = [None, {}, {"body": "issue"}, {"state": "open"},
               {"body": None, "state": None}, {"body": 1, "state": "open"},
               {"body": "  ", "state": "open"}, {"body": "issue", "state": 1},
               {"body": "issue", "state": "unknown"}]
    batch = []
    for number, issue in enumerate(invalid, 1):
        pr = observation(number)
        pr["governing_issue"] = issue
        # Simulate trusted receipts bound to the malformed contract itself.
        identity = work_identity(pr)
        pr.update(independent_review_identity=identity, verify_evidence=receipt(identity),
                  closure_authorized=receipt(identity))
        batch.append(pr)
    good = observation(len(batch) + 1)
    good["governing_issue"]["state"] = "closed"
    identity = work_identity(good)
    good.update(independent_review_identity=identity, verify_evidence=receipt(identity),
                closure_authorized=receipt(identity))
    results = run(tmp_path, [*batch, good])
    assert all(r["action"] == "wait" and r["reason"] == "invalid PR observation"
               and r["operation_id"] is None for r in results[:-1])
    assert results[-1]["action"] == "verification-and-closure"
    assert [r["number"] for r in records(tmp_path)] == [good["number"]]


def test_concurrent_callers_share_reservation(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    setup_run(tmp_path)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: run(tmp_path, [observation()])[0], range(2)))
    assert sorted(r["action"] for r in results) == ["reconcile", "verification-and-closure"]
    assert len(records(tmp_path)) == 1


def test_raw_reviews_gate_conflicting_receipt_and_handle_review_states(tmp_path):
    setup_run(tmp_path)
    def review(state, day, user="reviewer"):
        return {"user": {"login": user}, "state": state,
                "submitted_at": f"2026-01-{day:02d}T00:00:00Z"}

    blocked = observation(1)
    blocked["reviews"] = [review("CHANGES_REQUESTED", 1)]
    approved = observation(2)
    approved["reviews"] = [review("CHANGES_REQUESTED", 1), review("APPROVED", 2)]
    dismissed = observation(3)
    dismissed["reviews"] = [review("DISMISSED", 1)]
    malformed = observation(4)
    malformed["reviews"] = [review("UNKNOWN", 1)]
    commented = observation(5)
    commented["reviews"] = [review("CHANGES_REQUESTED", 1), review("COMMENTED", 2)]
    results = run(tmp_path, [blocked, approved, dismissed, malformed, commented])
    assert [r["action"] for r in results] == ["wait", "verification-and-closure",
        "verification-and-closure", "wait", "wait"]
    assert results[0]["reason"] == "review repair belongs to current owner"
    assert results[3]["reason"] == "invalid PR observation"
    assert work_identity(blocked) == blocked["independent_review_identity"]


def test_recursive_observation_does_not_stop_next_pr(tmp_path, monkeypatch):
    setup_run(tmp_path)
    bad = observation(1)
    import json.encoder
    import sys
    monkeypatch.setattr(json.encoder, "c_make_encoder", None)
    nested = []
    for _ in range(sys.getrecursionlimit() + 100):
        nested = [nested]
    bad["verification"] = {"nested": nested}
    results = run(tmp_path, [bad, observation(2)])
    assert [r["action"] for r in results] == ["wait", "verification-and-closure"]
    assert results[0]["reason"] == "invalid PR observation"
    assert results[1]["operation_id"]
