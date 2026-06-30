"""GitHub API failure-classification regression tests."""

from __future__ import annotations

import json
import subprocess

import pytest

from app.dispatcher.sync_github import classify_github_api_failure
from scripts import reconcile_project_status


def test_classifies_primary_secondary_resource_timeout_network() -> None:
    cases = [
        (
            RuntimeError("API rate limit exceeded"),
            {"http_status": 403},
            "primary_quota",
        ),
        (
            RuntimeError("You have exceeded a secondary rate limit. Retry-After: 7"),
            {"http_status": 403},
            "secondary_quota",
        ),
        (
            RuntimeError("GraphQL: query cost too high"),
            {"graphql_error_type": "RESOURCE_LIMITS_EXCEEDED"},
            "resource_limit",
        ),
        (
            RuntimeError("GraphQL query timed out"),
            {"graphql_error_type": "TIMEOUT"},
            "resource_limit",
        ),
        (
            RuntimeError("abuse detection mechanism triggered"),
            {"http_status": 403},
            "write_content_limit",
        ),
        (
            RuntimeError("connection reset by peer"),
            {"http_status": 502},
            "network",
        ),
    ]

    for error, kwargs, expected in cases:
        classification = classify_github_api_failure(error, **kwargs)
        assert classification.kind == expected
        if expected == "resource_limit":
            assert classification.reduce_page_size is True
        if expected in {"primary_quota", "secondary_quota", "network"}:
            assert classification.retryable is True


def test_quota_sleeps_until_reset_and_cost_shrinks_page(monkeypatch: pytest.MonkeyPatch) -> None:
    slept: list[float] = []
    monkeypatch.setattr(reconcile_project_status.time, "sleep", lambda seconds: slept.append(seconds))
    monkeypatch.setattr(reconcile_project_status.time, "time", lambda: 1000)

    calls = {"count": 0}

    def rate_limited_then_ok(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls["count"] += 1
        if calls["count"] == 1:
            raise subprocess.CalledProcessError(
                returncode=1,
                cmd=cmd,
                stderr="GraphQL: API rate limit exceeded",
            )
        return subprocess.CompletedProcess(cmd, 0, stdout="ok\n", stderr="")

    monkeypatch.setattr(reconcile_project_status.subprocess, "run", rate_limited_then_ok)
    monkeypatch.setattr(reconcile_project_status, "graphql_rate_limit", lambda: (0, 1007))

    assert reconcile_project_status.run_gh("project", "item-list", "1") == "ok"
    assert slept == [8.0]

    item_list_limits: list[str] = []

    def shrink_then_succeed(*args: str) -> str:
        item_list_limits.append(args[args.index("--limit") + 1])
        if item_list_limits[-1] == "200":
            raise subprocess.CalledProcessError(
                returncode=1,
                cmd=["gh", *args],
                stderr="GraphQL: RESOURCE_LIMITS_EXCEEDED",
            )
        return json.dumps(
            {
                "items": [
                    {"id": "item-1", "content": {"type": "Issue", "number": 1}},
                ],
                "totalCount": 1,
            }
        )

    monkeypatch.setattr(reconcile_project_status, "run_gh", shrink_then_succeed)

    items = reconcile_project_status.list_project_items("RasmusTho", 1)

    assert item_list_limits == ["200", "100"]
    assert items == [{"id": "item-1", "content": {"type": "Issue", "number": 1}}]
