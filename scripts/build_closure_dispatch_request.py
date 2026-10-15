#!/usr/bin/env python3
"""Build a bounded, artifact-only request for post-merge closure recovery.

The output is an inert handoff for the separately governed VM102 consumer.  It
contains no GitHub mutation authority.  The event and recovery entry points
both call :func:`build_request`, so their idempotency identity cannot drift.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TypeGuard


CONTRACT_VERSION = "closure_dispatch_request.v1"
STAGE = "closure"
_SHA = re.compile(r"^[0-9a-f]{40}$")
_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def _positive_int(value: object) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _as_dict(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, Mapping) else {}


def _nested_str(value: object, *keys: str) -> str:
    current = value
    for key in keys:
        if not isinstance(current, Mapping):
            return ""
        current = current.get(key)
    return current if isinstance(current, str) else ""


def _merge_sha(pr: Mapping[str, object]) -> str:
    return (
        str(pr.get("merge_commit_sha"))
        if isinstance(pr.get("merge_commit_sha"), str)
        else _nested_str(pr, "merge_commit", "sha")
    )


def _pr_repository(pr: Mapping[str, object]) -> str:
    for candidate in (
        _nested_str(pr, "repository", "full_name"),
        _nested_str(pr, "repository", "name_with_owner"),
        _nested_str(pr, "base", "repo", "full_name"),
        _nested_str(pr, "base", "repository", "full_name"),
    ):
        if candidate:
            return candidate
    return ""


def idempotency_key(*, repository: str, pr_number: int, merge_sha: str) -> str:
    """Return the stable identity shared by event and recovery producers."""

    identity = {
        "contract_version": CONTRACT_VERSION,
        "merge_sha": merge_sha,
        "pr_number": pr_number,
        "repository": repository,
        "stage": STAGE,
    }
    encoded = json.dumps(identity, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _classification_link(
    classification: Mapping[str, object] | None,
    *,
    repository: str,
    pr_number: int,
    merge_sha: str,
) -> dict[str, object] | None:
    if not isinstance(classification, Mapping) or not classification:
        return None
    link = _as_dict(classification)
    linked_repository = link.get("repository")
    linked_pr = link.get("merged_pr_number", link.get("pr_number"))
    linked_sha = link.get("merged_pr_sha", link.get("merge_sha"))
    impact = link.get("impact_classification", link.get("classification"))
    if linked_repository != repository:
        return None
    if linked_pr != pr_number:
        return None
    if linked_sha != merge_sha:
        return None
    # Keep only a bounded, content-addressable classification reference.  The
    # full classifier artifact remains available to a future consumer.
    digest = link.get("artifact_sha256")
    artifact = link.get("artifact_name")
    if artifact is not None and not isinstance(artifact, str):
        return None
    if digest is not None and (
        not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)
    ):
        return None
    if not (
        isinstance(impact, str) and bool(impact)
        or isinstance(artifact, str) and bool(artifact)
        or isinstance(digest, str) and bool(digest)
    ):
        return None
    result: dict[str, object] = {
        "repository": repository,
        "pr_number": pr_number,
        "merge_sha": merge_sha,
    }
    if isinstance(artifact, str):
        result["artifact_name"] = artifact
    if isinstance(digest, str):
        result["artifact_sha256"] = digest
    if isinstance(impact, str):
        result["impact_classification"] = impact
    return result


def build_request(
    *,
    event: Mapping[str, object] | None = None,
    pr: Mapping[str, object] | None = None,
    classification: Mapping[str, object] | None = None,
    source: str = "merged_event",
) -> dict[str, object] | None:
    """Build one request, or ``None`` when evidence is ineligible.

    ``event`` may be a pull-request webhook payload or a recovery snapshot.
    All identity fields are re-derived from the PR snapshot; untrusted event
    text cannot override them.
    """

    event_data = _as_dict(event)
    pr_data = _as_dict(pr)
    if not pr_data:
        pr_data = _as_dict(event_data.get("pull_request"))
    event_repository = _nested_str(event_data, "repository", "full_name")
    pr_repository = _pr_repository(pr_data)
    if event_repository and pr_repository and event_repository != pr_repository:
        return None
    repository = event_repository or pr_repository
    number = pr_data.get("number")
    merged = pr_data.get("merged")
    merge_sha = _merge_sha(pr_data)
    generated_at = (
        _nested_str(event_data, "pull_request", "merged_at")
        or (pr_data.get("merged_at") if isinstance(pr_data.get("merged_at"), str) else "")
        or (event_data.get("generated_at") if isinstance(event_data.get("generated_at"), str) else "")
    )
    if (
        not _REPOSITORY.fullmatch(repository)
        or not _positive_int(number)
        or not (
            merged is True
            or (merged is None and isinstance(pr_data.get("merged_at"), str) and bool(pr_data.get("merged_at")))
        )
        or not _SHA.fullmatch(merge_sha)
        or not generated_at
        or source not in {"merged_event", "bounded_recovery"}
    ):
        return None
    link = _classification_link(
        classification,
        repository=repository,
        pr_number=number,
        merge_sha=merge_sha,
    )
    if link is None:
        return None
    request: dict[str, object] = {
        "contract_version": CONTRACT_VERSION,
        "stage": STAGE,
        "repository": repository,
        "pr_number": number,
        "merge_sha": merge_sha,
        "classification": link,
        "source": source,
        "generated_at": generated_at,
        "idempotency_key": idempotency_key(
            repository=repository, pr_number=number, merge_sha=merge_sha
        ),
    }
    return request


def render_markdown(request: Mapping[str, object]) -> str:
    return "\n".join(
        [
            "# Closure Dispatch Request",
            "",
            f"- Contract: `{request['contract_version']}`",
            f"- Repository: `{request['repository']}`",
            f"- PR: `#{request['pr_number']}`",
            f"- Merge SHA: `{request['merge_sha']}`",
            f"- Stage: `{request['stage']}`",
            f"- Source: `{request['source']}`",
            f"- Idempotency key: `{request['idempotency_key']}`",
            "",
            "This is an artifact-only request. The consumer must re-fetch live authority before acting.",
            "",
        ]
    )


def _load(path: Path) -> dict[str, object]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return _as_dict(loaded)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event-json", type=Path, required=True)
    parser.add_argument("--pr-json", type=Path, required=True)
    parser.add_argument("--classification-json", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-markdown", type=Path, required=True)
    parser.add_argument("--source", choices=("merged_event", "bounded_recovery"), default="merged_event")
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args(argv)
    request = build_request(
        event=_load(args.event_json),
        pr=_load(args.pr_json),
        classification=_load(args.classification_json),
        source=args.source,
    )
    if request is None:
        if args.github_output:
            args.github_output.write_text("emitted=false\n", encoding="utf-8")
        return 0
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(request, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.output_markdown.write_text(render_markdown(request), encoding="utf-8")
    if args.github_output:
        args.github_output.write_text("emitted=true\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
