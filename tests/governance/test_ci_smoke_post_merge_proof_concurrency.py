"""Regression coverage for CI Smoke concurrency and metadata-event routing (#4812).

Pure pull-request title/body metadata edits do not alter the checked-out source
or merge inputs. Their CI Smoke jobs are skipped and Issue and PR Governance
validates the contract. A base-ref retarget is also an ``edited`` event, but it
changes a merge input and must keep the full CI Smoke jobs enabled. For the
remaining source/integration events, CI Smoke keeps event-class concurrency so
push runs and PR runs cannot cancel one another.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
CI_SMOKE = REPO_ROOT / ".github" / "workflows" / "ci-smoke.yaml"
EXPECTED_GROUP_EXPRESSION = (
    "ci-smoke-${{ github.event_name }}-"
    "${{ github.event.pull_request.number || github.ref }}-"
    "${{ github.event.action == 'edited' && "
    "github.event.changes.base.ref.from == null && 'metadata' || 'code' }}"
)


def _workflow_text() -> str:
    return CI_SMOKE.read_text(encoding="utf-8")


def _concurrency_block() -> str:
    workflow = _workflow_text()
    return workflow.split("\nconcurrency:\n", maxsplit=1)[1].split(
        "\npermissions:", maxsplit=1
    )[0]


def _workflow_group_expression() -> str:
    match = re.search(r"^  group: (.+)$", _concurrency_block(), flags=re.MULTILINE)
    assert match is not None, "CI Smoke must declare a workflow concurrency group"
    return match.group(1)


def _pull_request_event(
    *,
    action: str,
    number: int,
    merged: bool,
    ref: str,
    run_attempt: int = 1,
) -> dict[str, Any]:
    return {
        "event_name": "pull_request",
        "event": {
            "action": action,
            "number": number,
            "pull_request": {
                "number": number,
                "merged": merged,
            },
        },
        "ref": ref,
        "run_attempt": run_attempt,
    }


def _push_event(
    *, ref: str, run_attempt: int = 1, after: str = "a" * 40
) -> dict[str, Any]:
    return {
        "event_name": "push",
        "event": {"after": after},
        "ref": ref,
        "run_attempt": run_attempt,
    }


def _render_group(fixture: dict[str, Any]) -> str:
    """Evaluate the one accepted expression over a bounded event fixture."""

    assert _workflow_group_expression() == EXPECTED_GROUP_EXPRESSION
    payload = fixture["event"]
    pull_request = payload.get("pull_request", {})
    pull_request_number = pull_request.get("number")
    identity = pull_request_number or fixture["ref"]
    changes = payload.get("changes", {})
    base_ref_from = changes.get("base", {}).get("ref", {}).get("from")
    pure_metadata = payload.get("action") == "edited" and base_ref_from is None
    suffix = "metadata" if pure_metadata else "code"
    return f"ci-smoke-{fixture['event_name']}-{identity}-{suffix}"


def test_ci_smoke_skips_pure_metadata_but_runs_base_ref_edits() -> None:
    restored_body_edit = _pull_request_event(
        action="edited",
        number=4803,
        merged=True,
        ref="refs/heads/main",
    )
    workflow = _workflow_text()
    smoke_trigger = workflow.split("\non:\n", maxsplit=1)[1].split(
        "\n\nconcurrency:", maxsplit=1
    )[0]
    governance_trigger = (
        REPO_ROOT / ".github" / "workflows" / "issue-pr-governance.yml"
    ).read_text(encoding="utf-8").split("\non:\n", maxsplit=1)[1].split(
        "\n\npermissions:", maxsplit=1
    )[0]

    assert restored_body_edit["event"]["action"] == "edited"
    assert restored_body_edit["ref"] == "refs/heads/main"
    assert "types: [opened, synchronize, reopened, edited]" in smoke_trigger
    assert "types: [opened, edited, reopened, synchronize]" in governance_trigger

    smoke_job = workflow.split("  smoke:\n", maxsplit=1)[1].split(
        "  smoke-docker:\n", maxsplit=1
    )[0]
    assert "github.event.action != 'edited'" in smoke_job
    assert "github.event.changes.base.ref.from != null" in smoke_job

    pure_metadata = {"action": "edited", "changes": {}}
    base_ref_edit = {
        "action": "edited",
        "changes": {"base": {"ref": {"from": "main"}}},
    }
    def allows_ci(event: dict[str, Any]) -> bool:
        return (
            event["action"] != "edited"
            or event.get("changes", {}).get("base", {}).get("ref", {}).get("from")
            is not None
        )
    assert allows_ci(pure_metadata) is False
    assert allows_ci(base_ref_edit) is True


def test_metadata_edit_does_not_cancel_same_pr_code_run() -> None:
    source_run = _pull_request_event(
        action="synchronize",
        number=4812,
        merged=False,
        ref="refs/pull/4812/merge",
    )
    metadata_edit = _pull_request_event(
        action="edited",
        number=4812,
        merged=True,
        ref="refs/heads/main",
    )

    assert _render_group(source_run) == "ci-smoke-pull_request-4812-code"
    assert _render_group(metadata_edit) == "ci-smoke-pull_request-4812-metadata"
    assert _render_group(source_run) != _render_group(metadata_edit)


def test_main_pushes_retain_cancel_in_progress_group() -> None:
    first_push = _push_event(ref="refs/heads/main", after="c" * 40)
    later_push = _push_event(ref="refs/heads/main", after="d" * 40)

    assert _render_group(first_push) == "ci-smoke-push-refs/heads/main-code"
    assert _render_group(first_push) == _render_group(later_push)
    assert "cancel-in-progress: true" in _concurrency_block()


def test_same_pr_event_runs_share_only_their_pr_concurrency_group() -> None:
    same_pr_events = (
        _pull_request_event(
            action="opened",
            number=4812,
            merged=False,
            ref="refs/pull/4812/merge",
        ),
        _pull_request_event(
            action="synchronize",
            number=4812,
            merged=False,
            ref="refs/pull/4812/merge",
        ),
        _pull_request_event(
            action="reopened",
            number=4812,
            merged=False,
            ref="refs/pull/4812/merge",
        ),
    )
    another_pr = _pull_request_event(
        action="synchronize",
        number=4813,
        merged=False,
        ref="refs/pull/4813/merge",
    )
    main_push = _push_event(ref="refs/heads/main")

    assert {event["event"]["action"] for event in same_pr_events} == {
        "opened",
        "synchronize",
        "reopened",
    }
    assert {_render_group(event) for event in same_pr_events} == {
        "ci-smoke-pull_request-4812-code"
    }
    assert _render_group(another_pr) == "ci-smoke-pull_request-4813-code"
    assert _render_group(another_pr) != _render_group(same_pr_events[0])
    assert _render_group(main_push) != _render_group(same_pr_events[0])


def test_source_and_integration_events_keep_required_unit_job_enabled() -> None:
    synchronize = _pull_request_event(
        action="synchronize",
        number=4803,
        merged=False,
        ref="refs/pull/4803/merge",
    )
    workflow = _workflow_text()
    trigger_block = workflow.split("\non:\n", maxsplit=1)[1].split(
        "\nconcurrency:", maxsplit=1
    )[0]
    jobs = yaml.safe_load(workflow)["jobs"]
    required_unit_job = jobs["pr-unit-tests-not-pg"]

    assert "pull_request:" in trigger_block
    assert "types: [opened, synchronize, reopened, edited]" in trigger_block
    assert _render_group(synchronize) == "ci-smoke-pull_request-4803-code"
    assert required_unit_job["name"] == "Unit tests (not pg)"
    assert required_unit_job["if"] == (
        "github.event_name == 'pull_request' && (github.event.action != 'edited' "
        "|| github.event.changes.base.ref.from != null)"
    )


def test_push_tags_and_other_refs_keep_event_scoped_ref_namespace() -> None:
    tag_push = _push_event(ref="refs/tags/v5.5.0", after="e" * 40)
    another_tag_push = _push_event(ref="refs/tags/v5.5.1", after="f" * 40)
    other_ref_push = _push_event(ref="refs/heads/recovery", after="0" * 40)

    assert _render_group(tag_push) == "ci-smoke-push-refs/tags/v5.5.0-code"
    assert _render_group(another_tag_push) == "ci-smoke-push-refs/tags/v5.5.1-code"
    assert _render_group(tag_push) != _render_group(another_tag_push)
    assert _render_group(other_ref_push) == "ci-smoke-push-refs/heads/recovery-code"


def test_reruns_retain_the_original_event_identity() -> None:
    original_pr_run = _pull_request_event(
        action="synchronize",
        number=4803,
        merged=False,
        ref="refs/pull/4803/merge",
        run_attempt=1,
    )
    rerun_pr_attempt = _pull_request_event(
        action="synchronize",
        number=4803,
        merged=False,
        ref="refs/pull/4803/merge",
        run_attempt=2,
    )
    original_main_run = _push_event(ref="refs/heads/main", run_attempt=1)
    rerun_main_attempt = _push_event(ref="refs/heads/main", run_attempt=2)

    assert original_pr_run["run_attempt"] != rerun_pr_attempt["run_attempt"]
    assert _render_group(original_pr_run) == _render_group(rerun_pr_attempt)
    assert original_main_run["run_attempt"] != rerun_main_attempt["run_attempt"]
    assert _render_group(original_main_run) == _render_group(rerun_main_attempt)


def test_workflow_pins_the_minimal_event_identity_expression() -> None:
    assert _workflow_group_expression() == EXPECTED_GROUP_EXPRESSION
    assert "github.event.number" not in _workflow_group_expression()
    assert "cancel-in-progress: true" in _concurrency_block()
