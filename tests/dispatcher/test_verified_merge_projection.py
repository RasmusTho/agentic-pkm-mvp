from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from app.dispatcher import verified_merge
from scripts import await_verified_merge_projection_convergence as await_projection


HEAD = "a" * 40
BASE_SHA = "b" * 40
REPOSITORY = "RasmusTho/agentic-pkm-mvp"
PR_NODE_ID = "PR_kwDOQEip6s4825"
EDIT_NODE_ID = "UCE_kwDOQEip6s4825"


def _context() -> dict[str, object]:
    return {
        "contract": "verification_closer_dispatch_context.v2",
        "run_id": "vrun-projection-convergence",
        "repository": REPOSITORY,
        "pr_number": 3822,
        "governing_issue": 3821,
        "closing_issues": [3820],
        "supporting_issues": [3820],
        "head_sha": HEAD,
        "repair_budget": {
            "policy_version": "v2",
            "mechanisms": [
                {
                    "mechanism_id": "closing-projection-convergence",
                    "failure_domain": "review_code_correctness",
                    "standard_used": 2,
                    "standard_remaining": 0,
                    "escalated_used": 0,
                    "escalated_remaining": 2,
                }
            ],
        },
    }


def _canonical_body() -> str:
    return (
        "Governing-Issue: #3821\n\n"
        "Fixes #3820\n"
        "Refs #3900\n"
    )


def _canonical_pr() -> dict[str, object]:
    return {
        "number": 3822,
        "node_id": PR_NODE_ID,
        "state": "open",
        "merged": False,
        "merged_at": None,
        "draft": False,
        "title": "Fence verified-merge projection convergence",
        "body": _canonical_body(),
        "head": {"sha": HEAD, "ref": "codex/projection-convergence"},
        "base": {"sha": BASE_SHA, "ref": "main"},
    }


def _readiness() -> dict[str, object]:
    return {
        "contract": "verified_issue_set_merge_readiness.v1",
        "further_commits_anticipated": False,
        "head_sha": HEAD,
        "required_checks_green": True,
        "review_gate_resolved": True,
    }


def _observation(
    neutralized_body: str,
    *,
    observed_at: str,
    closing_issues: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "errors": [],
        "rate_limit": {
            "cost": 1,
            "kill_switch_active": False,
            "remaining": 4999,
            "reset_at": "2026-08-12T06:00:00Z",
        },
        "repository": {
            "name_with_owner": REPOSITORY,
            "default_branch": "main",
            "default_branch_sha": BASE_SHA,
        },
        "pull_request": {
            "node_id": PR_NODE_ID,
            "number": 3822,
            "head_sha": HEAD,
            "head_ref": "codex/projection-convergence",
            "base_ref": "main",
            "state": "OPEN",
            "draft": False,
            "title": "Fence verified-merge projection convergence",
            "body": neutralized_body,
            "last_edited_at": "2026-08-12T05:00:00Z",
            "latest_body_edit": {
                "node_id": EDIT_NODE_ID,
                "edited_at": "2026-08-12T05:00:00Z",
                "editor_login": "RasmusTho",
                "editor_association": "OWNER",
            },
            "body_edits_page_info": {"has_next_page": False},
            "closing_issues": closing_issues or [],
            "closing_issues_page_info": {"has_next_page": False},
        },
        "observed_at": observed_at,
    }


def test_projection_convergence_requires_post_edit_pr_contract_and_empty_quorum() -> None:
    plan = verified_merge.prepare_verified_merge(
        context=_context(),
        pr=_canonical_pr(),
        live_closing_issues=[3820],
        merge_readiness=_readiness(),
    )
    authority = plan["authority_receipt"]
    neutralized_body = str(plan["neutralized_body"])
    authority_digest = hashlib.sha256(
        verified_merge.json.dumps(
            authority, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    post_edit_pr_contract = {
        "name": "pr-contract",
        "workflow_run_id": 31563507265,
        "check_run_id": 94010509600,
        "check_suite_id": 85619125108,
        "event": "pull_request",
        "head_sha": HEAD,
        "head_ref": "codex/projection-convergence",
        "base_ref": "main",
        "status": "completed",
        "conclusion": "success",
        "created_at": "2026-08-12T05:00:01Z",
        "started_at": "2026-08-12T05:00:02Z",
        "completed_at": "2026-08-12T05:00:03Z",
        "authority_sha256": authority_digest,
        "neutralized_body_sha256": authority["neutralized_body_sha256"],
        "repository": REPOSITORY,
        "pr_number": 3822,
        "pull_request_node_id": PR_NODE_ID,
        "title": "Fence verified-merge projection convergence",
        "default_branch": "main",
        "default_branch_sha": BASE_SHA,
        "body_edit": {
            "node_id": EDIT_NODE_ID,
            "edited_at": "2026-08-12T05:00:00Z",
            "editor_login": "RasmusTho",
            "editor_association": "OWNER",
        },
    }
    first = _observation(
        neutralized_body, observed_at="2026-08-12T05:00:04Z"
    )
    second = _observation(
        neutralized_body, observed_at="2026-08-12T05:00:06Z"
    )

    result = verified_merge.build_verified_merge_projection_convergence(
        authority_receipt=authority,
        pr_contract=post_edit_pr_contract,
        observations=[first, second],
        minimum_backoff_seconds=1,
    )

    receipt = result["convergence_receipt"]
    assert receipt["contract"] == (
        "verified-merge-closing-projection-convergence.v1"
    )
    assert receipt["authority_sha256"] == authority_digest
    assert receipt["head_sha"] == HEAD
    assert receipt["run_id"] == authority["run_id"]
    assert [row["closing_issues"] for row in receipt["observations"]] == [[], []]
    assert receipt["observation_policy"] == {
        "minimum_backoff_seconds": 1,
        "required_empty_observations": 2,
    }
    assert len(receipt["receipt_sha256"]) == 64


def test_projection_convergence_rejects_regression_drift_and_ambiguous_reads() -> None:
    plan = verified_merge.prepare_verified_merge(
        context=_context(),
        pr=_canonical_pr(),
        live_closing_issues=[3820],
        merge_readiness=_readiness(),
    )
    authority = plan["authority_receipt"]
    neutralized_body = str(plan["neutralized_body"])
    authority_digest = hashlib.sha256(
        verified_merge.json.dumps(
            authority, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    pr_contract = {
        "name": "pr-contract",
        "workflow_run_id": 31563507265,
        "check_run_id": 94010509600,
        "check_suite_id": 85619125108,
        "event": "pull_request",
        "head_sha": HEAD,
        "head_ref": "codex/projection-convergence",
        "base_ref": "main",
        "status": "completed",
        "conclusion": "success",
        "created_at": "2026-08-12T05:00:01Z",
        "started_at": "2026-08-12T05:00:02Z",
        "completed_at": "2026-08-12T05:00:03Z",
        "authority_sha256": authority_digest,
        "neutralized_body_sha256": authority["neutralized_body_sha256"],
        "repository": REPOSITORY,
        "pr_number": 3822,
        "pull_request_node_id": PR_NODE_ID,
        "title": "Fence verified-merge projection convergence",
        "default_branch": "main",
        "default_branch_sha": BASE_SHA,
        "body_edit": {
            "node_id": EDIT_NODE_ID,
            "edited_at": "2026-08-12T05:00:00Z",
            "editor_login": "RasmusTho",
            "editor_association": "OWNER",
        },
    }
    first = _observation(
        neutralized_body, observed_at="2026-08-12T05:00:04Z"
    )
    second = _observation(
        neutralized_body, observed_at="2026-08-12T05:00:06Z"
    )

    rejected: list[tuple[dict[str, object], dict[str, object]]] = []

    regression = copy.deepcopy(second)
    regression["pull_request"]["closing_issues"] = [  # type: ignore[index]
        {"number": 3820, "repository": REPOSITORY}
    ]
    rejected.append((first, regression))

    incomplete = copy.deepcopy(second)
    incomplete["pull_request"]["closing_issues_page_info"] = {  # type: ignore[index]
        "has_next_page": True
    }
    rejected.append((first, incomplete))

    stale_edit = copy.deepcopy(second)
    stale_edit["pull_request"]["latest_body_edit"]["node_id"] = (  # type: ignore[index]
        "UCE_stale"
    )
    rejected.append((first, stale_edit))

    title_drift = copy.deepcopy(second)
    title_drift["pull_request"]["title"] = "Drifted title"  # type: ignore[index]
    rejected.append((first, title_drift))

    main_drift = copy.deepcopy(second)
    main_drift["repository"]["default_branch_sha"] = "c" * 40  # type: ignore[index]
    rejected.append((first, main_drift))

    ambiguous = copy.deepcopy(second)
    ambiguous["errors"] = [{"message": "closing projection unavailable"}]
    rejected.append((first, ambiguous))

    kill_switched = copy.deepcopy(second)
    kill_switched["rate_limit"]["kill_switch_active"] = True  # type: ignore[index]
    rejected.append((first, kill_switched))

    incomplete_edits = copy.deepcopy(second)
    incomplete_edits["pull_request"]["body_edits_page_info"] = {  # type: ignore[index]
        "has_next_page": True
    }
    rejected.append((first, incomplete_edits))

    head_drift = copy.deepcopy(second)
    head_drift["pull_request"]["head_sha"] = "c" * 40  # type: ignore[index]
    rejected.append((first, head_drift))

    base_drift = copy.deepcopy(second)
    base_drift["pull_request"]["base_ref"] = "release"  # type: ignore[index]
    rejected.append((first, base_drift))

    body_drift = copy.deepcopy(second)
    body_drift["pull_request"]["body"] = "drifted"  # type: ignore[index]
    rejected.append((first, body_drift))

    for admitted_first, rejected_second in rejected:
        with pytest.raises(
            ValueError, match="projection convergence is malformed"
        ):
            verified_merge.build_verified_merge_projection_convergence(
                authority_receipt=authority,
                pr_contract=pr_contract,
                observations=[admitted_first, rejected_second],
                minimum_backoff_seconds=1,
            )

    for field, value in (
        ("created_at", "2026-08-12T04:59:59Z"),
        ("event", "workflow_dispatch"),
        ("head_sha", "c" * 40),
        ("conclusion", "cancelled"),
    ):
        stale_contract = copy.deepcopy(pr_contract)
        stale_contract[field] = value
        with pytest.raises(
            ValueError, match="projection convergence is malformed"
        ):
            verified_merge.build_verified_merge_projection_convergence(
                authority_receipt=authority,
                pr_contract=stale_contract,
                observations=[first, second],
                minimum_backoff_seconds=1,
            )


def _projection_fixture() -> tuple[
    dict[str, object],
    str,
    dict[str, object],
    dict[str, object],
]:
    plan = verified_merge.prepare_verified_merge(
        context=_context(),
        pr=_canonical_pr(),
        live_closing_issues=[3820],
        merge_readiness=_readiness(),
    )
    authority = plan["authority_receipt"]
    assert isinstance(authority, dict)
    neutralized_body = str(plan["neutralized_body"])
    authority_digest = hashlib.sha256(
        verified_merge.json.dumps(
            authority, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    pr_contract = {
        "name": "pr-contract",
        "workflow_run_id": 31563507265,
        "check_run_id": 94010509600,
        "check_suite_id": 85619125108,
        "event": "pull_request",
        "head_sha": HEAD,
        "head_ref": "codex/projection-convergence",
        "base_ref": "main",
        "status": "completed",
        "conclusion": "success",
        "created_at": "2026-08-12T05:00:01Z",
        "started_at": "2026-08-12T05:00:02Z",
        "completed_at": "2026-08-12T05:00:03Z",
        "authority_sha256": authority_digest,
        "neutralized_body_sha256": authority["neutralized_body_sha256"],
        "repository": REPOSITORY,
        "pr_number": 3822,
        "pull_request_node_id": PR_NODE_ID,
        "title": "Fence verified-merge projection convergence",
        "default_branch": "main",
        "default_branch_sha": BASE_SHA,
        "body_edit": {
            "node_id": EDIT_NODE_ID,
            "edited_at": "2026-08-12T05:00:00Z",
            "editor_login": "RasmusTho",
            "editor_association": "OWNER",
        },
    }
    convergence = verified_merge.build_verified_merge_projection_convergence(
        authority_receipt=authority,
        pr_contract=pr_contract,
        observations=[
            _observation(
                neutralized_body, observed_at="2026-08-12T05:00:04Z"
            ),
            _observation(
                neutralized_body, observed_at="2026-08-12T05:00:06Z"
            ),
        ],
        minimum_backoff_seconds=1,
    )["convergence_receipt"]
    assert isinstance(convergence, dict)
    return authority, neutralized_body, pr_contract, convergence


def test_prepared_phase_requires_matching_projection_convergence_receipt() -> None:
    authority, neutralized_body, _, convergence = _projection_fixture()
    neutralized_pr = {**_canonical_pr(), "body": neutralized_body}
    final_observation = _observation(
        neutralized_body, observed_at="2026-08-12T05:00:07Z"
    )

    with pytest.raises(ValueError, match="projection convergence"):
        verified_merge.build_verified_merge_phase(
            authority_receipt=authority,
            phase="prepared",
            pr=neutralized_pr,
        )

    prepared = verified_merge.build_verified_merge_phase(
        authority_receipt=authority,
        phase="prepared",
        pr=neutralized_pr,
        projection_convergence_receipt=convergence,
        final_projection_observation=final_observation,
    )
    assert prepared["phase_receipt"]["phase"] == "prepared"
    assert prepared["phase_receipt"]["projection_convergence_sha256"] == (
        convergence["receipt_sha256"]
    )
    assert prepared["phase_receipt"]["final_projection_observation_sha256"] == (
        hashlib.sha256(
            json.dumps(
                final_observation, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()
    )

    replayed_final = copy.deepcopy(final_observation)
    replayed_final["observed_at"] = "2026-08-12T05:00:06Z"
    with pytest.raises(ValueError, match="projection convergence"):
        verified_merge.build_verified_merge_phase(
            authority_receipt=authority,
            phase="prepared",
            pr=neutralized_pr,
            projection_convergence_receipt=convergence,
            final_projection_observation=replayed_final,
        )

    for field, value in (
        ("authority_sha256", "0" * 64),
        ("head_sha", "c" * 40),
        ("run_id", "other-run"),
        ("neutralized_body_sha256", "0" * 64),
    ):
        forged = copy.deepcopy(convergence)
        forged[field] = value
        with pytest.raises(ValueError, match="projection convergence"):
            verified_merge.build_verified_merge_phase(
                authority_receipt=authority,
                phase="prepared",
                pr=neutralized_pr,
                projection_convergence_receipt=forged,
                final_projection_observation=final_observation,
            )

    regressed_final = copy.deepcopy(final_observation)
    regressed_final["pull_request"]["closing_issues"] = [  # type: ignore[index]
        {"number": 3820, "repository": REPOSITORY}
    ]
    with pytest.raises(ValueError, match="projection convergence"):
        verified_merge.build_verified_merge_phase(
            authority_receipt=authority,
            phase="prepared",
            pr=neutralized_pr,
            projection_convergence_receipt=convergence,
            final_projection_observation=regressed_final,
        )


def _trusted_comment(body: str) -> dict[str, object]:
    return {
        "author_association": "OWNER",
        "body": body,
        "created_at": "2026-08-12T05:00:00Z",
        "updated_at": "2026-08-12T05:00:00Z",
    }


def test_restored_unique_authority_resumes_without_duplicate_receipt() -> None:
    plan = verified_merge.prepare_verified_merge(
        context=_context(),
        pr=_canonical_pr(),
        live_closing_issues=[3820],
        merge_readiness=_readiness(),
    )
    authority = plan["authority_receipt"]
    authority_comment = _trusted_comment(str(plan["authority_receipt_comment"]))

    resumed = verified_merge.resume_verified_merge_projection_convergence(
        [authority_comment],
        pr=_canonical_pr(),
        repository=REPOSITORY,
        expected_run_id="vrun-projection-convergence",
    )
    assert resumed == {
        "authority_receipt": authority,
        "authority_receipt_comment": None,
        "authority_receipt_reused": True,
    }

    assert (
        verified_merge.resume_verified_merge_projection_convergence(
            [authority_comment, copy.deepcopy(authority_comment)],
            pr=_canonical_pr(),
            repository=REPOSITORY,
            expected_run_id="vrun-projection-convergence",
        )
        is None
    )

    conflicting = copy.deepcopy(authority)
    conflicting["run_id"] = "conflicting-run"
    conflicting_comment = _trusted_comment(
        "verified issue-set merge authority:\n```json\n"
        + verified_merge.json.dumps(
            conflicting, sort_keys=True, separators=(",", ":")
        )
        + "\n```"
    )
    assert (
        verified_merge.resume_verified_merge_projection_convergence(
            [authority_comment, conflicting_comment],
            pr=_canonical_pr(),
            repository=REPOSITORY,
        )
        is None
    )


def test_projection_timeout_restores_body_without_delivery_effects() -> None:
    plan = verified_merge.prepare_verified_merge(
        context=_context(),
        pr=_canonical_pr(),
        live_closing_issues=[3820],
        merge_readiness=_readiness(),
    )
    authority = plan["authority_receipt"]
    assert isinstance(authority, dict)
    neutralized_pr = {
        **_canonical_pr(),
        "body": str(plan["neutralized_body"]),
    }

    restoration = verified_merge.plan_projection_convergence_failure_restoration(
        authority_receipt=authority,
        pr=neutralized_pr,
        canonical_body=_canonical_body(),
        failure="timeout",
    )

    assert restoration["contract"] == (
        "verified-merge-closing-projection-restoration.v1"
    )
    assert restoration["status"] == "restore_body_only"
    assert restoration["restore_body"] == _canonical_body()
    assert restoration["authority_sha256"] == hashlib.sha256(
        verified_merge.json.dumps(
            authority, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    assert set(restoration) == {
        "authority_sha256",
        "contract",
        "failure",
        "head_sha",
        "pr_number",
        "repository",
        "restore_body",
        "restore_body_sha256",
        "run_id",
        "status",
    }

    drifted = {**neutralized_pr, "head": {"sha": "c" * 40}}
    with pytest.raises(ValueError, match="restoration is malformed"):
        verified_merge.plan_projection_convergence_failure_restoration(
            authority_receipt=authority,
            pr=drifted,
            canonical_body=_canonical_body(),
            failure="timeout",
        )


def test_projection_convergence_cli_is_bounded_and_read_only() -> None:
    source = Path(await_projection.__file__).read_text(encoding="utf-8")

    assert "time.sleep" in source
    assert "is_kill_switch_active" in source
    assert "filter=latest" in source
    assert "_authenticate_unique_authority" in source
    assert "_authenticate_pr_contract" in source
    assert "minimum-backoff-seconds\", type=int, default=60" in source
    for forbidden in (
        "gh pr edit",
        "gh pr merge",
        "gh issue close",
        "gh issue reopen",
        "gh api --method POST",
        "gh api --method PATCH",
        "gh api --method DELETE",
    ):
        assert forbidden not in source


def test_projection_convergence_cli_orders_quorum_and_final_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    authority, neutralized_body, pr_contract, _ = _projection_fixture()
    authority_path = tmp_path / "authority.json"
    pr_contract_path = tmp_path / "pr-contract.json"
    output_path = tmp_path / "convergence.json"
    authority_path.write_text(json.dumps(authority), encoding="utf-8")
    pr_contract_path.write_text(json.dumps(pr_contract), encoding="utf-8")
    snapshots = [
        _observation(neutralized_body, observed_at="2026-08-12T05:00:04Z"),
        _observation(neutralized_body, observed_at="2026-08-12T05:00:06Z"),
        _observation(neutralized_body, observed_at="2026-08-12T05:00:07Z"),
    ]
    clock = [0.0]
    events: list[str] = []

    def authenticate_contract(*args: object, **kwargs: object) -> None:
        events.append("pr-contract")

    def authenticate_authority(*args: object, **kwargs: object) -> None:
        events.append("authority")

    def snapshot(*args: object, **kwargs: object) -> dict[str, object]:
        events.append("snapshot")
        return snapshots.pop(0)

    def sleep(seconds: float) -> None:
        events.append(f"sleep:{seconds:g}")
        clock[0] += seconds

    monkeypatch.setattr(
        await_projection, "_authenticate_pr_contract", authenticate_contract
    )
    monkeypatch.setattr(
        await_projection, "_authenticate_unique_authority", authenticate_authority
    )
    monkeypatch.setattr(await_projection, "_snapshot", snapshot)
    monkeypatch.setattr(await_projection.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(await_projection.time, "sleep", sleep)

    result = await_projection.main(
        [
            "--authority-json",
            str(authority_path),
            "--pr-contract-json",
            str(pr_contract_path),
            "--repository",
            REPOSITORY,
            "--pr-number",
            "3822",
            "--minimum-backoff-seconds",
            "1",
            "--final-backoff-seconds",
            "1",
            "--timeout-seconds",
            "5",
            "--output-json",
            str(output_path),
        ]
    )

    assert result == 0
    assert snapshots == []
    assert events == [
        "pr-contract",
        "snapshot",
        "authority",
        "sleep:1",
        "snapshot",
        "sleep:1",
        "snapshot",
        "authority",
        "pr-contract",
    ]
    output = json.loads(output_path.read_text(encoding="utf-8"))
    assert output["status"] == "converged"
    assert output["convergence_receipt"]["receipt_sha256"]
    assert output["final_projection_observation"]["observed_at"] == (
        "2026-08-12T05:00:07Z"
    )
