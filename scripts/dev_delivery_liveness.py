"""Check that the post-merge dev controller is alive and making progress.

The private controller publishes two credential-free GitHub commit-status
signals: a frequently refreshed heartbeat on the current ``main`` commit and
a dev verdict on each admitted build.  This scheduled workflow only reads
those signals and the successful image-build runs; it never receives channel
or deployment credentials.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import subprocess
from typing import Any, Callable

REPOSITORY = "RasmusTho/agentic-pkm-mvp"
BUILD_WORKFLOW = ".github/workflows/app-image-build.yml"
HEARTBEAT_CONTEXT = "post-merge-dev-test/heartbeat"
VERDICT_CONTEXT = "post-merge-dev-test/verdict"
GRACE = timedelta(hours=6)
HEARTBEAT_GRACE = timedelta(hours=2)


class LivenessRefused(ValueError):
    """Raised when GitHub evidence cannot be trusted as a liveness signal."""


@dataclass(frozen=True)
class AdmittedBuild:
    sha: str
    completed_at: datetime
    run_id: int


@dataclass(frozen=True)
class LivenessResult:
    ok: bool
    reason: str
    description: str


def _timestamp(value: Any) -> datetime:
    if not isinstance(value, str):
        raise LivenessRefused("timestamp_missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise LivenessRefused("timestamp_invalid") from None
    if parsed.tzinfo is None:
        raise LivenessRefused("timestamp_timezone_missing")
    return parsed.astimezone(timezone.utc)


def _status_timestamp(status: dict[str, Any]) -> datetime:
    return _timestamp(status.get("updated_at") or status.get("created_at"))


def _validate_sha(value: Any) -> str:
    if not isinstance(value, str) or len(value) != 40 or any(char not in "0123456789abcdef" for char in value):
        raise LivenessRefused("sha_invalid")
    return value


def latest_admitted_build(repo: str, *, api: Callable[[str], Any]) -> AdmittedBuild | None:
    payload = api(
        f"repos/{repo}/actions/workflows/app-image-build.yml/runs"
        "?branch=main&event=push&status=completed&per_page=20"
    )
    if not isinstance(payload, dict) or not isinstance(payload.get("workflow_runs"), list):
        raise LivenessRefused("build_runs_unreadable")
    candidates = []
    for run in payload["workflow_runs"]:
        if not isinstance(run, dict):
            continue
        repository = run.get("repository") or {}
        head_repository = run.get("head_repository") or {}
        if (run.get("status") != "completed" or run.get("conclusion") != "success"
                or run.get("event") != "push"
                or run.get("head_branch") != "main"
                or run.get("path") not in {None, BUILD_WORKFLOW}
                or repository.get("full_name") != repo
                or head_repository.get("full_name") != repo):
            continue
        try:
            sha = _validate_sha(run.get("head_sha"))
            completed_at = _timestamp(run.get("completed_at") or run.get("updated_at"))
            run_id = int(run["id"])
            if run_id < 1:
                raise ValueError()
        except (KeyError, TypeError, ValueError, LivenessRefused):
            continue
        candidates.append(AdmittedBuild(sha, completed_at, run_id))
    if not candidates:
        return None
    return max(candidates, key=lambda candidate: candidate.completed_at)


def _latest_status(statuses: Any, context: str) -> dict[str, Any] | None:
    if not isinstance(statuses, list):
        raise LivenessRefused("statuses_unreadable")
    matching = [
        status for status in statuses
        if isinstance(status, dict) and status.get("context") == context
    ]
    if not matching:
        return None
    return max(matching, key=_status_timestamp)


def evaluate(
    build: AdmittedBuild | None,
    *,
    heartbeat_statuses: Any,
    verdict_statuses: Any,
    now: datetime,
) -> LivenessResult:
    """Evaluate freshness without treating the dev result as a merge gate."""
    current = now.astimezone(timezone.utc)
    verdict = _latest_status(verdict_statuses, VERDICT_CONTEXT)
    if (build is not None and verdict is not None
            and verdict.get("state") in {"success", "failure"}
            and _status_timestamp(verdict) >= build.completed_at):
        # A fresh terminal verdict is itself proof that the controller was
        # alive. This also lets a fresh verdict recover a stale heartbeat
        # signal while the next heartbeat update is in flight.
        return LivenessResult(True, "fresh_dev_verdict", f"dev verdict is fresh for {build.sha[:12]}")

    heartbeat = _latest_status(heartbeat_statuses, HEARTBEAT_CONTEXT)
    if heartbeat is None or heartbeat.get("state") != "success":
        return LivenessResult(False, "heartbeat_missing", "post-merge dev controller heartbeat is missing")
    heartbeat_age = current - _status_timestamp(heartbeat)
    if heartbeat_age > HEARTBEAT_GRACE:
        hours = int(HEARTBEAT_GRACE.total_seconds() // 3600)
        return LivenessResult(False, "heartbeat_stale", f"controller heartbeat is older than {hours} h")

    if build is None:
        return LivenessResult(True, "no_admitted_build", "no successful admitted main build is available")

    if current - build.completed_at > GRACE:
        hours = int(GRACE.total_seconds() // 3600)
        return LivenessResult(False, "missing_dev_verdict", f"no dev verdict for {build.sha[:12]} within {hours} h")
    return LivenessResult(True, "within_grace", f"dev verdict for {build.sha[:12]} is within the grace period")


def _github(path: str) -> Any:
    result = subprocess.run(["gh", "api", path], capture_output=True, text=True, check=True, timeout=60)
    return json.loads(result.stdout)


def check(repo: str, github_sha: str, *, api: Callable[[str], Any] = _github,
          now: datetime | None = None) -> LivenessResult:
    _validate_sha(github_sha)
    current = now or datetime.now(timezone.utc)
    build = latest_admitted_build(repo, api=api)
    heartbeat = api(f"repos/{repo}/commits/{github_sha}/statuses?per_page=100")
    verdict = api(f"repos/{repo}/commits/{build.sha}/statuses?per_page=100") if build else []
    return evaluate(build, heartbeat_statuses=heartbeat, verdict_statuses=verdict, now=current)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=REPOSITORY)
    parser.add_argument("--github-sha", required=True)
    args = parser.parse_args(argv)
    try:
        result = check(args.repo, _validate_sha(args.github_sha))
    except Exception as error:
        result = LivenessResult(False, "evidence_refused", str(error))
    print(json.dumps({"ok": result.ok, "reason": result.reason, "description": result.description}, sort_keys=True))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
