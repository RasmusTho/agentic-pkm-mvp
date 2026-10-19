"""Check that the post-merge dev controller is alive and making progress.

The private controller publishes two credential-free GitHub commit-status
signals: a frequently refreshed heartbeat on the current ``main`` commit and
a dev verdict on each admitted build.  This scheduled workflow only reads
those signals and the successful image-build runs; it never receives channel
or deployment credentials.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Callable

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

REPOSITORY = "RasmusTho/agentic-pkm-mvp"
BUILD_WORKFLOW = ".github/workflows/app-image-build.yml"
HEARTBEAT_CONTEXT = "post-merge-dev-test/heartbeat"
VERDICT_CONTEXT = "post-merge-dev-test/verdict"
GRACE = timedelta(hours=6)
HEARTBEAT_GRACE = timedelta(hours=2)
MAX_HISTORY_PAGES = 20
MAX_HEARTBEAT_COMMITS = 100


class LivenessRefused(ValueError):
    """Raised when GitHub evidence cannot be trusted as a liveness signal."""


@dataclass(frozen=True)
class AdmittedBuild:
    sha: str
    completed_at: datetime
    run_id: int
    created_at: datetime | None = None


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
    # Use the producer observation, never the time a delayed/replayed Actions
    # request finally writes the status. This protocol is new in #6222.
    description = status.get("description", "")
    if not isinstance(description, str) or not description.startswith("observed_at="):
        raise LivenessRefused("signal_observation_missing")
    return _timestamp(description.split(";", 1)[0].removeprefix("observed_at="))


def _validate_sha(value: Any) -> str:
    if not isinstance(value, str) or len(value) != 40 or any(char not in "0123456789abcdef" for char in value):
        raise LivenessRefused("sha_invalid")
    return value


def _admitted_builds(repo: str, *, api: Callable[[str], Any]) -> list[AdmittedBuild]:
    candidates: dict[str, AdmittedBuild] = {}
    for page in range(1, MAX_HISTORY_PAGES + 1):
        payload = api(
            f"repos/{repo}/actions/workflows/app-image-build.yml/runs"
            f"?branch=main&event=push&status=completed&per_page=100&page={page}"
        )
        if not isinstance(payload, dict) or not isinstance(payload.get("workflow_runs"), list):
            raise LivenessRefused("build_runs_unreadable")
        runs = payload["workflow_runs"]
        for run in runs:
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
                created_at = _timestamp(run.get("created_at")) if run.get("created_at") else completed_at
                run_id = int(run["id"])
                if run_id < 1:
                    raise ValueError()
            except (KeyError, TypeError, ValueError, LivenessRefused):
                continue
            candidate = AdmittedBuild(sha, completed_at, run_id, created_at)
            previous = candidates.get(sha)
            if previous is None or (candidate.created_at or candidate.completed_at, candidate.run_id) > (previous.created_at or previous.completed_at, previous.run_id):
                candidates[sha] = candidate
        if len(runs) < 100:
            break
    else:
        raise LivenessRefused("build_runs_incomplete")
    # GitHub's workflow-run listing is ordered by creation. A rerun may complete
    # later than a newer run, so creation time selects the admitted SHA while
    # retaining every distinct build for outstanding-verdict evaluation.
    return sorted(
        candidates.values(),
        key=lambda candidate: (candidate.created_at or candidate.completed_at, candidate.run_id),
        reverse=True,
    )


def latest_admitted_build(repo: str, *, api: Callable[[str], Any]) -> AdmittedBuild | None:
    builds = _admitted_builds(repo, api=api)
    return builds[0] if builds else None


def _startup_failure(status: Any) -> bool:
    return (isinstance(status, dict) and isinstance(status.get('description'), str)
            and status['description'].endswith(';startup=self_check_failed'))


def _latest_status(statuses: Any, context: str, *, allow_rotated_context: bool = False) -> dict[str, Any] | None:
    if not isinstance(statuses, list):
        raise LivenessRefused("statuses_unreadable")
    matching = [
        status for status in statuses
        if (isinstance(status, dict) and isinstance(status.get("context"), str)
                and (status.get("context") == context
                     or (allow_rotated_context and status["context"].startswith(context + "/"))))
    ]
    if not matching:
        return None
    if context != HEARTBEAT_CONTEXT:
        return max(matching, key=_status_timestamp)
    observations: dict[int, tuple[datetime, str, str]] = {}
    for status in matching:
        sequence, observed = _heartbeat_order(status)
        if sequence:
            evidence = (observed, status['state'], status['description'])
            if sequence in observations and observations[sequence] != evidence:
                raise LivenessRefused("heartbeat_sequence_conflict")
            observations[sequence] = evidence
    ordered_times = [observations[sequence][0] for sequence in sorted(observations)]
    if ordered_times != sorted(ordered_times):
        raise LivenessRefused("heartbeat_clock_order_refused")
    # Startup diagnostics cannot import or mutate the checkpoint producer.
    # Preserve the sequenced activity order, then let a newer failed-startup
    # observation override it. A later genuine activity observation recovers;
    # a queued/replayed older diagnostic cannot override current activity.
    startup = [status for status in matching if _startup_failure(status)]
    activity = [status for status in matching if not _startup_failure(status)]
    latest = max(activity, key=_heartbeat_order) if activity else None
    failed = max(startup, key=_status_timestamp) if startup else None
    if failed is not None and (latest is None or _status_timestamp(failed) >= _status_timestamp(latest)):
        return failed
    return latest


def _heartbeat_order(status: dict[str, Any]) -> tuple[int, datetime]:
    description = status.get("description", "")
    match = re.fullmatch(
        r"observed_at=([^;]+)(?:;seq=([1-9][0-9]{0,17}))?(?:;paused_issue=([1-9][0-9]{0,9});until=([^;]+)|;startup=(self_check_failed))?",
        description if isinstance(description, str) else "",
    )
    if (match is None or status.get("state") not in {"success", "failure"}
            or (status['state'] == 'failure') != bool(match[3] or match[5])
            or (match[3] and not match[2]) or (match[5] and match[2])):
        raise LivenessRefused("heartbeat_observation_refused")
    # Shipped legacy heartbeats are normal only. Sequenced producer continuity
    # outranks those observations even when its adoption followed a clock reset.
    return int(match[2] or 0), _timestamp(match[1])


def _heartbeat_pause(status: dict[str, Any] | None) -> tuple[int, datetime] | None:
    if status is None or status.get("state") != "failure":
        return None
    match = re.fullmatch(
        r"observed_at=([^;]+);seq=[1-9][0-9]{0,17};paused_issue=([1-9][0-9]{0,9});until=([^;]+)",
        status.get("description", ""),
    )
    if match is None:
        return None
    expires = _timestamp(match[3])
    if expires <= _status_timestamp(status):
        raise LivenessRefused("pause_expiry_refused")
    return int(match[2]), expires


def evaluate(
    build: AdmittedBuild | None,
    *,
    heartbeat_statuses: Any,
    verdict_statuses: Any,
    now: datetime,
) -> LivenessResult:
    """Evaluate freshness without treating the dev result as a merge gate."""
    current = now.astimezone(timezone.utc)
    heartbeat = _latest_status(heartbeat_statuses, HEARTBEAT_CONTEXT, allow_rotated_context=True)
    # A diagnostic cannot erase the durable sequenced pause. Even a later
    # verdict must remain red while that pause is active.
    activity = _latest_status([status for status in heartbeat_statuses if not _startup_failure(status)],
                              HEARTBEAT_CONTEXT, allow_rotated_context=True)
    pause = _heartbeat_pause(activity)
    if heartbeat is not None and _status_timestamp(heartbeat) > current:
        return LivenessResult(False, "heartbeat_future", "controller heartbeat observation is in the future")
    if pause is not None and activity is not None and _status_timestamp(activity) <= current < pause[1]:
        if _startup_failure(heartbeat):
            return LivenessResult(False, 'startup_self_check_failed', 'controller pinned tooling startup self-check failed')
        return LivenessResult(False, "paused", f"paused (#{pause[0]}, until {pause[1].isoformat()})")
    verdict = _latest_status(verdict_statuses, VERDICT_CONTEXT)
    verdict_at = _status_timestamp(verdict) if verdict is not None else None
    terminal_verdict = (build is not None and verdict is not None
                        and verdict.get("state") in {"success", "failure"}
                        and verdict_at is not None and verdict_at >= build.completed_at
                        and verdict_at <= current)
    if (heartbeat is not None and heartbeat.get('state') == 'failure'
            and heartbeat.get('description', '').endswith(';startup=self_check_failed')
            and _status_timestamp(heartbeat) <= current
            and (not terminal_verdict or _status_timestamp(heartbeat) > verdict_at)):
        return LivenessResult(False, 'startup_self_check_failed', 'controller pinned tooling startup self-check failed')
    if (terminal_verdict
            and current - verdict_at <= HEARTBEAT_GRACE):
        # A fresh terminal verdict is itself proof that the controller was
        # alive. This also lets a fresh verdict recover a stale heartbeat
        # signal while the next heartbeat update is in flight.
        return LivenessResult(True, "fresh_dev_verdict", f"dev verdict is fresh for {build.sha[:12]}")

    if heartbeat is None or (heartbeat.get("state") != "success" and pause is None):
        return LivenessResult(False, "heartbeat_missing", "post-merge dev controller heartbeat is missing")
    heartbeat_age = current - _status_timestamp(heartbeat)
    if heartbeat_age < timedelta(0) or heartbeat_age > HEARTBEAT_GRACE:
        hours = int(HEARTBEAT_GRACE.total_seconds() // 3600)
        return LivenessResult(False, "heartbeat_stale", f"controller heartbeat is older than {hours} h")

    if build is None:
        return LivenessResult(True, "no_admitted_build", "no successful admitted main build is available")

    if terminal_verdict:
        # A prior terminal verdict remains valid once heartbeat freshness is
        # established above, even when the verdict itself is older than the
        # heartbeat grace window.
        return LivenessResult(True, "dev_verdict_recorded", f"dev verdict is recorded for {build.sha[:12]}")

    if current - build.completed_at > GRACE:
        hours = int(GRACE.total_seconds() // 3600)
        return LivenessResult(False, "missing_dev_verdict", f"no dev verdict for {build.sha[:12]} within {hours} h")
    return LivenessResult(True, "within_grace", f"dev verdict for {build.sha[:12]} is within the grace period")


def _github(path: str) -> Any:
    result = subprocess.run(["gh", "api", path], capture_output=True, text=True, check=True, timeout=60)
    return json.loads(result.stdout)


def _status_history(repo: str, sha: str, context: str, *, api: Callable[[str], Any]) -> list[Any]:
    """Read status history until the requested context is found or exhausted."""
    collected: list[Any] = []
    previous_created: datetime | None = None
    for page in range(1, MAX_HISTORY_PAGES + 1):
        statuses = api(f"repos/{repo}/commits/{sha}/statuses?per_page=100&page={page}")
        if not isinstance(statuses, list):
            raise LivenessRefused("statuses_unreadable")
        collected.extend(statuses)
        matching = [
            status for status in statuses
            if isinstance(status, dict) and isinstance(status.get("context"), str)
            and (status["context"] == context or
                 (context == HEARTBEAT_CONTEXT and status["context"].startswith(context + "/")))
        ]
        if len(statuses) < 100 or (matching and context != HEARTBEAT_CONTEXT):
            return collected
        if context == HEARTBEAT_CONTEXT:
            # GitHub lists statuses in reverse creation order. A queued old
            # heartbeat may be written after a pause, so a match alone cannot
            # terminate history. Stop only once older writes cannot contain a
            # later producer observation. The trusted producer persists a
            # nondecreasing clock with its sequence; GitHub creation precision
            # is whole seconds, so equality cannot prove completeness. Legacy
            # normal observations cannot prove the sequenced migration floor.
            created = [_timestamp(status.get("created_at")) for status in statuses
                       if isinstance(status, dict)]
            if (len(created) != len(statuses) or created != sorted(created, reverse=True)
                    or (previous_created is not None and created[0] > previous_created)):
                raise LivenessRefused("statuses_creation_order_refused")
            previous_created = created[-1]
            latest = _latest_status(collected, context, allow_rotated_context=True)
            if (latest is not None and _heartbeat_order(latest)[0] > 0
                    and created[-1] < _status_timestamp(latest).replace(microsecond=0)):
                return collected
    raise LivenessRefused("statuses_incomplete")


def _main_heartbeat_history(repo: str, sha: str, *, api: Callable[[str], Any]) -> list[Any]:
    # A stopped controller cannot copy its pause onto a later main SHA. Follow
    # the actual first-parent main lineage, including commits without builds,
    # until the nearest actual normal/pause activity. Startup diagnostics
    # cannot retire ancestor activity: retain them while finding the causal
    # signal. A later normal tick supersedes the earlier pause; transport or
    # history ambiguity must never produce green.
    collected: list[Any] = []
    seen: set[str] = set()
    for _ in range(MAX_HEARTBEAT_COMMITS):
        if sha in seen:
            raise LivenessRefused("heartbeat_ancestry_refused")
        seen.add(sha)
        statuses = _status_history(repo, sha, HEARTBEAT_CONTEXT, api=api)
        # Validate diagnostics too, before following untrusted ancestry. A
        # diagnostic-only commit changes discovery, never signal admission.
        _latest_status(statuses, HEARTBEAT_CONTEXT, allow_rotated_context=True)
        collected.extend(statuses)
        activity = [status for status in statuses if not _startup_failure(status)]
        if _latest_status(activity, HEARTBEAT_CONTEXT, allow_rotated_context=True) is not None:
            return collected
        commit = api(f"repos/{repo}/git/commits/{sha}")
        if (not isinstance(commit, dict) or commit.get("sha") != sha
                or not isinstance(commit.get("parents"), list)
                or any(not isinstance(parent, dict) for parent in commit["parents"])):
            raise LivenessRefused("heartbeat_ancestry_refused")
        parents = [_validate_sha(parent.get("sha")) for parent in commit["parents"]]
        if not parents:
            return collected
        sha = parents[0]
    raise LivenessRefused("heartbeat_ancestry_incomplete")


def check(repo: str, github_sha: str, *, api: Callable[[str], Any] = _github,
          now: datetime | None = None) -> LivenessResult:
    _validate_sha(github_sha)
    current = now or datetime.now(timezone.utc)
    builds = _admitted_builds(repo, api=api)
    build = builds[0] if builds else None
    heartbeat = _main_heartbeat_history(repo, github_sha, api=api)
    progress_build = build
    progress_verdict: list[Any] = []
    outstanding: list[AdmittedBuild] = []
    for candidate in builds:
        verdict = _status_history(repo, candidate.sha, VERDICT_CONTEXT, api=api)
        if candidate is build:
            progress_verdict = verdict
        recorded = _latest_status(verdict, VERDICT_CONTEXT)
        if recorded is not None and recorded.get("state") in {"success", "failure"}:
            recorded_at = _status_timestamp(recorded)
            if candidate.completed_at <= recorded_at <= current:
                # Creation-ordered build identity is the progress watermark.
                # A late verdict for an older build cannot retire newer work;
                # a newer terminal build does retire skipped earlier history.
                progress_build = candidate
                progress_verdict = verdict
                break
        outstanding.append(candidate)

    if outstanding:
        oldest_outstanding = min(outstanding, key=lambda candidate: candidate.completed_at)
        if current - oldest_outstanding.completed_at > GRACE:
            return evaluate(oldest_outstanding, heartbeat_statuses=heartbeat,
                            verdict_statuses=[], now=current)

    # Once newer outstanding work is within grace, the qualified progress
    # watermark also proves controller activity. Its freshness remains useful
    # when a newer build arrives before the next heartbeat reaches main.
    return evaluate(progress_build, heartbeat_statuses=heartbeat,
                    verdict_statuses=progress_verdict, now=current)


def record_signal(kind: str, payload: str, *, repo: str, event: str, ref: str,
                  actor: str, triggering_actor: str, run_url: str,
                  api: Callable[[str], Any] = _github,
                  now: datetime | None = None) -> None:
    """The only liveness writer: narrow owner-originated, main-bound evidence.

    The controller's owner-provisioned Actions-write client is trusted to report
    DEV terminality; it cannot select a status context or borrow heavy-test
    authority. Actions independently re-admits the public build proof.
    """
    from scripts.postmerge_dev_test import LIVENESS_PROTOCOL, load_candidate, validate_pause, validate_observation

    owner = REPOSITORY.split("/", 1)[0]
    if (repo != REPOSITORY or event != "workflow_dispatch" or ref != "refs/heads/main"
            or actor != owner or triggering_actor != owner
            or kind not in {"heartbeat", "verdict"}
            or re.fullmatch(rf"https://github.com/{re.escape(repo)}/actions/runs/[1-9][0-9]*", run_url) is None
            or len(payload) > 2048):
        raise LivenessRefused("signal_producer_refused")
    signal = json.loads(payload)
    fields = {"protocol", "sha", "observed_at"}
    if kind == "verdict":
        fields |= {"candidate", "result", "operation_id"}
    elif isinstance(signal, dict):
        fields |= set(signal) & {"pause", "sequence"}
    if kind == 'heartbeat' and isinstance(signal, dict) and 'startup' in signal:
        fields |= {'startup'}
        if signal['startup'] != 'failed' or set(signal) & {'pause', 'sequence'}:
            raise LivenessRefused('signal_startup_refused')
    if not isinstance(signal, dict) or set(signal) != fields or signal["protocol"] != LIVENESS_PROTOCOL:
        raise LivenessRefused("signal_protocol_refused")
    sha = _validate_sha(signal["sha"])
    observed = _timestamp(signal["observed_at"])
    current = now or datetime.now(timezone.utc)
    if not timedelta(0) <= current - observed <= HEARTBEAT_GRACE:
        raise LivenessRefused("signal_observation_stale_or_future")
    compare = api(f"repos/{repo}/compare/{sha}...main")
    if not isinstance(compare, dict) or compare.get("status") not in {"identical", "ahead"}:
        raise LivenessRefused("signal_sha_not_on_main")
    description = "observed_at=" + observed.isoformat()
    state = "success"
    if kind == "heartbeat":
        context = f"{HEARTBEAT_CONTEXT}/{observed:%Y%m%d%H}"
        if "sequence" in signal:
            validate_observation({"sequence": signal["sequence"], "observed_at": signal["observed_at"]})
            description += f";seq={signal['sequence']}"
        if "pause" in signal:
            if "sequence" not in signal:
                raise LivenessRefused("pause_sequence_required")
            pause = validate_pause(signal["pause"])
            if not _timestamp(pause["engaged_at"]) <= observed < _timestamp(pause["expires_at"]):
                raise LivenessRefused("pause_observation_refused")
            state = "failure"
            description += f";paused_issue={pause['issue']};until={pause['expires_at']}"
        if signal.get('startup') == 'failed':
            state = 'failure'
            description += ';startup=self_check_failed'
    else:
        evidence = signal["candidate"]
        if (not isinstance(evidence, dict) or type(evidence.get("run_id")) is not int
                or evidence["run_id"] < 1 or signal["result"] not in {"passed", "failed"}):
            raise LivenessRefused("signal_candidate_refused")
        candidate = load_candidate(evidence["run_id"])
        if (asdict(candidate) != evidence or candidate.sha != sha
                or signal["operation_id"] != candidate.operation_id("dev")):
            raise LivenessRefused("signal_candidate_refused")
        context = VERDICT_CONTEXT
        state = "success" if signal["result"] == "passed" else "failure"
        description += f";run={candidate.run_id};attempt={candidate.run_attempt}"
    subprocess.run(["gh", "api", f"repos/{repo}/statuses/{sha}", "-f", f"state={state}",
                    "-f", f"context={context}", "-f", f"description={description}",
                    "-f", f"target_url={run_url}"], capture_output=True, text=True, check=True, timeout=60)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=REPOSITORY)
    parser.add_argument("--github-sha", required=True)
    parser.add_argument("--record-signal", action="store_true")
    parser.add_argument("--kind", default="")
    parser.add_argument("--payload", default="{}")
    args = parser.parse_args(argv)
    try:
        if args.record_signal:
            record_signal(args.kind, args.payload, repo=args.repo,
                          event=os.environ.get("GITHUB_EVENT_NAME", ""),
                          ref=os.environ.get("GITHUB_REF", ""), actor=os.environ.get("GITHUB_ACTOR", ""),
                          triggering_actor=os.environ.get("GITHUB_TRIGGERING_ACTOR", ""),
                          run_url=os.environ.get("RUN_URL", ""))
            return 0
        result = check(args.repo, _validate_sha(args.github_sha))
    except Exception as error:
        result = LivenessResult(False, "evidence_refused", str(error))
    print(json.dumps({"ok": result.ok, "reason": result.reason, "description": result.description}, sort_keys=True))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
