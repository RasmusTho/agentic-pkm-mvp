from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

import jsonschema
import pytest

from app.dispatcher.verification_agent_loop import VerificationAgentLoop
from app.dispatcher.verification_api import BuilderOpsVerificationLedger
from app.dispatcher.verification_consumer import (
    sanitize_verification_closer_receipt,
    validate_verification_closer_receipt,
)
from app.dispatcher.verification_dispatch import (
    REPAIR_INTENT_ATTEMPT_KIND,
    VerificationDispatchLedger,
    _ValidatedVerificationAttemptReceipt,
    _is_exact_event_batch_replay,
    _verification_receipt_admission_binding,
    build_repair_transition_evidence,
    plan_repair_progress_intents,
)
from scripts.build_verification_dispatch_request import build_request
from tests.dispatcher.builderops_verification_fakes import FakeBuilderOpsClient
from tests.dispatcher.verification_helpers import (
    HEAD,
    REPO,
    admit_verification_receipt,
    ledger,
    request,
    verified_attempt_receipt,
)


FINDING = "progress-admission"
DOMAIN = "review_code_correctness"
MECHANISM = "verification-repair-progress"
SECOND_HEAD = "b" * 40
SEED_HEAD = "0" * 40
MECHANISM_PATH = "app/dispatcher/verification_dispatch.py"
MECHANISM_PATH_SHA = hashlib.sha256(MECHANISM_PATH.encode()).hexdigest()
OTHER_MECHANISM_PATH_SHA = hashlib.sha256(
    b"app/dispatcher/verification_consumer.py"
).hexdigest()


def _identity_request(repository: str, pr_number: int) -> dict[str, object]:
    result = build_request(
        event={
            "repository": {"full_name": repository},
            "artifact_workflow_run": {"id": 123, "repository_id": 456},
            "workflow_run": {
                "id": 99,
                "run_attempt": 1,
                "name": "CI Smoke",
                "event": "pull_request",
                "conclusion": "success",
                "head_sha": HEAD,
                "updated_at": "2026-07-13T12:00:00Z",
            },
        },
        pr={
            "number": pr_number,
            "state": "open",
            "body": (
                f"Governing-Issue: #{pr_number}\n\nFixes #{pr_number}\n\n"
                "Final-Review-Rounds: 1"
            ),
            "base": {"ref": "main"},
            "head": {"ref": f"codex/issue-{pr_number}", "sha": HEAD},
            "live_closing_issues": [
                {"number": pr_number, "repository": repository},
            ],
        },
        issue={"number": pr_number},
    )
    assert result is not None
    return result


def _verified_receipt(head: str = HEAD, *, verdict: str = "verified"):
    return verified_attempt_receipt(head, verdict=verdict, summary="verified")


def _transition(
    base_head: str,
    repaired_head: str,
    *,
    path: str = MECHANISM_PATH,
    blob_sha: str | None = None,
    extra_paths: tuple[str, ...] = (),
) -> dict[str, object]:
    return build_repair_transition_evidence(
        base_head_sha=base_head,
        repaired_head_sha=repaired_head,
        commits=[repaired_head],
        files=[
            {
                "path_sha256": hashlib.sha256(candidate.encode()).hexdigest(),
                "previous_path_sha256": None,
                "status": "modified",
                "blob_sha": blob_sha or repaired_head,
            }
            for candidate in (path, *extra_paths)
        ],
    )


def _repair_event(intent_id: str) -> dict[str, object]:
    return {
        "kind": "repair",
        "session_id": "repair-2",
        "capability": "gpt-5.6-terra",
        "reasoning_effort": "high",
        "outcome": "fixed",
        "finding_id": FINDING,
        "failure_domain": DOMAIN,
        "mechanism_id": MECHANISM,
        "progress_intent_id": intent_id,
        "strongest": False,
    }


def _exercise_progress_intent_parity(
    state: Any,
    restart: Callable[[], Any],
) -> None:
    run = state.ingest(request())
    claimed = state.claim(run.run_id, "verification-host")
    assert claimed.claimed_by is not None
    assert claimed.lease_id is not None
    holder = claimed.claimed_by
    lease_id = claimed.lease_id
    loop = VerificationAgentLoop(
        state,
        run.run_id,
        holder=holder,
        lease_id=lease_id,
    )
    context = {"head": HEAD}
    loop.repair(
        finding_id=FINDING,
        failure_domain=DOMAIN,
        mechanism_id=MECHANISM,
        session_id="repair-1",
        capability="gpt-5.6-terra",
        reasoning_effort="high",
        context=context,
        outcome="fixed",
        transition_evidence=_transition(
            SEED_HEAD,
            HEAD,
            extra_paths=("docs/unrelated.md",),
        ),
    )
    loop.review(
        finding_id=FINDING,
        failure_domain=DOMAIN,
        mechanism_id=MECHANISM,
        session_id="review-1",
        capability="gpt-5.6-terra",
        reasoning_effort="high",
        context=context,
        outcome="blocking",
        mechanism_path_sha256=[MECHANISM_PATH_SHA],
    )

    intent = plan_repair_progress_intents(
        state.attempts(run.run_id),
        current_head_sha=HEAD,
        validation_sha256="1" * 64,
    )[0]
    intent_id = str(intent["intent_id"])
    with pytest.raises(ValueError, match="ownership mismatch"):
        state.record_attempt(
            run.run_id,
            REPAIR_INTENT_ATTEMPT_KIND,
            intent_id,
            "deterministic",
            "none",
            context,
            "admitted",
            intent,
            holder=holder,
            lease_id="stale-lease",
            idempotency_key=intent_id,
        )
    assert (
        state.record_attempt(
            run.run_id,
            REPAIR_INTENT_ATTEMPT_KIND,
            intent_id,
            "deterministic",
            "none",
            context,
            "admitted",
            intent,
            holder=holder,
            lease_id=lease_id,
            idempotency_key=intent_id,
        )
        == 1
    )
    assert (
        state.record_attempt(
            run.run_id,
            REPAIR_INTENT_ATTEMPT_KIND,
            intent_id,
            "deterministic",
            "none",
            context,
            "admitted",
            intent,
            holder=holder,
            lease_id=lease_id,
            idempotency_key=intent_id,
        )
        == 1
    )

    restarted = restart()
    assert restarted.attempts(run.run_id)[-1]["receipt"] == intent
    restarted.rebind_head(
        run.run_id,
        SECOND_HEAD,
        expected_head_sha=HEAD,
        observed_repository=REPO,
        observed_pr_number=3603,
        observed_head_sha=SECOND_HEAD,
        holder=holder,
        lease_id=lease_id,
    )
    restarted_loop = VerificationAgentLoop(
        restarted,
        run.run_id,
        holder=holder,
        lease_id=lease_id,
    )
    repair_context = {
        "head": SECOND_HEAD,
        "progress_validation_sha256": "2" * 64,
        "repair_transition_evidence": _transition(HEAD, SECOND_HEAD),
    }
    event = _repair_event(intent_id)
    restarted_loop.apply_events([event], context=repair_context)
    restarted_loop.apply_events([event], context=repair_context)
    attempts = restarted.attempts(run.run_id)
    repaired = [row for row in attempts if row["kind"] in {"standard_repair", "escalated_repair"}]
    assert len(repaired) == 2
    evidence = repaired[-1]["receipt"]["progress_evidence"]
    assert evidence["intent_id"] == intent_id
    assert evidence["reviewed_head_sha"] == HEAD
    assert evidence["repaired_head_sha"] == SECOND_HEAD

    restarted_loop.review(
        finding_id=FINDING,
        failure_domain=DOMAIN,
        mechanism_id=MECHANISM,
        session_id="review-2",
        capability="gpt-5.6-terra",
        reasoning_effort="high",
        context=repair_context,
        outcome="blocking",
        mechanism_path_sha256=[MECHANISM_PATH_SHA],
    )
    restarted.backoff(
        run.run_id,
        {"reason": "takeover-test"},
        "2000-01-01T00:00:00+00:00",
        holder=holder,
        lease_id=lease_id,
    )
    taken_over = restarted.claim(run.run_id, "verification-host")
    assert taken_over.claimed_by is not None
    assert taken_over.lease_id is not None
    assert taken_over.lease_id != lease_id
    next_intent = plan_repair_progress_intents(
        restarted.attempts(run.run_id),
        current_head_sha=SECOND_HEAD,
        validation_sha256="3" * 64,
    )[0]
    next_intent_id = str(next_intent["intent_id"])
    assert (
        restarted.record_attempt(
            run.run_id,
            REPAIR_INTENT_ATTEMPT_KIND,
            next_intent_id,
            "deterministic",
            "none",
            {"head": SECOND_HEAD},
            "admitted",
            next_intent,
            holder=taken_over.claimed_by,
            lease_id=taken_over.lease_id,
            idempotency_key=next_intent_id,
        )
        == 2
    )
    with pytest.raises(ValueError, match="ownership mismatch"):
        restarted.record_attempt(
            run.run_id,
            REPAIR_INTENT_ATTEMPT_KIND,
            next_intent_id,
            "deterministic",
            "none",
            {"head": SECOND_HEAD},
            "admitted",
            next_intent,
            holder=holder,
            lease_id=lease_id,
            idempotency_key=next_intent_id,
        )


def test_progress_intent_round_trips_schema_and_consumer_without_authority_loss() -> None:
    schema_path = (
        Path(__file__).resolve().parents[2]
        / "app/dispatcher/schemas/verification_closer_receipt.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    intent_id = "repair-intent-" + "a" * 24
    receipt = {
        "verdict": "blocked",
        "head_sha": HEAD,
        "summary": "repair requires independent review",
        "receipt_ids": [],
        "retry_after": None,
        "review_events": [
            {
                **_repair_event(intent_id),
                "session_id": "repair-session",
            }
        ],
        "human_exception": None,
    }

    validate_verification_closer_receipt(receipt, schema)
    sanitized = sanitize_verification_closer_receipt(receipt)
    validate_verification_closer_receipt(sanitized, schema)
    assert sanitized["review_events"][0]["progress_intent_id"] == intent_id
    assert sanitized["review_events"][0]["mechanism_path_sha256"] is None

    blocking_review = json.loads(json.dumps(receipt))
    blocking_review["review_events"][0].update(
        {
            "kind": "review",
            "outcome": "blocking",
            "progress_intent_id": None,
            "mechanism_path_sha256": [MECHANISM_PATH_SHA],
            "strongest": None,
        }
    )
    validate_verification_closer_receipt(blocking_review, schema)
    sanitized_review = sanitize_verification_closer_receipt(blocking_review)
    validate_verification_closer_receipt(sanitized_review, schema)
    assert sanitized_review["review_events"][0][
        "mechanism_path_sha256"
    ] == [MECHANISM_PATH_SHA]

    unprojected_review = json.loads(json.dumps(blocking_review))
    unprojected_review["review_events"][0]["mechanism_path_sha256"] = None
    with pytest.raises(
        jsonschema.ValidationError,
        match="requires a mechanism path projection",
    ):
        validate_verification_closer_receipt(unprojected_review, schema)

    malformed = json.loads(json.dumps(receipt))
    malformed["review_events"][0]["progress_intent_id"] = "repair-intent-not-canonical"
    with pytest.raises(jsonschema.ValidationError):
        validate_verification_closer_receipt(malformed, schema)


def test_sqlite_progress_intent_is_fenced_monotonic_and_replay_safe(tmp_path) -> None:
    state = ledger(tmp_path)
    _exercise_progress_intent_parity(
        state,
        lambda: VerificationDispatchLedger(state.store),
    )


def test_builderops_progress_intent_is_fenced_monotonic_and_replay_safe() -> None:
    api = FakeBuilderOpsClient()
    state = BuilderOpsVerificationLedger(api, repository=REPO)
    _exercise_progress_intent_parity(
        state,
        lambda: BuilderOpsVerificationLedger(api, repository=REPO),
    )


@pytest.mark.parametrize("backend", ("sqlite", "builderops"))
def test_direct_and_batch_ledgers_cannot_replace_same_round_mechanism_paths(
    tmp_path,
    backend: str,
) -> None:
    state = (
        BuilderOpsVerificationLedger(
            FakeBuilderOpsClient(),
            repository=REPO,
        )
        if backend == "builderops"
        else ledger(tmp_path)
    )
    run = state.ingest(request())
    claimed = state.claim(run.run_id, "verification-host")
    assert claimed.claimed_by is not None
    assert claimed.lease_id is not None
    loop = VerificationAgentLoop(
        state,
        run.run_id,
        holder=claimed.claimed_by,
        lease_id=claimed.lease_id,
    )
    loop.repair(
        finding_id=FINDING,
        failure_domain=DOMAIN,
        mechanism_id=MECHANISM,
        session_id="repair-1",
        capability="gpt-5.6-terra",
        reasoning_effort="high",
        context={"head": HEAD},
        outcome="fixed",
        transition_evidence=_transition(SEED_HEAD, HEAD),
    )
    repair_attempt = state.attempts(run.run_id)[0]
    invalid_clean_receipts = (
        (
            {
                "reviewed_attempt_id": repair_attempt["attempt_id"],
                "head_sha": HEAD,
                "verdict": "clean",
                "finding_id": FINDING,
                "failure_domain": DOMAIN,
                "mechanism_id": MECHANISM,
                "mechanism_path_sha256": None,
            },
            "clean review cannot carry a failure binding",
        ),
        (
            {
                "reviewed_attempt_id": repair_attempt["attempt_id"],
                "head_sha": HEAD,
                "verdict": "clean",
                "finding_id": None,
                "failure_domain": None,
                "mechanism_id": None,
                "mechanism_path_sha256": [MECHANISM_PATH_SHA],
            },
            "only a blocking review may bind mechanism paths",
        ),
    )

    def invalid_clean_batch(receipt_to_write, session):
        def plan(attempts, attempt_id_for):
            return [
                {
                    "attempt_id": attempt_id_for(0),
                    "kind": "review",
                    "ordinal": 1,
                    "session_id": session,
                    "capability": "gpt-5.6-terra",
                    "reasoning_effort": "high",
                    "context_hash": "0" * 64,
                    "outcome": "clean",
                    "receipt": receipt_to_write,
                }
            ]

        return plan

    for index, (invalid_receipt, message) in enumerate(invalid_clean_receipts):
        session = f"invalid-clean-{index}"
        with pytest.raises(ValueError, match=message):
            state.record_attempt(
                run.run_id,
                "review",
                session,
                "gpt-5.6-terra",
                "high",
                {"head": HEAD},
                "clean",
                invalid_receipt,
                holder=claimed.claimed_by,
                lease_id=claimed.lease_id,
            )
        with pytest.raises(ValueError, match=message):
            state.record_attempt_batch(
                run.run_id,
                f"invalid-clean-batch-{index}",
                1,
                HEAD,
                invalid_clean_batch(invalid_receipt, f"{session}-batch"),
                holder=claimed.claimed_by,
                lease_id=claimed.lease_id,
            )
    assert len(state.attempts(run.run_id)) == 1
    review_receipt = {
        "reviewed_attempt_id": repair_attempt["attempt_id"],
        "head_sha": HEAD,
        "verdict": "blocking",
        "finding_id": FINDING,
        "failure_domain": DOMAIN,
        "mechanism_id": MECHANISM,
        "mechanism_path_sha256": [MECHANISM_PATH_SHA],
    }
    assert state.record_attempt(
        run.run_id,
        "review",
        "review-round",
        "gpt-5.6-terra",
        "high",
        {"head": HEAD},
        "blocking",
        review_receipt,
        holder=claimed.claimed_by,
        lease_id=claimed.lease_id,
    ) == 1
    same_round_second_finding = {
        **review_receipt,
        "finding_id": "progress-admission-second-finding",
    }
    assert state.record_attempt(
        run.run_id,
        "review",
        "review-round",
        "gpt-5.6-terra",
        "high",
        {"head": HEAD},
        "blocking",
        same_round_second_finding,
        holder=claimed.claimed_by,
        lease_id=claimed.lease_id,
    ) == 2
    substituted_receipt = {
        **review_receipt,
        "mechanism_path_sha256": [OTHER_MECHANISM_PATH_SHA],
    }
    clean_receipt = {
        **review_receipt,
        "verdict": "clean",
        "mechanism_path_sha256": None,
    }

    with pytest.raises(ValueError, match="independent re-review requires a fresh session"):
        state.record_attempt(
            run.run_id,
            "review",
            "review-round",
            "gpt-5.6-terra",
            "high",
            {"head": HEAD},
            "blocking",
            substituted_receipt,
            holder=claimed.claimed_by,
            lease_id=claimed.lease_id,
        )
    with pytest.raises(ValueError, match="blocking review requires repair"):
        state.record_attempt(
            run.run_id,
            "review",
            "review-fresh-clean",
            "gpt-5.6-terra",
            "high",
            {"head": HEAD},
            "clean",
            clean_receipt,
            holder=claimed.claimed_by,
            lease_id=claimed.lease_id,
        )
    with pytest.raises(ValueError, match="blocking review requires repair"):
        state.record_attempt(
            run.run_id,
            "review",
            "review-fresh-session",
            "gpt-5.6-terra",
            "high",
            {"head": HEAD},
            "blocking",
            substituted_receipt,
            holder=claimed.claimed_by,
            lease_id=claimed.lease_id,
        )
    with pytest.raises(ValueError, match="canonical mechanism path projection"):
        state.record_attempt(
            run.run_id,
            "review",
            "review-missing-paths",
            "gpt-5.6-terra",
            "high",
            {"head": HEAD},
            "blocking",
            {**review_receipt, "mechanism_path_sha256": None},
            holder=claimed.claimed_by,
            lease_id=claimed.lease_id,
        )

    def substituted_batch(attempts, attempt_id_for):
        return [
            {
                "attempt_id": attempt_id_for(0),
                "kind": "review",
                "ordinal": 3,
                "session_id": "review-round",
                "capability": "gpt-5.6-terra",
                "reasoning_effort": "high",
                "context_hash": "1" * 64,
                "outcome": "blocking",
                "receipt": substituted_receipt,
            }
        ]

    with pytest.raises(ValueError, match="independent re-review requires a fresh session"):
        state.record_attempt_batch(
            run.run_id,
            "substituted-review-paths",
            1,
            HEAD,
            substituted_batch,
            holder=claimed.claimed_by,
            lease_id=claimed.lease_id,
        )

    def fresh_clean_batch(attempts, attempt_id_for):
        return [
            {
                "attempt_id": attempt_id_for(0),
                "kind": "review",
                "ordinal": 3,
                "session_id": "review-fresh-clean-batch",
                "capability": "gpt-5.6-terra",
                "reasoning_effort": "high",
                "context_hash": "2" * 64,
                "outcome": "clean",
                "receipt": clean_receipt,
            }
        ]

    with pytest.raises(ValueError, match="blocking review requires repair"):
        state.record_attempt_batch(
            run.run_id,
            "fresh-clean-review-laundering",
            1,
            HEAD,
            fresh_clean_batch,
            holder=claimed.claimed_by,
            lease_id=claimed.lease_id,
        )

    def fresh_session_substituted_batch(attempts, attempt_id_for):
        return [
            {
                "attempt_id": attempt_id_for(0),
                "kind": "review",
                "ordinal": 3,
                "session_id": "review-fresh-batch",
                "capability": "gpt-5.6-terra",
                "reasoning_effort": "high",
                "context_hash": "2" * 64,
                "outcome": "blocking",
                "receipt": substituted_receipt,
            }
        ]

    with pytest.raises(ValueError, match="blocking review requires repair"):
        state.record_attempt_batch(
            run.run_id,
            "fresh-session-substituted-review-paths",
            1,
            HEAD,
            fresh_session_substituted_batch,
            holder=claimed.claimed_by,
            lease_id=claimed.lease_id,
        )
    attempts = state.attempts(run.run_id)
    assert len(attempts) == 3
    assert all(
        row["receipt"]["mechanism_path_sha256"] == [MECHANISM_PATH_SHA]
        for row in attempts
        if row["kind"] == "review"
    )


@pytest.mark.parametrize("backend", ("sqlite", "builderops"))
def test_direct_attempt_cannot_predeclare_future_atomic_batch_replay(
    tmp_path,
    backend: str,
) -> None:
    state = (
        BuilderOpsVerificationLedger(
            FakeBuilderOpsClient(),
            repository=REPO,
        )
        if backend == "builderops"
        else ledger(tmp_path)
    )
    run = state.ingest(request())
    claimed = state.claim(run.run_id, "verification-host")
    assert claimed.claimed_by is not None
    assert claimed.lease_id is not None
    loop = VerificationAgentLoop(
        state,
        run.run_id,
        holder=claimed.claimed_by,
        lease_id=claimed.lease_id,
    )
    context = {"head": HEAD}
    loop.repair(
        finding_id=FINDING,
        failure_domain=DOMAIN,
        mechanism_id=MECHANISM,
        session_id="repair-1",
        capability="gpt-5.6-terra",
        reasoning_effort="high",
        context=context,
        outcome="fixed",
        transition_evidence=_transition(SEED_HEAD, HEAD),
    )
    repair_attempt = state.attempts(run.run_id)[0]
    event = {
        "kind": "review",
        "session_id": "blocking-review",
        "capability": "gpt-5.6-terra",
        "reasoning_effort": "high",
        "outcome": "blocking",
        "finding_id": FINDING,
        "failure_domain": DOMAIN,
        "mechanism_id": MECHANISM,
        "mechanism_path_sha256": [MECHANISM_PATH_SHA],
    }
    context_hash = hashlib.sha256(
        json.dumps(
            context,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    ).hexdigest()
    batch_id = hashlib.sha256(
        json.dumps(
            {
                "context_hash": context_hash,
                "events": [event],
                "head_sha": HEAD,
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    ).hexdigest()
    injected_clean = {
        "reviewed_attempt_id": repair_attempt["attempt_id"],
        "head_sha": HEAD,
        "verdict": "clean",
        "finding_id": None,
        "failure_domain": None,
        "mechanism_id": None,
        "mechanism_path_sha256": None,
        "event_batch_id": batch_id,
        "event_batch_index": 0,
        "event_batch_size": 1,
    }

    with pytest.raises(ValueError, match="batch metadata is producer-reserved"):
        state.record_attempt(
            run.run_id,
            "review",
            "injected-clean",
            "gpt-5.6-terra",
            "high",
            context,
            "clean",
            injected_clean,
            holder=claimed.claimed_by,
            lease_id=claimed.lease_id,
        )

    loop.apply_events([event], context=context)
    attempts = state.attempts(run.run_id)
    assert [row["kind"] for row in attempts] == ["standard_repair", "review"]
    assert attempts[-1]["outcome"] == "blocking"
    assert attempts[-1]["receipt"]["event_batch_id"] == batch_id
    assert loop.closure_ready() is False


@pytest.mark.parametrize("backend", ("sqlite", "builderops"))
@pytest.mark.parametrize("invalid_batch_id", (True, 1))
def test_atomic_batch_identity_rejects_bool_and_integer_aliases(
    tmp_path,
    backend: str,
    invalid_batch_id: object,
) -> None:
    state = (
        BuilderOpsVerificationLedger(
            FakeBuilderOpsClient(),
            repository=REPO,
        )
        if backend == "builderops"
        else ledger(tmp_path)
    )
    run = state.ingest(request())
    claimed = state.claim(run.run_id, "verification-host")
    assert claimed.claimed_by is not None
    assert claimed.lease_id is not None

    with pytest.raises(ValueError, match="batch identity is required"):
        state.record_attempt_batch(
            run.run_id,
            invalid_batch_id,
            1,
            HEAD,
            lambda attempts, attempt_id_for: [],
            holder=claimed.claimed_by,
            lease_id=claimed.lease_id,
        )


def test_atomic_batch_replay_rejects_boolean_size_alias() -> None:
    with pytest.raises(ValueError, match="batch is partially persisted"):
        _is_exact_event_batch_replay(
            [
                {
                    "attempt_id": "vattempt-expected",
                    "receipt": {
                        "event_batch_id": "batch-1",
                        "event_batch_index": 0,
                        "event_batch_size": True,
                    },
                }
            ],
            batch_id="batch-1",
            batch_size=1,
            attempt_id_for=lambda index: "vattempt-expected",
        )


@pytest.mark.parametrize("backend", ("sqlite", "builderops"))
def test_atomic_batch_rejects_forged_planner_attempt_id_before_write(
    tmp_path,
    backend: str,
) -> None:
    state = (
        BuilderOpsVerificationLedger(
            FakeBuilderOpsClient(),
            repository=REPO,
        )
        if backend == "builderops"
        else ledger(tmp_path)
    )
    run = state.ingest(request())
    claimed = state.claim(run.run_id, "verification-host")
    assert claimed.claimed_by is not None
    assert claimed.lease_id is not None
    admitted_receipt = admit_verification_receipt(
        state,
        run.run_id,
        "verification-session",
        _verified_receipt(),
        holder=claimed.claimed_by,
        lease_id=claimed.lease_id,
    )

    def plan(attempt_id: str):
        def build(attempts, attempt_id_for):
            return [
                {
                    "attempt_id": attempt_id,
                    "kind": "verification",
                    "ordinal": 1,
                    "session_id": "verification-session",
                    "capability": "gpt-5.6-terra",
                    "reasoning_effort": "high",
                    "context_hash": "0" * 64,
                    "outcome": "launched",
                    "receipt": admitted_receipt,
                }
            ]

        return build

    with pytest.raises(ValueError, match="batch attempt id is malformed"):
        state.record_attempt_batch(
            run.run_id,
            "batch-forged-id",
            1,
            HEAD,
            plan("vattempt-forged"),
            holder=claimed.claimed_by,
            lease_id=claimed.lease_id,
        )
    assert state.attempts(run.run_id) == []

    def exact_plan(attempts, attempt_id_for):
        return plan(attempt_id_for(0))(attempts, attempt_id_for)

    assert state.record_attempt_batch(
        run.run_id,
        "batch-exact-id",
        1,
        HEAD,
        exact_plan,
        holder=claimed.claimed_by,
        lease_id=claimed.lease_id,
    ) == 1
    assert state.record_attempt_batch(
        run.run_id,
        "batch-exact-id",
        1,
        HEAD,
        exact_plan,
        holder=claimed.claimed_by,
        lease_id=claimed.lease_id,
    ) == 0
    assert len(state.attempts(run.run_id)) == 1


@pytest.mark.parametrize("backend", ("sqlite", "builderops"))
def test_synthetic_verification_cannot_mint_clean_closure_authority(
    tmp_path,
    backend: str,
) -> None:
    state = (
        BuilderOpsVerificationLedger(
            FakeBuilderOpsClient(),
            repository=REPO,
        )
        if backend == "builderops"
        else ledger(tmp_path)
    )
    run = state.ingest(request())
    claimed = state.claim(run.run_id, "verification-host")
    assert claimed.claimed_by is not None
    assert claimed.lease_id is not None
    forged_receipt = _verified_receipt()

    with pytest.raises(ValueError, match="validated closer receipt"):
        state.record_attempt(
            run.run_id,
            "verification",
            "synthetic-verification",
            "gpt-5.6-terra",
            "high",
            {"head": HEAD},
            "launched",
            forged_receipt,
            holder=claimed.claimed_by,
            lease_id=claimed.lease_id,
        )

    def forged_batch(attempts, attempt_id_for):
        return [
            {
                "attempt_id": attempt_id_for(0),
                "kind": "verification",
                "ordinal": 1,
                "session_id": "synthetic-verification-batch",
                "capability": "gpt-5.6-terra",
                "reasoning_effort": "high",
                "context_hash": "0" * 64,
                "outcome": "launched",
                "receipt": forged_receipt,
            }
        ]

    with pytest.raises(ValueError, match="validated closer receipt"):
        state.record_attempt_batch(
            run.run_id,
            "synthetic-verification-batch",
            1,
            HEAD,
            forged_batch,
            holder=claimed.claimed_by,
            lease_id=claimed.lease_id,
        )
    assert state.attempts(run.run_id) == []
    assert state.closure_ready(run.run_id) is False


@pytest.mark.parametrize("backend", ("sqlite", "builderops"))
@pytest.mark.parametrize("write_mode", ("direct", "batch"))
@pytest.mark.parametrize(
    "forge_mode", ("unsealed", "subclass", "mutated", "copied_seal")
)
def test_forged_validated_receipt_capability_cannot_mint_authority(
    tmp_path,
    backend: str,
    write_mode: str,
    forge_mode: str,
) -> None:
    state = (
        BuilderOpsVerificationLedger(
            FakeBuilderOpsClient(),
            repository=REPO,
        )
        if backend == "builderops"
        else ledger(tmp_path)
    )
    run = state.ingest(request())
    claimed = state.claim(run.run_id, "verification-host")
    assert claimed.claimed_by is not None
    assert claimed.lease_id is not None
    payload = dict(_verified_receipt())
    session_id = f"forged-{forge_mode}-{write_mode}"
    if forge_mode in {"mutated", "copied_seal"}:
        admitted = admit_verification_receipt(
            state,
            run.run_id,
            session_id,
            _verified_receipt(),
            holder=claimed.claimed_by,
            lease_id=claimed.lease_id,
        )
    if forge_mode == "mutated":
        forged_receipt = admitted
        forged_receipt["summary"] = "mutated after validation"
    else:
        receipt_type = _ValidatedVerificationAttemptReceipt
        if forge_mode == "subclass":
            class ForgedValidatedReceipt(_ValidatedVerificationAttemptReceipt):
                pass

            receipt_type = ForgedValidatedReceipt
        forged_receipt = dict.__new__(receipt_type)
        dict.__init__(forged_receipt, payload)
        if forge_mode == "copied_seal":
            object.__setattr__(
                forged_receipt,
                "_ValidatedVerificationAttemptReceipt__validation_seal",
                getattr(
                    admitted,
                    "_ValidatedVerificationAttemptReceipt__validation_seal",
                ),
            )

    if write_mode == "direct":
        with pytest.raises(ValueError, match="validated closer receipt"):
            state.record_attempt(
                run.run_id,
                "verification",
                session_id,
                "gpt-5.6-terra",
                "high",
                {"head": HEAD},
                "launched",
                forged_receipt,
                holder=claimed.claimed_by,
                lease_id=claimed.lease_id,
            )
    else:
        def forged_batch(attempts, attempt_id_for):
            return [
                {
                    "attempt_id": attempt_id_for(0),
                    "kind": "verification",
                    "ordinal": 1,
                    "session_id": session_id,
                    "capability": "gpt-5.6-terra",
                    "reasoning_effort": "high",
                    "context_hash": "0" * 64,
                    "outcome": "launched",
                    "receipt": forged_receipt,
                }
            ]

        with pytest.raises(ValueError, match="validated closer receipt"):
            state.record_attempt_batch(
                run.run_id,
                f"forged-{forge_mode}-batch",
                1,
                HEAD,
                forged_batch,
                holder=claimed.claimed_by,
                lease_id=claimed.lease_id,
            )
    assert state.attempts(run.run_id) == []
    assert state.closure_ready(run.run_id) is False


@pytest.mark.parametrize("backend", ("sqlite", "builderops"))
@pytest.mark.parametrize("write_mode", ("direct", "batch"))
@pytest.mark.parametrize("binding_case", ("session", "head", "restart"))
def test_admitted_receipt_is_bound_to_exact_run_frontier(
    tmp_path,
    backend: str,
    write_mode: str,
    binding_case: str,
) -> None:
    api = FakeBuilderOpsClient()
    state = (
        BuilderOpsVerificationLedger(api, repository=REPO)
        if backend == "builderops"
        else ledger(tmp_path)
    )
    run = state.ingest(request())
    claimed = state.claim(run.run_id, "verification-host")
    assert claimed.claimed_by is not None
    assert claimed.lease_id is not None
    admitted_session = "admitted-verification"
    admitted = admit_verification_receipt(
        state,
        run.run_id,
        admitted_session,
        _verified_receipt(),
        holder=claimed.claimed_by,
        lease_id=claimed.lease_id,
    )
    record_session = admitted_session
    expected_head = HEAD
    if binding_case == "session":
        record_session = "different-verification-session"
    elif binding_case == "head":
        state.rebind_head(
            run.run_id,
            SECOND_HEAD,
            expected_head_sha=HEAD,
            observed_repository=REPO,
            observed_pr_number=3603,
            observed_head_sha=SECOND_HEAD,
            holder=claimed.claimed_by,
            lease_id=claimed.lease_id,
        )
        expected_head = SECOND_HEAD
    else:
        state = (
            BuilderOpsVerificationLedger(api, repository=REPO)
            if backend == "builderops"
            else VerificationDispatchLedger(state.store)
        )

    if write_mode == "direct":
        with pytest.raises(ValueError, match="validated closer receipt"):
            state.record_attempt(
                run.run_id,
                "verification",
                record_session,
                "gpt-5.6-terra",
                "high",
                {"head": expected_head},
                "launched",
                admitted,
                holder=claimed.claimed_by,
                lease_id=claimed.lease_id,
            )
    else:
        def batch(attempts, attempt_id_for):
            return [
                {
                    "attempt_id": attempt_id_for(0),
                    "kind": "verification",
                    "ordinal": 1,
                    "session_id": record_session,
                    "capability": "gpt-5.6-terra",
                    "reasoning_effort": "high",
                    "context_hash": "0" * 64,
                    "outcome": "launched",
                    "receipt": admitted,
                }
            ]

        with pytest.raises(ValueError, match="validated closer receipt"):
            state.record_attempt_batch(
                run.run_id,
                f"wrong-{binding_case}-batch",
                1,
                expected_head,
                batch,
                holder=claimed.claimed_by,
                lease_id=claimed.lease_id,
            )
    assert state.attempts(run.run_id) == []


@pytest.mark.parametrize("backend", ("sqlite", "builderops"))
@pytest.mark.parametrize("write_mode", ("direct", "batch"))
def test_admitted_receipt_cannot_cross_run_or_pr_boundary(
    tmp_path,
    backend: str,
    write_mode: str,
) -> None:
    state = (
        BuilderOpsVerificationLedger(FakeBuilderOpsClient(), repository=REPO)
        if backend == "builderops"
        else ledger(tmp_path)
    )
    source = state.ingest(request())
    source_claim = state.claim(source.run_id, "verification-host")
    assert source_claim.claimed_by is not None
    assert source_claim.lease_id is not None
    session_id = "source-verification-session"
    admitted = admit_verification_receipt(
        state,
        source.run_id,
        session_id,
        _verified_receipt(),
        holder=source_claim.claimed_by,
        lease_id=source_claim.lease_id,
    )

    target = state.ingest(_identity_request(REPO, 3604))
    if backend == "sqlite":
        # The local adapter deliberately permits only one live verification
        # subscription. Retire A's lease while retaining its unconsumed
        # admission, then prove that object still cannot cross into B.
        state.terminal(
            source.run_id,
            "superseded",
            {"reason": "cross-run admission probe"},
            reason="test_probe",
            holder=source_claim.claimed_by,
            lease_id=source_claim.lease_id,
        )
    target_claim = state.claim(target.run_id, "verification-host")
    assert target_claim.pr_number == 3604
    assert target_claim.run_id != source.run_id
    assert target_claim.claimed_by is not None
    assert target_claim.lease_id is not None

    if write_mode == "direct":
        with pytest.raises(ValueError, match="validated closer receipt"):
            state.record_attempt(
                target.run_id,
                "verification",
                session_id,
                "gpt-5.6-terra",
                "high",
                {"head": HEAD},
                "launched",
                admitted,
                holder=target_claim.claimed_by,
                lease_id=target_claim.lease_id,
            )
    else:
        def batch(attempts, attempt_id_for):
            return [
                {
                    "attempt_id": attempt_id_for(0),
                    "kind": "verification",
                    "ordinal": 1,
                    "session_id": session_id,
                    "capability": "gpt-5.6-terra",
                    "reasoning_effort": "high",
                    "context_hash": "0" * 64,
                    "outcome": "launched",
                    "receipt": admitted,
                }
            ]

        with pytest.raises(ValueError, match="validated closer receipt"):
            state.record_attempt_batch(
                target.run_id,
                "cross-run-pr-batch",
                1,
                HEAD,
                batch,
                holder=target_claim.claimed_by,
                lease_id=target_claim.lease_id,
            )
    assert state.attempts(source.run_id) == []
    assert state.attempts(target.run_id) == []


@pytest.mark.parametrize("backend", ("sqlite", "builderops"))
@pytest.mark.parametrize("identity_field", ("run_id", "repository", "pr_number"))
def test_receipt_admission_registry_rejects_each_identity_dimension(
    tmp_path,
    backend: str,
    identity_field: str,
) -> None:
    state = (
        BuilderOpsVerificationLedger(FakeBuilderOpsClient(), repository=REPO)
        if backend == "builderops"
        else ledger(tmp_path)
    )
    run = state.ingest(request())
    claimed = state.claim(run.run_id, "verification-host")
    assert claimed.claimed_by is not None
    assert claimed.lease_id is not None
    session_id = "identity-bound-verification"
    receipt = _verified_receipt()
    admitted = admit_verification_receipt(
        state,
        run.run_id,
        session_id,
        receipt,
        holder=claimed.claimed_by,
        lease_id=claimed.lease_id,
    )
    binding = _verification_receipt_admission_binding(
        run_id=run.run_id,
        repository=run.repository,
        pr_number=run.pr_number,
        head_sha=run.current_head_sha,
        session_id=session_id,
        holder=claimed.claimed_by,
        lease_id=claimed.lease_id,
        receipt=admitted,
    )
    mismatched_values: dict[str, object] = {
        "run_id": "vrun-different",
        "repository": "other/repository",
        "pr_number": 3604,
    }
    mismatched = replace(
        binding,
        **{identity_field: mismatched_values[identity_field]},
    )
    assert not state._verification_receipt_admissions.authorizes(
        admitted,
        binding=mismatched,
    )
    assert state.attempts(run.run_id) == []


def test_builderops_ledger_rejects_cross_repository_run_identity() -> None:
    state = BuilderOpsVerificationLedger(FakeBuilderOpsClient(), repository=REPO)
    with pytest.raises(ValueError, match="RepoRef"):
        state.ingest(_identity_request("other/repository", 3604))


@pytest.mark.parametrize("backend", ("sqlite", "builderops"))
@pytest.mark.parametrize("authority_case", ("holder", "lease"))
def test_receipt_admission_requires_exact_live_lease_authority(
    tmp_path,
    backend: str,
    authority_case: str,
) -> None:
    state = (
        BuilderOpsVerificationLedger(FakeBuilderOpsClient(), repository=REPO)
        if backend == "builderops"
        else ledger(tmp_path)
    )
    run = state.ingest(request())
    claimed = state.claim(run.run_id, "verification-host")
    assert claimed.claimed_by is not None
    assert claimed.lease_id is not None
    holder = (
        "different-verification-host"
        if authority_case == "holder"
        else claimed.claimed_by
    )
    lease_id = "vlease-different" if authority_case == "lease" else claimed.lease_id
    with pytest.raises(ValueError):
        admit_verification_receipt(
            state,
            run.run_id,
            "verification-session",
            _verified_receipt(),
            holder=holder,
            lease_id=lease_id,
        )
    assert state.attempts(run.run_id) == []


@pytest.mark.parametrize("backend", ("sqlite", "builderops"))
@pytest.mark.parametrize("write_mode", ("direct", "batch"))
@pytest.mark.parametrize("verdict", ("blocked", "needs_human", "retry"))
def test_failed_verification_verdict_cannot_become_closure_anchor(
    tmp_path,
    backend: str,
    write_mode: str,
    verdict: str,
) -> None:
    state = (
        BuilderOpsVerificationLedger(
            FakeBuilderOpsClient(),
            repository=REPO,
        )
        if backend == "builderops"
        else ledger(tmp_path)
    )
    run = state.ingest(request())
    claimed = state.claim(run.run_id, "verification-host")
    assert claimed.claimed_by is not None
    assert claimed.lease_id is not None
    successful_session = "successful-verification"
    successful_receipt = admit_verification_receipt(
        state,
        run.run_id,
        successful_session,
        _verified_receipt(),
        holder=claimed.claimed_by,
        lease_id=claimed.lease_id,
    )
    state.record_attempt(
        run.run_id,
        "verification",
        successful_session,
        "gpt-5.6-sol",
        "xhigh",
        {"head": HEAD},
        "launched",
        successful_receipt,
        holder=claimed.claimed_by,
        lease_id=claimed.lease_id,
    )
    successful_anchor = state.attempts(run.run_id)[0]
    state.record_attempt(
        run.run_id,
        "review",
        "successful-clean-review",
        "gpt-5.6-sol",
        "xhigh",
        {"head": HEAD},
        "clean",
        {
            "reviewed_attempt_id": successful_anchor["attempt_id"],
            "head_sha": HEAD,
            "verdict": "clean",
            "finding_id": None,
            "failure_domain": None,
            "mechanism_id": None,
            "mechanism_path_sha256": None,
        },
        holder=claimed.claimed_by,
        lease_id=claimed.lease_id,
    )
    assert state.closure_ready(run.run_id) is True
    failed_session = (
        f"{verdict}-verification"
        if write_mode == "direct"
        else f"{verdict}-verification-batch"
    )
    failed_receipt = admit_verification_receipt(
        state,
        run.run_id,
        failed_session,
        _verified_receipt(verdict=verdict),
        holder=claimed.claimed_by,
        lease_id=claimed.lease_id,
    )

    if write_mode == "direct":
        state.record_attempt(
            run.run_id,
            "verification",
            failed_session,
            "gpt-5.6-terra",
            "high",
            {"head": HEAD},
            "launched",
            failed_receipt,
            holder=claimed.claimed_by,
            lease_id=claimed.lease_id,
        )
    else:
        def failed_batch(attempts, attempt_id_for):
            return [
                {
                    "attempt_id": attempt_id_for(0),
                    "kind": "verification",
                    "ordinal": 2,
                    "session_id": failed_session,
                    "capability": "gpt-5.6-terra",
                    "reasoning_effort": "high",
                    "context_hash": "0" * 64,
                    "outcome": "launched",
                    "receipt": failed_receipt,
                }
            ]

        state.record_attempt_batch(
            run.run_id,
            f"{verdict}-verification-batch",
            1,
            HEAD,
            failed_batch,
            holder=claimed.claimed_by,
            lease_id=claimed.lease_id,
        )

    anchor = state.attempts(run.run_id)[-1]
    assert anchor.get("verification_receipt_sha256") is None
    assert state.closure_ready(run.run_id) is False
    if backend == "builderops":
        with pytest.raises(
            ValueError,
            match="fresh verified review gate",
        ):
            state.mark_merge_ready(
                run.run_id,
                {"verdict": "verified", "head_sha": HEAD},
                holder=claimed.claimed_by,
                lease_id=claimed.lease_id,
            )
    with pytest.raises(ValueError, match="anchor lacks producer authority"):
        state.record_attempt(
            run.run_id,
            "review",
            f"{verdict}-clean-review",
            "gpt-5.6-sol",
            "xhigh",
            {"head": HEAD},
            "clean",
            {
                "reviewed_attempt_id": anchor["attempt_id"],
                "head_sha": HEAD,
                "verdict": "clean",
                "finding_id": None,
                "failure_domain": None,
                "mechanism_id": None,
                "mechanism_path_sha256": None,
            },
            holder=claimed.claimed_by,
            lease_id=claimed.lease_id,
        )


@pytest.mark.parametrize(
    ("validation_after", "transition_path", "blob_sha", "message"),
    (
        ("1" * 64, MECHANISM_PATH, None, "progress evidence is unchanged"),
        (
            "2" * 64,
            "docs/unrelated.md",
            None,
            "does not change the reviewed mechanism",
        ),
        ("2" * 64, MECHANISM_PATH, HEAD, "progress evidence is unchanged"),
    ),
)
def test_repeated_repair_rejects_non_progressing_server_evidence(
    tmp_path,
    validation_after: str,
    transition_path: str,
    blob_sha: str | None,
    message: str,
) -> None:
    state = ledger(tmp_path)
    run = state.ingest(request())
    claimed = state.claim(run.run_id, "verification-host")
    assert claimed.claimed_by is not None
    assert claimed.lease_id is not None
    loop = VerificationAgentLoop(
        state,
        run.run_id,
        holder=claimed.claimed_by,
        lease_id=claimed.lease_id,
    )
    binding = {
        "finding_id": FINDING,
        "failure_domain": DOMAIN,
        "mechanism_id": MECHANISM,
    }
    loop.repair(
        **binding,
        session_id="repair-1",
        capability="gpt-5.6-terra",
        reasoning_effort="high",
        context={"head": HEAD},
        outcome="fixed",
        transition_evidence=_transition(
            SEED_HEAD,
            HEAD,
            extra_paths=("docs/unrelated.md",),
        ),
    )
    loop.review(
        **binding,
        session_id="review-1",
        capability="gpt-5.6-terra",
        reasoning_effort="high",
        context={"head": HEAD},
        outcome="blocking",
        mechanism_path_sha256=[MECHANISM_PATH_SHA],
    )
    intent = plan_repair_progress_intents(
        state.attempts(run.run_id),
        current_head_sha=HEAD,
        validation_sha256="1" * 64,
    )[0]
    intent_id = str(intent["intent_id"])
    state.record_attempt(
        run.run_id,
        REPAIR_INTENT_ATTEMPT_KIND,
        intent_id,
        "deterministic",
        "none",
        {"head": HEAD},
        "admitted",
        intent,
        holder=claimed.claimed_by,
        lease_id=claimed.lease_id,
        idempotency_key=intent_id,
    )
    state.rebind_head(
        run.run_id,
        SECOND_HEAD,
        expected_head_sha=HEAD,
        observed_repository=REPO,
        observed_pr_number=3603,
        observed_head_sha=SECOND_HEAD,
        holder=claimed.claimed_by,
        lease_id=claimed.lease_id,
    )
    with pytest.raises(ValueError, match=message):
        loop.apply_events(
            [_repair_event(intent_id)],
            context={
                "head": SECOND_HEAD,
                "progress_validation_sha256": validation_after,
                "repair_transition_evidence": _transition(
                    HEAD,
                    SECOND_HEAD,
                    path=transition_path,
                    blob_sha=blob_sha,
                ),
            },
        )

    assert [
        row["kind"]
        for row in state.attempts(run.run_id)
        if row["kind"] in {"standard_repair", "escalated_repair"}
    ] == ["standard_repair"]
