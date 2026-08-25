from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping
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
        final_projection_observation=_observation(
            neutralized_body, observed_at="2026-08-12T05:00:07Z"
        ),
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


def test_projection_convergence_allows_same_second_edit_and_workflow_creation() -> None:
    authority, neutralized_body, pr_contract, _ = _projection_fixture()
    pr_contract["created_at"] = "2026-08-12T05:00:00Z"
    pr_contract["started_at"] = "2026-08-12T05:00:00Z"
    pr_contract["completed_at"] = "2026-08-12T05:00:00Z"

    result = verified_merge.build_verified_merge_projection_convergence(
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
        final_projection_observation=_observation(
            neutralized_body, observed_at="2026-08-12T05:00:07Z"
        ),
        minimum_backoff_seconds=1,
    )

    assert result["convergence_receipt"]["pr_contract"] == pr_contract

    neutralized_pr = {**_canonical_pr(), "body": neutralized_body}
    prepared = verified_merge.build_verified_merge_phase(
        authority_receipt=authority,
        phase="prepared",
        pr=neutralized_pr,
        projection_convergence_receipt=result["convergence_receipt"],
        final_projection_observation=_observation(
            neutralized_body, observed_at="2026-08-12T05:00:07Z"
        ),
    )
    resolved = verified_merge.resolve_verified_merge_phase(
        [
            _trusted_convergence_comment(result["convergence_receipt"]),
            _trusted_comment(str(prepared["phase_receipt_comment"])),
        ],
        authority_receipt=authority,
        pr=neutralized_pr,
    )
    assert resolved == prepared["phase_receipt"]


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
                final_projection_observation=_observation(
                    neutralized_body, observed_at="2026-08-12T05:00:07Z"
                ),
                minimum_backoff_seconds=1,
            )

    for field, value in (
        ("created_at", "2026-08-12T04:59:59Z"),
        ("completed_at", "2026-08-12T05:00:05Z"),
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
                final_projection_observation=_observation(
                    neutralized_body, observed_at="2026-08-12T05:00:07Z"
                ),
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
        final_projection_observation=_observation(
            neutralized_body, observed_at="2026-08-12T05:00:07Z"
        ),
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


def _trusted_convergence_comment(
    convergence: Mapping[str, object],
    *,
    association: str = "OWNER",
) -> dict[str, object]:
    return {
        "author_association": association,
        "body": (
            "verified merge closing projection convergence:\n```json\n"
            + json.dumps(convergence, sort_keys=True, separators=(",", ":"))
            + "\n```"
        ),
        "created_at": "2026-08-12T05:00:06Z",
        "updated_at": "2026-08-12T05:00:06Z",
    }


def test_unique_authority_authentication_allows_current_replacement_after_stale_prepared_phase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority, neutralized_body, stale_contract, stale_convergence = (
        _projection_fixture()
    )
    stale_prepared = verified_merge.build_verified_merge_phase(
        authority_receipt=authority,
        phase="prepared",
        pr={**_canonical_pr(), "body": neutralized_body},
        projection_convergence_receipt=stale_convergence,
        final_projection_observation=_observation(
            neutralized_body, observed_at="2026-08-12T05:00:07Z"
        ),
    )["phase_receipt"]

    replacement_contract = copy.deepcopy(stale_contract)
    replacement_edit = replacement_contract["body_edit"]
    assert isinstance(replacement_edit, dict)
    replacement_edit["node_id"] = "UCE_kwDOQEip6s4825_replacement"
    replacement_edit["edited_at"] = "2026-08-12T05:00:08Z"
    replacement_contract["created_at"] = "2026-08-12T05:00:08Z"
    replacement_contract["started_at"] = "2026-08-12T05:00:09Z"
    replacement_contract["completed_at"] = "2026-08-12T05:00:10Z"
    replacement_observations = [
        copy.deepcopy(_observation(neutralized_body, observed_at=observed_at))
        for observed_at in (
            "2026-08-12T05:00:11Z",
            "2026-08-12T05:00:12Z",
            "2026-08-12T05:00:13Z",
        )
    ]
    for observation in replacement_observations:
        pull_request = observation["pull_request"]
        assert isinstance(pull_request, dict)
        pull_request["latest_body_edit"] = copy.deepcopy(replacement_edit)
        pull_request["last_edited_at"] = replacement_edit["edited_at"]
    replacement_convergence = verified_merge.build_verified_merge_projection_convergence(
        authority_receipt=authority,
        pr_contract=replacement_contract,
        observations=replacement_observations[:2],
        final_projection_observation=replacement_observations[2],
        minimum_backoff_seconds=1,
    )["convergence_receipt"]
    assert isinstance(replacement_convergence, dict)

    comments = [
        _trusted_comment(
            "verified issue-set merge authority:\n```json\n"
            + json.dumps(authority, sort_keys=True, separators=(",", ":"))
            + "\n```"
        ),
        _trusted_convergence_comment(stale_convergence),
        _trusted_comment(
            "verified issue-set merge phase:\n```json\n"
            + json.dumps(stale_prepared, sort_keys=True, separators=(",", ":"))
            + "\n```"
        ),
        _trusted_convergence_comment(replacement_convergence),
    ]
    monkeypatch.setattr(await_projection, "_comments", lambda *args, **kwargs: comments)

    assert await_projection._authenticate_unique_authority(
        "gh",
        repository=REPOSITORY,
        authority=authority,
        snapshot=replacement_observations[2],
        pr_contract=replacement_contract,
    ) == replacement_convergence


def test_phase_recovery_requires_authenticated_durable_convergence_receipt() -> None:
    authority, neutralized_body, _, convergence = _projection_fixture()
    neutralized_pr = {**_canonical_pr(), "body": neutralized_body}
    prepared = verified_merge.build_verified_merge_phase(
        authority_receipt=authority,
        phase="prepared",
        pr=neutralized_pr,
        projection_convergence_receipt=convergence,
        final_projection_observation=_observation(
            neutralized_body, observed_at="2026-08-12T05:00:07Z"
        ),
    )["phase_receipt"]
    prepared_comment = _trusted_comment(
        "verified issue-set merge phase:\n```json\n"
        + json.dumps(prepared, sort_keys=True, separators=(",", ":"))
        + "\n```"
    )

    assert verified_merge.resolve_verified_merge_phase(
        [prepared_comment],
        authority_receipt=authority,
        pr=neutralized_pr,
    ) is None

    untrusted = _trusted_convergence_comment(convergence, association="NONE")
    assert verified_merge.resolve_verified_merge_phase(
        [untrusted, prepared_comment],
        authority_receipt=authority,
        pr=neutralized_pr,
    ) is None

    forged = copy.deepcopy(convergence)
    forged["observations"][0]["closing_issues"] = [3820]  # type: ignore[index]
    forged_comment = _trusted_convergence_comment(forged)
    assert verified_merge.resolve_verified_merge_phase(
        [forged_comment, prepared_comment],
        authority_receipt=authority,
        pr=neutralized_pr,
    ) is None

    mismatched = copy.deepcopy(prepared)
    mismatched["projection_convergence_sha256"] = "f" * 64
    mismatched_comment = _trusted_comment(
        "verified issue-set merge phase:\n```json\n"
        + json.dumps(mismatched, sort_keys=True, separators=(",", ":"))
        + "\n```"
    )
    durable_comment = _trusted_convergence_comment(convergence)
    assert verified_merge.resolve_verified_merge_phase(
        [durable_comment, mismatched_comment],
        authority_receipt=authority,
        pr=neutralized_pr,
    ) is None
    assert verified_merge.resolve_verified_merge_phase(
        [durable_comment, prepared_comment],
        authority_receipt=authority,
        pr=neutralized_pr,
    ) == prepared


def test_phase_recovery_rejects_mismatched_final_observation_digest() -> None:
    authority, neutralized_body, _, convergence = _projection_fixture()
    neutralized_pr = {**_canonical_pr(), "body": neutralized_body}
    prepared = verified_merge.build_verified_merge_phase(
        authority_receipt=authority,
        phase="prepared",
        pr=neutralized_pr,
        projection_convergence_receipt=convergence,
        final_projection_observation=_observation(
            neutralized_body, observed_at="2026-08-12T05:00:07Z"
        ),
    )["phase_receipt"]
    forged_prepared = {
        **prepared,
        "final_projection_observation_sha256": "f" * 64,
    }

    assert verified_merge.resolve_verified_merge_phase(
        [
            _trusted_convergence_comment(convergence),
            _trusted_comment(
                "verified issue-set merge phase:\n```json\n"
                + json.dumps(
                    forged_prepared, sort_keys=True, separators=(",", ":")
                )
                + "\n```"
            ),
        ],
        authority_receipt=authority,
        pr=neutralized_pr,
    ) is None


def test_phase_recovery_rejects_extra_current_schema_fields_beside_valid_chain() -> None:
    authority, neutralized_body, _, convergence = _projection_fixture()
    neutralized_pr = {**_canonical_pr(), "body": neutralized_body}
    prepared = verified_merge.build_verified_merge_phase(
        authority_receipt=authority,
        phase="prepared",
        pr=neutralized_pr,
        projection_convergence_receipt=convergence,
        final_projection_observation=_observation(
            neutralized_body, observed_at="2026-08-12T05:00:07Z"
        ),
    )["phase_receipt"]
    malformed_prepared = {**prepared, "unexpected": "current-schema-extension"}

    assert verified_merge.resolve_verified_merge_phase(
        [
            _trusted_convergence_comment(convergence),
            _trusted_comment(
                "verified issue-set merge phase:\n```json\n"
                + json.dumps(prepared, sort_keys=True, separators=(",", ":"))
                + "\n```"
            ),
            _trusted_comment(
                "verified issue-set merge phase:\n```json\n"
                + json.dumps(
                    malformed_prepared, sort_keys=True, separators=(",", ":")
                )
                + "\n```"
            ),
        ],
        authority_receipt=authority,
        pr=neutralized_pr,
    ) is None


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


def test_projection_convergence_cli_is_bounded_and_posts_only_its_receipt() -> None:
    source = Path(await_projection.__file__).read_text(encoding="utf-8")

    assert "time.sleep" in source
    assert "is_kill_switch_active" in source
    assert "filter=latest" in source
    assert "_authenticate_unique_authority" in source
    assert "_authenticate_pr_contract" in source
    assert "_post_convergence_receipt" in source
    assert '"POST"' in source
    assert "minimum-backoff-seconds\", type=int, default=60" in source
    for forbidden in (
        "gh pr edit",
        "gh pr merge",
        "gh issue close",
        "gh issue reopen",
        "gh api --method PATCH",
        "gh api --method DELETE",
    ):
        assert forbidden not in source


def _github_pr_contract_records(
    pr_contract: dict[str, object],
    *,
    latest_rows: list[object],
) -> list[dict[str, object]]:
    pull_request = {
        "number": pr_contract["pr_number"],
        "head": {
            "sha": pr_contract["head_sha"],
            "ref": pr_contract["head_ref"],
        },
        "base": {"ref": pr_contract["base_ref"]},
    }
    workflow_run_id = pr_contract["workflow_run_id"]
    return [
        {
            "id": workflow_run_id,
            "name": "Issue and PR Governance",
            "path": ".github/workflows/issue-pr-governance.yml",
            "event": "pull_request",
            "head_sha": pr_contract["head_sha"],
            "head_branch": pr_contract["head_ref"],
            "status": "completed",
            "conclusion": "success",
            "created_at": pr_contract["created_at"],
            "check_suite_id": pr_contract["check_suite_id"],
            "repository": {"full_name": REPOSITORY},
            "pull_requests": [pull_request],
        },
        {
            "id": pr_contract["check_run_id"],
            "name": "pr-contract",
            "head_sha": pr_contract["head_sha"],
            "status": "completed",
            "conclusion": "success",
            "started_at": pr_contract["started_at"],
            "completed_at": pr_contract["completed_at"],
            "check_suite": {"id": pr_contract["check_suite_id"]},
            "app": {"slug": "github-actions"},
            "details_url": (
                f"https://github.com/{REPOSITORY}/actions/runs/"
                f"{workflow_run_id}/job/1"
            ),
            "pull_requests": [pull_request],
        },
        {"total_count": len(latest_rows), "check_runs": latest_rows},
    ]


def test_pr_contract_authentication_selects_requested_id_from_multi_suite_latest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, pr_contract, _ = _projection_fixture()
    records = _github_pr_contract_records(
        pr_contract,
        latest_rows=[
            {"id": 94010509599, "check_suite": {"id": 85619125107}},
            {
                "id": pr_contract["check_run_id"],
                "check_suite": {"id": pr_contract["check_suite_id"]},
            },
        ],
    )
    monkeypatch.setattr(await_projection, "_run_json", lambda *args: records.pop(0))

    await_projection._authenticate_pr_contract(
        "gh", repository=REPOSITORY, pr_contract=pr_contract
    )


@pytest.mark.parametrize(
    "latest_rows",
    (
        [{"id": 94010509599}],
        [{"id": 94010509600}, {"id": 94010509600}],
    ),
    ids=("requested-id-missing", "requested-id-duplicated"),
)
def test_pr_contract_authentication_rejects_missing_or_duplicate_requested_id(
    latest_rows: list[object], monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, pr_contract, _ = _projection_fixture()
    records = _github_pr_contract_records(
        pr_contract, latest_rows=latest_rows
    )
    monkeypatch.setattr(await_projection, "_run_json", lambda *args: records.pop(0))

    with pytest.raises(ValueError, match="stale or unauthenticated"):
        await_projection._authenticate_pr_contract(
            "gh", repository=REPOSITORY, pr_contract=pr_contract
        )


def test_projection_convergence_cli_orders_quorum_and_final_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    authority, neutralized_body, pr_contract, durable_convergence = (
        _projection_fixture()
    )
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

    authority_reads = [None, None, durable_convergence]

    def authenticate_authority(
        *args: object, **kwargs: object
    ) -> dict[str, object] | None:
        events.append("authority")
        return authority_reads.pop(0)

    def post_receipt(*args: object, **kwargs: object) -> dict[str, object]:
        events.append("post")
        return {
            "author_association": "OWNER",
            "body": kwargs["comment_body"],
        }

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
    monkeypatch.setattr(
        await_projection, "_post_convergence_receipt", post_receipt
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
        "post",
        "authority",
    ]
    output = json.loads(output_path.read_text(encoding="utf-8"))
    assert output["status"] == "converged"
    assert output["convergence_receipt"]["receipt_sha256"]
    assert output["final_projection_observation"]["observed_at"] == (
        "2026-08-12T05:00:07Z"
    )
    terminal_output = json.loads(capsys.readouterr().out)
    assert terminal_output == {"status": "converged"}
    assert neutralized_body not in json.dumps(terminal_output)
    assert authority_reads == []


def test_projection_convergence_cli_reuses_post_comment_crash_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    authority, neutralized_body, pr_contract, durable_convergence = (
        _projection_fixture()
    )
    authority_path = tmp_path / "authority.json"
    pr_contract_path = tmp_path / "pr-contract.json"
    output_path = tmp_path / "convergence.json"
    authority_path.write_text(json.dumps(authority), encoding="utf-8")
    pr_contract_path.write_text(json.dumps(pr_contract), encoding="utf-8")
    snapshots = [
        _observation(neutralized_body, observed_at="2026-08-12T05:00:07Z"),
        _observation(neutralized_body, observed_at="2026-08-12T05:00:08Z"),
    ]
    clock = [0.0]
    events: list[str] = []

    monkeypatch.setattr(
        await_projection,
        "_authenticate_pr_contract",
        lambda *args, **kwargs: events.append("pr-contract"),
    )

    def authenticate_authority(
        *args: object, **kwargs: object
    ) -> dict[str, object]:
        events.append("authority")
        return durable_convergence

    monkeypatch.setattr(
        await_projection, "_authenticate_unique_authority", authenticate_authority
    )
    monkeypatch.setattr(
        await_projection,
        "_post_convergence_receipt",
        lambda *args, **kwargs: pytest.fail("durable receipt must not be duplicated"),
    )
    monkeypatch.setattr(
        await_projection,
        "_snapshot",
        lambda *args, **kwargs: (events.append("snapshot"), snapshots.pop(0))[1],
    )
    monkeypatch.setattr(await_projection.time, "monotonic", lambda: clock[0])

    def sleep(seconds: float) -> None:
        events.append(f"sleep:{seconds:g}")
        clock[0] += seconds

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
        "authority",
        "pr-contract",
    ]
    output = json.loads(output_path.read_text(encoding="utf-8"))
    assert output["convergence_receipt"] == durable_convergence
    assert output["convergence_receipt_comment"] is None


def test_projection_convergence_cli_failure_stdout_redacts_restoration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    authority, neutralized_body, pr_contract, _ = _projection_fixture()
    authority_path = tmp_path / "authority.json"
    pr_contract_path = tmp_path / "pr-contract.json"
    canonical_body_path = tmp_path / "canonical-body.md"
    output_path = tmp_path / "convergence.json"
    authority_path.write_text(json.dumps(authority), encoding="utf-8")
    pr_contract_path.write_text(json.dumps(pr_contract), encoding="utf-8")
    canonical_body_path.write_text(_canonical_body(), encoding="utf-8")

    monkeypatch.setattr(
        await_projection,
        "_authenticate_pr_contract",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            ValueError("forced convergence failure")
        ),
    )
    monkeypatch.setattr(
        await_projection,
        "_snapshot",
        lambda *args, **kwargs: {
            "pull_request": {
                "number": 3822,
                "state": "OPEN",
                "head_sha": HEAD,
                "body": neutralized_body,
            }
        },
    )

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
            "--canonical-body-file",
            str(canonical_body_path),
            "--output-json",
            str(output_path),
        ]
    )

    assert result == 3
    output = json.loads(output_path.read_text(encoding="utf-8"))
    assert output["restoration"]["restore_body"] == _canonical_body()
    assert json.loads(capsys.readouterr().out) == {"status": "failed_closed"}


def test_projection_convergence_cli_rebuilds_after_body_edit_aba(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    authority, neutralized_body, old_pr_contract, durable_convergence = (
        _projection_fixture()
    )
    current_pr_contract = copy.deepcopy(old_pr_contract)
    current_body_edit = {
        "node_id": "UCE_kwDOQEip6s4825_aba",
        "edited_at": "2026-08-12T05:10:00Z",
        "editor_login": "RasmusTho",
        "editor_association": "OWNER",
    }
    current_pr_contract.update(
        {
            "created_at": "2026-08-12T05:10:01Z",
            "started_at": "2026-08-12T05:10:02Z",
            "completed_at": "2026-08-12T05:10:03Z",
            "body_edit": current_body_edit,
        }
    )
    authority_path = tmp_path / "authority.json"
    pr_contract_path = tmp_path / "pr-contract.json"
    output_path = tmp_path / "convergence.json"
    authority_path.write_text(json.dumps(authority), encoding="utf-8")
    pr_contract_path.write_text(
        json.dumps(current_pr_contract), encoding="utf-8"
    )

    def current_observation(observed_at: str) -> dict[str, object]:
        observation = _observation(
            neutralized_body, observed_at=observed_at
        )
        pull_request = observation["pull_request"]
        assert isinstance(pull_request, dict)
        pull_request["last_edited_at"] = current_body_edit["edited_at"]
        pull_request["latest_body_edit"] = dict(current_body_edit)
        return observation

    snapshots = [
        current_observation("2026-08-12T05:10:04Z"),
        current_observation("2026-08-12T05:10:06Z"),
        current_observation("2026-08-12T05:10:07Z"),
    ]
    clock = [0.0]
    events: list[str] = []
    replacement_convergence = (
        verified_merge.build_verified_merge_projection_convergence(
            authority_receipt=authority,
            pr_contract=current_pr_contract,
            observations=snapshots[:2],
            final_projection_observation=snapshots[2],
            minimum_backoff_seconds=1,
        )["convergence_receipt"]
    )
    historical_and_current_comments = [
        _trusted_convergence_comment(durable_convergence),
        _trusted_convergence_comment(replacement_convergence),
    ]
    assert verified_merge.resolve_verified_merge_projection_convergence_receipt(
        historical_and_current_comments,
        authority_receipt=authority,
        pr_contract=current_pr_contract,
    ) == replacement_convergence
    assert verified_merge.resolve_verified_merge_projection_convergence_receipt(
        historical_and_current_comments, authority_receipt=authority
    ) == replacement_convergence
    authority_reads = iter(
        [durable_convergence, durable_convergence, replacement_convergence]
    )
    monkeypatch.setattr(
        await_projection,
        "_authenticate_pr_contract",
        lambda *args, **kwargs: events.append("pr-contract"),
    )
    monkeypatch.setattr(
        await_projection,
        "_authenticate_unique_authority",
        lambda *args, **kwargs: (
            events.append("authority"),
            next(authority_reads),
        )[1],
    )
    monkeypatch.setattr(
        await_projection,
        "build_verified_merge_projection_convergence",
        lambda *args, **kwargs: {
            "convergence_receipt": replacement_convergence,
            "convergence_receipt_comment": "replacement",
        },
    )
    monkeypatch.setattr(
        await_projection,
        "_post_convergence_receipt",
        lambda *args, **kwargs: events.append("post"),
    )
    monkeypatch.setattr(
        await_projection,
        "_snapshot",
        lambda *args, **kwargs: (
            events.append("snapshot"),
            snapshots.pop(0),
        )[1],
    )
    monkeypatch.setattr(await_projection.time, "monotonic", lambda: clock[0])

    def sleep(seconds: float) -> None:
        events.append(f"sleep:{seconds:g}")
        clock[0] += seconds

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
        "post",
        "authority",
    ]
    output = json.loads(output_path.read_text(encoding="utf-8"))
    assert output["status"] == "converged"
    assert output["convergence_receipt"] == replacement_convergence


def test_phase_recovery_binds_same_second_aba_replacement_by_receipt_digest() -> None:
    authority, neutralized_body, stale_pr_contract, stale_convergence = (
        _projection_fixture()
    )
    current_pr_contract = copy.deepcopy(stale_pr_contract)
    current_body_edit = dict(current_pr_contract["body_edit"])
    current_body_edit["node_id"] = "UCE_kwDOQEip6s4825_same_second_aba"
    current_pr_contract["body_edit"] = current_body_edit

    def current_observation(observed_at: str) -> dict[str, object]:
        observation = _observation(
            neutralized_body, observed_at=observed_at
        )
        pull_request = observation["pull_request"]
        assert isinstance(pull_request, dict)
        pull_request["latest_body_edit"] = current_body_edit
        return observation

    replacement_convergence = (
        verified_merge.build_verified_merge_projection_convergence(
            authority_receipt=authority,
            pr_contract=current_pr_contract,
            observations=[
                current_observation("2026-08-12T05:00:04Z"),
                current_observation("2026-08-12T05:00:06Z"),
            ],
            final_projection_observation=current_observation(
                "2026-08-12T05:00:07Z"
            ),
            minimum_backoff_seconds=1,
        )["convergence_receipt"]
    )
    neutralized_pr = {**_canonical_pr(), "body": neutralized_body}
    stale_prepared = verified_merge.build_verified_merge_phase(
        authority_receipt=authority,
        phase="prepared",
        pr=neutralized_pr,
        projection_convergence_receipt=stale_convergence,
        final_projection_observation=_observation(
            neutralized_body, observed_at="2026-08-12T05:00:07Z"
        ),
    )
    prepared = verified_merge.build_verified_merge_phase(
        authority_receipt=authority,
        phase="prepared",
        pr=neutralized_pr,
        projection_convergence_receipt=replacement_convergence,
        final_projection_observation=current_observation("2026-08-12T05:00:07Z"),
    )

    comments = [
        _trusted_convergence_comment(stale_convergence),
        _trusted_convergence_comment(replacement_convergence),
        _trusted_comment(str(stale_prepared["phase_receipt_comment"])),
        _trusted_comment(str(prepared["phase_receipt_comment"])),
    ]

    assert verified_merge.resolve_verified_merge_phase(
        comments,
        authority_receipt=authority,
        pr=neutralized_pr,
    ) is None
    assert verified_merge.resolve_verified_merge_phase(
        comments,
        authority_receipt=authority,
        pr=neutralized_pr,
        current_body_edit=current_body_edit,
    ) == prepared["phase_receipt"]
    assert verified_merge.resolve_verified_merge_phase(
        [
            *comments,
            _trusted_convergence_comment(replacement_convergence),
        ],
        authority_receipt=authority,
        pr=neutralized_pr,
        current_body_edit=current_body_edit,
    ) is None


def test_post_merge_rejects_discontinuous_historical_current_schema_chain() -> None:
    authority, neutralized_body, stale_pr_contract, stale_convergence = (
        _projection_fixture()
    )
    current_pr_contract = copy.deepcopy(stale_pr_contract)
    current_body_edit = dict(current_pr_contract["body_edit"])
    current_body_edit["node_id"] = "UCE_kwDOQEip6s4825_discontinuous_history"
    current_pr_contract["body_edit"] = current_body_edit

    def current_observation(observed_at: str) -> dict[str, object]:
        observation = _observation(neutralized_body, observed_at=observed_at)
        pull_request = observation["pull_request"]
        assert isinstance(pull_request, dict)
        pull_request["latest_body_edit"] = current_body_edit
        return observation

    replacement_convergence = (
        verified_merge.build_verified_merge_projection_convergence(
            authority_receipt=authority,
            pr_contract=current_pr_contract,
            observations=[
                current_observation("2026-08-12T05:00:04Z"),
                current_observation("2026-08-12T05:00:06Z"),
            ],
            final_projection_observation=current_observation(
                "2026-08-12T05:00:07Z"
            ),
            minimum_backoff_seconds=1,
        )["convergence_receipt"]
    )
    neutralized_pr = {**_canonical_pr(), "body": neutralized_body}
    merged_pr = {
        **neutralized_pr,
        "state": "closed",
        "merged": True,
        "merged_at": "2026-08-12T05:00:08Z",
        "merge_commit_sha": "c" * 40,
    }
    stale_merged = verified_merge.build_verified_merge_phase(
        authority_receipt=authority,
        phase="merged",
        pr=merged_pr,
        projection_convergence_receipt=stale_convergence,
    )
    replacement_prepared = verified_merge.build_verified_merge_phase(
        authority_receipt=authority,
        phase="prepared",
        pr=neutralized_pr,
        projection_convergence_receipt=replacement_convergence,
        final_projection_observation=current_observation("2026-08-12T05:00:07Z"),
    )
    replacement_merged = verified_merge.build_verified_merge_phase(
        authority_receipt=authority,
        phase="merged",
        pr=merged_pr,
        projection_convergence_receipt=replacement_convergence,
    )

    assert verified_merge.resolve_verified_merge_phase(
        [
            _trusted_convergence_comment(stale_convergence),
            _trusted_convergence_comment(replacement_convergence),
            _trusted_comment(str(stale_merged["phase_receipt_comment"])),
            _trusted_comment(str(replacement_prepared["phase_receipt_comment"])),
            _trusted_comment(str(replacement_merged["phase_receipt_comment"])),
        ],
        authority_receipt=authority,
        pr=merged_pr,
    ) is None
