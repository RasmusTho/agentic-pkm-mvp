#!/usr/bin/env python3
"""Classify PR check-run state without polling or mutating GitHub."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

GREEN_CONCLUSIONS = frozenset({"success", "skipped", "neutral"})
RERUN_CANDIDATE_CONCLUSIONS = frozenset({
    "cancelled",
    "stale",
    "startup_failure",
    "timed_out",
})
DEFAULT_STALL_THRESHOLD_SECONDS = 30 * 60


class CiStallClassifierError(ValueError):
    """Raised when classifier input is malformed."""


@dataclass(frozen=True)
class CheckRun:
    name: str
    status: str
    conclusion: str | None
    started_at: str | None = None
    created_at: str | None = None
    completed_at: str | None = None
    id: int | str | None = None


@dataclass(frozen=True)
class CiStallClassification:
    classification: str
    recommended_next_action: str
    failure: bool
    stalled: bool
    pending: bool
    summary: str
    checks_considered: list[dict[str, Any]]
    pending_checks: list[dict[str, Any]]
    failed_checks: list[dict[str, Any]]
    missing_checks: list[str]
    threshold_seconds: int
    now: str


def classify_ci_state(
    payload: Any,
    *,
    now: datetime | str | None = None,
    stall_threshold_seconds: int = DEFAULT_STALL_THRESHOLD_SECONDS,
    expected_checks: Sequence[str] = (),
) -> CiStallClassification:
    """Classify check-runs into wait/stall/failure guidance.

    Input may be the raw REST check-runs response (`{"check_runs": [...]}`), an
    object with `checks`, or a bare list. Only the latest run per check name is
    classified, matching `scripts/await_pr_checks.sh`.
    """

    if stall_threshold_seconds <= 0:
        raise CiStallClassifierError("stall_threshold_seconds must be positive")
    current = _normalize_now(now)
    checks = _latest_by_name(_extract_checks(payload))
    missing = _missing_checks(checks, expected_checks)
    failed = [
        check for check in checks
        if check.status == "completed"
        and check.conclusion is not None
        and check.conclusion not in GREEN_CONCLUSIONS
    ]
    pending = [check for check in checks if check.status != "completed"]

    if failed:
        rerun_candidates = [
            check for check in failed
            if check.conclusion in RERUN_CANDIDATE_CONCLUSIONS
        ]
        if len(rerun_candidates) == len(failed):
            return _classification(
                "flaky_or_external_failure",
                "rerun_candidate",
                "latest failed check conclusion points to infrastructure/flaky behavior; rerun is advisory only",
                checks,
                pending,
                failed,
                missing,
                stall_threshold_seconds,
                current,
                failure=True,
                stalled=False,
            )
        return _classification(
            "actionable_failure",
            "repair_failure",
            "latest completed checks include actionable failures; do not wait or treat as stall",
            checks,
            pending,
            failed,
            missing,
            stall_threshold_seconds,
            current,
            failure=True,
            stalled=False,
        )

    if pending:
        stalled = [
            check for check in pending
            if _check_age_seconds(check, current) is None
            or _check_age_seconds(check, current) > stall_threshold_seconds
        ]
        if stalled:
            return _classification(
                "stalled",
                "handoff_as_ci_pending_or_rerun_candidate",
                "queued or in-progress checks exceeded the bounded wait threshold",
                checks,
                pending,
                failed,
                missing,
                stall_threshold_seconds,
                current,
                failure=False,
                stalled=True,
            )
        return _classification(
            "wait",
            "wait",
            "queued or in-progress checks are still within the bounded wait threshold",
            checks,
            pending,
            failed,
            missing,
            stall_threshold_seconds,
            current,
            failure=False,
            stalled=False,
        )

    if missing:
        return _classification(
            "missing_checks",
            "wait_for_check_attachment",
            "expected checks are not attached to the current head yet",
            checks,
            pending,
            failed,
            missing,
            stall_threshold_seconds,
            current,
            failure=False,
            stalled=False,
        )

    if not checks:
        return _classification(
            "missing_checks",
            "wait_for_check_attachment",
            "no check-runs are attached to the current head yet",
            checks,
            pending,
            failed,
            missing,
            stall_threshold_seconds,
            current,
            failure=False,
            stalled=False,
        )

    return _classification(
        "green",
        "continue_hot_path",
        "latest check-runs are terminal green",
        checks,
        pending,
        failed,
        missing,
        stall_threshold_seconds,
        current,
        failure=False,
        stalled=False,
    )


def _classification(
    classification: str,
    next_action: str,
    summary: str,
    checks: list[CheckRun],
    pending: list[CheckRun],
    failed: list[CheckRun],
    missing: list[str],
    threshold: int,
    now: datetime,
    *,
    failure: bool,
    stalled: bool,
) -> CiStallClassification:
    return CiStallClassification(
        classification=classification,
        recommended_next_action=next_action,
        failure=failure,
        stalled=stalled,
        pending=bool(pending),
        summary=summary,
        checks_considered=[asdict(check) for check in checks],
        pending_checks=[_check_summary(check, now) for check in pending],
        failed_checks=[_check_summary(check, now) for check in failed],
        missing_checks=list(missing),
        threshold_seconds=threshold,
        now=_format_utc(now),
    )


def _check_summary(check: CheckRun, now: datetime) -> dict[str, Any]:
    summary = asdict(check)
    summary["age_seconds"] = _check_age_seconds(check, now)
    return summary


def _extract_checks(payload: Any) -> list[CheckRun]:
    if isinstance(payload, Mapping):
        raw = payload.get("check_runs", payload.get("checks", []))
    else:
        raw = payload
    if not isinstance(raw, list):
        raise CiStallClassifierError("check-runs payload must contain a list")
    return [_normalize_check(item) for item in raw]


def _normalize_check(value: Any) -> CheckRun:
    if not isinstance(value, Mapping):
        raise CiStallClassifierError("checks must be objects")
    name = _required_string(value.get("name"), "check.name")
    status = _required_string(value.get("status", "completed"), "check.status").lower()
    conclusion = value.get("conclusion")
    if conclusion is None or conclusion == "":
        normalized_conclusion = None
    else:
        normalized_conclusion = _required_string(
            conclusion,
            "check.conclusion",
        ).lower()
    check_id = value.get("id")
    if isinstance(check_id, bool) or not isinstance(check_id, (int, str)):
        check_id = None
    return CheckRun(
        name=name,
        status=status,
        conclusion=normalized_conclusion,
        started_at=_optional_string(value.get("started_at", value.get("startedAt"))),
        created_at=_optional_string(value.get("created_at", value.get("createdAt"))),
        completed_at=_optional_string(value.get("completed_at", value.get("completedAt"))),
        id=check_id,
    )


def _latest_by_name(checks: list[CheckRun]) -> list[CheckRun]:
    latest: dict[str, CheckRun] = {}
    for check in checks:
        existing = latest.get(check.name)
        if existing is None or _check_rank(check) >= _check_rank(existing):
            latest[check.name] = check
    return list(latest.values())


def _check_rank(check: CheckRun) -> tuple[str, int]:
    return (
        check.started_at or check.created_at or "",
        _numeric_check_id(check.id),
    )


def _numeric_check_id(value: int | str | None) -> int:
    """Return the REST check-run id in its numeric ordering domain."""
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            pass
    return -1


def _missing_checks(checks: list[CheckRun], expected: Sequence[str]) -> list[str]:
    present = {check.name for check in checks}
    return [name for name in expected if name not in present]


def _check_age_seconds(check: CheckRun, now: datetime) -> int | None:
    started = _parse_time(check.started_at or check.created_at)
    if started is None:
        return None
    return max(0, int((now - started).total_seconds()))


def _normalize_now(value: datetime | str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc).replace(microsecond=0)
    if isinstance(value, datetime):
        current = value
    else:
        current = _parse_time(value)
        if current is None:
            raise CiStallClassifierError("now must be an ISO-8601 timestamp")
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).replace(microsecond=0)


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).replace(microsecond=0)


def _format_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _required_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CiStallClassifierError(f"{field} must be a non-empty string")
    return value.strip()


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    return _required_string(value, "timestamp")


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CiStallClassifierError(f"invalid JSON in {path}: {exc}") from exc


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check-runs-json",
        type=Path,
        required=True,
        help="Raw REST check-runs JSON, object with checks, or a JSON list.",
    )
    parser.add_argument("--now", default=None, help="ISO timestamp for deterministic age checks.")
    parser.add_argument(
        "--stall-threshold-seconds",
        type=int,
        default=DEFAULT_STALL_THRESHOLD_SECONDS,
    )
    parser.add_argument(
        "--expected-check",
        action="append",
        default=[],
        help="Expected check name. Repeat to detect missing attached checks.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = classify_ci_state(
            _load_json(args.check_runs_json),
            now=args.now,
            stall_threshold_seconds=args.stall_threshold_seconds,
            expected_checks=args.expected_check,
        )
    except CiStallClassifierError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps({"ok": True, **asdict(result)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
