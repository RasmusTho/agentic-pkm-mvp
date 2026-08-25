from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping

from app.dispatcher.verified_merge import (
    build_verified_merge_projection_convergence,
)


def projection_phase_kwargs(
    authority_receipt: Mapping[str, object],
    pr: Mapping[str, object],
    *,
    authority_comment: Mapping[str, object] | None = None,
    body_edit: Mapping[str, object] | None = None,
) -> dict[str, Mapping[str, object]]:
    """Build deterministic convergence evidence for phase-unit fixtures."""

    repository = str(authority_receipt["repository"])
    pr_number = int(authority_receipt["pr_number"])
    head_sha = str(authority_receipt["head_sha"])
    title = str(pr.get("title", "verified merge fixture"))
    body = str(pr["body"])
    node_id = f"PR_fixture_{pr_number}"
    edit = dict(body_edit) if body_edit is not None else {
        "node_id": f"UCE_fixture_{pr_number}",
        "edited_at": "2026-08-12T05:00:00Z",
        "editor_login": repository.split("/", 1)[0],
        "editor_association": "OWNER",
    }
    authority_digest = hashlib.sha256(
        json.dumps(
            dict(authority_receipt), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    pr_contract = {
        "name": "pr-contract",
        "workflow_run_id": 1,
        "check_run_id": 2,
        "check_suite_id": 3,
        "event": "pull_request",
        "head_sha": head_sha,
        "head_ref": "fixture-head",
        "base_ref": "main",
        "status": "completed",
        "conclusion": "success",
        "created_at": "2026-08-12T05:00:01Z",
        "started_at": "2026-08-12T05:00:02Z",
        "completed_at": "2026-08-12T05:00:03Z",
        "authority_sha256": authority_digest,
        "neutralized_body_sha256": authority_receipt[
            "neutralized_body_sha256"
        ],
        "repository": repository,
        "pr_number": pr_number,
        "pull_request_node_id": node_id,
        "title": title,
        "default_branch": "main",
        "default_branch_sha": "b" * 40,
        "body_edit": edit,
    }

    def observation(observed_at: str) -> dict[str, object]:
        return {
            "errors": [],
            "rate_limit": {
                "cost": 1,
                "kill_switch_active": False,
                "remaining": 4999,
                "reset_at": "2026-08-12T06:00:00Z",
            },
            "repository": {
                "name_with_owner": repository,
                "default_branch": "main",
                "default_branch_sha": "b" * 40,
            },
            "pull_request": {
                "node_id": node_id,
                "number": pr_number,
                "head_sha": head_sha,
                "head_ref": "fixture-head",
                "base_ref": "main",
                "state": "OPEN",
                "draft": False,
                "title": title,
                "body": body,
                "last_edited_at": edit["edited_at"],
                "latest_body_edit": edit,
                "body_edits_page_info": {"has_next_page": False},
                "closing_issues": [],
                "closing_issues_page_info": {"has_next_page": False},
            },
            "observed_at": observed_at,
        }

    final_observation = observation("2026-08-12T05:00:07Z")
    convergence = build_verified_merge_projection_convergence(
        authority_receipt=authority_receipt,
        authority_comment=authority_comment,
        pr_contract=pr_contract,
        observations=[
            observation("2026-08-12T05:00:04Z"),
            observation("2026-08-12T05:00:06Z"),
        ],
        final_projection_observation=final_observation,
        minimum_backoff_seconds=1,
    )["convergence_receipt"]
    assert isinstance(convergence, Mapping)
    return {
        "projection_convergence_receipt": convergence,
        "final_projection_observation": final_observation,
    }


def projection_convergence_comment(
    phase_kwargs: Mapping[str, Mapping[str, object]],
    *,
    association: str = "COLLABORATOR",
) -> dict[str, object]:
    receipt = phase_kwargs["projection_convergence_receipt"]
    return {
        "author_association": association,
        "body": (
            "verified merge closing projection convergence:\n```json\n"
            + json.dumps(dict(receipt), sort_keys=True, separators=(",", ":"))
            + "\n```"
        ),
    }
