"""GitHub live plane: read-time REST join for the BuilderOps cockpit registry.

Implements BUILDEROPS_COCKPIT/GITHUB_LIVE_PLANE.md (BOPS-COCKPIT-03, #4450). This
module owns exactly one job: fetch open issues, open PRs, PR->issue edges,
per-SHA check state, and the branch list from GitHub, via REST only (never
GraphQL — the shared REST/GraphQL budget on this host dies on GraphQL first),
at the instant it is called.

Decision Q5 (docs/BUILDEROPS_COCKPIT/DESIGN_DECISIONS.md :: Q5) governs the
degradation posture enforced here:

- No cache survives a reload. Every call to :func:`fetch_github_live` performs
  its own read; nothing module-level is memoized across calls.
- A failed or rate-limited read degrades to the refused-claim state
  (``state="unavailable"``) for every GitHub-owned fact — never a zero count,
  never stale data presented as fresh.
- The reader is injectable (:data:`GithubReader`) so tests exercise the join
  logic with a fake reader and no network in CI; :func:`default_github_reader`
  is the only code path that shells out to ``gh``.

This module never writes to GitHub and never touches
``app/dispatcher/sync_github.py`` or ``scripts/issue_pickup_claim.sh`` — those
own the dispatcher's pull-sync mirror and are out of scope here (#4440/#4441).
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

__all__ = [
    "GithubIssue",
    "GithubPull",
    "GithubLiveSnapshot",
    "GithubLiveResult",
    "GithubReadError",
    "GithubReader",
    "default_github_reader",
    "fetch_github_live",
    "parse_governing_issue",
]

# Bounded REST pagination. A page cap that is hit is treated as a refusal
# (truncated snapshot), never a silently-partial success — the same posture
# `app/dispatcher/sync_github.py` uses for its own bounded REST pages.
_ISSUES_PAGE_SIZE = 100
_ISSUES_MAX_PAGES = 10
_PULLS_PAGE_SIZE = 100
_PULLS_MAX_PAGES = 10
_BRANCHES_PAGE_SIZE = 100
_BRANCHES_MAX_PAGES = 10

_GH_TIMEOUT_SECONDS = 20

_GOVERNING_ISSUE_RE = re.compile(r"(?im)^governing-issue:\s*#(\d+)\s*$")
_CLOSING_KEYWORD_RE = re.compile(
    r"(?im)\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s*:?\s*#(\d+)\b"
)


class GithubReadError(RuntimeError):
    """Raised when the live GitHub read cannot be completed.

    Every raise site here is caught by :func:`fetch_github_live`, which turns
    it into the refused-claim ``_SourceRead`` the cockpit registry renders —
    this exception type never escapes to a caller and never crashes the join.
    """


@dataclass(frozen=True)
class GithubIssue:
    number: int
    title: str
    state: str
    html_url: str


@dataclass(frozen=True)
class GithubPull:
    number: int
    title: str
    state: str
    html_url: str
    head_sha: str
    head_ref: str
    governing_issue: int | None


@dataclass(frozen=True)
class GithubLiveSnapshot:
    """Everything one live GitHub read produced, for one cockpit render.

    Immutable and process-local: a fresh instance is built on every
    :func:`fetch_github_live` call and nothing here is persisted (decision
    Q5 — no cache survives a reload).
    """

    read_at: str
    issues: dict[int, GithubIssue] = field(default_factory=dict)
    pulls: dict[int, GithubPull] = field(default_factory=dict)
    checks: dict[str, str] = field(default_factory=dict)  # head_sha -> combined state
    branches: tuple[str, ...] = ()
    # Head SHAs whose per-PR check-status read failed. Absence from `checks`
    # otherwise means "this SHA has no checks recorded" — a claim about GitHub.
    # A failed read is not that claim, and must not be able to impersonate it.
    check_read_failures: frozenset[str] = frozenset()

    def issue_url(self, issue_number: int | None) -> str | None:
        if issue_number is None:
            return None
        issue = self.issues.get(issue_number)
        return issue.html_url or None if issue else None

    def pull_url(self, pr_number: int | None) -> str | None:
        if pr_number is None:
            return None
        pull = self.pulls.get(pr_number)
        return pull.html_url or None if pull else None

    def authority_link(
        self, *, issue_number: int | None, pr_number: int | None
    ) -> str | None:
        """The nearest live authority link: the PR's own URL, else the issue's."""
        return self.pull_url(pr_number) or self.issue_url(issue_number)

    def check_state_for(self, head_sha: str | None) -> str | None:
        if not head_sha:
            return None
        return self.checks.get(head_sha)

    def check_read_failed(self, head_sha: str | None) -> bool:
        """True when this SHA's check state could not be read at all.

        Callers that treat a missing check state as evidence ("this PR has no
        CI") must consult this first: unread is not the same claim as absent.
        """
        if not head_sha:
            return False
        return head_sha in self.check_read_failures

    def pulls_governing(self, issue_number: int) -> list[GithubPull]:
        return [
            pull for pull in self.pulls.values() if pull.governing_issue == issue_number
        ]


@dataclass(frozen=True)
class GithubLiveResult:
    """The named-source-read shape :mod:`cockpit_registry` folds into ``sources``."""

    snapshot: GithubLiveSnapshot | None
    state: str  # "fresh" | "unavailable"
    last_successful_read: str | None
    detail: str


def parse_governing_issue(body: str | None) -> int | None:
    """Extract the PR->issue edge from a PR body.

    Prefers the explicit ``Governing-Issue: #N`` line (the CI-enforced
    convention this repo's PRs already carry); falls back to a GitHub closing
    keyword (``Fixes/Closes/Resolves #N``) so PRs authored before that
    convention still join. Returns ``None`` when neither is present — an
    absent edge, not a guessed one.
    """
    if not body:
        return None
    match = _GOVERNING_ISSUE_RE.search(body)
    if match:
        return int(match.group(1))
    match = _CLOSING_KEYWORD_RE.search(body)
    if match:
        return int(match.group(1))
    return None


def _run_gh(args: list[str]) -> Any:
    """Run one ``gh`` REST call and parse its JSON stdout.

    Every failure mode (missing binary, non-zero exit, timeout, non-JSON
    output) raises :class:`GithubReadError` — the single refusal signal
    :func:`fetch_github_live` catches. REST only: callers pass ``api
    repos/...`` args, never a GraphQL query.
    """
    try:
        result = subprocess.run(
            ["gh", *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=_GH_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as exc:
        raise GithubReadError(
            "gh CLI not found; ensure gh is installed and authenticated"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise GithubReadError(f"gh api call timed out: {' '.join(args)}") from exc
    if result.returncode != 0:
        raise GithubReadError(
            f"gh api call failed ({' '.join(args)}): {result.stderr.strip()}"
        )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise GithubReadError(
            f"gh api call returned non-JSON output ({' '.join(args)}): {exc}"
        ) from exc


def _paged_rest(
    owner: str,
    name: str,
    endpoint: str,
    *,
    page_size: int,
    max_pages: int,
    extra_fields: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for page in range(1, max_pages + 1):
        args = [
            "api",
            f"repos/{owner}/{name}/{endpoint}",
            "--method",
            "GET",
            "-F",
            f"per_page={page_size}",
            "-F",
            f"page={page}",
        ]
        for field_kv in extra_fields:
            args.extend(["-f", field_kv])
        payload = _run_gh(args)
        if not isinstance(payload, list):
            raise GithubReadError(f"gh api {endpoint} returned a non-list payload")
        items.extend(payload)
        if len(payload) < page_size:
            return items
    raise GithubReadError(
        f"gh api {endpoint} exceeded {max_pages} pages with more results likely "
        "remaining; refusing a truncated snapshot"
    )


def default_github_reader(repo: str) -> GithubLiveSnapshot:
    """Fetch the live GitHub plane via REST (never GraphQL) using the ``gh`` CLI.

    Bounded pagination, no retries: a failure here must surface promptly as a
    refused claim, not a retry loop or a stale render (decision Q5). Auth is
    whatever ``gh`` already resolves from the host environment (``gh auth
    login`` credentials or ``GITHUB_TOKEN``); an unauthenticated host simply
    fails the first REST call, which is caught by :func:`fetch_github_live`.
    """
    owner, _, name = repo.partition("/")
    if not name:
        raise GithubReadError(f"repo must be 'owner/name', got: {repo!r}")

    read_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # The raw /issues endpoint mixes pull requests into the same page budget;
    # filter them out here rather than paying for a second bounded page walk.
    raw_issues = _paged_rest(
        owner,
        name,
        "issues",
        page_size=_ISSUES_PAGE_SIZE,
        max_pages=_ISSUES_MAX_PAGES,
        extra_fields=("state=open",),
    )
    issues: dict[int, GithubIssue] = {}
    for node in raw_issues:
        if node.get("pull_request"):
            continue
        number = node.get("number")
        if number is None:
            continue
        issues[int(number)] = GithubIssue(
            number=int(number),
            title=str(node.get("title") or ""),
            state=str(node.get("state") or "open"),
            html_url=str(node.get("html_url") or ""),
        )

    raw_pulls = _paged_rest(
        owner,
        name,
        "pulls",
        page_size=_PULLS_PAGE_SIZE,
        max_pages=_PULLS_MAX_PAGES,
        extra_fields=("state=open",),
    )
    pulls: dict[int, GithubPull] = {}
    for node in raw_pulls:
        number = node.get("number")
        if number is None:
            continue
        head = node.get("head") or {}
        pulls[int(number)] = GithubPull(
            number=int(number),
            title=str(node.get("title") or ""),
            state=str(node.get("state") or "open"),
            html_url=str(node.get("html_url") or ""),
            head_sha=str(head.get("sha") or ""),
            head_ref=str(head.get("ref") or ""),
            governing_issue=parse_governing_issue(node.get("body")),
        )

    # Combined status per PR head SHA. One PR's check lookup failing does not
    # refuse the whole plane — but it is recorded as a failed read rather than
    # dropped, because "we could not read this SHA's checks" and "this SHA has
    # no checks" are different claims and only one of them is about GitHub.
    checks: dict[str, str] = {}
    check_read_failures: set[str] = set()
    for pull in pulls.values():
        if not pull.head_sha:
            continue
        try:
            status_payload = _run_gh(
                ["api", f"repos/{owner}/{name}/commits/{pull.head_sha}/status"]
            )
        except GithubReadError:
            check_read_failures.add(pull.head_sha)
            continue
        state = status_payload.get("state") if isinstance(status_payload, dict) else None
        if state:
            checks[pull.head_sha] = str(state)

    raw_branches = _paged_rest(
        owner,
        name,
        "branches",
        page_size=_BRANCHES_PAGE_SIZE,
        max_pages=_BRANCHES_MAX_PAGES,
    )
    branches = tuple(
        str(node["name"]) for node in raw_branches if node.get("name")
    )

    return GithubLiveSnapshot(
        read_at=read_at,
        issues=issues,
        pulls=pulls,
        checks=checks,
        branches=branches,
        check_read_failures=frozenset(check_read_failures),
    )


GithubReader = Callable[[str], GithubLiveSnapshot]


def fetch_github_live(
    repo: str | None,
    *,
    reader: GithubReader = default_github_reader,
) -> GithubLiveResult:
    """Read the live GitHub plane once, returning a named-source-read result.

    Refuses (``state="unavailable"``, ``snapshot=None``) rather than raising
    when ``repo`` is not configured or the reader fails for any reason — the
    caller (``cockpit_registry.build_registry``) must never see an exception
    from this function, matching the try/except-per-source pattern the rest
    of the registry already uses for the dispatcher store, verification
    runs, and deploy receipts.
    """
    if not repo:
        return GithubLiveResult(
            snapshot=None,
            state="unavailable",
            last_successful_read=None,
            detail="no repo configured for the live GitHub read"
            " (set COCKPIT_GITHUB_REPO)",
        )
    try:
        snapshot = reader(repo)
    except Exception as exc:  # noqa: BLE001 - any reader failure degrades to refusal
        return GithubLiveResult(
            snapshot=None,
            state="unavailable",
            last_successful_read=None,
            detail=f"read failed: {exc}",
        )
    detail = (
        f"{len(snapshot.issues)} open issues, {len(snapshot.pulls)} open PRs,"
        f" {len(snapshot.branches)} branches"
    )
    return GithubLiveResult(
        snapshot=snapshot,
        state="fresh",
        last_successful_read=snapshot.read_at,
        detail=detail,
    )
