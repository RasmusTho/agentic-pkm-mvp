"""Resolve what a post-merge heavy-tests workflow run must do (#6158).

The heavy targets `scripts/select_pr_tests.py` defers from the PR path run on
the ygg `test` VM. The private host controller dispatches
`.github/workflows/post-merge-heavy-tests.yml` with a bounded verdict, and this
script decides the run's mode:

- `verdict`: a host-dispatched verdict for a commit on `main`. The workflow
  records the `post-merge-heavy-tests/ygg` commit status and goes red unless
  the verdict is `passed`.
- `fallback`: the GitHub-hosted heavy job runs for one SHA. The hourly watchdog
  selects it when no ygg verdict arrived within the grace period; a manual
  dispatch without a verdict selects it for the dispatched ref.
- `noop`: the watchdog found a verdict (or an earlier fallback) in time.

A missing verdict is red even when the fallback passes: the VM path is broken.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import re
import subprocess
from typing import Any, Callable

YGG_CONTEXT = "post-merge-heavy-tests/ygg"
FALLBACK_CONTEXT = "post-merge-heavy-tests/fallback"
GRACE = timedelta(hours=6)
VERDICTS = ("passed", "failed", "refused")
_COUNTS = re.compile(r"(?:(?:selected|passed|failed|skipped|docker_skipped)=\d{1,7} ?){0,5}")
_FAILURES = re.compile(r"[A-Za-z0-9_./:\[\]@+=, -]{0,1000}")


class VerdictRefused(ValueError):
    pass


@dataclass(frozen=True)
class Resolution:
    mode: str
    sha: str
    reason: str
    description: str = ""

    def outputs(self) -> dict[str, str]:
        return {"mode": self.mode, "sha": self.sha, "reason": self.reason, "description": self.description}


def validate_verdict(inputs: dict[str, str]) -> Resolution:
    sha = inputs.get("sha", "")
    verdict = inputs.get("verdict", "")
    operation_id = inputs.get("operation_id", "")
    counts = inputs.get("counts", "")
    reason = inputs.get("reason", "")
    failures = inputs.get("failures", "")
    if (re.fullmatch(r"[0-9a-f]{40}", sha) is None or verdict not in VERDICTS
        or re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", operation_id) is None
        or _COUNTS.fullmatch(counts) is None or re.fullmatch(r"[a-z0-9_]{0,64}", reason) is None
        or _FAILURES.fullmatch(failures) is None
        or (verdict == "refused") != bool(reason)
        or (verdict == "passed" and failures)):
        raise VerdictRefused("malformed ygg verdict")
    detail = reason if verdict == "refused" else counts.strip()
    description = f"ygg-test {verdict}: {detail}"[:140]
    why = f"ygg-test verdict {verdict}" + (f" ({reason})" if reason else "")
    if failures:
        why += f"; failing: {failures}"
    return Resolution("verdict", sha, why, description)


def watchdog(commits: list[dict[str, Any]], contexts: Callable[[str], set[str]], now: datetime) -> Resolution:
    """Newest-first `main` commits. Red when none at or after the newest
    commit older than the grace period carries a ygg verdict."""
    due = next((i for i, c in enumerate(commits) if now - _date(c) >= GRACE), None)
    if due is None:
        return Resolution("noop", "", "no main commit is older than the grace period")
    for commit in commits[: due + 1]:
        seen = contexts(commit["sha"])
        if YGG_CONTEXT in seen:
            return Resolution("noop", commit["sha"], "ygg verdict present")
        if FALLBACK_CONTEXT in seen:
            return Resolution("noop", commit["sha"], "fallback already ran")
    sha = commits[due]["sha"]
    hours = int(GRACE.total_seconds() // 3600)
    return Resolution("fallback", sha, f"no ygg verdict within {hours} h; GitHub-hosted fallback run")


def _date(commit: dict[str, Any]) -> datetime:
    return datetime.fromisoformat(commit["commit"]["committer"]["date"].replace("Z", "+00:00"))


def _gh(path: str) -> Any:
    return json.loads(subprocess.run(["gh", "api", path], capture_output=True, text=True, check=True,
                                     timeout=60).stdout)


def resolve(event: str, inputs: dict[str, str], github_sha: str, repo: str, *,
            api: Callable[[str], Any] = _gh, now: datetime | None = None) -> Resolution:
    if event == "workflow_dispatch" and inputs.get("verdict"):
        resolution = validate_verdict(inputs)
        compare = api(f"repos/{repo}/compare/{resolution.sha}...main")
        if compare.get("status") not in {"identical", "ahead"}:
            raise VerdictRefused("verdict SHA is not on main")
        return resolution
    if event == "workflow_dispatch":
        return Resolution("fallback", github_sha, "manual GitHub-hosted heavy run")
    if event != "schedule":
        raise VerdictRefused(f"unsupported event {event}")
    commits = api(f"repos/{repo}/commits?sha=main&per_page=50")

    def contexts(sha: str) -> set[str]:
        return {row["context"] for row in api(f"repos/{repo}/commits/{sha}/statuses?per_page=100")}

    return watchdog(commits, contexts, now or datetime.now(timezone.utc))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event", required=True)
    parser.add_argument("--inputs", default="{}", help="workflow_dispatch inputs as JSON")
    parser.add_argument("--github-sha", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--github-output", required=True)
    args = parser.parse_args()
    inputs = {k: str(v) for k, v in (json.loads(args.inputs or "{}") or {}).items()}
    try:
        resolution = resolve(args.event, inputs, args.github_sha, args.repo)
    except VerdictRefused as exc:
        # A forged or malformed verdict is red, never silently ignored.
        sha = inputs.get("sha", "")
        if re.fullmatch(r"[0-9a-f]{40}", sha) is None:
            sha = args.github_sha
        resolution = Resolution("refused", sha, f"verdict refused: {exc}")
    with open(args.github_output, "a", encoding="utf-8") as output:
        for key, value in resolution.outputs().items():
            output.write(f"{key}={value.replace(chr(10), ' ')}\n")
    print(json.dumps(resolution.outputs(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
