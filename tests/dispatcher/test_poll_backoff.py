from __future__ import annotations

from app.dispatcher.poll_backoff import PollPolicy, PollResponse, poll_until, resolve_codex_verdict


def test_poll_respects_interval_cap_and_retry_after() -> None:
    now = 1_000.0
    sleeps: list[float] = []
    responses = iter(
        [
            PollResponse(False, {"Retry-After": "7"}),
            PollResponse(False, {"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1020"}),
            PollResponse(True, {}),
        ]
    )

    def clock() -> float:
        return now

    def sleeper(seconds: float) -> None:
        nonlocal now
        sleeps.append(seconds)
        now += seconds

    result = poll_until(
        lambda: next(responses),
        bool,
        policy=PollPolicy(
            interval_seconds=5,
            max_attempts=5,
            max_elapsed_seconds=30,
            backoff_multiplier=2,
            max_interval_seconds=12,
        ),
        clock=clock,
        sleeper=sleeper,
    )

    assert result is True
    assert sleeps == [7.0, 13.0]


def test_codex_verdict_single_combined_query() -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def client(query: str, variables: dict[str, object]) -> dict[str, object]:
        calls.append((query, variables))
        return {
            "data": {
                "repository": {
                    "pullRequest": {
                        "reviews": {"nodes": []},
                        "reviewThreads": {"nodes": []},
                        "comments": {"nodes": []},
                        "reactions": {
                            "nodes": [
                                {
                                    "content": "THUMBS_UP",
                                    "createdAt": "2026-06-30T10:05:00Z",
                                    "user": {"login": "chatgpt-codex-connector"},
                                }
                            ]
                        },
                        "reactionGroups": [
                            {
                                "content": "+1",
                                "reactors": {"nodes": [{"login": "chatgpt-codex-connector[bot]"}]},
                            }
                        ],
                    },
                }
            }
        }

    verdict = resolve_codex_verdict(
        repo="RasmusTho/agentic-pkm-mvp",
        pr=2682,
        head_started_at="2026-06-30T10:00:00Z",
        client=client,
    )

    assert verdict.status == "pass"
    assert len(calls) == 1
    query, variables = calls[0]
    assert variables == {"owner": "RasmusTho", "repo": "agentic-pkm-mvp", "pr": 2682}
    assert "reactionGroups" in query
    assert "reactions(first: 100, after: $reactionsCursor)" in query
    assert "reviews(first: 100, after: $reviewsCursor)" in query
    assert "reviewThreads(first: 100, after: $threadsCursor)" in query
    assert "... on User" in query


def test_codex_verdict_pages_top_level_connections() -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def client(query: str, variables: dict[str, object]) -> dict[str, object]:
        calls.append((query, variables))
        thread_page = variables.get("threadsCursor")
        return {
            "data": {
                "repository": {
                    "pullRequest": {
                        "reviews": {"pageInfo": {"hasNextPage": False}, "nodes": []},
                        "reviewThreads": {
                            "pageInfo": {
                                "hasNextPage": thread_page is None,
                                "endCursor": "thread-page-1" if thread_page is None else None,
                            },
                            "nodes": [
                                {
                                    "id": "thread-1" if thread_page is None else "thread-2",
                                    "comments": {
                                        "pageInfo": {"hasNextPage": False},
                                        "nodes": []
                                        if thread_page is None
                                        else [
                                            {
                                                "author": {"login": "chatgpt-codex-connector"},
                                                "body": "finding",
                                                "originalCommit": {"oid": "head-sha"},
                                            }
                                        ],
                                    },
                                }
                            ],
                        },
                        "comments": {"pageInfo": {"hasNextPage": False}, "nodes": []},
                        "reactions": {"pageInfo": {"hasNextPage": False}, "nodes": []},
                        "reactionGroups": [],
                    },
                }
            }
        }

    verdict = resolve_codex_verdict(
        repo="RasmusTho/agentic-pkm-mvp",
        pr=2682,
        head_sha="head-sha",
        client=client,
    )

    assert verdict.status == "blocking"
    assert len(calls) == 2
    assert calls[1][1]["threadsCursor"] == "thread-page-1"


def test_codex_verdict_pages_nested_thread_comments() -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def client(query: str, variables: dict[str, object]) -> dict[str, object]:
        calls.append((query, variables))
        if "threadId" in variables:
            return {
                "data": {
                    "node": {
                        "comments": {
                            "pageInfo": {"hasNextPage": False},
                            "nodes": [
                                {
                                    "author": {"login": "chatgpt-codex-connector"},
                                    "body": "finding",
                                    "originalCommit": {"oid": "head-sha"},
                                }
                            ],
                        }
                    }
                }
            }
        return {
            "data": {
                "repository": {
                    "pullRequest": {
                        "reviews": {"pageInfo": {"hasNextPage": False}, "nodes": []},
                        "reviewThreads": {
                            "pageInfo": {"hasNextPage": False},
                            "nodes": [
                                {
                                    "id": "thread-1",
                                    "comments": {
                                        "pageInfo": {
                                            "hasNextPage": True,
                                            "endCursor": "comment-page-1",
                                        },
                                        "nodes": [],
                                    },
                                }
                            ],
                        },
                        "comments": {"pageInfo": {"hasNextPage": False}, "nodes": []},
                        "reactions": {"pageInfo": {"hasNextPage": False}, "nodes": []},
                        "reactionGroups": [],
                    },
                }
            }
        }

    verdict = resolve_codex_verdict(
        repo="RasmusTho/agentic-pkm-mvp",
        pr=2682,
        head_sha="head-sha",
        client=client,
    )

    assert verdict.status == "blocking"
    assert len(calls) == 2
    assert calls[1][1] == {"threadId": "thread-1", "commentsCursor": "comment-page-1"}
