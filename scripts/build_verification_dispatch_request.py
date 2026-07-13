#!/usr/bin/env python3
"""Build an artifact-only request for current-head PR verification."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Sequence


CONTRACT_VERSION = "verification_dispatch_request.v1"
STAGE = "verification"
SOURCE_WORKFLOW = "CI"
EVIDENCE_WORKFLOW = "PR Evidence Pack"


def _as_dict(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _load_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return _as_dict(value)


def _nested_str(data: dict[str, object], *keys: str) -> str:
    current: object = data
    for key in keys:
        if not isinstance(current, dict):
            return ""
        current = current.get(key)
    return current if isinstance(current, str) else ""


def _idempotency_key(
    *, repository: str, pr_number: int, head_sha: str, stage: str
) -> str:
    identity = {
        "contract_version": CONTRACT_VERSION,
        "head_sha": head_sha,
        "pr_number": pr_number,
        "repository": repository,
        "stage": stage,
    }
    encoded = json.dumps(
        identity, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def resolve_pr_number(
    *, event: dict[str, object], candidates: Sequence[object]
) -> int | None:
    """Resolve one PR, falling back to unique open current-head candidates."""
    run = _as_dict(event.get("workflow_run"))
    if run.get("event") != "pull_request":
        return None
    associations = run.get("pull_requests")
    if not isinstance(associations, list):
        return None

    if associations:
        if len(associations) != 1 or not isinstance(associations[0], dict):
            return None
        associated_number = associations[0].get("number")
        return associated_number if isinstance(associated_number, int) else None

    run_head_sha = run.get("head_sha")
    if not isinstance(run_head_sha, str) or not run_head_sha:
        return None
    matches: dict[int, dict[str, object]] = {}
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        number = candidate.get("number")
        if (
            isinstance(number, int)
            and candidate.get("state") == "open"
            and _nested_str(candidate, "head", "sha") == run_head_sha
        ):
            matches[number] = candidate
    if len(matches) != 1:
        return None
    return next(iter(matches))


def build_request(
    *,
    event: dict[str, object],
    pr: dict[str, object],
    issue: dict[str, object] | None = None,
) -> dict[str, object] | None:
    """Return a dispatch request only for successful CI on the current PR head."""
    run = _as_dict(event.get("workflow_run"))
    if (
        run.get("name") != SOURCE_WORKFLOW
        or run.get("event") != "pull_request"
        or run.get("conclusion") != "success"
    ):
        return None

    repository = _nested_str(event, "repository", "full_name")
    pr_number = pr.get("number")
    run_id = run.get("id")
    run_attempt = run.get("run_attempt")
    run_head_sha = run.get("head_sha")
    current_head_sha = _nested_str(pr, "head", "sha")
    base_ref = _nested_str(pr, "base", "ref")
    head_ref = _nested_str(pr, "head", "ref")
    generated_at = run.get("updated_at")
    if not (
        repository
        and isinstance(pr_number, int)
        and isinstance(run_id, int)
        and isinstance(run_attempt, int)
        and isinstance(run_head_sha, str)
        and run_head_sha
        and run_head_sha == current_head_sha
        and base_ref
        and head_ref
        and isinstance(generated_at, str)
        and generated_at
    ):
        return None

    issue_data = issue or {}
    linked_issue = issue_data.get("number")
    if not isinstance(linked_issue, int):
        linked_issue = None

    return {
        "contract_version": CONTRACT_VERSION,
        "stage": STAGE,
        "repository": repository,
        "pr_number": pr_number,
        "linked_issue": linked_issue,
        "base_ref": base_ref,
        "head_ref": head_ref,
        "current_head_sha": current_head_sha,
        "source_workflow": {
            "name": SOURCE_WORKFLOW,
            "run_id": run_id,
            "run_attempt": run_attempt,
            "head_sha": run_head_sha,
        },
        "evidence_pack": {
            "contract": "pr_evidence_pack",
            "workflow_name": EVIDENCE_WORKFLOW,
            "artifact_name": f"pr-evidence-pack-{pr_number}",
            "repository": repository,
            "pr_number": pr_number,
            "head_sha": current_head_sha,
        },
        "live_truth": {
            "repository": repository,
            "pr_number": pr_number,
            "current_head_sha": current_head_sha,
            "source_run_id": run_id,
        },
        "generated_at": generated_at,
        "idempotency_key": _idempotency_key(
            repository=repository,
            pr_number=pr_number,
            head_sha=current_head_sha,
            stage=STAGE,
        ),
    }


def render_markdown(request: dict[str, object]) -> str:
    source = _as_dict(request.get("source_workflow"))
    evidence = _as_dict(request.get("evidence_pack"))
    lines = [
        "# Verification Dispatch Request",
        "",
        f"- Contract: `{request['contract_version']}`",
        f"- Repository: `{request['repository']}`",
        f"- PR: `#{request['pr_number']}`",
        f"- Head SHA: `{request['current_head_sha']}`",
        f"- Stage: `{request['stage']}`",
        f"- Source run: `{source.get('run_id', '')}`",
        f"- Evidence artifact: `{evidence.get('artifact_name', '')}`",
        f"- Idempotency key: `{request['idempotency_key']}`",
        f"- Generated at: `{request['generated_at']}`",
        "",
        "The consumer must re-fetch PR and workflow truth before acting.",
        "",
    ]
    return "\n".join(lines)


def _write_github_output(path: Path | None, *, emitted: bool) -> None:
    if path is None:
        return
    with path.open("a", encoding="utf-8") as output:
        output.write(f"emitted={'true' if emitted else 'false'}\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event-json", type=Path, required=True)
    parser.add_argument("--pr-json", type=Path, required=True)
    parser.add_argument("--issue-json", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-markdown", type=Path, required=True)
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args(argv)

    request = build_request(
        event=_load_json(args.event_json),
        pr=_load_json(args.pr_json),
        issue=_load_json(args.issue_json),
    )
    if request is None:
        _write_github_output(args.github_output, emitted=False)
        return 0

    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(request, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    args.output_markdown.write_text(render_markdown(request), encoding="utf-8")
    _write_github_output(args.github_output, emitted=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
