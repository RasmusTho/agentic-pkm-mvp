from __future__ import annotations

import pytest

from app.dispatcher.verification_consumer import _checks_rejection
from tests.dispatcher.verification_helpers import HEAD


def _check(
    *,
    check_id: int,
    conclusion: str,
    app_slug: str | None = "github-actions",
    suite_id: int | None = 100,
    workflow_path: str | None = ".github/workflows/ci.yml",
    workflow_suite_id: int | None = None,
    workflow_event: str = "pull_request",
    workflow_head_sha: str = HEAD,
) -> dict[str, object]:
    check: dict[str, object] = {
        "id": check_id,
        "name": "Unit tests (not pg)",
        "status": "completed",
        "conclusion": conclusion,
    }
    if app_slug is not None:
        check["app"] = {"slug": app_slug}
    if suite_id is not None:
        check["check_suite"] = {"id": suite_id}
    if workflow_path is not None:
        check["workflow_run"] = {
            "id": 1000 + check_id,
            "path": workflow_path,
            "event": workflow_event,
            "head_sha": workflow_head_sha,
            "check_suite_id": (
                suite_id if workflow_suite_id is None else workflow_suite_id
            ),
        }
    return check


def test_required_check_rejects_same_name_success_from_untrusted_app() -> None:
    checks = [
        _check(check_id=10, conclusion="failure"),
        _check(check_id=11, conclusion="success", app_slug="untrusted-app"),
    ]

    assert _checks_rejection(checks, expected_head_sha=HEAD) == "checks_not_green"


def test_required_check_accepts_latest_github_actions_rerun() -> None:
    checks = [
        _check(check_id=10, conclusion="failure"),
        _check(check_id=11, conclusion="success"),
    ]

    assert _checks_rejection(checks, expected_head_sha=HEAD) is None


def test_required_check_rejects_missing_producer_identity() -> None:
    checks = [_check(check_id=11, conclusion="success", app_slug=None)]

    assert _checks_rejection(checks, expected_head_sha=HEAD) == "missing_checks"


def test_required_check_rejects_same_app_success_from_foreign_workflow_suite() -> None:
    checks = [
        _check(check_id=20, conclusion="failure", suite_id=100),
        _check(
            check_id=21,
            conclusion="success",
            suite_id=999,
            workflow_path=".github/workflows/ci-smoke.yaml",
        ),
    ]

    assert _checks_rejection(checks, expected_head_sha=HEAD) == "checks_not_green"


def test_required_check_accepts_latest_authoritative_workflow_rerun() -> None:
    checks = [
        _check(check_id=20, conclusion="failure", suite_id=100),
        _check(check_id=21, conclusion="success", suite_id=101),
    ]

    assert _checks_rejection(checks, expected_head_sha=HEAD) is None


@pytest.mark.parametrize(
    "updates",
    [
        {"workflow_path": None},
        {"workflow_path": ".github/workflows/ci-smoke.yaml"},
        {"workflow_event": "workflow_dispatch"},
        {"workflow_head_sha": "f" * 40},
        {"workflow_suite_id": 999},
        {"suite_id": None},
    ],
)
def test_required_check_rejects_incomplete_workflow_suite_identity(
    updates: dict[str, object],
) -> None:
    check = _check(check_id=30, conclusion="success", **updates)  # type: ignore[arg-type]

    assert _checks_rejection([check], expected_head_sha=HEAD) == "missing_checks"
