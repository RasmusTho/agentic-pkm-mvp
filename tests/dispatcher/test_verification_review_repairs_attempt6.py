from __future__ import annotations

import io
import json
from pathlib import Path
import zipfile
import pytest

from app.dispatcher.cli import _compact_verification_run
from app.dispatcher.verification_consumer import (
    CodexExecLauncher,
    GhCliVerificationSource,
    VerificationConsumer,
    _checks_rejection,
    _trusted_evidence_urls,
    context_pack,
    sanitize_verification_closer_receipt as _sanitize_verification_closer_receipt,
)
from tests.dispatcher.test_verification_consumer import (
    Auth,
    DeliveredLauncher,
    FailingPostLaunchPrTruth,
    GREEN,
    Launcher,
    Truth,
    eligible_pr,
    merged_pr,
)
from tests.dispatcher.verification_helpers import HEAD, ledger, request


_SECRET = "credential=SHOULD_NOT_PERSIST"
_PRIVATE_PATH = "/Users/operator/private-vault"
_ADVERSARIAL_PRIVATE_VALUES = (
    "OPENAI_API_KEY SHOULD_NOT_PERSIST",
    "AWS_SECRET=SHOULD_NOT_PERSIST",
    "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.signature0123456789",
    "/root/.ssh/id_rsa",
    "/srv/private/vault",
    "/mnt/secrets/token",
    r"C:\Users\operator\private-vault\token.txt",
    r"\\server\share\private-vault\token.txt",
    r'{"x-api-key":"hunter\"vault-secret"}',
    "https://github.com/%2567%2568%2570%255FABCDEF1234567890/repo/issues/1",
    "https://[github.com/org/repo",
    "https://github.com：443/org/repo",
    "https://github.com／org/repo",
    "https://github.com/private-codename-rose/repo/issues/1",
)
_TRUSTED_REPOSITORY = "RasmusTho/agentic-pkm-mvp"
_SAFE_EVIDENCE_URL = f"https://github.com/{_TRUSTED_REPOSITORY}/pull/3603"


def sanitize_verification_closer_receipt(
    receipt: dict[str, object],
) -> dict[str, object]:
    """Exercise repository-bound projection; run-bound tests pass exact evidence."""

    return _sanitize_verification_closer_receipt(
        receipt, trusted_repository=_TRUSTED_REPOSITORY
    )


def _assert_private_text_absent(value: object) -> None:
    encoded = json.dumps(value, sort_keys=True)
    assert "SHOULD_NOT_PERSIST" not in encoded
    assert _PRIVATE_PATH not in encoded
    for private_value in _ADVERSARIAL_PRIVATE_VALUES:
        assert private_value not in encoded
    assert len(encoded) < 20_000


def _unsafe_text() -> str:
    return " ; ".join((_SECRET, _PRIVATE_PATH, *_ADVERSARIAL_PRIVATE_VALUES))


@pytest.mark.parametrize(
    "summary",
    [
        'diagnostic {"password": "hunter2", "credential": "vault-secret"}',
        "diagnostic {'password': 'hunter2', 'credential': 'vault-secret'}",
        'diagnostic {"x-api-key": "hunter2", "db.password": "vault-secret"}',
    ],
)
def test_quoted_credential_assignments_are_sanitized_before_persistence(
    summary: str,
) -> None:
    sanitized = sanitize_verification_closer_receipt(
        {
            "verdict": "blocked",
            "head_sha": HEAD,
            "summary": summary,
            "receipt_ids": [],
            "retry_after": None,
            "review_events": None,
            "human_exception": None,
        }
    )

    encoded = json.dumps(sanitized, sort_keys=True)
    assert "hunter2" not in encoded
    assert "vault-secret" not in encoded
    assert sanitized["summary"] == "[REDACTED]"
    assert sanitize_verification_closer_receipt(sanitized) == sanitized


@pytest.mark.parametrize("quote", ['"', "'"])
def test_hyphenated_quoted_credential_assignments_are_sanitized_before_persistence(
    quote: str,
) -> None:
    summary = (
        f"{{{quote}x-api-key{quote}: {quote}hunter2{quote}, "
        f"{quote}client-secret{quote}: {quote}vault-secret{quote}}}"
    )
    sanitized = sanitize_verification_closer_receipt(
        {
            "verdict": "blocked",
            "head_sha": HEAD,
            "summary": summary,
            "receipt_ids": [],
            "retry_after": None,
            "review_events": None,
            "human_exception": None,
        }
    )

    encoded = json.dumps(sanitized, sort_keys=True)
    assert "hunter2" not in encoded
    assert "vault-secret" not in encoded


@pytest.mark.parametrize(
    "summary",
    [
        r'{"x-api-key":"hunter\"vault-secret"}',
        r"{'x-api-key':'hunter\'vault-secret'}",
    ],
)
def test_escaped_quoted_credential_value_is_fully_redacted(summary: str) -> None:
    sanitized = sanitize_verification_closer_receipt(
        {
            "verdict": "blocked",
            "head_sha": HEAD,
            "summary": summary,
            "receipt_ids": [],
            "retry_after": None,
            "review_events": None,
            "human_exception": None,
        }
    )

    assert "hunter" not in str(sanitized["summary"])
    assert "vault-secret" not in str(sanitized["summary"])
    assert sanitize_verification_closer_receipt(sanitized) == sanitized


def test_secret_shaped_github_urls_are_sanitized_before_persistence() -> None:
    aws_key = "AKIA" + "IOSFODNN7EXAMPLE"
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.signature0123456789"
    safe_urls = [
        "https://github.com/RasmusTho/agentic-pkm-mvp",
        "https://github.com/RasmusTho/agentic-pkm-mvp/issues/3764",
        "https://github.com/RasmusTho/agentic-pkm-mvp/pull/3620",
        "https://github.com/RasmusTho/agentic-pkm-mvp/actions/runs/123",
    ]
    unsafe_urls = [
        f"https://github.com/RasmusTho/agentic-pkm-mvp/actions/runs/123/{aws_key}",
        f"https://github.com/RasmusTho/agentic-pkm-mvp/actions/runs/123/{jwt}",
        "https://github.com/RasmusTho/agentic-pkm-mvp/actions/runs/123/credential=vault-secret",
        "https://github.com/RasmusTho/agentic-pkm-mvp/blob/main/Users/operator/private-vault",
        "https://operator:hunter2@github.com/RasmusTho/agentic-pkm-mvp",
    ]
    safe_projection = sanitize_verification_closer_receipt(
        {
            "verdict": "blocked",
            "head_sha": HEAD,
            "summary": " ".join(safe_urls),
            "receipt_ids": [],
            "retry_after": None,
            "review_events": None,
            "human_exception": None,
        }
    )
    safe_summary = safe_projection["summary"]
    assert isinstance(safe_summary, str)

    for safe_url in safe_urls:
        assert safe_url in safe_summary
    for unsafe_url, private_value in zip(
        unsafe_urls,
        (aws_key, jwt, "vault-secret", "/Users/operator/private-vault", "hunter2"),
        strict=True,
    ):
        unsafe_projection = sanitize_verification_closer_receipt(
            {
                "verdict": "blocked",
                "head_sha": HEAD,
                "summary": unsafe_url,
                "receipt_ids": [],
                "retry_after": None,
                "review_events": None,
                "human_exception": None,
            }
        )
        assert private_value not in str(unsafe_projection["summary"])
        assert unsafe_projection["summary"] == "[REDACTED]"


def test_free_form_coordinator_text_is_allowlisted_before_persistence() -> None:
    private_values = (
        "Basic YWRtaW46c2VjcmV0",
        "short-private-material",
        "novel-secret-value",
    )
    sanitized = sanitize_verification_closer_receipt(
        {
            "verdict": "blocked",
            "head_sha": HEAD,
            "summary": (
                "Authorization: Basic YWRtaW46c2VjcmV0; "
                "private_key: short-private-material; "
                "unclassified_material: novel-secret-value"
            ),
            "receipt_ids": [],
            "retry_after": None,
            "review_events": None,
            "human_exception": None,
        }
    )

    assert sanitized["summary"] == "[REDACTED]"
    encoded = json.dumps(sanitized, sort_keys=True)
    for private_value in private_values:
        assert private_value not in encoded


def test_allowlisted_text_projection_retains_only_safe_github_evidence() -> None:
    safe_urls = (
        "https://github.com/RasmusTho/agentic-pkm-mvp",
        "https://github.com/RasmusTho/agentic-pkm-mvp/issues/3768",
        "https://github.com/RasmusTho/agentic-pkm-mvp/pull/3620",
        "https://github.com/RasmusTho/agentic-pkm-mvp/actions/runs/123",
    )
    sanitized = sanitize_verification_closer_receipt(
        {
            "verdict": "blocked",
            "head_sha": HEAD,
            "summary": (
                "private narrative "
                + " ".join(safe_urls)
                + " https://example.com/private https://github.com/org/repo/blob/main/private"
            ),
            "receipt_ids": [],
            "retry_after": None,
            "review_events": None,
            "human_exception": None,
        }
    )

    assert sanitized["summary"] == "[REDACTED] " + " ".join(safe_urls)
    assert "private narrative" not in str(sanitized["summary"])
    assert "example.com" not in str(sanitized["summary"])
    assert "/blob/" not in str(sanitized["summary"])


def test_allowlisted_urls_require_authenticated_repository_identity() -> None:
    trusted_url = f"https://github.com/{_TRUSTED_REPOSITORY}/issues/3769"
    private_identity = "private-codename-rose"
    foreign_urls = (
        f"https://github.com/{private_identity}/repo/issues/1",
        f"https://api.github.com/repos/{private_identity}/repo/issues/1",
        f"https://github.com/{private_identity}/repo/actions/runs/1",
    )
    sanitized = sanitize_verification_closer_receipt(
        {
            "verdict": "blocked",
            "head_sha": HEAD,
            "summary": " ".join((trusted_url, *foreign_urls)),
            "receipt_ids": [],
            "retry_after": None,
            "review_events": None,
            "human_exception": None,
        }
    )

    summary = str(sanitized["summary"])
    assert trusted_url in summary
    assert private_identity not in summary


def test_allowlisted_urls_require_authenticated_run_evidence(tmp_path) -> None:
    run = ledger(tmp_path).ingest(request())
    trusted = _trusted_evidence_urls(run)
    expected = {
        f"https://github.com/{_TRUSTED_REPOSITORY}",
        f"https://api.github.com/repos/{_TRUSTED_REPOSITORY}",
        f"https://github.com/{_TRUSTED_REPOSITORY}/issues/3603",
        f"https://api.github.com/repos/{_TRUSTED_REPOSITORY}/issues/3603",
        f"https://github.com/{_TRUSTED_REPOSITORY}/pull/3603",
        f"https://api.github.com/repos/{_TRUSTED_REPOSITORY}/pulls/3603",
        f"https://github.com/{_TRUSTED_REPOSITORY}/actions/runs/99",
        f"https://api.github.com/repos/{_TRUSTED_REPOSITORY}/actions/runs/99",
        f"https://github.com/{_TRUSTED_REPOSITORY}/actions/runs/123",
        f"https://api.github.com/repos/{_TRUSTED_REPOSITORY}/actions/runs/123",
    }
    assert trusted == frozenset(expected)

    arbitrary_same_repo_url = (
        f"https://github.com/{_TRUSTED_REPOSITORY}/issues/999999999"
    )
    sanitized = _sanitize_verification_closer_receipt(
        {
            "verdict": "blocked",
            "head_sha": HEAD,
            "summary": f"{next(iter(expected))} {arbitrary_same_repo_url}",
            "receipt_ids": [],
            "retry_after": None,
            "review_events": None,
            "human_exception": None,
        },
        trusted_repository=_TRUSTED_REPOSITORY,
        trusted_evidence_urls=trusted,
    )

    assert arbitrary_same_repo_url not in str(sanitized["summary"])


def test_human_exception_actions_are_canonical_safe_and_actionable() -> None:
    _, receipt = Launcher().launch({})
    packet = receipt["human_exception"]
    assert isinstance(packet, dict)
    packet["options"] = [
        {
            "id": "privatecodename",
            "label": "Private owner wording",
            "consequence": "Private consequence",
        },
        {
            "id": "model-authored-action",
            "label": "Authorize requested action",
            "consequence": "Continue within linked gates",
        },
        {
            "id": "another-private-option",
            "label": "Choose a different path",
            "consequence": "Record a choice on the linked issue",
        },
    ]
    packet["no_action_option"] = "privatecodename"
    packet["recommended_option"] = "model-authored-action"

    sanitized = sanitize_verification_closer_receipt(receipt)
    safe_packet = sanitized["human_exception"]
    assert isinstance(safe_packet, dict)
    assert [option["id"] for option in safe_packet["options"]] == [
        "hold",
        "authorize",
        "select-alternative",
    ]
    assert safe_packet["no_action_option"] == "hold"
    assert safe_packet["recommended_option"] == "authorize"
    assert [option["label"] for option in safe_packet["options"]] == [
        "Keep delivery blocked",
        "Authorize the linked gated action",
        "Select an alternative on the linked issue",
    ]
    encoded = json.dumps(safe_packet, sort_keys=True)
    assert "privatecodename" not in encoded
    assert "model-authored-action" not in encoded
    assert "another-private-option" not in encoded


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (float("nan"), None),
        (float("inf"), None),
        (-1, None),
        (10**1000, None),
        (7200, 3600),
        ("5m", "300s"),
        ("9" * 10_000 + "h", None),
        ("2030-01-02T03:04:05", None),
        (
            "2030-01-02T03:04:05+02:00",
            "2030-01-02T01:04:05.000000+00:00",
        ),
    ],
)
def test_retry_after_is_bounded_and_canonical(
    value: object, expected: object
) -> None:
    _, receipt = Launcher().launch({})
    receipt["retry_after"] = value

    sanitized = sanitize_verification_closer_receipt(receipt)

    assert sanitized["retry_after"] == expected


def _mixed_channel_failure_launcher(
    tmp_path, *, stderr: str, terminal_event: dict[str, object]
) -> CodexExecLauncher:
    class Result:
        returncode = 1

        def __init__(self) -> None:
            self.stdout = "\n".join(
                (
                    json.dumps(
                        {
                            "type": "thread.started",
                            "thread_id": "01900000-0000-7000-8000-000000000092",
                        }
                    ),
                    json.dumps(terminal_event),
                )
            )
            self.stderr = stderr

    def runner(*args, **kwargs):
        return Result()

    return CodexExecLauncher(
        tmp_path,
        Path(__file__).resolve().parents[2]
        / "app/dispatcher/schemas/verification_closer_receipt.schema.json",
        tmp_path / "context.json",
        adapter_path=Path(__file__).resolve().parents[2]
        / ".codex/agents/verification-closer.toml",
        runner=runner,
    )


def test_structured_stdout_rate_limit_is_not_masked_by_benign_stderr(
    tmp_path,
) -> None:
    state = ledger(tmp_path)
    result = VerificationConsumer(
        state,
        Truth(eligible_pr(), GREEN),
        Auth(),
        _mixed_channel_failure_launcher(
            tmp_path,
            stderr="benign provider warning",
            terminal_event={
                "type": "error",
                "error": {"code": "rate_limit_exceeded", "status": 429},
            },
        ),
        "host",
    ).consume(request())

    assert result.status == "backoff"
    assert result.terminal_receipt["api_fallback"] is False
    assert result.terminal_receipt["failure_receipt"]["failure_class"] == "rate_limit"
    assert state.attempts(result.run_id)[-1]["outcome"] == "rate_limited"


def test_mixed_channel_prose_does_not_authorize_rate_limit_backoff(tmp_path) -> None:
    result = VerificationConsumer(
        ledger(tmp_path),
        Truth(eligible_pr(), GREEN),
        Auth(),
        _mixed_channel_failure_launcher(
            tmp_path,
            stderr="rate limit exceeded according to a free-form warning",
            terminal_event={
                "type": "error",
                "message": "free-form 429 rate limit prose",
            },
        ),
        "host",
    ).consume(request())

    assert result.status == "failed"
    assert result.stop_reason == "codex_exec_failed"
    assert result.terminal_receipt["failure_class"] == "execution"


def test_untrusted_branch_refs_never_cross_dispatch_or_context_boundaries(
    tmp_path,
) -> None:
    raw_request = request()
    assert "base_ref" not in raw_request
    assert "head_ref" not in raw_request
    run = ledger(tmp_path).ingest(raw_request)
    pr = eligible_pr()
    secret_ref = "codex/ghp_LEAKME1234567890"
    pr["base"]["ref"] = secret_ref
    pr["head"]["ref"] = secret_ref

    pack = context_pack(run, pr)
    encoded = json.dumps({"request": run.request, "pack": pack}, sort_keys=True)

    assert secret_ref not in encoded
    assert "base_ref" not in pack
    assert "head_ref" not in pack


def test_dispatch_identity_does_not_require_branch_refs(tmp_path) -> None:
    raw_request = request()
    raw_request.pop("base_ref", None)
    raw_request.pop("head_ref", None)

    run = ledger(tmp_path).ingest(raw_request)
    pack = context_pack(run, eligible_pr())

    assert run.repository == _TRUSTED_REPOSITORY
    assert run.pr_number == 3603
    assert run.head_sha == HEAD
    assert "base_ref" not in pack
    assert "head_ref" not in pack


def _artifact_source_with_authenticated_runs(
    *, uploader_name: str, uploader_path: str
) -> tuple[GhCliVerificationSource, list[str], list[int]]:
    raw_request = request()
    archive_bytes = io.BytesIO()
    with zipfile.ZipFile(archive_bytes, "w") as archive:
        archive.writestr("verification-dispatch/request.json", json.dumps(raw_request))
    calls: list[str] = []
    downloads: list[int] = []
    source = GhCliVerificationSource()

    def json_response(endpoint: str) -> object:
        calls.append(endpoint)
        if endpoint.endswith("actions/artifacts?per_page=100"):
            return {
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
                            "head_sha": "b" * 40,
                        },
                    }
                ]
            }
        if endpoint.endswith("actions/runs/123"):
            return {
                "id": 123,
                "name": uploader_name,
                "path": uploader_path,
                "event": "workflow_run",
                "run_attempt": 1,
                "status": "completed",
                "conclusion": "success",
                "head_sha": "b" * 40,
                "repository": {"id": 456, "full_name": _TRUSTED_REPOSITORY},
                "head_repository": {
                    "id": 456,
                    "full_name": _TRUSTED_REPOSITORY,
                },
            }
        if endpoint.endswith("actions/runs/99"):
            return {
                "id": 99,
                "run_attempt": 1,
                "name": "CI",
                "event": "pull_request",
                "status": "completed",
                "conclusion": "success",
                "head_sha": HEAD,
                "repository": {"id": 456, "full_name": _TRUSTED_REPOSITORY},
                "head_repository": {
                    "id": 456,
                    "full_name": _TRUSTED_REPOSITORY,
                },
            }
        raise AssertionError(f"unexpected GitHub endpoint: {endpoint}")

    def artifact_bytes(_endpoint: str, artifact_id: int) -> bytes:
        downloads.append(artifact_id)
        return archive_bytes.getvalue()

    source._json = json_response  # type: ignore[method-assign]
    source._artifact_bytes = artifact_bytes  # type: ignore[method-assign]
    return source, calls, downloads


def test_foreign_artifact_uploader_workflow_is_rejected_before_persistence() -> None:
    source, calls, downloads = _artifact_source_with_authenticated_runs(
        uploader_name="Foreign Artifact Producer",
        uploader_path=".github/workflows/foreign.yml",
    )

    with pytest.raises(ValueError, match="artifact uploader workflow identity"):
        source.pending_requests(_TRUSTED_REPOSITORY)

    assert any(endpoint.endswith("actions/runs/123") for endpoint in calls)
    assert downloads == []


def test_canonical_artifact_uploader_workflow_is_authenticated() -> None:
    source, calls, downloads = _artifact_source_with_authenticated_runs(
        uploader_name="Verification Dispatch Request",
        uploader_path=".github/workflows/verification-dispatch-request.yml",
    )

    assert source.pending_requests(_TRUSTED_REPOSITORY) == [request()]
    assert any(endpoint.endswith("actions/runs/123") for endpoint in calls)
    assert downloads == [7]


def _mixed_artifact_source(
    artifacts: list[dict[str, object]], *, fail_uploader_read: bool = False
) -> GhCliVerificationSource:
    raw_request = request()
    archive_bytes = io.BytesIO()
    with zipfile.ZipFile(archive_bytes, "w") as archive:
        archive.writestr("verification-dispatch/request.json", json.dumps(raw_request))
    source = GhCliVerificationSource()

    def json_response(endpoint: str) -> object:
        if endpoint.endswith("actions/artifacts?per_page=100"):
            return {"artifacts": artifacts}
        if endpoint.endswith("actions/runs/123"):
            if fail_uploader_read:
                raise RuntimeError("GitHub transport unavailable")
            return {
                "id": 123,
                "name": "Verification Dispatch Request",
                "path": ".github/workflows/verification-dispatch-request.yml",
                "event": "workflow_run",
                "run_attempt": 1,
                "status": "completed",
                "conclusion": "success",
                "head_sha": "b" * 40,
                "repository": {"id": 456, "full_name": _TRUSTED_REPOSITORY},
                "head_repository": {"id": 456, "full_name": _TRUSTED_REPOSITORY},
            }
        if endpoint.endswith("actions/runs/99"):
            return {
                "id": 99,
                "run_attempt": 1,
                "name": "CI",
                "event": "pull_request",
                "status": "completed",
                "conclusion": "success",
                "head_sha": HEAD,
                "repository": {"id": 456, "full_name": _TRUSTED_REPOSITORY},
                "head_repository": {"id": 456, "full_name": _TRUSTED_REPOSITORY},
            }
        raise AssertionError(f"unexpected GitHub endpoint: {endpoint}")

    source._json = json_response  # type: ignore[method-assign]
    source._artifact_bytes = (  # type: ignore[method-assign]
        lambda _endpoint, _artifact_id: archive_bytes.getvalue()
    )
    return source


def _valid_artifact() -> dict[str, object]:
    return {
        "id": 7,
        "name": f"verification-dispatch-3603-{HEAD}",
        "size_in_bytes": 1,
        "expired": False,
        "workflow_run": {
            "id": 123,
            "repository_id": 456,
            "head_repository_id": 456,
            "head_sha": "b" * 40,
        },
    }


def _legacy_artifact() -> dict[str, object]:
    return {
        "id": 8,
        "name": f"verification-dispatch-legacy-{HEAD}",
        "size_in_bytes": 1,
        "expired": False,
        "workflow_run": {},
    }


def test_valid_artifact_survives_legacy_and_malformed_candidates() -> None:
    source = _mixed_artifact_source([_valid_artifact(), _legacy_artifact()])

    assert source.pending_requests(_TRUSTED_REPOSITORY) == [request()]


def test_invalid_artifact_cannot_deny_service_to_later_valid_candidate() -> None:
    source = _mixed_artifact_source([_legacy_artifact(), _valid_artifact()])

    assert source.pending_requests(_TRUSTED_REPOSITORY) == [request()]


def test_artifact_poll_transport_failure_is_not_silently_skipped() -> None:
    source = _mixed_artifact_source([_valid_artifact()], fail_uploader_read=True)

    with pytest.raises(RuntimeError, match="GitHub transport unavailable"):
        source.pending_requests(_TRUSTED_REPOSITORY)


def test_allowlisted_text_projection_preserves_structural_receipt_fields() -> None:
    _, receipt = Launcher().launch({})
    receipt["retry_after"] = "2030-01-02T03:04:05+00:00"

    sanitized = sanitize_verification_closer_receipt(receipt)
    packet = sanitized["human_exception"]

    assert sanitized["verdict"] == "needs_human"
    assert sanitized["head_sha"] == HEAD
    assert sanitized["retry_after"] == "2030-01-02T03:04:05.000000+00:00"
    assert isinstance(packet, dict)
    assert packet["recommended_option"] == "hold"
    assert packet["no_action_option"] == "hold"
    assert [option["id"] for option in packet["options"]] == ["hold", "authorize"]

    receipt["retry_after"] = "Authorization: Basic YWRtaW46c2VjcmV0"
    assert sanitize_verification_closer_receipt(receipt)["retry_after"] is None


@pytest.mark.parametrize(
    ("url", "private_value"),
    [
        (
            "https://github.com/gh" + "p_ABCDEF1234567890/repo/issues/1",
            "gh" + "p_ABCDEF1234567890",
        ),
        (
            "https://github.com/org/ABCDEF0123456789abcdef/pull/1",
            "ABCDEF0123456789abcdef",
        ),
        (
            "https://api.github.com/repos/gh"
            + "p_ABCDEF1234567890/repo/issues/1",
            "gh" + "p_ABCDEF1234567890",
        ),
    ],
)
def test_secret_shaped_github_identity_components_are_redacted(
    url: str,
    private_value: str,
) -> None:
    sanitized = sanitize_verification_closer_receipt(
        {
            "verdict": "blocked",
            "head_sha": HEAD,
            "summary": url,
            "receipt_ids": [],
            "retry_after": None,
            "review_events": None,
            "human_exception": None,
        }
    )

    assert private_value not in str(sanitized["summary"])
    assert sanitized["summary"] == "[REDACTED]"


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/%2567%2568%2570%255FABCDEF1234567890/repo/issues/1",
        "https://api.github.com/repos/org/%2567%2568%2570%255FABCDEF1234567890/issues/1",
        "https://github.com/org/repo/%252FUsers%252Foperator%252Fprivate-vault",
    ],
)
def test_encoded_github_components_fail_closed(url: str) -> None:
    sanitized = sanitize_verification_closer_receipt(
        {
            "verdict": "blocked",
            "head_sha": HEAD,
            "summary": url,
            "receipt_ids": [],
            "retry_after": None,
            "review_events": None,
            "human_exception": None,
        }
    )

    assert "%" not in str(sanitized["summary"])
    assert sanitized["summary"] == "[REDACTED]"


@pytest.mark.parametrize(
    "url",
    [
        "https://[github.com/org/repo",
        "https://github.com：443/org/repo",
        "https://github.com／org/repo",
    ],
)
def test_malformed_https_origins_fail_closed(url: str) -> None:
    sanitized = sanitize_verification_closer_receipt(
        {
            "verdict": "blocked",
            "head_sha": HEAD,
            "summary": url,
            "receipt_ids": [],
            "retry_after": None,
            "review_events": None,
            "human_exception": None,
        }
    )

    assert sanitized["summary"] == "[REDACTED]"


def test_quoted_safe_github_urls_and_many_placeholders_remain_actionable() -> None:
    safe_urls = [
        f"https://github.com/{_TRUSTED_REPOSITORY}/issues/{index}"
        for index in range(6)
    ]
    quoted = f'"{safe_urls[0]}"'
    sanitized = sanitize_verification_closer_receipt(
        {
            "verdict": "blocked",
            "head_sha": HEAD,
            "summary": " ; ".join((quoted, *safe_urls[1:])),
            "receipt_ids": [],
            "retry_after": None,
            "review_events": None,
            "human_exception": None,
        }
    )

    summary = str(sanitized["summary"])
    assert summary.startswith("[REDACTED] ")
    assert all(url in summary for url in safe_urls)
    assert sanitize_verification_closer_receipt(sanitized) == sanitized


def test_raw_placeholder_text_cannot_duplicate_a_preserved_url() -> None:
    safe_url = f"https://github.com/{_TRUSTED_REPOSITORY}/issues/3764"
    sanitized = sanitize_verification_closer_receipt(
        {
            "verdict": "blocked",
            "head_sha": HEAD,
            "summary": f"raw=\x00SAFELINK0\x00 ; {safe_url}",
            "receipt_ids": [],
            "retry_after": None,
            "review_events": None,
            "human_exception": None,
        }
    )

    assert str(sanitized["summary"]).count(safe_url) == 1


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


class _UnsafeBlockedLauncher(Launcher):
    def launch(self, context_pack, **kwargs):
        self.calls.append((context_pack, kwargs.get("resume_session_id")))
        session = "01900000-0000-7000-8000-000000000091"
        if callback := kwargs.get("on_thread_started"):
            callback(session)
        return session, {
            "verdict": "blocked",
            "head_sha": HEAD,
            "summary": _unsafe_text() + " " + "x" * 5_000,
            "receipt_ids": [
                f"token={_SECRET}",
                _PRIVATE_PATH,
                "AWS_SECRET=SHOULD_NOT_PERSIST",
            ],
            "retry_after": None,
            "review_events": None,
            "human_exception": None,
        }


class _UnsafeDeliveredLauncher(DeliveredLauncher):
    def launch(self, context_pack, **kwargs):
        session, receipt = super().launch(context_pack, **kwargs)
        receipt["summary"] = _unsafe_text() + " " + "x" * 5_000
        receipt["receipt_ids"] = [
            f"token={_SECRET}",
            _PRIVATE_PATH,
            "AWS_SECRET=SHOULD_NOT_PERSIST",
        ]
        events = receipt["review_events"]
        assert isinstance(events, list)
        events[0]["session_id"] = _PRIVATE_PATH
        events[1]["session_id"] = "AWS_SECRET=SHOULD_NOT_PERSIST"
        return session, receipt


class _RepeatedReplayOutageTruth(Truth):
    def __init__(self) -> None:
        super().__init__(eligible_pr(), GREEN)
        self.pull_calls = 0

    def pull_request(self, repository, pr_number):
        self.pull_calls += 1
        if self.pull_calls <= 2:
            return eligible_pr()
        if self.pull_calls <= 4:
            raise RuntimeError("simulated repeated post-merge terminal outage")
        return merged_pr()


def test_schema_valid_receipt_text_is_sanitized_before_all_durable_writes(
    tmp_path,
) -> None:
    blocked_state = ledger(tmp_path / "blocked")
    blocked = VerificationConsumer(
        blocked_state,
        Truth(eligible_pr(), GREEN),
        Auth(),
        _UnsafeBlockedLauncher(),
        "host",
    ).consume(request())
    _assert_private_text_absent(blocked_state.attempts(blocked.run_id))
    _assert_private_text_absent(blocked.terminal_receipt)
    _assert_private_text_absent(_compact_verification_run(blocked))

    pending_state = ledger(tmp_path / "pending")
    pending = VerificationConsumer(
        pending_state,
        FailingPostLaunchPrTruth(),
        Auth(),
        _UnsafeDeliveredLauncher(),
        "host",
    ).consume(request())
    assert pending.status == "backoff"
    _assert_private_text_absent(pending_state.attempts(pending.run_id))
    _assert_private_text_absent(pending.terminal_receipt)
    _assert_private_text_absent(_compact_verification_run(pending))


def test_sanitized_pending_delivery_replay_preserves_required_semantics(
    tmp_path,
) -> None:
    state = ledger(tmp_path)
    launcher = _UnsafeDeliveredLauncher()
    consumer = VerificationConsumer(
        state,
        _RepeatedReplayOutageTruth(),
        Auth(),
        launcher,
        "host",
    )

    pending = consumer.consume(request())
    assert pending.status == "backoff"
    assert pending.terminal_receipt is not None
    persisted = pending.terminal_receipt["pending_terminal_receipt"]
    _assert_private_text_absent(persisted)

    def release_backoff() -> None:
        with state.store._connect() as conn:
            conn.execute(
                "UPDATE verification_runs SET retry_after='2000-01-01T00:00:00+00:00' "
                "WHERE run_id=?",
                (pending.run_id,),
            )
            conn.commit()

    release_backoff()
    pending_again = consumer.consume(request())
    assert pending_again.status == "backoff"
    assert pending_again.terminal_receipt is not None
    assert pending_again.terminal_receipt["pending_terminal_receipt"] == persisted
    assert state.attempts(pending.run_id)[0]["receipt"] == persisted

    release_backoff()
    completed = consumer.consume(request())

    assert completed.status == "completed"
    assert completed.verified_head_sha == HEAD
    assert len(launcher.calls) == 1
    assert [row["kind"] for row in state.attempts(completed.run_id)] == [
        "verification",
        "review",
        "review",
    ]
    _assert_private_text_absent(state.attempts(completed.run_id))
    _assert_private_text_absent(completed.terminal_receipt)


class _UnsafeHumanExceptionLauncher(Launcher):
    def launch(self, context_pack, **kwargs):
        session, receipt = super().launch(context_pack, **kwargs)
        packet = receipt["human_exception"]
        assert isinstance(packet, dict)
        unsafe = (
            "retain decision context; "
            + _unsafe_text()
            + f"; evidence {_SAFE_EVIDENCE_URL}?token=SHOULD_NOT_PERSIST"
        )
        for key in (
            "original_intent",
            "current_state",
            "why_unsafe",
            "recommendation_rationale",
            "consequence_of_doing_nothing",
        ):
            packet[key] = unsafe + " x" * 2_000
        packet["tried_actions"] = [unsafe]
        packet["evidence"] = [unsafe]
        for option in packet["options"]:
            option["label"] = unsafe
            option["consequence"] = unsafe
        receipt["summary"] = unsafe
        receipt["receipt_ids"] = [unsafe]
        return session, receipt


def test_human_exception_packet_is_bounded_and_sanitized(tmp_path) -> None:
    state = ledger(tmp_path)
    result = VerificationConsumer(
        state,
        Truth(eligible_pr(), GREEN),
        Auth(),
        _UnsafeHumanExceptionLauncher(),
        "host",
    ).consume(request())

    assert result.status == "needs_human"
    with state.store._connect() as conn:
        row = conn.execute(
            "SELECT packet_json FROM verification_exceptions WHERE run_id=?",
            (result.run_id,),
        ).fetchone()
    assert row is not None
    packet = json.loads(row["packet_json"])
    _assert_private_text_absent(packet)
    assert packet["recommended_option"] == "hold"
    assert packet["no_action_option"] == "hold"
    assert len(packet["options"]) == 2
    assert all(len(item["consequence"]) <= 512 for item in packet["options"])
    assert all(len(item) <= 512 for item in packet["evidence"])
    assert _SAFE_EVIDENCE_URL in packet["evidence"][0]
    assert "?token=" not in packet["evidence"][0]


def test_receipt_sanitization_is_a_canonical_fixed_point() -> None:
    _, receipt = _UnsafeDeliveredLauncher().launch({})

    once = sanitize_verification_closer_receipt(receipt)
    twice = sanitize_verification_closer_receipt(once)

    assert twice == once


def test_pending_receipt_replay_uses_only_sanitized_fixed_point() -> None:
    _, receipt = _UnsafeDeliveredLauncher().launch({})

    sanitized = sanitize_verification_closer_receipt(receipt)

    assert sanitize_verification_closer_receipt(sanitized) == sanitized


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
