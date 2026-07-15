from __future__ import annotations

import json
import pytest

from app.dispatcher.cli import _compact_verification_run
from app.dispatcher.verification_consumer import (
    VerificationConsumer,
    _checks_rejection,
    sanitize_verification_closer_receipt,
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
)
_SAFE_EVIDENCE_URL = "https://github.com/RasmusTho/agentic-pkm-mvp/pull/3620"


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
    assert encoded.count("[REDACTED]") == 2


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
