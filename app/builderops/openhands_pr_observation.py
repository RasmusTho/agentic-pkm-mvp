"""Read-only public GitHub REST observation collector for PR completion intake.

Collects the contract facts GitHub itself reports (body, head, base, labels,
reviews, governing Issue). Owner, route, review/Verify/CI/closure evidence and
effect outcomes have no trusted source here and stay ``unknown``; this module
never authenticates, writes to GitHub, launches models or runs shell commands.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

from app.builderops.devui_issue_work import _governs
from app.builderops.openhands_pr_completion import REPOSITORY, intake, work_identity

API_ROOT = "https://api.github.com"
PER_PAGE = 100
MAX_PAGES = 5
MAX_RESPONSE_BYTES = 2_000_000
REQUEST_TIMEOUT = 15.0
DEADLINE_SECONDS = 120.0
HELD_ISSUES = (6588,)
UNSUPPORTED = ("trusted_owner", "route", "review_outcome", "verify_evidence", "ci",
               "closure_authorization", "effect_outcomes")

Fetch = Callable[[str, float], tuple[int, bytes]]

_PATH = re.compile(rf"/repos/{re.escape(REPOSITORY)}/(pulls|issues)(/[1-9][0-9]*(/reviews)?)?"
                   r"(\?(state=open&)?per_page=[0-9]+&page=[1-9][0-9]*)?")
_MARKER = re.compile(r"(?im)^[ \t]{0,3}Governing-Issue[ \t]*:[ \t]*#([1-9][0-9]*)")
_REVIEW_STATES = ("APPROVED", "CHANGES_REQUESTED", "COMMENTED", "DISMISSED", "PENDING")


class ObservationError(Exception):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def public_fetch(path: str, timeout: float) -> tuple[int, bytes]:
    """Unauthenticated GET against the pinned GitHub API host and repository only."""
    if not _PATH.fullmatch(path):
        raise ObservationError("path outside the pinned repository")
    request = urllib.request.Request(
        API_ROOT + path, method="GET",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "pkm-pr-observation"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    try:
        with opener.open(request, timeout=timeout) as response:
            return response.status, response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        return exc.code, b""
    except (OSError, urllib.error.URLError) as exc:
        raise ObservationError(f"transport failure: {type(exc).__name__}") from exc


class _Reader:
    def __init__(self, fetch: Fetch, clock: Callable[[], float]) -> None:
        self.fetch, self.clock = fetch, clock
        self.stop = clock() + DEADLINE_SECONDS

    def get(self, path: str) -> Any:
        remaining = self.stop - self.clock()
        if remaining <= 0:
            raise ObservationError("scan deadline exceeded")
        status, body = self.fetch(path, min(REQUEST_TIMEOUT, remaining))
        if status != 200:
            raise ObservationError(f"HTTP {status} for {path.split('?')[0]}")
        if len(body) > MAX_RESPONSE_BYTES:
            raise ObservationError("response exceeds size bound")
        try:
            return json.loads(body)
        except ValueError as exc:
            raise ObservationError("response is not JSON") from exc

    def pages(self, path: str, limit: int, rows: list[Any] | None = None) -> list[Any]:
        rows = [] if rows is None else rows
        for page in range(1, limit + 1):
            sep = "&" if "?" in path else "?"
            data = self.get(f"{path}{sep}per_page={PER_PAGE}&page={page}")
            if not isinstance(data, list):
                raise ObservationError("expected a JSON list")
            rows.extend(data)
            if len(data) < PER_PAGE:
                return rows
        raise ObservationError("pagination truncated at the page bound")


def _text(value: Any, what: str) -> str:
    if not isinstance(value, str) or not value:
        raise ObservationError(f"{what} missing")
    return value


def _governing_number(body: str) -> int:
    numbers = {int(n) for n in _MARKER.findall(body)}
    if not numbers:
        raise ObservationError("governing issue missing")
    if len(numbers) > 1:
        raise ObservationError("governing issue conflicting")
    (number,) = numbers
    if not _governs(body, number):
        raise ObservationError("governing issue marker not exactly one canonical line")
    return number


def _observe(reader: _Reader, number: int) -> dict[str, Any] | None:
    """Return the intake observation, or None for a PR that is now closed."""
    pr = reader.get(f"/repos/{REPOSITORY}/pulls/{number}")
    if not isinstance(pr, dict) or pr.get("number") != number:
        raise ObservationError("PR identity mismatch")
    state = pr.get("state")
    if state not in ("open", "closed"):
        raise ObservationError(f"PR state null or unknown (KD-D5A2534ED444): {state!r}")
    if state == "closed":
        return None
    head, base = pr.get("head"), pr.get("base")
    if (not isinstance(head, dict) or not isinstance(base, dict) or type(pr.get("draft")) is not bool
            or not isinstance(pr.get("labels"), list)
            or not all(isinstance(x, dict) and isinstance(x.get("name"), str) for x in pr["labels"])):
        raise ObservationError("PR contract fields unreadable")
    body = pr.get("body") or ""
    if not isinstance(body, str):
        raise ObservationError("PR body unreadable")
    head_repo = head.get("repo")
    head_repository = head_repo.get("full_name") if isinstance(head_repo, dict) else None
    governing = _governing_number(body)
    issue = reader.get(f"/repos/{REPOSITORY}/issues/{governing}")
    if (not isinstance(issue, dict) or issue.get("number") != governing or "pull_request" in issue
            or issue.get("state") not in ("open", "closed") or not isinstance(issue.get("body"), str)
            or not issue["body"].strip()):
        raise ObservationError("governing issue unreadable")
    reviews = []
    for row in reader.pages(f"/repos/{REPOSITORY}/pulls/{number}/reviews", MAX_PAGES):
        user = row.get("user") if isinstance(row, dict) else None
        if (not isinstance(user, dict) or not isinstance(user.get("login"), str)
                or row.get("state") not in _REVIEW_STATES):
            raise ObservationError("review record unreadable")
        reviews.append({"user": {"login": user["login"]}, "state": row["state"],
                        "submitted_at": row.get("submitted_at")})
    held = [f"#{n} hold" for n in HELD_ISSUES
            if n in (number, governing) or re.search(rf"#{n}(?![0-9])", body)]
    return {
        "repository": REPOSITORY, "number": number, "state": "open",
        "head_repository": head_repository if isinstance(head_repository, str) else "unknown",
        "head_sha": _text(head.get("sha"), "head sha"), "body": body, "draft": pr["draft"],
        "labels": [x["name"] for x in pr["labels"]],
        "base_ref": _text(base.get("ref"), "base ref"), "base_sha": _text(base.get("sha"), "base sha"),
        "governing_issue": {"body": issue["body"], "state": issue["state"]},
        "reviews": reviews, "verification": {}, "restrictions": held,
        "owner": "unknown", "route": "unknown", "effect_outcome": "unknown", "effect_outcomes": {},
        "ci": "unknown", "verify_evidence": "unknown", "review_outcome": "unknown",
        "independent_review_identity": None, "closure_authorized": "unknown",
    }


def collect(fetch: Fetch = public_fetch, *, clock: Callable[[], float] = time.monotonic) -> dict[str, Any]:
    reader = _Reader(fetch, clock)
    failures: list[dict[str, Any]] = []
    numbers: list[int] = []
    complete = True
    listed: list[Any] = []
    try:
        reader.pages(f"/repos/{REPOSITORY}/pulls?state=open", MAX_PAGES, listed)
    except ObservationError as exc:
        failures.append({"number": None, "reason": f"inventory incomplete: {exc}"})
        complete = False
    for row in listed:
        number = row.get("number") if isinstance(row, dict) else None
        if type(number) is not int or number <= 0:
            failures.append({"number": None, "reason": "inventory entry unreadable"})
            complete = False
        elif number not in numbers:
            numbers.append(number)
    observations: list[dict[str, Any]] = []
    closed: list[int] = []
    for number in numbers:
        try:
            observed = _observe(reader, number)
        except (ObservationError, AttributeError, KeyError, TypeError, ValueError) as exc:
            failures.append({"number": number, "reason": str(exc) or type(exc).__name__})
            continue
        if observed is None:
            closed.append(number)
        else:
            observations.append(observed)
    return {"repository": REPOSITORY, "complete": complete and not failures,
            "inventory_complete": complete, "observations": observations,
            "identities": {o["number"]: work_identity(o) for o in observations},
            "closed": closed, "failures": failures, "unsupported": list(UNSUPPORTED)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only public PR observation scan.")
    parser.add_argument("--run-id")
    parser.add_argument("--root")
    parser.add_argument("--epic-issue", type=int)
    args = parser.parse_args(argv)
    report = collect(public_fetch)
    if args.run_id:
        if not args.root or args.epic_issue is None:
            parser.error("--run-id requires --root and --epic-issue")
        report["decisions"] = intake(
            report["observations"], run_id=args.run_id, root=Path(args.root),
            expected_run_id=args.run_id, expected_root=Path(args.root),
            expected_epic_issue_number=args.epic_issue)
    json.dump(report, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0 if report["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
