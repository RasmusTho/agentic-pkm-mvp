from __future__ import annotations

import io
import json
import zipfile

import pytest

from app.dispatcher.verification_consumer import GhCliVerificationSource
from tests.dispatcher.test_verification_consumer import artifact_request
from tests.dispatcher.verification_helpers import HEAD, REPO


def _source(
    request_payload: dict[str, object],
    *,
    authenticated_source_run_id: int = 99,
    authenticated_repository: str = REPO,
    authenticated_run_updates: dict[str, object] | None = None,
) -> tuple[GhCliVerificationSource, list[str]]:
    archive_bytes = io.BytesIO()
    with zipfile.ZipFile(archive_bytes, "w") as archive:
        archive.writestr("verification-dispatch/request.json", json.dumps(request_payload))

    class Result:
        returncode = 0

        def __init__(self, stdout: str | bytes) -> None:
            self.stdout = stdout

    endpoints: list[str] = []

    def runner(command: list[str], **_kwargs: object) -> Result:
        endpoint = command[-1]
        endpoints.append(endpoint)
        if endpoint.endswith("actions/artifacts?per_page=100"):
            return Result(
                json.dumps(
                    {
                        "artifacts": [
                            {
                                "id": 7,
                                "name": f"verification-dispatch-3603-{HEAD}",
                                "size_in_bytes": len(archive_bytes.getvalue()),
                                "expired": False,
                                "workflow_run": {
                                    "id": 123,
                                    "repository_id": 456,
                                    "head_repository_id": 456,
                                },
                            }
                        ]
                    }
                )
            )
        if endpoint.endswith("artifacts/7/zip"):
            return Result(archive_bytes.getvalue())
        if "/actions/runs/" in endpoint:
            source_run = {
                "id": authenticated_source_run_id,
                "run_attempt": 1,
                "name": "CI",
                "event": "pull_request",
                "status": "completed",
                "conclusion": "success",
                "head_sha": HEAD,
                "repository": {
                    "id": 456,
                    "full_name": authenticated_repository,
                },
                "head_repository": {
                    "id": 456,
                    "full_name": authenticated_repository,
                },
            }
            source_run.update(authenticated_run_updates or {})
            return Result(
                json.dumps(source_run)
            )
        raise AssertionError(f"unexpected GitHub read: {endpoint}")

    return GhCliVerificationSource(runner=runner), endpoints


@pytest.mark.parametrize(
    ("source_updates", "run_updates", "authenticated_repository"),
    [
        ({"run_id": 999}, {}, REPO),
        ({"name": "Untrusted CI"}, {}, REPO),
        ({"run_attempt": 77}, {}, REPO),
        ({"head_sha": "b" * 40}, {}, REPO),
        ({}, {"event": "push"}, REPO),
        ({}, {"status": "in_progress"}, REPO),
        ({}, {"conclusion": "failure"}, REPO),
        ({}, {}, "attacker/other-repo"),
    ],
)
def test_artifact_source_workflow_run_matches_authenticated_metadata(
    source_updates: dict[str, object],
    run_updates: dict[str, object],
    authenticated_repository: str,
) -> None:
    payload = artifact_request()
    source_workflow = dict(payload["source_workflow"])
    source_workflow.update(source_updates)
    payload["source_workflow"] = source_workflow
    payload["live_truth"] = {
        **dict(payload["live_truth"]),
        "source_run_id": source_workflow["run_id"],
    }
    source, endpoints = _source(
        payload,
        authenticated_repository=authenticated_repository,
        authenticated_run_updates=run_updates,
    )

    with pytest.raises(ValueError, match="source workflow identity mismatch"):
        source.pending_requests(REPO)

    assert endpoints[-1] == (
        f"repos/{REPO}/actions/runs/{source_workflow['run_id']}"
    )


def test_artifact_source_workflow_matching_metadata_is_accepted() -> None:
    payload = artifact_request()
    source, endpoints = _source(payload)

    assert source.pending_requests(REPO) == [payload]
    assert endpoints == [
        f"repos/{REPO}/actions/artifacts?per_page=100",
        f"repos/{REPO}/actions/artifacts/7/zip",
        f"repos/{REPO}/actions/runs/99",
    ]
