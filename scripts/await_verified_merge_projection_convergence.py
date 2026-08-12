#!/usr/bin/env python3
"""Read-only bounded wait for verified-merge closing-projection convergence.

The command performs no GitHub mutation. It admits exactly two empty,
same-identity GraphQL snapshots after an authenticated post-edit ``pr-contract``
success, then captures one fresh final snapshot for prepared-phase creation.
Any API ambiguity, drift, regression, or timeout fails closed.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from functools import lru_cache
import json
from pathlib import Path
import subprocess
import time
from typing import Mapping, Sequence, cast
from urllib.parse import quote

from app.dispatcher.verified_merge import (
    VERIFIED_MERGE_PROJECTION_CONVERGENCE_MARKER,
    build_verified_merge_projection_convergence,
    plan_projection_convergence_failure_restoration,
    resume_verified_merge_projection_convergence,
    validate_verified_merge_projection_observation,
)
from app.dispatcher.github_call_logger import is_kill_switch_active


_QUERY = """
query($owner: String!, $name: String!, $number: Int!) {
  rateLimit { cost remaining resetAt }
  repository(owner: $owner, name: $name) {
    nameWithOwner
    defaultBranchRef { name target { oid } }
    pullRequest(number: $number) {
      id
      number
      headRefOid
      headRefName
      baseRefName
      state
      isDraft
      title
      body
      lastEditedAt
      userContentEdits(last: 1) {
        nodes { id editedAt editor { login } }
        pageInfo { hasNextPage }
      }
      closingIssuesReferences(first: 11) {
        nodes { number repository { nameWithOwner } }
        pageInfo { hasNextPage }
      }
    }
  }
}
"""


def _mapping(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _run_json_value(
    argv: list[str], *, stdin: Mapping[str, object] | None = None
) -> object:
    completed = subprocess.run(
        argv,
        input=(json.dumps(stdin) if stdin is not None else None),
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise ValueError("GitHub read failed")
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("GitHub read returned malformed JSON") from exc
    return value


def _run_json(
    argv: list[str], *, stdin: Mapping[str, object] | None = None
) -> dict[str, object]:
    value = _run_json_value(argv, stdin=stdin)
    if not isinstance(value, dict):
        raise ValueError("GitHub read returned a non-object")
    return value


def _graphql_budget(gh_bin: str) -> int:
    value = _run_json([gh_bin, "api", "rate_limit"])
    resources = value.get("resources")
    graphql = (
        resources.get("graphql") if isinstance(resources, Mapping) else None
    )
    remaining = graphql.get("remaining") if isinstance(graphql, Mapping) else None
    if (
        not isinstance(remaining, int)
        or isinstance(remaining, bool)
        or remaining < 0
        or is_kill_switch_active(remaining)
    ):
        raise ValueError("GitHub GraphQL budget is unavailable or kill-switched")
    return remaining


@lru_cache(maxsize=32)
def _editor_association(
    gh_bin: str,
    *,
    repository: str,
    editor_login: str,
) -> str:
    owner = repository.split("/", 1)[0]
    if editor_login.casefold() == owner.casefold():
        return "OWNER"
    permission = _run_json(
        [
            gh_bin,
            "api",
            f"repos/{repository}/collaborators/{quote(editor_login, safe='')}/permission",
        ]
    ).get("permission")
    if permission not in {"admin", "maintain", "write"}:
        raise ValueError("body editor is not an authenticated repository collaborator")
    return "COLLABORATOR"


def _comments(
    gh_bin: str, *, repository: str, pr_number: int
) -> list[dict[str, object]]:
    comments: list[dict[str, object]] = []
    for page in range(1, 11):
        value = _run_json_value(
            [
                gh_bin,
                "api",
                f"repos/{repository}/issues/{pr_number}/comments"
                f"?per_page=100&page={page}",
            ]
        )
        if not isinstance(value, list) or any(
            not isinstance(item, dict) for item in value
        ):
            raise ValueError("GitHub authority comments are incomplete")
        comments.extend(cast(list[dict[str, object]], value))
        if len(value) < 100:
            return comments
    raise ValueError("GitHub authority comments exceed bounded scan")


def _authenticate_unique_authority(
    gh_bin: str,
    *,
    repository: str,
    authority: Mapping[str, object],
    snapshot: Mapping[str, object],
) -> None:
    pull = snapshot.get("pull_request")
    if not isinstance(pull, Mapping):
        raise ValueError("GitHub pull request snapshot is incomplete")
    comments = _comments(
        gh_bin,
        repository=repository,
        pr_number=cast(int, authority.get("pr_number")),
    )
    if any(
        isinstance(comment.get("body"), str)
        and VERIFIED_MERGE_PROJECTION_CONVERGENCE_MARKER
        in cast(str, comment["body"])
        for comment in comments
    ):
        raise ValueError("a convergence receipt already exists for this attempt")
    result = resume_verified_merge_projection_convergence(
        comments,
        pr={
            "number": pull.get("number"),
            "state": str(pull.get("state", "")).lower(),
            "merged": False,
            "merged_at": None,
            "draft": pull.get("draft"),
            "title": pull.get("title"),
            "body": pull.get("body"),
            "head": {"sha": pull.get("head_sha")},
        },
        repository=repository,
        expected_run_id=cast(str, authority.get("run_id")),
        expected_repair_budget=cast(
            Mapping[str, object], authority.get("repair_budget")
        ),
    )
    if result is None or result.get("authority_receipt") != authority:
        raise ValueError("unique trusted verified-merge authority is unavailable")


def _authenticate_pr_contract(
    gh_bin: str,
    *,
    repository: str,
    pr_contract: Mapping[str, object],
) -> None:
    workflow_run_id = pr_contract.get("workflow_run_id")
    check_run_id = pr_contract.get("check_run_id")
    if (
        not isinstance(workflow_run_id, int)
        or isinstance(workflow_run_id, bool)
        or workflow_run_id < 1
        or not isinstance(check_run_id, int)
        or isinstance(check_run_id, bool)
        or check_run_id < 1
    ):
        raise ValueError("pr-contract GitHub identities are malformed")
    workflow = _run_json(
        [gh_bin, "api", f"repos/{repository}/actions/runs/{workflow_run_id}"]
    )
    check = _run_json(
        [gh_bin, "api", f"repos/{repository}/check-runs/{check_run_id}"]
    )
    latest_checks = _run_json(
        [
            gh_bin,
            "api",
            f"repos/{repository}/commits/{pr_contract.get('head_sha')}"
            "/check-runs?check_name=pr-contract&filter=latest&per_page=100",
        ]
    )
    check_suite = check.get("check_suite")
    app = check.get("app")
    details_url = check.get("details_url")
    workflow_repository = workflow.get("repository")
    workflow_pull_requests = workflow.get("pull_requests")
    check_pull_requests = check.get("pull_requests")
    latest_rows = latest_checks.get("check_runs")

    def matching_pull_request(value: object) -> bool:
        if not isinstance(value, list) or len(value) != 1:
            return False
        row = value[0]
        if not isinstance(row, Mapping):
            return False
        head = row.get("head")
        base = row.get("base")
        return bool(
            row.get("number") == pr_contract.get("pr_number")
            and isinstance(head, Mapping)
            and head.get("sha") == pr_contract.get("head_sha")
            and head.get("ref") == pr_contract.get("head_ref")
            and isinstance(base, Mapping)
            and base.get("ref") == pr_contract.get("base_ref")
        )

    if (
        workflow.get("id") != workflow_run_id
        or workflow.get("name") != "Issue and PR Governance"
        or workflow.get("path") != ".github/workflows/issue-pr-governance.yml"
        or workflow.get("event") != "pull_request"
        or workflow.get("head_sha") != pr_contract.get("head_sha")
        or workflow.get("head_branch") != pr_contract.get("head_ref")
        or workflow.get("status") != "completed"
        or workflow.get("conclusion") != "success"
        or workflow.get("created_at") != pr_contract.get("created_at")
        or workflow.get("check_suite_id") != pr_contract.get("check_suite_id")
        or not isinstance(workflow_repository, Mapping)
        or workflow_repository.get("full_name") != repository
        or not matching_pull_request(workflow_pull_requests)
        or check.get("id") != check_run_id
        or check.get("name") != "pr-contract"
        or check.get("head_sha") != pr_contract.get("head_sha")
        or check.get("status") != "completed"
        or check.get("conclusion") != "success"
        or check.get("started_at") != pr_contract.get("started_at")
        or check.get("completed_at") != pr_contract.get("completed_at")
        or not isinstance(check_suite, Mapping)
        or check_suite.get("id") != pr_contract.get("check_suite_id")
        or not isinstance(app, Mapping)
        or app.get("slug") != "github-actions"
        or not isinstance(details_url, str)
        or f"/actions/runs/{workflow_run_id}" not in details_url
        or not matching_pull_request(check_pull_requests)
        or latest_checks.get("total_count") != 1
        or not isinstance(latest_rows, list)
        or len(latest_rows) != 1
        or not isinstance(latest_rows[0], Mapping)
        or latest_rows[0].get("id") != check_run_id
    ):
        raise ValueError("pr-contract GitHub identity is stale or unauthenticated")


def _timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _snapshot(
    gh_bin: str,
    *,
    repository: str,
    pr_number: int,
) -> dict[str, object]:
    _graphql_budget(gh_bin)
    owner, name = repository.split("/", 1)
    response = _run_json(
        [gh_bin, "api", "graphql", "--input", "-"],
        stdin={
            "query": _QUERY,
            "variables": {"owner": owner, "name": name, "number": pr_number},
        },
    )
    errors = response.get("errors", [])
    data = response.get("data")
    repository_row = data.get("repository") if isinstance(data, Mapping) else None
    pull = (
        repository_row.get("pullRequest")
        if isinstance(repository_row, Mapping)
        else None
    )
    default_ref = (
        repository_row.get("defaultBranchRef")
        if isinstance(repository_row, Mapping)
        else None
    )
    default_target = (
        default_ref.get("target") if isinstance(default_ref, Mapping) else None
    )
    edits = pull.get("userContentEdits") if isinstance(pull, Mapping) else None
    edit_nodes = edits.get("nodes") if isinstance(edits, Mapping) else None
    closing = (
        pull.get("closingIssuesReferences") if isinstance(pull, Mapping) else None
    )
    closing_nodes = closing.get("nodes") if isinstance(closing, Mapping) else None
    rate_limit = data.get("rateLimit") if isinstance(data, Mapping) else None
    if (
        errors != []
        or not isinstance(repository_row, Mapping)
        or not isinstance(pull, Mapping)
        or not isinstance(default_ref, Mapping)
        or not isinstance(default_target, Mapping)
        or not isinstance(edit_nodes, list)
        or len(edit_nodes) != 1
        or not isinstance(edit_nodes[0], Mapping)
        or not isinstance(closing_nodes, list)
        or any(not isinstance(row, Mapping) for row in closing_nodes)
        or not isinstance(rate_limit, Mapping)
    ):
        raise ValueError("GitHub projection response is incomplete or ambiguous")
    assert isinstance(edits, Mapping)
    assert isinstance(closing, Mapping)
    edit = cast(Mapping[str, object], edit_nodes[0])
    editor = edit.get("editor")
    if not isinstance(editor, Mapping) or not isinstance(editor.get("login"), str):
        raise ValueError("GitHub body edit identity is incomplete")
    editor_login = cast(str, editor["login"])
    normalized_closing = [
        {
            "number": row.get("number"),
            "repository": (
                cast(Mapping[str, object], row.get("repository")).get(
                    "nameWithOwner"
                )
                if isinstance(row.get("repository"), Mapping)
                else None
            ),
        }
        for row in cast(list[Mapping[str, object]], closing_nodes)
    ]
    return {
        "errors": [],
        "observed_at": _timestamp(),
        "rate_limit": {
            "cost": rate_limit.get("cost"),
            "kill_switch_active": is_kill_switch_active(
                cast(int, rate_limit.get("remaining"))
            )
            if isinstance(rate_limit.get("remaining"), int)
            and not isinstance(rate_limit.get("remaining"), bool)
            else True,
            "remaining": rate_limit.get("remaining"),
            "reset_at": rate_limit.get("resetAt"),
        },
        "repository": {
            "name_with_owner": repository_row.get("nameWithOwner"),
            "default_branch": default_ref.get("name"),
            "default_branch_sha": default_target.get("oid"),
        },
        "pull_request": {
            "node_id": pull.get("id"),
            "number": pull.get("number"),
            "head_sha": pull.get("headRefOid"),
            "head_ref": pull.get("headRefName"),
            "base_ref": pull.get("baseRefName"),
            "state": pull.get("state"),
            "draft": pull.get("isDraft"),
            "title": pull.get("title"),
            "body": pull.get("body"),
            "last_edited_at": pull.get("lastEditedAt"),
            "latest_body_edit": {
                "node_id": edit.get("id"),
                "edited_at": edit.get("editedAt"),
                "editor_login": editor_login,
                "editor_association": _editor_association(
                    gh_bin,
                    repository=repository,
                    editor_login=editor_login,
                ),
            },
            "body_edits_page_info": {
                "has_next_page": (
                    edits.get("pageInfo", {}).get("hasNextPage")
                    if isinstance(edits.get("pageInfo"), Mapping)
                    else None
                )
            },
            "closing_issues": normalized_closing,
            "closing_issues_page_info": {
                "has_next_page": (
                    closing.get("pageInfo", {}).get("hasNextPage")
                    if isinstance(closing.get("pageInfo"), Mapping)
                    else None
                )
            },
        },
    }


def _write(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authority-json", type=Path, required=True)
    parser.add_argument("--pr-contract-json", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--pr-number", type=int, required=True)
    parser.add_argument("--minimum-backoff-seconds", type=int, default=60)
    parser.add_argument("--final-backoff-seconds", type=int, default=1)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--canonical-body-file", type=Path)
    parser.add_argument("--gh-bin", default="gh")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if (
        args.pr_number < 1
        or args.minimum_backoff_seconds < 1
        or args.final_backoff_seconds < 1
        or args.timeout_seconds
        < args.minimum_backoff_seconds + args.final_backoff_seconds
        or args.repository.count("/") != 1
    ):
        raise ValueError("bounded convergence arguments are malformed")
    authority = _mapping(args.authority_json)
    pr_contract = _mapping(args.pr_contract_json)
    deadline = time.monotonic() + args.timeout_seconds
    try:
        _authenticate_pr_contract(
            args.gh_bin,
            repository=args.repository,
            pr_contract=pr_contract,
        )
        empty_observations: list[dict[str, object]] = []
        projection_identity_sha256: str | None = None
        authority_authenticated = False
        next_read_at = time.monotonic()
        while len(empty_observations) < 2:
            remaining = deadline - time.monotonic()
            delay = max(0.0, next_read_at - time.monotonic())
            if remaining <= delay:
                raise TimeoutError
            if delay:
                time.sleep(delay)
            snapshot = _snapshot(
                args.gh_bin,
                repository=args.repository,
                pr_number=args.pr_number,
            )
            if not authority_authenticated:
                _authenticate_unique_authority(
                    args.gh_bin,
                    repository=args.repository,
                    authority=authority,
                    snapshot=snapshot,
                )
                authority_authenticated = True
            admitted = validate_verified_merge_projection_observation(
                authority_receipt=authority,
                pr_contract=pr_contract,
                observation=snapshot,
            )
            if admitted["empty"] is True:
                identity = cast(str, admitted["identity_sha256"])
                if (
                    projection_identity_sha256 is not None
                    and identity != projection_identity_sha256
                ):
                    raise ValueError("closing projection identity drifted")
                projection_identity_sha256 = identity
                empty_observations.append(snapshot)
                next_read_at = (
                    time.monotonic() + args.minimum_backoff_seconds
                )
            else:
                # A non-empty projection is expected while GitHub converges,
                # but it does not count toward the quorum. A later non-empty
                # read after the first empty is a regression and fails closed.
                if empty_observations:
                    raise ValueError("closing projection regressed after empty")
                next_read_at = (
                    time.monotonic() + args.minimum_backoff_seconds
                )
        convergence = build_verified_merge_projection_convergence(
            authority_receipt=authority,
            pr_contract=pr_contract,
            observations=empty_observations,
            minimum_backoff_seconds=args.minimum_backoff_seconds,
        )
        remaining = deadline - time.monotonic()
        if remaining < args.final_backoff_seconds:
            raise TimeoutError
        time.sleep(args.final_backoff_seconds)
        # A separate final read is consumed by prepared-phase construction; it
        # is not folded into the two-observation convergence authority.
        final_observation = _snapshot(
            args.gh_bin, repository=args.repository, pr_number=args.pr_number
        )
        _authenticate_unique_authority(
            args.gh_bin,
            repository=args.repository,
            authority=authority,
            snapshot=final_observation,
        )
        _authenticate_pr_contract(
            args.gh_bin,
            repository=args.repository,
            pr_contract=pr_contract,
        )
        final_admission = validate_verified_merge_projection_observation(
            authority_receipt=authority,
            pr_contract=pr_contract,
            observation=final_observation,
        )
        final_observed_at = final_observation.get("observed_at")
        quorum_observed_at = empty_observations[-1].get("observed_at")
        if (
            final_admission["empty"] is not True
            or final_admission["identity_sha256"]
            != projection_identity_sha256
            or not isinstance(final_observed_at, str)
            or not isinstance(quorum_observed_at, str)
            or final_observed_at <= quorum_observed_at
        ):
            raise ValueError("final closing projection is stale or drifted")
        success_payload: dict[str, object] = {
            **convergence,
            "final_projection_observation": final_observation,
            "status": "converged",
        }
        _write(args.output_json, success_payload)
        print(json.dumps(success_payload, indent=2, sort_keys=True))
        return 0
    except TimeoutError:
        failure = "timeout"
    except (OSError, ValueError, subprocess.SubprocessError):
        failure = "failed_convergence"

    payload: dict[str, object] = {
        "failure": failure,
        "restoration_required": True,
        "status": "failed_closed",
    }
    if args.canonical_body_file is not None:
        canonical_body = args.canonical_body_file.read_text(encoding="utf-8")
        try:
            live = _snapshot(
                args.gh_bin, repository=args.repository, pr_number=args.pr_number
            )["pull_request"]
            assert isinstance(live, dict)
            payload["restoration"] = plan_projection_convergence_failure_restoration(
                authority_receipt=authority,
                pr={
                    "number": live.get("number"),
                    "state": str(live.get("state", "")).lower(),
                    "merged_at": None,
                    "head": {"sha": live.get("head_sha")},
                    "body": live.get("body"),
                },
                canonical_body=canonical_body,
                failure=failure,
            )
        except (AssertionError, OSError, ValueError, subprocess.SubprocessError):
            payload["restoration"] = None
    _write(args.output_json, payload)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 2 if failure == "timeout" else 3


if __name__ == "__main__":
    raise SystemExit(main())
