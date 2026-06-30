"""Shared GitHub polling backoff helpers for builder delivery workflows."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import timezone
import email.utils
import json
import subprocess
import time
from typing import Any, Callable, Mapping, Protocol, TypeVar


T = TypeVar("T")

POSITIVE_REACTIONS = {"+1", "heart", "hooray", "rocket", "laugh"}
NEGATIVE_REACTIONS = {"-1", "confused"}
CODEX_BOT_LOGINS = {"chatgpt-codex-connector[bot]", "chatgpt-codex-connector"}


@dataclass(frozen=True)
class PollPolicy:
    """Bounded polling policy shared by CI and Codex wait loops."""

    interval_seconds: float = 90.0
    max_attempts: int = 20
    max_elapsed_seconds: float = 1800.0
    backoff_multiplier: float = 1.5
    max_interval_seconds: float = 300.0


@dataclass(frozen=True)
class PollResponse:
    """One polling response plus optional GitHub rate-limit headers."""

    value: Any
    headers: Mapping[str, str] | None = None


class Clock(Protocol):
    def __call__(self) -> float: ...


class Sleeper(Protocol):
    def __call__(self, seconds: float) -> None: ...


def _header(headers: Mapping[str, str] | None, name: str) -> str | None:
    if not headers:
        return None
    lowered = name.lower()
    for key, value in headers.items():
        if key.lower() == lowered:
            return value
    return None


def retry_after_seconds(headers: Mapping[str, str] | None, *, now: float | None = None) -> float | None:
    """Return the sleep requested by Retry-After/x-ratelimit-reset, if present."""

    if now is None:
        now = time.time()

    retry_after = _header(headers, "Retry-After")
    if retry_after:
        try:
            return max(0.0, float(retry_after))
        except ValueError:
            try:
                parsed = email.utils.parsedate_to_datetime(retry_after)
            except (TypeError, ValueError):
                parsed = None
            if parsed is not None:
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return max(0.0, parsed.timestamp() - now)

    remaining = _header(headers, "x-ratelimit-remaining")
    reset = _header(headers, "x-ratelimit-reset")
    if remaining == "0" and reset:
        try:
            return max(0.0, float(reset) - now)
        except ValueError:
            return None
    return None


def poll_until(
    attempt: Callable[[], PollResponse],
    is_done: Callable[[Any], bool],
    *,
    policy: PollPolicy | None = None,
    clock: Clock = time.time,
    sleeper: Sleeper = time.sleep,
) -> Any:
    """Poll until ``is_done`` returns true, respecting caps and GitHub backoff headers."""

    policy = policy or PollPolicy()
    start = clock()
    delay = policy.interval_seconds
    last_value: Any = None

    for attempt_number in range(1, policy.max_attempts + 1):
        response = attempt()
        last_value = response.value
        if is_done(response.value):
            return response.value

        elapsed = clock() - start
        if attempt_number >= policy.max_attempts or elapsed >= policy.max_elapsed_seconds:
            raise TimeoutError(
                f"poll timed out after {attempt_number} attempts/{elapsed:.1f}s; last={last_value!r}"
            )

        requested = retry_after_seconds(response.headers, now=clock())
        sleep_for = requested if requested is not None else delay
        remaining = max(0.0, policy.max_elapsed_seconds - elapsed)
        sleeper(min(sleep_for, remaining))
        delay = min(policy.max_interval_seconds, delay * policy.backoff_multiplier)

    raise TimeoutError(f"poll timed out; last={last_value!r}")


CODEX_VERDICT_QUERY = """
query CodexVerdict(
  $owner: String!,
  $repo: String!,
  $pr: Int!,
  $reviewsCursor: String,
  $threadsCursor: String,
  $issueCommentsCursor: String,
  $reactionsCursor: String
) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $pr) {
      reviews(first: 100, after: $reviewsCursor) {
        pageInfo { hasNextPage endCursor }
        nodes {
          author { login }
          state
          body
          commit { oid }
        }
      }
      reviewThreads(first: 100, after: $threadsCursor) {
        pageInfo { hasNextPage endCursor }
        nodes {
          id
          comments(first: 100) {
            pageInfo { hasNextPage endCursor }
            nodes {
              author { login }
              body
              originalCommit { oid }
            }
          }
        }
      }
      comments(first: 100, after: $issueCommentsCursor) {
        pageInfo { hasNextPage endCursor }
        nodes {
          author { login }
          body
          createdAt
        }
      }
      reactions(first: 100, after: $reactionsCursor) {
        pageInfo { hasNextPage endCursor }
        nodes {
          content
          createdAt
          user {
            login
          }
        }
      }
      reactionGroups {
        content
        reactors(first: 100) {
          nodes {
            ... on User {
              login
            }
          }
        }
      }
    }
  }
}
"""


CODEX_THREAD_COMMENTS_QUERY = """
query CodexThreadComments($threadId: ID!, $commentsCursor: String) {
  node(id: $threadId) {
    ... on PullRequestReviewThread {
      comments(first: 100, after: $commentsCursor) {
        pageInfo { hasNextPage endCursor }
        nodes {
          author { login }
          body
          originalCommit { oid }
        }
      }
    }
  }
}
"""


@dataclass(frozen=True)
class CodexVerdict:
    status: str
    reason: str

    @property
    def is_pass(self) -> bool:
        return self.status == "pass"


def _is_codex_login(login: str | None) -> bool:
    return bool(login in CODEX_BOT_LOGINS)


def parse_codex_verdict(
    payload: Mapping[str, Any],
    *,
    head_sha: str | None = None,
    head_started_at: str | None = None,
) -> CodexVerdict:
    """Classify Codex verdict evidence returned by ``CODEX_VERDICT_QUERY``."""

    repo = payload.get("data", {}).get("repository", {})
    pr = repo.get("pullRequest") or {}
    reviews = pr.get("reviews", {}).get("nodes") or []
    review_threads = pr.get("reviewThreads", {}).get("nodes") or []
    issue_comments = pr.get("comments", {}).get("nodes") or []
    reactions = pr.get("reactions", {}).get("nodes") or []

    paginated_surfaces = [
        pr.get("reviews", {}).get("pageInfo", {}).get("hasNextPage"),
        pr.get("reviewThreads", {}).get("pageInfo", {}).get("hasNextPage"),
        pr.get("comments", {}).get("pageInfo", {}).get("hasNextPage"),
        pr.get("reactions", {}).get("pageInfo", {}).get("hasNextPage"),
    ]
    paginated_surfaces.extend(
        (thread.get("comments") or {}).get("pageInfo", {}).get("hasNextPage")
        for thread in review_threads
    )
    if any(paginated_surfaces):
        return CodexVerdict("unresolved", "Codex verdict evidence is paginated; fetch more before merging")

    codex_reviews = [r for r in reviews if _is_codex_login((r.get("author") or {}).get("login"))]
    pr_comments = [
        comment
        for thread in review_threads
        for comment in ((thread.get("comments") or {}).get("nodes") or [])
    ]
    codex_pr_comments = [c for c in pr_comments if _is_codex_login((c.get("author") or {}).get("login"))]
    codex_issue_comments = [c for c in issue_comments if _is_codex_login((c.get("author") or {}).get("login"))]

    def on_head(node: Mapping[str, Any], key: str) -> bool:
        if not head_sha:
            return True
        obj = node.get(key) or {}
        return obj.get("oid") == head_sha

    head_reviews = [r for r in codex_reviews if on_head(r, "commit")]
    if any(r.get("state") == "CHANGES_REQUESTED" for r in head_reviews):
        return CodexVerdict("blocking", "Codex requested changes on the verified head")
    if any("Useful? React" in (r.get("body") or "") for r in head_reviews):
        return CodexVerdict("blocking", "Codex review body contains findings on the verified head")
    if any(on_head(c, "originalCommit") for c in codex_pr_comments):
        return CodexVerdict("blocking", "Codex inline comments exist on the verified head")
    fresh_issue_findings = [
        c
        for c in codex_issue_comments
        if "Useful? React" in (c.get("body") or "")
        and (not head_started_at or str(c.get("createdAt") or "") > head_started_at)
    ]
    if fresh_issue_findings:
        return CodexVerdict("blocking", "Codex conversation comments contain findings")

    bot_reactions = [
        r
        for r in reactions
        if _is_codex_login((r.get("user") or {}).get("login"))
    ]
    fresh_negative_reactions = [
        r
        for r in bot_reactions
        if str(r.get("content") or "").replace("THUMBS_DOWN", "-1").replace("CONFUSED", "confused")
        in NEGATIVE_REACTIONS
        and (not head_started_at or str(r.get("createdAt") or "") > head_started_at)
    ]
    if fresh_negative_reactions:
        return CodexVerdict("blocking", "Codex left a negative reaction")
    fresh_positive_reactions = [
        r
        for r in bot_reactions
        if str(r.get("content") or "")
        .replace("THUMBS_UP", "+1")
        .replace("LAUGH", "laugh")
        .replace("HOORAY", "hooray")
        .replace("HEART", "heart")
        .replace("ROCKET", "rocket")
        in POSITIVE_REACTIONS
        and (not head_started_at or str(r.get("createdAt") or "") > head_started_at)
    ]
    if head_reviews or fresh_positive_reactions:
        return CodexVerdict("pass", "Codex verdict passed")
    return CodexVerdict("unresolved", "No Codex verdict found")


class GraphQLClient(Protocol):
    def __call__(self, query: str, variables: Mapping[str, Any]) -> Mapping[str, Any]: ...


def _pull_request(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    return payload.get("data", {}).get("repository", {}).get("pullRequest") or {}


def _connection(payload: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    return _pull_request(payload).get(name) or {}


def _page_info(connection: Mapping[str, Any]) -> Mapping[str, Any]:
    return connection.get("pageInfo") or {}


def _merge_connection_nodes(target: dict[str, Any], page: Mapping[str, Any], name: str) -> None:
    target_pr = target["data"]["repository"]["pullRequest"]
    target_connection = target_pr.setdefault(name, {"nodes": [], "pageInfo": {}})
    page_connection = _connection(page, name)
    target_connection.setdefault("nodes", []).extend(page_connection.get("nodes") or [])
    target_connection["pageInfo"] = dict(_page_info(page_connection))


def _fetch_complete_codex_payload(
    client: GraphQLClient,
    variables: Mapping[str, Any],
    *,
    max_pages: int = 100,
) -> Mapping[str, Any]:
    payload = deepcopy(client(CODEX_VERDICT_QUERY, variables))
    cursor_vars = {
        "reviews": "reviewsCursor",
        "reviewThreads": "threadsCursor",
        "comments": "issueCommentsCursor",
        "reactions": "reactionsCursor",
    }

    for _ in range(max_pages):
        cursors = {
            var_name: _page_info(_connection(payload, connection_name)).get("endCursor")
            for connection_name, var_name in cursor_vars.items()
            if _page_info(_connection(payload, connection_name)).get("hasNextPage")
        }
        if not cursors:
            break
        if any(cursor in (None, "") for cursor in cursors.values()):
            return payload

        page_variables = dict(variables)
        page_variables.update(cursors)
        page = client(CODEX_VERDICT_QUERY, page_variables)
        for connection_name, var_name in cursor_vars.items():
            if var_name in cursors:
                _merge_connection_nodes(payload, page, connection_name)

    review_threads = ((_pull_request(payload).get("reviewThreads") or {}).get("nodes") or [])
    for thread in review_threads:
        comments = thread.get("comments") or {}
        for _ in range(max_pages):
            page_info = _page_info(comments)
            if not page_info.get("hasNextPage"):
                break
            cursor = page_info.get("endCursor")
            thread_id = thread.get("id")
            if not cursor or not thread_id:
                break
            page = client(
                CODEX_THREAD_COMMENTS_QUERY,
                {"threadId": thread_id, "commentsCursor": cursor},
            )
            page_comments = ((page.get("data") or {}).get("node") or {}).get("comments") or {}
            comments.setdefault("nodes", []).extend(page_comments.get("nodes") or [])
            comments["pageInfo"] = dict(_page_info(page_comments))
            thread["comments"] = comments
    return payload


def resolve_codex_verdict(
    *,
    repo: str,
    pr: int,
    head_sha: str | None = None,
    head_started_at: str | None = None,
    client: GraphQLClient | None = None,
) -> CodexVerdict:
    """Resolve the Codex verdict with one combined GraphQL query."""

    owner, name = repo.split("/", 1)
    if client is None:
        client = gh_graphql
    payload = _fetch_complete_codex_payload(client, {"owner": owner, "repo": name, "pr": pr})
    return parse_codex_verdict(payload, head_sha=head_sha, head_started_at=head_started_at)


def gh_graphql(query: str, variables: Mapping[str, Any]) -> Mapping[str, Any]:
    args = ["gh", "api", "graphql", "-f", f"query={query}"]
    for key, value in variables.items():
        flag = "-F" if isinstance(value, int) else "-f"
        args.extend([flag, f"{key}={value}"])
    result = subprocess.run(args, check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    verdict_parser = sub.add_parser("codex-verdict")
    verdict_parser.add_argument("--repo", required=True)
    verdict_parser.add_argument("--pr", required=True, type=int)
    verdict_parser.add_argument("--sha")
    verdict_parser.add_argument("--head-started-at")
    args = parser.parse_args(argv)

    if args.command == "codex-verdict":
        verdict = resolve_codex_verdict(
            repo=args.repo,
            pr=args.pr,
            head_sha=args.sha,
            head_started_at=args.head_started_at,
        )
        print(json.dumps({"status": verdict.status, "reason": verdict.reason}))
        return {"pass": 0, "blocking": 3, "unresolved": 4}[verdict.status]
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
