from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping

import httpx
import pytest

import app.dispatcher.verification_github as verification_github
from app.dispatcher.verification_github import GitHubProtectedRepositoryAuthority
from app.dispatcher.verified_merge import (
    VERIFIED_MERGE_READINESS_CONTRACT,
    build_verified_merge_phase,
    prepare_verified_merge,
    verified_merge_body_sha256,
)
from app.dispatcher.verification_merge import MergeAuthorityError
from tests.dispatcher.verified_merge_projection_helpers import (
    projection_convergence_comment,
    projection_phase_kwargs,
)


REPOSITORY = "RasmusTho/agentic-pkm-mvp"
HEAD = "a" * 40


def test_neutralized_body_transport_uses_shared_canonical_digest(monkeypatch) -> None:
    repair_budget = {"policy_version": "v2", "mechanisms": []}
    original_pr: dict[str, object] = {
        "number": 3822,
        "state": "open",
        "merged": False,
        "merged_at": None,
        "draft": False,
        "title": "bug: preserve neutralized transport digest",
        "body": (
            "Governing-Issue: #3821\n"
            "Fixes #3820\n"
            "Refs #3900\n"
        ),
        "head": {"sha": HEAD},
    }
    plan = prepare_verified_merge(
        context={
            "contract": "verification_closer_dispatch_context.v2",
            "run_id": "vrun-transport",
            "repository": REPOSITORY.lower(),
            "pr_number": 3822,
            "governing_issue": 3821,
            "closing_issues": [3820],
            "supporting_issues": [3820],
            "head_sha": HEAD,
            "repair_budget": repair_budget,
        },
        pr=original_pr,
        live_closing_issues=[3820],
        merge_readiness={
            "contract": VERIFIED_MERGE_READINESS_CONTRACT,
            "head_sha": HEAD,
            "required_checks_green": True,
            "review_gate_resolved": True,
            "further_commits_anticipated": False,
        },
    )
    authority = plan["authority_receipt"]
    assert isinstance(authority, Mapping)
    transport_body = str(plan["neutralized_body"])
    assert not transport_body.endswith("\n")
    live_body = transport_body + "\n"
    prepared_pr = {**original_pr, "body": live_body}
    phase_kwargs = projection_phase_kwargs(authority, prepared_pr)
    phase = build_verified_merge_phase(
        authority_receipt=authority,
        phase="prepared",
        pr=prepared_pr,
        projection_convergence_receipt=phase_kwargs[
            "projection_convergence_receipt"
        ],
        final_projection_observation=phase_kwargs[
            "final_projection_observation"
        ],
    )
    comments = [
        {
            "author_association": "COLLABORATOR",
            "body": plan["authority_receipt_comment"],
        },
        {
            "author_association": "COLLABORATOR",
            "body": projection_convergence_comment(phase_kwargs)["body"],
        },
        {
            "author_association": "COLLABORATOR",
            "body": phase["phase_receipt_comment"],
        },
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/pulls/3822"):
            return httpx.Response(200, json=prepared_pr)
        if request.url.path.endswith("/issues/3822/comments"):
            return httpx.Response(200, json=comments)
        if request.url.path == "/graphql":
            return httpx.Response(
                200,
                json={
                    "data": {
                        "repository": {
                            "pullRequest": {
                                "userContentEdits": {
                                    "nodes": [
                                        {
                                            "id": "UCE_fixture_3822",
                                            "editedAt": "2026-08-12T05:00:00Z",
                                            "editor": {"login": "rasmustho"},
                                        }
                                    ],
                                    "pageInfo": {"hasNextPage": False},
                                },
                                "closingIssuesReferences": {
                                    "nodes": [],
                                    "pageInfo": {"hasNextPage": False},
                                }
                            }
                        }
                    }
                },
            )
        raise AssertionError(f"unexpected GitHub request: {request.url}")

    digest_calls: list[str] = []

    def tracked_digest(body: str) -> str:
        digest_calls.append(body)
        return verified_merge_body_sha256(body)

    monkeypatch.setattr(
        verification_github, "verified_merge_body_sha256", tracked_digest
    )
    adapter = GitHubProtectedRepositoryAuthority(
        "host-read-token",
        http_client=httpx.Client(
            base_url="https://api.github.test",
            transport=httpx.MockTransport(handler),
        ),
    )

    gate = adapter.verified_merge_prepared(
        REPOSITORY,
        3822,
        run_id="vrun-transport",
        head_sha=HEAD,
        expected_repair_budget=repair_budget,
    )

    assert digest_calls == [live_body]
    assert gate["neutralized_body_sha256"] == verified_merge_body_sha256(
        live_body
    )
    assert gate["neutralized_body_sha256"] == authority[
        "neutralized_body_sha256"
    ]
    assert gate["body_edit"] == {
        "node_id": "UCE_fixture_3822",
        "edited_at": "2026-08-12T05:00:00Z",
        "editor_login": "rasmustho",
        "editor_association": "OWNER",
    }


def test_prepared_gate_preserves_authenticated_legacy_terminal_lf_digest() -> None:
    repair_budget = {"policy_version": "v2", "mechanisms": []}
    original_pr: dict[str, object] = {
        "number": 4052,
        "state": "open",
        "merged": False,
        "merged_at": None,
        "draft": False,
        "title": "legacy neutralized transport recovery",
        "body": "Governing-Issue: #4051\nFixes #4050\n",
        "head": {"sha": HEAD},
    }
    plan = prepare_verified_merge(
        context={
            "contract": "verification_closer_dispatch_context.v2",
            "run_id": "vrun-legacy-transport",
            "repository": REPOSITORY.lower(),
            "pr_number": 4052,
            "governing_issue": 4051,
            "closing_issues": [4050],
            "supporting_issues": [4050],
            "head_sha": HEAD,
            "repair_budget": repair_budget,
        },
        pr=original_pr,
        live_closing_issues=[4050],
        merge_readiness={
            "contract": VERIFIED_MERGE_READINESS_CONTRACT,
            "head_sha": HEAD,
            "required_checks_green": True,
            "review_gate_resolved": True,
            "further_commits_anticipated": False,
        },
    )
    authority = copy.deepcopy(plan["authority_receipt"])
    assert isinstance(authority, dict)
    transport_body = str(plan["neutralized_body"])
    authority["body_sha256"] = hashlib.sha256(
        str(plan["original_body"]).encode()
    ).hexdigest()
    authority["neutralized_body_sha256"] = hashlib.sha256(
        (transport_body + "\n").encode()
    ).hexdigest()
    authority_comment = {
        "author_association": "COLLABORATOR",
        "created_at": "2026-07-21T16:16:34Z",
        "updated_at": "2026-07-21T16:16:34Z",
        "body": (
            "verified issue-set merge authority:\n```json\n"
            + json.dumps(authority, sort_keys=True, separators=(",", ":"))
            + "\n```"
        ),
    }
    prepared_pr = {**original_pr, "body": transport_body}
    phase_kwargs = projection_phase_kwargs(
        authority, prepared_pr, authority_comment=authority_comment
    )
    phase = build_verified_merge_phase(
        authority_receipt=authority,
        authority_comment=authority_comment,
        phase="prepared",
        pr=prepared_pr,
        projection_convergence_receipt=phase_kwargs[
            "projection_convergence_receipt"
        ],
        final_projection_observation=phase_kwargs[
            "final_projection_observation"
        ],
    )
    comments = [
        authority_comment,
        {
            "author_association": "COLLABORATOR",
            "body": projection_convergence_comment(phase_kwargs)["body"],
        },
        {
            "author_association": "COLLABORATOR",
            "body": phase["phase_receipt_comment"],
        },
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/pulls/4052"):
            return httpx.Response(200, json=prepared_pr)
        if request.url.path.endswith("/issues/4052/comments"):
            return httpx.Response(200, json=comments)
        if request.url.path == "/graphql":
            return httpx.Response(
                200,
                json={
                    "data": {
                        "repository": {
                            "pullRequest": {
                                "userContentEdits": {
                                    "nodes": [
                                        {
                                            "id": "UCE_fixture_4052",
                                            "editedAt": "2026-08-12T05:00:00Z",
                                            "editor": {"login": "rasmustho"},
                                        }
                                    ],
                                    "pageInfo": {"hasNextPage": False},
                                },
                                "closingIssuesReferences": {
                                    "nodes": [],
                                    "pageInfo": {"hasNextPage": False},
                                }
                            }
                        }
                    }
                },
            )
        raise AssertionError(f"unexpected GitHub request: {request.url}")

    adapter = GitHubProtectedRepositoryAuthority(
        "host-read-token",
        http_client=httpx.Client(
            base_url="https://api.github.test",
            transport=httpx.MockTransport(handler),
        ),
    )

    gate = adapter.verified_merge_prepared(
        REPOSITORY,
        4052,
        run_id="vrun-legacy-transport",
        head_sha=HEAD,
        expected_repair_budget=repair_budget,
    )

    assert gate["neutralized_body_sha256"] == verified_merge_body_sha256(
        transport_body
    )
    assert gate["neutralized_body_sha256"] != authority[
        "neutralized_body_sha256"
    ]
    assert gate["body_edit"] == {
        "node_id": "UCE_fixture_4052",
        "edited_at": "2026-08-12T05:00:00Z",
        "editor_login": "rasmustho",
        "editor_association": "OWNER",
    }


def test_prepared_gate_rejects_body_edit_race_during_final_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repair_budget = {"policy_version": "v2", "mechanisms": []}
    original_pr: dict[str, object] = {
        "number": 3822,
        "state": "open",
        "merged": False,
        "merged_at": None,
        "draft": False,
        "title": "body edit race fixture",
        "body": (
            "Governing-Issue: #3821\n"
            "Fixes #3820\n"
            "Refs #3900\n"
        ),
        "head": {"sha": HEAD},
    }
    plan = prepare_verified_merge(
        context={
            "contract": "verification_closer_dispatch_context.v2",
            "run_id": "vrun-raced-body-edit",
            "repository": REPOSITORY.lower(),
            "pr_number": 3822,
            "governing_issue": 3821,
            "closing_issues": [3820],
            "supporting_issues": [3820],
            "head_sha": HEAD,
            "repair_budget": repair_budget,
        },
        pr=original_pr,
        live_closing_issues=[3820],
        merge_readiness={
            "contract": VERIFIED_MERGE_READINESS_CONTRACT,
            "head_sha": HEAD,
            "required_checks_green": True,
            "review_gate_resolved": True,
            "further_commits_anticipated": False,
        },
    )
    authority = plan["authority_receipt"]
    assert isinstance(authority, Mapping)
    prepared_pr = {**original_pr, "body": str(plan["neutralized_body"]) + "\n"}
    phase_kwargs = projection_phase_kwargs(authority, prepared_pr)
    phase = build_verified_merge_phase(
        authority_receipt=authority,
        phase="prepared",
        pr=prepared_pr,
        projection_convergence_receipt=phase_kwargs[
            "projection_convergence_receipt"
        ],
        final_projection_observation=phase_kwargs[
            "final_projection_observation"
        ],
    )
    comments = [
        {
            "author_association": "COLLABORATOR",
            "body": plan["authority_receipt_comment"],
        },
        {
            "author_association": "COLLABORATOR",
            "body": projection_convergence_comment(phase_kwargs)["body"],
        },
        {
            "author_association": "COLLABORATOR",
            "body": phase["phase_receipt_comment"],
        },
    ]
    edit = {
        "node_id": "UCE_fixture_race_before",
        "edited_at": "2026-08-12T05:00:00Z",
        "editor_login": "rasmustho",
        "editor_association": "OWNER",
    }
    raced_edit = {**edit, "node_id": "UCE_fixture_race_after"}
    adapter = object.__new__(GitHubProtectedRepositoryAuthority)
    monkeypatch.setattr(adapter, "_pull", lambda *_args: prepared_pr)
    monkeypatch.setattr(adapter, "_issue_comments", lambda *_args: comments)
    monkeypatch.setattr(adapter, "_closing_issue_references", lambda *_args: [])
    current_edits = iter([edit, raced_edit])
    monkeypatch.setattr(
        adapter, "_current_body_edit", lambda *_args: next(current_edits)
    )

    with pytest.raises(
        MergeAuthorityError, match="changed during final closing projection read"
    ):
        adapter.verified_merge_prepared(
            REPOSITORY,
            3822,
            run_id="vrun-raced-body-edit",
            head_sha=HEAD,
            expected_repair_budget=repair_budget,
        )
